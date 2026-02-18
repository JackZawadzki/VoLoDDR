"""
VoLo Earth Ventures — Due Diligence Report Generator
=====================================================
Web interface for the Due Diligence Report Generator.

Installation:
    pip install streamlit anthropic pypdf reportlab python-dotenv

Run locally:
    streamlit run ddr_app.py

Deploy (Streamlit Community Cloud):
    1. Push this file + DDR(draft 11).py to a GitHub repo
    2. Go to share.streamlit.io → New app → point at ddr_app.py
    3. Add ANTHROPIC_API_KEY in the app's Secrets settings

API Key (local):
    Set ANTHROPIC_API_KEY as an environment variable, or add to .streamlit/secrets.toml:
        ANTHROPIC_API_KEY = "sk-ant-..."
"""

import os
import sys
import tempfile
import importlib.util
from pathlib import Path
from datetime import datetime

import streamlit as st

# ── Load the analyzer from the existing DDR file ─────────────────────────────
_ddr_path = Path(__file__).parent / "DDR(draft 11).py"
_spec = importlib.util.spec_from_file_location("ddr_module", _ddr_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
DueDiligenceAnalyzer = _mod.DueDiligenceAnalyzer

# ── API key ───────────────────────────────────────────────────────────────────
def get_api_key() -> str:
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        return os.environ.get("ANTHROPIC_API_KEY", "")

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="VoLo Earth Ventures · DDR",
    page_icon="🌿",
    layout="centered",
)

# ── Styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* ── Fonts & base ── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    /* ── Force dark text everywhere on light backgrounds ── */
    .stApp { background-color: #f4f8f5; color: #1a1a1a; }
    .stApp p, .stApp label, .stApp span, .stApp div { color: #1a1a1a; }
    .stMarkdown p { color: #1a1a1a !important; }
    .stCaption, .stCaption p { color: #555555 !important; }

    /* ── Block container ── */
    .block-container { padding-top: 2rem; max-width: 780px; }

    /* ── Hero banner (white text on dark green — intentional) ── */
    .hero {
        background: linear-gradient(135deg, #1a472a 0%, #2d5f3f 60%, #3a7d52 100%);
        border-radius: 14px;
        padding: 2.5rem 2rem 2rem 2rem;
        margin-bottom: 1.8rem;
        text-align: center;
        box-shadow: 0 4px 20px rgba(45, 95, 63, 0.3);
    }
    .hero * { color: white !important; }
    .hero-logo { font-size: 2.8rem; margin-bottom: 0.3rem; }
    .hero-brand {
        font-size: 0.85rem;
        font-weight: 600;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: #a8d5b5 !important;
        margin-bottom: 0.5rem;
    }
    .hero-title {
        font-size: 2rem;
        font-weight: 700;
        color: white !important;
        margin: 0 0 0.6rem 0;
        line-height: 1.2;
    }
    .hero-sub {
        font-size: 0.97rem;
        color: #c8e6d2 !important;
        max-width: 520px;
        margin: 0 auto;
        line-height: 1.6;
    }

    /* ── Upload label ── */
    .upload-label {
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #2d5f3f !important;
        margin-bottom: 0.5rem;
    }

    /* ── Upload area — force dark text inside ── */
    [data-testid="stFileUploader"] {
        border: 2px dashed #5a9e72 !important;
        border-radius: 10px !important;
        background: #f9fcfa !important;
        padding: 0.5rem !important;
    }
    [data-testid="stFileUploader"] * { color: #1a1a1a !important; }
    [data-testid="stFileUploader"] small { color: #555555 !important; }
    [data-testid="stFileUploaderDropzoneInstructions"] { color: #1a1a1a !important; }
    [data-testid="stFileUploaderDropzoneInstructions"] * { color: #333333 !important; }

    /* ── Buttons ── */
    .stButton > button {
        background: linear-gradient(135deg, #2d5f3f, #3a7d52) !important;
        color: white !important;
        font-weight: 600 !important;
        border: none !important;
        padding: 0.7rem 2.2rem !important;
        border-radius: 8px !important;
        font-size: 1rem !important;
        transition: all 0.2s !important;
        box-shadow: 0 2px 8px rgba(45, 95, 63, 0.3) !important;
        width: 100% !important;
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #1a472a, #2d5f3f) !important;
        box-shadow: 0 4px 14px rgba(45, 95, 63, 0.45) !important;
        transform: translateY(-1px) !important;
    }
    .stButton > button:disabled {
        background: #b0c8b8 !important;
        color: #ffffff !important;
        box-shadow: none !important;
        transform: none !important;
    }

    /* ── Download button ── */
    [data-testid="stDownloadButton"] > button {
        background: linear-gradient(135deg, #1a472a, #2d5f3f) !important;
        color: white !important;
        font-weight: 700 !important;
        font-size: 1.05rem !important;
        padding: 0.85rem !important;
        border-radius: 10px !important;
        box-shadow: 0 4px 16px rgba(45, 95, 63, 0.4) !important;
        border: none !important;
        width: 100% !important;
    }
    [data-testid="stDownloadButton"] > button:hover {
        background: linear-gradient(135deg, #0f2d1a, #1a472a) !important;
        transform: translateY(-1px) !important;
    }

    /* ── File info box ── */
    .file-info {
        background: #eef7f1;
        border-left: 4px solid #2d5f3f;
        padding: 0.75rem 1.1rem;
        border-radius: 6px;
        margin: 0.6rem 0;
        font-size: 0.93rem;
        color: #1a3d28 !important;
    }

    /* ── Status steps ── */
    [data-testid="stStatusWidget"] { color: #1a1a1a !important; }
    [data-testid="stStatusWidget"] * { color: #1a1a1a !important; }

    /* ── Success box ── */
    [data-testid="stAlert"] { border-radius: 8px !important; }
    [data-testid="stAlert"] p { color: #1a1a1a !important; }

    /* ── Footer ── */
    .footer {
        text-align: center;
        font-size: 0.78rem;
        color: #4a7a5a !important;
        padding: 1.5rem 0 0.5rem 0;
        border-top: 1px solid #c0d8c8;
        margin-top: 2rem;
    }

    /* ── Step pills ── */
    .step-row {
        display: flex;
        gap: 0.5rem;
        justify-content: center;
        margin: 1rem 0 0.5rem 0;
        flex-wrap: wrap;
    }
    .step-pill {
        background: rgba(255,255,255,0.18);
        border: 1px solid rgba(255,255,255,0.35);
        color: white !important;
        border-radius: 20px;
        padding: 0.25rem 0.85rem;
        font-size: 0.78rem;
        font-weight: 500;
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
        <span class="step-pill">📄 Extract</span>
        <span class="step-pill">🔬 Analyze</span>
        <span class="step-pill">📊 Score</span>
        <span class="step-pill">📑 Generate PDF</span>
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
    api_key = get_api_key()
    if not api_key:
        st.error(
            "No API key found. Set **ANTHROPIC_API_KEY** as an environment variable "
            "or add it to the Streamlit Secrets settings."
        )
        st.stop()

    try:
        analyzer = DueDiligenceAnalyzer(api_key)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name

    try:
        # ── Step 1: Extract ───────────────────────────────────────────────────
        with st.status("📄 Extracting text from PDF...", expanded=True) as status:
            pitch_text = analyzer.extract_pdf(tmp_path)
            char_count = len(pitch_text)
            st.write(f"✓ Extracted {char_count:,} characters")
            if char_count > 60000:
                st.write("⚠️ Deck is large — analysis will use the first ~60,000 characters")
            status.update(label="📄 PDF extracted", state="complete")

        # ── Step 2: Analyse ───────────────────────────────────────────────────
        with st.status("🔬 Running deep analysis (2–4 minutes)...", expanded=True) as status:
            st.write("Identifying claims, verification gaps, and competitive landscape...")
            analysis = analyzer.analyze(pitch_text)

            if "error" in analysis:
                st.error(f"Analysis error: {analysis['error']}")
                st.stop()

            company_name = analysis.get("company_name", "Company")
            unverified = analysis.get("unverified_claims", [])
            critical = sum(1 for c in unverified if c.get("priority") == "CRITICAL")
            high = sum(1 for c in unverified if c.get("priority") == "HIGH")

            st.write(f"✓ Analysis complete — {company_name}")
            st.write(f"✓ {len(unverified)} unverified claims ({critical} critical, {high} high priority)")
            status.update(label="🔬 Analysis complete", state="complete")

        # ── Step 3: Score ─────────────────────────────────────────────────────
        with st.status("📊 Adding confidence scores...", expanded=False) as status:
            scored = analyzer.add_confidence_scores(analysis)
            status.update(label="📊 Confidence scores added", state="complete")

        # ── Step 4: Generate PDF ──────────────────────────────────────────────
        with st.status("📑 Generating PDF report...", expanded=False) as status:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = company_name.replace(" ", "_").replace("/", "-")
            output_filename = f"{safe_name}_DDR_{timestamp}.pdf"
            output_path = os.path.join(tempfile.gettempdir(), output_filename)
            analyzer.generate_pdf(scored, output_path)
            status.update(label="📑 PDF report generated", state="complete")

    except FileNotFoundError as e:
        st.error(f"File error: {e}")
        st.stop()
    except Exception as e:
        st.error(f"An error occurred: {e}")
        st.stop()
    finally:
        os.unlink(tmp_path)

    # ── Download ──────────────────────────────────────────────────────────────
    st.write("")
    st.success(f"✅ Due diligence report ready — {company_name}")
    with open(output_path, "rb") as f:
        pdf_bytes = f.read()

    st.download_button(
        label="⬇️  Download Due Diligence Report (PDF)",
        data=pdf_bytes,
        file_name=output_filename,
        mime="application/pdf",
        use_container_width=True,
    )

    st.caption(
        f"Generated {datetime.now().strftime('%B %d, %Y at %H:%M')} · "
        "No investment recommendation is made by this tool."
    )

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="footer">
    🌿 <strong>VoLo Earth Ventures</strong> &nbsp;·&nbsp;
    Due Diligence Report Generator &nbsp;·&nbsp;
    Powered by Claude AI &nbsp;·&nbsp;
    No investment recommendation is made by this tool.
    <br style="margin-bottom:0.3rem;">
    Built by <strong>Jack Zawadzki</strong>
</div>
""", unsafe_allow_html=True)
