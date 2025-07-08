from builtins import str
from django.test.testcases import TestCase
from django.utils import timezone
from mock import patch
from dateutil.relativedelta import relativedelta

from juloserver.julo.tests.factories import (
    LoanFactory,
    ApplicationFactory,
    FeatureSettingFactory,
    OtpRequestFactory,
    SmsHistoryFactory,
    CustomerFactory,
    StatusLookupFactory,
    LenderFactory,
    PaymentFactory,
)

from juloserver.julo.exceptions import JuloException

from ..factories import LoanRefinancingRequestFactory

from juloserver.loan_refinancing.services.offer_related import (
    determine_collection_offer_eligibility,
    check_collection_offer_eligibility,
    validate_collection_offer_otp,
    generate_or_get_active_otp,
    pass_check_refinancing_max_cap_rule_by_account_id,
    is_account_can_offered_refinancing,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.waiver.tests.factories import WaiverRequestFactory

from juloserver.julo.constants import FeatureNameConst


class TestDetermineCollectionOfferEligibility(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.application = ApplicationFactory()
        self.loan_refinancing_request = LoanRefinancingRequestFactory()

    def test_determine_collection_offer_eligibility(self):
        mock_browser_data = {
            'data_trigger_location': '',
            'browser_name': '',
            'browser_version': '',
            'os_name': '',
            'os_version': '',
            'os_version_name': '',
            'platform_type': '',
            'engine_name': ''
        }
        self.application.mobile_phone_1 = '08123123123'
        self.application.application_status_id = 180
        self.application.save()

        self.loan.application = self.application
        self.loan.loan_status_id = 211
        self.loan.application_status_id = 180
        self.loan.save()

        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.status = 'Approved'
        self.loan_refinancing_request.save()

        res = determine_collection_offer_eligibility('08123123123',mock_browser_data)
        self.assertEqual(res,(self.application,self.application.customer,True))


    def test_determine_collection_offer_eligibility_false_case(self):
        mock_browser_data = {
            'data_trigger_location': '',
            'browser_name': '',
            'browser_version': '',
            'os_name': '',
            'os_version': '',
            'os_version_name': '',
            'platform_type': '',
            'engine_name': ''
        }
        self.application.mobile_phone_1 = '08123123123'
        self.application.application_status_id = 180
        self.application.save()

        self.loan.application = self.application
        self.loan.loan_status_id = 211
        self.loan.application_status_id = 180
        self.loan.save()

        self.loan_refinancing_request.loan_id = 123123123
        self.loan_refinancing_request.status = 'Approved'
        self.loan_refinancing_request.save()

        res = determine_collection_offer_eligibility('08123123123',mock_browser_data)
        self.assertEqual(res,(self.application,None,False))
        self.loan.loan_status_id = 0
        self.loan.save()
        res = determine_collection_offer_eligibility('08123123123',mock_browser_data)
        self.assertEqual(res,(self.application,None,False))
        self.loan.application_id = 123123123
        self.loan.save()
        res = determine_collection_offer_eligibility('08123123123',mock_browser_data)
        self.assertEqual(res,(self.application,None,False))
        res = determine_collection_offer_eligibility('08111111111',mock_browser_data)
        self.assertEqual(res,(None,None,False))


class TestCheckCollectionOfferEligibility(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.application = ApplicationFactory()
        self.loan_refinancing_request = LoanRefinancingRequestFactory()
        self.feature_setting = FeatureSettingFactory()

    @patch('juloserver.loan_refinancing.services.offer_related.send_sms_otp_token')
    def test_determine_collection_offer_eligibility(self, mokc_send_sms_otp_token):
        mock_browser_data = {
            'data_trigger_location': '',
            'browser_name': '',
            'browser_version': '',
            'os_name': '',
            'os_version': '',
            'os_version_name': '',
            'platform_type': '',
            'engine_name': ''
        }
        mock_parameters = {
            'otp_wait_time_seconds': '',
            'otp_max_request': '',
            'otp_resend_time': ''
        }
        self.feature_setting.feature_name = 'collection_offer_general_website'
        self.feature_setting.is_active = True
        self.feature_setting.parameters = mock_parameters
        self.feature_setting.save()

        self.application.mobile_phone_1 = '08123123123'
        self.application.application_status_id = 180
        self.application.save()

        self.loan.application = self.application
        self.loan.loan_status_id = 211
        self.loan.application_status_id = 180
        self.loan.save()

        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.status = 'Approved'
        self.loan_refinancing_request.save()

        res = check_collection_offer_eligibility('08123123123', mock_browser_data)

    def test_determine_collection_offer_eligibility_false_case(self):
        mock_browser_data = {
            'data_trigger_location': '',
            'browser_name': '',
            'browser_version': '',
            'os_name': '',
            'os_version': '',
            'os_version_name': '',
            'platform_type': '',
            'engine_name': ''
        }
        mock_parameters = {
            'otp_wait_time_seconds': '',
            'otp_max_request': '',
            'otp_resend_time': ''
        }
        self.feature_setting.feature_name = 'collection_offer_general_website'
        self.feature_setting.is_active = False
        self.feature_setting.parameters = mock_parameters
        self.feature_setting.save()
        with self.assertRaises(JuloException) as context:
            check_collection_offer_eligibility('08123123123', mock_browser_data)
        self.assertTrue('Verifikasi kode tidak aktif' in str(context.exception))

        self.feature_setting.is_active = True
        self.feature_setting.save()
        with self.assertRaises(JuloException) as context:
            check_collection_offer_eligibility('08123123123', mock_browser_data)
        self.assertTrue('You are not eligible' in str(context.exception))


class TestValidateCollectionOfferOTP(TestCase):
    def setUp(self):
        self.otp_request = OtpRequestFactory()
        self.sms_history = SmsHistoryFactory()
        self.loan_refinancing_request = LoanRefinancingRequestFactory()
        self.application = ApplicationFactory()
        self.loan = LoanFactory()

    @patch('juloserver.loan_refinancing.services.offer_related.send_sms_notification')
    @patch('juloserver.loan_refinancing.services.offer_related.pyotp')
    def test_validate_collection_offer_otp(self, mock_pyotp, mock_task):
        self.sms_history.cdate = '2099-12-30'
        self.sms_history.save()

        self.otp_request.is_used = False
        self.otp_request.request_id += str(self.otp_request.customer_id)
        self.otp_request.sms_history = self.sms_history
        self.otp_request.application = self.application
        self.otp_request.save()

        self.loan.application = self.application
        self.loan.save()

        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.url = 'test_url'
        self.loan_refinancing_request.save()

        mock_pyotp.HTOP.return_value.verify.return_value = True
        res = validate_collection_offer_otp(self.otp_request.otp_token,
                                            self.otp_request.request_id, 0)
        self.assertEqual(res,self.loan_refinancing_request.url)

    @patch('juloserver.loan_refinancing.services.offer_related.pyotp')
    def test_validate_collection_offer_otp_false_case(self, mock_pyotp):
        self.otp_request.is_used = False
        self.otp_request.sms_history = self.sms_history
        self.otp_request.save()
        with self.assertRaises(JuloException) as context:
            validate_collection_offer_otp('test',self.otp_request.request_id,0)
        self.assertTrue('OTP not found: test' in str(context.exception))
        #
        with self.assertRaises(JuloException) as context:
            validate_collection_offer_otp(self.otp_request.otp_token,self.otp_request.request_id,0)
        self.assertTrue('request ID invalid: 555551234' in str(context.exception))
        #
        self.sms_history.cdate = '2000-12-30'
        self.sms_history.save()

        self.otp_request.request_id += str(self.otp_request.customer_id)
        self.otp_request.save()
        mock_pyotp.HTOP.return_value.verify.return_value = True
        with self.assertRaises(JuloException) as context:
            validate_collection_offer_otp(self.otp_request.otp_token,self.otp_request.request_id,0)
        self.assertTrue('OTP expired after: 0 seconds' in str(context.exception))


class TestGenerateOrGetActiveOtp(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.customer = CustomerFactory()
        self.otp_request = OtpRequestFactory()
        self.sms_history = SmsHistoryFactory()

    def test_generate_or_get_otp(self):
        self.otp_request.customer = self.customer
        self.otp_request.is_used = False
        self.otp_request.phone_number = '08222222222'
        self.otp_request.save()
        # without sms_history
        res = generate_or_get_active_otp(self.application,self.customer,'08222222222',180,1,1)
        self.assertEqual(res,(self.otp_request,True,False))
        # max request
        self.sms_history.cdate = '2099-12-30'
        self.sms_history.save()

        self.otp_request.sms_history = self.sms_history
        self.otp_request.save()
        res = generate_or_get_active_otp(self.application, self.customer, '08222222222', 180, 1, 1)
        # self.assertEqual(res, (self.otp_request, True, False))


class TestPassCheckRefinancingMaxCapRulebyAccountId(TestCase):
    def setUp(self):
        self.now = timezone.localtime(timezone.now())
        self.account = AccountFactory()
        self.loan_refinancing_request = LoanRefinancingRequestFactory(
            account=self.account,
            status='Activated',
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.REFINANCING_MAX_CAP_RULE_TRIGGER,
            parameters={'R1': True, 'R2': True, 'R3': True, 'R4': True, 'Stacked': False},
            is_active=True,
            description="Trigger setting for refinancing max cap rule",
            category='loan refinancing',
        )

    def test_offering_r1(self):
        self.loan_refinancing_request.product_type = 'R1'
        self.loan_refinancing_request.offer_activated_ts = self.now - relativedelta(months=2)
        self.loan_refinancing_request.save()
        is_passed, err_msg = pass_check_refinancing_max_cap_rule_by_account_id(self.account.id, 'r1')
        self.assertEqual(is_passed, False)
        self.assertEqual(err_msg, 'Hanya bisa digunakan sekali dalam 12 bulan terakhir')

    def test_offering_r2_r3(self):
        LoanRefinancingRequestFactory(
            account=self.account,
            status='Activated',
            offer_activated_ts=self.now - relativedelta(months=9),
            product_type='R3'
        )
        self.loan_refinancing_request.product_type = 'R2'
        self.loan_refinancing_request.offer_activated_ts = self.now - relativedelta(months=5)
        self.loan_refinancing_request.save()
        is_passed, err_msg = pass_check_refinancing_max_cap_rule_by_account_id(self.account.id, 'R2')
        self.assertEqual(is_passed, False)
        self.assertEqual(err_msg, 'Kombinasi 2 tawaran refinancing ini hanya berlaku 2 kali dalam 12 bulan terakhir')

    def test_offering_r4(self):
        WaiverRequestFactory(
            program_name="r4",
            account=self.account,
            loan_refinancing_request=self.loan_refinancing_request,
            unrounded_requested_principal_waiver_percentage=0.5
        )
        is_passed, err_msg = pass_check_refinancing_max_cap_rule_by_account_id(self.account.id, 'R4')
        self.assertEqual(is_passed, False)
        self.assertEqual(err_msg, 'Hanya dapat digunakan 1 kali selamanya untuk pelanggan dengan diskon pokok yang diberikan >= 50%')

    def test_passed(self):
        self.loan_refinancing_request.product_type = 'R2'
        self.loan_refinancing_request.offer_activated_ts = self.now - relativedelta(years=1, days=1)
        self.loan_refinancing_request.save()
        is_passed, err_msg = pass_check_refinancing_max_cap_rule_by_account_id(self.account.id, 'R2')
        self.assertEqual(is_passed, True)
        self.assertEqual(err_msg, '')


class TestAccountCanRefinancing(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.status = StatusLookupFactory(status_code=220)
        self.status_90 = StatusLookupFactory(status_code=234)
        self.lender_ska = LenderFactory(lender_name='ska')
        self.lender_bss = LenderFactory(lender_name='bss_channeling')
        self.loan = LoanFactory(
            account=self.account,
            loan_disbursement_amount=100000,
            loan_amount=105000,
        )
        self.today = timezone.localtime(timezone.now()).date()
        self.payment = PaymentFactory(
            payment_status=StatusLookupFactory(status_code=324),
            loan=self.loan,
        )

    def test_cannot_refinancing_cause_active_loan(self):
        self.loan.lender = self.lender_bss
        self.loan.loan_status=self.status
        self.loan.save()
        result = is_account_can_offered_refinancing(self.account)
        self.assertEqual(result, False)

    def test_cannot_refinancing_cause_due_still_dpd_90(self):
        self.loan.lender = self.lender_bss
        self.loan.loan_status = self.status_90
        self.loan.save()
        self.payment.due_date = self.today - relativedelta(days=90)
        self.payment.save()
        result = is_account_can_offered_refinancing(self.account)
        self.assertEqual(result, False)

    def test_can_refinancing_on_dpd_91(self):
        self.loan.lender = self.lender_bss
        self.loan.loan_status = self.status_90
        self.loan.save()
        self.payment.due_date = self.today - relativedelta(days=91)
        self.payment.save()
        result = is_account_can_offered_refinancing(self.account)
        self.assertEqual(result, True)

    def test_can_refinancing_lender_not_bss(self):
        self.loan.lender = self.lender_ska
        self.loan.save()
        result = is_account_can_offered_refinancing(self.account)
        self.assertEqual(result, True)
