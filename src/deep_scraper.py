import glob
import logging
import os
import re
import time
import random
import urllib.parse
import requests
from datetime import datetime, timezone

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
)

from src.database import (
    get_final_table_collection,
    get_raw_posts_collection,
    get_user_scrapped_collection,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEMP_DOWNLOAD_PATH = os.path.join(os.getcwd(), "temp_downloads")
SELENIUM_TIMEOUT = 10
CONTACT_WAIT_TIMEOUT = 8
RATE_LIMIT_DELAY = 30
PROFILE_LOAD_DELAY = 6


def random_delay(base_seconds, variance=0.3):
    """Add random variance to delays to appear more human-like."""
    variance_amount = base_seconds * variance
    return base_seconds + random.uniform(-variance_amount, variance_amount)


def ensure_temp_folder():
    """Ensure temporary download folder exists."""
    if not os.path.exists(TEMP_DOWNLOAD_PATH):
        os.makedirs(TEMP_DOWNLOAD_PATH)


def get_driver():
    """Configure Chrome WebDriver with minimal, stable options."""
    options = webdriver.ChromeOptions()
    
    # Use persistent session directory (same as scraper.py)
    session_dir = os.path.join(os.getcwd(), "linkedin_session")
    if not os.path.exists(session_dir):
        os.makedirs(session_dir)
    
    options.add_argument(f"user-data-dir={session_dir}")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    
    prefs = {
        "download.default_directory": TEMP_DOWNLOAD_PATH,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
    }
    options.add_experimental_option("prefs", prefs)
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    return webdriver.Chrome(options=options)


def normalize_link(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        if "linkedin.com" in parsed.netloc and "/redir/redirect" in parsed.path:
            qs = urllib.parse.parse_qs(parsed.query)
            if "url" in qs and qs["url"]:
                return qs["url"][0]
        return url
    except Exception:
        return url


def extract_contact_from_text(text: str, html: str):
    data = {"emails": [], "mobiles": [], "links": []}

    email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    emails = re.findall(email_pattern, text or "")
    data["emails"] = list(set([e.lower() for e in emails]))

    mobile_pattern = r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
    mobiles = re.findall(mobile_pattern, text or "")
    valid_mobiles = [m for m in mobiles if len(re.sub(r"\D", "", m)) >= 10]
    data["mobiles"] = list(set(valid_mobiles))

    if html:
        link_pattern = r"href=[\"\']?(https?://[^\s\"\']+)[\"\']?"
        links = re.findall(link_pattern, html)
        clean_links = []
        for link in links:
            link = normalize_link(link)
            if any(x in link for x in ["/search/", "/feed/", "/people/", "/in/"]):
                continue
            if "w3.org" in link or "schema.org" in link:
                continue
            clean_links.append(link)
        data["links"] = list(set(clean_links))

    text_link_pattern = r"(?:(https?://[^\s]+)|(www\.[^\s]+))"
    text_links = re.findall(text_link_pattern, text or "")
    for full_url, www_url in text_links:
        candidate = full_url or www_url
        if candidate.startswith("www."):
            candidate = "https://" + candidate
        candidate = candidate.rstrip(").,;")
        candidate = normalize_link(candidate)
        if any(x in candidate for x in ["/search/", "/feed/", "/people/", "/in/"]):
            continue
        if "w3.org" in candidate or "schema.org" in candidate:
            continue
        data["links"].append(candidate)

    data["links"] = list(set(data["links"]))
    return data


def extract_safe_zone_data(driver, source="top_card"):
    """
    STRICT EXTRACTION: Only extracts data from specific containers.
    source='top_card': The header box (Name, Headline, Custom Buttons)
    source='modal': The Contact Info popup
    Ignores: Feed, Posts, Activity, Similar Profiles
    """
    data = {"emails": [], "mobiles": [], "links": []}
    
    try:
        element_text = ""
        element_html = ""

        if source == "top_card":
            # Target ONLY the profile header (User or Company)
            try:
                selectors = [
                    ".pv-top-card",
                    ".org-top-card",
                    "[data-test-id='top-card']",
                    "section.artdeco-card.pv-top-card",
                    "section.artdeco-card.org-top-card",
                ]
                container = None
                for selector in selectors:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        container = elements[0]
                        break
                if not container:
                    container = WebDriverWait(driver, 3).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".pv-top-card, .org-top-card"))
                    )
                element_text = container.text
                element_html = container.get_attribute("innerHTML")
            except:
                return data
                
        elif source == "modal":
            # Target ONLY the Contact Info Modal
            try:
                container = driver.find_element(By.CLASS_NAME, "artdeco-modal__content")
                element_text = container.text
                element_html = container.get_attribute('innerHTML')
            except:
                return data
        else:
            return data

        # --- 1. EMAIL EXTRACTION ---
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, element_text)
        data["emails"] = list(set([e.lower() for e in emails]))
        
        # --- 2. MOBILE EXTRACTION ---
        # Matches: +91 987..., (555) 123..., 9876543210
        mobile_pattern = r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'
        mobiles = re.findall(mobile_pattern, element_text)
        # Filter out short/junk numbers (dates/years often look like numbers)
        valid_mobiles = [m for m in mobiles if len(re.sub(r'\D', '', m)) >= 10]
        data["mobiles"] = list(set(valid_mobiles))
        
        # --- 3. LINK EXTRACTION (STRICT) ---
        if element_html:
            # Capture hrefs inside the safe zone
            link_pattern = r'href=["\']?(https?://[^\s"\']+)["\']?'
            links = re.findall(link_pattern, element_html)
            
            clean_links = []
            for link in links:
                link = normalize_link(link)
                # IGNORE: Internal LinkedIn Nav (Search, Feed, People)
                if any(x in link for x in ["/search/", "/feed/", "/people/", "/in/"]):
                    continue
                
                # KEEP: External links OR Company Pages (often current employer)
                # Also ignore junk like schema.org or w3.org
                if "w3.org" not in link and "schema.org" not in link:
                    clean_links.append(link)
            
            data["links"] = list(set(clean_links))

        # Also extract links from visible text (e.g., plain www.example.com)
        text_link_pattern = r'(?:(https?://[^\s]+)|(www\.[^\s]+))'
        text_links = re.findall(text_link_pattern, element_text)
        for full_url, www_url in text_links:
            candidate = full_url or www_url
            if candidate.startswith("www."):
                candidate = "https://" + candidate
            candidate = candidate.rstrip(').,;')
            candidate = normalize_link(candidate)
            if any(x in candidate for x in ["/search/", "/feed/", "/people/", "/in/"]):
                continue
            if "w3.org" in candidate or "schema.org" in candidate:
                continue
            data["links"].append(candidate)

        data["links"] = list(set(data["links"]))
        
        if source == "top_card":
            logger.info(f"🎫 Top Card Safe Zone: {len(data['emails'])} emails, {len(data['mobiles'])} mobiles, {len(data['links'])} links")
        else:
            logger.info(f"📇 Modal Safe Zone: {len(data['emails'])} emails, {len(data['mobiles'])} mobiles, {len(data['links'])} links")
        
        return data
        
    except Exception as exc:
        logger.warning(f"Error extracting safe zone data ({source}): {str(exc)[:100]}")
        return data


def extract_company_overflow_links(driver):
    """Extract website link from company overflow (3-dots) menu in the top card."""
    data = {"links": []}
    try:
        def capture_url_from_click(el):
            original_window = driver.current_window_handle
            original_url = driver.current_url
            existing_handles = set(driver.window_handles)

            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                time.sleep(random_delay(0.3, 0.2))
                driver.execute_script("arguments[0].click();", el)
            except Exception:
                return None

            try:
                WebDriverWait(driver, 4).until(lambda d: len(d.window_handles) > len(existing_handles))
            except Exception:
                pass

            new_handles = list(set(driver.window_handles) - existing_handles)
            if new_handles:
                new_handle = new_handles[0]
                driver.switch_to.window(new_handle)
                time.sleep(random_delay(1.0, 0.2))
                new_url = driver.current_url
                actual_url = normalize_link(new_url)
                try:
                    driver.close()
                except Exception:
                    pass
                driver.switch_to.window(original_window)
                return actual_url

            try:
                WebDriverWait(driver, 3).until(EC.url_changes(original_url))
            except Exception:
                return None

            new_url = driver.current_url
            actual_url = normalize_link(new_url)
            try:
                driver.get(original_url)
                time.sleep(random_delay(0.6, 0.2))
            except Exception:
                pass
            return actual_url

        menu_btn = None
        selectors = [
            "button[aria-label*='More']",
            ".top-card-profile-actions__overflow-button",
            "button[data-test-id='top-card-overflow-menu-trigger']",
            "button[aria-label='More actions']",
        ]
        for selector in selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if elements:
                menu_btn = elements[0]
                break

        if not menu_btn:
            return data

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", menu_btn)
        time.sleep(random_delay(0.4, 0.2))
        driver.execute_script("arguments[0].click();", menu_btn)
        time.sleep(random_delay(0.6, 0.2))

        # Prefer explicit menu items
        menu_item_xpaths = [
            "//div[@role='menu']//*[self::a or self::button or self::div][.//span[contains(., 'Visit website')] or contains(., 'Visit website')]",
            "//div[@role='menu']//*[self::a or self::button or self::div][.//span[contains(., 'Learn more')] or contains(., 'Learn more')]",
            "//div[@role='menu']//*[self::a or self::button or self::div][.//span[contains(., 'Register')] or contains(., 'Register')]",
            "//div[@role='menu']//*[self::a or self::button or self::div][.//span[contains(., 'Sign up')] or contains(., 'Sign up')]",
            "//div[@role='menu']//*[self::a or self::button or self::div][.//span[contains(., 'Visit portfolio')] or contains(., 'Visit portfolio')]",
            "//div[@role='menu']//*[self::a or self::button or self::div][.//span[contains(., 'Visit store')] or contains(., 'Visit store')]",
            "//div[@role='menu']//*[self::a or self::button or self::div][.//span[contains(., 'Contact us')] or contains(., 'Contact us')]",
        ]

        captured = False
        for xpath in menu_item_xpaths:
            elements = driver.find_elements(By.XPATH, xpath)
            if not elements:
                continue
            target = elements[0]
            href = target.get_attribute("href")
            if href:
                data["links"].append(normalize_link(href))
                captured = True
                break
            clicked_url = capture_url_from_click(target)
            if clicked_url:
                data["links"].append(clicked_url)
                captured = True
                break

        if not captured:
            # Fallback: collect any hrefs in menu
            menu_links = driver.find_elements(By.CSS_SELECTOR, "div[role='menu'] a[href]")
            for link_el in menu_links:
                href = link_el.get_attribute("href")
                if href:
                    data["links"].append(normalize_link(href))

        # Close menu
        driver.execute_script("document.querySelectorAll('[role=menu]').forEach(m => m.remove());")

        # Normalize links
        data["links"] = list(set(data["links"]))
        return data
    except Exception as exc:
        logger.warning(f"Company overflow link extraction failed: {str(exc)[:100]}")
        return data


def extract_company_about(driver):
    """Click About tab/section and extract full text + emails/mobiles/links."""
    result = {"about_text": "", "emails": [], "mobiles": [], "links": []}

    try:
        current_url = driver.current_url
        on_about_page = "/about" in current_url

        about_btn = None
        about_selectors = [
            "a[href$='/about/']",
            "a[href*='/about']",
            "a[aria-label*='About']",
            "button[aria-label*='About']",
        ]

        for selector in about_selectors:
            elems = driver.find_elements(By.CSS_SELECTOR, selector)
            if elems:
                about_btn = elems[0]
                break

        if not about_btn:
            # Fallback: top nav link by text
            elems = driver.find_elements(By.XPATH, "//a[.//span[contains(., 'About')] or contains(., 'About')]")
            if elems:
                about_btn = elems[0]

        if about_btn and not on_about_page:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", about_btn)
            time.sleep(random_delay(0.4, 0.2))
            driver.execute_script("arguments[0].click();", about_btn)
            time.sleep(random_delay(2.0, 0.4))

        # Find About section container
        containers = []
        section_selectors = [
            "section.org-page-details__definition",
            "section.org-page-details__definition-term",
            "section.org-page-details__definition-list",
        ]

        for selector in section_selectors:
            try:
                elems = driver.find_elements(By.CSS_SELECTOR, selector)
                containers.extend(elems)
            except Exception:
                continue

        try:
            containers.extend(driver.find_elements(By.XPATH, "//section[.//h2[contains(., 'Overview')]]"))
            containers.extend(driver.find_elements(By.XPATH, "//section[.//h2[contains(., 'About')]]"))
        except Exception:
            pass

        containers = [c for c in containers if c is not None]
        if not containers:
            logger.info("About section not found")
            return result

        # Choose the container with the most text
        container = max(containers, key=lambda c: len((c.text or "").strip()))
        about_text = (container.text or "").strip()
        about_html = container.get_attribute("innerHTML") or ""

        result["about_text"] = about_text
        extracted = extract_contact_from_text(about_text, about_html)
        result["emails"] = extracted.get("emails", [])
        result["mobiles"] = extracted.get("mobiles", [])
        result["links"] = extracted.get("links", [])

        logger.info(f"📄 Company About: {len(result['about_text'])} chars, {len(result['emails'])} emails, {len(result['mobiles'])} mobiles, {len(result['links'])} links")
        return result
    except Exception as exc:
        logger.warning(f"Company About extraction failed: {str(exc)[:100]}")
        return result


def extract_user_about(driver):
    """Extract user About section text + emails/mobiles/links."""
    result = {"about_text": "", "emails": [], "mobiles": [], "links": []}

    try:
        containers = []
        section_selectors = [
            "section#about",
            "section.pv-about-section",
            "section.pv-profile-section",
            "section.artdeco-card",
        ]

        for selector in section_selectors:
            try:
                containers.extend(driver.find_elements(By.CSS_SELECTOR, selector))
            except Exception:
                pass

        try:
            containers.extend(driver.find_elements(By.XPATH, "//section[.//h2[contains(., 'About')]]"))
            containers.extend(driver.find_elements(By.XPATH, "//section[.//h2[contains(., 'Summary')]]"))
        except Exception:
            pass

        containers = [c for c in containers if c is not None]
        if not containers:
            logger.info("User About section not found")
            return result

        container = max(containers, key=lambda c: len((c.text or "").strip()))
        about_text = (container.text or "").strip()
        about_html = container.get_attribute("innerHTML") or ""

        result["about_text"] = about_text
        extracted = extract_contact_from_text(about_text, about_html)
        result["emails"] = extracted.get("emails", [])
        result["mobiles"] = extracted.get("mobiles", [])
        result["links"] = extracted.get("links", [])

        logger.info(
            f"📄 User About: {len(result['about_text'])} chars, {len(result['emails'])} emails, {len(result['mobiles'])} mobiles, {len(result['links'])} links"
        )
        return result
    except Exception as exc:
        logger.warning(f"User About extraction failed: {str(exc)[:100]}")
        return result


def extract_company_bio_links(driver):
    """Extract company custom button links (top buttons + overflow menu)."""
    bio_links = []
    try:
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random_delay(1.2, 0.3))

        # Top card links
        top_card_data = extract_safe_zone_data(driver, source="top_card")
        bio_links.extend(top_card_data.get("links", []))

        # Overflow menu links (3-dots)
        overflow_data = extract_company_overflow_links(driver)
        bio_links.extend(overflow_data.get("links", []))

        # De-dup and filter internal LinkedIn
        cleaned = []
        for link in list(set(bio_links)):
            if "linkedin.com" in link.lower():
                continue
            cleaned.append(link)

        logger.info(f"📎 Company bio links: {len(cleaned)}")
        return cleaned
    except Exception as exc:
        logger.warning(f"Company bio links extraction failed: {str(exc)[:100]}")
        return bio_links


def detect_profile_type(driver):
    """Detect if profile is a user profile or company profile."""
    try:
        current_url = driver.current_url
        if "/company/" in current_url:
            logger.info("📊 Company profile detected")
            return "company"
        elif "/in/" in current_url:
            logger.info("👤 User profile detected")
            return "user"
        # DOM-based fallback (handles URL edge cases)
        if driver.find_elements(By.CSS_SELECTOR, ".org-top-card"):
            logger.info("📊 Company profile detected (DOM)")
            return "company"
        if driver.find_elements(By.CSS_SELECTOR, ".pv-top-card"):
            logger.info("👤 User profile detected (DOM)")
            return "user"
        if driver.find_elements(By.ID, "top-card-text-details-contact-info"):
            logger.info("👤 User profile detected (contact button)")
            return "user"
        logger.warning("❓ Unknown profile type")
        return "unknown"
    except:
        return "unknown"


def extract_profile_name(driver, profile_type="user"):
    """Extract the name/title from user or company profile."""
    try:
        name = ""
        
        if profile_type == "user":
            # User profile name selectors (from most specific to most general)
            user_selectors = [
                "h1.text-heading-xlarge",
                ".pv-top-card h1",
                ".pv-top-card__name",
                ".pv-text-details__left-panel h1",
                "div.mt2.relative h1",
                "section.pv-top-card h1",
            ]
            
            for selector in user_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements and elements[0].text.strip():
                        name = elements[0].text.strip()
                        break
                except:
                    continue
            
            # XPath fallback for user
            if not name:
                try:
                    elements = driver.find_elements(By.XPATH, "//main//section[contains(@class, 'pv-top-card')]//h1")
                    if elements and elements[0].text.strip():
                        name = elements[0].text.strip()
                except:
                    pass
                    
        elif profile_type == "company":
            # Company profile name selectors (from most specific to most general)
            company_selectors = [
                "h1.org-top-card-summary__title",
                ".org-top-card h1",
                "h1[data-test-id='org-top-card-primary-content__title']",
                "section.org-top-card h1",
                "div.org-top-card-summary__title h1",
            ]
            
            for selector in company_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements and elements[0].text.strip():
                        name = elements[0].text.strip()
                        break
                except:
                    continue
            
            # XPath fallback for company
            if not name:
                try:
                    elements = driver.find_elements(By.XPATH, "//main//section[contains(@class, 'org-top-card')]//h1")
                    if elements and elements[0].text.strip():
                        name = elements[0].text.strip()
                except:
                    pass
        
        # Final fallback: any h1 in main area
        if not name:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, "main h1")
                for elem in elements:
                    text = elem.text.strip()
                    # Skip empty or very long names (likely not the profile name)
                    if text and len(text) < 200:
                        name = text
                        break
            except:
                pass
        
        if name:
            logger.info(f"📛 Name extracted: {name}")
        else:
            logger.warning("❌ Name not found")
            
        return name
        
    except Exception as e:
        logger.warning(f"Name extraction failed: {str(e)[:100]}")
        return ""


def scrape_contact_info(driver, profile_type="user"):
    """Scrape contact info. Combines Top Card (Buttons) + Modal (Hidden info)."""
    # 1. Always scrape Top Card (Buttons/Header) first
    final_data = extract_safe_zone_data(driver, source="top_card")
    
    # 2. If it's a User, try the Contact Modal
    if profile_type == "company":
        overflow_data = extract_company_overflow_links(driver)
        final_data["links"] = list(set(final_data["links"] + overflow_data.get("links", [])))
        return final_data

    if profile_type == "user":
        for attempt in range(2):
            try:
                contact_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.ID, "top-card-text-details-contact-info"))
                )
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", contact_btn)
                time.sleep(random_delay(0.5, 0.2))
                driver.execute_script("arguments[0].click();", contact_btn)
                time.sleep(1.5)
                
                # Scrape Modal
                modal_data = extract_safe_zone_data(driver, source="modal")
                
                # Merge Data
                final_data["emails"] = list(set(final_data["emails"] + modal_data["emails"]))
                final_data["mobiles"] = list(set(final_data["mobiles"] + modal_data["mobiles"]))
                final_data["links"] = list(set(final_data["links"] + modal_data["links"]))
                
                # Close Modal
                try:
                    dismiss_btn = driver.find_element(By.CLASS_NAME, "artdeco-modal__dismiss")
                    driver.execute_script("arguments[0].click();", dismiss_btn)
                except:
                    driver.execute_script("document.querySelector('.artdeco-modal__dismiss')?.click()")
                
                time.sleep(1)
                break
                
            except TimeoutException:
                logger.info("No contact info button found (private profile).")
                break
            except (ElementClickInterceptedException, StaleElementReferenceException):
                if attempt < 1:
                    time.sleep(random_delay(1, 0.2))
                    continue
                logger.warning("Modal interaction failed after retry (click intercepted)")
            except Exception as e:
                logger.warning(f"Modal interaction failed: {type(e).__name__}: {str(e)[:100]}")

    return final_data


def extract_bio_links(driver, profile_type="user"):
    """
    Extract custom profile buttons like 'View my portfolio', 'Resources', etc.
    Handles LinkedIn redirect URLs and returns only external URLs.
    Returns: List of URLs (strings only, no text).
    """
    bio_links = []
    
    if profile_type != "user":
        logger.info("⏭️ Skipping bio links for company profile")
        return bio_links
    
    try:
        # Scroll to top and wait for profile to fully load
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random_delay(2, 0.4))
        
        logger.info("🔍 Searching for custom profile buttons...")
        
        # Target ONLY the action buttons area (below headline, above "Open to work")
        # This is where "View my portfolio", "Resources" etc. appear
        link_selectors = [
            ".pv-top-card-v2-ctas a[href]",
            ".pvs-profile-actions a[href]",
            "div.pv-top-card--list-bullet a[href]",
            "div.pv-top-card__actions a[href]",
        ]

        button_selectors = [
            ".pv-top-card-v2-ctas__custom button",
            ".pvs-profile-actions__custom-action",
            ".pvs-profile-actions__custom-action-scaled",
            "button[data-view-name='premium-custom-button-on-profile-top-card']",
            ".pvs-profile-actions__custom button",
        ]

        link_elems = []
        for selector in link_selectors:
            try:
                link_elems.extend(driver.find_elements(By.CSS_SELECTOR, selector))
            except:
                continue

        button_elems = []
        for selector in button_selectors:
            try:
                button_elems.extend(driver.find_elements(By.CSS_SELECTOR, selector))
            except:
                continue

        logger.info(f"Found {len(link_elems)} potential bio links (anchors)")
        logger.info(f"Found {len(button_elems)} potential bio buttons")

        def is_internal_link(url: str) -> bool:
            internal_patterns = [
                "linkedin.com/in/",
                "linkedin.com/company/",
                "linkedin.com/school/",
                "linkedin.com/feed/",
                "linkedin.com/search/",
                "linkedin.com/premium/",
                "linkedin.com/mynetwork/",
                "linkedin.com/jobs/",
                "linkedin.com/messaging/",
                "linkedin.com/notifications/",
            ]
            return any(pattern in url.lower() for pattern in internal_patterns)

        def capture_url_from_button(btn):
            original_window = driver.current_window_handle
            original_url = driver.current_url
            existing_handles = set(driver.window_handles)

            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                time.sleep(random_delay(0.3, 0.2))
                driver.execute_script("arguments[0].click();", btn)
            except Exception:
                return None

            # Wait for new tab/window
            try:
                WebDriverWait(driver, 4).until(lambda d: len(d.window_handles) > len(existing_handles))
            except Exception:
                pass

            new_handles = list(set(driver.window_handles) - existing_handles)
            if new_handles:
                new_handle = new_handles[0]
                driver.switch_to.window(new_handle)
                time.sleep(random_delay(1.0, 0.2))
                new_url = driver.current_url
                actual_url = normalize_link(new_url)
                try:
                    driver.close()
                except Exception:
                    pass
                driver.switch_to.window(original_window)
                return actual_url

            # Same tab redirect
            try:
                WebDriverWait(driver, 4).until(EC.url_changes(original_url))
            except Exception:
                return None

            new_url = driver.current_url
            actual_url = normalize_link(new_url)
            try:
                driver.get(original_url)
                time.sleep(random_delay(0.6, 0.2))
            except Exception:
                pass
            return actual_url

        # Process each anchor link
        seen_urls = set()
        for elem in link_elems:
            try:
                # Check if element is visible
                if not elem.is_displayed():
                    continue
                
                href = elem.get_attribute("href")
                if not href:
                    continue
                
                text = elem.text.strip()
                logger.info(f"🔎 Button: '{text[:40]}' → {href[:60]}...")
                
                # Extract actual URL from LinkedIn redirect links
                actual_url = normalize_link(href)
                
                # Check if it's a redirect URL we couldn't extract
                if "/redir/redirect" in actual_url or "/redir-redirect" in actual_url:
                    # Try to extract url parameter
                    try:
                        from urllib.parse import parse_qs, urlparse
                        parsed = urlparse(actual_url)
                        params = parse_qs(parsed.query)
                        if 'url' in params and params['url']:
                            actual_url = params['url'][0]
                            logger.info(f"  🔓 Extracted redirect: {actual_url[:60]}...")
                    except:
                        pass
                
                if is_internal_link(actual_url):
                    logger.info(f"  ⏩ Skipped (internal LinkedIn)")
                    continue
                
                # Add to bio links if unique and external
                if actual_url not in seen_urls and actual_url not in bio_links:
                    bio_links.append(actual_url)
                    seen_urls.add(actual_url)
                    logger.info(f"✅ ADDED BIO LINK: {actual_url}")
                    
            except Exception as e:
                logger.warning(f"  ⚠️ Error processing button: {str(e)[:50]}")
                continue

        # Process custom buttons (no href)
        for btn in button_elems:
            try:
                if not btn.is_displayed():
                    continue

                btn_text = btn.text.strip()
                if btn_text.lower() in ["follow", "message", "connect", "more", "open to", "add profile section"]:
                    continue

                logger.info(f"🔎 Button (click): '{btn_text[:40]}'")
                actual_url = capture_url_from_button(btn)
                if not actual_url:
                    continue

                if is_internal_link(actual_url):
                    logger.info("  ⏩ Skipped (internal LinkedIn)")
                    continue

                if actual_url not in seen_urls and actual_url not in bio_links:
                    bio_links.append(actual_url)
                    seen_urls.add(actual_url)
                    logger.info(f"✅ ADDED BIO LINK (button): {actual_url}")
            except Exception as e:
                logger.warning(f"  ⚠️ Error processing custom button: {str(e)[:50]}")
                continue
        
        # Also check Resources dropdown button
        try:
            resources_btns = driver.find_elements(By.XPATH, 
                "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'resources')]"
            )
            
            if resources_btns and len(resources_btns) > 0:
                logger.info(f"Found Resources dropdown, clicking...")
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", resources_btns[0])
                time.sleep(random_delay(0.5, 0.2))
                driver.execute_script("arguments[0].click();", resources_btns[0])
                time.sleep(random_delay(1, 0.3))
                
                # Extract links from dropdown
                menu_links = driver.find_elements(By.CSS_SELECTOR, "div[role='menu'] a[href], ul[role='menu'] a[href]")
                logger.info(f"Found {len(menu_links)} links in Resources dropdown")
                
                for link_elem in menu_links:
                    try:
                        href = link_elem.get_attribute("href")
                        if not href:
                            continue
                        
                        actual_url = normalize_link(href)
                        
                        # Skip internal LinkedIn links
                        is_internal = any(pattern in actual_url.lower() for pattern in [
                            "linkedin.com/in/", "linkedin.com/company/", "linkedin.com/feed/",
                            "linkedin.com/search/", "linkedin.com/premium/"
                        ])
                        
                        if not is_internal and actual_url not in bio_links:
                            bio_links.append(actual_url)
                            logger.info(f"✅ ADDED BIO LINK (Resources): {actual_url}")
                    except:
                        continue
                
                # Close menu
                try:
                    driver.execute_script("document.querySelectorAll('[role=menu]').forEach(m => m.remove());")
                    time.sleep(0.3)
                except:
                    pass
        except Exception as e:
            logger.warning(f"Resources dropdown failed: {str(e)[:50]}")
        
        logger.info(f"📎 Extracted {len(bio_links)} external bio links")
        return bio_links
        
    except Exception as e:
        logger.warning(f"Bio links extraction failed: {type(e).__name__}: {str(e)[:100]}")
        return bio_links


def run_deep_scraper(callback_url: str = None):
    """Main scraper loop with comprehensive error handling."""
    print("🕵️‍♂️ Starting Deep Profile Scraper...")
    logger.info("Deep Scraper initialized")
    
    if callback_url:
        logger.info(f"📍 Callback URL registered: {callback_url}")
    
    ensure_temp_folder()
    col_raw_posts = get_raw_posts_collection()
    col_user_scrapped = get_user_scrapped_collection()
    col_final_table = get_final_table_collection()

    pending_tasks = list(col_final_table.find({"pipeline_status.3": 0}))
    logger.info(f"Found {len(pending_tasks)} profiles to visit")

    if not pending_tasks:
        logger.info("No pending profiles")
        return

    driver = get_driver()

    try:
        # Login window
        print("\n" + "="*70)
        print("⏳ PHASE 1: LinkedIn Login Check (30 seconds)")
        print("="*70)
        print("ACTION REQUIRED:")
        print("  1. If you see a login page, log in to LinkedIn now")
        print("  2. Once logged in, navigate to your feed or any LinkedIn page")
        print("  3. Wait for this timer to complete...")
        print("="*70 + "\n")
        
        driver.get("https://www.linkedin.com/feed/")
        logger.info("Opened LinkedIn feed for authentication check")
        
        # Wait 30 seconds for manual login
        for i in range(30, 0, -1):
            print(f"⏱️  Starting profile scraping in {i} seconds...", end='\r')
            time.sleep(1)
        
        print("\n\n🚀 PHASE 2: Starting Profile Scraping...\n")
        logger.info("Login phase complete, starting profile visits")

        success_count = 0
        for idx, task in enumerate(pending_tasks, 1):
            master_id = task.get("_id")
            raw_id = task.get("ref_raw_post")
            
            logger.info(f"\n--- Profile {idx}/{len(pending_tasks)} ---")
            
            try:
                raw_post = col_raw_posts.find_one({"_id": raw_id})
                if not raw_post:
                    logger.warning(f"Raw post not found for {raw_id}")
                    continue

                # Get Profile URL
                original_url = raw_post.get("author_profile_url") or raw_post.get("profile_url")
                if not original_url:
                    logger.warning("No profile URL found")
                    continue

                # 🧹 URL CLEANING LOGIC: Remove /posts, /about, /jobs, /people, /life suffixes
                # This turns "company/xyz/posts" -> "company/xyz"
                clean_url = re.sub(r'/(posts|about|jobs|people|life)/?(\?.*)?$', '', original_url)
                
                # Remove trailing slash if present
                if clean_url.endswith('/'):
                    clean_url = clean_url[:-1]

                logger.info(f"🚀 Visiting: {clean_url}")
                driver.get(clean_url)
                time.sleep(random_delay(PROFILE_LOAD_DELAY, 0.4))

                # Check if logged in
                if "login" in driver.current_url or "authwall" in driver.current_url:
                    logger.error("❌ LinkedIn session expired. Please restart and log in.")
                    break

                # Detect Type & Scrape
                p_type = detect_profile_type(driver)
                
                # 1) Extract name first (for both user and company)
                profile_name = extract_profile_name(driver, profile_type=p_type)
                time.sleep(random_delay(0.5, 0.2))
                
                c_about_text = ""

                if p_type == "company":
                    # 3) Company bio links first (top card + 3-dots)
                    bio_links = extract_company_bio_links(driver)
                    time.sleep(random_delay(0.6, 0.2))

                    # 4) About section next (full text + contacts)
                    about_data = extract_company_about(driver)
                    contact_data = {
                        "emails": about_data.get("emails", []),
                        "mobiles": about_data.get("mobiles", []),
                        "links": about_data.get("links", []),
                    }
                    c_about_text = about_data.get("about_text", "")
                    time.sleep(random_delay(0.8, 0.2))
                else:
                    # User: match company flow by extracting About section text + contacts
                    about_data = extract_user_about(driver)
                    contact_data = {
                        "emails": about_data.get("emails", []),
                        "mobiles": about_data.get("mobiles", []),
                        "links": about_data.get("links", []),
                    }
                    c_about_text = about_data.get("about_text", "")
                    time.sleep(random_delay(0.8, 0.2))

                    # Extract bio links (custom buttons like "View my portfolio")
                    bio_links = extract_bio_links(driver, profile_type=p_type)
                    time.sleep(random_delay(0.8, 0.2))

                # Save to DB
                user_doc = {
                    "linked_raw_post_id": raw_id,
                    "name": profile_name,
                    "profile_type": p_type,
                    "contact_email": contact_data.get("emails", []),
                    "contact_mobile": contact_data.get("mobiles", []),
                    "contact_links": contact_data.get("links", []),
                    "bio_links": bio_links,  # NEW: Custom profile buttons
                    "c_about_text": c_about_text,
                    "scraped_at": datetime.now(timezone.utc),
                }
                res = col_user_scrapped.insert_one(user_doc)

                # Update Tracker
                col_final_table.update_one(
                    {"_id": master_id},
                    {"$set": {"ref_user_scrapped": res.inserted_id, "pipeline_status.3": 1}}
                )
                
                success_count += 1
                logger.info(f"✅ Profile {idx} complete. Links: {len(contact_data.get('links', []))}")
                
                if idx < len(pending_tasks):
                    delay = random_delay(RATE_LIMIT_DELAY, 0.4)
                    logger.info(f"Rate limiting: waiting {delay:.1f}s...")
                    time.sleep(delay)

            except Exception as e:
                logger.error(f"Failed profile {idx}: {str(e)[:100]}", exc_info=False)
                try:
                    col_final_table.update_one(
                        {"_id": master_id},
                        {"$set": {"pipeline_status.3": 2, "error": str(e)}}
                    )
                except:
                    pass
                time.sleep(5)
                continue

        logger.info(f"\n=== Scraper Complete ===")
        logger.info(f"Processed: {idx}/{len(pending_tasks)}")
        logger.info(f"Success: {success_count}/{len(pending_tasks)}")
        
        # Send callback to n8n
        if callback_url:
            logger.info(f"📞 Calling back n8n at: {callback_url}")
            try:
                response = requests.post(
                    callback_url,
                    json={"status": "success", "message": "Deep Scraper Done", "processed": success_count, "total": len(pending_tasks)},
                    timeout=15
                )
                logger.info(f"✅ Callback sent successfully. Status: {response.status_code}")
            except Exception as e:
                logger.error(f"❌ Callback failed: {e}")

    except Exception as critical_exc:
        logger.critical(f"Critical scraper error: {critical_exc}", exc_info=True)
        
        # Send error callback to n8n
        if callback_url:
            try:
                requests.post(
                    callback_url,
                    json={"status": "error", "error": str(critical_exc)},
                    timeout=15
                )
            except Exception as callback_exc:
                logger.error(f"❌ CRITICAL: Could not send error callback: {callback_exc}")
    finally:
        try:
            driver.quit()
            logger.info("WebDriver closed")
        except:
            pass


if __name__ == "__main__":
    run_deep_scraper()

