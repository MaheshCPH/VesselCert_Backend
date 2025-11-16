import contextlib
import io
import traceback

import streamlit as st

import main as ingest_app


def run_ingest_with_capture():
    """Execute main.py and return captured stdout plus any exception."""
    buffer = io.StringIO()
    error = None
    with contextlib.redirect_stdout(buffer):
        try:
            ingest_app.main()
        except Exception as exc:  # noqa: BLE001 - surface full failure details in UI
            error = exc
            traceback.print_exc()
    return buffer.getvalue(), error


st.set_page_config(page_title="Vessel Certificate Downloader", page_icon="📥", layout="centered")
st.title("Vessel Certificate Downloader")
st.caption("Trigger the Microsoft Graph ingest and upload PDFs to Google Cloud Storage.")

if st.button("Run ingest now", type="primary"):
    with st.spinner("Running downloader..."):
        output, err = run_ingest_with_capture()
    if err:
        st.error(f"Run failed: {err}")
    else:
        st.success("Ingest completed successfully.")
    st.code(output or "(no output)", language="text")
else:
    st.info("Click the button above whenever you want to pull the latest PDFs.")
