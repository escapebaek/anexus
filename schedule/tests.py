from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

import json

from .models import SurgerySchedule, PatientMemo
from .views import build_board, status_group, update_schedules_from_records

from unittest import mock as _mock

# 표 업로드 중 '예상 시간 열 찾기' AI 호출은 기본으로 끔 (서버 환경에 실제 키가 있어도 테스트가 밖으로 나가지 않게)
_no_ai_columns = _mock.patch('schedule.views.find_duration_column', return_value=None)


def setUpModule():
    _no_ai_columns.start()


def tearDownModule():
    _no_ai_columns.stop()


def make(user, room, time_slot, status='예정', name='환자', surgery='Op', info='12345678 (M/40)', **extra):
    extra.setdefault('duration', 60)
    return SurgerySchedule.objects.create(
        user=user, date=date(2026, 8, 27), room=room, time_slot=time_slot, surgery_name=surgery,
        department='GS', surgeon='김의사', patient_name=name, patient_info=info,
        status=status, **extra,
    )


def rec(room, time_slot, name, surgery, info='', **extra):
    data = dict(date='2026-08-27', room=room, time_slot=time_slot, surgery_name=surgery, department='GS',
                surgeon='김의사', duration=60, patient_name=name, patient_info=info, status='예정')
    data.update(extra)
    return data


class BoardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('doc', password='x')

    def board(self):
        return build_board(SurgerySchedule.objects.filter(user=self.user).order_by('date', 'room', 'time_slot', 'id'))

    def test_status_groups(self):
        self.assertEqual(status_group('수술중'), 'ongoing')
        self.assertEqual(status_group(' 진행중 '), 'ongoing')
        self.assertEqual(status_group('완료'), 'finished')
        self.assertEqual(status_group('예정'), 'pending')
        self.assertEqual(status_group(''), 'pending')

    def test_rooms_sorted_naturally(self):
        for room in ['P10', '110', 'P2', '102', '', '1', '301']:
            make(self.user, room, '08:00', name=room or 'none')
        self.assertEqual([r['room'] for r in self.board()['rooms']], ['1', '102', '110', '301', 'P2', 'P10', ''])

    def test_current_case_prefers_ongoing_then_pending(self):
        make(self.user, '101', '08:00', status='완료')
        make(self.user, '101', '10:00', status='예정')
        make(self.user, '101', '12:00', status='수술중')
        make(self.user, '102', '08:00', status='완료')
        make(self.user, '102', '10:00', status='예정')
        make(self.user, '103', '08:00', status='완료')
        make(self.user, '103', '10:00', status='완료')
        rooms = {r['room']: r for r in self.board()['rooms']}
        self.assertEqual((rooms['101']['state'], rooms['101']['cases'][rooms['101']['current']]['time_slot']), ('ongoing', '12:00'))
        self.assertEqual((rooms['102']['state'], rooms['102']['cases'][rooms['102']['current']]['time_slot']), ('pending', '10:00'))
        self.assertEqual((rooms['103']['state'], rooms['103']['current']), ('finished', 1))

    def test_counts(self):
        make(self.user, '101', '08:00', status='수술중')
        make(self.user, '101', '10:00', status='예정')
        make(self.user, '102', '08:00', status='완료')
        board = self.board()
        self.assertEqual(board['counts'], {'ongoing': 1, 'pending': 1, 'finished': 1, 'on_call': 0, 'hold': 0})
        self.assertEqual((board['total'], board['remaining']), (3, 2))


class DashboardViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user('doc', password='x')
        self.user.is_specially_approved = True
        self.user.save()
        other = User.objects.create_user('other', password='x')
        make(other, '999', '08:00', name='타인환자')
        self.client.force_login(self.user)

    def test_renders_own_board_safely(self):
        make(self.user, '101', '08:00', name='</script><script>alert(1)</script>')
        res = self.client.get(reverse('schedule_dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual([r['room'] for r in res.context['board']['rooms']], ['101'])
        self.assertNotContains(res, '</script><script>alert(1)')
        self.assertNotContains(res, '타인환자')

    def test_empty_board(self):
        res = self.client.get(reverse('schedule_dashboard'))
        self.assertContains(res, '등록된 수술 일정이 없습니다')


class UpdateKeepsMemoTests(TestCase):
    """스케줄 '업데이트' 시 메모가 같은 환자/수술에 그대로 남는지."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('doc', password='x')

    def memo(self, schedule, text):
        PatientMemo.objects.create(schedule=schedule, content=text)

    def update(self, records):
        update_schedules_from_records(records, self.user, list(SurgerySchedule.objects.filter(user=self.user)))

    def memos(self):
        return {
            (s.room, s.time_slot, s.surgery_name): (s.memos.first().content if s.memos.exists() else None)
            for s in SurgerySchedule.objects.filter(user=self.user)
        }

    def test_memo_follows_patient_when_room_and_order_change(self):
        a = make(self.user, '101', '08:00', name='홍길동', surgery='TKRA', info='11111111 (M/70)')
        b = make(self.user, '102', '08:00', name='김영희', surgery='Lap chole', info='')
        self.memo(a, 'memo A')
        self.memo(b, 'memo B')
        self.update([
            rec('301', '13:00', '김영희', 'Laparoscopic cholecystectomy'),
            rec('205', '09:00', '홍길동', 'TKRA', '11111111 (M/70)'),
        ])
        self.assertEqual(self.memos(), {
            ('301', '13:00', 'Laparoscopic cholecystectomy'): 'memo B',
            ('205', '09:00', 'TKRA'): 'memo A',
        })
        self.assertEqual(SurgerySchedule.objects.filter(user=self.user).count(), 2)

    def test_same_patient_two_cases_do_not_swap_memos(self):
        lt = make(self.user, '101', '08:00', name='홍길동', surgery='TKRA (Lt)', info='11111111 (M/70)')
        rt = make(self.user, '101', '11:00', name='홍길동', surgery='TKRA (Rt)', info='11111111 (M/70)')
        self.memo(lt, 'memo Lt')
        self.memo(rt, 'memo Rt')
        # 새 파일에서는 Rt 가 먼저 오고, 방과 표기가 바뀜
        self.update([
            rec('105', '08:00', '홍길동', 'TKRA Rt', '11111111 (M/70)'),
            rec('105', '12:00', '홍길동', 'TKRA Lt', '11111111 (M/70)'),
        ])
        self.assertEqual(self.memos(), {
            ('105', '08:00', 'TKRA Rt'): 'memo Rt',
            ('105', '12:00', 'TKRA Lt'): 'memo Lt',
        })

    def test_same_name_different_registration_is_a_different_patient(self):
        old = make(self.user, '101', '08:00', name='김민준', surgery='Op', info='11111111 (M/70)')
        self.memo(old, 'memo old')
        self.update([rec('101', '08:00', '김민준', 'Op', '22222222 (M/5)')])
        self.assertEqual(self.memos(), {('101', '08:00', 'Op'): None})

    def test_manual_anesthesiologist_kept_when_file_has_none(self):
        make(self.user, '101', '08:00', name='홍길동', surgery='Op', info='', anesthesiologist='이마취')
        self.update([rec('102', '09:00', '홍길동', 'Op')])
        self.assertEqual(SurgerySchedule.objects.get(user=self.user).anesthesiologist, '이마취')
        self.update([rec('102', '09:00', '홍길동', 'Op', anesthesiologist='박마취')])
        self.assertEqual(SurgerySchedule.objects.get(user=self.user).anesthesiologist, '박마취')

    def test_cancelled_case_removed(self):
        make(self.user, '101', '08:00', name='홍길동', surgery='Op', info='')
        make(self.user, '102', '08:00', name='김영희', surgery='Op', info='')
        self.update([rec('101', '08:00', '홍길동', 'Op')])
        self.assertEqual(list(SurgerySchedule.objects.filter(user=self.user).values_list('patient_name', flat=True)), ['홍길동'])


class ApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user('doc', password='x')
        self.user.is_specially_approved = True
        self.user.save()
        self.other = User.objects.create_user('other', password='x')
        self.other.is_specially_approved = True
        self.other.save()
        self.mine = make(self.user, '101', '08:00')
        self.theirs = make(self.other, '101', '08:00')
        self.client.force_login(self.user)

    def post(self, url, payload):
        return self.client.post(url, json.dumps(payload), content_type='application/json')

    def test_memo_roundtrip(self):
        url = reverse('handle_memo', args=[self.mine.id])
        self.assertEqual(self.post(url, {'content': '알레르기: PCN'}).json()['status'], 'success')
        self.assertEqual(self.post(url, {'content': '알레르기: PCN, 난삽관'}).json()['status'], 'success')
        self.assertEqual(self.client.get(url).json()['content'], '알레르기: PCN, 난삽관')
        self.assertEqual(PatientMemo.objects.filter(schedule=self.mine).count(), 1)
        board = self.client.get(reverse('schedule_dashboard')).context['board']
        self.assertEqual(board['rooms'][0]['cases'][0]['memo'], '알레르기: PCN, 난삽관')

    def test_cannot_read_or_write_other_users_memo(self):
        PatientMemo.objects.create(schedule=self.theirs, content='secret')
        url = reverse('handle_memo', args=[self.theirs.id])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.post(url, {'content': 'x'}).status_code, 404)
        self.assertEqual(PatientMemo.objects.get(schedule=self.theirs).content, 'secret')

    def test_set_anesthesiologist(self):
        res = self.post(reverse('schedule_update', args=[self.mine.id]), {'anesthesiologist': ' 이마취 '})
        self.assertEqual(res.json()['room']['cases'][0]['anesthesiologist'], '이마취')
        self.assertEqual(self.post(reverse('schedule_update', args=[self.theirs.id]), {'anesthesiologist': 'x'}).status_code, 404)

    def test_case_flags_are_per_case(self):
        nxt = make(self.user, '101', '11:00')
        url = reverse('schedule_update', args=[self.mine.id])
        room = self.post(url, {'on_call': True}).json()['room']
        room = self.post(reverse('schedule_update', args=[nxt.id]), {'hold': True}).json()['room']
        self.assertEqual([(c['on_call'], c['hold']) for c in room['cases']], [(True, False), (False, True)])
        board = self.client.get(reverse('schedule_dashboard')).context['board']
        self.assertEqual((board['counts']['on_call'], board['counts']['hold']), (1, 1))
        self.post(url, {'on_call': False})
        self.mine.refresh_from_db()
        self.assertFalse(self.mine.on_call)
        self.assertEqual(self.post(reverse('schedule_update', args=[self.theirs.id]), {'hold': True}).status_code, 404)

    def test_invalid_status_rejected_without_partial_save(self):
        res = self.post(reverse('schedule_update', args=[self.mine.id]), {'hold': True, 'status': 'bogus'})
        self.assertEqual(res.status_code, 400)
        self.mine.refresh_from_db()
        self.assertFalse(self.mine.hold)


class ManualStatusTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('doc', password='x')
        self.user.is_specially_approved = True
        self.user.save()
        self.client.force_login(self.user)
        self.a = make(self.user, '101', '08:00', status='진행중', name='A')
        self.b = make(self.user, '101', '10:00', status='예정', name='B')
        self.c = make(self.user, '101', '12:00', status='예정', name='C')
        self.other_room = make(self.user, '102', '08:00', status='진행중', name='X')

    def set_status(self, case, status):
        res = self.client.post(reverse('schedule_update', args=[case.id]), json.dumps({'status': status}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 200)
        return res.json()['room']

    def statuses(self):
        return [SurgerySchedule.objects.get(id=c.id).status for c in (self.a, self.b, self.c, self.other_room)]

    def test_complete_starts_next_case(self):
        room = self.set_status(self.a, 'finished')
        self.assertEqual(self.statuses(), ['완료', '진행중', '예정', '진행중'])
        self.assertEqual(room['cases'][room['current']]['patient_name'], 'B')

    def test_complete_does_not_auto_start_held_case(self):
        SurgerySchedule.objects.filter(id=self.b.id).update(hold=True)
        self.set_status(self.a, 'finished')
        self.assertEqual(self.statuses(), ['완료', '예정', '예정', '진행중'])

    def test_reopen_finished_case_sets_current_back_to_pending(self):
        self.set_status(self.a, 'finished')           # A 완료, B 진행중
        self.set_status(self.a, 'ongoing')            # A 다시 진행중 -> B 예정
        self.assertEqual(self.statuses(), ['진행중', '예정', '예정', '진행중'])

    def test_manual_status_survives_schedule_update(self):
        self.set_status(self.a, 'finished')
        records = [rec(r, t, n, 'Op', '12345678 (M/40)', status='예정')
                   for r, t, n in [('101', '08:00', 'A'), ('101', '10:00', 'B'), ('101', '12:00', 'C'), ('102', '08:00', 'X')]]
        update_schedules_from_records(records, self.user, list(SurgerySchedule.objects.filter(user=self.user)))
        self.assertEqual(self.statuses(), ['완료', '진행중', '예정', '예정'])


class UploadActionTests(TestCase):
    """업로드 폼: 'update' 는 메모를 유지하고, action 값이 빠져도 전체 교체되지 않아야 함."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('doc', password='x')
        self.user.is_specially_approved = True
        self.user.save()
        self.client.force_login(self.user)
        self.case = make(self.user, '101', '08:00', name='홍길동', surgery='TKRA', info='11111111 (M/70)')
        PatientMemo.objects.create(schedule=self.case, content='memo')
        SurgerySchedule.objects.filter(id=self.case.id).update(hold=True, on_call=True)

    def upload(self, **post):
        from unittest import mock
        from django.core.files.uploadedfile import SimpleUploadedFile
        records = [rec('205', '10:00', '홍길동', 'TKRA', '11111111 (M/70)')]
        with mock.patch('schedule.views.extract_schedules', return_value=records), \
                mock.patch('schedule.views.start_background', side_effect=lambda f, *a: f(*a)):
            post['file'] = SimpleUploadedFile('s.txt', '자유 형식 메모'.encode())
            return self.client.post(reverse('schedule_dashboard'), post)

    def test_missing_action_defaults_to_update(self):
        self.assertEqual(self.upload().status_code, 302)
        schedule = SurgerySchedule.objects.get(user=self.user)
        self.assertEqual((schedule.id, schedule.room), (self.case.id, '205'))
        self.assertEqual(schedule.memos.get().content, 'memo')

    def test_update_keeps_memo_and_flags(self):
        self.upload(action='update')
        self.assertEqual(PatientMemo.objects.get().content, 'memo')
        self.assertTrue(SurgerySchedule.objects.filter(user=self.user, room='205', hold=True, on_call=True).exists())

    def test_replace_clears_everything(self):
        self.upload(action='replace')
        self.assertFalse(PatientMemo.objects.exists())
        self.assertFalse(SurgerySchedule.objects.filter(user=self.user, hold=True).exists())
        self.assertEqual(SurgerySchedule.objects.get(user=self.user).room, '205')


class GeminiFallbackTests(TestCase):
    """무료 등급: 과부하(503)·한도(429)·없는 모델(404)이면 다음 무료 모델로 넘어감."""

    def run_with(self, responses):
        from unittest import mock
        from django.test import override_settings
        from . import gemini_client

        calls = []

        class Resp:
            def __init__(self, code, text='{}'):
                self.status_code, self.text = code, text

            def json(self):
                return json.loads(self.text)

        ok_body = json.dumps({'candidates': [{'content': {'parts': [{'text': json.dumps({'schedules': [rec('101', '08:00', 'A', 'Op')]})}]}}]})

        def fake_post(url, **kwargs):
            model = url.split('/models/')[1].split(':')[0]
            calls.append(model)
            code = responses[model].pop(0) if isinstance(responses[model], list) else responses[model]
            return Resp(code, ok_body if code == 200 else 'error')

        with override_settings(GEMINI_API_KEY='k', GEMINI_MODEL='m1', GEMINI_FALLBACK_MODELS='m2, m3,m1'), \
                mock.patch.object(gemini_client.requests, 'post', side_effect=fake_post), \
                mock.patch.object(gemini_client.time, 'sleep'):
            try:
                result = gemini_client.extract_schedules_from_text('data', 'f.txt')
            except gemini_client.ScheduleExtractionError as exc:
                return calls, exc
        return calls, result

    def test_overloaded_model_falls_back(self):
        calls, result = self.run_with({'m1': 503, 'm2': 200, 'm3': 200})
        self.assertEqual(calls, ['m1', 'm1', 'm2'])
        self.assertEqual(result[0]['patient_name'], 'A')

    def test_quota_and_missing_model_skip_ahead(self):
        calls, result = self.run_with({'m1': 429, 'm2': 404, 'm3': 200})
        self.assertEqual(calls, ['m1', 'm2', 'm3'])
        self.assertIsInstance(result, list)

    def test_overload_recovers_on_retry(self):
        calls, result = self.run_with({'m1': [503, 200], 'm2': 200, 'm3': 200})
        self.assertEqual(calls, ['m1', 'm1'])

    def test_all_quota_exhausted_message(self):
        calls, exc = self.run_with({'m1': 429, 'm2': 429, 'm3': 429})
        self.assertIn('무료 사용량 한도', str(exc))

    def test_all_overloaded_message(self):
        calls, exc = self.run_with({'m1': 503, 'm2': 503, 'm3': 503})
        self.assertEqual(calls, ['m1', 'm1', 'm2', 'm2', 'm3', 'm3'])
        self.assertIn('혼잡', str(exc))

    def test_bad_key_stops_immediately(self):
        calls, exc = self.run_with({'m1': 403, 'm2': 200, 'm3': 200})
        self.assertEqual(calls, ['m1'])
        self.assertIn('API 키', str(exc))



class TableParserTests(TestCase):
    """열 이름이 있는 표 형식 파일은 AI 없이 읽음."""

    def test_template_workbook(self):
        import openpyxl
        from .table_parser import parse_workbook
        wb = openpyxl.load_workbook('schedule/surgery_schedule_template.xlsx', data_only=True)
        records = parse_workbook(wb, 'surgery_schedule_template.xlsx')
        self.assertEqual(len(records), 20)
        self.assertEqual(records[0], {
            'date': '2025-01-30', 'room': 'Rm1', 'time_slot': '8A', 'surgery_name': 'Appendectomy',
            'department': 'GS', 'surgeon': '김철수', 'anesthesiologist': '', 'anesthesia_type': '', 'duration': 60,
            'patient_name': '박나나', 'patient_info': 'F/61', 'status': '완료',
        })
        self.assertEqual(records[2]['status'], '예정')  # 대기 -> 예정

    def test_csv_with_regnum_cosurgeon_and_two_time_columns(self):
        from .table_parser import parse_delimited_text
        text = ('날짜,방,시간,과,병실,등록번호,이름,성/나이,수술명,집도의,마취의,시간,현황\n'
                '2025-06-01,E1,MD,GS,054/19,71203438,배동규,M/42,부신절제술,김남규,이마취,4:00,수술중\n'
                '2025-06-01,,,,,,,,부신절제술,박신균,,4:00,\n'
                ',,11:00,GS,,71203439,김철수,F/50,담낭절제술,김남규,,1시간 30분,\n')
        records = parse_delimited_text(text)
        self.assertEqual(len(records), 2)
        first, second = records
        self.assertEqual((first['surgeon'], first['anesthesiologist'], first['duration'], first['status']),
                         ('김남규, 박신균', '이마취', 240, '진행중'))
        self.assertEqual(first['patient_info'], '71203438 (M/42)')
        # 병합된 방/날짜 칸은 위 행 값을 이어받음
        self.assertEqual((second['room'], second['date'], second['duration']), ('E1', '2025-06-01', 90))

    def test_free_text_is_left_for_ai(self):
        from .table_parser import parse_delimited_text
        self.assertIsNone(parse_delimited_text('오늘 수술 메모\n7/25 1번방 아침 9시 - 홍길동 충수돌기절제술'))

    def test_table_upload_applies_without_ai(self):
        from unittest import mock
        from django.core.files.uploadedfile import SimpleUploadedFile
        user = get_user_model().objects.create_user('doc', password='x')
        user.is_specially_approved = True
        user.save()
        self.client.force_login(user)
        csv_bytes = '방,시간,수술명,집도의,환자명\n101,08:00,TKRA,김의사,홍길동\n'.encode('cp949')
        with mock.patch('schedule.views.extract_schedules') as ai:
            res = self.client.post(reverse('schedule_dashboard'), {'file': SimpleUploadedFile('s.csv', csv_bytes), 'action': 'update'})
        ai.assert_not_called()
        self.assertRedirects(res, reverse('schedule_dashboard'), fetch_redirect_response=False)
        self.assertEqual(SurgerySchedule.objects.get(user=user).patient_name, '홍길동')


class AiProviderTests(TestCase):
    """무료 AI 제공자: 키가 있는 것만 순서대로, 실패하면 다음 모델/제공자로."""

    def run_with(self, responses, providers='groq,openrouter,gemini', keys=None):
        from unittest import mock
        from django.test import override_settings
        from . import ai_client, gemini_client

        keys = keys if keys is not None else {'GROQ_API_KEY': 'g', 'OPENROUTER_API_KEY': 'o', 'GEMINI_API_KEY': ''}
        calls = []
        good = {'schedules': [rec('101', '08:00', 'A', 'Op')]}

        class Resp:
            def __init__(self, code, body):
                self.status_code, self.text, self._body = code, json.dumps(body), body

            def json(self):
                return self._body

        def fake_post(url, **kwargs):
            model = (kwargs.get('json') or {}).get('model', '')
            calls.append(model)
            code, content = responses.get(model, (404, None))
            body = {'choices': [{'message': {'content': content}}]} if code == 200 else {'error': 'x'}
            return Resp(code, body)

        with override_settings(SCHEDULE_AI_PROVIDERS=providers, GROQ_MODELS='g1,g2', OPENROUTER_MODELS='o1',
                               SCHEDULE_AI_TIME_BUDGET=100, **keys), \
                mock.patch.object(ai_client.requests, 'post', side_effect=fake_post), \
                mock.patch.object(gemini_client.requests, 'post', side_effect=fake_post):
            try:
                return calls, ai_client.extract_schedules('메모', 'm.txt')
            except gemini_client.ScheduleExtractionError as exc:
                return calls, exc

    def test_groq_model_fallback(self):
        calls, result = self.run_with({'g1': (429, None), 'g2': (200, json.dumps({'schedules': [rec('1', '1', 'A', 'Op')]}))})
        self.assertEqual(calls, ['g1', 'g2'])
        self.assertEqual(result[0]['patient_name'], 'A')

    def test_falls_through_to_next_provider_and_parses_fenced_json(self):
        fenced = '```json\n' + json.dumps({'schedules': [rec('1', '1', 'B', 'Op')]}) + '\n```'
        calls, result = self.run_with({'g1': (503, None), 'g2': (413, None), 'o1': (200, fenced)})
        self.assertEqual(calls, ['g1', 'g2', 'o1'])
        self.assertEqual(result[0]['patient_name'], 'B')

    def test_providers_without_keys_are_skipped(self):
        calls, result = self.run_with({'o1': (200, json.dumps({'schedules': [rec('1', '1', 'C', 'Op')]}))},
                                      keys={'GROQ_API_KEY': '', 'OPENROUTER_API_KEY': 'o', 'GEMINI_API_KEY': ''})
        self.assertEqual(calls, ['o1'])

    def test_no_keys_gives_clear_message(self):
        calls, exc = self.run_with({}, keys={'GROQ_API_KEY': '', 'OPENROUTER_API_KEY': '', 'GEMINI_API_KEY': ''})
        self.assertEqual(calls, [])
        self.assertIn('API 키가 설정되어 있지 않습니다', str(exc))

    def test_only_gemini_configured_hints_other_keys(self):
        calls, exc = self.run_with({}, providers='groq,gemini,openrouter',
                                   keys={'GROQ_API_KEY': '', 'OPENROUTER_API_KEY': '', 'GEMINI_API_KEY': 'k'})
        self.assertIn('Gemini 만 사용 중', str(exc))
        self.assertIn('GROQ_API_KEY', str(exc))
        self.assertIn('OPENROUTER_API_KEY', str(exc))

    def test_all_fail_reports_each_provider(self):
        calls, exc = self.run_with({'g1': (429, None), 'g2': (429, None), 'o1': (503, None)})
        self.assertIn('Groq', str(exc))
        self.assertIn('OpenRouter', str(exc))


class UploadJobTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('doc', password='x')
        self.user.is_specially_approved = True
        self.user.save()
        self.client.force_login(self.user)

    def upload(self, **ai):
        from unittest import mock
        from django.core.files.uploadedfile import SimpleUploadedFile
        with mock.patch('schedule.views.extract_schedules', **ai), \
                mock.patch('schedule.views.start_background', side_effect=lambda f, *a: f(*a)):
            return self.client.post(reverse('schedule_dashboard'),
                                     {'file': SimpleUploadedFile('memo.txt', '자유 형식'.encode()), 'action': 'update'})

    def test_ai_upload_runs_as_job(self):
        from .models import ScheduleUploadJob
        res = self.upload(return_value=[rec('101', '08:00', '홍길동', 'Op')])
        job = ScheduleUploadJob.objects.get(user=self.user)
        self.assertRedirects(res, f"{reverse('schedule_dashboard')}?job={job.id}", fetch_redirect_response=False)
        status = self.client.get(reverse('schedule_upload_job', args=[job.id])).json()['job']
        self.assertEqual(status['state'], 'done')
        self.assertEqual(SurgerySchedule.objects.get(user=self.user).patient_name, '홍길동')
        page = self.client.get(f"{reverse('schedule_dashboard')}?job={job.id}")
        self.assertContains(page, '1건을 AI로 읽어 반영했습니다')

    def test_ai_failure_reported_not_500(self):
        from .gemini_client import ScheduleExtractionError
        from .models import ScheduleUploadJob
        self.upload(side_effect=ScheduleExtractionError('모두 혼잡'))
        job = ScheduleUploadJob.objects.get(user=self.user)
        self.assertEqual((job.status, job.message), ('error', '모두 혼잡'))

    def test_unexpected_error_becomes_job_error(self):
        from .models import ScheduleUploadJob
        self.upload(side_effect=RuntimeError('boom'))
        self.assertEqual(ScheduleUploadJob.objects.get(user=self.user).status, 'error')

    def test_stale_running_job_marked_failed(self):
        from datetime import timedelta
        from django.utils import timezone
        from .models import ScheduleUploadJob
        job = ScheduleUploadJob.objects.create(user=self.user, filename='x')
        ScheduleUploadJob.objects.filter(id=job.id).update(updated_at=timezone.now() - timedelta(minutes=30))
        self.assertEqual(self.client.get(reverse('schedule_upload_job', args=[job.id])).json()['job']['state'], 'error')

    def test_cannot_see_other_users_job(self):
        from .models import ScheduleUploadJob
        other = get_user_model().objects.create_user('other', password='x')
        job = ScheduleUploadJob.objects.create(user=other, filename='x')
        self.assertEqual(self.client.get(reverse('schedule_upload_job', args=[job.id])).status_code, 404)


class AnesthesiaTypeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('doc', password='x')
        self.user.is_specially_approved = True
        self.user.save()
        self.client.force_login(self.user)

    def test_normalize(self):
        from .table_parser import normalize_anesthesia as n
        self.assertEqual([n(v) for v in ['전신', 'General (ETT)', 'TIVA', 'S/A', '척추마취', 'Epidural', 'CSE',
                                          'nerve block', 'MAC/sedation', '국소', 'Spinal + sedation', '']],
                         ['GA', 'GA', 'GA', 'SA', 'SA', 'EA', 'CSE', 'BL', 'MAC', 'LA', 'SA', ''])
        self.assertEqual(n('gamma knife'), 'gamma knife')  # 모르는 값은 원문 유지
        self.assertEqual(n('김마취', keep_unknown=False), '')

    def test_table_columns(self):
        from .table_parser import parse_delimited_text
        # '마취방법' 열 + '마취' 열(이름) / '마취' 열(방법)
        a = parse_delimited_text('방,수술명,환자명,마취방법,마취\n101,Op,A,척추,이마취\n')[0]
        self.assertEqual((a['anesthesia_type'], a['anesthesiologist']), ('SA', '이마취'))
        b = parse_delimited_text('방,수술명,환자명,마취의,마취\n101,Op,B,이마취,MAC\n')[0]
        self.assertEqual((b['anesthesia_type'], b['anesthesiologist']), ('MAC', '이마취'))

    def test_board_counts_manual_set_and_kept_on_update(self):
        case = make(self.user, '101', '08:00', name='홍길동', info='')
        make(self.user, '102', '08:00', name='김영희', info='', anesthesia_type='GA')
        res = self.client.post(reverse('schedule_update', args=[case.id]), json.dumps({'anesthesia_type': '척추'}),
                               content_type='application/json')
        self.assertEqual(res.json()['room']['cases'][0]['anesthesia_type'], 'SA')
        board = self.client.get(reverse('schedule_dashboard')).context['board']
        self.assertEqual(board['anesthesia_counts'], {'SA': 1, 'GA': 1})
        # 파일에 마취 방법이 없으면 수동 값 유지, 있으면 파일 값
        update_schedules_from_records([rec('105', '09:00', '홍길동', 'Op'), rec('102', '08:00', '김영희', 'Op', anesthesia_type='MAC/sedation')],
                                      self.user, list(SurgerySchedule.objects.filter(user=self.user)))
        self.assertEqual(dict(SurgerySchedule.objects.filter(user=self.user).values_list('patient_name', 'anesthesia_type')),
                         {'홍길동': 'SA', '김영희': 'MAC'})


class NoticeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user('doc', password='x')
        self.user.is_specially_approved = True
        self.user.save()
        self.client.force_login(self.user)

    def test_save_and_render(self):
        from .models import BoardNotice
        res = self.client.post(reverse('schedule_notice'), json.dumps({'content': '11시 회의 <b>'}), content_type='application/json')
        self.assertEqual(res.json()['status'], 'success')
        self.client.post(reverse('schedule_notice'), json.dumps({'content': '11시 회의 <b>!'}), content_type='application/json')
        self.assertEqual(BoardNotice.objects.get(user=self.user).content, '11시 회의 <b>!')
        page = self.client.get(reverse('schedule_dashboard'))
        self.assertContains(page, '11시 회의 &lt;b&gt;!')

    def test_notice_is_per_user(self):
        from .models import BoardNotice
        other = get_user_model().objects.create_user('other', password='x')
        BoardNotice.objects.create(user=other, content='비밀 공지')
        self.assertNotContains(self.client.get(reverse('schedule_dashboard')), '비밀 공지')


class HeaderVariantTests(TestCase):
    """다른 병원·EMR 양식의 열 이름도 표로 읽히는지 (열 이름이 조금씩 달라도)."""

    HEADERS = {
        'kr_basic': ["날짜", "방", "시간", "수술명", "진료과", "집도의", "수술 시간", "환자명", "환자정보", "진행 상황"],
        'kr_formal': ["수술일자", "수술실", "순번", "예정시각", "진료과", "집도의사", "마취의사", "마취방법", "환자성명", "등록번호", "성별", "나이", "수술명", "진행상태"],
        'en_emr': ["Date", "OR", "Start Time", "Est. Duration", "Dept", "Surgeon", "Anesthesiologist", "Anesthesia", "Patient Name", "MRN", "Sex/Age", "Procedure", "Status"],
        'en_abbr': ["OP Date", "Room No.", "Seq", "Time", "Department", "Operator", "Anes. Dr", "Anes. Type", "Name", "Chart No", "Age/Sex", "Operation Name", "Progress"],
        'kr_units': ["수술방번호", "수술시작예정", "소요시간(분)", "과명", "주집도의", "담당마취의", "마취종류", "환자명", "병록번호", "성별/나이", "수술명(국문)", "수술상태"],
        'kr_short': ["방번호", "시작", "예상시간", "과", "집도", "마취", "성명", "ID", "S/A", "수술", "상태"],
        'us': ["OR Room", "Scheduled Start", "Procedure Description", "Primary Surgeon", "Anesthesia Provider", "Anesthesia Type", "Patient", "MRN", "Case Status"],
        'ward_col': ["수술일", "수술실", "병실", "시간", "환자명", "등록번호", "진단명", "수술명", "집도의", "상태"],
        'en_short': ["Room#", "Time", "Case", "Surgeon", "Anesth", "Pt", "Age", "Sex", "Status"],
        'kr_spaced': ["수술실(호)", "예정 시간", "수술 명", "집도 의", "환자 이름", "환자 번호", "마취 방법", "진행"],
    }

    def parse(self, header, row):
        from .table_parser import parse_table_rows
        report = {}
        return parse_table_rows([header, row], report=report), report

    def test_all_variants_read_as_tables(self):
        for name, header in self.HEADERS.items():
            with self.subTest(name):
                row = [f"v{i}" for i in range(len(header))]
                records, report = self.parse(header, row)
                self.assertIsNotNone(records, report.get('reason'))
                rec = records[0]
                # 방·수술명·환자 정보가 빠짐없이 들어와야 함
                self.assertTrue(rec['room'] and rec['surgery_name'])
                self.assertTrue(rec['patient_name'] or rec['patient_info'])

    def test_field_mapping_details(self):
        h = self.HEADERS['kr_formal']
        row = ['2026-09-25', '3', '1', '08:30', 'OS', '김집도', '이마취', '척추', '홍길동', '12345678', 'M', '70', 'TKRA', '대기']
        rec = self.parse(h, row)[0][0]
        self.assertEqual(
            {k: rec[k] for k in ('date', 'room', 'time_slot', 'surgeon', 'anesthesiologist', 'anesthesia_type', 'patient_name', 'patient_info', 'surgery_name', 'status')},
            {'date': '2026-09-25', 'room': '3', 'time_slot': '08:30', 'surgeon': '김집도', 'anesthesiologist': '이마취', 'anesthesia_type': 'SA',
             'patient_name': '홍길동', 'patient_info': '12345678 (M/70)', 'surgery_name': 'TKRA', 'status': '예정'})

    def test_ward_room_and_diagnosis_are_not_misread(self):
        h = self.HEADERS['ward_col']
        rec, report = self.parse(h, ['2026-09-25', '5', '702호', '08:00', '홍길동', '123', '무릎 관절염', 'TKRA', '김', '대기'])
        self.assertEqual((rec[0]['room'], rec[0]['surgery_name']), ('5', 'TKRA'))
        self.assertEqual(report['unused'], ['병실', '진단명'])

    def test_unsure_tables_go_to_ai(self):
        # 수술명 열 없음 / 환자 열을 못 찾았는데 모르는 열이 있음 -> 표로 읽지 않음(AI 로)
        for header in (["방", "시간", "환자명", "집도의"], ["방", "시간", "수술명", "Pt. Nm"]):
            with self.subTest(header):
                records, report = self.parse(header, ["101", "08:00", "x", "y"])
                self.assertIsNone(records)
                self.assertTrue(report['reason'])

    def test_two_row_header_and_section_rows(self):
        from .table_parser import parse_table_rows
        rec = parse_table_rows([["수술", "", "환자", "", ""], ["방", "수술명", "이름", "번호", "집도의"],
                                ["101", "TKRA", "홍길동", "123456", "김"]])[0]
        self.assertEqual((rec['patient_name'], rec['patient_info']), ('홍길동', '123456'))
        recs = parse_table_rows([["방", "시간", "수술명", "환자명"], ["2026-09-25"], ["3번방"], ["", "08:00", "Op1", "A"],
                                 ["OR 5"], ["", "09:00", "Op2", "B"]])
        self.assertEqual([(r['date'], r['room']) for r in recs], [('2026-09-25', '3번방'), ('2026-09-25', 'OR 5')])

    def test_upload_message_lists_columns_and_force_ai(self):
        from unittest import mock
        from django.core.files.uploadedfile import SimpleUploadedFile
        user = get_user_model().objects.create_user('doc', password='x')
        user.is_specially_approved = True
        user.save()
        self.client.force_login(user)
        csv_bytes = '수술실,예정시각,수술명,집도의사,환자성명,병실\n3,08:00,TKRA,김,홍길동,702\n'.encode()
        res = self.client.post(reverse('schedule_dashboard'), {'file': SimpleUploadedFile('s.csv', csv_bytes)}, follow=True)
        msg = [str(m) for m in res.context['messages']][0]
        self.assertIn('1건을 표 형식으로', msg)
        self.assertIn('환자성명→환자명', msg)
        self.assertIn('사용하지 않은 열: 병실', msg)
        # 'AI로 분석' 을 고르면 표로 읽지 않음
        with mock.patch('schedule.views.extract_schedules', return_value=[rec('9', '1', 'X', 'Op')]) as ai, \
                mock.patch('schedule.views.start_background', side_effect=lambda f, *a: f(*a)):
            self.client.post(reverse('schedule_dashboard'), {'file': SimpleUploadedFile('s.csv', csv_bytes), 'force_ai': '1'})
        ai.assert_called_once()


class ManualRoomOrderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('doc', password='x')
        self.user.is_specially_approved = True
        self.user.save()
        self.client.force_login(self.user)
        self.a = make(self.user, '101', '08:00', status='진행중', name='A', info='')
        self.b = make(self.user, '101', '10:00', status='예정', name='B', info='')
        self.c = make(self.user, '101', '12:00', status='예정', name='C', info='')

    def post(self, case, payload):
        res = self.client.post(reverse('schedule_update', args=[case.id]), json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def order(self, room='101'):
        board = self.client.get(reverse('schedule_dashboard')).context['board']
        found = next((r for r in board['rooms'] if r['room'] == room), None)
        return [c['patient_name'] for c in found['cases']] if found else []

    def test_move_up_and_down(self):
        room = self.post(self.c, {'move': 'up'})['room']
        self.assertEqual([c['patient_name'] for c in room['cases']], ['A', 'C', 'B'])
        self.post(self.a, {'move': 'down'})
        self.assertEqual(self.order(), ['C', 'A', 'B'])
        self.post(self.c, {'move': 'up'})  # 이미 맨 앞 - 그대로
        self.assertEqual(self.order(), ['C', 'A', 'B'])

    def test_reorder_changes_which_case_starts_next(self):
        self.post(self.c, {'move': 'up'})           # A, C, B
        self.post(self.a, {'status': 'finished'})   # 다음 = C
        statuses = dict(SurgerySchedule.objects.filter(user=self.user).values_list('patient_name', 'status'))
        self.assertEqual(statuses, {'A': '완료', 'C': '진행중', 'B': '예정'})

    def test_move_to_other_room_returns_board(self):
        data = self.post(self.b, {'room': ' 205 '})
        self.assertEqual(data['room']['room'], '205')
        self.assertEqual([r['room'] for r in data['board']['rooms']], ['101', '205'])
        self.assertEqual(self.order('101'), ['A', 'C'])
        self.assertEqual(self.order('205'), ['B'])

    def test_schedule_update_resets_manual_room_and_order_to_file(self):
        self.post(self.b, {'room': '205'})
        self.post(self.c, {'move': 'up'})           # B 는 205 로, 101: C 를 A 앞으로
        self.assertEqual(self.order('101'), ['C', 'A'])
        # 업데이트 파일: B 는 101 그대로, C 는 301 로 바뀜 -> 파일이 기준
        records = [rec('101', '08:00', 'A', 'Op'), rec('101', '10:00', 'B', 'Op'), rec('301', '09:00', 'C', 'Op'),
                   rec('101', '13:00', 'D', 'Op')]
        update_schedules_from_records(records, self.user, list(SurgerySchedule.objects.filter(user=self.user)))
        self.assertEqual(self.order('101'), ['A', 'B', 'D'])
        self.assertEqual(self.order('301'), ['C'])
        self.assertEqual(self.order('205'), [])
        self.assertFalse(SurgerySchedule.objects.filter(user=self.user).exclude(position=0).exists())
        # 메모 등 수술별 정보는 그대로 같은 수술에 남음 (같은 행이 갱신됨)
        self.assertEqual(SurgerySchedule.objects.get(user=self.user, patient_name='B').id, self.b.id)

    def test_invalid_room_or_move_rejected(self):
        for payload in ({'room': '  '}, {'move': 'sideways'}):
            res = self.client.post(reverse('schedule_update', args=[self.a.id]), json.dumps(payload), content_type='application/json')
            self.assertEqual(res.status_code, 400)


class ExpectedEndTests(TestCase):
    """진행 중 수술의 종료 예정 = 진행중으로 바꾼 시각 + 예상 시간."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('doc', password='x')
        self.user.is_specially_approved = True
        self.user.save()
        self.client.force_login(self.user)
        self.a = make(self.user, '101', '08:00', name='A', duration=120)
        self.b = make(self.user, '101', '10:00', name='B', duration=90)

    def post(self, case, **data):
        return self.client.post(reverse('schedule_update', args=[case.id]), json.dumps(data), content_type='application/json')

    def get(self, case):
        return SurgerySchedule.objects.get(id=case.id)

    def test_start_finish_and_auto_start_record_times(self):
        from datetime import datetime, timezone as dt_tz
        t1 = datetime(2026, 8, 27, 0, 5, tzinfo=dt_tz.utc)     # 09:05 KST
        with _mock.patch('schedule.views._now', return_value=t1):
            room = self.post(self.a, status='ongoing').json()['room']
        self.assertEqual(self.get(self.a).started_at, t1)
        self.assertEqual(room['cases'][0]['started_at'], '2026-08-27T09:05:00+09:00')
        t2 = datetime(2026, 8, 27, 2, 0, tzinfo=dt_tz.utc)
        with _mock.patch('schedule.views._now', return_value=t2):
            self.post(self.a, status='finished')
        a, b = self.get(self.a), self.get(self.b)
        self.assertEqual((a.started_at, a.finished_at), (t1, t2))
        self.assertEqual((b.status, b.started_at), ('진행중', t2))    # 다음 수술 자동 시작 시각
        self.post(self.b, status='pending')
        self.assertIsNone(self.get(self.b).started_at)

    def test_restarting_other_case_clears_previous_start(self):
        self.post(self.a, status='ongoing')
        self.post(self.b, status='ongoing')
        self.assertIsNone(self.get(self.a).started_at)
        self.assertIsNotNone(self.get(self.b).started_at)

    def test_edit_duration_and_start_time(self):
        from datetime import datetime, timezone as dt_tz
        self.post(self.a, status='ongoing')
        now = datetime(2026, 8, 27, 1, 0, tzinfo=dt_tz.utc)    # 10:00 KST
        with _mock.patch('schedule.views._now', return_value=now):
            res = self.post(self.a, duration=150, started_at='08:40')
        self.assertEqual(res.status_code, 200)
        a = self.get(self.a)
        self.assertEqual((a.duration, a.started_at), (150, datetime(2026, 8, 26, 23, 40, tzinfo=dt_tz.utc)))
        # 지금보다 늦은 시각 -> 자정 전에 시작한 수술 (전날)
        with _mock.patch('schedule.views._now', return_value=now):
            self.post(self.a, started_at='23:30')
        self.assertEqual(self.get(self.a).started_at, datetime(2026, 8, 26, 14, 30, tzinfo=dt_tz.utc))
        for bad in ({'duration': -5}, {'duration': 5000}, {'duration': 'abc'}, {'started_at': '25:00'}, {'started_at': '9시'}):
            with self.subTest(bad):
                self.assertEqual(self.post(self.a, **bad).status_code, 400)
        self.assertEqual(self.get(self.a).duration, 150)

    def test_update_keeps_start_time_and_manual_duration(self):
        self.post(self.a, status='ongoing')
        self.post(self.b, duration=45)
        started = self.get(self.a).started_at
        records = [rec('101', '08:00', 'A', 'Op', '12345678 (M/40)', duration=100),
                   rec('101', '10:00', 'B', 'Op', '12345678 (M/40)', duration=0)]
        update_schedules_from_records(records, self.user, list(SurgerySchedule.objects.filter(user=self.user)))
        a, b = self.get(self.a), self.get(self.b)
        self.assertEqual((a.started_at, a.duration), (started, 100))   # 파일에 값이 있으면 파일 기준
        self.assertEqual(b.duration, 45)                                 # 파일이 비었으면 직접 입력한 값 유지

    def test_dashboard_has_eta_hooks(self):
        self.post(self.a, status='ongoing')
        res = self.client.get(reverse('schedule_dashboard'))
        self.assertContains(res, 'id="timeForm"')
        self.assertContains(res, '"started_at": "20')


class DurationColumnTests(TestCase):
    """예상 시간 열: 규칙 → 종료 시각으로 계산 → (그래도 없으면) AI 에 열만 물어봄."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_clock_parsing(self):
        from .table_parser import clock_minutes, duration_from_times
        for text, minutes in [('09:30', 570), ('8A', 480), ('1:30P', 810), ('2 PM', 840), ('오후 2시', 840),
                              ('9시 30분', 570), ('12A', 0), ('3', None), ('MD', None), ('25:00', None)]:
            with self.subTest(text):
                self.assertEqual(clock_minutes(text), minutes)
        self.assertEqual(duration_from_times('23:00', '01:30'), 150)
        self.assertEqual(duration_from_times('MD', '11:00'), 0)

    def test_end_time_column_gives_duration(self):
        from .table_parser import parse_table_rows
        report = {}
        recs = parse_table_rows([['방', '시작시간', '종료예정', '수술명', '환자명'],
                                 ['1', '08:30', '10:00', 'TKRA', 'A'], ['1', '1P', '3:15P', 'THRA', 'B']], report=report)
        self.assertEqual([r['duration'] for r in recs], [90, 135])
        self.assertIn('종료예정→종료시각', report['used'])

    def test_ai_found_column_is_used_and_checked(self):
        from .table_parser import parse_table_rows
        rows = [['방', '시간', '수술명', '환자명', 'OP예정', '비고2'],
                ['1', '08:00', 'TKRA', '홍길동', '90', '김'], ['1', '10:00', 'THRA', '김철수', '2시간', '이']]
        seen = []

        def resolver(candidates):
            seen.extend(candidates)
            return (4, 'duration')
        report = {}
        recs = parse_table_rows(rows, report=report, resolve_duration=resolver)
        self.assertEqual([r['duration'] for r in recs], [90, 120])
        self.assertIn('OP예정→소요시간(AI)', report['used'])
        # AI 에는 모르는 열의 이름과 시간처럼 생긴 값만 (환자 이름 등 글자는 가림)
        self.assertEqual(seen, [{'index': 4, 'header': 'OP예정', 'samples': ['90', '2시간']},
                                {'index': 5, 'header': '비고2', 'samples': ['(글자)', '(글자)']}])
        # 엉뚱한 열을 고르면 값 검증에서 걸러 예상 시간 없음
        recs = parse_table_rows(rows, resolve_duration=lambda c: (5, 'duration'))
        self.assertEqual([r['duration'] for r in recs], [0, 0])
        # AI 오류는 업로드를 막지 않음
        recs = parse_table_rows(rows, resolve_duration=_mock.Mock(side_effect=RuntimeError('down')))
        self.assertEqual(len(recs), 2)

    def test_rule_found_column_skips_ai(self):
        from .table_parser import parse_table_rows
        resolver = _mock.Mock()
        parse_table_rows([['방', '수술명', '환자명', '소요시간'], ['1', 'Op', 'A', '60']], resolve_duration=resolver)
        resolver.assert_not_called()

    @_mock.patch('schedule.ai_client.configured_providers', return_value=['groq'])
    def test_find_duration_column_asks_once_per_layout(self, _providers):
        from .ai_client import find_duration_column
        cands = [{'index': 4, 'header': 'OP예정', 'samples': ['90']}]
        with _mock.patch('schedule.ai_client.ask_json', return_value={'index': 4, 'kind': 'duration'}) as ask:
            self.assertEqual(find_duration_column(cands), (4, 'duration'))
            self.assertEqual(find_duration_column(cands), (4, 'duration'))
        ask.assert_called_once()
        self.assertIn('OP예정', ask.call_args[0][1])
        with _mock.patch('schedule.ai_client.ask_json', return_value={'index': None, 'kind': None}):
            self.assertIsNone(find_duration_column([{'index': 1, 'header': 'X', 'samples': []}]))
        with _mock.patch('schedule.ai_client.ask_json', return_value=None) as ask:   # 실패는 기억하지 않음
            find_duration_column([{'index': 2, 'header': 'Y', 'samples': []}])
            find_duration_column([{'index': 2, 'header': 'Y', 'samples': []}])
        self.assertEqual(ask.call_count, 2)

    def test_no_ai_keys_means_no_call(self):
        from .ai_client import find_duration_column
        with _mock.patch('schedule.ai_client.configured_providers', return_value=[]), \
                _mock.patch('schedule.ai_client.ask_json') as ask:
            self.assertIsNone(find_duration_column([{'index': 1, 'header': 'X', 'samples': []}]))
        ask.assert_not_called()

    def test_upload_uses_ai_column_and_says_so(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from . import ai_client
        user = get_user_model().objects.create_user('doc', password='x')
        user.is_specially_approved = True
        user.save()
        self.client.force_login(user)
        csv_bytes = '방,시간,수술명,환자명,OP예정\n1,08:00,TKRA,홍길동,90\n'.encode()
        with _mock.patch('schedule.views.find_duration_column', wraps=ai_client.find_duration_column), \
                _mock.patch('schedule.ai_client.configured_providers', return_value=['groq']), \
                _mock.patch('schedule.ai_client.ask_json', return_value={'index': 4, 'kind': 'duration'}):
            res = self.client.post(reverse('schedule_dashboard'), {'file': SimpleUploadedFile('s.csv', csv_bytes)}, follow=True)
        self.assertEqual(SurgerySchedule.objects.get(user=user).duration, 90)
        self.assertIn('OP예정→소요시간(AI)', str(list(res.context['messages'])[0]))
        # 예상 시간을 전혀 못 찾으면 직접 입력 안내
        res = self.client.post(reverse('schedule_dashboard'),
                               {'file': SimpleUploadedFile('s.csv', '방,시간,수술명,환자명\n1,08:00,TKRA,홍길동\n'.encode())}, follow=True)
        self.assertIn('수술 메뉴에서 예상 시간을 입력', str(list(res.context['messages'])[0]))
