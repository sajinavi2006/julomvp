import mock
from rest_framework.test import APIClient
from rest_framework.test import APITestCase
from django.test import override_settings
import time
from django.contrib.auth.models import Permission
from django.contrib.auth.models import User
from django.contrib.auth.models import Group


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class JuloAPITestCase(APITestCase):

    client = APIClient()

    @mock.patch('juloserver.apiv1.views.send_email_verification_email')
    def setUp(self, mock_send_email_verification_email):
        self.agent1 = "agent1"
        self.group= Group.objects.get_or_create(name=self.agent1)

        url = '/api/v1/rest-auth/registration/'
        data = {
            'email': 'hans+test_%s@julofinance.com' % time.time(),
            'password1': '1234567',
            'password2': '1234567'
        }
        response = self.client.post(url, data, format='json')
        user = User.objects.get(email=data['email'])
        permission = Permission.objects.get(codename='add_agent')
        user.user_permissions.add(permission)
        token = response.data['token']
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

    @mock.patch('juloserver.apiv1.tasks.send_email_verification_email')
    @mock.patch('collectioncrm.authserver.api.requests.post')
    def test_agent_create(self, mock_data, mock_task):

        mock_data.return_value.ok = True
        role_url = '/api/v1/agents/roles'
        roles = self.client.get(role_url, format='json')
        url = '/api/v1/agents/'
        data = {
            'name': "name",
            'password': "password",
            "user":"julo@julofinance.com",
            "role":self.group[0].pk
        }
        result = self.client.post(url, data, format='json')
        self.assertEqual(200, result.status_code)

