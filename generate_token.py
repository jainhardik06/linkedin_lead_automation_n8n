"""
Generate OAuth 2.0 Token (token.json)

This script performs a one-time manual login to create token.json.
After running this once, the script can use your Google Drive quota forever.

Usage:
    python generate_token.py

A browser window will open. Log in with your Google account and click "Allow".
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# Scopes required for Google Drive access
SCOPES = ['https://www.googleapis.com/auth/drive']


def main():
    """Generate token.json from credentials.json via manual login."""
    creds = None

    # 1. Check if token already exists
    if os.path.exists('token.json'):
        print("📄 token.json already exists. Loading...")
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    # 2. If no valid token, start login flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Token expired. Refreshing...")
            creds.refresh(Request())
        else:
            print("🔐 Starting OAuth login flow...")
            print("   A browser window will open. Log in with your Google account.")
            print("   After login, you'll see 'The authentication flow has completed.'")
            print()

            if not os.path.exists('credentials.json'):
                print("❌ ERROR: credentials.json not found!")
                print("   Step 1: Download OAuth credentials from Google Cloud Console")
                print("   Step 2: Place it in the project root as 'credentials.json'")
                return

            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                print(f"❌ Login failed: {e}")
                return

        # 3. Save token for future use
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            print()
            print("=" * 60)
            print("✅ SUCCESS! token.json created.")
            print("=" * 60)
            print()
            print("📝 What to do next:")
            print("   1. You can now delete credentials.json (for security)")
            print("   2. Run the deep scraper: python -m src.deep_scraper")
            print("   3. Your 15GB Google Drive quota is now available!")
            print()
            print("🚀 token.json will auto-refresh. No manual login needed again.")
            print()


if __name__ == '__main__':
    main()
