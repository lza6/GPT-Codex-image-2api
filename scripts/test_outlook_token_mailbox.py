from __future__ import annotations

import argparse
import imaplib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_MESSAGES_URL = "https://graph.microsoft.com/v1.0/me/messages"
GRAPH_SCOPE = "offline_access https://graph.microsoft.com/Mail.Read"
IMAP_SCOPE = "offline_access https://outlook.office.com/IMAP.AccessAsUser.All"
DEFAULT_IMAP_HOST = "outlook.office365.com"


@dataclass(frozen=True)
class OutlookCredential:
    email: str
    password: str
    client_id: str
    refresh_token: str
    line_number: int


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    text: str

    def json(self) -> Any:
        return json.loads(self.text)


def _clean(value: str) -> str:
    return value.replace("\ufeff", "").replace("\u00a0", " ").strip()


def _redact_email(email: str) -> str:
    local, sep, domain = email.partition("@")
    if not sep:
        return "***"
    if len(local) <= 2:
        masked = local[:1] + "***"
    else:
        masked = local[:2] + "***" + local[-1:]
    return f"{masked}@{domain}"


def parse_credentials(path: Path) -> list[OutlookCredential]:
    credentials: list[OutlookCredential] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = _clean(raw_line)
        if not line or "----" not in line:
            continue
        parts = [_clean(part) for part in line.split("----", 3)]
        if len(parts) != 4:
            continue
        email, password, client_id, refresh_token = parts
        if "@" not in email or not client_id or not refresh_token:
            continue
        credentials.append(
            OutlookCredential(
                email=email,
                password=password,
                client_id=client_id,
                refresh_token=refresh_token,
                line_number=line_number,
            )
        )
    return credentials


def _http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 30,
) -> HttpResponse:
    target = url
    if params:
        query = urllib.parse.urlencode(params)
        target = f"{url}?{query}"

    body: bytes | None = None
    request_headers = dict(headers or {})
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

    request = urllib.request.Request(target, data=body, headers=request_headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                status_code=int(response.status),
                text=response.read().decode("utf-8", errors="replace"),
            )
    except urllib.error.HTTPError as error:
        return HttpResponse(
            status_code=int(error.code),
            text=error.read().decode("utf-8", errors="replace"),
        )


def exchange_refresh_token(credential: OutlookCredential, scope: str, timeout: float) -> str:
    response = _http_request(
        "POST",
        TOKEN_URL,
        data={
            "client_id": credential.client_id,
            "grant_type": "refresh_token",
            "refresh_token": credential.refresh_token,
            "scope": scope,
        },
        timeout=timeout,
    )
    try:
        data = response.json()
    except Exception:
        data = {}
    if response.status_code != 200:
        detail = data.get("error_description") or data.get("error") or response.text[:300]
        raise RuntimeError(f"token refresh failed: HTTP {response.status_code}, {detail}")
    access_token = str(data.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("token refresh response did not include access_token")
    return access_token


def _graph_sender(message: dict[str, Any]) -> str:
    sender = message.get("from") or {}
    if isinstance(sender, dict):
        address = sender.get("emailAddress") or {}
        if isinstance(address, dict):
            return str(address.get("address") or address.get("name") or "")
    return ""


def read_graph_messages(access_token: str, limit: int, timeout: float) -> list[dict[str, str]]:
    response = _http_request(
        "GET",
        GRAPH_MESSAGES_URL,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        params={
            "$top": max(1, min(limit, 50)),
            "$orderby": "receivedDateTime desc",
            "$select": "subject,receivedDateTime,from,bodyPreview",
        },
        timeout=timeout,
    )
    try:
        data = response.json()
    except Exception:
        data = {}
    if response.status_code != 200:
        detail = data.get("error", {}).get("message") if isinstance(data.get("error"), dict) else response.text[:300]
        raise RuntimeError(f"graph messages failed: HTTP {response.status_code}, {detail}")
    items = data.get("value") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("graph messages response did not include value[]")
    return [
        {
            "received": str(item.get("receivedDateTime") or ""),
            "from": _graph_sender(item),
            "subject": str(item.get("subject") or ""),
            "preview": str(item.get("bodyPreview") or ""),
        }
        for item in items
        if isinstance(item, dict)
    ]


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _message_text_preview(message: Message, limit: int = 240) -> str:
    text_parts: list[str] = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_maintype() == "multipart":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        try:
            payload = part.get_content()
        except Exception:
            continue
        if payload:
            text_parts.append(str(payload))
        if content_type == "text/plain" and text_parts:
            break
    text = "\n".join(text_parts)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _parse_imap_message(raw: bytes, include_preview: bool) -> dict[str, str]:
    message = message_from_bytes(raw, policy=policy.default)
    received = ""
    try:
        parsed = parsedate_to_datetime(str(message.get("Date") or ""))
        received = parsed.isoformat()
    except Exception:
        received = str(message.get("Date") or "")
    return {
        "received": received,
        "from": _decode_header(str(message.get("From") or "")),
        "subject": _decode_header(str(message.get("Subject") or "")),
        "preview": _message_text_preview(message) if include_preview else "",
    }


def read_imap_messages(access_token: str, email: str, host: str, limit: int, include_preview: bool) -> list[dict[str, str]]:
    auth_string = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
    mailbox = imaplib.IMAP4_SSL(host)
    try:
        mailbox.authenticate("XOAUTH2", lambda _: auth_string.encode("utf-8"))
        status, _ = mailbox.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("imap select INBOX failed")
        status, data = mailbox.uid("search", None, "ALL")
        if status != "OK" or not data or not data[0]:
            return []
        uids = data[0].split()[-max(1, limit) :]
        messages: list[dict[str, str]] = []
        for uid in reversed(uids):
            status, fetched = mailbox.uid("fetch", uid, "(RFC822)")
            if status != "OK":
                continue
            raw_payload = next((item[1] for item in fetched if isinstance(item, tuple) and isinstance(item[1], bytes)), b"")
            if raw_payload:
                messages.append(_parse_imap_message(raw_payload, include_preview))
        return messages
    finally:
        try:
            mailbox.logout()
        except Exception:
            pass


def print_messages(messages: list[dict[str, str]], include_preview: bool) -> None:
    if not messages:
        print("  no recent messages")
        return
    for index, message in enumerate(messages, start=1):
        print(f"  {index}. {message['received']} | {message['from']} | {message['subject']}")
        if include_preview and message.get("preview"):
            print(f"     preview: {message['preview']}")


def test_credential(
    credential: OutlookCredential,
    mode: str,
    limit: int,
    timeout: float,
    imap_host: str,
    include_preview: bool,
    show_email: bool,
) -> bool:
    label = credential.email if show_email else _redact_email(credential.email)
    print(f"[line {credential.line_number}] {label}")
    errors: list[str] = []

    if mode in {"graph", "auto"}:
        try:
            access_token = exchange_refresh_token(credential, GRAPH_SCOPE, timeout)
            messages = read_graph_messages(access_token, limit, timeout)
            print("  graph: ok")
            print_messages(messages, include_preview)
            return True
        except Exception as error:
            errors.append(f"graph: {error}")
            if mode == "graph":
                print(f"  graph: failed - {error}")
                return False

    if mode in {"imap", "auto"}:
        try:
            access_token = exchange_refresh_token(credential, IMAP_SCOPE, timeout)
            messages = read_imap_messages(access_token, credential.email, imap_host, limit, include_preview)
            print("  imap: ok")
            print_messages(messages, include_preview)
            return True
        except Exception as error:
            errors.append(f"imap: {error}")
            if mode == "imap":
                print(f"  imap: failed - {error}")
                return False

    print("  failed")
    for error in errors:
        print(f"  - {error}")
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Test Outlook/Hotmail mailbox access from lines formatted as email----password----client_id----refresh_token.",
    )
    parser.add_argument("--file", default=r"D:\Desktop\yx.txt", help="Credential text file path.")
    parser.add_argument("--mode", choices=("auto", "graph", "imap"), default="auto", help="Mailbox read method.")
    parser.add_argument("--limit-accounts", type=int, default=1, help="How many accounts to test.")
    parser.add_argument("--message-limit", type=int, default=5, help="How many recent messages to list per account.")
    parser.add_argument("--timeout", type=float, default=30, help="HTTP request timeout in seconds.")
    parser.add_argument("--imap-host", default=DEFAULT_IMAP_HOST, help="IMAP host for XOAUTH2 mode.")
    parser.add_argument("--preview", action="store_true", help="Print body preview/snippet. Disabled by default.")
    parser.add_argument("--show-email", action="store_true", help="Print full email address. Secrets are never printed.")
    parser.add_argument("--json", action="store_true", help="Only parse the file and print non-secret account metadata as JSON.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    path = Path(args.file)
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 2

    credentials = parse_credentials(path)
    if not credentials:
        print(f"no valid credentials parsed from: {path}", file=sys.stderr)
        return 2

    limit_accounts = max(1, int(args.limit_accounts or 1))
    selected = credentials[:limit_accounts]

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "line": item.line_number,
                        "email": item.email if args.show_email else _redact_email(item.email),
                        "client_id": item.client_id,
                        "has_password": bool(item.password),
                        "has_refresh_token": bool(item.refresh_token),
                    }
                    for item in selected
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"parsed {len(credentials)} credential(s), testing {len(selected)}")
    success = 0
    for credential in selected:
        if test_credential(
            credential=credential,
            mode=str(args.mode),
            limit=max(1, int(args.message_limit or 1)),
            timeout=max(1.0, float(args.timeout or 30)),
            imap_host=str(args.imap_host),
            include_preview=bool(args.preview),
            show_email=bool(args.show_email),
        ):
            success += 1
    print(f"summary: {success}/{len(selected)} account(s) readable")
    return 0 if success == len(selected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
