"""Durable LifeSignal configuration, observation and delivery state."""
from copy import deepcopy
import hashlib
import difflib
import re
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_SOURCES = 100


def normalize_source(raw):
    if not isinstance(raw, dict):
        raise ValueError("Source must be an object")
    ident = raw.get("id") or uuid4().hex
    if not isinstance(ident, str) or not ID.fullmatch(ident):
        raise ValueError("Invalid source ID")
    name = raw.get("name", "")
    url = raw.get("url", "")
    kind = raw.get("kind", "page")
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValueError("Enter a source name")
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError("Enter a valid HTTPS URL")
    if 'YOUR_SEARCH' in url:
        raise ValueError("Replace YOUR_SEARCH in the source URL with a search term")
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname and not parsed.username
                 and not parsed.password and parsed.port in (None, 443) and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Enter an HTTPS URL without credentials, a fragment, or a custom port")
    if kind not in ("page", "rss", "wikipedia"):
        raise ValueError("Choose webpage, RSS/Atom, or Wikipedia")
    mode = raw.get('analysis_mode', 'changes')
    if mode not in ('changes', 'captcha') or (mode == 'captcha' and kind != 'page'):
        raise ValueError('CAPTCHA monitoring requires a webpage source')
    if kind == "wikipedia" and (parsed.hostname != "en.wikipedia.org" or not parsed.path.startswith("/wiki/") or len(parsed.path) <= 6):
        raise ValueError("Wikipedia sources must be English Wikipedia article URLs")
    keywords = raw.get("keywords", [])
    if (not isinstance(keywords, list) or (mode != 'captcha' and not keywords) or len(keywords) > 40
            or any(not isinstance(k, str) or not k.strip() or len(k) > 100 for k in keywords)):
        raise ValueError("Enter at least one keyword (one per line)")
    try:
        interval = int(raw.get("interval_sec", 3600))
    except (ValueError, TypeError):
        raise ValueError("Invalid interval") from None
    if not 120 <= interval <= 86400:
        raise ValueError("Interval must be between 120 and 86400 seconds")
    role = raw.get("alert_role", "hive.alert")
    if not isinstance(role, str) or not role.strip() or len(role) > 128 or "@" in role:
        raise ValueError("Enter a valid alert service role")
    enabled = raw.get("enabled", True)
    if type(enabled) is not bool:
        raise ValueError("Invalid enabled setting")
    return {"id": ident, "name": name.strip(), "url": url, "kind": kind, "analysis_mode": mode,
            "keywords": [k.strip() for k in keywords], "interval_sec": interval,
            "alert_role": role.strip(), "enabled": enabled}


class LifeSignalEngine:
    def __init__(self, persist, saved=None):
        self.persist = persist
        self.lock = threading.RLock()
        self.doc = deepcopy(saved) if saved is not None else {
            "version": 1, "revision": 0, "sources": [], "blocked_hosts": {}, "host_retry_until": {},
            "observations": {}, "pending": {}, "events": [], "death_keys": [], "wiki_dirty": {}, "stream_cursor": ""}
        if self.doc.get("version") != 1:
            raise ValueError("Invalid LifeSignal state")
        if saved is None:
            self.persist(deepcopy(self.doc))

    def _write(self, doc):
        self.persist(deepcopy(doc))
        self.doc = doc

    @staticmethod
    def _pending_host(doc, item):
        source = next((s for s in doc['sources'] if s['id'] == item['source_id']), None)
        return urlsplit(source['url'] if source else item['url']).hostname

    def snapshot(self):
        with self.lock:
            result = deepcopy({k: self.doc[k] for k in
                ("revision", "sources", "blocked_hosts", "observations", "events")})
            for observation in result['observations'].values():
                observation['baseline_ready'] = bool(observation.get('digest')) or 'seen' in observation
                # Older saved observations have no separate successful-check field.
                if observation['baseline_ready'] and 'last_success_at' not in observation and not observation.get('error'):
                    observation['last_success_at'] = observation.get('checked_at')
                observation.pop('text', None)
                observation.pop('seen', None)
            result['analysis_errors'] = {qid: {'source_id': item['source_id'], 'error': item['error']}
                for qid, item in self.doc['pending'].items() if item.get('error')}
            result['pending_counts'] = {}
            for item in self.doc['pending'].values():
                ident = item['source_id']
                result['pending_counts'][ident] = result['pending_counts'].get(ident, 0) + 1
            result['wiki_dirty'] = deepcopy(self.doc.get('wiki_dirty', {}))
            result['host_retry_until'] = deepcopy(self.doc.get('host_retry_until', {}))
            return result

    def replace(self, sources, revision):
        if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
            raise ValueError("Too many sources")
        sources = [normalize_source(s) for s in sources]
        if len({s['id'] for s in sources}) != len(sources):
            raise ValueError("Duplicate source ID")
        with self.lock:
            if revision != self.doc["revision"]:
                raise ValueError("Configuration changed; reload and try again")
            doc = deepcopy(self.doc)
            old = {s['id']: s for s in doc['sources']}
            current = {s['id']: s for s in sources}
            def same_except_interval(ident):
                previous, updated = old.get(ident), current.get(ident)
                if not previous or not updated:
                    return False
                previous = dict(previous, analysis_mode=previous.get('analysis_mode', 'changes'))
                return all(previous.get(key) == updated.get(key) for key in previous if key != 'interval_sec')

            doc['pending'] = {qid: item for qid, item in doc['pending'].items()
                              if item['source_id'] in current and current[item['source_id']].get('enabled')
                              and same_except_interval(item['source_id'])}
            for source in sources:
                previous = old.get(source['id'])
                if previous and (previous['url'], previous['kind'], previous.get('analysis_mode', 'changes')) != (
                        source['url'], source['kind'], source['analysis_mode']):
                    doc['observations'].pop(source['id'], None)
            doc['sources'] = sources
            doc['wiki_dirty'] = {ident: value for ident, value in doc.get('wiki_dirty', {}).items()
                                 if ident in current and current[ident]['enabled'] and same_except_interval(ident)}
            doc['revision'] += 1
            self._write(doc)
            return self.snapshot()

    def panel_snapshot(self):
        result = self.snapshot()
        result['events'] = result['events'][:10]
        result.pop('wiki_dirty', None)
        result.pop('host_retry_until', None)
        return result

    def pause_host(self, host, reason):
        with self.lock:
            doc = deepcopy(self.doc)
            doc['blocked_hosts'][host.lower()] = {"reason": reason, "time": time.time()}
            doc['pending'] = {query: item for query, item in doc['pending'].items()
                              if self._pending_host(doc, item) != host.lower()}
            self._write(doc)

    def report_challenge(self, source, reason):
        """Persist a stop for a recognized access challenge."""
        host = urlsplit(source['url']).hostname.lower()
        with self.lock:
            if host in self.doc['blocked_hosts']:
                return
            doc = deepcopy(self.doc)
            doc['blocked_hosts'][host] = {'reason': reason, 'time': time.time()}
            doc['pending'] = {query: item for query, item in doc['pending'].items()
                              if self._pending_host(doc, item) != host}
            self._write(doc)

    def record_error(self, source_id, error, retry_at=None):
        with self.lock:
            doc = deepcopy(self.doc)
            observation = doc['observations'].setdefault(source_id, {})
            observation.update(error=error[:200], checked_at=time.time())
            if retry_at is not None:
                observation['retry_at'] = retry_at
            self._write(doc)

    def defer_host(self, host, retry_at):
        with self.lock:
            doc = deepcopy(self.doc)
            hosts = doc.setdefault('host_retry_until', {})
            hosts[host] = max(hosts.get(host, 0), retry_at)
            self._write(doc)

    def resume_host(self, host):
        with self.lock:
            if host not in self.doc['blocked_hosts']:
                raise ValueError("Source is not paused")
            doc = deepcopy(self.doc)
            del doc['blocked_hosts'][host]
            self._write(doc)

    def record_observation(self, source_id, text, url, title, now=None):
        """Baseline silently; queue changed content once for Oracle analysis."""
        now = now or time.time()
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        with self.lock:
            source = next((s for s in self.doc['sources'] if s['id'] == source_id), None)
            if not source or source['url'] != url or not source['enabled'] or urlsplit(source['url']).hostname in self.doc['blocked_hosts']:
                return None
            doc = deepcopy(self.doc)
            prior = doc['observations'].get(source_id, {})
            if prior.get('digest') and prior['digest'] != digest and len(doc['pending']) >= 100:
                prior.update(error='Analysis queue full; retry pending', checked_at=now)
                doc['observations'][source_id] = prior
                self._write(doc)
                return None
            changes = ''
            if prior.get('digest') and prior['digest'] != digest and isinstance(prior.get('text'), str):
                changes = '\n'.join(difflib.unified_diff(prior['text'].splitlines(), text.splitlines(),
                                                         fromfile='previous', tofile='current', n=1))
                if len(changes) > 30000:
                    prior.update(error='Change too large to analyze; review source manually', checked_at=now)
                    doc['observations'][source_id] = prior
                    self._write(doc)
                    return None
            doc['observations'][source_id] = {"digest": digest, "text": text, "checked_at": now, "last_success_at": now}
            if changes and len(doc['pending']) < 100:
                query_id = uuid4().hex
                doc['pending'][query_id] = {"source_id": source_id, "source_name": source['name'],
                    "url": url, "title": title, "text": text, "changes": changes, "keywords": source['keywords'],
                    "alert_role": source['alert_role'], "created": now, "last_sent": 0,
                    "oracle_uid": ""}
            else:
                query_id = None
            self._write(doc)
            return query_id

    def record_feed(self, source_id, entries, now=None, expected_url=None):
        """Remember existing entries on first read and analyze newly appearing entries."""
        now = now or time.time()
        with self.lock:
            source = next((s for s in self.doc['sources'] if s['id'] == source_id), None)
            if (not source or (expected_url is not None and source['url'] != expected_url)
                    or not source['enabled'] or urlsplit(source['url']).hostname in self.doc['blocked_hosts']):
                return
            doc = deepcopy(self.doc)
            prior = doc['observations'].get(source_id, {})
            seen = prior.get('seen', [])
            existing = set(seen)
            for entry in reversed(entries[:100]):
                key = hashlib.sha256(entry['id'].encode('utf-8')).hexdigest()
                if key not in existing:
                    if 'seen' in prior and len(doc['pending']) >= 100:
                        break
                    if 'seen' in prior and len(doc['pending']) < 100:
                        query_id = uuid4().hex
                        doc['pending'][query_id] = {"source_id": source_id, "source_name": source['name'],
                            "url": entry['url'], "title": entry['title'], "text": entry['text'], "changes": '',
                            "keywords": source['keywords'], "alert_role": source['alert_role'],
                            "created": now, "last_sent": 0, "oracle_uid": ""}
                    seen.append(key)
                    existing.add(key)
            doc['observations'][source_id] = {"seen": seen[-1000:], "checked_at": now, "last_success_at": now}
            self._write(doc)

    def record_captcha_check(self, source_id, text, url, title, now=None):
        """Queue one full-page Oracle challenge check, including the first read."""
        now = now or time.time()
        with self.lock:
            source = next((s for s in self.doc['sources'] if s['id'] == source_id), None)
            if (not source or source['url'] != url or not source['enabled']
                    or source.get('analysis_mode', 'changes') != 'captcha'
                    or urlsplit(url).hostname in self.doc['blocked_hosts']):
                return None
            doc = deepcopy(self.doc)
            prior = doc['observations'].get(source_id, {})
            observation = {"digest": hashlib.sha256(text.encode('utf-8')).hexdigest(),
                           "text": text, "checked_at": now, "last_success_at": now}
            for key in ('captcha_status', 'captcha_checked_at', 'captcha_summary'):
                if key in prior:
                    observation[key] = prior[key]
            doc['observations'][source_id] = observation
            pending = any(item['source_id'] == source_id for item in doc['pending'].values())
            query_id = None
            if not pending and len(doc['pending']) < 100:
                query_id = uuid4().hex
                doc['pending'][query_id] = {'source_id': source_id, 'source_name': source['name'],
                    'url': url, 'title': title, 'text': text, 'changes': '',
                    'keywords': source['keywords'], 'alert_role': source['alert_role'],
                    'analysis_mode': 'captcha', 'created': now, 'last_sent': 0, 'oracle_uid': ''}
            elif not pending:
                observation['error'] = 'Analysis queue full; retry pending'
            self._write(doc)
            return query_id

    def queue(self):
        with self.lock:
            return deepcopy(self.doc['pending'])

    def stream_cursor(self):
        with self.lock:
            return self.doc.get('stream_cursor', '')

    def mark_wiki_dirty(self, source_id):
        with self.lock:
            doc = deepcopy(self.doc)
            dirty = doc.setdefault('wiki_dirty', {})
            dirty[source_id] = uuid4().hex
            self._write(doc)

    def clear_wiki_dirty(self, source_id, observed_version):
        with self.lock:
            if not observed_version or self.doc.get('wiki_dirty', {}).get(source_id) != observed_version:
                return
            doc = deepcopy(self.doc)
            doc['wiki_dirty'].pop(source_id, None)
            self._write(doc)

    def set_stream_cursor(self, cursor):
        if not isinstance(cursor, str) or len(cursor) > 512 or '\n' in cursor or '\r' in cursor:
            return
        with self.lock:
            doc = deepcopy(self.doc)
            doc['stream_cursor'] = cursor
            self._write(doc)

    def analysis_error(self, query_id, oracle_uid, message):
        with self.lock:
            pending = self.doc['pending'].get(query_id)
            if not pending or pending['oracle_uid'] != oracle_uid:
                return
            doc = deepcopy(self.doc)
            doc['pending'][query_id]['error'] = message[:200]
            observation = doc['observations'].setdefault(pending['source_id'], {})
            observation['error'] = message[:200]
            self._write(doc)

    def retry_analysis(self, source_id):
        with self.lock:
            doc = deepcopy(self.doc)
            count = 0
            for item in doc['pending'].values():
                if item['source_id'] == source_id and item.get('error'):
                    item.pop('error', None)
                    item['last_sent'] = 0
                    item['attempts'] = 0
                    count += 1
            if not count:
                raise ValueError('No failed analyses for this source')
            doc['observations'].get(source_id, {}).pop('error', None)
            self._write(doc)

    def mark_sent(self, query_id, oracle_uid, now=None):
        with self.lock:
            if query_id not in self.doc['pending']:
                return
            doc = deepcopy(self.doc)
            item = doc['pending'][query_id]
            item.update(last_sent=now or time.time(), oracle_uid=oracle_uid,
                        attempts=item.get('attempts', 0) + 1)
            self._write(doc)

    def complete_analysis(self, query_id, oracle_uid, result):
        with self.lock:
            pending = self.doc['pending'].get(query_id)
            if not pending or not oracle_uid or pending['oracle_uid'] != oracle_uid:
                return False
            if not isinstance(result, dict):
                return False
            is_captcha = pending.get('analysis_mode') == 'captcha'
            if is_captcha and result.get('captcha') not in ('yes', 'no', 'uncertain'):
                return False
            if not is_captcha and type(result.get('match')) is not bool:
                return False
            doc = deepcopy(self.doc)
            item = doc['pending'].pop(query_id)
            if is_captcha:
                status = result['captcha']
                observation = doc['observations'].setdefault(item['source_id'], {})
                observation.update(captcha_status=status, captcha_checked_at=time.time(),
                    captcha_summary=str(result.get('summary', ''))[:500])
                if status == 'yes':
                    host = urlsplit(item['url']).hostname.lower()
                    if host not in doc['blocked_hosts']:
                        reason = 'Oracle reported an access challenge; operator review required'
                        doc['blocked_hosts'][host] = {'reason': reason, 'time': time.time()}
                        doc['pending'] = {query: queued for query, queued in doc['pending'].items()
                                          if self._pending_host(doc, queued) != host}
                self._write(doc)
                return True
            if result['match']:
                person = str(result.get('person', '')).strip().casefold()
                event_type = str(result.get('event_type', '')).strip().casefold()
                identity = re.sub(r'\s+', ' ', person) + '|death' if person and event_type == 'death' else ''
                deaths = doc.setdefault('death_keys', [])
                if identity and (identity in deaths or any(event.get('identity') == identity for event in doc['events'])):
                    self._write(doc)
                    return True
                if identity:
                    deaths.append(identity)
                    doc['death_keys'] = deaths[-10000:]
                doc['events'].insert(0, {"id": query_id, "source": item['source_name'],
                    "url": item['url'], "title": item['title'], "summary": str(result.get('summary', ''))[:500],
                    "identity": identity, "created": time.time(), "alert_role": item['alert_role'], "queued": [], "targets": None})
                doc['events'] = doc['events'][:500]
            self._write(doc)
            return True

    def update_event(self, event):
        with self.lock:
            doc = deepcopy(self.doc)
            for i, item in enumerate(doc['events']):
                if item['id'] == event['id']:
                    doc['events'][i] = deepcopy(event)
                    self._write(doc)
                    return
