"""
ddr_engine.py
=============
AI analysis engine for the VoLo DDR (Due Diligence Report) tool.

Handles:
  - PDF text extraction
  - Agentic Claude Opus + web_search analysis
  - JSON parsing with recovery
  - AI self-assessed confidence display enrichment
  - Graph data fallback extraction (graph1 + graph2)
  - Dedicated technology benchmark research (graph3)

All Opus API calls go through one shared _agentic_call() function.
"""

import os
import json
import re
import time
from typing import Dict  # noqa: F401 — kept for potential future use

from pypdf import PdfReader
from anthropic import Anthropic, RateLimitError

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Constants ────────────────────────────────────────────────────────────────

MODEL = "claude-opus-4-6"

WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
}


# ── PDF Extraction ───────────────────────────────────────────────────────────

def extract_pdf(path: str) -> str:
    """Extract text from a PDF file using pypdf."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"PDF not found: {path}")
    text = ""
    reader = PdfReader(path)
    for i, page in enumerate(reader.pages, 1):
        text += page.extract_text() + "\n\n"
        if i % 5 == 0:
            print(f"   Processed {i}/{len(reader.pages)} pages")
    print(f"   Extracted {len(text):,} characters")
    if len(text) > 60000:
        print(f"   Deck is large — analysis will use the first ~60,000 characters")
    return text


# ── Shared Agentic Loop ─────────────────────────────────────────────────────

def _agentic_call(client: Anthropic, prompt: str,
                  max_tokens: int = 20000, temperature: float = 0.2,
                  on_progress=None) -> str:
    """
    Run a single agentic Opus + web_search call.

    Loops until stop_reason == "end_turn" or no tool calls remain.
    Returns the final text block from the model.

    on_progress: optional callback(search_count: int) for UI updates.
    """
    messages = [{"role": "user", "content": prompt}]
    final_text = ""

    while True:
        # Retry on rate limit — wait silently and try again (up to 5 times)
        for attempt in range(5):
            try:
                response = client.messages.create(
                    model=MODEL,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    tools=[WEB_SEARCH_TOOL],
                    messages=messages,
                )
                break  # success
            except RateLimitError:
                if attempt < 4:
                    time.sleep(60)
                else:
                    raise  # give up after 5 attempts

        # Collect the last text block
        for block in response.content:
            if hasattr(block, "text"):
                final_text = block.text

        # Report search progress
        tool_calls = [b for b in response.content if b.type == "tool_use"]
        if on_progress and tool_calls:
            on_progress(len(tool_calls))

        # Done?
        if response.stop_reason == "end_turn":
            break

        # Feed tool results back and continue
        messages.append({"role": "assistant", "content": response.content})
        tool_results = [
            {"type": "tool_result", "tool_use_id": b.id, "content": ""}
            for b in response.content if b.type == "tool_use"
        ]
        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    return final_text


# ── JSON Extraction with Recovery ────────────────────────────────────────────

def _extract_json(raw_text: str) -> dict:
    """
    Parse JSON from Claude's response text.

    Recovery strategy:
      1. Strip markdown fences
      2. Regex extract outermost { ... }
      3. json.loads()
      4. If fails: try closing open braces/brackets
      5. If fails: try ASCII-only cleanup
      6. If all fail: return error dict
    """
    raw = raw_text.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    json_match = re.search(r'\{[\s\S]*\}', raw)
    if not json_match:
        return {"company_name": "Unknown", "error": "No JSON found in response"}

    fragment = json_match.group()

    # Attempt 1: direct parse
    try:
        return json.loads(fragment)
    except json.JSONDecodeError:
        pass

    # Attempt 2: close open braces/brackets
    try:
        open_b = fragment.count("{") - fragment.count("}")
        open_a = fragment.count("[") - fragment.count("]")
        patched = fragment + ("]" * max(open_a, 0)) + ("}" * max(open_b, 0))
        return json.loads(patched)
    except json.JSONDecodeError:
        pass

    # Attempt 3: ASCII-only cleanup
    try:
        clean = fragment.encode("ascii", errors="ignore").decode("ascii")
        return json.loads(clean)
    except json.JSONDecodeError:
        return {"company_name": "Unknown", "error": "JSON parse failed",
                "raw": raw_text[:2000]}


# ── AI Confidence Display ────────────────────────────────────────────────────

def get_stars(confidence: float) -> str:
    """Convert confidence score to star rating string."""
    if confidence >= 0.85: return '\u2b50\u2b50\u2b50\u2b50\u2b50'
    elif confidence >= 0.70: return '\u2b50\u2b50\u2b50\u2b50'
    elif confidence >= 0.50: return '\u2b50\u2b50\u2b50'
    elif confidence >= 0.30: return '\u2b50\u2b50'
    else: return '\u2b50'


def add_confidence_display(analysis: dict) -> dict:
    """Walk the analysis and add display-friendly confidence strings.

    The AI assigns ai_confidence scores (0.0-1.0) during analysis — these
    reflect how confident the AI is in its OWN analytical conclusions, not
    confidence in the company's claims.  This function reads those scores
    and adds star-rating strings for PDF display.

    Confidence is displayed ONLY at the section level for:
      - outcome_magnitude scenarios (forward-looking analysis)
      - bankruptcy_insolvency (legal/financial finding)

    It is NOT displayed on individual unverified claims, technology claims,
    market claims, peer competitors, or market leaders.
    """

    # ── Defensive cleanup: strip ai_confidence from data-reporting sections
    # The AI may add these fields despite being told not to in the prompt.
    _STRIP_KEYS = ('ai_confidence', 'ai_confidence_score', 'ai_confidence_stars')

    for section in ('technology_claims', 'market_claims', 'unverified_claims'):
        for item in analysis.get(section, []):
            for k in _STRIP_KEYS:
                item.pop(k, None)

    comp_landscape = analysis.get('competitive_landscape', {})
    for comp in comp_landscape.get('peer_competitors', []):
        for k in _STRIP_KEYS:
            comp.pop(k, None)
    for leader in comp_landscape.get('market_leaders', []):
        for k in _STRIP_KEYS:
            leader.pop(k, None)

    # ── Enrich sections that SHOULD display confidence ──

    # Bankruptcy/insolvency — AI concludes legal/financial status
    status = analysis.get('company_financial_legal_status', {})
    bank = status.get('bankruptcy_insolvency', {})
    if 'ai_confidence' in bank:
        bank['ai_confidence_score'] = bank['ai_confidence']
        bank['ai_confidence_stars'] = get_stars(bank['ai_confidence'])

    # Outcome magnitude — AI's forward-looking scenario analysis
    mag = analysis.get('outcome_magnitude', {})
    for key in ('if_all_claims_verified', 'if_core_tech_only_verified'):
        sub = mag.get(key, {})
        if 'ai_confidence' in sub:
            sub['ai_confidence_score'] = sub['ai_confidence']
            sub['ai_confidence_stars'] = get_stars(sub['ai_confidence'])

    return analysis


# ── Analysis Prompt ──────────────────────────────────────────────────────────

_ANALYSIS_PROMPT = """You are conducting deep due diligence on a pitch deck. Your job is NOT to decide whether to invest. Your job is to:

1. Surface every significant claim the company makes — be exhaustive
2. Flag which claims are UNVERIFIED and need investigation
3. For each unverified claim, size the potential outcome IF it turns out to be true
4. Map the full competitive landscape at both peer scale and larger market scale

THOROUGHNESS GUIDANCE:
- Include only claims that are genuinely significant — skip trivial or obvious ones
- Focus on the claims that an investment committee would actually care about
- For each section, include as many or as few entries as the deck warrants — some companies make 3 big claims, others make 12. Match the deck, don't pad.
- competitive_landscape: include the most relevant peer competitors and market leaders — typically 2-4 of each, but use your judgment based on how crowded the market is
- Do not be vague — quote claims precisely from the deck and name real companies with known valuations

DATA LABELING — label every claim as:
- "COMPANY CLAIM (Unverified)" — only from the pitch deck, no independent confirmation
- "VERIFIED: [Source]" — confirmed by independent third party
- "PARTIALLY VERIFIED: Company claims X, [Source] indicates Y"

OUTCOME COMPARABLES — reference real companies with known valuations:
- "If the efficiency claims are accurate, this could compete with [Company] which holds X% of the market, valued at $Y"
- Use: IEA, Bloomberg NEF, Bain, McKinsey, CB Insights, Crunchbase, PitchBook

Pitch Deck:
{pitch_text}

Return comprehensive JSON:
{{
    "company_name": "Name",
    "industry": "Industry",
    "founded_year": 2020,

    "company_overview": {{
        "description": "2-3 paragraphs describing what the company does and what it claims",
        "stage": "Pre-revenue / Early revenue / Growth",
        "key_claims_summary": ["Top claim 1", "Top claim 2", "Top claim 3"]
    }},

    "company_financial_legal_status": {{
        "bankruptcy_insolvency": {{
            "status": "ACTIVE / IN ADMINISTRATION / BANKRUPTCY / RECEIVERSHIP / NONE FOUND",
            "details": "Specific details if found",
            "date_filed": "YYYY-MM-DD or null",
            "jurisdiction": "Location",
            "implications": "What this means for IP, liabilities, deal structure",
            "sources": ["Court records", "News articles"],
            "ai_confidence": 0.90
        }},
        "recent_funding": {{
            "last_round_attempted": "Series A / €15M round / etc",
            "outcome": "SUCCESSFUL / FAILED / ONGOING / UNKNOWN",
            "amount_sought": 15000000,
            "amount_raised": 0,
            "date": "YYYY-MM-DD",
            "failure_reasons": "Why it failed if applicable",
            "sources": ["Crunchbase", "News"]
        }},
        "litigation_liabilities": {{
            "active_lawsuits": ["Case 1"],
            "regulatory_actions": ["Action 1"],
            "outstanding_debts": "Description or amount if known",
            "sources": ["Court records"]
        }},
        "ip_ownership": {{
            "status": "CLEAR / DISPUTED / ENCUMBERED / UNKNOWN",
            "details": "Patents owned, licensed, or disputed",
            "encumbrances": "Liens, pledges, or claims on IP",
            "sources": ["Patent office", "Court records"]
        }},
        "overall_status": "HEALTHY / DISTRESSED / CRITICAL / UNKNOWN",
        "notes": "Key facts IC should know for context"
    }},

    "competitive_landscape": {{
        "positioning_summary": "1-2 sentences on how the company positions itself in the market",
        "peer_competitors": [
            {{
                "name": "Real company name at similar stage",
                "stage": "Seed / Series A / Series B / etc",
                "funding_raised_usd": 5000000,
                "description": "What they do and how they overlap with this company",
                "their_differentiator": "What makes them distinct",
                "company_advantage_claimed": "What this company claims makes it better — label as COMPANY CLAIM or VERIFIED",
                "sources": ["Crunchbase", "TechCrunch"]
            }}
        ],
        "market_leaders": [
            {{
                "name": "Real large incumbent or category leader",
                "market_position": "e.g. '35% market share in offshore wind installation'",
                "valuation_or_revenue": "e.g. '$18B market cap' or '$2.4B revenue 2023'",
                "description": "What they do and why they are relevant to this company's market",
                "threat_to_company": "How this incumbent could block or outcompete the company",
                "sources": ["Bloomberg", "Annual report"]
            }}
        ],
        "competitive_risks": ["Specific risk 1", "Specific risk 2"],
        "potential_acquirers": ["Company that might acquire if successful — and why"]
    }},

    "technology_claims": [
        {{
            "claim": "Exact quoted claim from the deck",
            "verification_status": "VERIFIED / UNVERIFIED / PARTIALLY VERIFIED",
            "source_label": "COMPANY CLAIM (Unverified) / VERIFIED: [Source]",
            "what_needs_investigation": "Specific test, data request, or expert that could verify this",
            "sources": ["Source 1"]
        }}
    ],

    "market_claims": [
        {{
            "claim": "Exact quoted claim from the deck",
            "verification_status": "VERIFIED / UNVERIFIED / PARTIALLY VERIFIED",
            "source_label": "COMPANY CLAIM (Unverified) / VERIFIED: [Source]",
            "what_needs_investigation": "Specific data source or analyst report that would verify this",
            "sources": ["Source 1"]
        }}
    ],

    "unverified_claims": [
        {{
            "claim": "Specific unverified claim — quote it precisely",
            "category": "Technology / Market / Financial / Team / Legal",
            "why_unverified": "What is specifically missing — no third-party data, no independent test, no customer validation",
            "investigation_steps": ["Concrete step 1", "Concrete step 2"],
            "outcome_if_true": {{
                "description": "What it means if this claim holds up",
                "market_opportunity_usd": 5000000000,
                "comparable_companies": [
                    {{
                        "company": "Real named company",
                        "context": "Specific comparison explaining the parallel",
                        "comparable_valuation_usd": 20000000000,
                        "market_share_potential": "5-15% of addressable market"
                    }}
                ],
                "outcome_magnitude": "HIGH / MEDIUM / LOW",
                "key_caveat": "The single most important condition for this outcome"
            }},
            "priority": "CRITICAL / HIGH / MEDIUM / LOW",
            "ai_confidence": 0.82
        }}
    ],

    "outcome_magnitude": {{
        "if_all_claims_verified": {{
            "description": "What the company could become if all major claims hold up",
            "addressable_market_usd": 50000000000,
            "realistic_market_share_pct": 5,
            "comparable_companies": ["Real Company A", "Real Company B"],
            "framing": "If the technology and market claims are accurate, this company could compete with [X] in the [Y] market, which currently supports companies valued at $Z",
            "ai_confidence": 0.80
        }},
        "if_core_tech_only_verified": {{
            "description": "Outcome if just the core technology works, market claims prove more modest",
            "addressable_market_usd": 5000000000,
            "comparable_companies": ["Real smaller comp"],
            "framing": "Even with a smaller market, proven tech alone positions this similarly to [X] at [stage/valuation]",
            "ai_confidence": 0.85
        }},
        "key_dependencies": ["Specific dependency 1", "Specific dependency 2"]
    }},

    "sources_consulted": 30,

    "graph_data": {{
        "company_name": "Same as top-level company_name",
        "sector": "Same as top-level industry",
        "graph1": {{
            "years": [2024, 2025, 2026, 2027, 2028, 2029, 2030],
            "company_revenue_usd_m": [0, 0, 5, 20, 60, 150, 350],
            "peers": [
                {{
                    "name": "Real Peer Co A (public or well-known)",
                    "years": [2024, 2025, 2026, 2027, 2028, 2029, 2030],
                    "revenue_usd_m": [500, 600, 720, 850, 1000, 1150, 1300]
                }},
                {{
                    "name": "Real Peer Co B",
                    "years": [2024, 2025, 2026, 2027, 2028, 2029, 2030],
                    "revenue_usd_m": [200, 240, 290, 340, 400, 460, 530]
                }}
            ],
            "note": "Peer revenues sourced from [real sources — annual reports, Crunchbase, etc.]"
        }},
        "graph2": {{
            "years": [2020, 2021, 2022, 2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030],
            "tam_usd_b": [10, 12, 14, 17, 20, 24, 29, 35, 42, 50, 60],
            "sam_usd_b": [1.5, 1.8, 2.2, 2.7, 3.3, 4.0, 4.9, 6.0, 7.3, 8.9, 10.8],
            "tam_label": "Global [Sector] Market",
            "sam_label": "Serviceable Market ([sub-niche])",
            "source_note": "Source: [IEA, BloombergNEF, Grand View Research, etc.]"
        }}
    }}
}}

AI CONFIDENCE SCORING:
Only the fields marked with "ai_confidence" in the schema above should receive a confidence
score. These are sections where you are making significant analytical conclusions or
synthesizing findings — NOT sections that merely report discovered data.

Specifically, ai_confidence applies to:
- unverified_claims: your assessment of why something is unverified and your outcome sizing
- outcome_magnitude scenarios: your forward-looking analytical conclusions
- bankruptcy_insolvency: your legal/financial finding from research

Do NOT add ai_confidence to technology_claims, market_claims, peer_competitors, or
market_leaders — those are data reporting, not analytical conclusions.

Assign a value between 0.0 and 1.0 representing YOUR confidence in YOUR OWN analytical
conclusion — NOT confidence in the company's claim itself.

Scoring guidance:
- 0.95-1.00: Multiple authoritative sources directly confirm your assessment
- 0.88-0.94: Strong evidence from reputable sources; minor gaps only
- 0.80-0.87: Good evidence with some extrapolation or indirect sources
- 0.70-0.79: Moderate evidence; notable assumptions made but grounded in data
- Below 0.70: ONLY use this when you are genuinely fabricating or assuming with no real evidence

Target average across a full report: 0.85-0.92. Most web-researched assessments will have
decent evidence and should score 0.82+. Reserve scores below 0.75 for cases where you truly
have no supporting data and are relying on inference alone.
Do NOT assign the same score to every item — vary them based on actual evidence quality.

IMPORTANT:
- Quality over quantity — include what matters, skip what doesn't
- Every unverified claim needs 1-2 concrete investigation steps naming specific data sources or tests
- All competitor names must be real companies with verifiable existence
- Do not recommend whether to invest — only surface what is unverified and what it could mean

WEB RESEARCH REQUIREMENTS:
You have access to web_search — use it to verify and enrich your analysis.
Do at least 6-8 searches covering:
  - Search for the company name + "funding" / "crunchbase" / "news"
  - Search for competitor names + "revenue" / "valuation" / "market share"
  - Search for "[sector] market size TAM 2024 2025" (BloombergNEF, IEA, Grand View Research)
  - Search for "[sector] CAGR forecast 2030"
  - Search for technology performance benchmarks relevant to the company's claims
  - Search for "[company] litigation" / "bankruptcy" / "lawsuit" if relevant
Do NOT guess at numbers — search for real data first. Cite what you find.

GRAPH DATA REQUIREMENTS (the "graph_data" field):
- graph1: Use the company's own revenue projections from the deck. For peers, use WEB SEARCH to find 2-3 real public/well-known competitors with actual revenue figures. Cite sources in the "note" field.
- graph2: TAM/SAM should reflect real market research figures found via WEB SEARCH (IEA, BloombergNEF, Grand View, Mordor Intelligence, etc.). Cite sources in "source_note".
- NOTE: graph3 (technology benchmark) is handled by a separate dedicated research call — do NOT include it here.

After completing your web research, return the full JSON and nothing else — no markdown fences, no prose.
"""


# ── Graph Data Fallback Prompt ───────────────────────────────────────────────

_GRAPH_EXTRACTION_PROMPT = """
You are building structured numerical data for two investment analysis charts.
You have access to web_search — use it extensively to find real, verified numbers.

STEP 1 — Read the due diligence analysis provided at the end of this prompt.
STEP 2 — Use web_search to look up REAL data for:
  - Peer company revenues (search "[Company] annual revenue 2023 2024")
  - Market size (search "[sector] market size TAM 2024 BloombergNEF IEA Grand View Research")
  - Market growth rates (search "[sector] CAGR market growth forecast 2030")
  Do at least 4-6 searches before producing your final answer.
STEP 3 — Return ONLY valid JSON with no markdown, no prose.

CHART DATA TO PRODUCE:

1. COMPANY PROJECTIONS vs PEERS (revenue timeline)
   - The subject company's own revenue projections by year (2024-2030, from the analysis).
   - 2-3 established/public peer companies in the same sector. Use WEB SEARCH to get
     their real revenues — do not guess. Cite the source in the "note" field.

2. MARKET SIZE OVER TIME
   - Global TAM for the company's sector in $B, years 2020-2030.
   - Sub-niche SAM the company targets, in $B, same period.
   - Use WEB SEARCH to find real market research figures (BloombergNEF, IEA, Grand View,
     Mordor Intelligence, etc.). Cite the source in source_note.

NOTE: graph3 (technology benchmark) is handled by a separate dedicated call — do NOT include it.

Return this exact JSON structure:
{
  "company_name": "string",
  "sector": "string",
  "graph1": {
    "years": [2024, 2025, 2026, 2027, 2028, 2029, 2030],
    "company_revenue_usd_m": [0, 0, 5, 20, 60, 150, 350],
    "peers": [
      {
        "name": "Peer Co A",
        "years": [2024, 2025, 2026, 2027, 2028, 2029, 2030],
        "revenue_usd_m": [500, 600, 720, 850, 1000, 1150, 1300]
      },
      {
        "name": "Peer Co B",
        "years": [2024, 2025, 2026, 2027, 2028, 2029, 2030],
        "revenue_usd_m": [200, 240, 290, 340, 400, 460, 530]
      }
    ],
    "note": "Peer revenues sourced from [actual sources found via search]"
  },
  "graph2": {
    "years": [2020, 2021, 2022, 2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030],
    "tam_usd_b": [10, 12, 14, 17, 20, 24, 29, 35, 42, 50, 60],
    "sam_usd_b": [1.5, 1.8, 2.2, 2.7, 3.3, 4.0, 4.9, 6.0, 7.3, 8.9, 10.8],
    "tam_label": "Global [Sector] Market",
    "sam_label": "Serviceable Market ([sub-niche])",
    "source_note": "Source: [actual sources found via search, e.g. BloombergNEF 2024]"
  }
}

Here is the due diligence analysis:
"""


# ── Public API ───────────────────────────────────────────────────────────────

def analyze(api_key: str, pitch_text: str, on_progress=None) -> dict:
    """
    Run the full Opus + web_search analysis on pitch deck text.

    Args:
        api_key:     Anthropic API key.
        pitch_text:  Extracted text from the pitch deck.
        on_progress: Optional callback(search_count: int) for UI updates.

    Returns: Parsed analysis dict with all 12 top-level keys.
    """
    client = Anthropic(api_key=api_key)
    prompt = _ANALYSIS_PROMPT.format(pitch_text=pitch_text[:60000])

    raw_text = _agentic_call(
        client, prompt,
        max_tokens=20000, temperature=0.2,
        on_progress=on_progress,
    )
    return _extract_json(raw_text)


def extract_graph_data_fallback(api_key: str, analysis: dict,
                                on_progress=None) -> dict:
    """
    Fallback: extract graph1+graph2 data via a separate Opus + web_search call.
    Used only when analysis["graph_data"] is missing.
    """
    client = Anthropic(api_key=api_key)
    analysis_json = json.dumps(analysis, indent=2)[:40_000]
    prompt = _GRAPH_EXTRACTION_PROMPT + analysis_json

    raw_text = _agentic_call(
        client, prompt,
        max_tokens=8000, temperature=0.1,
        on_progress=on_progress,
    )
    return _extract_json(raw_text)


# ── Technology Benchmark — Dedicated Research Call ──────────────────────────

_BENCHMARK_PROMPT = """You are a technology analyst building a rigorous competitive benchmark.
Your task: identify the SINGLE most important quantifiable performance metric for a company's
core technology, then use extensive web research to build a comprehensive, well-sourced dataset
of competitor values for that exact metric.

ANALYTICAL RIGOR REQUIREMENTS:
- Every data point must have a named source (press release, investor deck, technical paper, etc.)
- Classify each data point by maturity stage:
    "production" — commercially shipping in products today
    "target" — announced roadmap goal, not yet achieved
    "prototype" — demonstrated in lab, pilot plant, or pre-commercial testing
- Specify the measurement basis so values are comparable (e.g., "cell-level Wh/kg, pouch format"
  or "EPA-rated miles" or "STC efficiency %" or "levelized cost $/MWh")
- If a competitor's number uses different conditions (e.g., pack-level vs cell-level), note that
  in the source field and normalize if possible, or flag it as non-comparable
- Include the current commercially-available best-in-class value as a baseline reference

WEB SEARCH STRATEGY — do at least 10-15 searches:
  1. "[company name] [metric] specifications" — find the subject company's exact claim
  2. "[sector] [metric] comparison 2024 2025" — broad competitive landscape
  3. "[competitor 1] [metric] roadmap target" — for each known competitor
  4. "[sector] performance benchmarks [year]" — industry surveys and rankings
  5. "[metric] state of the art record" — academic/lab records
  6. "[sector] technology leaders [metric]" — identify additional competitors you may have missed
  7. "[competitor] press release [metric]" — verify specific claims
  8. "best [metric] commercially available [year]" — current best-in-class baseline
  Search for as many named competitors as you can find. The goal is 8-15+ data points.
  Do NOT guess or fabricate values. If you cannot find a reliable source, skip that competitor.

METRIC SELECTION:
Read the due diligence analysis below. Identify the company's core technology value proposition.
Pick the ONE quantitative metric that most directly measures their competitive advantage.
Examples: battery energy density (Wh/kg), solar cell efficiency (%), EV range (miles),
carbon capture cost ($/ton CO2), wind turbine capacity (MW), drug response rate (%),
chip transistor density (nm), data throughput (Gbps), electrolyzer efficiency (kWh/kg H2),
etc. The metric must be something the company explicitly claims a specific number for.

Return ONLY this JSON structure — no markdown, no prose:
{
  "metric_name": "Gravimetric Energy Density",
  "metric_unit": "Wh/kg",
  "measurement_basis": "Cell-level, pouch format, room temperature",
  "target_year": 2028,
  "company_name": "Subject Company",
  "company_claim": 500,
  "company_claim_stage": "target",
  "company_claim_source": "Pitch deck / investor presentation",
  "competitor_claims": [
    {
      "name": "CATL",
      "value": 500,
      "source": "CATL Condensed Battery press release, April 2023",
      "stage": "prototype"
    },
    {
      "name": "Samsung SDI",
      "value": 400,
      "source": "Samsung SDI Investor Day 2024 presentation",
      "stage": "production"
    },
    {
      "name": "BYD",
      "value": 180,
      "source": "BYD Blade Battery specs, company website",
      "stage": "production"
    }
  ],
  "higher_is_better": true,
  "current_best_in_class": 350,
  "current_best_source": "BloombergNEF battery survey 2024",
  "conditions_note": "All values are cell-level gravimetric energy density unless noted. Production = shipping in commercial products. Target = announced roadmap/goal. Prototype = demonstrated in lab or pilot.",
  "rationale": "Energy density is the primary differentiator for next-gen batteries, directly determining EV range and cost competitiveness.",
  "sources_searched": 12
}

IMPORTANT:
- Return as many competitor data points as you can find with reliable sources (aim for 8-15+)
- Do NOT include competitors where you cannot find a specific, sourced number
- The "stage" field is critical — it separates what exists today from what is aspirational
- All values should be normalized to the same measurement_basis where possible
- If a value is not directly comparable (different test conditions), note this in the source field

Here is the due diligence analysis to base your benchmark on:
"""


def research_tech_benchmark(api_key: str, analysis: dict,
                            on_progress=None) -> dict:
    """
    Dedicated web research call to build a rigorous technology benchmark.

    Runs a separate Claude + web_search call focused entirely on finding
    comparable, well-sourced competitor data points for the company's key
    performance metric. Returns graph3-compatible data dict.

    Args:
        api_key:     Anthropic API key.
        analysis:    The main analysis dict (used for context).
        on_progress: Optional callback(search_count: int) for UI updates.

    Returns: Dict with metric_name, competitor_claims, stages, sources, etc.
    """
    client = Anthropic(api_key=api_key)
    analysis_json = json.dumps(analysis, indent=2)[:40_000]
    prompt = _BENCHMARK_PROMPT + analysis_json

    raw_text = _agentic_call(
        client, prompt,
        max_tokens=8000, temperature=0.1,
        on_progress=on_progress,
    )
    return _extract_json(raw_text)
