"""
imap_poller.py — IMAP email poller for PO attachments.

Connects to any IMAP server (Gmail, Outlook, etc.) using credentials from env vars:
  IMAP_HOST, IMAP_PORT, IMAP_USER, IMAP_PASSWORD, IMAP_USE_SSL

Polls INBOX for unread emails containing PDF, XML, or CSV attachments,
downloads each attachment, passes it through the PO intake pipeline,
and marks the email as read.  Runs as a background asyncio task.
"""

import asyncio
import email
import imaplib
import logging
import os
import tempfile
from email.header import decode_header
from typing import Optional

logger = logging.getLogger(__name__)

IMAP_HOST    = os.environ.get("IMAP_HOST", "")
IMAP_PORT    = int(os.environ.get("IMAP_PORT", "993"))
IMAP_USER    = os.environ.get("IMAP_USER", "")
IMAP_PASSWORD = os.environ.get("IMAP_PASSWORD", "")
IMAP_USE_SSL = os.environ.get("IMAP_USE_SSL", "true").lower() not in ("false", "0", "no")
POLL_INTERVAL = int(os.environ.get("IMAP_POLL_INTERVAL", "60"))  # seconds

SUPPORTED_EXTS = (".pdf", ".xml", ".cxml", ".csv")


def _decode_str(s: bytes | str) -> str:
    if isinstance(s, bytes):
        return s.decode("utf-8", errors="replace")
    return s or ""


def _connect() -> imaplib.IMAP4:
    """Open and return an authenticated IMAP connection."""
    if IMAP_USE_SSL:
        conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    else:
        conn = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
    conn.login(IMAP_USER, IMAP_PASSWORD)
    return conn


def _get_attachment_name(part) -> Optional[str]:
    """Extract filename from a MIME part, or None if not an attachment."""
    cd = part.get("Content-Disposition", "")
    if "attachment" not in cd.lower() and "inline" not in cd.lower():
        return None
    raw = part.get_filename()
    if not raw:
        return None
    decoded, enc = decode_header(raw)[0]
    if isinstance(decoded, bytes):
        return decoded.decode(enc or "utf-8", errors="replace")
    return decoded


def poll_once(conn: imaplib.IMAP4) -> list[dict]:
    """
    Fetch all UNSEEN messages, extract PO attachments, mark emails as read.
    Returns list of {filename, content, subject, sender} dicts.
    """
    attachments = []
    conn.select("INBOX")
    _, data = conn.search(None, "UNSEEN")
    msg_ids = data[0].split() if data[0] else []

    if msg_ids:
        logger.info(f"IMAP: {len(msg_ids)} unread email(s) found")

    for msg_id in msg_ids:
        try:
            _, msg_data = conn.fetch(msg_id, "(RFC822)")
            raw_msg = msg_data[0][1]
            msg = email.message_from_bytes(raw_msg)
            subject = _decode_str(msg.get("Subject", ""))
            sender  = _decode_str(msg.get("From", ""))

            found_attachment = False
            for part in msg.walk():
                fname = _get_attachment_name(part)
                if not fname:
                    continue
                ext = os.path.splitext(fname.lower())[1]
                if ext not in SUPPORTED_EXTS:
                    continue
                content = part.get_payload(decode=True)
                if content:
                    attachments.append({
                        "filename": fname,
                        "content":  content,
                        "subject":  subject,
                        "sender":   sender,
                        "msg_id":   msg_id,
                    })
                    found_attachment = True
                    logger.info(f"IMAP: attachment found — {fname} from '{sender}' re: '{subject}'")

            # Mark as read regardless (prevent re-processing even empty emails)
            conn.store(msg_id, "+FLAGS", "\\Seen")

        except Exception as e:
            logger.warning(f"IMAP: error processing message {msg_id}: {e}")

    return attachments


async def run_imap_poller(process_attachment_fn):
    """
    Background task: poll IMAP every POLL_INTERVAL seconds.
    Calls process_attachment_fn(filename, content, source) for each attachment found.
    """
    logger.info(
        f"IMAP poller starting — host={IMAP_HOST}:{IMAP_PORT} "
        f"user={IMAP_USER} ssl={IMAP_USE_SSL} interval={POLL_INTERVAL}s"
    )
    consecutive_errors = 0

    while True:
        try:
            conn = await asyncio.get_event_loop().run_in_executor(None, _connect)
            try:
                attachments = await asyncio.get_event_loop().run_in_executor(
                    None, poll_once, conn
                )
                consecutive_errors = 0

                for att in attachments:
                    fname = att["filename"]
                    ext   = os.path.splitext(fname.lower())[1]
                    src   = "email"
                    try:
                        await process_attachment_fn(fname, att["content"], src)
                        logger.info(f"IMAP: processed {fname}")
                    except Exception as e:
                        logger.error(f"IMAP: failed to process {fname}: {e}")
            finally:
                try:
                    conn.logout()
                except Exception:
                    pass

        except imaplib.IMAP4.error as e:
            consecutive_errors += 1
            logger.error(f"IMAP auth/protocol error (#{consecutive_errors}): {e}")
            if consecutive_errors >= 5:
                logger.error("IMAP: 5 consecutive errors — waiting 10 minutes before retry")
                await asyncio.sleep(600)
                consecutive_errors = 0
        except ConnectionRefusedError:
            logger.error(f"IMAP: connection refused to {IMAP_HOST}:{IMAP_PORT}")
            await asyncio.sleep(120)
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"IMAP poller unexpected error (#{consecutive_errors}): {e}")

        await asyncio.sleep(POLL_INTERVAL)


def imap_credentials_configured() -> bool:
    """Return True if the minimum IMAP credentials are set."""
    return bool(IMAP_HOST and IMAP_USER and IMAP_PASSWORD)
