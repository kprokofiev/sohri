import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
import onboarding
from bot import Bot, review_text
from storage import Store
import setup

PROFILE = {'goals': 'Освоить акварель', 'interests': 'Практика, без покупок новых курсов',
           'constraints': '20 минут в день', 'completed': True, 'language': 'ru'}
PLAN = {'title': 'Упражнение', 'summary': 'Полезная практика', 'score': 85, 'verdict': 'implement',
        'project': '', 'reason': 'Соответствует цели', 'task': 'Попробовать одну заливку',
        'acceptance': ['Один пробный лист готов']}


class PersonalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bot = Bot.__new__(Bot)
        self.bot.data = self.root
        self.bot.owner = 123456789
        self.bot.config = {'projects': {}, 'profile': PROFILE, 'execution_enabled': False}
        self.bot.store = Store(self.root / 'state.db')
        self.bot.tg = Mock()
        self.bot.export = Mock()
        self.bot.stop = threading.Event()

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_repo_needed_and_confirmed_focus_reaches_analysis(self):
        with patch('agent.cli', return_value=json.dumps(PLAN)) as cli:
            result = agent.analyze('Упражнение по акварели', self.bot.config, self.root / 'run')
        self.assertEqual(result['task'], PLAN['task'])
        self.assertEqual(result['verdict'], 'implement')
        prompt = cli.call_args.args[0]
        self.assertIn(PROFILE['goals'], prompt)
        self.assertIn(PROFILE['constraints'], prompt)
        self.assertIn('личный помощник по приоритизации', prompt)

    def test_personal_action_only_saves_plan(self):
        iid = self.bot.store.new_item(1, {'text': 'painting'})
        job = self.bot.store.claim()
        self.bot.store.finish(job['id'])
        self.bot.store.set(iid, status='review', analysis=json.dumps(PLAN))
        text, keyboard = review_text(self.bot.store.get(iid))
        self.assertIn(PLAN['task'], text)
        self.assertEqual(keyboard['inline_keyboard'][0][0]['callback_data'], f'plan:{iid}')
        self.assertTrue(self.bot.store.decide(iid, 'plan'))
        self.assertFalse(self.bot.store.decide(iid, 'execute'))
        self.assertEqual(self.bot.store.listed('planned')[0]['id'], iid)
        self.assertIsNone(self.bot.store.claim())
        self.assertTrue(self.bot.store.complete_personal(iid))
        self.assertFalse(self.bot.store.complete_personal(iid))
        self.assertFalse(self.bot.store.listed('planned'))

    def test_existing_focus_skips_onboarding(self):
        self.bot.command('/start')
        self.assertIsNone(self.bot.store.meta('onboarding'))
        self.assertTrue(self.bot.store.deliveries())

    def test_focus_check_is_three_questions_without_identity(self):
        self.bot.config['profile'] = {}
        self.bot.command('/start')
        self.assertEqual(self.bot.store.meta('onboarding')['step'], 0)
        for answer in ['Хочу научиться рисовать', 'Упражнения, без рекламы', '20 минут в день']:
            self.bot.onboarding_answer(answer)
        self.assertTrue(onboarding.ready(self.bot.profile()))
        self.assertEqual(self.bot.profile()['goals'], 'Хочу научиться рисовать')
        self.assertNotIn('name', self.bot.profile())
        self.assertIsNone(self.bot.store.meta('onboarding'))

    def test_worker_waits_for_focus_and_keeps_material(self):
        self.bot.config['profile'] = {}
        iid = self.bot.store.new_item(1, {'text': 'material'})
        self.bot.stop = Mock()
        self.bot.stop.is_set.side_effect = [False, True]
        with patch('agent.analyze') as analyze:
            self.bot.worker()
        analyze.assert_not_called()
        self.assertEqual(self.bot.store.get(iid)['status'], 'queued')

    def test_execution_is_disabled_even_for_old_valid_plan(self):
        with self.assertRaisesRegex(ValueError, 'выключено'):
            agent.execute(1, {'project': 'p', 'task': 'change'}, self.bot.config, self.root, Mock())

    def test_profile_update_preserves_local_configuration(self):
        config = {'owner_id': 42, 'execution_enabled': True, 'projects': {'private': {'path': 'local'}}}
        setup.save_profile(config, PROFILE, self.root)
        self.assertEqual(config['owner_id'], 42)
        self.assertTrue(config['execution_enabled'])
        self.assertIn('private', config['projects'])

    def test_source_switch_does_not_change_approved_base(self):
        repo = self.root / 'fixture'
        repo.mkdir()
        def git(*args):
            return subprocess.check_output(['git', '-C', str(repo), *args], text=True, stderr=subprocess.DEVNULL).strip()
        git('init', '-b', 'main')
        (repo / 'README.md').write_text('main\n')
        git('add', '.')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture')
        config = {'execution_enabled': True, 'projects': {'p': {'path': str(repo)}}}
        plan = agent.prepare_execution(PLAN | {'project': 'p'}, config)
        original = plan['execution']['sha']
        git('switch', '-c', 'other')
        (repo / 'README.md').write_text('other\n')
        git('add', '.')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'other')
        response = {'status': 'completed', 'summary': 'fixture only', 'checks': [], 'limitations': ''}
        with patch('agent.cli', return_value=json.dumps(response)):
            result = agent.execute(1, plan, config, self.root / 'jobs', Mock())
        worktree = Path(result['path'])
        self.assertEqual(subprocess.check_output(['git', '-C', str(worktree), 'rev-parse', 'HEAD'], text=True).strip(), original)
        self.assertEqual((worktree / 'README.md').read_text(), 'main\n')
        git('worktree', 'remove', str(worktree))


if __name__ == '__main__':
    unittest.main()
