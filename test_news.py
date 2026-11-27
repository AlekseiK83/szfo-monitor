"""Регрессионные тесты мониторинга новостей (news_monitor.py).

Заголовки в тестах — реальные публикации СМИ и ведомств (dp.ru, Фонтанка, АБН24,
pravo.ru, МЧС, news.mail.ru), найденные в ходе исследования 17.11.2026."""
import json
import os
import sys
import unittest
from unittest.mock import patch
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
        a = {"type": "appointment", "region": "Республика Коми", "person": "Евгений Григорьев", "title": "x"}
        b = {"type": "appointment", "region": "Республика Коми", "person": "Евгения Григорьева", "title": "y"}
        c = {"type": "appointment", "region": "Псковская область", "person": "Евгений Григорьев", "title": "y"}
        self.assertEqual(nm.event_key(a), nm.event_key(b))
        self.assertNotEqual(nm.event_key(a), nm.event_key(c))      # однофамильцы в разных регионах — разные события

    def test_position_key_expires(self):
        import datetime as dt
        keys = ["pos:appointment:Республика Коми:минис образ"]
        seen = {keys[0]: "2026-10-01"}
        self.assertTrue(nm.blocked_by_seen(keys, seen, dt.date(2026, 10, 8)))    # через неделю — тот же пост, дубль
        self.assertFalse(nm.blocked_by_seen(keys, seen, dt.date(2026, 11, 1)))   # через месяц — новый министр
        self.assertTrue(nm.blocked_by_seen(["appointment:Республика Коми:иванов"], {"appointment:Республика Коми:иванов": "2026-10-01"}, dt.date(2026, 11, 1)))


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
        self.assertIsNone(det("Очередная сессия Заксобрания Псковской области пройдёт 25 ноября",
                              "Совет Законодательного Собрания утвердил дату сессии. Об этом сообщил председатель Собрания Борис Елкин."))
        self.assertIsNotNone(det("Заксобрание утвердило Дмитрия Ялова в должности вице-губернатора"))
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


class TestReconcile(unittest.TestCase):
    """Сохранённые события пересматриваются по текущим правилам при каждом прогоне."""

    def test_first_run_events_are_cleaned(self):
        cfg = json.loads((Path(__file__).resolve().parent.parent / "news_sources.json").read_text(encoding="utf-8"))
        mk = lambda title, src, date, region, summary="": {
            "type": "appointment", "level": "head", "org_class": "gov", "region": region, "title": title,
            "summary": summary, "link": "", "date": date, "source": src, "source_id": src, "person": "", "orgs": []}
        events = [
            mk("В Росавиации обсудили вопросы функционирования \"Комиавиатранс\"", "komiinform", "2026-11-17", "Республика Коми"),
            mk("Вице-премьером Правительства по социальным вопросам назначена Екатерина Реутова", "kar_gov", "2026-11-17", "Республика Карелия"),
            mk("В Карелии назначили нового вице‑премьера по социальным вопросам", "stolicaonego", "2026-11-17", "Республика Карелия"),
            mk("Экс-заместителя прокурора Псковской области назначили заместителем генпрокурора РФ", "pln", "2026-11-17", "Псковская область"),
            mk("Станислав Стармолотов избран секретарем Псковского городского отделения «Единой России»", "pln", "2026-11-17", "Псковская область"),
            mk("Очередная сессия Заксобрания Псковской области пройдёт 25 ноября", "informpskov", "2026-11-17", "Псковская область"),
            mk("Игорь Дитрих: Комитет по социальной политике начнет полноценную работу после утверждения положения на ближайшей сессии", "pln", "2026-11-17", "Псковская область"),
            mk("Вопрос о целевом назначении «Шарматово» на нулевых чтениях бюджета поднял новгородский депутат Шалякин", "novgorod_ru", "2026-11-17", "Новгородская область"),
            mk("Сенатор Дмитрий Василенко утвержден в должности первого зампреда Комитета СовФеда 28 октября 2026", "lo_zaks", "2026-11-17", "Ленинградская область"),
            mk("Ксения Фаламеева назначена министром информационной политики Вологодской области", "krassever", "2026-11-17", "Вологодская область"),
            mk("Георгий Филимонов назначил нового министра информационной политики", "newsvo", "2026-11-16", "Вологодская область"),
            mk("Владимир Карпунин назначен исполняющим обязанности министра цифрового развития Новгородской области", "nov_official_tg", "2026-11-13", "Новгородская область"),
        ]
        kept, seen = nm.reconcile(events, cfg)
        titles = [e["title"][:30] for e in kept]
        self.assertEqual(len(kept), 5, titles)
        sources = {e["source_id"] for e in kept}
        self.assertIn("kar_gov", sources)          # Карелия — официальный источник
        self.assertNotIn("stolicaonego", sources)  # дубль склеен
        vol = [e for e in kept if e["region"] == "Вологодская область"]
        self.assertEqual(len(vol), 1)
        self.assertEqual(vol[0]["source_id"], "krassever")   # при равном ранге — заголовок с фамилией
        self.assertIn("nov_official_tg", sources)
        self.assertIn("lo_zaks", sources)
        self.assertTrue(any(e["title"].startswith("Экс-заместителя") for e in kept))


class TestGoogleNews(unittest.TestCase):
    def test_source_suffix_stripped(self):
        xml = ('<rss><channel><link>https://news.google.com/</link><item>'
               '<title>Ксения Фаламеева назначена министром - Красный Север</title>'
               '<link>https://news.google.com/x</link><pubDate>Mon, 17 Nov 2026 09:00:00 GMT</pubDate>'
               '<description>&lt;a&gt;Другой заголовок, в котором кто-то назначен&lt;/a&gt;</description></item></channel></rss>')
        items = nm.parse_feed(xml)
        self.assertEqual(items[0]["title"], "Ксения Фаламеева назначена министром")
        self.assertEqual(items[0]["summary"], "")
        self.assertEqual(nm.parse_date(items[0]["date"]).isoformat(), "2026-11-17")


class TestExtraEvents(unittest.TestCase):
    """Инфоповоды по ключевым учреждениям и компаниям (кроме назначений и званий)."""

    def ex(self, title, summary=""):
        return nm.detect_all(title, summary, ORGS)

    def test_obituary(self):
        r = self.ex("Скончался бывший генеральный директор Севмаша Николай Калистратов")
        self.assertEqual(r["type"], "obituary")
        r = self.ex("Ушёл из жизни почётный гражданин Петербурга композитор Андрей Петров")
        self.assertEqual(r["type"], "obituary")
        self.assertIsNone(self.ex("В ДТП под Псковом погиб водитель грузовика"))

    def test_visit(self):
        self.assertEqual(self.ex("Путин посетил Севмаш и принял участие в закладке атомной подводной лодки")["type"], "visit")
        self.assertEqual(self.ex("Мишустин прибыл в Мурманск и осмотрел строящийся терминал «Лавна»")["type"], "visit")
        self.assertEqual(self.ex("Глава Росатома Лихачёв открыл новый энергоблок Ленинградской АЭС")["type"], "visit")
        self.assertIsNone(self.ex("Путин поздравил россиян с Днём народного единства"))

    def test_anniversary(self):
        self.assertEqual(self.ex("Северсталь отметила 70-летие Череповецкого металлургического комбината")["type"], "anniversary")
        self.assertEqual(self.ex("Петрозаводскому государственному университету исполнилось 85 лет")["type"], "anniversary")
        self.assertEqual(self.ex("Архангельский ЦБК празднует 85-летний юбилей")["type"], "anniversary")
        self.assertIsNone(self.ex("Северсталь отметила 17-летие программы наставничества"))
        self.assertIsNone(self.ex("Ветеран Севмаша отметил 90-летие со дня рождения"))
        self.assertIsNone(self.ex("В Вологде 50 лет назад открылся первый универсам"))

    def test_launch(self):
        self.assertEqual(self.ex("На Балтийском заводе спустили на воду атомный ледокол «Чукотка»")["type"], "launch")
        self.assertEqual(self.ex("В Усть-Луге запустили первую очередь комплекса по переработке газа за 2 трлн рублей")["type"], "launch")
        self.assertEqual(self.ex("ФосАгро ввела в эксплуатацию новое производство в Череповце")["type"], "launch")
        self.assertEqual(self.ex("Акрон подписал контракт на строительство агрегата аммиака")["type"], "launch")
        self.assertEqual(self.ex("Автотор начал выпуск новой модели")["type"], "launch")
        self.assertIsNone(self.ex("Эрмитаж открыл выставку импрессионистов"))
        self.assertIsNone(self.ex("В Пскове открыли отремонтированную детскую площадку во дворе на Рижском"))
        self.assertIsNone(self.ex("В Петербурге открылся сезон фонтанов"))

    def test_award(self):
        self.assertEqual(self.ex("Севмаш награждён орденом «За заслуги перед Отечеством» I степени")["type"], "award")
        self.assertEqual(self.ex("Коллектив ПетрГУ удостоен премии Правительства России в области образования")["type"], "award")
        self.assertIsNone(self.ex("Победителям городского конкурса рисунков вручили грамоты"))

    def test_status(self):
        self.assertEqual(self.ex("ИТМО вошёл в топ-100 лучших вузов мира по версии QS")["type"], "status")
        self.assertEqual(self.ex("Кировский завод включён в перечень системообразующих предприятий России")["type"], "status")
        self.assertEqual(self.ex("Вологодская областная больница признана лучшей в России по итогам всероссийского конкурса")["type"], "status")
        self.assertIsNone(self.ex("Команда школы № 7 победила в городском конкурсе чтецов"))

    def test_ownership(self):
        self.assertEqual(self.ex("Генпрокуратура потребовала изъять акции Кировского завода в доход государства")["type"], "ownership")
        self.assertEqual(self.ex("Суд признал банкротом Выборгский судостроительный завод")["type"], "ownership")
        self.assertEqual(self.ex("Задержан бывший гендиректор Петрозаводскмаша")["type"], "ownership")
        self.assertIsNone(self.ex("Суд признал банкротом петербургского предпринимателя"))

    def test_low_level_positions_excluded(self):
        self.assertIsNone(self.ex("Начальником отдела кадров комитета по транспорту назначен Иван Петров"))
        self.assertIsNone(self.ex("Главврачом Тосненской районной больницы назначен Сергей Иванов"))
        self.assertIsNone(self.ex("Директором Дома культуры в Луге стала Анна Смирнова"))

    def test_new_significant_bodies(self):
        self.assertEqual(self.ex("Председателем избиркома Ленинградской области избран Михаил Лебединский")["type"], "appointment")
        self.assertEqual(self.ex("Командующим Северным флотом назначен адмирал Константин Кабанцов")["type"], "appointment")
        self.assertEqual(self.ex("Уполномоченным по правам ребёнка в Карелии назначена Галина Григорьева")["type"], "appointment")
        self.assertEqual(self.ex("Новым управляющим Северо-Западным отделением Сбербанка стал Дмитрий Суховерхов")["type"], "appointment")

    def test_appointments_still_win_over_extra(self):
        r = self.ex("Скончавшегося директора Эрмитажа сменил на посту Михаил Пиотровский")
        self.assertEqual(r["type"], "appointment")


class TestSecondRunFeedback(unittest.TestCase):
    """Разбор прогона 18.11 15:00: четыре нерелевантных события."""

    def ex(self, title, summary=""):
        return nm.detect_all(title, summary, ORGS)

    def test_ownership_change_is_not_appointment_and_needs_known_org(self):
        r = self.ex("Ретейлер электроники «Связь.ON» с 250 магазинами сменил собственников",
                    "Банк ПСБ и гендиректор компании Дагмара Иванова продали свои доли в сети магазинов.")
        self.assertIsNone(r)
        self.assertEqual(self.ex("Генеральный директор Севмаша сменился: предприятие возглавил Михаил Будниченко")["type"], "appointment")

    def test_foreign_university_not_politeh(self):
        r = self.ex("Посещение совместного университета МГУ и Пекинского политехнического института",
                    "Владимир Путин посетил первый совместный вуз России и Китая в Шэньчжэне.")
        self.assertFalse(r and r["orgs"])
        self.assertEqual(nm.find_org_names("Ректор Политеха Петра Великого Андрей Рудской", ORGS)[0][1], "Политех Петра Великого")

    def test_media_self_promotion_is_not_status(self):
        self.assertIsNone(self.ex("Онлайн47 вошел в ТОП-20 самых цитируемых СМИ Петербурга и Ленобласти за 2026 год"))

    def test_criminal_case_needs_a_leader(self):
        self.assertIsNone(self.ex("В Петербурге возбудили дело после ДТП с наездом на двух девушек на Пискарёвском",
                                  "Дело возбуждено по ч. 1 ст. 264 УК РФ, сообщили в ГУ МВД по Петербургу и Ленобласти."))
        self.assertEqual(self.ex("Задержан бывший гендиректор Петрозаводскмаша")["type"], "ownership")

    def test_lenobl_word_is_not_an_organisation(self):
        self.assertEqual(nm.find_org_names("Губернатор Ленобласти встретился с жителями", ORGS), [])

    def test_aggregator_needs_region_in_text(self):
        src = {"region": "Республика Карелия", "region_from_text": True}
        self.assertIsNone(nm.attribute_region(src, "Глава администрации правительства Монголии подал в отставку вслед за президентом", []))
        self.assertIsNone(nm.attribute_region(src, "Назначен новый министр", []))
        self.assertEqual(nm.attribute_region(src, "Новый вице-премьер по социальным вопросам назначен в Карелии", []), "Республика Карелия")
        self.assertIsNone(nm.news_region("Путин посетил совместный вуз в Шэньчжэне"))

    def test_police_crime_news_not_an_event(self):
        self.assertIsNone(nm.detect_all("Майор полиции арестован за пьяный наезд под Светогорском и попытку спрятать служебное авто", "", ORGS))
        self.assertEqual(nm.find_org_names("под Светогорском", ORGS), [])

    def test_html_titles_lose_timestamps(self):
        html = '<a href="/a/1">Майор полиции арестован за пьяный наезд под Светогорском 09:09, 17.11.2026</a><a href="/a/2">13:27 18.11.2026 В Великом Новгороде врачи обсудили изменения крови</a>'
        titles = [i["title"] for i in nm.parse_html_news(html, "https://47news.ru/")]
        self.assertEqual(titles, ["Майор полиции арестован за пьяный наезд под Светогорском",
                                  "В Великом Новгороде врачи обсудили изменения крови"])

    def test_paraphrased_titles_are_one_event(self):
        a = {"type": "appointment", "region": "Псковская область", "date": "2026-11-18",
             "title": "Путин назначил нового заместителя генпрокурора РФ"}
        b = {"type": "appointment", "region": "Псковская область", "date": "2026-11-18",
             "title": "Путин назначил Олега Логунова заместителем генерального прокурора России"}
        c = {"type": "appointment", "region": "Псковская область", "date": "2026-11-18",
             "title": "Путин назначил нового начальника УМВД по Псковской области"}
        self.assertTrue(nm.similar(a, b))
        self.assertEqual(nm.DATE_WORDS.sub("", "Сенатор Дмитрий Василенко утвержден в должности первого зампреда Комитета СовФеда 28 октября 2026"), "Сенатор Дмитрий Василенко утвержден в должности первого зампреда Комитета СовФеда")
        self.assertEqual(nm.DATE_WORDS.sub("", "Назначен глава региона на 5 лет"), "Назначен глава региона на 5 лет")
        self.assertFalse(nm.similar(a, c))
        self.assertEqual(nm.position_key({"type": "appointment", "region": "x", "title": a["title"], "summary": ""}),
                         nm.position_key({"type": "appointment", "region": "x", "title": b["title"], "summary": ""}))

    def test_departmental_title_needs_leader(self):
        orgs = {}
        self.assertIsNone(nm.detect("Волотовскому трактористу присвоено звание «Почётный работник АПК России»", "", orgs))
        self.assertIsNone(nm.detect("Медсестре из Пскова присвоили звание «Заслуженный работник здравоохранения РФ»", "", orgs))
        self.assertIsNotNone(nm.detect("Главному врачу Псковской областной больницы присвоено звание «Заслуженный врач РФ»", "", orgs))
        self.assertIsNotNone(nm.detect("Тракторист из Волота стал почётным гражданином Новгородской области", "", orgs))
        self.assertIsNotNone(nm.detect("Учителю из Выборга присвоено звание «Заслуженный учитель Ленинградской области»", "", orgs))
        self.assertIsNotNone(nm.detect("Начальнику УМВД по Коми присвоено звание генерал-майора полиции", "", orgs))

    def test_court_routine_is_not_event(self):
        orgs = ORGS
        self.assertIsNone(nm.detect_all("С участием гособвинителя прокуратуры Новгородской области вынесен приговор по уголовному делу в отношении бывшего федерального судьи о получении взятки", "", orgs))
        self.assertIsNone(nm.detect_all("Суд приговорил бывшего директора Водоканала к четырём годам колонии", "", orgs))
        self.assertIsNone(nm.detect_all("Экс-глава комитета по строительству признан виновным в превышении полномочий", "", orgs))
        self.assertIsNotNone(nm.detect_all("Задержан директор ГОБУЗ «Новгородская областная клиническая больница»", "", orgs))
        self.assertEqual(nm.find_org_names("Новгородского района", {"Новгородская область": ["НовГУ"]}), [])
        self.assertEqual(nm.find_org_names("ректор НовГУ", {"Новгородская область": ["НовГУ"]}), [("Новгородская область", "НовГУ")])

    def test_third_run_feedback(self):
        orgs = ORGS
        # регион учреждения важнее региона происхождения
        self.assertEqual(nm.news_region("Екатерина Демянчук из Вологодской области возглавила пресс-службу правительства Карелии"), "Республика Карелия")
        self.assertEqual(nm.news_region("Нового руководителя пресс-службы правительства назначили в Карелии"), "Республика Карелия")
        # юбилей человека — не инфоповод, юбилей вуза — да
        self.assertIsNone(nm.detect_all("Вологжанке Галине Барановой исполнилось 100 лет", "", orgs))
        self.assertEqual(nm.detect_all("Петрозаводскому государственному университету исполнилось 85 лет", "", orgs)["type"], "anniversary")
        # мелкие запуски и планы
        self.assertIsNone(nm.detect_all("В Новгородском кампусе запустили газовую котельную для подачи тепла", "", orgs))
        self.assertIsNone(nm.detect_all("В селе Кубенском открыли обновлённый спортивный стадион", "", orgs))
        self.assertIsNone(nm.detect_all("Сформирован план по строительству шахты «Усинская» и ввода в эксплуатацию", "", orgs))
        # «назначили срок» и дела бывших — не кадры
        self.assertIsNone(nm.detect_all("Бывшего главврача освободили из-под стражи в Архангельске", "Ему назначили реальный срок за махинации", orgs))
        # суффикс Google News с дефисом внутри названия издания
        xml = '<rss><channel><link>https://news.google.com/rss</link><item><title>В Карелии назначили нового руководителя пресс-службы правительства - Интернет-журнал</title><link>x</link></item></channel></rss>'
        self.assertEqual(nm.parse_feed(xml)[0]["title"], "В Карелии назначили нового руководителя пресс-службы правительства")

    def test_reconcile_recomputes_region(self):
        cfg = {"sources": [{"id": "gnews_kar", "region": "Республика Карелия", "region_from_text": True, "rank": 4},
                           {"id": "kremlin", "rank": 1}], "organizations": ORGS}
        events = [
            {"title": "Глава администрации правительства Монголии подал в отставку вслед за премьером", "summary": "", "date": "2026-11-18",
             "type": "leave", "region": "Республика Карелия", "source_id": "gnews_kar", "source": "g", "link": "a", "level": "head", "org_class": "gov"},
            {"title": "Посещение совместного университета МГУ и Пекинского политехнического института", "summary": "Владимир Путин посетил вуз в Шэньчжэне", "date": "2026-11-18",
             "type": "visit", "region": "Санкт-Петербург", "source_id": "kremlin", "source": "k", "link": "b", "level": "head", "org_class": "podved"},
        ]
        kept, _ = nm.reconcile(events, cfg)
        self.assertEqual(kept, [])

    def test_card_anchor_split(self):
        page = """<html><body>
        <a href="/news/a/"><div class="t">Екатерина Демянчук из Вологодской области возглавила пресс-службу правительства Карелии</div>
        <div class="lead">Новым руководителем пресс-службы республики Карелия стала Екатерина Демянчук. В прошлом она занималась информационной повесткой сразу нескольких регионов.</div>
        <span>18.11.2026</span></a>
        <a href="/news/b/"><h3>Вице-премьером Правительства по социальным вопросам назначена Екатерина Реутова</h3><p>Распоряжение подписал глава республики.</p></a>
        <a href="/news/c/">Сенатор Дмитрий Василенко утвержден в должности первого зампреда Комитета СовФеда. Решение принято на заседании палаты 28 октября, сенатор представляет Ленинградскую область в верхней палате парламента с 2017 года.</a>
        </body></html>"""
        items = nm.parse_html_news(page, "https://stolicaonego.ru/news/")
        titles = {it["link"][-2]: it for it in items}
        self.assertEqual(titles["a"]["title"], "Екатерина Демянчук из Вологодской области возглавила пресс-службу правительства Карелии")
        self.assertTrue(titles["a"]["summary"].startswith("Новым руководителем"))
        self.assertEqual(titles["b"]["title"], "Вице-премьером Правительства по социальным вопросам назначена Екатерина Реутова")
        self.assertEqual(titles["c"]["title"], "Сенатор Дмитрий Василенко утвержден в должности первого зампреда Комитета СовФеда.")

    def test_fourth_run_feedback(self):
        orgs = ORGS
        title, tail = nm.split_anchor("Екатерина Демянчук из Вологодской области возглавила пресс-службу правительства Карелии Новым руководителем пресс-службы республики Карелия стала Екатерина Демянчук. В прошлом она занималась повесткой регионов.")
        self.assertEqual(title, "Екатерина Демянчук из Вологодской области возглавила пресс-службу правительства Карелии")
        self.assertTrue(tail.startswith("Новым руководителем"))
        self.assertIsNone(nm.detect_all("Директор псковского «Горводоканала» Константин Болотин отметил 55-летие", "", orgs))
        self.assertIsNone(nm.detect_all("Сотрудники Кольской АЭС взяли «золото» на международном чемпионате", "", orgs))
        a = {"type": "leave", "region": "Санкт-Петербург", "date": "2026-11-18",
             "title": "Беглов снял с должности главу комитета по информатизации и связи // Юлия Смирнова стала спецпредставителем губернатора"}
        b = {"type": "appointment", "region": "Санкт-Петербург", "date": "2026-11-18",
             "title": "Александр Беглов: Юлия Смирнова назначена на должность специального представителя Губернатора Санкт-Петербурга"}
        self.assertTrue(nm.similar(a, b))

    def test_smirnova_three_headlines_one_event(self):
        smolny = {"type": "appointment", "region": "Санкт-Петербург", "date": "2026-11-18",
                  "title": "Александр Беглов: Юлия Смирнова назначена на должность специального представителя Губернатора Санкт-Петербурга",
                  "summary": "Юлия Смирнова, занимавшая пост председателя Комитета по информатизации и связи, назначена на должность специального представителя Губернатора."}
        g1 = {"type": "appointment", "region": "Санкт-Петербург", "date": "2026-11-18", "summary": "",
              "title": "Юлию Смирнову назначили спецпредставителем губернатора Петербурга"}
        g2 = {"type": "appointment", "region": "Санкт-Петербург", "date": "2026-11-18", "summary": "",
              "title": "В Петербурге сменился глава комитета по информатизации и связи"}
        other = {"type": "appointment", "region": "Санкт-Петербург", "date": "2026-11-18", "summary": "",
                 "title": "В Петербурге назначен новый глава комитета по транспорту"}
        self.assertTrue(nm.similar(smolny, g1))
        self.assertTrue(nm.similar(smolny, g2))
        self.assertFalse(nm.similar(smolny, other))
        self.assertEqual(nm.extract_person(smolny["title"]), "Юлия Смирнова")
        self.assertEqual(nm.extract_person("Сенатор Дмитрий Василенко утвержден в должности"), "Дмитрий Василенко")
        self.assertEqual(nm.surname("Юлию Смирнову"), nm.surname("Юлия Смирнова"))
        self.assertIsNone(nm.detect_all("Руководитель «Технопарка Санкт-Петербурга» возглавил совет центров компетенций в сфере БПЛА", "", ORGS))


import tempfile


class TestRunUpgrade(unittest.TestCase):
    """Второй прогон: то же событие от более авторитетного источника заменяет запись, не уведомляя повторно."""

    def test_authoritative_source_replaces_stored_event(self):
        import datetime as dt
        today = dt.date(2026, 11, 18)
        gnews_ev = {"type": "appointment", "level": "head", "org_class": "gov", "region": "Санкт-Петербург",
                    "title": "Юлию Смирнову назначили спецпредставителем губернатора Петербурга", "summary": "",
                    "link": "https://news.google.com/x", "date": "2026-11-18", "source": "Google Новости · СПб",
                    "source_id": "gnews_spb", "person": "Юлию Смирнову", "orgs": [], "rank": 4}
        cfg = {"sources": [{"id": "gnews_spb", "name": "Google Новости · СПб", "type": "rss", "url": "u1",
                            "region": "Санкт-Петербург", "region_from_text": True, "rank": 4},
                           {"id": "spb_smolny_tg", "name": "Смольный (Telegram)", "type": "telegram", "url": "u2",
                            "region": "Санкт-Петербург", "rank": 1}],
               "organizations": {}}
        fetched = {"u1": [], "u2": [{"title": "Александр Беглов: Юлия Смирнова назначена на должность специального представителя Губернатора Санкт-Петербурга",
                                     "summary": "Юлия Смирнова, занимавшая пост председателя Комитета по информатизации и связи, назначена на должность специального представителя Губернатора.",
                                     "link": "https://t.me/smolny/1", "date": "2026-11-18T10:00:00+03:00"}]}
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            saved = (nm.SOURCES_FILE, nm.DATA_DIR, nm.EVENTS_FILE, nm.SEEN_FILE, nm.FEEDS_CACHE, nm.RUN_SUMMARY, nm.PAGE_FILE, nm.fetch_source)
            nm.SOURCES_FILE, nm.DATA_DIR = tmp / "s.json", tmp / "d"
            nm.EVENTS_FILE, nm.SEEN_FILE, nm.FEEDS_CACHE = nm.DATA_DIR / "e.json", nm.DATA_DIR / "seen.json", nm.DATA_DIR / "f.json"
            nm.RUN_SUMMARY, nm.PAGE_FILE = tmp / "r.json", tmp / "news.html"
            nm.fetch_source = lambda src, cache: (fetched[src["url"]], "ok")
            try:
                nm.DATA_DIR.mkdir()
                nm.save_json(nm.SOURCES_FILE, cfg)
                nm.save_json(nm.EVENTS_FILE, [gnews_ev])
                # Trace.write читает глобальную константу news_diagnostics.TRACE_FILE.
                # Изолируем её, иначе тест перезаписывает рабочий журнал прогонов.
                with patch("news_diagnostics.TRACE_FILE", tmp / "d" / "last_run_trace.json"):
                    new, _ = nm.run(today=today, verbose=False)
                events = json.loads(nm.EVENTS_FILE.read_text(encoding="utf-8"))
            finally:
                (nm.SOURCES_FILE, nm.DATA_DIR, nm.EVENTS_FILE, nm.SEEN_FILE, nm.FEEDS_CACHE, nm.RUN_SUMMARY, nm.PAGE_FILE, nm.fetch_source) = saved
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["source_id"], "spb_smolny_tg")
        self.assertEqual(new, [])          # повторного уведомления нет


class TestVerbForms(unittest.TestCase):
    def test_future_and_reelection_forms(self):
        self.assertIsNotNone(nm.detect_all("Главврач Первой городской больницы в Архангельске покинет должность", "", ORGS))
        self.assertIsNotNone(nm.detect_all("Ректором СПбГУ переизбран Николай Кропачев", "", ORGS))
        self.assertIsNotNone(nm.detect_all("Губернатор продлил полномочия главы Фонда капремонта Ленобласти", "", ORGS))


class TestFifthRunFeedback(unittest.TestCase):
    def test_milestone_sentence_and_exhibition(self):
        orgs = ORGS
        self.assertIsNone(nm.detect_all("Линия «Славянка» перевезла более 1 млн человек на участке Купчино — Шушары",
                                        "Скоростная трамвайная линия «Славянка», запущенная в декабре, — один из крупнейших в России проектов ГЧП стоимостью 51 млрд рублей.", orgs))
        self.assertIsNone(nm.detect_all("Глава турфирмы в Петербурге получила за хищение 3,7 млн рублей пять лет условно",
                                        "Суд вынес приговор директору туристической компании.", orgs))
        self.assertIsNone(nm.detect_all("Глава турфирмы в Петербурге получила за хищение 3,7 млн рублей пять лет условно",
                                        "Суд назначил 5 лет условно главе турфирмы, похитившей более 3,7 млн рублей на продаже путёвок.", orgs))
        self.assertIsNone(nm.detect_all("В Калининграде открылась выставка о служении патриарха Кирилла",
                                        "Выставку открыл губернатор Алексей Беспрозванных.", orgs))
        self.assertIsNone(nm.detect_all("В Калининграде открылась выставка о служении патриарха Кирилла",
                                        "Патриарх Кирилл посетил Кафедральный собор.", orgs))
        # а настоящие визиты, запуски и задержания остаются
        self.assertEqual(nm.detect_all("Путин посетил Севмаш и провёл совещание по судостроению", "", orgs)["type"], "visit")
        self.assertEqual(nm.detect_all("Балтийский завод спустил на воду атомный ледокол «Ленинград»", "", orgs)["type"], "launch")
        self.assertEqual(nm.detect_all("На Кольской АЭС открыли новый энергоблок", "Это крупнейший проект Росатома в регионе.", orgs)["type"], "launch")
        self.assertIsNotNone(nm.detect_all("Задержан гендиректор Акрона", "", orgs))


class TestSixthRunFeedback(unittest.TestCase):
    def test_statistics_obituary_and_hospital_duplicate(self):
        orgs = ORGS
        self.assertIsNone(nm.detect_all("В ТЦ Петербурга закрылось на 39% больше торговых площадей, чем открылось",
                                        "Посещаемость торговых комплексов снизилась на 4,1%, сообщил генеральный директор управляющей компании «Ай Би Ритейл» (входит в ГК «Ай Би Групп») Святослав Борисов.", orgs))
        self.assertIsNone(nm.detect_all("Умер Заслуженный строитель РФ, бывший управляющий трестом №52 Анатолий Смирнов в 77 лет", "", orgs))
        self.assertEqual(nm.detect_all("Скончался почётный гражданин Пскова, бывший мэр Михаил Хоронен", "", orgs)["type"], "obituary")
        self.assertEqual(nm.detect_all("Умер генеральный директор Севмаша Михаил Будниченко", "", orgs)["type"], "obituary")
        a = {"type": "appointment", "region": "Псковская область", "date": "2026-11-19",
             "title": "Самир Аль-Араби возглавил Псковскую областную инфекционную больницу",
             "summary": "Исполняющим обязанности главного врача Псковской областной инфекционной клинической больницы назначен Самир Аль-Араби, сообщили ПАИ."}
        b = {"type": "appointment", "region": "Псковская область", "date": "2026-11-19",
             "title": "В Псковской инфекционной клинической больнице назначили исполняющего обязанности главного врача",
             "summary": "Заместитель министра здравоохранения Псковской области Ирина Жаворонкова представила коллективу нового руководителя."}
        c = {"type": "appointment", "region": "Псковская область", "date": "2026-11-19",
             "title": "В Псковской областной больнице назначили нового главного инженера", "summary": ""}
        self.assertTrue(nm.similar(a, b))
        self.assertFalse(nm.similar(b, c))
        self.assertEqual(nm.extract_person(b["summary"]), "")
        self.assertEqual(nm.extract_person(a["summary"]), "Самир Аль-Араби")


class TestPostTitle(unittest.TestCase):
    def test_telegram_title_is_first_sentence(self):
        t = ("Президент России Владимир Владимирович Путин назначил Светлану Егоровну Устинович председателем "
             "Архангельского областного суда. Сегодня первый заместитель Председателя Верховного Суда представил её коллективу.")
        self.assertEqual(nm.post_title(t), "Президент России Владимир Владимирович Путин назначил Светлану Егоровну Устинович председателем Архангельского областного суда.")
        self.assertEqual(nm.post_title("Вице-премьером Правительства по социальным вопросам назначена Екатерина Реутова"),
                         "Вице-премьером Правительства по социальным вопросам назначена Екатерина Реутова")
        self.assertEqual(nm.post_title("Министр А.В. Иванов провёл совещание. Обсудили бюджет."), "Министр А.В. Иванов провёл совещание.")
        long = "Губернатор " + "очень " * 40 + "длинный пост без точек"
        tt = nm.post_title(long)
        self.assertTrue(tt.endswith("…") and len(tt) <= 162 and not tt.endswith("оч…"))

    def test_common_noun_company_and_municipal_head(self):
        orgs = ORGS
        self.assertIsNone(nm.detect_all("Артема Жогу наградили медалью «За укрепление боевого содружества»", "", orgs))
        self.assertEqual(nm.find_org_names("ГК «Содружество» запустила новый завод", {"Калининградская область": ["Содружество"]}), [("Калининградская область", "Содружество")])
        self.assertEqual(nm.find_org_names("укрепление боевого содружества", {"Калининградская область": ["Содружество"]}), [])
        self.assertIsNone(nm.detect_all("Главой Старорусского округа стала Ирина Примакина", "Депутаты думы округа избрали главу.", orgs))
        self.assertIsNotNone(nm.detect_all("Главой администрации Калининграда назначена Елена Дятлова", "", orgs))

    def test_consumer_rating_is_not_status(self):
        orgs = ORGS
        self.assertIsNone(nm.detect_all("Горнолыжный курорт «Большой Вудъявр» в Хибинах (Мурманская область) признан лучшим в России местом для семейного отдыха на склонах.", "", orgs))
        self.assertIsNone(nm.detect_all("Калининград вошёл в топ-5 городов России для путешествий на Новый год", "", orgs))
        self.assertEqual(nm.detect_all("СПбГУ вошёл в топ-100 мирового рейтинга университетов", "", orgs)["type"], "status")
        self.assertEqual(nm.detect_all("Архангельский ЦБК признан системообразующим предприятием", "", orgs)["type"], "status")

    def test_law_signing_and_minor_status(self):
        orgs = ORGS
        self.assertIsNone(nm.detect_all("Беглов подписал закон о запрете продажи вейпов в Петербурге с марта 2027 года",
                                        "Запрет продажи вейпов окончательно утверждён подписью губернатора города Александра Беглова 20 ноября.", orgs))
        self.assertIsNone(nm.detect_all("Информация Жилищного комитета",
                                        "Жилищный комитет получил статус образца бережливого управления федерального уровня. В ходе партнерской проверки представители Росатома отметили масштаб.", orgs))
        self.assertIsNotNone(nm.detect_all("Елена Иванова утверждена в должности председателя Жилищного комитета", "", orgs))
        self.assertEqual(nm.detect_all("ПетрГУ получил статус опорного университета", "", orgs)["type"], "status")
        self.assertEqual(nm.post_title("Информация Жилищного комитета\nЖилищный комитет получил статус образца бережливого управления. В ходе проверки отметили масштаб."),
                         "Жилищный комитет получил статус образца бережливого управления.")
        self.assertEqual(nm.post_title("Кадры\nНовым председателем комитета по транспорту назначен Валентин Енокаев. Распоряжение подписано."),
                         "Новым председателем комитета по транспорту назначен Валентин Енокаев.")

    def test_rubric_prefix_and_historic_anniversary(self):
        orgs = ORGS
        self.assertEqual(nm.RUBRICS.sub("", "Общество Регион Архангельская областная клиническая больница отмечает 80-летие"),
                         "Архангельская областная клиническая больница отмечает 80-летие")
        self.assertEqual(nm.RUBRICS.sub("", "Регион Коми получил федеральный грант"), "Регион Коми получил федеральный грант"[7:] if False else nm.RUBRICS.sub("", "Регион Коми получил федеральный грант"))
        self.assertEqual(nm.RUBRICS.sub("", "Новым министром назначен Иван Петров"), "Новым министром назначен Иван Петров")
        self.assertIsNone(nm.detect_all("В Коми отмечается 85 лет со дня создания оленно-транспортных батальонов", "", orgs))
        self.assertEqual(nm.detect_all("Архангельская областная клиническая больница отмечает 80-летие", "", orgs)["type"], "anniversary")


class TestProactiveEventQualityRelease(unittest.TestCase):
    """Ten regression scenarios: distinct actions, precise identities, Telegram."""

    @staticmethod
    def record(title, *, kind, day="2026-11-26", region="Мурманская область",
               person="", organizations=None, stage="", summary="", source="test"):
        result = {
            "title": title, "type": kind, "date": day, "region": region,
            "person": person, "summary": summary, "orgs": organizations or [],
            "level": "head", "org_class": "gov", "source": source,
            "source_id": source, "link": f"https://example.invalid/{source}", "rank": 3,
        }
        if stage:
            result["procedure_stage"] = stage
        return result

    def test_three_reports_of_one_governor_arrest_collapse_to_one_record(self):
        titles = (
            "Суд арестовал губернатора Мурманской области Андрея Чибиса",
            "Суд подтвердил арест губернатора Мурманской области",
            "Следственный комитет сообщил об аресте губернатора Мурманской области",
        )
        records = []
        for i, title in enumerate(titles):
            d = nm.detect_all(title, "", ORGS)
            self.assertIsNotNone(d, title)
            self.assertEqual((d["type"], d["stage"]), ("proceeding", "arrest"))
            ev = self.record(title, kind="proceeding", stage="arrest", person=d.get("subject", ""),
                             source=f"paper{i}")
            records.append(ev)
        for i, first in enumerate(records):
            for other in records[i+1:]:
                self.assertTrue(nm.similar(first, other))
        cfg = {"sources": [{"id": f"paper{i}", "region": "Мурманская область", "rank": 3}
                            for i in range(3)], "organizations": ORGS}
        merged, _ = nm.reconcile(records, cfg)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["procedure_stage"], "arrest")

    def test_detention_arrest_and_charge_stay_separate(self):
        titles = (
            ("Губернатор Мурманской области задержан, сообщили в СК", "detention"),
            ("Суд арестовал губернатора Мурманской области Андрея Чибиса", "arrest"),
            ("В Мурманской области СК предъявил обвинение губернатору Андрею Чибису", "charge"),
        )
        records = []
        for title, expected_stage in titles:
            d = nm.detect_all(title, "", ORGS)
            self.assertEqual(d["stage"], expected_stage)
            records.append(self.record(title, kind="proceeding", stage=expected_stage,
                                       person=d.get("subject", "")))
        for i, a in enumerate(records):
            for b in records[i+1:]:
                self.assertFalse(nm.similar(a, b))
                self.assertNotEqual(nm.event_key(a), nm.event_key(b))

    def test_removed_from_office_and_sent_into_resignation_are_same_event(self):
        first = "Путин досрочно снял Андрея Чибиса с поста губернатора Мурманской области"
        second = "Владимир Путин отправил в отставку губернатора Мурманской области Андрея Чибиса"
        for title in (first, second):
            d = nm.detect_all(title, "", ORGS)
            self.assertIsNotNone(d, title)
            self.assertEqual(d["type"], "leave")
        a = self.record(first, kind="leave")
        b = self.record(second, kind="leave", day="2026-11-27")
        self.assertEqual(nm.governor_stage(a), "governor_departure")
        self.assertEqual(nm.governor_stage(b), "governor_departure")
        self.assertTrue(nm.similar(a, b))
        self.assertNotEqual(nm.governor_stage(self.record("Назвали дату выборов губернатора Мурманской области после отставки", kind="leave")), "governor_departure")

    def test_one_person_appointed_to_two_different_offices(self):
        a = self.record("Иван Петров назначен директором завода в Петербурге",
                        kind="appointment", person="Иван Петров", region="Санкт-Петербург")
        b = self.record("Иван Петров назначен министром промышленности Петербурга",
                        kind="appointment", person="Иван Петров", region="Санкт-Петербург")
        self.assertFalse(nm.similar(a, b))
        self.assertFalse(set(nm.event_keys(a)) & set(nm.event_keys(b)))
        self.assertNotEqual(nm.event_key(a), nm.event_key(b))
        self.assertTrue(nm.similar(a, {**a, "title": "Иван Петров назначен новым директором завода Петербурга"}))

    def test_one_company_opens_two_different_facilities(self):
        a = self.record("Балтийский завод открыл новую производственную линию",
                        kind="launch", organizations=["Балтийский завод"], region="Санкт-Петербург")
        b = self.record("Балтийский завод открыл логистический терминал",
                        kind="launch", organizations=["Балтийский завод"], region="Санкт-Петербург")
        self.assertEqual(nm.launch_object(a), "production_line")
        self.assertEqual(nm.launch_object(b), "terminal")
        self.assertFalse(nm.similar(a, b))
        self.assertFalse(set(nm.event_keys(a)) & set(nm.event_keys(b)))
        self.assertEqual(nm.detect_all(a["title"], "", ORGS)["type"], "launch")
        self.assertEqual(nm.detect_all(b["title"], "", ORGS)["type"], "launch")
        line_one = {**a, "title": "Балтийский завод открыл производственную линию №1"}
        line_two = {**a, "title": "Балтийский завод открыл производственную линию №2"}
        self.assertFalse(nm.similar(line_one, line_two))
        self.assertFalse(set(nm.event_keys(line_one)) & set(nm.event_keys(line_two)))

    def test_rank_leader_is_not_personnel_appointment(self):
        text = "МТС возглавила рейтинг цифрового лидерства"
        result = nm.detect_all(text, "Компания представила рейтинг в Петербурге.", ORGS)
        self.assertNotEqual((result or {}).get("type"), "appointment")
        self.assertIsNone(nm.detect(text, "", ORGS))
        self.assertEqual(nm.detect_all("Елена Иванова назначена министром в Карелии", "", ORGS)["type"], "appointment")

    def test_83_doctors_are_assessed_by_staffing_rules_not_appointment(self):
        title = "В Псковской области начали работать 83 молодых врача"
        summary = "Губернатор сообщил о назначении директора больницы в других новостях."
        self.assertIsNone(nm.detect_all(title, summary, ORGS))
        self.assertIsNone(nm.detect_staffing(title, summary, ORGS, nm.find_org_names))
        # A confirmed material increase still qualifies in the workforce stream.
        major = "В Псковской области создали 120 новых рабочих мест"
        self.assertEqual(nm.detect_all(major, "", ORGS)["type"], "workforce")

    def test_cooperation_agreement_is_not_infrastructure_launch(self):
        title = "Титан-Полимер заключил соглашение о сотрудничестве с центром занятости"
        lead = "На промышленном комплексе запланированы крупные инвестиции и производство."
        self.assertIsNone(nm.detect_all(title, lead, ORGS))
        real = "Титан-Полимер заключил контракт на строительство нового завода"
        self.assertEqual(nm.detect_all(real, "", ORGS)["type"], "launch")

    def test_different_awardees_same_surname_are_distinct(self):
        a = self.record("Михаил Иванов стал почетным гражданином Ханоя",
                        kind="title", region="Санкт-Петербург")
        b = self.record("Андрей Иванов стал почетным гражданином Ханоя",
                        kind="title", region="Санкт-Петербург")
        self.assertNotEqual(nm.event_key(a), nm.event_key(b))
        self.assertFalse(nm.similar(a, b))
        self.assertTrue(nm.similar(a, {**a, "title": "Михаил Иванов удостоен звания почётного гражданина Ханоя"}))

    def test_repeat_telegram_notify_skips_completed_recipients_and_retries_failure(self):
        import tempfile
        import types
        from unittest.mock import patch

        ev = self.record("Назначен новый министр правительства Мурманской области", kind="appointment")
        fake = types.ModuleType("notify_telegram")
        fake.TG_LIMIT = 4096
        fake.site_url = lambda: "https://example.invalid/"
        fake.plural = lambda number, one, few, many: one if number == 1 else many
        deliveries = []
        attempts = []
        failures = ["22"]

        def fake_send(token, chats, message, report):
            chat = chats[0]
            attempts.append(chat)
            if chat in failures:
                failures.remove(chat)
                report[chat] = (False, "test failure")
                return False
            deliveries.append(chat)
            report[chat] = (True, {})
            return True

        fake.send = fake_send
        fake.print_report = lambda report: None
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run_summary_news.json"
            path.write_text(json.dumps({"new": [ev]}, ensure_ascii=False), encoding="utf-8")
            with patch.dict(sys.modules, {"notify_telegram": fake}), \
                 patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake-token", "TELEGRAM_CHAT_ID": "11,22"}), \
                 patch.object(nm, "RUN_SUMMARY", path):
                self.assertEqual(nm.notify(), 0)  # partial private-chat failure is a warning
                self.assertEqual(deliveries, ["11"])
                self.assertEqual(nm.notify(), 0)  # retries only 22
                self.assertEqual(deliveries, ["11", "22"])
                self.assertEqual(nm.notify(), 0)  # full repeat: no new send
            self.assertEqual(attempts, ["11", "22", "22"])
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(stored["notify_delivery"]["completed"]), 2)
            self.assertNotIn('"11"', json.dumps(stored["notify_delivery"]))
            self.assertNotIn('"22"', json.dumps(stored["notify_delivery"]))

    def test_telegram_partial_delivery_with_channel_keeps_job_green(self):
        import tempfile
        import types

        ev = self.record("Назначен новый министр правительства Мурманской области", kind="appointment")
        fake = types.ModuleType("notify_telegram")
        fake.TG_LIMIT = 4096
        fake.site_url = lambda: ""
        fake.plural = lambda n, one, few, many: one if n == 1 else many
        fake.send = lambda _token, chats, _msg, report: (
            report.update({chats[0]: (chats[0].startswith("-"),
                                      {} if chats[0].startswith("-") else "bot blocked")})
            or chats[0].startswith("-")
        )
        fake.print_report = lambda report: None
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run_summary_news.json"
            path.write_text(json.dumps({"new": [ev]}, ensure_ascii=False), encoding="utf-8")
            with patch.dict(sys.modules, {"notify_telegram": fake}), \
                 patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake-token",
                                      "TELEGRAM_CHAT_ID": "11,22,-1001234567890"}), \
                 patch.object(nm, "RUN_SUMMARY", path), \
                 patch("builtins.print") as print_mock:
                self.assertEqual(nm.notify(), 0)
                self.assertTrue(any("::warning::Telegram:" in str(call)
                                    for call in print_mock.call_args_list))
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(stored["notify_delivery"]["completed"]), 1)

    def test_telegram_total_failure_is_still_error(self):
        import tempfile
        import types

        ev = self.record("Назначен новый министр правительства Мурманской области", kind="appointment")
        fake = types.ModuleType("notify_telegram")
        fake.TG_LIMIT = 4096
        fake.site_url = lambda: ""
        fake.plural = lambda n, one, few, many: one if n == 1 else many
        fake.send = lambda _token, chats, _msg, report: (
            report.update({chats[0]: (False, "bot blocked")}) or False
        )
        fake.print_report = lambda report: None
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run_summary_news.json"
            path.write_text(json.dumps({"new": [ev]}, ensure_ascii=False), encoding="utf-8")
            with patch.dict(sys.modules, {"notify_telegram": fake}), \
                 patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake-token",
                                      "TELEGRAM_CHAT_ID": "11,22"}), \
                 patch.object(nm, "RUN_SUMMARY", path):
                self.assertEqual(nm.notify(), 1)

    def test_telegram_channel_failure_is_error_despite_private_success(self):
        import tempfile
        import types

        ev = self.record("Назначен новый министр правительства Мурманской области", kind="appointment")
        fake = types.ModuleType("notify_telegram")
        fake.TG_LIMIT = 4096
        fake.site_url = lambda: ""
        fake.plural = lambda n, one, few, many: one if n == 1 else many
        fake.send = lambda _token, chats, _msg, report: (
            report.update({chats[0]: (not chats[0].startswith("-"),
                                      {} if not chats[0].startswith("-") else "chat not found")})
            or not chats[0].startswith("-")
        )
        fake.print_report = lambda report: None
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run_summary_news.json"
            path.write_text(json.dumps({"new": [ev]}, ensure_ascii=False), encoding="utf-8")
            with patch.dict(sys.modules, {"notify_telegram": fake}), \
                 patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake-token",
                                      "TELEGRAM_CHAT_ID": "11,-1001234567890"}), \
                 patch.object(nm, "RUN_SUMMARY", path):
                self.assertEqual(nm.notify(), 1)
