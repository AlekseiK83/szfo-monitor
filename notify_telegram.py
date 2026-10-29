"""Уведомления о ежедневном прогоне в Telegram.

Запускается шагом GitHub Actions после генерации дайджеста:
    python notify_telegram.py            — сводка по обработанным дням
    python notify_telegram.py --failure  — сообщение о сбое прогона

Настройки (Settings → Secrets and variables → Actions):
    секрет   TELEGRAM_BOT_TOKEN  — токен бота от @BotFather
    секрет   TELEGRAM_CHAT_ID    — id чата/канала; несколько — через запятую
    перемен. TELEGRAM_MODE       — all (по умолчанию): сообщение каждый день;
                                   awards: только дни с наградными документами
Если токен или chat_id не заданы — скрипт тихо завершается, прогон не падает.
"""
import argparse
import html
import json
import os
import sys
from pathlib import Path

import requests

REPORTS_DIR = Path("reports")
RUN_SUMMARY = Path("run_summary.json")
TG_LIMIT = 4096

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря"]


def human_date(iso):
    y, m, d = iso.split("-")
    return f"{int(d)} {MONTHS_GEN[int(m) - 1]} {y}"


def site_url():
    """https://<owner>.github.io/<repo>/ — или SITE_URL, если задан."""
    explicit = os.environ.get("SITE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/") + "/"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


def plural(n, one, few, many):
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    return {1: one, 2: few, 3: few, 4: few}.get(n % 10, many)


def day_message(report, base_url):
    """Текст сообщения (HTML-разметка Telegram) по одному дню."""
    e = html.escape
    iso = report["date"]
    st = report.get("stats", {})
    awarding, szfo = st.get("awarding", 0), st.get("szfo", 0)
    link = f"{base_url}reports/{iso}.html" if base_url else ""

    if not awarding:
        return f"📭 <b>{e(human_date(iso))}</b> — наградных указов нет."

    lines = [f"🏛 <b>Дайджест СЗФО за {e(human_date(iso))}</b>",
             f"Наградных документов: <b>{awarding}</b> · "
             f"награждённых из СЗФО: <b>{szfo}</b>"]
    if szfo:
        lines.append("")
        for r in report.get("regions", []):
            kinds = {"collective": 0, "city": 0}
            for a in r.get("awards", []):
                for p in a.get("people", []):
                    if p.get("kind") in kinds:
                        kinds[p["kind"]] += 1
            extra = []
            if kinds["collective"]:
                extra.append(f'{kinds["collective"]} {plural(kinds["collective"], "коллектив", "коллектива", "коллективов")}')
            if kinds["city"]:
                extra.append(f'{kinds["city"]} {plural(kinds["city"], "населённый пункт", "населённых пункта", "населённых пунктов")}')
            tail = f" (в т.ч. {', '.join(extra)})" if extra else ""
            lines.append(f"▸ {e(r['name'])} — <b>{r['count']}</b>{e(tail)}")
    else:
        lines.append("Награждённых из регионов СЗФО нет.")
    if link:
        lines += ["", f'<a href="{e(link)}">Открыть дайджест →</a>']
    return "\n".join(lines)


def failure_message():
    e = html.escape
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    text = ("⚠️ <b>Ежедневный прогон дайджеста СЗФО не прошёл.</b>\n"
            "Данные на сайте не обновлялись. Пропущенные дни обработаются "
            "автоматически при следующем успешном прогоне.")
    if repo and run_id:
        text += f'\n\n<a href="{e(f"{server}/{repo}/actions/runs/{run_id}")}">Открыть лог прогона →</a>'
    return text


def build_messages(summary, mode, base_url, reports_dir=REPORTS_DIR):
    """Список сообщений по итогу прогона. Пустой список — отправлять нечего."""
    messages = []
    for iso in summary.get("processed", []):
        path = reports_dir / f"{iso}.json"
        if not path.exists():
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        if mode == "awards" and not report.get("stats", {}).get("awarding"):
            continue
        messages.append(day_message(report, base_url))
    failed = summary.get("failed", [])
    if failed:
        messages.append("⚠️ Не удалось обработать: "
                        + ", ".join(html.escape(human_date(d)) for d in failed)
                        + ". Повторная попытка — при следующем прогоне.")
    return [m[:TG_LIMIT] for m in messages]


def send(token, chat_ids, text):
    ok = True
    for chat in chat_ids:
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              data={"chat_id": chat, "text": text, "parse_mode": "HTML",
                                    "disable_web_page_preview": "true"},
                              timeout=30)
            if r.status_code != 200:
                # описание ошибки от Telegram, без токена
                try:
                    desc = r.json().get("description") or f"HTTP {r.status_code}"
                except Exception:
                    desc = f"HTTP {r.status_code}"
                print(f"⚠ Telegram отклонил сообщение для чата {chat}: {desc}", flush=True)
                ok = False
        except requests.RequestException as ex:
            print(f"⚠ Не удалось связаться с Telegram ({type(ex).__name__})", flush=True)
            ok = False
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--failure", action="store_true", help="сообщить о сбое прогона")
    args = ap.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    if not token or not chat_ids:
        print("Telegram не настроен (нет TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID) — пропускаю.")
        return 0

    if args.failure:
        messages = [failure_message()]
    else:
        if not RUN_SUMMARY.exists():
            print("Нет run_summary.json — нечего отправлять.")
            return 0
        summary = json.loads(RUN_SUMMARY.read_text(encoding="utf-8"))
        mode = os.environ.get("TELEGRAM_MODE", "all").strip().lower() or "all"
        messages = build_messages(summary, mode, site_url())
        if not messages:
            print("Новых дней нет — уведомление не нужно.")
            return 0

    sent = sum(send(token, chat_ids, m) for m in messages)
    print(f"✓ Отправлено сообщений: {sent}/{len(messages)} в {len(chat_ids)} чат(а/ов)")
    return 0  # уведомления не должны валить прогон


if __name__ == "__main__":
    sys.exit(main())
