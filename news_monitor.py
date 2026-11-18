"""Мониторинг новостей СЗФО: назначения руководителей и новые звания.

Второй поток szfo-monitor. Указы Президента ловит generate.py; этот скрипт
читает новостные ленты (RSS, страницы новостей, публичные Telegram-каналы)
и выбирает два типа событий:

  1. звание   — региональные звания («Почётный гражданин …», «Заслуженный …
               области»), генеральские и специальные звания руководителям
               ведомств в регионе;
  2. назначение — назначен / возглавил / освобождён от должности руководитель
               или заместитель: правительство региона, подведомственные
               учреждения, крупнейшие компании, МВД, ФСИН, Росгвардия, МЧС,
               прокуратура, Следственный комитет.

Запуск:
    python news_monitor.py            — прогон: собрать ленты, найти события,
                                        обновить data/news/*.json и news.html,
                                        записать run_summary_news.json
    python news_monitor.py --check    — проверить доступность всех источников
                                        (таблица в лог, ничего не сохраняется)
    python news_monitor.py --rebuild  — пересобрать news.html из сохранённых событий
    python news_monitor.py --notify   — отправить новые события в Telegram

Источники и словарь организаций — в news_sources.json.
"""
import argparse
import html as html_module
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

import generate as g

SOURCES_FILE = Path("news_sources.json")
DATA_DIR = Path("data/news")
EVENTS_FILE = DATA_DIR / "events.json"
SEEN_FILE = DATA_DIR / "seen.json"
FEEDS_CACHE = DATA_DIR / "feeds.json"
RUN_SUMMARY = Path("run_summary_news.json")
PAGE_FILE = Path("news.html")

KEEP_EVENTS_DAYS = 120       # сколько держать события на странице
KEEP_SEEN_DAYS = 45          # память дедупликации
FRESH_DAYS = 4               # новости старше не берём (ленты дают историю)
TIMEOUT = 15
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; szfo-monitor/1.0; +https://github.com/)",
           "Accept-Language": "ru,en;q=0.5"}

esc = html_module.escape


# ═══════════════════════════════════════════════════════════════════════
# Детекция событий
# ═══════════════════════════════════════════════════════════════════════

# ── Назначения ──
APPOINT_VERB = re.compile(
    r"\b(?:назнач(?:ен[аоы]?|ил[аио]?|ат|ит)\b|возглавил[аи]?|возглавит|возглавят|"
    r"избран[аы]?\b|избрали|утвержд[её]н[аы]?\b|утвердил[аи]?|вступил[аи]?\s+в\s+должност|"
    r"приступил[аи]?\s+к\s+(?:работе|исполнению|обязанност)|стал[аи]?\s+(?:новым\s+)?(?:главой|руководителем|"
    r"директором|начальником|председателем|министром|ректором|прокурором|заместителем|"
    r"вице-|зам|и\.о\.|врио|временным)|станет\s+(?:новым\s+)?(?:главой|руководителем|директором|"
    r"начальником|председателем|министром|ректором|заместителем|вице-|зам)|"
    r"представил[аи]?\s+(?:нового|новую|коллективу|личному\s+составу)|сменил[аи]?|сменит|"
    r"новы[йм]\s+(?:глав[аы]|руководител|директор|начальник|председател|министр|ректор|прокурор|"
    r"зам|вице-)|новая\s+(?:глава|руководитель|директор|начальник|председатель|министр)|"
    r"врио|временно\s+исполняющ|и\.\s?о\.\s+(?:глав|руковод|директор|начальник|министр|председател|прокурор)|"
    r"сменил[аи]?сь|сменился|сформировал[аи]?\s+(?:новое\s+)?правительств|перераспредел\w+\s+полномочи|"
    r"нов\w+\s+состав\w*\s+правительств|обновил[аи]?\s+(?:состав|правительств)|кадров\w+\s+(?:перестановк|изменени|решени))",
    re.I)
# «возглавил комитет» — должность следует из глагола, отдельного слова-должности не нужно
HEAD_VERB = re.compile(r"\bвозглавил[аи]?\b|\bвозглавит\b|\bвозглавят\b|сформировал[аи]?\s+(?:новое\s+)?правительств|"
                       r"перераспредел\w+\s+полномочи|нов\w+\s+состав\w*\s+правительств|кадров\w+\s+(?:перестановк|изменени|решени)", re.I)
# «… руководителем … стала Наталья Волкова», «станет художественным руководителем»
INSTRUMENTAL = re.compile(
    r"\b(?:руководителем|главой|директором|гендиректором|начальником|председателем|министром|прокурором|"
    r"заместителем|зампредом|ректором|худруком|вице-губернатором|вице-премьером|губернатором|управляющим|"
    r"командующим|главврачом|главным\s+(?:врачом|редактором|инженером|архитектором)|и\.\s?о\.|врио)", re.I)
BECOME = re.compile(r"\bстал[аи]?\b|\bстанет\b|\bстанут\b", re.I)
LEAVE_VERB = re.compile(
    r"\b(?:покинул[аи]?\s+(?:пост|должност|свой\s+пост)|покидает\s+(?:пост|должност)|уходит\s+(?:в\s+отставку|с\s+поста|"
    r"с\s+должности)|уш[её]л\s+(?:в\s+отставку|с\s+поста)|ушла\s+(?:в\s+отставку|с\s+поста)|"
    r"отставк[аеиу]|освобожд[её]н[аы]?\s+от\s+должност|освободил[аи]?\s+от\s+должност|"
    r"отправлен[аы]?\s+в\s+отставку|уволен[аы]?|лишил[аи]?сь\s+(?:поста|должности)|сложил[аи]?\s+полномочия)",
    re.I)
POSITION = re.compile(
    r"\b(?:губернатор|вице-губернатор|глав(?:а|ы|у|е|ой|ою)\b|руководител|председател|зампред|заместител|"
    r"министр|директор|гендиректор|генеральн\w+\s+директор|начальник|ректор|главн(?:ый|ого|ым|ому)\s+врач|"
    r"главврач|прокурор|управляющ|командующ|командир|президент|вице-президент|вице-премьер|"
    r"первы[йм]\s+зам|и\.\s?о\.|врио|худрук|художественн\w+\s+руководител|главн\w+\s+редактор|"
    r"главн\w+\s+инженер|главн\w+\s+архитектор|главн\w+\s+федеральн\w+\s+инспектор|сити-менеджер)",
    re.I)
ORG_GOV = re.compile(
    r"\b(?:правительств|администраци|губернатор|комитет|министерств|министр|департамент|управлени|агентств|"
    r"служб|инспекци|заксобрани|законодательн|областн\w+\s+дум|городск\w+\s+дум|областн\w+\s+собрани|"
    r"госсовет|государственн\w+\s+совет|вице-губернатор|зампред|смольн|аппарат|"
    r"глав(?:а|ы|у|е|ой|ою)\s+(?:\S+\s+){0,2}?(?:регион|област|республик|кра[яюе]|города|субъект)|врио\s+глав)", re.I)
ORG_FORCE = re.compile(
    r"(?:\bМВД\b|\bУМВД\b|\bГУ\s*МВД\b|полици|\bФСИН\b|\bУФСИН\b|\bГУФСИН\b|Росгварди|\bМЧС\b|прокурор|"
    r"прокуратур|\bСКР?\b|\bСУ\s*СК\b|следственн\w+\s+(?:комитет|управлени|отдел)|Следком|\bФСБ\b|"
    r"таможн|\bУФНС\b|налогов\w+\s+(?:служб|инспекц)|Роспотребнадзор|Росприроднадзор|Ростехнадзор|"
    r"Россельхознадзор|\bУФАС\b|антимонопольн|Росреестр|Соцфонд|\bСФР\b|судебн\w+\s+пристав|\bУФССП\b|"
    r"\bВС\s+РФ\b|военн\w+\s+комиссар)", re.I)
ORG_PODVED = re.compile(
    r"\b(?:больниц|клиническ|поликлиник|медицинск\w+\s+(?:центр|учрежден)|медцентр|диспансер|университет|"
    r"институт|академи|\bвуз|театр|филармони|музе[йяею]|библиотек|водоканал|фонд\w*\s+капитальн|"
    r"фонд\w*\s+капремонт|региональн\w+\s+оператор|аэропорт|\bпорт[а-я]*\b|метрополитен|\bГУП\b|\bГБУ\b|"
    r"\bГАУ\b|\bМФЦ\b|центр\w*\s+занятост|\bТЭК\b|корпораци\w+\s+развити|агентств\w+\s+(?:инвестиц|развити)|"
    r"телеканал|\bГТРК\b|\bМУП\b|\bГКУ\b|стадион|спортшкол|дворц|ледов)", re.I)
ORG_BUSINESS = re.compile(
    r"\b(?:завод|комбинат|\bЦБК\b|\bГОК\b|\bЛПК\b|\bГМК\b|\bАЭС\b|\bГРЭС\b|\bТЭЦ\b|холдинг|корпораци|"
    r"компани|\bбанк|концерн|верф|пароходств|флот|железн\w+\s+дорог|энерго|\bПАО\b|\bАО\b|\bООО\b|"
    r"\bГК\b|групп\w+\s+компани|предприяти|фабрик|рудник|шахт|месторожден|\bСПГ\b|нефт|газ\w*\b|"
    r"девелопер|ритейл|сет[ьи]\s+магазин|авиакомпани|перевозчик)", re.I)

# ── Звания ──
TITLE_VERB = re.compile(
    r"\b(?:присво(?:ен|ена|ено|ены|ил|ила|или|ят|ит)\w*|удостоен[аы]?|удостоил[аи]?|получил[аи]?\s+(?:звани|"
    r"почётн|почетн|погоны|генеральск)|стал[аи]?\s+(?:почётн|почетн|заслуженн|народн|генерал|"
    r"контр-адмирал|вице-адмирал)|избран[аы]?\s+почётн|избран[аы]?\s+почетн|избрали\s+почётн|избрали\s+почетн|"
    r"пополнил[аи]?\s+(?:список|ряды)\s+почётн|пополнил[аи]?\s+(?:список|ряды)\s+почетн|"
    r"вручил[аи]?\b|вручен[аы]?\b|пополнил[аи]?\b)",
    re.I)
# слабые глаголы («вручили», «пополнили») считаются только с сильным существительным
WEAK_TITLE_VERB = re.compile(r"\b(?:вручил[аи]?|вручен[аы]?|пополнил[аи]?)\b", re.I)
STRONG_TITLE_NOUN = re.compile(r"(?:звани[еяюй]|почётн|почетн|заслуженн|народн\w+\s+(?:артист|художник|учител|врач))", re.I)
TITLE_NOUN = re.compile(
    r"(?:звани[еяюй]|почётн\w+\s+граждан\w*|почетн\w+\s+граждан\w*|почётн\w+\s+благотворител\w*|почетн\w+\s+благотворител\w*|"
    r"заслуженн\w+\s+(?:работник|учител|врач|артист|деятел|строител|юрист|эконом|энергетик|мастер|"
    r"тренер|художник|архитектор|геолог|метеоролог|лесовод|машиностроител|металлург|спасател|сотрудник|"
    r"\w+\s+(?:Санкт-Петербурга|Ленинградской|Архангельской|Вологодской|Калининградской|Мурманской|"
    r"Псковской|Новгородской|Республики|Карелии|Коми))|народн\w+\s+(?:артист|художник|учител|врач)|"
    r"генерал-майор|генерал-лейтенант|генерал-полковник|генерал\s+армии|контр-адмирал|вице-адмирал|"
    r"\bгенерал[аеу]?\b|погон\w*\s+генерал|высш\w+\s+(?:офицер|начальствующ))", re.I)

# ── Что исключаем ──
UNCERTAIN = re.compile(
    r"\b(?:кандидат|конкурс|голосовани|претендент|может\s+(?:стать|возглавить|быть\s+назначен)|могут\s+(?:назначить|"
    r"присвоить|стать)|планиру|предлож|предлага|обсужда|слух|прочат|рассматрива|не\s+исключ|"
    r"хотят\s+(?:назначить|присвоить)|выдвину|номинир|отбор\s+кандидат|объявлен\s+конкурс|выберут|присвоят\s+не\s+более|"
    r"не\s+более\s+\w+\s+звани|закон\w*\s+о\s+звани|положени\w*\s+о\s+звани|порядок\s+присвоения|лиш[её]н|лишил|"
    r"посмертно|годовщин|юбиле|день\s+рождения|скончал|умер\b|памяти)", re.I)
NOT_OUR_SCOPE = re.compile(
    r"\b(?:тренер|сборн\w+\s+(?:России|страны|команд)|футбольн|хоккейн|волейбольн|баскетбольн|клуб[аеу]?\b|"
    r"\bФК\b|\bХК\b|капитан\w*\s+команд|школ[аыуе]\b|школы\s+№|детск\w+\s+сад|лице[йя]|гимнази|"
    r"сельск\w+\s+поселен|городск\w+\s+поселен|муниципальн\w+\s+(?:образовани|район|округ)|"
    r"приход|епархи|митрополит|настоятел|батюшк|блогер|шоу|сериал|фильм[аеу]?\b|телешоу|"
    r"церемони\w+\s+награждения\s+(?:конкурс|премии)|премии\s+«|лауреат|"
    r"секретар\w+\s+(?:\S+\s+){0,3}?отделени|парти[ияюе]\b|единой\s+росси|единая\s+россия|\bлдпр\b|\bкпрф\b|"
    r"справедлив\w+\s+росси|новые\s+люди|избран\w*\s+депутат|целев\w+\s+назначени|по\s+назначению|"
    r"назначени[ея]\s+(?:платеж|пособи|выплат|пенси|экспертиз|наказани))", re.I)
# «присвоил имя скверу» — не звание
NAME_GIVING = re.compile(r"присво\w+\s+(?:им[яе]н?\w*|названи|наименовани|статус|категори|адрес)", re.I)
# главы районов — только внутри Санкт-Петербурга (это не муниципалитеты)
DISTRICT_HEAD = re.compile(r"глав\w*\s+(?:администрации\s+)?\S+\s+района", re.I)

DEPUTY = re.compile(r"\b(?:заместител|зампред|вице-|первы[йм]\s+зам|замглав|замначальник|замминистр|"
                    r"замдиректор|замруководител)", re.I)


def normalize(text):
    """Неразрывные и типографские дефисы → обычный, пробелы схлопываем."""
    return re.sub(r"[ \t]+", " ", (text or "").replace("\u2011", "-").replace("\u2010", "-")
                  .replace("\u00ad", "").replace("\xa0", " "))


def first_sentence(text, limit=180):
    text = text.strip()
    m = re.search(r"[.!?]\s", text)
    return text[:m.end()] if m and m.end() <= limit else text[:limit]


def classify_org(text):
    """Класс организации по тексту: gov / force / podved / business / None."""
    if ORG_FORCE.search(text):
        return "force"
    if ORG_GOV.search(text):
        return "gov"
    if ORG_PODVED.search(text):
        return "podved"
    if ORG_BUSINESS.search(text):
        return "business"
    return None


_ORG_CACHE = {}


def org_pattern(name):
    """«Северсталь» → \bсеверстал\w* : ловим падежи («Северстали», «Севмаша»)."""
    pat = _ORG_CACHE.get(name)
    if pat is None:
        words = name.split()
        last = words[-1]
        if len(last) > 4 and last[-1].lower() in "ьаяыиоеую":
            last = last[:-1]
        stem = r"\s+".join(re.escape(w) for w in words[:-1] + [last])
        pat = re.compile(r"(?<![а-яёa-z])" + stem + r"\w*", re.I)
        _ORG_CACHE[name] = pat
    return pat


def find_org_names(text, organizations):
    """Названия организаций из словаря, упомянутые в тексте → [(регион, название)]."""
    found = []
    for region, names in organizations.items():
        for name in names:
            if org_pattern(name).search(text):
                found.append((region, name))
    return found


def detect(title, summary, organizations):
    """Возвращает описание события или None.

    {"type": "appointment"|"title"|"leave", "level": "head"|"deputy",
     "org_class": ..., "orgs": [...], "hints": [...]}"""
    title = normalize(title)
    summary = normalize(summary or "")
    text = f"{title}\n{summary}"
    head = title + " " + summary[:300]            # должность и организация — заголовок и начало текста
    lead = title + " " + first_sentence(summary)  # глагол события — только заголовок и первая фраза

    if UNCERTAIN.search(head) or NOT_OUR_SCOPE.search(head):
        return None

    orgs = find_org_names(text, organizations)
    org_class = classify_org(head)

    # ── Звание ──
    tv = TITLE_VERB.search(lead)
    if tv and TITLE_NOUN.search(head) and not NAME_GIVING.search(head) \
            and (not WEAK_TITLE_VERB.fullmatch(tv.group(0)) or STRONG_TITLE_NOUN.search(head)):
        return {"type": "title", "level": "head", "org_class": org_class or "person", "orgs": orgs}

    # ── Назначение / уход ──
    has_pos = POSITION.search(head)
    appoint = APPOINT_VERB.search(lead) or (BECOME.search(lead) and INSTRUMENTAL.search(lead))
    if HEAD_VERB.search(lead):
        appoint, has_pos = True, True
    if not has_pos:
        return None
    leave = LEAVE_VERB.search(lead)
    if not appoint and not leave:
        return None
    if not org_class and not orgs:
        return None
    if DISTRICT_HEAD.search(head) and not re.search(r"петербург|спб", head, re.I):
        return None
    level = "deputy" if DEPUTY.search(head) else "head"
    etype = "appointment" if appoint else "leave"
    return {"type": etype, "level": level, "org_class": org_class or "company", "orgs": orgs}


# ── Извлечение имени (эвристика, для дедупликации и подписи) ──
NAME_RE = re.compile(
    r"\b([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)\s+([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)(?:\s+([А-ЯЁ][а-яё]+(?:вич|вна|чна|ич)[а-яё]*))?")
NAME_STOP = {
    "российской", "федерации", "россии", "области", "область", "республики", "республика", "санкт",
    "петербурга", "петербург", "ленинградской", "архангельской", "вологодской", "калининградской",
    "мурманской", "псковской", "новгородской", "карелия", "карелии", "коми", "президент", "президента",
    "губернатор", "губернатора", "правительство", "правительства", "главного", "главное", "управление",
    "управления", "министерство", "министерства", "следственного", "комитета", "указом", "указ", "министр",
    "генеральной", "прокуратуры", "почётный", "почетный", "гражданин", "заслуженный", "народный",
    "артист", "работник", "владимир", "путин", "путина", "генерал", "майора", "майор", "лейтенант",
    "полковник", "полиции", "юстиции", "внутренней", "службы", "мчс", "мвд", "северо", "западного",
    "федерального", "округа", "великий", "новгород", "новгорода", "псков", "пскова", "мурманск", "мурманска",
    "вологда", "вологды", "калининград", "калининграда", "архангельск", "архангельска", "сыктывкар",
    "петрозаводск", "череповец", "гатчина", "выборг", "законодательного", "собрания", "областной",
    "областного", "думы", "дума", "государственной", "совета", "совет", "департамента", "комитет",
}


def extract_person(text):
    for m in NAME_RE.finditer(text):
        words = [w for w in m.groups() if w]
        if any(w.lower() in NAME_STOP for w in words[:2]):
            continue
        if len(words) == 2 and (len(words[0]) < 3 or len(words[1]) < 3):
            continue
        return " ".join(words)
    return ""


# ═══════════════════════════════════════════════════════════════════════
# Загрузка источников
# ═══════════════════════════════════════════════════════════════════════

def http_get(url):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def _text(el):
    return (el.text or "").strip() if el is not None else ""


def parse_feed(xml_text):
    """RSS 2.0 / Atom → [{title, link, date, summary}]."""
    xml_text = re.sub(r"^\s*<\?xml[^>]*\?>", "", xml_text, count=1)
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        return []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = []
    for it in root.iter("item"):                              # RSS
        items.append({"title": _text(it.find("title")), "link": _text(it.find("link")),
                      "date": _text(it.find("pubDate")) or _text(it.find("{http://purl.org/dc/elements/1.1/}date")),
                      "summary": _text(it.find("description"))})
    for it in root.iter("{http://www.w3.org/2005/Atom}entry"):   # Atom
        link_el = it.find("atom:link", ns)
        items.append({"title": _text(it.find("atom:title", ns)),
                      "link": link_el.get("href", "") if link_el is not None else "",
                      "date": _text(it.find("atom:published", ns)) or _text(it.find("atom:updated", ns)),
                      "summary": _text(it.find("atom:summary", ns)) or _text(it.find("atom:content", ns))})
    for it in items:
        it["summary"] = strip_tags(it["summary"])[:800]
        it["title"] = strip_tags(it["title"])
    return [it for it in items if it["title"]]


BLOCK_TAG_RE = re.compile(r"</?(?:p|div|br|li|ul|ol|h\d|tr|td|th|table|blockquote|section|article)\b[^>]*>", re.I)
TAG_RE = re.compile(r"<[^>]+>")


COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def strip_tags(s):
    s = COMMENT_RE.sub(" ", s or "")
    s = BLOCK_TAG_RE.sub(" ", s)
    s = TAG_RE.sub("", s)
    s = html_module.unescape(s).replace("\xa0", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", s).strip()


FEED_LINK_RE = re.compile(r"<link[^>]+>", re.I)


def discover_feed(page_html, base_url):
    """Адрес RSS/Atom из <link rel="alternate"> или заметной ссылки на /rss."""
    for tag in FEED_LINK_RE.findall(page_html):
        if re.search(r'type=["\']application/(?:rss|atom)\+xml', tag, re.I):
            m = re.search(r'href=["\']([^"\']+)', tag, re.I)
            if m:
                return urljoin(base_url, html_module.unescape(m.group(1)))
    m = re.search(r'href=["\']([^"\']*(?:/rss[^"\']*|\.rss|/feed/?|rss\.xml|feed\.xml))["\']', page_html, re.I)
    if m:
        return urljoin(base_url, html_module.unescape(m.group(1)))
    return None


ANCHOR_RE = re.compile(r"<a\b[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)


def parse_html_news(page_html, page_url):
    """Заголовки новостей со страницы: ссылки на тот же сайт с осмысленным текстом."""
    host = urlparse(page_url).netloc
    seen, items, counts = set(), [], {}
    page_html = COMMENT_RE.sub(" ", page_html)
    for href, inner in ANCHOR_RE.findall(page_html):
        title = re.sub(r"\s+", " ", re.sub(r"<!--|-->", " ", strip_tags(inner))).strip()
        if len(title) < 28 or len(title) > 300 or not re.search(r"[а-яё]", title, re.I):
            continue
        if not re.search(r"\s", title):        # одно слово — это меню
            continue
        url = urljoin(page_url, html_module.unescape(href))
        if urlparse(url).netloc != host or url in seen:
            continue
        seen.add(url)
        counts[title] = counts.get(title, 0) + 1
        items.append({"title": title, "link": url, "date": "", "summary": ""})
    # один и тот же текст на разных ссылках — это меню или название сайта, не новость
    return [it for it in items if counts[it["title"]] == 1]


TG_MSG_RE = re.compile(r'<div class="tgme_widget_message_wrap[^"]*"(.*?)(?=<div class="tgme_widget_message_wrap|\Z)', re.S)
TG_POST_RE = re.compile(r'data-post="([^"]+)"')
TG_TEXT_RE = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
TG_TIME_RE = re.compile(r'<time[^>]+datetime="([^"]+)"')


def parse_telegram(page_html):
    items = []
    for block in TG_MSG_RE.findall(page_html):
        post = TG_POST_RE.search(block)
        text_m = TG_TEXT_RE.search(block)
        if not post or not text_m:
            continue
        text = html_module.unescape(re.sub(r"<br\s*/?>", "\n", text_m.group(1)))
        text = strip_tags(text)
        text = re.sub(r"[ \t]+", " ", text).strip()
        if not text:
            continue
        first = text.split("\n", 1)[0].strip()
        if len(first) < 20 and "\n" in text:
            first = " ".join(text.split("\n")[:2]).strip()
        time_m = TG_TIME_RE.search(block)
        items.append({"title": first[:220], "link": f"https://t.me/{post.group(1)}",
                      "date": time_m.group(1) if time_m else "", "summary": text[:800]})
    return items


def parse_date(s):
    """pubDate / ISO → date или None."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")[:25]).date()
    except ValueError:
        pass
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def fetch_source(src, feeds_cache):
    """→ (items, status). status: 'rss N' | 'html N' | 'telegram N' | 'error: …'."""
    kind = src["type"]
    try:
        if kind == "rss":
            items = parse_feed(http_get(src["url"]))
            return items, f"rss {len(items)}"
        if kind == "telegram":
            items = parse_telegram(http_get(f"https://t.me/s/{src['url']}"))
            return items, (f"telegram {len(items)}" if items else "error: канал без веб-версии или пуст")
        # site: лента из кэша → автопоиск ленты → заголовки со страницы новостей
        feed_url = feeds_cache.get(src["id"])
        if feed_url:
            try:
                items = parse_feed(http_get(feed_url))
                if items:
                    return items, f"rss {len(items)}"
            except requests.RequestException:
                pass
        news_url = src.get("news_url") or src["url"]
        page = http_get(news_url)
        found = discover_feed(page, news_url)
        if found and found != feed_url:
            try:
                items = parse_feed(http_get(found))
                if items:
                    feeds_cache[src["id"]] = found
                    return items, f"rss {len(items)} (найдена {found})"
            except requests.RequestException:
                pass
        items = parse_html_news(page, news_url)
        return items, (f"html {len(items)}" if items else "error: на странице нет заголовков")
    except requests.RequestException as ex:
        code = getattr(getattr(ex, "response", None), "status_code", None)
        return [], f"error: {'HTTP ' + str(code) if code else type(ex).__name__}"
    except Exception as ex:                      # noqa: BLE001 — один источник не должен ронять прогон
        return [], f"error: {type(ex).__name__}: {str(ex)[:80]}"


# ═══════════════════════════════════════════════════════════════════════
# Прогон
# ═══════════════════════════════════════════════════════════════════════

def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


NEWS_FOREIGN = re.compile(
    r"\b(?!ленинградск|архангельск|вологодск|калининградск|мурманск|псковск|новгородск|петербургск|"
    r"санкт|ненецк|российск|всероссийск|северо|западн|сельск|городск|морск|областн|районн|"
    r"следственн|гражданск|советск|детск|женск|мужск|московск)"
    r"[а-яё]+ск(?:ая|ой|ую|ое|ими|ом|ий|ого|ому|им|их|ие)\s+(?:област|обл\.|кра[йяюе]|МЧС|УМВД|МВД|ГУ\b|УФСИН|"
    r"прокуратур|губернатор|правительств|ГУФСИН|СУ\b|СК\b)|"
    r"\b(?:татарстан|башкортостан|башкири|дагестан|чечн|чеченск|удмурти|чуваши|мордови|якути|бурят|тыв[аеы]|"
    r"хакаси|адыге|калмыки|ингушети|осети|крым|подмосковь|москв[аеыу]|московск|тюмен|омск|томск|казан[ьи]|"
    r"нижн\w+\s+новгород|екатеринбург|новосибирск|краснодар|ростов|самар[аеы]|перм[ьи]|челябинск|воронеж|"
    r"волгоград|хабаровск|владивосток|иркутск|красноярск|саратов|ярославл|твер[ьи]|тул[аеы]|калуг|курск|"
    r"белгород|липецк|тамбов|брянск|смоленск|рязан|ульяновск|пенз|оренбург|киров|ижевск|чебоксар|"
    r"ставропол|севастопол|симферопол|магадан|камчатк|сахалин|якутск|чит[аеы]\b|кемеров|кузбасс|барнаул|"
    r"тольятти|магнитогорск|сургут|югр[аеы]|ямал|донецк|луганск|запорожск|херсонск|ивановск|костром|"
    r"владимирск|орловск|курган)", re.I)


# Разговорные и газетные имена регионов, которых нет в словаре для указов
NEWS_REGION_EXTRA = {
    "Санкт-Петербург": [r"\bпетербург\w*", r"\bпитер[аеу]?\b", r"\bсмольн\w+", r"\bпетербуржц\w*"],
    "Ленинградская область": [r"\bленобласт\w*", r"\b47-\w+\s+регион", r"\bленинградц\w*", r"\bобластн\w+\s+правительств\w*\s+(?:47|ленобл)"],
    "Архангельская область": [r"\bпоморь\w*", r"\bархангелогородц\w*", r"\bсеверодвинск\w*", r"\bняо\b"],
    "Вологодская область": [r"\bвологодчин\w*", r"\bвологжан\w*", r"\bчереповц\w*", r"\bчереповчан\w*"],
    "Калининградская область": [r"\bянтарн\w+\s+кра[йяюе]", r"\bкалининградц\w*"],
    "Мурманская область": [r"\bзаполярь\w*", r"\bмурманчан\w*", r"\bкольск\w+\s+(?:полуостров|край|заполярь)"],
    "Республика Карелия": [r"\bкарел\w*", r"\bпетрозаводск\w*", r"\bпетрозаводчан\w*"],
    "Псковская область": [r"\bпсковщин\w*", r"\bпсковичи?\b", r"\bпсковичей\b", r"\bвеликолукск\w*", r"\bвелики[ех]\s+лук"],
    "Республика Коми": [r"\bсыктывкар\w*", r"\bухт[аеыу]\b", r"\bворкут\w*", r"\bкоми\b"],
    "Новгородская область": [r"\bновгородчин\w*", r"\bновгородц\w*", r"\bвелик\w+\s+новгород\w*", r"\bборовичи?\b"],
}
_NEWS_REGION_COMPILED = [(name, [re.compile(p, re.I) for p in pats]) for name, pats in NEWS_REGION_EXTRA.items()]


def news_region(text):
    """Регион СЗФО по тексту новости. Побеждает самое раннее упоминание;
    при явном чужом регионе — None (как в generate.match_region)."""
    if not text or g._has_foreign_region(text) or NEWS_FOREIGN.search(text):
        return None
    best = None
    for name, _slug, patterns in g.SZFO_COMPILED:
        for p in patterns:
            m = p.search(text)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), name)
    for name, patterns in _NEWS_REGION_COMPILED:
        for p in patterns:
            m = p.search(text)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), name)
    return best[1] if best else None


def attribute_region(src, text, orgs):
    """Регион события: по тексту → по словарю организаций → по источнику."""
    from_text = news_region(text)
    if from_text:
        return from_text
    if orgs:
        return orgs[0][0]
    if src.get("region"):
        if g._has_foreign_region(text) or NEWS_FOREIGN.search(text):   # региональное СМИ пишет о чужом регионе
            return None
        return src["region"]
    return None


def surname(person):
    words = person.split()
    if not words:
        return ""
    return words[0].lower() if len(words) == 3 else words[-1].lower()


POS_STOP = {"нового", "новым", "новой", "новую", "новый", "новая", "новое", "бывший", "бывшего", "экс",
            "правительства", "правительство", "области", "областной", "республики", "республика", "края", "региона",
            "назначен", "назначена", "назначили", "назначил", "стал", "стала", "станет", "возглавил", "возглавила",
            "исполняющим", "исполняющий", "обязанности", "врио", "временно", "должности", "должность", "пост",
            "на", "в", "по", "и", "с", "о", "для", "им", "имени", "главы", "губернатора", "который", "которая",
            "санкт", "петербурга", "петербург", "ленинградской", "ленобласти", "архангельской", "вологодской",
            "калининградской", "мурманской", "псковской", "новгородской", "карелии", "карелия", "коми",
            "области", "год", "года"}


def position_key(ev):
    """«министром информационной политики Вологодской области» и
    «нового министра информационной политики» → один ключ 'минис инфор полит'."""
    head = normalize(ev["title"] + " " + ev.get("summary", "")[:200])
    m = POSITION.search(head)
    if not m:
        return ""
    chunk = head[m.start():m.start() + 90].lower().replace("ё", "е")
    chunk = re.split(r"[.!?;:«»\"()—–]", chunk)[0]
    stems = []
    for w in re.findall(r"[а-яa-z][а-яa-z-]+", chunk):
        if re.match(r"(?:назнач|стал|стан|возглав|избран|утвержд|приступ|вступ|представ|освобо|покин)", w):
            break                                  # дальше идёт имя или другая часть фразы
        if w in POS_STOP or len(w) < 3:
            continue
        stems.append(w[:5])
        if len(stems) == 3:
            break
    return f"{ev['type']}:{ev['region']}:{' '.join(stems)}" if stems else ""


def event_keys(ev):
    keys = [event_key(ev)]
    pk = position_key(ev)
    if pk:
        keys.append(pk)
    return keys


def event_key(ev):
    person = ev.get("person", "")
    if person:
        return f"{ev['type']}:{surname(person)}"
    norm = re.sub(r"[^а-яёa-z0-9 ]", "", ev["title"].lower())
    return f"{ev['type']}:{norm[:70]}"


def run(today=None, verbose=True):
    cfg = load_json(SOURCES_FILE, {"sources": [], "organizations": {}})
    organizations = cfg.get("organizations", {})
    feeds_cache = load_json(FEEDS_CACHE, {})
    seen = load_json(SEEN_FILE, {})
    events = load_json(EVENTS_FILE, [])
    today = today or g.msk_today()
    fresh_from = today - timedelta(days=FRESH_DAYS)

    candidates, statuses = [], []
    for src in cfg["sources"]:
        if not src.get("enabled", True):
            continue
        t0 = time.time()
        items, status = fetch_source(src, feeds_cache)
        statuses.append((src["id"], src["name"], status, round(time.time() - t0, 1)))
        if verbose:
            print(f"  {src['id']:<16} {status:<40} {time.time() - t0:4.1f}s", flush=True)
        for it in items:
            d = parse_date(it.get("date"))
            if d and d < fresh_from:
                continue
            det = detect(it["title"], it.get("summary", ""), organizations)
            if not det:
                continue
            text = f"{it['title']} {it.get('summary', '')}"
            region = attribute_region(src, text, det["orgs"])
            if not region:
                continue
            ev = {"type": det["type"], "level": det["level"], "org_class": det["org_class"],
                  "region": region, "title": normalize(it["title"]).strip(), "summary": normalize(it.get("summary", ""))[:400],
                  "link": it.get("link", ""), "date": (d or today).isoformat(),
                  "source": src["name"], "source_id": src["id"], "rank": src.get("rank", 3),
                  "person": extract_person(it["title"]) or extract_person(it.get("summary", "")[:300]),
                  "orgs": sorted({o[1] for o in det["orgs"]})}
            candidates.append(ev)

    # одно событие — одна запись: сначала самый авторитетный источник, остальные склеиваются
    candidates.sort(key=lambda e: (e["rank"], e["date"]), reverse=False)
    new_events = []
    for ev in candidates:
        keys = event_keys(ev)
        if any(k in seen for k in keys):
            continue
        for k in keys:
            seen[k] = today.isoformat()
        new_events.append(ev)

    # ── сохранить ──
    cutoff = (today - timedelta(days=KEEP_EVENTS_DAYS)).isoformat()
    events = [e for e in events if e.get("date", "") >= cutoff] + new_events
    events.sort(key=lambda e: (e["date"], e["region"], e["title"]), reverse=True)
    seen_cut = (today - timedelta(days=KEEP_SEEN_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= seen_cut}
    save_json(EVENTS_FILE, events)
    save_json(SEEN_FILE, seen)
    save_json(FEEDS_CACHE, feeds_cache)
    errors = [s for s in statuses if s[2].startswith("error")]
    save_json(RUN_SUMMARY, {"date": today.isoformat(), "new": new_events,
                            "sources_total": len(statuses), "sources_failed": len(errors),
                            "failed": [{"id": s[0], "name": s[1], "status": s[2]} for s in errors]})
    render_page(events, today)
    if verbose:
        print(f"\nИсточников: {len(statuses)}, с ошибкой: {len(errors)}; новых событий: {len(new_events)}")
        for ev in new_events:
            print(f"  [{ev['type']}/{ev['level']}] {ev['region']}: {ev['title'][:100]}")
    return new_events, statuses


def check_sources():
    cfg = load_json(SOURCES_FILE, {"sources": []})
    feeds_cache = {}
    rows, ok = [], 0
    print(f"{'id':<16} {'тип':<9} {'статус':<48} {'сек':>5}  источник")
    for src in cfg["sources"]:
        if not src.get("enabled", True):
            print(f"{src['id']:<16} {src['type']:<9} {'выключен':<48} {'':>5}  {src['name']}")
            continue
        t0 = time.time()
        items, status = fetch_source(src, feeds_cache)
        dt = time.time() - t0
        if not status.startswith("error"):
            ok += 1
        sample = items[0]["title"][:70] if items else ""
        print(f"{src['id']:<16} {src['type']:<9} {status[:48]:<48} {dt:5.1f}  {src['name']}"
              + (f"\n{'':<16} {'':<9} пример: {sample}" if sample else ""), flush=True)
        rows.append((src, status))
    print(f"\nДоступно {ok} из {len(rows)} источников.")
    bad = [s for s, st in rows if st.startswith("error")]
    if bad:
        print("Недоступны:", ", ".join(s["id"] for s in bad))
    return rows


# ═══════════════════════════════════════════════════════════════════════
# Страница news.html
# ═══════════════════════════════════════════════════════════════════════

TYPE_LABEL = {"appointment": "Назначение", "leave": "Отставка", "title": "Звание"}
CLASS_LABEL = {"gov": "власть", "force": "силовые ведомства", "podved": "учреждение",
               "business": "компания", "company": "компания", "person": ""}

PAGE_CSS = """
.ev { padding: 12px 0 13px; border-bottom: 1px solid var(--line); }
.ev:last-child { border-bottom: none; }
.ev-top { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; font-size: 12px;
          color: var(--muted); margin-bottom: 4px; }
.ev-type { font-weight: 600; letter-spacing: .06em; text-transform: uppercase; font-size: 11px; }
.ev-type.appointment { color: var(--accent); } .ev-type.title { color: var(--gold-ink); }
.ev-type.leave { color: var(--faint); }
.ev-title { font-size: 15.5px; font-weight: 600; }
.ev-title a { color: var(--ink); text-decoration: none; }
.ev-title a:hover { color: var(--accent); }
.ev-sum { font-size: 13.5px; color: var(--muted); margin-top: 3px; }
.ev-src { font-size: 12px; color: var(--faint); margin-top: 4px; }
.day-head { font-family: var(--serif); font-size: 19px; color: var(--accent-deep); margin: 28px 0 4px;
            padding-bottom: 6px; border-bottom: 1px solid var(--line); }
.day-head:first-child { margin-top: 0; }
.ev.hidden { display: none; }
.day-block.hidden { display: none; }
.empty-note { text-align: center; color: var(--muted); padding: 30px 0; font-family: var(--serif);
              font-size: 17px; }
"""


def render_page(events, today):
    by_day = {}
    for ev in events:
        by_day.setdefault(ev["date"], []).append(ev)
    regions_present = sorted({e["region"] for e in events},
                             key=lambda r: g.REGION_ORDER.index(r) if r in g.REGION_ORDER else 99)
    chips = ['<button class="filter-btn active" data-region="">Все <span class="badge">%d</span></button>' % len(events)]
    for r in regions_present:
        n = sum(1 for e in events if e["region"] == r)
        chips.append(f'<button class="filter-btn" data-region="{esc(r)}">{esc(r)} <span class="badge">{n}</span></button>')
    type_chips = []
    for t, lbl in TYPE_LABEL.items():
        n = sum(1 for e in events if e["type"] == t)
        type_chips.append(f'<button class="filter-btn" data-type="{t}">{lbl} <span class="badge">{n}</span></button>')

    blocks = []
    for day in sorted(by_day, reverse=True):
        rows = []
        for ev in by_day[day]:
            cls = CLASS_LABEL.get(ev["org_class"], "")
            meta = [f'<span class="ev-type {ev["type"]}">{TYPE_LABEL.get(ev["type"], ev["type"])}</span>',
                    f"<span>{esc(ev['region'])}</span>"]
            if ev["level"] == "deputy":
                meta.append("<span>заместитель</span>")
            if cls:
                meta.append(f"<span>{cls}</span>")
            if ev.get("orgs"):
                meta.append(f"<span>{esc(', '.join(ev['orgs'][:3]))}</span>")
            link = esc(ev["link"])
            summary = ev.get("summary", "")
            if summary and summary.strip() != ev["title"].strip():
                summary = summary[:280] + ("…" if len(summary) > 280 else "")
            else:
                summary = ""
            rows.append(f"""
      <div class="ev" data-region="{esc(ev['region'])}" data-type="{ev['type']}">
        <div class="ev-top">{' · '.join(meta)}</div>
        <div class="ev-title"><a href="{link}" target="_blank" rel="noopener">{esc(ev['title'])}</a></div>
        {f'<div class="ev-sum">{esc(summary)}</div>' if summary else ''}
        <div class="ev-src">{esc(ev['source'])}</div>
      </div>""")
        blocks.append(f"""
    <div class="day-block" data-day="{day}">
      <div class="day-head">{esc(g.format_display_date(day))}</div>{''.join(rows)}
    </div>""")
    body = "".join(blocks) if blocks else '<div class="empty-note">Событий пока нет — первый прогон ещё не прошёл.</div>'

    page = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f7f3ec" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#15120f" media="(prefers-color-scheme: dark)">
<title>Назначения и звания в СЗФО — мониторинг новостей</title>
<style>
{g.BASE_CSS}
{PAGE_CSS}
</style>
</head>
<body>
<div class="shell">
  <div class="nav"><a href="index.html">← Наградные указы</a></div>
  <div class="report">
    <div class="report-head">
      <div class="eyebrow">Мониторинг новостей СЗФО</div>
      <h1>Назначения и звания</h1>
      <div class="period">руководители и заместители в органах власти, ведомствах, учреждениях и крупнейших компаниях ·
        региональные и генеральские звания</div>
      <div class="rule"></div>
    </div>
    <div class="filter-bar"><span class="filter-label">Регион:</span>{''.join(chips)}</div>
    <div class="filter-bar"><span class="filter-label">Тип:</span>
      <button class="filter-btn active" data-type="">Все</button>{''.join(type_chips)}</div>
    {body}
    <div class="report-footer">
      Источники: официальные сайты и Telegram-каналы правительств, ведомств и ведущих СМИ регионов (news_sources.json).
      Отбор автоматический по ключевым словам; заголовок ведёт на исходную публикацию.<br>
      Обновлено {esc(g.format_msk(datetime.utcnow().isoformat()))}
    </div>
  </div>
</div>
<script>
(function() {{
  var region = '', type = '';
  function apply() {{
    document.querySelectorAll('.ev').forEach(function(el) {{
      var show = (!region || el.dataset.region === region) && (!type || el.dataset.type === type);
      el.classList.toggle('hidden', !show);
    }});
    document.querySelectorAll('.day-block').forEach(function(b) {{
      b.classList.toggle('hidden', !b.querySelector('.ev:not(.hidden)'));
    }});
  }}
  document.querySelectorAll('.filter-btn[data-region]').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      region = btn.dataset.region;
      document.querySelectorAll('.filter-btn[data-region]').forEach(function(b) {{ b.classList.toggle('active', b === btn); }});
      apply();
    }});
  }});
  document.querySelectorAll('.filter-btn[data-type]').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      type = btn.dataset.type;
      document.querySelectorAll('.filter-btn[data-type]').forEach(function(b) {{ b.classList.toggle('active', b === btn); }});
      apply();
    }});
  }});
}})();
</script>
</body>
</html>
"""
    PAGE_FILE.write_text(page, encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════
# Telegram
# ═══════════════════════════════════════════════════════════════════════

def notify():
    import notify_telegram as nt
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    if not token or not chat_ids:
        print("Telegram не настроен — пропускаю.")
        return 0
    summary = load_json(RUN_SUMMARY, {})
    new = summary.get("new", [])
    if not new:
        print("Новых событий нет — уведомление не нужно.")
        return 0
    base = nt.site_url()
    by_region = {}
    for ev in new:
        by_region.setdefault(ev["region"], []).append(ev)
    icon = {"appointment": "👤", "leave": "🚪", "title": "🎖"}
    lines = [f"📰 <b>Назначения и звания в СЗФО</b> — {len(new)} "
             f"{nt.plural(len(new), 'новое событие', 'новых события', 'новых событий')}"]
    for region in sorted(by_region, key=lambda r: g.REGION_ORDER.index(r) if r in g.REGION_ORDER else 99):
        lines.append(f"\n<b>{esc(region)}</b>")
        for ev in by_region[region]:
            lines.append(f"{icon.get(ev['type'], '•')} <a href=\"{esc(ev['link'])}\">{esc(ev['title'][:160])}</a>"
                         f" <i>({esc(ev['source'])})</i>")
    if base:
        lines.append(f'\n<a href="{esc(base)}news.html">Все события →</a>')
    text = "\n".join(lines)
    messages, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > nt.TG_LIMIT - 50:
            messages.append(cur)
            cur = ""
        cur += line + "\n"
    messages.append(cur)
    report = {}
    for m in messages:
        nt.send(token, chat_ids, m.strip(), report)
    nt.print_report(report)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="проверить доступность источников")
    ap.add_argument("--rebuild", action="store_true", help="пересобрать news.html")
    ap.add_argument("--notify", action="store_true", help="отправить новые события в Telegram")
    args = ap.parse_args()
    if args.check:
        check_sources()
        return 0
    if args.rebuild:
        render_page(load_json(EVENTS_FILE, []), g.msk_today())
        print("news.html пересобран")
        return 0
    if args.notify:
        return notify()
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
