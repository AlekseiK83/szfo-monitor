"""Осторожный резервный парсер ссылок Росбалта (только второй поток).

Не используется скрытый API, обход ограничений сайта или внешние прокси.
Выбираются только публичные ссылки на статьи со страниц самого Росбалта.
Если ссылки в HTML отсутствуют, источник честно считается недоступным.
"""
from datetime import date, timedelta
from html import unescape
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit

ROSBALT_ARTICLE = re.compile(
    r'(?:https?://(?:www\.)?rosbalt\.ru)?/news/(?P<date>20\d{2}-\d{2}-\d{2})/[a-z0-9_-]+-\d+', re.I)


class _ArticleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.jsonld = []
        self._in_script = False
        self._in_h1 = False
        self.h1 = []
        self.script = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta':
            key = (a.get('property') or a.get('name') or '').lower()
            if key and a.get('content'):
                self.meta.setdefault(key, a['content'].strip())
        if tag == 'script' and a.get('type', '').lower() == 'application/ld+json':
            self._in_script = True
            self.script = []
        if tag == 'h1':
            self._in_h1 = True

    def handle_data(self, data):
        if self._in_script:
            self.script.append(data)
        if self._in_h1:
            self.h1.append(data)

    def handle_endtag(self, tag):
        if tag == 'h1':
            self._in_h1 = False
        if tag == 'script' and self._in_script:
            self._in_script = False
            try:
                self.jsonld.append(json.loads(''.join(self.script)))
            except (ValueError, TypeError):
                pass


def _iter_ld(obj):
    if isinstance(obj, list):
        for entry in obj:
            yield from _iter_ld(entry)
    elif isinstance(obj, dict):
        yield obj
        if '@graph' in obj:
            yield from _iter_ld(obj['@graph'])


def article_metadata(page_html, url):
    """Возвращает газетную карточку или None, если нет заголовка статьи."""
    p = _ArticleHTML()
    p.feed(page_html)
    title = p.meta.get('og:title') or p.meta.get('twitter:title')
    summary = p.meta.get('og:description') or p.meta.get('description') or ''
    pub_date = p.meta.get('article:published_time') or p.meta.get('datepublished') or ''
    for item in _iter_ld(p.jsonld):
        typ = item.get('@type', '')
        if isinstance(typ, list):
            typ = ' '.join(typ)
        if 'article' in str(typ).lower() or 'news' in str(typ).lower():
            title = title or item.get('headline') or item.get('name')
            summary = summary or item.get('description', '')
            pub_date = pub_date or item.get('datePublished', '')
    title = title or ' '.join(p.h1).strip()
    if not isinstance(title, str) or not title.strip():
        return None
    title = re.sub(r'\s*[-—|]\s*Росбалт\s*$', '', unescape(title).strip(), flags=re.I)
    if not title or len(title) < 15:
        return None
    if not pub_date:
        m = ROSBALT_ARTICLE.search(url)
        if m:
            pub_date = m.group('date')
    return {'title': title[:300], 'summary': unescape(str(summary))[:800],
            'link': url, 'date': pub_date}


def listing_links(page_html, base_url, today=None, days=4, limit=22):
    """Публичные ссылки на реальные статьи в HTML/JSON страницы.

    Не пытается создать заголовки из URL. Устаревшие ссылки игнорируются.
    """
    s = unescape(page_html).replace('\\/', '/').replace('\\u002F', '/')
    urls = []
    seen = set()
    lower = (today - timedelta(days=days)) if today else None
    for m in ROSBALT_ARTICLE.finditer(s):
        if lower:
            try:
                d = date.fromisoformat(m.group('date'))
            except ValueError:
                continue
            if not lower <= d <= today:
                continue
        raw = m.group(0)
        url = urljoin(base_url, raw)
        if urlsplit(url).hostname not in {'www.rosbalt.ru', 'rosbalt.ru'}:
            continue
        url = url.split('?', 1)[0]
        if url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= 500:
            break
    # В sitemap порядок может быть произвольным. Берём самые новые даты URL.
    urls.sort(key=lambda u: (ROSBALT_ARTICLE.search(u).group('date')
                              if ROSBALT_ARTICLE.search(u) else ''), reverse=True)
    return urls[:limit]


def fetch_rosbalt_fallback(src, get_text, today=None, max_articles=16):
    """Пробует /news и главную страницу, затем метаданные найденных статей.

    status содержит причину, когда не удалось получить ни одной карточки.
    """
    home = src.get('url', 'https://www.rosbalt.ru/')
    pages = [src.get('news_url', 'https://www.rosbalt.ru/news'), home]
    links, errors = [], []
    page_stats = []  # только размеры/количество ссылок, НЕ полный ответ сайта
    seen = set()
    for url in dict.fromkeys(pages):
        try:
            page = get_text(url)
            found = listing_links(page, url, today=today, limit=24)
            page_stats.append(f'{urlsplit(url).path or "/"}:len={len(page)},links={len(found)}')
            for item in found:
                if item not in seen:
                    seen.add(item)
                    links.append(item)
        except Exception as exc:  # не скрываем ошибку, но позволяем пробовать второй адрес
            errors.append(type(exc).__name__)
    if not links:
        # Публичная карта сайта — ещё один независимый способ найти URL,
        # когда HTML-вёрстка новостной ленты собирается JavaScript-ом.
        # Не предполагаем, что sitemap существует: ошибка отражается в статусе.
        for path in ('/sitemap.xml', '/sitemap-news.xml'):
            try:
                candidate = urljoin(home, path)
                xml = get_text(candidate)
                for item in listing_links(xml, candidate, today=today, limit=24):
                    if item not in seen:
                        seen.add(item)
                        links.append(item)
                if links:
                    break
            except Exception as exc:
                errors.append(type(exc).__name__)
    if not links:
        detail = ','.join(errors[:4]) if errors else 'no_article_links'
        sizes = ';'.join(page_stats)[:130]
        return [], 'error: rosbalt_no_articles: ' + detail + ('; page_stats=' + sizes if sizes else '')
    items = []
    for url in links[:max_articles]:
        try:
            item = article_metadata(get_text(url), url)
            if item:
                items.append(item)
        except Exception as exc:
            errors.append(type(exc).__name__)
    if not items:
        return [], f'error: rosbalt_no_article_metadata: links={len(links)}'
    return items, f'rosbalt articles {len(items)} (links={len(links)}, errors={len(errors)})'

# Публичный RSS-поиск Google News — запасной способ обнаружить публикации,
# когда сайт не отдаёт HTML-ссылки GitHub Actions. Это не API Росбалта:
# статус источника должен явно фиксировать переход к агрегатору.
ROSBALT_GOOGLE_RSS = (
    'https://news.google.com/rss/search?'
    'q=site%3Arosbalt.ru%2Fnews+when%3A4d&hl=ru&gl=RU&ceid=RU%3Aru'
)


def google_news_rosbalt(xml_text, today=None, max_items=20):
    """Взять только записи, где Google RSS указывает издателя Росбалт.

    Не считаем все результаты запроса принадлежащими Росбалту. Сохраняем
    Google URL как промежуточную ссылку, не выдавая её за прямой адрес статьи.
    """
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    try:
        root = ET.fromstring(xml_text.encode('utf-8') if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        return []
    out = []
    for entry in root.iter('item'):
        publisher = (entry.findtext('source') or '').strip().lower().replace('ё', 'е')
        publisher_url = (entry.find('source').get('url', '')
                         if entry.find('source') is not None else '')
        if 'росбалт' not in publisher and 'rosbalt.ru' not in publisher_url:
            continue
        title = (entry.findtext('title') or '').strip()
        title = re.sub(r'\s+[-—]\s+(?:Росбалт|ИА Росбалт)\s*$', '', title, flags=re.I)
        url = (entry.findtext('link') or '').strip()
        pub_date = (entry.findtext('pubDate') or '').strip()
        if len(title) < 20 or not ('news.google.com' in url or ROSBALT_ARTICLE.search(url)):
            continue
        if today and pub_date:
            try:
                published = parsedate_to_datetime(pub_date).date()
                if not today - timedelta(days=4) <= published <= today:
                    continue
            except (ValueError, TypeError, OverflowError):
                pass
        out.append({'title': title[:300], 'summary': '',
                    'link': url, 'date': pub_date})
        if len(out) >= max_items:
            break
    return out
