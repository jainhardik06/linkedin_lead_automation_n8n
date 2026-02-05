import os
from pymongo import MongoClient
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

_client = None

def get_db_client():
    global _client
    if _client is None:
        uri = os.getenv("MONGO_URI")
        _client = MongoClient(uri)
    return _client

def get_db():
    db_name = os.getenv("DB_NAME", os.getenv("DATABASE_NAME", "webasthetic_leads"))
    client = get_db_client()
    return client[db_name]

def get_collection(name: str):
    db = get_db()
    return db[name]

def get_raw_posts_collection():
    raw_name = os.getenv("RAW_POSTS_COLLECTION") or os.getenv("COLLECTION_NAME", "webastheticleads")
    return get_collection(raw_name)

def get_post_summaries_collection():
    return get_collection(os.getenv("POST_SUMMARIES_COLLECTION", "post_summaries"))

def get_post_emails_collection():
    return get_collection(os.getenv("POST_EMAILS_COLLECTION", "post_emails"))

def get_post_mobiles_collection():
    return get_collection(os.getenv("POST_MOBILES_COLLECTION", "post_mobiles"))

def get_user_scrapped_collection():
    return get_collection(os.getenv("USER_SCRAPPED_COLLECTION", "user_scrapped"))

def get_final_table_collection():
    return get_collection(os.getenv("FINAL_TABLE_COLLECTION", "final_table"))

def get_user_mobile_collection():
    return get_collection(os.getenv("USER_MOBILE_COLLECTION", "user_mobile"))

def get_user_mail_collection():
    return get_collection(os.getenv("USER_MAIL_COLLECTION", "user_mail"))

def get_user_links_collection():
    return get_collection(os.getenv("USER_LINKS_COLLECTION", "user_links"))

def get_user_summary_collection():
    return get_collection(os.getenv("USER_SUMMARY_COLLECTION", "user_summary"))

def get_master_leads_collection():
    return get_collection(os.getenv("MASTER_LEADS_COLLECTION", "master_leads"))

# Backward compatibility for existing code
def get_db_collection():
    return get_raw_posts_collection()

if __name__ == "__main__":
    # Test connection
    col = get_db_collection()
    print(f"Connected to Atlas: {col.full_name}")