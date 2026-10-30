"""Bounded fetch and local media transcription; delete only successfully processed temporary files."""
import ipaddress
import json
import socket
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from agent import run_process

MAX_BYTES = 20 * 1024 * 1024
MEDIA_HOSTS = {'instagram.com', 'www.instagram.com', 'youtube.com', 'www.youtube.com',
               'youtu.be', 'm.youtube.com', 'tiktok.com', 'www.tiktok.com', 'vm.tiktok.com'}


def public_url(url):
    p = urlsplit(url)
    if p.scheme not in {'http', 'https'} or not p.hostname or p.username or p.password:
        raise ValueError('Допустимы только публичные http/https ссылки')
    if p.port not in {None, 80, 443}:
        raise ValueError('Нестандартный порт запрещён')
    addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Локальные и служебные адреса запрещены')
    return url


def fetch_page(url):
    # Recheck every redirect; refuse implicit credentials/cookies/proxies.
    session = requests.Session()
    session.trust_env = False
    for _ in range(5):
        public_url(url)
        with session.get(url, timeout=(10, 25), stream=True, allow_redirects=False,
                         headers={'User-Agent': 'SohriPersonalArchive/1.0'}) as r:
            if 300 <= r.status_code < 400:
                url = urljoin(url, r.headers.get('Location', ''))
                continue
            r.raise_for_status()
            if int(r.headers.get('Content-Length', 0)) > MAX_BYTES:
                raise ValueError('Страница превышает 20 МБ')
            chunks, size = [], 0
            for chunk in r.iter_content(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError('Страница превышает 20 МБ')
                chunks.append(chunk)
            body = b''.join(chunks)
            mime = r.headers.get('Content-Type', '').lower()
            if 'html' not in mime and 'text/' not in mime and 'json' not in mime:
                raise ValueError('Ссылка ведёт на файл; отправь файл боту напрямую')
            soup = BeautifulSoup(body, 'html.parser')
            for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'noscript']):
                tag.decompose()
            return f'Источник: {url}\n\n' + soup.get_text('\n', strip=True)[:50000]
    raise ValueError('Слишком много перенаправлений')


def transcribe(path, config):
    """Separate process gives download/model hangs a hard upper bound."""
    import importlib.util
    if importlib.util.find_spec('faster_whisper') is None:
        raise ValueError('Модуль распознавания речи не установлен. Попроси Codex включить обработку видео и голоса; оригинал сохранён.')
    out = run_process([sys.executable, str(Path(__file__).resolve()), '--transcribe',
                       str(path), config.get('whisper_model', 'small'),
                       str(config.get('max_media_seconds', 900))], timeout=1500)
    result = json.loads(out)
    if not result['text'].strip():
        raise ValueError('Речь не распознана; видео сохранено для проверки')
    return f"Язык: {result['language']}\n\n{result['text']}"


def video_url(url, folder, config):
    p = urlsplit(public_url(url))
    if p.hostname not in MEDIA_HOSTS:
        raise ValueError('Этот видеохостинг пока не поддерживается')
    folder.mkdir(parents=True, exist_ok=True)
    cached = folder / 'transcript.txt'
    if cached.exists():
        return cached.read_text(encoding='utf-8')
    import importlib.util
    if importlib.util.find_spec('yt_dlp') is None or importlib.util.find_spec('faster_whisper') is None:
        raise ValueError('Обработка видео ещё не включена. Попроси Codex установить дополнительный модуль медиа.')
    template = str(folder / 'source.%(ext)s')
    # --ignore-config prevents loading user cookies, plugins or execution hooks from yt-dlp config.
    args = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-playlist',
            '--no-progress', '--no-warnings', '--socket-timeout', '25', '--retries', '2',
            '--max-filesize', '100M', '--match-filter', f'duration <=? {config.get("max_media_seconds", 900)}',
            '-f', 'best[height<=720]/best', '-o', template, '--', url]
    run_process(args, timeout=420)
    files = [p for p in folder.glob('source.*') if p.suffix not in {'.part', '.ytdl', '.json'}]
    if not files:
        raise ValueError('Видео недоступно, слишком длинное или требует авторизации Instagram')
    transcript = transcribe(files[0], config)
    # Persist transcript BEFORE ordinary unlink; no recursive removal, force flags or shell deletion.
    (folder / 'transcript.txt').write_text(f'Источник: {url}\n\n{transcript}', encoding='utf-8')
    for f in files:
        f.unlink()
    return f'Источник: {url}\n\n{transcript}'


def attachment_text(path, mime, config):
    suffix = path.suffix.lower()
    if mime.startswith(('audio/', 'video/')) or suffix in {'.mp4', '.mov', '.webm', '.mp3', '.ogg', '.m4a', '.wav'}:
        text = transcribe(path, config)
        path.with_suffix(path.suffix + '.transcript.txt').write_text(text, encoding='utf-8')
        path.unlink()
        return text
    if suffix == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(path)
        text = '\n'.join((p.extract_text() or '') for p in reader.pages[:100])[:60000]
        if not text.strip():
            raise ValueError('PDF содержит сканы без текста. OCR пока не подключён; оригинал сохранён.')
        return text
    if suffix == '.docx':
        from docx import Document
        doc = Document(path)
        return '\n'.join(p.text for p in doc.paragraphs)[:60000]
    if mime.startswith('text/') or suffix in {'.md', '.txt', '.json', '.csv', '.log', '.py', '.js', '.html'}:
        return path.read_text(encoding='utf-8', errors='replace')[:60000]
    raise ValueError('Файл сохранён. Для этого формата извлечение текста пока не поддерживается.')


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--transcribe':
        from faster_whisper import WhisperModel
        model = WhisperModel(sys.argv[3], device='cpu', compute_type='int8', cpu_threads=4)
        segments, info = model.transcribe(sys.argv[2], beam_size=3, vad_filter=True)
        if info.duration > int(sys.argv[4]):
            raise ValueError('Медиа длиннее допустимого лимита')
        text = ' '.join(s.text.strip() for s in segments)
        print(json.dumps({'text': text, 'language': info.language}, ensure_ascii=False))
