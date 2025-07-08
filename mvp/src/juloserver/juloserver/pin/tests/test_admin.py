from django.core.urlresolvers import reverse
from django.test import TestCase

from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.pin.models import BlacklistedFraudster


class  TestBlacklistFraudster(TestCase):
    def setUp(self):
        self.auth_user = AuthUserFactory(username='usertest', is_superuser=True, is_staff=True)
        self.client.force_login(self.auth_user)

    def test_get_add(self):
        url = reverse('admin:pin_blacklistedfraudster_add')
        res = self.client.get(url)

        self.assertContains(res, 'Save')

    def test_post_add(self):
        url = reverse('admin:pin_blacklistedfraudster_add')
        post_data = {
            'android_id': 'android id test',
            'blacklist_reason': 'reason'
        }
        res = self.client.post(url, post_data)

        obj = BlacklistedFraudster.objects.get(android_id='android id test')
        self.assertIsNotNone(obj)
        self.assertEqual('reason', obj.blacklist_reason)
        self.assertEqual(self.auth_user.id, obj.added_by_id)
