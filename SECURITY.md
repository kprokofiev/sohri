# Security and privacy

Sohri is a single-user, local application. It accepts messages only from the
configured owner's private Telegram chat. Do not deploy it as a shared multi-user
service without a separate security review.

## Data flow

- Materials travel through Telegram. The bot downloads them to your computer.
- Extracted text and your confirmed focus are submitted to authenticated Codex
  for analysis. They are not guaranteed to remain on your computer: Codex uses
  the account's configured service. Account limits and provider terms apply.
- Speech recognition runs locally with faster-whisper. A model may be downloaded
  from its provider on first use. Private Instagram cookies are not imported.
- Original messages, transcripts, decisions, pending actions and execution logs
  live in `data/`. The vault has its own local Git history. Archive is not erasure.
- Do not send material you are not permitted to process with those services.

## Credentials

Use your own Telegram bot and your own Codex login. Keep credentials in `.env`
and Codex's own authentication storage. Never send token values in issues, chat,
screenshots, command arguments or a public repo. Setup uses a hidden local prompt.
Telegram BotFather is the only way to revoke/reissue the bot token; the bot API
cannot rotate it. If a token was exposed, revoke it and update your local `.env`.

## Optional code execution

Disabled by default. Personal plans only save a suggested next step; they do not
send messages, buy anything, change files in your projects or schedule events.
Code execution requires an explicit local allowlist and approval of a card bound
to a repo path and commit SHA. It runs in an isolated worktree with Codex's
workspace permissions. No automatic merge, push or deployment is requested.

Instructions in a material are untrusted. Sandbox settings and prompt rules are
defences, not a guarantee that arbitrary hostile code is safe. Only enable code
execution for repositories you trust, review changes, and keep credentials out of
them. Windows uses Codex's `unelevated` sandbox; do not describe it as a VM or a
strict security boundary for unknown code. Network isolation depends on the CLI
and operating system.

## Reporting

Do not publish secrets or exploit data in a public issue. Use a repository's
private vulnerability reporting feature if enabled; otherwise contact the
maintainer privately. Only share a minimal sanitised reproducer.

## Retention and backups

To back up your private data, stop the bot, then copy `data/` and local settings to
a protected location. To erase a material fully, its SQLite records, original
files, logs, Git history and backups must all be considered; the archive command
does not do this. The source ZIP produced by the release tool includes none of
these private files.
