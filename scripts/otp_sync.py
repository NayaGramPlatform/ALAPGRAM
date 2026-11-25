#!/usr/bin/env python3
"""
NayaGram Test Account Real-Time OTP Sync Service
Strictly reads ONLY official Telegram login code notifications from user ID 777000 (+42777)
for the dedicated review test account. Personal chats and phone numbers are never exposed publicly.

Modes:
  --once    Fetch recent +42777 login codes once and update local codes.json (GitHub Actions backup)
  --daemon  Stay connected 24/7 (Render / Koyeb free tier), listen in real time + 10s safety poll,
            push codes.json to GitHub within 1 second, AND serve live /codes.json over HTTP with CORS.
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
PUBLIC_ACCOUNT_LABEL = "NayaGram Test Account"
DEFAULT_TTL_MINUTES = 30
MAX_CODES = 10
DAEMON_POLL_SECONDS = 10

OTP_PATTERNS = [
    re.compile(r"(?:Login code|Web login code|Verification code|Confirmation code)\s*[:\-]?\s*(\d{5,6})\b", re.IGNORECASE),
    re.compile(r"(?:লগইন কোড|ভেরিফিকেশন কোড)\s*[:\-]?\s*(\d{5,6})\b"),
    re.compile(r"\bcode\s*[:\-]\s*(\d{5,6})\b", re.IGNORECASE),
]
FALLBACK_DIGITS = re.compile(r"\b(\d{5,6})\b")
LOGIN_KEYWORDS = ("login", "code", "sign in", "verification", "telegram", "লগইন", "কোড")


def extract_otp_code(text: str):
    if not text:
        return None
    cleaned = re.sub(r"[*_`<>]", "", text)
    for pattern in OTP_PATTERNS:
        m = pattern.search(cleaned)
        if m:
            return m.group(1)
    lower = cleaned.lower()
    if any(kw in lower for kw in LOGIN_KEYWORDS):
        for m in FALLBACK_DIGITS.finditer(cleaned):
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


def build_payload(codes_list: list, ttl_minutes: int) -> dict:
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
        "account": PUBLIC_ACCOUNT_LABEL,
        "source": "+42777",
        "ttl_minutes": ttl_minutes,
        "updated_at": iso_utc(utc_now()),
        "codes": filtered,
    }


def codes_signature(payload: dict) -> list:
    return [(c["id"], c["code"], c["received_at"]) for c in payload.get("codes", [])]


def write_local_json(path: Path, payload: dict) -> bool:
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


def push_to_github_api(
    payload: dict,
    repo: str,
    token: str,
    branch: str = "main",
    file_path: str = "codes.json",
) -> bool:
    """Push updated codes.json to GitHub via Contents API with automatic 409 SHA conflict retry."""
    api_url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "nayagram-otp-sync",
        "Content-Type": "application/json",
    }

    for attempt in range(2):
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
        except Exception as e:
            print(f"[warn] GitHub GET error: {e}", flush=True)
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
                    print(f"[sync] Published {len(payload['codes'])} active code(s) to GitHub", flush=True)
                    return True
        except urllib.error.HTTPError as e:
            if e.code == 409 and attempt == 0:
                print("[info] GitHub 409 SHA conflict, retrying with fresh SHA...", flush=True)
                continue
            print(f"[warn] GitHub PUT failed: HTTP {e.code}", flush=True)
            return False
        except Exception as e:
            print(f"[warn] GitHub PUT error: {e}", flush=True)
            return False
    return False


async def fetch_recent_777000_codes(client: TelegramClient, ttl_minutes: int) -> list:
    cutoff = utc_now() - datetime.timedelta(minutes=ttl_minutes)
    results = []
    async for msg in client.iter_messages(TELEGRAM_SERVICE_USER_ID, limit=20):
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


class LiveState:
    def __init__(self, ttl_minutes: int):
        self.lock = threading.Lock()
        self.connected = False
        self.payload = build_payload([], ttl_minutes)

    def update(self, payload: dict):
        with self.lock:
            self.payload = payload

    def snapshot(self) -> tuple:
        with self.lock:
            return self.connected, dict(self.payload)


def start_http_server(port: int, live_state: LiveState):
    """Serves health pings (GET & HEAD for cron-job.org / UptimeRobot) and live /codes.json with CORS."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def _send_cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Cache-Control", "no-store, max-age=0")

        def do_OPTIONS(self):
            self.send_response(204)
            self._send_cors()
            self.end_headers()

        def do_HEAD(self):
            self.send_response(200)
            self._send_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            connected, payload = live_state.snapshot()

            if path in ("/codes.json", "/api/codes"):
                body = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
            else:
                health = {
                    "status": "ok",
                    "service": "nayagram-otp-sync",
                    "connected": connected,
                    "active_codes": len(payload.get("codes", [])),
                    "updated_at": payload.get("updated_at"),
                }
                body = (json.dumps(health) + "\n").encode("utf-8")

            self.send_response(200)
            self._send_cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[http] Listening on 0.0.0.0:{port} (/health, /codes.json)", flush=True)


async def run_once(api_id: int, api_hash: str, session_str: str, ttl_minutes: int, output_path: Path):
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            print("[error] TELEGRAM_SESSION is invalid or revoked. Re-run Phone Session Setup.", file=sys.stderr)
            sys.exit(1)
        recent = await fetch_recent_777000_codes(client, ttl_minutes)
        payload = build_payload(recent, ttl_minutes)
        changed = write_local_json(output_path, payload)
        print(f"[once] Active codes: {len(payload['codes'])}, changed: {changed}", flush=True)
    finally:
        await client.disconnect()


async def run_daemon(
    api_id: int,
    api_hash: str,
    session_str: str,
    ttl_minutes: int,
    output_path: Path,
    gh_token: str,
    gh_repo: str,
    gh_branch: str,
):
    live_state = LiveState(ttl_minutes)
    port_env = os.environ.get("PORT", "").strip()
    if port_env.isdigit():
        start_http_server(int(port_env), live_state)

    if not gh_token:
        print("[warn] GITHUB_TOKEN is not set! Codes will be served at /codes.json, but GitHub Pages will NOT auto-update until GITHUB_TOKEN is added.", flush=True)

    last_pushed_sig = None
    publish_lock = asyncio.Lock()

    async def sync_publish(codes_list: list, force_check: bool = False):
        nonlocal last_pushed_sig
        async with publish_lock:
            payload = build_payload(codes_list, ttl_minutes)
            live_state.update(payload)
            write_local_json(output_path, payload)
            sig = codes_signature(payload)
            if gh_token and gh_repo and (force_check or sig != last_pushed_sig):
                # Run blocking GitHub HTTP request in worker thread so MTProto never stalls
                await asyncio.to_thread(push_to_github_api, payload, gh_repo, gh_token, gh_branch)
                last_pushed_sig = sig

    while True:
        client = TelegramClient(
            StringSession(session_str),
            api_id,
            api_hash,
            auto_reconnect=True,
            connection_retries=10,
            retry_delay=3,
        )
        poll_task = None
        try:
            await client.connect()
            if not await client.is_user_authorized():
                print("[error] TELEGRAM_SESSION is invalid or revoked. Re-run Phone Session Setup.", file=sys.stderr)
                sys.exit(1)

            live_state.connected = True
            active_codes = await fetch_recent_777000_codes(client, ttl_minutes)
            await sync_publish(active_codes, force_check=True)

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
                print(f"[live] Instant +42777 OTP received at {entry['received_at']}", flush=True)
                await sync_publish(active_codes)

            async def safety_poll_loop():
                """Checks +42777 every 10s so zero codes are ever missed even after brief network blips."""
                while True:
                    await asyncio.sleep(DAEMON_POLL_SECONDS)
                    try:
                        if not client.is_connected():
                            continue
                        fresh = await fetch_recent_777000_codes(client, ttl_minutes)
                        active_codes[:] = fresh
                        await sync_publish(active_codes)
                    except Exception as poll_err:
                        print(f"[warn] Safety poll error: {poll_err}", flush=True)

            poll_task = asyncio.create_task(safety_poll_loop())
            print("[daemon] Connected 24/7 — instant +42777 listener + 10s safety poll active.", flush=True)
            await client.run_until_disconnected()
        except Exception as e:
            print(f"[warn] Daemon disconnected ({e}); reconnecting in 5 seconds...", flush=True)
        finally:
            live_state.connected = False
            if poll_task:
                poll_task.cancel()
            try:
                await client.disconnect()
            except Exception:
                pass
        await asyncio.sleep(5)


def main():
    parser = argparse.ArgumentParser(description="NayaGram +42777 OTP Sync")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="Fetch recent codes once and update codes.json")
    group.add_argument("--daemon", action="store_true", help="Listen 24/7 in real time and publish via GitHub API")
    parser.add_argument("--output", default="codes.json", help="Path to local codes.json")
    args = parser.parse_args()

    api_id_raw = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    session_str = os.environ.get("TELEGRAM_SESSION", "").strip()
    ttl_minutes = int(os.environ.get("OTP_TTL_MINUTES", str(DEFAULT_TTL_MINUTES)))
    gh_token = os.environ.get("GITHUB_TOKEN", "").strip()
    gh_repo = os.environ.get("GITHUB_REPOSITORY", "NayaGramPlatform/ALAPGRAM").strip()
    gh_branch = os.environ.get("GITHUB_BRANCH", "main").strip()

    if not api_id_raw or not api_hash:
        print("[error] TELEGRAM_API_ID and TELEGRAM_API_HASH must be set.", file=sys.stderr)
        sys.exit(1)
    if not session_str:
        print("[info] TELEGRAM_SESSION is not configured yet. Run Phone Session Setup first.", flush=True)
        sys.exit(0)

    api_id = int(api_id_raw)
    if args.daemon:
        asyncio.run(run_daemon(api_id, api_hash, session_str, ttl_minutes, Path(args.output), gh_token, gh_repo, gh_branch))
    else:
        asyncio.run(run_once(api_id, api_hash, session_str, ttl_minutes, Path(args.output)))


if __name__ == "__main__":
    main()
