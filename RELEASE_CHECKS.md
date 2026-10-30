# Release verification · v0.1.0

This source release focuses on personalised prioritisation without repositories.
The maintainer's operational bot, credentials and materials are not included.

## Deterministic checks

On 2026-10-30, all **31 tests passed** on Windows/Python 3.12, including in a new
virtual environment installed from `requirements.txt` without media packages.
The text-only dependency check reported ready; no speech model was downloaded.

`python -m unittest discover -s tests -v` covers private-chat ownership, duplicate
updates and approvals, durable queues, rejected notifications, archival, safe
media cleanup, multi-video cache separation, three-question focus onboarding,
existing-profile reuse, no-repository personal actions, execution disabled by
default, immutable approval SHA and release export boundaries.

`python tools/check_release.py .` scans allowlisted sources for credential
patterns and personal absolute paths, checks neutral example defaults, and
rejects tracked private files. This is a useful automated gate, not a guarantee
that all possible sensitive information can be detected.

The prepared source tree has no inherited commit history. Its ZIP is produced
from an explicit file allowlist and excludes Git internals, runtime data, private
configuration, credentials, models and installed dependencies.

## Live and external checks

The earlier private prototype was tested with real Telegram messages, Reels
transcription and Codex worktree execution on Windows. These checks are not a
claim that every third-party media host, account or Codex version will work.
The new focus flow and immutable-base regressions have deterministic tests.
A live Codex analysis with an example watercolour-learning profile and **zero
repositories** returned `implement`, a personal next step and an empty project
field. This confirms the main path is not dependent on coding projects.

GitHub Actions configuration is included for Python 3.11/3.12 on Windows/Linux;
its remote runs only happen after the repository is published. The full desktop
experience and autostart are supported first on Windows. No actual second user's
Telegram token or Codex account is included or tested in this release.

## Known limits

- PC must remain awake, logged in and online. Telegram update retention is limited.
- No automatic reading of a user's personal Telegram Saved Messages.
- Photo understanding and OCR of scanned PDFs are not implemented.
- Private or blocked Reels may fail to download.
- Claude is not a runtime provider yet; authenticated Codex is required.
- Personal plans save suggestions only; they do not execute external actions.
- Code execution is optional and still requires human review of the result.
- Broad dependency ranges resolve at install time; bundled binaries/models need
  their own license and compatibility review.

See `SECURITY.md` and `THIRD_PARTY.md` before sharing data or bundling dependencies.
