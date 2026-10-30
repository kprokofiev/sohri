# Contributing

Open a focused issue or pull request. Include the concrete problem, expected
behaviour, a sanitised reproducer and relevant tests. Do not include private
materials, transcripts, account IDs, tokens or your local config.

Use Python 3.11+ and a virtual environment:

```sh
python -m venv .venv
# Activate the environment for your shell, then:
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Deterministic tests must not require real Telegram/Codex credentials, network
access or downloaded speech models. Run `tests/smoke_live.py` only deliberately:
it invokes authenticated Codex and consumes usage. It modifies a disposable test
repo and must not operate on a real user's projects.

Keep the default experience useful without code repositories. Do not enable code
execution by default, expand permissions silently, auto-run material instructions,
or replace focus-based prioritisation with a stream of mandatory tasks.
