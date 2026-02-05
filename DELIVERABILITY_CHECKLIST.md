# 📧 Email Deliverability Checklist

## Current Status
✅ SPF: Configured correctly  
⚠️ **DKIM: MISSING** (This is why emails go to spam!)  
✅ DMARC: Configured  
✅ SMTP: Working  

---

## 🔧 Fix DKIM (CRITICAL - Do This Now)

### Step 1: Enable DKIM in Hostinger
1. Go to: https://hpanel.hostinger.com
2. Navigate to: **Emails → Email Accounts**
3. Find your domain: `webasthetic.in`
4. Click **DKIM Records** or **Email Authentication**
5. Click **Enable DKIM**
6. Copy the generated DKIM record

### Step 2: Add DKIM to DNS
**If using Hostinger DNS:**
- Hostinger may auto-add it for you
- Verify in: **Domains → DNS Zone Editor**

**If using external DNS (Cloudflare/GoDaddy):**
- Add a **TXT record**:
  - Name: `default._domainkey` (or as shown by Hostinger)
  - Value: (paste the DKIM value from Hostinger)
  - TTL: Auto or 3600

### Step 3: Wait for Propagation
- DNS changes take **1-24 hours** to propagate worldwide
- Check propagation: https://mxtoolbox.com/dkim.aspx
- Enter: `default._domainkey.webasthetic.in`

---

## 📝 Additional Deliverability Tips

### 1. Warm Up Your Sending Domain
**Current Status:** New domain, sending cold emails = High spam risk

**Warm-up Schedule:**
- Week 1: Send 10-20 emails/day
- Week 2: Send 30-50 emails/day  
- Week 3: Send 75-100 emails/day
- Week 4+: Ramp up to 200-500/day

**Why:** ISPs (Gmail, Outlook) track sender reputation. New domains sending lots of emails = spam flag.

### 2. Improve Email Content
**Spam Trigger Words to Avoid:**
- ❌ "Free", "Click here", "Act now", "Limited time"
- ❌ ALL CAPS SUBJECT LINES
- ❌ Too many exclamation marks!!!
- ❌ Heavy image-to-text ratio (text is better)

**Better Practices:**
- ✅ Personalized subject lines (use recipient's name/company)
- ✅ Natural, conversational language
- ✅ Proper grammar and punctuation
- ✅ Include unsubscribe link (we'll add this)
- ✅ Text-heavy with minimal images

### 3. Monitor Bounce Rate
**Keep bounce rate < 5%**
- Verify emails before sending (use email verification API)
- Remove invalid emails from list
- High bounce rate = damaged sender reputation

### 4. Track Engagement
**Good engagement = better deliverability**
- Gmail tracks: Opens, clicks, replies, deletes, marks as spam
- High engagement → Inbox  
- Low engagement → Spam folder

**Tips to increase engagement:**
- Send at optimal times (Tue-Thu, 10 AM - 2 PM)
- A/B test subject lines
- Personalize content (use AI summaries we already have)
- Follow up with engaged recipients

---

## 🧪 Testing After DKIM Setup

**1. Send Test Email (24 hours after DKIM setup):**
```bash
python -m src.email_sender
```

**2. Check Email Headers:**
- Open the test email in Gmail
- Click **⋮** (three dots) → **Show original**
- Look for:
  ```
  SPF: PASS
  DKIM: PASS
  DMARC: PASS
  ```

**3. Use Email Tester Tools:**
- https://www.mail-tester.com
- Send email to the provided address
- Check spam score (aim for 9-10/10)

**4. Check Blacklists:**
- https://mxtoolbox.com/blacklists.aspx
- Enter: `webasthetic.in`
- Ensure not blacklisted

---

## 📊 Current Email Stats

**Generated Emails:** 26 ready to send  
**Batch Size:** 10 emails/run (for warm-up)  
**Delay Between Emails:** 8 seconds  
**Daily Limit:** ~450 emails (30 batches × 15 emails)

---

## ⚡ Quick Start After DKIM Setup

**1. Wait 24 hours for DKIM propagation**

**2. Uncomment production mode in `src/email_sender.py`:**
- Remove `# ========== COMMENTED OUT FOR TESTING ==========` sections
- This enables MongoDB integration

**3. Run email sender:**
```bash
python -m src.email_sender
```

**4. Monitor results:**
- Check Gmail deliverability for first 10 emails
- Adjust content if emails still go to spam
- Increase batch size gradually

---

## 🆘 Still Going to Spam?

If DKIM is enabled and emails still go to spam after 24-48 hours:

1. **Content Review:**
   - Remove any spammy words
   - Make emails more conversational
   - Add more personalization

2. **Sender Reputation:**
   - Reduce send volume (5-10/day for 1-2 weeks)
   - Ask recipients to mark as "Not Spam"
   - Get initial replies to build reputation

3. **Technical:**
   - Verify reverse DNS (PTR record)
   - Check if Hostinger IP is blacklisted
   - Consider using Gmail/Outlook SMTP for higher deliverability

4. **Alternative Solutions:**
   - Use email sending service (SendGrid, Mailgun, Amazon SES)
   - These have pre-warmed IPs with good reputation
   - Cost: ~$0.001 per email

---

## 📞 Support Resources

- **Hostinger Support:** https://www.hostinger.com/cpanel-login → Live Chat
- **Email Authentication Guide:** https://support.hostinger.com/en/articles/1583448
- **Our Email Setup:** `EMAIL_SENDER_SETUP.md` in this project

---

**Last Updated:** 2026-02-05  
**Next Action:** Enable DKIM in Hostinger → Wait 24 hours → Re-test
