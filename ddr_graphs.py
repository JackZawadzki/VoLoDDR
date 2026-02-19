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
    3. Technology Performance Claims Distribution — maps the subject
       company's key performance claim against a statistical distribution
       of competitor claims for the same metric, with P10 / P50 / P90
       percentile overlays showing where the company sits

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

3. TECHNOLOGY PERFORMANCE CLAIMS DISTRIBUTION
   This chart maps the subject company's key performance claim against the full
   competitive landscape. The goal is technology forecasting — answering:
   "Is their claim credible relative to what everyone else is targeting?"

   Steps:
   a) Identify the SINGLE most important, quantifiable performance metric for this
      company's technology (examples: EV range in miles, solar cell efficiency %,
      battery energy density Wh/kg, carbon capture cost $/ton, wind turbine capacity MW,
      drug efficacy rate %, chip transistor density, data throughput Gbps, etc.).
   b) Find the subject company's specific claim/target for that metric and the
      year they claim to achieve it (the "target_year").
   c) Use WEB SEARCH extensively (at least 4-6 searches) to find as many competitor
      and industry claims/targets for the SAME metric around the SAME target year as
      possible. Search for "[metric] targets 2030", "[sector] performance benchmarks",
      "[competitor] [metric] roadmap", etc. You need at least 5 competitor data points,
      ideally 8-15+.
   d) Return ALL the raw data points so we can build the distribution.

   IMPORTANT: The metric should be whatever is most relevant to the company's core
   value proposition — it could be efficiency, cost, range, speed, density, yield,
   or any other measurable performance claim. Pick the ONE metric that matters most.

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
    "metric_name": "EV Range",
    "metric_unit": "miles",
    "target_year": 2030,
    "company_claim": 500,
    "competitor_claims": [
      {"name": "Honda", "value": 400, "source": "Honda EV roadmap 2024"},
      {"name": "Toyota", "value": 450, "source": "Toyota bZ press release"},
      {"name": "Tesla", "value": 520, "source": "Tesla investor day 2024"},
      {"name": "BMW", "value": 435, "source": "BMW Neue Klasse announcement"},
      {"name": "BYD", "value": 470, "source": "BYD Blade battery roadmap"}
    ],
    "higher_is_better": true,
    "current_best_in_class": 350,
    "current_best_source": "EPA ratings 2024",
    "rationale": "Metric chosen because range is the primary differentiator..."
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
            model="claude-opus-4-6",
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


# ── Graph 3: Technology Performance Claims Distribution ──────────────────────

def _graph3(data: dict) -> plt.Figure:
    g = data["graph3"]
    company      = data["company_name"]
    metric_name  = g["metric_name"]
    metric_unit  = g["metric_unit"]
    target_year  = g.get("target_year", "")
    company_val  = g["company_claim"]
    competitors  = g["competitor_claims"]
    higher_better = g.get("higher_is_better", True)
    current_best  = g.get("current_best_in_class")
    current_src   = g.get("current_best_source", "")
    rationale     = g.get("rationale", "")

    # Collect all competitor values
    comp_values = [c["value"] for c in competitors]
    comp_names  = [c["name"] for c in competitors]
    all_values  = comp_values + [company_val]

    # Build a kernel density estimate from competitor claims for the distribution curve
    from scipy.stats import gaussian_kde

    # Fit KDE on competitor claims only (the "landscape")
    if len(comp_values) >= 2:
        kde = gaussian_kde(comp_values, bw_method="silverman")
        x_pad = (max(all_values) - min(all_values)) * 0.3
        x_lo = min(all_values) - x_pad
        x_hi = max(all_values) + x_pad
        x_range = np.linspace(x_lo, x_hi, 500)
        density = kde(x_range)
    else:
        x_range = np.array([])
        density = np.array([])

    # Compute percentiles of the competitor landscape
    p10 = np.percentile(comp_values, 10)
    p50 = np.percentile(comp_values, 50)
    p90 = np.percentile(comp_values, 90)

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor("white")
    ax.set_facecolor(VOLO_PALE)

    # Plot distribution curve
    if len(x_range) > 0:
        ax.fill_between(x_range, density, alpha=0.18, color=ACCENT_BLUE)
        ax.plot(x_range, density, color=ACCENT_BLUE, linewidth=2, alpha=0.7)

    # Plot individual competitor claims as a strip / rug + labeled markers
    y_rug = -0.02 * max(density) if len(density) > 0 else -0.01
    comp_colors = ["#5b7ea8"] * len(competitors)

    for i, c in enumerate(competitors):
        ax.plot(c["value"], 0, marker="D", markersize=7, color="#5b7ea8",
                zorder=8, markeredgecolor="white", markeredgewidth=0.8)
        # Stagger labels to reduce overlap
        y_offset = -0.06 * (max(density) if len(density) > 0 else 1) * (1 + (i % 3) * 0.7)
        ax.annotate(
            c["name"],
            xy=(c["value"], 0), xytext=(c["value"], y_offset),
            fontsize=7, color="#5b7ea8", ha="center", va="top",
            fontweight="bold",
            arrowprops=dict(arrowstyle="-", color="#5b7ea8", lw=0.5),
        )

    # Percentile lines on the competitor distribution
    y_top = max(density) if len(density) > 0 else 1
    line_cfg = [
        (p10, "#c0392b", "P10"),
        (p50, VOLO_GREEN, "P50"),
        (p90, ACCENT_ORANGE, "P90"),
    ]
    for val, color, label in line_cfg:
        ax.axvline(val, color=color, linewidth=1.8, linestyle="--", alpha=0.7, zorder=5)
        ax.text(val, y_top * 1.02, f"{label}\n{val:.4g} {metric_unit}",
                ha="center", va="bottom", fontsize=7.5, color=color,
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.25", facecolor="white",
                          edgecolor=color, alpha=0.85))

    # Company claim — bold highlighted marker
    ax.axvline(company_val, color=VOLO_GREEN, linewidth=2.8, linestyle="-", zorder=9)
    # Place company label at top of chart
    ax.text(company_val, y_top * 1.14,
            f"{company}\n{company_val:.4g} {metric_unit}",
            ha="center", va="bottom", fontsize=9.5, color=VOLO_GREEN,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.35", facecolor="white",
                      edgecolor=VOLO_GREEN, linewidth=2, alpha=0.95))

    # Current best-in-class marker if provided
    if current_best is not None:
        ax.axvline(current_best, color="#888888", linewidth=1.5, linestyle=":",
                   zorder=4, alpha=0.7)
        ax.text(current_best, y_top * 0.85,
                f"Current Best\n{current_best:.4g} {metric_unit}",
                ha="center", va="top", fontsize=7, color="#666666",
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.25", facecolor="#f5f5f5",
                          edgecolor="#bbbbbb", alpha=0.85))

    year_str = f" (Target ~{target_year})" if target_year else ""
    direction = "→ Higher = Better" if higher_better else "→ Lower = Better"

    _apply_base_style(
        ax,
        title=f"{company} — Technology Claims vs. Competitive Landscape{year_str}",
        xlabel=f"{metric_name} ({metric_unit})  {direction}",
        ylabel="Density of Competitor Claims"
    )

    # Hide y-axis ticks (density values aren't meaningful to the reader)
    ax.set_yticks([])
    ax.set_ylabel("")

    # Extend y-axis to make room for labels
    ax.set_ylim(bottom=-0.25 * y_top, top=y_top * 1.35)

    ax.tick_params(axis="x", rotation=0)

    # Caption
    n_comps = len(competitors)
    caption = (
        f"Distribution built from {n_comps} competitor performance claims/targets "
        f"for {metric_name.lower()} ({metric_unit}). "
        f"P10/P50/P90 reflect the competitive landscape spread.\n"
    )
    if current_best and current_src:
        caption += f"Current best-in-class: {current_best:.4g} {metric_unit} ({current_src}). "
    if rationale:
        caption += rationale

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
        "Technology Performance Claims vs. Competitive Landscape",
    ]
    captions = [
        "Company's own revenue projections (dashed) plotted against real, publicly known peers in the same sector.\n"
        "Dashed line reflects unverified company claims.",
        "Global addressable market (TAM) and the company's serviceable sub-niche (SAM) based on independent industry research.",
        "Statistical distribution of competitor performance claims for the company's key technology metric.\n"
        "P10/P50/P90 reflect the competitive landscape. Company's claim shown as solid green line.",
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
    Build three matplotlib figures from graph data.

    If the analysis dict already contains a "graph_data" key (produced by the
    main Opus analysis call), those numbers are used directly — no extra API
    call needed.  If "graph_data" is missing, falls back to a separate Opus
    + web search call to get real data.

    Args:
        analysis: The scored analysis dict from DueDiligenceAnalyzer.
        client:   An initialised anthropic.Anthropic client (used only if
                  graph_data is missing from the analysis).

    Returns:
        [fig1, fig2, fig3]  — ready for st.pyplot() or PDF embedding.
    """
    graph_data = analysis.get("graph_data")

    if graph_data is None:
        # Fallback: separate Opus + web search call to get real data
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
