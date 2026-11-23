"""Добавляет источник Росбалт без изменения остальных 80+ источников.
Запускается перед сбором второго потока. Повторный запуск идемпотентен.
"""
import json
from pathlib import Path

P = Path("news_sources.json")

def main():
    data = json.loads(P.read_text(encoding="utf-8"))
    if any(s.get("id") == "rosbalt" for s in data["sources"]):
        print("Источник Росбалт уже настроен")
        return
    data["sources"].append({
        "id": "rosbalt",
        "name": "Росбалт",
        "type": "site",
        "url": "https://www.rosbalt.ru/",
        "news_url": "https://www.rosbalt.ru/news",
        "region": None,
        "verified": False,
        "rank": 2,
    })
    P.write_text(json.dumps(data, ensure_ascii=False, indent=1)+"\n", encoding="utf-8")
    print("Добавлен источник Росбалт; доступность HTML/RSS проверяется при прогоне")

if __name__ == "__main__":
    main()
