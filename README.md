# SIC Code Inference from Company Homepages

A small pipeline that scrapes a company's homepage and uses Claude to infer a
more accurate UK SIC (Standard Industrial Classification) code than whatever
generic or outdated code is currently on file — built for the Creditsafe
take-home exercise.

## The problem, briefly

Companies self-declare a SIC code on formation and rarely update it. A lot of
UK companies end up stuck under a catch-all code like `96090 - Other service
activities n.e.c.`, which tells you nothing about what the business actually
does. This project scrapes each company's homepage, extracts the readable
text, and asks an LLM to infer a better-fitting code from the evidence on the
page — the same way a human analyst would skim the site and make a judgement
call, just automated and at scale.

## Approach

1. **Scrape** (`src/scraper.py`) — fetch the homepage with `requests`, follow
   redirects, and pull out the page `<title>`, meta description, and visible
   body text with BeautifulSoup (scripts/styles/nav noise stripped out).
   Failures (dead domain, timeout, blocked bot, non-HTML response) are
   caught and recorded rather than crashing the batch.
2. **Classify** (`src/classifier.py`) — send the company name, its current
   SIC code, and the cleaned homepage text to Claude with a system prompt
   that asks it to (a) infer the SIC 2007 code that best matches what the
   business *currently* does, (b) quote the specific evidence for that
   choice, and (c) say "I can't tell" (`null`) rather than guess when the
   page genuinely doesn't support a confident answer.
3. **Orchestrate** (`src/pipeline.py`) — reads `companies.csv`, runs steps 1–2
   for every row, and writes one combined `output/output.json`.

I went with an LLM rather than a keyword/rules classifier because the whole
point of the exercise is that the *existing* classification is too generic —
a keyword list runs into the same problem, since most homepages don't
literally contain SIC terminology. An LLM can read a page the way a human
would (tagline, "about us" copy, product descriptions) and reason about the
underlying business, while I keep it honest by forcing it to cite evidence
and to abstain when the page doesn't support a real answer.

## Output format

`output/output.json` contains one object per company:

```json
{
  "company_name": "...",
  "website": "...",
  "current_sic": "96090",
  "current_sic_description": "Other service activities n.e.c.",
  "inferred_sic": "41202 - Construction of domestic buildings",
  "evidence": "...",
  "confidence": "high | medium | low",
  "company_summary": "one-line summary of what the company does",
  "scrape_status": "success | failed",
  "resolved_url": "the URL actually fetched, after redirects"
}
```

The brief asked for company name, current SIC, inferred SIC and supporting
evidence. I added:
- `confidence` — flags borderline calls for human review rather than hiding
  them behind a single "best guess".
- `company_summary` — a one-line plain-English gloss, useful for a human
  reviewer sanity-checking the result quickly without re-reading the page.
- `scrape_status` / `resolved_url` — makes scrape failures visible and
  debuggable instead of silently producing a blank/wrong classification.

See `output/sample_output.json` for two hand-checked example records
(one housebuilder, one cycling-apparel brand) showing what a correct result
looks like end to end, and `output/output.json` (once you run the pipeline)
for the full 10-company run — including the two scrape-failure modes above
(dead domain vs. bot-blocked) reported honestly rather than papered over.

## Assumptions & limitations

- Only the **homepage** is scraped, per the brief. For companies whose
  homepage is mostly a splash page (e.g. "enter site"), a deeper crawl of
  `/about` or `/products` would likely improve accuracy — noted as a next
  step below rather than built, to keep the solution to what was asked.
- Some of the supplied URLs are stale, redirect elsewhere, or actively block
  simple bots (Cloudflare challenge pages, etc.). These are reported in
  `scrape_status`/`evidence` rather than causing the run to fail. On a live
  run against the 10 supplied companies, 6/10 homepages were reachable. The
  other 4 failed for two distinct reasons worth distinguishing: three
  returned a connection error (the domain didn't resolve or refused the
  connection — likely stale/dead URLs in the source data), while one
  returned an HTTP 403 (the site's bot protection actively blocked the
  request, rather than the domain being unreachable). Telling these apart
  matters — one is "the lead is probably dead", the other is "worth a
  retry or a different scraping approach".
- The classifier retries once on transient provider errors (e.g. a
  `503 UNAVAILABLE` from an overloaded free-tier endpoint) before giving
  up, since these clear up on their own — added after a live run showed
  two otherwise-successful scrapes failing only at the classification step
  for this reason.
- The classifier is asked to return a real SIC 2007 code from its own
  knowledge rather than being given the full ~700-code SIC list in the
  prompt. This keeps the prompt small, but means it's worth spot-checking
  outputs against the [official ONS SIC 2007 list](https://onsdigital.github.io/dp-classification-tools/standard-industrial-classification/ONS_SIC_hierarchy_view.html)
  for a production version.
- No paid tools/APIs are used. The classifier defaults to the **Gemini API**
  (`gemini-2.0-flash`), which has a genuinely free tier at
  [aistudio.google.com](https://aistudio.google.com) — no card required.
  Claude is supported as a drop-in alternative (`LLM_PROVIDER=anthropic` in
  `.env`) for anyone who already has API credit, since the brief mentions
  either is fine.

## If I had more time

- Fall back to crawling 1–2 internal links (About/Services) when the
  homepage alone is too thin to classify confidently.
- Batch multiple companies into a single Claude call to cut latency/cost
  on larger runs.
- Cross-check the inferred code against the official ONS SIC list
  programmatically, rather than trusting the model's recall of exact codes.
- Add basic retry/backoff tuned to specific hosting providers (a few sites
  in the sample data return soft-block responses rather than clean errors).

## Tools used

Python 3, `requests`, `beautifulsoup4`, and the Gemini API (Google) for the
classification step, with Claude (Anthropic) supported as a drop-in
alternative — see `src/classifier.py`. I used Claude throughout while
building this — for structuring the pipeline, writing the prompt, and
reviewing the code — which the brief explicitly welcomed. All of the design
decisions and trade-offs above are mine; the AI was the assistant, not the
author.

## How to run

```bash
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt

cp .env.example .env
# Edit .env and add a free Gemini key from https://aistudio.google.com
# (Get API key -> Create API key - no card needed). Leave LLM_PROVIDER=gemini.
export $(grep -v '^#' .env | xargs)

python -m src.pipeline                      # runs all companies in companies.csv
python -m src.pipeline --limit 3            # quick test on the first 3 rows
python -m src.pipeline --input other.csv --output output/other.json
```

To use Claude instead, set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`
in `.env` — no code changes needed.

Output is written to `output/output.json`. Progress/logging goes to stderr
so it doesn't interfere with anything reading stdout.

## Project structure

```
.
├── companies.csv           # supplied input data
├── requirements.txt
├── .env.example
├── src/
│   ├── config.py           # timeouts, model name, file paths
│   ├── scraper.py           # homepage fetch + HTML → text cleaning
│   ├── classifier.py        # Claude prompt + call + response parsing
│   └── pipeline.py          # CLI entry point, ties it all together
└── output/
    ├── output.json          # generated by running the pipeline
    └── sample_output.json   # hand-checked example (see above)
```
