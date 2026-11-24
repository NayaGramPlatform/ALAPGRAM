#!/usr/bin/env python3
"""
One-time helper to generate a Telethon StringSession for your dedicated NayaGram test account.
"""

import os
from telethon.sync import TelegramClient
from telethon.sessions import StringSession


def main():
    api_id = os.environ.get("TELEGRAM_API_ID") or input("Enter TELEGRAM_API_ID: ").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH") or input("Enter TELEGRAM_API_HASH: ").strip()
    phone = os.environ.get("TEST_PHONE_NUMBER") or input("Enter test phone number (with country code): ").strip()

    with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        client.start(phone=phone)
        session_string = client.session.save()
        print("\n" + "=" * 64)
        print("SUCCESS! Copy the TELEGRAM_SESSION string below and save it")
        print("in GitHub Actions Secrets as TELEGRAM_SESSION:")
        print("=" * 64)
        print(session_string)
        print("=" * 64 + "\n")


if __name__ == "__main__":
    main()
