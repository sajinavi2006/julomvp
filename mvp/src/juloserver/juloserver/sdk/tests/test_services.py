from django.test.testcases import TestCase, override_settings
from ..services import update_axiata_offer, register_digisign_pede
from juloserver.julo.tests.factories import OfferFactory, ApplicationFactory
from .factories import AxiataCustomerDataFactory
from juloserver.julo.exceptions import JuloException
from mock import patch

@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestAxiataOfferUpdate(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.offer = OfferFactory(application=self.application)

    def test_update_axiata_offer(self):
        with self.assertRaises(JuloException):
            update_axiata_offer(self.offer)

        self.axiata_customer_data = AxiataCustomerDataFactory()
        self.axiata_customer_data.application = self.application
        self.axiata_customer_data.loan_amount = 100000
        self.axiata_customer_data.interest_rate = 0.25
        self.axiata_customer_data.save()
        return_value = update_axiata_offer(self.offer)
        self.offer.refresh_from_db()
        self.assertIsNone(return_value)
        assert self.offer.installment_amount_offer == 100250
        assert self.offer.first_installment_amount == 100250


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestRegisterDigisignPede(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.offer = OfferFactory(application=self.application)
        self.mock_user_status_value = self.mock_register_response_success = {
            'JSONFile' : {
                'result': '00',
                'info': 'aktif',
                'notif': 'success'
            }
        }
        self.mock_user_register_value = {
            'JSONFile' : {
                'result': '00',
                'notif': 'success'
            }
        }

        self.mock_user_status_value_not_found = {
            'JSONFile' : {
                'result': '05',
                'notif': 'failed'
            }
        }

        self.mock_fail_value = {
            'JSONFile' : {
                'result': 'xx',
                'info': 'fail',
                'notif': 'failure'
            }
        }

    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.julo.clients.digisign.JuloDigisignClient.user_status')
    @patch('juloserver.julo.clients.digisign.JuloDigisignClient.register')
    def test_register_digisign_pede_success(self, mock_register, mock_user_status,
                                                               mock_status_change):
        mock_user_status.return_value = self.mock_user_status_value
        mock_register.return_value = self.mock_user_register_value
        url, reason, status = register_digisign_pede(self.application)
        assert url is not None
        assert status is not None
        assert reason is not None

    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.julo.clients.digisign.JuloDigisignClient.user_status')
    @patch('juloserver.julo.clients.digisign.JuloDigisignClient.register')
    def test_register_digisign_pede_data_not_found(self, mock_register, mock_user_status,
                                                                      mock_status_change):
        mock_user_status.return_value = self.mock_user_status_value_not_found
        mock_register.return_value = self.mock_register_response_success
        url, reason, status = register_digisign_pede(self.application)
        assert url is not None
        assert status is not None
        assert reason is not None

    @patch('juloserver.julo.services.process_application_status_change')
    @patch('juloserver.julo.clients.digisign.JuloDigisignClient.user_status')
    @patch('juloserver.julo.clients.digisign.JuloDigisignClient.register')
    def test_register_digisign_pede_data_not_found_fail_register(self, mock_register,
                                                mock_user_status, mock_status_change):
        mock_user_status.return_value = self.mock_user_status_value_not_found
        mock_register.return_value = self.mock_fail_value
        mock_status_change = True
        url, status, reason = register_digisign_pede(self.application)
        assert url is None
        assert status is 'registration_failed'
        assert reason is self.mock_fail_value['JSONFile']['notif']

