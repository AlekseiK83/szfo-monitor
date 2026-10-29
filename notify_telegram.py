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


# ── Отчёт о получателях ──
# Репозиторий публичный, логи Actions видны всем, поэтому chat_id и имена
# в логе частично скрываются: видно ровно столько, чтобы узнать «своего».

def mask_chat(chat):
    """«123456789» → «12•••••89», «@szfo_nagrady» → «@sz•••dy»."""
    c = str(chat)
    if c.startswith("@"):
        name = c[1:]
        return "@" + (name[:2] + "•••" + name[-2:] if len(name) > 5 else name[:1] + "•••")
    sign = "-" if c.startswith("-") else ""
    digits = c.lstrip("-")
    if len(digits) <= 4:
        return sign + "•" * len(digits)
    return sign + digits[:2] + "•" * (len(digits) - 4) + digits[-2:]


def mask_name(name):
    """«Алексей» → «Але…», «Наградные указы СЗФО» → «Нагр…»."""
    name = (name or "").strip()
    if not name:
        return ""
    keep = 3 if len(name) <= 10 else 4
    return name[:keep] + "…" if len(name) > keep else name[:1] + "…"


def chat_kind(chat, info=None):
    t = (info or {}).get("type")
    if t:
        return {"private": "личный чат", "channel": "канал",
                "group": "группа", "supergroup": "группа"}.get(t, t)
    c = str(chat)
    if c.startswith("@"):
        return "канал"
    return "группа или канал" if c.startswith("-") else "личный чат"


HINTS = [
    ("chat not found", "получатель не нажал Start в боте или chat_id с ошибкой"),
    ("bot was blocked", "получатель заблокировал бота"),
    ("user is deactivated", "аккаунт получателя удалён"),
    ("bot is not a member", "бот не добавлен в канал/группу"),
    ("not enough rights", "у бота нет права публиковать сообщения в канале"),
    ("need administrator rights", "бот должен быть администратором канала"),
    ("unauthorized", "неверный токен бота (TELEGRAM_BOT_TOKEN)"),
    ("too many requests", "слишком много сообщений подряд, Telegram попросил подождать"),
]


def explain(desc):
    d = (desc or "").lower()
    for key, hint in HINTS:
        if key in d:
            return hint
    return desc or "неизвестная ошибка"


def _post(token, method, data):
    """(ok, result|описание ошибки). Токен в лог не попадает."""
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/{method}", data=data, timeout=30)
    except requests.RequestException as ex:
        return False, f"нет связи с Telegram ({type(ex).__name__})"
    try:
        body = r.json()
    except Exception:
        body = {}
    if r.status_code == 200 and body.get("ok", True):
        return True, body.get("result") or {}
    return False, body.get("description") or f"HTTP {r.status_code}"


def recipient_label(chat, info=None):
    info = info or {}
    name = info.get("title") or " ".join(
        x for x in (info.get("first_name"), info.get("last_name")) if x)
    label = f"{mask_chat(chat)} · {chat_kind(chat, info)}"
    return label + (f" · {mask_name(name)}" if name else "")


def send(token, chat_ids, text, report=None):
    """Отправляет text каждому получателю. report: dict chat → (ok, info|ошибка),
    в него складывается результат по каждому чату."""
    ok_all = True
    for chat in chat_ids:
        ok, res = _post(token, "sendMessage", {"chat_id": chat, "text": text, "parse_mode": "HTML",
                                                "disable_web_page_preview": "true"})
        ok_all &= ok
        if report is not None:
            prev = report.get(chat)
            if prev is None or prev[0]:      # первая ошибка по чату сохраняется
                report[chat] = (ok, (res.get("chat") if ok and isinstance(res, dict) else res))
    return ok_all


def print_report(report, title="Получатели"):
    delivered = [c for c, (ok, _) in report.items() if ok]
    print(f"\n── {title}: {len(report)} в списке, доставлено {len(delivered)}, "
          f"не доставлено {len(report) - len(delivered)} ──", flush=True)
    for chat, (ok, info) in report.items():
        if ok:
            print(f"  ✓ {recipient_label(chat, info if isinstance(info, dict) else None)} — доставлено",
                  flush=True)
        else:
            print(f"  ✗ {recipient_label(chat)} — не доставлено: {explain(info)}", flush=True)


def check_recipients(token, chat_ids, send_test=False):
    """Проверка списка без рассылки дайджеста: getChat по каждому получателю,
    по желанию — тестовое сообщение."""
    ok_bot, me = _post(token, "getMe", {})
    if not ok_bot:
        print(f"✗ Бот недоступен: {explain(me)}", flush=True)
        return {}
    print(f"Бот: @{me.get('username', '?')}", flush=True)
    report = {}
    for chat in chat_ids:
        ok, res = _post(token, "getChat", {"chat_id": chat})
        report[chat] = (ok, res)
    if send_test:
        text = ("✅ <b>Тестовое сообщение</b>\nВы подписаны на ежедневные сводки "
                "дайджеста наградных указов СЗФО.")
        reachable = [c for c, (ok, _) in report.items() if ok]
        test_report = {}
        send(token, reachable, text, test_report)
        for c, val in test_report.items():
            if not val[0]:
                report[c] = val
    print_report(report, "Проверка получателей" + (" (с тестовым сообщением)" if send_test else ""))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--failure", action="store_true", help="сообщить о сбое прогона")
    ap.add_argument("--check", action="store_true", help="проверить список получателей")
    ap.add_argument("--test", action="store_true", help="вместе с --check: разослать тестовое сообщение")
    args = ap.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    if not token or not chat_ids:
        print("Telegram не настроен (нет TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID) — пропускаю.")
        return 0

    if args.check:
        check_recipients(token, chat_ids, send_test=args.test)
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

    report = {}
    for m in messages:
        send(token, chat_ids, m, report)
    print(f"Сообщений в рассылке: {len(messages)}", flush=True)
    print_report(report)
    return 0  # уведомления не должны валить прогон


if __name__ == "__main__":
    sys.exit(main())
