"""
Small, fast unit tests for the parts of scraper.py that don't need network
access. Run with: python -m pytest tests/ -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.scraper import _normalise_url, _clean_html_to_text


def test_normalise_url_adds_scheme():
    assert _normalise_url("AJCHOMES.CO.UK") == "https://AJCHOMES.CO.UK"


def test_normalise_url_keeps_existing_scheme():
    assert _normalise_url("http://example.com") == "http://example.com"


def test_normalise_url_strips_whitespace():
    assert _normalise_url("  example.com  ") == "https://example.com"


def test_normalise_url_handles_empty_string():
    assert _normalise_url("") == ""


def test_clean_html_to_text_strips_scripts_and_styles():
    html = """
    <html><head><title>Acme Ltd</title>
    <style>body{color:red}</style></head>
    <body>
      <script>trackUser();</script>
      <h1>Welcome to Acme</h1>
      <p>We manufacture bespoke furniture.</p>
    </body></html>
    """
    text = _clean_html_to_text(html)
    assert "trackUser" not in text
    assert "color:red" not in text
    assert "Acme" in text
    assert "bespoke furniture" in text


def test_clean_html_to_text_picks_up_meta_description():
    html = """
    <html><head><title>Acme</title>
    <meta name="description" content="Bespoke furniture makers since 1990"></head>
    <body><p>Hello</p></body></html>
    """
    text = _clean_html_to_text(html)
    assert "Bespoke furniture makers since 1990" in text


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok: {name}")
    print("All tests passed.")
