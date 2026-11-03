"""Bounded, sender-scoped assembly of fragmented Oracle prompts."""
import base64
import json
import re
import threading
import time

MAX_FRAGMENT_CHARS = 16000
MAX_ASSEMBLIES = 8
MAX_ASSEMBLED_BYTES = 4_000_000
MAX_FRAGMENTS = 512
TTL = 300
COMPLETED_TTL = 90


class PromptAssembly:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = {}
        self.completed = {}

    def accept(self, sender, content):
        if not isinstance(sender, str) or not sender or not isinstance(content, dict):
            raise ValueError('Invalid fragment sender')
        query = content.get('query_id')
        index, count = content.get('index'), content.get('count')
        data = content.get('fragment')
        if (not isinstance(query, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', query)
                or type(index) is not int or type(count) is not int or not 1 <= count <= MAX_FRAGMENTS
                or not 0 <= index < count or not isinstance(data, str) or len(data) > MAX_FRAGMENT_CHARS):
            raise ValueError('Invalid fragment')
        try:
            chunk = base64.b64decode(data, validate=True)
        except (ValueError, TypeError):
            raise ValueError('Invalid fragment encoding') from None
        key = (sender, query)
        now = time.monotonic()
        with self.lock:
            self.pending = {k: v for k, v in self.pending.items() if now - v['time'] < TTL}
            self.completed = {k: t for k, t in self.completed.items() if now - t < COMPLETED_TTL}
            if key in self.completed:
                return None
            if key not in self.pending:
                if len(self.pending) >= MAX_ASSEMBLIES:
                    raise ValueError('Too many incomplete prompts')
                self.pending[key] = {'time': now, 'count': count, 'parts': {}, 'size': 0}
            item = self.pending[key]
            if item['count'] != count or (index in item['parts'] and item['parts'][index] != chunk):
                self.pending.pop(key, None)
                raise ValueError('Conflicting fragments')
            if index not in item['parts']:
                item['parts'][index] = chunk
                item['size'] += len(chunk)
            if item['size'] > MAX_ASSEMBLED_BYTES:
                self.pending.pop(key, None)
                raise ValueError('Fragmented prompt too large')
            if len(item['parts']) != count:
                return None
            raw = b''.join(item['parts'][i] for i in range(count))
            self.pending.pop(key, None)
            try:
                request = json.loads(raw.decode('utf-8'))
            except (ValueError, UnicodeError):
                raise ValueError('Invalid assembled prompt') from None
            if (not isinstance(request, dict) or request.get('query_id') != query
                    or request.get('target_universal_id') != sender or request.get('use_callback')):
                raise ValueError('Fragmented prompt identity mismatch')
            self.completed[key] = now
            return request
