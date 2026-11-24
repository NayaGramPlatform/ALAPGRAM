#!/usr/bin/env python3
"""
Phone-Friendly NayaGram Test Account Session Setup (No Computer Required)
Runs securely inside GitHub Actions:
  Step 1 (send):   Sends Telegram OTP to +8801320917532 and saves AES-encrypted pending_login.enc
  Step 2 (verify): Downloads & decrypts pending_login.enc, verifies OTP, and sends the private
                   TELEGRAM_SESSION strictly to the test account's own Telegram Saved Messages ("me").
                   NEVER prints TELEGRAM_SESSION to public logs!
"""

import argparse
import asyncio
import base64
import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from cryptography.fernet import Fernet
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

DEFAULT_PHONE = "+8801320917532"
ARTIFACT_NAME = "pending-otp-state"
STATE_FILE = Path("pending_login.enc")


def make_cipher(api_hash: str) -> Fernet:
    digest = hashlib.sha256(f"nayagram-otp-state::{api_hash}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def download_latest_artifact(repo: str, token: str) -> bytes:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "nayagram-phone-setup",
    }
    list_url = f"https://api.github.com/repos/{repo}/actions/artifacts?name={ARTIFACT_NAME}&per_page=5"
    req = urllib.request.Request(list_url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    artifacts = [a for a in data.get("artifacts", []) if not a.get("expired")]
    if not artifacts:
        raise RuntimeError(
            "No pending OTP state found. Please run Step 1 (1-send-otp) first, then run Step 2 within 5 minutes."
        )

    latest = artifacts[0]
    artifact_id = latest["id"]
    dl_url = latest["archive_download_url"]

    dl_req = urllib.request.Request(dl_url, headers=headers)
    with urllib.request.urlopen(dl_req, timeout=30) as resp:
        zip_bytes = resp.read()

    # Best-effort delete temporary artifact after download
    try:
        del_req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}",
            headers=headers,
            method="DELETE",
        )
        urllib.request.urlopen(del_req, timeout=15).read()
    except Exception:
        pass

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if name.endswith("pending_login.enc"):
                return zf.read(name)

    raise RuntimeError("Artifact did not contain pending_login.enc.")


async def step_send(api_id: int, api_hash: str, phone: str):
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        payload = json.dumps({
            "phone": phone,
            "phone_code_hash": sent.phone_code_hash,
            "session": client.session.save(),
        }).encode("utf-8")
        encrypted = make_cipher(api_hash).encrypt(payload)
        STATE_FILE.write_bytes(encrypted)
        print(f"[ok] Telegram OTP request sent to {phone}.", flush=True)
        print("[next] Check your Telegram/SMS for the 5-digit code, then run Step 2 (2-verify-otp).", flush=True)
    finally:
        await client.disconnect()


async def step_verify(api_id: int, api_hash: str, otp_code: str, two_fa: str, repo: str, gh_token: str):
    clean_code = "".join(ch for ch in (otp_code or "") if ch.isdigit())
    if not clean_code or len(clean_code) < 4:
        print("[error] Please enter the 5-digit Telegram OTP code in the otp_code field.", file=sys.stderr)
        sys.exit(1)

    encrypted = download_latest_artifact(repo, gh_token)
    try:
        raw = make_cipher(api_hash).decrypt(encrypted)
        pending = json.loads(raw.decode("utf-8"))
    except Exception:
        print("[error] Failed to decrypt pending login state. Re-run Step 1 (1-send-otp).", file=sys.stderr)
        sys.exit(1)

    phone = pending["phone"]
    phone_code_hash = pending["phone_code_hash"]
    partial_session = pending["session"]

    client = TelegramClient(StringSession(partial_session), api_id, api_hash)
    await client.connect()
    try:
        try:
            await client.sign_in(phone=phone, code=clean_code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            if not two_fa:
                print(
                    "[error] This test account has 2-Step Verification (2FA) enabled. "
                    "Add your test account 2FA password as secret TELEGRAM_2FA_PASSWORD and re-run Step 2.",
                    file=sys.stderr,
                )
                sys.exit(1)
            await client.sign_in(password=two_fa)

        final_session = client.session.save()
        # Mask immediately so GitHub Actions can never accidentally reveal it
        print(f"::add-mask::{final_session}", flush=True)

        # Deliver privately to the test account's own Telegram Saved Messages ("me")
        msg_text = (
            "NayaGram Verification Portal — TELEGRAM_SESSION\n\n"
            "Copy the entire code below and paste it into GitHub:\n"
            "ALAPGRAM -> Settings -> Secrets and variables -> Actions -> New repository secret\n"
            "Name: TELEGRAM_SESSION\n\n"
            f"`{final_session}`"
        )
        await client.send_message("me", msg_text, parse_mode="markdown")
        print("[success] Sign-in complete! Your private TELEGRAM_SESSION has been sent to Saved Messages on your test Telegram account.", flush=True)
        print("[next] Open Telegram Saved Messages on +8801320917532, tap to copy the session string, and save it as GitHub Secret TELEGRAM_SESSION.", flush=True)
    finally:
        await client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Phone-friendly Telegram Session Setup")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("send")
    v = sub.add_parser("verify")
    v.add_argument("--code", required=True)
    args = parser.parse_args()

    api_id_raw = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    phone = os.environ.get("TEST_PHONE_NUMBER", DEFAULT_PHONE).strip() or DEFAULT_PHONE
    two_fa = os.environ.get("TELEGRAM_2FA_PASSWORD", "").strip()
    gh_token = os.environ.get("GITHUB_TOKEN", "").strip()
    gh_repo = os.environ.get("GITHUB_REPOSITORY", "NayaGramPlatform/ALAPGRAM").strip()

    if not api_id_raw or not api_hash:
        print("[error] TELEGRAM_API_ID and TELEGRAM_API_HASH secrets must be configured.", file=sys.stderr)
        sys.exit(1)

    api_id = int(api_id_raw)
    if args.cmd == "send":
        asyncio.run(step_send(api_id, api_hash, phone))
    else:
        asyncio.run(step_verify(api_id, api_hash, args.code, two_fa, gh_repo, gh_token))


if __name__ == "__main__":
    main()
