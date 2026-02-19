"""
DUE DILIGENCE REPORT GENERATOR
================================
Produces IC-ready reports that:
1. Identify unverified claims and flag what needs investigation
2. Show the potential outcome magnitude of each claim if proven true
3. Compare against real market comps ("if accurate, could compete with X")
4. Check company financial/legal status

Installation:
    pip install anthropic pypdf reportlab python-dotenv

Usage:
    python "DDR(draft 11).py" pitch_deck.pdf

API Key:
    Set ANTHROPIC_API_KEY as an environment variable, or create a .env file:
        ANTHROPIC_API_KEY=sk-ant-...
"""

import os
import sys
import json
import re
from datetime import datetime
from typing import Dict

from pypdf import PdfReader
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from anthropic import Anthropic

# Load API key from environment (set ANTHROPIC_API_KEY in your shell or a .env file)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional

MODEL = "claude-opus-4-6"


def _esc(text) -> str:
    """Escape special ReportLab/XML characters in Claude-generated strings."""
    if not isinstance(text, str):
        text = str(text)
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("$", "&#36;"))

SOURCE_CREDIBILITY = {
    'bloomberg': 0.95, 'reuters': 0.90, 'iea': 0.95, 'bain': 0.85,
    'mckinsey': 0.85, 'bcg': 0.85, 'sec': 0.95, 'crunchbase': 0.85,
    'pitchbook': 0.90, 'cbinsights': 0.85, 'court_records': 0.95,
    'government': 0.85, 'industry_report': 0.75, 'unknown': 0.20
}


class ConfidenceScorer:
    @staticmethod
    def score_claim(sources: list, data_age_months: int = 999,
                    sources_agree: bool = False, has_numbers: bool = False) -> float:
        confidence = 0.3
        if len(sources) >= 5: confidence += 0.25
        elif len(sources) >= 3: confidence += 0.15
        elif len(sources) == 2: confidence += 0.08
        elif len(sources) == 1: confidence += 0.03

        if sources:
            avg_cred = sum(ConfidenceScorer._get_credibility(s) for s in sources) / len(sources)
            confidence += avg_cred * 0.30

        if data_age_months <= 6: confidence += 0.15
        elif data_age_months <= 12: confidence += 0.08
        if sources_agree: confidence += 0.15
        if has_numbers: confidence += 0.10
        return min(1.0, confidence)

    @staticmethod
    def _get_credibility(source: str) -> float:
        source_lower = source.lower()
        for key, score in SOURCE_CREDIBILITY.items():
            if key in source_lower:
                return score
        return SOURCE_CREDIBILITY['unknown']

    @staticmethod
    def get_stars(confidence: float) -> str:
        if confidence >= 0.85: return '⭐⭐⭐⭐⭐'
        elif confidence >= 0.70: return '⭐⭐⭐⭐'
        elif confidence >= 0.50: return '⭐⭐⭐'
        elif confidence >= 0.30: return '⭐⭐'
        else: return '⭐'


class DueDiligenceAnalyzer:

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError(
                "API key not found. Set the ANTHROPIC_API_KEY environment variable."
            )
        self.client = Anthropic(api_key=api_key)
        self.scorer = ConfidenceScorer()

    def extract_pdf(self, path: str) -> str:
        if not os.path.exists(path):
            raise FileNotFoundError(f"PDF not found: {path}")
        print(f"📄 Extracting from {path}...")
        text = ""
        reader = PdfReader(path)
        for i, page in enumerate(reader.pages, 1):
            text += page.extract_text() + "\n\n"
            if i % 5 == 0:
                print(f"   Processed {i}/{len(reader.pages)} pages")
        print(f"   ✓ Extracted {len(text):,} characters")
        if len(text) > 60000:
            print(f"   ⚠️  Deck is large — analysis will use the first ~60,000 characters")
        return text

    def analyze(self, pitch_text: str) -> Dict:
        """
        Deep due diligence: surfaces unverified claims, flags what needs
        investigation, and sizes the potential outcome if each claim is true.
        """
        print("\n🔬 Running deep analysis (this will take 2-4 minutes)...")
        print("   Identifying claims, verification gaps, and outcome comparables...")

        text_preview = pitch_text[:60000]

        prompt = f"""You are conducting deep due diligence on a pitch deck. Your job is NOT to decide whether to invest. Your job is to:

1. Surface every significant claim the company makes — be exhaustive
2. Flag which claims are UNVERIFIED and need investigation
3. For each unverified claim, size the potential outcome IF it turns out to be true
4. Map the full competitive landscape at both peer scale and larger market scale

THOROUGHNESS REQUIREMENTS:
- technology_claims: minimum 6 entries covering every performance, efficiency, IP, and technical claim
- market_claims: minimum 6 entries covering every TAM, growth rate, customer, and adoption claim
- unverified_claims: minimum 8 entries drawn from Technology, Market, Financial, and Team categories
- competitive_landscape.peer_competitors: minimum 3 real named companies at similar stage/scale
- competitive_landscape.market_leaders: minimum 3 real named large incumbents or category leaders
- Do not be vague — quote claims precisely from the deck and name real companies with known valuations

DATA LABELING — label every claim as:
- "COMPANY CLAIM (Unverified)" — only from the pitch deck, no independent confirmation
- "VERIFIED: [Source]" — confirmed by independent third party
- "PARTIALLY VERIFIED: Company claims X, [Source] indicates Y"

OUTCOME COMPARABLES — reference real companies with known valuations:
- "If the efficiency claims are accurate, this could compete with [Company] which holds X% of the market, valued at $Y"
- Use: IEA, Bloomberg NEF, Bain, McKinsey, CB Insights, Crunchbase, PitchBook

Pitch Deck:
{text_preview}

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
            "sources": ["Court records", "News articles"]
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
            "priority": "CRITICAL / HIGH / MEDIUM / LOW"
        }}
    ],

    "outcome_magnitude": {{
        "if_all_claims_verified": {{
            "description": "What the company could become if all major claims hold up",
            "addressable_market_usd": 50000000000,
            "realistic_market_share_pct": 5,
            "comparable_companies": ["Real Company A", "Real Company B"],
            "framing": "If the technology and market claims are accurate, this company could compete with [X] in the [Y] market, which currently supports companies valued at $Z"
        }},
        "if_core_tech_only_verified": {{
            "description": "Outcome if just the core technology works, market claims prove more modest",
            "addressable_market_usd": 5000000000,
            "comparable_companies": ["Real smaller comp"],
            "framing": "Even with a smaller market, proven tech alone positions this similarly to [X] at [stage/valuation]"
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
        }},
        "graph3": {{
            "metric_name": "The single most important quantifiable performance metric for this technology",
            "metric_unit": "unit (e.g. miles, %, Wh/kg, $/ton, MW, Gbps)",
            "target_year": 2030,
            "company_claim": 500,
            "competitor_claims": [
                {{"name": "Competitor A", "value": 400, "source": "Source"}},
                {{"name": "Competitor B", "value": 450, "source": "Source"}},
                {{"name": "Competitor C", "value": 520, "source": "Source"}},
                {{"name": "Competitor D", "value": 435, "source": "Source"}},
                {{"name": "Competitor E", "value": 470, "source": "Source"}}
            ],
            "higher_is_better": true,
            "current_best_in_class": 350,
            "current_best_source": "Source for current best",
            "rationale": "Why this metric was chosen as the key performance indicator"
        }}
    }}
}}

IMPORTANT:
- Be exhaustive — hit the minimum counts above for every list
- Every unverified claim needs 2 concrete investigation steps naming specific data sources or tests
- All competitor names must be real companies with verifiable existence
- Do not recommend whether to invest — only surface what is unverified and what it could mean

GRAPH DATA REQUIREMENTS (the "graph_data" field):
- graph1: Use the company's own revenue projections from the deck. For peers, use 2-3 real public/well-known competitors in the same sector with realistic revenue figures based on your knowledge.
- graph2: TAM/SAM should reflect real market research figures (IEA, BloombergNEF, Grand View, Mordor Intelligence, etc.).
- graph3: Identify the SINGLE most important quantifiable performance metric for this company's core technology (e.g. battery energy density Wh/kg, solar efficiency %, EV range miles, carbon capture cost $/ton, wind capacity MW, drug efficacy %, etc.). Find the company's claim for that metric, then list 5-15 real competitor claims/targets for the SAME metric around the same target year. This is for technology forecasting — mapping where the company sits in the competitive distribution.
"""

        response_text = ""
        print("   Analysis in progress", end='', flush=True)

        try:
            with self.client.messages.stream(
                model=MODEL,
                max_tokens=16000,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}]
            ) as stream:
                for i, text in enumerate(stream.text_stream):
                    response_text += text
                    if i % 50 == 0:
                        print(".", end='', flush=True)
        except Exception as e:
            print(f"\n❌ API call failed: {e}")
            raise

        print()
        print("   ✓ Analysis complete")

        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError as e:
                print(f"   ⚠️  JSON parse error: {e}")
                return {"company_name": "Unknown", "error": "JSON parse failed", "raw": response_text[:2000]}
        else:
            return {"company_name": "Unknown", "error": "No JSON found in response"}

    def add_confidence_scores(self, analysis: Dict) -> Dict:
        print("\n📊 Adding confidence scores...")

        for claim in analysis.get('technology_claims', []):
            conf = self.scorer.score_claim(sources=claim.get('sources', []))
            claim['ai_confidence_score'] = conf
            claim['ai_confidence_stars'] = self.scorer.get_stars(conf)

        for claim in analysis.get('market_claims', []):
            conf = self.scorer.score_claim(sources=claim.get('sources', []), has_numbers=True)
            claim['ai_confidence_score'] = conf
            claim['ai_confidence_stars'] = self.scorer.get_stars(conf)

        for claim in analysis.get('unverified_claims', []):
            conf = self.scorer.score_claim(sources=[])  # unverified by definition
            claim['ai_confidence_score'] = conf
            claim['ai_confidence_stars'] = self.scorer.get_stars(conf)

        if 'company_financial_legal_status' in analysis:
            status = analysis['company_financial_legal_status']
            if 'bankruptcy_insolvency' in status:
                bank = status['bankruptcy_insolvency']
                conf = self.scorer.score_claim(sources=bank.get('sources', []), has_numbers=True)
                bank['ai_confidence_score'] = conf
                bank['ai_confidence_stars'] = self.scorer.get_stars(conf)

        print("   ✓ Confidence scores added")
        return analysis

    def generate_pdf(self, analysis: Dict, output_path: str):
        print("\n📑 Generating PDF report...")

        doc = SimpleDocTemplate(output_path, pagesize=letter,
                                topMargin=0.75*inch, bottomMargin=0.75*inch,
                                leftMargin=0.75*inch, rightMargin=0.75*inch)

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'],
                                     fontSize=24, textColor=colors.HexColor('#2d5f3f'),
                                     spaceAfter=20, alignment=TA_CENTER, fontName='Helvetica-Bold')
        heading_style = ParagraphStyle('CustomHeading', parent=styles['Heading2'],
                                       fontSize=16, textColor=colors.HexColor('#2d5f3f'),
                                       spaceAfter=12, spaceBefore=20, fontName='Helvetica-Bold')
        subheading_style = ParagraphStyle('CustomSubheading', parent=styles['Heading3'],
                                          fontSize=13, textColor=colors.HexColor('#1a472a'),
                                          spaceAfter=8, spaceBefore=12, fontName='Helvetica-Bold')
        body_style = ParagraphStyle('CustomBody', parent=styles['BodyText'],
                                    fontSize=11, leading=16, spaceAfter=12, alignment=TA_JUSTIFY)
        alert_style = ParagraphStyle('Alert', parent=styles['BodyText'],
                                     fontSize=11, leading=16, spaceAfter=12,
                                     textColor=colors.HexColor('#8B0000'),
                                     backColor=colors.HexColor('#FFE4E1'),
                                     borderPadding=8)
        flag_style = ParagraphStyle('Flag', parent=styles['BodyText'],
                                    fontSize=11, leading=16, spaceAfter=12,
                                    textColor=colors.HexColor('#5c3d00'),
                                    backColor=colors.HexColor('#FFF8E1'),
                                    borderPadding=8)
        verified_style = ParagraphStyle('Verified', parent=styles['BodyText'],
                                        fontSize=11, leading=16, spaceAfter=12,
                                        textColor=colors.HexColor('#1a4a1a'),
                                        backColor=colors.HexColor('#E8F5E9'),
                                        borderPadding=8)

        story = []

        # ── PAGE 1: TITLE, OVERVIEW & FINANCIAL/LEGAL SNAPSHOT ───────────────
        story.append(Paragraph("DUE DILIGENCE REPORT", title_style))
        story.append(Spacer(1, 0.15*inch))

        company = analysis.get('company_name', 'Unknown')
        industry = analysis.get('industry', 'Unknown')

        story.append(Paragraph(f"<b>{company}</b>", heading_style))
        story.append(Paragraph(
            f"Industry: {industry} &nbsp;|&nbsp; "
            f"Report Date: {datetime.now().strftime('%B %d, %Y')}",
            body_style
        ))
        story.append(Spacer(1, 0.2*inch))

        # Pull status data early — used both in alert and snapshot table
        status_obj = analysis.get('company_financial_legal_status', {})
        overall_status = status_obj.get('overall_status', 'UNKNOWN')

        # Only show an alert banner if something is actually wrong
        if overall_status in ['DISTRESSED', 'CRITICAL']:
            story.append(Paragraph(
                f"<b>⚠️ COMPANY STATUS ALERT: {overall_status}</b><br/>"
                f"{_esc(status_obj.get('notes', ''))}",
                alert_style
            ))
            story.append(Spacer(1, 0.15*inch))

        # Two-column layout: unverified claims table LEFT, financial/legal snapshot RIGHT
        unverified = analysis.get('unverified_claims', [])
        priority_counts = {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
        for c in unverified:
            p = c.get('priority', 'LOW')
            priority_counts[p] = priority_counts.get(p, 0) + 1

        bank = status_obj.get('bankruptcy_insolvency', {})
        fund = status_obj.get('recent_funding', {})
        ip   = status_obj.get('ip_ownership', {})
        lit  = status_obj.get('litigation_liabilities', {})

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
            ['Active litigation', 'YES' if has_lit else 'NONE FOUND'],
        ]

        def make_snapshot_table(data):
            t = Table(data, colWidths=[3.5*inch, 2.5*inch])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2d5f3f')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
            ]))
            return t

        story.append(make_snapshot_table(left_data))
        story.append(Spacer(1, 0.15*inch))
        story.append(make_snapshot_table(right_data))
        story.append(Spacer(1, 0.25*inch))

        # Flag any specific financial/legal issues inline as brief callouts
        if bank_status not in ['NONE FOUND', 'UNKNOWN', 'ACTIVE'] and bank.get('details'):
            story.append(Paragraph(
                f"<b>⚠️ Bankruptcy/Insolvency:</b> {_esc(bank['details'])} "
                f"— {_esc(bank.get('implications', ''))}",
                alert_style
            ))
        if fund_outcome == 'FAILED' and fund.get('failure_reasons'):
            sought = (fund.get('amount_sought') or 0) / 1e6
            story.append(Paragraph(
                f"<b>⚠️ Failed Funding Round:</b> Sought &#36;{sought:.1f}M — "
                f"{_esc(fund.get('failure_reasons', 'Reasons not disclosed'))}",
                alert_style
            ))
        if ip_status in ['DISPUTED', 'ENCUMBERED'] and ip.get('details'):
            story.append(Paragraph(
                f"<b>⚠️ IP {ip_status}:</b> {_esc(ip.get('details', ''))} "
                f"{('— ' + _esc(ip['encumbrances'])) if ip.get('encumbrances') else ''}",
                alert_style
            ))
        if has_lit:
            lawsuits = lit.get('active_lawsuits', [])
            story.append(Paragraph(
                f"<b>⚠️ Active Litigation:</b> {_esc('; '.join(lawsuits))}"
                f"{(' — Debts: ' + _esc(lit['outstanding_debts'])) if lit.get('outstanding_debts') else ''}",
                alert_style
            ))

        # Company overview
        overview = analysis.get('company_overview', {})
        story.append(Paragraph("COMPANY OVERVIEW", heading_style))
        story.append(Paragraph(_esc(overview.get('description', 'Not available')), body_style))
        story.append(Paragraph(f"<b>Stage:</b> {_esc(overview.get('stage', 'Unknown'))}", body_style))
        if status_obj.get('notes') and overall_status not in ['DISTRESSED', 'CRITICAL']:
            story.append(Paragraph(f"<b>Background:</b> {_esc(status_obj['notes'])}", body_style))

        story.append(PageBreak())

        priority_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']

        def render_unverified_block(uc, counter):
            """Render a single unverified claim with outcome sizing."""
            priority = uc.get('priority', 'LOW')
            outcome = uc.get('outcome_if_true') or {}
            mkt_usd = outcome.get('market_opportunity_usd') or 0
            mkt_str = (f"&#36;{mkt_usd/1e9:.1f}B" if mkt_usd >= 1e9
                       else (f"&#36;{mkt_usd/1e6:.0f}M" if mkt_usd > 0 else "Not quantified"))
            use_style = flag_style if priority in ['MEDIUM', 'LOW'] else alert_style

            story.append(Paragraph(
                f"<b>#{counter} [{priority}] {_esc(uc.get('claim', 'Not specified'))}</b><br/>"
                f"<b>Why Unverified:</b> {_esc(uc.get('why_unverified', 'No independent verification found'))}",
                use_style
            ))
            steps = uc.get('investigation_steps', [])
            if steps:
                story.append(Paragraph(
                    "<b>Steps to Verify:</b> " + " &nbsp;|&nbsp; ".join(f"({j+1}) {_esc(s)}" for j, s in enumerate(steps)),
                    body_style
                ))
            if outcome:
                story.append(Paragraph(
                    f"<b>Outcome If Verified:</b> {_esc(outcome.get('description', ''))} "
                    f"— Opportunity: <b>{mkt_str}</b>",
                    body_style
                ))
                for comp in outcome.get('comparable_companies', []):
                    val = comp.get('comparable_valuation_usd') or 0
                    val_str = f" — valued at &#36;{val/1e9:.1f}B" if val else ""
                    share_str = f" | {_esc(comp['market_share_potential'])}" if comp.get('market_share_potential') else ""
                    story.append(Paragraph(
                        f"<b>↳ {_esc(comp.get('company', 'N/A'))}</b>{val_str}: {_esc(comp.get('context', ''))}{share_str}",
                        verified_style
                    ))
                if outcome.get('key_caveat'):
                    story.append(Paragraph(f"<i>Caveat: {_esc(outcome['key_caveat'])}</i>", body_style))
            story.append(Spacer(1, 0.2*inch))

        def render_claims_table(claims, include_sources=False):
            """Render a compact claims list — status + label only, no duplication of outcome detail."""
            for claim in claims:
                v_status = claim.get('verification_status', 'UNVERIFIED')
                use_style = (verified_style if v_status == 'VERIFIED'
                             else flag_style if v_status == 'PARTIALLY VERIFIED'
                             else alert_style)
                label = '✅' if v_status == 'VERIFIED' else ('⚠️' if v_status == 'PARTIALLY VERIFIED' else '❌')
                claim_text = (
                    f"<b>{label} {_esc(claim.get('claim', 'Not specified'))}</b><br/>"
                    f"{_esc(claim.get('source_label', v_status))}"
                )
                if include_sources and claim.get('sources'):
                    claim_text += f" — <i>{_esc(', '.join(claim['sources'][:2]))}</i>"
                story.append(Paragraph(claim_text, use_style))
                story.append(Spacer(1, 0.08*inch))

        # ── PAGE 3: COMPETITIVE LANDSCAPE ─────────────────────────────────────
        comp_landscape = analysis.get('competitive_landscape', {})
        story.append(Paragraph("COMPETITIVE LANDSCAPE", heading_style))
        story.append(Paragraph(
            _esc(comp_landscape.get('positioning_summary', '')),
            body_style
        ))
        story.append(Spacer(1, 0.15*inch))

        # Peer competitors
        peer_comps = comp_landscape.get('peer_competitors', [])
        if peer_comps:
            story.append(Paragraph("Peer-Stage Competitors", subheading_style))
            for comp in peer_comps:
                funding = comp.get('funding_raised_usd') or 0
                funding_str = f"&#36;{funding/1e6:.0f}M raised" if funding else "Funding unknown"
                peer_text = (
                    f"<b>{_esc(comp.get('name', 'Unknown'))}</b> ({_esc(comp.get('stage', '?'))} — {funding_str})<br/>"
                    f"{_esc(comp.get('description', ''))}<br/>"
                    f"<b>Their edge:</b> {_esc(comp.get('their_differentiator', 'N/A'))}<br/>"
                    f"<b>Company's claimed advantage:</b> {_esc(comp.get('company_advantage_claimed', 'N/A'))}"
                )
                if comp.get('sources'):
                    peer_text += f"<br/><i>Sources: {_esc(', '.join(comp['sources'][:2]))}</i>"
                story.append(Paragraph(peer_text, body_style))
                story.append(Spacer(1, 0.12*inch))

        # Market leaders
        leaders = comp_landscape.get('market_leaders', [])
        if leaders:
            story.append(Paragraph("Market Leaders & Incumbents", subheading_style))
            for leader in leaders:
                leader_text = (
                    f"<b>{_esc(leader.get('name', 'Unknown'))}</b> — {_esc(leader.get('market_position', ''))}<br/>"
                    f"{_esc(leader.get('valuation_or_revenue', ''))}<br/>"
                    f"{_esc(leader.get('description', ''))}<br/>"
                    f"<b>Threat to company:</b> {_esc(leader.get('threat_to_company', 'N/A'))}"
                )
                if leader.get('sources'):
                    leader_text += f"<br/><i>Sources: {_esc(', '.join(leader['sources'][:2]))}</i>"
                story.append(Paragraph(leader_text, body_style))
                story.append(Spacer(1, 0.12*inch))

        risks = comp_landscape.get('competitive_risks', [])
        acquirers = comp_landscape.get('potential_acquirers', [])
        if risks or acquirers:
            row = []
            if risks:
                row.append(["Key Competitive Risks"] + [f"• {r}" for r in risks])
            if acquirers:
                row.append(["Potential Acquirers"] + [f"• {a}" for a in acquirers])
            for section_items in row:
                story.append(Paragraph(f"<b>{section_items[0]}:</b>", body_style))
                for item in section_items[1:]:
                    story.append(Paragraph(item, body_style))

        story.append(PageBreak())

        # ── PAGE 4: TECHNOLOGY CLAIMS + UNVERIFIED TECH ───────────────────────
        story.append(Paragraph("TECHNOLOGY CLAIMS", heading_style))
        story.append(Paragraph(
            "<i>Quick-scan status of all technology claims. "
            "Unverified claims with full investigation detail and outcome sizing follow below.</i>",
            body_style
        ))
        story.append(Spacer(1, 0.1*inch))

        render_claims_table(analysis.get('technology_claims', []), include_sources=True)

        tech_unverified = sorted(
            [uc for uc in unverified if uc.get('category', '').lower() == 'technology'],
            key=lambda c: priority_order.index(c.get('priority', 'LOW')) if c.get('priority', 'LOW') in priority_order else 3
        )
        unverified_counter = 1
        if tech_unverified:
            story.append(Spacer(1, 0.15*inch))
            story.append(Paragraph("Unverified Technology Claims — Investigation & Outcome", subheading_style))
            story.append(Spacer(1, 0.05*inch))
            for uc in tech_unverified:
                render_unverified_block(uc, unverified_counter)
                unverified_counter += 1

        story.append(PageBreak())

        # ── PAGE 5: MARKET CLAIMS + UNVERIFIED MARKET ────────────────────────
        story.append(Paragraph("MARKET CLAIMS", heading_style))
        story.append(Paragraph(
            "<i>Quick-scan status of all market claims. "
            "Unverified claims with full investigation detail and outcome sizing follow below.</i>",
            body_style
        ))
        story.append(Spacer(1, 0.1*inch))

        render_claims_table(analysis.get('market_claims', []), include_sources=True)

        market_unverified = sorted(
            [uc for uc in unverified if uc.get('category', '').lower() == 'market'],
            key=lambda c: priority_order.index(c.get('priority', 'LOW')) if c.get('priority', 'LOW') in priority_order else 3
        )
        if market_unverified:
            story.append(Spacer(1, 0.15*inch))
            story.append(Paragraph("Unverified Market Claims — Investigation & Outcome", subheading_style))
            story.append(Spacer(1, 0.05*inch))
            for uc in market_unverified:
                render_unverified_block(uc, unverified_counter)
                unverified_counter += 1

        # Other unverified claims (Financial, Team, Legal)
        other_unverified = sorted(
            [uc for uc in unverified if uc.get('category', '').lower() not in ('technology', 'market')],
            key=lambda c: priority_order.index(c.get('priority', 'LOW')) if c.get('priority', 'LOW') in priority_order else 3
        )
        if other_unverified:
            story.append(Spacer(1, 0.15*inch))
            story.append(Paragraph("Other Unverified Claims (Financial / Team / Legal)", subheading_style))
            story.append(Spacer(1, 0.05*inch))
            for uc in other_unverified:
                render_unverified_block(uc, unverified_counter)
                unverified_counter += 1

        story.append(PageBreak())

        # ── PAGE 6: OUTCOME MAGNITUDE + CONCLUSION ────────────────────────────
        story.append(Paragraph("OUTCOME MAGNITUDE", heading_style))
        story.append(Paragraph(
            "<i>If the major claims hold up, what could this company become? "
            "Compared against real companies in the same space.</i>",
            body_style
        ))
        story.append(Spacer(1, 0.2*inch))

        magnitude = analysis.get('outcome_magnitude', {})

        if_all = magnitude.get('if_all_claims_verified', {})
        if if_all:
            story.append(Paragraph("If All Major Claims Are Verified:", subheading_style))
            story.append(Paragraph(_esc(if_all.get('description', 'Not available')), body_style))
            story.append(Paragraph(_esc(if_all.get('framing', '')), body_style))
            mkt = if_all.get('addressable_market_usd') or 0
            share = if_all.get('realistic_market_share_pct') or 0
            mkt_str_all = f"&#36;{mkt/1e9:.1f}B" if mkt > 0 else "Not quantified"
            details_text = (
                f"<b>Addressable Market:</b> {mkt_str_all}<br/>"
                f"<b>Realistic Market Share:</b> {share}%<br/>"
            )
            if if_all.get('comparable_companies'):
                details_text += f"<b>Comparable Companies:</b> {_esc(', '.join(if_all['comparable_companies']))}<br/>"
            story.append(Paragraph(details_text, body_style))
            story.append(Spacer(1, 0.2*inch))

        if_core = magnitude.get('if_core_tech_only_verified', {})
        if if_core:
            story.append(Paragraph("If Only Core Technology Is Verified:", subheading_style))
            story.append(Paragraph(_esc(if_core.get('description', 'Not available')), body_style))
            story.append(Paragraph(_esc(if_core.get('framing', '')), body_style))
            mkt = if_core.get('addressable_market_usd') or 0
            mkt_str_core = f"&#36;{mkt/1e9:.1f}B" if mkt > 0 else "Not quantified"
            details_text = f"<b>Addressable Market:</b> {mkt_str_core}<br/>"
            if if_core.get('comparable_companies'):
                details_text += f"<b>Comparable Companies:</b> {_esc(', '.join(if_core['comparable_companies']))}<br/>"
            story.append(Paragraph(details_text, body_style))
            story.append(Spacer(1, 0.2*inch))

        deps = magnitude.get('key_dependencies', [])
        if deps:
            story.append(Paragraph("What Must Be Proven First:", subheading_style))
            for dep in deps:
                story.append(Paragraph(f"• {_esc(dep)}", body_style))

        story.append(Spacer(1, 0.3*inch))

        # ── CONCLUSION ────────────────────────────────────────────────────────
        story.append(Paragraph("CONCLUSION", heading_style))

        critical_claims = [uc for uc in unverified if uc.get('priority') == 'CRITICAL']
        high_claims = [uc for uc in unverified if uc.get('priority') == 'HIGH']

        conclusion_intro = (
            f"This report identified <b>{len(unverified)} unverified claims</b> across "
            f"{company}'s pitch deck, of which <b>{len(critical_claims)} are critical</b> and "
            f"<b>{len(high_claims)} are high priority</b> for investigation."
        )
        story.append(Paragraph(conclusion_intro, body_style))

        if critical_claims:
            story.append(Paragraph("Critical Claims Requiring Immediate Investigation:", subheading_style))
            for uc in critical_claims:
                outcome = uc.get('outcome_if_true') or {}
                mkt_usd = outcome.get('market_opportunity_usd') or 0
                mkt_str = (f"${mkt_usd/1e9:.1f}B" if mkt_usd >= 1e9
                           else (f"${mkt_usd/1e6:.0f}M" if mkt_usd > 0 else "unquantified"))
                story.append(Paragraph(
                    f"• <b>{uc.get('claim', 'Not specified')}</b> — "
                    f"potential outcome: {mkt_str}",
                    body_style
                ))

        if if_all.get('framing'):
            story.append(Spacer(1, 0.15*inch))
            story.append(Paragraph("Overall Opportunity Context:", subheading_style))
            story.append(Paragraph(if_all.get('framing', ''), body_style))

        story.append(Spacer(1, 0.3*inch))
        method_text = (
            f"<i><b>Methodology:</b> Analysis based on {analysis.get('sources_consulted', '?')} sources "
            f"including court records, financial databases, and industry reports. Confidence scores reflect "
            f"source quality, recency, and corroboration. No investment recommendation is made.</i><br/><br/>"
            f"<b>Report Generated:</b> {datetime.now().strftime('%B %d, %Y at %H:%M:%S')}"
        )
        story.append(Paragraph(method_text, body_style))

        doc.build(story)
        print(f"   ✓ PDF generated: {output_path}")


def main():
    print("=" * 70)
    print("  DUE DILIGENCE REPORT GENERATOR")
    print("  + Surfaces unverified claims and what needs investigation")
    print("  + Sizes potential outcome if claims are proven true")
    print("  + Compares against real market comps")
    print("  + Company financial/legal status check")
    print("=" * 70)
    print()

    if len(sys.argv) < 2:
        print("Usage: python \"DDR(draft 11).py\" <pitch_deck.pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    try:
        analyzer = DueDiligenceAnalyzer(api_key)
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)

    pitch_text = analyzer.extract_pdf(pdf_path)
    analysis = analyzer.analyze(pitch_text)
    scored_analysis = analyzer.add_confidence_scores(analysis)

    company = scored_analysis.get('company_name', 'Company').replace(' ', '_')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = f"{company}_DDR_{timestamp}.pdf"

    analyzer.generate_pdf(scored_analysis, output_path)

    print("\n" + "=" * 70)
    print("✅ REPORT COMPLETE")
    print("=" * 70)
    print(f"\nCompany: {scored_analysis.get('company_name', 'Unknown')}")

    status_obj = scored_analysis.get('company_financial_legal_status', {})
    if status_obj:
        print(f"Company Status: {status_obj.get('overall_status', 'UNKNOWN')}")

    unverified = scored_analysis.get('unverified_claims', [])
    critical = sum(1 for c in unverified if c.get('priority') == 'CRITICAL')
    high = sum(1 for c in unverified if c.get('priority') == 'HIGH')
    print(f"Unverified Claims: {len(unverified)} total ({critical} critical, {high} high priority)")
    print(f"\nReport: {output_path}")
    print()


if __name__ == "__main__":
    main()
