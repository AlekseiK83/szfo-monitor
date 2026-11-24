"""Прозрачная трассировка каждого полученного сообщения второго потока.

В формате сохранена обратная совместимость поля `links` (поиск по ссылке).
Поле `records` не склеивает разные источники или одноимённые URL и содержит
ровно одну запись на каждый полученный элемент. Не сохраняет полный текст
статей, заголовки ограничены 200 символами, query-параметры ссылок не пишутся.
"""
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACE_FILE = Path('data/news/last_run_trace.json')
TRACKING_PREFIXES = ('utm_', 'yclid', 'gclid', 'fbclid', 'ysclid', '_openstat')


def canonical_url(url):
    try:
        p = urlsplit((url or '').strip())
        if p.scheme.lower() not in ('http', 'https') or not p.hostname:
            return ''
        query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                           if not k.lower().startswith(TRACKING_PREFIXES)])
        return urlunsplit(('https', p.netloc.lower(), p.path.rstrip('/') or '/', query, ''))
    except ValueError:
        return ''


def url_key(url):
    clean = canonical_url(url)
    return hashlib.sha256(clean.encode('utf-8')).hexdigest()[:20] if clean else ''


class Trace:
    def __init__(self, run_date):
        self.date = str(run_date)
        self.links = {}
        self.sources = []
        self.records = []

    def start_item(self, url, source_id, title=''):
        """Зарегистрировать входную статью ещё до проверок и вернуть её индекс."""
        safe_url = canonical_url(url)
        safe_url = safe_url.split('?', 1)[0] if safe_url else ''
        idx = len(self.records)
        self.records.append({
            'source': source_id,
            'url': safe_url[:600],
            'url_hash': url_key(url),
            'title': str(title or '').strip()[:200],
            'status': 'received',
            'reason': ''
        })
        return idx

    def update(self, index, status, reason=''):
        record = self.records[index]
        record['status'] = status
        record['reason'] = reason
        if record['url_hash']:
            self.links[record['url_hash']] = {
                'source': record['source'], 'status': status, 'reason': reason
            }

    def record(self, url, source_id, status, reason=''):
        """Прежний интерфейс сохраняется для внешнего кода и тестов."""
        key = url_key(url)
        if key:
            self.links[key] = {'source': source_id, 'status': status, 'reason': reason}

    def source(self, source_id, status, count):
        self.sources.append({'id': source_id, 'status': status, 'items': count})

    def payload(self):
        return {'date': self.date, 'sources': self.sources, 'links': self.links,
                'records': self.records, 'record_count': len(self.records),
                'legend': {'old': 'старше окна свежести',
                           'not_detected': 'не распознано событие',
                           'relevance_rejected': 'не прошёл фильтр релевантности',
                           'region_rejected': 'нет подтверждённого региона',
                           'candidate': 'прошёл фильтры, до дедупликации',
                           'duplicate': 'уже существовало', 'new': 'новое событие',
                           'upgraded': 'замена источника без нового уведомления'}}

    def write(self, path=None):
        dst = Path(path) if path else TRACE_FILE
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(self.payload(), ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def lookup(url, path=None):
    src = Path(path) if path else TRACE_FILE
    if not src.exists():
        return {'found': False, 'reason': 'trace_missing'}
    data = json.loads(src.read_text(encoding='utf-8'))
    entry = data.get('links', {}).get(url_key(url))
    return {'found': bool(entry), 'run_date': data.get('date'),
            **(entry if entry else {'reason': 'not_seen_in_last_run'})}
