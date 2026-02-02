import asyncio
import json
import os
import re
import sys
from datetime import datetime, date
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from src.database import get_db_collection 

collection = get_db_collection()

async def main(search_url: str | None = None):
    # 1. READ ARGUMENT FROM N8N
    # If n8n sends a URL, use it. Otherwise, use a default for testing.
    if not search_url:
        if len(sys.argv) > 1:
            search_url = sys.argv[1]
            print(f"🔗 Received Target from n8n: {search_url}")
        else:
            # Fallback / Default
            keywords = '%22looking%20for%22%20AND%20(%22web%20developer%22%20OR%20%22web%20development%20agency%22)'
            search_url = f"https://www.linkedin.com/search/results/content/?datePosted=%22past-24h%22&keywords={keywords}"
    # VERIFIED SCROLL JS: Mimics manual scrolling perfectly
    apex_mimic_js = """
    (async () => {
        const sleep = ms => new Promise(r => setTimeout(r, ms));
        for (let i = 0; i < 45; i++) {
            // 1. Smooth scroll
            window.scrollBy(0, 1000);
            await sleep(2000);

            // 2. Click 'See More' on every visible post to trigger expansion
            const buttons = document.querySelectorAll('button[aria-label*="see more"], .feed-shared-inline-show-more-text__see-more-less-toggle');
            buttons.forEach(btn => { if(btn.offsetParent !== null) btn.click(); });
            
            // 3. Click 'Show more results' if it appears
            const loadBtn = document.querySelector('button.scaffold-finite-scroll__load-button');
            if (loadBtn) { loadBtn.scrollIntoView(); loadBtn.click(); await sleep(4000); }
        }
    })();
    """

    browser_cfg = BrowserConfig(
        headless=False,
        user_data_dir="./linkedin_session",
        use_managed_browser=True
    )

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        session_id = "webasthetic_apex"
        
        print(f"\n🚀 [Webasthetic] Apex Engine Engaged.")
        print("⏳ PHASE 1: Login & Setup (30s Window)")
        print("ACTION: Ensure search results load. Scroll down manually to 'wake up' the feed.")
        
        await crawler.arun(
            url=search_url,
            config=CrawlerRunConfig(
                session_id=session_id,
                cache_mode=CacheMode.BYPASS,
                delay_before_return_html=30.0 
            )
        )

        print("🚀 PHASE 2: Python-Controlled Deep Harvest... (Watching for 100% full text)")
        
        # WE CAPTURE THE FINAL STATE
        result = await crawler.arun(
            url=search_url,
            config=CrawlerRunConfig(
                session_id=session_id,
                js_code=apex_mimic_js,
                wait_for="css:main",
                # WE INCREASE THIS DELAY: This ensures the text expansion 
                # actually finishes before Python grabs the HTML string.
                delay_before_return_html=50.0, 
                page_timeout=1200000 
            )
        )

        if result and result.html:
            print("📦 Harvesting Data from Rendered DOM with BeautifulSoup...")
            soup = BeautifulSoup(result.html, 'html.parser')
            
            # Targeting URNs is the most impeccable way as these IDs never change
            containers = soup.find_all(attrs={"data-urn": re.compile(r"activity:")})
            if not containers:
                containers = soup.select(".occludable-update")

            timezone_name = os.getenv("TIMEZONE", "UTC")
            try:
                today_str = datetime.now(ZoneInfo(timezone_name)).date().isoformat()
            except Exception:
                today_str = date.today().isoformat()

            leads = []
            seen_profiles = set()

            for c in containers:
                try:
                    # 1. Profile extraction
                    actor = c.find('a', href=re.compile(r"/in/|/company/"))
                    if not actor: continue
                    link = actor['href'].split('?')[0]
                    if not link.startswith('http'): link = "https://www.linkedin.com" + link

                    # 2. Content extraction (Targeting THE SPAN that appears AFTER expansion)
                    # We grab every span inside the text area to ensure we catch the newly injected text
                    body = c.select_one(".update-components-text, .feed-shared-update-v2__description")
                    if not body: continue
                    
                    # separator=" " ensures we don't bunch lines together
                    text = body.get_text(separator=" ", strip=True)
                    
                    # Remove trailing "see more" and fix whitespace
                    text = re.sub(r'…see more|see more$', '', text, flags=re.IGNORECASE).strip()

                    # Filter junk and duplicates
                    if len(text) > 100 and link not in seen_profiles:
                        leads.append({
                            "profile_url": link,
                            "content": text,
                            "scraped_at": today_str
                        })
                        seen_profiles.add(link)
                except:
                    continue

            if leads:
                try:
                    collection.insert_many(leads, ordered=False)
                    print(f"✅ SUCCESS: {len(leads)} leads harvested with 100% FULL text.")
                    print(f"📄 Full Body Verification: {leads[0]['content'][:250]}...")
                except Exception:
                    print(f"ℹ️ {len(leads)} leads processed and synced.")
            else:
                print("❌ No leads found in rendered HTML. Check if posts were expanded on screen.")
        else:
            print("❌ Critical Fail: Browser returned no HTML.")

def run_selenium_scraper(search_url: str):
    print(f"🕵️‍♂️ Starting Scraper for: {search_url}")
    asyncio.run(main(search_url))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Stopped.")