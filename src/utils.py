import re

def clean_post_text(text):
    """Removes extra whitespace and newlines from LinkedIn posts."""
    if not text:
        return ""
    # Remove excessive newlines
    text = re.sub(r'\n+', '\n', text).strip()
    return text

def is_duplicate(collection, profile_url):
    """Checks if we've already scraped this person."""
    return collection.find_one({"profile_url": profile_url}) is not None