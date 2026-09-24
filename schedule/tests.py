from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import SurgerySchedule
from .views import build_board, status_group


def make(user, room, time_slot, status='예정', name='환자', surgery='Op'):
    return SurgerySchedule.objects.create(
        user=user, date=date(2026, 8, 27), room=room, time_slot=time_slot, surgery_name=surgery,
        department='GS', surgeon='김의사', duration=60, patient_name=name, patient_info='12345678 (M/40)',
        status=status,
    )


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
        self.assertEqual(board['counts'], {'ongoing': 1, 'pending': 1, 'finished': 1})
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
