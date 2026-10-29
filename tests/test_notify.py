"""Тесты уведомлений в Telegram (без сети: отправка подменяется)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import notify_telegram as nt  # noqa: E402


def report(date, awarding, regions):
    szfo = sum(r["count"] for r in regions)
    return {"date": date, "stats": {"documents": 5, "awarding": awarding,
                                    "awardees": 100, "szfo": szfo}, "regions": regions}


REGIONS = [
    {"name": "Санкт-Петербург", "count": 3, "awards": [
        {"title": "ОРДЕНОМ ПОЧЕТА", "people": [{"fio": "А", "kind": "person"},
                                               {"fio": "Б", "kind": "person"}]},
        {"title": "Благодарность", "people": [{"fio": "Коллектив", "kind": "collective"}]}]},
    {"name": "Республика Коми", "count": 1, "awards": [
        {"title": 'Почётное звание "Город трудовой доблести"',
         "people": [{"fio": "г. Ухте", "kind": "city"}]}]},
]


class TestMessages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        for r in [report("2026-10-27", 0, []), report("2026-10-28", 2, REGIONS),
                  report("2026-10-29", 1, [])]:
            (self.dir / f"{r['date']}.json").write_text(json.dumps(r, ensure_ascii=False),
                                                        encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, processed, mode="all", failed=()):
        return nt.build_messages({"processed": processed, "failed": list(failed)},
                                 mode, "https://x.github.io/szfo-monitor/", self.dir)

    def test_day_with_szfo(self):
        (msg,) = self.build(["2026-10-28"])
        self.assertIn("Дайджест СЗФО за 28 октября 2026", msg)
        self.assertIn("награждённых из СЗФО: <b>4</b>", msg)
        self.assertIn("▸ Санкт-Петербург — <b>3</b> (в т.ч. 1 коллектив)", msg)
        self.assertIn("▸ Республика Коми — <b>1</b> (в т.ч. 1 населённый пункт)", msg)
        self.assertIn('href="https://x.github.io/szfo-monitor/reports/2026-10-28.html"', msg)

    def test_empty_day_and_modes(self):
        self.assertEqual(self.build(["2026-10-27"]),
                         ["📭 <b>27 октября 2026</b> — наградных указов нет."])
        self.assertEqual(self.build(["2026-10-27"], mode="awards"), [])
        self.assertEqual(len(self.build(["2026-10-27", "2026-10-28"], mode="awards")), 1)

    def test_awards_without_szfo(self):
        (msg,) = self.build(["2026-10-29"])
        self.assertIn("Награждённых из регионов СЗФО нет.", msg)

    def test_nothing_new_nothing_sent(self):
        # страховочный прогон: новых дней нет → сообщений нет
        self.assertEqual(self.build([]), [])

    def test_failed_dates_reported(self):
        msgs = self.build([], failed=["2026-10-30"])
        self.assertEqual(len(msgs), 1)
        self.assertIn("30 октября 2026", msgs[0])


class TestRunMain(unittest.TestCase):
    def test_not_configured_is_silent(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}), \
             mock.patch.object(sys, "argv", ["notify_telegram.py"]), \
             mock.patch.object(nt.requests, "post") as post:
            self.assertEqual(nt.main(), 0)
            post.assert_not_called()

    def test_failure_message_and_multiple_chats(self):
        env = {"TELEGRAM_BOT_TOKEN": "123:ABC", "TELEGRAM_CHAT_ID": "-1001, 42",
               "GITHUB_REPOSITORY": "AlekseiK83/szfo-monitor", "GITHUB_RUN_ID": "777"}
        resp = mock.Mock(status_code=200)
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(sys, "argv", ["notify_telegram.py", "--failure"]), \
             mock.patch.object(nt.requests, "post", return_value=resp) as post:
            self.assertEqual(nt.main(), 0)
        self.assertEqual(post.call_count, 2)
        chats = [c.kwargs["data"]["chat_id"] for c in post.call_args_list]
        self.assertEqual(chats, ["-1001", "42"])
        text = post.call_args.kwargs["data"]["text"]
        self.assertIn("не прошёл", text)
        self.assertIn("actions/runs/777", text)

    def test_telegram_error_does_not_fail_run(self):
        env = {"TELEGRAM_BOT_TOKEN": "123:ABC", "TELEGRAM_CHAT_ID": "42"}
        resp = mock.Mock(status_code=400, headers={"content-type": "application/json"})
        resp.json.return_value = {"description": "Bad Request: chat not found"}
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(sys, "argv", ["notify_telegram.py", "--failure"]), \
             mock.patch.object(nt.requests, "post", return_value=resp):
            self.assertEqual(nt.main(), 0)

    def test_site_url(self):
        with mock.patch.dict(os.environ, {"SITE_URL": "", "GITHUB_REPOSITORY": "AlekseiK83/szfo-monitor"}):
            self.assertEqual(nt.site_url(), "https://alekseik83.github.io/szfo-monitor/")


def fake_post(responses):
    """requests.post, отвечающий по chat_id: {chat: (status, json)}; getMe — бот."""
    def _post(url, data=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        if method == "getMe":
            status, body = 200, {"ok": True, "result": {"username": "szfo_test_bot"}}
        else:
            status, body = responses[data["chat_id"]]
        r = mock.Mock(status_code=status)
        r.json.return_value = body
        return r
    return _post


OK_USER = (200, {"ok": True, "result": {"id": 123456789, "type": "private", "first_name": "Алексей",
                                         "chat": {"id": 123456789, "type": "private",
                                                  "first_name": "Алексей"}}})
OK_CHANNEL = (200, {"ok": True, "result": {"id": -1009876543210, "type": "channel",
                                            "title": "Наградные указы СЗФО",
                                            "chat": {"id": -1009876543210, "type": "channel",
                                                     "title": "Наградные указы СЗФО"}}})
NOT_FOUND = (400, {"ok": False, "description": "Bad Request: chat not found"})
BLOCKED = (403, {"ok": False, "description": "Forbidden: bot was blocked by the user"})


class TestRecipientsReport(unittest.TestCase):
    CHATS = {"123456789": OK_USER, "-1009876543210": OK_CHANNEL,
             "555000111": NOT_FOUND, "@szfo_nagrady": BLOCKED}
    ENV = {"TELEGRAM_BOT_TOKEN": "123:SECRET", "TELEGRAM_CHAT_ID": ", ".join(CHATS)}

    def run_main(self, argv):
        import io, contextlib
        out = io.StringIO()
        with mock.patch.dict(os.environ, self.ENV), \
             mock.patch.object(sys, "argv", ["notify_telegram.py"] + argv), \
             mock.patch.object(nt.requests, "post", side_effect=fake_post(self.CHATS)) as post, \
             contextlib.redirect_stdout(out):
            self.assertEqual(nt.main(), 0)
        return out.getvalue(), post

    def test_masking(self):
        self.assertEqual(nt.mask_chat("123456789"), "12•••••89")
        self.assertEqual(nt.mask_chat("-1009876543210"), "-10•••••••••10")
        self.assertEqual(nt.mask_chat("@szfo_nagrady"), "@sz•••dy")
        self.assertEqual(nt.mask_name("Алексей"), "Але…")
        self.assertEqual(nt.mask_name("Наградные указы СЗФО"), "Нагр…")

    def test_check_mode_lists_every_recipient(self):
        log, post = self.run_main(["--check"])
        self.assertIn("4 в списке, доставлено 2, не доставлено 2", log)
        self.assertIn("✓ 12•••••89 · личный чат · Але… — доставлено", log)
        self.assertIn("✓ -10•••••••••10 · канал · Нагр… — доставлено", log)
        self.assertIn("✗ 55•••••11 · личный чат — не доставлено: получатель не нажал Start", log)
        self.assertIn("✗ @sz•••dy · канал — не доставлено: получатель заблокировал бота", log)
        methods = [c.args[0].rsplit("/", 1)[-1] for c in post.call_args_list]
        self.assertNotIn("sendMessage", methods)          # без --test ничего не шлём

    def test_check_with_test_message(self):
        log, post = self.run_main(["--check", "--test"])
        sent_to = [c.kwargs["data"]["chat_id"] for c in post.call_args_list
                   if c.args[0].endswith("sendMessage")]
        self.assertEqual(sorted(sent_to), ["-1009876543210", "123456789"])  # только доступным
        self.assertIn("с тестовым сообщением", log)

    def test_digest_run_reports_each_recipient(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd(); os.chdir(tmp)
            try:
                Path("reports").mkdir()
                Path("reports/2026-10-28.json").write_text(json.dumps(
                    report("2026-10-28", 1, REGIONS), ensure_ascii=False), encoding="utf-8")
                Path("run_summary.json").write_text('{"processed": ["2026-10-28"], "failed": []}')
                log, _ = self.run_main([])
            finally:
                os.chdir(cwd)
        self.assertIn("Сообщений в рассылке: 1", log)
        self.assertIn("доставлено 2, не доставлено 2", log)

    def test_full_ids_and_token_never_in_log(self):
        for argv in (["--check"], ["--check", "--test"], ["--failure"]):
            log, _ = self.run_main(argv)
            for secret in ["123456789", "9876543210", "555000111", "szfo_nagrady", "SECRET",
                           "Алексей", "Наградные указы"]:
                self.assertNotIn(secret, log, f"{argv}: в логе «{secret}»")


if __name__ == "__main__":
    unittest.main(verbosity=2)
