"""Post-run guard: the unrelated PLN interview must not remain in events."""
import json
from pathlib import Path

BAD_ARTICLE_PATH = "/automir/606632.html"
events = json.loads(Path("data/news/events.json").read_text(encoding="utf-8"))
for event in events:
    if BAD_ARTICLE_PATH in event.get("link", ""):
        raise SystemExit("FAIL: нерелевантное интервью ПЛН осталось в events.json")
print("PASS: нерелевантное интервью ПЛН отсутствует в events.json")
