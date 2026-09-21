"""
classifier.py
-------------
Sends a company's homepage text to an LLM and asks it to infer a more
accurate UK SIC 2007 code than whatever generic/outdated code is on
file (e.g. 96090 "Other service activities n.e.c.").

Supports two providers, switched via LLM_PROVIDER in config.py:
  - "gemini"    (default) - Google Gemini, has a free API tier with no
                 card required: https://aistudio.google.com
  - "anthropic" - Claude, needs a paid/trial Anthropic API key

Why an LLM rather than keyword-matching against the SIC list:
the whole point of the task is that the *current* classification is too
generic to be useful, and a rules/keyword approach tends to just recreate
that problem (most homepages don't literally say "manufacture of X").
An LLM can read the page the way a human analyst would - tagline, product
photo captions, "about us" copy - and reason about what the business
actually does, while still being constrained to return a valid SIC code
and to quote its evidence so the output is auditable.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

from . import config

SYSTEM_PROMPT = """You are assisting a business-data company (Creditsafe) with cleaning up \
low-quality UK SIC (Standard Industrial Classification 2007) codes.

You will be given a company's name, its current SIC code/description, and text \
scraped from its homepage. Many companies are stuck with a generic code such as \
"96090 - Other service activities n.e.c." that was assigned on formation and never \
updated, or a legacy code that no longer reflects the business.

Your job: infer the SIC 2007 code that most accurately reflects what the company \
actually does TODAY, based only on the evidence in the scraped text.

Rules:
- Use real UK SIC 2007 codes and their official descriptions (5 digits, e.g. "43210 - Electrical installation").
- If the scraped text gives clear evidence of a specific activity, prefer a specific, narrow code over a vague one.
- If the scraped text is empty, unrelated to a business (e.g. a parked-domain or "site under construction" page), \
  or genuinely too vague to support a specific code, say so honestly rather than guessing - set \
  "inferred_sic_code" to null and explain why in "evidence".
- "evidence" must directly quote or closely paraphrase the specific words in the scraped text that justify \
  your answer - not a generic restatement of the SIC description.
- Respond with ONLY a single JSON object, no markdown fences, no commentary, matching exactly this schema:

{
  "inferred_sic_code": "43210 - Electrical installation" or null,
  "confidence": "high" | "medium" | "low",
  "evidence": "short quote/paraphrase from the scraped text supporting the code, or reason none could be inferred",
  "company_summary": "one sentence describing what the company appears to do"
}
"""


@dataclass
class ClassificationResult:
    inferred_sic_code: Optional[str] = None
    confidence: Optional[str] = None
    evidence: Optional[str] = None
    company_summary: Optional[str] = None
    error: Optional[str] = None


def _build_user_prompt(company_name: str, current_sic: str, scraped_text: str) -> str:
    return (
        f"Company name: {company_name}\n"
        f"Current SIC on file: {current_sic}\n\n"
        f"Scraped homepage text:\n\"\"\"\n{scraped_text}\n\"\"\"\n"
    )


def _extract_json(raw_text: str) -> dict:
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        raw_text = raw_text[4:] if raw_text.lower().startswith("json") else raw_text
    return json.loads(raw_text.strip())


def make_client():
    """Build whichever provider client is configured. Called once and
    reused across all companies in a run."""
    if config.LLM_PROVIDER == "gemini":
        if not config.GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Get a free key at https://aistudio.google.com "
                "(Get API key -> Create API key), no card required."
            )
        from google import genai
        return genai.Client(api_key=config.GEMINI_API_KEY)

    elif config.LLM_PROVIDER == "anthropic":
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        import anthropic
        return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    raise RuntimeError(f"Unknown LLM_PROVIDER: {config.LLM_PROVIDER!r} (expected 'gemini' or 'anthropic')")


def _classify_with_gemini(client, user_prompt: str) -> str:
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=user_prompt,
        config={
            "system_instruction": SYSTEM_PROMPT,
            "response_mime_type": "application/json",
        },
    )
    return response.text


def _classify_with_anthropic(client, user_prompt: str) -> str:
    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")


def classify_company(
    client,
    company_name: str,
    current_sic: str,
    scraped_text: str,
) -> ClassificationResult:
    if not scraped_text:
        return ClassificationResult(error="no_text_to_classify")

    user_prompt = _build_user_prompt(company_name, current_sic, scraped_text)

    # Free-tier LLM endpoints occasionally return a transient "overloaded"
    # error (e.g. Gemini 503 UNAVAILABLE) that clears up on retry - worth
    # a couple of attempts before giving up on an otherwise-good scrape.
    last_error = None
    for attempt in range(config.MAX_LLM_RETRIES + 1):
        try:
            if config.LLM_PROVIDER == "gemini":
                raw_text = _classify_with_gemini(client, user_prompt)
            else:
                raw_text = _classify_with_anthropic(client, user_prompt)

            parsed = _extract_json(raw_text)
            return ClassificationResult(
                inferred_sic_code=parsed.get("inferred_sic_code"),
                confidence=parsed.get("confidence"),
                evidence=parsed.get("evidence"),
                company_summary=parsed.get("company_summary"),
            )

        except json.JSONDecodeError as exc:
            last_error = f"unparseable_llm_response:{exc}"
            break  # retrying won't fix malformed output
        except Exception as exc:  # provider SDKs raise their own error types
            last_error = f"llm_call_failed:{type(exc).__name__}:{exc}"
            is_transient = "503" in str(exc) or "UNAVAILABLE" in str(exc) or "overloaded" in str(exc).lower()
            if not is_transient or attempt == config.MAX_LLM_RETRIES:
                break
            time.sleep(config.LLM_RETRY_BACKOFF_SECONDS * (attempt + 1))
        finally:
            time.sleep(config.SECONDS_BETWEEN_LLM_CALLS)

    return ClassificationResult(error=last_error)
