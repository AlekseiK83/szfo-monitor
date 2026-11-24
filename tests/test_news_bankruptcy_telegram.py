"""Targeted regression: 24 Nov 2026 B-port insolvency event and multiline Telegram titles."""
import copy
import json
import re
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import news_monitor as nm


ORGS = json.loads(Path('news_sources.json').read_text(encoding='utf-8'))['organizations']
SOURCE = {'id': 'bport_tg', 'type': 'telegram', 'name': 'Б-порт (Telegram)',
          'region': 'Мурманская область', 'rank': 3}
BROKEN_TITLE = '✅ В «Мурмашинской тепловой компании» на стадии'
FULL_TITLE = ('✅ В «Мурмашинской тепловой компании» на стадии банкротства '
              'назначили временного управляющего')
BODY = ('В «Мурмашинской тепловой компании» назначили временного управляющего '
        'и введено наблюдение. Решение принято на заседании Арбитражного суда '
        'Мурманской области 24 ноября 2026 года.')
SUMMARY = FULL_TITLE + '\n' + BODY
ARTICLE_URL = 'https://t.me/bportcom/87218'


class BankruptcyNotAppointmentTests(unittest.TestCase):
    def test_original_short_title_is_not_an_appointment(self):
        self.assertTrue(nm.bankruptcy_administrator_appointment(BROKEN_TITLE, SUMMARY))
        self.assertIsNone(nm.detect_all(BROKEN_TITLE, SUMMARY, ORGS))

    def test_full_title_is_not_an_appointment(self):
        self.assertIsNone(nm.detect_all(FULL_TITLE, BODY, ORGS))

    def test_bankruptcy_administrator_not_a_silovoe_department(self):
        self.assertIsNone(nm.detect_all('В Мурманске арбитражный суд утвердил конкурсного управляющего',
                                        'В рамках дела о банкротстве введено конкурсное производство.', ORGS))

    def test_reverse_word_order(self):
        self.assertIsNone(nm.detect_all('Временным управляющим при банкротстве тепловой компании назначен Иванов',
                                        'Арбитражный суд ввёл наблюдение.', ORGS))

    def test_bankruptcy_context_is_required(self):
        self.assertFalse(nm.bankruptcy_administrator_appointment(
            'Назначен управляющий филиалом банка', 'Он приступил к работе в Мурманской области.'))

    def test_new_company_director_survives_background_about_insolvency(self):
        for title in ('Назначен новый директор Мурмашинской тепловой компании',
                      'Директором Мурмашинской тепловой компании назначена Мария Иванова',
                      'На банкротном заводе назначили нового директора, временный управляющий продолжит работу'):
            with self.subTest(title=title):
                self.assertFalse(nm.bankruptcy_administrator_appointment(title, SUMMARY))
                ev = nm.detect_all(title, SUMMARY, ORGS)
                self.assertIsNotNone(ev)
                self.assertEqual(ev['type'], 'appointment')

    def test_new_court_chair_survives_summary_about_insolvency(self):
        title = 'Председателем Арбитражного суда Мурманской области назначен Иван Иванов'
        self.assertFalse(nm.bankruptcy_administrator_appointment(title, SUMMARY))
        self.assertEqual(nm.detect_all(title, SUMMARY, ORGS)['type'], 'appointment')

    def test_real_criminal_proceeding_is_not_suppressed(self):
        title = 'В Мурманской области задержан действующий губернатор'
        summary = ('По официальному сообщению Следственного комитета России задержан действующий губернатор. '
                   'Ранее суд назначил временного управляющего при банкротстве предприятия.')
        # Criminal proceedings have independent scope/confirmation requirements.
        self.assertFalse(nm.bankruptcy_administrator_appointment(title, summary))


class TelegramTitleTests(unittest.TestCase):
    def test_line_wrap_reassembled(self):
        raw = BROKEN_TITLE + '\nбанкротства назначили временного управляющего\n' + BODY
        self.assertEqual(nm.telegram_post_title(raw), FULL_TITLE)

    def test_parser_preserves_wrapped_headline(self):
        raw = ('<div class="tgme_widget_message_wrap"><div data-post="bportcom/87218">'
               '<div class="tgme_widget_message_text js-message_text" dir="auto">'
               '✅ В «Мурмашинской тепловой компании» на стадии<br>'
               'банкротства назначили временного управляющего<br><br>'
               + BODY + '</div><time datetime="2026-11-24T11:30:00+03:00"></time></div></div>')
        items = nm.parse_telegram(raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['title'], FULL_TITLE)
        self.assertEqual(items[0]['link'], ARTICLE_URL)
        self.assertIsNone(nm.detect_all(items[0]['title'], items[0]['summary'], ORGS))

    def test_complete_title_is_not_glued_to_next_paragraph(self):
        original = 'В Архангельске назначен новый прокурор'
        self.assertEqual(nm.telegram_post_title(original + '\nподробности в сообщении ниже'), original)

    def test_existing_title_extraction_stable(self):
        raw = ('Министр А.В. Иванов провёл совещание. Обсудили бюджет.\n'
               'Другой текст')
        self.assertEqual(nm.telegram_post_title(raw), 'Министр А.В. Иванов провёл совещание.')

    def test_reconcile_removes_bport_copy_without_touching_real_appointment(self):
        good = {'title': 'В Мурманской области назначен новый министр культуры',
                'summary': 'Глава региона представил нового министра.', 'type': 'appointment',
                'region': 'Мурманская область', 'date': '2026-11-24', 'level': 'head',
                'source_id': 'bport_tg', 'source': 'Б-порт (Telegram)', 'link': 'https://t.me/bportcom/111',
                'org_class': 'gov', 'orgs': [], 'person': ''}
        bad = {**good, 'title': BROKEN_TITLE, 'summary': SUMMARY, 'link': ARTICLE_URL, 'org_class': 'force'}
        cfg = {'sources': [SOURCE], 'organizations': ORGS}
        after, keys = nm.reconcile(copy.deepcopy([bad, good]), cfg)
        self.assertEqual([x['link'] for x in after], [good['link']])
        self.assertFalse(any(ARTICLE_URL in x['link'] for x in after))

    def test_telegram_truncation_has_word_boundary_and_ellipsis(self):
        # Telegram notification does not cut a word in the middle.
        long_title = 'Значимое решение по региональному проекту ' + 'компании ' * 30
        ev = {'title': long_title, 'region': 'Мурманская область', 'type': 'appointment',
              'link': 'https://example.org/a', 'source': 'Тест'}
        sent = []
        fake = types.ModuleType('notify_telegram')
        fake.TG_LIMIT = 4096
        fake.site_url = lambda: 'https://example.org/'
        fake.plural = lambda num, *forms: forms[0]
        fake.send = lambda *args, **kwargs: sent.append(args[2])
        fake.print_report = lambda _: None
        with patch.dict('sys.modules', {'notify_telegram': fake}), \
             patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': 'demo', 'TELEGRAM_CHAT_ID': '123'}), \
             patch.object(nm, 'load_json', return_value={'new': [ev]}):
            self.assertEqual(nm.notify(), 0)
        self.assertEqual(len(sent), 1)
        linktext = re.search(r'<a href="https://example.org/a">([^<]+)</a>', sent[0]).group(1)
        self.assertTrue(linktext.endswith('…'))
        self.assertTrue(len(linktext) <= 160)
        self.assertFalse(linktext.endswith('компан…'))

    def test_no_telegram_on_empty_new_events(self):
        fake = types.ModuleType('notify_telegram')
        fake.site_url = lambda: 'https://example.org/'
        fake.plural = lambda num, *forms: forms[0]
        with patch.dict('sys.modules', {'notify_telegram': fake}), \
             patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': 'demo', 'TELEGRAM_CHAT_ID': '123'}), \
             patch.object(nm, 'load_json', return_value={'new': []}):
            self.assertEqual(nm.notify(), 0)


if __name__ == '__main__':
    unittest.main()
