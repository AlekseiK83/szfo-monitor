"""Контроль 23 ноября: публикация должна быть сохранена как значимый персонал.
Во все остальные дни проверка пропускается без изменения расписания.
"""
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

URL = ("https://www.rosbalt.ru/news/2026-11-23/"
       "zabrali-82-vseh-kvot-v-2027-godu-v-lenoblast-priedut-18-6-tys-rabochih-iz-kitaya-5739313")
DATE = "2026-11-23"


def check_for_date(day):
    if day != DATE:
        print("Контроль Росбалта 23.11: пропуск — другая дата")
        return True
    events = json.loads(Path("data/news/events.json").read_text(encoding="utf8"))
    summary = json.loads(Path("run_summary_news.json").read_text(encoding="utf8"))
    matching = [e for e in events if e.get("link", "").split("?")[0] == URL]
    if not matching:
        raise AssertionError("Публикация Росбалта отсутствует в events.json: проверка 23.11 НЕ ПРОЙДЕНА")
    if not all(e.get("type") == "workforce" and
               e.get("region") == "Ленинградская область" and
               e.get("date") == DATE for e in matching):
        raise AssertionError("Ошибка категории, региона или даты публикации")
    fresh = [e for e in summary.get("new", []) if e.get("link", "").split("?")[0] == URL]
    print(f"PASS: статья Росбалта опубликована в events.json; новых событий для Telegram: {len(fresh)}")
    if not fresh:
        print("Примечание: повторный запуск не должен повторно рассылать уже сохранённую статью")
    return True


if __name__ == "__main__":
    today = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    check_for_date(today)
