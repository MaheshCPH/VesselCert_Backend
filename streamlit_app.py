import zipfile
import contextlib
import io
import traceback
import streamlit as st
import main as ingest_app


def run_ingest_with_capture():
    """Execute main.py and return captured stdout, any exception, and downloaded files."""
    buffer = io.StringIO()
    error = None
    files = []
    with contextlib.redirect_stdout(buffer):
        try:
            files = ingest_app.main()
        except Exception as exc:  # noqa: BLE001 - surface full failure details in UI
            error = exc
            traceback.print_exc()
    return buffer.getvalue(), error, files


st.set_page_config(page_title="Vessel Certificate Downloader", page_icon="📥", layout="centered")
st.title("Vessel Certificate Downloader")
st.caption("Trigger the Microsoft Graph ingest and upload PDFs to Google Cloud Storage.")

if st.button("Run ingest now", type="primary"):
    with st.spinner("Running downloader..."):
        output, err, files = run_ingest_with_capture()
    if err:
        st.error(f"Run failed: {err}")
    else:
        st.success("Ingest completed successfully.")
        
        if files:
            # Create a zip of all files in memory
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname, content in files:
                    zf.writestr(fname, content)
            
            st.download_button(
                label=f"Download {len(files)} files (ZIP)",
                data=zip_buffer.getvalue(),
                file_name="downloaded_certificates.zip",
                mime="application/zip",
            )
        else:
            st.info("No PDF attachments found in the specified window.")

    st.code(output or "(no output)", language="text")
else:
    st.info("Click the button above whenever you want to pull the latest PDFs.")
