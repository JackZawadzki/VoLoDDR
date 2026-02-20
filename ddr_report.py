"""
ddr_report.py
=============
All output generation for the VoLo DDR tool.

Handles:
  - PDF due diligence report (ReportLab)
  - Three matplotlib analysis charts
  - Chart PDF export

Key feature: _p(text, style) auto-escaping wrapper eliminates manual _esc()
calls — all dynamic text is escaped automatically while preserving ReportLab
markup tags (<b>, <i>, <br/>).
"""

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
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
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
# Matches: &amp; &lt; &gt; &nbsp; &#36; &#123; etc.
_ENTITY_RE = re.compile(r'&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);')


def _esc_preserving_entities(text: str) -> str:
    """Escape text but preserve any existing HTML entities from double-escaping."""
    # Split on entities, escape the non-entity parts, reassemble
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

    # Split text into tags and non-tag chunks, escape only the non-tag parts
    parts = _SAFE_TAG_RE.split(text)
    tags = _SAFE_TAG_RE.findall(text)

    escaped_parts = [_esc_preserving_entities(p) for p in parts]

    # Interleave escaped parts with preserved tags
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
    """Build and return all ReportLab ParagraphStyles used in the report."""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            'CustomTitle', parent=base['Heading1'],
            fontSize=24, textColor=colors.HexColor('#2d5f3f'),
            spaceAfter=20, alignment=TA_CENTER, fontName='Helvetica-Bold',
        ),
        "heading": ParagraphStyle(
            'CustomHeading', parent=base['Heading2'],
            fontSize=16, textColor=colors.HexColor('#2d5f3f'),
            spaceAfter=12, spaceBefore=20, fontName='Helvetica-Bold',
        ),
        "subheading": ParagraphStyle(
            'CustomSubheading', parent=base['Heading3'],
            fontSize=13, textColor=colors.HexColor('#1a472a'),
            spaceAfter=8, spaceBefore=12, fontName='Helvetica-Bold',
        ),
        "body": ParagraphStyle(
            'CustomBody', parent=base['BodyText'],
            fontSize=11, leading=16, spaceAfter=12, alignment=TA_JUSTIFY,
        ),
        "alert": ParagraphStyle(
            'Alert', parent=base['BodyText'],
            fontSize=11, leading=16, spaceAfter=12,
        ),
        "flag": ParagraphStyle(
            'Flag', parent=base['BodyText'],
            fontSize=11, leading=16, spaceAfter=12,
        ),
        "verified": ParagraphStyle(
            'Verified', parent=base['BodyText'],
            fontSize=11, leading=16, spaceAfter=12,
        ),
    }


# ── PDF Generation ───────────────────────────────────────────────────────────

def generate_report_pdf(analysis: dict, output_path: str):
    """
    Generate the full due diligence PDF report.

    Same 7-page layout as the original:
      Page 1: Title, overview, financial/legal snapshot
      Page 2: Competitive landscape
      Page 3: Technology claims + unverified tech
      Page 4: Market claims + unverified market + other unverified
      Page 5: Outcome magnitude + conclusion
      Page 6: Sources page
    """
    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )

    S = _build_styles()
    story = []

    # ── PAGE 1: TITLE, OVERVIEW & FINANCIAL/LEGAL SNAPSHOT ───────────────
    story.append(_p("DUE DILIGENCE REPORT", S["title"]))
    story.append(Spacer(1, 0.15 * inch))

    company = analysis.get('company_name', 'Unknown')
    industry = analysis.get('industry', 'Unknown')

    story.append(_p(f"<b>{company}</b>", S["heading"]))
    story.append(_p(
        f"Industry: {industry} &nbsp;|&nbsp; "
        f"Report Date: {datetime.now().strftime('%B %d, %Y')}",
        S["body"],
    ))
    story.append(Spacer(1, 0.2 * inch))

    # Pull status data early
    status_obj = analysis.get('company_financial_legal_status', {})
    overall_status = status_obj.get('overall_status', 'UNKNOWN')

    if overall_status in ['DISTRESSED', 'CRITICAL']:
        story.append(_p(
            f"<b>⚠️ COMPANY STATUS ALERT: {overall_status}</b><br/>"
            f"{status_obj.get('notes', '')}",
            S["alert"],
        ))
        story.append(Spacer(1, 0.15 * inch))

    # Snapshot tables
    unverified = analysis.get('unverified_claims', [])
    priority_counts = {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
    for c in unverified:
        p = c.get('priority', 'LOW')
        priority_counts[p] = priority_counts.get(p, 0) + 1

    bank = status_obj.get('bankruptcy_insolvency', {})
    fund = status_obj.get('recent_funding', {})
    ip = status_obj.get('ip_ownership', {})
    lit = status_obj.get('litigation_liabilities', {})

    bank_status = bank.get('status', 'UNKNOWN')
    fund_outcome = fund.get('outcome', 'UNKNOWN')
    ip_status = ip.get('status', 'UNKNOWN')
    has_lit = bool(lit.get('active_lawsuits') or lit.get('outstanding_debts'))

    left_data = [
        ['UNVERIFIED CLAIMS', ''],
        ['Critical', str(priority_counts['CRITICAL'])],
        ['High', str(priority_counts['HIGH'])],
        ['Medium', str(priority_counts['MEDIUM'])],
        ['Low', str(priority_counts['LOW'])],
        ['Total', str(len(unverified))],
        ['Sources consulted', str(analysis.get('sources_consulted', '?'))],
    ]
    right_data = [
        ['FINANCIAL & LEGAL SNAPSHOT', ''],
        ['Company status', overall_status],
        ['Bankruptcy / insolvency', bank_status],
        ['Recent funding', fund_outcome],
        ['IP ownership', ip_status],
    ]

    def _snapshot_table(data):
        t = Table(data, colWidths=[3.5 * inch, 2.5 * inch])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2d5f3f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.white, colors.HexColor('#f5f5f5')]),
        ]))
        return t

    story.append(_snapshot_table(left_data))
    story.append(Spacer(1, 0.15 * inch))
    story.append(_snapshot_table(right_data))
    story.append(Spacer(1, 0.25 * inch))

    # Company overview
    overview = analysis.get('company_overview', {})
    story.append(_p("COMPANY OVERVIEW", S["heading"]))
    story.append(_p(overview.get('description', 'Not available'), S["body"]))
    story.append(_p(f"<b>Stage:</b> {overview.get('stage', 'Unknown')}", S["body"]))
    if status_obj.get('notes') and overall_status not in ['DISTRESSED', 'CRITICAL']:
        story.append(_p(f"<b>Background:</b> {status_obj['notes']}", S["body"]))

    # Weave any financial/legal flags into the overview as a brief note
    flags = []
    if bank_status not in ['NONE FOUND', 'UNKNOWN', 'ACTIVE'] and bank.get('details'):
        flags.append(f"Bankruptcy/Insolvency ({bank_status}): {bank['details']}")
    if fund_outcome == 'FAILED' and fund.get('failure_reasons'):
        sought = (fund.get('amount_sought') or 0) / 1e6
        flags.append(f"Failed funding round (sought {_dollar(sought * 1e6)}): {fund.get('failure_reasons', 'Reasons not disclosed')}")
    if ip_status in ['DISPUTED', 'ENCUMBERED'] and ip.get('details'):
        flags.append(f"IP {ip_status}: {ip.get('details', '')}")
    if has_lit:
        lawsuits = lit.get('active_lawsuits', [])
        flags.append(f"Active litigation: {'; '.join(lawsuits)}")
    if flags:
        story.append(_p(
            "<b>⚠️ Key Legal/Financial Flags:</b> " + " | ".join(flags),
            S["alert"],
        ))

    story.append(PageBreak())

    # ── Helper: render unverified claim block ────────────────────────────
    priority_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']

    def _render_unverified(uc, counter):
        priority = uc.get('priority', 'LOW')
        outcome = uc.get('outcome_if_true') or {}
        mkt_usd = outcome.get('market_opportunity_usd') or 0
        mkt_str = _dollar(mkt_usd)
        use_style = S["flag"] if priority in ['MEDIUM', 'LOW'] else S["alert"]

        score = uc.get('ai_confidence_score')
        conf_str = f" &nbsp;| &nbsp;Confidence: {score:.0%}" if score is not None else ""

        story.append(_p(
            f"<b>#{counter} [{priority}] {uc.get('claim', 'Not specified')}</b>{conf_str}<br/>"
            f"<b>Why Unverified:</b> {uc.get('why_unverified', 'No independent verification found')}",
            use_style,
        ))
        steps = uc.get('investigation_steps', [])
        if steps:
            step_parts = " &nbsp;|&nbsp; ".join(
                f"({j + 1}) {s}" for j, s in enumerate(steps)
            )
            story.append(_p(f"<b>Steps to Verify:</b> {step_parts}", S["body"]))
        if outcome:
            story.append(_p(
                f"<b>Outcome If Verified:</b> {outcome.get('description', '')} "
                f"— Opportunity: <b>{mkt_str}</b>",
                S["body"],
            ))
            for comp in outcome.get('comparable_companies', []):
                val = comp.get('comparable_valuation_usd') or 0
                val_str = f" — valued at {_dollar(val)}" if val else ""
                share_str = f" | {comp['market_share_potential']}" if comp.get('market_share_potential') else ""
                story.append(_p(
                    f"<b>↳ {comp.get('company', 'N/A')}</b>{val_str}: "
                    f"{comp.get('context', '')}{share_str}",
                    S["verified"],
                ))
            if outcome.get('key_caveat'):
                story.append(_p(f"<i>Caveat: {outcome['key_caveat']}</i>", S["body"]))
        story.append(Spacer(1, 0.2 * inch))

    # ── Helper: render claims table ──────────────────────────────────────
    def _render_claims_table(claims, include_sources=False):
        for claim in claims:
            v_status = claim.get('verification_status', 'UNVERIFIED')
            use_style = (S["verified"] if v_status == 'VERIFIED'
                         else S["flag"] if v_status == 'PARTIALLY VERIFIED'
                         else S["alert"])
            label = ('✅' if v_status == 'VERIFIED'
                     else '⚠️' if v_status == 'PARTIALLY VERIFIED'
                     else '❌')
            score = claim.get('ai_confidence_score')
            conf_str = f" &nbsp;| &nbsp;Confidence: {score:.0%}" if score is not None else ""

            text = (
                f"<b>{label} {claim.get('claim', 'Not specified')}</b>{conf_str}<br/>"
                f"{claim.get('source_label', v_status)}"
            )
            if include_sources and claim.get('sources'):
                text += f" — <i>{', '.join(claim['sources'][:3])}</i>"
            story.append(_p(text, use_style))
            story.append(Spacer(1, 0.08 * inch))

    # ── PAGE 2: COMPETITIVE LANDSCAPE ────────────────────────────────────
    comp_landscape = analysis.get('competitive_landscape', {})
    story.append(_p("COMPETITIVE LANDSCAPE", S["heading"]))
    story.append(_p(comp_landscape.get('positioning_summary', ''), S["body"]))
    story.append(Spacer(1, 0.15 * inch))

    # Peer competitors
    for comp in comp_landscape.get('peer_competitors', []):
        funding = comp.get('funding_raised_usd') or 0
        funding_str = _dollar(funding) + " raised" if funding else "Funding unknown"
        score = comp.get('ai_confidence_score')
        conf_tag = f" &nbsp;| &nbsp;Confidence: {score:.0%}" if score is not None else ""
        if comp_landscape.get('peer_competitors', []).index(comp) == 0:
            story.append(_p("Peer-Stage Competitors", S["subheading"]))
        story.append(_p(
            f"<b>{comp.get('name', 'Unknown')}</b> "
            f"({comp.get('stage', '?')} — {funding_str}){conf_tag}<br/>"
            f"{comp.get('description', '')}<br/>"
            f"<b>Their edge:</b> {comp.get('their_differentiator', 'N/A')}<br/>"
            f"<b>Company's claimed advantage:</b> {comp.get('company_advantage_claimed', 'N/A')}"
            + (f"<br/><i>Sources: {', '.join(comp['sources'][:3])}</i>" if comp.get('sources') else ""),
            S["body"],
        ))
        story.append(Spacer(1, 0.12 * inch))

    # Market leaders
    leaders = comp_landscape.get('market_leaders', [])
    if leaders:
        story.append(_p("Market Leaders &amp; Incumbents", S["subheading"]))
        for leader in leaders:
            score = leader.get('ai_confidence_score')
            conf_tag = f" &nbsp;| &nbsp;Confidence: {score:.0%}" if score is not None else ""
            story.append(_p(
                f"<b>{leader.get('name', 'Unknown')}</b> — "
                f"{leader.get('market_position', '')}{conf_tag}<br/>"
                f"{leader.get('valuation_or_revenue', '')}<br/>"
                f"{leader.get('description', '')}<br/>"
                f"<b>Threat to company:</b> {leader.get('threat_to_company', 'N/A')}"
                + (f"<br/><i>Sources: {', '.join(leader['sources'][:3])}</i>" if leader.get('sources') else ""),
                S["body"],
            ))
            story.append(Spacer(1, 0.12 * inch))

    risks = comp_landscape.get('competitive_risks', [])
    acquirers = comp_landscape.get('potential_acquirers', [])
    if risks:
        story.append(_p("<b>Key Competitive Risks:</b>", S["body"]))
        for r in risks:
            story.append(_p(f"• {r}", S["body"]))
    if acquirers:
        story.append(_p("<b>Potential Acquirers:</b>", S["body"]))
        for a in acquirers:
            story.append(_p(f"• {a}", S["body"]))

    story.append(PageBreak())

    # ── PAGE 3: TECHNOLOGY CLAIMS + UNVERIFIED TECH ──────────────────────
    story.append(_p("TECHNOLOGY CLAIMS", S["heading"]))
    story.append(_p(
        "<i>Quick-scan status of all technology claims. "
        "Unverified claims with full investigation detail and outcome sizing follow below.</i>",
        S["body"],
    ))
    story.append(Spacer(1, 0.1 * inch))

    _render_claims_table(analysis.get('technology_claims', []), include_sources=True)

    tech_unverified = sorted(
        [uc for uc in unverified if uc.get('category', '').lower() == 'technology'],
        key=lambda c: priority_order.index(c.get('priority', 'LOW'))
        if c.get('priority', 'LOW') in priority_order else 3,
    )
    counter = 1
    if tech_unverified:
        story.append(Spacer(1, 0.15 * inch))
        story.append(_p("Unverified Technology Claims — Investigation &amp; Outcome", S["subheading"]))
        story.append(Spacer(1, 0.05 * inch))
        for uc in tech_unverified:
            _render_unverified(uc, counter)
            counter += 1

    story.append(PageBreak())

    # ── PAGE 4: MARKET CLAIMS + UNVERIFIED MARKET + OTHER ────────────────
    story.append(_p("MARKET CLAIMS", S["heading"]))
    story.append(_p(
        "<i>Quick-scan status of all market claims. "
        "Unverified claims with full investigation detail and outcome sizing follow below.</i>",
        S["body"],
    ))
    story.append(Spacer(1, 0.1 * inch))

    _render_claims_table(analysis.get('market_claims', []), include_sources=True)

    market_unverified = sorted(
        [uc for uc in unverified if uc.get('category', '').lower() == 'market'],
        key=lambda c: priority_order.index(c.get('priority', 'LOW'))
        if c.get('priority', 'LOW') in priority_order else 3,
    )
    if market_unverified:
        story.append(Spacer(1, 0.15 * inch))
        story.append(_p("Unverified Market Claims — Investigation &amp; Outcome", S["subheading"]))
        story.append(Spacer(1, 0.05 * inch))
        for uc in market_unverified:
            _render_unverified(uc, counter)
            counter += 1

    other_unverified = sorted(
        [uc for uc in unverified if uc.get('category', '').lower() not in ('technology', 'market')],
        key=lambda c: priority_order.index(c.get('priority', 'LOW'))
        if c.get('priority', 'LOW') in priority_order else 3,
    )
    if other_unverified:
        story.append(Spacer(1, 0.15 * inch))
        story.append(_p("Other Unverified Claims (Financial / Team / Legal)", S["subheading"]))
        story.append(Spacer(1, 0.05 * inch))
        for uc in other_unverified:
            _render_unverified(uc, counter)
            counter += 1

    story.append(PageBreak())

    # ── PAGE 5: OUTCOME MAGNITUDE + CONCLUSION ───────────────────────────
    story.append(_p("OUTCOME MAGNITUDE", S["heading"]))
    story.append(_p(
        "<i>If the major claims hold up, what could this company become? "
        "Compared against real companies in the same space.</i>",
        S["body"],
    ))
    story.append(Spacer(1, 0.2 * inch))

    magnitude = analysis.get('outcome_magnitude', {})

    if_all = magnitude.get('if_all_claims_verified', {})
    if if_all:
        story.append(_p("If All Major Claims Are Verified:", S["subheading"]))
        story.append(_p(if_all.get('description', 'Not available'), S["body"]))
        story.append(_p(if_all.get('framing', ''), S["body"]))
        mkt = if_all.get('addressable_market_usd') or 0
        share = if_all.get('realistic_market_share_pct') or 0
        details = (
            f"<b>Addressable Market:</b> {_dollar(mkt)}<br/>"
            f"<b>Realistic Market Share:</b> {share}%<br/>"
        )
        if if_all.get('comparable_companies'):
            details += f"<b>Comparable Companies:</b> {', '.join(if_all['comparable_companies'])}<br/>"
        story.append(_p(details, S["body"]))
        story.append(Spacer(1, 0.2 * inch))

    if_core = magnitude.get('if_core_tech_only_verified', {})
    if if_core:
        story.append(_p("If Only Core Technology Is Verified:", S["subheading"]))
        story.append(_p(if_core.get('description', 'Not available'), S["body"]))
        story.append(_p(if_core.get('framing', ''), S["body"]))
        mkt = if_core.get('addressable_market_usd') or 0
        details = f"<b>Addressable Market:</b> {_dollar(mkt)}<br/>"
        if if_core.get('comparable_companies'):
            details += f"<b>Comparable Companies:</b> {', '.join(if_core['comparable_companies'])}<br/>"
        story.append(_p(details, S["body"]))
        story.append(Spacer(1, 0.2 * inch))

    deps = magnitude.get('key_dependencies', [])
    if deps:
        story.append(_p("What Must Be Proven First:", S["subheading"]))
        for dep in deps:
            story.append(_p(f"• {dep}", S["body"]))

    story.append(Spacer(1, 0.3 * inch))

    # ── CONCLUSION ───────────────────────────────────────────────────────
    story.append(_p("CONCLUSION", S["heading"]))

    critical_claims = [uc for uc in unverified if uc.get('priority') == 'CRITICAL']
    high_claims = [uc for uc in unverified if uc.get('priority') == 'HIGH']

    story.append(_p(
        f"This report identified <b>{len(unverified)} unverified claims</b> across "
        f"{company}'s pitch deck, of which <b>{len(critical_claims)} are critical</b> and "
        f"<b>{len(high_claims)} are high priority</b> for investigation.",
        S["body"],
    ))

    if critical_claims:
        story.append(_p("Critical Claims Requiring Immediate Investigation:", S["subheading"]))
        for uc in critical_claims:
            outcome = uc.get('outcome_if_true') or {}
            mkt_usd = outcome.get('market_opportunity_usd') or 0
            story.append(_p(
                f"• <b>{uc.get('claim', 'Not specified')}</b> — "
                f"potential outcome: {_dollar(mkt_usd)}",
                S["body"],
            ))

    if if_all.get('framing'):
        story.append(Spacer(1, 0.15 * inch))
        story.append(_p("Overall Opportunity Context:", S["subheading"]))
        story.append(_p(if_all.get('framing', ''), S["body"]))

    story.append(Spacer(1, 0.3 * inch))
    story.append(_p(
        f"<i><b>Methodology:</b> Analysis based on {analysis.get('sources_consulted', '?')} sources "
        f"including court records, financial databases, and industry reports. Confidence scores reflect "
        f"source quality, recency, and corroboration. No investment recommendation is made.</i><br/><br/>"
        f"<b>Report Generated:</b> {datetime.now().strftime('%B %d, %Y at %H:%M:%S')}",
        S["body"],
    ))

    # ── SOURCES PAGE (compact — fits on one page) ─────────────────────────
    story.append(PageBreak())
    story.append(_p("SOURCES", S["heading"]))

    # Compact styles for dense source listing
    src_heading = ParagraphStyle(
        'SrcHeading', parent=S["body"],
        fontSize=9, leading=12, spaceAfter=2, spaceBefore=6,
        fontName='Helvetica-Bold', textColor=colors.HexColor('#2d5f3f'),
    )
    src_item = ParagraphStyle(
        'SrcItem', parent=S["body"],
        fontSize=8, leading=10, spaceAfter=1, spaceBefore=0,
        textColor=colors.HexColor('#333333'),
    )

    section_sources = {}

    def _collect(obj, section_label):
        """Recursively gather source strings from lists and dicts."""
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

    _collect(analysis.get('technology_claims', []), 'Technology Claims')
    _collect(analysis.get('market_claims', []), 'Market Claims')
    _collect(analysis.get('unverified_claims', []), 'Unverified Claims')
    _collect(analysis.get('competitive_landscape', {}), 'Competitive Landscape')
    _collect(analysis.get('company_financial_legal_status', {}), 'Financial & Legal Status')
    _collect(analysis.get('outcome_magnitude', {}), 'Outcome Magnitude')
    _collect(analysis.get('graph_data', {}), 'Graph Data')

    total_unique = set()
    if section_sources:
        for section_label in ['Technology Claims', 'Market Claims',
                              'Competitive Landscape', 'Financial & Legal Status',
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

            # Section label + all sources as a single comma-separated line
            sources_line = " · ".join(unique)
            story.append(_p(f"<b>{section_label}:</b> {sources_line}", src_heading))

        story.append(Spacer(1, 0.1 * inch))
        story.append(_p(
            f"<b>Total unique sources cited:</b> {len(total_unique)}",
            src_item,
        ))
    else:
        story.append(_p("No structured source data available.", src_item))

    doc.build(story)


# ═══════════════════════════════════════════════════════════════════════════════
#  PART 2 — MATPLOTLIB CHARTS
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


# ── Chart 3: Technology performance claims distribution ──────────────────────

def _chart_tech_distribution(data: dict) -> plt.Figure:
    from scipy.stats import gaussian_kde

    g = data["graph3"]
    company = data["company_name"]
    metric_name = g["metric_name"]
    metric_unit = g["metric_unit"]
    target_year = g.get("target_year", "")
    company_val = g["company_claim"]
    competitors = g["competitor_claims"]
    higher_better = g.get("higher_is_better", True)
    current_best = g.get("current_best_in_class")

    comp_values = [c["value"] for c in competitors]
    all_values = comp_values + [company_val]
    sorted_comps = sorted(competitors, key=lambda c: c["value"], reverse=higher_better)

    # KDE on competitor claims
    if len(comp_values) >= 2:
        kde = gaussian_kde(comp_values, bw_method="silverman")
        x_pad = (max(all_values) - min(all_values)) * 0.35
        x_lo = min(all_values) - x_pad
        x_hi = max(all_values) + x_pad
        x_range = np.linspace(x_lo, x_hi, 500)
        density = kde(x_range)
    else:
        x_range = np.array([])
        density = np.array([])

    p10 = np.percentile(comp_values, 10)
    p50 = np.percentile(comp_values, 50)
    p90 = np.percentile(comp_values, 90)

    # Two-panel layout: chart left, table right
    fig, (ax, ax_tbl) = plt.subplots(
        1, 2, figsize=(13, 6), gridspec_kw={"width_ratios": [3, 1.2]},
    )
    fig.patch.set_facecolor("white")
    ax.set_facecolor(VOLO_PALE)

    # Left panel: distribution curve
    if len(x_range) > 0:
        ax.fill_between(x_range, density, alpha=0.18, color=ACCENT_BLUE)
        ax.plot(x_range, density, color=ACCENT_BLUE, linewidth=2, alpha=0.7)

    # Rug ticks
    for c in competitors:
        ax.plot(c["value"], 0, marker="|", markersize=10, color="#5b7ea8",
                zorder=8, markeredgewidth=1.5)

    y_top = max(density) if len(density) > 0 else 1

    # Percentile lines
    pct_label_heights = [0.92, 0.78, 0.64]
    line_cfg = [
        (p10, "#c0392b", "P10"),
        (p50, VOLO_GREEN, "P50"),
        (p90, ACCENT_ORANGE, "P90"),
    ]
    for (val, color, label), y_frac in zip(line_cfg, pct_label_heights):
        ax.axvline(val, color=color, linewidth=1.5, linestyle="--", alpha=0.6, zorder=5)
        ax.text(val, y_top * y_frac, f" {label}: {val:.4g}",
                fontsize=7.5, color=color, fontweight="bold", va="center",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                          edgecolor=color, alpha=0.85))

    # Company claim line
    ax.axvline(company_val, color=VOLO_GREEN, linewidth=2.8, linestyle="-", zorder=9)
    ax.text(company_val, y_top * 1.08,
            f"  {company}: {company_val:.4g} {metric_unit}",
            ha="left", va="bottom", fontsize=9, color=VOLO_GREEN,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                      edgecolor=VOLO_GREEN, linewidth=2, alpha=0.95))

    # Current best marker
    if current_best is not None:
        ax.axvline(current_best, color="#888888", linewidth=1.3, linestyle=":",
                   zorder=4, alpha=0.6)
        ax.text(current_best, y_top * 0.50,
                f" Best today: {current_best:.4g}",
                fontsize=7, color="#666666", va="center",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#f5f5f5",
                          edgecolor="#bbbbbb", alpha=0.85))

    year_str = f" (Target ~{target_year})" if target_year else ""
    direction = "Higher = Better" if higher_better else "Lower = Better"

    _apply_base_style(
        ax,
        title=f"{company} — Tech Claims vs. Competitors{year_str}",
        xlabel=f"{metric_name} ({metric_unit})  [{direction}]",
        ylabel="",
    )
    ax.set_yticks([])
    ax.set_ylim(bottom=-0.08 * y_top, top=y_top * 1.25)

    # Right panel: competitor table
    ax_tbl.axis("off")
    ax_tbl.set_title(f"Competitor Claims\n({metric_unit})",
                     fontsize=10, fontweight="bold", color=TEXT_DARK, pad=10)

    tbl_data = []
    for i, c in enumerate(sorted_comps):
        name = c["name"]
        if len(name) > 22:
            name = name[:20] + "…"
        tbl_data.append([str(i + 1), name, f"{c['value']:.4g}"])
    tbl_data.append(["★", company[:20], f"{company_val:.4g}"])

    tbl = ax_tbl.table(
        cellText=tbl_data,
        colLabels=["#", "Company", metric_unit],
        loc="upper center",
        cellLoc="left",
        colWidths=[0.12, 0.58, 0.30],
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(7.5)

    for (row, col), cell in tbl.get_celld().items():
        cell.set_edgecolor("#d4e6da")
        cell.set_linewidth(0.5)
        if row == 0:
            cell.set_facecolor(VOLO_GREEN)
            cell.set_text_props(color="white", fontweight="bold")
            cell.set_height(0.06)
        elif row == len(tbl_data):
            cell.set_facecolor("#e8f5e9")
            cell.set_text_props(fontweight="bold", color=VOLO_GREEN)
            cell.set_height(0.045)
        else:
            cell.set_facecolor("white" if row % 2 == 1 else "#f8fbf9")
            cell.set_height(0.045)

    n_comps = len(competitors)
    fig.text(0.35, 0.01,
             f"Distribution of {n_comps} competitor claims · P10/P50/P90 of landscape shown",
             ha="center", fontsize=7.5, color=TEXT_MID, style="italic")

    _add_ai_watermark(fig)
    fig.tight_layout()
    fig.subplots_adjust(wspace=0.05)
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
    Build three matplotlib figures from graph data dict.

    Args:
        graph_data: Dict with keys company_name, sector, graph1, graph2, graph3.

    Returns:
        [fig1, fig2, fig3] — ready for st.pyplot() or PDF embedding.
    """
    figs = []
    for build_fn in (_chart_revenue, _chart_market, _chart_tech_distribution):
        try:
            figs.append(build_fn(graph_data))
        except Exception as e:
            figs.append(_blank_figure(f"Chart unavailable: {e}"))
    return figs


def save_charts_pdf(figs: list, output_path: str, company_name: str) -> str:
    """Save the three figures to a single multi-page PDF with a cover page."""
    from matplotlib.backends.backend_pdf import PdfPages

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
                   f"Generated by VoLo Earth Ventures DDR Tool  ·  {datetime.now().strftime('%B %d, %Y')}",
                   ha="center", va="center", fontsize=9, color="#a8d5b5",
                   transform=cover.transFigure)
        pdf.savefig(cover, bbox_inches="tight")
        plt.close(cover)

        for fig in figs:
            pdf.savefig(fig, bbox_inches="tight")

    return output_path
