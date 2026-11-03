"""Persistent page captures and attributed change reports."""
from copy import deepcopy
import difflib
import hashlib
import time
from urllib.parse import urlsplit
from uuid import uuid4

from life_signal.engine import LifeSignalEngine

MAX_CAPTURES = 100
MAX_CAPTURE_BYTES = 10_000_000


class WatchEngine(LifeSignalEngine):
    PROFILE = 'promise'

    def replace(self, sources, revision):
        if not isinstance(sources, list) or any(
                not isinstance(s, dict) or s.get('kind', 'page') != 'page'
                or s.get('analysis_mode', 'changes') != 'changes' for s in sources):
            raise ValueError('This agent supports webpage change watches')
        return super().replace(sources, revision)

    def panel_snapshot(self):
        with self.lock:
            result = super().panel_snapshot()
            result['captures'] = [dict(id=c['id'], source_id=c['source_id'],
                captured_at=c['captured_at'], sha256=c['sha256'])
                for c in reversed(self.doc.get('captures', [])[-10:])]
            return result

    def record_observation(self, source_id, text, url, title, now=None):
        now = now or time.time()
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        with self.lock:
            source = next((s for s in self.doc['sources'] if s['id'] == source_id), None)
            if (not source or source['url'] != url or not source['enabled']
                    or urlsplit(url).hostname in self.doc['blocked_hosts']):
                return None
            doc = deepcopy(self.doc)
            prior = doc['observations'].get(source_id, {})
            if prior.get('digest') == digest:
                prior.update(checked_at=now, last_success_at=now)
                prior.pop('error', None)
                doc['observations'][source_id] = prior
                self._write(doc)
                return None
            captures = doc.setdefault('captures', [])
            history_bytes = sum(len(c['text'].encode('utf-8')) for c in captures)
            if len(captures) >= MAX_CAPTURES or history_bytes + len(text.encode('utf-8')) > MAX_CAPTURE_BYTES:
                prior.update(error='Capture history full; clear saved snapshots for a source to continue', checked_at=now)
                doc['observations'][source_id] = prior
                self._write(doc)
                return None
            if prior.get('digest') and len(doc['pending']) >= 100:
                prior.update(error='Analysis queue full; retry pending', checked_at=now)
                doc['observations'][source_id] = prior
                self._write(doc)
                return None
            changes = ''
            if prior.get('digest') and isinstance(prior.get('text'), str):
                changes = '\n'.join(difflib.unified_diff(prior['text'].splitlines(), text.splitlines(),
                                                         fromfile='previous', tofile='current', n=1))
                if len(changes) > 30000:
                    prior.update(error='Change too large to analyze; review source manually', checked_at=now)
                    doc['observations'][source_id] = prior
                    self._write(doc)
                    return None
            capture = {'id': uuid4().hex, 'source_id': source_id, 'url': url, 'title': title,
                       'captured_at': now, 'sha256': digest, 'text': text}
            captures.append(capture)
            doc['observations'][source_id] = {'digest': digest, 'text': text,
                                               'checked_at': now, 'last_success_at': now, 'baseline_ready': True}
            query_id = None
            if changes:
                query_id = uuid4().hex
                doc['pending'][query_id] = {'source_id': source_id, 'source_name': source['name'],
                    'url': url, 'title': title, 'text': text, 'changes': changes,
                    'keywords': source['keywords'], 'alert_role': source['alert_role'],
                    'analysis_mode': self.PROFILE, 'created': now, 'last_sent': 0, 'oracle_uid': ''}
            self._write(doc)
            return query_id

    def capture_chunk(self, capture_id, offset):
        if not isinstance(capture_id, str) or type(offset) is not int or offset < 0:
            raise ValueError('Invalid capture request')
        with self.lock:
            item = next((c for c in self.doc.get('captures', []) if c['id'] == capture_id), None)
            if not item or offset > len(item['text']):
                raise ValueError('Capture not found')
            chunk = item['text'][offset:offset + 1500]
            next_offset = offset + len(chunk)
            return {'capture_id': capture_id, 'offset': offset, 'next_offset': next_offset,
                    'chunk': chunk, 'done': next_offset >= len(item['text']),
                    'captured_at': item['captured_at'], 'url': item['url'], 'sha256': item['sha256']}

    def clear_history(self, source_id):
        with self.lock:
            if not any(s['id'] == source_id for s in self.doc['sources']) and not any(
                    c['source_id'] == source_id for c in self.doc.get('captures', [])):
                raise ValueError('Source not found')
            doc = deepcopy(self.doc)
            doc['captures'] = [c for c in doc.get('captures', []) if c['source_id'] != source_id]
            self._write(doc)

    def complete_analysis(self, query_id, oracle_uid, result):
        with self.lock:
            pending = self.doc['pending'].get(query_id)
            if (not pending or not oracle_uid or pending['oracle_uid'] != oracle_uid
                    or not isinstance(result, dict) or type(result.get('match')) is not bool):
                return False
            doc = deepcopy(self.doc)
            item = doc['pending'].pop(query_id)
            if result['match']:
                before = [line[1:].strip() for line in item['changes'].splitlines()
                          if line.startswith('-') and not line.startswith('---')]
                after = [line[1:].strip() for line in item['changes'].splitlines()
                         if line.startswith('+') and not line.startswith('+++')]
                summary = result.get('summary')
                summary = summary[:500] if isinstance(summary, str) else ''
                if before:
                    summary += '\nBefore: ' + ' '.join(before)[:200]
                if after:
                    summary += '\nAfter: ' + ' '.join(after)[:200]
                effective = result.get('effective_date') if self.PROFILE == 'fortune' else ''
                effective = effective[:100] if isinstance(effective, str) else ''
                if effective:
                    summary += '\nReported effective date (verify source): ' + effective
                doc['events'].insert(0, {'id': query_id, 'source': item['source_name'],
                    'url': item['url'], 'title': item['title'], 'summary': summary,
                    'effective_date': effective, 'created': time.time(), 'alert_role': item['alert_role'],
                    'queued': [], 'targets': None})
                doc['events'] = doc['events'][:500]
            self._write(doc)
            return True


class PromiseEngine(WatchEngine):
    PROFILE = 'promise'


class FortuneEngine(WatchEngine):
    PROFILE = 'fortune'
