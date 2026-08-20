"""Генератор дайджеста наградных указов СЗФО за один день.

Использование:
    python generate.py                    # за вчера
    python generate.py --date 2026-08-12  # за конкретную дату

Выход:
    reports/YYYY-MM-DD.html               # красивый отчёт за день
    reports/YYYY-MM-DD.json               # сырые данные
    reports/index.json                    # список обработанных дат
    index.html                            # главная страница со списком
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


def parse_awardees(raw_text, decree_ref):
    text = re.sub(r"(\S)-\s*\n\s*(\S)", r"\1-\2", raw_text)
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
# РЕГИОНЫ СЗФО
# ═══════════════════════════════════════════════════════════════════════
SZFO_REGIONS = [
    ("Санкт-Петербург", [
        r"санкт[-\s]петербург[а-я]*",
        r"г\.?\s*с[.\-]\s*петербург[а-я]*",
        r"\bспб\b",
    ]),
    ("Ленинградская область", [
        r"ленинградск(?:ая|ой|ую|ое|ими|ом)\s+(?:област[ьию]|обл\.)",
    ]),
    ("Архангельская область", [
        r"архангельск(?:ая|ой|ую|ое|ими|ом)\s+(?:област[ьию]|обл\.)",
        r"г\.?\s*архангельск[а-я]*",
        r"\bархангельск(?:а|у|е|ом|ий|ого|ому|им)\b",
    ]),
    ("Вологодская область", [
        r"вологодск(?:ая|ой|ую|ое|ими|ом)\s+(?:област[ьию]|обл\.)",
        r"\bвологд(?:а|ы|у|е|ой)\b",
    ]),
    ("Калининградская область", [
        r"калининградск(?:ая|ой|ую|ое|ими|ом)\s+(?:област[ьию]|обл\.)",
        r"\bкалининград(?:а|у|е|ом)?\b",
    ]),
    ("Мурманская область", [
        r"мурманск(?:ая|ой|ую|ое|ими|ом)\s+(?:област[ьию]|обл\.)",
        r"\bмурманск(?:а|у|е|ом)?\b",
    ]),
    ("Республика Карелия", [
        r"республик[аеиу]\s+карели[яеию]",
        r"\bкарели[яеию]\b",
    ]),
    ("Псковская область", [
        r"псковск(?:ая|ой|ую|ое|ими|ом)\s+(?:област[ьию]|обл\.)",
        r"\bпсков(?:а|у|е|ом)?\b",
    ]),
    ("Республика Коми", [
        r"республик[аеиу]\s+коми",
    ]),
    ("Новгородская область", [
        r"новгородск(?:ая|ой|ую|ое|ими|ом)\s+(?:област[ьию]|обл\.)",
        r"велик(?:ий|ого|ому|им|ом)\s+новгород[а-я]*",
    ]),
]
SZFO_COMPILED = [
    (name, [re.compile(p, re.IGNORECASE) for p in patterns])
    for name, patterns in SZFO_REGIONS
]


def match_region(text):
    if not text:
        return None
    for name, patterns in SZFO_COMPILED:
        if any(p.search(text) for p in patterns):
            return name
    return None


# ═══════════════════════════════════════════════════════════════════════
# ПАЙПЛАЙН
# ═══════════════════════════════════════════════════════════════════════
def run_pipeline(date_str):
    print(f"▶ Запрос за {date_str}", flush=True)
    docs = fetch_documents(date_str)
    print(f"✓ Документов: {len(docs)}", flush=True)

    awarding = [d for d in docs if is_awarding(d)]
    print(f"✓ Наградных: {len(awarding)}", flush=True)

    all_szfo, total = [], 0

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
        total += len(parsed)

        doc_szfo = 0
        for rec in parsed:
            region = match_region(rec["position_org"]) or match_region(rec["raw"])
            if region:
                rec["region"] = region
                all_szfo.append(rec)
                doc_szfo += 1
        print(f"  извлечено {len(parsed)}, из СЗФО: {doc_szfo}", flush=True)

    # Группировка
    by_region = {}
    for a in all_szfo:
        r = by_region.setdefault(a["region"], {"count": 0, "awards": {}})
        r["count"] += 1
        r["awards"].setdefault(a["award"], []).append(a)

    regions = []
    for name, _ in SZFO_REGIONS:
        if name in by_region:
            r = by_region[name]
            regions.append({
                "name": name,
                "count": r["count"],
                "awards": [{"title": t, "people": p_} for t, p_ in r["awards"].items()],
            })

    return {
        "date": date_str,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "stats": {
            "documents": len(docs),
            "awarding": len(awarding),
            "awardees": total,
            "szfo": len(all_szfo),
        },
        "regions": regions,
    }


# ═══════════════════════════════════════════════════════════════════════
# HTML-РЕНДЕР ОТЧЁТА ЗА ДЕНЬ
# ═══════════════════════════════════════════════════════════════════════
BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #f6f2ea; color: #1a1a1a; line-height: 1.55; min-height: 100vh; }
.shell { max-width: 940px; margin: 0 auto; padding: 32px 20px 60px; }
.nav { display: flex; gap: 12px; align-items: center; margin-bottom: 20px; font-size: 14px; }
.nav a { color: #7d1e2a; text-decoration: none; }
.nav a:hover { text-decoration: underline; }
.nav .sep { color: #ccc; }
.report { background: white; border: 1px solid #e8e2d5; border-radius: 10px;
          padding: 48px 56px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }
.report-head { text-align: center; padding-bottom: 22px; border-bottom: 2px solid #b8860b;
               margin-bottom: 26px; }
.report-head h1 { font-family: Georgia, serif; font-size: 24px; font-weight: 500;
                  color: #5c1620; margin-bottom: 8px; }
.period { font-size: 14px; color: #6b6b6b; }
.report-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px;
                margin-bottom: 34px; }
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
.count { font-size: 13px; color: #6b6b6b; }
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
@media (max-width: 640px) {
  .shell { padding: 20px 14px; }
  .report { padding: 26px 20px; }
  .report-stats { grid-template-columns: 1fr; }
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

    regions_html = ""
    if not d["regions"]:
        regions_html = '<div class="no-results">За выбранную дату награждённых ' \
                       'из регионов СЗФО не найдено</div>'
    else:
        for r in d["regions"]:
            regions_html += f'<div class="region-block">' \
                            f'<div class="region-header"><span class="marker">▸</span>' \
                            f'<h2>{esc(r["name"])}</h2>' \
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
  <div class="nav">
    <a href="../index.html">← Все дайджесты</a>
  </div>
  <div class="report">
    <div class="report-head">
      <h1>Дайджест наградных указов СЗФО</h1>
      <div class="period">Период: {esc(display_date)}</div>
    </div>
    <div class="report-stats">{stats_html}</div>
    {regions_html}
    <div class="report-footer">
      Источник: <a href="http://publication.pravo.gov.ru/documents/daily"
                    target="_blank" rel="noopener">publication.pravo.gov.ru</a><br>
      Всего в указах награждённых: {d["stats"]["awardees"]} ·
      Отфильтровано по 10 регионам СЗФО<br>
      Сгенерировано автоматически: {esc(d["generated_at"])}
    </div>
  </div>
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════
# HTML-РЕНДЕР ГЛАВНОЙ СТРАНИЦЫ (ИНДЕКС)
# ═══════════════════════════════════════════════════════════════════════
def render_index_html(index_data):
    esc = html_module.escape
    entries = sorted(index_data["reports"], key=lambda x: x["date"], reverse=True)

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
        rows_html = '<div class="no-results">Дайджесты пока не сгенерированы. ' \
                    'Первый прогон workflow скоро создаст запись.</div>'

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
           margin-bottom: 24px; }}
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
  <div class="entries">{rows_html}</div>
  <div class="updated">Обновлено: {esc(last_update)} UTC ·
    Автоматически ежедневно</div>
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНОЕ
# ═══════════════════════════════════════════════════════════════════════
MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня",
             "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def format_display_date(iso_date):
    """2026-08-17 → 17 августа 2026"""
    try:
        y, m, d = iso_date.split("-")
        return f"{int(d)} {MONTHS_RU[int(m) - 1]} {y}"
    except (ValueError, IndexError):
        return iso_date


def to_pravo_date(iso_date):
    """2026-08-17 → 17.08.2026"""
    y, m, d = iso_date.split("-")
    return f"{d}.{m}.{y}"


def update_index_json(iso_date, stats):
    index = {"reports": [], "updated_at": ""}
    if INDEX_JSON.exists():
        try:
            index = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Убираем предыдущую запись за эту дату, добавляем новую
    index["reports"] = [r for r in index["reports"] if r["date"] != iso_date]
    index["reports"].append({"date": iso_date, "stats": stats})
    index["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    INDEX_JSON.write_text(json.dumps(index, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    return index


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="YYYY-MM-DD (по умолчанию — вчера)")
    args = parser.parse_args()

    if args.date:
        iso_date = args.date
    else:
        iso_date = (date.today() - timedelta(days=1)).isoformat()

    pravo_date = to_pravo_date(iso_date)
    REPORTS_DIR.mkdir(exist_ok=True)

    print(f"═══ Дайджест за {iso_date} ({pravo_date}) ═══", flush=True)

    try:
        result = run_pipeline(pravo_date)
    except Exception as e:
        print(f"✗ Ошибка пайплайна: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)

    # Сохраняем JSON и HTML отчёта за день
    json_path = REPORTS_DIR / f"{iso_date}.json"
    html_path = REPORTS_DIR / f"{iso_date}.html"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    html_path.write_text(render_report_html(result), encoding="utf-8")
    print(f"✓ Записано: {html_path}, {json_path}", flush=True)

    # Обновляем index.json и перегенерируем index.html
    index = update_index_json(iso_date, result["stats"])
    Path("index.html").write_text(render_index_html(index), encoding="utf-8")
    print(f"✓ Обновлено: index.html ({len(index['reports'])} записей)", flush=True)

    print(f"═══ Готово ═══", flush=True)


if __name__ == "__main__":
    main()
