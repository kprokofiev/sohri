# Third-party components

The MIT license in `LICENSE` applies to Sohri's original source code. Dependencies,
speech model weights and external executables retain their own licenses and terms.
This source release bundles none of their binaries, models or source trees.

Direct dependencies (license metadata checked in the maintainer's environment on
2026-10-30; check the actual versions you install):

| Package | Role | Reported license |
| --- | --- | --- |
| requests | Telegram and web requests | Apache-2.0 |
| beautifulsoup4 | Text extraction | MIT |
| yt-dlp | Optional video download | Unlicense for project code; distributions may include other components |
| faster-whisper | Optional local transcription | MIT |
| pypdf | Optional PDF text extraction | BSD-3-Clause |
| python-docx | Optional DOCX extraction | MIT |

Important transitive components include CTranslate2 (MIT), PyAV (BSD-3-Clause),
tokenizers (Apache-2.0), and ONNX Runtime (MIT). PyAV/FFmpeg builds can include
components with different licensing requirements; this is not a certification of
all binary distributions or their compatibility with every redistribution plan.

FFmpeg, Git and Codex are installed independently and are not relicensed here.
FFmpeg's license depends on its build options. Whisper model weights and any
downloaded VAD assets are separate artifacts: check the relevant model cards and
licenses before redistributing them. Telegram, Instagram, Codex and model hosting
services also have their own usage terms.

If distributing a bundled executable, Docker image, model bundle or installer
that contains dependencies, perform a separate review of that exact artifact and
include required notices. The prepared release is source-only.
