from __future__ import annotations

import imaplib
import email
import os
from email.header import decode_header
from bs4 import BeautifulSoup

from .types import RawItem


def fetch(
    source_id: str,
    host: str,
    user: str,
    password_env: str,
    folder: str = "INBOX",
    limit: int = 20,
) -> list[RawItem]:
    password = os.environ.get(password_env, "")
    if not password:
        return []

    items: list[RawItem] = []
    try:
        mail = imaplib.IMAP4_SSL(host)
        mail.login(user, password)
        mail.select(folder)
        _, data = mail.search(None, "UNSEEN")
        ids = data[0].split()[-limit:]
        for uid in ids:
            _, msg_data = mail.fetch(uid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            subject = _decode_header(msg.get("Subject", ""))
            body = _extract_body(msg)
            items.append(RawItem(
                source_id=source_id,
                url=None,
                title=subject,
                body_text=body,
                author=msg.get("From"),
            ))
        mail.logout()
    except Exception:
        pass
    return items


def _decode_header(value: str) -> str:
    parts = decode_header(value)
    decoded = []
    for b, enc in parts:
        if isinstance(b, bytes):
            decoded.append(b.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(b)
    return " ".join(decoded)


def _extract_body(msg: email.message.Message) -> str:
    for part in msg.walk():
        ct = part.get_content_type()
        if ct == "text/html":
            html = part.get_payload(decode=True).decode("utf-8", errors="replace")
            return BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)[:4000]
        if ct == "text/plain":
            return part.get_payload(decode=True).decode("utf-8", errors="replace")[:4000]
    return ""
