import unittest
from news_relevance import check_relevance

ORGS = {"Архангельская область": ["Севмаш"], "Санкт-Петербург": ["Эрмитаж"]}

def find_org_names(text, orgs):
    return [(r, n) for r, names in orgs.items() for n in names if n.lower() in text.lower()]

def news_region(text):
    for r in ("Ленинградской области", "Санкт-Петербурге", "Архангельской области"):
        if r.lower() in text.lower():
            return r
    return None

class RelevanceTests(unittest.TestCase):
    def check(self, title, summary="", org_class="business", source=None, event_type="launch"):
        return check_relevance(title, summary,
                               {"type": event_type, "org_class": org_class}, source or {},
                               ORGS, find_org_names, news_region)

    def test_market_territory_even_if_misclassified_as_anniversary(self):
        title = ("Губернатор Георгий Филимонов сообщил об открытии обновлённой "
                 "территории у Колхозного рынка в Череповце")
        result = self.check(title, "Губернатор сообщил об открытии.",
                            "gov", {"region": "Вологодская область"},
                            event_type="anniversary")
        self.assertEqual(result, (False, "minor_public_space_not_scope"))

    def test_appointment_in_department_of_improvement_preserved(self):
        title = "Назначен руководитель департамента благоустройства"
        self.assertTrue(self.check(title, org_class="gov",
                                   source={"region": "Вологодская область"},
                                   event_type="appointment")[0])

    def test_leaving_improvement_department_preserved(self):
        title = "Освобождён от должности директор департамента благоустройства"
        self.assertTrue(self.check(title, org_class="gov",
                                   source={"region": "Вологодская область"},
                                   event_type="leave")[0])

    def test_cherepovets_market_territory_rejected(self):
        title = ("Губернатор Георгий Филимонов сообщил об открытии обновлённой "
                 "территории у Колхозного рынка в Череповце")
        self.assertEqual(self.check(title, org_class="gov",
                                    source={"region": "Вологодская область"}),
                         (False, "minor_public_space_not_scope"))

    def test_small_park_opening_rejected(self):
        self.assertFalse(self.check("В Пскове открыли обновлённый сквер",
                                    org_class="gov",
                                    source={"region": "Псковская область"})[0])

    def test_real_infrastructure_still_passes(self):
        self.assertTrue(self.check("В Ленинградской области открыли новый завод")[0])

    def test_local_appointment_still_passes(self):
        self.assertTrue(self.check("Назначен новый министр",
                                   org_class="gov",
                                   source={"region": "Республика Коми"})[0])

    def test_kim_general_news_rejected(self):
        self.assertFalse(self.check("Татьяна Ким рассказала о развитии Wildberries")[0])

    def test_kim_ranking_rejected(self):
        self.assertFalse(self.check("Татьяна Ким вошла в рейтинг богатейших женщин")[0])

    def test_regional_project_passes(self):
        self.assertTrue(self.check("Wildberries открыл склад в Ленинградской области")[0])

    def test_local_organization_passes(self):
        self.assertTrue(self.check("Севмаш назначил нового директора")[0])

    def test_local_official_passes(self):
        self.assertTrue(self.check("Назначен новый министр", org_class="gov",
                                   source={"region": "Республика Коми"})[0])

    def test_regional_source_does_not_validate_federal_brand(self):
        self.assertFalse(self.check("Татьяна Ким рассказала о Wildberries",
                                    source={"region": "Санкт-Петербург"})[0])

    def test_region_only_in_tail_not_enough(self):
        self.assertFalse(self.check("Татьяна Ким рассказала о Wildberries",
                                    "Обсудили бизнес. Позднее упомянули Санкт-Петербурге.")[0])

    def test_pikalevsky_pool_anniversary_removed_even_if_regional(self):
        title = "Пикалевский бассейн отметил 50-летие соревнованиями пловцов"
        summary = ("В Пикалево завершились двухдневные торжества в честь 50-летия "
                   "плавательного бассейна.")
        result = self.check(title, summary, org_class="business",
                            source={"region": "Ленинградская область"},
                            event_type="anniversary")
        self.assertEqual(result, (False, "minor_sports_facility_anniversary"))

    def test_pool_anniversary_not_saved_if_place_in_org_dictionary(self):
        local_orgs = {"Ленинградская область": ["Пикалевск"]}
        title = "Пикалевский бассейн отметил 50-летие соревнованиями пловцов"
        result = check_relevance(
            title, "В Пикалево состоялся праздник.",
            {"type": "anniversary", "org_class": "business"},
            {"region": "Ленинградская область"}, local_orgs,
            find_org_names, news_region)
        self.assertEqual(result, (False, "minor_sports_facility_anniversary"))

    def test_sports_school_anniversary_excluded(self):
        self.assertFalse(self.check(
            "Спортивная школа отметила 30-летний юбилей",
            org_class="podved", source={"region": "Республика Карелия"},
            event_type="anniversary")[0])

    def test_pool_director_appointment_retained(self):
        self.assertTrue(self.check(
            "Назначен новый директор плавательного бассейна",
            org_class="podved", source={"region": "Ленинградская область"},
            event_type="appointment")[0])

    def test_important_hospital_anniversary_retained(self):
        # В рабочем словаре есть региональная клиническая больница.
        local_orgs = {"Архангельская область": ["Архангельская областная клиническая"]}
        self.assertTrue(check_relevance(
            "Архангельская областная клиническая больница отмечает 80-летие",
            "", {"type": "anniversary", "org_class": "podved"},
            {"region": "Архангельская область"}, local_orgs,
            find_org_names, news_region)[0])

    def test_important_company_anniversary_retained(self):
        self.assertTrue(self.check(
            "Севмаш отметил 85-летие со дня основания",
            org_class="business", source={"region": "Архангельская область"},
            event_type="anniversary")[0])

    def test_region_from_text_source_not_trusted(self):
        self.assertFalse(self.check("Назначен новый министр", org_class="gov",
                                    source={"region": "Республика Коми", "region_from_text": True})[0])

if __name__ == "__main__":
    unittest.main()
