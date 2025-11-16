#!/usr/bin/env python3
import os
import time
import base64
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from requests import Request

import requests
from msal import ConfidentialClientApplication
from dotenv import load_dotenv
from google.cloud import storage
from google.api_core.exceptions import NotFound

# ---------- Config ----------
# Put these in environment variables or a secrets manager
# .env keys for local dev:
# TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# CLIENT_SECRET=your-very-secret
# MAILBOX=ingest@company.com
# DOWNLOAD_DIR=/opt/mail_ingest/downloads

load_dotenv()

TENANT_ID     = os.environ["TENANT_ID"]
CLIENT_ID     = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
MAILBOX       = os.environ["MAILBOX"]
DOWNLOAD_DIR  = os.environ.get("DOWNLOAD_DIR", "./downloads").strip()
if not DOWNLOAD_DIR:
    DOWNLOAD_DIR = None
GCS_BUCKET_NAME = os.environ["GCS_BUCKET_NAME"]

GRAPH_SCOPE   = ["https://graph.microsoft.com/.default"]
GRAPH_BASE    = "https://graph.microsoft.com/v1.0"

# ---------- Helpers ----------
def ensure_dir(path: str):
    """Create the target directory if it does not already exist."""
    os.makedirs(path, exist_ok=True)

def get_app_token() -> str:
    """Return an application-only Microsoft Graph access token."""
    app = ConfidentialClientApplication(
        client_id=CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}"
    )
    res = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
    if "access_token" not in res:
        raise RuntimeError(f"Failed to get token: {res}")
    return res["access_token"]

def throttle_sleep(resp):
    """Sleep for the duration suggested by Graph throttling headers."""
    # Simple backoff for 429/503
    retry_after = resp.headers.get("Retry-After")
    if retry_after and retry_after.isdigit():
        time.sleep(int(retry_after))
    else:
        time.sleep(3)

def graph_get(session, url):
    """Perform a GET against Graph, retrying throttled requests and returning JSON."""
    while True:
        r = session.get(url)
        if r.status_code in (429, 503, 504):
            throttle_sleep(r)
            continue
        if r.status_code >= 400:
            try:
                print("[GRAPH ERROR]", r.status_code, r.json())
            except Exception:
                print("[GRAPH ERROR RAW]", r.status_code, r.text)
            r.raise_for_status()
        return r.json()


def graph_get_stream(session, url):
    """Call Microsoft Graph and keep retrying until a streaming response succeeds."""
    while True:
        r = session.get(url, stream=True)
        if r.status_code in (429, 503, 504):
            throttle_sleep(r)
            continue
        r.raise_for_status()
        return r


def get_gcs_bucket():
    """Initialize a Google Cloud Storage bucket client using ADC/service account key."""
    client = storage.Client()
    try:
        return client.get_bucket(GCS_BUCKET_NAME)
    except NotFound as exc:
        raise RuntimeError(f"GCS bucket '{GCS_BUCKET_NAME}' not found or inaccessible.") from exc


def upload_pdf_to_bucket(bucket, blob_name, payload):
    """Store the given PDF payload in Cloud Storage."""
    blob = bucket.blob(blob_name)
    blob.upload_from_string(payload, content_type="application/pdf")

def compute_window_cet():
    """
    Return (start_utc_iso, end_utc_iso) for:
      start = most recent 06:00 Europe/Copenhagen *before* now
      end   = start + 24h
    If it's currently before 06:00, start is yesterday 06:00 → today 06:00.
    If it's after 06:00, start is today 06:00 → tomorrow 06:00 (for manual runs).
    """
    tz = ZoneInfo("Europe/Copenhagen")
    now = datetime.now(tz)
    today_six = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now >= today_six:
        start_local = today_six
    else:
        start_local = (today_six - timedelta(days=1))
    end_local = start_local + timedelta(days=1)

    # Convert to UTC ISO8601 'Z'
    start_utc = start_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
    end_utc   = end_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
    return start_utc, end_utc, start_local, end_local, now

def build_time_filter(start_iso_z, end_iso_z):
    """Build the Graph $filter clause for the provided inclusive/exclusive window."""
    # $filter on receivedDateTime (UTC), inclusive start, exclusive end
    # Note: Graph requires single quotes around timestamps
    return f"receivedDateTime ge {start_iso_z!r} and receivedDateTime lt {end_iso_z!r}"


def list_messages_in_window(session, mailbox, start_iso_z, end_iso_z):
    """Yield messages received within the provided UTC window for a mailbox."""
    flt = f"receivedDateTime ge {start_iso_z} and receivedDateTime lt {end_iso_z}"
    base = f"{GRAPH_BASE}/users/{mailbox}/messages"
    params = {
        "$filter":  flt,
        "$select":  "id,subject,receivedDateTime,hasAttachments",
        "$orderby": "receivedDateTime desc",
        "$top":     "50",
    }
    url = Request("GET", base, params=params).prepare().url

    while True:
        data = graph_get(session, url)
        for m in data.get("value", []):
            yield m
        url = data.get("@odata.nextLink")
        if not url:
            break

def download_pdf_attachments(session, mailbox, message, bucket, outdir=None):
    """Download PDF attachments, optionally keep local copies, and upload to GCS."""
    if not message.get("hasAttachments"):
        return 0
    mid = message["id"]
    att_url = f"{GRAPH_BASE}/users/{mailbox}/messages/{mid}/attachments?$top=50"
    saved = 0

    while True:
        data = graph_get(session, att_url)
        for att in data.get("value", []):
            # FileAttachment has 'contentType' and 'contentBytes'
            if att.get("@odata.type") == "#microsoft.graph.fileAttachment":
                name = att.get("name") or "attachment"
                ctype = att.get("contentType") or ""
                is_pdf = (ctype.lower() == "application/pdf") or name.lower().endswith(".pdf")
                if is_pdf:
                    content_b64 = att.get("contentBytes")
                    if content_b64:
                        blob = base64.b64decode(content_b64)
                        # Build a safe filename: YYYYmmdd_HHMMSS__subject__orig.pdf
                        rdt = message.get("receivedDateTime", "").replace(":", "").replace("-", "")
                        subj = (message.get("subject") or "").strip().replace("/", "_")[:80]
                        fname = f"{rdt}__{subj}__{name}"
                        if outdir:
                            fpath = os.path.join(outdir, fname)
                            with open(fpath, "wb") as f:
                                f.write(blob)
                        upload_pdf_to_bucket(bucket, fname, blob)
                        saved += 1
            # ItemAttachment could wrap an email with its own attachments; skip here or handle if needed.

        att_url = data.get("@odata.nextLink")
        if not att_url:
            break

    return saved

def main():
    """Coordinate downloading PDF attachments across the scheduled time window."""
    local_dir = DOWNLOAD_DIR
    if local_dir:
        ensure_dir(local_dir)
    token = get_app_token()
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})
    bucket = get_gcs_bucket()

    start_iso_z, end_iso_z, start_local, end_local, now_local = compute_window_cet()
    print(f"[INFO] Window (Europe/Copenhagen): {start_local} → {end_local} (now={now_local})")
    print(f"[INFO] Window (UTC): {start_iso_z} → {end_iso_z}")
    print(f"[INFO] Storage bucket: {GCS_BUCKET_NAME}")
    if local_dir:
        print(f"[INFO] Local cache directory: {os.path.abspath(local_dir)}")

    total_msgs = 0
    total_pdfs = 0

    for msg in list_messages_in_window(session, MAILBOX, start_iso_z, end_iso_z):
        total_msgs += 1
        total_pdfs += download_pdf_attachments(session, MAILBOX, msg, bucket, local_dir)

    print(f"[INFO] Messages scanned: {total_msgs}")
    print(f"[INFO] PDF attachments saved: {total_pdfs}")
    print(f"[INFO] Objects available in gs://{GCS_BUCKET_NAME}")
    if local_dir:
        print(f"[INFO] Local cache retained at: {os.path.abspath(local_dir)}")

if __name__ == "__main__":
    main()
