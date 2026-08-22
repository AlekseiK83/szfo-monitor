"""Генератор дайджеста наградных указов СЗФО за один день.

Использование:
    python generate.py                    # за вчера
    python generate.py --date 2026-08-12  # за конкретную дату
    python generate.py --rebuild          # пересобрать всё из reports/*.json без OCR
                                          # (после правки паттернов регионов)

Выход:
    reports/YYYY-MM-DD.html               # отчёт за день (с JS-фильтром по региону)
    reports/YYYY-MM-DD.json               # сырые данные + all_awardees для реюза
    reports/index.json                    # список обработанных дат
    regions/<slug>.html                   # лента награждённых по каждому региону
    index.html                            # главная страница
"""
import argparse
import json
import os
import re
import io
import sys
import time
import html as html_module
import traceback
from datetime import date, timedelta, datetime
from pathlib import Path

import requests
import pdfplumber
from pdf2image import convert_from_bytes
import pytesseract

API_BASE = "http://publication.pravo.gov.ru"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "SZFO-Monitor/1.0 (public monitoring)"})

REPORTS_DIR = Path("reports")
REGIONS_DIR = Path("regions")
INDEX_JSON = REPORTS_DIR / "index.json"


# ═══════════════════════════════════════════════════════════════════════
# КЛАССИФИКАЦИЯ + API
# ═══════════════════════════════════════════════════════════════════════
AWARDING_PATTERNS = [
    re.compile(r"о\s+награждении", re.IGNORECASE),
    re.compile(r"о\s+присвоении\s+поч[её]тного\s+звания", re.IGNORECASE),
    re.compile(r"об\s+объявлении\s+благодарности", re.IGNORECASE),
    re.compile(r"о\s+поощрении", re.IGNORECASE),
]


def is_awarding(doc):
    name = doc.get("complexName") or doc.get("name") or doc.get("title") or ""
    return any(p.search(name) for p in AWARDING_PATTERNS)


def fetch_documents(date_str):
    all_items, index, total_pages = [], 1, 1
    while index <= total_pages:
        r = SESSION.get(f"{API_BASE}/api/Documents", params={
            "block": "president", "PeriodType": "day", "Date": date_str,
            "PageSize": 100, "Index": index,
        }, timeout=30)
        r.raise_for_status()
        data = r.json()
        items = data.get("items") or data.get("Items") or data.get("documents") or []
        all_items.extend(items)
        total_pages = data.get("pagesTotalCount") or data.get("PagesTotalCount") or 1
        print(f"  стр. {index}/{total_pages}: {len(items)} документов", flush=True)
        index += 1
        if index <= total_pages:
            time.sleep(0.4)
    return all_items


def download_pdf(eo_number):
    r = SESSION.get(f"{API_BASE}/file/pdf", params={"eoNumber": eo_number}, timeout=90)
    r.raise_for_status()
    return r.content


# ═══════════════════════════════════════════════════════════════════════
# OCR
# ═══════════════════════════════════════════════════════════════════════
def ocr_pdf(pdf_bytes):
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception:
        text = ""
    if len(text) >= 100:
        print(f"  текстовый слой: {len(text)} симв.", flush=True)
        return text
    print("  OCR (текстового слоя нет)…", flush=True)
    images = convert_from_bytes(pdf_bytes, dpi=250)
    parts = []
    for i, img in enumerate(images, 1):
        t = pytesseract.image_to_string(img, lang="rus")
        parts.append(t)
        print(f"  стр. {i}/{len(images)}: OCR {len(t)} симв.", flush=True)
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════
# ПАРСЕР НАГРАЖДЁННЫХ
# ═══════════════════════════════════════════════════════════════════════
AWARD_KW = re.compile(
    r'^\s*(ОРДЕНОМ|МЕДАЛЬЮ|ЗНАКОМ|ЗВАНИЕМ|ПОЧЁТНЫМ\s+ЗВАНИЕМ|ПОЧЕТНЫМ\s+ЗВАНИЕМ|БЛАГОДАРНОСТЬ)'
    r'[А-ЯЁ\s"«»,\-.№()]{0,200}\s*$'
)
AWARD_QT = re.compile(r'^\s*[«"„][А-ЯЁ ,\-.№()IVX]{5,}[»"“]\s*$')
SPLITTER = re.compile(
    r'^\s*(Присвоить(?:\s+поч[её]тные)?\s+звания\s*:?'
    r'|Наградить(?:\s+посмертно)?\s*:?'
    r'|Объявить\s+благодарность'
    r'|За\s+заслуги\s+в[^:]{0,300}наградить\s*:?)\s*$',
    re.IGNORECASE
)
FIO_START = re.compile(
    r'^([А-ЯЁ]{2,}(?:-[А-ЯЁ]{2,})?)\s+'
    r'([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)'
    r'(\s+[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)?'
)
TRIM_MARKERS = [
    re.compile(r"(?:^|\s)За\s+заслуги\s+в", re.IGNORECASE),
    re.compile(r"(?:^|\s)Присвоить\s+", re.IGNORECASE),
    re.compile(r"(?:^|\s)Наградить\s+", re.IGNORECASE),
    re.compile(r"(?:^|\s)Объявить\s+благодарность", re.IGNORECASE),
    re.compile(r"(?:^|\s)Президент\s+Российской\s+Федерации", re.IGNORECASE),
]


def normalize_fio(raw):
    parts = raw.strip().split()
    if len(parts) < 2:
        return raw
    s = parts[0]
    return " ".join([s[0] + s[1:].lower()] + parts[1:])


def trim_by_markers(s):
    cut = len(s)
    for rx in TRIM_MARKERS:
        m = rx.search(s)
        if m and 20 < m.start() < cut:
            cut = m.start()
    return re.sub(r"[\s.,]+[0-9A-Za-z]{1,3}\s*$", "", s[:cut]).strip()


def preprocess_multiline_award_headers(text):
    """Заголовок звания в кавычках может быть напечатан в PDF на 2+ строках,
    например:
        "ЗАСЛУЖЕННЫЙ РАБОТНИК ЗДРАВООХРАНЕНИЯ
        РОССИЙСКОЙ ФЕДЕРАЦИИ"
    Склеиваем такие блоки в одну строку — до парсинга. AWARD_QT сработает как
    для обычного однострочного заголовка."""
    pattern = re.compile(
        r'([«"„])([А-ЯЁ \-,\.\d\n\t]{5,400}?)([»"“])',
        re.MULTILINE
    )
    def collapse(m):
        content = m.group(2).replace('\n', ' ').replace('\t', ' ')
        content = re.sub(r'\s+', ' ', content).strip()
        return m.group(1) + content + m.group(3)
    return pattern.sub(collapse, text)


def parse_awardees(raw_text, decree_ref):
    # Склеиваем OCR-переносы слов внутри одного слова: "Санкт-\nПетербург"
    text = re.sub(r"(\S)-\s*\n\s*(\S)", r"\1-\2", raw_text)
    # Склеиваем многострочные заголовки званий в кавычках
    text = preprocess_multiline_award_headers(text)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    results, seen = [], set()
    cur_award, cur_rec = None, None

    def flush():
        nonlocal cur_rec
        if not cur_rec or not cur_award:
            cur_rec = None
            return
        key = (cur_rec["fio"].lower(), cur_award.lower())
        if key in seen:
            cur_rec = None
            return
        seen.add(key)
        cur_rec["position_org"] = trim_by_markers(cur_rec["position_org"])
        results.append({**cur_rec, "award": cur_award, "decree": decree_ref})
        cur_rec = None

    for line in lines:
        if SPLITTER.match(line):
            flush()
            cur_award = None
            continue
        if AWARD_QT.match(line):
            flush()
            cur_award = re.sub(r'^[«"„]|[»"“]$', "", line).strip()
            continue
        if AWARD_KW.match(line):
            flush()
            cur_award = line.strip()
            continue
        m = FIO_START.match(line)
        if m and m.start() == 0:
            flush()
            fio_raw = m.group(0)
            rest = re.sub(r"^\s*[-—,]\s*", "", line[len(fio_raw):]).strip()
            cur_rec = {"fio": normalize_fio(fio_raw), "position_org": rest, "raw": line}
            continue
        if cur_rec:
            cur_rec["raw"] += " " + line
            cur_rec["position_org"] += " " + line
    flush()
    return results


# ═══════════════════════════════════════════════════════════════════════
# РЕГИОНЫ СЗФО — РАСШИРЕННЫЕ ПАТТЕРНЫ
# ═══════════════════════════════════════════════════════════════════════
# Философия матчинга:
# 1. Название региона (все падежи) — уверенно
# 2. Уникальные крупные города (все падежи + прилагательные) — уверенно
# 3. Города-омонимы (Кировск, Мирный, Остров, Сокол и т.д.) — не ловим
#    без явного контекста региона, чтобы не приписать чужих
#
# Формат: каждый паттерн должен матчить фразу как слово (границы \b),
# но с учётом русской морфологии — все падежные окончания.

SZFO_REGIONS = [
    # ── Санкт-Петербург (нет городов-спутников в границах субъекта) ──
    ("Санкт-Петербург", "sankt-peterburg", [
        r"санкт[-\s]петербург[а-я]*",
        r"г\.?\s*с[.\-]\s*петербург[а-я]*",
        r"\bспб\b",
        # Кронштадт входит в состав Санкт-Петербурга
        r"кронштадт(?:а|у|е|ом|ский|ская|ского|ской|ские)?",
        # Колпино, Пушкин, Петергоф — районы СПб, но «Пушкин» слишком коллизионен (поэт, город
        # в Тверской обл., улицы), «Петергоф» — обычно с уточнением; ловим осторожно
        r"колпин(?:о|а|у|е|ом)",
        r"петергоф(?:а|у|е|ом|ский|ская)?",
        r"сестрорецк(?:а|у|е|ом|ий|ая)?",
    ]),

    # ── Ленинградская область ──
    ("Ленинградская область", "leningradskaya-oblast", [
        r"ленинградск(?:ая|ой|ую|ое|ими|ом)\s+(?:област[ьию]|обл\.)",
        r"\bленинградск(?:ий|ая|ое|ого|ой|ому|им|ом|ими|их|ые|ых|ым|ую)\b",
        # Гатчина — административный центр
        r"гатчин(?:а|ы|у|е|ой|ский|ская|ского|ской)",
        r"выборг(?:а|у|е|ом|ский|ская|ского|ской)?",
        r"г(?:\.|орода?|ороду|ороде|ородом)?\s*тихвин(?:а|у|е|ом)?|тихвинск(?:ий|ая|ого|ой|ому|им|ом)\s+(?:райо|мест|поселе|окру|мун)",
        r"г(?:\.|орода?|ороду|ороде|ородом)?\s*соснов(?:ый|ого|ому|ым|ом)\s+бор(?:а|у|ом|е)?",  # ЛАЭС, только с "г."
        r"всеволожск(?:а|у|е|ом|ий|ая|ого|ой)?",
        r"кингисепп(?:а|у|е|ом|ский|ская)?",
        r"кириши(?:ей|ах|ями)?",
        r"г(?:\.|орода?|ороду|ороде|ородом)?\s*луг(?:а|и|у|е|ой)\b|луж(?:ский|ская|ского|ской)",  # г. Луга или Лужский р-н
        # «Волхов» ловим только с уточнением "город" или в связке с областью, иначе река
        r"город\s+волхов(?:а|у|е|ом)?",
        r"волхов(?:а|у|е|ом|ский|ская)\s+(?:област|район|муниципа|город|бор)",
        r"приозерск(?:а|у|е|ом|ий|ая)?",
        r"подпорожь(?:е|я|ю|ем|и)",
        r"лодейно(?:е|го|му|м)\s+пол(?:е|я|ю|ем)",
    ]),

    # ── Архангельская область ──
    ("Архангельская область", "arhangelskaya-oblast", [
        r"архангельск(?:ая|ой|ую|ое|ими|ом)\s+(?:област[ьию]|обл\.)",
        r"\bархангельск(?:ий|ая|ое|ого|ой|ому|им|ом|ими|их|ые|ых|ым|ую)\b",
        r"\bархангельск(?:а|у|е|ом|ий|ого|ому|им)?\b",
        r"северодвинск(?:а|у|е|ом|ий|ая|ого|ой)?",
        r"котлас(?:а|у|е|ом|ский|ская|ского|ской)?",
        r"новодвинск(?:а|у|е|ом|ий|ая)?",
        r"коряжм(?:а|ы|у|е|ой|ский|ская)",
        r"онег(?:а|и|у|е|ой|ский|ская)\s+(?:город|район|област|мест)",  # осторожно, чтоб не спутать
        r"город\s+онег(?:а|и|у|е|ой)",
        r"мирн(?:ый|ого|ому|ым|ом)\s+архангельск",  # ЗАТО Мирный только с уточнением
        r"плесецк(?:а|у|е|ом|ий|ая)?",
        r"каргопол(?:ь|я|ю|ем|е|ьский|ьская)",
        r"вельск(?:а|у|е|ом|ий|ая|ого|ой)?",
        # Ненецкий АО — часть Архангельской области (сложный статус, но по прописке — да)
        r"нарьян[-\s]мар(?:а|у|е|ом|ский|ская)?",
        r"ненецк(?:ий|ого|ому|им|ом|ая|ой)\s+(?:автономн|округ|нац)",
    ]),

    # ── Вологодская область ──
    ("Вологодская область", "vologodskaya-oblast", [
        r"вологодск(?:ая|ой|ую|ое|ими|ом)\s+(?:област[ьию]|обл\.)",
        r"\bвологодск(?:ий|ая|ое|ого|ой|ому|им|ом|ими|их|ые|ых|ым|ую)\b",
        r"\bвологд(?:а|ы|у|е|ой)\b",
        r"вологодск(?:ий|ого|ому|им|ом)\b",  # прилагательное
        r"череповц(?:а|у|е|ом)|череповец(?:кий|кая|кого|кой|ким|ким)?",
        # Соколу нужен уточнитель — слишком коллизионный
        r"город\s+сокол(?:а|у|е|ом)?",
        r"великий\s+устюг|велик(?:ого|ому|им)\s+устюг(?:а|у|е|ом)",
        r"тотьм(?:а|ы|у|е|ой|ский|ская)",
        r"кириллов(?:а|у|е|ом|ский|ская)\s+(?:вологод|мест|город|район|монаст)",
        r"город\s+кириллов",
        r"белозерск(?:а|у|е|ом|ий|ая)?",
        r"грязовец(?:а|у|е|ом|кий|кая)?",
        r"устюжн(?:а|ы|у|е|ой|ский|ская)",
        r"вытегр(?:а|ы|у|е|ой|ский|ская)",
    ]),

    # ── Калининградская область ──
    ("Калининградская область", "kaliningradskaya-oblast", [
        r"калининградск(?:ая|ой|ую|ое|ими|ом)\s+(?:област[ьию]|обл\.)",
        r"\bкалининградск(?:ий|ая|ое|ого|ой|ому|им|ом|ими|их|ые|ых|ым|ую)\b",
        r"\bкалининград(?:а|у|е|ом|ский|ская|ского|ской)?\b",
        r"советск(?:а|у|е|ом|ий|ая)\s+(?:калининград|област)",  # Советск в Калининградской, но омоним!
        r"город\s+советск(?:а|у|е|ом)?\b",
        r"черняховск(?:а|у|е|ом|ий|ая)?",
        r"балтийск(?:а|у|е|ом|ий|ая|ого|ой)?",
        r"гусев(?:а|у|е|ом|ский|ская)\s+(?:калининград|област|город|район)",
        r"город\s+гусев(?:а|у|е|ом)?",
        r"светлогорск(?:а|у|е|ом|ий|ая)?",
        r"пионерск(?:а|у|е|ом|ий|ая)\s+(?:калининград|област|город)",
        r"зеленоградск(?:а|у|е|ом|ий|ая)?",
        r"неман(?:а|у|е|ом|ский|ская)\s+(?:город|калининград|област|район)",
        r"город\s+неман(?:а|у|е|ом)?\b",
        r"багратионовск(?:а|у|е|ом|ий|ая)?",
        r"гвардейск(?:а|у|е|ом|ий|ая)\s+(?:калининград|област|город|район)",
        r"город\s+гвардейск(?:а|у|е|ом)?",
    ]),

    # ── Мурманская область ──
    ("Мурманская область", "murmanskaya-oblast", [
        r"мурманск(?:ая|ой|ую|ое|ими|ом)\s+(?:област[ьию]|обл\.)",
        r"\bмурманск(?:ий|ая|ое|ого|ой|ому|им|ом|ими|их|ые|ых|ым|ую)\b",
        r"\bмурманск(?:а|у|е|ом|ий|ая|ого|ой)?\b",
        r"апатит(?:ы|ов|ам|ах|ами|ский|ская)",
        r"кировск(?:а|у|е|ом|ий|ая|ому|им)\s+(?:мурман|заполярн)",  # только с явным Мурманском/Заполярьем
        r"город\s+кировск(?:а|у|е|ом)?\s+мурман",
        r"мончегорск(?:а|у|е|ом|ий|ая)?",
        r"североморск(?:а|у|е|ом|ий|ая|ого|ой)?",
        r"кандалакш(?:а|и|у|е|ей|ский|ская)",
        r"полярн(?:ый|ого|ому|ом|ым|ые)\s+(?:зор|мурман|город)",
        r"полярные\s+зори",
        r"оленегорск(?:а|у|е|ом|ий|ая)?",
        r"заполярн(?:ый|ого|ому|ом|ым)",
        r"снежногорск(?:а|у|е|ом|ий|ая)?",
        r"гаджиев(?:а|у|е|ом|ский|ская)?",  # ЗАТО, редко фамилия
        r"североморск|заозёрск|островной\s+мурман",
        r"печенг(?:а|и|у|е|ой|ский|ская)",
        r"ковдор(?:а|у|е|ом|ский|ская)?",
    ]),

    # ── Республика Карелия ──
    ("Республика Карелия", "respublika-kareliya", [
        r"республик[аеиу]\s+карели[яеию]",
        r"\bкарели[яеию]\b",
        r"карельск(?:ий|ая|ого|ой|ому|ой|им|ой|ом)",
        r"петрозаводск(?:а|у|е|ом|ий|ая|ого|ой)?",
        r"кондопог(?:а|и|у|е|ой|ский|ская)",
        r"сегеж(?:а|и|у|е|ой|ский|ская)",
        r"костомукш(?:а|и|у|е|ой|ский|ская)",
        r"сортавал(?:а|ы|у|е|ой|ский|ская)",
        r"беломорск(?:а|у|е|ом|ий|ая)?",
        r"кем(?:ь|и|ью|ский|ская)\s+(?:карели|карельск|город|район)",
        r"город\s+кем(?:ь|и|ью)",
        r"олонец(?:а|у|е|ом|кий|кая)?",
        r"питкярант(?:а|ы|у|е|ой|ский|ская)",
        r"пудож(?:а|у|е|ом|ский|ская)?",
        r"суоярви",
        r"медвежьегорск(?:а|у|е|ом|ий|ая)?",
        r"лахденпохь(?:я|и|е|ей|ский|ская)",
    ]),

    # ── Псковская область ──
    ("Псковская область", "pskovskaya-oblast", [
        r"псковск(?:ая|ой|ую|ое|ими|ом)\s+(?:област[ьию]|обл\.)",
        r"\bпсковск(?:ий|ая|ое|ого|ой|ому|им|ом|ими|их|ые|ых|ым|ую)\b",
        r"\bпсков(?:а|у|е|ом|ский|ская|ского|ской)?\b",
        r"велик(?:ие|их|им|ими)\s+лук(?:и|ах|ами|)\b",
        r"великолукск(?:ий|ая|ого|ой|ому|им|ом|ое|ими)",
        r"остров(?:а|у|е|ом|ский|ская)\s+(?:псков|област|город|район)",
        r"город\s+остров(?:а|у|е|ом)?\b",
        r"опочк(?:а|и|у|е|ой|ский|ская)",
        r"порхов(?:а|у|е|ом|ский|ская)?",
        r"печор(?:ы|ам|ах|ами|ский|ская)\s+(?:псков|област)",
        r"город\s+печоры\s+псков",  # чтобы отличать от Печоры Коми
        r"невель(?:я|ю|ем|е|ский|ская)?",
        r"дн(?:о|а|у|е|ом)\s+(?:псков|област|город|район)",  # Дно — город в Псковской обл.
        r"город\s+дно",
        r"себеж(?:а|у|е|ом|ский|ская)?",
        r"новоржев(?:а|у|е|ом|ский|ская)?",
        r"пыталово",
        r"гдов(?:а|у|е|ом|ский|ская)?",
    ]),

    # ── Республика Коми ──
    ("Республика Коми", "respublika-komi", [
        r"республик[аеиу]\s+коми",
        r"\bреспублик[аеиу]?\s+коми\b",
        # "Коми" отдельно (без "республика") — слишком коллизионно, не ловим
        r"коми\-пермяцк(?:ий|ая|ого|ой|ому|ом)",  # это Пермский край, специально исключаем
        r"сыктывкар(?:а|у|е|ом|ский|ская|ского|ской)?",
        r"ухт(?:а|ы|у|е|ой|инский|инская|инского|инской)",
        r"воркут(?:а|ы|у|е|ой|инский|инская|инского|инской)",
        r"печор(?:а|ы|у|е|ой|ский|ская)\s+(?:коми|город|район|мест)",  # с уточнением
        r"город\s+печор(?:а|ы|у|е|ой)",
        r"инт(?:а|ы|у|е|ой|инский|инская)",  # Инта — город
        r"усинск(?:а|у|е|ом|ий|ая|ого|ой)?",
        r"сосногорск(?:а|у|е|ом|ий|ая)?",
        r"вуктыл(?:а|у|е|ом|ский|ская)?",
        r"емв(?:а|ы|у|е|ой|инский|инская)",
        r"микунь(?:я|ю|ем|е|ский|ская)?",
    ]),

    # ── Новгородская область ──
    ("Новгородская область", "novgorodskaya-oblast", [
        r"новгородск(?:ая|ой|ую|ое|ими|ом)\s+(?:област[ьию]|обл\.)",
        r"\bновгородск(?:ий|ая|ое|ого|ой|ому|им|ом|ими|их|ые|ых|ым|ую)\b",
        r"велик(?:ий|ого|ому|им|ом)\s+новгород[а-я]*",
        r"г\.?\s*велик(?:ий|ого)\s+новгород",
        r"борович(?:и|ей|ах|ами|ский|ская)",
        r"стар(?:ая|ой)\s+русс(?:а|ы|у|е|ой)",
        r"чудов(?:а|у|е|ом|ский|ская)?",
        r"валда(?:й|я|ю|ем|е|йский|йская)",
        r"пестов(?:а|у|е|ом|ский|ская)?",
        r"окуловк(?:а|и|у|е|ой|ский|ская)",
        r"сольц(?:ы|ам|ах|ами|ский|ская)",
        r"холм(?:а|у|е|ом|ский|ская)\s+(?:новгород|област|город|район)",
        r"город\s+холм(?:а|у|е|ом)?",
        r"мал(?:ая|ой|ую|ой)\s+вишер(?:а|ы|е|ой)",
    ]),
]

SZFO_COMPILED = [
    (name, slug, [re.compile(p, re.IGNORECASE) for p in patterns])
    for name, slug, patterns in SZFO_REGIONS
]
REGION_SLUG = {name: slug for name, slug, _ in SZFO_REGIONS}
REGION_ORDER = [name for name, _, _ in SZFO_REGIONS]

def match_region(text):
    """Возвращает название региона СЗФО или None.

    Защита: если в тексте есть явное упоминание НЕ-СЗФО региона
    (Новосибирская область, Республика Татарстан, Краснодарский край,
    Москва и т.д.) — вероятно, это чужой человек, а любое СЗФО-упоминание
    в этом же тексте — залипший хвост от соседа. В этом случае матч
    отменяем.
    """
    if not text:
        return None
    if _has_foreign_region(text):
        return None
    matched = []
    for name, _slug, patterns in SZFO_COMPILED:
        if any(p.search(text) for p in patterns):
            matched.append(name)
    if not matched:
        return None
    if len(matched) == 1:
        return matched[0]
    # Несколько СЗФО-регионов сматчились — приоритет тому, у кого есть
    # явное упоминание субъекта (не только города-омонима)
    subject_hint = {
        "Санкт-Петербург": [r"санкт[-\s]петербург", r"\bспб\b"],
        "Ленинградская область": [r"ленинградск\S+\s+обл"],
        "Архангельская область": [r"архангельск\S+\s+обл", r"ненецк\S+\s+(?:авт|окр)"],
        "Вологодская область": [r"вологодск\S+\s+обл"],
        "Калининградская область": [r"калининградск\S+\s+обл"],
        "Мурманская область": [r"мурманск\S+\s+обл"],
        "Республика Карелия": [r"республик\S+\s+карели", r"\bкарели[яеию]\b"],
        "Псковская область": [r"псковск\S+\s+обл"],
        "Республика Коми": [r"республик\S+\s+коми"],
        "Новгородская область": [r"новгородск\S+\s+обл", r"велик\S+\s+новгород"],
    }
    scored = []
    for name in matched:
        score = 0
        for pat in subject_hint.get(name, []):
            if re.search(pat, text, re.IGNORECASE):
                score += 10
        scored.append((score, name))
    scored.sort(reverse=True)
    return scored[0][1]


# ═══════════════════════════════════════════════════════════════════════
# ЗАЩИТА: НЕ-СЗФО РЕГИОНЫ (отсекают ложные срабатывания на «хвостах»)
# ═══════════════════════════════════════════════════════════════════════
# Если в тексте position_org явно упомянут регион-НЕ-СЗФО, то любые
# упоминания СЗФО-регионов в этом же тексте с большой вероятностью —
# залипший фрагмент от предыдущей записи или подписной блок указа.
# В этом случае match_region возвращает None.
FOREIGN_REGION_PATTERNS = [
    # -ская область — кроме 7 областей СЗФО
    re.compile(
        r"\b(?!ленинградск|архангельск|вологодск|калининградск|мурманск|псковск|новгородск)"
        r"[а-яё]+ск(?:ая|ой|ую|ое|ими|ом)\s+(?:област[ьию]|обл\.)",
        re.IGNORECASE
    ),
    # Республики — кроме Коми и Карелии
    re.compile(
        r"\bреспублик[аеиу]\s+(?!коми\b|карели[яеию])(?:[а-яё]|-)+",
        re.IGNORECASE
    ),
    # Чувашская, Удмуртская, Кабардино-Балкарская, Карачаево-Черкесская
    # (пишутся с прилагательным, не «Республика Х»)
    re.compile(
        r"\b(?:чувашск|удмуртск|кабардино[-\s]балкарск|карачаево[-\s]черкесск)"
        r"(?:ая|ой|ую|ое|ими|ом)\s+респ",
        re.IGNORECASE
    ),
    # Края — все, у нас в СЗФО краёв нет
    re.compile(r"\b[а-яё]+ск(?:ий|ого|ому|им|ом)\s+кра[йяю]", re.IGNORECASE),
    # Автономные округа — кроме Ненецкого (входит в Архангельскую)
    re.compile(
        r"\b(?!ненецк)[а-яё]+ск(?:ий|ого|ому|им|ом)\s+автономн",
        re.IGNORECASE
    ),
    # Ямало-Ненецкий АО, Ханты-Мансийский АО — двухсоставные
    re.compile(r"\bямало[-\s]ненецк", re.IGNORECASE),
    re.compile(r"\bханты[-\s]мансийск", re.IGNORECASE),
    # Москва (город, области, «города Москвы»)
    re.compile(r"\bг(?:\.|орода?|ороду|ороде|ородом)?\s*москв[аыуеой]", re.IGNORECASE),
    re.compile(r"\bмосковск(?:ая|ой|ую|ое|ими|ом)\s+(?:област|обл\.)", re.IGNORECASE),
    # Севастополь
    re.compile(r"\bг(?:\.|орода?|ороду|ороде|ородом)?\s*севастопол", re.IGNORECASE),
    # Заграница — если в тексте «в Монголии», «во Франции» и т.п.,
    # это точно не наш награждённый по прописке
    re.compile(
        r"\bв\s+(?:монголии|китае|казахстане|беларуси|киргизии|узбекистане|"
        r"таджикистане|турк[а-я]+ии|азербайджане|армении|грузии|"
        r"украине|молдове|латвии|литве|эстонии|финляндии|швеции|норвегии|"
        r"германии|франции|италии|испании|великобритании|"
        r"сша|японии|индии|иране|турции|сирии|египте|бразилии|кубе|вьетнаме)\b",
        re.IGNORECASE
    ),
    # Явный «Краснодар», «Ростов-на-Дону», «Екатеринбург» и т.д.
    # (крупные не-СЗФО города, которые могут быть упомянуты без «область»)
    re.compile(
        r"\bг(?:\.|орода?|ороду|ороде|ородом)?\s*"
        r"(?:краснодар|ростов[-\s]на[-\s]дон|екатеринбург|новосибирск|"
        r"нижн(?:ий|его|ем)\s+новгород|казан|уф|перм|самар|"
        r"воронеж|волгоград|ставропол|барнаул|хабаровск|владивосток|"
        r"иркутск|омск|томск|тюмен|челябинск|ярославл|тверь|владимир|"
        r"кострома|тул|калуг|курск|липецк|тамбов|орёл|орл|брянск|смоленск|"
        r"грозный|махачкал|нальчик|владикавказ|астрахан|элист|"
        r"якутск|чит|биробидж|благовещенск|"
        r"симферопол|ялт|керч|"
        r"улан[-\s]удэ|горно[-\s]алтайск|"
        r"кемеров|новокузнецк|магнитогорск|тольятт|"
        r"кинешм|иванов[а-я]*)",
        re.IGNORECASE
    ),
]


def _has_foreign_region(text):
    """True, если в тексте явно указан НЕ-СЗФО регион."""
    for pat in FOREIGN_REGION_PATTERNS:
        if pat.search(text):
            return True
    return False


def _which_pattern_matched(text, patterns):
    """Диагностика: возвращает первый совпавший паттерн и подстроку."""
    for pat in patterns:
        m = pat.search(text)
        if m:
            return pat.pattern, m.group(0)
    return None, None


# ═══════════════════════════════════════════════════════════════════════
# ПАЙПЛАЙН
# ═══════════════════════════════════════════════════════════════════════
def build_result_from_awardees(all_awardees, docs_count, awarding_count):
    """Строит итоговый result dict из уже извлечённых awardees.
    Каждый awardee: {fio, award, position_org, raw, decree}"""
    all_szfo = []
    for rec in all_awardees:
        region = match_region(rec.get("position_org", "")) or match_region(rec.get("raw", ""))
        if region:
            rec_copy = {**rec, "region": region}
            all_szfo.append(rec_copy)

    # Группировка по регионам
    by_region = {}
    for a in all_szfo:
        r = by_region.setdefault(a["region"], {"count": 0, "awards": {}})
        r["count"] += 1
        r["awards"].setdefault(a["award"], []).append(a)

    regions = []
    for name in REGION_ORDER:
        if name in by_region:
            r = by_region[name]
            regions.append({
                "name": name,
                "count": r["count"],
                "awards": [{"title": t, "people": p_} for t, p_ in r["awards"].items()],
            })

    return {
        "stats": {
            "documents": docs_count,
            "awarding": awarding_count,
            "awardees": len(all_awardees),
            "szfo": len(all_szfo),
        },
        "regions": regions,
        # Сохраняем ВСЕХ извлечённых награждённых — для быстрой пересборки
        # при изменении паттернов регионов без повторного OCR
        "all_awardees": all_awardees,
    }


def run_pipeline(date_str):
    print(f"▶ Запрос за {date_str}", flush=True)
    docs = fetch_documents(date_str)
    print(f"✓ Документов: {len(docs)}", flush=True)

    awarding = [d for d in docs if is_awarding(d)]
    print(f"✓ Наградных: {len(awarding)}", flush=True)

    all_awardees = []

    for i, doc in enumerate(awarding, 1):
        num = doc.get("number") or doc.get("Number") or "?"
        eo = doc.get("eoNumber") or doc.get("EoNumber") or doc.get("id")
        print(f"[{i}/{len(awarding)}] Указ № {num} ({eo})", flush=True)

        try:
            pdf_bytes = download_pdf(eo)
            print(f"  скачано: {len(pdf_bytes)/1024:.1f} КБ", flush=True)
            text = ocr_pdf(pdf_bytes)
        except Exception as e:
            print(f"  ✗ {e}", flush=True)
            continue

        parsed = parse_awardees(text, {"number": num, "date": date_str, "eo": eo})
        all_awardees.extend(parsed)
        print(f"  извлечено записей: {len(parsed)}", flush=True)

    result = build_result_from_awardees(all_awardees, len(docs), len(awarding))
    result["date"] = date_str
    result["generated_at"] = datetime.utcnow().isoformat() + "Z"
    print(f"✓ Из СЗФО: {result['stats']['szfo']}", flush=True)
    return result


def rebuild_report_from_json(json_data):
    """Пересобирает отчёт из сохранённого all_awardees, применяя актуальные паттерны."""
    all_awardees = json_data.get("all_awardees", [])
    if not all_awardees:
        # Старые JSON без all_awardees — используем то, что уже сгруппировано
        return json_data
    docs_count = json_data.get("stats", {}).get("documents", 0)
    awarding_count = json_data.get("stats", {}).get("awarding", 0)
    new_result = build_result_from_awardees(all_awardees, docs_count, awarding_count)
    new_result["date"] = json_data["date"]
    new_result["generated_at"] = json_data.get("generated_at", "")
    new_result["rebuilt_at"] = datetime.utcnow().isoformat() + "Z"
    return new_result


# ═══════════════════════════════════════════════════════════════════════
# CSS + HTML-РЕНДЕРЫ (без изменений в стиле)
# ═══════════════════════════════════════════════════════════════════════
BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #f6f2ea; color: #1a1a1a; line-height: 1.55; min-height: 100vh; }
.shell { max-width: 940px; margin: 0 auto; padding: 32px 20px 60px; }
.nav { display: flex; gap: 12px; align-items: center; margin-bottom: 20px; font-size: 14px; }
.nav a { color: #7d1e2a; text-decoration: none; }
.nav a:hover { text-decoration: underline; }

.report { background: white; border: 1px solid #e8e2d5; border-radius: 10px;
          padding: 48px 56px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }
.report-head { text-align: center; padding-bottom: 22px; border-bottom: 2px solid #b8860b;
               margin-bottom: 26px; }
.report-head h1 { font-family: Georgia, serif; font-size: 24px; font-weight: 500;
                  color: #5c1620; margin-bottom: 8px; }
.period { font-size: 14px; color: #6b6b6b; }
.report-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px;
                margin-bottom: 26px; }
.stat { text-align: center; padding: 16px 12px; background: #faf7f0;
        border-radius: 8px; border: 1px solid #eee6d3; }
.stat-value { font-family: Georgia, serif; font-size: 26px; color: #7d1e2a;
              line-height: 1; margin-bottom: 6px; }
.stat-label { font-size: 11px; color: #6b6b6b; text-transform: uppercase; letter-spacing: 0.5px; }

.region-block { margin-bottom: 26px; }
.region-header { display: flex; align-items: baseline; gap: 10px; padding-bottom: 6px;
                 border-bottom: 1px solid #e8e2d5; margin-bottom: 14px; }
.marker { color: #b8860b; font-size: 12px; }
.region-header h2 { font-family: Georgia, serif; font-size: 19px; font-weight: 500;
                    color: #5c1620; flex: 1; }
.region-header .count { font-size: 13px; color: #6b6b6b; }
.region-header a.region-link { font-family: Georgia, serif; font-size: 19px; font-weight: 500;
                               color: #5c1620; text-decoration: none; flex: 1; }
.region-header a.region-link:hover { text-decoration: underline; }
.award-group { margin-bottom: 16px; padding-left: 14px; border-left: 2px solid #fdf6e3; }
.award-title { font-size: 12px; font-weight: 600; letter-spacing: 0.6px; color: #7d1e2a;
               text-transform: uppercase; margin-bottom: 8px; }
.awardee { padding: 6px 0 8px; border-bottom: 1px dotted #e8e2d5; }
.awardee:last-child { border-bottom: none; }
.fio { font-weight: 500; color: #1a1a1a; font-size: 14.5px; }
.position { font-size: 13px; color: #6b6b6b; margin-top: 2px; }
.decree { font-size: 11px; color: #999; margin-top: 3px; font-style: italic; }

.no-results { text-align: center; padding: 40px 20px; color: #6b6b6b; font-size: 14px; }
.report-footer { margin-top: 34px; padding-top: 18px; border-top: 1px solid #e8e2d5;
                 text-align: center; font-size: 12px; color: #6b6b6b; }
.report-footer a { color: #7d1e2a; text-decoration: none; }

.filter-bar { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 22px;
              padding: 12px 14px; background: #faf7f0;
              border: 1px solid #eee6d3; border-radius: 8px; }
.filter-bar .filter-label { font-size: 11px; color: #6b6b6b; text-transform: uppercase;
                            letter-spacing: 0.5px; align-self: center; padding-right: 4px; }
.filter-btn { font: inherit; font-size: 13px; padding: 5px 12px; border: 1px solid #d4cbb8;
              background: white; color: #5c1620; border-radius: 999px; cursor: pointer;
              transition: all .12s; }
.filter-btn:hover { background: #fdf6e3; }
.filter-btn.active { background: #7d1e2a; color: white; border-color: #7d1e2a; }
.filter-btn .badge { display: inline-block; margin-left: 6px; padding: 0 6px;
                     background: rgba(184,134,11,0.15); color: #7d1e2a;
                     font-size: 11px; border-radius: 999px; }
.filter-btn.active .badge { background: rgba(255,255,255,0.25); color: white; }

.region-nav { background: white; border: 1px solid #e8e2d5; border-radius: 10px;
              padding: 18px 22px; margin-bottom: 20px; }
.region-nav .title { font-size: 11px; color: #6b6b6b; text-transform: uppercase;
                     letter-spacing: 0.5px; margin-bottom: 10px; }
.region-nav .pills { display: flex; flex-wrap: wrap; gap: 8px; }
.region-pill { display: inline-flex; align-items: center; padding: 6px 14px;
               background: #faf7f0; border: 1px solid #eee6d3; border-radius: 999px;
               color: #5c1620; text-decoration: none; font-size: 13.5px; transition: all .12s; }
.region-pill:hover { background: #7d1e2a; color: white; border-color: #7d1e2a; }
.region-pill.active { background: #7d1e2a; color: white; border-color: #7d1e2a; }
.region-pill .badge { display: inline-block; margin-left: 8px; padding: 0 7px;
                      background: rgba(184,134,11,0.15); color: #7d1e2a;
                      font-size: 11px; border-radius: 999px; font-variant-numeric: tabular-nums; }
.region-pill:hover .badge,
.region-pill.active .badge { background: rgba(255,255,255,0.25); color: white; }

.timeline-item { background: white; border: 1px solid #e8e2d5; border-radius: 8px;
                 padding: 14px 18px; margin-bottom: 10px; }
.timeline-date { font-size: 12px; color: #b8860b; font-weight: 600;
                 letter-spacing: 0.4px; text-transform: uppercase; margin-bottom: 6px; }
.timeline-date a { color: #b8860b; text-decoration: none; }
.timeline-date a:hover { text-decoration: underline; }
.timeline-item .fio { font-size: 15px; margin-bottom: 4px; }
.timeline-item .award-name { font-size: 12px; font-weight: 600; letter-spacing: 0.5px;
                             color: #7d1e2a; text-transform: uppercase; margin-bottom: 6px; }
.timeline-item .position { font-size: 13px; color: #6b6b6b; }
.timeline-item .decree { font-size: 11px; color: #999; margin-top: 6px; font-style: italic; }

@media (max-width: 640px) {
  .shell { padding: 20px 14px; }
  .report { padding: 26px 20px; }
  .report-stats { grid-template-columns: 1fr; }
  .filter-bar { padding: 10px; }
}
"""


def render_report_html(d):
    esc = html_module.escape
    display_date = format_display_date(d["date"])

    stats_html = ""
    for val, lbl in [(d["stats"]["documents"], "Документов за день"),
                     (d["stats"]["awarding"], "Наградных указов"),
                     (d["stats"]["szfo"], "Награждённых СЗФО")]:
        stats_html += f'<div class="stat"><div class="stat-value">{val}</div>' \
                      f'<div class="stat-label">{lbl}</div></div>'

    filter_html = ""
    regions_html = ""
    if d["regions"]:
        filter_buttons = [
            '<button class="filter-btn active" data-region="all">Все<span class="badge">'
            + str(d["stats"]["szfo"]) + '</span></button>'
        ]
        for r in d["regions"]:
            slug = REGION_SLUG[r["name"]]
            filter_buttons.append(
                f'<button class="filter-btn" data-region="{slug}">{esc(r["name"])}'
                f'<span class="badge">{r["count"]}</span></button>'
            )
        filter_html = f'''
        <div class="filter-bar">
          <span class="filter-label">Регион:</span>
          {"".join(filter_buttons)}
        </div>'''

        for r in d["regions"]:
            slug = REGION_SLUG[r["name"]]
            regions_html += f'<div class="region-block" data-region="{slug}">' \
                            f'<div class="region-header"><span class="marker">▸</span>' \
                            f'<a class="region-link" href="../regions/{slug}.html">{esc(r["name"])}</a>' \
                            f'<span class="count">{r["count"]}</span></div>'
            for a in r["awards"]:
                regions_html += f'<div class="award-group">' \
                                f'<div class="award-title">{esc(a["title"])}</div>'
                for p_ in a["people"]:
                    pos = (p_.get("position_org") or "")[:260]
                    regions_html += f'<div class="awardee">' \
                                    f'<div class="fio">{esc(p_["fio"])}</div>' \
                                    f'<div class="position">{esc(pos)}</div>' \
                                    f'<div class="decree">Указ № ' \
                                    f'{esc(str(p_["decree"]["number"]))} от ' \
                                    f'{esc(p_["decree"]["date"])}</div></div>'
                regions_html += '</div>'
            regions_html += '</div>'
    else:
        regions_html = '<div class="no-results">За выбранную дату награждённых ' \
                       'из регионов СЗФО не найдено</div>'

    filter_js = """
    <script>
    (function(){
      const btns = document.querySelectorAll('.filter-btn');
      const blocks = document.querySelectorAll('.region-block');
      btns.forEach(btn => btn.addEventListener('click', () => {
        const target = btn.dataset.region;
        btns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        blocks.forEach(block => {
          block.style.display = (target === 'all' || block.dataset.region === target) ? '' : 'none';
        });
      }));
    })();
    </script>"""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Дайджест СЗФО за {esc(d["date"])}</title>
<style>{BASE_CSS}</style>
</head>
<body>
<div class="shell">
  <div class="nav"><a href="../index.html">← Все дайджесты</a></div>
  <div class="report">
    <div class="report-head">
      <h1>Дайджест наградных указов СЗФО</h1>
      <div class="period">Период: {esc(display_date)}</div>
    </div>
    <div class="report-stats">{stats_html}</div>
    {filter_html}
    {regions_html}
    <div class="report-footer">
      Источник: <a href="http://publication.pravo.gov.ru/documents/daily"
                    target="_blank" rel="noopener">publication.pravo.gov.ru</a><br>
      Всего в указах награждённых: {d["stats"]["awardees"]} ·
      Отфильтровано по 10 регионам СЗФО<br>
      Сгенерировано автоматически: {esc(d.get("generated_at", ""))}
    </div>
  </div>
</div>
{filter_js}
</body>
</html>"""


def render_region_html(region_name, people, all_region_counts):
    esc = html_module.escape

    date_from = min(p["iso_date"] for p in people) if people else "—"
    date_to = max(p["iso_date"] for p in people) if people else "—"

    nav_pills = []
    for name in REGION_ORDER:
        cnt = all_region_counts.get(name, 0)
        if cnt == 0:
            continue
        slug = REGION_SLUG[name]
        active = " active" if name == region_name else ""
        nav_pills.append(
            f'<a class="region-pill{active}" href="{esc(slug)}.html">'
            f'{esc(name)}<span class="badge">{cnt}</span></a>'
        )
    nav_html = f'''
    <div class="region-nav">
      <div class="title">Другие регионы СЗФО</div>
      <div class="pills">{"".join(nav_pills)}</div>
    </div>''' if nav_pills else ""

    items_html = ""
    for p in people:
        pos = (p.get("position_org") or "")[:260]
        iso_date = p["iso_date"]
        display = format_display_date(iso_date)
        items_html += f'''
        <div class="timeline-item">
          <div class="timeline-date">
            <a href="../reports/{esc(iso_date)}.html">{esc(display)}</a>
          </div>
          <div class="award-name">{esc(p["award"])}</div>
          <div class="fio">{esc(p["fio"])}</div>
          <div class="position">{esc(pos)}</div>
          <div class="decree">Указ № {esc(str(p["decree"]["number"]))} от {esc(p["decree"]["date"])}</div>
        </div>'''

    if not items_html:
        items_html = '<div class="no-results">Награждённые из этого региона в архиве не найдены.</div>'

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(region_name)} — Мониторинг СЗФО</title>
<style>{BASE_CSS}</style>
</head>
<body>
<div class="shell">
  <div class="nav"><a href="../index.html">← Все дайджесты</a></div>
  <div class="report">
    <div class="report-head">
      <h1>{esc(region_name)}</h1>
      <div class="period">Награждённые за всё время: {len(people)} ·
        период с {esc(format_display_date(date_from))} по {esc(format_display_date(date_to))}</div>
    </div>
    {nav_html}
    {items_html}
    <div class="report-footer">
      Источник: <a href="http://publication.pravo.gov.ru/documents/daily"
                    target="_blank" rel="noopener">publication.pravo.gov.ru</a>
    </div>
  </div>
</div>
</body>
</html>"""


def render_index_html(index_data, region_counts):
    esc = html_module.escape
    entries = sorted(index_data["reports"], key=lambda x: x["date"], reverse=True)

    nav_pills = []
    for name in REGION_ORDER:
        cnt = region_counts.get(name, 0)
        if cnt == 0:
            continue
        slug = REGION_SLUG[name]
        nav_pills.append(
            f'<a class="region-pill" href="regions/{esc(slug)}.html">'
            f'{esc(name)}<span class="badge">{cnt}</span></a>'
        )
    nav_html = f'''
    <div class="region-nav">
      <div class="title">Просмотр по региону</div>
      <div class="pills">{"".join(nav_pills)}</div>
    </div>''' if nav_pills else ""

    rows_html = ""
    for e in entries:
        szfo = e["stats"]["szfo"]
        awarding = e["stats"]["awarding"]
        empty_class = " empty" if szfo == 0 else ""
        rows_html += f"""
        <a class="entry{empty_class}" href="reports/{esc(e['date'])}.html">
          <div class="entry-date">{esc(format_display_date(e['date']))}</div>
          <div class="entry-stats">
            <span>Наградных: <b>{awarding}</b></span>
            <span>Из СЗФО: <b>{szfo}</b></span>
          </div>
        </a>"""

    if not entries:
        rows_html = '<div class="no-results">Дайджесты пока не сгенерированы.</div>'

    total_reports = len(entries)
    total_szfo = sum(e["stats"]["szfo"] for e in entries)
    last_update = index_data.get("updated_at", "")

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Мониторинг наградных указов СЗФО</title>
<style>
{BASE_CSS}
.hero {{ text-align: center; padding: 24px 0 32px; }}
.hero .emblem {{ font-size: 40px; margin-bottom: 12px; }}
.hero h1 {{ font-family: Georgia, serif; font-size: 26px; color: #5c1620;
           font-weight: 500; margin-bottom: 6px; }}
.hero .sub {{ font-size: 14px; color: #6b6b6b; }}
.summary {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px;
           margin-bottom: 20px; }}
.entries {{ background: white; border: 1px solid #e8e2d5; border-radius: 10px;
           overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
.entry {{ display: flex; justify-content: space-between; align-items: center;
         padding: 16px 24px; border-bottom: 1px solid #e8e2d5;
         color: inherit; text-decoration: none; transition: background 0.15s; }}
.entry:hover {{ background: #faf7f0; }}
.entry:last-child {{ border-bottom: none; }}
.entry-date {{ font-family: Georgia, serif; font-size: 16px; color: #5c1620; }}
.entry-stats {{ display: flex; gap: 20px; font-size: 13px; color: #6b6b6b; }}
.entry-stats b {{ color: #7d1e2a; font-weight: 600; }}
.entry.empty {{ opacity: 0.55; }}
.updated {{ text-align: center; font-size: 12px; color: #999; margin-top: 20px; }}
</style>
</head>
<body>
<div class="shell">
  <div class="hero">
    <div class="emblem">🏛</div>
    <h1>Мониторинг наградных указов СЗФО</h1>
    <div class="sub">Северо-Западный федеральный округ · 10 регионов ·
                     источник: publication.pravo.gov.ru</div>
  </div>
  <div class="summary">
    <div class="stat"><div class="stat-value">{total_reports}</div>
      <div class="stat-label">Дайджестов в архиве</div></div>
    <div class="stat"><div class="stat-value">{total_szfo}</div>
      <div class="stat-label">Награждённых из СЗФО (всего)</div></div>
  </div>
  {nav_html}
  <div class="entries">{rows_html}</div>
  <div class="updated">Обновлено: {esc(last_update)} UTC · Автоматически ежедневно</div>
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════
# АГРЕГАЦИЯ + СБОРКА
# ═══════════════════════════════════════════════════════════════════════
def migrate_legacy_filenames():
    """Одноразовая миграция: переименовать reports/DD.MM.YYYY.* → reports/YYYY-MM-DD.*
    и нормализовать поле date в JSON к ISO-формату.

    Такие файлы могли остаться от прогонов, где имя файла случайно писалось
    в pravo-формате. Функция чинит это, чтобы сортировка на главной странице
    работала корректно."""
    pravo_pattern = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})\.(json|html)$")
    migrated = 0
    for f in list(REPORTS_DIR.glob("*.json")) + list(REPORTS_DIR.glob("*.html")):
        m = pravo_pattern.match(f.name)
        if not m:
            continue
        d, mo, y, ext = m.groups()
        iso_date = f"{y}-{mo}-{d}"
        iso_name = f"{iso_date}.{ext}"
        target = REPORTS_DIR / iso_name

        # Если целевой ISO-файл уже есть — legacy устарел, удаляем
        if target.exists():
            print(f"  ⚠ legacy {f.name} → ISO уже есть, удаляю legacy", flush=True)
            try: f.unlink()
            except Exception: pass
            migrated += 1
            continue

        if ext == "json":
            # Нормализуем поле date внутри JSON и записываем под новым именем
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                data["date"] = iso_date
                target.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
                f.unlink()
                print(f"  → {f.name} → {iso_name} (date нормализовано)", flush=True)
            except Exception as e:
                print(f"  ⚠ {f.name}: не удалось прочитать/переписать: {e}", flush=True)
                continue
        else:
            # HTML — просто переименовать (потом при rebuild пересоздастся из JSON)
            try:
                f.rename(target)
                print(f"  → {f.name} → {iso_name}", flush=True)
            except Exception as e:
                print(f"  ⚠ {f.name}: {e}", flush=True)
                continue
        migrated += 1
    return migrated


def normalize_date_field(iso_or_pravo):
    """Приводит любую дату к ISO-формату YYYY-MM-DD."""
    if not iso_or_pravo:
        return iso_or_pravo
    s = iso_or_pravo.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", s)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{mo}-{d}"
    return s  # если что-то ещё — возвращаем как есть


def load_all_reports():
    reports = []
    if not REPORTS_DIR.exists():
        return reports
    for json_file in sorted(REPORTS_DIR.glob("*.json")):
        if json_file.name == "index.json":
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            data["date"] = normalize_date_field(data.get("date", ""))
            reports.append(data)
        except Exception as e:
            print(f"  ⚠ Не удалось прочитать {json_file}: {e}", flush=True)
    return reports


def build_region_pages():
    print("▶ Пересборка страниц регионов…", flush=True)
    all_reports = load_all_reports()

    by_region = {}
    for report in all_reports:
        iso_date = report["date"]
        for region in report.get("regions", []):
            name = region["name"]
            if name not in REGION_SLUG:
                continue
            by_region.setdefault(name, [])
            for award in region.get("awards", []):
                for person in award.get("people", []):
                    by_region[name].append({
                        "fio": person.get("fio", ""),
                        "award": award["title"],
                        "position_org": person.get("position_org", ""),
                        "decree": person.get("decree", {"number": "?", "date": "—"}),
                        "iso_date": iso_date,
                    })

    for name in by_region:
        by_region[name].sort(key=lambda x: x["iso_date"], reverse=True)

    region_counts = {name: len(people) for name, people in by_region.items()}

    REGIONS_DIR.mkdir(exist_ok=True)
    written = 0
    for name, people in by_region.items():
        slug = REGION_SLUG[name]
        html = render_region_html(name, people, region_counts)
        (REGIONS_DIR / f"{slug}.html").write_text(html, encoding="utf-8")
        written += 1

    print(f"✓ Страниц регионов: {written}", flush=True)
    return region_counts


MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня",
             "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def format_display_date(iso_date):
    try:
        y, m, d = iso_date.split("-")
        return f"{int(d)} {MONTHS_RU[int(m) - 1]} {y}"
    except (ValueError, IndexError):
        return iso_date


def to_pravo_date(iso_date):
    y, m, d = iso_date.split("-")
    return f"{d}.{m}.{y}"


def update_index_json(iso_date, stats):
    iso_date = normalize_date_field(iso_date)
    index = {"reports": [], "updated_at": ""}
    if INDEX_JSON.exists():
        try:
            index = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Нормализуем все существующие записи к ISO
    for r in index.get("reports", []):
        r["date"] = normalize_date_field(r.get("date", ""))
    index["reports"] = [r for r in index["reports"] if r["date"] != iso_date]
    index["reports"].append({"date": iso_date, "stats": stats})
    index["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    INDEX_JSON.write_text(json.dumps(index, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    return index


def rebuild_all_daily_pages():
    print("▶ Перегенерация дневных страниц…", flush=True)
    count = 0
    for json_file in sorted(REPORTS_DIR.glob("*.json")):
        if json_file.name == "index.json":
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            html_path = json_file.with_suffix(".html")
            html_path.write_text(render_report_html(data), encoding="utf-8")
            count += 1
        except Exception as e:
            print(f"  ⚠ {json_file}: {e}", flush=True)
    print(f"✓ Перегенерировано дневных страниц: {count}", flush=True)


def rebuild_all_from_json():
    """Пересобирает ВСЕ отчёты из reports/*.json — переприменяет актуальные паттерны
    к сохранённым all_awardees, обновляет JSON и HTML. Без OCR.

    Дополнительно: нормализует поле date к ISO-формату во всех JSON — это чинит
    случаи, когда файлы уже переименованы к ISO, а поле date внутри осталось
    в pravo-формате (тогда сортировка на главной ломается, ссылки уходят в 404)."""
    print("▶ Миграция legacy-имён файлов (если есть)…", flush=True)
    n = migrate_legacy_filenames()
    if n:
        print(f"✓ Перенесено {n} файл(ов) к ISO-формату", flush=True)
    else:
        print(f"  ничего мигрировать не нужно", flush=True)

    print("▶ Пересборка всех отчётов из JSON (без OCR)…", flush=True)

    fresh_index_reports = []
    reprocessed = 0
    legacy_skipped = 0
    normalized_dates = 0

    for json_file in sorted(REPORTS_DIR.glob("*.json")):
        if json_file.name == "index.json":
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ⚠ {json_file}: {e}", flush=True)
            continue

        # Нормализуем поле date к ISO — независимо от ветки ниже
        original_date = data.get("date", "")
        iso_date = normalize_date_field(original_date)
        date_was_fixed = (iso_date != original_date)
        data["date"] = iso_date

        if "all_awardees" not in data:
            # Legacy JSON без сохранённых awardees: пересобрать содержимое не можем,
            # но поле date поправим — этого достаточно, чтобы ссылки в index.html
            # были корректными
            legacy_skipped += 1
            if date_was_fixed:
                json_file.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
                normalized_dates += 1
            fresh_index_reports.append({"date": iso_date, "stats": data["stats"]})
            continue

        # Новый JSON с all_awardees: переприменяем паттерны и пересобираем HTML
        new_data = rebuild_report_from_json(data)
        new_data["date"] = iso_date  # гарантируем ISO
        json_file.write_text(json.dumps(new_data, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        html_path = json_file.with_suffix(".html")
        html_path.write_text(render_report_html(new_data), encoding="utf-8")
        fresh_index_reports.append({"date": iso_date, "stats": new_data["stats"]})
        reprocessed += 1
        if date_was_fixed:
            normalized_dates += 1
        print(f"  {iso_date}: {new_data['stats']['szfo']} из СЗФО "
              f"(из {new_data['stats']['awardees']} всего)", flush=True)

    print(f"✓ Переобработано с новыми паттернами: {reprocessed}", flush=True)
    print(f"✓ Legacy без all_awardees (только дата нормализована): {legacy_skipped}", flush=True)
    if normalized_dates:
        print(f"✓ Поле date нормализовано в {normalized_dates} файл(ах)", flush=True)

    # Обновляем index.json (все даты уже ISO)
    index = {"reports": fresh_index_reports,
             "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}
    INDEX_JSON.write_text(json.dumps(index, ensure_ascii=False, indent=2),
                          encoding="utf-8")

    # Пересобираем страницы регионов и главную
    region_counts = build_region_pages()
    Path("index.html").write_text(
        render_index_html(index, region_counts), encoding="utf-8"
    )
    print(f"✓ Готово: {len(fresh_index_reports)} записей, {len(region_counts)} регионов",
          flush=True)


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════
def debug_region(region_name):
    """Диагностика: печатает все записи, попавшие в указанный регион, с raw,
    position_org и указанием, какой именно паттерн сработал."""
    print(f"═══ ДИАГНОСТИКА региона: '{region_name}' ═══", flush=True)
    if region_name not in REGION_SLUG:
        print(f"⚠ Неизвестный регион. Доступные: {', '.join(REGION_SLUG)}")
        return

    # Находим паттерны для этого региона
    target_patterns = None
    for name, slug, patterns in SZFO_COMPILED:
        if name == region_name:
            target_patterns = patterns
            break

    all_reports = load_all_reports()
    total_hits = 0
    for report in all_reports:
        iso_date = report["date"]
        for reg in report.get("regions", []):
            if reg["name"] != region_name:
                continue
            for award in reg.get("awards", []):
                for person in award.get("people", []):
                    total_hits += 1
                    pos = person.get("position_org", "")
                    raw = person.get("raw", "")

                    pat_pos, hit_pos = _which_pattern_matched(pos, target_patterns)
                    pat_raw, hit_raw = _which_pattern_matched(raw, target_patterns)
                    foreign_pos = _has_foreign_region(pos)
                    foreign_raw = _has_foreign_region(raw)

                    print(f"\n── {iso_date} · {person.get('fio', '?')}")
                    print(f"   награда:      {award['title'][:80]}")
                    print(f"   position_org: {pos[:200]}")
                    if len(pos) > 200:
                        print(f"                 …{pos[200:400]}")
                    print(f"   raw:          {raw[:200]}")
                    if len(raw) > 200:
                        print(f"                 …{raw[200:400]}")
                    if pat_pos:
                        print(f"   ✓ POSITION_ORG сматчил: '{hit_pos}' (паттерн: {pat_pos[:60]})")
                    elif pat_raw:
                        print(f"   ⚠ POSITION_ORG чист, RAW сматчил: '{hit_raw}' (паттерн: {pat_raw[:60]})")
                    else:
                        print(f"   ✗ НЕ ДОЛЖЕН БЫЛ ПОПАСТЬ — паттерны {region_name} не срабатывают!")
                    if foreign_pos:
                        print(f"   ⚠ В position_org есть маркер ЧУЖОГО региона — сейчас должен отсекаться")
                    if foreign_raw:
                        print(f"   ⚠ В raw есть маркер ЧУЖОГО региона — сейчас должен отсекаться")
    print(f"\n═══ Всего записей в '{region_name}': {total_hits} ═══")


def find_person(query):
    """Ищет запись по подстроке в fio во всех reports/*.json (в поле all_awardees
    и в структуре regions). Печатает найденные и подсказывает, где парсер спотыкается."""
    print(f"═══ ПОИСК: '{query}' ═══", flush=True)
    q = query.lower()
    all_reports = load_all_reports()
    found_in_awardees = 0
    found_in_regions = 0

    for report in all_reports:
        iso_date = report["date"]
        # 1. В all_awardees (полный список всех извлечённых, включая не-СЗФО)
        for rec in report.get("all_awardees", []):
            if q in rec.get("fio", "").lower():
                found_in_awardees += 1
                region = match_region(rec.get("position_org", "")) or match_region(rec.get("raw", ""))
                foreign = _has_foreign_region(rec.get("position_org", "")) or _has_foreign_region(rec.get("raw", ""))
                print(f"\n── {iso_date} · В all_awardees ──")
                print(f"   ФИО:          {rec.get('fio')}")
                print(f"   Award:        {rec.get('award', '')[:100]}")
                print(f"   position_org: {rec.get('position_org', '')[:250]}")
                print(f"   raw:          {rec.get('raw', '')[:250]}")
                print(f"   → match_region: {region or 'None'}")
                print(f"   → foreign_region: {foreign}")
                if not region and not foreign:
                    print(f"   ⚠ Не попал в дайджест: паттерны СЗФО не сработали на её тексте")
                elif not region and foreign:
                    print(f"   ⚠ Не попал: сработал фильтр чужого региона")
        # 2. В сгруппированных regions
        for reg in report.get("regions", []):
            for award in reg.get("awards", []):
                for person in award.get("people", []):
                    if q in person.get("fio", "").lower():
                        found_in_regions += 1
                        print(f"\n── {iso_date} · В дайджесте, регион '{reg['name']}' ──")
                        print(f"   ФИО:          {person.get('fio')}")
                        print(f"   Award:        {award['title'][:100]}")
                        print(f"   position_org: {person.get('position_org', '')[:250]}")

    print(f"\n═══ Итого: в all_awardees — {found_in_awardees}, в дайджесте — {found_in_regions} ═══")
    if found_in_awardees == 0 and found_in_regions == 0:
        print("⚠ Ничего не найдено. Возможные причины:")
        print("   • ФИО OCR-нулось с ошибкой (проверьте варианты написания)")
        print("   • Записи нет в поле all_awardees — старый JSON без сохранённых данных")
        print("   • Парсер не распознал строку с ФИО как начало новой записи")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="YYYY-MM-DD (по умолчанию — вчера)")
    parser.add_argument("--rebuild", action="store_true",
                        help="Пересобрать все отчёты из reports/*.json без OCR "
                             "(применить актуальные паттерны регионов)")
    parser.add_argument("--debug-region", metavar="ИМЯ",
                        help="Диагностика: показать все записи в указанном регионе с "
                             "информацией о том, какой паттерн сработал")
    parser.add_argument("--find-person", metavar="СТРОКА",
                        help="Диагностика: найти по подстроке в ФИО во всех отчётах")
    args = parser.parse_args()

    REPORTS_DIR.mkdir(exist_ok=True)

    if args.find_person:
        find_person(args.find_person)
        return

    # Одноразовая миграция файлов (безвредна, если ничего чинить не надо)
    if not args.debug_region:
        n = migrate_legacy_filenames()
        if n:
            print(f"✓ Миграция: перенесено {n} файл(ов) к ISO-формату", flush=True)

    if args.debug_region:
        debug_region(args.debug_region)
        return

    if args.rebuild:
        print("═══ REBUILD-режим: без OCR, применяем актуальные паттерны ═══", flush=True)
        rebuild_all_from_json()
        print("═══ Готово ═══", flush=True)
        return

    if args.date:
        iso_date = args.date
    else:
        iso_date = (date.today() - timedelta(days=1)).isoformat()

    pravo_date = to_pravo_date(iso_date)
    print(f"═══ Дайджест за {iso_date} ({pravo_date}) ═══", flush=True)

    try:
        result = run_pipeline(pravo_date)
        result["date"] = iso_date
    except Exception as e:
        print(f"✗ Ошибка пайплайна: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)

    json_path = REPORTS_DIR / f"{iso_date}.json"
    html_path = REPORTS_DIR / f"{iso_date}.html"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    html_path.write_text(render_report_html(result), encoding="utf-8")
    print(f"✓ Записано: {html_path}, {json_path}", flush=True)

    index = update_index_json(iso_date, result["stats"])
    rebuild_all_daily_pages()
    region_counts = build_region_pages()
    Path("index.html").write_text(
        render_index_html(index, region_counts), encoding="utf-8"
    )
    print(f"✓ Обновлено: index.html ({len(index['reports'])} записей, "
          f"{len(region_counts)} регионов)", flush=True)
    print(f"═══ Готово ═══", flush=True)


if __name__ == "__main__":
    main()
