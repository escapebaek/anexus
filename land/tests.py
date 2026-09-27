import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class HomeTests(TestCase):
    def make_user(self, **extra):
        return get_user_model().objects.create_user('u', 'u@example.com', 'S3cure-pass!', **extra)

    def test_cards_are_grouped_into_sections(self):
        res = self.client.get(reverse('home'))
        titles = [s['title'] for s in res.context['sections']]
        self.assertEqual(titles, ['ANExuS', 'Calculators & Simulators', 'Resources'])
        cards = [c for s in res.context['sections'] for c in s['cards']]
        self.assertEqual(len(cards), 17)
        self.assertNotIn('Trends in Anesthesia', [c['title'] for c in cards])   # 추후 개발 후 다시 추가
        # 내부 기능은 첫 섹션에만, 외부 링크는 external 로 표시
        self.assertFalse(any(c['external'] for c in res.context['sections'][0]['cards']))
        self.assertTrue(all(c['external'] for s in res.context['sections'][1:] for c in s['cards']))

    def test_anonymous_cards_go_to_login(self):
        res = self.client.get(reverse('home'))
        self.assertContains(res, '로그인 후 이용', count=17)
        self.assertContains(res, 'href="%s?next=/board/"' % reverse('login'))
        self.assertContains(res, '?next=https%3A//www.nysora.com/')
        self.assertNotContains(res, 'href="https://www.nysora.com/"')

    def test_pending_member_sees_locked_cards(self):
        self.client.force_login(self.make_user(is_approved=False))
        res = self.client.get(reverse('home'))
        self.assertContains(res, 'is-locked', count=17)
        self.assertNotContains(res, 'href="/board/"')

    def test_member_gets_links_and_new_tabs_are_safe(self):
        self.client.force_login(self.make_user(is_approved=True))
        res = self.client.get(reverse('home'))
        html = res.content.decode()
        self.assertIn('href="/board/"', html)
        self.assertIn('href="https://www.nysora.com/" target="_blank" rel="noopener noreferrer"', html)
        # 새 탭으로 여는 링크는 모두 noopener
        for tag in re.findall(r'<a [^>]*target="_blank"[^>]*>', html):
            self.assertIn('rel="noopener noreferrer"', tag)
        # 내부 기능은 같은 탭에서 연다
        self.assertNotRegex(html, r'href="/board/"[^>]*target="_blank"')

    def test_specially_approved_member_is_member(self):
        self.client.force_login(self.make_user(is_approved=False, is_specially_approved=True))
        self.assertContains(self.client.get(reverse('home')), 'href="/board/"')


class SurgerySummaryTests(TestCase):
    """현황판을 쓰는 회원에게는 랜딩에 진행 중 수술을 보여준다."""

    def make_case(self, user, room, status, **extra):
        from datetime import date
        from schedule.models import SurgerySchedule
        return SurgerySchedule.objects.create(
            user=user, date=date(2026, 9, 27), room=room, time_slot='08:00', surgery_name=f'Op {room}',
            department='GS', surgeon='김', duration=extra.pop('duration', 60), patient_name='환자',
            patient_info='1', status=status, **extra)

    def test_shows_ongoing_cases_and_counts(self):
        from datetime import timedelta
        from django.utils import timezone
        user = get_user_model().objects.create_user('sp', 'sp@example.com', 'x', is_approved=True, is_specially_approved=True)
        self.make_case(user, '102', '진행중', started_at=timezone.now() - timedelta(minutes=90))   # 60분 예정 → 초과
        self.make_case(user, '101', '진행중', started_at=timezone.now())
        self.make_case(user, '103', '예정')
        self.make_case(user, '104', '완료')
        self.client.force_login(user)
        res = self.client.get(reverse('home'))
        s = res.context['surgeries']
        self.assertEqual(s['counts'], {'ongoing': 2, 'pending': 1, 'finished': 1})
        self.assertEqual([c['room'] for c in s['ongoing']], ['101', '102'])
        self.assertEqual([c['overdue'] for c in s['ongoing']], [False, True])
        self.assertContains(res, 'class="lp-or"')
        self.assertContains(res, '예정 초과')

    def test_hidden_for_others_and_without_schedule(self):
        member = get_user_model().objects.create_user('m', 'm@example.com', 'x', is_approved=True)
        self.make_case(member, '101', '진행중')
        self.client.force_login(member)
        self.assertNotContains(self.client.get(reverse('home')), 'class="lp-or"')   # 현황판 권한 없음
        special = get_user_model().objects.create_user('s2', 's2@example.com', 'x', is_specially_approved=True)
        self.client.force_login(special)
        self.assertNotContains(self.client.get(reverse('home')), 'class="lp-or"')   # 등록된 일정 없음


class VisitCounterTests(TestCase):
    UA = {'HTTP_USER_AGENT': 'Mozilla/5.0 (iPhone)'}

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def total(self):
        from land.models import DailyVisit
        return sum(DailyVisit.objects.values_list('count', flat=True))

    def test_counts_once_per_browser_visit(self):
        res = self.client.get(reverse('home'), **self.UA)
        self.assertEqual(self.total(), 1)
        self.assertIn('anx_visit', res.cookies)
        self.client.get(reverse('home'), **self.UA)          # 쿠키가 살아 있으면 같은 방문
        self.client.get(reverse('login'), **self.UA)
        self.assertEqual(self.total(), 1)
        self.client.cookies.pop('anx_visit')                  # 30분 지나 쿠키가 사라지면 새 방문
        self.client.get(reverse('home'), **self.UA)
        self.assertEqual(self.total(), 2)

    def test_bots_and_non_pages_are_not_counted(self):
        from django.test import Client
        Client().get(reverse('home'), HTTP_USER_AGENT='Googlebot/2.1')
        Client().get(reverse('home'))                         # 브라우저 정보 없음
        Client().get('/health/', **self.UA)
        Client().post(reverse('login'), {}, **self.UA)
        self.assertEqual(self.total(), 0)

    def test_landing_shows_totals(self):
        from datetime import timedelta
        from django.utils import timezone
        from land.models import DailyVisit
        DailyVisit.objects.create(date=timezone.localdate() - timedelta(days=1), count=40)
        res = self.client.get(reverse('home'), **self.UA)     # 이 방문이 오늘 1회
        self.assertEqual(res.context['visits'], {'total': 40, 'today': 0})   # 표시는 방문을 세기 전 값
        res = self.client.get(reverse('home'), **self.UA)
        self.assertContains(res, 'TOTAL VISITS')
        self.assertContains(res, 'data-count="41"')
