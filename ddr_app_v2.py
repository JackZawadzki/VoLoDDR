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

    /* ── Keyframe animations ── */
    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(18px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes fadeIn {
        from { opacity: 0; }
        to   { opacity: 1; }
    }
    @keyframes slideInLeft {
        from { opacity: 0; transform: translateX(-12px); }
        to   { opacity: 1; transform: translateX(0); }
    }
    @keyframes subtleFloat {
        0%, 100% { transform: translateY(0); }
        50%      { transform: translateY(-4px); }
    }
    @keyframes pulseGlow {
        0%, 100% { box-shadow: 0 0 8px rgba(201, 169, 110, 0.15); }
        50%      { box-shadow: 0 0 20px rgba(201, 169, 110, 0.35); }
    }
    @keyframes shimmerSweep {
        0%   { background-position: -200% center; }
        100% { background-position: 200% center; }
    }
    @keyframes scanLine {
        0%   { transform: translateX(-100%); opacity: 0; }
        10%  { opacity: 1; }
        90%  { opacity: 1; }
        100% { transform: translateX(100%); opacity: 0; }
    }
    @keyframes breatheGlow {
        0%, 100% { box-shadow: 0 3px 12px rgba(20, 61, 43, 0.35); }
        50%      { box-shadow: 0 3px 18px rgba(20, 61, 43, 0.55), 0 0 0 2px rgba(201, 169, 110, 0.12); }
    }
    @keyframes rotateDash {
        to { stroke-dashoffset: -20; }
    }
    @keyframes goldDividerGlow {
        0%, 100% { opacity: 0.35; }
        50%      { opacity: 0.65; }
    }
    @keyframes logoFloat {
        0%, 100% { transform: translateY(0) scale(1); filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3)); }
        50%      { transform: translateY(-3px) scale(1.04); filter: drop-shadow(0 6px 12px rgba(201,169,110,0.25)); }
    }
    @keyframes pillFadeIn {
        from { opacity: 0; transform: translateY(8px) scale(0.95); }
        to   { opacity: 1; transform: translateY(0) scale(1); }
    }

    .stApp {
        background-color: #F5F1EB;
        color: #1a1a1a;
    }
    .stApp p, .stApp label, .stApp span, .stApp div { color: #1a1a1a; }
    .stMarkdown p { color: #1a1a1a !important; }
    .stCaption, .stCaption p { color: #5A554F !important; }

    /* ── Block container ── */
    .block-container {
        padding-top: 2rem;
        max-width: 780px;
        animation: fadeIn 0.6s ease-out;
    }

    /* ── Hero banner — frosted glass + depth ── */
    .hero {
        background:
            radial-gradient(ellipse at 20% 80%, rgba(201, 169, 110, 0.08) 0%, transparent 50%),
            radial-gradient(ellipse at 80% 20%, rgba(201, 169, 110, 0.06) 0%, transparent 50%),
            radial-gradient(circle at 60% 100%, rgba(43, 106, 79, 0.25) 0%, transparent 40%),
            linear-gradient(160deg, #061A0E 0%, #0D2818 25%, #143D2B 50%, #1B4332 75%, #2D6A4F 100%);
        border-radius: 20px;
        padding: 3rem 2.2rem 2.2rem 2.2rem;
        margin-bottom: 2rem;
        text-align: center;
        box-shadow:
            0 12px 40px rgba(6, 26, 14, 0.5),
            0 2px 8px rgba(0, 0, 0, 0.15),
            inset 0 1px 0 rgba(201, 169, 110, 0.1);
        border: 1px solid rgba(201, 169, 110, 0.12);
        position: relative;
        overflow: hidden;
        animation: fadeInUp 0.7s ease-out;
    }
    /* Gold accent bar at bottom */
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
    /* Scanning line — tech HUD sweep */
    .hero::after {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        width: 40%;
        height: 100%;
        background: linear-gradient(90deg,
            transparent 0%,
            rgba(201, 169, 110, 0.04) 40%,
            rgba(201, 169, 110, 0.08) 50%,
            rgba(201, 169, 110, 0.04) 60%,
            transparent 100%);
        animation: scanLine 6s ease-in-out infinite;
        pointer-events: none;
    }
    .hero * { color: white !important; }
    .hero-logo {
        font-size: 3.2rem;
        margin-bottom: 0.5rem;
        filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3));
    }
    .hero-brand {
        font-size: 0.8rem;
        font-weight: 500;
        letter-spacing: 0.25em;
        text-transform: uppercase;
        color: #C9A96E !important;
        margin-bottom: 0.6rem;
        text-shadow: 0 0 16px rgba(201, 169, 110, 0.3);
    }
    .hero-title {
        font-size: 2.1rem;
        font-weight: 700;
        color: #FAFAF8 !important;
        margin: 0 0 0.7rem 0;
        line-height: 1.2;
        letter-spacing: -0.01em;
        text-shadow: 0 2px 12px rgba(0, 0, 0, 0.25);
        animation: fadeInUp 0.8s ease-out 0.2s both;
    }
    .hero-sub {
        font-size: 0.95rem;
        color: #A8C5B0 !important;
        max-width: 520px;
        margin: 0 auto;
        line-height: 1.7;
        font-weight: 300;
        animation: fadeInUp 0.8s ease-out 0.4s both;
    }

    /* ── Upload label ── */
    .upload-label {
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.15em;
        text-transform: uppercase;
        color: #8B7340 !important;
        margin-bottom: 0.5rem;
        animation: fadeInUp 0.6s ease-out 0.5s both;
    }

    /* ── Upload area — frosted glass with subtle corner accents ── */
    [data-testid="stFileUploader"] {
        border: 2px dashed #81A88E !important;
        border-radius: 14px !important;
        background: rgba(250, 250, 248, 0.7) !important;
        backdrop-filter: blur(8px) !important;
        -webkit-backdrop-filter: blur(8px) !important;
        padding: 0.5rem !important;
        transition: all 0.35s ease !important;
        animation: fadeInUp 0.6s ease-out 0.6s both;
    }
    [data-testid="stFileUploader"]:hover {
        border-color: #2D6A4F !important;
        background: rgba(240, 237, 230, 0.8) !important;
        box-shadow:
            0 4px 20px rgba(45, 106, 79, 0.12),
            inset 0 0 0 1px rgba(45, 106, 79, 0.06) !important;
    }
    [data-testid="stFileUploader"] * { color: #1a1a1a !important; }
    [data-testid="stFileUploader"] small { color: #5A554F !important; }
    [data-testid="stFileUploaderDropzoneInstructions"] { color: #1a1a1a !important; }
    [data-testid="stFileUploaderDropzoneInstructions"] * { color: #333333 !important; }

    /* ── Buttons — emerald with sweep + breathing glow ── */
    .stButton > button {
        background: linear-gradient(145deg, #143D2B, #1B6B42, #1B4332) !important;
        color: #FAFAF8 !important;
        font-weight: 600 !important;
        border: 1px solid rgba(201, 169, 110, 0.15) !important;
        padding: 0.75rem 2.2rem !important;
        border-radius: 12px !important;
        font-size: 1rem !important;
        transition: all 0.35s ease !important;
        box-shadow: 0 3px 12px rgba(20, 61, 43, 0.35) !important;
        width: 100% !important;
        letter-spacing: 0.02em !important;
        position: relative !important;
        overflow: hidden !important;
        animation: breatheGlow 3s ease-in-out infinite;
    }
    /* Light sweep on hover */
    .stButton > button::after {
        content: '';
        position: absolute;
        top: 0;
        left: -100%;
        width: 60%;
        height: 100%;
        background: linear-gradient(90deg,
            transparent 0%,
            rgba(255, 255, 255, 0.08) 40%,
            rgba(255, 255, 255, 0.15) 50%,
            rgba(255, 255, 255, 0.08) 60%,
            transparent 100%);
        transition: left 0.5s ease;
    }
    .stButton > button:hover::after {
        left: 100%;
    }
    .stButton > button:hover {
        background: linear-gradient(145deg, #0D2818, #143D2B, #1B4332) !important;
        box-shadow:
            0 6px 24px rgba(20, 61, 43, 0.45),
            0 0 0 1px rgba(201, 169, 110, 0.25) !important;
        transform: translateY(-2px) !important;
        border-color: rgba(201, 169, 110, 0.3) !important;
    }
    .stButton > button:disabled {
        background: #B8B2A2 !important;
        color: #FAFAF8 !important;
        box-shadow: none !important;
        transform: none !important;
        border-color: transparent !important;
        opacity: 0.75 !important;
        animation: none !important;
    }

    /* ── Download button — gold shimmer sweep ── */
    [data-testid="stDownloadButton"] > button {
        background: linear-gradient(145deg, #0D2818, #143D2B, #1B4332) !important;
        color: #FAFAF8 !important;
        font-weight: 700 !important;
        font-size: 1.05rem !important;
        padding: 0.9rem !important;
        border-radius: 14px !important;
        box-shadow:
            0 6px 24px rgba(13, 40, 24, 0.4),
            0 0 0 1px rgba(201, 169, 110, 0.2) !important;
        border: 1px solid rgba(201, 169, 110, 0.25) !important;
        width: 100% !important;
        letter-spacing: 0.03em !important;
        transition: all 0.35s ease !important;
        position: relative !important;
        overflow: hidden !important;
        animation: fadeInUp 0.5s ease-out both;
    }
    /* Gold shimmer loop */
    [data-testid="stDownloadButton"] > button::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: linear-gradient(
            105deg,
            transparent 0%,
            transparent 35%,
            rgba(201, 169, 110, 0.12) 45%,
            rgba(201, 169, 110, 0.2) 50%,
            rgba(201, 169, 110, 0.12) 55%,
            transparent 65%,
            transparent 100%
        );
        background-size: 200% 100%;
        animation: shimmerSweep 3s ease-in-out infinite;
        pointer-events: none;
    }
    [data-testid="stDownloadButton"] > button:hover {
        background: linear-gradient(145deg, #061A0E, #0D2818, #143D2B) !important;
        transform: translateY(-2px) !important;
        box-shadow:
            0 8px 32px rgba(13, 40, 24, 0.5),
            0 0 0 1px rgba(201, 169, 110, 0.35),
            0 0 24px rgba(201, 169, 110, 0.1) !important;
        border-color: rgba(201, 169, 110, 0.4) !important;
    }

    /* ── File info box — frosted glass ── */
    .file-info {
        background: linear-gradient(135deg, rgba(235, 243, 237, 0.75), rgba(240, 237, 230, 0.75));
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border-left: 4px solid #C9A96E;
        padding: 0.85rem 1.2rem;
        border-radius: 10px;
        margin: 0.7rem 0;
        font-size: 0.93rem;
        color: #143D2B !important;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
        animation: slideInLeft 0.4s ease-out;
    }

    /* ── Status steps — clean with green tint ── */
    [data-testid="stStatusWidget"] {
        color: #1a1a1a !important;
        border-radius: 12px !important;
        animation: fadeIn 0.4s ease-out;
    }
    [data-testid="stStatusWidget"] * { color: #1a1a1a !important; }

    /* ── Success box ── */
    [data-testid="stAlert"] {
        border-radius: 12px !important;
        box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06) !important;
        animation: fadeInUp 0.5s ease-out;
    }
    [data-testid="stAlert"] p { color: #1a1a1a !important; }

    /* ── Footer — refined with glow ── */
    .footer {
        text-align: center;
        font-size: 0.78rem;
        color: #5A554F !important;
        padding: 1.8rem 0 0.6rem 0;
        border-top: 1px solid #D4C9B5;
        margin-top: 2.5rem;
        position: relative;
        animation: fadeIn 0.8s ease-out;
    }
    .footer strong {
        color: #143D2B !important;
        text-shadow: 0 0 12px rgba(20, 61, 43, 0.15);
    }
    .footer .gold { color: #8B7340 !important; }

    /* ── Step pills — animated pipeline ── */
    .step-row {
        display: flex;
        gap: 0.5rem;
        justify-content: center;
        align-items: center;
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
        transition: all 0.3s ease;
        animation: pillFadeIn 0.5s ease-out both;
    }
    .step-pill:nth-child(1) { animation-delay: 0.5s; }
    .step-pill:nth-child(3) { animation-delay: 0.65s; }
    .step-pill:nth-child(5) { animation-delay: 0.8s; }
    .step-pill:hover {
        background: rgba(201, 169, 110, 0.2);
        border-color: rgba(201, 169, 110, 0.55);
        transform: translateY(-1px);
        box-shadow: 0 2px 10px rgba(201, 169, 110, 0.15);
    }
    /* Connecting arrows between pills */
    .step-arrow {
        color: rgba(201, 169, 110, 0.4) !important;
        font-size: 0.7rem;
        animation: pillFadeIn 0.5s ease-out both;
    }
    .step-arrow:nth-child(2) { animation-delay: 0.58s; }
    .step-arrow:nth-child(4) { animation-delay: 0.73s; }

    /* ── Gold divider — animated glow ── */
    .gold-divider {
        height: 1px;
        background: linear-gradient(90deg, transparent 0%, #C9A96E 50%, transparent 100%);
        margin: 1.5rem 0;
        animation: goldDividerGlow 4s ease-in-out infinite;
    }

    /* ── Botanical leaf accent for footer ── */
    .footer-leaf {
        display: inline-block;
        animation: subtleFloat 5s ease-in-out infinite;
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
        <span class="step-arrow">&#9656;</span>
        <span class="step-pill">Analyze + Benchmark</span>
        <span class="step-arrow">&#9656;</span>
        <span class="step-pill">Generate Report</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ── File uploader ─────────────────────────────────────────────────────────────
st.markdown('<div class="upload-label">Upload Pitch Deck</div>', unsafe_allow_html=True)
uploaded_file = st.file_uploader(
    "Drop a PDF here or click to browse",
    type=["pdf"],
    help="Maximum recommended size: 50MB. Large decks will be analysed on the first ~60,000 characters.",
    label_visibility="collapsed",
)

if uploaded_file:
    file_size_mb = uploaded_file.size / (1024 * 1024)
    st.markdown(
        f'<div class="file-info"><b>{uploaded_file.name}</b> &nbsp;&middot;&nbsp; {file_size_mb:.1f} MB</div>',
        unsafe_allow_html=True,
    )
    if file_size_mb > 50:
        st.warning("This file is very large. Consider compressing the PDF before uploading.")

st.write("")

# ── Run button ────────────────────────────────────────────────────────────────
run_button = st.button(
    "Run Due Diligence Analysis",
    disabled=uploaded_file is None,
    use_container_width=True,
)
if uploaded_file is None:
    st.caption("Upload a pitch deck PDF to begin")

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
        with st.status("Extracting text from PDF...", expanded=False) as status:
            pitch_text = extract_pdf(tmp_path)
            char_count = len(pitch_text)
            status.update(label="PDF extracted", state="complete", expanded=False)

        # ── Step 2: Analyze (single Opus call — analysis + benchmark) ──
        with st.status("Running deep analysis with web research (3-5 min)...", expanded=True) as status:
            search_holder = st.empty()
            search_total = [0]

            def _on_search(count):
                search_total[0] += count
                search_holder.write(f"Web searches performed: {search_total[0]}")

            analysis_result = analyze(api_key, pitch_text, on_progress=_on_search)

            if "error" in analysis_result:
                st.error(f"Analysis error: {analysis_result['error']}")
                st.stop()

            company_name = analysis_result.get("company_name", "Company")
            unverified = analysis_result.get("unverified_claims", [])
            critical = sum(1 for c in unverified if c.get("priority") == "CRITICAL")
            high = sum(1 for c in unverified if c.get("priority") == "HIGH")

            # Check graph data
            graph_data = analysis_result.get("graph_data")

            status.update(label="Analysis complete", state="complete", expanded=False)

        # ── Step 3: Generate PDF with inline charts ──────────────────────
        with st.status("Generating report with charts...", expanded=False) as status:
            # Build charts
            if graph_data:
                figs = build_charts(graph_data)
            else:
                figs = []

            # Generate single PDF
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = company_name.replace(" ", "_").replace("/", "-")
            output_filename = f"{safe_name}_DDR_Full_{timestamp}.pdf"
            output_path = os.path.join(tempfile.gettempdir(), output_filename)

            generate_report_pdf(analysis_result, graph_data or {}, figs, output_path)

            # Read PDF bytes for download
            with open(output_path, "rb") as f:
                pdf_bytes = f.read()

            status.update(label="Report generated", state="complete", expanded=False)

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
    st.success(f"Due diligence report ready — {st.session_state['company_name']}")

    st.download_button(
        label="Download Full Report (PDF)",
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
    <span class="footer-leaf">🌿</span> <strong>VoLo Earth Ventures</strong> &nbsp;<span class="gold">&middot;</span>&nbsp;
    Due Diligence Report Generator &nbsp;<span class="gold">&middot;</span>&nbsp;
    Powered by Claude AI
    <br style="margin-bottom:0.3rem;">
    <span style="font-size:0.72rem; opacity:0.7;">No investment recommendation is made by this tool.</span>
    <br style="margin-bottom:0.2rem;">
    Built by <strong>Jack Zawadzki</strong>
</div>
""", unsafe_allow_html=True)
