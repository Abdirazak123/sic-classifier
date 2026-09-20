"""
Central configuration for the SIC classification pipeline.

Kept deliberately small and explicit rather than pulling in a config
framework - there are only a handful of knobs that actually matter here.
"""

import os

# --- LLM provider -------------------------------------------------------
# "anthropic" (Claude, requires a paid/trial API key) or
# "gemini" (Google Gemini, has a genuinely free API tier - no card needed,
# see https://aistudio.google.com). Defaults to gemini so this runs
# without any billing setup out of the box.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

# --- Scraping ----------------------------------------------------------------
REQUEST_TIMEOUT = 10          # seconds per HTTP request
MAX_RETRIES = 2               # retries per URL before giving up
RETRY_BACKOFF_SECONDS = 1.5
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 SICClassifierBot/1.0"
)

# Cap how much homepage text we feed the LLM. Homepages rarely need more
# than this to reveal what a company does, and it keeps token cost down.
MAX_TEXT_CHARS = 6000

# --- Rate limiting -------------------------------------------------------
# Small pause between LLM calls so a batch run doesn't hammer the API.
SECONDS_BETWEEN_LLM_CALLS = 0.5

# --- Paths -----------------------------------------------------------------
INPUT_CSV = "companies.csv"
OUTPUT_JSON = "output/output.json"
