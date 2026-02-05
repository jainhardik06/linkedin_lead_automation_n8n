import os
import smtplib
import imaplib
import time
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from src.database import get_master_leads_collection
from dotenv import load_dotenv
import logging

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.hostinger.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.hostinger.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

# Safety Limits
BATCH_SIZE = 5  # Only send 5 at a time per run (adjust gradually for warm-up)
DELAY_BETWEEN_EMAILS = 8  # Seconds (Hostinger rate limit protection)
CC_EMAIL = "webasthetic@gmail.com"  # CC for all outgoing emails
MAX_SMTP_RETRIES = 2  # Automatic retries for transient SMTP issues
RETRY_BACKOFF_SECONDS = 15  # Base backoff between retries

def send_email(to_email, subject, body_text):
    """
    Sends a Multipart Email (Plain Text + HTML) via Hostinger SMTP.
    Returns True on success, False on failure.
    """
    msg = MIMEMultipart('alternative')
    msg['From'] = f"WebAsthetic Solutions <{SMTP_EMAIL}>"
    msg['To'] = to_email
    msg['Cc'] = CC_EMAIL
    msg['Subject'] = subject

    # 1. Plain Text Version (Good for anti-spam filters)
    part1 = MIMEText(body_text, 'plain')
    
    # 2. Modern, Clean HTML Design (inspired by contemporary email patterns)
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{ 
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; 
            background-color: #f8f9fb;
            margin: 0; 
            padding: 30px 0; 
            line-height: 1.65;
        }}
        
        .email-container {{ 
            max-width: 600px; 
            margin: 0 auto; 
            background: #ffffff; 
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        }}
        
        .header {{ 
            background: #ffffff;
            padding: 40px 40px 30px;
            text-align: center;
            position: relative;
            border-bottom: 1px solid #e8eaed;
        }}
        
        .decorative-dots {{
            position: absolute;
            top: 20px;
            left: 20px;
            right: 20px;
            height: 60px;
            opacity: 0.15;
        }}
        
        .dot {{
            position: absolute;
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: #6366f1;
        }}
        
        .logo {{ 
            font-size: 26px; 
            font-weight: 700; 
            color: #0f172a;
            letter-spacing: -0.5px;
            position: relative;
            z-index: 1;
        }}
        
        .logo-accent {{
            color: #6366f1;
        }}
        
        .tagline {{ 
            color: #64748b;
            font-size: 13px;
            font-weight: 500;
            margin-top: 6px;
            position: relative;
            z-index: 1;
        }}
        
        .content {{ 
            padding: 50px 40px;
        }}
        
        .body-text {{ 
            font-size: 15px;
            color: #334155;
            line-height: 1.75;
            margin-bottom: 30px;
            white-space: pre-wrap;
            word-wrap: break-word;
        }}
        
        .cta-container {{
            text-align: center;
            margin: 40px 0;
        }}
        
        .cta-button {{ 
            display: inline-block;
            padding: 15px 36px;
            background: #6366f1;
            color: #ffffff !important;
            text-decoration: none;
            border-radius: 6px;
            font-weight: 600;
            font-size: 14px;
            letter-spacing: 0.2px;
            box-shadow: 0 1px 3px rgba(99, 102, 241, 0.3);
        }}
        
        .cta-subtext {{
            margin-top: 14px;
            font-size: 13px;
            color: #94a3b8;
        }}
        
        .divider {{
            height: 1px;
            background: #e8eaed;
            margin: 40px 0;
        }}
        
        .info-section {{
            background: #f8f9fb;
            border-radius: 6px;
            padding: 28px;
            margin: 30px 0;
        }}
        
        .info-title {{
            font-size: 15px;
            font-weight: 600;
            color: #0f172a;
            margin-bottom: 18px;
        }}
        
        .info-list {{
            list-style: none;
            padding: 0;
        }}
        
        .info-item {{
            padding: 10px 0;
            font-size: 14px;
            color: #475569;
            position: relative;
            padding-left: 24px;
        }}
        
        .info-item:before {{
            content: '';
            position: absolute;
            left: 0;
            top: 16px;
            width: 12px;
            height: 2px;
            background: #6366f1;
        }}
        
        .signature {{ 
            margin-top: 45px;
            padding-top: 30px;
            border-top: 1px solid #e8eaed;
        }}
        
        .signature-name {{ 
            font-size: 15px;
            font-weight: 600;
            color: #0f172a;
            margin-bottom: 2px;
        }}
        
        .signature-company {{ 
            font-size: 15px;
            font-weight: 700;
            color: #6366f1;
            margin: 8px 0 4px;
        }}
        
        .signature-tagline {{ 
            font-size: 13px;
            color: #64748b;
            margin-bottom: 16px;
        }}
        
        .link-row {{ 
            margin-top: 16px;
        }}
        
        .text-link {{ 
            color: #6366f1 !important;
            text-decoration: none;
            font-size: 13px;
            font-weight: 500;
            margin-right: 16px;
        }}
        
        .footer {{ 
            background: #f8f9fb;
            padding: 30px 40px;
            text-align: center;
            border-top: 1px solid #e8eaed;
        }}
        
        .footer-highlight {{ 
            background: #ffffff;
            border: 1px solid #e8eaed;
            border-radius: 6px;
            padding: 20px;
            margin-bottom: 20px;
            font-size: 13px;
            color: #475569;
        }}
        
        .footer-highlight strong {{
            color: #0f172a;
        }}
        
        .footer-links {{ 
            margin-top: 18px;
        }}
        
        .footer-link {{ 
            color: #6366f1 !important;
            text-decoration: none;
            font-size: 12px;
            margin: 0 8px;
            font-weight: 500;
        }}
        
        .footer-copyright {{ 
            margin-top: 16px;
            font-size: 11px;
            color: #94a3b8;
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <!-- Header -->
        <div class="header">
            <div class="decorative-dots">
                <span class="dot" style="top: 10px; left: 30px;"></span>
                <span class="dot" style="top: 25px; left: 60px;"></span>
                <span class="dot" style="top: 15px; right: 80px;"></span>
                <span class="dot" style="top: 35px; right: 40px;"></span>
                <span class="dot" style="top: 8px; left: 45%;"></span>
            </div>
            <div class="logo"><span class="logo-accent">Web</span>Asthetic Solutions</div>
            <div class="tagline">Building Your Digital Dreams</div>
        </div>
        
        <!-- Main Content -->
        <div class="content">
            <div class="body-text">{body_text}</div>
            
            <!-- CTA -->
            <div class="cta-container">
                <a href="https://cal.com/webastheticsolutions" class="cta-button">
                    Schedule a Free Consultation
                </a>
                <div class="cta-subtext">No commitment required</div>
            </div>
            
            <div class="divider"></div>
            
            <!-- What We Offer -->
            <div class="info-section">
                <div class="info-title">Why Choose WebAsthetic?</div>
                <ul class="info-list">
                    <li class="info-item"><strong>Expert Development</strong> &mdash; Full-stack solutions with cutting-edge technologies</li>
                    <li class="info-item"><strong>Beautiful Design</strong> &mdash; UI/UX that converts and engages users</li>
                    <li class="info-item"><strong>Lightning Fast</strong> &mdash; Optimized for speed and performance</li>
                </ul>
            </div>
            
            <!-- Signature -->
            <div class="signature">
                <div class="signature-name">Best regards,</div>
                <div class="signature-company">WebAsthetic Solutions</div>
                <div class="signature-tagline">Your Strategic Partner in Digital Transformation</div>
                <div class="link-row">
                    <a href="https://webasthetic.in" class="text-link">Visit Website</a>
                    <a href="https://webasthetic.in/portfolio" class="text-link">View Portfolio</a>
                </div>
            </div>
        </div>
        
        <!-- Footer -->
        <div class="footer">
            <div class="footer-highlight">
                <strong>Launch Special Offer:</strong> Free Consultation + 1 Month Free Maintenance + Unlimited Revisions
            </div>
            <div class="footer-links">
                <a href="https://webasthetic.in/about" class="footer-link">About</a>
                <a href="https://webasthetic.in/services" class="footer-link">Services</a>
                <a href="https://webasthetic.in/contact" class="footer-link">Contact</a>
            </div>
            <div class="footer-copyright">
                Automated Email
                &copy; 2026 WebAsthetic Solutions. All rights reserved.
            </div>
        </div>
    </div>
</body>
</html>"""
    part2 = MIMEText(html_content, "html")

    msg.attach(part1)
    msg.attach(part2)

    for attempt in range(1, MAX_SMTP_RETRIES + 2):
        try:
            # Connect & Send via SMTP SSL
            logger.info(f"   🔗 Connecting to {SMTP_SERVER}:{SMTP_PORT}...")
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=15) as server:
                logger.info(f"   🔐 Authenticating as {SMTP_EMAIL}...")
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                logger.info(f"   📤 Sending to {to_email}...")
                server.send_message(msg)  # Use send_message() like the working test
                logger.info(f"   ✅ Email sent successfully!")
            
            # Save copy to Sent folder via IMAP
            save_to_sent_folder(msg)
            
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"   ❌ SMTP Auth Failed: Check SMTP_EMAIL and SMTP_PASSWORD in .env")
            logger.error(f"      Error: {e}")
            return False
        except (smtplib.SMTPException, TimeoutError, OSError) as e:
            logger.error(f"   ❌ SMTP Error: {e}")
            if attempt <= MAX_SMTP_RETRIES:
                backoff = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.info(f"   🔁 Retrying in {backoff}s (attempt {attempt}/{MAX_SMTP_RETRIES})...")
                time.sleep(backoff)
                continue
            return False
        except Exception as e:
            logger.error(f"   ❌ Unexpected Error: {e}")
            import traceback
            traceback.print_exc()
            return False


def save_to_sent_folder(msg):
    """Save email copy to IMAP Sent folder"""
    try:
        # Connect to IMAP
        imap = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        imap.login(SMTP_EMAIL, SMTP_PASSWORD)
        
        # Save to Sent folder (Hostinger uses "Sent" folder name)
        imap.append('Sent', '\\Seen', imaplib.Time2Internaldate(time.time()), msg.as_bytes())
        imap.logout()
        logger.info(f"      💾 Saved to Sent folder")
        return True
    except Exception as e:
        logger.warning(f"      ⚠️ Could not save to Sent folder: {e}")
        return False


def run_email_sender(callback_url: str = None):
    """
    Sends generated cold emails from master_leads table via Hostinger SMTP.
    Only processes leads with generated_subject and generated_body.
    """
    print("📨 Starting Email Dispatcher (PRODUCTION MODE)...")
    
    if callback_url:
        logger.info(f"📍 Callback URL registered: {callback_url}")
    
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        logger.error("❌ SMTP_EMAIL or SMTP_PASSWORD not configured in .env")
        return 0

    # Connect to MongoDB
    col_master_leads = get_master_leads_collection()

    # Get leads that have emails generated but not sent yet
    pending_leads = list(col_master_leads.find({
        "generated_subject": {"$exists": True},
        "generated_body": {"$exists": True},
        "status": {"$ne": "sent"}
    }).limit(BATCH_SIZE))

    print(f"   📧 Found {len(pending_leads)} leads ready to send (batch size: {BATCH_SIZE})...")

    if not pending_leads:
        print("   ✨ No pending emails to send.")
        if callback_url:
            try:
                requests.post(callback_url, json={"status": "success", "sent": 0}, timeout=15)
            except:
                pass
        return 0

    sent_count = 0
    failed_count = 0
    
    for idx, lead in enumerate(pending_leads, 1):
        email = lead.get("email", "unknown")
        subject = lead.get("generated_subject", "No Subject")
        body = lead.get("generated_body", "")
        
        print(f"   [{idx}/{len(pending_leads)}] Sending to: {email}...", end=" ")

        success = send_email(email, subject, body)

        if success:
            # Update MongoDB status to 'sent'
            col_master_leads.update_one(
                {"_id": lead["_id"]},
                {
                    "$set": {
                        "status": "sent",
                        "email_sent_at": datetime.now(timezone.utc)
                    }
                }
            )
            print("✅")
            sent_count += 1
            
            # Rate limiting delay (except for last email)
            if idx < len(pending_leads):
                time.sleep(DELAY_BETWEEN_EMAILS)
        else:
            # Update status to 'failed' for retry tracking
            col_master_leads.update_one(
                {"_id": lead["_id"]},
                {
                    "$set": {
                        "status": "failed",
                        "email_failed_at": datetime.now(timezone.utc)
                    }
                }
            )
            print("❌")
            failed_count += 1

    print(f"\n📨 Email Dispatch Complete!")
    print(f"   ✅ Sent: {sent_count} emails")
    print(f"   ❌ Failed: {failed_count} emails")

    # Callback to n8n
    if callback_url:
        logger.info(f"📞 Calling back n8n at: {callback_url}")
        try:
            response = requests.post(
                callback_url,
                json={
                    "status": "success",
                    "message": f"Email dispatch complete. Sent {sent_count}, Failed {failed_count}",
                    "sent_count": sent_count,
                    "failed_count": failed_count
                },
                timeout=15
            )
            logger.info(f"✅ Callback sent. Status: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Callback failed: {e}")

    return sent_count


if __name__ == "__main__":
    run_email_sender()
