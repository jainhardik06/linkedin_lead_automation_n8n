# Phase 10: Email Sender Setup Guide

## 🔧 Hostinger Configuration (REQUIRED - Do This First!)

### Step 1: Enable DKIM & SPF in Hostinger

1. **Log in to Hostinger** → **Hosting** → Your Domain → **Emails**
2. Click **Manage** on your domain
3. Go to **Email Security** or **DKIM Settings**
4. **Enable DKIM** (usually auto-enabled, but confirm)
5. **Check SPF Record:** Should show `v=spf1 include:_spf.mail.hostinger.com ~all`

### Step 2: Add DMARC Record (Optional but Recommended)

1. Go to **DNS Settings** in Hostinger
2. Add a new **TXT Record:**
   - **Name/Host:** `_dmarc`
   - **Value:** `v=DMARC1; p=quarantine; rua=mailto:your-email@webasthetic.in`
3. Save

### Step 3: Create Email Account in Hostinger

1. **Emails** → **Create New Email**
2. **Email Address:** `hello@webasthetic.in` (or any address you want)
3. **Password:** Create a strong password (you'll need this in .env)
4. **Storage:** 10 GB is fine for sending
5. Save and remember the password

---

## 📝 Update `.env` File

Add these lines to your `.env` file:

```ini
# Hostinger SMTP Settings
SMTP_SERVER=smtp.hostinger.com
SMTP_PORT=465
SMTP_EMAIL=hello@webasthetic.in
SMTP_PASSWORD=your-email-password-here
```

**Replace:**
- `hello@webasthetic.in` with the email you created in Hostinger
- `your-email-password-here` with the password you set

---

## ⚙️ Configuration in `src/email_sender.py`

The script is pre-configured with safe defaults:

```python
BATCH_SIZE = 10              # Send 10 emails per run
DELAY_BETWEEN_EMAILS = 8     # Wait 8 seconds between each email
```

### Warm-Up Strategy (IMPORTANT!)

Your Hostinger plan allows **1000 emails/day**, but new senders are flagged as spam if they spike volume.

**Follow this gradual warm-up:**

| Week | BATCH_SIZE | Daily Volume | Instructions |
|------|-----------|--------------|-------------|
| 1 | 10 | 10 emails | Keep current setting |
| 2 | 20 | 20 emails | Edit line 26: `BATCH_SIZE = 20` |
| 3 | 30 | 30 emails | Edit line 26: `BATCH_SIZE = 30` |
| 4+ | 50+ | 50+ emails | Gradually increase |

**Edit in `src/email_sender.py` (line 26):**
```python
BATCH_SIZE = 10  # Change this value gradually
```

---

## 🚀 Testing the Email Sender

### Test 1: Send a Single Email Manually

```bash
cd d:\D\Linkedin_Lead_Automation
python -c "from src.email_sender import send_email; send_email('your-test-email@gmail.com', 'Test Subject', 'Hello World')"
```

If successful, you'll see "✅ Sent" output.

### Test 2: Run the Full Dispatcher

```bash
python -m src.email_sender
```

This will:
1. Look for generated emails in `master_leads` table
2. Send up to `BATCH_SIZE` emails
3. Mark them as `email_sent: True` in MongoDB
4. Show a summary

---

## 🤖 n8n Workflow Setup (Phase 10)

### New Separate Workflow: "Email Dispatcher"

**Workflow Structure:**

```
[Schedule Trigger (Daily at 10 AM)]
    ↓
[HTTP Request: Run Email Sender]
    ↓
[Wait Node: Webhook Callback]
    ↓
[Optional: Slack/Notification Node]
    ↓
[Stop]
```

### n8n Node Configuration

#### 1. **Schedule Trigger Node**
- **Type:** Schedule (Trigger)
- **Schedule:** Every day
- **Time:** 10:00 AM (or whenever you want)

#### 2. **HTTP Request Node** - "Run Email Sender"
- **Method:** `POST`
- **URL:** `http://host.docker.internal:8000/run-email-sender`
- **Body (JSON):**
  ```json
  {
    "callback_url": "{{ $execution.resumeUrl }}"
  }
  ```

#### 3. **Wait Node**
- **Resume:** `On Webhook Call`
- **HTTP Method:** `POST`
- **Respond:** `Immediately`

#### 4. **Slack Notification (Optional)**
- **Channel:** `#automation`
- **Message:** `Email batch sent: {{ $node["HTTP Request"].data.message }}`

---

## 📊 Database Schema - What Gets Updated

**Collection:** `master_leads`

**Before Sending:**
```json
{
  "email": "hiring@company.com",
  "generated_subject": "Quick idea for [Company]",
  "generated_body": "Hi there...",
  "email_sent": false  // or doesn't exist
}
```

**After Sending:**
```json
{
  "email": "hiring@company.com",
  "generated_subject": "Quick idea for [Company]",
  "generated_body": "Hi there...",
  "email_sent": true,
  "email_sent_at": "2026-02-04T10:30:45.123Z"
}
```

---

## ⚠️ Troubleshooting

### "SMTP Error: 535 Authentication failed"
- **Cause:** Wrong email or password in `.env`
- **Fix:** Double-check both in Hostinger and .env

### "Emails going to Spam"
- **Cause:** DKIM/SPF not configured
- **Fix:** Follow the Hostinger setup steps above

### "Rate limit exceeded"
- **Cause:** Sending too many emails too fast
- **Fix:** Reduce `BATCH_SIZE` or increase `DELAY_BETWEEN_EMAILS`

### "All emails show as sent but recipient didn't receive"
- **Cause:** Domain reputation issue (likely)
- **Fix:** 
  - Check Hostinger's outgoing email status
  - Add more DNS records (DMARC)
  - Wait a few days for domain warmup

---

## 🔄 Full Pipeline Flow (Phases 1-10)

```
[Phase 1: Scrape LinkedIn Posts]
    ↓
[Phase 2: Extract Emails & Mobiles]
    ↓
[Phase 3: Summarize Posts (Groq)]
    ↓
[Phase 4: Deep Scrape Profiles]
    ↓
[Phase 5: Summarize Profiles (Groq)]
    ↓
[Phase 6: Aggregate Leads + Generate Emails (Groq)]
    ↓
[Phase 10: Send Emails via SMTP] ← You are here
    ↓
[✅ Complete - Ready for replies]
```

---

## 🎯 Next Steps

1. ✅ Configure Hostinger (DKIM/SPF/Email Account)
2. ✅ Update `.env` with SMTP credentials
3. ✅ Test manually: `python -m src.email_sender`
4. ✅ Set up n8n workflow with Schedule trigger
5. ✅ Let it run for Week 1 with `BATCH_SIZE = 10`
6. ✅ Monitor spam folder for first batch
7. ✅ Increase `BATCH_SIZE` weekly

---

## 📞 Support

If emails aren't sending:
- Check `.env` for typos
- Verify email exists in Hostinger
- Check MongoDB for `master_leads` records
- Look at application logs for SMTP errors
