from django.test.testcases import TestCase
from unittest.mock import patch
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    StatusLookupFactory,
    CustomerFactory,
    FeatureSettingFactory,
)
from juloserver.julo.constants import (
    FeatureNameConst,
)
from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory
from juloserver.digisign.constants import RegistrationStatus, DigisignFeeTypeConst
from juloserver.digisign.models import DigisignRegistration
from juloserver.digisign.tests.factories import (
    DigisignRegistrationFactory,
    DigisignRegistrationFeeFactory
)
from juloserver.digisign.services.digisign_register_services import (
    get_registration_status,
    register_digisign,
    can_make_digisign,
)
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.digisign.services.common_services import (
    calc_digisign_fee,
    calc_registration_fee,
    get_total_digisign_fee,
)
from juloserver.digisign.exceptions import (
    DigitallySignedRegistrationException,
)


class TestDigisignRegistration(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.suspended),
            ever_entered_B5=True,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )

    def test_register_digisign_fail(self):
        DigisignRegistrationFactory(customer_id=self.customer.id)
        with self.assertRaises(DigitallySignedRegistrationException):
            register_digisign(self.application)

    @patch('juloserver.digisign.services.digisign_client.DigisignClient.register')
    def test_register_digisign_success(self, mock_register_req):
        mock_register_req.return_value = {
            'success': True,
            'data': {
                'reference_number': '111',
                'registration_status': 6,
                'error_code': 'no error'
            }
        }
        register_digisign(self.application)

        digi_registration = DigisignRegistration.objects.filter(
            customer_id=self.customer.id
        ).last()

        self.assertIsNotNone(digi_registration)
        self.assertEqual(digi_registration.registration_status, RegistrationStatus.INITIATED)

    @patch(
        'juloserver.digisign.services.digisign_client.DigisignClient.get_registration_status_code'
    )
    def test_get_registration_status(self, mock_get_status_req):
        status = get_registration_status(self.application)
        self.assertIsNone(status)

        mock_get_status_req.return_value = {
            'success': True,
            'data': {
                'reference_number': '111',
                'registration_status': 1,
                'error_code': 'no error'
            }
        }
        digi_registration = DigisignRegistrationFactory(
            customer_id=self.customer.id,
            reference_number='111',
            registration_status=RegistrationStatus.INITIATED
        )
        digi_registration.save()
        status = get_registration_status(self.application)
        self.assertIsNotNone(status)

        digi_registration.refresh_from_db()
        self.assertEqual(status, digi_registration.registration_status)

    @patch(
        'juloserver.digisign.services.digisign_client.DigisignClient.get_registration_status_code'
    )
    def test_can_make_digisign(self, mock_get_status_req):
        result = can_make_digisign(self.application)
        self.assertFalse(result)

        digi_registration = DigisignRegistrationFactory(
            customer_id=self.customer.id,
            reference_number='111',
            registration_status=RegistrationStatus.INITIATED
        )
        mock_get_status_req.return_value = {
            'success': True,
            'data': {
                'reference_number': '111',
                'registration_status': 6,
                'error_code': 'no error'
            }
        }
        result = can_make_digisign(self.application)
        self.assertFalse(result)

        mock_get_status_req.return_value = {
            'success': True,
            'data': {
                'reference_number': '111',
                'registration_status': 2,
                'error_code': 'no error'
            }
        }
        result = can_make_digisign(self.application)
        self.assertFalse(result)
        digi_registration.refresh_from_db()
        self.assertEqual(
            digi_registration.registration_status, RegistrationStatus.WAITING_VERIFICATION
        )

        mock_get_status_req.return_value = {
            'success': True,
            'data': {
                'reference_number': '111',
                'registration_status': 1,
                'error_code': 'no error'
            }
        }
        result = can_make_digisign(self.application)
        self.assertTrue(result)
        digi_registration.refresh_from_db()
        self.assertEqual(digi_registration.registration_status, RegistrationStatus.REGISTERED)

    @patch(
        'juloserver.digisign.services.digisign_client.DigisignClient.get_registration_status_code'
    )
    @patch(
        'juloserver.digisign.services.digisign_client.DigisignClient.register'
    )
    def test_can_make_digisign_with_force(self, mock_register_req, mock_status_req):
        mock_status_req.return_value = {
            'success': False,
            'error': 'programming error'
        }
        result = can_make_digisign(self.application)
        self.assertFalse(result)

        mock_register_req.return_value = {
            'success': True,
            'data': {
                'reference_number': '111',
                'registration_status': 1,
                'error_code': 'no error'
            }
        }
        result = can_make_digisign(self.application, True)
        self.assertTrue(result)
        digi_registration = DigisignRegistration.objects.filter(
            customer_id=self.customer.id
        ).last()
        self.assertIsNotNone(digi_registration)
        self.assertEqual(digi_registration.registration_status, RegistrationStatus.REGISTERED)


class TestDigisignFee(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.suspended),
            ever_entered_B5=True,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.DIGISIGN,
            is_active=True,
            parameters={
                "digisign_fee": {
                    "signature_fee": {
                        "borrower_fee": 500,
                        "lender_fee": 1500,
                        "transaction_method_settings": [
                            {"transaction_method": 1, "is_active": True},
                            {"transaction_method": 2, "is_active": True},
                        ],
                        "minimum_loan_amount": 500_000,
                    },
                    "registration_fee": {
                        "dukcapil_check_fee": 1000,
                        "fr_check_fee": 2000,
                        "liveness_check_fee": 5000,
                    }
                },
            },
        )
        DigisignRegistrationFactory(
            customer_id=self.customer.id,
            reference_number='111',
            registration_status=RegistrationStatus.INITIATED,
            verification_results={
                'dukcapil_present': True,
                'fr_present': True,
                'liveness_present': True,
            }
        )

    def test_calc_digisign_fee(self):
        loan_amount = 500_000
        digisign_fee = calc_digisign_fee(
            loan_amount,
            TransactionMethodCode.CREDIT_CARD.code
        )
        self.assertEqual(digisign_fee, 0)

        loan_amount = 499_999
        digisign_fee = calc_digisign_fee(
            loan_amount,
            TransactionMethodCode.SELF.code
        )
        self.assertEqual(digisign_fee, 0)

        loan_amount = 500_000
        self.fs.update_safely(is_active=False)
        digisign_fee = calc_digisign_fee(
            loan_amount,
            TransactionMethodCode.SELF.code
        )
        self.assertEqual(digisign_fee, 0)

        loan_amount = 500_000
        self.fs.update_safely(is_active=True)
        digisign_fee = calc_digisign_fee(
            loan_amount,
            TransactionMethodCode.SELF.code
        )
        self.assertEqual(digisign_fee, 2000)

    def test_calc_registration_fee(self):
        dukcapil_check_fee = DigisignRegistrationFeeFactory(
            customer_id=self.customer.id,
            fee_type=DigisignFeeTypeConst.REGISTRATION_DUKCAPIL_FEE_TYPE,
            fee_amount=1000,
            extra_data={'loan_id': 1234}
        )
        fr_check_fee = DigisignRegistrationFeeFactory(
            customer_id=self.customer.id,
            fee_type=DigisignFeeTypeConst.REGISTRATION_FR_FEE_TYPE,
            fee_amount=1000,
            extra_data={'loan_id': 1234}
        )
        liveness_check_fee = DigisignRegistrationFeeFactory(
            customer_id=self.customer.id,
            fee_type=DigisignFeeTypeConst.REGISTRATION_LIVENESS_FEE_TYPE,
            fee_amount=1000,
            extra_data={'loan_id': 1234}
        )
        registration_fees = calc_registration_fee(self.application)
        total_fee = sum(registration_fees.values())
        self.assertEqual(total_fee, 0)

        dukcapil_check_fee.delete()
        registration_fees = calc_registration_fee(self.application)
        total_fee = sum(registration_fees.values())
        self.assertEqual(total_fee, 1000)

        fr_check_fee.delete()
        registration_fees = calc_registration_fee(self.application)
        total_fee = sum(registration_fees.values())
        self.assertEqual(total_fee, 3000)

        liveness_check_fee.delete()
        registration_fees = calc_registration_fee(self.application)
        total_fee = sum(registration_fees.values())
        self.assertEqual(total_fee, 8000)

    @patch('juloserver.digisign.services.common_services.can_charge_digisign_fee')
    def test_get_total_digisign_fee_happy_case(self, mock_can_charge_digisign_fee):
        mock_can_charge_digisign_fee.return_value = True

        # more than minimum for digisign
        requested_amount = 1_000_000

        # case fs is false
        self.fs.update_safely(is_active=False)
        total_fee = get_total_digisign_fee(
            app=self.application,
            requested_loan_amount=requested_amount,
            transaction_code=TransactionMethodCode.OTHER.code,
        )

        self.assertEqual(total_fee, 0)

        # case fs is true
        self.fs.update_safely(is_active=True)

        expected_total_fee = (
            self.fs.parameters['digisign_fee']['signature_fee']['borrower_fee']
            + self.fs.parameters['digisign_fee']['signature_fee']['lender_fee']
            + self.fs.parameters['digisign_fee']['registration_fee']['dukcapil_check_fee']
            + self.fs.parameters['digisign_fee']['registration_fee']['fr_check_fee']
            + self.fs.parameters['digisign_fee']['registration_fee']['liveness_check_fee']
        )
        total_fee = get_total_digisign_fee(
            app=self.application,
            requested_loan_amount=requested_amount,
            transaction_code=TransactionMethodCode.OTHER.code,
        )

        self.assertEqual(total_fee, expected_total_fee)
