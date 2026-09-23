"""Регрессионные тесты szfo-monitor.

Каждая ошибка, найденная в реальных указах, фиксируется здесь как тест.
Если правка generate.py ломает хотя бы один старый кейс — тесты падают,
и ежедневная генерация не публикует сломанные данные.

Запуск локально:   python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import generate as g  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

SPB = "Санкт-Петербург"
NOVGOROD = "Новгородская область"
PSKOV = "Псковская область"
KOMI = "Республика Коми"
KALININGRAD = "Калининградская область"
ARKH = "Архангельская область"
VOLOGDA = "Вологодская область"


# Разрыв страницы в фикстурах — видимая строка-метка, а не невидимый символ \f:
# так файлы переживают копирование через веб-редактор GitHub.
PAGE_MARK = "<<<PAGE>>>"


def load_fixture(name):
    path = FIXTURES / name
    if not path.exists():
        raise AssertionError(f"Нет файла фикстуры {path.relative_to(ROOT)} — "
                             f"загрузите папку tests/fixtures целиком")
    text = path.read_text(encoding="utf-8")
    return text.replace(PAGE_MARK, "\f")


def parse_fixture(name, number, date, eo="0000000000000000"):
    return g.parse_awardees(load_fixture(name), {"number": number, "date": date, "eo": eo})


def region_of(rec):
    # Та же логика, что в build_result_from_awardees
    return g.match_region(rec.get("position_org", "")) or g.match_region(rec.get("raw", ""))


def find(recs, fio_prefix):
    hits = [r for r in recs if r["fio"].lower().startswith(fio_prefix.lower())]
    if not hits:
        raise AssertionError(f"Запись «{fio_prefix}» не найдена. "
                             f"Есть: {[r['fio'] for r in recs]}")
    return hits[0]


# ═══════════════════════════════════════════════════════════════════════
# 0. Предпроверка окружения — понятные сообщения при ошибках загрузки
# ═══════════════════════════════════════════════════════════════════════
class Test00Setup(unittest.TestCase):
    def test_generate_py_is_current(self):
        for name in ("source_url", "render_decree_line", "COLLECTIVE_START"):
            self.assertTrue(hasattr(g, name),
                            f"В generate.py нет «{name}» — в репозитории старая версия "
                            f"generate.py, загрузите новую")

    def test_fixtures_present(self):
        expected = ["rp_316_2026-08-24.txt", "ukaz_548_2026-08-04.txt",
                    "ukaz_580_2026-08-12.txt", "ukaz_597_2026-08-24.txt",
                    "ukaz_667_2026-09-18.txt"]
        missing = [n for n in expected if not (FIXTURES / n).exists()]
        self.assertFalse(missing, f"Нет фикстур в tests/fixtures/: {missing}")

    def test_fixtures_have_page_marks(self):
        text = (FIXTURES / "ukaz_580_2026-08-12.txt").read_text(encoding="utf-8")
        self.assertIn(PAGE_MARK, text,
                      "В фикстурах нет меток <<<PAGE>>> — загружена старая версия фикстур")


class Base(unittest.TestCase):
    def check(self, recs, fio, award_part, region, page=None):
        rec = find(recs, fio)
        self.assertIn(award_part.lower(), rec["award"].lower(),
                      f"{fio}: неверная награда «{rec['award']}»")
        self.assertEqual(region_of(rec), region,
                         f"{fio}: неверный регион (position: {rec['position_org'][:150]})")
        if page is not None:
            self.assertEqual(rec.get("page"), page, f"{fio}: неверная страница")
        return rec


# ═══════════════════════════════════════════════════════════════════════
# Распоряжение № 316-рп от 24.08.2026 — грамоты, благодарности, коллективы
# ═══════════════════════════════════════════════════════════════════════
class TestRasporyazhenie316(Base):
    @classmethod
    def setUpClass(cls):
        cls.recs = parse_fixture("rp_316_2026-08-24.txt", "316-рп", "24.08.2026")

    def test_gramota_basic(self):
        self.check(self.recs, "Гребенникова", "грамота", SPB, page=1)

    def test_blagodarnost_basic(self):
        self.check(self.recs, "Бугаёвой", "благодарность", NOVGOROD, page=2)
        self.check(self.recs, "Рагозину", "благодарность", PSKOV, page=3)

    def test_gramota_heading_on_two_lines(self):
        # «наградить Почетной грамотой Президента Российской / Федерации» без двоеточия
        self.check(self.recs, "Карасеву", "грамота", None)

    def test_gramota_verb_and_object_on_different_lines(self):
        # «За активную общественную деятельность наградить / Почетной грамотой …»
        self.check(self.recs, "Куликову", "грамота", None)

    def test_edinaya_rossiya_is_not_an_award(self):
        for r in self.recs:
            self.assertNotIn("ЕДИНАЯ", r["award"].upper(),
                             f"{r['fio']}: «ЕДИНАЯ РОССИЯ» принята за награду")
        self.check(self.recs, "Шамшурину", "благодарность", None)
        self.check(self.recs, "Шерстобитову", "благодарность", None)
        self.check(self.recs, "Александрову", "благодарность", SPB)

    def test_mikhailova_komi_blagodarnost(self):
        # Регресс 24.08: была «ЕДИНАЯ РОССИЯ» вместо благодарности
        self.check(self.recs, "Михайловой", "благодарность", KOMI, page=8)

    def test_culture_section(self):
        self.check(self.recs, "Бурцева", "грамота", None)
        self.check(self.recs, "Василевича", "грамота", PSKOV)
        self.check(self.recs, "Бурукину", "благодарность", None)
        self.check(self.recs, "Сидоренко", "благодарность", SPB)
        self.check(self.recs, "Соколовой", "благодарность", KOMI)
        self.check(self.recs, "Шукшину", "благодарность", SPB)

    def test_after_collectives_persons_parse_again(self):
        self.check(self.recs, "Гаман-Голутвину", "грамота", None)
        self.check(self.recs, "Иванову Елену", "грамота", None)
        self.check(self.recs, "Карповой", "благодарность", NOVGOROD)
        rec = self.check(self.recs, "Храброй", "благодарность", PSKOV)
        self.assertNotIn("Путин", rec["position_org"])

    # ── Коллективы ──
    def collectives(self):
        return [r for r in self.recs if r.get("kind") == "collective"]

    def test_collectives_count(self):
        # Самара (архив), РВИО, Транснефть, ЛЭТИ, Саратовская юр. академия
        self.assertEqual(len(self.collectives()), 5,
                         [c["position_org"][:60] for c in self.collectives()])

    def test_leti_collective_is_spb(self):
        leti = [c for c in self.collectives() if "ЛЭТИ" in c["position_org"]]
        self.assertEqual(len(leti), 1)
        leti = leti[0]
        self.assertEqual(leti["award"], g.BLAGODARNOST_AWARD)
        self.assertEqual(region_of(leti), SPB)
        self.assertNotIn("Саратов", leti["position_org"],
                         "ЛЭТИ склеился с соседним коллективом")

    def test_non_szfo_collectives_have_no_region(self):
        for c in self.collectives():
            if "ЛЭТИ" in c["position_org"]:
                continue
            self.assertIsNone(region_of(c), c["position_org"][:100])
            self.assertEqual(c["award"], g.BLAGODARNOST_AWARD)

    def test_transneft_split_from_rvio(self):
        names = [c["position_org"] for c in self.collectives()]
        self.assertTrue(any("Транснефть" in n and "военно-историческое" not in n for n in names))


# ═══════════════════════════════════════════════════════════════════════
# Указ № 580 от 12.08.2026 — многострочные звания, прилагательные регионов
# ═══════════════════════════════════════════════════════════════════════
class TestUkaz580(Base):
    @classmethod
    def setUpClass(cls):
        cls.recs = parse_fixture("ukaz_580_2026-08-12.txt", "580", "12.08.2026")

    def test_zasluzhenny_vrach(self):
        self.check(self.recs, "Баранову", "ЗАСЛУЖЕННЫЙ ВРАЧ", None)
        self.check(self.recs, "Кроту", "ЗАСЛУЖЕННЫЙ ВРАЧ", NOVGOROD)
        self.check(self.recs, "Орлову", "ЗАСЛУЖЕННЫЙ ВРАЧ", SPB)
        self.check(self.recs, "Хатькову", "ЗАСЛУЖЕННЫЙ ВРАЧ", None)

    def test_radzhabova_double_patronymic(self):
        rec = self.check(self.recs, "Раджабовой", "ЗАСЛУЖЕННЫЙ ВРАЧ", SPB, page=2)
        self.assertEqual(rec["fio"], "Раджабовой Замире Ахмед-Гаджиевне")

    def test_sadovnikova_spb_adjective_split_by_hyphen(self):
        self.check(self.recs, "Садовниковой", "ЗАСЛУЖЕННЫЙ ВРАЧ", SPB)

    def test_multiline_header_buravleva(self):
        # Регресс 12.08: заголовок звания на 2 строках + «Новгородской» без «область»
        self.check(self.recs, "Буравлевой", "ЗДРАВООХРАНЕНИЯ", NOVGOROD, page=2)

    def test_kremkov_correct_award(self):
        self.check(self.recs, "Кремкову", "ЗДРАВООХРАНЕНИЯ", SPB, page=3)

    def test_kirov_is_not_szfo(self):
        self.check(self.recs, "Семеновскому", "ЗДРАВООХРАНЕНИЯ", None)

    def test_orders(self):
        self.check(self.recs, "Копцева", "ЗА СПАСЕНИЕ ПОГИБАВШИХ", None)
        self.check(self.recs, "Сазонову", "ОРДЕНОМ ДРУЖБЫ", SPB)
        self.check(self.recs, "Исаченко", "ОРДЕНОМ ПОЧЕТА", SPB)
        self.check(self.recs, "Найду", "ОРДЕНОМ ПОЧЕТА", SPB)

    def test_degree_appended_to_award(self):
        rec = self.check(self.recs, "Трофимова", "ЗА ЗАСЛУГИ ПЕРЕД ОТЕЧЕСТВОМ", NOVGOROD)
        self.assertTrue(rec["award"].endswith("II СТЕПЕНИ"), rec["award"])

    def test_komi_and_novgorod_sport(self):
        self.check(self.recs, "Ермолиной", "ФИЗИЧЕСКОЙ КУЛЬТУРЫ", KOMI)
        self.check(self.recs, "Нутрихиной", "ФИЗИЧЕСКОЙ КУЛЬТУРЫ", KOMI)
        self.check(self.recs, "Филиппову", "ФИЗИЧЕСКОЙ КУЛЬТУРЫ", NOVGOROD)

    def test_collective_in_ukaz(self):
        coll = [r for r in self.recs if r.get("kind") == "collective"]
        self.assertEqual(len(coll), 1)
        self.assertIn("ОРДЕНОМ ПОЧЕТА", coll[0]["award"])
        self.assertIn("радиовещательная сеть", coll[0]["position_org"])
        self.assertIsNone(region_of(coll[0]))


# ═══════════════════════════════════════════════════════════════════════
# Указ № 597 от 24.08.2026
# ═══════════════════════════════════════════════════════════════════════
class TestUkaz597(Base):
    @classmethod
    def setUpClass(cls):
        cls.recs = parse_fixture("ukaz_597_2026-08-24.txt", "597", "24.08.2026")

    def test_family_awards(self):
        self.check(self.recs, "Буравовой", "МАТЬ-ГЕРОИНЯ", None)
        self.check(self.recs, "Моршнева", "РОДИТЕЛЬСКАЯ СЛАВА", ARKH)
        self.check(self.recs, "Моршневу", "РОДИТЕЛЬСКАЯ СЛАВА", ARKH)
        rec = self.check(self.recs, "Казакова", "РОДИТЕЛЬСКАЯ СЛАВА", VOLOGDA)
        self.assertIn("МЕДАЛЬЮ", rec["award"])

    def test_senators(self):
        self.check(self.recs, "Кондратенко", "ОРДЕНОМ ДРУЖБЫ", None)
        self.check(self.recs, "Писареву", "ОРДЕНОМ ДРУЖБЫ", NOVGOROD)

    def test_moscow_region_collective_not_szfo(self):
        coll = [r for r in self.recs if r.get("kind") == "collective"]
        self.assertEqual(len(coll), 1)
        self.assertIsNone(region_of(coll[0]))

    def test_regions_by_cities_and_adjectives(self):
        self.check(self.recs, "Ермолаева", "II СТЕПЕНИ", KALININGRAD)
        self.check(self.recs, "Парамонова", "II СТЕПЕНИ", PSKOV)

    def test_veterinary(self):
        self.check(self.recs, "Ануфриевой", "ВЕТЕРИНАРНЫЙ", None)
        self.check(self.recs, "Беляковой", "ВЕТЕРИНАРНЫЙ", KOMI)
        self.check(self.recs, "Новиковой", "ВЕТЕРИНАРНЫЙ", KALININGRAD)


# ═══════════════════════════════════════════════════════════════════════
# Точечные регрессии
# ═══════════════════════════════════════════════════════════════════════
class TestPointRegressions(Base):
    def test_kuzmina_local_government(self):
        # Регресс 04.08: была «ЗАСЛУЖЕННЫЙ АРТИСТ»
        recs = parse_fixture("ukaz_548_2026-08-04.txt", "548", "04.08.2026")
        self.check(recs, "Кузьминой", "МЕСТНОГО САМОУПРАВЛЕНИЯ", KALININGRAD)
        self.check(recs, "Ивановой", "ЗАСЛУЖЕННЫЙ АРТИСТ", None)

    def test_zinina_intensive_is_not_inta(self):
        # Регресс 18.09: «интенсивным» ловилось как город Инта (Коми)
        recs = parse_fixture("ukaz_667_2026-09-18.txt", "667", "18.09.2026")
        self.check(recs, "Зининой", "ЗАСЛУЖЕННЫЙ ВРАЧ", None)

    def test_old_raw_text_without_page_marks(self):
        text = ('"ЗАСЛУЖЕННЫЙ ВРАЧ РОССИЙСКОЙ ФЕДЕРАЦИИ"\n'
                'ПЕТРОВУ Ивану Ивановичу - врачу больницы, город Санкт-Петербург\n')
        recs = g.parse_awardees(text, {"number": "1", "date": "01.01.2026", "eo": "x"})
        self.assertEqual(len(recs), 1)
        self.assertIsNone(recs[0]["page"])
        self.assertEqual(region_of(recs[0]), SPB)


# ═══════════════════════════════════════════════════════════════════════
# Матчер регионов
# ═══════════════════════════════════════════════════════════════════════
class TestRegionMatcher(unittest.TestCase):
    CASES = [
        # Ложные срабатывания — не СЗФО
        ('главному врачу "Новосибирская психиатрическая больница с интенсивным наблюдением"', None),
        ("работник интернет-провайдера в Москве", None),
        ("сотрудник интерната, Оренбургская область", None),
        ("Новосибирская область.", None),
        ("Волгоградская область.", None),
        ("Карасунского района города Краснодара.", None),
        ("Чрезвычайного и Полномочного Посла Российской Федерации в Монголии.", None),
        ("Кировский областной перинатальный центр", None),
        ("работал в сосновом бору", None),
        ("на заливных лугах", None),
        # СЗФО
        ("врач ГБУЗ Республики Коми", KOMI),
        ("работник Сыктывкарской больницы", KOMI),
        ("житель Инты", KOMI),
        ("сотрудник Интинского района", KOMI),
        ("врач Ухтинской городской больницы", KOMI),
        ("шахтёр Воркуты", KOMI),
        ("судостроитель Северодвинска", ARKH),
        ("оленевод Нарьян-Мара", ARKH),
        ("металлург Череповца", VOLOGDA),
        ("работник г. Сосновый Бор Ленинградской области", "Ленинградская область"),
        ("врач Великолукской больницы", PSKOV),
        ("педагог Петрозаводска", "Республика Карелия"),
        ("работник Кронштадта", SPB),
        ("фельдшер Новгородской подстанции скорой помощи", NOVGOROD),
        ("сотрудник Мурманского морского порта", "Мурманская область"),
        ("работник ГОУ г. Кировск Мурманской области", "Мурманская область"),
    ]

    def test_cases(self):
        for text, expected in self.CASES:
            with self.subTest(text=text):
                self.assertEqual(g.match_region(text), expected)


# ═══════════════════════════════════════════════════════════════════════
# Ссылка на первоисточник и рендер
# ═══════════════════════════════════════════════════════════════════════
class TestSourceLinks(unittest.TestCase):
    def test_source_url_with_page(self):
        url = g.source_url({"eo": "0001202608240015"}, 16)
        self.assertEqual(url, "http://publication.pravo.gov.ru/file/pdf"
                              "?eoNumber=0001202608240015#page=16")

    def test_source_url_without_page_or_eo(self):
        self.assertTrue(g.source_url({"eo": "0001"}).endswith("eoNumber=0001"))
        self.assertIsNone(g.source_url({}))
        self.assertIsNone(g.source_url({"eo": "?"}))

    def test_decree_kind(self):
        self.assertEqual(g.decree_kind("316-рп"), "Распоряжение")
        self.assertEqual(g.decree_kind("597"), "Указ")

    def test_decree_line_html(self):
        html = g.render_decree_line({"decree": {"number": "316-рп", "date": "24.08.2026",
                                                "eo": "0001202608240015"}, "page": 16})
        self.assertIn("Распоряжение № 316-рп от 24.08.2026", html)
        self.assertIn("#page=16", html)
        self.assertIn("стр. 16", html)


class TestEndToEnd(unittest.TestCase):
    """Пересборка из raw_texts (как делает --rebuild) и рендер HTML."""

    def test_rebuild_and_render(self):
        text = load_fixture("rp_316_2026-08-24.txt")
        data = {
            "date": "2026-08-24",
            "stats": {"documents": 20, "awarding": 1, "awardees": 0, "szfo": 0},
            "raw_texts": {"0001202608240015": {"number": "316-рп", "date": "24.08.2026",
                                               "text": text}},
        }
        result = g.rebuild_report_from_json(data)
        spb = next(r for r in result["regions"] if r["name"] == SPB)
        people = [p for a in spb["awards"] for p in a["people"]]
        self.assertTrue(any(p.get("kind") == "collective" and "ЛЭТИ" in p["position_org"]
                            for p in people), "ЛЭТИ нет в Санкт-Петербурге")

        html = g.render_report_html(result)
        self.assertIn("PDF-оригинал", html)
        self.assertIn("организация", html)
        self.assertIn("Распоряжение № 316-рп", html)
        self.assertIn("eoNumber=0001202608240015#page=", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
