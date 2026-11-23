"""Три регрессии второго потока: высшее руководство, награда СМИ, федеральная статистика.

Все имена процессуальных кейсов синтетические: тест НЕ утверждает фактов
о каких-либо действующих должностных лицах.
"""
import copy
import json
import os
import re
import tempfile
import sys
import types
import unittest
from pathlib import Path
from datetime import date
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

import news_monitor as nm
from news_relevance import check_relevance
from news_proceedings import detect_proceedings

ORGS = {"Санкт-Петербург": ["Деловой Петербург"],
        "Архангельская область": ["Севмаш"]}
STUB_REGIONS = [
    ("Мурманская область", "murmansk", [re.compile(r"Мурманск\w*\s+област\w*", re.I)]),
    ("Санкт-Петербург", "spb", [re.compile(r"Санкт[ -]Петербург\w*|Петербург\w*", re.I)]),
    ("Республика Карелия", "karelia", [re.compile(r"Карели\w*", re.I)]),
    ("Псковская область", "pskov", [re.compile(r"Псковск\w*\s+област\w*", re.I)]),
]

PERSON_TITLE = "Сотрудники МВД России задержали губернатора Мурманской области Петра Синицына"
PERSON_LEAD = "МВД России сообщило о задержании руководителя региона по подозрению в преступлении."
JOURNALIST_TITLE = ('Фотокорреспондент "Делового Петербурга" Сергей Ермохин стал лауреатом '
                    'конкурса на премию правительства Петербурга в области журналистики по итогам 2026 года.')
DEPOSITS_TITLE = 'В России с начала 2026 года открыли 250 месторождений полезных ископаемых'


def article(title, summary, source_id, region, typ, who=""):
    return {"title": title, "summary": summary, "link": f"https://example.test/{source_id}",
            "source": source_id, "source_id": source_id, "region": region,
            "date": "2026-11-23", "type": typ, "level": "head", "org_class": "gov",
            "orgs": [], "rank": 3, "person": who}


class ProceedingsScopeTests(unittest.TestCase):
    def test_detention_of_current_governor(self):
        d = nm.detect_all(PERSON_TITLE, PERSON_LEAD, ORGS)
        self.assertIsNotNone(d)
        self.assertEqual(d["type"], "proceeding")
        self.assertEqual(d["stage"], "detention")

    def test_deputy_governor(self):
        d = detect_proceedings(
            "МВД подтвердило: задержан вице-губернатор Мурманской области Пётр Синицын", "")
        self.assertIsNotNone(d)
        self.assertEqual(d["level"], "deputy")

    def test_regional_minister(self):
        d = detect_proceedings("Следственный комитет задержал министра транспорта Псковской области", "")
        self.assertIsNotNone(d)
        self.assertEqual(d["stage"], "detention")

    def test_deputy_minister(self):
        d = detect_proceedings("По сообщению МВД задержан заместитель министра транспорта Мурманской области", "")
        self.assertIsNotNone(d)
        self.assertEqual(d["level"], "deputy")

    def test_official_charge_is_separate_stage(self):
        d = detect_proceedings(
            "Следственный комитет предъявил обвинение губернатору Мурманской области", "")
        self.assertEqual(d["stage"], "charge")

    def test_case_opened_against_governor(self):
        d = detect_proceedings(
            "Следственный комитет возбудил уголовное дело в отношении губернатора Мурманской области", "")
        self.assertEqual(d["stage"], "case")

    def test_suspected_without_event_not_enough(self):
        self.assertIsNone(detect_proceedings(
            "Губернатора Мурманской области подозревают в нарушениях", "МВД проводит проверку."))

    def test_federal_minister_is_not_regional_role(self):
        self.assertIsNone(detect_proceedings(
            "МВД задержало министра федерального ведомства России", ""))

    def test_authority_mentioned_but_not_confirming_is_insufficient(self):
        self.assertIsNone(detect_proceedings(
            "Задержан губернатор Мурманской области Пётр Синицын",
            "МВД пока не комментирует распространяемые сообщения."))

    def test_official_report_not_confirmed_only_by_keyword(self):
        self.assertIsNone(detect_proceedings(
            "Задержан губернатор Мурманской области Пётр Синицын",
            "МВД проверяет сообщения СМИ."))

    def test_subject_extraction_even_for_governor(self):
        d = detect_proceedings(PERSON_TITLE, PERSON_LEAD)
        self.assertEqual(d["subject"], "Петра Синицына")

    def test_former_governor_not_in_scope(self):
        self.assertIsNone(detect_proceedings(
            "МВД задержало бывшего губернатора Мурманской области Петра Синицына", ""))

    def test_former_deputy_not_in_scope(self):
        self.assertIsNone(detect_proceedings(
            "МВД задержало экс-вице-губернатора Мурманской области Петра Синицына", ""))

    def test_unnamed_sources_not_confirmation(self):
        self.assertIsNone(detect_proceedings(
            "По данным источников задержан губернатор Мурманской области", ""))

    def test_denial_not_confirmed(self):
        self.assertIsNone(detect_proceedings(
            "МВД опровергло задержание губернатора Мурманской области", ""))

    def test_interview_is_not_proceeding(self):
        self.assertIsNone(detect_proceedings(
            "Губернатор Мурманской области прокомментировал задержание директора завода", "МВД ведёт дело."))

    def test_detention_without_official_attribution(self):
        self.assertIsNone(detect_proceedings(
            "Задержан губернатор Мурманской области Пётр Синицын", "СМИ обсуждают новость."))

    def test_different_stages_distinct(self):
        detained = article(PERSON_TITLE, PERSON_LEAD, "a", "Мурманская область",
                           "proceeding", "Пётр Синицын")
        detained["procedure_stage"] = "detention"
        charged = copy.deepcopy(detained)
        charged["procedure_stage"] = "charge"
        self.assertNotEqual(nm.event_key(detained), nm.event_key(charged))
        self.assertFalse(nm.similar(detained, charged))
        self.assertEqual(nm.event_keys(detained), [nm.event_key(detained)])

    def test_same_stage_duplicate_deduplicated(self):
        a = article(PERSON_TITLE, PERSON_LEAD, "a", "Мурманская область",
                    "proceeding", "Пётр Синицын")
        a["procedure_stage"] = "detention"
        b = copy.deepcopy(a)
        b["title"] = "В МВД сообщили: задержан губернатор Мурманской области Пётр Синицын"
        self.assertEqual(nm.event_key(a), nm.event_key(b))
        self.assertTrue(nm.similar(a,b))

    def test_explicit_region_is_required_not_just_regional_source(self):
        d = {"type": "proceeding", "stage": "detention", "level": "head", "org_class": "gov", "orgs": []}
        with patch.object(nm.g, "SZFO_COMPILED", STUB_REGIONS):
            good = nm.event_relevance(PERSON_TITLE, PERSON_LEAD, d,
                {"region": "Мурманская область"}, ORGS)
            bad = nm.event_relevance("МВД задержало губернатора", "МВД сообщило о задержании.", d,
                {"region": "Мурманская область"}, ORGS)
        self.assertTrue(good[0])
        self.assertFalse(bad[0])


class NoiseCases(unittest.TestCase):
    def test_photojournalist_prize_excluded(self):
        src = {"region": "Санкт-Петербург"}
        d = {"type": "award", "org_class": "business", "orgs": [("Санкт-Петербург", "Деловой Петербург")]}
        with patch.object(nm.g, "SZFO_COMPILED", STUB_REGIONS):
            ok, reason = nm.event_relevance(JOURNALIST_TITLE, "", d, src, ORGS)
        self.assertFalse(ok)
        self.assertEqual(reason, "personal_media_award_not_scope")

    def test_other_honor_of_a_governor_still_passes(self):
        title = "В Мурманской области губернатора наградили государственным орденом"
        with patch.object(nm.g, "SZFO_COMPILED", STUB_REGIONS):
            ok, _ = nm.event_relevance(title, "", {"type": "award", "org_class": "gov", "orgs": []}, {}, ORGS)
        self.assertTrue(ok)

    def test_personal_prize_not_affect_appointment(self):
        title = "Назначен новый главный редактор Делового Петербурга"
        with patch.object(nm.g, "SZFO_COMPILED", STUB_REGIONS):
            ok, _ = nm.event_relevance(title, "", {"type": "appointment", "org_class": "business", "orgs": []},
                                       {"region": "Санкт-Петербург"}, ORGS)
        self.assertTrue(ok)

    def test_russia_250_deposits_not_local_project(self):
        d = {"type": "launch", "org_class": "business", "orgs": []}
        with patch.object(nm.g, "SZFO_COMPILED", STUB_REGIONS):
            ok, reason = nm.event_relevance(DEPOSITS_TITLE, "По данным ведомства, среди регионов есть Карелия.", d,
                                              {"region": "Республика Карелия"}, ORGS)
        self.assertFalse(ok)
        self.assertEqual(reason, "national_aggregate_not_local_event")

    def test_real_new_regional_mine_passes(self):
        with patch.object(nm.g, "SZFO_COMPILED", STUB_REGIONS):
            ok, _ = nm.event_relevance("В Карелии открыли новое месторождение", "",
                           {"type": "launch", "org_class": "business", "orgs": []}, {}, ORGS)
        self.assertTrue(ok)

    def test_offline_run_keeps_proceeding_and_removes_noise(self):
        source = {"id": "offline", "type": "curated", "region": "Республика Карелия",
                  "name": "Региональные новости", "rank": 2,
                  "items": [
                      {"title": PERSON_TITLE, "summary": PERSON_LEAD,
                       "link": "https://example.test/process", "date": "2026-11-23"},
                      {"title": JOURNALIST_TITLE, "summary": "Премия в области журналистики",
                       "link": "https://example.test/prize", "date": "2026-11-23"},
                      {"title": DEPOSITS_TITLE, "summary": "Всего по России",
                       "link": "https://example.test/deposits", "date": "2026-11-23"},
                  ]}
        with tempfile.TemporaryDirectory() as td:
            old = Path.cwd()
            try:
                os.chdir(td)
                Path("news_sources.json").write_text(json.dumps(
                    {"sources": [source], "organizations": ORGS}, ensure_ascii=False), encoding="utf8")
                fake_g = types.SimpleNamespace(
                    SZFO_COMPILED=STUB_REGIONS, _has_foreign_region=lambda text: False,
                    REGION_ORDER=["Мурманская область", "Санкт-Петербург", "Республика Карелия"],
                    BASE_CSS="", format_display_date=lambda x: x,
                    format_weekday=lambda x: "понедельник", format_msk=lambda x: x,
                    _plural=lambda n,*words: words[0],
                )
                with patch.object(nm, "g", fake_g):
                    fresh, _ = nm.run(today=date(2026,11,23), verbose=False)
                    self.assertEqual(len(fresh), 1)
                    self.assertEqual(fresh[0]["type"], "proceeding")
                    self.assertEqual(fresh[0]["procedure_stage"], "detention")
                    self.assertEqual(fresh[0]["region"], "Мурманская область")
                    text = Path("news.html").read_text(encoding="utf8")
                    self.assertIn("Процессуальное событие", text)
                    self.assertNotIn(JOURNALIST_TITLE, text)
                    self.assertNotIn(DEPOSITS_TITLE, text)
                    again, _ = nm.run(today=date(2026,11,23), verbose=False)
                    self.assertEqual(again, [])
                    events = json.loads(Path("data/news/events.json").read_text("utf8"))
                    self.assertEqual(len(events), 1)
            finally:
                os.chdir(old)

    def test_existing_records_removed_during_reconcile(self):
        cfg = {"sources": [{"id": "dp", "region": "Санкт-Петербург", "rank":3},
                            {"id": "onego", "region": "Республика Карелия", "rank":3}],
               "organizations": ORGS}
        saved = [article(JOURNALIST_TITLE, "", "dp", "Санкт-Петербург", "award"),
                 article(DEPOSITS_TITLE, "В России открыто 250 месторождений", "onego",
                         "Республика Карелия", "launch")]
        with patch.object(nm.g, "SZFO_COMPILED", STUB_REGIONS):
            kept, _ = nm.reconcile(saved, cfg)
        self.assertEqual(kept, [])


# Конкретные заголовки воспроизводят три записи из дайджеста (но не
# подтверждают и не проверяют достоверность содержащихся в них утверждений).
THREE_SOURCE_TITLES = [
    "Сотрудниками МВД России задержан губернатор Мурманской области Андрей Чибис",
    "В МВД подтвердили задержание губернатора Мурманской области",
    "МВД России подтвердило задержание мурманского губернатора Чибиса",
]


class ProceedingsMultiSourceDedup(unittest.TestCase):
    def _record(self, headline, when="2026-11-23", stage="detention", region="Мурманская область"):
        detected = nm.detect_all(headline, "", ORGS)
        self.assertIsNotNone(detected)
        self.assertEqual(detected["type"], "proceeding")
        return {"type": "proceeding", "level": detected["level"], "org_class": "gov",
                "title": headline, "summary": "", "person": detected.get("subject", ""),
                "orgs": [], "region": region, "date": when, "procedure_stage": stage,
                "source_id": "demo", "source": "Тестовый источник", "link": "https://example.test/story",
                "rank": 3}

    def test_three_headlines_same_detention_one_semantic_event(self):
        records = [self._record(t) for t in THREE_SOURCE_TITLES]
        for i in range(len(records)):
            for j in range(i):
                self.assertTrue(nm.similar(records[i], records[j]), (i, j))

    def test_lastname_in_genitive_same_key(self):
        records = [self._record(t) for t in THREE_SOURCE_TITLES]
        self.assertEqual(nm.event_key(records[0]), nm.event_key(records[2]))

    def test_distinct_named_governors_remain_distinct(self):
        a = self._record("МВД задержало губернатора Мурманской области Андрея Чибиса")
        b = self._record("МВД задержало губернатора Мурманской области Петра Синицына")
        self.assertFalse(nm.similar(a, b))
        self.assertNotEqual(nm.event_key(a), nm.event_key(b))

    def test_different_procedural_stages_remain_distinct(self):
        a = self._record(THREE_SOURCE_TITLES[0])
        b = self._record(THREE_SOURCE_TITLES[1], stage="arrest")
        self.assertFalse(nm.similar(a, b))
        self.assertNotEqual(nm.event_key(a), nm.event_key(b))

    def test_different_regions_and_later_new_events_not_glued(self):
        a = self._record(THREE_SOURCE_TITLES[0])
        b = self._record(THREE_SOURCE_TITLES[1], region="Архангельская область")
        c = self._record(THREE_SOURCE_TITLES[1], when="2026-12-10")
        self.assertFalse(nm.similar(a, b))
        self.assertFalse(nm.similar(a, c))

    def test_unnamed_deputies_not_falsely_merged(self):
        a = {"type": "proceeding", "level": "deputy", "org_class": "gov",
             "title": "МВД задержало вице-губернатора Мурманской области", "summary": "",
             "person": "", "orgs": [], "region": "Мурманская область",
             "date": "2026-11-23", "procedure_stage": "detention"}
        b = dict(a, title="СК подтвердил задержание заместителя губернатора Мурманской области")
        self.assertFalse(nm.similar(a, b))

    def test_reconcile_removes_three_existing_copies(self):
        records = [self._record(title) for title in THREE_SOURCE_TITLES]
        with patch.object(nm, "event_relevance", return_value=(True, "test")), \
             patch.object(nm, "event_region", return_value="Мурманская область"):
            retained, _seen = nm.reconcile(records, {"sources": [{"id": "demo", "rank": 3,
                                      "region": "Мурманская область"}], "organizations": ORGS})
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0]["procedure_stage"], "detention")

    def test_existing_three_duplicates_cleaned_without_new_alerts(self):
        records = [self._record(title) for title in THREE_SOURCE_TITLES]
        sources = []
        for i, title in enumerate(THREE_SOURCE_TITLES):
            records[i]["source_id"] = f"src{i}"
            records[i]["source"] = f"Источник {i}"
            records[i]["rank"] = i + 1
            sources.append({"id": f"src{i}", "name": f"Источник {i}",
                            "type": "curated", "rank": i + 1, "region": "Мурманская область",
                            "items": [{"title": title, "summary": "", "date": "2026-11-23",
                                       "link": f"https://example.test/{i}"}]})
        with tempfile.TemporaryDirectory() as td:
            old = Path.cwd()
            try:
                os.chdir(td)
                Path("news_sources.json").write_text(
                    json.dumps({"sources": sources, "organizations": ORGS}, ensure_ascii=False),
                    encoding="utf-8")
                Path("data/news").mkdir(parents=True)
                Path("data/news/events.json").write_text(
                    json.dumps(records, ensure_ascii=False), encoding="utf-8")
                fake_g = types.SimpleNamespace(
                    SZFO_COMPILED=STUB_REGIONS, _has_foreign_region=lambda text: False,
                    REGION_ORDER=["Мурманская область", "Санкт-Петербург"],
                    BASE_CSS="", format_display_date=lambda x: x,
                    format_weekday=lambda x: "понедельник", format_msk=lambda x: x,
                    _plural=lambda n, *forms: forms[0])
                with patch.object(nm, "g", fake_g):
                    new_events, _ = nm.run(today=date(2026, 11, 23), verbose=False)
                self.assertEqual(new_events, [])
                self.assertEqual(len(json.loads(Path("data/news/events.json").read_text("utf-8"))), 1)
                self.assertEqual(json.loads(Path("run_summary_news.json").read_text("utf-8"))["new"], [])
            finally:
                os.chdir(old)

    def test_offline_run_three_sources_only_one_notification(self):
        sources = []
        for i, title in enumerate(THREE_SOURCE_TITLES):
            sources.append({"id": f"src{i}", "type": "curated", "region": "Мурманская область",
                            "name": f"Тестовый источник {i}", "rank": i + 1,
                            "items": [{"title": title, "summary": "", "link": f"https://example.test/{i}",
                                       "date": "2026-11-23"}]})
        with tempfile.TemporaryDirectory() as td:
            original = Path.cwd()
            try:
                os.chdir(td)
                Path("news_sources.json").write_text(
                    json.dumps({"sources": sources, "organizations": ORGS}, ensure_ascii=False),
                    encoding="utf-8")
                fake_g = types.SimpleNamespace(
                    SZFO_COMPILED=STUB_REGIONS, _has_foreign_region=lambda text: False,
                    REGION_ORDER=["Мурманская область", "Санкт-Петербург"],
                    BASE_CSS="", format_display_date=lambda x: x,
                    format_weekday=lambda x: "понедельник", format_msk=lambda x: x,
                    _plural=lambda n, *forms: forms[0],
                )
                with patch.object(nm, "g", fake_g):
                    new, _statuses = nm.run(today=date(2026, 11, 23), verbose=False)
                    self.assertEqual(len(new), 1)
                    self.assertEqual(new[0]["type"], "proceeding")
                    self.assertEqual(new[0]["procedure_stage"], "detention")
                    self.assertEqual(len(json.loads(Path("data/news/events.json").read_text("utf-8"))), 1)
                    self.assertEqual(len(json.loads(Path("run_summary_news.json").read_text("utf-8"))["new"]), 1)
                    again, _ = nm.run(today=date(2026, 11, 23), verbose=False)
                    self.assertEqual(again, [])
                    self.assertEqual(len(json.loads(Path("data/news/events.json").read_text("utf-8"))), 1)
                    self.assertEqual(json.loads(Path("run_summary_news.json").read_text("utf-8"))["new"], [])
            finally:
                os.chdir(original)


if __name__ == "__main__":
    unittest.main()
