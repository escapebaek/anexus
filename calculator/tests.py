from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class CalculatorPageTests(TestCase):
    """성인·소아 계산기: 승인된 회원만, 계산은 브라우저(static/js/calculator)에서."""

    def login(self, **extra):
        user = get_user_model().objects.create_user('u', 'u@example.com', 'x', **extra)
        self.client.force_login(user)

    def test_anonymous_goes_to_login_and_pending_member_to_notice(self):
        for name in ('calculator_drug', 'calculator_pediatric'):
            res = self.client.get(reverse(name))
            self.assertRedirects(res, f"{reverse('login')}?next={reverse(name)}", fetch_redirect_response=False)
        self.login(is_approved=False)
        res = self.client.get(reverse('calculator_drug'))
        self.assertRedirects(res, reverse('approval_pending'), fetch_redirect_response=False)

    def test_member_sees_both_calculators(self):
        self.login(is_approved=True)
        res = self.client.get(reverse('calculator_drug'))
        self.assertContains(res, 'js/calculator/drug.js')
        self.assertContains(res, 'data-img-base="/static/img/drugs/"')
        self.assertContains(res, 'id="weight"')
        self.assertContains(res, reverse('calculator_pediatric'))           # 서로 오가는 링크
        res = self.client.get(reverse('calculator_pediatric'))
        self.assertContains(res, 'js/calculator/pediatric.js')
        self.assertContains(res, 'id="drugGrid"')
        # 사이트 공통 스크립트가 submit 버튼을 'Loading...' 으로 바꾸지 않게 계산 버튼은 type=button
        self.assertContains(res, 'type="button" class="cx-btn-calc"')
        self.assertNotContains(res, 'type="submit" class="cx-')

    def test_landing_cards_point_to_internal_calculators(self):
        self.login(is_approved=True)
        cards = {c['title']: c for s in self.client.get(reverse('home')).context['sections'] for c in s['cards']}
        self.assertEqual(cards['Drug Calculator']['url'], reverse('calculator_drug'))
        self.assertEqual(cards['Pediatric Calculator']['url'], reverse('calculator_pediatric'))
        self.assertFalse(cards['Drug Calculator']['external'] or cards['Pediatric Calculator']['external'])
