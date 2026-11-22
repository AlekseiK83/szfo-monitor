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
    def check(self, title, summary="", org_class="business", source=None):
        return check_relevance(title, summary, {"org_class": org_class}, source or {},
                               ORGS, find_org_names, news_region)

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

    def test_region_from_text_source_not_trusted(self):
        self.assertFalse(self.check("Назначен новый министр", org_class="gov",
                                    source={"region": "Республика Коми", "region_from_text": True})[0])

if __name__ == "__main__":
    unittest.main()
