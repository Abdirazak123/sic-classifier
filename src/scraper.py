"""
scraper.py
----------
Fetches a company's homepage and reduces it to plain, readable text.

Real-world messiness this has to cope with, because the source list is
Companies House-style data rather than a curated list:
  * URLs stored without a scheme (e.g. "AJCHOMES.CO.UK")
  * URLs that redirect, are dead, or now point somewhere unrelated
  * Sites that block simple bots (Cloudflare/JS challenges) - these are
    reported rather than silently skipped, so a human can follow up
  * Pages that are mostly nav/cookie-banner/script noise
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

from . import config


@dataclass
class ScrapeResult:
    company_name: str
    input_url: str
    resolved_url: Optional[str] = None
    success: bool = False
    text: str = ""
    status_code: Optional[int] = None
    error: Optional[str] = None


def _normalise_url(raw_url: str) -> str:
    """Companies House-style exports rarely include a scheme. Default to
    https and let requests follow any redirect down to http if needed."""
    url = raw_url.strip()
    if not url:
        return url
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _clean_html_to_text(html: str) -> str:
    """Strip script/style/nav noise and collapse whitespace so the LLM
    sees the same kind of text a human skimming the page would see."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()

    # Title and meta description are often the single highest-signal
    # fields on a homepage (e.g. "Bespoke Timber Cladding Suppliers")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
    meta_desc = meta_desc_tag.get("content", "").strip() if meta_desc_tag else ""

    body_text = soup.get_text(separator=" ")
    body_text = " ".join(body_text.split())  # collapse whitespace/newlines

    parts = [p for p in (f"TITLE: {title}", f"META DESCRIPTION: {meta_desc}", body_text) if p.strip() not in ("TITLE:", "META DESCRIPTION:", "")]
    combined = "\n".join(parts)
    return combined[: config.MAX_TEXT_CHARS]


def scrape_homepage(company_name: str, raw_url: str) -> ScrapeResult:
    """Fetch one company's homepage. Never raises - failures are captured
    in the returned ScrapeResult so a bad URL can't kill the batch run."""
    result = ScrapeResult(company_name=company_name, input_url=raw_url)

    url = _normalise_url(raw_url)
    if not url:
        result.error = "empty_url"
        return result

    headers = {"User-Agent": config.USER_AGENT, "Accept-Language": "en-GB,en;q=0.9"}
    last_error = None

    for attempt in range(config.MAX_RETRIES + 1):
        try:
            resp = requests.get(
                url,
                headers=headers,
                timeout=config.REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            result.status_code = resp.status_code
            result.resolved_url = resp.url

            if resp.status_code >= 400:
                last_error = f"http_{resp.status_code}"
                # Don't bother retrying a clean 404/403 - it won't change.
                if resp.status_code in (404, 410):
                    break
                time.sleep(config.RETRY_BACKOFF_SECONDS)
                continue

            content_type = resp.headers.get("Content-Type", "")
            if "html" not in content_type and resp.text.strip()[:15].lstrip().lower() != "<!doctype html":
                last_error = f"non_html_content_type:{content_type or 'unknown'}"
                break

            text = _clean_html_to_text(resp.text)
            if not text:
                last_error = "empty_after_cleaning"
                break

            result.success = True
            result.text = text
            result.error = None
            return result

        except requests.exceptions.SSLError as exc:
            last_error = f"ssl_error:{exc}"
            # retry once over plain http as a fallback
            url = url.replace("https://", "http://", 1)
        except requests.exceptions.Timeout:
            last_error = "timeout"
        except requests.exceptions.ConnectionError as exc:
            last_error = f"connection_error:{type(exc).__name__}"
        except requests.exceptions.RequestException as exc:
            last_error = f"request_error:{type(exc).__name__}"

        time.sleep(config.RETRY_BACKOFF_SECONDS)

    result.error = last_error or "unknown_error"
    return result
