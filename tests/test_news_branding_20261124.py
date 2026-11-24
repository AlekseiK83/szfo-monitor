"""Переименование второго потока: проверка отображения без изменения логики сбора."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import news_monitor as nm


ROOT = Path(__file__).resolve().parents[1]
MAIN_WORKFLOW = ROOT / '.github/workflows/news.yml'
AUDIT_WORKFLOW = ROOT / '.github/workflows/news-audit.yml'


class StreamBrandingTests(unittest.TestCase):
    def test_single_source_of_truth_for_name(self):
        self.assertEqual(nm.STREAM_NAME, 'Значимые события')
        self.assertEqual(nm.STREAM_FULL_NAME, 'Значимые события СЗФО')
        self.assertEqual(nm.PAGE_FILE.as_posix(), 'news.html')

    def test_render_page_title_description_and_existing_filters(self):
        event = {
            'date': '2026-11-24', 'region': 'Санкт-Петербург',
            'type': 'appointment', 'level': 'head', 'org_class': 'gov',
            'title': 'Назначен руководитель городского комитета',
            'link': 'https://example.org/official-news', 'summary': '',
            'source': 'Официальный сайт', 'orgs': [],
        }
        with tempfile.TemporaryDirectory() as d, patch.object(nm, 'PAGE_FILE', Path(d) / 'news.html'):
            nm.render_page([event], nm.g.msk_today())
            html = (Path(d) / 'news.html').read_text(encoding='utf-8')
        self.assertIn('<title>Значимые события СЗФО — мониторинг новостей</title>', html)
        self.assertIn('<h1>Значимые события</h1>', html)
        self.assertIn('Кадровые решения и отставки', html)
        self.assertIn('процессуальные события', html)
        self.assertIn('meta name="description"', html)
        self.assertIn('meta property="og:title" content="Значимые события СЗФО"', html)
        self.assertIn('data-region="Санкт-Петербург"', html)
        self.assertIn('data-type="appointment"', html)
        self.assertIn('<a href="index.html">← Наградные указы</a>', html)
        self.assertIn('https://example.org/official-news', html)
        self.assertNotIn('<h1>Назначения и звания</h1>', html)

    def test_empty_page_has_correct_title_and_existing_empty_message(self):
        with tempfile.TemporaryDirectory() as d, patch.object(nm, 'PAGE_FILE', Path(d) / 'news.html'):
            nm.render_page([], nm.g.msk_today())
            html = (Path(d) / 'news.html').read_text(encoding='utf-8')
        self.assertIn('<h1>Значимые события</h1>', html)
        self.assertIn('Событий пока нет', html)
        self.assertIn('data-region=""', html)

    def test_telegram_new_title_preserves_existing_url_and_notification_logic(self):
        messages = []
        fake = types.ModuleType('notify_telegram')
        fake.TG_LIMIT = 4096
        fake.site_url = lambda: 'https://alekseik83.github.io/szfo-monitor/'
        fake.plural = lambda n, one, few, many: one if n == 1 else many
        fake.send = lambda token, chats, message, report: messages.append((token, chats, message))
        fake.print_report = lambda report: None
        ev = {
            'date': '2026-11-24', 'region': 'Санкт-Петербург', 'type': 'appointment',
            'title': 'Назначен новый руководитель', 'link': 'https://example.org/appointment',
            'source': 'Официальный источник',
        }
        with patch.dict(sys.modules, {'notify_telegram': fake}), \
                patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': 'test-token', 'TELEGRAM_CHAT_ID': '100'}, clear=False), \
                patch.object(nm, 'load_json', return_value={'new': [ev]}):
            self.assertEqual(nm.notify(), 0)
        self.assertEqual(len(messages), 1)
        self.assertIn('📰 <b>Значимые события СЗФО</b>', messages[0][2])
        self.assertIn('https://alekseik83.github.io/szfo-monitor/news.html', messages[0][2])
        self.assertIn('https://example.org/appointment', messages[0][2])
        self.assertNotIn('<b>Назначения и звания в СЗФО</b>', messages[0][2])

    def test_renaming_sends_no_telegram_when_no_new_events(self):
        messages = []
        fake = types.ModuleType('notify_telegram')
        fake.TG_LIMIT = 4096
        fake.site_url = lambda: 'https://alekseik83.github.io/szfo-monitor/'
        fake.send = lambda *args, **kw: messages.append(args)
        with patch.dict(sys.modules, {'notify_telegram': fake}), \
                patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': 'test-token', 'TELEGRAM_CHAT_ID': '100'}, clear=False), \
                patch.object(nm, 'load_json', return_value={'new': []}):
            self.assertEqual(nm.notify(), 0)
        self.assertEqual(messages, [])

    def test_existing_event_types_still_available(self):
        for name in ('appointment', 'leave', 'title', 'anniversary', 'launch',
                     'award', 'visit', 'workforce', 'proceeding', 'ownership'):
            self.assertIn(name, nm.TYPE_LABEL)

    def test_workflow_file_name_schedule_and_commands_stable(self):
        text = MAIN_WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('name: Значимые события СЗФО', text)
        self.assertIn("cron: '37 */3 * * *'", text)
        self.assertIn('group: szfo-data', text)
        self.assertIn('run: python news_monitor.py\n', text)
        self.assertIn('run: python news_monitor.py --notify', text)
        self.assertIn('run: python -m unittest tests.test_news -v', text)
        self.assertIn('run: python -m unittest tests.test_news_branding_20261124 -v', text)
        self.assertIn('Значимые события СЗФО, $(date -u', text)
        self.assertNotIn('Новости — назначения и звания', text)
        self.assertNotIn('Новости: назначения и звания,', text)

    def test_manual_audit_is_renamed_without_changing_readonly_behavior(self):
        if not AUDIT_WORKFLOW.exists():
            self.skipTest('Необязательный workflow диагностики не установлен')
        text = AUDIT_WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('name: Значимые события СЗФО — проверка публикации', text)
        self.assertIn('contents: read', text)
        self.assertIn('workflow_dispatch:', text)
        self.assertIn('--audit-url "$ARTICLE_URL"', text)
        self.assertNotIn('--notify', text)


if __name__ == '__main__':
    unittest.main()
