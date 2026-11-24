<div align="center">

<img src="./assets/ng-logo.png" alt="NayaGram Official Logo" width="108" height="108" />

# NayaGram — Verification Codes Portal

**Official live verification code viewer for the dedicated NayaGram review test account.**

[![Live Portal](https://img.shields.io/badge/Live%20Portal-Open%20Verification%20Page-0EA5E9?style=for-the-badge)](https://nayagramplatform.github.io/ALAPGRAM/)

</div>

---

## About

This portal provides automated, read-only access to official Telegram login verification codes (`+42777`) for the dedicated **NayaGram** review test account. It is designed to help authorized app reviewers sign in smoothly without requiring personal credentials.

- **Live Web Page:** [nayagramplatform.github.io/ALAPGRAM](https://nayagramplatform.github.io/ALAPGRAM/)
- **Privacy First:** The test phone number is never published in this repository or on the web page—it is stored privately in encrypted repository secrets and shared only with authorized reviewers.
- **Strict Scope:** Reads strictly official Telegram service login notifications (`+42777` / user ID `777000`). Personal chats, groups, and unrelated messages are never accessed.
- **Auto-Refresh & Auto-Expiry:** The portal refreshes automatically every **25 seconds**, displays all timestamps in **UTC**, and expires codes automatically after **30 minutes**.

---

## Mobile-Friendly Setup (No Computer Needed)

1. Ensure your encrypted repository secrets (`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and `TEST_PHONE_NUMBER`) are configured under **Settings → Secrets and variables → Actions**.
2. Open **Actions → Phone Session Setup (No Computer Needed) → Run workflow**.
3. Run **`1-send-otp`** to request a 5-digit Telegram login code on your dedicated test account.
4. Run **`2-verify-otp`** with that 5-digit code. Your private `TELEGRAM_SESSION` will be delivered strictly to **Saved Messages** on the test account (never printed in public logs).
5. Save that session string as a repository secret named **`TELEGRAM_SESSION`**.

---

<div align="center">
<sub>© 2026 NayaGram Platform · NayaGram is an unofficial Telegram client and is not affiliated with Telegram FZ-LLC.</sub>
</div>
