# Сохранёнки: instructions for a setup assistant

## First-time setup is a short focus check, not a coding project

When a person opens this project in Codex to set it up, help them run their own
personal saved-materials assistant. Do not start by asking for repositories.
If the local configuration and profile are already complete, do not repeat onboarding.
For unrelated code maintenance/review requests, do that requested work without onboarding.

1. Use personal context and memory already available to you in the current Codex
   session. Do not ask the person's name, profession or biography again. Do not
   scan `.codex` databases, other chats, credentials or another person's profile.
   If no relevant memory is available, say so briefly and ask about current focus.
2. Offer a brief proposed focus based on what you already know, then ask only what
   is missing or may have changed. Bundle at most three short questions: current
   desired outcomes; useful/unwanted material; attention/time/other constraints.
   Let the person confirm or correct the proposal. Do not infer consent from silence.
3. Store only their confirmed priorities in `config.local.json` -> `profile`, using
   `goals`, `interests`, `constraints`, `language`, `completed: true`. No identity
   questionnaire is needed. Keep `execution_enabled: false` and `projects: {}` by
   default. The main feature is ranking saved materials for this person's life.
4. Check Python 3.11+, Git and Codex login. Install `requirements.txt` in a local
   `.venv`, not the system Python. Video/PDF/DOCX dependencies are optional in
   `requirements-media.txt`; ask whether video transcription is useful before
   downloading a speech model. FFmpeg is an external prerequisite for media.
5. Help create a NEW bot through @BotFather. Never reuse an author's bot or token.
   Do not request credentials in chat or put them into command arguments. Ask the
   person to paste the token locally into `.env` or the hidden prompt of
   `python setup.py`. That wizard also pairs the owner's private Telegram chat:
   they press /start in their own bot and confirm the account locally.
6. Preserve existing local settings. `python setup.py --profile-json '<JSON>'`
   updates only confirmed focus when explicitly requested. The interactive setup
   can reuse a completed profile; don't make the person answer the same questions twice.
7. Run unit tests and `python bot.py --check`, then start the bot. It asks its own
   three-question focus check only if no completed profile was supplied. Explain
   `/profile`, `/onboard`, `/plan`, and that the PC must remain awake and online.
   Windows autostart is optional: install it only when the person wants it.
8. Code execution is an optional separate feature: configure an explicit local Git
   repo and enable execution only at the person's request. Explain approval and
   isolated worktrees. Never enable it because the person happens to use Codex.

## Maintenance

Do not read, export, publish or commit `.env`, `config.local.json`, `data/` or
private chat histories. Do not delete Git index.lock files. Preserve work by other
agents. Use `python -m unittest discover -s tests -v` for deterministic checks.
`tests/smoke_live.py` calls authenticated Codex and consumes account usage; run it
only as an explicitly intended live verification in a disposable fixture.
Release exports must use the allowlist in `tools/build_release.py`, not a recursive
copy of the working folder. The clean release has a fresh Git history and no data.
