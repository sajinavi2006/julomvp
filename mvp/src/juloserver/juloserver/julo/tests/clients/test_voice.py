import json
from datetime import datetime

from django.utils import timezone
from factory import Iterator
from mock import patch

from datetime import (
    datetime,
    timedelta,
)

from django.test import SimpleTestCase
from django.test.testcases import TestCase

from django.test.utils import override_settings

from juloserver.application_flow.factories import ExperimentSettingFactory
from juloserver.julo.clients.infobip import JuloInfobipVoiceClient
from juloserver.julo.clients.voice import JuloVoiceClient
from juloserver.julo.clients.voice_v2 import JuloVoiceClientV2
from juloserver.julo.models import (
    CommsProviderLookup,
    VoiceCallRecord,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CommsProviderLookupFactory,
    CustomerFactory,
    VoiceCallRecordFactory,
)
from juloserver.nexmo.models import RobocallCallingNumberChanger
from juloserver.nexmo.tests.factories import RobocallCallingNumberChangerFactory


class TestJuloVoiceClient(SimpleTestCase):
    def setUp(self):
        self.sample_private_key = '''-----BEGIN RSA PRIVATE KEY-----
MIICXAIBAAKBgQCqGKukO1De7zhZj6+H0qtjTkVxwTCpvKe4eCZ0FPqri0cb2JZfXJ/DgYSF6vUp
wmJG8wVQZKjeGcjDOL5UlsuusFncCzWBQ7RKNUSesmQRMSGkVb1/3j+skZ6UtW+5u09lHNsj6tQ5
1s1SPrCBkedbNf0Tp0GbMJDyR4e9T04ZZwIDAQABAoGAFijko56+qGyN8M0RVyaRAXz++xTqHBLh
3tx4VgMtrQ+WEgCjhoTwo23KMBAuJGSYnRmoBZM3lMfTKevIkAidPExvYCdm5dYq3XToLkkLv5L2
pIIVOFMDG+KESnAFV7l2c+cnzRMW0+b6f8mR1CJzZuxVLL6Q02fvLi55/mbSYxECQQDeAw6fiIQX
GukBI4eMZZt4nscy2o12KyYner3VpoeE+Np2q+Z3pvAMd/aNzQ/W9WaI+NRfcxUJrmfPwIGm63il
AkEAxCL5HQb2bQr4ByorcMWm/hEP2MZzROV73yF41hPsRC9m66KrheO9HPTJuo3/9s5p+sqGxOlF
L0NDt4SkosjgGwJAFklyR1uZ/wPJjj611cdBcztlPdqoxssQGnh85BzCj/u3WqBpE2vjvyyvyI5k
X6zk7S0ljKtt2jny2+00VsBerQJBAJGC1Mg5Oydo5NwD6BiROrPxGo2bpTbu/fhrT8ebHkTz2epl
U9VQQSQzY1oZMVX8i1m5WUTLPz2yLJIBQVdXqhMCQBGoiuSoSjafUhV7i1cEGpb88h5NBYZzWXGZ
37sJ5QsW+sJyoNde3xH8vdXhzU7eT82D6X/scw9RZz+/6rCJ4p0=
-----END RSA PRIVATE KEY-----'''

    def test_crypt_init_error(self):
        """
        https://juloprojects.atlassian.net/browse/CLS3-106
        https://sentry.io/organizations/juloeng/issues/2526454695
        """
        client = JuloVoiceClient('NEXMO_API_KEY', 'NEXMO_API_SECRET', 'https://api.nexmo.com/v1/calls',
                                 'NEXMO_APPLICATION_ID', self.sample_private_key, '1,2,3', 'http://localhost/')
        headers = client.get_headers()

        self.assertEqual('nexmo-python/2.0.0/2.7.12+', headers.get('User-Agent'))
        self.assertRegex(headers.get('Authorization'), r'^Bearer .+$')


class TestJuloVoiceClientV2(TestCase):
    def setUp(self) -> None:
        self.application = ApplicationFactory()
        self.sample_private_key = '''-----BEGIN RSA PRIVATE KEY-----
            MIICXAIBAAKBgQCqGKukO1De7zhZj6+H0qtjTkVxwTCpvKe4eCZ0FPqri0cb2JZfXJ/DgYSF6vUp
            wmJG8wVQZKjeGcjDOL5UlsuusFncCzWBQ7RKNUSesmQRMSGkVb1/3j+skZ6UtW+5u09lHNsj6tQ5
            1s1SPrCBkedbNf0Tp0GbMJDyR4e9T04ZZwIDAQABAoGAFijko56+qGyN8M0RVyaRAXz++xTqHBLh
            3tx4VgMtrQ+WEgCjhoTwo23KMBAuJGSYnRmoBZM3lMfTKevIkAidPExvYCdm5dYq3XToLkkLv5L2
            pIIVOFMDG+KESnAFV7l2c+cnzRMW0+b6f8mR1CJzZuxVLL6Q02fvLi55/mbSYxECQQDeAw6fiIQX
            GukBI4eMZZt4nscy2o12KyYner3VpoeE+Np2q+Z3pvAMd/aNzQ/W9WaI+NRfcxUJrmfPwIGm63il
            AkEAxCL5HQb2bQr4ByorcMWm/hEP2MZzROV73yF41hPsRC9m66KrheO9HPTJuo3/9s5p+sqGxOlF
            L0NDt4SkosjgGwJAFklyR1uZ/wPJjj611cdBcztlPdqoxssQGnh85BzCj/u3WqBpE2vjvyyvyI5k
            X6zk7S0ljKtt2jny2+00VsBerQJBAJGC1Mg5Oydo5NwD6BiROrPxGo2bpTbu/fhrT8ebHkTz2epl
            U9VQQSQzY1oZMVX8i1m5WUTLPz2yLJIBQVdXqhMCQBGoiuSoSjafUhV7i1cEGpb88h5NBYZzWXGZ
            37sJ5QsW+sJyoNde3xH8vdXhzU7eT82D6X/scw9RZz+/6rCJ4p0=
            -----END RSA PRIVATE KEY-----'''
        self.experiment_setting = ExperimentSettingFactory(
            code='1WayRobocallVendorsABTest',
            start_date=datetime(2023, 3, 1, 12, 0, 0),
            end_date=datetime(2023, 3, 10, 12, 0, 0),
            is_active=True,
            criteria={'nexmo': [0, 1, 2, 3, 4],
                      'infobip': {
                          'calling_number': '628213456789',
                          'account_id_tail': [5, 6, 7, 8, 9]
                      }},
        )
        self.comms_provider = CommsProviderLookup.objects.get(provider_name='Nexmo')

    def test_rotate_voice_for_account_payment_reminder(self):
        VoiceCallRecordFactory(
            application=self.application,
            voice_style_id=0,
            comms_provider=self.comms_provider
        )

        self.application.customer.gender = 'Pria'
        self.application.customer.save()

        with patch.object(
            timezone, 'now', return_value=datetime(2023, 3, 11)
        ):
            client = JuloVoiceClientV2(
                'NEXMO_API_KEY', 'NEXMO_API_SECRET', 'NEXMO_APPLICATION_ID',
                self.sample_private_key, '1,2,3', 'http://localhost/', '999999999')
            style = client.rotate_voice_for_account_payment_reminder(self.application.customer)
            self.assertIn(style, [1, 4])

    def test_account_payment_reminder_with_ab_vendor_experiment_active(self):
        pass

    def test_rotate_nexmo_caller(self):
        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 7, 12, 0, 0)
        ):
            robocall_calling_number_changer_preset = Iterator(['6282112345678', '6282187654321',
                                                               '6282168745123'])
            RobocallCallingNumberChangerFactory.create_batch(
                3, new_calling_number=robocall_calling_number_changer_preset
            )
            VoiceCallRecordFactory.create(
                application_id=self.application.id,
                call_from='6282168745123'
            )

            client = JuloVoiceClientV2(
                'NEXMO_API_KEY', 'NEXMO_API_SECRET', 'NEXMO_APPLICATION_ID', self.sample_private_key,
                '1,2,3', 'http://localhost/', '999999999')
            result = client.rotate_nexmo_caller(self.application.id)

            self.assertIn(result, ['6282112345678', '6282187654321'])

    def test_rotate_nexmo_caller_without_prior_voice_call_record(self):
        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 7, 12, 0, 0)
        ):
            robocall_calling_number_changer_preset = Iterator(['6282112345678', '6282187654321',
                                                               '6282168745123'])
            RobocallCallingNumberChangerFactory.create_batch(
                3, new_calling_number=robocall_calling_number_changer_preset
            )

            client = JuloVoiceClientV2(
                'NEXMO_API_KEY', 'NEXMO_API_SECRET', 'NEXMO_APPLICATION_ID', self.sample_private_key,
                '1,2,3', 'http://localhost/', '999999999')
            result = client.rotate_nexmo_caller(self.application.id)

            self.assertIn(result, ['6282112345678', '6282187654321', '6282168745123'])


class TestJuloInfobipVoiceClient(TestCase):
    def setUp(self):
        self.response_data = [
                {
                    'bulkId': '40978e58-cbdf-4426-97b9-5e7c2068389d',
                    'messageId': '2b43ddc1-9eb6-431a-9415-f67841990577',
                    'from': '442032864231',
                    'to': '6282123457689',
                    'sentAt': '2023-03-14T13:51:03.327+0700',
                    'mccMnc': None,
                    'callbackData': None,
                    'voiceCall': {
                        'feature': 'Text-to-Speech',
                        'startTime': '2023-03-14T13:51:03.000+0700',
                        'answerTime': '2023-03-14T13:51:10.000+0700',
                        'endTime': '2023-03-14T13:51:15.705+0700',
                        'duration': 6,
                        'chargedDuration': 0,
                        'fileDuration': 5.256,
                        'dtmfCodes': None,
                        'ivr': None
                    },
                    'price': {
                        'pricePerSecond': 0.0,
                        'currency': 'UNKNOWN'
                    },
                    'status': {
                        'id': 5,
                        'groupId': 3,
                        'groupName': 'DELIVERED',
                        'name': 'DELIVERED_TO_HANDSET',
                        'description': 'Message delivered to handset'
                    },
                    'error': {
                        'id': 5000,
                        'name': 'VOICE_ANSWERED',
                        'description': 'Call answered by human',
                        'groupId': 0,
                        'groupName': 'OK',
                        'permanent': True
                    }
                }
            ]
        self.voice_call_record = VoiceCallRecordFactory(
            uuid=self.response_data[0]['messageId']
        )
        self.comms_provider_lookup = CommsProviderLookupFactory(provider_name='Infobip')

    def test_infobip_voice_client_with_correct_source(self):
        client = JuloInfobipVoiceClient()
        self.assertEqual(client.source, '442032864231')

        client = JuloInfobipVoiceClient('628123456789')
        self.assertEqual(client.source, '628123456789')

    def test_infobip_voice_client_fetch_voice_report(self):
        infobip_client = JuloInfobipVoiceClient()
        infobip_client.fetch_voice_report(self.response_data)

        voice_call_record = VoiceCallRecord.objects.get(
            uuid=self.response_data[0]['messageId']
        )
        self.assertEqual('DELIVERED', voice_call_record.status)

    @patch('juloserver.julo.clients.infobip.logger')
    def test_infobip_client_fetch_voice_report_with_voice_call_record_none(self, mock_logger):
        self.voice_call_record.delete()
        infobip_client = JuloInfobipVoiceClient()
        infobip_client.fetch_voice_report(self.response_data)

        mock_logger.info.assert_called_once_with({
            'message': 'Infobip send unregistered messsageId',
            'message_id': self.response_data[0]['messageId'],
            'data': self.response_data[0]
        })

    @patch('juloserver.julo.clients.infobip.logger')
    def test_infobip_voice_client_fetch_voice_report_failure(self, mock_logger):
        self.response_data[0]['status'] = {
            'groupId': 4,
            'groupName': 'EXPIRED',
            'id': 15,
            'name': 'EXPIRED_EXPIRED',
            'description': 'Message expired'
        },
        self.response_data[0]['error'] = {
            'id': 5003,
            'name': 'EC_VOICE_NO_ANSWER',
            'description': 'User was notified, but did not answer call',
            'groupId': 2,
            'groupName': 'USER_ERRORS',
            'permanent': True
        }

        infobip_client = JuloInfobipVoiceClient()
        infobip_client.fetch_voice_report(self.response_data)

        mock_logger.warning.assert_called_once_with({
            'message': 'Infobip returns error',
            'message_id': self.response_data[0]['messageId'],
            'error': 'EC_VOICE_NO_ANSWER - User was notified, but did not answer call',
            'error_id': 5003
        })

        voice_call_record = VoiceCallRecord.objects.get(
            uuid=self.response_data[0]['messageId']
        )
        self.assertEqual('failed', voice_call_record.status)

    @override_settings(BASE_URL='http://localhost:8000')
    @override_settings(INFOBIP_VOICE_API_KEY='T3stK3Y')
    @patch('juloserver.julo.clients.infobip.logger')
    def test_infobip_voice_client_construct_request_data_with_false_randomize(self, mock_logger):
        customer = CustomerFactory()

        infobip_client = JuloInfobipVoiceClient()
        payload, header, voice = infobip_client.construct_request_data(
            'Test message', '627123123124', False, **{'customer': customer}
        )
        expected_payload = json.dumps({
            'messages': [
                {
                    'from': '442032864231',
                    'destinations': [{'to': '627123123124'}],
                    'text': 'Test message',
                    'language': 'id',
                    'voice': {
                        'name': 'Andika',
                        'gender': 'male'
                    },
                    'notifyUrl': 'http://localhost:8000/api/streamlined_communication/callbacks/v1/'
                                 'infobip-voice-report',
                }
            ]
        })
        expected_header = {
            'Authorization': 'App T3stK3Y',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        expected_voice = 20

        self.assertEqual(payload, expected_payload)
        self.assertEqual(header, expected_header)
        self.assertEqual(voice, expected_voice)

    @override_settings(BASE_URL='http://localhost:8000')
    @override_settings(INFOBIP_VOICE_API_KEY='T3stK3Y')
    @patch('juloserver.julo.clients.infobip.logger')
    def test_infobip_voice_client_rotate_voice_caller(self, mock_logger):
        customer = CustomerFactory(gender='Pria')
        application = ApplicationFactory(customer=customer)
        VoiceCallRecordFactory(application=application,  voice_style_id=20,
            comms_provider=self.comms_provider_lookup)

        infobip_client = JuloInfobipVoiceClient()
        caller_voice, voice_id = infobip_client.rotate_voice_caller(customer)

        self.assertNotEqual(caller_voice, {'name': 'Andika', 'gender': 'male'})
        self.assertIn(caller_voice,
            [{'name': 'Arif (beta)', 'gender': 'male'}, {'name': 'Reza (beta)', 'gender': 'male'}])

    @override_settings(BASE_URL='http://localhost:8000')
    @override_settings(INFOBIP_VOICE_API_KEY='T3stK3Y')
    @patch('juloserver.julo.clients.infobip.logger')
    def test_infobip_voice_client_rotate_voice_caller_for_new_customer(self, mock_logger):
        customer = CustomerFactory(gender='Pria')
        ApplicationFactory(customer=customer)

        infobip_client = JuloInfobipVoiceClient()
        caller_voice, voice_id = infobip_client.rotate_voice_caller(customer)

        self.assertIn(caller_voice,
            [{'name': 'Andika', 'gender': 'male'}, {'name': 'Arif (beta)', 'gender': 'male'},
             {'name': 'Reza (beta)', 'gender': 'male'}])
