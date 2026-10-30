import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage import Store
from bot import authorized, Bot
import media
import agent

OWNER = 123456789


def message(uid=1, owner=OWNER, chat=None, kind='private'):
    return {'update_id': uid, 'message': {'from': {'id': owner}, 'chat': {'id': owner if chat is None else chat, 'type': kind}, 'text': 'test'}}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'state.db')

    def tearDown(self):
        # sqlite connection context commits; CPython closes connection references promptly.
        import gc
        gc.collect()
        self.tmp.cleanup()

    def item(self):
        return self.store.new_item(1, message()['message'])

    def reviewed(self):
        iid = self.item()
        self.store.set(iid, status='review', analysis=json.dumps({'project': 'test', 'task': 'bounded task', 'execution': {'sha': 'a' * 40}}))
        return iid

    def test_intake_idempotence_and_durable_offset(self):
        self.store.ingest([message(10), message(11)])
        self.assertEqual(Store(self.store.path).offset(), 12)
        self.assertEqual(len(self.store.pending_updates()), 2)
        self.store.handled(10)
        self.assertEqual(len(self.store.pending_updates()), 1)
        self.assertIsNotNone(self.item())
        self.assertIsNone(self.item())

    def test_double_click_and_archive_cannot_execute(self):
        iid = self.reviewed()
        self.assertTrue(self.store.decide(iid, 'archive'))
        self.assertFalse(self.store.decide(iid, 'execute'))
        self.assertEqual(self.store.get(iid)['status'], 'archived')
        job = self.store.claim()
        self.assertEqual(job['kind'], 'analyze')
        self.store.finish(job['id'])
        self.assertIsNone(self.store.claim())

    def test_execution_approval_exactly_once(self):
        iid = self.reviewed()
        self.assertTrue(self.store.decide(iid, 'execute'))
        self.assertFalse(self.store.decide(iid, 'execute'))
        first = self.store.claim()
        self.store.finish(first['id'])
        second = self.store.claim()
        self.assertEqual(second['kind'], 'execute')
        self.store.finish(second['id'])
        self.assertIsNone(self.store.claim())

    def test_recovery_never_replays_execution(self):
        iid = self.reviewed()
        self.store.decide(iid, 'execute')
        self.store.finish(self.store.claim()['id'])
        job = self.store.claim()
        self.assertEqual(job['kind'], 'execute')
        self.assertEqual(self.store.recover(), [iid])
        self.assertEqual(self.store.get(iid)['status'], 'interrupted')
        self.assertIsNone(self.store.claim())
        self.assertFalse(self.store.retry(iid))

    def test_analysis_resumes_after_crash(self):
        iid = self.item()
        self.store.claim()
        self.assertEqual(self.store.recover(), [])
        self.assertEqual(self.store.claim()['item_id'], iid)

    def test_outbox_survives_restart(self):
        self.store.notify('hello')
        new = Store(self.store.path)
        deliveries = new.deliveries()
        self.assertEqual(deliveries[0][1]['text'], 'hello')
        new.delivered(deliveries[0][0])
        self.assertFalse(self.store.deliveries())

    def test_expired_callback_does_not_block_archive(self):
        iid = self.reviewed()
        instance = Bot.__new__(Bot)
        instance.owner = OWNER
        instance.store = self.store
        instance.tg = unittest.mock.Mock()
        instance.tg.call.side_effect = RuntimeError('query is too old')
        instance.export = unittest.mock.Mock()
        instance.notify = unittest.mock.Mock()
        instance.handle({'callback_query': {'id': 'expired', 'from': {'id': OWNER},
                        'data': f'archive:{iid}', 'message': {'message_id': 7,
                        'chat': {'id': OWNER, 'type': 'private'}}}})
        self.assertEqual(self.store.get(iid)['status'], 'archived')
        instance.notify.assert_called_once()


    def bot(self):
        instance = Bot.__new__(Bot)
        instance.owner = OWNER
        instance.store = self.store
        instance.config = {'projects': {}, 'execution_enabled': False,
                           'profile': {'goals': 'Learn photography', 'completed': True}}
        instance.tg = unittest.mock.Mock()
        return instance

    def test_rejected_notification_does_not_block_outbox(self):
        from bot import TelegramError
        self.store.notify('bad')
        self.store.notify('good')
        instance = self.bot()
        sent = []
        def call(method, **payload):
            if payload['text'] == 'bad':
                raise TelegramError('Bad Request', 400)
            sent.append(payload['text'])
            instance.stop.set()
        instance.tg.call.side_effect = call
        instance.stop = unittest.mock.Mock()
        instance.stop.is_set.side_effect = [False, True]
        instance.sender()
        self.assertEqual(sent, ['good'])
        self.assertFalse(self.store.deliveries())

    def test_whitespace_chunks_are_not_queued(self):
        instance = self.bot()
        instance.notify('a' * 3700 + '   ')
        self.assertEqual([p['text'] for _, p in self.store.deliveries()], ['a' * 3700])

    def test_archive_verdict_is_archived_without_click(self):
        iid = self.item()
        instance = self.bot()
        instance.data = Path(self.tmp.name)
        instance.export = unittest.mock.Mock()
        instance.notify = unittest.mock.Mock()
        instance.active = None
        plan = {'title': 'Noise', 'summary': 'No value', 'score': 2, 'verdict': 'archive',
                'project': '', 'reason': 'Nothing to do', 'task': '', 'acceptance': []}
        instance.stop = unittest.mock.Mock()
        instance.stop.is_set.side_effect = [False, True]
        self.store.set(iid, content='text')
        with patch('agent.analyze', return_value=plan):
            instance.worker()
        self.assertEqual(self.store.get(iid)['status'], 'archived')
        self.assertIsNone(instance.notify.call_args[0][1])
        self.assertFalse(self.store.decide(iid, 'archive'))

    def test_vault_failure_does_not_break_intake(self):
        instance = self.bot()
        instance.vault = Path(self.tmp.name) / 'vault'
        (instance.vault / '.git').mkdir(parents=True)
        (instance.vault / '.git' / 'index.lock').write_text('', encoding='utf-8')
        instance.vault_lock = __import__('threading').Lock()
        instance.vault_pending = set()
        iid = self.item()
        with patch('agent.run_process', side_effect=RuntimeError('git: код 128')):
            instance.export(iid)
        self.assertTrue((instance.vault / f'{iid:06d}' / 'material.md').exists())
        self.assertTrue((instance.vault / '.git' / 'index.lock').exists())
        self.assertEqual(self.store.meta('vault_pending'), [iid])


class SecurityTests(unittest.TestCase):
    def test_archive_verdict_with_empty_project_stays_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = {'title': 'Noise', 'summary': 'No value', 'score': 2, 'verdict': 'archive',
                    'project': '', 'reason': 'No problem to solve', 'task': '', 'acceptance': []}
            with patch('agent.cli', return_value=json.dumps(plan)), patch('agent.project_context', return_value={}):
                actual = agent.analyze('test', {'projects': {}}, Path(tmp))
            self.assertEqual(actual['verdict'], 'archive')

    def test_unknown_project_cannot_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = {'title': 'Test', 'summary': 'Test', 'score': 90, 'verdict': 'implement',
                    'project': '../../other', 'reason': 'Test', 'task': 'touch files', 'acceptance': []}
            with patch('agent.cli', return_value=json.dumps(plan)), patch('agent.project_context', return_value={}):
                actual = agent.analyze('test', {'projects': {}}, Path(tmp))
            self.assertEqual(actual['project'], '')
            self.assertEqual(actual['task'], '')
            self.assertEqual(actual['verdict'], 'watch')

    def test_transcript_cache_avoids_redownload_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'transcript.txt').write_text('Source and transcript', encoding='utf-8')
            with patch('media.public_url', side_effect=lambda s: s), patch('media.run_process') as run:
                actual = media.video_url('https://www.instagram.com/reel/test/', folder, {})
                self.assertEqual(actual, 'Source and transcript')
                run.assert_not_called()

    def test_each_video_link_gets_own_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            instance = Bot.__new__(Bot)
            instance.data = Path(tmp)
            instance.config = {}
            instance.notify = unittest.mock.Mock()
            seen = []
            def video(url, folder, config):
                seen.append(folder.name)
                return url
            msg = {'text': 'https://www.instagram.com/reel/a/ https://www.instagram.com/reel/b/'}
            with patch('media.video_url', side_effect=video):
                content = instance.extract(1, msg)
            self.assertEqual(seen, ['video', 'video-2'])
            self.assertIn('reel/b', content)

    def test_execution_uses_configured_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            def run(args, **kwargs):
                calls.append(args)
                return ('a' * 40 + '\n') if 'rev-parse' in args else 'main\n'
            plan = {'project': 'p', 'task': 't', 'acceptance': [], 'reason': 'r'}
            config = {'execution_enabled': True, 'projects': {'p': {'path': tmp, 'base': 'main'}}}
            result = {'status': 'completed', 'summary': 's', 'checks': [], 'limitations': ''}
            with patch('agent.run_process', side_effect=run), patch('agent.cli', return_value=json.dumps(result)):
                plan = agent.prepare_execution(plan, config)
                actual = agent.execute(1, plan, config, Path(tmp), lambda p: None)
            add = next(a for a in calls if 'worktree' in a)
            self.assertEqual(add[-1], 'a' * 40)
            self.assertEqual(actual['base'], 'main @ ' + 'a' * 12)

    def test_owner_only_in_private_chat(self):
        self.assertTrue(authorized(message(), OWNER))
        self.assertFalse(authorized(message(owner=123), OWNER))
        self.assertFalse(authorized(message(chat=-123, kind='group'), OWNER))
        self.assertFalse(authorized({'channel_post': {}}, OWNER))

    def test_callback_owner_check(self):
        cb = {'callback_query': {'from': {'id': OWNER}, 'message': {'chat': {'id': OWNER, 'type': 'private'}}}}
        self.assertTrue(authorized(cb, OWNER))
        cb['callback_query']['from']['id'] = 123
        self.assertFalse(authorized(cb, OWNER))

    def test_reject_local_urls(self):
        for url in ['file:///etc/passwd', 'http://127.0.0.1', 'http://169.254.169.254/latest/meta-data', 'http://[::1]', 'http://a:b@example.com', 'http://example.com:3000']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                media.public_url(url)

    def test_redirects_revalidated(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.status_code = 302
        response.headers = {'Location': 'http://127.0.0.1/secret'}
        def resolve(host, *args, **kwargs):
            return [(2,1,6,'',('127.0.0.1' if host == '127.0.0.1' else '93.184.216.34',80))]
        with patch('media.requests.Session') as session, patch('media.socket.getaddrinfo', side_effect=resolve):
            session.return_value.get.return_value = response
            with self.assertRaises(ValueError):
                media.fetch_page('https://example.com')
            self.assertEqual(session.return_value.get.call_count, 1)

    def test_media_only_deleted_after_persisted_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'video.mp4'
            p.write_bytes(b'fake')
            with patch('media.transcribe', side_effect=ValueError('failed')):
                with self.assertRaises(ValueError):
                    media.attachment_text(p, 'video/mp4', {})
            self.assertTrue(p.exists())
            with patch('media.transcribe', return_value='Recognized speech'):
                self.assertEqual(media.attachment_text(p, 'video/mp4', {}), 'Recognized speech')
            self.assertFalse(p.exists())
            self.assertEqual(p.with_suffix('.mp4.transcript.txt').read_text(encoding='utf-8'), 'Recognized speech')


if __name__ == '__main__':
    unittest.main()
