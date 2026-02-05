import logging
import requests
import json
import time
import os
from datetime import datetime, timezone
from src.database import (
    get_final_table_collection,
    get_master_leads_collection,
    get_post_emails_collection,
    get_user_mail_collection,
    get_user_scrapped_collection,
    get_post_summaries_collection,
    get_user_summary_collection,
    get_raw_posts_collection,
)

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Fixed Footer for all emails
FIXED_FOOTER = """with regards,
WebAsthetic Solutions
webasthetic.in
https://cal.com/webastheticsolutions"""

# Rate Limiting Config
# Groq free tier is fast, but keep a safe RPM
GROQ_RPM = 30  # adjust if your plan allows higher
MIN_REQUEST_INTERVAL = 60 / GROQ_RPM  # 2 seconds between requests
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2  # Exponential backoff multiplier

# Groq model fallback order (must be available in your account)
GROQ_MODELS = [
        "llama-3.3-70b-versatile",        # Fallback 1: better quality
        "llama-3.1-8b-instant",           # Primary: fast & cheap
        "qwen/qwen3-32b",                 # Fallback 2: alternative
        "moonshotai/kimi-k2-instruct",    # Fallback 3: last resort   
]


class RateLimiter:
    """Simple token bucket rate limiter for API requests."""
    
    def __init__(self, requests_per_minute: int):
        self.rpm = requests_per_minute
        self.min_interval = 60 / requests_per_minute
        self.last_request_time = 0
    
    def wait_if_needed(self):
        """Wait if necessary to maintain rate limit."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.min_interval:
            sleep_time = self.min_interval - time_since_last
            logger.debug(f"⏱️ Rate limit: Sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()


def setup_indexes():
    """Ensure email is unique in the master table."""
    col_master_leads = get_master_leads_collection()
    try:
        index_info = col_master_leads.index_information()
        if "email_1" in index_info:
            col_master_leads.drop_index("email_1")

        col_master_leads.create_index(
            [("email", 1), ("lead_date", 1)],
            unique=True,
            sparse=True
        )
        logger.info("✅ Master leads index created (email + lead_date unique)")
    except Exception as e:
        logger.warning(f"⚠️ Index creation warning: {e}")


def get_today_str():
    """Returns today's date string in the configured timezone."""
    timezone_name = os.getenv("TIMEZONE", "UTC")
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()


def get_context_data(task_doc):
    """
    Fetches Name, Post Summary, and Profile Summary using IDs from final_table.
    
    Returns:
        dict: Contains name, post_summary, profile_summary, raw_post_id, lead_date
    """
    col_user_scrapped = get_user_scrapped_collection()
    col_raw_posts = get_raw_posts_collection()
    col_summaries = get_post_summaries_collection()
    col_user_summary = get_user_summary_collection()
    
    context = {
        "name": "Unknown",
        "post_summary": "Not available",
        "profile_summary": "Not available",
        "raw_post_id": task_doc.get("ref_raw_post"),
        "lead_date": get_today_str()
    }

    # 1. Fetch Name (Prioritize User Profile > Raw Post Author)
    if task_doc.get("ref_user_scrapped"):
        try:
            user_doc = col_user_scrapped.find_one({"_id": task_doc["ref_user_scrapped"]})
            if user_doc and user_doc.get("name"):
                context["name"] = user_doc["name"]
        except Exception as e:
            logger.warning(f"⚠️ Error fetching user name: {e}")
    
    if task_doc.get("ref_raw_post"):
        try:
            raw_doc = col_raw_posts.find_one({"_id": task_doc["ref_raw_post"]})
            if raw_doc and raw_doc.get("scraped_at"):
                context["lead_date"] = raw_doc["scraped_at"]
            if context["name"] == "Unknown" and raw_doc and raw_doc.get("author_name"):
                context["name"] = raw_doc["author_name"]
        except Exception as e:
            logger.warning(f"⚠️ Error fetching raw post author: {e}")

    # 2. Fetch Post Summary (using ref_summary field, fallback to linked_raw_post_id)
    if task_doc.get("ref_summary"):
        try:
            p_sum_doc = col_summaries.find_one({"_id": task_doc["ref_summary"]})
            if p_sum_doc:
                context["post_summary"] = p_sum_doc.get("summary_text", p_sum_doc.get("summary", "Not available"))
        except Exception as e:
            logger.warning(f"⚠️ Error fetching post summary by ID: {e}")
    
    # Fallback: If no ref_summary, try to find by linked_raw_post_id
    if context["post_summary"] == "Not available" and task_doc.get("ref_raw_post"):
        try:
            p_sum_doc = col_summaries.find_one({"linked_raw_post_id": task_doc["ref_raw_post"]})
            if p_sum_doc:
                context["post_summary"] = p_sum_doc.get("summary_text", p_sum_doc.get("summary", "Not available"))
        except Exception as e:
            logger.warning(f"⚠️ Error fetching post summary by linked_raw_post_id: {e}")

    # 3. Fetch Profile Summary (using ref_user_summary field)
    if task_doc.get("ref_user_summary"):
        try:
            u_sum_doc = col_user_summary.find_one({"_id": task_doc["ref_user_summary"]})
            if u_sum_doc:
                context["profile_summary"] = u_sum_doc.get("summary", "Not available")
        except Exception as e:
            logger.warning(f"⚠️ Error fetching profile summary: {e}")

    return context


def generate_email_content(lead_data, attempt=1):
    """
    Uses Groq (Llama 3.x) to generate personalized cold email.
    Retries on rate/quota errors with exponential backoff.
    Returns dict: {"subject": "...", "body": "..."} or None if failed.
    """
    if not GROQ_AVAILABLE:
        logger.warning("⚠️ groq not installed. Skipping email generation.")
        return None
    
    try:
        api_key = os.getenv("GROQ_COPYWRITER_API_KEY")
        if not api_key:
            logger.warning("⚠️ GROQ_COPYWRITER_API_KEY not found in .env file")
            return None

        client = Groq(api_key=api_key)

        name = lead_data.get("name", "there")
        post_sum = lead_data.get("post_summary", "Generic web development needs")
        profile_sum = lead_data.get("profile_summary", "Technology professional")

        system_prompt = (
            "You are the Founder of WebAsthetic Solutions, a web engineering agency that specializes in building "
            "high-converting, fast-loading digital experiences. Your core philosophy: most websites fail because they prioritize looks over results. "
            "You focus on user experience, business outcomes, and measurable growth. Output ONLY valid JSON with subject and body keys."
        )

        user_prompt = f"""
Write a personalized cold email to {name}.

**LEAD CONTEXT:**
- Name: {name}
- What they're doing/recent activity: {post_sum}
- Role/background: {profile_sum}

**KEY POINTS TO WEAVE IN (naturally, not as a list):**
1. Reference their specific activity/role to show research.
2. Identify a business challenge they likely face (conversion, user experience, slow sites, authority).
3. Explain how WebAsthetic solves it: faster sites = more conversions, better user experience = trust, strategic design = measurable ROI.
4. Avoid technical jargon. Don't mention React, Next.js, or tech stacks.
5. Mention portfolio: https://www.webasthetic.in/portfolio
6. End with a low-friction ask: "Worth a 10-min chat?" or "Open to exploring this? and also mention that you can reachout from our website also"

**TONE & STYLE:**
- Sound like a real founder having a business conversation.
- Confident, direct, human. Short sentences.
- NO fluff: avoid "thrilled", "passionate", "cutting-edge", "synergy".
- Each email is unique, fully personalized—never use templates or structure.

**FORMATTING:**
- Subject: 3–7 words, casual and relevant to their world.
- Body: Start with "Hi {name}," on its own line, then blank line, then first paragraph.
- 3 paragraphs, each separated by a blank line.
- No bullet points, no footer/signature.

**OUTPUT:**
{{
    "subject": "...",
    "body": "Hi {name},\n\n[Paragraph 1]\n\n[Paragraph 2]\n\n[Paragraph 3]"
}}
"""

        last_error = None
        for model_name in GROQ_MODELS:
            try:
                completion = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"}
                )

                raw_content = completion.choices[0].message.content
                result = json.loads(raw_content)
                return result
            except Exception as inner_e:
                last_error = inner_e
                inner_msg = str(inner_e).lower()
                if "decommissioned" in inner_msg or "not found" in inner_msg:
                    continue
                raise

        if last_error:
            raise last_error
    except json.JSONDecodeError as e:
        logger.warning(f"⚠️ JSON Parse Error for {lead_data.get('email')}: {e}")
        return None
    except Exception as e:
        error_str = str(e).lower()

        if "429" in str(e) or "quota" in error_str or "exceeded" in error_str:
            if attempt < MAX_RETRIES:
                wait_time = (60 * (RETRY_BACKOFF_FACTOR ** (attempt - 1))) + 5
                logger.warning(f"⚠️ Quota exceeded. Retry {attempt}/{MAX_RETRIES} in {wait_time}s...")
                time.sleep(wait_time)
                return generate_email_content(lead_data, attempt + 1)
            else:
                logger.warning(f"❌ Max retries ({MAX_RETRIES}) reached for {lead_data.get('email')}. Quota exceeded.")
                return None
        else:
            logger.warning(f"⚠️ Groq API Error for {lead_data.get('email')}: {str(e)[:100]}")
            return None


def run_email_generation(col_master_leads):
    """
    Generates emails for leads that don't have them yet.
    Updates master_leads collection with generated_subject and generated_body.
    Respects configured RPM rate limit for Groq API.
    """
    print("\n✍️ Generating cold emails with Groq...")
    
    if not GROQ_AVAILABLE:
        logger.warning("⚠️ groq not installed. Install with: pip install groq")
        return 0
    
    today_str = get_today_str()

    # Find leads for today without generated emails
    pending_leads = list(
        col_master_leads.find({"lead_date": today_str, "generated_subject": {"$exists": False}})
    )
    print(f"   📧 Found {len(pending_leads)} leads needing email generation for {today_str}...")
    print(f"   ⏱️ Rate limit: {GROQ_RPM} RPM ({MIN_REQUEST_INTERVAL:.1f}s per request)")
    print(f"   🔄 Model: {GROQ_MODELS[0]} (fallbacks enabled)")
    
    if not pending_leads:
        print("   ✨ All leads already have generated emails!")
        return 0
    
    generated_count = 0
    col_final_table = get_final_table_collection()
    rate_limiter = RateLimiter(GROQ_RPM)
    
    for idx, lead in enumerate(pending_leads, 1):
        email = lead.get("email", "unknown")
        
        # Apply rate limiting BEFORE making the request
        rate_limiter.wait_if_needed()
        
        print(f"   [{idx}/{len(pending_leads)}] Generating for {email}...", end=" ")
        
        content = generate_email_content(lead)
        
        if content and "subject" in content and "body" in content:
            # Append fixed footer
            full_body = content["body"].strip() + "\n\n" + FIXED_FOOTER
            
            # Update master_leads
            col_master_leads.update_one(
                {"_id": lead["_id"]},
                {
                    "$set": {
                        "generated_subject": content["subject"],
                        "generated_body": full_body,
                        "email_generated_at": datetime.now(timezone.utc)
                    }
                }
            )

            # Update pipeline_status[5] in final_table
            if lead.get("ref_final_table_id"):
                col_final_table.update_one(
                    {"_id": lead["ref_final_table_id"]},
                    {"$set": {"pipeline_status.5": 1, "updated_at": datetime.now(timezone.utc)}}
                )

            print("✅")
            generated_count += 1
        else:
            if lead.get("ref_final_table_id"):
                col_final_table.update_one(
                    {"_id": lead["ref_final_table_id"], "pipeline_status.5": {"$ne": 1}},
                    {"$set": {"pipeline_status.5": 2, "updated_at": datetime.now(timezone.utc)}}
                )
            print("⚠️ (AI Generation Failed)")
    
    print(f"   ✍️ Email generation complete: {generated_count}/{len(pending_leads)} emails created")
    return generated_count


def upsert_lead(email, context, source_type, master_id):
    """
    Inserts or Updates a lead in the Master Leads table.
    
    Skips invalid emails.
    Uses upsert to handle duplicates - if email exists, updates with latest data.
    """
    if not email:
        return False
    
    # Validate email format
    email_clean = email.lower().strip()
    if "@" not in email_clean or len(email_clean) < 5:
        logger.warning(f"⚠️ Invalid email format: {email}")
        return False

    col_master_leads = get_master_leads_collection()
    
    lead_doc = {
        "email": email_clean,
        "lead_date": context.get("lead_date"),
        "name": context["name"],
        "post_summary": context["post_summary"],
        "profile_summary": context["profile_summary"],
        "source": source_type,
        "ref_final_table_id": master_id,
        "ref_raw_post_id": context["raw_post_id"],
        "updated_at": datetime.now(timezone.utc)
    }

    try:
        result = col_master_leads.update_one(
            {"email": email_clean, "lead_date": context.get("lead_date")},
            {
                "$set": lead_doc,
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)}
            },
            upsert=True
        )
        
        if result.upserted_id:
            logger.info(f"   ✅ NEW: {email_clean} ({source_type})")
        else:
            logger.debug(f"   🔄 UPDATED: {email_clean} ({source_type})")
        
        return True
    except Exception as e:
        logger.warning(f"   ⚠️ Error saving {email_clean}: {e}")
        return False


def run_lead_aggregator(callback_url: str = None):
    """
    Master Lead Aggregator.
    
    Iterates directly through all email sources:
    1. post_emails (emails in post description)
    2. user_mail (emails extracted from profile/about section)
    3. user_scrapped (raw contact emails)
    
    For each email, traces back to final_table entry to get context.
    Deduplicates by email and enriches with names and summaries.
    """
    print("💎 Starting Master Lead Aggregator...")
    
    col_final_table = get_final_table_collection()
    col_post_emails = get_post_emails_collection()
    col_user_mail = get_user_mail_collection()
    col_user_scrapped = get_user_scrapped_collection()
    col_raw_posts = get_raw_posts_collection()
    
    # Setup unique index on email
    setup_indexes()

    total_emails = 0
    new_count = 0
    duplicate_count = 0

    # --- SOURCE 1: POST EMAILS (Iterate directly through collection) ---
    print("\n📧 Scanning POST EMAILS table...")
    post_emails_docs = list(col_post_emails.find({}))
    print(f"   Found {len(post_emails_docs)} post_emails documents")
    
    for doc in post_emails_docs:
        if not doc.get("emails"):
            continue
        
        # Find the final_table entry via linked_raw_post_id
        linked_raw_post_id = doc.get("linked_raw_post_id")
        final_entry = None
        
        if linked_raw_post_id:
            final_entry = col_final_table.find_one({"ref_raw_post": linked_raw_post_id})
        
        if not final_entry:
            logger.debug(f"⚠️ Could not link post_emails doc {doc.get('_id')} to final_table")
            continue
        
        context = get_context_data(final_entry)
        master_id = final_entry["_id"]
        
        for email in doc["emails"]:
            if upsert_lead(email, context, "Post Description", master_id):
                total_emails += 1
                new_count += 1
            else:
                duplicate_count += 1

    # --- SOURCE 2: USER MAILS (Iterate directly through collection) ---
    print("\n📧 Scanning USER MAIL table...")
    user_mail_docs = list(col_user_mail.find({}))
    print(f"   Found {len(user_mail_docs)} user_mail documents")
    
    for doc in user_mail_docs:
        if not doc.get("emails"):
            continue
        
        # Find the final_table entry via linked_raw_post_id
        linked_raw_post_id = doc.get("linked_raw_post_id")
        final_entry = None
        
        if linked_raw_post_id:
            final_entry = col_final_table.find_one({"ref_raw_post": linked_raw_post_id})
        
        if not final_entry:
            logger.debug(f"⚠️ Could not link user_mail doc {doc.get('_id')} to final_table")
            continue
        
        context = get_context_data(final_entry)
        master_id = final_entry["_id"]
        
        for email in doc["emails"]:
            if upsert_lead(email, context, "Profile About Section", master_id):
                total_emails += 1
                new_count += 1
            else:
                duplicate_count += 1

    # --- SOURCE 3: USER SCRAPPED (Iterate directly through collection) ---
    print("\n📧 Scanning USER SCRAPPED table...")
    user_scrapped_docs = list(col_user_scrapped.find({}))
    print(f"   Found {len(user_scrapped_docs)} user_scrapped documents")
    
    for doc in user_scrapped_docs:
        if not doc.get("contact_email"):
            continue
        
        # Find the final_table entry via ref_user_scrapped
        final_entry = col_final_table.find_one({"ref_user_scrapped": doc["_id"]})
        
        if not final_entry:
            logger.debug(f"⚠️ Could not link user_scrapped doc {doc.get('_id')} to final_table")
            continue
        
        context = get_context_data(final_entry)
        master_id = final_entry["_id"]
        
        # Handle both list and string format
        c_emails = doc.get("contact_email", [])
        email_list = c_emails if isinstance(c_emails, list) else ([c_emails] if c_emails else [])
        
        for email in email_list:
            if upsert_lead(email, context, "LinkedIn Raw Contact", master_id):
                total_emails += 1
                new_count += 1
            else:
                duplicate_count += 1

    # Get final counts from master_leads
    col_master_leads = get_master_leads_collection()
    total_unique_leads = col_master_leads.count_documents({})
    
    print(f"\n💎 Aggregation Complete!")
    print(f"   📧 Total processed: {total_emails} emails")
    print(f"   ✨ New leads added: {new_count}")
    print(f"   🔄 Deduplicated: {duplicate_count} duplicates")
    print(f"   ✨ Unique leads in master_leads: {total_unique_leads}")

    # --- PHASE 2: EMAIL GENERATION WITH GEMINI ---
    emails_generated = run_email_generation(col_master_leads)

    # --- CALLBACK TO N8N ---
    if callback_url:
        logger.info(f"📞 Calling back n8n at: {callback_url}")
        try:
            response = requests.post(
                callback_url,
                json={
                    "status": "success",
                    "message": "Lead Aggregation & Email Generation Done",
                    "total_emails_processed": total_emails,
                    "new_leads": new_count,
                    "unique_leads": total_unique_leads,
                    "duplicates_handled": duplicate_count,
                    "emails_generated": emails_generated
                },
                timeout=15
            )
            logger.info(f"✅ Callback sent. Status: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Callback failed: {e}")


if __name__ == "__main__":
    run_lead_aggregator()
