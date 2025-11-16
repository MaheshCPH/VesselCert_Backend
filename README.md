# Vessel Certificate Mail Downloader

Python utility that authenticates with Microsoft Graph via the client-credential flow, scans a specific mailbox for messages received in the latest 24-hour Europe/Copenhagen window (06:00 → 06:00), and saves every PDF attachment to Google Cloud Storage (an optional local cache can be kept on disk). Use it to automate downloading of vessel certificates or other operational documents delivered by email.

## Prerequisites
- Python 3.11+
- Azure AD (Entra ID) application registration with `Mail.Read` application permission and admin consent
- Client credentials (tenant ID, client ID, client secret) for the registration
- Google Cloud project with Cloud Storage enabled, a destination bucket, and a service account with `roles/storage.objectAdmin` (export the JSON key for local runs)

## Setup
1. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install requests msal python-dotenv google-cloud-storage streamlit
   ```
3. Copy `.env` from the sample below (or edit the included template) and fill in your tenant-specific values:
   ```ini
   TENANT_ID=00000000-0000-0000-0000-000000000000
   CLIENT_ID=00000000-0000-0000-0000-000000000000
   CLIENT_SECRET=super-secret-value
   MAILBOX=sharedmailbox@contoso.com
   GCS_BUCKET_NAME=my-vessel-cert-bucket
   DOWNLOAD_DIR=/optional/local/cache
   ```
4. Point `GOOGLE_APPLICATION_CREDENTIALS` to the downloaded Google service-account JSON file (or authenticate via `gcloud auth application-default login`).

## Running the downloader
```bash
python main.py
```

The script will:
1. Authenticate against Microsoft Graph using the provided client credentials.
2. Authenticate against Google Cloud using Application Default Credentials.
3. Compute the correct CET window (latest 06:00 to 06:00) and print it in CET and UTC.
4. Enumerate every message in the mailbox received in that window (Graph paging is handled automatically).
5. Upload each PDF attachment to the configured Cloud Storage bucket (and optionally stash a copy locally), naming the file with the receipt timestamp and subject for traceability.

## Operational notes
- The helper functions handle Graph throttling responses (429/503/504) with basic backoff.
- Non-PDF attachments and nested `ItemAttachment` payloads are skipped; extend `download_pdf_attachments` if you need extra formats.
- Set `DOWNLOAD_DIR` blank in `.env` if you don’t want to keep local copies; Cloud Storage uploads will still run.
- Run the script via cron/systemd/Task Scheduler if you need a recurring ingest process.

## Web trigger (Streamlit)
1. Ensure the dependencies above are installed (including `streamlit`).
2. Start the UI:
   ```bash
   streamlit run streamlit_app.py
   ```
3. Open the local URL printed by Streamlit (typically http://localhost:8501) and click **Run ingest now** whenever you want to execute `main.py`. The UI shows stdout logs and whether the run succeeded or failed.
- Run the script via cron/systemd/Task Scheduler if you need a recurring ingest process.
