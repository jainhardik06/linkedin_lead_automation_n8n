import os
import re
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo

from src.database import (
    get_final_table_collection,
    get_post_mobiles_collection,
    get_raw_posts_collection,
)

MOBILE_REGEX = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")


def extract_mobiles_from_text(text: str):
    if not text:
        return []
    matches = MOBILE_REGEX.findall(text)
    cleaned = [re.sub(r"\s+", " ", m).strip() for m in matches if m.strip()]
    unique = sorted(set(cleaned))
    return unique


def run_mobile_extractor():
    print("📱 Starting Post Mobile Extraction...")

    timezone_name = os.getenv("TIMEZONE", "UTC")
    try:
        today_str = datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    except Exception:
        today_str = date.today().isoformat()

    col_raw_posts = get_raw_posts_collection()
    col_post_mobiles = get_post_mobiles_collection()
    col_final_table = get_final_table_collection()

    pending_tasks = col_final_table.find({"pipeline_status.2": 0, "ref_post_mobile": None})
    tasks = list(pending_tasks)
    print(f"Found {len(tasks)} posts to scan for mobiles.")

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
        found_mobiles = extract_mobiles_from_text(content)
        stored_mobiles = found_mobiles if found_mobiles else None

        if stored_mobiles:
            print(f"   📞 Found mobile(s) for {master_id}: {stored_mobiles}")
        else:
            print(f"   ℹ️ No mobiles in post for {master_id}.")

        mobile_doc = {
            "linked_raw_post_id": raw_id,
            "mobiles": stored_mobiles,
            "extracted_at": datetime.now(timezone.utc),
        }

        result = col_post_mobiles.insert_one(mobile_doc)
        new_mobile_obj_id = result.inserted_id

        col_final_table.update_one(
            {"_id": master_id},
            {
                "$set": {
                    "ref_post_mobile": new_mobile_obj_id,
                    "pipeline_status.2": 1,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

    print("✨ Mobile Extraction Complete.")


if __name__ == "__main__":
    run_mobile_extractor()
