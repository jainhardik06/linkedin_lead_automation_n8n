import os
import re
import io
import time
import logging
import requests
from datetime import datetime, timezone
import pdfplumber
from groq import Groq
from src.database import (
    get_final_table_collection,
    get_user_scrapped_collection,
    get_user_mobile_collection,
    get_user_mail_collection,
    get_user_links_collection,
    get_user_summary_collection,
)
from src.drive_upload import download_file_content
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def extract_text_from_pdf_bytes(pdf_bytes):
    """Converts PDF binary data to String."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join([page.extract_text() or "" for page in pdf.pages])
        return text
    except Exception as e:
        logger.warning(f"⚠️ PDF Read Error: {e}")
        return ""


def regex_extractor(text):
    """Extracts Entities from Text Block."""
    data = {"emails": [], "mobiles": [], "links": []}
    if not text:
        return data

    # Email Regex
    data["emails"] = list(
        set(re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", text))
    )

    # Mobile Regex
    mobiles = re.findall(
        r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text
    )
    data["mobiles"] = list(
        set([m for m in mobiles if len(re.sub(r"\D", "", m)) >= 10])
    )

    # Link Regex
    links = re.findall(r"(https?://[^\s]+)", text)
    clean_links = [
        l for l in links if "linkedin.com" not in l and "google.com" not in l
    ]
    data["links"] = list(set(clean_links))

    return data


def generate_ai_profile_summary(text, profile_type):
    """Uses Groq to summarize the profile with rate limiting."""
    # Truncate to fit within token limits (llama-3.3-70b can handle more)
    # Approximate: 1 token ≈ 4 chars, limit to ~8000 chars for safety
    max_chars = 8000
    truncated_text = text[:max_chars] if len(text) > max_chars else text
    
    prompt = f"""
    Summarize this {profile_type} profile for a B2B cold email.
    Focus on: Skills, Decision Making Power, and Recent Projects.
    Keep it under 3 sentences.
    
    TEXT: {truncated_text}
    """
    try:
        # Using llama-3.3-70b-versatile: 30 RPM, 1K RPD, 12K TPM, 100K TPD
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.05,
        )
        return completion.choices[0].message.content
    except Exception as e:
        logger.error(f"❌ AI Error: {e}")
        return "Summary generation failed."


def run_profile_processor(callback_url: str = None):
    print("🧠 Starting Profile Intelligence Processor...")
    
    if callback_url:
        logger.info(f"📍 Callback URL registered: {callback_url}")

    col_final_table = get_final_table_collection()
    col_user_scrapped = get_user_scrapped_collection()
    col_user_mobile = get_user_mobile_collection()
    col_user_mail = get_user_mail_collection()
    col_user_links = get_user_links_collection()
    col_user_summary = get_user_summary_collection()

    # Get today's date range (UTC)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=999999)

    print(f"   Looking for profiles scraped between {today_start} and {today_end}")

    # Find user_scrapped documents from today
    today_scraped = list(
        col_user_scrapped.find(
            {
                "scraped_at": {"$gte": today_start, "$lte": today_end}
            }
        )
    )

    print(f"   Found {len(today_scraped)} profiles scraped today")

    # Filter to only those with pipeline_status.4 = 0 (processor pending)
    pending_profiles = []
    for user_data in today_scraped:
        scraped_id = user_data.get("_id")
        if not scraped_id:
            continue

        final_entry = col_final_table.find_one({"ref_user_scrapped": scraped_id})
        if not final_entry:
            continue

        pipeline_status = final_entry.get("pipeline_status", [0, 0, 0, 0, 0, 0])

        if len(pipeline_status) > 4 and pipeline_status[4] == 0:
            pending_profiles.append((user_data, final_entry))

    print(f"   Found {len(pending_profiles)} profiles pending processing (pipeline_status.4 = 0)")

    if not pending_profiles:
        print("   No profiles to process.")
        return

    # Rate limiting setup
    # llama-3.3-70b-versatile: 30 RPM, 1K RPD
    # Safe rate: 1 request every 3 seconds = 20 RPM (leaving buffer)
    rate_limit_delay = 3.0
    request_count = 0
    start_time = time.time()
    
    processed_count = 0

    for user_data, final_entry in pending_profiles:
        master_id = final_entry["_id"]
        raw_id = final_entry.get("ref_raw_post")

        p_type = user_data.get("profile_type", "user")
        profile_name = user_data.get("name", "Unknown")
        final_text = ""

        # --- 1. GET CONTENT ---
        if p_type == "company":
            final_text = user_data.get("c_about_text", "")
            print(f"   🏢 Processing Company: {profile_name}")
        else:
            # User Profile -> Try PDF
            pdf_link = user_data.get("contact_pdf_link")
            if pdf_link:
                print(f"   👤 Processing User: {profile_name}")
                pdf_bytes = download_file_content(pdf_link)
                if pdf_bytes:
                    final_text = extract_text_from_pdf_bytes(pdf_bytes)
                else:
                    logger.warning("   ⚠️ Could not download PDF.")
            else:
                logger.warning("   ⚠️ No PDF Link found.")

        if not final_text:
            final_text = "No content available."

        # --- 2. EXTRACT DATA ---
        extracted = regex_extractor(final_text)
        logger.info(
            f"   📊 Extracted: {len(extracted['emails'])} emails, {len(extracted['mobiles'])} mobiles, {len(extracted['links'])} links"
        )

        # --- 3. AI SUMMARY ---
        ai_summary = generate_ai_profile_summary(final_text, p_type)
        logger.info(f"   🤖 AI Summary: {ai_summary[:60]}...")
        
        # Rate limiting: Enforce delay between requests
        request_count += 1
        elapsed = time.time() - start_time
        expected_time = request_count * rate_limit_delay
        
        if elapsed < expected_time:
            sleep_time = expected_time - elapsed
            logger.info(f"   ⏳ Rate limiting: waiting {sleep_time:.1f}s...")
            time.sleep(sleep_time)

        # --- 4. SAVE TO DB (The 4 Tables) ---
        ts = datetime.now(timezone.utc)

        # A. Mobile
        res_mobile = col_user_mobile.insert_one(
            {"linked_raw_post_id": raw_id, "mobiles": extracted["mobiles"], "extracted_at": ts}
        )

        # B. Mail
        res_mail = col_user_mail.insert_one(
            {"linked_raw_post_id": raw_id, "emails": extracted["emails"], "extracted_at": ts}
        )

        # C. Links
        res_links = col_user_links.insert_one(
            {"linked_raw_post_id": raw_id, "links": extracted["links"], "extracted_at": ts}
        )

        # D. Summary
        res_summary = col_user_summary.insert_one(
            {"linked_raw_post_id": raw_id, "summary": ai_summary, "generated_at": ts}
        )

        # --- 5. UPDATE FINAL TABLE ---
        col_final_table.update_one(
            {"_id": master_id},
            {
                "$set": {
                    "ref_user_mobile": res_mobile.inserted_id,
                    "ref_user_mail": res_mail.inserted_id,
                    "ref_user_links": res_links.inserted_id,
                    "ref_user_summary": res_summary.inserted_id,
                    "pipeline_status.4": 1,
                    "updated_at": ts,
                }
            },
        )
        logger.info(f"   ✅ Processed & Linked to final_table")
        processed_count += 1

    print(f"\n🎉 Profile Processor Complete: {processed_count}/{len(pending_profiles)} profiles analyzed.")
    
    # Send callback to n8n
    if callback_url:
        logger.info(f"📞 Calling back n8n at: {callback_url}")
        try:
            response = requests.post(
                callback_url,
                json={"status": "success", "message": "Profile Processor Done", "processed": processed_count, "total": len(pending_profiles)},
                timeout=15
            )
            logger.info(f"✅ Callback sent successfully. Status: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Callback failed: {e}")


if __name__ == "__main__":
    run_profile_processor()
