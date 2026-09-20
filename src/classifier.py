"""
classifier.py
-------------
Sends a company's homepage text to Claude and asks it to infer a more
accurate UK SIC 2007 code than whatever generic/outdated code is on
file (e.g. 96090 "Other service activities n.e.c.").

Why an LLM rather than keyword-matching against the SIC list:
the whole point of the task is that the *current* classification is too
generic to be useful, and a rules/keyword approach tends to just recreate
that problem (most homepages don't literally say "manufacture of X").
An LLM can read the page the way a human analyst would - tagline, product
photos captions, "about us" copy - and reason about what the business
actually does, while still being constrained to return a valid SIC code
and to quote its evidence so the output is auditable.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

import anthropic

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


def classify_company(
    client: "anthropic.Anthropic",
    company_name: str,
    current_sic: str,
    scraped_text: str,
) -> ClassificationResult:
    if not scraped_text:
        return ClassificationResult(error="no_text_to_classify")

    try:
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": _build_user_prompt(company_name, current_sic, scraped_text),
                }
            ],
        )
        raw_text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()

        # Claude is asked for bare JSON, but strip fences defensively in
        # case a model response wraps it in ```json anyway.
        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`")
            raw_text = raw_text[4:] if raw_text.lower().startswith("json") else raw_text

        parsed = json.loads(raw_text)
        return ClassificationResult(
            inferred_sic_code=parsed.get("inferred_sic_code"),
            confidence=parsed.get("confidence"),
            evidence=parsed.get("evidence"),
            company_summary=parsed.get("company_summary"),
        )

    except json.JSONDecodeError as exc:
        return ClassificationResult(error=f"unparseable_llm_response:{exc}")
    except anthropic.APIError as exc:
        return ClassificationResult(error=f"anthropic_api_error:{exc}")
    finally:
        time.sleep(config.SECONDS_BETWEEN_LLM_CALLS)
