#!/usr/bin/env python3
"""
NayaGram Test Account OTP Sync Service
Strictly reads ONLY official Telegram login code notifications from user ID 777000 (+42777)
for the dedicated Google Play review test account. Personal chats are never accessed.

Modes:
  --once    Fetch recent login codes once and update local codes.json (for GitHub Actions)
  --daemon  Stay connected in real time and push codes.json via GitHub API within 1 second
"""

import argparse
import asyncio
import base64
import datetime
import http.server
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

from telethon import TelegramClient, events
from telethon.sessions import StringSession

TELEGRAM_SERVICE_USER_ID = 777000  # Official Telegram notifications (+42777)
DEFAULT_ACCOUNT = "+8801320917532"
DEFAULT_TTL_MINUTES = 30
MAX_CODES = 10

# Strictly match official Telegram login verification codes (5-6 digits)
OTP_PATTERNS = [
    re.compile(r"(?:Login code|Web login code|Verification code)\s*:\s*(\d{5,6})\b", re.IGNORECASE),
    re.compile(r"\bcode\s*[:\-]\s*(\d{5,6})\b", re.IGNORECASE),
]
FALLBACK_DIGITS = re.compile(r"\b(\d{5,6})\b")
LOGIN_KEYWORDS = ("login", "code", "sign in", "verification", "telegram")


def extract_otp_code(text: str):
    """Return the 5-6 digit Telegram login code if and only if text is a login OTP message."""
    if not text:
        return None
    for pattern in OTP_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1)
    lower = text.lower()
    if any(kw in lower for kw in LOGIN_KEYWORDS):
        # Exclude 42777 phone number itself if mentioned
        for m in FALLBACK_DIGITS.finditer(text):
            candidate = m.group(1)
            if candidate != "42777":
                return candidate
    return None


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def iso_utc(dt: datetime.datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_payload(codes_list: list, account: str, ttl_minutes: int) -> dict:
    cutoff = utc_now() - datetime.timedelta(minutes=ttl_minutes)
    filtered = []
    seen_ids = set()
    for item in codes_list:
        try:
            dt = datetime.datetime.fromisoformat(item["received_at"].replace("Z", "+00:00"))
        except Exception:
            continue
        if dt < cutoff:
            continue
        if item["id"] in seen_ids:
            continue
        seen_ids.add(item["id"])
        filtered.append(item)

    filtered.sort(key=lambda x: x["received_at"], reverse=True)
    filtered = filtered[:MAX_CODES]

    return {
        "account": account,
        "source": "+42777",
        "ttl_minutes": ttl_minutes,
        "updated_at": iso_utc(utc_now()),
        "codes": filtered,
    }


def codes_signature(payload: dict) -> list:
    return [(c["id"], c["code"], c["received_at"]) for c in payload.get("codes", [])]


def write_local_json(path: Path, payload: dict) -> bool:
    """Write codes.json only if codes changed or file does not exist. Returns True if changed."""
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if (
                codes_signature(existing) == codes_signature(payload)
                and existing.get("account") == payload.get("account")
            ):
                return False
        except Exception:
            pass
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return True


def push_to_github_api(payload: dict, repo: str, token: str, branch: str = "main", file_path: str = "codes.json") -> bool:
    """Push updated codes.json directly to GitHub via Contents API (instant live update)."""
    api_url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "nayagram-otp-sync",
        "Content-Type": "application/json",
    }

    sha = None
    try:
        req = urllib.request.Request(f"{api_url}?ref={branch}", headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            current = json.loads(resp.read().decode("utf-8"))
            sha = current.get("sha")
            raw_existing = base64.b64decode(current.get("content", "")).decode("utf-8", errors="ignore")
            try:
                existing_json = json.loads(raw_existing)
                if codes_signature(existing_json) == codes_signature(payload):
                    return False
            except Exception:
                pass
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"[warn] GitHub GET failed: HTTP {e.code}", flush=True)
            return False

    encoded = base64.b64encode((json.dumps(payload, indent=2) + "\n").encode("utf-8")).decode("ascii")
    body = {
        "message": "chore: update verification codes",
        "content": encoded,
        "branch": branch,
    }
    if sha:
        body["sha"] = sha

    put_req = urllib.request.Request(
        api_url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="PUT",
    )
    try:
        with urllib.request.urlopen(put_req, timeout=15) as resp:
            if resp.status in (200, 201):
                print(f"[sync] Published {len(payload['codes'])} active code(s) to {repo}/{file_path}", flush=True)
                return True
    except urllib.error.HTTPError as e:
        print(f"[warn] GitHub PUT failed: HTTP {e.code}", flush=True)
    return False


async def fetch_recent_777000_codes(client: TelegramClient, ttl_minutes: int) -> list:
    """Strictly read ONLY messages from Telegram official service ID 777000 (+42777)."""
    cutoff = utc_now() - datetime.timedelta(minutes=ttl_minutes)
    results = []
    async for msg in client.iter_messages(TELEGRAM_SERVICE_USER_ID, limit=15):
        if msg.sender_id != TELEGRAM_SERVICE_USER_ID:
            continue
        msg_dt = msg.date
        if msg_dt.tzinfo is None:
            msg_dt = msg_dt.replace(tzinfo=datetime.timezone.utc)
        if msg_dt < cutoff:
            break
        code = extract_otp_code(msg.message or "")
        if code:
            results.append({
                "id": f"tg_{msg.id}",
                "code": code,
                "received_at": iso_utc(msg_dt),
                "source": "+42777",
            })
    return results


def start_health_server(port: int):
    """Lightweight health endpoint so free cloud hosts (Koyeb/Render) keep daemon healthy."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok","service":"nayagram-otp-sync"}\n')

        def log_message(self, format, *args):
            return

    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[health] Listening on 0.0.0.0:{port}", flush=True)


async def run(mode: str, output_path: Path):
    api_id_raw = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    session_str = os.environ.get("TELEGRAM_SESSION", "").strip()
    account = os.environ.get("TEST_PHONE_NUMBER", DEFAULT_ACCOUNT).strip() or DEFAULT_ACCOUNT
    ttl_minutes = int(os.environ.get("OTP_TTL_MINUTES", str(DEFAULT_TTL_MINUTES)))
    gh_token = os.environ.get("GITHUB_TOKEN", "").strip()
    gh_repo = os.environ.get("GITHUB_REPOSITORY", "NayaGramPlatform/ALAPGRAM").strip()
    gh_branch = os.environ.get("GITHUB_BRANCH", "main").strip()

    if not api_id_raw or not api_hash:
        print("[error] TELEGRAM_API_ID and TELEGRAM_API_HASH must be set.", file=sys.stderr)
        sys.exit(1)
    if not session_str:
        print("[info] TELEGRAM_SESSION is not configured yet. Run scripts/create_session.py once and add TELEGRAM_SESSION to GitHub Secrets.", flush=True)
        sys.exit(0)

    api_id = int(api_id_raw)
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print("[error] TELEGRAM_SESSION is invalid or revoked. Re-generate with scripts/create_session.py.", file=sys.stderr)
        await client.disconnect()
        sys.exit(1)

    def publish(codes_list: list):
        payload = build_payload(codes_list, account, ttl_minutes)
        if mode == "once":
            changed = write_local_json(output_path, payload)
            print(f"[once] Active codes: {len(payload['codes'])}, changed: {changed}", flush=True)
        else:
            write_local_json(output_path, payload)
            if gh_token and gh_repo:
                push_to_github_api(payload, gh_repo, gh_token, gh_branch)

    # Initial sync on startup
    recent = await fetch_recent_777000_codes(client, ttl_minutes)
    publish(recent)

    if mode == "once":
        await client.disconnect()
        return

    # Real-time daemon mode
    port_env = os.environ.get("PORT", "").strip()
    if port_env.isdigit():
        start_health_server(int(port_env))

    active_codes = list(recent)

    @client.on(events.NewMessage(from_users=TELEGRAM_SERVICE_USER_ID))
    async def on_telegram_service_message(event):
        if event.sender_id != TELEGRAM_SERVICE_USER_ID:
            return
        code = extract_otp_code(event.raw_text or "")
        if not code:
            return
        msg_dt = event.message.date or utc_now()
        entry = {
            "id": f"tg_{event.message.id}",
            "code": code,
            "received_at": iso_utc(msg_dt),
            "source": "+42777",
        }
        active_codes.insert(0, entry)
        print(f"[live] Received new +42777 verification code at {entry['received_at']}", flush=True)
        publish(active_codes)

    async def periodic_expiry_cleanup():
        while True:
            await asyncio.sleep(60)
            publish(active_codes)

    cleanup_task = asyncio.create_task(periodic_expiry_cleanup())
    print("[daemon] Connected and listening strictly to +42777 (777000)...", flush=True)
    try:
        await client.run_until_disconnected()
    finally:
        cleanup_task.cancel()


def main():
    parser = argparse.ArgumentParser(description="NayaGram +42777 OTP Sync")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="Fetch recent codes once and update codes.json")
    group.add_argument("--daemon", action="store_true", help="Listen in real time and publish via GitHub API")
    parser.add_argument("--output", default="codes.json", help="Path to local codes.json")
    args = parser.parse_args()

    mode = "daemon" if args.daemon else "once"
    asyncio.run(run(mode, Path(args.output)))


if __name__ == "__main__":
    main()
