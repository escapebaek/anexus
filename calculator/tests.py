from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class CalculatorPageTests(TestCase):
    """성인·소아 계산기를 한 화면에서 토글: 승인된 회원만, 계산은 브라우저(static/js/calculator)에서."""

    def login(self, **extra):
        user = get_user_model().objects.create_user('u', 'u@example.com', 'x', **extra)
        self.client.force_login(user)

    def test_anonymous_goes_to_login_and_pending_member_to_notice(self):
        url = reverse('calculator')
        res = self.client.get(url)
        self.assertRedirects(res, f"{reverse('login')}?next={url}", fetch_redirect_response=False)
        self.login(is_approved=False)
        res = self.client.get(url)
        self.assertRedirects(res, reverse('approval_pending'), fetch_redirect_response=False)

    def test_one_page_has_both_calculators_and_toggle(self):
        self.login(is_approved=True)
        res = self.client.get(reverse('calculator'))
        for script in ('js/calculator/drug.js', 'js/calculator/pediatric.js', 'js/calculator/calculator.js'):
            self.assertContains(res, script)
        self.assertContains(res, 'data-mode="adult"')                     # 기본은 성인
        self.assertContains(res, 'data-img-base="/static/img/drugs/"')
        self.assertContains(res, 'id="weight"', count=1)                   # 환자 정보는 한 벌만
        self.assertContains(res, 'id="adultGrid"')
        self.assertContains(res, 'id="drugGrid"')
        self.assertContains(res, 'class="cx-mode-btn" data-mode="ped"')
        # 사이트 공통 스크립트가 submit 버튼을 'Loading...' 으로 바꾸지 않게 계산 버튼은 type=button
        self.assertContains(res, 'type="button" class="cx-btn-calc"')
        self.assertNotContains(res, 'type="submit" class="cx-')
        res = self.client.get(reverse('calculator') + '?mode=ped')
        self.assertContains(res, '<div class="calc" data-mode="ped"')
        res = self.client.get(reverse('calculator') + '?mode=weird')
        self.assertContains(res, '<div class="calc" data-mode="adult"')

    def test_old_addresses_redirect_to_the_right_mode(self):
        self.assertRedirects(self.client.get(reverse('calculator_drug')), reverse('calculator') + '?mode=adult',
                             status_code=301, fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('calculator_pediatric')), reverse('calculator') + '?mode=ped',
                             status_code=301, fetch_redirect_response=False)

    def test_landing_has_one_calculator_card(self):
        self.login(is_approved=True)
        cards = {c['title']: c for s in self.client.get(reverse('home')).context['sections'] for c in s['cards']}
        self.assertEqual(cards['Drug Calculator']['url'], reverse('calculator'))
        self.assertFalse(cards['Drug Calculator']['external'])
        self.assertNotIn('Pediatric Calculator', cards)
