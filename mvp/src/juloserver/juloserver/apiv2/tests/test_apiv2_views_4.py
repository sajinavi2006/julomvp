from __future__ import print_function

import json
from builtins import str
from unittest import mock

from django.conf import settings
from django.test import override_settings
from mock import patch
from juloserver.customer_module.tests.factories import AccountDeletionRequestFactory
from rest_framework.test import APIClient, APITestCase

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory
from juloserver.apiv2.tests.factories import PdWebModelResultFactory
from juloserver.cfs.constants import TierId
from juloserver.cfs.tests.factories import CfsTierFactory
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.exceptions import JuloException
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AppVersionFactory,
    AuthUserFactory,
    CreditScoreFactory,
    CustomerFactory,
    DocumentFactory,
    FaqItemFactory,
    FaqSectionFactory,
    FrontendViewFactory,
    JuloContactDetailFactory,
    LoanFactory,
    MobileFeatureSettingFactory,
    PartnerFactory,
    PaymentFactory,
    ProductLineFactory,
    PTPFactory,
    ReferralSystemFactory,
    SkiptraceFactory,
    SkiptraceResultChoiceFactory,
    StatusLookupFactory,
    UserFeedbackFactory,
    WorkflowFactory,
    HelpCenterSectionFactory,
    HelpCenterItemFactory,
)
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.promo.tests.factories import PromoHistoryFactory


class TestVersionCheckViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.app_version = AppVersionFactory()
        self.app_version_1 = AppVersionFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestVersionCheckViewAPIv2_version_name_required(self):
        data = {}
        response = self.client.get('/api/v2/version/check', data=data)
        assert response.status_code == 400
        assert response.json()['version_name'] == 'This field is required'

    def test_TestVersionCheckViewAPIv2_success_status_not_supported(self):
        data = {'version_name': 'test_version_name'}
        self.app_version_1.status = 'latest'
        self.app_version_1.save()

        self.app_version.status = 'not_supported'
        self.app_version.app_version = 'test_version_name'
        self.app_version.save()

        response = self.client.get('/api/v2/version/check', data=data)
        assert response.status_code == 200
        assert response.json()['content']['current_version_status'] == 'not_supported'

    def test_TestVersionCheckViewAPIv2_success_status_deprecated(self):
        data = {'version_name': 'test_version_name'}
        self.app_version_1.status = 'latest'
        self.app_version_1.save()

        self.app_version.status = 'deprecated'
        self.app_version.app_version = 'test_version_name'
        self.app_version.save()

        response = self.client.get('/api/v2/version/check', data=data)
        assert response.status_code == 200
        assert response.json()['content']['current_version_status'] == 'deprecated'

    def test_TestVersionCheckViewAPIv2_failed(self):
        data = {'version_name': 'test_version_name'}
        self.app_version_1.status = 'latest'
        self.app_version_1.save()

        self.app_version.status = 'deprecated'
        self.app_version.app_version = ''
        self.app_version.save()

        response = self.client.get('/api/v2/version/check', data=data)
        assert response.status_code == 400
        assert response.json()['error_message'] == 'app_version not found'


class TestFAQDataViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.faq_item = FaqItemFactory()
        self.faq_section = FaqSectionFactory()
        self.julo_contact_detail = JuloContactDetailFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestFAQDataViewAPIv2_get_faqitem_not_found(self):
        response = self.client.get('/api/v2/faq/123123123/')
        assert response.status_code == 400
        assert response.json()['errors'] == [u'Faq Item not found']

    def test_TestFAQDataViewAPIv2_get_success(self):
        self.faq_item.id = 123123123
        self.faq_item.save()

        response = self.client.get('/api/v2/faq/123123123/')
        assert response.status_code == 200

    def test_TestFAQDataViewAPIv2_get_assist_contact_not_found(self):
        self.julo_contact_detail.visible = False
        self.julo_contact_detail.save()

        response = self.client.get('/api/v2/faq/assist/')
        assert response.status_code == 400
        assert response.json()['errors'] == [
            u'Data Not available contact your administrator to request data'
        ]

    def test_TestFAQDataViewAPIv2_get_assist_success(self):
        self.julo_contact_detail.visible = True
        self.julo_contact_detail.save()

        response = self.client.get('/api/v2/faq/assist/')
        assert response.status_code == 200

    def test_TestFAQDataViewAPIv2_get_all_success(self):
        self.julo_contact_detail.visible = True
        self.julo_contact_detail.section = self.faq_section
        self.julo_contact_detail.save()

        response = self.client.get('/api/v2/faq/')
        assert response.status_code == 200


class TestAdditionalInfoViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.frontend_view = FrontendViewFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestAdditionalInfoViewAPIv2_success(self):
        response = self.client.get('/api/v2/additional/info/')
        assert response.status_code == 200

    @patch('juloserver.apiv2.views.AdditionalInfoSerializer')
    def test_TestAdditionalInfoViewAPIv2_failed(self, mock_additionalInfoserializer):
        mock_additionalInfoserializer.side_effect = ValueError()
        response = self.client.get('/api/v2/additional/info/')
        assert response.status_code == 400


class TestPromoInfoViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, id=123123123)
        self.promo_history = PromoHistoryFactory(customer=self.customer)
        self.loan = LoanFactory(customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestPromoInfoViewAPIv2_customer_not_found(self):
        response = self.client.get('/api/v2/promo/123123/')
        assert response.status_code == 200

    def test_TestPromoInfoViewAPIv2_promo_history_not_none(self):
        self.promo_history.promo_type = 'promo-cash-aug20.html'
        self.promo_history.loan = self.loan
        self.promo_history.save()

        response = self.client.get('/api/v2/promo/123123123/')
        assert response.status_code == 200

    def test_TestPromoInfoViewAPIv2_promo_(self):
        response = self.client.get('/api/v2/promo/123123123/')
        assert response.status_code == 200


class TestMobileFeatureSettingViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.mobile_feature_setting = MobileFeatureSettingFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestMobileFeatureSettingViewAPIv2_feature_name_required(self):
        data = {}
        response = self.client.get('/api/v2/mobile/feature-settings', data=data)
        assert response.status_code == 400
        print(response.json()['error_message'] == 'feature_name is required')

    def test_TestMobileFeatureSettingViewAPIv2_feature_not_found(self):
        data = {'feature_name': 'failover_digisign'}
        self.mobile_feature_setting.feature_name = 'test'
        self.mobile_feature_setting.save()

        response = self.client.get('/api/v2/mobile/feature-settings', data=data)
        assert response.status_code == 400
        print(response.json()['error_message'] == 'feature not found')

    def test_TestMobileFeatureSettingViewAPIv2_success(self):
        data = {'feature_name': 'failover_digisign'}
        self.mobile_feature_setting.feature_name = 'digital_signature_failover'
        self.mobile_feature_setting.save()

        response = self.client.get('/api/v2/mobile/feature-settings', data=data)
        assert response.status_code == 200

    @mock.patch("juloserver.apiv2.views.get_ongoing_account_deletion_request")
    def test_ongoing_account_deletion(self, mock_get_ongoing_account_deletion_request):
        mock_get_ongoing_account_deletion_request.return_value = AccountDeletionRequestFactory(
            customer=self.customer,
        )
        data = {'feature_name': 'autodebet_reminder_setting'}
        self.mobile_feature_setting.feature_name = 'autodebet_reminder_setting'
        self.mobile_feature_setting.save()

        response = self.client.get('/api/v2/mobile/feature-settings', data=data)
        assert response.status_code == 200
        assert response.json() == {
            'success': True,
            'content': {
                'active': False,
                'paramater': {},
            },
        }


class TestCheckPayslipMandatoryAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer, id=123123123)
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.mobile_feature_setting = MobileFeatureSettingFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestCheckPayslipMandatoryAPIv2_feature_setting_not_found(self):
        response = self.client.get('/api/v2/mobile/check-payslip-mandatory/123123123/')
        assert response.status_code == 200
        assert response.json()['is_mandatory'] == True

    @patch('juloserver.apiv2.views.check_payslip_mandatory')
    def test_TestCheckPayslipMandatoryAPIv2_check_payslip_mandatory_is_none(
        self, mock_check_payslip_mandatory
    ):
        self.mobile_feature_setting.feature_name = 'set_payslip_no_required'
        self.mobile_feature_setting.save()

        mock_check_payslip_mandatory.return_value = None
        response = self.client.get('/api/v2/mobile/check-payslip-mandatory/123123123/')
        assert response.status_code == 400
        assert response.json()['error_message'] == 'unable to check payslip mandatory'

    @patch('juloserver.apiv2.views.check_payslip_mandatory')
    def test_TestCheckPayslipMandatoryAPIv2_success(self, mock_check_payslip_mandatory):
        self.mobile_feature_setting.feature_name = 'set_payslip_no_required'
        self.mobile_feature_setting.save()

        mock_check_payslip_mandatory.return_value = True
        response = self.client.get('/api/v2/mobile/check-payslip-mandatory/123123123/')
        assert response.status_code == 200
        assert response.json()['is_mandatory'] == True


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestUpdateCenterixSkiptraceDataAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.loan = LoanFactory()
        self.payment = PaymentFactory()
        self.application = ApplicationFactory(id=123123123)
        self.skiptrace_result_choice = SkiptraceResultChoiceFactory()
        self.skiptrace = SkiptraceFactory()
        self.ptp = PTPFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestUpdateCenterixSkiptraceDataAPIv2_invalid_credentials(self):
        data = {"JuloCredUser": '', "JuloCredPassword": ''}
        response = self.client.post('/api/v2/upload/update-centerix-skiptrace-data', data=data)
        assert response.status_code == 200
        assert response.json()['ErrMessage'] == 'Invalid authentication credentials'

    def test_TestUpdateCenterixSkiptraceDataAPIv2_invalid_ptp(self):
        data = {
            "JuloCredUser": settings.CENTERIX_JULO_USER_ID,
            "JuloCredPassword": settings.CENTERIX_JULO_PASSWORD,
            "Datas": [
                {
                    "PAYMENT_ID": self.payment.id,
                    "CUSTOMER_ID": self.customer.id,
                    "APPLICATION_ID": self.application.id,
                    "LOAN_ID": self.loan.id,
                    "PHONE": "08123456789",
                    "RESULT": "test_result",
                    "SUBRESULT": 'RPC - PTP',
                    "STATUSCALL": "test_status_call",
                    "PTPDATE": "30/12/2020",
                    "CALLBACKTIME": 1,
                    "PTP": None,
                    "NOTES": "test_notes",
                    "AGENTNAME": 123,
                    "CAMPAIGN": "test_campaign",
                    "TYPEOF": "test",
                    "CENTERIXCAMPAIGN": "test",
                    "DATE": "30/12/2020",
                    "TIME": "12.59.59",
                    "DURATION": None,
                    "NONPAYMENTREASON": "test_nonpaymentreason",
                    "NONPAYMENTREASONOTHER": "test_nonpaymentreason_other",
                    "SPOKEWITH": "test_spoke_with",
                }
            ],
        }
        response = self.client.post(
            '/api/v2/upload/update-centerix-skiptrace-data',
            data=json.dumps(data),
            content_type='application/json',
        )
        assert response.status_code == 200
        assert response.json()['ErrMessage'] == 'Invalid PTP Amount/Date'

    def test_TestUpdateCenterixSkiptraceDataAPIv2_invalid_campaign(self):
        data = {
            "JuloCredUser": settings.CENTERIX_JULO_USER_ID,
            "JuloCredPassword": settings.CENTERIX_JULO_PASSWORD,
            "Datas": [
                {
                    "PAYMENT_ID": self.payment.id,
                    "CUSTOMER_ID": self.customer.id,
                    "APPLICATION_ID": self.application.id,
                    "LOAN_ID": self.loan.id,
                    "PHONE": "08123456789",
                    "RESULT": "test_result",
                    "SUBRESULT": '',
                    "STATUSCALL": "test_status_call",
                    "PTPDATE": "30/12/2020",
                    "CALLBACKTIME": 1,
                    "PTP": None,
                    "NOTES": "test_notes",
                    "AGENTNAME": 123,
                    "CAMPAIGN": "test_campaign",
                    "TYPEOF": "test",
                    "CENTERIXCAMPAIGN": "test",
                    "DATE": "30/12/2020",
                    "TIME": "12.59.59",
                    "DURATION": None,
                    "NONPAYMENTREASON": "test_nonpaymentreason",
                    "NONPAYMENTREASONOTHER": "test_nonpaymentreason_other",
                    "SPOKEWITH": "test_spoke_with",
                }
            ],
        }
        response = self.client.post(
            '/api/v2/upload/update-centerix-skiptrace-data',
            data=json.dumps(data),
            content_type='application/json',
        )
        assert response.status_code == 200
        assert response.json()['ErrMessage'] == 'Invalid campaign test_campaign'

    def test_TestUpdateCenterixSkiptraceDataAPIv2_payment_notfound(self):
        data = {
            "JuloCredUser": settings.CENTERIX_JULO_USER_ID,
            "JuloCredPassword": settings.CENTERIX_JULO_PASSWORD,
            "Datas": [
                {
                    "PAYMENT_ID": 123,
                    "CUSTOMER_ID": self.customer.id,
                    "APPLICATION_ID": self.application.id,
                    "LOAN_ID": self.loan.id,
                    "PHONE": "08123456789",
                    "RESULT": "test_result",
                    "SUBRESULT": '',
                    "STATUSCALL": "test_status_call",
                    "PTPDATE": "30/12/2020",
                    "CALLBACKTIME": 1,
                    "PTP": None,
                    "NOTES": "test_notes",
                    "AGENTNAME": 123,
                    "CAMPAIGN": 'JULO',
                    "TYPEOF": "test",
                    "CENTERIXCAMPAIGN": "test",
                    "DATE": "30/12/2020",
                    "TIME": "12.59.59",
                    "DURATION": None,
                    "NONPAYMENTREASON": "test_nonpaymentreason",
                    "NONPAYMENTREASONOTHER": "test_nonpaymentreason_other",
                    "SPOKEWITH": "test_spoke_with",
                }
            ],
        }
        response = self.client.post(
            '/api/v2/upload/update-centerix-skiptrace-data',
            data=json.dumps(data),
            content_type='application/json',
        )
        assert response.status_code == 200
        assert response.json()['ErrMessage'] == 'Not found payment for application - 123123123'

    def test_TestUpdateCenterixSkiptraceDataAPIv2_customerid_field_required(self):
        data = {
            "JuloCredUser": settings.CENTERIX_JULO_USER_ID,
            "JuloCredPassword": settings.CENTERIX_JULO_PASSWORD,
            "Datas": [
                {
                    "PAYMENT_ID": self.payment.id,
                    "CUSTOMER_ID": None,
                    "APPLICATION_ID": self.application.id,
                    "LOAN_ID": self.loan.id,
                    "PHONE": "08123456789",
                    "RESULT": "test_result",
                    "SUBRESULT": '',
                    "STATUSCALL": "test_status_call",
                    "PTPDATE": "30/12/2020",
                    "CALLBACKTIME": 1,
                    "PTP": None,
                    "NOTES": "test_notes",
                    "AGENTNAME": 123,
                    "CAMPAIGN": 'JULO',
                    "TYPEOF": "test",
                    "CENTERIXCAMPAIGN": "test",
                    "DATE": "30/12/2020",
                    "TIME": "12.59.59",
                    "DURATION": None,
                    "NONPAYMENTREASON": "test_nonpaymentreason",
                    "NONPAYMENTREASONOTHER": "test_nonpaymentreason_other",
                    "SPOKEWITH": "test_spoke_with",
                }
            ],
        }
        response = self.client.post(
            '/api/v2/upload/update-centerix-skiptrace-data',
            data=json.dumps(data),
            content_type='application/json',
        )
        assert response.status_code == 200
        assert response.json()['ErrMessage'] == 'Invalid customer details - None'

    def test_TestUpdateCenterixSkiptraceDataAPIv2_customer_not_found(self):
        data = {
            "JuloCredUser": settings.CENTERIX_JULO_USER_ID,
            "JuloCredPassword": settings.CENTERIX_JULO_PASSWORD,
            "Datas": [
                {
                    "PAYMENT_ID": self.payment.id,
                    "CUSTOMER_ID": 123,
                    "APPLICATION_ID": self.application.id,
                    "LOAN_ID": self.loan.id,
                    "PHONE": "08123456789",
                    "RESULT": "test_result",
                    "SUBRESULT": '',
                    "STATUSCALL": "test_status_call",
                    "PTPDATE": "30/12/2020",
                    "CALLBACKTIME": 1,
                    "PTP": None,
                    "NOTES": "test_notes",
                    "AGENTNAME": 123,
                    "CAMPAIGN": 'JULO',
                    "TYPEOF": "test",
                    "CENTERIXCAMPAIGN": "test",
                    "DATE": "30/12/2020",
                    "TIME": "12.59.59",
                    "DURATION": None,
                    "NONPAYMENTREASON": "test_nonpaymentreason",
                    "NONPAYMENTREASONOTHER": "test_nonpaymentreason_other",
                    "SPOKEWITH": "test_spoke_with",
                }
            ],
        }
        response = self.client.post(
            '/api/v2/upload/update-centerix-skiptrace-data',
            data=json.dumps(data),
            content_type='application/json',
        )
        assert response.status_code == 200
        assert response.json()['ErrMessage'] == 'Invalid customer details - 123'

    def test_TestUpdateCenterixSkiptraceDataAPIv2_user_not_found(self):
        data = {
            "JuloCredUser": settings.CENTERIX_JULO_USER_ID,
            "JuloCredPassword": settings.CENTERIX_JULO_PASSWORD,
            "Datas": [
                {
                    "PAYMENT_ID": self.payment.id,
                    "CUSTOMER_ID": self.customer.id,
                    "APPLICATION_ID": self.application.id,
                    "LOAN_ID": self.loan.id,
                    "PHONE": "08123456789",
                    "RESULT": "test_result",
                    "SUBRESULT": '',
                    "STATUSCALL": "test_status_call",
                    "PTPDATE": "30/12/2020",
                    "CALLBACKTIME": 1,
                    "PTP": None,
                    "NOTES": "test_notes",
                    "AGENTNAME": 'test_agent_name',
                    "CAMPAIGN": 'JULO',
                    "TYPEOF": "test",
                    "CENTERIXCAMPAIGN": "test",
                    "DATE": "30/12/2020",
                    "TIME": "12.59.59",
                    "DURATION": None,
                    "NONPAYMENTREASON": "test_nonpaymentreason",
                    "NONPAYMENTREASONOTHER": "test_nonpaymentreason_other",
                    "SPOKEWITH": "test_spoke_with",
                }
            ],
        }
        response = self.client.post(
            '/api/v2/upload/update-centerix-skiptrace-data',
            data=json.dumps(data),
            content_type='application/json',
        )
        assert response.status_code == 200
        assert response.json()['ErrMessage'] == 'Invalid agent details - test_agent_name'

    def test_TestUpdateCenterixSkiptraceDataAPIv2_skip_result_choice_not_found(self):
        data = {
            "JuloCredUser": settings.CENTERIX_JULO_USER_ID,
            "JuloCredPassword": settings.CENTERIX_JULO_PASSWORD,
            "Datas": [
                {
                    "PAYMENT_ID": self.payment.id,
                    "CUSTOMER_ID": self.customer.id,
                    "APPLICATION_ID": self.application.id,
                    "LOAN_ID": self.loan.id,
                    "PHONE": "08123456789",
                    "RESULT": 'result',
                    "SUBRESULT": 'subresult',
                    "STATUSCALL": "test_status_call",
                    "PTPDATE": "30/12/2020",
                    "CALLBACKTIME": 1,
                    "PTP": None,
                    "NOTES": "test_notes",
                    "AGENTNAME": self.user.username,
                    "CAMPAIGN": 'JULO',
                    "TYPEOF": "test",
                    "CENTERIXCAMPAIGN": "test",
                    "DATE": "30/12/2020",
                    "TIME": "12.59.59",
                    "DURATION": None,
                    "NONPAYMENTREASON": "test_nonpaymentreason",
                    "NONPAYMENTREASONOTHER": "test_nonpaymentreason_other",
                    "SPOKEWITH": "test_spoke_with",
                }
            ],
        }
        response = self.client.post(
            '/api/v2/upload/update-centerix-skiptrace-data',
            data=json.dumps(data),
            content_type='application/json',
        )
        assert response.status_code == 200
        assert response.json()['ErrMessage'] == 'Invalid SUBRESULT - subresult'

    def test_TestUpdateCenterixSkiptraceDataAPIv2_skiptrace_obj_not_found(self):
        data = {
            "JuloCredUser": settings.CENTERIX_JULO_USER_ID,
            "JuloCredPassword": settings.CENTERIX_JULO_PASSWORD,
            "Datas": [
                {
                    "PAYMENT_ID": self.payment.id,
                    "CUSTOMER_ID": self.customer.id,
                    "APPLICATION_ID": self.application.id,
                    "LOAN_ID": self.loan.id,
                    "PHONE": "08123456789",
                    "RESULT": 'result',
                    "SUBRESULT": 'subresult',
                    "STATUSCALL": "test_status_call",
                    "PTPDATE": "30/12/2020",
                    "CALLBACKTIME": 1,
                    "PTP": None,
                    "NOTES": "test_notes",
                    "AGENTNAME": self.user.username,
                    "CAMPAIGN": 'JULO',
                    "TYPEOF": "test",
                    "CENTERIXCAMPAIGN": "test",
                    "DATE": "30/12/2020",
                    "TIME": "12.59.59",
                    "DURATION": None,
                    "NONPAYMENTREASON": "test_nonpaymentreason",
                    "NONPAYMENTREASONOTHER": "test_nonpaymentreason_other",
                    "SPOKEWITH": "test_spoke_with",
                }
            ],
        }
        self.skiptrace_result_choice.name = 'subresult'
        self.skiptrace_result_choice.save()

        self.loan.application = self.application
        self.loan.save()

        self.payment.payment_status_id = 330
        self.payment.loan = self.loan
        self.payment.save()

        response = self.client.post(
            '/api/v2/upload/update-centerix-skiptrace-data',
            data=json.dumps(data),
            content_type='application/json',
        )
        assert response.status_code == 200
        assert response.json()['ErrMessage'] == 'Details updated for application - 123123123'

    def test_TestUpdateCenterixSkiptraceDataAPIv2_success(self):
        data = {
            "JuloCredUser": settings.CENTERIX_JULO_USER_ID,
            "JuloCredPassword": settings.CENTERIX_JULO_PASSWORD,
            "Datas": [
                {
                    "PAYMENT_ID": self.payment.id,
                    "CUSTOMER_ID": self.customer.id,
                    "APPLICATION_ID": self.application.id,
                    "LOAN_ID": self.loan.id,
                    "PHONE": "08123456789",
                    "RESULT": 'result',
                    "SUBRESULT": 'subresult',
                    "STATUSCALL": "test_status_call",
                    "PTPDATE": "30/12/2020",
                    "CALLBACKTIME": 1,
                    "PTP": '1',
                    "NOTES": "test_notes",
                    "AGENTNAME": self.user.username,
                    "CAMPAIGN": 'JULO',
                    "TYPEOF": "test",
                    "CENTERIXCAMPAIGN": "test",
                    "DATE": "30/12/2020",
                    "TIME": "12.59.59",
                    "DURATION": None,
                    "NONPAYMENTREASON": "test_nonpaymentreason",
                    "NONPAYMENTREASONOTHER": "test_nonpaymentreason_other",
                    "SPOKEWITH": "test_spoke_with",
                }
            ],
        }
        self.skiptrace_result_choice.name = 'subresult'
        self.skiptrace_result_choice.save()

        self.skiptrace.phone_number = format_e164_indo_phone_number('08123456789')
        self.skiptrace.customer_id = self.customer.id
        self.skiptrace.save()

        self.loan.application = self.application
        self.loan.save()

        self.payment.payment_status_id = 330
        self.payment.loan = self.loan
        self.payment.save()

        response = self.client.post(
            '/api/v2/upload/update-centerix-skiptrace-data',
            data=json.dumps(data),
            content_type='application/json',
        )
        assert response.status_code == 200
        assert response.json()['ErrMessage'] == 'Details updated for application - 123123123'


class TestTutorialSphpPopupViewAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestTutorialSphpPopupViewAPIv2_success(self):
        response = self.client.get('/api/v2/popup/sphp-tutorial')
        assert response.status_code == 200


class TestReferralHomeAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, self_referral_code='test')
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.application = ApplicationFactory(
            customer=self.customer,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            workflow=WorkflowFactory(name='JuloOneWorkflow'),
            account=self.account,
        )
        self.partner = PartnerFactory(name='julo')
        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=190), partner=self.partner
        )

        CreditScoreFactory(application_id=self.application.id, score='B+')
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.referral_system = ReferralSystemFactory(
            extra_data={
                'content': {
                    'header': '11',
                    'body': 'cashback:{} referee:{}',
                    'footer': '33',
                    'message': 'referee:{} code:{}',
                    'terms': 'cashback:{}',
                }
            }
        )
        self.first_loan = LoanFactory(
            account=self.account, application=self.application, customer=self.customer
        )
        self.first_payment = self.first_loan.payment_set.order_by('payment_number').first()
        self.first_payment.update_safely(payment_status_id=330)
        # CFS data
        self.cfs_tier = CfsTierFactory(id=TierId.STARTER, point=0, referral_bonus=2000)
        PdWebModelResultFactory(application_id=self.application.id)

    def test_TestReferralHomeAPIv2_success(self):
        self.customer.self_referral_code = 'test'
        self.customer.save()

        response = self.client.get('/api/v2/referral-home/{}/'.format(self.customer.id))
        assert response.status_code == 200

        # testcase julover
        self.referral_system.product_code.append(200)
        self.referral_system.save()
        julover_product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        julover_workflow = WorkflowFactory(name=WorkflowConst.JULOVER)
        self.application.product_line = julover_product_line
        self.application.workflow = julover_workflow
        self.application.save()
        response = self.client.get('/api/v2/referral-home/{}/'.format(self.customer.id))
        json_data = response.json()

        self.assertEqual(200, response.status_code)
        resp_data = json_data.get('data')
        self.assertIsNotNone(resp_data, json_data)
        self.assertEqual('cashback:Rp 40.000 referee:Rp 20.000', resp_data.get('body'))
        self.assertEqual('cashback:Rp 40.000', resp_data.get('terms'))

    def test_TestReferralHomeAPIv2_referral_code_empty(self):
        self.referral_system.is_active = False
        self.referral_system.save()
        response = self.client.get('/api/v2/referral-home/{}/'.format(self.customer.id))
        assert response.json()['content']['message'] == 'Mohon maaf, fitur ini sedang tidak aktif.'

    def test_TestReferralHomeAPIv2_referral_system_not_found(self):
        self.referral_system.is_active = False
        self.referral_system.save()
        self.referral_system.name = 'test'
        self.referral_system.save()

        self.customer.self_referral_code = 'test'
        self.customer.save()

        response = self.client.get('/api/v2/referral-home/{}/'.format(self.customer.id))
        assert response.json()['content']['message'] == 'Mohon maaf, fitur ini sedang tidak aktif.'


class TestUserFeedbackAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.application = ApplicationFactory(customer=self.customer, id=123123123)
        self.user_feedback = UserFeedbackFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestUserFeedbackAPIv2_application_not_found(self):
        data = {'application_id': 123123}
        response = self.client.post('/api/v2/user-feedback', data=data)
        assert response.status_code == 404
        assert response.json()['error_message'] == 'application not found'

    def test_TestUserFeedbackAPIv2_feedback_field_required(self):
        data = {'application_id': 123123123}
        response = self.client.post('/api/v2/user-feedback', data=data)
        assert response.status_code == 400
        assert response.json()['error_message'] == 'Feedback field require'

    def test_TestUserFeedbackAPIv2_rating_field_required(self):
        data = {'application_id': 123123123, 'feedback': 'test'}
        response = self.client.post('/api/v2/user-feedback', data=data)
        assert response.status_code == 400
        assert response.json()['error_message'] == 'Rating field require'

    def test_TestUserFeedbackAPIv2_user_feeback_found(self):
        data = {'application_id': 123123123, 'feedback': 'test', 'rating': 1}
        self.user_feedback.application = self.application
        self.user_feedback.save()

        response = self.client.post('/api/v2/user-feedback', data=data)
        assert response.status_code == 400
        assert response.json()['error_message'] == 'application has already given feedback'

    def test_TestUserFeedbackAPIv2_success(self):
        data = {'application_id': 123123123, 'feedback': 'test', 'rating': 1}

        response = self.client.post('/api/v2/user-feedback', data=data)
        assert response.status_code == 201


class TestSecurityFaqApiView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.faq_item = FaqItemFactory()
        self.faq_section = FaqSectionFactory()
        self.faq_section.is_security_faq = True
        self.faq_section.save()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_security_faq_item_not_found(self):
        response = self.client.get('/api/v2/security-faq/{0}/'.format(self.faq_section.id))
        assert response.status_code == 400
        assert response.json()['errors'] == [u'Security Faq items not found']

    def test_get_security_faq_item_success(self):
        self.faq_item.section = self.faq_section
        self.faq_item.save()

        response = self.client.get('/api/v2/security-faq/{0}/'.format(self.faq_section.id))
        assert response.status_code == 200

    def test_security_faq_get_all_success(self):
        self.faq_section.visible = True
        self.faq_section.save()

        self.faq_item.visible = True
        self.faq_item.section = self.faq_section
        self.faq_item.save()

        response = self.client.get('/api/v2/security-faq/')
        assert response.status_code == 200


class TestHelpCenterView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.help_center_section_1 = HelpCenterSectionFactory(
            slug="lupa-pin", visible=True, title="Lupa pin"
        )
        self.help_center_item_1 = HelpCenterItemFactory(
            section=self.help_center_section_1,
            description="its a test",
            visible=True,
        )

        self.help_center_section_2 = HelpCenterSectionFactory(
            slug="ubha-pin", visible=True, title="Ubha pin"
        )
        self.help_center_item_2 = HelpCenterItemFactory(
            section=self.help_center_section_2,
            description="Ubha pin desc 1",
            visible=True,
        )
        self.help_center_item_3 = HelpCenterItemFactory(
            section=self.help_center_section_2,
            description="Ubha pin desc",
            visible=True,
        )

    def test_help_center_success_get(self):
        response = self.client.get('/api/v2/help-center/lupa-pin/')
        self.assertEquals(response.status_code, 200)
        self.assertEquals(len(response.data.get('data')), 1)

    def test_help_center_success_get_all(self):
        response = self.client.get('/api/v2/help-center/')
        self.assertEquals(response.status_code, 200)
        self.assertEquals(len(response.data.get('data')), 2)

    def test_help_center_not_existing_slug(self):
        response = self.client.get('/api/v2/help-center/abcd/')
        self.assertEquals(response.status_code, 400)
        self.assertEquals(response.data.get('errors'), ['items not found'])

    def test_help_center_item_not_visible(self):

        self.help_center_item_2.visible = False
        self.help_center_item_2.save()

        response = self.client.get('/api/v2/help-center/ubha-pin/')
        self.assertEquals(response.status_code, 200)
        self.assertEquals(len(response.data.get('data')), 1)

        # marking both items as not visible
        self.help_center_item_3.visible = False
        self.help_center_item_3.save()

        response = self.client.get('/api/v2/help-center/ubha-pin/')
        self.assertEquals(response.status_code, 400)
        self.assertEquals(response.data.get('errors'), ['items not found'])

    def test_help_center_section_not_visible(self):
        self.help_center_section_1.visible = False
        self.help_center_section_1.save()

        response = self.client.get('/api/v2/help-center/')
        self.assertEquals(response.status_code, 200)
        self.assertEquals(len(response.data.get('data')), 1)

        # marking a section as not visible and fetch them
        self.help_center_item_1.visible = False
        self.help_center_item_1.save()
        response = self.client.get('/api/v2/help-center/lupa-pin/')
        self.assertEquals(response.status_code, 400)
        self.assertEquals(response.data.get('errors'), ['items not found'])
