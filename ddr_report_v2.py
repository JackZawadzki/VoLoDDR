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
    Flowable,
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

def _fig_to_image(fig, width=6.5*inch, min_height=3.5*inch) -> Image:
    """Convert a matplotlib figure to a ReportLab Image flowable.

    Uses the figure's own figsize to compute the aspect ratio, avoiding
    bbox_inches='tight' which aggressively crops whitespace and can make
    charts render tiny.
    """
    # Get aspect ratio from the figure's own dimensions (set via figsize)
    fig_w, fig_h = fig.get_size_inches()
    aspect = fig_h / fig_w
    height = max(width * aspect, min_height)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150,
                facecolor="white", edgecolor="none")
    plt.close(fig)
    buf.seek(0)

    return Image(buf, width=width, height=height)


# ── PDF Generation ───────────────────────────────────────────────────────────

def generate_report_pdf(analysis: dict, graph_data: dict, figs: list,
                        output_path: str):
    """
    Generate the complete V2 due diligence PDF report with inline charts
    and a table of contents with accurate page numbers.

    Uses a two-pass build: first pass captures section page numbers,
    second pass renders the final PDF with a populated TOC.
    """
    # ── Pre-render chart figures to reusable PNG byte buffers ──────────
    chart_renders = []
    for fig in figs:
        fw, fh = fig.get_size_inches()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150,
                    facecolor="white", edgecolor="none")
        plt.close(fig)
        chart_renders.append((buf.getvalue(), fw, fh))

    S = _build_styles()
    toc_tracker = {}

    # Section keys in display order for TOC
    _TOC_ORDER = [
        ("overview", "Company Overview"),
        ("competitive", "Competitive Landscape"),
        ("claims", "Claims Assessment"),
        ("unverified", "Unverified Claims"),
        ("outcome", "Outcome Magnitude"),
        ("conclusion", "Conclusion"),
        ("sources", "Sources"),
        ("chart_tam", "Market Size \u2014 TAM & SAM"),
        ("chart_mc", "Hybrid Monte Carlo Projection"),
    ]

    class _Anchor(Flowable):
        """Zero-height flowable that records its page when rendered."""
        def __init__(self, key):
            Flowable.__init__(self)
            self.key = key
            self.width = 0
            self.height = 0
        def draw(self):
            toc_tracker[self.key] = self.canv.getPageNumber()

    class _CommentaryField(Flowable):
        """Fillable PDF form text field for team commentary."""
        def __init__(self, field_name, label="Team Commentary:",
                     field_width=6.5*inch, field_height=1.5*inch):
            Flowable.__init__(self)
            self.field_name = field_name
            self.label = label
            self.field_width = field_width
            self.field_height = field_height
            self.width = field_width
            self.height = field_height + 16
        def draw(self):
            canv = self.canv
            canv.setStrokeColor(colors.HexColor('#d4e6da'))
            canv.setLineWidth(0.5)
            canv.line(0, self.height, self.field_width, self.height)
            canv.setFont('Helvetica-Bold', 8)
            canv.setFillColor(colors.HexColor(VOLO_GREEN))
            canv.drawString(2, self.field_height + 3, self.label)
            canv.acroForm.textfield(
                name=self.field_name,
                tooltip=self.label,
                x=0, y=0,
                width=self.field_width,
                height=self.field_height,
                borderStyle='inset',
                borderColor=colors.HexColor('#c8dcc8'),
                fillColor=colors.HexColor('#f8fbf9'),
                textColor=colors.black,
                forceBorder=True,
                relative=True,
                fieldFlags='multiline',
                fontSize=9,
            )

    def _chart_img(idx, width=7.0*inch, min_height=5.0*inch):
        """Create a ReportLab Image from a pre-rendered chart buffer."""
        png_bytes, fw, fh = chart_renders[idx]
        aspect = fh / fw
        height = max(width * aspect, min_height)
        return Image(io.BytesIO(png_bytes), width=width, height=height)

    def _toc_flowables(entries=None):
        """Return flowables for the Table of Contents page."""
        items = []
        toc_title = ParagraphStyle(
            'TOCTitle', parent=S['title'],
            fontSize=20, spaceAfter=16, alignment=TA_CENTER,
        )
        items.append(_p("TABLE OF CONTENTS", toc_title))
        items.append(Spacer(1, 0.15 * inch))
        # Green divider line
        items.append(Table(
            [['']],
            colWidths=[6.5 * inch],
            style=TableStyle([
                ('LINEBELOW', (0, 0), (-1, -1), 1.5,
                 colors.HexColor(VOLO_GREEN)),
            ]),
        ))
        items.append(Spacer(1, 0.25 * inch))
        if entries:
            toc_name = ParagraphStyle(
                'TOCName', parent=S['body'],
                fontSize=11, leading=18,
            )
            toc_pg = ParagraphStyle(
                'TOCPg', parent=S['body'],
                fontSize=11, leading=18, alignment=TA_CENTER,
                fontName='Helvetica-Bold',
                textColor=colors.HexColor(VOLO_GREEN),
            )
            rows = []
            for key, label in _TOC_ORDER:
                if key in entries:
                    rows.append([
                        Paragraph(label, toc_name),
                        Paragraph(str(entries[key]), toc_pg),
                    ])
            if rows:
                tbl = Table(rows, colWidths=[5.8 * inch, 0.7 * inch])
                tbl.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('TOPPADDING', (0, 0), (-1, -1), 5),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                    ('LINEBELOW', (0, 0), (-1, -1), 0.4,
                     colors.HexColor('#e0e8e2')),
                ]))
                items.append(tbl)
        else:
            # Placeholder: reserve roughly 1 page of vertical space
            items.append(Spacer(1, 5 * inch))
        items.append(PageBreak())
        return items

    def _make_story(toc_entries=None):
        """Build the complete story list. Called twice for TOC page numbering."""
        story = []

        # ── PAGE 1: TITLE, OVERVIEW & STATUS FLAGS ───────────────────
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
        story.append(_Anchor("overview"))
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

        story.append(Spacer(1, 0.15 * inch))
        story.append(_CommentaryField(
            "commentary_overview", "Team Commentary \u2014 Company Overview:"))
        story.append(PageBreak())

        # ── TABLE OF CONTENTS PAGE ───────────────────────────────────
        story.extend(_toc_flowables(toc_entries))

        # ── COMPETITIVE LANDSCAPE ────────────────────────────────────
        comp = analysis.get('competitive_landscape', {})
        story.append(_Anchor("competitive"))
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
                ldr_pos = ldr.get('market_position', '')
                ldr_val = ldr.get('valuation_or_revenue', '')
                ldr_meta = ""
                if ldr_pos and ldr_val:
                    ldr_meta = f" — {ldr_pos} ({ldr_val})"
                elif ldr_pos:
                    ldr_meta = f" — {ldr_pos}"
                elif ldr_val:
                    ldr_meta = f" ({ldr_val})"
                story.append(_p(
                    f"<b>{ldr.get('name', 'Unknown')}</b>{ldr_meta}: "
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

        story.append(Spacer(1, 0.15 * inch))
        story.append(_CommentaryField(
            "commentary_competitive", "Team Commentary \u2014 Competitive Landscape:"))
        story.append(PageBreak())

        # ── CLAIMS ASSESSMENT ────────────────────────────────────────
        claims = analysis.get('claims', [])
        story.append(_Anchor("claims"))
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

            text = (
                f"<b>[{cl_type}] {cl.get('claim', 'N/A')}</b><br/>"
                f"{cl.get('source_label', v_status)}"
            )
            if cl.get('sources'):
                text += f" — <i>{', '.join(cl['sources'][:2])}</i>"
            story.append(_p(text, use_style))
            story.append(Spacer(1, 0.04 * inch))

        story.append(Spacer(1, 0.1 * inch))
        story.append(_CommentaryField(
            "commentary_claims", "Team Commentary \u2014 Claims Assessment:"))

        # ── UNVERIFIED CLAIMS (CRITICAL + HIGH only) ─────────────────
        unverified = analysis.get('unverified_claims', [])
        priority_order = ['CRITICAL', 'HIGH']
        uv_filtered = sorted(
            [uc for uc in unverified if uc.get('priority', 'LOW') in priority_order],
            key=lambda c: priority_order.index(c.get('priority', 'HIGH'))
            if c.get('priority', 'HIGH') in priority_order else 1,
        )

        if uv_filtered:
            story.append(Spacer(1, 0.12 * inch))
            story.append(_Anchor("unverified"))
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
                            f"-&gt; <b>{cmp.get('company', 'N/A')}</b>{val_str}: "
                            f"{cmp.get('context', '')}",
                            S["body_small"],
                        ))
                    if outcome.get('key_caveat'):
                        story.append(_p(
                            f"<i>Caveat: {outcome['key_caveat']}</i>",
                            S["body_small"],
                        ))

                story.append(Spacer(1, 0.06 * inch))
                story.append(_CommentaryField(
                    f"commentary_unverified_{idx}",
                    f"Team Response \u2014 Claim #{idx}:",
                    field_height=1.2*inch))
                story.append(Spacer(1, 0.1 * inch))

        story.append(PageBreak())

        # ── OUTCOME MAGNITUDE + CONCLUSION ───────────────────────────
        story.append(_Anchor("outcome"))
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
            story.append(Spacer(1, 0.12 * inch))

        deps = magnitude.get('key_dependencies', [])
        if deps:
            story.append(_p("What Must Be Proven First:", S["subheading"]))
            for dep in deps:
                story.append(_p(f"- {dep}", S["body_small"]))

        story.append(Spacer(1, 0.15 * inch))
        story.append(_CommentaryField(
            "commentary_outcome", "Team Commentary \u2014 Outcome Assessment:"))
        story.append(Spacer(1, 0.2 * inch))

        # ── CONCLUSION ───────────────────────────────────────────────
        story.append(_Anchor("conclusion"))
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
                    f"- <b>{uc.get('claim', 'N/A')}</b> — {_dollar(mkt_usd)}",
                    S["body_small"],
                ))

        if if_all.get('framing'):
            story.append(Spacer(1, 0.1 * inch))
            story.append(_p(if_all.get('framing', ''), S["body_small"]))

        story.append(Spacer(1, 0.15 * inch))
        story.append(_p(
            f"<i><b>Methodology:</b> Analysis based on {analysis.get('sources_consulted', '?')} sources "
            f"including web research, financial databases, and industry reports. "
            f"No investment recommendation is made.</i><br/>"
            f"<b>Generated:</b> {datetime.now().strftime('%B %d, %Y at %H:%M:%S')}",
            S["body_small"],
        ))

        story.append(Spacer(1, 0.15 * inch))
        story.append(_CommentaryField(
            "commentary_conclusion",
            "Team Commentary \u2014 Final Notes & Next Steps:",
            field_height=2.0*inch))

        # ── SOURCES PAGE ─────────────────────────────────────────────
        story.append(PageBreak())
        story.append(_Anchor("sources"))
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

        # ── CHART PAGES — one chart per page, full size ──────────────
        chart_titles = [
            "Market Size \u2014 TAM & SAM",
            "Hybrid Monte Carlo Projection",
        ]
        chart_keys = ["chart_tam", "chart_mc"]
        for i in range(len(chart_renders)):
            story.append(PageBreak())
            story.append(_Anchor(chart_keys[i]))
            if i < len(chart_titles):
                story.append(_p(chart_titles[i], S["heading"]))
                story.append(Spacer(1, 0.1 * inch))
            story.append(_chart_img(i))

            # After hybrid MC chart: add competitor table + methodology
            if i == 1:
                g3 = graph_data.get("graph3", {})
                if g3 and g3.get("competitor_claims"):
                    hp = _estimate_hybrid_params(g3)
                    competitors_list = g3.get("competitor_claims", [])
                    metric_unit_g3 = g3.get("metric_unit", "")
                    hb = g3.get("higher_is_better", True)
                    ll = "ceiling" if hb else "floor"

                    # ── Compact competitor table ──
                    story.append(Spacer(1, 0.15 * inch))
                    comp_header = [[
                        _p("<b>Competitor</b>", S["body_small"]),
                        _p(f"<b>{_esc(metric_unit_g3)}</b>", S["body_small"]),
                        _p("<b>Stage</b>", S["body_small"]),
                    ]]
                    comp_rows = [
                        [c["name"], f"{c['value']:.4g}",
                         c.get("stage", "target").title()]
                        for c in competitors_list
                    ]
                    comp_rows.append([
                        f"{g3.get('company_name', 'Company')} (target)",
                        f"{g3['company_claim']:.4g}",
                        "Target",
                    ])
                    comp_tbl = Table(
                        comp_header + comp_rows,
                        colWidths=[3.0 * inch, 1.2 * inch, 1.0 * inch],
                    )
                    comp_tbl.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0),
                         colors.HexColor(VOLO_GREEN)),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -2),
                         [colors.white, colors.HexColor(VOLO_PALE)]),
                        ("BACKGROUND", (0, -1), (-1, -1),
                         colors.HexColor("#e8f5e9")),
                        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                        ("GRID", (0, 0), (-1, -1), 0.3,
                         colors.HexColor(GRID_COLOR)),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]))
                    story.append(comp_tbl)

                    # ── Methodology (2 paragraphs + equation) ──
                    story.append(Spacer(1, 0.2 * inch))
                    story.append(_p(
                        "Methodology \u2014 Hybrid GBM + S-Curve Monte Carlo",
                        S["subheading"],
                    ))

                    story.append(_p(
                        "This projection uses a hybrid model that combines "
                        "Geometric Brownian Motion (stochastic compounding) "
                        "with S-curve saturation (physical limits). Unlike "
                        "standard GBM \u2014 which assumes constant improvement "
                        "rates indefinitely \u2014 or pure S-curves \u2014 where the "
                        "trajectory is predetermined \u2014 the hybrid applies a "
                        "state-dependent drift that naturally decays as values "
                        f"approach the theoretical {ll}. Each of the 5,000 "
                        "simulations independently bootstraps the competitor "
                        "pool with replacement, draws unique parameter values "
                        f"from uncertainty distributions (mu_max, sigma, {ll} "
                        "L), and evolves its own stochastic path. The result "
                        "is genuinely random, path-dependent trajectories "
                        "that respect physical bounds.",
                        S["body_small"],
                    ))

                    # Equation box
                    if hb:
                        rem_eq = "remaining = (L - X(t)) / (L - X(0))"
                    else:
                        rem_eq = "remaining = (X(t) - L) / (X(0) - L)"

                    formula_style = ParagraphStyle(
                        'HybridFormula', parent=S["body_small"],
                        fontName="Courier", fontSize=8, leading=12,
                        textColor=colors.HexColor(TEXT_MID),
                    )
                    formula_box = Table(
                        [[_p(
                            f"{rem_eq} &nbsp;&nbsp;|&nbsp;&nbsp; "
                            "mu(t) = mu_max * remaining "
                            "&nbsp;&nbsp;|&nbsp;&nbsp; "
                            "X(t+1) = X(t) * exp((mu(t) - "
                            "sigma^2/2)dt + sigma*sqrt(dt)*Z)",
                            formula_style,
                        )]],
                        colWidths=[6.5 * inch],
                    )
                    formula_box.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, -1),
                         colors.HexColor("#f5f8f5")),
                        ("BOX", (0, 0), (-1, -1), 0.5,
                         colors.HexColor(GRID_COLOR)),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ]))
                    story.append(Spacer(1, 0.08 * inch))
                    story.append(formula_box)
                    story.append(Spacer(1, 0.1 * inch))

                    story.append(_p(
                        f"Far from the {ll}, the full drift applies and "
                        f"compounding is rapid. Near the {ll}, drift vanishes "
                        "and the value saturates \u2014 mirroring how real "
                        "technologies approach fundamental physical bounds. "
                        "The P10/P50/P90 bands represent the 10th, 50th, and "
                        "90th percentiles across all simulations, capturing "
                        "both parameter uncertainty (each run has different "
                        "mu, sigma, and L) and stochastic noise (each path "
                        "follows its own random walk). This provides a "
                        "realistic envelope of plausible outcomes for the "
                        "competitive landscape.",
                        S["body_small"],
                    ))

        return story

    # ── Two-pass build for accurate TOC page numbers ─────────────────
    _doc_args = dict(
        pagesize=letter,
        topMargin=0.65 * inch, bottomMargin=0.65 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
    )

    # Pass 1: build to buffer, capturing page numbers via anchors
    doc1 = SimpleDocTemplate(io.BytesIO(), **_doc_args)
    doc1.build(_make_story())

    # Pass 2: build with populated TOC
    captured = dict(toc_tracker)
    toc_tracker.clear()
    doc2 = SimpleDocTemplate(output_path, **_doc_args)
    doc2.build(_make_story(toc_entries=captured))


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

    fig, ax = plt.subplots(figsize=(10, 6.5))
    fig.patch.set_facecolor("white")

    ax.set_facecolor(VOLO_PALE)
    ax.set_title(f"{company} Revenue Trajectory vs. Established Peers",
                 fontsize=14, fontweight="bold", color=TEXT_DARK, pad=18)
    ax.set_xlabel("Year", fontsize=11, color=TEXT_MID, labelpad=10)
    ax.set_ylabel("Revenue (USD)", fontsize=11, color=TEXT_MID, labelpad=10)
    ax.tick_params(colors=TEXT_MID, labelsize=10, pad=6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRID_COLOR)
    ax.spines["bottom"].set_color(GRID_COLOR)
    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.8, linestyle="--")
    ax.set_axisbelow(True)

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

    _add_ai_watermark(fig)
    fig.tight_layout(pad=1.8)

    if note:
        fig.text(0.5, 0.01, f"Note: {note}", ha="center",
                 fontsize=7.5, color=TEXT_MID, style="italic")
        fig.subplots_adjust(bottom=0.13)

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

    fig, ax = plt.subplots(figsize=(10, 6.5))
    fig.patch.set_facecolor("white")

    ax.set_facecolor(VOLO_PALE)
    ax.set_title("Market Size Over Time — TAM & SAM",
                 fontsize=14, fontweight="bold", color=TEXT_DARK, pad=18)
    ax.set_xlabel("Year", fontsize=11, color=TEXT_MID, labelpad=10)
    ax.set_ylabel("Market Size (USD Billions)", fontsize=11, color=TEXT_MID, labelpad=10)
    ax.tick_params(colors=TEXT_MID, labelsize=10, pad=6)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRID_COLOR)
    ax.spines["bottom"].set_color(GRID_COLOR)
    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.8, linestyle="--")
    ax.set_axisbelow(True)

    ax.fill_between(years, tam, alpha=0.15, color=VOLO_GREEN)
    ax.plot(years, tam, color=VOLO_GREEN, linewidth=2.5,
            marker="o", markersize=5, label=tam_lbl)

    ax.fill_between(years, sam, alpha=0.25, color=ACCENT_BLUE)
    ax.plot(years, sam, color=ACCENT_BLUE, linewidth=2.5,
            marker="s", markersize=5, linestyle="--", label=sam_lbl)

    ax.annotate(f"  ${tam[-1]:.0f}B", xy=(years[-1], tam[-1]),
                fontsize=9, color=VOLO_GREEN, fontweight="bold", va="center")
    ax.annotate(f"  ${sam[-1]:.1f}B", xy=(years[-1], sam[-1]),
                fontsize=9, color=ACCENT_BLUE, fontweight="bold", va="center")

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_billions))
    ax.legend(fontsize=9, framealpha=0.9, edgecolor=GRID_COLOR)

    _add_ai_watermark(fig)
    fig.tight_layout(pad=1.8)

    if src_note:
        fig.text(0.5, 0.01, src_note, ha="center",
                 fontsize=7.5, color=TEXT_MID, style="italic")
        fig.subplots_adjust(bottom=0.13)

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

    fig, ax = plt.subplots(figsize=(10, 7))
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
                  fontsize=11, color=TEXT_MID, labelpad=12)
    ax.set_yticks([])
    ax.set_ylabel("")
    ax.set_title(f"{company} — Technology Claim vs. Competitive Landscape",
                 fontsize=14, fontweight="bold", color=TEXT_DARK, pad=18)

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

    fig.tight_layout(pad=1.5)

    _add_ai_watermark(fig)
    return fig


# ── Chart 5: Hybrid GBM + S-Curve Monte Carlo ───────────────────────────

def _estimate_hybrid_params(g3):
    """Estimate hybrid MC simulation parameters from graph3 competitor data."""
    competitors = g3.get("competitor_claims", [])
    comp_values = np.array([c["value"] for c in competitors], dtype=float)
    higher_better = g3.get("higher_is_better", True)

    base_year = datetime.now().year
    target_year = g3.get("target_year", base_year + 3)
    if target_year <= base_year:
        target_year = base_year + 3
    horizon = target_year - base_year

    median_val = float(np.median(comp_values))
    std_val = float(np.std(comp_values))
    cv = std_val / median_val if median_val > 0 else 0.1

    # Sigma: based on coefficient of variation of competitor spread
    sigma_lo = max(cv * 0.4, 0.05)
    sigma_hi = max(cv * 1.2, 0.20)

    if higher_better:
        best = float(np.max(comp_values))
        ratio = best / median_val if median_val > 0 else 1.1
        annual_rate = max(ratio ** (1.0 / horizon) - 1, 0.01)
        mu_lo = max(annual_rate * 0.3, 0.02)
        mu_hi = max(annual_rate * 2.0, 0.15)
        limit_lo = best * 1.3
        limit_hi = best * 2.0
    else:
        best = float(np.min(comp_values))
        ratio = best / median_val if median_val > 0 else 0.9
        annual_rate = min(ratio ** (1.0 / horizon) - 1, -0.01)
        mu_lo = min(annual_rate * 2.0, -0.15)
        mu_hi = min(annual_rate * 0.3, -0.02)
        limit_lo = max(best * 0.2, 1.0)
        limit_hi = best * 0.7

    return {
        "base_year": base_year,
        "target_year": target_year,
        "mu_range": (round(mu_lo, 4), round(mu_hi, 4)),
        "sigma_range": (round(sigma_lo, 4), round(sigma_hi, 4)),
        "limit_range": (round(limit_lo, 1), round(limit_hi, 1)),
        "comp_values": comp_values,
        "n_comp": len(competitors),
        "higher_better": higher_better,
    }


def _hybrid_mc_simulate(g3, n_sim=5000):
    """Run hybrid GBM + S-curve MC simulation using graph3 data."""
    hp = _estimate_hybrid_params(g3)
    comp_values = hp["comp_values"]
    n_comp = hp["n_comp"]
    higher_better = hp["higher_better"]

    years = np.arange(hp["base_year"], hp["target_year"] + 1)
    n_years = len(years)
    dt = 1.0
    rng = np.random.default_rng(42)

    all_paths = np.zeros((n_sim, n_years))

    for s in range(n_sim):
        indices = rng.integers(0, n_comp, size=n_comp)
        pool = comp_values[indices]

        mu_max = rng.uniform(hp["mu_range"][0], hp["mu_range"][1])
        sigma = rng.uniform(hp["sigma_range"][0], hp["sigma_range"][1])
        L = rng.uniform(hp["limit_range"][0], hp["limit_range"][1])

        start = float(rng.choice(pool))
        path = [start]

        for t in range(1, n_years):
            current = path[-1]
            if higher_better:
                remaining = max((L - current) / (L - start), 0.0) if L > start else 0.0
            else:
                remaining = max((current - L) / (start - L), 0.0) if start > L else 0.0

            mu_t = mu_max * remaining
            z = rng.normal()
            new_val = current * np.exp(
                (mu_t - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z
            )

            if higher_better:
                new_val = min(max(new_val, float(np.min(comp_values)) * 0.3), L)
            else:
                new_val = max(new_val, L)

            path.append(new_val)

        all_paths[s] = path

    p10 = np.percentile(all_paths, 10, axis=0)
    p50 = np.percentile(all_paths, 50, axis=0)
    p90 = np.percentile(all_paths, 90, axis=0)

    return years, all_paths, p10, p50, p90, hp


def _chart_hybrid_mc(data: dict) -> plt.Figure:
    """Create hybrid GBM + S-curve Monte Carlo chart from graph3 data."""
    g3 = data["graph3"]
    company = data.get("company_name", g3.get("company_name", "Company"))
    higher_better = g3.get("higher_is_better", True)
    competitors = g3["competitor_claims"]
    company_val = g3["company_claim"]
    metric_unit = g3["metric_unit"]
    metric_name = g3["metric_name"]
    target_year = g3.get("target_year", datetime.now().year + 3)

    n_sim = 5000
    n_show = 80

    years, all_paths, p10, p50, p90, hp = _hybrid_mc_simulate(g3, n_sim=n_sim)

    # Color assignments
    if higher_better:
        OPT_COLOR = VOLO_GREEN
        PESS_COLOR = ACCENT_ORANGE
    else:
        OPT_COLOR = VOLO_GREEN
        PESS_COLOR = ACCENT_ORANGE
    MED_COLOR = TEXT_DARK
    SIM_COLOR = "#c8dcc8"

    fig, ax = plt.subplots(figsize=(10, 6.5))
    fig.patch.set_facecolor("white")
    ax.set_facecolor(VOLO_PALE)

    ax.set_title(
        f"{company} \u2014 Hybrid GBM + S-Curve Monte Carlo",
        fontsize=14, fontweight="bold", color=TEXT_DARK, pad=20,
    )

    limit_label = "ceiling" if higher_better else "floor"
    ax.text(
        0, 1.02,
        f"mu_max ~ U({hp['mu_range'][0]:.0%}, {hp['mu_range'][1]:.0%})  |  "
        f"sigma ~ U({hp['sigma_range'][0]:.0%}, {hp['sigma_range'][1]:.0%})  |  "
        f"{limit_label} ~ U({hp['limit_range'][0]:.0f}, {hp['limit_range'][1]:.0f}) "
        f"{metric_unit}  |  bootstrapped",
        transform=ax.transAxes, fontsize=8, color=TEXT_MID, va="bottom",
    )

    ax.set_xlabel("Year", fontsize=10, color=TEXT_MID, labelpad=8)
    ax.set_ylabel(
        f"{metric_name} ({metric_unit})", fontsize=10, color=TEXT_MID, labelpad=8,
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRID_COLOR)
    ax.spines["bottom"].set_color(GRID_COLOR)
    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.8, linestyle="--")
    ax.xaxis.grid(True, color=GRID_COLOR, linewidth=0.3, linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)

    # Sim paths
    show_idx = np.random.choice(n_sim, min(n_show, n_sim), replace=False)
    for idx in show_idx:
        ax.plot(years, all_paths[idx], color=SIM_COLOR, linewidth=0.3,
                alpha=0.2, zorder=1)

    # Bands + percentile lines
    if higher_better:
        ax.fill_between(years, p50, p90, color=VOLO_GREEN, alpha=0.08, zorder=3)
        ax.fill_between(years, p10, p50, color=ACCENT_ORANGE, alpha=0.08, zorder=3)
        ax.plot(years, p90, color=OPT_COLOR, linewidth=1.4, linestyle="--",
                label="P90 (optimistic)", zorder=5)
        ax.plot(years, p10, color=PESS_COLOR, linewidth=1.4, linestyle="--",
                label="P10 (pessimistic)", zorder=5)
    else:
        ax.fill_between(years, p90, p50, color=ACCENT_ORANGE, alpha=0.08, zorder=3)
        ax.fill_between(years, p50, p10, color=VOLO_GREEN, alpha=0.08, zorder=3)
        ax.plot(years, p10, color=OPT_COLOR, linewidth=1.4, linestyle="--",
                label="P10 (optimistic)", zorder=5)
        ax.plot(years, p90, color=PESS_COLOR, linewidth=1.4, linestyle="--",
                label="P90 (pessimistic)", zorder=5)
    ax.plot(years, p50, color=MED_COLOR, linewidth=2.2,
            label="P50 (median)", zorder=6)

    # End labels
    for val, clr, lbl in [
        (p90[-1], OPT_COLOR if higher_better else PESS_COLOR, "P90"),
        (p50[-1], MED_COLOR, "P50"),
        (p10[-1], PESS_COLOR if higher_better else OPT_COLOR, "P10"),
    ]:
        ax.annotate(
            f"{lbl}: {val:.0f}", (years[-1], val),
            textcoords="offset points", xytext=(8, 0),
            fontsize=7.5, fontweight="bold", color=clr, va="center",
            bbox=dict(boxstyle="round,pad=0.15", facecolor="white",
                      edgecolor=clr, alpha=0.85, linewidth=0.6),
        )

    # Competitors at base year
    plotted_stages = set()
    for c in competitors:
        st = c.get("stage", "target")
        style = _STAGE_STYLE.get(st, _STAGE_STYLE["target"])
        ax.scatter(
            hp["base_year"], c["value"], marker=style["marker"],
            color=style["color"], s=55, zorder=14, edgecolors="white",
            linewidths=0.6, alpha=0.9,
            label=style["label"] if st not in plotted_stages else None,
        )
        plotted_stages.add(st)
        ax.annotate(
            c["name"], (hp["base_year"], c["value"]),
            textcoords="offset points", xytext=(-8, 0),
            fontsize=6, color=TEXT_MID, ha="right", va="center", alpha=0.7,
        )

    # Company target star
    ax.plot(target_year, company_val, marker="*", color=VOLO_GREEN,
            markersize=22, zorder=20, markeredgecolor="white",
            markeredgewidth=1.0)
    ax.annotate(
        f"{company} Target\n{company_val:.4g} {metric_unit}",
        (target_year, company_val),
        textcoords="offset points", xytext=(-60, -25),
        fontsize=9, fontweight="bold", color=VOLO_GREEN,
        ha="center", va="top",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                  edgecolor=VOLO_GREEN, linewidth=1.5, alpha=0.95),
        arrowprops=dict(arrowstyle="->", color=VOLO_GREEN,
                        connectionstyle="arc3,rad=-0.2", linewidth=1.2),
    )

    # Limit range shading
    L_mean = np.mean(hp["limit_range"])
    ax.axhspan(hp["limit_range"][0], hp["limit_range"][1],
               color="#aaaaaa", alpha=0.06, zorder=1)
    ax.axhline(L_mean, color="#aaaaaa", linewidth=1.0, linestyle=":",
               alpha=0.6, zorder=2)
    y_offset = -8 if higher_better else 3
    va_align = "top" if higher_better else "bottom"
    ax.text(
        target_year + 0.12, L_mean + y_offset,
        f"Theoretical {limit_label} "
        f"~{hp['limit_range'][0]:.0f}-{hp['limit_range'][1]:.0f} {metric_unit}",
        fontsize=7, color="#999999", va=va_align, fontstyle="italic",
    )

    # Zone annotation
    if higher_better:
        if company_val > p90[-1]:
            zone, zc = "Above P90 \u2014 Highly Ambitious", OPT_COLOR
        elif company_val > p50[-1]:
            zone, zc = "P50-P90 \u2014 Competitive", ACCENT_BLUE
        elif company_val > p10[-1]:
            zone, zc = "P10-P50 \u2014 Market Parity", PESS_COLOR
        else:
            zone, zc = "Below P10 \u2014 Below Market", ACCENT_ORANGE
        zone_pos, zone_va = (0.02, 0.97), "top"
    else:
        if company_val < p10[-1]:
            zone, zc = "Below P10 \u2014 Highly Ambitious", OPT_COLOR
        elif company_val < p50[-1]:
            zone, zc = "P10-P50 \u2014 Competitive", ACCENT_BLUE
        elif company_val < p90[-1]:
            zone, zc = "P50-P90 \u2014 Market Parity", PESS_COLOR
        else:
            zone, zc = "Above P90 \u2014 Below Market", ACCENT_ORANGE
        zone_pos, zone_va = (0.02, 0.02), "bottom"

    ax.text(
        zone_pos[0], zone_pos[1], zone, transform=ax.transAxes,
        fontsize=8, fontweight="bold", color=zc, va=zone_va, ha="left",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white",
                  edgecolor=zc, linewidth=1.2, alpha=0.92),
    )

    # Direction arrow
    if higher_better:
        ax.annotate("", xy=(0.98, 0.90), xytext=(0.98, 0.75),
                    xycoords="axes fraction",
                    arrowprops=dict(arrowstyle="->", color=VOLO_GREEN,
                                    linewidth=1.5))
        ax.text(0.98, 0.92, "Higher = Better", transform=ax.transAxes,
                fontsize=6.5, color=VOLO_GREEN, ha="center", fontweight="bold")
    else:
        ax.annotate("", xy=(0.98, 0.15), xytext=(0.98, 0.30),
                    xycoords="axes fraction",
                    arrowprops=dict(arrowstyle="->", color=VOLO_GREEN,
                                    linewidth=1.5))
        ax.text(0.98, 0.13, "Lower = Better", transform=ax.transAxes,
                fontsize=6.5, color=VOLO_GREEN, ha="center", fontweight="bold")

    legend_loc = "lower right" if higher_better else "upper right"
    ax.legend(fontsize=8, loc=legend_loc, framealpha=0.9,
              edgecolor=GRID_COLOR, ncol=1, handletextpad=0.5, borderpad=0.8)

    right_pad = 0.8 if higher_better else 1.0
    ax.set_xlim(hp["base_year"] - 0.3, target_year + right_pad)
    ax.set_xticks(years)

    note = (
        f"n = {n_sim:,} MC sims  |  Hybrid GBM + S-Curve: "
        f"state-dependent drift decays toward {limit_label}  |  "
        f"all params randomized per sim"
    )
    ax.text(0.5, -0.09, note, transform=ax.transAxes,
            fontsize=6.5, color="#aaaaaa", ha="center")

    fig.tight_layout(pad=1.5)
    _add_ai_watermark(fig)
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
    Build matplotlib figures from graph data dict.

    Args:
        graph_data: Dict with keys company_name, sector, graph2, graph3.

    Returns:
        [fig_market, fig_hybrid_mc]
    """
    figs = []
    for build_fn in (_chart_market, _chart_hybrid_mc):
        try:
            figs.append(build_fn(graph_data))
        except Exception as e:
            figs.append(_blank_figure(f"Chart unavailable: {e}"))
    return figs
