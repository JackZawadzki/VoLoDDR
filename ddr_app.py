"""
DDR Streamlit App
=================
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
# This imports DueDiligenceAnalyzer without running main()
_ddr_path = Path(__file__).parent / "DDR(draft 11).py"
_spec = importlib.util.spec_from_file_location("ddr_module", _ddr_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
DueDiligenceAnalyzer = _mod.DueDiligenceAnalyzer

# ── API key: try Streamlit secrets first, then environment ───────────────────
def get_api_key() -> str:
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        return os.environ.get("ANTHROPIC_API_KEY", "")

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Due Diligence Report Generator",
    page_icon="🔬",
    layout="centered",
)

# ── Styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { max-width: 760px; }
    .stButton > button {
        background-color: #2d5f3f;
        color: white;
        font-weight: 600;
        border: none;
        padding: 0.6rem 2rem;
        border-radius: 6px;
        font-size: 1rem;
    }
    .stButton > button:hover { background-color: #1a472a; }
    .status-box {
        background: #f0f7f2;
        border-left: 4px solid #2d5f3f;
        padding: 1rem 1.2rem;
        border-radius: 4px;
        margin: 0.5rem 0;
        font-size: 0.95rem;
    }
    .warn-box {
        background: #fff8e1;
        border-left: 4px solid #f59e0b;
        padding: 0.8rem 1.2rem;
        border-radius: 4px;
        margin: 0.5rem 0;
        font-size: 0.9rem;
    }
    h1 { color: #2d5f3f; }
    h2 { color: #2d5f3f; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🔬 Due Diligence Report Generator")
st.markdown(
    "Upload a pitch deck PDF to generate an IC-ready due diligence report. "
    "The report surfaces unverified claims, maps the competitive landscape, "
    "and sizes the potential outcome if each claim is proven true."
)
st.divider()

# ── File uploader ─────────────────────────────────────────────────────────────
uploaded_file = st.file_uploader(
    "Drop a pitch deck PDF here",
    type=["pdf"],
    help="Maximum recommended size: 50MB. Large decks will be analysed on the first ~60,000 characters.",
)

if uploaded_file:
    file_size_mb = uploaded_file.size / (1024 * 1024)
    st.markdown(
        f'<div class="status-box">📄 <b>{uploaded_file.name}</b> — {file_size_mb:.1f} MB uploaded</div>',
        unsafe_allow_html=True,
    )

    if file_size_mb > 50:
        st.warning("This file is very large. Consider compressing the PDF before uploading.")

st.divider()

# ── Run button ────────────────────────────────────────────────────────────────
col1, col2 = st.columns([2, 1])
with col1:
    run_button = st.button("▶ Run Analysis", disabled=uploaded_file is None)
with col2:
    if uploaded_file is None:
        st.caption("Upload a PDF to begin")

# ── Analysis ──────────────────────────────────────────────────────────────────
if run_button and uploaded_file:
    api_key = get_api_key()
    if not api_key:
        st.error(
            "No API key found. Set **ANTHROPIC_API_KEY** as an environment variable "
            "or add it to `.streamlit/secrets.toml`."
        )
        st.stop()

    try:
        analyzer = DueDiligenceAnalyzer(api_key)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    # Save uploaded file to a temp location for pypdf
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
            st.write(f"✓ {len(unverified)} unverified claims found ({critical} critical, {high} high priority)")
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
            status.update(label="📑 PDF generated", state="complete")

    except FileNotFoundError as e:
        st.error(f"File error: {e}")
        st.stop()
    except Exception as e:
        st.error(f"An error occurred: {e}")
        st.stop()
    finally:
        os.unlink(tmp_path)

    # ── Download button ───────────────────────────────────────────────────────
    st.divider()
    st.success("✅ Report complete!")
    with open(output_path, "rb") as f:
        pdf_bytes = f.read()

    st.download_button(
        label="⬇️ Download Full PDF Report",
        data=pdf_bytes,
        file_name=output_filename,
        mime="application/pdf",
        use_container_width=True,
    )

    st.caption(
        f"Report generated {datetime.now().strftime('%B %d, %Y at %H:%M')} · "
        f"{analysis.get('sources_consulted', '?')} sources consulted · "
        "No investment recommendation is made."
    )

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "Due Diligence Report Generator · Powered by Claude · "
    "No investment recommendation is made by this tool."
)
