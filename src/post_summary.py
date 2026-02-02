import json
import os
import time
from datetime import datetime, date
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from groq import Groq, RateLimitError

from src.database import (
    get_final_table_collection,
    get_post_summaries_collection,
    get_raw_posts_collection,
)

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def generate_ai_summary(text: str):
    prompt = f"""
Analyze this LinkedIn post for a cold email campaign.
POST: "{text}"

OUTPUT JSON ONLY:
{{
    "intent": "Hiring" or "Not Hiring",
    "role": "Job Title or None",
    "summary": "1 sentence summary of what they need",
    "personalization": "One sentence icebreaker mentioning their specific project or tech stack"
}}
"""
    max_retries = 5
    base_delay = 5

    for attempt in range(max_retries):
        try:
            completion = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            return completion.choices[0].message.content
        except RateLimitError:
            wait_time = base_delay * (attempt + 1)
            print(f"⚠️ Rate limit hit. Cooling down for {wait_time}s...")
            time.sleep(wait_time)
        except Exception as exc:
            print(f"❌ AI Error: {exc}")
            return None

    print("❌ Failed after max retries.")
    return None


def run_summarizer():
    print("🤖 Starting Post Summarization...")

    timezone_name = os.getenv("TIMEZONE", "UTC")
    try:
        today_str = datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    except Exception:
        today_str = date.today().isoformat()

    col_raw_posts = get_raw_posts_collection()
    col_summaries = get_post_summaries_collection()
    col_final_table = get_final_table_collection()

    pending_tasks = col_final_table.find(
        {"pipeline_status.0": 0, "ref_summary": None}
    )

    tasks = list(pending_tasks)
    print(f"Found {len(tasks)} posts to summarize.")

    for task in tasks:
        master_id = task.get("_id")
        raw_id = task.get("ref_raw_post")

        raw_post = col_raw_posts.find_one({"_id": raw_id})
        if not raw_post:
            print(f"⚠️ Raw post missing for {raw_id}")
            continue

        scraped_at = raw_post.get("scraped_at")
        if scraped_at != today_str:
            continue

        post_text = raw_post.get("content") or raw_post.get("post_content")
        if not post_text:
            print(f"⚠️ Content missing for {raw_id}")
            continue

        print(f"   Processing {raw_id}...")

        ai_response_str = generate_ai_summary(post_text)
        if not ai_response_str:
            print(f"⚠️ Skipping {raw_id} due to AI error.")
            continue

        try:
            ai_response = json.loads(ai_response_str)
        except json.JSONDecodeError:
            ai_response = {"raw": ai_response_str}

        summary_doc = {
            "linked_raw_post_id": raw_id,
            "intent": ai_response.get("intent"),
            "role": ai_response.get("role"),
            "summary_text": ai_response.get("summary"),
            "personalization": ai_response.get("personalization"),
            "ai_raw": ai_response,
            "generated_at": datetime.utcnow(),
        }

        result = col_summaries.insert_one(summary_doc)
        new_summary_id = result.inserted_id

        col_final_table.update_one(
            {"_id": master_id},
            {
                "$set": {
                    "ref_summary": new_summary_id,
                    "pipeline_status.0": 1,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        print(f"   ✅ Linked Summary {new_summary_id} to Master {master_id}")
        time.sleep(4)


if __name__ == "__main__":
    run_summarizer()