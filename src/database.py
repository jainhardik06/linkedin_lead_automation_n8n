import os
from pymongo import MongoClient
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

def get_db_collection():
    uri = os.getenv("MONGO_URI")
    db_name = os.getenv("DATABASE_NAME", "webasthetic_leads")
    col_name = os.getenv("COLLECTION_NAME", "webastheticleads")
    
    client = MongoClient(uri)
    db = client[db_name]
    return db[col_name]

if __name__ == "__main__":
    # Test connection
    col = get_db_collection()
    print(f"Connected to Atlas: {col.full_name}")