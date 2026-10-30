"""Local setup wizard. Credentials are entered only in a hidden local prompt."""
import argparse
import getpass
import json
import os
from pathlib import Path
import time

import onboarding

ROOT = Path(__file__).resolve().parent


def save_config(config, root=ROOT):
    path = root / 'config.local.json'
    temp = root / 'config.local.json.tmp'
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def save_profile(config, profile, root=ROOT):
    if not onboarding.ready(profile):
        raise ValueError('Нужен подтверждённый непустой текущий фокус')
    config['profile'] = profile
    save_config(config, root)
    if (root / 'data/state.sqlite3').exists():
        from storage import Store
        Store(root / 'data/state.sqlite3').put_meta('profile', profile)


def pairing(telegram, username, timeout=180):
    print(f'Открой https://t.me/{username} и нажми /start. Затем подтверди свой аккаунт здесь.')
    deadline, offset = time.time() + timeout, 0
    rejected = set()
    while time.time() < deadline:
        updates = telegram.call('getUpdates', offset=offset, timeout=20, allowed_updates=['message'])
        for update in updates:
            offset = max(offset, update['update_id'] + 1)
            message = update.get('message', {})
            chat, sender = message.get('chat', {}), message.get('from', {})
            if (chat.get('type') != 'private' or chat.get('id') != sender.get('id')
                    or not message.get('text', '').startswith('/start') or sender.get('id') in rejected):
                continue
            label = sender.get('username') or sender.get('first_name') or str(sender['id'])
            if input(f'Это твой аккаунт {label} (ID {sender["id"]})? [y/N] ').strip().lower() in {'y', 'yes', 'д', 'да'}:
                return sender['id']
            rejected.add(sender['id'])
    raise ValueError('Не получили подтверждённый /start. Запусти настройку ещё раз.')


def main():
    parser = argparse.ArgumentParser(description='Короткая настройка личного фильтра сохранённых материалов')
    parser.add_argument('--profile-json', help='Только подтверждённые приоритеты; без токенов')
    args = parser.parse_args()
    local = ROOT / 'config.local.json'
    config = json.loads((local if local.exists() else ROOT / 'config.example.json').read_text(encoding='utf-8-sig'))
    if args.profile_json:
        profile = json.loads(args.profile_json)
        save_profile(config, profile)
        print('Подтверждённый фокус сохранён. Локальные настройки и проекты сохранены.')
        return

    print('Сохранёнки: настроим актуальный фокус. Имя и биография не нужны.\n'
          'Если настраиваешь через Codex, он может опереться на уже доступную ему память.\n'
          'Бот получает только подтверждённые приоритеты; архив других чатов не читается.\n')
    if not onboarding.ready(config.get('profile')):
        answers = {key: input(question + '\n> ').strip() for key, question in onboarding.QUESTIONS}
        profile = onboarding.make_profile(answers)
        print('\n' + onboarding.summary(profile))
        if input('Верно сохранить такой фокус? [y/N] ').strip().lower() not in {'y', 'yes', 'д', 'да'}:
            print('Настройка отменена; фокус не сохранён.')
            return
        if not onboarding.ready(profile):
            raise ValueError('Текущий фокус не может быть пустым')
        save_profile(config, profile)
    else:
        print('Использую уже подтверждённый фокус:\n' + onboarding.summary(config['profile']))

    from bot import Telegram
    env_path = ROOT / '.env'
    env_text = env_path.read_text(encoding='utf-8-sig') if env_path.exists() else ''
    values = dict(line.split('=', 1) for line in env_text.splitlines() if '=' in line and not line.lstrip().startswith('#'))
    token = os.environ.get('TELEGRAM_BOT_TOKEN') or values.get('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        print('\nСоздай собственного бота у @BotFather. Токен вводится скрыто только в этом окне.')
        token = getpass.getpass('Токен бота: ').strip()
    import re
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', token):
        raise ValueError('Неверный формат токена')
    telegram = Telegram(token)
    me = telegram.call('getMe')
    if telegram.call('getWebhookInfo').get('url'):
        raise ValueError('Этот бот уже использует webhook. Для настройки создай отдельного бота.')
    if not config.get('owner_id'):
        config['owner_id'] = pairing(telegram, me['username'])
    # Preserve other local variables; never print the credential or put it into command arguments.
    if not values.get('TELEGRAM_BOT_TOKEN'):
        env_path.write_text(env_text.rstrip() + ('\n' if env_text else '') + 'TELEGRAM_BOT_TOKEN=' + token + '\n', encoding='utf-8')
        if os.name != 'nt':
            env_path.chmod(0o600)
    save_config(config)
    print(f'Готово: https://t.me/{me["username"]}\nПроверка: python bot.py --check\nЗапуск: python bot.py')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, KeyboardInterrupt) as exc:
        print('Настройка не завершена: ' + (str(exc) if str(exc) else 'отменено'))
        raise SystemExit(1)
