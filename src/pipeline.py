"""
pipeline.py
-----------
Entry point. Reads the supplied companies CSV, scrapes each homepage,
sends the result to Claude for SIC re-classification, and writes a
single output.json containing one record per company.

Usage:
    python -m src.pipeline
    python -m src.pipeline --input companies.csv --output output/output.json --limit 5
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone

from . import config
from .scraper import scrape_homepage
from .classifier import classify_company, make_client


def load_companies(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8-sig") as f:  # utf-8-sig: input has a BOM
        reader = csv.DictReader(f)
        return list(reader)


def process_company(client, row: dict) -> dict:
    name = row["name"].strip()
    website = row["website"].strip()
    current_sic = row.get("SIC", "").strip()
    current_desc = row.get("Desc.", "").strip()

    print(f"  -> scraping {website} ...", file=sys.stderr)
    scrape = scrape_homepage(name, website)

    record = {
        "company_name": name,
        "website": website,
        "current_sic": current_sic,
        "current_sic_description": current_desc,
        "inferred_sic": None,
        "evidence": None,
        # extra fields beyond the minimum spec - see README "Additional fields"
        "confidence": None,
        "company_summary": None,
        "scrape_status": "success" if scrape.success else "failed",
        "resolved_url": scrape.resolved_url,
    }

    if not scrape.success:
        record["evidence"] = f"Could not scrape homepage ({scrape.error})."
        return record

    print("     scraped ok, classifying with Claude ...", file=sys.stderr)
    classification = classify_company(client, name, f"{current_sic} {current_desc}".strip(), scrape.text)

    if classification.error:
        record["evidence"] = f"Scrape succeeded but classification failed ({classification.error})."
        return record

    record["inferred_sic"] = classification.inferred_sic_code
    record["evidence"] = classification.evidence
    record["confidence"] = classification.confidence
    record["company_summary"] = classification.company_summary
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="Infer accurate SIC codes from company homepages.")
    parser.add_argument("--input", default=config.INPUT_CSV)
    parser.add_argument("--output", default=config.OUTPUT_JSON)
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N rows (useful for testing).")
    args = parser.parse_args()

    try:
        client = make_client()
    except RuntimeError as exc:
        sys.exit(str(exc))

    companies = load_companies(args.input)
    if args.limit:
        companies = companies[: args.limit]

    results = []
    for i, row in enumerate(companies, start=1):
        print(f"[{i}/{len(companies)}] {row['name']}", file=sys.stderr)
        results.append(process_company(client, row))

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": args.input,
        "model_used": config.GEMINI_MODEL if config.LLM_PROVIDER == "gemini" else config.CLAUDE_MODEL,
        "total_companies": len(results),
        "successful_scrapes": sum(1 for r in results if r["scrape_status"] == "success"),
        "results": results,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nDone. Wrote {len(results)} records to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
