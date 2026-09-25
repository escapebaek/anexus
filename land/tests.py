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
        self.assertEqual(len(cards), 18)
        # 내부 기능은 첫 섹션에만, 외부 링크는 external 로 표시
        self.assertFalse(any(c['external'] for c in res.context['sections'][0]['cards']))
        self.assertTrue(all(c['external'] for s in res.context['sections'][1:] for c in s['cards']))

    def test_anonymous_cards_go_to_login(self):
        res = self.client.get(reverse('home'))
        self.assertContains(res, '로그인 후 이용', count=18)
        self.assertContains(res, 'href="%s?next=/board/"' % reverse('login'))
        self.assertContains(res, '?next=https%3A//www.nysora.com/')
        self.assertNotContains(res, 'href="https://www.nysora.com/"')

    def test_pending_member_sees_locked_cards(self):
        self.client.force_login(self.make_user(is_approved=False))
        res = self.client.get(reverse('home'))
        self.assertContains(res, 'is-locked', count=18)
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
