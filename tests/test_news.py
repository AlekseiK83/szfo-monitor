"""Регрессионные тесты мониторинга новостей (news_monitor.py).

Заголовки в тестах — реальные публикации СМИ и ведомств (dp.ru, Фонтанка, АБН24,
pravo.ru, МЧС, news.mail.ru), найденные в ходе исследования 17.11.2026."""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import news_monitor as nm  # noqa: E402

ORGS = json.loads((Path(__file__).resolve().parent.parent / "news_sources.json")
                  .read_text(encoding="utf-8"))["organizations"]


def det(title, summary=""):
    return nm.detect(title, summary, ORGS)


class TestAppointments(unittest.TestCase):
    POSITIVE = [
        ("Андрей Гаврилов назначен на должность главы комитета правопорядка Ленобласти", "head"),
        ("В Ленобласти назначили нового главу комитета госстройнадзора", "head"),
        ("Вице-губернатором Петербурга назначен генерал-майор Евгений Григорьев", "deputy"),
        ("Временным руководителем Правительства Псковской области стала Наталья Волкова", "head"),
        ("«Ленфильм» возглавил бывший руководитель департамента кинематографии Минкульта", "head"),
        ("Главу ВТБ Костина избрали главой «Объединенной судостроительной корпорации»", "head"),
        ("Евгений Орлов назначен начальником УМВД по Североморску", "head"),
        ("Старший советник юстиции Андрей Тимошичев стал прокурором Вологодской области", "head"),
        ("Полковник Дмитрий Остапенко назначен начальником УМВД по Архангельской области", "head"),
        ("Председателем жилищного комитета Петербурга назначен Олег Зотов", "head"),
        ("Комитет по архитектуре и градостроительству Ленинградской области возглавил Евгений Домрачев", "head"),
        ("Ильдар Абдразаков станет художественным руководителем Михайловского театра", "head"),
        ("Путин назначил Георгия Филимонова врио главы Вологодской области", "head"),
        ("Тюменское МЧС временно возглавит замруководителя из Мурманской области", "deputy"),
        ("Максим Мейксин приступил к работе в качестве вице-губернатора Петербурга", "deputy"),
        ("Беглов сформировал новое правительство и перераспределил полномочия вице-губернаторов", "deputy"),
        ("Алексей Беспрозванных представил новый состав правительства Калининградской области", "head"),
        ("Управление ФАС по Мурманской области возглавила экс-начальник госторгинспекции", "head"),
        ("Новым генеральным директором «Севмаша» назначен Михаил Будниченко", "head"),
        ("В «Северстали» сменился директор по производству на ЧерМК", "head"),
    ]
    LEAVE = [
        "Вице-губернатор Ленобласти по сельскому хозяйству досрочно покинул пост",
        "Путин подписал указ об отставке губернатора Вологодской области Кувшинникова",
        "Начальник УМВД по Мурманской области генерал-майор Игорь Баталов освобождён от должности",
    ]
    NEGATIVE = [
        "Министр транспорта Андрей Никитин встретился с губернатором Псковской области",
        "Губернатор Петербурга Александр Беглов подписал постановление о присвоении имён безымянным скверам",
        "В Ленобласти вырос спрос на посуточную аренду загородного жилья",
        "Беглов об обновлении правительства: «Есть бывшие коллеги, которые не справились с искушением»",
        "Губернатор Ленинградской области утвердит новую структуру правительства",      # будущее
        "Зам за замом: к ротации глав районов Петербурга привлекли комитет",
        "Главным тренером «Зенита» назначен Сергей Семак",
        "Директором школы № 5 Выборга назначена Ольга Иванова",
        "Главой Сланцевского сельского поселения избран Иван Петров",
        "Кто может возглавить комитет по транспорту Петербурга: источники называют трёх кандидатов",
        "Суд Петербурга отклонил апелляционную жалобу бывшего сотрудника таможни",
        "В Мурманской области до конца года внедрят беспилотники для защиты ЛЭП",
    ]

    def test_positive(self):
        for title, level in self.POSITIVE:
            with self.subTest(title=title):
                r = det(title)
                self.assertIsNotNone(r, title)
                self.assertEqual(r["type"], "appointment")
                self.assertEqual(r["level"], level)

    def test_leave(self):
        for title in self.LEAVE:
            with self.subTest(title=title):
                r = det(title)
                self.assertIsNotNone(r, title)
                self.assertEqual(r["type"], "leave")

    def test_negative(self):
        for title in self.NEGATIVE:
            with self.subTest(title=title):
                self.assertIsNone(det(title), title)

    def test_district_head_only_in_spb(self):
        self.assertIsNotNone(det("Главой администрации Красносельского района Петербурга назначена Ольга Акацевич"))
        self.assertIsNone(det("Главой администрации Тосненского района назначен Андрей Клементьев"))

    def test_org_dictionary_attaches_region(self):
        r = det("Новым генеральным директором «Севмаша» назначен Михаил Будниченко")
        self.assertIn(("Архангельская область", "Севмаш"), r["orgs"])


class TestTitles(unittest.TestCase):
    POSITIVE = [
        "Борис Эйфман и Пётр Яблонский избраны почётными гражданами Петербурга",
        "Список почётных граждан Петербурга пополнили два врача и народный артист России",
        "Путин присвоил начальнику УМВД по Омской области звание генерал-майора",
        "Указом Президента Российской Федерации сотрудникам МЧС России присвоены звания высших офицеров",
        "Начальник ГУФСИН по Челябинской области Игорь Третьяков стал генерал-майором внутренней службы",
        "Знаки «Почётный благотворитель Санкт-Петербурга» вручили в Мариинском дворце впервые в истории",
        "Директору ПИШ Алексею Боровкову присвоено звание «Почётный работник науки и высоких технологий»",
        "Главе Вологды присвоено звание «Заслуженный работник местного самоуправления Вологодской области»",
        "Валентина Матвиенко и патриарх Кирилл стали почётными гражданами Петербурга",
    ]
    NEGATIVE = [
        "В Петербурге меняют закон о звании почетного гражданина",
        "В этом году в Петербурге присвоят не более трёх званий «Почётный гражданин»",
        "Названы кандидаты на звание «Почетный благотворитель Петербурга»",
        "В Петербурге выберут двух новых «Почетных благотворителей» в 2026 году",
        "Губернатор Петербурга подписал постановление о присвоении имён безымянным скверам",
        "В Петербурге исчерпали лимит избрания почетных граждан",
        "Более 70 учёных и педагогов получили премии правительства Петербурга",
    ]

    def test_positive(self):
        for title in self.POSITIVE:
            with self.subTest(title=title):
                r = det(title)
                self.assertIsNotNone(r, title)
                self.assertEqual(r["type"], "title")

    def test_negative(self):
        for title in self.NEGATIVE:
            with self.subTest(title=title):
                self.assertIsNone(det(title), title)


class TestPerson(unittest.TestCase):
    def test_extract(self):
        self.assertEqual(nm.extract_person("Вице-губернатором Петербурга назначен генерал-майор Евгений Григорьев"),
                         "Евгений Григорьев")
        self.assertEqual(nm.extract_person("Андрей Гаврилов назначен на должность главы комитета правопорядка Ленобласти"),
                         "Андрей Гаврилов")
        self.assertEqual(nm.extract_person("Главу ВТБ Костина избрали главой ОСК"), "")

    def test_key_dedup_same_person(self):
        a = {"type": "appointment", "person": "Евгений Григорьев", "title": "x"}
        b = {"type": "appointment", "person": "Евгений Григорьев", "title": "y"}
        self.assertEqual(nm.event_key(a), nm.event_key(b))


class TestParsers(unittest.TestCase):
    RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Тест</title>
<item><title>Первая &amp; новость</title><link>https://ex.ru/1</link>
<pubDate>Mon, 16 Nov 2026 10:00:00 +0300</pubDate><description><![CDATA[<p>Текст <b>описания</b></p>]]></description></item>
<item><title>Вторая</title><link>https://ex.ru/2</link></item>
</channel></rss>"""
    ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Атом</title>
<link href="https://ex.ru/a"/><published>2026-11-16T09:00:00Z</published><summary>s</summary></entry></feed>"""
    TG = """<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message text_not_supported_wrap js-widget_message" data-post="smolnypress/1857" data-view="x">
<div class="tgme_widget_message_text js-message_text" dir="auto">Вице-губернатором Петербурга назначен <b>Евгений Григорьев</b>.<br/>Он курировал внешние связи.</div>
<time datetime="2026-11-16T12:30:00+00:00" class="time">15:30</time></div></div>
<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message" data-post="smolnypress/1858">
<div class="tgme_widget_message_text js-message_text">Второй пост без времени</div></div></div>"""
    HTML = """<html><head><link rel="alternate" type="application/rss+xml" href="/rss/"></head><body>
<a href="/news/1">Андрей Гаврилов назначен на должность главы комитета правопорядка Ленобласти</a>
<a href="/news/1">дубль</a><a href="/about">О нас</a>
<a href="https://other.ru/x">Чужой сайт с длинным заголовком новости о назначении</a>
<a href="/news/2"><span>В Ленобласти назначили</span> нового главу комитета госстройнадзора</a></body></html>"""

    def test_rss(self):
        items = nm.parse_feed(self.RSS)
        self.assertEqual([i["title"] for i in items], ["Первая & новость", "Вторая"])
        self.assertEqual(items[0]["summary"], "Текст описания")
        self.assertEqual(nm.parse_date(items[0]["date"]).isoformat(), "2026-11-16")

    def test_atom(self):
        items = nm.parse_feed(self.ATOM)
        self.assertEqual(items[0]["link"], "https://ex.ru/a")
        self.assertEqual(nm.parse_date(items[0]["date"]).isoformat(), "2026-11-16")

    def test_telegram(self):
        items = nm.parse_telegram(self.TG)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Вице-губернатором Петербурга назначен Евгений Григорьев.")
        self.assertEqual(items[0]["link"], "https://t.me/smolnypress/1857")
        self.assertIn("курировал", items[0]["summary"])
        self.assertEqual(nm.parse_date(items[0]["date"]).isoformat(), "2026-11-16")

    def test_html_news_and_feed_discovery(self):
        self.assertEqual(nm.discover_feed(self.HTML, "https://lenobl.ru/news/"), "https://lenobl.ru/rss/")
        items = nm.parse_html_news(self.HTML, "https://lenobl.ru/news/")
        self.assertEqual([i["link"] for i in items], ["https://lenobl.ru/news/1", "https://lenobl.ru/news/2"])
        self.assertEqual(items[1]["title"], "В Ленобласти назначили нового главу комитета госстройнадзора")


class TestRegion(unittest.TestCase):
    def test_federal_source_needs_region(self):
        src = {"region": None}
        self.assertIsNone(nm.attribute_region(src, "Назначен новый прокурор Тульской области", []))
        self.assertEqual(nm.attribute_region(src, "Назначен новый прокурор Мурманской области", []),
                         "Мурманская область")
        self.assertEqual(nm.attribute_region(src, "Севмаш получил нового директора",
                                             [("Архангельская область", "Севмаш")]), "Архангельская область")

    def test_news_region_names(self):
        self.assertEqual(nm.news_region("Вице-губернатором Петербурга назначен Евгений Григорьев"), "Санкт-Петербург")
        self.assertEqual(nm.news_region("В Ленобласти назначили нового главу комитета"), "Ленинградская область")
        self.assertEqual(nm.news_region("Глава Поморья представил нового министра"), "Архангельская область")
        self.assertEqual(nm.news_region("Новым мэром Сыктывкара стал Владимир Голдин"), "Республика Коми")
        self.assertEqual(nm.news_region("Бывший вице-губернатор Петербурга возглавил комитет Ленобласти"),
                         "Санкт-Петербург")     # побеждает первое упоминание
        self.assertIsNone(nm.news_region("Тюменское МЧС временно возглавит замруководителя из Мурманской области"))

    def test_surname_key(self):
        self.assertEqual(nm.surname("Евгений Григорьев"), "григорьев")
        self.assertEqual(nm.surname("Григорьев Евгений Николаевич"), "григорьев")

    def test_regional_source_default_and_foreign(self):
        src = {"region": "Республика Коми"}
        self.assertEqual(nm.attribute_region(src, "Назначен министр здравоохранения", []), "Республика Коми")
        self.assertIsNone(nm.attribute_region(src, "Назначен министр здравоохранения Татарстана", []))


class TestPage(unittest.TestCase):
    def test_render_page_and_filters(self):
        import tempfile
        events = [{"type": "appointment", "level": "deputy", "org_class": "gov", "region": "Санкт-Петербург",
                   "title": "Вице-губернатором Петербурга назначен Евгений Григорьев", "summary": "",
                   "link": "https://dp.ru/x", "date": "2026-11-16", "source": "ДП", "source_id": "dp",
                   "person": "Евгений Григорьев", "orgs": []},
                  {"type": "title", "level": "head", "org_class": "person", "region": "Республика Коми",
                   "title": "Главе Сыктывкара присвоено звание", "summary": "подробности", "link": "https://b.ru",
                   "date": "2026-11-15", "source": "БНК", "source_id": "bnkomi", "person": "", "orgs": []}]
        with tempfile.TemporaryDirectory() as tmp:
            old = nm.PAGE_FILE
            nm.PAGE_FILE = Path(tmp) / "news.html"
            try:
                nm.render_page(events, nm.g.msk_today())
                page = nm.PAGE_FILE.read_text(encoding="utf-8")
            finally:
                nm.PAGE_FILE = old
        self.assertIn('data-region="Санкт-Петербург"', page)
        self.assertIn("16 ноября 2026", page)
        self.assertIn('class="day-block" data-day="2026-11-16" open', page)
        self.assertIn("1 событие", page)
        self.assertIn('class="ev-type title"', page)
        self.assertEqual(page.count('class="ev"'), 2)


if __name__ == "__main__":
    unittest.main()


class TestFirstRunFeedback(unittest.TestCase):
    """Разбор первого прогона 17.11.2026: лишние события и дубли."""

    def test_summary_cannot_supply_the_verb(self):
        # глагол в аннотации, в заголовке события нет → не событие
        self.assertIsNone(det("Вопрос о целевом назначении «Шарматово» на нулевых чтениях бюджета поднял депутат Шалякин",
                              "Депутат спросил, когда будет назначен руководитель комитета по управлению имуществом."))
        self.assertIsNone(det("Очередная сессия Заксобрания Псковской области пройдёт 25 ноября",
                              "Депутаты утвердят председателя комитета по бюджету."))
        self.assertIsNone(det("В Росавиации обсудили вопросы функционирования «Комиавиатранс»",
                              "Совещание прошло 17 ноября. Генеральный директор назначен ответственным за программу."))

    def test_party_posts_and_noun_naznachenie(self):
        self.assertIsNone(det("Станислав Стармолотов избран секретарем Псковского городского отделения «Единой России»"))
        self.assertIsNone(det("Вопрос о целевом назначении «Шарматово» на нулевых чтениях бюджета поднял новгородский депутат Шалякин"))

    def test_verb_in_first_sentence_still_counts(self):
        r = det("Новый министр в Вологодской области", "Ксения Фаламеева назначена министром информационной политики.")
        self.assertIsNotNone(r)

    def test_position_key_merges_same_event(self):
        a = {"type": "appointment", "region": "Вологодская область",
             "title": "Георгий Филимонов назначил нового министра информационной политики", "summary": ""}
        b = {"type": "appointment", "region": "Вологодская область",
             "title": "Ксения Фаламеева назначена министром информационной политики Вологодской области", "summary": ""}
        self.assertEqual(nm.position_key(a), nm.position_key(b))
        c = {"type": "appointment", "region": "Республика Карелия",
             "title": "Вице-премьером Правительства по социальным вопросам назначена Екатерина Реутова", "summary": ""}
        d = {"type": "appointment", "region": "Республика Карелия",
             "title": "В Карелии назначили нового вице‑премьера по социальным вопросам", "summary": ""}
        self.assertEqual(nm.position_key(c), nm.position_key(d))
        e = {"type": "appointment", "region": "Республика Карелия",
             "title": "Министром здравоохранения Карелии назначен Михаил Охлопков", "summary": ""}
        self.assertNotEqual(nm.position_key(c), nm.position_key(e))

    def test_higher_rank_source_wins(self):
        import tempfile
        from datetime import date
        events = [
            {"type": "appointment", "level": "head", "org_class": "gov", "region": "Республика Карелия",
             "title": "В Карелии назначили нового вице-премьера по социальным вопросам", "summary": "", "link": "s",
             "date": "2026-11-17", "source": "Столица на Onego", "source_id": "stolicaonego", "rank": 3,
             "person": "", "orgs": []},
            {"type": "appointment", "level": "head", "org_class": "gov", "region": "Республика Карелия",
             "title": "Вице-премьером Правительства по социальным вопросам назначена Екатерина Реутова", "summary": "",
             "link": "g", "date": "2026-11-17", "source": "Правительство Республики Карелия", "source_id": "kar_gov",
             "rank": 1, "person": "Екатерина Реутова", "orgs": []}]
        events.sort(key=lambda e: (e["rank"], e["date"]))
        seen, kept = {}, []
        for ev in events:
            keys = nm.event_keys(ev)
            if any(k in seen for k in keys):
                continue
            for k in keys:
                seen[k] = "2026-11-17"
            kept.append(ev)
        self.assertEqual([e["source_id"] for e in kept], ["kar_gov"])
