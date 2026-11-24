"""Offline tests. Network, GitHub and Telegram are not contacted."""
import json
import os
import re
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import news_monitor as nm
from news_diagnostics import Trace, lookup, url_key
from news_source_rosbalt import article_metadata, listing_links, fetch_rosbalt_fallback

ARTICLE = 'https://www.rosbalt.ru/news/2026-11-23/soglasovali-kvoty-dlya-lenoblasti-5739313'
HTML_ARTICLE = '''<html><head><meta property="og:title" content="В Ленобласти согласовали 18 620 разрешений для работников Севен — Росбалт">
<meta name="description" content="Для проекта в Усть-Луге согласовали 18 620 разрешений на 2027 год">
<meta property="article:published_time" content="2026-11-23T10:00:00+03:00"></head><body><h1>Заголовок</h1></body></html>'''
NEWS = '<a href="/news/2026-11-23/soglasovali-kvoty-dlya-lenoblasti-5739313">ссылка</a>'


class RosbaltFallbackTests(unittest.TestCase):
    def test_list_news_links_and_cut_old(self):
        page = NEWS + '<a href="/news/2026-10-17/old-story-1111111">старое</a>'
        links = listing_links(page, 'https://www.rosbalt.ru/news', date(2026, 11, 23))
        self.assertEqual(links, [ARTICLE])

    def test_json_escaped_link(self):
        raw = r'{"url":"https:\/\/www.rosbalt.ru\/news\/2026-11-23\/soglasovali-kvoty-dlya-lenoblasti-5739313"}'
        links = listing_links(raw, 'https://www.rosbalt.ru/news', date(2026, 11, 23))
        self.assertEqual(links, [ARTICLE])

    def test_read_article_metadata(self):
        result = article_metadata(HTML_ARTICLE, ARTICLE)
        self.assertIn('согласовали', result['title'])
        self.assertEqual(result['link'], ARTICLE)
        self.assertIn('2026-11-23', result['date'])

    def test_extract_from_jsonld_when_og_missing(self):
        text = '''<script type="application/ld+json">{"@type":"NewsArticle","headline":"В Мурманской области назначен новый министр","datePublished":"2026-11-23"}</script>'''
        self.assertEqual(article_metadata(text, ARTICLE)['title'], 'В Мурманской области назначен новый министр')

    def test_fallback_to_homepage_and_article(self):
        seen = []
        def fake_get(url):
            seen.append(url)
            if url.endswith('/news'):
                return '<html>Здесь заголовков нет</html>'
            if url.endswith('rosbalt.ru/'):
                return NEWS
            if url == ARTICLE:
                return HTML_ARTICLE
            raise ValueError(url)
        items, status = fetch_rosbalt_fallback({'id':'rosbalt','url':'https://www.rosbalt.ru/',
            'news_url':'https://www.rosbalt.ru/news'}, fake_get, today=date(2026,11,23))
        self.assertEqual(len(items),1)
        self.assertIn('rosbalt articles 1',status)
        self.assertIn(ARTICLE,seen)

    def test_sitemap_fallback_if_both_listing_pages_empty(self):
        def fake_get(url):
            if url.endswith('/sitemap.xml'):
                return '<urlset><url><loc>' + ARTICLE + '</loc></url></urlset>'
            if url == ARTICLE:
                return HTML_ARTICLE
            return '<html>empty</html>'
        items, status = fetch_rosbalt_fallback({'url':'https://www.rosbalt.ru/'},
                          fake_get, today=date(2026,11,23))
        self.assertEqual(len(items), 1)
        self.assertIn('rosbalt articles', status)

    def test_no_links_is_explicit_error(self):
        items, status = fetch_rosbalt_fallback({'url':'https://www.rosbalt.ru/'},
                           lambda _: '<html>Нет ссылок</html>', today=date(2026,11,23))
        self.assertEqual(items,[])
        self.assertIn('error: rosbalt_no_articles',status)

    def test_fetch_source_calls_fallback_when_generic_zero(self):
        with patch.object(nm, 'http_get', side_effect=lambda u: HTML_ARTICLE if u==ARTICLE else NEWS):
            got, status = nm.fetch_source({'type':'site','id':'rosbalt',
                'url':'https://www.rosbalt.ru/','news_url':'https://www.rosbalt.ru/news'}, {},
                today=date(2026,11,23))
        self.assertEqual(len(got),1)
        self.assertEqual(got[0]['link'],ARTICLE)


class TraceTests(unittest.TestCase):
    def test_utm_does_not_change_fingerprint(self):
        self.assertEqual(url_key(ARTICLE),url_key(ARTICLE+'?utm_source=telegram'))

    def test_trace_last_run_lookup(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'trace.json'
            trace=Trace('2026-11-23')
            trace.source('rosbalt','error: sample',0)
            trace.record(ARTICLE,'rosbalt','relevance_rejected','no_reliable_regional_anchor')
            trace.write(path)
            value=lookup(ARTICLE+'?utm_campaign=test',path)
            self.assertTrue(value['found'])
            self.assertEqual(value['status'],'relevance_rejected')
            self.assertEqual(value['run_date'],'2026-11-23')

    def test_trace_not_found(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'trace.json'
            Trace('2026-11-23').write(path)
            self.assertFalse(lookup(ARTICLE,path)['found'])

    def test_full_run_records_non_event_and_source_health(self):
        with tempfile.TemporaryDirectory() as td:
            old=Path.cwd()
            try:
                os.chdir(td)
                cfg={'sources':[{'id':'demo','type':'curated','name':'Тест',
                    'region':'Мурманская область','rank':2,'items':[
                        {'title':'Нейтральный прогноз погоды по региону',
                         'summary':'Осадки и облачность','link':ARTICLE,'date':'2026-11-23'}]}],
                    'organizations':{}}
                Path('news_sources.json').write_text(json.dumps(cfg,ensure_ascii=False),encoding='utf-8')
                fake_g=types.SimpleNamespace(REGION_ORDER=['Мурманская область'],BASE_CSS='',
                    format_display_date=lambda s:s, format_weekday=lambda s:'понедельник',
                    format_msk=lambda s:s,_plural=lambda n,*w:w[0])
                with patch.object(nm,'g',fake_g):
                    new, statuses=nm.run(today=date(2026,11,23),verbose=False)
                self.assertEqual(new,[])
                got=lookup(ARTICLE)
                self.assertTrue(got['found'])
                self.assertEqual(got['status'],'not_detected')
                summary=json.loads(Path('run_summary_news.json').read_text(encoding='utf-8'))
                self.assertEqual(summary['diagnostics']['sources'][0]['id'],'demo')
            finally:
                os.chdir(old)

    def test_run_keeps_legacy_two_argument_fetch_source_mock(self):
        """Regression: the old tests replace fetch_source with a two-arg lambda."""
        with tempfile.TemporaryDirectory() as td:
            previous = Path.cwd()
            try:
                os.chdir(td)
                config = {'sources': [{'id': 'mock', 'type': 'site', 'name': 'Тест',
                                       'url': 'https://example.org/', 'region': None}],
                          'organizations': {}}
                Path('news_sources.json').write_text(
                    json.dumps(config, ensure_ascii=False), encoding='utf-8')
                fake_g = types.SimpleNamespace(
                    REGION_ORDER=['Мурманская область'], BASE_CSS='',
                    format_display_date=lambda s: s,
                    format_weekday=lambda s: 'понедельник',
                    format_msk=lambda s: s, _plural=lambda n, *w: w[0])
                with patch.object(nm, 'g', fake_g), patch.object(
                    nm, 'fetch_source', side_effect=lambda src, cache: ([], 'mock 0')):
                    new, statuses = nm.run(today=date(2026, 11, 23), verbose=False)
                self.assertEqual(new, [])
                self.assertEqual(statuses[0][2], 'mock 0')
            finally:
                os.chdir(previous)

    def test_audit_reads_trace_without_fetch_or_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            old=Path.cwd()
            try:
                os.chdir(td)
                Trace('2026-11-23').write()
                Path('news_sources.json').write_text('{"sources":[],"organizations":{}}',encoding='utf-8')
                # URL не в журнале, поэтому проверяем отказ сетевого клиента без падения
                with patch.object(nm, 'http_get', side_effect=nm.requests.Timeout('offline')):
                    from contextlib import redirect_stdout
                    import io
                    out=io.StringIO()
                    with redirect_stdout(out):
                        self.assertEqual(nm.audit_url(ARTICLE),0)
                result=json.loads(out.getvalue())
                self.assertEqual(result['analysis']['status'],'fetch_failed')
            finally:
                os.chdir(old)


if __name__ == '__main__':
    unittest.main()
