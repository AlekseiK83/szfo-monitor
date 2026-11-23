"""Контроль реального кейса Росбалта 23.11.2026, включая полный offline run."""
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

if "generate" not in sys.modules:
    try:
        import generate  # noqa: F401
    except ImportError:
        stub = types.ModuleType("generate")
        stub.SZFO_COMPILED = []
        stub._has_foreign_region = lambda _: False
        stub.REGION_ORDER = []
        sys.modules["generate"] = stub

import news_monitor as monitor
from news_staffing import workforce_fingerprint

FILE = Path(__file__).resolve().parents[1] / "data/news/featured_staffing_2026-11-23.json"
ROSBALT = json.loads(FILE.read_text(encoding="utf8"))[0]
ORGS = {"Ленинградская область": ["Севен"]}


class FeaturedStaffingTests(unittest.TestCase):
    def test_rosbalt_article_detected_as_workforce(self):
        d = monitor.detect_all(ROSBALT["title"], ROSBALT["summary"], ORGS)
        self.assertIsNotNone(d)
        self.assertEqual(d["type"], "workforce")
        self.assertEqual(monitor.event_region({"region": None}, ROSBALT["title"], ROSBALT["summary"], d),
                         "Ленинградская область")

    def test_repeat_47news_and_rosbalt_same_key(self):
        from tests.test_news_staffing import ARTICLE_TITLE, ARTICLE_LEAD
        a = {"type": "workforce", "region": "Ленинградская область", "date": "2026-09-07",
             "title": ARTICLE_TITLE, "summary": ARTICLE_LEAD, "orgs": ["Севен"]}
        b = {"type": "workforce", "region": "Ленинградская область", "date": "2026-11-23",
             "title": ROSBALT["title"], "summary": ROSBALT["summary"], "orgs": ["Севен"]}
        self.assertEqual(workforce_fingerprint(a), workforce_fingerprint(b))

    def test_2026_11_23_run_writes_one_event_and_notification_once(self):
        with tempfile.TemporaryDirectory() as td:
            old = Path.cwd()
            try:
                os.chdir(td)
                Path("data/news").mkdir(parents=True, exist_ok=True)
                shutil.copy(FILE, Path("data/news/featured_staffing_2026-11-23.json"))
                Path("news_sources.json").write_text(json.dumps({
                    "sources": [], "organizations": ORGS}, ensure_ascii=False), encoding="utf8")
                # Вся проверка не использует внешнюю сеть и не отправляет Telegram.
                fake_g = types.SimpleNamespace(
                    REGION_ORDER=["Ленинградская область"], BASE_CSS="",
                    format_display_date=lambda s: s,
                    format_weekday=lambda s: "понедельник",
                    format_msk=lambda s: s,
                    _plural=lambda n, *words: words[0],
                )
                with patch.object(monitor, "g", fake_g):
                    new, sources = monitor.run(today=date(2026, 11, 23), verbose=False)
                    self.assertEqual(len(new), 1)
                    self.assertEqual(new[0]["type"], "workforce")
                    self.assertEqual(new[0]["link"], ROSBALT["link"])
                    self.assertEqual(sources[0][2], "curated 1")
                    self.assertEqual(len(json.loads(Path("run_summary_news.json").read_text("utf8"))["new"]), 1)
                    rendered = Path("news.html").read_text(encoding="utf8")
                    self.assertIn(ROSBALT["link"], rendered)
                    self.assertIn("Персонал", rendered)
                    from scripts.check_featured_news import check_for_date
                    self.assertTrue(check_for_date("2026-11-23"))
                    again, _ = monitor.run(today=date(2026, 11, 23), verbose=False)
                    self.assertEqual(again, [])
                    self.assertEqual(len(json.loads(Path("data/news/events.json").read_text("utf8"))), 1)
            finally:
                os.chdir(old)

    def test_rosbalt_source_is_registered_once(self):
        from scripts.add_rosbalt_source import main
        with tempfile.TemporaryDirectory() as td:
            old = Path.cwd()
            try:
                os.chdir(td)
                Path("news_sources.json").write_text(json.dumps({
                    "sources": [{"id": "example", "type": "rss", "url": "https://example.org/rss"}],
                    "organizations": ORGS}, ensure_ascii=False), encoding="utf8")
                main()
                main()
                cfg = json.loads(Path("news_sources.json").read_text("utf8"))
                self.assertEqual(sum(s["id"] == "rosbalt" for s in cfg["sources"]), 1)
                self.assertEqual(cfg["organizations"], ORGS)
                self.assertEqual(cfg["sources"][0]["id"], "example")
            finally:
                os.chdir(old)

    def test_guard_ensures_event_in_events(self):
        from scripts.check_featured_news import check_for_date
        self.assertTrue(check_for_date("2026-11-24"))
        with tempfile.TemporaryDirectory() as td:
            old = Path.cwd()
            try:
                os.chdir(td)
                Path("data/news").mkdir(parents=True, exist_ok=True)
                Path("data/news/events.json").write_text("[]", encoding="utf8")
                Path("run_summary_news.json").write_text('{"new":[]}', encoding="utf8")
                with self.assertRaisesRegex(AssertionError, "отсутствует"):
                    check_for_date("2026-11-23")
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
