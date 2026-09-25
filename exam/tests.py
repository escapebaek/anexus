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
        self.user = User.objects.create_user('u', 'u@x.com', 'pw')
        self.special_user = User.objects.create_user('s', 's@x.com', 'pw', is_specially_approved=True)
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

    def test_results_page_shows_bookmark_state(self):
        Bookmark.objects.create(user=self.user, question=self.q1)
        res = self.save({'exam_id': self.exam.id, 'question_ids': [self.q1.id], 'answers': {}})
        page = self.client.get(reverse('exam_results') + f'?result_id={res.json()["result_id"]}')
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.context['result'].detailed_results[0]['is_bookmarked'])

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

        self.assertEqual(self.client.get(reverse('question_detail_partial', args=[self.secret.id])).status_code, 404)
        self.assertEqual(self.client.post(reverse('toggle_bookmark', args=[self.q1.id])).json()['is_bookmarked'], True)
        self.assertNotEqual(self.client.post(reverse('toggle_bookmark', args=[self.secret.id])).status_code, 200)
        self.assertEqual(self.save({'exam_id': self.special.id, 'question_ids': [self.secret.id]}).status_code, 404)
        self.assertEqual(self.save({'category_name': '약리', 'question_ids': [self.secret.id]}).status_code, 400)

    def test_special_user_sees_special_questions(self):
        self.client.force_login(self.special_user)
        html = self.client.get(reverse('category_questions', args=[self.cat.name])).content.decode()
        self.assertIn('특별 문제 지문', html)
        self.assertEqual(self.client.get(reverse('question_detail_partial', args=[self.secret.id])).status_code, 200)

    def test_unknown_category_is_404(self):
        self.assertEqual(self.client.get(reverse('category_questions', args=['없는카테고리'])).status_code, 404)


class BackfillMigrationTests(TestCase):
    def test_old_results_get_question_ids(self):
        user = get_user_model().objects.create_user('u', 'u@x.com', 'pw')
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
        user = get_user_model().objects.create_user('v', 'v@x.com', 'pw')
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
