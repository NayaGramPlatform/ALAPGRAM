# NayaGram Verification Codes Portal

Public verification code viewer for the dedicated NayaGram test account (`+8801320917532`).

- **Live Page:** `https://nayagramplatform.github.io/ALAPGRAM/`
- **Scope:** Strictly reads official Telegram login codes (`+42777` / user ID `777000`) for the dedicated test account only. No personal chats are accessed or exposed.
- **Auto-Expiry:** Codes expire automatically after 30 minutes.

## Quick Setup (1-Time)

1. Generate a Telethon `TELEGRAM_SESSION` for `+8801320917532`:
   ```bash
   pip install telethon
   python3 scripts/create_session.py
   ```
2. Add `TELEGRAM_SESSION` to **Settings → Secrets and variables → Actions** (alongside your existing `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`).
3. **Optional (Recommended for <1-second instant OTP delivery):** Deploy the included `Dockerfile` on a free always-on host (such as Koyeb or Render) with `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION`, `GITHUB_TOKEN`, and `GITHUB_REPOSITORY=NayaGramPlatform/ALAPGRAM`. Otherwise, GitHub Actions (`Sync Verification Codes`) runs automatically every 5 minutes and can also be triggered manually.
