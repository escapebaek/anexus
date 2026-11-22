from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


# 성인·소아 공통 묶음 순서 (각 모드는 자기에게 있는 묶음만, 이 순서대로)
CATEGORY_ORDER = ['pressor', 'vasodil', 'induction', 'analgesic', 'sedation', 'muscle', 'lytes', 'emergency']


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
        # 종류별 묶음 + 칩 자리, 권장 범위(벗어나면 경고), 내 농도 안내
        for cat in [c for c in CATEGORY_ORDER if c != 'sedation']:   # 성인에는 진정제 묶음이 없음
            self.assertContains(res, f'id="adult-{cat}" data-cat="{cat}"')
        self.assertContains(res, 'class="cx-card"', count=28)
        self.assertContains(res, 'id="calcChips"')
        self.assertContains(res, 'id="nep_dr" data-range="0.01,0.2"')
        self.assertContains(res, 'id="concNote" hidden')
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

    def test_adult_and_pediatric_use_the_same_group_order(self):
        import re
        from pathlib import Path
        from django.conf import settings
        adult = Path(settings.BASE_DIR, 'calculator/templates/calculator/_adult_cards.html').read_text()
        ped = Path(settings.BASE_DIR, 'static/js/calculator/pediatric.js').read_text()
        adult_cats = re.findall(r'<section class="cx-group" id="adult-[a-z]+" data-cat="([a-z]+)"', adult)
        groups = ped[ped.index('const GROUPS = ['):]
        ped_cats = re.findall(r'cat: "([a-z]+)"', groups[:groups.index('];')])
        for cats in (adult_cats, ped_cats):
            self.assertEqual(cats, [c for c in CATEGORY_ORDER if c in cats])
        # 같은 묶음은 같은 이름
        adult_labels = dict(re.findall(r'data-cat="([a-z]+)" data-label="([^"]+)"', adult))
        ped_labels = dict(re.findall(r'cat: "([a-z]+)", ko: "([^"]+)"', ped))
        for cat in set(adult_labels) & set(ped_labels):
            self.assertEqual(adult_labels[cat], ped_labels[cat], cat)
