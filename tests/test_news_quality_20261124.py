"""Системные регрессии по реальной выгрузке событий 24.11.2026 (без сети)."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import news_monitor as nm
from news_diagnostics import Trace, lookup
from news_source_rosbalt import google_news_rosbalt, ROSBALT_GOOGLE_RSS


def event(title, typ, region='Архангельская область', when='2026-11-23', **kw):
    return {'title': title, 'summary': '', 'type': typ, 'region': region,
            'date': when, 'level': 'head', 'person': '', 'orgs': [], **kw}


class ScopeTests(unittest.TestCase):
    def test_date_of_governor_hotline_is_not_appointment(self):
        self.assertIsNone(nm.detect_all('Назначена дата прямой линии губернатора Новгородской области', '', {}))

    def test_true_appointment_still_detected(self):
        d = nm.detect_all('В Новгородской области назначен исполняющий обязанности министра цифрового развития', '', {})
        self.assertEqual(d['type'], 'appointment')

    def test_festival_anniversary_not_event(self):
        self.assertIsNone(nm.detect_all('В Череповце химики отметили 25 лет "ФосАгро" фестивалем юмора', 'Фестиваль юмора', {}))

    def test_military_orchestra_anniversary_not_an_institution_milestone(self):
        title = 'В Санкт-Петербурге отметили 100-летие военного оркестра штаба Северо-Западного округа Росгвардии'
        self.assertIsNone(nm.detect_all(title, '', {}))

    def test_medical_institution_anniversary_stays(self):
        d = nm.detect_all('Архангельская областная клиническая больница отмечает 80-летие', '', {})
        self.assertEqual(d['type'], 'anniversary')

    def test_personal_director_birthday_is_not_institution_anniversary(self):
        self.assertIsNone(nm.detect_all('Режиссёр Калининградского драмтеатра Михаил Салес отмечает 80-летие', '', {}))

    def test_grant_to_launch_personal_business_not_launch(self):
        headline = 'Александр Беглов: в 2027 году участники СВО смогут получить до 2 миллионов рублей на запуск своего дела в Петербурге'
        self.assertIsNone(nm.detect_all(headline, '', {}))

    def test_true_launch_not_blocked(self):
        d = nm.detect_all('В Мурманской области открыли крупное месторождение с запасами руды на миллиарды рублей', '', {})
        self.assertIsNotNone(d)
        self.assertEqual(d['type'], 'launch')

    def test_presenter_deputy_does_not_change_judge_role(self):
        headline = 'Президент России Путин назначил Светлану Устинович председателем Архангельского областного суда'
        lead = 'Первый заместитель Председателя Верховного суда представил её юридическому сообществу.'
        d = nm.detect_all(headline, lead, {})
        self.assertEqual(d['level'], 'head')

    def test_presenter_deputy_does_not_change_doctor_role(self):
        headline = 'Самир Аль-Араби возглавил Псковскую областную инфекционную больницу'
        lead = 'Нового руководителя представила заместитель министра здравоохранения региона.'
        d = nm.detect_all(headline, lead, {})
        self.assertEqual(d['level'], 'head')

    def test_actual_deputy_role_preserved(self):
        d = nm.detect_all('Вице-премьером правительства Карелии назначена Екатерина Реутова', '', {})
        self.assertEqual(d['level'], 'deputy')

    def test_hospital_anniversary_two_articles_one_event(self):
        a = event('Архангельская областная больница отметила 80-летие', 'anniversary')
        b = event('Архангельская областная клиническая больница отмечает 80-летие', 'anniversary', when='2026-11-20')
        self.assertTrue(nm.similar(a, b))

    def test_distinct_anniversary_year_not_duplicate(self):
        a = event('Архангельская областная больница отметила 80-летие', 'anniversary')
        b = event('Архангельская областная больница отмечает 90-летие', 'anniversary')
        self.assertFalse(nm.similar(a, b))

    def test_different_type_of_hospital_stays_separate(self):
        a = event('Архангельская областная больница отметила 80-летие', 'anniversary')
        b = event('Архангельская городская больница отмечает 80-летие', 'anniversary')
        self.assertFalse(nm.similar(a, b))

    def test_same_region_different_institutions_not_duplicate(self):
        a = event('Архангельская областная больница отметила 80-летие', 'anniversary')
        b = event('Архангельская областная библиотека отмечает 80-летие', 'anniversary')
        self.assertFalse(nm.similar(a, b))

    def test_separate_region_anniversary_not_duplicate(self):
        a = event('Архангельская областная больница отметила 80-летие', 'anniversary')
        b = event('Архангельская областная клиническая больница отмечает 80-летие', 'anniversary', region='Вологодская область')
        self.assertFalse(nm.similar(a, b))

    def test_head_fsb_appointment_and_presentation_duplicate(self):
        a = event('Псков. Губернатору Псковской области представили нового начальника регионального управления ФСБ',
                  'appointment', region='Псковская область', when='2026-11-21')
        b = event('Новым главой псковского управления ФСБ назначен полковник Василий Дашко',
                  'appointment', region='Псковская область', when='2026-11-16')
        self.assertTrue(nm.similar(a, b))

    def test_deputy_fsb_not_automatically_same_as_head(self):
        a = event('Псковскому губернатору представили нового начальника регионального управления ФСБ',
                  'appointment', region='Псковская область')
        b = event('Назначен заместитель начальника псковского управления ФСБ',
                  'appointment', region='Псковская область', level='deputy')
        self.assertFalse(nm.similar(a, b))

    def test_reconcile_cleans_stored_copies_without_adding_notifications(self):
        import copy
        rows = [
            event('Архангельская областная больница отметила 80-летие', 'anniversary', when='2026-11-23'),
            event('Архангельская областная клиническая больница отмечает 80-летие', 'anniversary', when='2026-11-20'),
            event('Псков. Губернатору Псковской области представили нового начальника регионального управления ФСБ',
                  'appointment', region='Псковская область', when='2026-11-21'),
            event('Новым главой псковского управления ФСБ назначен полковник Василий Дашко',
                  'appointment', region='Псковская область', when='2026-11-16'),
            event('Назначена дата прямой линии губернатора Новгородской области', 'appointment',
                  region='Новгородская область')
        ]
        for i, e in enumerate(rows):
            e.update({'source_id': f'demo{i}', 'source': 'Тест', 'rank': 3, 'link':f'https://example.com/{i}'})
        cfg = {'sources': [{'id':e['source_id'], 'rank':3, 'region':e['region'], 'type':'site'} for e in rows],
               'organizations': {}}
        def resolve_region(text):
            if 'Архангельск' in text or 'архангельск' in text:
                return 'Архангельская область'
            if 'Псков' in text or 'псков' in text:
                return 'Псковская область'
            if 'Новгородск' in text or 'новгородск' in text:
                return 'Новгородская область'
            return None
        with patch.object(nm, 'news_region', side_effect=resolve_region):
            kept, _ = nm.reconcile(copy.deepcopy(rows), cfg)
        self.assertEqual(len(kept), 2)
        self.assertEqual({e['type'] for e in kept}, {'appointment', 'anniversary'})

    def test_proceeding_stages_unchanged(self):
        a = event('МВД подтвердило задержание губернатора Мурманской области Иванова', 'proceeding',
                  region='Мурманская область', procedure_stage='detention')
        b = event('Суд арестовал губернатора Мурманской области Иванова', 'proceeding',
                  region='Мурманская область', procedure_stage='arrest')
        self.assertFalse(nm.similar(a, b))


class TraceIntegrity(unittest.TestCase):
    def test_each_item_has_own_record_even_same_url(self):
        t = Trace('2026-11-24')
        url = 'https://example.com/a/1?utm_source=x'
        for ix in range(3):
            i = t.start_item(url, f'source{ix}', f'Публикация {ix}')
            t.update(i, 'duplicate' if ix else 'new')
        data = t.payload()
        self.assertEqual(data['record_count'], 3)
        self.assertEqual(len(data['records']), 3)
        self.assertNotIn('utm_source', json.dumps(data, ensure_ascii=False))
        self.assertEqual(len(data['links']), 1)  # старый поиск по URL сохранён

    def test_every_item_counted_in_real_run(self):
        from unittest.mock import patch
        import os
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            old = Path.cwd()
            try:
                os.chdir(tmp)
                cfg = {'sources':[{'id':'demo','type':'curated','name':'Тест','region':None,
                                   'items':[{'title':'Обычные новости без события','summary':'',
                                             'link':'https://example.com/a','date':'2026-11-24'},
                                            {'title':'Другие обычные новости','summary':'',
                                             'link':'https://example.com/a','date':'2026-11-24'}]}],
                       'organizations':{}}
                Path('news_sources.json').write_text(json.dumps(cfg, ensure_ascii=False))
                fake = SimpleNamespace(REGION_ORDER=[], BASE_CSS='',
                                       format_display_date=str, format_weekday=lambda x:'понедельник',
                                       format_msk=str, _plural=lambda x,*w:w[0] if w else '')
                with patch.object(nm, 'g', fake):
                    nm.run(today=date(2026, 11, 24), verbose=False)
                summary = json.loads(Path('run_summary_news.json').read_text())
                trace = json.loads(Path('data/news/last_run_trace.json').read_text())
                self.assertEqual(summary['diagnostics']['items_received'], trace['record_count'])
                self.assertEqual(len(trace['records']), 2)
            finally:
                os.chdir(old)


class RosbaltTests(unittest.TestCase):
    RSS = '''<rss version="2.0"><channel><item><title>В Ленинградской области открыли новый крупный завод - Росбалт</title>
    <link>https://news.google.com/rss/articles/some-id?oc=5</link>
    <pubDate>Tue, 24 Nov 2026 09:00:00 GMT</pubDate>
    <source url="https://www.rosbalt.ru">Росбалт</source></item>
    <item><title>Совершенно другая публикация</title><link>https://news.google.com/rss/articles/another</link>
    <source url="https://example.org">Другое агентство</source></item></channel></rss>'''

    def test_only_rosbalt_provenance_passes_google_rss(self):
        items = google_news_rosbalt(self.RSS, today=date(2026, 11, 24))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['title'], 'В Ленинградской области открыли новый крупный завод')

    def test_resilient_fetch_status_clearly_marks_aggregator(self):
        with patch.object(nm, 'fetch_rosbalt_fallback', return_value=([], 'error: rosbalt_no_articles')), \
             patch.object(nm, 'http_get', return_value=self.RSS):
            items, status = nm.fetch_rosbalt_resilient({'id':'rosbalt','url':'https://www.rosbalt.ru/'},
                                                         today=date(2026, 11, 24))
        self.assertEqual(len(items), 1)
        self.assertIn('via Google News', status)
        self.assertIn('rosbalt_no_articles', status)

    def test_original_direct_error_is_not_hidden_if_aggregator_empty(self):
        with patch.object(nm, 'fetch_rosbalt_fallback', return_value=([], 'error: rosbalt_no_articles')), \
             patch.object(nm, 'http_get', return_value='<rss><channel></channel></rss>'):
            items, status = nm.fetch_rosbalt_resilient({'id':'rosbalt','url':'https://www.rosbalt.ru/'},
                                                         today=date(2026, 11, 24))
        self.assertEqual(items, [])
        self.assertIn('rosbalt_no_articles', status)
        self.assertIn('google_news: no_matching_articles', status)


if __name__ == '__main__':
    unittest.main()
