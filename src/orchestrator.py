from datetime import datetime, date, timezone
import os
from zoneinfo import ZoneInfo

from src.database import get_raw_posts_collection, get_final_table_collection


def sync_raw_to_final():
    print("🔄 Syncing Raw Posts to Final Table...")

    timezone_name = os.getenv("TIMEZONE", "UTC")
    try:
        today_str = datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    except Exception:
        today_str = date.today().isoformat()

    col_raw_posts = get_raw_posts_collection()
    col_final_table = get_final_table_collection()

    raw_posts = col_raw_posts.find()
    new_count = 0

    for post in raw_posts:
        raw_id = post.get("_id")
        if raw_id is None:
            continue

        if post.get("scraped_at") != today_str:
            continue

        exists = col_final_table.find_one({"ref_raw_post": raw_id})
        if exists:
            continue

        master_entry = {
            "ref_raw_post": raw_id,
            "ref_summary": None,
            "ref_contact_info": None,
            "pipeline_status": [0, 0, 0, 0, 0, 0],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        col_final_table.insert_one(master_entry)
        new_count += 1
        print(f"   ➕ Registered Post: {raw_id}")

    print(f"✅ Sync Complete. {new_count} new leads added to Final Table.")


if __name__ == "__main__":
    sync_raw_to_final()
