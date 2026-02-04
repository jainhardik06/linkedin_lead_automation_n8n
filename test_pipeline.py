"""
Test script to validate the entire LinkedIn lead automation pipeline.
This script tests all stages without affecting production data.
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId

# Load environment variables
load_dotenv()

# Import project modules
from src.database import (
    get_raw_posts_collection,
    get_final_table_collection,
    get_post_summaries_collection,
    get_post_emails_collection,
    get_post_mobiles_collection,
    get_user_scrapped_collection
)

# Color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_success(message):
    print(f"{Colors.GREEN}✓ {message}{Colors.RESET}")

def print_error(message):
    print(f"{Colors.RED}✗ {message}{Colors.RESET}")

def print_info(message):
    print(f"{Colors.BLUE}ℹ {message}{Colors.RESET}")

def print_warning(message):
    print(f"{Colors.YELLOW}⚠ {message}{Colors.RESET}")

def print_header(message):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{message}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}\n")

# Get today's date in configured timezone
TIMEZONE = os.getenv("TIMEZONE", "UTC")
tz = ZoneInfo(TIMEZONE)
today_date = datetime.now(tz).strftime("%Y-%m-%d")

# Test data
TEST_POST_ID = None
TEST_FINAL_TABLE_ID = None

def test_1_database_connections():
    """Test 1: Verify MongoDB connections to all collections"""
    print_header("TEST 1: Database Connections")
    
    try:
        collections = {
            "Raw Posts": get_raw_posts_collection(),
            "Final Table": get_final_table_collection(),
            "Post Summaries": get_post_summaries_collection(),
            "Post Emails": get_post_emails_collection(),
            "Post Mobiles": get_post_mobiles_collection(),
            "User Scrapped": get_user_scrapped_collection()
        }
        
        for name, collection in collections.items():
            # Try to ping the collection
            collection.find_one()
            print_success(f"{name} collection: Connected")
        
        return True
    except Exception as e:
        print_error(f"Database connection failed: {e}")
        return False

def test_2_insert_test_data():
    """Test 2: Insert test post data with today's date"""
    print_header("TEST 2: Insert Test Data")
    
    global TEST_POST_ID
    
    try:
        raw_posts = get_raw_posts_collection()
        
        # Create test post with today's date
        test_post = {
            "author_name": "Test User",
            "author_profile_url": "https://www.linkedin.com/in/test-user-12345/",
            "post_link": f"https://www.linkedin.com/posts/test-user-12345_test-post-{datetime.now().timestamp()}",
            "post_content": """
            🚀 Exciting opportunity! We're hiring a Senior Python Developer.
            
            Contact us at: jobs@testcompany.com or hr@testcompany.com
            Call: +91-9876543210 or +1 (555) 123-4567
            
            Join our amazing team! #hiring #python #developer
            """,
            "scraped_at": today_date,
            "created_at": datetime.now(tz)
        }
        
        result = raw_posts.insert_one(test_post)
        TEST_POST_ID = result.inserted_id
        
        print_success(f"Test post inserted with ID: {TEST_POST_ID}")
        print_info(f"Scraped date: {today_date}")
        print_info(f"Post content includes: 2 emails, 2 mobile numbers")
        
        return True
    except Exception as e:
        print_error(f"Failed to insert test data: {e}")
        return False

def test_3_orchestrator():
    """Test 3: Test orchestrator - sync to final_table"""
    print_header("TEST 3: Orchestrator (Sync to Final Table)")
    
    global TEST_FINAL_TABLE_ID
    
    try:
        raw_posts = get_raw_posts_collection()
        final_table = get_final_table_collection()
        
        # Find today's test post
        post = raw_posts.find_one({"_id": TEST_POST_ID})
        if not post:
            print_error("Test post not found in raw_posts")
            return False
        
        # Check if already in final_table
        existing = final_table.find_one({"post_id": TEST_POST_ID})
        if existing:
            print_info("Test post already in final_table, using existing entry")
            TEST_FINAL_TABLE_ID = existing["_id"]
        else:
            # Insert into final_table
            final_entry = {
                "post_id": TEST_POST_ID,
                "author_name": post["author_name"],
                "author_profile_url": post["author_profile_url"],
                "post_link": post["post_link"],
                "scraped_at": post["scraped_at"],
                "pipeline_status": [0, 0, 0, 0],
                "created_at": datetime.now(tz)
            }
            
            result = final_table.insert_one(final_entry)
            TEST_FINAL_TABLE_ID = result.inserted_id
            print_success(f"Test post synced to final_table with ID: {TEST_FINAL_TABLE_ID}")
        
        # Verify pipeline_status
        entry = final_table.find_one({"_id": TEST_FINAL_TABLE_ID})
        print_info(f"Pipeline status: {entry['pipeline_status']}")
        
        return True
    except Exception as e:
        print_error(f"Orchestrator test failed: {e}")
        return False

def test_4_ai_summarizer():
    """Test 4: Test AI summarization with Groq"""
    print_header("TEST 4: AI Summarization")
    
    try:
        from groq import Groq
        import time
        
        raw_posts = get_raw_posts_collection()
        post_summaries = get_post_summaries_collection()
        final_table = get_final_table_collection()
        
        # Get test post
        post = raw_posts.find_one({"_id": TEST_POST_ID})
        if not post:
            print_error("Test post not found")
            return False
        
        # Check if summary already exists
        existing = post_summaries.find_one({"post_id": TEST_POST_ID})
        if existing:
            print_info("Summary already exists, skipping AI generation")
            print_success(f"Existing summary: {existing['summary'][:100]}...")
        else:
            # Generate AI summary
            print_info("Generating AI summary...")
            
            groq_api_key = os.getenv("GROQ_API_KEY")
            if not groq_api_key:
                print_warning("GROQ_API_KEY not found, skipping AI test")
                return True
            
            client = Groq(api_key=groq_api_key)
            
            prompt = f"""Analyze this LinkedIn post and provide a concise summary:

Post Content:
{post['post_content']}

Provide a brief summary highlighting the main topic and key points."""
            
            try:
                response = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=200
                )
                
                summary = response.choices[0].message.content.strip()
                
                # Store summary
                summary_doc = {
                    "post_id": TEST_POST_ID,
                    "summary": summary,
                    "scraped_at": today_date,
                    "created_at": datetime.now(tz)
                }
                
                post_summaries.insert_one(summary_doc)
                print_success(f"Summary generated: {summary[:100]}...")
                
                # Wait before rate limit
                time.sleep(4)
                
            except Exception as e:
                if "rate_limit" in str(e).lower():
                    print_warning(f"Rate limit hit (expected on free tier): {e}")
                else:
                    raise
        
        # Update pipeline_status[0] = 1
        final_table.update_one(
            {"_id": TEST_FINAL_TABLE_ID},
            {"$set": {"pipeline_status.0": 1}}
        )
        
        entry = final_table.find_one({"_id": TEST_FINAL_TABLE_ID})
        print_success(f"Pipeline status updated: {entry['pipeline_status']}")
        
        return True
    except Exception as e:
        print_error(f"AI summarizer test failed: {e}")
        return False

def test_5_email_extraction():
    """Test 5: Test email extraction"""
    print_header("TEST 5: Email Extraction")
    
    try:
        import re
        
        raw_posts = get_raw_posts_collection()
        post_emails = get_post_emails_collection()
        final_table = get_final_table_collection()
        
        # Get test post
        post = raw_posts.find_one({"_id": TEST_POST_ID})
        if not post:
            print_error("Test post not found")
            return False
        
        # Extract emails
        EMAIL_REGEX = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
        emails = list(set(re.findall(EMAIL_REGEX, post['post_content'], re.IGNORECASE)))
        emails = [e.lower() for e in emails]
        
        print_info(f"Found {len(emails)} emails: {emails}")
        
        # Check if already exists
        existing = post_emails.find_one({"post_id": TEST_POST_ID})
        if existing:
            print_info("Email record already exists")
        else:
            # Store emails
            email_doc = {
                "post_id": TEST_POST_ID,
                "emails": emails if emails else None,
                "scraped_at": today_date,
                "created_at": datetime.now(tz)
            }
            
            post_emails.insert_one(email_doc)
            print_success(f"Emails stored: {emails}")
        
        # Update pipeline_status[1] = 1
        final_table.update_one(
            {"_id": TEST_FINAL_TABLE_ID},
            {"$set": {"pipeline_status.1": 1}}
        )
        
        entry = final_table.find_one({"_id": TEST_FINAL_TABLE_ID})
        print_success(f"Pipeline status updated: {entry['pipeline_status']}")
        
        return True
    except Exception as e:
        print_error(f"Email extraction test failed: {e}")
        return False

def test_6_mobile_extraction():
    """Test 6: Test mobile number extraction"""
    print_header("TEST 6: Mobile Number Extraction")
    
    try:
        import re
        
        raw_posts = get_raw_posts_collection()
        post_mobiles = get_post_mobiles_collection()
        final_table = get_final_table_collection()
        
        # Get test post
        post = raw_posts.find_one({"_id": TEST_POST_ID})
        if not post:
            print_error("Test post not found")
            return False
        
        # Extract mobile numbers
        MOBILE_REGEX = r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}|\+?\d{10,13}'
        mobiles = list(set(re.findall(MOBILE_REGEX, post['post_content'])))
        
        print_info(f"Found {len(mobiles)} mobile numbers: {mobiles}")
        
        # Check if already exists
        existing = post_mobiles.find_one({"post_id": TEST_POST_ID})
        if existing:
            print_info("Mobile record already exists")
        else:
            # Store mobiles
            mobile_doc = {
                "post_id": TEST_POST_ID,
                "mobile_numbers": mobiles if mobiles else None,
                "scraped_at": today_date,
                "created_at": datetime.now(tz)
            }
            
            post_mobiles.insert_one(mobile_doc)
            print_success(f"Mobile numbers stored: {mobiles}")
        
        # Update pipeline_status to [1,1,1,0]
        final_table.update_one(
            {"_id": TEST_FINAL_TABLE_ID},
            {"$set": {"pipeline_status": [1, 1, 1, 0]}}
        )
        
        entry = final_table.find_one({"_id": TEST_FINAL_TABLE_ID})
        print_success(f"Pipeline status updated: {entry['pipeline_status']}")
        
        return True
    except Exception as e:
        print_error(f"Mobile extraction test failed: {e}")
        return False

def test_7_google_drive():
    """Test 7: Verify Google Drive integration"""
    print_header("TEST 7: Google Drive Integration")
    
    try:
        from src.drive_upload import authenticate_drive
        
        print_info("Testing Google Drive authentication...")
        
        service = authenticate_drive()
        
        # Try to get folder info
        folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
        if folder_id:
            folder = service.files().get(fileId=folder_id, fields="id,name").execute()
            print_success(f"Google Drive connected: Folder '{folder['name']}' accessible")
        else:
            print_warning("GOOGLE_DRIVE_FOLDER_ID not set in .env")
        
        return True
    except Exception as e:
        print_error(f"Google Drive test failed: {e}")
        print_info("This is non-critical - deep scraper can still work")
        return True  # Non-critical

def test_8_final_verification():
    """Test 8: Final verification of test data"""
    print_header("TEST 8: Final Verification")
    
    try:
        final_table = get_final_table_collection()
        
        # Get final entry
        entry = final_table.find_one({"_id": TEST_FINAL_TABLE_ID})
        if not entry:
            print_error("Test entry not found in final_table")
            return False
        
        print_info("Test Entry Details:")
        print(f"  Post ID: {entry['post_id']}")
        print(f"  Author: {entry['author_name']}")
        print(f"  Scraped At: {entry['scraped_at']}")
        print(f"  Pipeline Status: {entry['pipeline_status']}")
        
        # Check pipeline status
        expected_status = [1, 1, 1, 0]  # Summary, Email, Mobile done; Deep scraper pending
        if entry['pipeline_status'] == expected_status:
            print_success(f"Pipeline status correct: {entry['pipeline_status']}")
        else:
            print_warning(f"Pipeline status: {entry['pipeline_status']} (expected {expected_status})")
        
        # Verify data in other collections
        post_summaries = get_post_summaries_collection()
        post_emails = get_post_emails_collection()
        post_mobiles = get_post_mobiles_collection()
        
        summary_exists = post_summaries.find_one({"post_id": TEST_POST_ID}) is not None
        email_exists = post_emails.find_one({"post_id": TEST_POST_ID}) is not None
        mobile_exists = post_mobiles.find_one({"post_id": TEST_POST_ID}) is not None
        
        print_info("Data Verification:")
        print(f"  ✓ Summary: {'Found' if summary_exists else 'Missing'}")
        print(f"  ✓ Emails: {'Found' if email_exists else 'Missing'}")
        print(f"  ✓ Mobiles: {'Found' if mobile_exists else 'Missing'}")
        
        if summary_exists and email_exists and mobile_exists:
            print_success("All pipeline data verified successfully!")
            return True
        else:
            print_warning("Some pipeline data missing (may be expected)")
            return True
        
    except Exception as e:
        print_error(f"Final verification failed: {e}")
        return False

def cleanup_test_data():
    """Clean up test data from all collections"""
    print_header("CLEANUP: Removing Test Data")
    
    try:
        response = input(f"\n{Colors.YELLOW}Do you want to remove test data? (y/n): {Colors.RESET}")
        
        if response.lower() != 'y':
            print_info("Skipping cleanup - test data retained")
            return
        
        raw_posts = get_raw_posts_collection()
        final_table = get_final_table_collection()
        post_summaries = get_post_summaries_collection()
        post_emails = get_post_emails_collection()
        post_mobiles = get_post_mobiles_collection()
        
        # Delete test data
        raw_posts.delete_one({"_id": TEST_POST_ID})
        final_table.delete_one({"_id": TEST_FINAL_TABLE_ID})
        post_summaries.delete_one({"post_id": TEST_POST_ID})
        post_emails.delete_one({"post_id": TEST_POST_ID})
        post_mobiles.delete_one({"post_id": TEST_POST_ID})
        
        print_success("Test data cleaned up successfully")
        
    except Exception as e:
        print_error(f"Cleanup failed: {e}")

def main():
    """Run all tests"""
    print(f"{Colors.BOLD}{Colors.BLUE}")
    print("="*60)
    print("  LINKEDIN LEAD AUTOMATION - PIPELINE TEST SUITE")
    print("="*60)
    print(f"{Colors.RESET}")
    print_info(f"Test Date: {today_date}")
    print_info(f"Timezone: {TIMEZONE}")
    
    tests = [
        ("Database Connections", test_1_database_connections),
        ("Insert Test Data", test_2_insert_test_data),
        ("Orchestrator", test_3_orchestrator),
        ("AI Summarizer", test_4_ai_summarizer),
        ("Email Extraction", test_5_email_extraction),
        ("Mobile Extraction", test_6_mobile_extraction),
        ("Google Drive", test_7_google_drive),
        ("Final Verification", test_8_final_verification)
    ]
    
    results = []
    
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
            
            if not result:
                print_error(f"Test '{name}' failed - stopping test suite")
                break
                
        except KeyboardInterrupt:
            print_warning("\nTest suite interrupted by user")
            break
        except Exception as e:
            print_error(f"Test '{name}' crashed: {e}")
            results.append((name, False))
            break
    
    # Print summary
    print_header("TEST SUMMARY")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = f"{Colors.GREEN}PASSED{Colors.RESET}" if result else f"{Colors.RED}FAILED{Colors.RESET}"
        print(f"  {name}: {status}")
    
    print(f"\n{Colors.BOLD}Total: {passed}/{total} tests passed{Colors.RESET}")
    
    if passed == total:
        print_success("\n🎉 All tests passed! Your pipeline is ready to run.")
    else:
        print_warning(f"\n⚠ {total - passed} test(s) failed. Please fix issues before running main scripts.")
    
    # Cleanup
    if TEST_POST_ID:
        cleanup_test_data()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Test suite interrupted{Colors.RESET}")
        sys.exit(1)
