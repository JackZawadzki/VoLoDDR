# VoLo Earth Ventures — Due Diligence Report Generator

**Live app:** https://voloddr-htl47azjxmacv3i8zn4swz.streamlit.app

---

## What It Does

Upload any startup pitch deck (PDF) and receive a single downloadable PDF containing:
- A full **IC-ready due diligence report** with verified claims, risk scoring, and investment recommendation
- **Three analysis charts** with web-researched market data

Total runtime: ~3–5 minutes per deck.

---

## Architecture

The app is built in Python using Streamlit for the web interface and Anthropic's Claude API for all AI work. There are three core files:

### `ddr_app.py` — Web Interface & Pipeline Orchestrator
The Streamlit front-end. Handles file upload, runs the five-step pipeline in sequence, and serves the final merged PDF download. Stores results in `st.session_state` so the download button survives page reruns. Both output PDFs (report + charts) are merged into one file using `pypdf`.

### `DDR(draft 11).py` — Core Analysis Engine
Contains the `DueDiligenceAnalyzer` class which:
- Extracts text from the uploaded PDF
- Sends it to **Claude Opus** with a detailed IC-ready prompt
- Gets back structured JSON covering: company overview, financial/legal status, technology assessment, market analysis, competitive landscape, risk scores, and investment recommendation
- Labels every data point as *"COMPANY CLAIM (Unverified)"* or *"VERIFIED: [Source]"*
- Adds confidence star ratings based on source quality, quantity, and recency
- Renders everything into a formatted multi-page PDF using ReportLab

### `ddr_graphs.py` — Chart Generation Module
Runs a separate **Claude Sonnet** call with live web search to produce three matplotlib charts:
1. **Revenue Trajectory** — Company projections (dashed) vs. real established peers (verified revenues sourced live)
2. **TAM & SAM Growth** — Global addressable market over time, sourced from BloombergNEF, IEA, Grand View Research etc.
3. **Monte Carlo Simulation** — 50,000-run probabilistic 2035 revenue forecast with P10/P50/P90 overlays

All charts include an *"AI Estimates — Illustrative Only · Verify before use"* watermark.

---

## Pipeline Flow

```
Upload PDF
    │
    ▼
[Step 1] Extract text from PDF                         ~5 sec
    │
    ▼
[Step 2] Claude Opus — Deep IC analysis               ~2–4 min
         Web searches, claim verification,
         risk scoring, investment recommendation
    │
    ▼
[Step 3] Add confidence scores                         ~2 sec
    │
    ▼
[Step 4] Generate DDR PDF (ReportLab)                 ~5 sec
    │
    ▼
[Step 5] Claude Sonnet — Chart data extraction        ~30–60 sec
         Live web search for peer revenues,
         market size, and growth benchmarks
    │
    ▼
Merge DDR PDF + Charts PDF → Single download
```

---

## Models Used & Why

| Step | Model | Why |
|------|-------|-----|
| DDR Analysis | `claude-opus-4-6` | Nuanced IC-level reasoning, ambiguous judgment calls, deep claim verification |
| Graph Extraction | `claude-sonnet-4-5` | Structured data extraction + web search — fast enough, and has higher rate limits than Opus |

Opus and Sonnet share the same token-per-minute pool. Using Sonnet for graphs avoids hitting the rate limit immediately after the large Opus analysis call.

---

## Key Design Decisions

- **Session state for downloads** — Streamlit reruns the entire page on every button click. Storing results in `st.session_state` keeps the download button alive after it's clicked.
- **Single merged PDF** — Both outputs (report + charts) are merged into one file so users download everything in one click.
- **Agentic web search loop** — Graph extraction runs in a `while True` loop, feeding tool results back to Claude until it stops calling tools, then parses the final JSON response.
- **Robust JSON parsing** — Claude's responses sometimes include markdown fences or prose. The parser strips fences, extracts just the JSON object, and falls back to ASCII-only parsing if special characters cause issues.
- **Per-chart fallback** — If any individual chart fails to render, it shows a blank placeholder with the error message instead of crashing the whole app.

---

## Future Improvements

### Speed
- **Parallel execution** — Steps 4 (PDF generation) and 5 (chart extraction) are independent once scoring is done. Running them with Python `threading` or `concurrent.futures` would save ~30–60 seconds with zero quality change.
- **Cap web search rounds** — The graph extraction loop has no hard limit on searches. Capping at 4 rounds would shorten tail-case runtimes without meaningfully reducing accuracy.
- **Reduce graph `max_tokens`** — Currently 8,000 for the Sonnet call. Dropping to 4,000 would speed up the response with no quality loss for structured JSON output.
- **Stream progress token-by-token** — The Opus call already uses streaming internally. Surfacing this in the UI would make the wait feel shorter even if total time is unchanged.

### Quality
- **Structured Outputs / JSON schema enforcement** — Anthropic supports passing a strict JSON schema to the API. This would eliminate all JSON parsing errors and remove the need for the fallback parsing logic.
- **Persistent memory across decks** — Store past analyses so the app can compare a new deck against previously analyzed companies in the same sector, flagging unusual claims automatically.
- **Human-in-the-loop verification** — Surface the lowest-confidence claims for a quick manual review step before the final PDF is generated.
- **Source hyperlinking** — Embed clickable links to the actual sources cited in the report so IC readers can verify directly.
- **Richer Monte Carlo inputs** — Currently uses log-normal distribution calibrated by Claude. Could be improved with sector-specific historical startup outcome data.

### Product
- **User accounts & report history** — Save past reports tied to a login so the team can retrieve and compare analyses over time.
- **Slack / email delivery** — Automatically send the finished PDF to a Slack channel or email address when analysis completes, so the user doesn't have to wait on the page.
- **Batch processing** — Accept a folder of decks and process them sequentially overnight, delivering all reports the next morning.
- **Editable outputs** — Let users annotate or override AI findings (e.g. change a risk score, add a note) before the final PDF is generated.
- **Sector-specific prompts** — Swap in different analysis prompts for cleantech vs. SaaS vs. biotech, tuning the IC criteria to what matters in each sector.

---

*Built by Jack Zawadzki · Powered by Claude AI · VoLo Earth Ventures*
