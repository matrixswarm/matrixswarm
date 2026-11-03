"""LifeSignal durable monitoring and source handling tests."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'matrixos' / 'agents' / 'python_core'))
from life_signal.engine import LifeSignalEngine, normalize_source
from life_signal.sources import challenge, feed_entries, page_text, retry_seconds, robots_allowed, _read, Challenge, RateLimited


def source(**values):
    result = {'id': 'one', 'name': 'Example', 'url': 'https://example.com/news',
              'kind': 'page', 'keywords': ['celebrity', 'retirement'],
              'interval_sec': 3600, 'alert_role': 'hive.alert', 'enabled': True}
    result.update(values)
    return result


class LifeSignalTests(unittest.TestCase):
    def setUp(self):
        self.saved = []
        self.engine = LifeSignalEngine(lambda doc: self.saved.append(deepcopy(doc)))
        self.engine.replace([source()], 0)

    def test_first_read_is_baseline_changes_are_persistent_and_deduplicated(self):
        self.assertIsNone(self.engine.record_observation('one', 'old', 'https://example.com/news', 'Title'))
        query = self.engine.record_observation('one', 'new', 'https://example.com/news', 'Title')
        self.assertTrue(query)
        self.assertIsNone(self.engine.record_observation('one', 'new', 'https://example.com/news', 'Title'))
        resumed = LifeSignalEngine(lambda doc: self.saved.append(deepcopy(doc)), self.saved[-1])
        self.assertIn(query, resumed.queue())
        resumed.mark_sent(query, 'oracle-1')
        self.assertFalse(resumed.complete_analysis(query, 'forged', {'match': True}))
        self.assertTrue(resumed.complete_analysis(query, 'oracle-1', {'match': True, 'summary': 'A report'}))
        self.assertEqual(len(resumed.snapshot()['events']), 1)

    def test_snapshot_reports_successful_baseline_and_pending_analysis(self):
        self.assertNotIn('one', self.engine.snapshot()['observations'])
        self.engine.record_observation('one', 'old', source()['url'], 'Title', now=1000)
        baseline = self.engine.snapshot()['observations']['one']
        self.assertTrue(baseline['baseline_ready'])
        self.assertEqual(baseline['last_success_at'], 1000)
        self.assertNotIn('text', baseline)
        self.engine.record_observation('one', 'new', source()['url'], 'Title', now=1120)
        self.assertEqual(self.engine.snapshot()['pending_counts']['one'], 1)
        self.engine.record_error('one', 'network failure')
        self.assertEqual(self.engine.snapshot()['observations']['one']['last_success_at'], 1120)

    def test_empty_feed_still_has_a_valid_baseline(self):
        self.engine.record_feed('one', [], now=1000)
        observation = self.engine.snapshot()['observations']['one']
        self.assertTrue(observation['baseline_ready'])
        self.assertEqual(observation['last_success_at'], 1000)

    def test_challenge_pause_survives_restart_and_configuration_edit(self):
        self.engine.pause_host('example.com', 'challenge')
        revised = source(name='Updated')
        self.engine.replace([revised], 1)
        resumed = LifeSignalEngine(lambda doc: self.saved.append(deepcopy(doc)), self.saved[-1])
        self.assertIsNone(resumed.record_observation('one', 'ignored', revised['url'], 'Title'))
        self.assertIn('example.com', resumed.snapshot()['blocked_hosts'])
        resumed.resume_host('example.com')
        self.assertNotIn('example.com', resumed.snapshot()['blocked_hosts'])

    def test_feed_baseline_and_new_entry(self):
        entries = [{'id': 'old', 'url': 'https://example.com/old', 'title': 'old', 'text': 'old'}]
        self.engine.record_feed('one', entries)
        self.assertFalse(self.engine.queue())
        self.engine.record_feed('one', entries + [{'id': 'new', 'url': 'https://example.com/new', 'title': 'new', 'text': 'new'}])
        self.assertEqual(len(self.engine.queue()), 1)
        self.engine.record_feed('one', entries)
        self.assertEqual(len(self.engine.queue()), 1)

    def test_death_report_dedup_across_sources(self):
        self.engine.record_observation('one', 'base', source()['url'], 'Title')
        first = self.engine.record_observation('one', 'first', source()['url'], 'Title')
        self.engine.mark_sent(first, 'oracle')
        self.engine.complete_analysis(first, 'oracle', {'match': True, 'person': 'Jane Example', 'event_type': 'death'})
        second = self.engine.record_observation('one', 'second', source()['url'], 'Title')
        self.engine.mark_sent(second, 'oracle')
        self.engine.complete_analysis(second, 'oracle', {'match': True, 'person': 'Jane Example', 'event_type': 'death'})
        self.assertEqual(len(self.engine.snapshot()['events']), 1)

    def test_revision_and_disabled_source(self):
        with self.assertRaises(ValueError): self.engine.replace([], 0)
        self.engine.replace([source(enabled=False)], 1)
        self.assertIsNone(self.engine.record_observation('one', 'new', source()['url'], 'Title'))
        self.assertFalse(self.engine.queue())

    def test_invalid_urls_and_keywords(self):
        for url in ('http://example.com', 'https://user:secret@example.com', 'https://example.com:444'):
            with self.assertRaises(ValueError): normalize_source(source(url=url))
        with self.assertRaises(ValueError): normalize_source(source(keywords=[]))

    def test_two_minute_interval_persists_without_dropping_pending_analysis(self):
        self.engine.record_observation('one', 'old', source()['url'], 'Title')
        query = self.engine.record_observation('one', 'new', source()['url'], 'Title')
        self.engine.replace([source(interval_sec=120)], 1)
        resumed = LifeSignalEngine(lambda doc: self.saved.append(deepcopy(doc)), self.saved[-1])
        self.assertEqual(resumed.snapshot()['sources'][0]['interval_sec'], 120)
        self.assertIn(query, resumed.queue())
        with self.assertRaises(ValueError): normalize_source(source(interval_sec=119))

    def test_captcha_mode_checks_first_read_and_rechecks_after_a_clear_result(self):
        monitored = source(analysis_mode='captcha', keywords=[])
        self.engine.replace([monitored], 1)
        query = self.engine.record_captcha_check('one', 'Welcome to the site', monitored['url'], 'Page')
        self.assertTrue(query)
        self.assertIsNone(self.engine.record_captcha_check('one', 'Welcome', monitored['url'], 'Page'))
        self.engine.mark_sent(query, 'oracle')
        self.assertTrue(self.engine.complete_analysis(query, 'oracle', {'captcha': 'no', 'summary': 'Normal page'}))
        observation = self.engine.snapshot()['observations']['one']
        self.assertEqual(observation['captcha_status'], 'no')
        self.assertFalse(self.engine.snapshot()['blocked_hosts'])
        self.assertTrue(self.engine.record_captcha_check('one', 'Welcome again', monitored['url'], 'Page'))

    def test_captcha_mode_does_not_pause_for_inconclusive_or_unverified_response(self):
        monitored = source(analysis_mode='captcha', keywords=[])
        self.engine.replace([monitored], 1)
        query = self.engine.record_captcha_check('one', 'Unknown', monitored['url'], 'Page')
        self.engine.mark_sent(query, 'oracle')
        self.assertFalse(self.engine.complete_analysis(query, 'impostor', {'captcha': 'yes'}))
        self.assertTrue(self.engine.complete_analysis(query, 'oracle', {'captcha': 'uncertain'}))
        self.assertFalse(self.engine.snapshot()['blocked_hosts'])
        self.assertEqual(self.engine.snapshot()['observations']['one']['captcha_status'], 'uncertain')

    def test_captcha_pause_survives_restart_and_clears_queued_host_queries(self):
        monitored = source(analysis_mode='captcha', keywords=[])
        self.engine.replace([monitored], 1)
        query = self.engine.record_captcha_check('one', 'Verify access', monitored['url'], 'Page')
        self.engine.mark_sent(query, 'oracle')
        self.assertTrue(self.engine.complete_analysis(query, 'oracle', {'captcha': 'yes'}))
        resumed = LifeSignalEngine(lambda doc: self.saved.append(deepcopy(doc)), self.saved[-1])
        self.assertIn('example.com', resumed.snapshot()['blocked_hosts'])
        self.assertFalse(resumed.queue())
        self.assertIsNone(resumed.record_captcha_check('one', 'still blocked', monitored['url'], 'Page'))
        resumed.resume_host('example.com')
        self.assertTrue(resumed.record_captcha_check('one', 'fresh check', monitored['url'], 'Page'))

    def test_detected_challenge_removes_queued_feed_analysis_from_that_host(self):
        self.engine.record_feed('one', [])
        self.engine.record_feed('one', [{'id': 'new', 'url': 'https://elsewhere.example/story',
                                         'title': 'Story', 'text': 'Story'}])
        self.assertTrue(self.engine.queue())
        self.engine.report_challenge(source(), 'access challenge')
        self.assertIn('example.com', self.engine.snapshot()['blocked_hosts'])
        self.assertFalse(self.engine.queue())

    def test_feed_and_page_extraction(self):
        feed = b'<rss><channel><item><guid>one</guid><title>News</title><link>https://example.com/one</link><description>A story</description></item></channel></rss>'
        result = feed_entries(feed, 'https://example.com/feed')
        self.assertEqual(result[0]['id'], 'one')
        self.assertIn('A story', result[0]['text'])
        title, text = page_text(b'<html><title>News</title><script>ignore</script><p>Story</p></html>')
        self.assertEqual(title, 'News')
        self.assertIn('Story', text)
        self.assertNotIn('ignore', text)

    def test_challenge_and_retry_detection(self):
        self.assertTrue(challenge(200, b'<div class="g-recaptcha">'))
        self.assertTrue(challenge(403, b'forbidden'))
        self.assertFalse(challenge(200, b'<p>ordinary news</p>'))
        self.assertEqual(retry_seconds('7200'), 7200)

    def test_network_response_challenge_and_rate_limit(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content.return_value = [b'captcha-delivery']
        response.status_code = 200
        session = Mock(); session.get.return_value = response
        with patch('life_signal.sources.MIN_REQUEST_SPACING', 0):
            with self.assertRaises(Challenge): _read(session, 'https://example.com', 1000)
            response.iter_content.return_value = [b'too many requests']
            response.status_code = 429; response.headers = {'Retry-After': '7200'}
            with self.assertRaises(RateLimited) as error: _read(session, 'https://example.com', 1000)
        self.assertEqual(error.exception.retry_after, 7200)

    def test_robots_wildcards_and_most_specific_rule(self):
        rules = 'User-agent: *\nDisallow: /private/*\nAllow: /private/public$\n'
        self.assertFalse(robots_allowed(rules, 'https://example.com/private/story'))
        self.assertTrue(robots_allowed(rules, 'https://example.com/private/public'))
        self.assertFalse(robots_allowed(rules, 'https://example.com/private/public/more'))

    def test_oversized_analysis_requires_explicit_retry(self):
        self.engine.record_observation('one', 'old', source()['url'], 'Title')
        query = self.engine.record_observation('one', 'new', source()['url'], 'Title')
        self.engine.mark_sent(query, 'oracle')
        self.engine.analysis_error(query, 'oracle', 'too large')
        self.assertIn(query, self.engine.snapshot()['analysis_errors'])
        self.engine.retry_analysis('one')
        self.assertNotIn('error', self.engine.queue()[query])
        self.assertEqual(self.engine.queue()[query]['last_sent'], 0)

    def test_stream_change_survives_restart_and_newer_event_is_not_cleared(self):
        self.engine.mark_wiki_dirty('one')
        first = self.engine.snapshot()['wiki_dirty']['one']
        self.engine.mark_wiki_dirty('one')
        self.engine.clear_wiki_dirty('one', first)
        resumed = LifeSignalEngine(lambda doc: self.saved.append(deepcopy(doc)), self.saved[-1])
        self.assertIn('one', resumed.snapshot()['wiki_dirty'])
        latest = resumed.snapshot()['wiki_dirty']['one']
        resumed.clear_wiki_dirty('one', latest)
        self.assertNotIn('one', resumed.snapshot()['wiki_dirty'])


if __name__ == '__main__': unittest.main()
