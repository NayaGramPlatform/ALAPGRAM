# NayaGram Verification Codes Portal

Public verification code viewer for the dedicated NayaGram test account (`+8801320917532`).

- **Live Page:** `https://nayagramplatform.github.io/ALAPGRAM/`
- **Scope:** Strictly reads official Telegram login codes (`+42777` / user ID `777000`) for the dedicated test account only. No personal chats are accessed or exposed.
- **Auto-Expiry:** Codes expire automatically after 30 minutes.

## Phone-Only Setup (No Computer Required)

1. Open **Actions → Phone Session Setup (No Computer Needed) → Run workflow**.
2. Choose **`1-send-otp`** and tap **Run workflow**. Telegram will send a 5-digit OTP to `+8801320917532`.
3. Open **Run workflow** again, choose **`2-verify-otp`**, enter the 5-digit `otp_code`, and tap **Run workflow**.
4. Open **Saved Messages** in Telegram on `+8801320917532`, copy your private `TELEGRAM_SESSION`, and save it under **Settings → Secrets and variables → Actions → New repository secret** as `TELEGRAM_SESSION`.
   *(If your test account has 2FA enabled, add `TELEGRAM_2FA_PASSWORD` to Secrets before Step 2.)*
