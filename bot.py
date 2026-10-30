import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
from urllib.parse import urlsplit

import requests

import agent
import media
from storage import Store
import onboarding

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
LOG = logging.getLogger('sohri')
HELP = '''Сохранёнки — личный фильтр полезных материалов.

Пришли текст, ссылку, пересланный пост, PDF/DOCX, голосовое, видео или ссылку на Reels.
Я сохраню материал и оценю его пользу для твоих текущих целей.
«В мой план» — сохранить предложенный шаг, чтобы выполнить самостоятельно.
«В архив» — сохранить без выполнения.
Работа с кодом — дополнительный, явно включаемый режим с отдельным одобрением.

/status — состояние и последние материалы
/projects — подключённые проекты
/plan — мой план действий
/done 12 — отметить личный шаг выполненным
/profile — текущие приоритеты
/onboard — уточнить или изменить фокус
/archive — последние записи архива
/item 12 — открыть материал и решение
/retry 12 — повторить неудавшийся анализ
/help — эта справка

Видео: до 15 минут; файлы Telegram: до 20 МБ. MP4 удаляется обычным удалением после сохранения транскрипта.
Работаю на твоём ПК: он должен быть включён и подключён к интернету.'''


def load_settings():
    env = ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())
    config = json.loads((ROOT / 'config.local.json').read_text(encoding='utf-8-sig'))
    config.setdefault('projects', {})
    config.setdefault('execution_enabled', False)
    if not isinstance(config.get('owner_id'), int) or isinstance(config['owner_id'], bool) or config['owner_id'] <= 0:
        raise ValueError('Сначала настройте своего владельца: python setup.py')
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if not token or not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', token):
        raise ValueError('Укажите TELEGRAM_BOT_TOKEN в .env')
    if config.get('provider', 'codex') != 'codex':
        raise ValueError('В этом MVP подключён провайдер codex')
    return token, config


class TelegramError(RuntimeError):
    def __init__(self, text, code=None):
        super().__init__(text)
        self.code = code


class Telegram:
    def __init__(self, token):
        self._base = 'https://api.telegram.org/bot' + token + '/'
        self._file = 'https://api.telegram.org/file/bot' + token + '/'
        self.session = requests.Session()

    def call(self, method, **payload):
        try:
            r = self.session.post(self._base + method, json=payload, timeout=(10, 45))
            data = r.json()
        except (requests.RequestException, ValueError):
            raise TelegramError('Telegram: ошибка соединения') from None
        if not data.get('ok'):
            raise TelegramError('Telegram: ' + str(data.get('description', 'ошибка API')), data.get('error_code'))
        return data['result']

    def download(self, file_id, target):
        f = self.call('getFile', file_id=file_id)
        if f.get('file_size', 0) > media.MAX_BYTES:
            raise ValueError('Файл больше 20 МБ')
        try:
            with self.session.get(self._file + f['file_path'], timeout=(10, 90), stream=True) as r:
                r.raise_for_status()
                size = 0
                with target.open('wb') as out:
                    for chunk in r.iter_content(65536):
                        size += len(chunk)
                        if size > media.MAX_BYTES:
                            raise ValueError('Файл больше 20 МБ')
                        out.write(chunk)
        except requests.RequestException:
            raise RuntimeError('Telegram: не удалось скачать файл') from None


def authorized(update, owner):
    msg = update.get('message')
    if msg:
        return msg.get('from', {}).get('id') == owner and msg.get('chat', {}).get('id') == owner and msg.get('chat', {}).get('type') == 'private'
    cb = update.get('callback_query')
    if cb:
        chat = cb.get('message', {}).get('chat', {})
        return cb.get('from', {}).get('id') == owner and chat.get('id') == owner and chat.get('type') == 'private'
    return False


def review_text(item, base=None):
    plan = json.loads(item['analysis'])
    verdicts = {'implement': 'Стоит применить сейчас', 'archive': 'В архив: сейчас не нужно', 'watch': 'Сохранить на потом'}
    text = f"#{item['id']} · {plan['title']}\n\n{plan['summary']}\n\nПольза сейчас: {plan['score']}/100\n{verdicts[plan['verdict']]}\n{plan['reason']}"
    if plan['task']:
        if plan['project']:
            text += f"\n\nПроект: {plan['project']}"
        text += f"\n\nСледующий шаг: {plan['task']}"
        text += '\nПроверка:\n' + '\n'.join('• ' + a for a in plan['acceptance'])
        binding = plan.get('execution', {})
        if binding:
            text += f'\nВетка-основа: {binding["base"]} @ {binding["sha"][:12]}'
    if item['status'] == 'archived':
        text += '\n\nВ архиве, без действий. Открыть: /item ' + str(item['id'])
    buttons = []
    if plan['project'] and plan['task'] and plan.get('execution'):
        buttons.append({'text': '✅ Реализовать', 'callback_data': f'execute:{item["id"]}'})
    elif plan['task'] and not plan['project']:
        buttons.append({'text': 'В мой план', 'callback_data': f'plan:{item["id"]}'})
    buttons.append({'text': '📦 В архив', 'callback_data': f'archive:{item["id"]}'})
    keyboard = {'inline_keyboard': [buttons]} if item['status'] == 'review' else None
    return text, keyboard


class Bot:
    def __init__(self, token, config, data=DATA):
        self.config, self.data = config, Path(data)
        self.owner = int(config['owner_id'])
        self.store = Store(self.data / 'state.sqlite3')
        self.tg = Telegram(token)
        self.stop = threading.Event()
        self.active = None
        self.vault = self.data / 'vault'
        self.vault.mkdir(parents=True, exist_ok=True)
        if not (self.vault / '.git').exists():
            agent.run_process(['git', 'init', str(self.vault)])
        self.vault_lock = threading.Lock()
        self.vault_pending = set(self.store.meta('vault_pending', []))
        self.vault_retry_at = 0

    def notify(self, text, keyboard=None):
        # Telegram limits text to 4096 characters. Attach the decision to the final chunk.
        text = self.redact(text)
        # Telegram rejects whitespace-only text, so such chunks are dropped.
        chunks = [c for c in (text[i:i + 3700] for i in range(0, len(text), 3700)) if c.strip()] or ['Готово']
        for i, chunk in enumerate(chunks):
            self.store.notify(chunk, keyboard if i == len(chunks) - 1 else None)

    def redact(self, text):
        text = re.sub(r'\b\d{8,12}:[A-Za-z0-9_-]{25,}\b', '[BOT_TOKEN]', str(text))
        return re.sub(r'\bsk-[A-Za-z0-9_-]{15,}', '[API_KEY]', text)

    def export(self, iid):
        # The instance lock excludes other bot instances, but NOT a human's Git process.
        # Never delete index.lock, even if it looks old. SQLite remains the source of truth.
        with self.vault_lock:
            try:
                self._export(iid)
                self.vault_pending.discard(iid)
            except (RuntimeError, OSError) as exc:
                self.vault_pending.add(iid)
                LOG.warning('Vault export for #%s deferred: %s', iid, self.redact(exc))
            self.store.put_meta('vault_pending', sorted(self.vault_pending))

    def _export(self, iid):
        item = self.store.get(iid)
        plan = json.loads(item['analysis']) if item['analysis'] else {}
        folder = self.vault / f'{iid:06d}'
        folder.mkdir(parents=True, exist_ok=True)
        raw = json.loads(item['raw'])
        meta = {'id': iid, 'created': item['created'], 'status': item['status'],
                'telegram_message_id': raw.get('message_id'), 'forward_origin': raw.get('forward_origin'),
                'analysis': plan, 'worktree': item['worktree'], 'error': item['error'], 'result': item['result']}
        (folder / 'metadata.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        content = item['content'] or raw.get('text') or raw.get('caption') or '[вложение]'
        (folder / 'material.md').write_text(f"# {plan.get('title', 'Материал ' + str(iid))}\n\n{content}\n", encoding='utf-8')
        if plan:
            text, _ = review_text(item)
            (folder / 'decision.md').write_text(text, encoding='utf-8')
        if (self.vault / '.git' / 'index.lock').exists():
            raise RuntimeError('Git archive is locked; retry later without removing the lock')
        agent.run_process(['git', '-C', str(self.vault), 'add', '--', str(folder.relative_to(self.vault))])
        changed = agent.run_process(['git', '-C', str(self.vault), 'diff', '--cached', '--name-only'])
        if changed.strip():
            agent.run_process(['git', '-C', str(self.vault), '-c', 'user.name=Sohri Archive', '-c',
                               'user.email=sohri@localhost', 'commit', '-m', f'Material {iid}: {item["status"]}'])

    def base_label(self, plan):
        return plan.get('execution', {}).get('base')

    def profile(self):
        return self.store.meta('profile', self.config.get('profile', {}))

    def begin_onboarding(self):
        self.store.put_meta('onboarding', {'step': 0, 'answers': {}})
        self.notify('Уточним только актуальный фокус. Имя и биографию спрашивать не буду. '
                    'Если при настройке через Codex уже подтвердили приоритеты, они сохраняются в профиле.\n\n' + onboarding.QUESTIONS[0][1])

    def onboarding_answer(self, text):
        state = self.store.meta('onboarding')
        if not state:
            return False
        key, _ = onboarding.QUESTIONS[state['step']]
        state['answers'][key] = text[:3000]
        state['step'] += 1
        if state['step'] == len(onboarding.QUESTIONS):
            profile = onboarding.make_profile(state['answers'])
            self.store.put_meta('profile', profile)
            self.store.put_meta('onboarding', None)
            self.notify('Фокус сохранён. Теперь оцениваю находки по этим приоритетам:\n\n' + onboarding.summary(profile) + '\n\nМожешь присылать материалы. /profile — посмотреть, /onboard — изменить.')
        else:
            self.store.put_meta('onboarding', state)
            self.notify(onboarding.QUESTIONS[state['step']][1])
        return True

    def handle(self, update):
        if not authorized(update, self.owner):
            return
        if 'callback_query' in update:
            cb = update['callback_query']
            match = re.fullmatch(r'(execute|archive|plan):(\d+)', cb.get('data', ''))
            if match and match[1] == 'execute' and not self.config.get('execution_enabled', False):
                self.notify('Выполнение кода выключено. Его можно отдельно включить в локальной конфигурации.')
                return
            success = bool(match and self.store.decide(int(match[2]), match[1]))
            try:
                self.tg.call('answerCallbackQuery', callback_query_id=cb['id'],
                             text='Принято' if success else 'Решение уже принято или материал не готов')
            except RuntimeError:
                # Telegram expires callback acknowledgements; a stale acknowledgement must
                # not block the durable update queue or undo an already committed decision.
                LOG.info('Callback acknowledgement expired or unavailable')
            if success:
                iid = int(match[2])
                self.export(iid)
                self.notify(f'#{iid}: ' + {'execute': 'одобрено; задача в очереди выполнения.',
                                          'plan': 'добавлено в твой план. Внешние действия не выполнялись.',
                                          'archive': 'сохранено в архив без действий.'}[match[1]])
                try:
                    self.tg.call('editMessageReplyMarkup', chat_id=self.owner,
                                 message_id=cb['message']['message_id'], reply_markup={'inline_keyboard': []})
                except RuntimeError:
                    pass
            return
        message = update['message']
        text = message.get('text', '')
        if text.startswith('/'):
            self.command(text)
            return
        if text.strip() and 'http://' not in text and 'https://' not in text and not message.get('forward_origin'):
            if self.onboarding_answer(text.strip()):
                return
        iid = self.store.new_item(update['update_id'], message)
        if iid:
            self.export(iid)
            self.notify(f'#{iid}: сохранил. Разбираю материал; результат пришлю сюда.')
            if not onboarding.ready(self.profile()) and not self.store.meta('onboarding'):
                self.begin_onboarding()

    def command(self, text):
        args = text.split()
        cmd = args[0].split('@')[0]
        if cmd == '/onboard':
            self.begin_onboarding()
        elif cmd == '/profile':
            self.notify(onboarding.summary(self.profile()) + '\n\n/onboard — изменить фокус')
        elif cmd == '/cancel':
            self.store.put_meta('onboarding', None)
            self.notify('Уточнение отменено. Предыдущие приоритеты сохранены. /onboard — начать снова.')
        elif cmd == '/start' and not onboarding.ready(self.profile()):
            self.begin_onboarding()
        elif cmd in {'/start', '/help'}:
            self.notify(HELP)
        elif cmd == '/projects':
            self.notify('Работа с кодом: ' + ('включена' if self.config.get('execution_enabled', False) else 'выключена') + '\n\n' + ('\n\n'.join(f'{s}: {p["description"]}\n{p["path"]}' for s, p in self.config.get('projects', {}).items()) or 'Проектов нет — для приоритизации они не нужны.'))
        elif cmd == '/done' and len(args) == 2 and args[1].isdigit():
            iid = int(args[1])
            if self.store.complete_personal(iid):
                self.export(iid)
                self.notify(f'#{iid}: личный шаг отмечен выполненным.')
            else:
                self.notify('Этот материал не находится в личном плане.')
        elif cmd in {'/status', '/archive', '/plan'}:
            rows = self.store.recent(100 if cmd == '/archive' else 12)
            if cmd in {'/archive', '/plan'}:
                rows = self.store.listed('archived' if cmd == '/archive' else 'planned')
            lines = []
            for r in rows:
                title = json.loads(r['analysis'])['task' if cmd == '/plan' else 'title'] if r['analysis'] else (json.loads(r['raw']).get('text') or 'Вложение')[:65]
                lines.append(f'#{r["id"]} [{r["status"]}] {title}')
            heading = 'Мой план. Это предложения, а не обязательства.\n/done НОМЕР — отметить выполненным.' if cmd == '/plan' else f'Сохранёнки онлайн. Агент: Codex.\nСейчас: {self.active or "свободен"}'
            self.notify(heading + '\n\n' + ('\n'.join(lines) or 'Пока пусто.') + '\n\nОткрыть: /item НОМЕР')
        elif cmd in {'/item', '/retry'} and len(args) == 2 and args[1].isdigit():
            iid = int(args[1])
            item = self.store.get(iid)
            if not item:
                self.notify('Материал не найден')
            elif cmd == '/retry':
                self.notify('Анализ снова в очереди' if self.store.retry(iid) else 'Повтор доступен только для ошибки анализа')
            else:
                if item['analysis']:
                    plan = json.loads(item['analysis'])
                    if (item['status'] == 'review' and plan.get('project') and plan.get('task')
                            and not plan.get('execution') and self.config.get('execution_enabled', False)):
                        plan = agent.prepare_execution(plan, self.config)
                        self.store.set(iid, analysis=json.dumps(plan, ensure_ascii=False))
                        item = self.store.get(iid)
                    self.notify(*review_text(item, self.base_label(json.loads(item['analysis']))))
                else:
                    self.notify(f'#{iid}: {item["status"]}\n{item["error"] or (item["content"] or "Материал в очереди")[:2500]}')
                if item['result']:
                    self.notify(item['result'][:10000])
        else:
            self.notify('Не понял команду. /help — справка')

    def extract(self, iid, message):
        folder = self.data / 'files' / str(iid)
        folder.mkdir(parents=True, exist_ok=True)
        text = message.get('text') or message.get('caption') or ''
        parts = [text] if text else []
        attachment = None
        for kind in ['document', 'video', 'audio', 'voice', 'video_note']:
            if kind in message:
                attachment = message[kind]
                default_ext = {'voice': '.ogg', 'video': '.mp4', 'audio': '.mp3', 'video_note': '.mp4'}.get(kind, '.bin')
                # Never trust a filename as a path (including Windows separators).
                ext = Path(attachment.get('file_name', '')).suffix.lower()
                ext = ext if re.fullmatch(r'\.[a-z0-9]{1,8}', ext) else default_ext
                if attachment.get('file_size', 0) > media.MAX_BYTES:
                    raise ValueError('Telegram-файл больше 20 МБ')
                path = folder / ('attachment' + ext)
                self.tg.download(attachment['file_id'], path)
                parts.append(media.attachment_text(path, attachment.get('mime_type', kind + '/unknown'), self.config))
                break
        if 'photo' in message:
            photo = message['photo'][-1]
            path = folder / 'photo.jpg'
            self.tg.download(photo['file_id'], path)
            parts.append('[Фото сохранено. Для анализа изображения пришли также текст или подпись.]')
        urls = re.findall(r'https?://[^\s<>]+', text)
        for entity in message.get('entities', []) + message.get('caption_entities', []):
            if entity.get('type') == 'text_link' and entity.get('url'):
                urls.append(entity['url'])
        urls = list(dict.fromkeys(urls))
        for n, url in enumerate(urls[:3]):
            url = url.rstrip(').,;!?')
            host = urlsplit(url).hostname
            if host in media.MEDIA_HOSTS:
                self.notify(f'#{iid}: скачиваю видео и распознаю речь. Это может занять несколько минут.')
                # Each link needs its own folder: the transcript cache is per folder.
                parts.append(media.video_url(url, folder / ('video' if n == 0 else f'video-{n + 1}'), self.config))
            else:
                try:
                    parts.append(media.fetch_page(url))
                except Exception as exc:
                    # A failed source is visible to both the user and the analyst; no invented summary.
                    parts.append(f'СОДЕРЖИМОЕ ССЫЛКИ НЕ ПОЛУЧЕНО: {url}. Причина: {type(exc).__name__}. Нельзя судить о содержимом по URL.')
                    self.notify(f'#{iid}: содержимое ссылки получить не удалось. Сохраню ссылку; анализ учитывает только доступный текст.')
        if not parts:
            raise ValueError('Не найден текст или поддерживаемое вложение')
        return '\n\n'.join(parts)[:80000]

    def worker(self):
        while not self.stop.is_set():
            if hasattr(self, 'vault_pending') and time.time() >= self.vault_retry_at:
                self.vault_retry_at = time.time() + 60
                for pending in list(self.vault_pending):
                    self.export(pending)
            if not onboarding.ready(self.profile()):
                self.stop.wait(1)
                continue
            job = self.store.claim()
            if not job:
                self.stop.wait(1)
                continue
            iid = job['item_id']
            self.active = f'#{iid}: {job["kind"]}'
            try:
                item = self.store.get(iid)
                if job['kind'] == 'analyze':
                    content = item['content'] or self.extract(iid, json.loads(item['raw']))
                    self.store.set(iid, content=content)
                    self.export(iid)
                    effective = self.config | {'profile': self.profile()}
                    plan = agent.analyze(content, effective, self.data / 'runs' / str(iid))
                    plan = agent.prepare_execution(plan, self.config)
                    # "Not needed now" goes straight to the archive instead of waiting for a click.
                    status = 'archived' if plan['verdict'] == 'archive' else 'review'
                    self.store.set(iid, analysis=json.dumps(plan, ensure_ascii=False), status=status, error=None)
                    self.export(iid)
                    self.notify(*review_text(self.store.get(iid), self.base_label(plan)))
                else:
                    self.notify(f'#{iid}: начинаю одобренную задачу в отдельной Git-ветке.')
                    result = agent.execute(iid, json.loads(item['analysis']), self.config, self.data,
                                           lambda path: self.store.set(iid, worktree=path))
                    label = 'выполнение завершено' if result['status'] == 'completed' else 'задача не выполнена: агент сообщил о препятствии'
                    report = f'#{iid}: {label}.\nВетка: {result["branch"]} (от {result["base"]})\nПапка: {result["path"]}\n\n{result["summary"]}\n\nИзменения:\n{result["diff"]}\nНовые файлы:\n{result["new_files"]}\n\nРабочая ветка сохранена для проверки. Слияние и публикация не выполнялись.'
                    self.store.set(iid, status='done' if result['status'] == 'completed' else 'execution_blocked', result=report)
                    self.export(iid)
                    self.notify(report[:14000])
            except Exception as exc:
                # Full detail only in local protected data; keep Telegram error useful and credential-free.
                detail = self.redact(str(exc))
                LOG.error('Item %s %s failed: %s', iid, job['kind'], detail)
                status = 'error' if job['kind'] == 'analyze' else 'execution_error'
                self.store.set(iid, status=status, error=detail[:4000])
                self.export(iid)
                hint = f'/retry {iid} — повторить анализ.' if status == 'error' else 'Автоповтор выполнения отключён. Проверьте рабочую ветку.'
                # Avoid sending arbitrary CLI stderr (may contain local configuration) to the chat.
                visible = detail[:650] if isinstance(exc, ValueError) else f'Ошибка обработки ({type(exc).__name__}). Детали сохранены локально.'
                self.notify(f'#{iid}: {visible}\n{hint}')
            finally:
                self.store.finish(job['id'])
                self.active = None

    def sender(self):
        while not self.stop.is_set():
            for oid, payload in self.store.deliveries():
                try:
                    self.tg.call('sendMessage', chat_id=self.owner, **payload)
                    self.store.delivered(oid)
                except TelegramError as exc:
                    if exc.code == 400:
                        # Telegram will never accept this payload; retrying it would block every later message.
                        LOG.error('Outbox %s rejected, skipped: %s', oid, self.redact(exc))
                        self.store.delivered(oid, failed=True)
                        continue
                    LOG.warning('Outbox delivery: %s', self.redact(exc))
                    break
            self.stop.wait(2)

    def run(self):
        webhook = self.tg.call('getWebhookInfo')
        if webhook.get('url'):
            raise RuntimeError('У бота уже настроен webhook. Остановите другой экземпляр перед запуском.')
        me = self.tg.call('getMe')
        LOG.info('Starting @%s, owner %s', me['username'], self.owner)
        for iid in self.store.recover():
            self.notify(f'#{iid}: выполнение прервано перезапуском; проверь рабочую ветку. Автоповтор отключён.')
        worker = threading.Thread(target=self.worker, daemon=True)
        sender = threading.Thread(target=self.sender, daemon=True)
        worker.start()
        sender.start()
        failures = {}
        while not self.stop.is_set():
            if not worker.is_alive() or not sender.is_alive():
                raise RuntimeError('Worker thread stopped; restarting bot to recover durable jobs')
            try:
                for u in self.store.pending_updates():
                    try:
                        self.handle(u)
                    except Exception as exc:
                        # A permanently failing update must not stop polling for all later ones.
                        failures[u['update_id']] = failures.get(u['update_id'], 0) + 1
                        if failures[u['update_id']] < 3:
                            raise
                        LOG.error('Update %s skipped after 3 failures: %s', u['update_id'], self.redact(exc))
                        self.notify('Одно сообщение не удалось обработать после 3 попыток. Пришли его ещё раз.')
                    self.store.handled(u['update_id'])
                updates = self.tg.call('getUpdates', offset=self.store.offset(), timeout=25,
                                       allowed_updates=['message', 'callback_query'])
                self.store.ingest(updates)
                (self.data / 'heartbeat.json').write_text(json.dumps({'time': time.time(), 'active': self.active}), encoding='utf-8')
            except Exception as exc:
                LOG.warning('Polling: %s', self.redact(exc))
                self.stop.wait(5)


def setup_logging():
    DATA.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(DATA / 'bot.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    token, config = load_settings()
    setup_logging()
    bot = Bot(token, config)
    if args.check:
        me = bot.tg.call('getMe')
        webhook = bot.tg.call('getWebhookInfo')
        print(json.dumps({'bot': me['username'], 'owner': bot.owner, 'webhook': bool(webhook.get('url')),
                          'projects': list(config['projects'])}, ensure_ascii=False))
        return
    # OS file lock prevents concurrent consumers even after supervisor restart.
    lock = (DATA / 'instance.lock').open('a+b')
    if os.name == 'nt':
        import msvcrt
        lock.seek(0)
        if lock.read(1) == b'':
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    (DATA / 'bot.pid').write_text(str(os.getpid()), encoding='ascii')
    bot.run()


if __name__ == '__main__':
    main()
