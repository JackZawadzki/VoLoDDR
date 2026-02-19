"""
ddr_graphs.py
=============
Sector-agnostic graph generation module for the DDR webapp.

Takes the scored analysis dict (already produced by DueDiligenceAnalyzer)
and returns three matplotlib figures that can be displayed in Streamlit
or embedded in the PDF report.

Graphs:
    1. Company revenue projections vs. established peers (timeline)
    2. Global TAM + sub-niche SAM market growth over time
    3. Monte Carlo simulation — projected 2035 revenue histogram
       with P10 / P50 / P90 percentile overlays

Usage in ddr_app.py:
    from ddr_graphs import build_graphs
    figs = build_graphs(scored_analysis, anthropic_client)
    for fig in figs:
        st.pyplot(fig)
"""

import json
import re
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.patches import FancyBboxPatch
from anthropic import Anthropic

# ── Shared style ──────────────────────────────────────────────────────────────
VOLO_GREEN      = "#2d5f3f"
VOLO_LIGHT      = "#3a7d52"
VOLO_PALE       = "#eef7f1"
ACCENT_ORANGE   = "#e07b39"
ACCENT_BLUE     = "#3a6ea8"
ACCENT_PURPLE   = "#7b5ea7"
GRID_COLOR      = "#d4e6da"
TEXT_DARK       = "#1a1a1a"
TEXT_MID        = "#4a4a4a"

def _add_ai_watermark(fig):
    """Add a subtle 'AI Estimates — Illustrative Only' watermark to a figure."""
    fig.text(
        0.99, 0.01,
        "⚠ AI Estimates — Illustrative Only · Verify before use",
        ha="right", va="bottom", fontsize=7, color="#aaaaaa",
        style="italic", transform=fig.transFigure,
    )


def _apply_base_style(ax, title, xlabel, ylabel):
    ax.set_facecolor(VOLO_PALE)
    ax.set_title(title, fontsize=13, fontweight="bold", color=TEXT_DARK, pad=12)
    ax.set_xlabel(xlabel, fontsize=10, color=TEXT_MID)
    ax.set_ylabel(ylabel, fontsize=10, color=TEXT_MID)
    ax.tick_params(colors=TEXT_MID, labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRID_COLOR)
    ax.spines["bottom"].set_color(GRID_COLOR)
    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.8, linestyle="--")
    ax.set_axisbelow(True)


def _millions(x, _):
    if abs(x) >= 1_000:
        return f"${x/1_000:.1f}B"
    return f"${x:.0f}M"


def _billions(x, _):
    return f"${x:.0f}B"


# ── Claude data extraction ────────────────────────────────────────────────────

EXTRACTION_PROMPT = """
You are building structured numerical data for three investment analysis charts.
You have access to web_search — use it extensively to find real, verified numbers.

STEP 1 — Read the due diligence analysis provided at the end of this prompt.
STEP 2 — Use web_search to look up REAL data for:
  • Peer company revenues (search "[Company] annual revenue 2023 2024")
  • Market size (search "[sector] market size TAM 2024 BloombergNEF IEA Grand View Research")
  • Market growth rates (search "[sector] CAGR market growth forecast 2030")
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

3. MONTE CARLO — 2035 REVENUE
   - Calibrate the distribution using the company's projections AND verified industry
     growth benchmarks found via web search.
   - Higher sigma = more uncertainty (use 0.6-1.0 for early-stage, 0.4-0.6 for later).

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
  },
  "graph3": {
    "mean_2035_usd_m": 800,
    "lognorm_mu": 6.5,
    "lognorm_sigma": 0.7,
    "n_simulations": 50000,
    "rationale": "Distribution calibrated using [sources found via search]"
  }
}

Here is the due diligence analysis:
"""

_WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
}


def _extract_graph_data(analysis: dict, client: Anthropic) -> dict:
    """Ask Claude to pull structured graph data out of the analysis JSON,
    using web search to verify peer revenues and market size figures."""
    analysis_json = json.dumps(analysis, indent=2)[:40_000]  # guard token limit

    # Agentic loop — keep going until Claude stops using tools
    messages = [{"role": "user", "content": EXTRACTION_PROMPT + analysis_json}]
    final_text = ""

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=8000,
            temperature=0.1,
            tools=[_WEB_SEARCH_TOOL],
            messages=messages,
        )

        # Collect any text from this turn
        for block in response.content:
            if hasattr(block, "text"):
                final_text = block.text  # keep the last text block

        # If Claude is done (no more tool calls), break
        if response.stop_reason == "end_turn":
            break

        # Otherwise feed tool results back and continue
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "",   # web_search results are injected by the API
                })
        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        else:
            break  # no tool calls but stop_reason wasn't end_turn — exit anyway

    raw = final_text.strip()
    # Strip markdown fences if present
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    # Extract just the JSON object in case there's surrounding prose
    json_match = re.search(r'\{[\s\S]*\}', raw)
    if json_match:
        raw = json_match.group()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Strip any non-standard characters and retry
        raw_clean = raw.encode("ascii", errors="ignore").decode("ascii")
        return json.loads(raw_clean)


# ── Graph 1: Company projections vs. established peers ────────────────────────

def _graph1(data: dict) -> plt.Figure:
    g = data["graph1"]
    company = data["company_name"]
    years_c = g["years"]
    rev_c   = g["company_revenue_usd_m"]
    peers   = g["peers"]
    note    = g.get("note", "")

    fig, ax = plt.subplots(figsize=(9, 5))
    fig.patch.set_facecolor("white")

    _apply_base_style(
        ax,
        title=f"{company} Revenue Trajectory vs. Established Peers",
        xlabel="Year",
        ylabel="Revenue (USD)"
    )

    # Company line — bold green, dashed to signal projection
    ax.plot(years_c, rev_c, color=VOLO_GREEN, linewidth=2.8,
            linestyle="--", marker="o", markersize=6,
            label=f"{company} (projected)", zorder=5)

    peer_colors = [ACCENT_BLUE, ACCENT_ORANGE, ACCENT_PURPLE, "#888888"]
    for i, peer in enumerate(peers):
        ax.plot(peer["years"], peer["revenue_usd_m"],
                color=peer_colors[i % len(peer_colors)],
                linewidth=2.0, marker="s", markersize=5,
                label=peer["name"])

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_millions))
    ax.legend(fontsize=9, framealpha=0.9, edgecolor=GRID_COLOR)

    if note:
        fig.text(0.5, -0.04, f"Note: {note}", ha="center",
                 fontsize=7.5, color=TEXT_MID, style="italic")

    _add_ai_watermark(fig)
    fig.tight_layout()
    return fig


# ── Graph 2: Global TAM + sub-niche SAM growth over time ─────────────────────

def _graph2(data: dict) -> plt.Figure:
    g = data["graph2"]
    years    = g["years"]
    tam      = g["tam_usd_b"]
    sam      = g["sam_usd_b"]
    tam_lbl  = g.get("tam_label", "Global Market (TAM)")
    sam_lbl  = g.get("sam_label", "Serviceable Market (SAM)")
    src_note = g.get("source_note", "")

    fig, ax = plt.subplots(figsize=(9, 5))
    fig.patch.set_facecolor("white")

    _apply_base_style(
        ax,
        title="Market Size Over Time — TAM & SAM",
        xlabel="Year",
        ylabel="Market Size (USD Billions)"
    )

    # TAM — filled area + line
    ax.fill_between(years, tam, alpha=0.15, color=VOLO_GREEN)
    ax.plot(years, tam, color=VOLO_GREEN, linewidth=2.5,
            marker="o", markersize=5, label=tam_lbl)

    # SAM — filled area + line
    ax.fill_between(years, sam, alpha=0.25, color=ACCENT_BLUE)
    ax.plot(years, sam, color=ACCENT_BLUE, linewidth=2.5,
            marker="s", markersize=5, linestyle="--", label=sam_lbl)

    # Annotate latest values
    ax.annotate(f"  ${tam[-1]:.0f}B", xy=(years[-1], tam[-1]),
                fontsize=8.5, color=VOLO_GREEN, fontweight="bold", va="center")
    ax.annotate(f"  ${sam[-1]:.1f}B", xy=(years[-1], sam[-1]),
                fontsize=8.5, color=ACCENT_BLUE, fontweight="bold", va="center")

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_billions))
    ax.legend(fontsize=9, framealpha=0.9, edgecolor=GRID_COLOR)

    if src_note:
        fig.text(0.5, -0.04, src_note, ha="center",
                 fontsize=7.5, color=TEXT_MID, style="italic")

    _add_ai_watermark(fig)
    fig.tight_layout()
    return fig


# ── Graph 3: Monte Carlo histogram — projected 2035 revenue ──────────────────

def _graph3(data: dict) -> plt.Figure:
    g = data["graph3"]
    company    = data["company_name"]
    mu         = g["lognorm_mu"]
    sigma      = g["lognorm_sigma"]
    n          = g.get("n_simulations", 50_000)
    rationale  = g.get("rationale", "")

    rng = np.random.default_rng(42)
    samples = rng.lognormal(mean=mu, sigma=sigma, size=n)

    p10 = np.percentile(samples, 10)
    p50 = np.percentile(samples, 50)
    p90 = np.percentile(samples, 90)

    fig, ax = plt.subplots(figsize=(9, 5.5))
    fig.patch.set_facecolor("white")
    ax.set_facecolor(VOLO_PALE)

    # Clip display range to P2–P98 so extreme outliers don't flatten the chart
    lo, hi = np.percentile(samples, 2), np.percentile(samples, 98)
    clipped = samples[(samples >= lo) & (samples <= hi)]

    ax.hist(clipped, bins=80, color=VOLO_LIGHT, edgecolor="white",
            linewidth=0.4, alpha=0.85, density=True)

    # Percentile lines
    line_cfg = [
        (p10, "#c0392b", "P10 — Conservative"),
        (p50, VOLO_GREEN, "P50 — Median"),
        (p90, ACCENT_ORANGE, "P90 — Optimistic"),
    ]
    y_top = ax.get_ylim()[1]

    for val, color, label in line_cfg:
        ax.axvline(val, color=color, linewidth=2.2, linestyle="--", zorder=6)

        # Dollar label above line
        if val >= 1_000:
            val_str = f"${val/1_000:.1f}B"
        else:
            val_str = f"${val:.0f}M"

        ax.text(val, y_top * 0.97, f"{label.split('—')[0].strip()}\n{val_str}",
                ha="center", va="top", fontsize=8.5, color=color,
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                          edgecolor=color, alpha=0.9))

    _apply_base_style(
        ax,
        title=f"{company} — Monte Carlo: Projected 2035 Revenue",
        xlabel="Revenue (USD)",
        ylabel="Probability Density"
    )

    # Format x-axis dynamically
    def _rev_fmt(x, _):
        if x >= 1_000:
            return f"${x/1_000:.1f}B"
        return f"${x:.0f}M"

    ax.xaxis.set_major_formatter(mticker.FuncFormatter(_rev_fmt))
    ax.tick_params(axis="x", rotation=20)

    # Caption box
    caption = (
        f"Based on {n:,} Monte Carlo simulations. "
        f"P10 = conservative outcome, P50 = median (most likely), P90 = optimistic outcome.\n"
        + (f"{rationale}" if rationale else "")
    )
    fig.text(0.5, -0.06, caption, ha="center", fontsize=7.8,
             color=TEXT_MID, style="italic", wrap=True)

    _add_ai_watermark(fig)
    fig.tight_layout()
    return fig


# ── PDF export ───────────────────────────────────────────────────────────────

def figures_to_pdf(figs: list, output_path: str, company_name: str):
    """Save the three figures to a single multi-page PDF."""
    from matplotlib.backends.backend_pdf import PdfPages

    titles = [
        "Revenue Trajectory vs. Established Peers",
        "Global TAM & Sub-Niche SAM Growth Over Time",
        "Monte Carlo Simulation — Projected 2035 Revenue",
    ]
    captions = [
        "Company's own revenue projections (dashed) plotted against real, publicly known peers in the same sector.\n"
        "Dashed line reflects unverified company claims.",
        "Global addressable market (TAM) and the company's serviceable sub-niche (SAM) based on independent industry research.",
        "50,000-run Monte Carlo simulation of projected 2035 revenue.\n"
        "P10 = conservative, P50 = median, P90 = optimistic probabilistic outcomes.",
    ]

    with PdfPages(output_path) as pdf:
        # Cover page
        cover = plt.figure(figsize=(9, 4))
        cover.patch.set_facecolor(VOLO_GREEN)
        cover.text(0.5, 0.65, company_name, ha="center", va="center",
                   fontsize=22, fontweight="bold", color="white",
                   transform=cover.transFigure)
        cover.text(0.5, 0.45, "Investment Analysis Charts", ha="center", va="center",
                   fontsize=14, color="#c8e6d2", transform=cover.transFigure)
        cover.text(0.5, 0.28,
                   f"Generated by VoLo Earth Ventures DDR Tool  ·  {__import__('datetime').datetime.now().strftime('%B %d, %Y')}",
                   ha="center", va="center", fontsize=9, color="#a8d5b5",
                   transform=cover.transFigure)
        pdf.savefig(cover, bbox_inches="tight")
        plt.close(cover)

        # One page per chart
        for fig, title, caption in zip(figs, titles, captions):
            pdf.savefig(fig, bbox_inches="tight")

    return output_path


# ── Public entry point ────────────────────────────────────────────────────────

def _blank_figure(message: str) -> plt.Figure:
    """Return a plain figure with an error message, used as a fallback."""
    fig, ax = plt.subplots(figsize=(9, 5))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#f8f8f8")
    ax.text(0.5, 0.5, message, ha="center", va="center",
            fontsize=11, color="#888888", transform=ax.transAxes, wrap=True)
    ax.axis("off")
    fig.tight_layout()
    return fig


def build_graphs(analysis: dict, client: Anthropic) -> list[plt.Figure]:
    """
    Extract graph data from the analysis JSON using Claude, then build and
    return three matplotlib figures.

    Args:
        analysis: The scored analysis dict from DueDiligenceAnalyzer.
        client:   An initialised anthropic.Anthropic client.

    Returns:
        [fig1, fig2, fig3]  — ready for st.pyplot() or PDF embedding.
    """
    try:
        graph_data = _extract_graph_data(analysis, client)
    except Exception as e:
        msg = f"Chart data extraction failed: {e}"
        return [_blank_figure(msg)] * 3

    figs = []
    for build_fn in (_graph1, _graph2, _graph3):
        try:
            figs.append(build_fn(graph_data))
        except Exception as e:
            figs.append(_blank_figure(f"Chart unavailable: {e}"))

    return figs
