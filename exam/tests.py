import importlib
import json

from django.apps import apps as global_apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .grading import answer_index, split_option_label
from .models import Bookmark, Category, Exam, ExamResult, Question


def make_question(exam, order, answer, category=None, text=None, **options):
    fields = {f'option{i}': f'{"가나다라마"[i - 1]}. 보기{i}' for i in range(1, 6)}
    fields.update(options)
    return Question.objects.create(exam=exam, order=order, correct_option=answer, category=category,
                                   question_text=text or f'{exam.title} 문제 {order}', comment='해설', **fields)


class AnswerIndexTests(TestCase):
    def test_answer_formats(self):
        cases = {
            '다': 3, '㉯': 2, '가/가(GPT5)': 1, '마(GPT5)/미정': 5, '/나(GPT5)': 2, '4.': 4,
            '​라': 4, '①': 1, 'C': 3,
            '미정/마(GPT5)': None, '미정(가or나)': None, 'default': None, '': None, None: None,
        }
        for text, expected in cases.items():
            self.assertEqual(answer_index(text), expected, text)

    def test_option_label_is_split_only_when_it_matches_the_position(self):
        cases = [
            (('㉮ 도파민', 1), ('㉮', '도파민')),
            (('가. substance P', 1), ('가', 'substance P')),
            (('㉯', 2), ('㉯', '')),
            (('1. 보기', 1), ('1', '보기')),
            (('가. Marsh', 2), ('B', '가. Marsh')),     # 자리에 맞지 않는 기호는 그대로 둔다
            (('1 L', 1), ('A', '1 L')),                 # 숫자·영문자는 '.' ')' 가 있을 때만 기호
            (('A – UA', 1), ('A', 'A – UA')),
            (('Etomidate', 3), ('C', 'Etomidate')),
        ]
        for args, expected in cases:
            self.assertEqual(split_option_label(*args), expected, args)


class ExamViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user('u', 'u@x.com', 'pw', is_approved=True)
        self.special_user = User.objects.create_user('s', 's@x.com', 'pw', is_specially_approved=True, is_approved=True)
        self.cat = Category.objects.create(name='약리')
        self.exam = Exam.objects.create(title='일반시험')
        self.special = Exam.objects.create(title='특별시험', is_special=True)
        self.q1 = make_question(self.exam, 1, '다', self.cat)
        self.q2 = make_question(self.exam, 2, '㉯', self.cat)
        self.q3 = make_question(self.exam, 3, 'default', self.cat)
        self.q4 = make_question(self.exam, 4, '가')
        self.secret = make_question(self.special, 1, '가', self.cat, text='특별 문제 지문')
        self.client.force_login(self.user)

    def save(self, payload):
        return self.client.post(reverse('save_exam_results'), json.dumps(payload), content_type='application/json')

    # --- 서버 채점 ---
    def test_server_grades_by_question_id(self):
        res = self.save({'exam_id': self.exam.id,
                         'question_ids': [self.q1.id, self.q2.id, self.q3.id, self.q4.id],
                         'answers': {str(self.q1.id): 3, str(self.q2.id): 1, str(self.q3.id): 2}})
        self.assertEqual(res.status_code, 200, res.content)
        result = ExamResult.objects.get(id=res.json()['result_id'])
        self.assertEqual((result.num_correct, result.num_incorrect, result.num_noanswer, result.num_unanswered),
                         (1, 1, 1, 1))
        details = result.detailed_results
        self.assertEqual([d['question_id'] for d in details], [self.q1.id, self.q2.id, self.q3.id, self.q4.id])
        self.assertEqual([d['result'] for d in details], ['correct', 'incorrect', 'noanswer', 'unanswered'])
        self.assertEqual(details[0]['selected_answer'], '다. 보기3')
        self.assertEqual(details[0]['category'], '약리')

    def test_client_cannot_send_its_own_score(self):
        res = self.save({'exam_id': self.exam.id, 'question_ids': [self.q1.id],
                         'answers': {str(self.q1.id): 1}, 'num_correct': 99})
        result = ExamResult.objects.get(id=res.json()['result_id'])
        self.assertEqual((result.num_correct, result.num_incorrect), (0, 1))

    def test_exam_result_only_counts_that_exams_questions(self):
        res = self.save({'exam_id': self.exam.id, 'question_ids': [self.q1.id, self.secret.id], 'answers': {}})
        result = ExamResult.objects.get(id=res.json()['result_id'])
        self.assertEqual([d['question_id'] for d in result.detailed_results], [self.q1.id])

    def test_bad_payloads(self):
        self.assertEqual(self.client.get(reverse('save_exam_results')).status_code, 405)
        self.assertEqual(self.client.post(reverse('save_exam_results'), 'x', content_type='application/json').status_code, 400)
        self.assertEqual(self.save({'exam_id': self.exam.id, 'question_ids': []}).status_code, 400)
        self.assertEqual(self.save({'exam_id': 'abc', 'question_ids': [self.q1.id]}).status_code, 400)

    def test_results_page(self):
        Bookmark.objects.create(user=self.user, question=self.q1)
        res = self.save({'exam_id': self.exam.id,
                         'question_ids': [self.q1.id, self.q2.id, self.q3.id, self.q4.id],
                         'answers': {str(self.q1.id): 3, str(self.q2.id): 1}})
        page = self.client.get(reverse('exam_results') + f'?result_id={res.json()["result_id"]}')
        self.assertEqual(page.status_code, 200)
        items = page.context['items']
        self.assertEqual([i['result'] for i in items], ['correct', 'incorrect', 'noanswer', 'unanswered'])
        self.assertTrue(items[0]['is_bookmarked'])
        # 펼친 내용: 내가 고른 선택지(1번)와 정답(2번)이 표시된다
        wrong = {o['num']: o for o in items[1]['options']}
        self.assertTrue(wrong[1]['is_selected'] and not wrong[1]['is_answer'])
        self.assertTrue(wrong[2]['is_answer'])
        self.assertEqual((page.context['correct'], page.context['total'], page.context['pct']), (1, 4, 25.0))
        self.assertEqual(page.context['wrong_count'], 2)
        # 카테고리 정답률은 '정답 미정' 문제를 빼고 계산 (약리: 맞음 1 / 채점 2, 미분류: 0 / 1)
        cats = {c['name']: (c['correct'], c['graded']) for c in page.context['categories']}
        self.assertEqual(cats, {'약리': (1, 2), '미분류': (0, 1)})
        self.assertContains(page, reverse('retry_result', args=[res.json()['result_id']]))

    def test_results_page_handles_old_records(self):
        # 예전 기록: 선택지 번호 없이 선택지 글자만, 문제 ID 가 없는 문항도 있다
        result = ExamResult.objects.create(
            user=self.user, exam=self.exam, num_correct=0, num_incorrect=2, num_unanswered=0,
            detailed_results=[{'question_id': self.q2.id, 'question': 'x', 'selected_answer': '가. 보기1', 'correct_answer': '㉯', 'result': 'incorrect', 'category': 'N/A'},
                              {'question': '사라진 문제', 'selected_answer': 'a', 'correct_answer': 'b', 'result': 'incorrect'}])
        page = self.client.get(reverse('exam_results') + f'?result_id={result.id}')
        self.assertEqual(page.status_code, 200)
        items = page.context['items']
        self.assertTrue({o['num']: o for o in items[0]['options']}[1]['is_selected'])
        self.assertEqual(items[0]['category'], '약리')
        self.assertIsNone(items[1]['question'])
        self.assertContains(page, '자세한 내용을 표시할 수 없습니다')

    def test_other_users_result_is_404(self):
        other = get_user_model().objects.create_user('o', 'o@x.com', 'pw', is_approved=True)
        result = ExamResult.objects.create(user=other, exam=self.exam, num_correct=0, num_incorrect=0, num_unanswered=0, detailed_results=[])
        self.assertEqual(self.client.get(reverse('exam_results') + f'?result_id={result.id}').status_code, 404)
        self.assertEqual(self.client.get(reverse('retry_result', args=[result.id])).status_code, 404)

    def test_retry_wrong_questions(self):
        res = self.save({'exam_id': self.exam.id,
                         'question_ids': [self.q1.id, self.q2.id, self.q3.id, self.q4.id],
                         'answers': {str(self.q1.id): 3, str(self.q2.id): 1}})
        rid = res.json()['result_id']
        page = self.client.get(reverse('retry_result', args=[rid]))
        self.assertEqual([q.id for q in page.context['questions']], [self.q2.id, self.q4.id])   # 틀림 + 안 풂
        self.assertContains(page, f'data-quiz-key="retry_{rid}"')
        self.assertContains(page, '틀린 문제 다시 풀기 · 일반시험')
        page = self.client.get(reverse('retry_result', args=[rid]) + '?only=all')
        self.assertEqual(len(page.context['questions']), 4)
        # 다 맞힌 기록이면 채점 화면으로 돌려보낸다
        perfect = self.save({'exam_id': self.exam.id, 'question_ids': [self.q1.id], 'answers': {str(self.q1.id): 3}}).json()['result_id']
        self.assertRedirects(self.client.get(reverse('retry_result', args=[perfect])), reverse('exam_results') + f'?result_id={perfect}')

    def test_old_attempt_analytics_url_redirects(self):
        res = self.save({'exam_id': self.exam.id, 'question_ids': [self.q1.id], 'answers': {}})
        rid = res.json()['result_id']
        self.assertRedirects(self.client.get(f'/exam/analytics/result/{rid}/'), reverse('exam_results') + f'?result_id={rid}')

    def test_my_results_shows_score_percent(self):
        self.save({'exam_id': self.exam.id, 'question_ids': [self.q1.id, self.q2.id], 'answers': {str(self.q1.id): 3}})
        page = self.client.get(reverse('my_results'))
        row = page.context['results'][0]
        self.assertEqual((row['correct'], row['total'], row['score_percent'], row['wrong']), (1, 2, 50.0, 1))
        self.assertContains(page, 'width: 50.0%')

    def test_quiz_page_sends_option_numbers_and_hides_blank_options(self):
        q = make_question(self.exam, 5, '가', option5='default')
        html = self.client.get(reverse('question_list', args=[self.exam.id])).content.decode()
        self.assertIn(f'name="question_{q.id}" value="1"', html)
        self.assertNotIn(f'id="option5_{q.id}"', html)
        self.assertNotIn('data-correct-option', html)

    def test_quiz_page_layout(self):
        html = self.client.get(reverse('question_list', args=[self.exam.id])).content.decode()
        # 선택지 기호는 한 번만: '가. 보기1' → 기호 '가' + 내용 '보기1'
        self.assertIn('<span class="qz-option-label">가</span>', html)
        self.assertIn('<span class="qz-option-text">보기1</span>', html)
        # 연습 모드 즉시 채점용 정답 번호, 정답이 없는 문제는 비워 둔다
        self.assertIn(f'id="q_{self.q1.id}" class="qz-card"', html)
        self.assertRegex(html, rf'data-question-id="{self.q1.id}"[^>]*data-answer="3"')
        self.assertRegex(html, rf'data-question-id="{self.q3.id}"[^>]*data-answer=""')
        # 제출 버튼·번호판은 항상 있다 (타이머를 켜지 않아도 제출 가능)
        self.assertIn('id="qzSubmit"', html)
        self.assertEqual(html.count('<button type="button" data-target="'), 4)
        self.assertIn('data-default-mode="exam"', html)

    def test_bookmark_and_category_pages_use_practice_mode(self):
        Bookmark.objects.create(user=self.user, question=self.q1)
        html = self.client.get(reverse('bookmarked_questions')).content.decode()
        self.assertIn('data-default-mode="practice"', html)
        self.assertIn('class="qz-filter"', html)
        self.assertEqual(html.count('class="qz-card"'), 1)
        html = self.client.get(reverse('category_questions', args=[self.cat.name])).content.decode()
        self.assertIn('data-default-mode="practice"', html)
        self.assertIn('qz-chip-exam', html)   # 여러 회차가 섞이므로 회차 이름을 보여준다

    def test_empty_bookmarks_page(self):
        html = self.client.get(reverse('bookmarked_questions')).content.decode()
        self.assertIn('아직 북마크한 문제가 없습니다', html)
        self.assertNotIn('id="qzSubmit"', html)

    # --- 특별 시험 권한 ---
    def test_special_questions_hidden_from_normal_users(self):
        html = self.client.get(reverse('category_questions', args=[self.cat.name])).content.decode()
        self.assertIn(self.q1.question_text, html)
        self.assertNotIn('특별 문제 지문', html)

        Bookmark.objects.create(user=self.user, question=self.secret)
        html = self.client.get(reverse('bookmarked_questions')).content.decode()
        self.assertNotIn('특별 문제 지문', html)

        # 예전에 특별 시험을 풀었던 기록이 있어도, 다시 풀기에서는 특별 시험 문제가 빠진다
        old = ExamResult.objects.create(user=self.user, exam=None, category_name='x', num_correct=0, num_incorrect=2, num_unanswered=0,
                                        detailed_results=[{'question_id': self.secret.id, 'result': 'incorrect'},
                                                          {'question_id': self.q1.id, 'result': 'incorrect'}])
        page = self.client.get(reverse('retry_result', args=[old.id]))
        self.assertEqual([q.id for q in page.context['questions']], [self.q1.id])
        self.assertEqual(self.client.post(reverse('toggle_bookmark', args=[self.q1.id])).json()['is_bookmarked'], True)
        self.assertNotEqual(self.client.post(reverse('toggle_bookmark', args=[self.secret.id])).status_code, 200)
        self.assertEqual(self.save({'exam_id': self.special.id, 'question_ids': [self.secret.id]}).status_code, 404)
        self.assertEqual(self.save({'category_name': '약리', 'question_ids': [self.secret.id]}).status_code, 400)

    def test_special_user_sees_special_questions(self):
        self.client.force_login(self.special_user)
        html = self.client.get(reverse('category_questions', args=[self.cat.name])).content.decode()
        self.assertIn('특별 문제 지문', html)
        self.assertContains(self.client.get(reverse('bookmarked_questions')), 'qz-page')

    def test_unknown_category_is_404(self):
        self.assertEqual(self.client.get(reverse('category_questions', args=['없는카테고리'])).status_code, 404)



class ExamVisibilityTests(TestCase):
    """승인 회원은 일반 시험만, 특별 승인 회원은 특별 시험까지 모두."""

    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user('m', 'm@x.com', 'pw', is_approved=True)
        self.special_member = User.objects.create_user('s', 's@x.com', 'pw', is_approved=True, is_specially_approved=True)
        self.shared_cat = Category.objects.create(name='공통')
        self.special_cat = Category.objects.create(name='특별전용')
        self.ite = Exam.objects.create(title='2023 ITE')
        self.board = Exam.objects.create(title='2024 전문의 시험', is_special=True)
        self.q_ite = make_question(self.ite, 1, '가', self.shared_cat)
        self.q_board = make_question(self.board, 1, '가', self.shared_cat, text='전문의 공통 문제')
        self.q_board_only = make_question(self.board, 2, '가', self.special_cat, text='전문의 전용 문제')

    def test_member_sees_only_regular_exams(self):
        self.client.force_login(self.member)
        titles = [e.title for e in self.client.get(reverse('exam_list')).context['exams']]
        self.assertEqual(titles, ['2023 ITE'])
        self.assertRedirects(self.client.get(reverse('exam_detail', args=[self.board.id])), reverse('exam_list'))
        self.assertRedirects(self.client.get(reverse('question_list', args=[self.board.id])), reverse('exam_list'))
        # 카테고리: 특별 시험에만 있는 카테고리는 목록에서 빠지고, 공통 카테고리에서는 일반 문제만
        names = [c.name for c in self.client.get(reverse('category_list')).context['categories']]
        self.assertEqual(names, ['공통'])
        html = self.client.get(reverse('category_questions', args=['공통'])).content.decode()
        self.assertNotIn('전문의 공통 문제', html)
        # 북마크 필터 칩에 특별 시험 제목이 새지 않는다
        page = self.client.get(reverse('bookmarked_questions') + f'?exam={self.board.id}')
        self.assertEqual(list(page.context['selected_exam_objects']), [])

    def test_special_member_sees_everything(self):
        self.client.force_login(self.special_member)
        titles = [e.title for e in self.client.get(reverse('exam_list')).context['exams']]
        self.assertEqual(titles, ['2023 ITE', '2024 전문의 시험'])
        self.assertEqual(self.client.get(reverse('question_list', args=[self.board.id])).status_code, 200)
        names = [c.name for c in self.client.get(reverse('category_list')).context['categories']]
        self.assertEqual(names, ['공통', '특별전용'])
        html = self.client.get(reverse('category_questions', args=['공통'])).content.decode()
        self.assertIn('전문의 공통 문제', html)


class StatsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user('u', 'u@x.com', 'pw', is_approved=True)
        self.cat = Category.objects.create(name='약리')
        self.cat2 = Category.objects.create(name='생리')
        self.exam = Exam.objects.create(title='A회차')
        self.exam_b = Exam.objects.create(title='B회차')
        self.special = Exam.objects.create(title='특별', is_special=True)
        self.q = [make_question(self.exam, i, '가', self.cat if i % 2 else self.cat2) for i in range(1, 5)]
        self.qb = make_question(self.exam_b, 1, '가', self.cat)
        self.secret = make_question(self.special, 1, '가', self.cat)
        self.client.force_login(self.user)

    def take(self, exam, questions, right):
        """right: 맞힌 문제 목록. 나머지는 틀린 답(2번)을 고른다."""
        payload = {'question_ids': [q.id for q in questions],
                   'answers': {str(q.id): (1 if q in right else 2) for q in questions}}
        if exam:
            payload['exam_id'] = exam.id
        else:
            payload['category_name'] = '연습'
        return self.client.post(reverse('save_exam_results'), json.dumps(payload), content_type='application/json').json()['result_id']

    def test_empty(self):
        page = self.client.get(reverse('analytics_overview'))
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context['has_data'])
        self.assertContains(page, '시험 보러 가기')

    def test_overall_stats(self):
        self.take(self.exam, self.q, right=self.q[:2])      # 50%
        self.take(self.exam, self.q, right=self.q[:3])      # 75%
        self.take(self.exam_b, [self.qb], right=[])          # 0%
        page = self.client.get(reverse('analytics_overview'))
        c = page.context
        self.assertEqual((c['attempts'], c['latest_pct'], c['best_pct'], c['avg_pct']), (3, 0.0, 75.0, 41.7))
        self.assertEqual(c['answered'], 9)
        rows = {r['exam'].title: (r['attempts'], r['latest_pct'], r['best_pct']) for r in c['exam_rows']}
        self.assertEqual(rows, {'A회차': (2, 75.0, 75.0), 'B회차': (1, 0.0, 0.0)})
        cats = {x['name']: (x['correct'], x['graded']) for x in c['categories']}
        self.assertEqual(cats, {'약리': (3, 5), '생리': (2, 4)})
        self.assertEqual([x['name'] for x in c['categories']], ['생리', '약리'])   # 낮은 순
        self.assertContains(page, reverse('category_questions', args=['약리']))
        self.assertNotIn('trend', c)

    def test_exam_scope(self):
        self.take(self.exam, self.q, right=self.q[:2])
        self.take(self.exam, self.q, right=self.q)
        self.take(self.exam_b, [self.qb], right=[])
        page = self.client.get(reverse('analytics_overview') + f'?exam={self.exam.id}')
        c = page.context
        self.assertEqual(c['exam'], self.exam)
        self.assertEqual(c['attempts'], 2)
        self.assertEqual([t['pct'] for t in c['trend']], [50.0, 100.0])
        self.assertEqual(json.loads(c['trend_json'])[1]['y'], 100.0)
        self.assertContains(page, 'id="stTrend"')
        self.assertEqual(c['wrong_total'], 0)                # 두 번째에 다 맞혔으므로 오답 없음
        # 푼 적 없는 회차·특별 시험은 범위로 고를 수 없다
        self.assertRedirects(self.client.get(reverse('analytics_overview') + f'?exam={self.special.id}'), reverse('analytics_overview'))

    def test_wrong_notebook_tracks_last_result(self):
        self.take(self.exam, self.q, right=[])               # 4문제 모두 틀림
        self.take(None, self.q[:2], right=[self.q[0]])       # 다시 풀어 1번만 맞힘
        c = self.client.get(reverse('analytics_overview')).context
        self.assertEqual(c['wrong_total'], 3)
        self.assertEqual(c['wrong_top'][0].id, self.q[1].id)  # 두 번 틀린 문제가 먼저
        self.assertEqual(c['wrong_top'][0].history['wrong'], 2)
        page = self.client.get(reverse('review_wrong'))
        self.assertEqual([q.id for q in page.context['questions']], [self.q[1].id, self.q[2].id, self.q[3].id])
        self.assertContains(page, 'data-quiz-key="review_all"')
        self.assertContains(page, '오답노트 · 전체')
        page = self.client.get(reverse('review_wrong') + f'?exam={self.exam_b.id}')
        self.assertRedirects(page, reverse('analytics_overview') + f'?exam={self.exam_b.id}', fetch_redirect_response=False)

    def test_wrong_notebook_hides_special_and_other_users(self):
        other = get_user_model().objects.create_user('o', 'o@x.com', 'pw', is_approved=True)
        ExamResult.objects.create(user=other, exam=self.exam, num_correct=0, num_incorrect=1, num_unanswered=0,
                                  detailed_results=[{'question_id': self.q[0].id, 'result': 'incorrect'}])
        ExamResult.objects.create(user=self.user, exam=None, category_name='x', num_correct=0, num_incorrect=1, num_unanswered=0,
                                  detailed_results=[{'question_id': self.secret.id, 'result': 'incorrect', 'category': '약리'}])
        self.assertEqual(self.client.get(reverse('analytics_overview')).context['wrong_total'], 0)

    def test_old_urls_redirect(self):
        self.assertRedirects(self.client.get(f'/exam/analytics/exam/{self.exam.id}/'),
                             reverse('analytics_overview') + f'?exam={self.exam.id}', fetch_redirect_response=False)
        self.assertRedirects(self.client.get('/exam/analytics/exams/'), reverse('analytics_overview'))

    def test_category_link_only_for_linkable_names(self):
        Category.objects.create(name='A&B/C')
        ExamResult.objects.create(user=self.user, exam=None, category_name='x', num_correct=1, num_incorrect=0, num_unanswered=0,
                                  detailed_results=[{'question_id': self.q[0].id, 'result': 'correct', 'category': 'A&B/C'}])
        page = self.client.get(reverse('analytics_overview'))
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context['categories'][0]['can_practice'])


class BackfillMigrationTests(TestCase):
    def test_old_results_get_question_ids(self):
        user = get_user_model().objects.create_user('u', 'u@x.com', 'pw', is_approved=True)
        cat = Category.objects.create(name='생리')
        exam_a = Exam.objects.create(title='A')
        exam_b = Exam.objects.create(title='B')
        same_b = make_question(exam_b, 1, '가', text='같은 지문의 문제입니다 (두 시험에 중복)')
        same_a = make_question(exam_a, 1, '가', cat, text='같은 지문의 문제입니다 (두 시험에 중복)')
        html_q = make_question(exam_a, 2, '나', text='<b>굵은</b> 지문이 있는 문제입니다 아주 길게 씁니다')
        result = ExamResult.objects.create(
            user=user, exam=exam_a, num_correct=0, num_incorrect=0, num_unanswered=0,
            detailed_results=[
                {'question': '같은 지문의 문제입니다 (두 시험에 중복)', 'result': 'correct', 'category': 'N/A'},
                {'question': '굵은 지문이 있는 문제입니다 아주 길게 씁니다', 'result': 'incorrect'},
                {'question': '없는 문제', 'result': 'incorrect'},
                {'question_id': 12345, 'question': 'x', 'result': 'correct'},
            ])
        migration = importlib.import_module('exam.migrations.0013_backfill_result_question_ids')
        migration.backfill(global_apps, None)
        details = ExamResult.objects.get(id=result.id).detailed_results
        self.assertEqual(details[0]['question_id'], same_a.id)  # 같은 시험의 문제가 우선
        self.assertEqual(details[0]['category'], '생리')
        self.assertEqual(details[1]['question_id'], html_q.id)
        self.assertNotIn('question_id', details[2])
        self.assertEqual(details[3]['question_id'], 12345)
        self.assertNotEqual(same_a.id, same_b.id)

    def test_second_pass_ignores_spacing_changes(self):
        user = get_user_model().objects.create_user('v', 'v@x.com', 'pw', is_approved=True)
        exam = Exam.objects.create(title='C')
        q = make_question(exam, 1, '가', text='문 1. 일측폐환기를 이용한 폐절제술에서\r\n적절한 수액관리 전략으로 옳은 것은?')
        result = ExamResult.objects.create(
            user=user, exam=exam, num_correct=0, num_incorrect=0, num_unanswered=0,
            detailed_results=[{'question': '문1. 일측폐환기를 이용한 폐절제술에서 적절한 수액관리 전략으로 옳은 것은?', 'result': 'correct'},
                              {'question': '짧음', 'result': 'correct'}])
        migration = importlib.import_module('exam.migrations.0014_backfill_result_question_ids_ignore_spaces')
        migration.backfill(global_apps, None)
        details = ExamResult.objects.get(id=result.id).detailed_results
        self.assertEqual(details[0]['question_id'], q.id)
        self.assertNotIn('question_id', details[1])   # 너무 짧은 지문은 엉뚱한 문제와 맞추지 않는다
