"""Bounded HTTPS collection and feed parsing for LifeSignal."""
import ipaddress
import re
import socket
import threading
import time
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit
import xml.etree.ElementTree as ET

import requests

USER_AGENT = "MatrixSwarm-LifeSignal/1.0 (+https://matrixswarm.com)"
MAX_BYTES = 2_000_000
MAX_TEXT = 150_000
MIN_REQUEST_SPACING = 5
_rate_lock = threading.Lock()
_next_request = {}


class SourceError(Exception):
    pass


class Challenge(SourceError):
    pass


class RateLimited(SourceError):
    def __init__(self, retry_after):
        super().__init__('Rate limited; retry delayed')
        self.retry_after = retry_after


def retry_seconds(value):
    try:
        return max(60, int(value))
    except (ValueError, TypeError):
        try:
            return max(60, int(parsedate_to_datetime(value).timestamp() - time.time()))
        except (TypeError, ValueError, OverflowError):
            return 3600


def public_host(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise SourceError('Only public HTTPS sources on port 443 are supported')
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise SourceError('Source hostname must resolve to public addresses')
    except (OSError, ValueError):
        raise SourceError('Source DNS lookup failed') from None
    return parsed.hostname.lower()


def challenge(status, body):
    sample = body[:30000].lower()
    return (status in (401, 403) or b'cf-chl-' in sample or b'g-recaptcha' in sample
            or b'hcaptcha' in sample or b'captcha-delivery' in sample
            or b'please verify you are human' in sample)


def get(url, check_robots=True):
    public_host(url)
    session = requests.Session()
    session.trust_env = False
    session.headers.update({'User-Agent': USER_AGENT})
    try:
        if check_robots:
            parsed = urlsplit(url)
            robots_url = f'https://{parsed.netloc}/robots.txt'
            robots_body = _read(session, robots_url, 300_000, allow_missing=True)
            if not robots_allowed(robots_body.decode('utf-8-sig', 'replace'), url):
                raise SourceError('robots.txt disallows automated access')
        return _read(session, url, MAX_BYTES)
    finally:
        session.close()


def robots_allowed(robots, url):
    """Apply matching user-agent groups and wildcard allow/disallow paths."""
    groups, agents, rules = [], [], []
    for line in robots.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line or ':' not in line:
            continue
        field, value = (part.strip() for part in line.split(':', 1))
        field = field.lower()
        if field == 'user-agent':
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif field in ('allow', 'disallow') and agents and value:
            rules.append((field == 'allow', value))
    if agents:
        groups.append((agents, rules))
    applicable = []
    product = USER_AGENT.split('/', 1)[0].lower()
    for agents, rules in groups:
        matches = [len(agent) if agent != '*' else 0 for agent in agents
                   if agent == '*' or agent and agent in product]
        if matches:
            applicable.append((max(matches), rules))
    if not applicable:
        return True
    best_group = max(group[0] for group in applicable)
    parsed = urlsplit(url)
    path = unquote(parsed.path or '/') + (('?' + unquote(parsed.query)) if parsed.query else '')
    matching = []
    for specificity, rules in applicable:
        if specificity != best_group:
            continue
        for allow, rule in rules:
            rule = unquote(rule)
            anchored = rule.endswith('$')
            if anchored:
                rule = rule[:-1]
            pattern = '^' + '.*'.join(re.escape(part) for part in rule.split('*'))
            if anchored:
                pattern += '$'
            if re.search(pattern, path):
                matching.append((len(rule.replace('*', '')), allow))
    return max(matching)[1] if matching else True


def _read(session, url, limit, allow_missing=False):
    host = urlsplit(url).hostname
    with _rate_lock:
        delay = _next_request.get(host, 0) - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        _next_request[host] = time.monotonic() + MIN_REQUEST_SPACING
    with session.get(url, stream=True, allow_redirects=False, timeout=(10, 20)) as response:
        if response.status_code in (401, 403):
            raise Challenge('CAPTCHA or access challenge detected')
        if response.status_code == 429:
            raise RateLimited(retry_seconds(response.headers.get('Retry-After')))
        if allow_missing and response.status_code in (404, 410):
            return b''
        if response.status_code != 200:
            raise SourceError(f'Source returned HTTP {response.status_code}; redirects are not followed')
        chunks, size = [], 0
        prefix = b''
        for chunk in response.iter_content(16384):
            if len(prefix) < 30000:
                prefix = (prefix + chunk)[:30000]
                if challenge(response.status_code, prefix):
                    raise Challenge('CAPTCHA or access challenge detected')
            size += len(chunk)
            if size > limit:
                raise SourceError('Source exceeds the maximum size')
            chunks.append(chunk)
        return b''.join(chunks)


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title = [], []
        self.suppressed = 0
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.suppressed += 1
        elif tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg') and self.suppressed:
            self.suppressed -= 1
        elif tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if not self.suppressed and data.strip():
            self.parts.append(data.strip())
            if self.in_title:
                self.title.append(data.strip())


def page_text(body):
    parser = TextExtractor()
    parser.feed(body.decode('utf-8', 'replace'))
    title = ' '.join(parser.title)
    text = '\n'.join(parser.parts)
    if len(text) > MAX_TEXT:
        raise SourceError('Page text exceeds Oracle input limit; no partial page was sent')
    if not text:
        raise SourceError('Source page has no readable text')
    return title[:300], text


def feed_entries(body, base_url):
    # The standard parser does not resolve external entities; reject DTDs outright.
    if b'<!doctype' in body.lower() or b'<!entity' in body.lower():
        raise SourceError('Feed contains unsupported XML declarations')
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise SourceError('Invalid RSS/Atom feed') from None
    entries = []
    for item in root.findall('.//item') + root.findall('.//{http://www.w3.org/2005/Atom}entry'):
        def text_of(*tags):
            for tag in tags:
                element = item.find(tag)
                if element is not None:
                    return ''.join(element.itertext()).strip()
            return ''
        title = text_of('title', '{http://www.w3.org/2005/Atom}title')
        link = text_of('link')
        atom_link = item.find('{http://www.w3.org/2005/Atom}link')
        if not link and atom_link is not None:
            link = atom_link.get('href', '')
        link = urljoin(base_url, link) if link else base_url
        if urlsplit(link).scheme != 'https':
            link = base_url
        ident = text_of('guid', '{http://www.w3.org/2005/Atom}id') or link or title
        body_text = text_of('description', '{http://www.w3.org/2005/Atom}content',
                            '{http://www.w3.org/2005/Atom}summary')
        parser = TextExtractor()
        parser.feed(body_text)
        cleaned = ' '.join(parser.parts)
        content = f'{title}\n{cleaned}'
        if len(content) <= MAX_TEXT and ident:
            entries.append({'id': ident[:2048], 'url': link[:2048], 'title': title[:300], 'text': content})
    return entries[:100]
