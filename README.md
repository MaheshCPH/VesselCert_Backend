# Vessel Certificate Mail Downloader

Simple Python utility that authenticates with Microsoft Graph via the client-credential flow, scans a specific mailbox for messages received inside the latest 24-hour Europe/Copenhagen window (06:00 → 06:00), and stores every PDF attachment it finds to disk. Use it to automate downloading of vessel certificates or other operational documents delivered by email.

## Prerequisites
- Python 3.11+
- Azure AD (Entra ID) application registration with `Mail.Read` application permission and admin consent
- Client credentials (tenant ID, client ID, client secret) for the registration

## Setup
1. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install requests msal python-dotenv
   ```
3. Copy `.env` from the sample below (or edit the included template) and fill in your tenant-specific values:
   ```ini
   TENANT_ID=00000000-0000-0000-0000-000000000000
   CLIENT_ID=00000000-0000-0000-0000-000000000000
   CLIENT_SECRET=super-secret-value
   MAILBOX=sharedmailbox@contoso.com
   DOWNLOAD_DIR=/absolute/path/for/pdfs
   ```

## Running the downloader
```bash
python main.py
```

The script will:
1. Authenticate using the provided client credentials.
2. Compute the correct CET window (latest 06:00 to 06:00) and print it in CET and UTC.
3. Enumerate every message in the mailbox received in that window (Graph paging is handled automatically).
4. Download each PDF attachment to `DOWNLOAD_DIR`, naming the file with the receipt timestamp and subject for traceability.

## Operational notes
- The helper functions handle Graph throttling responses (429/503/504) with basic backoff.
- Non-PDF attachments and nested `ItemAttachment` payloads are skipped; extend `download_pdf_attachments` if you need extra formats.
- Run the script via cron/systemd/Task Scheduler if you need a recurring ingest process.
