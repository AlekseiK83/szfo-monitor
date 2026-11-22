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
