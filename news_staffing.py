"""Строгий детектор значимых решений о кадровой потребности в СЗФО.

Не рассматривает согласованную квоту как фактически нанятый персонал.
Изолирован от первого потока (generate.py) и от отправки Telegram.
"""

import re

# Консервативный порог: только масштабные решения, а не вакансии и частный найм.
MIN_SIGNIFICANT_JOBS = 100

_QUANTITY = r"(?:\d{1,3}(?:[\s\u00a0]\d{3})+|\d{1,6}(?:[.,]\d+)?)"
_MAGNITUDE = r"(?:тыс\.?|тысяч\w*|млн\.?|миллион\w*)"
_STAFF_UNIT = (r"(?:квот\w*|разрешен\w*\s+на\s+работу|"
               r"рабоч\w*\s+мест\w*|штатн\w*\s+единиц\w*|"
               r"работник\w*|сотрудник\w*|специалист\w*|человек|рабочих\b)")
_QTY_BEFORE_UNIT = re.compile(
    rf"(?<!\w)(?P<num>{_QUANTITY})\s*(?P<mag>{_MAGNITUDE})?\s+"
    rf"(?:нов\w*\s+|дополнительн\w*\s+|иностранн\w*\s+|"
    rf"трудов\w*\s+|визов\w*\s+){{0,3}}{_STAFF_UNIT}", re.I)
_STAFF_EXPANSION = re.compile(
    rf"\b(?:увелич\w*|расшир\w*|нараст\w*)\s+(?:штат\w*|"
    rf"численност\w*\s+(?:штат\w*|персонал\w*|работник\w*))\s+"
    rf"(?:на|до)\s+(?P<num>{_QUANTITY})\s*(?P<mag>{_MAGNITUDE})?\b", re.I)

_CONFIRMED = re.compile(
    r"\b(?:согласовал\w*|согласован\w*|одобрил\w*|одобрен\w*|"
    r"утвердил\w*|утвержден\w*|утверждён\w*|"
    r"выделил\w*|выделен\w*|выделён\w*|"
    r"увеличил\w*|увеличен\w*|расширил\w*|расширен\w*|"
    r"создал\w*|создан\w*|закрепил\w*|закрепл[её]н\w*|"
    r"получил\w*\s+(?:квот\w*|разрешен\w*)|"
    r"открыл\w*\s+\d+\s+новых\s+рабочих\s+мест)\b", re.I)
_NEGATIVE_OR_SPECULATION = re.compile(
    r"\b(?:планиру\w*|планирует\w*|намерен\w*|собира\w*|"
    r"могут\s+(?:выделить|согласовать|нанять)|"
    r"просят\s+(?:выделить|согласовать)|"
    r"предложил\w*|отказал\w*|отклонен\w*|отклонён\w*)\b", re.I)

# Привязка к месту работы. Иностранное гражданство персонала НЕ считается
# иностранным регионом выполнения работ. Не достаточно одного местного СМИ.
_REGION_PATTERNS = (
    ("Ленинградская область", r"ленинградск\w*\s+област\w*|ленобласт\w*|усть[-–\s]луг\w*|кингисепп\w*|всеволожск\w*|гатчин\w*|выборг\w*|тихвин\w*|сосн\w*\s+бор\w*"),
    ("Санкт-Петербург", r"санкт[-\s]петербург\w*|петербург\w*|питер\w*"),
    ("Архангельская область", r"архангельск\w*\s+област\w*|архангельск\w*|северодвинск\w*|котлас\w*"),
    ("Вологодская область", r"вологодск\w*\s+област\w*|вологд\w*|череповц\w*|череповец\w*"),
    ("Калининградская область", r"калининградск\w*\s+област\w*|калининград\w*|советск\w*\s+калининградск\w*"),
    ("Мурманская область", r"мурманск\w*\s+област\w*|мурманск\w*|мончегорск\w*|апатит\w*"),
    ("Новгородская область", r"новгородск\w*\s+област\w*|велик\w*\s+новгород\w*|борович\w*"),
    ("Псковская область", r"псковск\w*\s+област\w*|псков\w*|велик\w*\s+лук\w*"),
    ("Республика Карелия", r"республик\w*\s+карели\w*|карели\w*|петрозаводск\w*|костомукш\w*"),
    ("Республика Коми", r"республик\w*\s+коми\b|\bкоми\b|сыктывкар\w*|ухт\w*|воркут\w*"),
    ("Ненецкий автономный округ", r"ненецк\w*\s+автономн\w*\s+округ\w*|нарьян[-\s]мар\w*"),
)
_REGION_COMPILED = tuple((region, re.compile(
    rf"\b(?:в|во|на|под|возле|для|по|около)\s+(?:{pat})\b|"
    rf"\b(?:правительств\w*|администраци\w*|комисси\w*)\s+(?:{pat})\b", re.I))
    for region, pat in _REGION_PATTERNS)


def _number(num, magnitude):
    n = float(num.replace("\u00a0", " ").replace(" ", "").replace(",", "."))
    if magnitude:
        m = magnitude.lower()
        n *= 1_000_000 if m.startswith(("млн", "миллион")) else 1_000
    return n


def _headline_and_lead(title, summary):
    # Короткое начало статьи; поздние случайные географические/числовые
    # упоминания не должны определять тему публикации.
    summary = re.sub(r"\s+", " ", summary or "").strip()
    m = re.search(r"[.!?]\s", summary)
    lead = summary[:m.end()] if m and m.end() <= 380 else summary[:380]
    return f"{title or ''} {lead}".strip()


def staffing_region(text):
    """Регион фактического места/объекта работ (не гражданства работников)."""
    for region, pat in _REGION_COMPILED:
        if pat.search(text or ""):
            return region
    return None


def detect_staffing(title, summary, organizations, find_org_names):
    """Новое событие workforce либо None; не заменяет назначения руководителей."""
    text = _headline_and_lead(title, summary)
    # Требуем локальную площадку, не просто региональную редакцию или бренд.
    if not staffing_region(text):
        return None
    approves = list(_CONFIRMED.finditer(text))
    if not approves:
        return None
    quantities = list(_QTY_BEFORE_UNIT.finditer(text)) + list(_STAFF_EXPANSION.finditer(text))
    for match in quantities:
        if _number(match.group("num"), match.group("mag")) < MIN_SIGNIFICANT_JOBS:
            continue
        # Решение должно относиться к цифре, а не просто находиться где-то в статье.
        if min(abs(a.start() - match.start()) for a in approves) > 150:
            continue
        context = text[max(0, match.start()-80):match.end()+30]
        # Нельзя принять отдельную отклоненную заявку, но отрицание в другой
        # части статьи о других компаниях не блокирует согласованный проект.
        if _NEGATIVE_OR_SPECULATION.search(context) and not _CONFIRMED.search(context):
            continue
        orgs = find_org_names(text, organizations)
        return {"type": "workforce", "level": "head", "org_class": "company", "orgs": orgs}
    return None


def staffing_region_for_story(title, summary):
    return staffing_region(_headline_and_lead(title, summary))


def workforce_fingerprint(event):
    """Одинаковая кадровая квота в разных публикациях -> один ключ.

    Компания + площадка + точная численность + тип решения. В пределах
    45 дней отсечения seen не считаем дату перепечатки новой публикацией.
    Важно: год квоты может отсутствовать в коротком RSS-анонсе.
    """
    title = event.get("title", "")
    summary = event.get("summary", "")
    txt = _headline_and_lead(title, summary).lower().replace("ё", "е")
    company = "seven" if re.search(r"\bсевен\b|\bseven\b", txt) else ""
    if not company:
        orgs = event.get("orgs", [])
        company = re.sub(r"[^а-яa-z0-9]", "", orgs[0].lower().replace("ё", "е")) if orgs else "other"
    site = "ustluga" if re.search(r"усть[-–\s]?луг", txt) else re.sub(
        r"[^а-яa-z0-9]", "", event.get("region", "").lower().replace("ё", "е"))
    category = "quota" if re.search(r"квот|разрешен\w*\s+на\s+работу", txt) else "staff"
    matches = list(_QTY_BEFORE_UNIT.finditer(txt)) + list(_STAFF_EXPANSION.finditer(txt))
    # Точная численность без округления предпочтительнее 'почти 19 тысяч'.
    precise = [m for m in matches if not m.group("mag") and
               _number(m.group("num"), m.group("mag")) >= MIN_SIGNIFICANT_JOBS]
    chosen = precise[0] if precise else (matches[0] if matches else None)
    amount = int(round(_number(chosen.group("num"), chosen.group("mag")))) if chosen else 0
    return f"workforce:{event.get('region', '')}:{company}:{site}:{category}:{amount}"
