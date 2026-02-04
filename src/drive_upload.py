import os
import io
import logging
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError

# Suppress Google warnings
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)

TOKEN_FILE = 'token.json'
PARENT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
SCOPES = ['https://www.googleapis.com/auth/drive']

logger = logging.getLogger(__name__)


def authenticate_drive():
    """
    Authenticate using User OAuth Token (NOT Service Account).
    This uses YOUR Google Drive quota (15GB/2TB), NOT a bot's 0GB quota.
    """
    creds = None

    # 1. Load the Token
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    else:
        logger.error(
            "❌ token.json not found! Run this command first:\n"
            "   python generate_token.py\n"
            "Then follow the login prompts in your browser."
        )
        return None

    # 2. Refresh if expired (token auto-refreshes, never ask to log in again)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Save the refreshed token back to file
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
            logger.info("🔄 OAuth token refreshed automatically")
        except Exception as e:
            logger.error(f"❌ Token refresh failed: {e}")
            return None

    # 3. Build and return service
    try:
        service = build('drive', 'v3', credentials=creds)
        logger.info("✅ Authenticated as user (YOUR Drive quota)")
        return service
    except Exception as e:
        logger.error(f"❌ Failed to build Drive service: {e}")
        return None


def upload_pdf_to_drive(local_file_path: str, file_name: str):
    """
    Upload PDF to Google Drive using USER quota.
    
    Replaces service account (0GB) with personal account (15GB/2TB).
    Returns: Google Drive webViewLink or None on failure.
    """
    if not PARENT_FOLDER_ID:
        logger.warning(
            "⚠️ GOOGLE_DRIVE_FOLDER_ID not set in .env. "
            "Skipping upload. PDFs will remain in temp_downloads/."
        )
        return None

    service = authenticate_drive()
    if not service:
        logger.error("❌ Authentication failed. Check token.json exists and is valid.")
        return None

    try:
        file_metadata = {
            "name": file_name,
            "parents": [PARENT_FOLDER_ID]
        }

        media = MediaFileUpload(local_file_path, mimetype="application/pdf")

        logger.info(f"☁️ Uploading {file_name} to Google Drive (YOUR quota)...")

        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink"
        ).execute()

        file_id = file.get("id")
        link = file.get("webViewLink")

        logger.info(f"✅ Upload Complete. File ID: {file_id}")

        # Cleanup local file
        if os.path.exists(local_file_path):
            try:
                os.remove(local_file_path)
                logger.info("🧹 Local temp file deleted.")
            except Exception as e:
                logger.warning(f"Could not delete local file: {e}")

        return link

    except HttpError as http_err:
        error_message = str(http_err)
        logger.error(f"❌ Google Drive API Error: {error_message[:200]}")
        
        # Cleanup on error
        if os.path.exists(local_file_path):
            try:
                os.remove(local_file_path)
            except:
                pass
        return None

    except Exception as exc:
        logger.error(f"❌ Upload Failed: {type(exc).__name__}: {str(exc)[:200]}")
        
        # Cleanup on error
        if os.path.exists(local_file_path):
            try:
                os.remove(local_file_path)
            except:
                pass
        return None


def download_file_content(file_link):
    """
    Downloads file content from Drive Link into memory (RAM).
    Returns bytes.
    """
    service = authenticate_drive()
    if not service or not file_link:
        return None
    
    try:
        # Extract File ID from Link
        # Link format: https://drive.google.com/file/d/FILE_ID/view...
        file_id = file_link.split('/d/')[1].split('/')[0]
        
        request = service.files().get_media(fileId=file_id)
        file_stream = io.BytesIO()
        downloader = MediaIoBaseDownload(file_stream, request)
        
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            
        logger.info(f"✅ Downloaded file content from Drive (File ID: {file_id})")
        return file_stream.getvalue()
        
    except Exception as e:
        logger.error(f"❌ Failed to download file content: {e}")
        return None
