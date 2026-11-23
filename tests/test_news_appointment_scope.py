"""Защита второго потока от ложных кадровых новостей: статус != назначение."""
import sys
import types
import unittest

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

REGION = "Псковская область"
ORGS = {"Ленинградская область": ["Севен"], "Архангельская область": ["Севмаш"]}
PLN_TITLE = (
    "Врио министра транспорта Псковской области объяснила, почему "
    "реконструкция дорог — это долго и дорого"
)
PLN_LEAD = (
    "Оксана Ильина, временно исполняющая обязанности министра транспорта "
    "Псковской области, рассказала о дороговизне проектирования и этапах "
    "реконструкции автомобильных дорог."
)


class AppointmentScopeTests(unittest.TestCase):
    def test_pln_actual_article_is_not_appointment(self):
        self.assertIsNone(monitor.detect_all(PLN_TITLE, PLN_LEAD, ORGS))

    def test_pln_actual_headline_alone_is_not_appointment(self):
        self.assertIsNone(monitor.detect_all(PLN_TITLE, "", ORGS))

    def test_mention_of_acting_minister_is_not_appointment(self):
        self.assertIsNone(monitor.detect_all(
            "Врио министра транспорта рассказала о ремонте дорог", "", ORGS))

    def test_interim_status_wording_is_not_appointment(self):
        self.assertIsNone(monitor.detect_all(
            "Временно исполняющая обязанности министра оценила ремонт дорог", "", ORGS))

    def test_io_minister_comment_is_not_appointment(self):
        self.assertIsNone(monitor.detect_all(
            "И. о. министра транспорта объяснила стоимость ремонта", "", ORGS))

    def test_real_interim_minister_appointment_survives(self):
        det = monitor.detect_all(
            "В Псковской области назначили врио министра транспорта", "", ORGS)
        self.assertIsNotNone(det)
        self.assertEqual(det["type"], "appointment")

    def test_became_acting_minister_survives(self):
        det = monitor.detect_all(
            "Оксана Ильина стала врио министра транспорта Псковской области", "", ORGS)
        self.assertIsNotNone(det)
        self.assertEqual(det["type"], "appointment")

    def test_real_full_status_appointment_survives(self):
        det = monitor.detect_all(
            "Временно исполняющим обязанности министра транспорта назначили Иванова", "", ORGS)
        self.assertIsNotNone(det)
        self.assertEqual(det["type"], "appointment")

    def test_rosbalt_workforce_category_survives(self):
        from news_staffing import detect_staffing
        title = "В Усть-Луге согласовали 18 620 разрешений на работу для Севен"
        lead = "Правительство Ленинградской области согласовало заявки компании Севен на выдачу 18 620 разрешений на работу."
        det = monitor.detect_all(title, lead, ORGS)
        self.assertIsNotNone(det)
        self.assertEqual(det["type"], "workforce")

    def test_saved_pln_event_dropped_by_reconcile(self):
        old = {
            "title": PLN_TITLE,
            "summary": PLN_LEAD,
            "link": "https://pln-pskov.ru/automir/606632.html",
            "type": "appointment",
            "level": "head",
            "org_class": "gov",
            "region": REGION,
            "date": "2026-11-23",
            "source": "ПЛН",
            "source_id": "pln",
            "rank": 3,
            "person": "",
            "orgs": [],
        }
        kept, _ = monitor.reconcile(
            [old], {"sources": [{"id": "pln", "region": REGION, "name": "ПЛН"}],
                    "organizations": ORGS})
        self.assertEqual(kept, [])


if __name__ == "__main__":
    unittest.main()
