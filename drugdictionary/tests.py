from django.test import TestCase

# Create your tests here.


from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings


class DrugInfoTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('u', 'u@example.com', 'x', is_approved=True))

    @override_settings(FDA_API_KEY='')
    def test_errors_are_not_shown_raw_and_key_is_optional(self):
        with mock.patch('drugdictionary.views.requests.get', side_effect=RuntimeError('secret internals')) as get:
            res = self.client.get('/drugdictionary/?q=propofol')
        self.assertNotContains(res, 'secret internals')
        self.assertContains(res, 'Could not load drug information')
        self.assertNotIn('api_key', get.call_args.kwargs['params'])

    @override_settings(FDA_API_KEY='k123')
    def test_key_comes_from_settings(self):
        with mock.patch('drugdictionary.views.requests.get') as get:
            get.return_value.status_code = 404
            get.return_value.json.return_value = {}
            self.client.get('/drugdictionary/?q=propofol')
        self.assertEqual(get.call_args.kwargs['params']['api_key'], 'k123')
