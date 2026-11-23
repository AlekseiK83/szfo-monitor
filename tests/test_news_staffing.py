"""Проверки отдельного инфоповода 'Персонал' во втором потоке."""
import sys
import types
import unittest

# В репозитории используется реальный generate.py; для автономной проверки
# модуль можно подменить его минимальным интерфейсом до импорта news_monitor.
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
from news_staffing import detect_staffing, staffing_region_for_story

ARTICLE_TITLE = ("Китайцам согласовали почти 19 тысяч рабочих мест в Усть-Луге. "
                 "Сербам отказали в двенадцати")
ARTICLE_LEAD = (
    'Правительство 47-го региона согласовало заявку "Китайской национальной '
    'химической инженерной и строительной Корпорации Севен КНР в Ленинградской области" '
    'на выдачу 18 620 разрешений на работу. Компания является подрядчиком '
    'на стройке газохимического комплекса в Усть-Луге.'
)
ORGS = {"Ленинградская область": ["Севен"], "Архангельская область": ["Севмаш"]}


def find_org(text, organizations):
    return [(r, n) for r, names in organizations.items() for n in names if n.lower() in text.lower()]


class StaffingTests(unittest.TestCase):
    def detect(self, title, summary=""):
        return detect_staffing(title, summary, ORGS, find_org)

    def test_47news_article_is_workforce(self):
        item = self.detect(ARTICLE_TITLE, ARTICLE_LEAD)
        self.assertIsNotNone(item)
        self.assertEqual(item["type"], "workforce")
        self.assertEqual(staffing_region_for_story(ARTICLE_TITLE, ARTICLE_LEAD), "Ленинградская область")

    def test_47news_short_headline_is_enough(self):
        self.assertEqual(self.detect(ARTICLE_TITLE)["type"], "workforce")

    def test_actual_monitor_detector_accepts_article(self):
        det = monitor.detect_all(ARTICLE_TITLE, ARTICLE_LEAD, ORGS)
        self.assertEqual(det["type"], "workforce")
        self.assertTrue(monitor.event_relevance(ARTICLE_TITLE, ARTICLE_LEAD, det,
                                                {"region": "Ленинградская область"}, ORGS)[0])
        self.assertEqual(monitor.event_region({"region": "Ленинградская область"},
                                              ARTICLE_TITLE, ARTICLE_LEAD, det), "Ленинградская область")

    def test_region_not_in_source_alone(self):
        t = "Компания согласовала 1200 разрешений на работу"
        det = {"type": "workforce", "orgs": []}
        self.assertFalse(monitor.event_relevance(t, "", det,
                         {"region": "Ленинградская область"}, ORGS)[0])

    def test_100_approved_permits_accepted(self):
        self.assertIsNotNone(self.detect("В Пскове согласовали 100 разрешений на работу"))

    def test_99_permits_rejected(self):
        self.assertIsNone(self.detect("В Пскове согласовали 99 разрешений на работу"))

    def test_12_permits_rejected(self):
        self.assertIsNone(self.detect("В Усть-Луге согласовали 12 квот на работников"))

    def test_company_growth_in_headcount(self):
        self.assertIsNotNone(self.detect("В Череповце компания увеличила штат на 150 человек"))

    def test_confirmed_new_jobs(self):
        self.assertIsNotNone(self.detect("В Архангельске создано 500 новых рабочих мест"))

    def test_rejected_permits_not_accepted(self):
        self.assertIsNone(self.detect("В Ленинградской области отказали в 1000 разрешениях на работу"))

    def test_vacancy_list_not_accepted(self):
        self.assertIsNone(self.detect("В Пскове работодатели открыли 500 вакансий"))

    def test_proposal_without_approval_not_accepted(self):
        self.assertIsNone(self.detect("В Пскове предложили выделить 800 квот на работников"))

    def test_plan_without_approval_not_accepted(self):
        self.assertIsNone(self.detect("В Пскове планируют нанять 2500 сотрудников"))

    def test_overseas_project_not_accepted(self):
        self.assertIsNone(self.detect("Российская компания согласовала 12000 рабочих мест в Китае"))

    def test_local_source_not_enough_for_foreign_worksite(self):
        det = {"type": "workforce", "orgs": []}
        self.assertIsNone(monitor.event_region({"region": "Ленинградская область"},
                                 "Согласовали 12000 рабочих мест в Китае", "", det))

    def test_same_company_distinct_workforce_events_not_merged(self):
        a = {"type": "workforce", "region": "Ленинградская область", "date": "2026-11-23",
             "title": "В Усть-Луге Севен согласовали 18000 рабочих мест", "orgs": ["Севен"], "person": ""}
        b = dict(a, title="В Усть-Луге Севен согласовали 500 рабочих мест для другого проекта")
        self.assertNotEqual(monitor.event_key(a), monitor.event_key(b))

    def test_old_appointment_detector_unchanged(self):
        det = monitor.detect_all("Назначен новый директор Севмаша", "", ORGS)
        self.assertEqual(det["type"], "appointment")

    def test_small_park_not_new_workforce(self):
        self.assertIsNone(self.detect("В Череповце губернатор открыл обновлённый сквер"))

    def test_pool_anniversary_not_new_workforce(self):
        self.assertIsNone(self.detect("В Пикалёво бассейн отметил 50-летний юбилей"))


if __name__ == "__main__":
    unittest.main()
