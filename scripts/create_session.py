#!/usr/bin/env python3
"""
One-time helper to generate a Telethon StringSession for the dedicated NayaGram test account (+8801320917532).
Run this ONCE on your phone (Termux) or computer, then paste the printed string into:
  GitHub Repo -> Settings -> Secrets and variables -> Actions -> New repository secret -> TELEGRAM_SESSION
"""

import os
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

DEFAULT_PHONE = "+8801320917532"


def main():
    api_id = os.environ.get("TELEGRAM_API_ID") or input("Enter TELEGRAM_API_ID: ").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH") or input("Enter TELEGRAM_API_HASH: ").strip()
    phone = input(f"Enter test phone number [{DEFAULT_PHONE}]: ").strip() or DEFAULT_PHONE

    with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        client.start(phone=phone)
        session_string = client.session.save()
        print("\n" + "=" * 64)
        print("SUCCESS! Copy the entire TELEGRAM_SESSION string below and add it")
        print("to GitHub Actions Secrets as TELEGRAM_SESSION (keep it private!):")
        print("=" * 64)
        print(session_string)
        print("=" * 64 + "\n")


if __name__ == "__main__":
    main()
