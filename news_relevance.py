"""Дополнительная проверка региональной связи события (без внешних зависимостей)."""
import re

# Проверка не блокирует федеральные бренды по имени: важен локальный предмет новости.
LOCAL_ACTION = re.compile(
    r"\b(?:назнач\w*|возглав\w*|избран\w*|утвержд\w*|освобожд\w*|отставк\w*|"
    r"присво\w*|награжд\w*|скончал\w*|умер\w*|открыл\w*|открыти\w*|"
    r"запуст\w*|введ\w*|ввод\w*|спуст\w*|залож\w*|постро\w*|"
    r"посет\w*|прибыл\w*|визит\w*|юбиле\w*|исполнилось|"
    r"побед\w*|получил\w*|вош\w*|банкрот\w*|задержан\w*|"
    r"сменил\w*|контракт\w*|собственник\w*)\b", re.I)

# Небольшие объекты благоустройства — не кадровые, статусные или крупные
# инфраструктурные события. Проверяем тему самого заголовка, а не наличие
# должности губернатора или географической привязки.
MINOR_PUBLIC_SPACE = re.compile(
    r"(?:благоустрой\w*|сквер\w*|детск\w+\s+площадк\w*|"
    r"общественн\w+\s+пространств\w*|пешеходн\w+\s+зон\w*|"
    r"(?:обновл[её]нн\w*|отремонтированн\w*|"
    r"благоустроенн\w*)\s+(?:городск\w+\s+)?территори\w*|"
    r"территори\w*\s+(?:у|возле|вокруг|около)\s+(?:\S+\s+){0,3}?(?:рынк\w*|сквер\w*|парк\w*))",
    re.I,
)

# Юбилеи местных спортивно-досуговых объектов не являются значимым
# кадровым, статусным или инфраструктурным событием. Ограничиваем это
# правило только категорией "anniversary": назначения директоров таких
# учреждений и ввод крупных объектов не должны блокироваться здесь.
MINOR_SPORTS_ANNIVERSARY = re.compile(
    r"\b(?:бассейн\w*|плавательн\w+\s+(?:бассейн\w*|комплекс\w*)|"
    r"спортшкол\w*|спортивн\w+\s+(?:школ\w*|секци\w*|клуб\w*))\b", re.I
)

# Федеральные сюжеты без локального предмета: рейтинги персон, общие заявления.
GENERIC_STORY = re.compile(
    r"\b(?:рассказал\w*|заявил\w*|прокомментировал\w*|объяснил\w*|"
    r"поделил\w*|оценил\w*|вош\w*\s+в\s+рейтинг|"
    r"богатейш\w*|состояни\w*|капитализаци\w*)\b", re.I)


def first_lead(summary, limit=240):
    s = re.sub(r"\s+", " ", summary or "").strip()
    match = re.search(r"[.!?](?:[»\"])?\s", s)
    return s[:match.end()] if match and match.end() <= limit else s[:limit]


def check_relevance(title, summary, detection, source, organizations,
                    find_org_names, news_region):
    """Возвращает (принять, причина). Вызывать после detect_all()."""
    if not detection:
        return False, "no_detected_event"
    # Исключаем малое благоустройство лишь для сопутствующих инфоповодов.
    # Само слово «благоустройство» не должно отсеивать реальные назначения,
    # уход с должности, присвоение звания, некролог или смену собственника.
    core_events = {"appointment", "leave", "title", "obituary", "ownership"}
    if detection.get("type") not in core_events and MINOR_PUBLIC_SPACE.search(title or ""):
        return False, "minor_public_space_not_scope"
    # Юбилей бассейна или местной спортивной школы — вне предмета дайджеста,
    # даже если указан регион или местная организация присутствует в словаре.
    if detection.get("type") == "anniversary" and MINOR_SPORTS_ANNIVERSARY.search(
            f"{title or ''} {first_lead(summary)}"):
        return False, "minor_sports_facility_anniversary"
    title = title or ""
    lead = first_lead(summary)
    anchor = f"{title} {lead}"
    explicit_region = news_region(anchor)
    local_orgs = find_org_names(anchor, organizations)
    # Не разрешаем региональному источнику автоматически легализовать
    # федеральную новость о компании без локального учреждения/предмета.
    if explicit_region:
        return True, "region_in_title_or_lead"
    if local_orgs:
        return True, "known_local_organization"
    is_regional_source = bool(source.get("region")) and not source.get("region_from_text")
    local_institution = detection.get("org_class") in ("gov", "force", "podved")
    if is_regional_source and local_institution and LOCAL_ACTION.search(anchor):
        return True, "regional_institution_event"
    if GENERIC_STORY.search(title):
        return False, "generic_federal_without_local_anchor"
    return False, "missing_regional_event_anchor"
