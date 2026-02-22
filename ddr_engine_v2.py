"""
ddr_engine_v2.py
================
AI analysis engine for the VoLo DDR V2 tool.

V2 consolidation:
  - Single Opus + web_search call returns ALL data (analysis + graph1/2 + graph3 benchmark)
  - No separate benchmark call, no fallback graph extraction
  - Estimated cost: ~$1.00-1.50 per report (vs. $1.75-2.50 in V1)

Reused from V1: extract_pdf(), _agentic_call(), _extract_json()
"""

import os
import json
import re
import time

from pypdf import PdfReader
from anthropic import Anthropic, RateLimitError, APIStatusError

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
                  max_tokens: int = 16000, temperature: float = 0.2,
                  on_progress=None) -> str:
    """
    Run a single agentic Claude + web_search call.

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
            except APIStatusError as e:
                # 529 = Anthropic overloaded — shorter wait, then retry
                if e.status_code == 529 and attempt < 4:
                    time.sleep(30)
                else:
                    raise

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
      1. Strip markdown fences and surrounding prose
      2. Regex extract outermost { ... }
      3. json.loads()
      4. If fails: fix common issues (control chars, unescaped quotes)
      5. If fails: try closing open braces/brackets
      6. If fails: try ASCII-only cleanup
      7. If all fail: return error dict
    """
    raw = raw_text.strip()
    # Strip markdown fences anywhere in the text
    raw = re.sub(r"```[a-z]*\s*\n?", "", raw)
    raw = re.sub(r"\n?\s*```", "", raw)

    json_match = re.search(r'\{[\s\S]*\}', raw)
    if not json_match:
        return {"company_name": "Unknown", "error": "No JSON found in response"}

    fragment = json_match.group()

    def _clean(s: str) -> str:
        """Remove control characters and fix common JSON issues."""
        # Remove control chars except \n \r \t
        s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)
        # Fix unescaped newlines inside strings — replace literal newlines
        # within JSON string values with \\n
        return s

    # Attempt 1: direct parse
    try:
        return json.loads(fragment)
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 2: clean control chars and retry
    try:
        return json.loads(_clean(fragment))
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 3: close open braces/brackets
    try:
        cleaned = _clean(fragment)
        open_b = cleaned.count("{") - cleaned.count("}")
        open_a = cleaned.count("[") - cleaned.count("]")
        patched = cleaned + ("]" * max(open_a, 0)) + ("}" * max(open_b, 0))
        return json.loads(patched)
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 4: strip non-ASCII and retry
    try:
        clean = fragment.encode("ascii", errors="ignore").decode("ascii")
        return json.loads(clean)
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 5: try to find a smaller valid JSON object
    # Sometimes the AI puts prose after the JSON closing brace
    try:
        depth = 0
        end_idx = 0
        for idx, ch in enumerate(fragment):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end_idx = idx + 1
                    break
        if end_idx > 0:
            return json.loads(_clean(fragment[:end_idx]))
    except (json.JSONDecodeError, ValueError):
        pass

    return {"company_name": "Unknown", "error": "JSON parse failed",
            "raw": raw_text[:2000]}


# ── V2 Unified Analysis Prompt ──────────────────────────────────────────────

_ANALYSIS_PROMPT = """You are conducting deep due diligence on a pitch deck. Your job is NOT to decide whether to invest. Your job is to:

1. Surface every significant claim the company makes — be exhaustive
2. Flag which claims are UNVERIFIED and need investigation
3. For each unverified claim, size the potential outcome IF it turns out to be true
4. Map the full competitive landscape at both peer scale and larger market scale
5. Build a rigorous technology benchmark with real competitor data

CONCISENESS GUIDANCE — This report targets 10-12 pages total. Be precise:
- company_overview: 1-2 paragraphs (not 2-3)
- Peer competitors: 2-4 entries, 1-2 sentences each for description
- Market leaders: 2-3 entries, 1-2 sentences each
- Claims: include only genuinely significant claims. Skip trivial or obvious ones.
- Unverified claims: include ONLY CRITICAL and HIGH priority claims (skip MEDIUM and LOW entirely).
  For each, keep investigation_steps to 1-2 concrete items.
- outcome_magnitude: 1 paragraph per scenario, not 2-3

THOROUGHNESS GUIDANCE:
- Focus on the claims an investment committee would actually care about
- Do not be vague — quote claims precisely from the deck and name real companies with known valuations
- Every unverified claim needs 1-2 concrete investigation steps naming specific data sources or tests
- All competitor names must be real companies with verifiable existence

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
        "description": "1-2 concise paragraphs describing what the company does and what it claims",
        "stage": "Pre-revenue / Early revenue / Growth",
        "key_claims_summary": ["Top claim 1", "Top claim 2", "Top claim 3"]
    }},

    "status_flags": {{
        "overall_status": "HEALTHY / DISTRESSED / CRITICAL / UNKNOWN",
        "bankruptcy_insolvency": {{
            "status": "ACTIVE / IN ADMINISTRATION / BANKRUPTCY / NONE FOUND",
            "details": "Specific details if found",
            "sources": ["Court records", "News articles"]
        }},
        "recent_funding": {{
            "last_round": "Series A / €15M round / etc",
            "outcome": "SUCCESSFUL / FAILED / ONGOING / UNKNOWN",
            "amount_sought": 15000000,
            "amount_raised": 0,
            "date": "YYYY-MM-DD",
            "failure_reasons": "Why it failed if applicable",
            "sources": ["Crunchbase", "News"]
        }},
        "ip_status": {{
            "status": "CLEAR / DISPUTED / ENCUMBERED / UNKNOWN",
            "details": "Patents owned, licensed, or disputed",
            "sources": ["Patent office"]
        }},
        "active_litigation": {{
            "lawsuits": ["Case 1 if any"],
            "regulatory_actions": ["Action 1 if any"],
            "sources": ["Court records"]
        }},
        "notes": "Key facts IC should know for context"
    }},

    "competitive_landscape": {{
        "positioning_summary": "1-2 sentences on how the company positions itself",
        "peer_competitors": [
            {{
                "name": "Real company at similar stage",
                "stage": "Seed / Series A / Series B",
                "funding_raised_usd": 5000000,
                "description": "1-2 sentences: what they do, how they overlap, their edge vs this company",
                "sources": ["Crunchbase"]
            }}
        ],
        "market_leaders": [
            {{
                "name": "Real large incumbent",
                "market_position": "e.g. '35% market share in offshore wind'",
                "valuation_or_revenue": "e.g. '$18B market cap'",
                "description": "1-2 sentences: what they do, threat to this company",
                "sources": ["Bloomberg"]
            }}
        ],
        "competitive_risks": ["Specific risk 1", "Specific risk 2"],
        "potential_acquirers": ["Company that might acquire — and why"]
    }},

    "claims": [
        {{
            "type": "TECHNOLOGY",
            "claim": "Exact quoted claim from the deck",
            "verification_status": "VERIFIED / UNVERIFIED / PARTIALLY VERIFIED",
            "source_label": "COMPANY CLAIM (Unverified) / VERIFIED: [Source]",
            "what_needs_investigation": "Specific test or data source that could verify this",
            "sources": ["Source 1"]
        }},
        {{
            "type": "MARKET",
            "claim": "Exact quoted claim from the deck",
            "verification_status": "VERIFIED / UNVERIFIED / PARTIALLY VERIFIED",
            "source_label": "COMPANY CLAIM (Unverified) / VERIFIED: [Source]",
            "what_needs_investigation": "Specific data source that would verify this",
            "sources": ["Source 1"]
        }}
    ],

    "unverified_claims": [
        {{
            "claim": "Specific unverified claim — quote it precisely",
            "category": "Technology / Market / Financial / Team / Legal",
            "why_unverified": "What is specifically missing",
            "investigation_steps": ["Concrete step 1", "Concrete step 2"],
            "outcome_if_true": {{
                "description": "What it means if this claim holds up",
                "market_opportunity_usd": 5000000000,
                "comparable_companies": [
                    {{
                        "company": "Real named company",
                        "context": "Specific comparison",
                        "comparable_valuation_usd": 20000000000,
                        "market_share_potential": "5-15% of addressable market"
                    }}
                ],
                "outcome_magnitude": "HIGH / MEDIUM / LOW",
                "key_caveat": "The single most important condition for this outcome"
            }},
            "priority": "CRITICAL / HIGH"
        }}
    ],

    "outcome_magnitude": {{
        "if_all_claims_verified": {{
            "description": "1 paragraph: what the company could become",
            "addressable_market_usd": 50000000000,
            "realistic_market_share_pct": 5,
            "comparable_companies": ["Real Company A", "Real Company B"],
            "framing": "If the technology and market claims are accurate, this company could compete with [X] in the [Y] market"
        }},
        "if_core_tech_only_verified": {{
            "description": "1 paragraph: outcome if just the core technology works",
            "addressable_market_usd": 5000000000,
            "comparable_companies": ["Real smaller comp"],
            "framing": "Even with a smaller market, proven tech alone positions this similarly to [X]"
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
            "note": "Peer revenues sourced from [actual sources]"
        }},
        "graph2": {{
            "years": [2020, 2021, 2022, 2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030],
            "tam_usd_b": [10, 12, 14, 17, 20, 24, 29, 35, 42, 50, 60],
            "sam_usd_b": [1.5, 1.8, 2.2, 2.7, 3.3, 4.0, 4.9, 6.0, 7.3, 8.9, 10.8],
            "tam_label": "Global [Sector] Market",
            "sam_label": "Serviceable Market ([sub-niche])",
            "source_note": "Source: [IEA, BloombergNEF, Grand View Research, etc.]"
        }},
        "graph3": {{
            "metric_name": "Key Performance Metric",
            "metric_unit": "unit",
            "measurement_basis": "How it's measured (e.g. cell-level Wh/kg)",
            "target_year": 2028,
            "company_name": "Subject Company",
            "company_claim": 500,
            "company_claim_stage": "target",
            "company_claim_source": "Pitch deck",
            "competitor_claims": [
                {{
                    "name": "Competitor A",
                    "value": 400,
                    "source": "Press release or investor deck, with date",
                    "stage": "production"
                }},
                {{
                    "name": "Competitor B",
                    "value": 350,
                    "source": "Annual report 2024",
                    "stage": "production"
                }}
            ],
            "higher_is_better": true,
            "current_best_in_class": 350,
            "current_best_source": "Source for current best",
            "conditions_note": "Measurement conditions and comparability notes",
            "rationale": "Why this metric was chosen"
        }}
    }}
}}

WEB RESEARCH REQUIREMENTS:
You have access to web_search — use it to verify and enrich your analysis.
Do 8-12 searches covering:
  - Company name + "funding" / "crunchbase" / "news"
  - Competitor names + "revenue" / "valuation" / "market share"
  - "[sector] market size TAM 2024 2025" (BloombergNEF, IEA, Grand View Research)
  - "[sector] CAGR forecast 2030"
  - Technology performance benchmarks relevant to company claims
  - "[company] litigation" / "bankruptcy" if relevant
  - "[sector] [metric] benchmark comparison" for graph3 technology data
  - "[competitor] [metric] specifications" for graph3 competitor values
Do NOT guess at numbers — search for real data first. Cite what you find.

GRAPH DATA REQUIREMENTS:
- graph1: Company's own revenue projections from the deck. For peers, use WEB SEARCH for 2-3 real competitors with actual revenue figures.
- graph2: TAM/SAM from real market research via WEB SEARCH (IEA, BloombergNEF, Grand View, etc.).
- graph3: Technology benchmark — identify the ONE key quantifiable metric for the company's core tech.
  Search for 5-10 competitor data points with named sources. Classify each as "production", "target", or "prototype".
  Include current best-in-class baseline. Do NOT guess — only include competitors with sourced values.

IMPORTANT:
- ONLY include CRITICAL and HIGH priority unverified claims. Skip MEDIUM and LOW entirely.
- Keep descriptions concise — this report targets 10-12 pages total.
- Do not recommend whether to invest — only surface what is unverified and what it could mean.
- After completing your web research, return the full JSON and nothing else — no markdown fences, no prose.
"""


# ── Public API ───────────────────────────────────────────────────────────────

def analyze(api_key: str, pitch_text: str, on_progress=None) -> dict:
    """
    Run the single unified Opus + web_search analysis on pitch deck text.

    Returns all data needed for the report: analysis, graph1/2, graph3 benchmark.
    One API call, ~8-12 web searches.
    """
    client = Anthropic(api_key=api_key)
    prompt = _ANALYSIS_PROMPT.format(pitch_text=pitch_text[:60000])

    raw_text = _agentic_call(
        client, prompt,
        max_tokens=16000, temperature=0.2,
        on_progress=on_progress,
    )
    return _extract_json(raw_text)
