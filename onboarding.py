"""A small focus check, not an identity questionnaire or a reader of private chat histories."""

QUESTIONS = [
    ('goals', 'Что сейчас в фокусе и к какому результату хочешь прийти? Можно коротко: 1–3 приоритета.'),
    ('interests', 'Какие материалы особенно полезны для этого? Что точно не стоит предлагать?'),
    ('constraints', 'Сколько времени и внимания готово уходить на применение находок? Есть другие ограничения?'),
]


def ready(profile):
    return isinstance(profile, dict) and profile.get('completed') is True and bool(str(profile.get('goals', '')).strip())


def make_profile(answers, language='ru'):
    return {key: str(answers.get(key, '')).strip()[:3000] for key, _ in QUESTIONS} | {'language': language, 'completed': True}


def summary(profile):
    return '\n'.join(f'{label}: {profile.get(key) or "не задано"}' for key, label in
                     [('goals', 'Текущий фокус'), ('interests', 'Полезное и нежелательное'), ('constraints', 'Ограничения')])
