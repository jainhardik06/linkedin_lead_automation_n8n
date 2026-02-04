import os
import re
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo

from src.database import (
    get_final_table_collection,
    get_post_emails_collection,
    get_raw_posts_collection,
)

EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def extract_emails_from_text(text: str):
    if not text:
        return []
    emails = EMAIL_REGEX.findall(text)
    unique = sorted(set(email.lower() for email in emails))
    return unique


def run_email_extractor():
    print("📧 Starting Post Email Extraction...")

    timezone_name = os.getenv("TIMEZONE", "UTC")
    try:
        today_str = datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    except Exception:
        today_str = date.today().isoformat()

    col_raw_posts = get_raw_posts_collection()
    col_post_emails = get_post_emails_collection()
    col_final_table = get_final_table_collection()

    pending_tasks = col_final_table.find({"pipeline_status.1": 0, "ref_post_email": None})
    tasks = list(pending_tasks)
    print(f"Found {len(tasks)} posts to scan for emails.")

    for task in tasks:
        master_id = task.get("_id")
        raw_id = task.get("ref_raw_post")

        raw_post = col_raw_posts.find_one({"_id": raw_id})
        if not raw_post:
            print(f"⚠️ Raw post missing for {raw_id}")
            continue

        if raw_post.get("scraped_at") != today_str:
            continue

        content = raw_post.get("content") or raw_post.get("post_content") or ""
        found_emails = extract_emails_from_text(content)
        stored_emails = found_emails if found_emails else None

        if stored_emails:
            print(f"   🎯 Found email(s) for {master_id}: {stored_emails}")
        else:
            print(f"   ℹ️ No emails in post for {master_id}.")

        email_doc = {
            "linked_raw_post_id": raw_id,
            "emails": stored_emails,
            "extracted_at": datetime.now(timezone.utc),
        }

        result = col_post_emails.insert_one(email_doc)
        new_email_obj_id = result.inserted_id

        col_final_table.update_one(
            {"_id": master_id},
            {
                "$set": {
                    "ref_post_email": new_email_obj_id,
                    "pipeline_status.1": 1,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

    print("✨ Email Extraction Complete.")


if __name__ == "__main__":
    run_email_extractor()
