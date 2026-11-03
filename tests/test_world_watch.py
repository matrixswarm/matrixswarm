"""Private snapshots, source-attributed reports and bounded history."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'matrixos' / 'agents' / 'python_core'))
from world_watch.engine import PromiseEngine, FortuneEngine


def source():
    return {'id': 'one', 'name': 'Example', 'url': 'https://example.com/', 'kind': 'page',
            'keywords': ['release'], 'interval_sec': 120, 'alert_role': 'hive.alert', 'enabled': True}


class WatchTests(unittest.TestCase):
    def test_baseline_change_restart_and_attributed_alert(self):
        for engine_class in (PromiseEngine, FortuneEngine):
            with self.subTest(engine=engine_class):
                saved = []
                engine = engine_class(lambda d: saved.append(deepcopy(d)))
                engine.replace([source()], 0)
                self.assertIsNone(engine.record_observation('one', 'release pending', source()['url'], 'Example', 1000))
                self.assertTrue(engine.snapshot()['observations']['one']['baseline_ready'])
                self.assertFalse(engine.queue())
                query = engine.record_observation('one', 'release available', source()['url'], 'Example', 1120)
                self.assertEqual(engine.queue()[query]['analysis_mode'], engine.PROFILE)
                self.assertIsNone(engine.record_observation('one', 'release available', source()['url'], 'Example', 1240))
                resumed = engine_class(lambda d: saved.append(deepcopy(d)), saved[-1])
                captures = resumed.panel_snapshot()['captures']
                self.assertEqual(len(captures), 2)
                self.assertEqual(resumed.capture_chunk(captures[0]['id'], 0)['chunk'], 'release available')
                resumed.mark_sent(query, 'oracle')
                self.assertFalse(resumed.complete_analysis(query, 'wrong', {'match': True}))
                self.assertTrue(resumed.complete_analysis(query, 'oracle', {'match': True, 'summary': 'Release announced', 'effective_date': 'June 1'}))
                event = resumed.snapshot()['events'][0]
                self.assertEqual(event['url'], source()['url'])
                self.assertIn('Before: release pending', event['summary'])
                self.assertIn('After: release available', event['summary'])
                if engine.PROFILE == 'fortune': self.assertIn('Reported effective date (verify source): June 1', event['summary'])

    def test_capture_chunks_and_explicit_history_clearing(self):
        engine = PromiseEngine(lambda d: None)
        engine.replace([source()], 0)
        body = '😀' * 2000
        engine.record_observation('one', body, source()['url'], 'Title')
        ident = engine.panel_snapshot()['captures'][0]['id']
        first = engine.capture_chunk(ident, 0)
        last = engine.capture_chunk(ident, first['next_offset'])
        self.assertFalse(first['done']); self.assertTrue(last['done'])
        self.assertEqual(first['chunk'] + last['chunk'], body)
        engine.replace([], 1)
        engine.clear_history('one')
        self.assertFalse(engine.panel_snapshot()['captures'])

    def test_full_history_preserves_data_and_retries_after_clear(self):
        engine = PromiseEngine(lambda d: None)
        engine.replace([source()], 0)
        engine.record_observation('one', 'old', source()['url'], 'Title')
        with patch('world_watch.engine.MAX_CAPTURES', 1):
            self.assertIsNone(engine.record_observation('one', 'new', source()['url'], 'Title'))
            self.assertIn('history full', engine.snapshot()['observations']['one']['error'])
            engine.clear_history('one')
            self.assertTrue(engine.record_observation('one', 'new', source()['url'], 'Title'))

    def test_challenge_pause_and_irrelevant_change(self):
        engine = FortuneEngine(lambda d: None)
        engine.replace([source()], 0)
        engine.record_observation('one', 'old', source()['url'], 'Title')
        engine.pause_host('example.com', 'CAPTCHA')
        self.assertIsNone(engine.record_observation('one', 'new', source()['url'], 'Title'))
        engine.resume_host('example.com')
        query = engine.record_observation('one', 'new', source()['url'], 'Title')
        engine.mark_sent(query, 'oracle')
        engine.complete_analysis(query, 'oracle', {'match': False})
        self.assertFalse(engine.snapshot()['events'])

if __name__ == '__main__': unittest.main()
