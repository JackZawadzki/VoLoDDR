"""
ddr_report_v2.py
================
All output generation for the VoLo DDR V2 tool.

V2 changes from V1:
  - Single PDF with inline charts (no separate charts PDF, no merge)
  - Combined claims table (TECHNOLOGY + MARKET in one table with Type column)
  - Only CRITICAL + HIGH unverified claims (skip MEDIUM/LOW)
  - Condensed competitor entries, status flags, and overview
  - 10pt body font for dense sections
  - Target: 10-12 pages total

Reused verbatim from V1: all chart functions, color constants, escaping,
_build_styles(), _p(), _dollar(), _esc()
"""

import io
import re
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image,
)
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY

# ── Shared Colors ────────────────────────────────────────────────────────────

VOLO_GREEN    = "#2d5f3f"
VOLO_LIGHT    = "#3a7d52"
VOLO_PALE     = "#eef7f1"
ACCENT_ORANGE = "#e07b39"
ACCENT_BLUE   = "#3a6ea8"
ACCENT_PURPLE = "#7b5ea7"
GRID_COLOR    = "#d4e6da"
TEXT_DARK     = "#1a1a1a"
TEXT_MID      = "#4a4a4a"


# ═══════════════════════════════════════════════════════════════════════════════
#  PART 1 — PDF REPORT (ReportLab)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Escaping ─────────────────────────────────────────────────────────────────

def _esc(text) -> str:
    """Escape special ReportLab/XML characters in dynamic text."""
    if not isinstance(text, str):
        text = str(text)
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("$", "&#36;"))


# Regex matching the ReportLab tags we want to PRESERVE (not escape)
_SAFE_TAG_RE = re.compile(
    r'</?(?:b|i|u|br|br/|super|sub|font|a|para|seq|seqreset|onDraw|index|img)(?:\s[^>]*)?>',
    re.IGNORECASE,
)

# Regex matching HTML/XML entities we want to PRESERVE (not double-escape)
_ENTITY_RE = re.compile(r'&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);')


def _esc_preserving_entities(text: str) -> str:
    """Escape text but preserve any existing HTML entities from double-escaping."""
    parts = _ENTITY_RE.split(text)
    entities = _ENTITY_RE.findall(text)
    escaped = [_esc(p) for p in parts]
    result = []
    for i, part in enumerate(escaped):
        result.append(part)
        if i < len(entities):
            result.append(entities[i])
    return "".join(result)


def _p(text, style) -> Paragraph:
    """
    Create a ReportLab Paragraph with auto-escaping.

    Preserves known markup tags (<b>, <i>, <br/>, etc.) AND existing HTML
    entities (&nbsp;, &#36;, &amp;, etc.) while escaping everything else.
    """
    if not isinstance(text, str):
        text = str(text)

    parts = _SAFE_TAG_RE.split(text)
    tags = _SAFE_TAG_RE.findall(text)

    escaped_parts = [_esc_preserving_entities(p) for p in parts]

    result = []
    for i, part in enumerate(escaped_parts):
        result.append(part)
        if i < len(tags):
            result.append(tags[i])

    return Paragraph("".join(result), style)


def _dollar(amount_usd: float) -> str:
    """Format a USD amount with a dollar sign for ReportLab (entity-safe)."""
    if amount_usd >= 1e9:
        return f"&#36;{amount_usd / 1e9:.1f}B"
    elif amount_usd > 0:
        return f"&#36;{amount_usd / 1e6:.0f}M"
    return "Not quantified"


# ── PDF Styles ───────────────────────────────────────────────────────────────

def _build_styles():
    """Build and return all ReportLab ParagraphStyles used in the V2 report."""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            'CustomTitle', parent=base['Heading1'],
            fontSize=24, textColor=colors.HexColor('#2d5f3f'),
            spaceAfter=16, alignment=TA_CENTER, fontName='Helvetica-Bold',
        ),
        "heading": ParagraphStyle(
            'CustomHeading', parent=base['Heading2'],
            fontSize=15, textColor=colors.HexColor('#2d5f3f'),
            spaceAfter=10, spaceBefore=16, fontName='Helvetica-Bold',
        ),
        "subheading": ParagraphStyle(
            'CustomSubheading', parent=base['Heading3'],
            fontSize=12, textColor=colors.HexColor('#1a472a'),
            spaceAfter=6, spaceBefore=10, fontName='Helvetica-Bold',
        ),
        "body": ParagraphStyle(
            'CustomBody', parent=base['BodyText'],
            fontSize=10, leading=14, spaceAfter=8, alignment=TA_JUSTIFY,
        ),
        "body_small": ParagraphStyle(
            'CustomBodySmall', parent=base['BodyText'],
            fontSize=9, leading=12, spaceAfter=6, alignment=TA_JUSTIFY,
        ),
        "alert": ParagraphStyle(
            'Alert', parent=base['BodyText'],
            fontSize=10, leading=14, spaceAfter=8,
        ),
        "flag": ParagraphStyle(
            'Flag', parent=base['BodyText'],
            fontSize=10, leading=14, spaceAfter=8,
        ),
        "verified": ParagraphStyle(
            'Verified', parent=base['BodyText'],
            fontSize=10, leading=14, spaceAfter=8,
        ),
    }


# ── Figure to ReportLab Image ───────────────────────────────────────────────

def _fig_to_image(fig, width=6.5*inch, height=4.0*inch) -> Image:
    """Convert a matplotlib figure to a ReportLab Image flowable."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=width, height=height)


# ── PDF Generation ───────────────────────────────────────────────────────────

def generate_report_pdf(analysis: dict, graph_data: dict, figs: list,
                        output_path: str):
    """
    Generate the complete V2 due diligence PDF report with inline charts.

    Layout (~10-12 pages):
      Page 1:   Title, overview, status flags
      Page 2:   Competitive landscape
      Page 3-4: Combined claims table + CRITICAL/HIGH unverified claims
      Page 5:   Outcome magnitude + conclusion
      Page 6:   Sources
      Page 7-10: Charts (one per page)

    Args:
        analysis:    Full analysis dict from ddr_engine_v2.analyze()
        graph_data:  The graph_data sub-dict (with graph1, graph2, graph3)
        figs:        List of 4 matplotlib figures from build_charts()
        output_path: Where to write the PDF
    """
    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        topMargin=0.65 * inch, bottomMargin=0.65 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
    )

    S = _build_styles()
    story = []

    # ── PAGE 1: TITLE, OVERVIEW & STATUS FLAGS ───────────────────────────
    story.append(_p("DUE DILIGENCE REPORT", S["title"]))
    story.append(Spacer(1, 0.1 * inch))

    company = analysis.get('company_name', 'Unknown')
    industry = analysis.get('industry', 'Unknown')

    story.append(_p(f"<b>{company}</b>", S["heading"]))
    story.append(_p(
        f"Industry: {industry} &nbsp;|&nbsp; "
        f"Report Date: {datetime.now().strftime('%B %d, %Y')}",
        S["body"],
    ))
    story.append(Spacer(1, 0.15 * inch))

    # Company overview
    overview = analysis.get('company_overview', {})
    story.append(_p("COMPANY OVERVIEW", S["heading"]))
    story.append(_p(overview.get('description', 'Not available'), S["body"]))
    story.append(_p(f"<b>Stage:</b> {overview.get('stage', 'Unknown')}", S["body"]))

    # Status flags — compact block
    status = analysis.get('status_flags', {})
    overall = status.get('overall_status', 'UNKNOWN')

    if overall in ['DISTRESSED', 'CRITICAL']:
        story.append(Spacer(1, 0.08 * inch))
        story.append(_p(
            f"<b>Company Status: {overall}</b> — {status.get('notes', '')}",
            S["alert"],
        ))

    # Compact flag line
    bank = status.get('bankruptcy_insolvency', {})
    fund = status.get('recent_funding', {})
    ip = status.get('ip_status', {})
    lit = status.get('active_litigation', {})

    flags = []
    bank_status = bank.get('status', 'UNKNOWN')
    if bank_status not in ['NONE FOUND', 'UNKNOWN', 'ACTIVE'] and bank.get('details'):
        flags.append(f"Bankruptcy ({bank_status}): {bank['details']}")
    fund_outcome = fund.get('outcome', 'UNKNOWN')
    if fund_outcome == 'FAILED' and fund.get('failure_reasons'):
        flags.append(f"Failed funding: {fund.get('failure_reasons', 'Not disclosed')}")
    ip_status = ip.get('status', 'UNKNOWN')
    if ip_status in ['DISPUTED', 'ENCUMBERED'] and ip.get('details'):
        flags.append(f"IP {ip_status}: {ip['details']}")
    lawsuits = lit.get('lawsuits', [])
    if lawsuits:
        flags.append(f"Litigation: {'; '.join(lawsuits[:2])}")
    if flags:
        story.append(_p(
            "<b>Flags:</b> " + " | ".join(flags),
            S["body_small"],
        ))
    elif overall not in ['DISTRESSED', 'CRITICAL'] and status.get('notes'):
        story.append(_p(f"<b>Background:</b> {status['notes']}", S["body_small"]))

    story.append(PageBreak())

    # ── PAGE 2: COMPETITIVE LANDSCAPE ────────────────────────────────────
    comp = analysis.get('competitive_landscape', {})
    story.append(_p("COMPETITIVE LANDSCAPE", S["heading"]))
    story.append(_p(comp.get('positioning_summary', ''), S["body"]))
    story.append(Spacer(1, 0.1 * inch))

    # Peer competitors — condensed
    peers = comp.get('peer_competitors', [])
    if peers:
        story.append(_p("Peer-Stage Competitors", S["subheading"]))
        for p in peers:
            funding = p.get('funding_raised_usd') or 0
            funding_str = _dollar(funding) + " raised" if funding else "Funding unknown"
            story.append(_p(
                f"<b>{p.get('name', 'Unknown')}</b> "
                f"({p.get('stage', '?')} — {funding_str}): "
                f"{p.get('description', '')}"
                + (f" <i>[{', '.join(p['sources'][:2])}]</i>" if p.get('sources') else ""),
                S["body_small"],
            ))
            story.append(Spacer(1, 0.04 * inch))

    # Market leaders — condensed
    leaders = comp.get('market_leaders', [])
    if leaders:
        story.append(Spacer(1, 0.06 * inch))
        story.append(_p("Market Leaders &amp; Incumbents", S["subheading"]))
        for ldr in leaders:
            story.append(_p(
                f"<b>{ldr.get('name', 'Unknown')}</b> — "
                f"{ldr.get('market_position', '')} "
                f"({ldr.get('valuation_or_revenue', '')}): "
                f"{ldr.get('description', '')}"
                + (f" <i>[{', '.join(ldr['sources'][:2])}]</i>" if ldr.get('sources') else ""),
                S["body_small"],
            ))
            story.append(Spacer(1, 0.04 * inch))

    # Risks + acquirers — inline
    risks = comp.get('competitive_risks', [])
    acquirers = comp.get('potential_acquirers', [])
    if risks:
        story.append(Spacer(1, 0.06 * inch))
        story.append(_p(
            "<b>Competitive Risks:</b> " + " · ".join(risks),
            S["body_small"],
        ))
    if acquirers:
        story.append(_p(
            "<b>Potential Acquirers:</b> " + " · ".join(acquirers),
            S["body_small"],
        ))

    story.append(PageBreak())

    # ── PAGE 3: COMBINED CLAIMS TABLE ────────────────────────────────────
    claims = analysis.get('claims', [])
    story.append(_p("CLAIMS ASSESSMENT", S["heading"]))
    story.append(_p(
        "<i>Quick-scan status of all technology and market claims.</i>",
        S["body_small"],
    ))
    story.append(Spacer(1, 0.08 * inch))

    for cl in claims:
        cl_type = cl.get('type', 'OTHER')[:4].upper()
        v_status = cl.get('verification_status', 'UNVERIFIED')
        use_style = (S["verified"] if v_status == 'VERIFIED'
                     else S["flag"] if v_status == 'PARTIALLY VERIFIED'
                     else S["alert"])
        label = ('✅' if v_status == 'VERIFIED'
                 else '⚠️' if v_status == 'PARTIALLY VERIFIED'
                 else '❌')

        text = (
            f"<b>[{cl_type}] {label} {cl.get('claim', 'N/A')}</b><br/>"
            f"{cl.get('source_label', v_status)}"
        )
        if cl.get('sources'):
            text += f" — <i>{', '.join(cl['sources'][:2])}</i>"
        story.append(_p(text, use_style))
        story.append(Spacer(1, 0.04 * inch))

    # ── UNVERIFIED CLAIMS (CRITICAL + HIGH only) ─────────────────────────
    unverified = analysis.get('unverified_claims', [])
    priority_order = ['CRITICAL', 'HIGH']
    uv_filtered = sorted(
        [uc for uc in unverified if uc.get('priority', 'LOW') in priority_order],
        key=lambda c: priority_order.index(c.get('priority', 'HIGH'))
        if c.get('priority', 'HIGH') in priority_order else 1,
    )

    if uv_filtered:
        story.append(Spacer(1, 0.12 * inch))
        story.append(_p("UNVERIFIED CLAIMS — Investigation &amp; Outcomes", S["heading"]))
        story.append(_p(
            "<i>Only CRITICAL and HIGH priority claims shown. Each includes "
            "investigation steps and potential outcome if verified.</i>",
            S["body_small"],
        ))
        story.append(Spacer(1, 0.06 * inch))

        for idx, uc in enumerate(uv_filtered, 1):
            priority = uc.get('priority', 'HIGH')
            outcome = uc.get('outcome_if_true') or {}
            mkt_usd = outcome.get('market_opportunity_usd') or 0
            mkt_str = _dollar(mkt_usd)
            use_style = S["alert"] if priority == 'CRITICAL' else S["flag"]

            story.append(_p(
                f"<b>#{idx} [{priority}] {uc.get('claim', 'Not specified')}</b><br/>"
                f"<b>Why Unverified:</b> {uc.get('why_unverified', 'No independent verification')}",
                use_style,
            ))

            steps = uc.get('investigation_steps', [])
            if steps:
                step_parts = " | ".join(f"({j+1}) {s}" for j, s in enumerate(steps))
                story.append(_p(f"<b>Steps:</b> {step_parts}", S["body_small"]))

            if outcome:
                story.append(_p(
                    f"<b>If Verified:</b> {outcome.get('description', '')} "
                    f"— Opportunity: <b>{mkt_str}</b>",
                    S["body_small"],
                ))
                for cmp in outcome.get('comparable_companies', []):
                    val = cmp.get('comparable_valuation_usd') or 0
                    val_str = f" ({_dollar(val)})" if val else ""
                    story.append(_p(
                        f"↳ <b>{cmp.get('company', 'N/A')}</b>{val_str}: "
                        f"{cmp.get('context', '')}",
                        S["body_small"],
                    ))
                if outcome.get('key_caveat'):
                    story.append(_p(
                        f"<i>Caveat: {outcome['key_caveat']}</i>",
                        S["body_small"],
                    ))

            story.append(Spacer(1, 0.12 * inch))

    story.append(PageBreak())

    # ── PAGE 5: OUTCOME MAGNITUDE + CONCLUSION ───────────────────────────
    story.append(_p("OUTCOME MAGNITUDE", S["heading"]))
    story.append(_p(
        "<i>If the major claims hold up, what could this company become?</i>",
        S["body_small"],
    ))
    story.append(Spacer(1, 0.12 * inch))

    magnitude = analysis.get('outcome_magnitude', {})

    if_all = magnitude.get('if_all_claims_verified', {})
    if if_all:
        story.append(_p("If All Major Claims Are Verified:", S["subheading"]))
        story.append(_p(if_all.get('description', 'Not available'), S["body"]))
        story.append(_p(if_all.get('framing', ''), S["body_small"]))
        mkt = if_all.get('addressable_market_usd') or 0
        share = if_all.get('realistic_market_share_pct') or 0
        details = f"<b>Market:</b> {_dollar(mkt)} &nbsp;|&nbsp; <b>Share:</b> {share}%"
        if if_all.get('comparable_companies'):
            details += f" &nbsp;|&nbsp; <b>Comps:</b> {', '.join(if_all['comparable_companies'])}"
        story.append(_p(details, S["body_small"]))
        score = if_all.get('ai_confidence')
        if score is not None:
            story.append(_p(f"<b>AI Confidence:</b> {score:.0%}", S["body_small"]))
        story.append(Spacer(1, 0.12 * inch))

    if_core = magnitude.get('if_core_tech_only_verified', {})
    if if_core:
        story.append(_p("If Only Core Technology Is Verified:", S["subheading"]))
        story.append(_p(if_core.get('description', 'Not available'), S["body"]))
        story.append(_p(if_core.get('framing', ''), S["body_small"]))
        mkt = if_core.get('addressable_market_usd') or 0
        details = f"<b>Market:</b> {_dollar(mkt)}"
        if if_core.get('comparable_companies'):
            details += f" &nbsp;|&nbsp; <b>Comps:</b> {', '.join(if_core['comparable_companies'])}"
        story.append(_p(details, S["body_small"]))
        score = if_core.get('ai_confidence')
        if score is not None:
            story.append(_p(f"<b>AI Confidence:</b> {score:.0%}", S["body_small"]))
        story.append(Spacer(1, 0.12 * inch))

    deps = magnitude.get('key_dependencies', [])
    if deps:
        story.append(_p("What Must Be Proven First:", S["subheading"]))
        for dep in deps:
            story.append(_p(f"• {dep}", S["body_small"]))

    story.append(Spacer(1, 0.2 * inch))

    # ── CONCLUSION ───────────────────────────────────────────────────────
    story.append(_p("CONCLUSION", S["heading"]))

    critical_claims = [uc for uc in unverified if uc.get('priority') == 'CRITICAL']
    high_claims = [uc for uc in unverified if uc.get('priority') == 'HIGH']

    story.append(_p(
        f"This report identified <b>{len(unverified)} unverified claims</b> across "
        f"{company}'s pitch deck, of which <b>{len(critical_claims)} are critical</b> and "
        f"<b>{len(high_claims)} are high priority</b>.",
        S["body"],
    ))

    if critical_claims:
        story.append(_p("Critical Claims Requiring Immediate Investigation:", S["subheading"]))
        for uc in critical_claims:
            outcome = uc.get('outcome_if_true') or {}
            mkt_usd = outcome.get('market_opportunity_usd') or 0
            story.append(_p(
                f"• <b>{uc.get('claim', 'N/A')}</b> — {_dollar(mkt_usd)}",
                S["body_small"],
            ))

    if if_all.get('framing'):
        story.append(Spacer(1, 0.1 * inch))
        story.append(_p(if_all.get('framing', ''), S["body_small"]))

    story.append(Spacer(1, 0.15 * inch))
    story.append(_p(
        f"<i><b>Methodology:</b> Analysis based on {analysis.get('sources_consulted', '?')} sources. "
        f"AI confidence scores shown only on significant analytical conclusions. "
        f"No investment recommendation is made.</i><br/>"
        f"<b>Generated:</b> {datetime.now().strftime('%B %d, %Y at %H:%M:%S')}",
        S["body_small"],
    ))

    # ── SOURCES PAGE ─────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(_p("SOURCES", S["heading"]))

    src_style = ParagraphStyle(
        'SrcItem', parent=S["body_small"],
        fontSize=8, leading=10, spaceAfter=1, spaceBefore=0,
        textColor=colors.HexColor('#333333'),
    )
    src_heading_style = ParagraphStyle(
        'SrcHeading', parent=S["body_small"],
        fontSize=9, leading=12, spaceAfter=2, spaceBefore=6,
        fontName='Helvetica-Bold', textColor=colors.HexColor('#2d5f3f'),
    )

    section_sources = {}

    def _collect(obj, section_label):
        if isinstance(obj, dict):
            for key in ('sources', 'source', 'current_best_source'):
                val = obj.get(key)
                if isinstance(val, list):
                    for s in val:
                        if isinstance(s, str) and s.strip():
                            section_sources.setdefault(section_label, []).append(s.strip())
                elif isinstance(val, str) and val.strip():
                    section_sources.setdefault(section_label, []).append(val.strip())
            for key in ('source_note', 'note'):
                val = obj.get(key)
                if isinstance(val, str) and val.strip():
                    section_sources.setdefault(section_label, []).append(val.strip())
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    _collect(v, section_label)
        elif isinstance(obj, list):
            for item in obj:
                _collect(item, section_label)

    _collect(analysis.get('claims', []), 'Claims')
    _collect(analysis.get('unverified_claims', []), 'Unverified Claims')
    _collect(analysis.get('competitive_landscape', {}), 'Competitive Landscape')
    _collect(analysis.get('status_flags', {}), 'Status & Legal')
    _collect(analysis.get('outcome_magnitude', {}), 'Outcome Magnitude')
    _collect(analysis.get('graph_data', {}), 'Graph Data')

    total_unique = set()
    for section_label in ['Claims', 'Competitive Landscape', 'Status & Legal',
                          'Unverified Claims', 'Outcome Magnitude', 'Graph Data']:
        sources = section_sources.get(section_label, [])
        if not sources:
            continue
        seen = set()
        unique = []
        for s in sources:
            key = s.lower()
            if key not in seen:
                seen.add(key)
                unique.append(s)
                total_unique.add(key)
        story.append(_p(
            f"<b>{section_label}:</b> {' · '.join(unique)}",
            src_heading_style,
        ))

    story.append(Spacer(1, 0.1 * inch))
    story.append(_p(
        f"<b>Total unique sources cited:</b> {len(total_unique)}",
        src_style,
    ))

    # ── CHART PAGES (one per page) ───────────────────────────────────────
    chart_titles = [
        "Revenue Trajectory vs. Peers",
        "Market Size — TAM & SAM",
        "Technology Benchmark — Competitor Table",
        "Technology Benchmark — Strip Chart",
    ]
    for i, fig in enumerate(figs):
        story.append(PageBreak())
        if i < len(chart_titles):
            story.append(_p(chart_titles[i], S["heading"]))
            story.append(Spacer(1, 0.1 * inch))
        story.append(_fig_to_image(fig, width=6.5*inch, height=4.5*inch))

    doc.build(story)


# ═══════════════════════════════════════════════════════════════════════════════
#  PART 2 — MATPLOTLIB CHARTS (copied verbatim from V1)
# ═══════════════════════════════════════════════════════════════════════════════

def _add_ai_watermark(fig):
    """Add a subtle 'AI Estimates' watermark to a figure."""
    fig.text(
        0.99, 0.01,
        "⚠ AI Estimates — Illustrative Only · Verify before use",
        ha="right", va="bottom", fontsize=7, color="#aaaaaa",
        style="italic", transform=fig.transFigure,
    )


def _apply_base_style(ax, title, xlabel, ylabel):
    """Apply consistent VoLo styling to a matplotlib axes."""
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
        return f"${x / 1_000:.1f}B"
    return f"${x:.0f}M"


def _billions(x, _):
    return f"${x:.0f}B"


# ── Chart 1: Company revenue vs. peers ───────────────────────────────────────

def _chart_revenue(data: dict) -> plt.Figure:
    g = data["graph1"]
    company = data["company_name"]
    years_c = g["years"]
    rev_c = g["company_revenue_usd_m"]
    peers = g["peers"]
    note = g.get("note", "")

    fig, ax = plt.subplots(figsize=(9, 5))
    fig.patch.set_facecolor("white")

    _apply_base_style(
        ax,
        title=f"{company} Revenue Trajectory vs. Established Peers",
        xlabel="Year",
        ylabel="Revenue (USD)",
    )

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


# ── Chart 2: TAM + SAM market growth ────────────────────────────────────────

def _chart_market(data: dict) -> plt.Figure:
    g = data["graph2"]
    years = g["years"]
    tam = g["tam_usd_b"]
    sam = g["sam_usd_b"]
    tam_lbl = g.get("tam_label", "Global Market (TAM)")
    sam_lbl = g.get("sam_label", "Serviceable Market (SAM)")
    src_note = g.get("source_note", "")

    fig, ax = plt.subplots(figsize=(9, 5))
    fig.patch.set_facecolor("white")

    _apply_base_style(
        ax,
        title="Market Size Over Time — TAM & SAM",
        xlabel="Year",
        ylabel="Market Size (USD Billions)",
    )

    ax.fill_between(years, tam, alpha=0.15, color=VOLO_GREEN)
    ax.plot(years, tam, color=VOLO_GREEN, linewidth=2.5,
            marker="o", markersize=5, label=tam_lbl)

    ax.fill_between(years, sam, alpha=0.25, color=ACCENT_BLUE)
    ax.plot(years, sam, color=ACCENT_BLUE, linewidth=2.5,
            marker="s", markersize=5, linestyle="--", label=sam_lbl)

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


# ── Chart 3: Technology benchmark — table + strip chart ──────────────────────

_STAGE_STYLE = {
    "production": {"marker": "o", "color": ACCENT_BLUE,   "label": "Production"},
    "target":     {"marker": "^", "color": ACCENT_ORANGE,  "label": "Target / Roadmap"},
    "prototype":  {"marker": "D", "color": ACCENT_PURPLE, "label": "Prototype / Lab"},
}
_STAGE_LABELS = {"production": "Prod.", "target": "Target", "prototype": "Proto."}


def _parse_graph3(data: dict) -> dict:
    """Parse graph3 data into a flat dict used by both chart functions."""
    g = data["graph3"]
    company = data.get("company_name", g.get("company_name", "Company"))
    competitors = g["competitor_claims"]
    higher_better = g.get("higher_is_better", True)

    has_stage_data = any("stage" in c for c in competitors)
    for c in competitors:
        if "stage" not in c:
            c["stage"] = "target"

    comp_values = [c["value"] for c in competitors]
    company_val = g["company_claim"]
    all_values = comp_values + [company_val]
    sorted_comps = sorted(competitors, key=lambda c: c["value"], reverse=higher_better)

    return {
        "g": g,
        "company": company,
        "metric_name": g["metric_name"],
        "metric_unit": g["metric_unit"],
        "target_year": g.get("target_year", ""),
        "company_val": company_val,
        "company_stage": g.get("company_claim_stage", "target"),
        "competitors": competitors,
        "higher_better": higher_better,
        "current_best": g.get("current_best_in_class"),
        "conditions_note": g.get("conditions_note", ""),
        "measurement_basis": g.get("measurement_basis", ""),
        "has_stage_data": has_stage_data,
        "comp_values": comp_values,
        "all_values": all_values,
        "sorted_comps": sorted_comps,
        "p10": np.percentile(comp_values, 10) if len(comp_values) >= 3 else None,
        "p50": np.percentile(comp_values, 50),
        "p90": np.percentile(comp_values, 90) if len(comp_values) >= 3 else None,
    }


def _chart_tech_table(data: dict) -> plt.Figure:
    """Standalone competitor benchmark table (one full page)."""
    d = _parse_graph3(data)
    sorted_comps = d["sorted_comps"]
    company = d["company"]
    company_val = d["company_val"]
    company_stage = d["company_stage"]
    metric_unit = d["metric_unit"]
    metric_name = d["metric_name"]
    target_year = d["target_year"]
    measurement_basis = d["measurement_basis"]

    n_rows = len(sorted_comps) + 1
    fig_h = max(5, n_rows * 0.5 + 2)
    fig, ax_tbl = plt.subplots(figsize=(10, fig_h))
    fig.patch.set_facecolor("white")

    ax_tbl.axis("off")
    year_str = f" (Target ~{target_year})" if target_year else ""
    basis_str = f" — {measurement_basis}" if measurement_basis else ""
    ax_tbl.set_title(
        f"Technology Benchmark — {metric_name} ({metric_unit}){year_str}{basis_str}",
        fontsize=13, fontweight="bold", color=TEXT_DARK, pad=12,
    )

    tbl_data = []
    for i, c in enumerate(sorted_comps):
        name = c["name"][:35] if len(c["name"]) > 35 else c["name"]
        stage_lbl = _STAGE_LABELS.get(c.get("stage", "target"), "Target")
        src = c.get("source", "")[:45]
        tbl_data.append([str(i + 1), name, f"{c['value']:.4g}", stage_lbl, src])
    company_stage_lbl = _STAGE_LABELS.get(company_stage, "Target")
    tbl_data.append(["*", company[:35], f"{company_val:.4g}", company_stage_lbl, "Pitch deck"])

    tbl = ax_tbl.table(
        cellText=tbl_data,
        colLabels=["#", "Company", metric_unit, "Stage", "Source"],
        loc="upper center",
        cellLoc="left",
        colWidths=[0.05, 0.30, 0.15, 0.12, 0.38],
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10)

    row_h = max(0.045, 0.6 / max(n_rows, 3))
    header_h = row_h * 1.3

    for (row, col), cell in tbl.get_celld().items():
        cell.set_edgecolor("#d4e6da")
        cell.set_linewidth(0.5)
        if row == 0:
            cell.set_facecolor(VOLO_GREEN)
            cell.set_text_props(color="white", fontweight="bold")
            cell.set_height(header_h)
        elif row == len(tbl_data):
            cell.set_facecolor("#e8f5e9")
            cell.set_text_props(fontweight="bold", color=VOLO_GREEN)
            cell.set_height(row_h)
        else:
            cell.set_facecolor("white" if row % 2 == 1 else "#f8fbf9")
            cell.set_height(row_h)

    _add_ai_watermark(fig)
    fig.tight_layout()
    return fig


def _chart_tech_strip(data: dict) -> plt.Figure:
    """Standalone strip chart visualization (one full page)."""
    d = _parse_graph3(data)
    company = d["company"]
    company_val = d["company_val"]
    metric_name = d["metric_name"]
    metric_unit = d["metric_unit"]
    competitors = d["competitors"]
    higher_better = d["higher_better"]
    current_best = d["current_best"]
    conditions_note = d["conditions_note"]
    has_stage_data = d["has_stage_data"]
    all_values = d["all_values"]
    p10, p50, p90 = d["p10"], d["p50"], d["p90"]

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    for stage_key, style in _STAGE_STYLE.items():
        stage_comps = [c for c in competitors if c.get("stage", "target") == stage_key]
        if not stage_comps:
            continue
        x_vals = [c["value"] for c in stage_comps]
        n = len(stage_comps)
        y_vals = [(i - (n - 1) / 2) * 0.06 for i in range(n)]
        ax.scatter(
            x_vals, y_vals,
            marker=style["marker"], color=style["color"],
            s=100, zorder=10, edgecolors="white", linewidths=0.8,
            label=style["label"],
        )
        for idx, (c, yv) in enumerate(zip(stage_comps, y_vals)):
            offset_y = 10 if idx % 2 == 0 else -13
            va = "bottom" if idx % 2 == 0 else "top"
            ax.annotate(
                c["name"], (c["value"], yv),
                textcoords="offset points", xytext=(0, offset_y),
                fontsize=8, color=TEXT_MID, ha="center", va=va,
            )

    ax.scatter(
        [company_val], [0],
        marker="*", color=VOLO_GREEN, s=320, zorder=15,
        edgecolors="white", linewidths=1.0,
        label=f"{company} (claim)",
    )
    ax.annotate(
        f"{company}: {company_val:.4g} {metric_unit}",
        (company_val, 0),
        textcoords="offset points", xytext=(0, -18),
        fontsize=10, fontweight="bold", color=VOLO_GREEN,
        ha="center", va="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                  edgecolor=VOLO_GREEN, linewidth=1.5, alpha=0.95),
    )

    y_lo, y_hi = ax.get_ylim()
    pct_lines = []
    if p10 is not None:
        pct_lines.append((p10, "#c0392b", "P10"))
    pct_lines.append((p50, TEXT_MID, "P50 (median)"))
    if p90 is not None:
        pct_lines.append((p90, ACCENT_ORANGE, "P90"))

    for val, color, label in pct_lines:
        ax.axvline(val, color=color, linewidth=1.2, linestyle="--", alpha=0.5, zorder=3)
        ax.text(val, y_hi * 0.85, f"{label}: {val:.4g}",
                fontsize=8, color=color, fontweight="bold", ha="center",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                          edgecolor=color, alpha=0.85))

    if current_best is not None:
        ax.axvline(current_best, color="#888888", linewidth=1.2, linestyle=":",
                   alpha=0.6, zorder=3)
        ax.text(current_best, y_lo * 0.8,
                f"Best today: {current_best:.4g}",
                fontsize=7.5, color="#666666", ha="center",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#f5f5f5",
                          edgecolor="#bbbbbb", alpha=0.85))

    direction = "Higher = Better" if higher_better else "Lower = Better"
    ax.set_xlabel(f"{metric_name} ({metric_unit})  [{direction}]",
                  fontsize=11, color=TEXT_MID)
    ax.set_yticks([])
    ax.set_ylabel("")
    ax.set_title(f"{company} — Technology Claim vs. Competitive Landscape",
                 fontsize=13, fontweight="bold", color=TEXT_DARK, pad=12)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color(GRID_COLOR)

    x_pad = (max(all_values) - min(all_values)) * 0.15
    ax.set_xlim(min(all_values) - x_pad, max(all_values) + x_pad)

    ax.xaxis.grid(True, color=GRID_COLOR, linewidth=0.5, linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)

    ax.legend(fontsize=9, loc="upper right", framealpha=0.9,
              edgecolor=GRID_COLOR, ncol=1, handletextpad=0.5)

    n_comps = len(competitors)
    note_parts = [f"Based on {n_comps} competitor data points."]
    note_parts.append("P10/P50/P90 from raw values (no smoothing).")
    if conditions_note:
        note_parts.append(conditions_note)
    elif not has_stage_data:
        note_parts.append("Stage classification not available; all shown as targets.")
    methodology_text = " ".join(note_parts)
    fig.text(0.5, 0.01, methodology_text,
             ha="center", fontsize=7.5, color=TEXT_MID, style="italic",
             wrap=True)

    _add_ai_watermark(fig)
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.08)
    return fig


# ── Blank fallback ───────────────────────────────────────────────────────────

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


# ── Public API ───────────────────────────────────────────────────────────────

def build_charts(graph_data: dict) -> list:
    """
    Build four matplotlib figures from graph data dict.

    Args:
        graph_data: Dict with keys company_name, sector, graph1, graph2, graph3.

    Returns:
        [fig_revenue, fig_market, fig_tech_table, fig_tech_strip]
    """
    figs = []
    for build_fn in (_chart_revenue, _chart_market, _chart_tech_table, _chart_tech_strip):
        try:
            figs.append(build_fn(graph_data))
        except Exception as e:
            figs.append(_blank_figure(f"Chart unavailable: {e}"))
    return figs
