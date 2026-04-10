"""OECM Favourability Tool — Streamlit entry point."""
import streamlit as st

st.set_page_config(page_title="OECM Favourability Tool", layout="wide")

st.markdown(
    "<style>[data-testid='stAppViewBlockContainer'] { opacity: 1 !important; }"
    " .stApp > header + div { opacity: 1 !important; }"
    " div[class*='stale'] { opacity: 1 !important; }</style>",
    unsafe_allow_html=True,
)
st.title("OECM Territorial Favourability Analysis Tool")

tab1, tab2 = st.tabs(["Module 1 — Protection Network Diagnostic", "Module 2 — OECM Favourability Analysis"])

with tab1:
    st.info("Module 1 under development.")

with tab2:
    st.info("Module 2 under development.")
