"""
Hostinger Email Deliverability Diagnostic Tool
Run this to check if your Hostinger account is properly configured
"""
import os
import smtplib
import dns.resolver
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.hostinger.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

print("=" * 60)
print("🔍 HOSTINGER EMAIL DELIVERABILITY DIAGNOSTIC")
print("=" * 60)

# 1. Check credentials
print("\n1️⃣ Checking Credentials...")
if not SMTP_EMAIL or not SMTP_PASSWORD:
    print("   ❌ SMTP_EMAIL or SMTP_PASSWORD not set in .env")
    exit(1)
print(f"   ✅ SMTP_EMAIL: {SMTP_EMAIL}")
print(f"   ✅ SMTP_PASSWORD: {'*' * len(SMTP_PASSWORD)}")

# 2. Check domain from email
domain = SMTP_EMAIL.split('@')[1]
print(f"\n2️⃣ Checking Domain: {domain}")

# 3. Check SPF Record
print(f"\n3️⃣ Checking SPF Record for {domain}...")
try:
    answers = dns.resolver.resolve(domain, 'TXT')
    spf_found = False
    for rdata in answers:
        txt = str(rdata).strip('"')
        if 'v=spf1' in txt:
            print(f"   ✅ SPF Record Found: {txt}")
            if 'include:_spf.mail.hostinger.com' in txt or 'include:mail.hostinger.com' in txt:
                print("   ✅ Hostinger SPF included correctly")
            else:
                print("   ⚠️ WARNING: Hostinger SPF might not be included!")
                print("   📝 Add this to your DNS TXT record:")
                print(f"      v=spf1 include:_spf.mail.hostinger.com ~all")
            spf_found = True
            break
    if not spf_found:
        print("   ❌ No SPF record found!")
        print("   📝 Add this TXT record to your DNS:")
        print(f"      v=spf1 include:_spf.mail.hostinger.com ~all")
except Exception as e:
    print(f"   ❌ SPF Check Failed: {e}")

# 4. Check DKIM
print(f"\n4️⃣ Checking DKIM for {domain}...")
try:
    # Common DKIM selector for Hostinger
    dkim_selector = "default._domainkey"
    dkim_domain = f"{dkim_selector}.{domain}"
    answers = dns.resolver.resolve(dkim_domain, 'TXT')
    print(f"   ✅ DKIM Record Found at {dkim_domain}")
    for rdata in answers:
        print(f"      {str(rdata)[:100]}...")
except Exception as e:
    print(f"   ⚠️ DKIM not found at default._domainkey.{domain}")
    print(f"   📝 To enable DKIM:")
    print(f"      1. Log in to Hostinger control panel")
    print(f"      2. Go to Email > DKIM Records")
    print(f"      3. Enable DKIM for {domain}")
    print(f"      4. Copy the DKIM record to your DNS")

# 5. Check DMARC
print(f"\n5️⃣ Checking DMARC for {domain}...")
try:
    dmarc_domain = f"_dmarc.{domain}"
    answers = dns.resolver.resolve(dmarc_domain, 'TXT')
    for rdata in answers:
        print(f"   ✅ DMARC Record Found: {str(rdata)}")
except Exception as e:
    print(f"   ⚠️ No DMARC record found")
    print(f"   📝 Recommended DMARC record (add as TXT for _dmarc.{domain}):")
    print(f"      v=DMARC1; p=none; rua=mailto:{SMTP_EMAIL}")

# 6. Test SMTP Connection
print(f"\n6️⃣ Testing SMTP Connection to {SMTP_SERVER}:{SMTP_PORT}...")
try:
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        print("   ✅ SMTP Connection & Authentication Successful")
except smtplib.SMTPAuthenticationError:
    print("   ❌ Authentication Failed - Check your email/password")
    exit(1)
except Exception as e:
    print(f"   ❌ Connection Failed: {e}")
    exit(1)

# 7. Send test email to multiple providers
print(f"\n7️⃣ Sending test emails to multiple providers...")
test_recipients = [
    "hardik3810@gmail.com",  # Gmail
]

for recipient in test_recipients:
    provider = recipient.split('@')[1]
    print(f"\n   📤 Sending to {provider}...")
    
    msg = MIMEMultipart('alternative')
    msg['From'] = f"WebAsthetic Solutions <{SMTP_EMAIL}>"
    msg['To'] = recipient
    msg['Subject'] = "🔍 Hostinger Deliverability Test"
    
    text_body = """
This is a test email from Hostinger.

If you received this email, your Hostinger setup is working correctly.

Please check:
1. Did this land in Inbox or Spam?
2. Does the sender show as "WebAsthetic Solutions"?

Best regards,
WebAsthetic Solutions
"""
    
    html_body = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #2563eb;">🔍 Hostinger Deliverability Test</h2>
        
        <p>This is a test email from Hostinger.</p>
        
        <p><strong>If you received this email, your Hostinger setup is working correctly.</strong></p>
        
        <p>Please check:</p>
        <ol>
            <li>Did this land in <strong>Inbox</strong> or <strong>Spam</strong>?</li>
            <li>Does the sender show as "<strong>WebAsthetic Solutions</strong>"?</li>
        </ol>
        
        <p>Best regards,<br>
        <strong>WebAsthetic Solutions</strong></p>
        
        <hr style="border: 0; border-top: 1px solid #ddd; margin: 20px 0;">
        <p style="font-size: 12px; color: #666;">
            This is an automated test email sent via Hostinger SMTP.<br>
            Domain: {domain}<br>
            Time: {time}
        </p>
    </div>
</body>
</html>
""".format(domain=domain, time=__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    
    msg.attach(MIMEText(text_body, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))
    
    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(msg)
            print(f"      ✅ Sent successfully to {recipient}")
    except Exception as e:
        print(f"      ❌ Failed: {e}")

print("\n" + "=" * 60)
print("📊 DIAGNOSTIC SUMMARY")
print("=" * 60)
print("\n✅ Next Steps:")
print("1. Check the recipient inbox AND spam folder")
print("2. If email is in spam:")
print("   - Enable DKIM in Hostinger control panel")
print("   - Add/verify SPF record in DNS")
print("   - Add DMARC record")
print("   - Wait 24-48 hours for DNS propagation")
print("3. If email not received at all:")
print("   - Verify email account is activated in Hostinger")
print("   - Check Hostinger email sending limits")
print("   - Contact Hostinger support")
print("\n🔗 Hostinger Email Setup Guide:")
print("   https://support.hostinger.com/en/articles/1583448-how-to-set-up-email-authentication-spf-dkim-and-dmarc")
print("=" * 60)
