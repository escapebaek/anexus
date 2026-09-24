from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

import json

from .models import SurgerySchedule, PatientMemo, RoomFlag
from .views import build_board, status_group, update_schedules_from_records


def make(user, room, time_slot, status='예정', name='환자', surgery='Op', info='12345678 (M/40)', **extra):
    return SurgerySchedule.objects.create(
        user=user, date=date(2026, 8, 27), room=room, time_slot=time_slot, surgery_name=surgery,
        department='GS', surgeon='김의사', duration=60, patient_name=name, patient_info=info,
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
        self.assertEqual(res.json()['anesthesiologist'], '이마취')
        self.assertEqual(self.post(reverse('schedule_update', args=[self.theirs.id]), {'anesthesiologist': 'x'}).status_code, 404)

    def test_room_flags(self):
        url = reverse('schedule_room_flag')
        self.assertEqual(self.post(url, {'room': '101', 'hold': True}).json()['hold'], True)
        self.post(url, {'room': '101', 'on_call': True})
        board = self.client.get(reverse('schedule_dashboard')).context['board']
        self.assertEqual((board['rooms'][0]['hold'], board['rooms'][0]['on_call']), (True, True))
        self.assertEqual((board['counts']['hold'], board['counts']['on_call']), (1, 1))
        self.post(url, {'room': '101', 'hold': False, 'on_call': False})
        self.assertFalse(RoomFlag.objects.filter(user=self.user).exists())
        self.assertEqual(self.post(url, {'room': '999', 'hold': True}).status_code, 404)


class UploadActionTests(TestCase):
    """업로드 폼: 'update' 는 메모를 유지하고, action 값이 빠져도 전체 교체되지 않아야 함."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('doc', password='x')
        self.user.is_specially_approved = True
        self.user.save()
        self.client.force_login(self.user)
        self.case = make(self.user, '101', '08:00', name='홍길동', surgery='TKRA', info='11111111 (M/70)')
        PatientMemo.objects.create(schedule=self.case, content='memo')
        RoomFlag.objects.create(user=self.user, room='101', hold=True)

    def upload(self, **post):
        from unittest import mock
        from django.core.files.uploadedfile import SimpleUploadedFile
        records = [rec('205', '10:00', '홍길동', 'TKRA', '11111111 (M/70)')]
        with mock.patch('schedule.views.extract_schedules_from_text', return_value=records):
            post['file'] = SimpleUploadedFile('s.txt', b'schedule')
            return self.client.post(reverse('schedule_dashboard'), post)

    def test_missing_action_defaults_to_update(self):
        self.assertEqual(self.upload().status_code, 302)
        schedule = SurgerySchedule.objects.get(user=self.user)
        self.assertEqual((schedule.id, schedule.room), (self.case.id, '205'))
        self.assertEqual(schedule.memos.get().content, 'memo')

    def test_update_keeps_memo_and_flags(self):
        self.upload(action='update')
        self.assertEqual(PatientMemo.objects.get().content, 'memo')
        self.assertTrue(RoomFlag.objects.filter(user=self.user, room='101', hold=True).exists())

    def test_replace_clears_everything(self):
        self.upload(action='replace')
        self.assertFalse(PatientMemo.objects.exists())
        self.assertFalse(RoomFlag.objects.filter(user=self.user).exists())
        self.assertEqual(SurgerySchedule.objects.get(user=self.user).room, '205')
