#!/usr/bin/env python3
"""Small guarded edit of the CURRENT checkout: preserve unrelated news code."""
import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MONITOR = ROOT / 'news_monitor.py'
WORKFLOW = ROOT / '.github' / 'workflows' / 'news.yml'
MARKER = '# HISTORICAL_APPOINTMENT_GUARD_20261124'

HELPER = '''\n\n# HISTORICAL_APPOINTMENT_GUARD_20261124
# The event is a former job, not a new appointment: e.g., a detained person
# "возглавил компанию ... в конце 2020 года" in a new crime story from 2026.
HISTORICAL_JOB_ACTION = re.compile(
    r"\\b(?:возглавил[аи]?|назначен[аоы]?|назначил[аи]?|"
    r"стал[аи]?\\s+(?:(?:новым|новой)\\s+)?(?:главой|директором|руководителем|председателем|гендиректором))\\b",
    re.I,
)
HISTORICAL_ROLE_YEAR = re.compile(
    r"\\b(?:в\\s+(?:(?:самом\\s+)?(?:конце|начале|середине)\\s+)?|"
    r"с\\s+(?:(?:самого\\s+)?(?:конца|начала|середины)\\s+)?)"
    r"(20\\d{2})\\b",
    re.I,
)
HISTORICAL_CAREER_CONTEXT = re.compile(
    r"\\b(?:практически\\s+с\\s+самого|с\\s+момента\\s+(?:создан|основан|возникнов)|"
    r"ранее\\s+(?:он|она)\\s+возглавлял|много\\s+лет\\s+назад)\\b",
    re.I,
)
CRIME_FOCUSED_HEADLINE = re.compile(
    r"^\\s*(?:задержанн\\w*|арестованн\\w*|осужд[её]нн\\w*|"
    r"обвиняем\\w*|приговор[её]нн\\w*|"
    r"(?:в\\s+\\S+\\s+)?(?:задержал\\w*|задержали|арестовал\\w*|осудил\\w*|"
    r"суд\\s+(?:вынес|приговорил)))(?=\\W)",
    re.I,
)
RECENT_REAL_APPOINTMENT = re.compile(
    r"\\b(?:сегодня|вчера|накануне|на\\s+днях|вновь|снова|повторно)\\b"
    r".{0,85}?\\b(?:возглавил[аи]?|назначен[аоы]?|назначил[аи]?|стал[аи]?)\\b",
    re.I,
)


def historical_appointment_backstory(title, summary):
    """Old career fact reused in a recent publication; do not invent appointment.

    Only match an old year connected to an actual appointment verb, or an
    explicitly retrospective crime-focused headline. A true recent appointment
    of a replacement person in the same news is not suppressed.
    """
    title = normalize(title or '').strip()
    summary = normalize(summary or '').strip()
    crime_focus = bool(CRIME_FOCUSED_HEADLINE.search(title))
    # For a general news title we don't infer an appointment from background
    # summary paragraphs. The exact headline itself is the strongest evidence.
    context = title + (' ' + first_sentence(summary, limit=260) if crime_focus else '')
    # A word such as "сегодня" in "сегодня задержан" does NOT make the
    # historical appointment recent. For crime-led headlines, require an
    # explicit renewed appointment, not merely a recent detention.
    if RECENT_REAL_APPOINTMENT.search(title) and (not crime_focus or re.search(
        r"\\b(?:вновь|снова|повторно)\\b.{0,85}?\\b(?:возглавил[аи]?|назначен[аоы]?)\\b",
        title, re.I)):
        return False
    for verb in HISTORICAL_JOB_ACTION.finditer(context):
        # Retrospective date may also precede the verb: "В конце 2020 года
        # Шмидт возглавил...". Do not suppress "а теперь возглавил".
        earlier = context[max(0, verb.start() - 100):verb.start()]
        for dated in HISTORICAL_ROLE_YEAR.finditer(earlier):
            after_date = earlier[dated.end():]
            if (int(dated.group(1)) <= g.msk_today().year - 2
                    and not re.search(r"\\b(?:а\\s+теперь|теперь|ныне|сейчас|сегодня|накануне|вновь|снова)\\b",
                                      after_date, re.I)):
                return True
        tail = context[verb.end():verb.end() + 215]
        for dated in HISTORICAL_ROLE_YEAR.finditer(tail):
            # "appointed ...; previously worked since 2020" is NOT an old
            # appointment. The date must belong to the same job clause.
            before_date = tail[:dated.start()]
            if re.search(r"(?:[.!?]\\s|\\b(?:до\\s+этого|ранее|раньше|прежде|до\\s+назначения|вместо)\\b)",
                         before_date, re.I):
                continue
            # An old year is a career date; a current-year date could be a
            # newly published appointment and must not be discarded.
            if int(dated.group(1)) <= g.msk_today().year - 2:
                return True
        if crime_focus and HISTORICAL_CAREER_CONTEXT.search(tail):
            return True
    return False
'''

TARGET_FN = 'def event_relevance(title, summary, detection, source, organizations):\n'
AFTER_DOC = '    """Квоты/штат: место работы в СЗФО; остальные события: прежний фильтр."""\n'
BLOCK = '''    if detection["type"] in ("appointment", "ownership") and historical_appointment_backstory(title, summary):
        return False, "historical_appointment_not_new_event"
'''
TEST_STEP = '''      - name: Тест исторических назначений и очистки ранее опубликованных карточек
        run: python -m unittest tests.test_news_historical_appointment -v

'''

def patch_code(raw):
    if MARKER in raw:
        if 'historical_appointment_not_new_event' not in raw:
            raise ValueError('The guard is incomplete: manual review required')
        return raw
    if raw.count(TARGET_FN) != 1 or raw.count(AFTER_DOC) != 1:
        raise ValueError('news_monitor.py has unexpected structure; stop without editing')
    out = raw.replace(TARGET_FN, HELPER + '\n' + TARGET_FN, 1)
    out = out.replace(AFTER_DOC, AFTER_DOC + BLOCK, 1)
    ast.parse(out, filename='news_monitor.py')
    return out


def patch_workflow(raw):
    if 'tests.test_news_historical_appointment' in raw:
        return raw
    if 'run: python news_monitor.py' not in raw or 'jobs:' not in raw:
        raise ValueError('news.yml has unexpected structure; stop without editing')
    import re
    anchor = re.search(r'(?m)^      - name: (?:Подключить Росбалт ко второму потоку|Сбор значимых событий СЗФО|Сбор новостей и поиск событий)\s*$', raw)
    if not anchor:
        raise ValueError('No safe insertion point for test step in news.yml')
    out = raw[:anchor.start()] + TEST_STEP + raw[anchor.start():]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='modify current repository files')
    args = ap.parse_args()
    a = MONITOR.read_text(encoding='utf8')
    b = WORKFLOW.read_text(encoding='utf8')
    a2, b2 = patch_code(a), patch_workflow(b)
    print('Monitor changed:', a2 != a, 'workflow changed:', b2 != b)
    if not args.apply:
        print('Preview only. Use --apply to write.'); return 0
    # All validation completed before touching either file.
    if a2 != a: MONITOR.write_text(a2, encoding='utf8')
    if b2 != b: WORKFLOW.write_text(b2, encoding='utf8')
    print('Patch installed. The normal --rebuild step removes false stored events.')
    return 0

if __name__ == '__main__':
    sys.exit(main())
