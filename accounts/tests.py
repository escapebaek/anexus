from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import CustomUser


def make_user(username='user', email='user@example.com', password='S3cure-pass!', **extra):
    extra.setdefault('is_approved', True)
    return CustomUser.objects.create_user(username, email, password, real_name='홍길동', **extra)


class AccountTestBase(TestCase):
    def setUp(self):
        cache.clear()


class LoginTests(AccountTestBase):
    def test_login_required_pages_go_to_real_login_page_and_come_back(self):
        # 예전엔 LOGIN_URL 이 없는 '/login/' 이라 404 가 났다
        res = self.client.get('/board/')
        self.assertRedirects(res, reverse('login') + '?next=/board/', fetch_redirect_response=False)
        self.assertEqual(self.client.get(res['Location']).status_code, 200)
        make_user()
        res = self.client.post(reverse('login') + '?next=/board/', {'username': 'user', 'password': 'S3cure-pass!', 'next': '/board/'})
        self.assertRedirects(res, '/board/', fetch_redirect_response=False)

    def test_next_to_other_site_is_ignored(self):
        make_user()
        res = self.client.post(reverse('login'), {'username': 'user', 'password': 'S3cure-pass!', 'next': 'https://evil.example.com/'})
        self.assertRedirects(res, reverse('home'), fetch_redirect_response=False)

    def test_wrong_password_shows_korean_error(self):
        make_user()
        res = self.client.post(reverse('login'), {'username': 'user', 'password': 'nope'})
        self.assertContains(res, '아이디 또는 비밀번호가 맞지 않습니다.')

    def test_too_many_failures_are_blocked_even_with_right_password(self):
        make_user()
        for _ in range(5):
            self.client.post(reverse('login'), {'username': 'user', 'password': 'nope'})
        res = self.client.post(reverse('login'), {'username': 'user', 'password': 'S3cure-pass!'}, follow=True)
        self.assertContains(res, '로그인 시도가 너무 많습니다')
        self.assertFalse(res.wsgi_request.user.is_authenticated)
        # 다른 IP 에서는 막히지 않는다
        res = self.client.post(reverse('login'), {'username': 'user', 'password': 'S3cure-pass!'}, HTTP_X_FORWARDED_FOR='10.0.0.9')
        self.assertEqual(res.status_code, 302)

    def test_success_resets_failure_count(self):
        make_user()
        for _ in range(4):
            self.client.post(reverse('login'), {'username': 'user', 'password': 'nope'})
        self.client.post(reverse('login'), {'username': 'user', 'password': 'S3cure-pass!'})
        self.client.post(reverse('logout'))
        for _ in range(4):
            self.client.post(reverse('login'), {'username': 'user', 'password': 'nope'})
        res = self.client.post(reverse('login'), {'username': 'user', 'password': 'S3cure-pass!'})
        self.assertEqual(res.status_code, 302)


class RegisterTests(AccountTestBase):
    def data(self, **kw):
        base = {'username': 'newbie', 'email': 'new@example.com', 'real_name': '김신입', 'training_hospital': '서울대',
                'password1': 'Str0ng-passw0rd', 'password2': 'Str0ng-passw0rd'}
        base.update(kw)
        return base

    def test_new_member_waits_for_approval(self):
        res = self.client.post(reverse('register'), self.data())
        self.assertRedirects(res, reverse('approval_pending'))
        user = CustomUser.objects.get(username='newbie')
        self.assertFalse(user.is_approved)
        # 승인 전: 회원 전용 화면은 승인 대기 안내로
        self.assertRedirects(self.client.get('/exam/'), reverse('approval_pending'))
        self.assertContains(self.client.get(reverse('home')), '승인 대기 중')
        # 관리자가 승인하면 이용 가능
        user.is_approved = True
        user.save()
        self.assertEqual(self.client.get('/exam/').status_code, 200)
        self.assertRedirects(self.client.get(reverse('approval_pending')), reverse('home'), fetch_redirect_response=False)

    def test_email_is_required_and_unique(self):
        make_user(email='taken@example.com')
        for email, message in [('', '이메일을 입력해 주세요'), ('TAKEN@example.com', '이미 다른 계정에서 쓰고 있는 이메일'),
                               ('default@default.com', '실제로 쓰는 이메일'), ('not-an-email', '올바른 이메일')]:
            res = self.client.post(reverse('register'), self.data(email=email))
            self.assertEqual(res.status_code, 200, email)
            self.assertContains(res, message)
        self.assertFalse(CustomUser.objects.filter(username='newbie').exists())

    def test_errors_keep_entered_values_and_are_korean(self):
        res = self.client.post(reverse('register'), self.data(password2='different'))
        self.assertContains(res, 'value="new@example.com"')
        self.assertContains(res, '비밀번호')
        self.assertNotContains(res, "didn’t match")

    def test_unknown_hospital_rejected(self):
        res = self.client.post(reverse('register'), self.data(training_hospital='<script>'))
        self.assertEqual(res.status_code, 200)
        self.assertFalse(CustomUser.objects.filter(username='newbie').exists())

    @override_settings(EMAIL_CONFIGURED=True, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_admins_get_signup_email_and_nav_badge(self):
        admin = make_user('boss', 'boss@example.com', is_staff=True, is_superuser=True)
        self.client.post(reverse('register'), self.data())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['boss@example.com'])
        self.assertIn('newbie', mail.outbox[0].subject)
        self.client.force_login(admin)
        res = self.client.get(reverse('home'))
        self.assertContains(res, '가입 승인 <b>1</b>')
        # 관리자 화면에서 한 번에 승인
        user = CustomUser.objects.get(username='newbie')
        res = self.client.post(reverse('admin:accounts_customuser_changelist'),
                               {'action': 'approve_users', '_selected_action': [user.pk]}, follow=True)
        user.refresh_from_db()
        self.assertTrue(user.is_approved)
        self.assertNotContains(self.client.get(reverse('home')), 'nav-approval-badge')

    def test_signup_rate_limit(self):
        for i in range(10):
            self.client.post(reverse('register'), self.data(username=f'u{i}', email=f'u{i}@example.com'))
            self.client.post(reverse('logout'))
        res = self.client.post(reverse('register'), self.data(username='u99', email='u99@example.com'))
        self.assertContains(res, '가입 요청이 너무 많습니다')
        self.assertFalse(CustomUser.objects.filter(username='u99').exists())


class MyPageTests(AccountTestBase):
    def setUp(self):
        super().setUp()
        self.user = make_user(email='default@default.com')
        self.client.force_login(self.user)

    def test_placeholder_email_prompts_for_real_one(self):
        res = self.client.get(reverse('mypage'))
        self.assertContains(res, '실제 이메일이 등록되어 있지 않습니다')
        self.assertNotContains(res, 'value="default@default.com"')

    def test_update_is_validated(self):
        make_user('other', 'other@example.com')
        res = self.client.post(reverse('mypage'), {'real_name': '가' * 80, 'email': 'OTHER@example.com', 'training_hospital': '<script>'})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '이미 다른 계정에서 쓰고 있는 이메일')
        self.user.refresh_from_db()
        self.assertEqual((self.user.real_name, self.user.email, self.user.training_hospital), ('홍길동', 'default@default.com', '기타'))

    def test_update_saves_and_stays_on_mypage(self):
        res = self.client.post(reverse('mypage'), {'real_name': ' 김철수 ', 'email': 'me@example.com', 'training_hospital': '서울아산'}, follow=True)
        self.assertRedirects(res, reverse('mypage'))
        self.assertContains(res, '회원 정보를 저장했습니다')
        self.user.refresh_from_db()
        self.assertEqual((self.user.real_name, self.user.email, self.user.training_hospital), ('김철수', 'me@example.com', '서울아산'))

    def test_password_change_returns_to_mypage(self):
        res = self.client.post(reverse('password_change'), {'old_password': 'S3cure-pass!', 'new_password1': 'N3w-passw0rd!', 'new_password2': 'N3w-passw0rd!'}, follow=True)
        self.assertRedirects(res, reverse('mypage'))
        self.assertContains(res, '비밀번호를 바꿨습니다')


class PasswordResetTests(AccountTestBase):
    @override_settings(DEBUG=False, EMAIL_CONFIGURED=False)
    def test_disabled_until_email_is_configured(self):
        make_user(email='me@example.com')
        res = self.client.get(reverse('password_reset'))
        self.assertContains(res, '메일 발송이 아직 설정되지 않아')
        res = self.client.post(reverse('password_reset'), {'email': 'me@example.com'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_CONFIGURED=True, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_sends_korean_mail_but_never_to_placeholder_addresses(self):
        make_user('a', 'me@example.com')
        make_user('b', 'default@default.com')
        make_user('c', 'default@default.com')
        res = self.client.post(reverse('password_reset'), {'email': 'me@example.com'})
        self.assertRedirects(res, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('비밀번호 재설정', mail.outbox[0].subject)
        self.assertIn('/accounts/reset/', mail.outbox[0].body)
        self.client.post(reverse('password_reset'), {'email': 'default@default.com'})
        self.assertEqual(len(mail.outbox), 1)      # 임시 주소 계정들에는 보내지 않는다

    @override_settings(EMAIL_CONFIGURED=True, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_rate_limited(self):
        make_user(email='me@example.com')
        for _ in range(5):
            self.client.post(reverse('password_reset'), {'email': 'me@example.com'})
        res = self.client.post(reverse('password_reset'), {'email': 'me@example.com'}, follow=True)
        self.assertContains(res, '요청이 너무 많습니다')
        self.assertEqual(len(mail.outbox), 5)

    def test_invalid_link_page(self):
        res = self.client.get('/accounts/reset/MQ/bad-token/')
        self.assertContains(res, '링크가 올바르지 않거나')


class SettingsTests(TestCase):
    def test_email_backend_never_logs_mail_in_production(self):
        from importlib import reload
        from django.conf import settings
        self.assertEqual(settings.LOGIN_URL, 'login')
        with mock.patch.dict('os.environ', {'DEBUG': 'False', 'EMAIL_HOST_USER': '', 'EMAIL_HOST_PASSWORD': ''}):
            import anhub.settings as prod
            reload(prod)
            self.assertEqual(prod.EMAIL_BACKEND, 'django.core.mail.backends.dummy.EmailBackend')
        with mock.patch.dict('os.environ', {'DEBUG': 'False', 'EMAIL_HOST_USER': 'x@gmail.com', 'EMAIL_HOST_PASSWORD': 'abcd'}):
            reload(prod)
            self.assertEqual(prod.EMAIL_BACKEND, 'django.core.mail.backends.smtp.EmailBackend')
            self.assertEqual(prod.DEFAULT_FROM_EMAIL, 'ANExuS <x@gmail.com>')
        reload(prod)
