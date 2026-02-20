"""
VoLo Earth Ventures — Due Diligence Report Generator V2
========================================================
Streamlined 3-step workflow: Extract → Analyze → Generate PDF

V2 improvements over V1:
  - Single Opus API call (analysis + graph1/2 + graph3 benchmark)
  - Single PDF with inline charts (no merge step)
  - ~50% cheaper and ~50% faster

Installation:
    pip install streamlit anthropic pypdf reportlab python-dotenv matplotlib numpy

Run locally:
    streamlit run ddr_app_v2.py
"""

import os
import tempfile
from datetime import datetime

import streamlit as st

from ddr_engine_v2 import extract_pdf, analyze
from ddr_report_v2 import generate_report_pdf, build_charts

# ── API key ───────────────────────────────────────────────────────────────────
def _get_api_key() -> str:
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        return os.environ.get("ANTHROPIC_API_KEY", "")

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="VoLo Earth Ventures · DDR V2",
    page_icon="🌿",
    layout="centered",
)

# ── Styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* ── Fonts & base ── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    /* ── Botanical Luxury — base palette ── */
    .stApp { background-color: #F5F1EB; color: #1a1a1a; }
    .stApp p, .stApp label, .stApp span, .stApp div { color: #1a1a1a; }
    .stMarkdown p { color: #1a1a1a !important; }
    .stCaption, .stCaption p { color: #5A554F !important; }

    /* ── Block container ── */
    .block-container { padding-top: 2rem; max-width: 780px; }

    /* ── Hero banner — deep botanical luxury ── */
    .hero {
        background:
            radial-gradient(ellipse at 20% 80%, rgba(201, 169, 110, 0.08) 0%, transparent 50%),
            radial-gradient(ellipse at 80% 20%, rgba(201, 169, 110, 0.06) 0%, transparent 50%),
            radial-gradient(circle at 60% 100%, rgba(43, 106, 79, 0.25) 0%, transparent 40%),
            linear-gradient(160deg, #061A0E 0%, #0D2818 25%, #143D2B 50%, #1B4332 75%, #2D6A4F 100%);
        border-radius: 16px;
        padding: 3rem 2.2rem 2.2rem 2.2rem;
        margin-bottom: 2rem;
        text-align: center;
        box-shadow:
            0 8px 32px rgba(6, 26, 14, 0.45),
            0 2px 8px rgba(0, 0, 0, 0.15),
            inset 0 1px 0 rgba(201, 169, 110, 0.08);
        border: 1px solid rgba(201, 169, 110, 0.12);
        position: relative;
        overflow: hidden;
    }
    .hero::before {
        content: '';
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: linear-gradient(90deg,
            transparent 0%,
            rgba(201, 169, 110, 0.5) 20%,
            #C9A96E 50%,
            rgba(201, 169, 110, 0.5) 80%,
            transparent 100%);
    }
    .hero * { color: white !important; }
    .hero-logo { font-size: 3.2rem; margin-bottom: 0.5rem; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3)); }
    .hero-brand {
        font-size: 0.8rem;
        font-weight: 500;
        letter-spacing: 0.25em;
        text-transform: uppercase;
        color: #C9A96E !important;
        margin-bottom: 0.6rem;
    }
    .hero-title {
        font-size: 2.1rem;
        font-weight: 700;
        color: #FAFAF8 !important;
        margin: 0 0 0.7rem 0;
        line-height: 1.2;
        letter-spacing: -0.01em;
        text-shadow: 0 2px 12px rgba(0, 0, 0, 0.25);
    }
    .hero-sub {
        font-size: 0.95rem;
        color: #A8C5B0 !important;
        max-width: 520px;
        margin: 0 auto;
        line-height: 1.7;
        font-weight: 300;
    }

    /* ── Upload label ── */
    .upload-label {
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.15em;
        text-transform: uppercase;
        color: #8B7340 !important;
        margin-bottom: 0.5rem;
    }

    /* ── Upload area ── */
    [data-testid="stFileUploader"] {
        border: 2px dashed #81A88E !important;
        border-radius: 12px !important;
        background: #FAFAF8 !important;
        padding: 0.5rem !important;
        transition: all 0.25s ease !important;
    }
    [data-testid="stFileUploader"]:hover {
        border-color: #2D6A4F !important;
        background: #F0EDE6 !important;
        box-shadow: 0 2px 12px rgba(45, 106, 79, 0.1) !important;
    }
    [data-testid="stFileUploader"] * { color: #1a1a1a !important; }
    [data-testid="stFileUploader"] small { color: #5A554F !important; }
    [data-testid="stFileUploaderDropzoneInstructions"] { color: #1a1a1a !important; }
    [data-testid="stFileUploaderDropzoneInstructions"] * { color: #333333 !important; }

    /* ── Buttons — emerald with gold hover ── */
    .stButton > button {
        background: linear-gradient(145deg, #143D2B, #1B6B42, #1B4332) !important;
        color: #FAFAF8 !important;
        font-weight: 600 !important;
        border: 1px solid rgba(201, 169, 110, 0.15) !important;
        padding: 0.75rem 2.2rem !important;
        border-radius: 10px !important;
        font-size: 1rem !important;
        transition: all 0.3s ease !important;
        box-shadow: 0 3px 12px rgba(20, 61, 43, 0.35) !important;
        width: 100% !important;
        letter-spacing: 0.02em !important;
    }
    .stButton > button:hover {
        background: linear-gradient(145deg, #0D2818, #143D2B, #1B4332) !important;
        box-shadow:
            0 6px 20px rgba(20, 61, 43, 0.4),
            0 0 0 1px rgba(201, 169, 110, 0.25) !important;
        transform: translateY(-1px) !important;
        border-color: rgba(201, 169, 110, 0.3) !important;
    }
    .stButton > button:disabled {
        background: #B8B2A2 !important;
        color: #FAFAF8 !important;
        box-shadow: none !important;
        transform: none !important;
        border-color: transparent !important;
        opacity: 0.75 !important;
    }

    /* ── Download button — premium gold glow ── */
    [data-testid="stDownloadButton"] > button {
        background: linear-gradient(145deg, #0D2818, #143D2B, #1B4332) !important;
        color: #FAFAF8 !important;
        font-weight: 700 !important;
        font-size: 1.05rem !important;
        padding: 0.9rem !important;
        border-radius: 12px !important;
        box-shadow:
            0 6px 24px rgba(13, 40, 24, 0.4),
            0 0 0 1px rgba(201, 169, 110, 0.2) !important;
        border: 1px solid rgba(201, 169, 110, 0.2) !important;
        width: 100% !important;
        letter-spacing: 0.03em !important;
        transition: all 0.3s ease !important;
    }
    [data-testid="stDownloadButton"] > button:hover {
        background: linear-gradient(145deg, #061A0E, #0D2818, #143D2B) !important;
        transform: translateY(-2px) !important;
        box-shadow:
            0 8px 28px rgba(13, 40, 24, 0.5),
            0 0 0 1px rgba(201, 169, 110, 0.35),
            0 0 20px rgba(201, 169, 110, 0.08) !important;
        border-color: rgba(201, 169, 110, 0.35) !important;
    }

    /* ── File info box ── */
    .file-info {
        background: linear-gradient(135deg, #EBF3ED, #F0EDE6);
        border-left: 4px solid #C9A96E;
        padding: 0.85rem 1.2rem;
        border-radius: 8px;
        margin: 0.7rem 0;
        font-size: 0.93rem;
        color: #143D2B !important;
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
    }

    /* ── Status steps ── */
    [data-testid="stStatusWidget"] { color: #1a1a1a !important; }
    [data-testid="stStatusWidget"] * { color: #1a1a1a !important; }

    /* ── Success box ── */
    [data-testid="stAlert"] {
        border-radius: 10px !important;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06) !important;
    }
    [data-testid="stAlert"] p { color: #1a1a1a !important; }

    /* ── Footer — gold accent ── */
    .footer {
        text-align: center;
        font-size: 0.78rem;
        color: #5A554F !important;
        padding: 1.8rem 0 0.6rem 0;
        border-top: 1px solid #D4C9B5;
        margin-top: 2.5rem;
    }
    .footer strong { color: #143D2B !important; }
    .footer .gold { color: #8B7340 !important; }

    /* ── Step pills — gold-accented ── */
    .step-row {
        display: flex;
        gap: 0.6rem;
        justify-content: center;
        margin: 1.2rem 0 0.5rem 0;
        flex-wrap: wrap;
    }
    .step-pill {
        background: rgba(201, 169, 110, 0.1);
        border: 1px solid rgba(201, 169, 110, 0.35);
        color: #C9A96E !important;
        border-radius: 20px;
        padding: 0.3rem 0.95rem;
        font-size: 0.76rem;
        font-weight: 500;
        letter-spacing: 0.02em;
        transition: all 0.2s ease;
    }
    .step-pill:hover {
        background: rgba(201, 169, 110, 0.18);
        border-color: rgba(201, 169, 110, 0.5);
    }

    /* ── Divider accent ── */
    .gold-divider {
        height: 1px;
        background: linear-gradient(90deg, transparent 0%, #C9A96E 50%, transparent 100%);
        margin: 1.5rem 0;
        opacity: 0.4;
    }
</style>
""", unsafe_allow_html=True)

# ── Hero Banner ───────────────────────────────────────────────────────────────
st.markdown("""
<div class="hero">
    <div class="hero-logo">🌿</div>
    <div class="hero-brand">VoLo Earth Ventures</div>
    <div class="hero-title">Due Diligence Report Generator</div>
    <div class="hero-sub">
        Upload a pitch deck and receive an IC-ready report surfacing unverified claims,
        competitive landscape, and outcome magnitude — powered by Claude AI.
    </div>
    <div class="step-row">
        <span class="step-pill">Extract</span>
        <span class="step-pill">Analyze + Benchmark</span>
        <span class="step-pill">Generate Report</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ── File uploader ─────────────────────────────────────────────────────────────
st.markdown('<div class="upload-label">📂 Upload Pitch Deck</div>', unsafe_allow_html=True)
uploaded_file = st.file_uploader(
    "Drop a PDF here or click to browse",
    type=["pdf"],
    help="Maximum recommended size: 50MB. Large decks will be analysed on the first ~60,000 characters.",
    label_visibility="collapsed",
)

if uploaded_file:
    file_size_mb = uploaded_file.size / (1024 * 1024)
    st.markdown(
        f'<div class="file-info">📄 <b>{uploaded_file.name}</b> &nbsp;·&nbsp; {file_size_mb:.1f} MB</div>',
        unsafe_allow_html=True,
    )
    if file_size_mb > 50:
        st.warning("This file is very large. Consider compressing the PDF before uploading.")

st.write("")

# ── Run button ────────────────────────────────────────────────────────────────
run_button = st.button(
    "▶ &nbsp; Run Due Diligence Analysis",
    disabled=uploaded_file is None,
    use_container_width=True,
)
if uploaded_file is None:
    st.caption("⬆️ Upload a pitch deck PDF to begin")

# ── Analysis ──────────────────────────────────────────────────────────────────
if run_button and uploaded_file:
    api_key = _get_api_key()
    if not api_key:
        st.error(
            "No API key found. Set **ANTHROPIC_API_KEY** as an environment variable "
            "or add it to the Streamlit Secrets settings."
        )
        st.stop()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name

    try:
        # ── Step 1: Extract ──────────────────────────────────────────────
        with st.status("📄 Extracting text from PDF...", expanded=True) as status:
            pitch_text = extract_pdf(tmp_path)
            char_count = len(pitch_text)
            st.write(f"✓ Extracted {char_count:,} characters")
            if char_count > 60000:
                st.write("⚠️ Deck is large — analysis will use the first ~60,000 characters")
            status.update(label="📄 PDF extracted", state="complete")

        # ── Step 2: Analyze (single Opus call — analysis + benchmark) ──
        with st.status("🔬 Running deep analysis with web research (3–5 minutes)...", expanded=True) as status:
            st.write("Single unified analysis: claims, competitors, benchmarks, and graph data...")
            search_holder = st.empty()
            search_total = [0]

            def _on_search(count):
                search_total[0] += count
                search_holder.write(f"🔍 Web searches performed: {search_total[0]}")

            analysis_result = analyze(api_key, pitch_text, on_progress=_on_search)

            if "error" in analysis_result:
                st.error(f"Analysis error: {analysis_result['error']}")
                st.stop()

            company_name = analysis_result.get("company_name", "Company")
            unverified = analysis_result.get("unverified_claims", [])
            critical = sum(1 for c in unverified if c.get("priority") == "CRITICAL")
            high = sum(1 for c in unverified if c.get("priority") == "HIGH")

            st.write(f"✓ Analysis complete — {company_name}")
            st.write(f"✓ {len(unverified)} unverified claims ({critical} critical, {high} high priority)")

            # Check graph data
            graph_data = analysis_result.get("graph_data")
            if graph_data and "graph3" in graph_data:
                n_comps = len(graph_data.get("graph3", {}).get("competitor_claims", []))
                st.write(f"✓ Technology benchmark — {n_comps} competitors found")
            else:
                st.write("⚠️ Graph data incomplete — charts may be limited")

            status.update(label="🔬 Analysis complete", state="complete")

        # ── Step 3: Generate PDF with inline charts ──────────────────────
        with st.status("📑 Generating report with charts...", expanded=True) as status:
            st.write("Building charts and assembling PDF...")

            # Build charts
            if graph_data:
                figs = build_charts(graph_data)
                st.write(f"✓ {len(figs)} charts generated")
            else:
                figs = []
                st.write("⚠️ No graph data — report generated without charts")

            # Generate single PDF
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = company_name.replace(" ", "_").replace("/", "-")
            output_filename = f"{safe_name}_DDR_Full_{timestamp}.pdf"
            output_path = os.path.join(tempfile.gettempdir(), output_filename)

            generate_report_pdf(analysis_result, graph_data or {}, figs, output_path)

            # Read PDF bytes for download
            with open(output_path, "rb") as f:
                pdf_bytes = f.read()

            st.write(f"✓ Report ready — {len(pdf_bytes) / 1024:.0f} KB")
            status.update(label="📑 Report generated", state="complete")

    except FileNotFoundError as e:
        st.error(f"File error: {e}")
        st.stop()
    except Exception as e:
        st.error(f"An error occurred: {e}")
        st.stop()
    finally:
        os.unlink(tmp_path)

    # Store in session state for download button persistence
    st.session_state["pdf_bytes"] = pdf_bytes
    st.session_state["pdf_filename"] = output_filename
    st.session_state["company_name"] = company_name
    st.session_state["generated_at"] = datetime.now().strftime('%B %d, %Y at %H:%M')

# ── Download section (rendered from session state, survives reruns) ───────────
if "pdf_bytes" in st.session_state:
    st.write("")
    st.success(f"✅ Due diligence report ready — {st.session_state['company_name']}")

    st.download_button(
        label="⬇️  Download Full Report (PDF)",
        data=st.session_state["pdf_bytes"],
        file_name=st.session_state["pdf_filename"],
        mime="application/pdf",
        use_container_width=True,
        key="dl_full",
    )

    st.caption(
        f"Generated {st.session_state['generated_at']} · "
        "Includes due diligence report and analysis charts · "
        "No investment recommendation is made by this tool."
    )

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown('<div class="gold-divider"></div>', unsafe_allow_html=True)
st.markdown("""
<div class="footer">
    🌿 <strong>VoLo Earth Ventures</strong> &nbsp;<span class="gold">·</span>&nbsp;
    Due Diligence Report Generator &nbsp;<span class="gold">·</span>&nbsp;
    Powered by Claude AI
    <br style="margin-bottom:0.3rem;">
    <span style="font-size:0.72rem; opacity:0.7;">No investment recommendation is made by this tool.</span>
    <br style="margin-bottom:0.2rem;">
    Built by <strong>Jack Zawadzki</strong>
</div>
""", unsafe_allow_html=True)
