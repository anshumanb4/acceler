import re
import requests
from bs4 import BeautifulSoup
from config import MAX_CONTENT_LENGTH

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}


def _annotate_links(soup: BeautifulSoup) -> None:
    """Inline LinkedIn URLs and mailto hrefs into visible text (mirrors content.js)."""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href or href.startswith("#") or href.startswith("javascript"):
            continue
        if "linkedin.com" in href or href.startswith("mailto:"):
            link_text = a.get_text(strip=True)
            a.string = f"{link_text} [{href}]"


def _extract_text(html: str) -> tuple[str, str]:
    """Return (text, title) from raw HTML."""
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.string.strip() if soup.title and soup.title.string else ""

    # Remove script/style noise
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    _annotate_links(soup)
    text = soup.get_text(separator="\n", strip=True)

    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text, title


def _try_requests(url: str) -> tuple[str, str] | None:
    """Simple HTTP fetch. Returns (text, title) or None if text is too short."""
    resp = requests.get(url, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    text, title = _extract_text(resp.text)
    if len(text) < 200:
        return None
    return text, title


def _try_playwright(url: str) -> tuple[str, str]:
    """Headless browser fetch for JS-heavy sites."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        html = page.content()
        browser.close()

    text, title = _extract_text(html)
    return text, title


def fetch_page(url: str) -> tuple[str, str]:
    """Fetch a page and return (text, title). Tries simple HTTP first, falls back to Playwright."""
    result = _try_requests(url)
    if result is None:
        print(f"  Simple fetch returned < 200 chars, falling back to Playwright...")
        result = _try_playwright(url)

    text, title = result

    # Truncate to match extension behavior
    if len(text) > MAX_CONTENT_LENGTH:
        text = text[:MAX_CONTENT_LENGTH] + "\n[...truncated]"

    return text, title
