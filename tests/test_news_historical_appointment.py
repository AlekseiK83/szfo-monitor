"""Regression: a recent publication can contain a historical job, not a new one."""
import unittest

import news_monitor as nm

ORG = {'Санкт-Петербург': ['Метрострой Северной столицы', 'Метрострой', 'Пилон']}
SOURCE = {'id': 'fontanka_tg', 'name': 'Фонтанка (Telegram)', 'type': 'telegram', 'region': 'Санкт-Петербург', 'rank': 3}
BAD = ('Задержанный в Петербурге Владимир Шмидт возглавил «Метрострой Северной столицы» '
       'практически с самого его возникновения в конце 2020 года (до этого он был известен как '
       'многолетний директор компании «Пилон», успел поработать и в руководстве КРТИ).')
GOOD = 'После задержания прежнего директора компанию «Метрострой Северной столицы» возглавил новый гендиректор Иван Петров'


class HistoricalAppointmentTests(unittest.TestCase):
    def classification(self, title, summary=''):
        d = nm.detect_all(title, summary, ORG)
        if not d:
            return None, (False, 'not_detected')
        return d, nm.event_relevance(title, summary, d, SOURCE, ORG)

    def test_exact_fontanka_publication_rejected(self):
        d, result = self.classification(BAD, BAD)
        self.assertEqual(d['type'], 'appointment')
        self.assertEqual(result, (False, 'historical_appointment_not_new_event'))

    def test_shorter_fontanka_version_rejected(self):
        d, result = self.classification(BAD[:145], BAD)
        self.assertEqual(result[1], 'historical_appointment_not_new_event')

    def test_unrelated_2020_career_in_crime_story_rejected(self):
        title = 'Осужденный директор завода возглавил компанию в 2020 году'
        _, result = self.classification(title)
        self.assertEqual(result[1], 'historical_appointment_not_new_event')

    def test_old_job_2022_without_crime_is_not_fresh_appointment(self):
        title = 'Иван Сидоров возглавил «Метрострой Северной столицы» ещё в 2022 году'
        d, result = self.classification(title)
        self.assertEqual(d['type'], 'appointment')
        self.assertEqual(result[1], 'historical_appointment_not_new_event')

    def test_crime_focused_title_summary_with_old_job_rejected(self):
        title = 'Задержанный в Петербурге директор строительной компании'
        summary = 'Владимир Шмидт возглавил «Метрострой Северной столицы» в конце 2020 года.'
        # Even if the primary detector does not fire, no wrong event is accepted.
        self.assertTrue(nm.historical_appointment_backstory(title, summary))
        d, result = self.classification(title, summary)
        self.assertFalse(result[0])

    def test_new_replacement_after_detention_preserved(self):
        d, result = self.classification(GOOD)
        self.assertEqual(d['type'], 'appointment')
        self.assertTrue(result[0], result)

    def test_new_appointment_may_mention_predecessor_old_history(self):
        title = 'Новым директором «Метростроя Северной столицы» назначен Иван Петров'
        summary = 'Предыдущий директор возглавил компанию с 2020 года, его позднее задержали.'
        d, result = self.classification(title, summary)
        self.assertEqual(d['type'], 'appointment')
        self.assertTrue(result[0], result)

    def test_new_appointment_not_rejected_by_old_job_in_same_title(self):
        title = ('Мария Петрова возглавила «Метрострой Северной столицы», '
                 'ранее руководила строительным подразделением с 2020 года')
        d, result = self.classification(title)
        self.assertEqual(d['type'], 'appointment')
        self.assertTrue(result[0], result)

    def test_historical_date_before_hiring_verb_requires_further_evidence(self):
        title = 'В конце 2020 года Иван Сидоров возглавил «Метрострой Северной столицы»'
        self.assertTrue(nm.historical_appointment_backstory(title, ''))
        _, result = self.classification(title)
        self.assertEqual(result[1], 'historical_appointment_not_new_event')

    def test_old_year_before_new_appointment_does_not_block_it(self):
        title = ('В 2020 году Иван Петров работал инженером, а теперь '
                 'возглавил «Метрострой Северной столицы»')
        d, result = self.classification(title)
        self.assertEqual(d['type'], 'appointment')
        self.assertTrue(result[0], result)

    def test_appointment_this_year_is_current(self):
        title = 'В 2026 году Иван Петров возглавил «Метрострой Северной столицы»'
        d, result = self.classification(title)
        self.assertEqual(d['type'], 'appointment')
        self.assertTrue(result[0], result)

    def test_today_refers_to_detention_not_appointment(self):
        title = ('Задержанный сегодня в Петербурге Владимир Шмидт возглавил '
                 '«Метрострой Северной столицы» в конце 2020 года')
        _, result = self.classification(title)
        self.assertEqual(result[1], 'historical_appointment_not_new_event')

    def test_recent_appointment_with_detention_word_preserved(self):
        title = 'После задержания прежнего руководителя на пост директора «Метростроя Северной столицы» назначен Иван Петров'
        d, result = self.classification(title)
        self.assertEqual(d['type'], 'appointment')
        self.assertTrue(result[0], result)

    def test_explicit_repeat_appointment_not_suppressed(self):
        title = 'Иван Петров снова возглавил «Метрострой Северной столицы» после задержания прежнего директора'
        d, result = self.classification(title)
        self.assertEqual(d['type'], 'appointment')
        self.assertTrue(result[0], result)

    def test_real_official_proceeding_unchanged(self):
        title = 'Сотрудниками МВД России задержан губернатор Мурманской области Андрей Чибис'
        summary = 'Сотрудники МВД России подтвердили задержание губернатора Мурманской области Андрея Чибиса.'
        # Any existing proceeding detection must NOT be affected by history guard.
        d = nm.detect_all(title, summary, ORG)
        self.assertEqual(d['type'], 'proceeding')
        self.assertFalse(nm.historical_appointment_backstory(title, summary))

    def test_reconcile_removes_saved_wrong_card_but_keeps_other(self):
        cfg = {'sources': [SOURCE], 'organizations': ORG}
        def ev(title, datevalue='2026-11-24'):
            return {'type': 'appointment', 'level': 'head', 'org_class': 'business',
                    'region': 'Санкт-Петербург', 'title': title,
                    'summary': title, 'source': SOURCE['name'], 'source_id': SOURCE['id'],
                    'date': datevalue, 'link': 'https://t.me/fontankaspb/114446',
                    'orgs': ['Метрострой Северной столицы'], 'rank': 3}
        cleaned, _ = nm.reconcile([ev(BAD), ev(GOOD)], cfg)
        self.assertEqual(len(cleaned), 1, cleaned)
        self.assertIn('Иван Петров', cleaned[0]['title'])

    def test_guard_is_idempotent_and_does_not_depend_on_whitelist(self):
        self.assertTrue(nm.historical_appointment_backstory(BAD, BAD))
        self.assertTrue(nm.historical_appointment_backstory(BAD, ''))
        self.assertFalse(nm.historical_appointment_backstory(GOOD, ''))

if __name__ == '__main__':
    unittest.main()
