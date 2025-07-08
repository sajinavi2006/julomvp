from datetime import datetime, timedelta
from unittest import mock, skip
from unittest.mock import MagicMock

from dateutil.relativedelta import relativedelta
from django.core.files.uploadedfile import InMemoryUploadedFile, SimpleUploadedFile
from django.test.testcases import TestCase
from django.utils import timezone
from mock import patch
from rest_framework.test import APIClient, APITestCase

from juloserver.account.constants import AccountLockReason
from juloserver.account.models import ExperimentGroup
from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.balance_consolidation.constants import BalanceConsolidationFeatureName
from juloserver.customer_module.constants import (
    AccountDeletionRequestStatuses,
    BankAccountCategoryConst,
    CXDocumentType,
    FailedAccountDeletionRequestStatuses,
    FeatureNameConst,
)
from juloserver.customer_module.models import CustomerDataChangeRequest
from juloserver.customer_module.tests.factories import (
    AccountDeletionRequestFactory,
    BankAccountCategoryFactory,
    BankAccountDestinationFactory,
)
from juloserver.customer_module.views.views_api_v1 import CustomerDataUploadView
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.julo.banks import BankCodes
from juloserver.julo.constants import ExperimentConst, WorkflowConst
from juloserver.julo.models import ProductLine, StatusLookup
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    AddressGeolocationFactory,
    ApplicationFactory,
    ApplicationHistoryFactory,
    ApplicationJ1Factory,
    AppVersionFactory,
    AuthUserFactory,
    BankFactory,
    CreditScoreFactory,
    CustomerFactory,
    DeviceFactory,
    ExperimentSettingFactory,
    FeatureSettingFactory,
    ImageFactory,
    LoanFactory,
    MasterAgreementTemplateFactory,
    MobileFeatureSettingFactory,
    ProductLineFactory,
    StatusLookupFactory,
    WorkflowFactory,
)
from juloserver.loyalty.constants import FeatureNameConst as LoyaltyFeatureNameConst
from juloserver.pin.models import LoginAttempt
from juloserver.pin.tests.factories import (
    CustomerPinFactory,
    LoginAttemptFactory,
    PinValidationTokenFactory,
)
from juloserver.promo.constants import FeatureNameConst as PromoFeatureNameConst
from juloserver.referral.constants import FeatureNameConst as ReferralFeatureNameConst


class TestBankDestination(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.bank = BankFactory(
            bank_code='012', bank_name='BCA', xfers_bank_code='BCA', swift_bank_code='01'
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='Pribadi', parent_category_id=1
        )
        self.bank_account_healthcare = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.HEALTHCARE,
            display_label='Healthcare',
            parent_category_id=1,
        )
        self.bank_account_balance_cons = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.BALANCE_CONSOLIDATION,
            display_label='Balance_Consolidation',
            parent_category_id=1,
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        BankAccountDestinationFactory(
            bank_account_category=self.bank_account_healthcare,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        BankAccountDestinationFactory(
            bank_account_category=self.bank_account_balance_cons,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )

    def test_get_bank(self):
        res = self.client.get('/api/customer-module/v1/bank/')
        assert res.status_code == 200

    def test_get_bank_account_category(self):
        res = self.client.get('/api/customer-module/v1/bank-account-category/')
        data = res.json()['data']
        for bank in data:
            assert bank['category'] != BankAccountCategoryConst.HEALTHCARE
        assert res.status_code == 200

    def test_get_bank_account_category_balance_cons(self):
        res = self.client.get('/api/customer-module/v1/bank-account-category/')
        data = res.json()['data']
        for bank in data:
            assert bank['category'] != BankAccountCategoryConst.BALANCE_CONSOLIDATION
        assert res.status_code == 200

    @skip('Outdated endpoint. Removed in urls.py')
    @patch('juloserver.disbursement.services.xfers.XfersService.validate')
    def test_verify_bank_account(self, mock_get_julo_xfers_service):
        data = {
            "bank_code": "BCA",
            "account_number": "19231231",
            "category_id": self.bank_account_category.id,
            "description": "new bank account",
            "customer_id": self.customer.id,
            "name_in_bank": "dudi",
        }
        mock_get_julo_xfers_service.return_value = {
            'id': 123,
            'status': 'success',
            'validated_name': 'jhon',
            'reason': 'success',
            'error_message': None,
            'account_no': '12314324',
            'bank_abbrev': 'BCA',
        }
        res = self.client.post(
            '/api/customer-module/v1/verify-bank-account', data=data, format='json'
        )
        assert res.status_code == 200


class TestCreditInfoView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.mobile_feature_setting = MobileFeatureSettingFactory(
            feature_name="limit_card_call_to_action",
            is_active=True,
            parameters={
                'bottom_left': {
                    "is_active": True,
                    "action_type": "app_deeplink",
                    "destination": "product_transfer_self",
                },
                "bottom_right": {
                    "is_active": True,
                    "action_type": "app_deeplink",
                    "destination": "aktivitaspinjaman",
                },
            },
        )

    @patch('juloserver.customer_module.views.views_api_v1.get_eta_time_for_c_score_delay')
    def test_get_bank(self, mock_get_eta_time_for_c_score_delay):
        account = AccountFactory(customer=self.application.customer)
        account.status_id = 420
        account.save()
        julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        credit_score = CreditScoreFactory(application_id=self.application.id)
        self.application.account = account
        self.application.application_status_id = 105
        self.application.workflow = julo_one_workflow
        self.application.save()
        mock_get_eta_time_for_c_score_delay.return_value = timezone.localtime(
            timezone.now()
        ) + relativedelta(days=1)
        res = self.client.get('/api/customer-module/v1/credit-info/')
        assert res.status_code == 200
        assert len(res.json()['data']['product']) != 1
        assert (
            res.json()['data']['creditInfo']['limit_message']
            == 'Pengajuan kredit JULO sedang dalam proses'
        )


class TestUserConfig(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.app_version = AppVersionFactory(status='latest', app_version='test123')
        self.j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.mtl_workflow = WorkflowFactory(name='CashLoanWorkflow')

        self.product_mtl = ProductLine.objects.get(pk=10)
        self.product_j1 = ProductLineFactory(product_line_code=1, product_line_type='J1')
        self.loan_60dpd = StatusLookup.objects.get(pk=233)
        self.loan_paid = StatusLookup.objects.get(pk=250)
        self.application_status_mtl_disbursement = StatusLookup.objects.get(pk=180)
        self.application_status_loc_approved = StatusLookup.objects.get(pk=190)
        self.application_status_document = StatusLookup.objects.get(pk=120)

    # # Julo One # #

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_user_has_pin__customer_can_reapply(self, mock_upgrade):
        self.pin = CustomerPinFactory(user=self.user)

        self.customer.can_reapply = True
        self.customer.save()

        self.application = ApplicationFactory(customer=self.customer, workflow=self.j1_workflow)

        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )

        data = response.json()['data']
        show_setup_pin = data['showSetupPin']
        use_new_ui = data['useNewUi']

        self.assertTrue(hasattr(self.user, 'pin'))
        self.assertTrue(self.customer.can_reapply)
        self.assertFalse(show_setup_pin)
        self.assertTrue(use_new_ui)

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_user_has_pin__customer_cannot_reapply(self, mock_upgrade):
        self.pin = CustomerPinFactory(user=self.user)

        self.customer.can_reapply = False
        self.customer.save()

        self.application = ApplicationFactory(customer=self.customer, workflow=self.j1_workflow)

        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )
        data = response.json()['data']
        show_setup_pin = data['showSetupPin']
        use_new_ui = data['useNewUi']
        self.assertTrue(hasattr(self.user, 'pin'))
        self.assertFalse(self.customer.can_reapply)
        self.assertFalse(show_setup_pin)
        self.assertTrue(use_new_ui)

    # # MTL ##

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_user_no_pin__customer_cannot_reapply__just_register(self, mock_upgrade):
        """
        MTL user that has no pin but cannot create new application.
        Because in the past only register and leave.

        But when logging in, application create automatically.
        """
        ApplicationFactory(
            customer=self.customer,
            workflow=self.j1_workflow,
            product_line=self.product_j1,
            application_status=self.application_status_loc_approved,
        )

        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )

        data = response.json()['data']
        show_setup_pin = data['showSetupPin']
        use_new_ui = data['useNewUi']

        self.assertFalse(hasattr(self.user, 'pin'))
        self.assertFalse(self.customer.can_reapply)
        self.assertTrue(show_setup_pin)
        self.assertTrue(use_new_ui)

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_user_no_pin__customer_cannot_reapply__running_mtl_loan(self, mock_upgrade):
        """
        MTL user that has no pin but cannot create new application.
        Because has on going MTL loan.
        """
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.mtl_workflow,
            product_line=self.product_mtl,
            application_status=self.application_status_mtl_disbursement,
        )

        self.application.application_status = self.application_status_mtl_disbursement
        self.application.save()

        LoanFactory(application=self.application, loan_status=self.loan_60dpd)

        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )

        data = response.json()['data']
        show_setup_pin = data['showSetupPin']
        use_new_ui = data['useNewUi']

        self.assertFalse(hasattr(self.user, 'pin'))
        self.assertFalse(self.customer.can_reapply)
        self.assertFalse(show_setup_pin)
        self.assertFalse(use_new_ui)

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_user_no_pin__customer_cannot_reapply__mtl_application_on_process(self, mock_upgrade):
        """
        MTL user that has no pin but cannot create new application.
        Because has on process MTL application (check from product line).
        """
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.mtl_workflow,
            product_line=self.product_mtl,
            application_status=self.application_status_document,
        )

        self.application.application_status = self.application_status_document
        self.application.save()

        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )

        data = response.json()['data']
        show_setup_pin = data['showSetupPin']
        use_new_ui = data['useNewUi']

        self.assertFalse(hasattr(self.user, 'pin'))
        self.assertFalse(self.customer.can_reapply)
        self.assertFalse(show_setup_pin)
        self.assertFalse(use_new_ui)

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_user_no_pin__customer_cannot_reapply__j1_application_on_process(self, mock_upgrade):
        """
        MTL user that has no pin and cannot create new application.
        Because has on process J1 application (check from product line).
        """
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.j1_workflow,
            product_line=self.product_j1,
            application_status=self.application_status_document,
        )

        self.application.application_status = self.application_status_document
        self.application.save()

        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )

        data = response.json()['data']
        show_setup_pin = data['showSetupPin']
        use_new_ui = data['useNewUi']

        self.assertFalse(hasattr(self.user, 'pin'))
        self.assertFalse(self.customer.can_reapply)
        self.assertTrue(show_setup_pin)
        self.assertTrue(use_new_ui)

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_user_no_pin__customer_cannot_reapply__j1_application_approved(self, mock_upgrade):
        """
        MTL user that has no pin and cannot create new application.
        Because has approved J1 application (check from product line).
        """
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.j1_workflow,
            product_line=self.product_j1,
            application_status=self.application_status_loc_approved,
        )

        self.application.application_status = self.application_status_loc_approved
        self.application.save()

        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )

        data = response.json()['data']
        show_setup_pin = data['showSetupPin']
        use_new_ui = data['useNewUi']

        self.assertFalse(hasattr(self.user, 'pin'))
        self.assertFalse(self.customer.can_reapply)
        self.assertTrue(show_setup_pin)
        self.assertTrue(use_new_ui)

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_user_no_pin__customer_cannot_reapply__running_j1_loan(self, mock_upgrade):
        """
        edge case.
        """
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.j1_workflow,
            product_line=self.product_j1,
            application_status=self.application_status_loc_approved,
        )

        self.application.application_status = self.application_status_loc_approved
        self.application.save()

        LoanFactory(application=self.application, loan_status=self.loan_60dpd)

        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )

        data = response.json()['data']
        show_setup_pin = data['showSetupPin']
        use_new_ui = data['useNewUi']

        self.assertFalse(hasattr(self.user, 'pin'))
        self.assertFalse(self.customer.can_reapply)
        self.assertTrue(show_setup_pin)
        self.assertTrue(use_new_ui)

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_user_no_pin__customer_cannot_reapply__j1_loan_finished(self, mock_upgrade):
        """
        edge case.
        """
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.j1_workflow,
            product_line=self.product_j1,
            application_status=self.application_status_loc_approved,
        )

        self.application.application_status = self.application_status_loc_approved
        self.application.save()

        LoanFactory(application=self.application, loan_status=self.loan_paid)

        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )

        data = response.json()['data']
        show_setup_pin = data['showSetupPin']
        use_new_ui = data['useNewUi']

        self.assertFalse(hasattr(self.user, 'pin'))
        self.assertFalse(self.customer.can_reapply)
        self.assertTrue(show_setup_pin)
        self.assertTrue(use_new_ui)

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_show_new_referral_default(self, mock_upgrade):
        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )
        data = response.json()['data']
        self.assertTrue(data['show_new_referral'])

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_show_new_referral_fail_case(self, mock_upgrade):
        FeatureSettingFactory(
            feature_name=ReferralFeatureNameConst.WHITELIST_NEW_REFERRAL_CUST,
            parameters={'customer_ids': [123456]},
        )
        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )
        data = response.json()['data']
        self.assertFalse(data['show_new_referral'])

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_show_new_referral_success_case(self, mock_upgrade):
        FeatureSettingFactory(
            feature_name=ReferralFeatureNameConst.WHITELIST_NEW_REFERRAL_CUST,
            parameters={'customer_ids': [self.customer.id]},
        )
        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )
        data = response.json()['data']
        self.assertTrue(data['show_new_referral'])

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_show_loyalty_fail_case(self, mock_upgrade):
        FeatureSettingFactory(
            feature_name=LoyaltyFeatureNameConst.WHITELIST_LOYALTY_CUST,
            parameters={'customer_ids': [123456]},
        )
        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )
        data = response.json()['data']
        self.assertFalse(data['show_loyalty'])

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_show_loyalty_success_case_1(self, mock_upgrade):
        # No feature setting case
        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )
        data = response.json()['data']
        self.assertTrue(data['show_loyalty'])

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_show_loyalty_success_case_2(self, mock_upgrade):
        # Has feature setting and in whitelist case
        fs = FeatureSettingFactory(
            feature_name=LoyaltyFeatureNameConst.WHITELIST_LOYALTY_CUST,
            parameters={'customer_ids': [self.customer.id]},
        )
        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )
        data = response.json()['data']
        self.assertTrue(data['show_loyalty'])

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_show_loyalty_success_case_3(self, mock_upgrade):
        # Has feature setting but is_active = False
        fs = FeatureSettingFactory(
            feature_name=LoyaltyFeatureNameConst.WHITELIST_LOYALTY_CUST,
            parameters={'customer_ids': [self.customer.id]},
            is_active=False,
        )
        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )
        data = response.json()['data']
        self.assertTrue(data['show_loyalty'])

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_show_promo_code_list_fail_case(self, mock_upgrade):
        FeatureSettingFactory(
            feature_name=PromoFeatureNameConst.PROMO_CODE_WHITELIST_CUST,
            parameters={'customer_ids': [123456789]},
        )
        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )
        data = response.json()['data']
        self.assertFalse(data['show_promo_list'])

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    def test_show_promo_code_list_success_case(self, mock_upgrade):
        FeatureSettingFactory(
            feature_name=PromoFeatureNameConst.PROMO_CODE_WHITELIST_CUST,
            parameters={'customer_ids': [self.customer.id]},
        )
        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )
        data = response.json()['data']
        self.assertTrue(data['show_promo_list'])

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    @patch('juloserver.customer_module.views.views_api_v1.get_ongoing_account_deletion_request')
    def test_not_have_ongoing_account_deletion_request(
        self, mock_get_ongoing_account_deletion_request, mock_upgrade
    ):
        mock_get_ongoing_account_deletion_request.return_value = None
        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )
        data = response.json()['data']
        self.assertFalse(data['has_ongoing_account_deletion_request'])

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    @patch('juloserver.customer_module.views.views_api_v1.get_ongoing_account_deletion_request')
    def test_ongoing_account_deletion_request(
        self, mock_get_ongoing_account_deletion_request, mock_upgrade
    ):
        deletion_request = AccountDeletionRequestFactory(
            customer=self.customer,
            request_status=AccountDeletionRequestStatuses.PENDING,
        )
        mock_get_ongoing_account_deletion_request.return_value = deletion_request
        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )
        data = response.json()['data']
        self.assertTrue(data['has_ongoing_account_deletion_request'])

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    @patch('juloserver.customer_module.views.views_api_v1.is_show_customer_data_menu')
    def test_is_show_customer_data_menu_called(self, mock_show_customer_data_menu, *args):
        mock_show_customer_data_menu.return_value = True
        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.json()['data']['show_customer_data_menu'])

    @patch(
        'juloserver.customer_module.views.views_api_v1.determine_application_for_credit_info',
        return_value=False,
    )
    @patch('juloserver.customer_module.views.views_api_v1.is_show_customer_data_menu')
    def test_is_show_customer_data_menu_error(self, mock_show_customer_data_menu, *args):
        mock_show_customer_data_menu.side_effect = Exception('error')
        response = self.client.get(
            '/api/customer-module/v1/user-config/?app_version={}'.format(
                self.app_version.app_version
            )
        )
        self.assertEqual(200, response.status_code)
        self.assertFalse(response.json()['data']['show_customer_data_menu'])


class TestCreditInfo(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        self.credit_score = CreditScoreFactory(application_id=self.application.id, score='B-')
        self.loan = LoanFactory(account=self.account)
        self.mobile_feature_setting = MobileFeatureSettingFactory(
            feature_name="limit_card_call_to_action",
            is_active=True,
            parameters={
                'bottom_left': {
                    "is_active": True,
                    "action_type": "app_deeplink",
                    "destination": "product_transfer_self",
                },
                "bottom_right": {
                    "is_active": True,
                    "action_type": "app_deeplink",
                    "destination": "aktivitaspinjaman",
                },
            },
        )

    def test_credit_info(self):
        response = self.client.get('/api/customer-module/v1/credit-info/')
        assert response.status_code == 200


class TestChangeEmail(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)

        CustomerPinFactory(user=self.customer.user)
        self.user.set_password('123456')
        self.user.save()
        self.user.refresh_from_db()

    def test_change_email_v1(self):
        data = {'email': 'newemail@gmail.com', 'pin': '123456'}
        response = self.client.post(
            '/api/customer-module/v1/change-email', data=data, format='json'
        )
        assert response.status_code == 400


class TestMasterAgreement(TestCase):
    get_url = '/api/customer-module/v1/master-agreement-template/{}'
    generate_url = '/api/customer-module/v1/submit-master-agreement/{}'

    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.customer = CustomerFactory(user=self.user)
        self.product_j1 = ProductLineFactory(product_line_code=1, product_line_type='J1')
        self.application = ApplicationFactory(
            customer=self.customer,
            product_line=self.product_j1,
        )
        self.master_agreement_template = MasterAgreementTemplateFactory()

    @patch('juloserver.customer_module.views.views_api_v1.master_agreement_template')
    def test_get_master_agreement(self, mock_template):
        mock_template.return_value = True
        response = self.client.get(self.get_url.format(self.application.id))

        assert response.status_code == 200

    def test_get_master_agreement_no_application(self):
        response = self.client.get(self.get_url.format(None))
        assert response.status_code == 404

    @patch('juloserver.customer_module.views.views_api_v1.master_agreement_template')
    def test_get_failed_get_master_agreement(self, mock_template):
        mock_template.return_value = False
        response = self.client.get(self.get_url.format(self.application.id))
        assert response.status_code == 400

    @patch('juloserver.customer_module.views.views_api_v1.master_agreement_created')
    def test_generate_master_agreement(self, mock_agreement):
        mock_agreement.return_value = True

        response = self.client.get(self.generate_url.format(self.application.id))
        assert response.status_code == 200

    def test_generate_master_agreement_no_application(self):
        response = self.client.get(self.generate_url.format(None))
        assert response.status_code == 404

    @patch('juloserver.customer_module.views.views_api_v1.master_agreement_created')
    def test_generate_failed_create_master_agreement(self, mock_agreement):
        mock_agreement.return_value = False

        response = self.client.get(self.generate_url.format(self.application.id))
        assert response.status_code == 400


class TestBankListAPI(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.bank = BankFactory(bank_code=BankCodes.PERMATA)
        self.bank.is_active = False
        self.bank.save()
        self.bca_bank = BankFactory(bank_code=BankCodes.BCA)
        self.bca_syariah_bank = BankFactory(bank_code=BankCodes.BCA_SYARIAH)

    def test_get_list_bank_active_name_without_fs(self):
        res = self.client.get('/api/customer-module/v1/list-bank-name/')
        data = res.json()['data']
        assert len(data) > 0
        assert res.status_code == 200

        # not getting the inactive bank
        list_bank_ids = [data['id'] for data in data]
        assert self.bank.pk not in list_bank_ids
        assert self.bca_bank.pk in list_bank_ids
        assert self.bca_syariah_bank.pk in list_bank_ids

    def test_get_list_bank_active_name_with_fs(self):
        FeatureSettingFactory(
            feature_name=BalanceConsolidationFeatureName.BANK_WHITELIST,
            is_active=True,
            parameters={'bank_codes': [BankCodes.PERMATA, BankCodes.BCA_SYARIAH]},
        )
        res = self.client.get('/api/customer-module/v1/list-bank-name/')
        data = res.json()['data']
        assert res.status_code == 200

        list_bank_ids = [data['id'] for data in data]
        assert self.bank.pk not in list_bank_ids
        assert self.bca_bank.pk not in list_bank_ids
        assert self.bca_syariah_bank.pk in list_bank_ids


class TestLimitTimerView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_limit = AccountLimitFactory(account=self.account, set_limit=100000)
        self.status_code = StatusLookupFactory(status_code=220)
        self.status_code_x190 = StatusLookupFactory(status_code=190)
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            application_status=self.status_code_x190,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.limit_timer_data = {
            'days_after_190': 5,
            'limit_utilization_rate': 0,
            'information': {'title': 'test', 'body': 'test'},
            'pop_up_message': {'title': 'test', 'body': 'test'},
            'countdown': 90,
            'repeat_time': 2,
        }
        self.feature_name = FeatureSettingFactory(
            feature_name=FeatureNameConst.VALIDITY_TIMER,
            parameters=self.limit_timer_data,
            is_active=True,
        )

    @patch('django.utils.timezone.now')
    def test_show_limit_timer_showing(self, moc_timezone_now):
        today = datetime(2023, 2, 14)
        moc_timezone_now.return_value = timezone.localtime(today) - timedelta(
            days=self.limit_timer_data['days_after_190']
        )
        self.history = ApplicationHistoryFactory(
            application_id=self.application.id, change_reason='Test', status_old=175, status_new=190
        )
        moc_timezone_now.return_value = today
        res = self.client.get('/api/customer-module/v1/limit-timer')
        data_expected = {
            'rest_of_countdown_days': 90,
            'information': {'body': 'test', 'title': 'test'},
            'pop_up_message': None,
        }
        self.assertEqual(res.json()['data'], data_expected)
        self.assertEqual(int(res._headers['x-cache-expiry'][1]), 1)

    @patch('django.utils.timezone.now')
    def test_show_limit_timer_not_showing(self, moc_timezone_now):
        today = datetime(2023, 2, 14)
        moc_timezone_now.return_value = timezone.localtime(today) - timedelta(
            days=self.limit_timer_data['days_after_190']
        )
        self.history = ApplicationHistoryFactory(
            application_id=self.application.id, change_reason='Test', status_old=175, status_new=190
        )
        moc_timezone_now.return_value = today
        LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_disbursement_amount=100000,
            loan_amount=105000,
            loan_status=self.status_code,
        )

        res = self.client.get('/api/customer-module/v1/limit-timer')
        self.assertEqual(res.json()['data'], None)
        self.assertEqual(int(res._headers['x-cache-expiry'][1]), 1)

    def test_show_limit_timer_not_showing_with_invalid_params(self):
        self.feature_name.parameters = None
        self.feature_name.save()

        res = self.client.get('/api/customer-module/v1/limit-timer')
        self.assertEqual(res.json()['data'], None)
        self.assertEqual(int(res._headers['x-cache-expiry'][1]), 1)


class TestCustomerAppsflyerView(TestCase):
    url = '/api/customer-module/v1/appsflyer'

    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_get_appsflyer_info(self):
        result = self.client.get(self.url)
        self.assertEqual(result.status_code, 404)

        customer = CustomerFactory(user=self.user)
        result = self.client.get(self.url)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            result.json()['data'],
            {
                "appsflyer_device_id": customer.appsflyer_device_id,
                "appsflyer_customer_id": customer.appsflyer_customer_id,
                "advertising_id": customer.advertising_id,
            },
        )

    def test_set_appsflyer_info(self):
        data = {
            "appsflyer_device_id": 'appsflyer_device_id',
            "appsflyer_customer_id": 'appsflyer_customer_id',
            "advertising_id": 'advertising_id',
        }
        result = self.client.patch(self.url, data=data)
        self.assertEqual(result.status_code, 404)

        CustomerFactory(user=self.user)
        result = self.client.patch(self.url, data=data)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            result.json()['data'],
            {
                "appsflyer_device_id": 'appsflyer_device_id',
                "appsflyer_customer_id": 'appsflyer_customer_id',
                "advertising_id": 'advertising_id',
            },
        )


@mock.patch('juloserver.customer_module.views.views_api_v1.request_account_deletion')
class TestRequestAccountDeletion(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)

        self.customer = CustomerFactory(user=self.user)
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        CustomerPinFactory(user=self.user)
        self.user.set_password('123456')
        self.user.save()
        self.user.refresh_from_db()
        pin_token = PinValidationTokenFactory(user=self.user)
        self.pin_validation_token = pin_token.access_key

        self.reason = 'Pengajuan ditolak'
        self.detail_reason = 'gak tahu nih kenapa aku ditolak terus ya, padahal sudah effort'
        self.survey_submission_uid = '6ebb30b2-a920-4acb-965c-39be489de77a'

    def test_no_pin_token(self, mock_request_account_deletion):
        data = {
            'reason': self.reason,
            'detail_reason': self.detail_reason,
        }
        response = self.client.post('/api/customer-module/v1/delete-request', data)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertIsNone(response.json()['data'])
        self.assertEqual(response.json()['errors'][0], 'pin_validation_token is required')

    def test_customer_not_exists(self, mock_request_account_deletion):
        mock_request_account_deletion.return_value = (
            None,
            FailedAccountDeletionRequestStatuses.NOT_EXISTS,
        )
        data = {
            'pin_validation_token': self.pin_validation_token,
            'survey_submission_uid': self.survey_submission_uid,
        }
        response = self.client.post('/api/customer-module/v1/delete-request', data)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertIsNone(response.json()['data'])
        self.assertEqual(response.json()['errors'][0], 'not_exists:user does not exists')

    def test_active_loans(self, mock_request_account_deletion):
        mock_request_account_deletion.return_value = (
            None,
            FailedAccountDeletionRequestStatuses.ACTIVE_LOANS,
        )
        data = {
            'pin_validation_token': self.pin_validation_token,
            'reason': self.reason,
            'detail_reason': self.detail_reason,
            'survey_submission_uid': self.survey_submission_uid,
        }
        response = self.client.post('/api/customer-module/v1/delete-request', data)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertIsNone(response.json()['data'])
        self.assertEqual(
            response.json()['errors'][0], 'active_loan:user have loans on disbursement'
        )

    def test_not_eligible(self, mock_request_account_deletion):
        mock_request_account_deletion.return_value = (
            None,
            FailedAccountDeletionRequestStatuses.ACCOUNT_NOT_ELIGIBLE,
        )
        data = {
            'pin_validation_token': self.pin_validation_token,
            'reason': self.reason,
            'detail_reason': self.detail_reason,
        }
        response = self.client.post('/api/customer-module/v1/delete-request', data)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertIsNone(response.json()['data'])
        self.assertEqual(
            response.json()['errors'][0], 'not_eligible:user is not eligible to delete account'
        )

    def test_success(self, mock_request_account_deletion):
        mock_request_account_deletion.return_value = AccountDeletionRequestFactory(), None
        data = {
            'pin_validation_token': self.pin_validation_token,
            'reason': self.reason,
            'detail_reason': self.detail_reason,
        }
        response = self.client.post('/api/customer-module/v1/delete-request', data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data'], 'success')
        self.assertEqual(response.json()['errors'], [])

    def test_detail_reason_trailing_whitespace(self, mock_request_account_deletion):
        mock_request_account_deletion.return_value = AccountDeletionRequestFactory(), None
        data = {
            'pin_validation_token': self.pin_validation_token,
            'reason': self.reason,
            'detail_reason': '                   gak tau ah  males pengen beli truk                         ',
            'survey_submission_uid': self.survey_submission_uid,
        }
        response = self.client.post('/api/customer-module/v1/delete-request', data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data'], 'success')
        self.assertEqual(response.json()['errors'], [])

    def test_invalid_survey_submission_uid(self, mock_request_account_deletion):
        mock_request_account_deletion.return_value = AccountDeletionRequestFactory(), None
        data = {
            'pin_validation_token': self.pin_validation_token,
            'reason': self.reason,
            'detail_reason': self.detail_reason,
            'survey_submission_uid': 'invalid-uid',
        }
        response = self.client.post('/api/customer-module/v1/delete-request', data)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertEqual(
            response.json()['errors'][0],
            {'survey_submission_uid': ['Silahkan isi survey terlebih dahulu']},
        )

    def test_success_with_valid_survey_submission_uid(self, mock_request_account_deletion):
        mock_request_account_deletion.return_value = AccountDeletionRequestFactory(), None
        data = {
            'pin_validation_token': self.pin_validation_token,
            'reason': self.reason,
            'detail_reason': self.detail_reason,
            'survey_submission_uid': '6ebb30b2-a920-4acb-965c-39be489de77a',
        }
        response = self.client.post('/api/customer-module/v1/delete-request', data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data'], 'success')
        self.assertEqual(response.json()['errors'], [])

    def test_success_without_reason_and_detail(self, mock_request_account_deletion):
        mock_request_account_deletion.return_value = AccountDeletionRequestFactory(), None
        data = {
            'pin_validation_token': self.pin_validation_token,
            'survey_submission_uid': '6ebb30b2-a920-4acb-965c-39be489de77a',
        }
        response = self.client.post('/api/customer-module/v1/delete-request', data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data'], 'success')
        self.assertEqual(response.json()['errors'], [])

    def test_success_with_empty_reason_and_detail(self, mock_request_account_deletion):
        mock_request_account_deletion.return_value = AccountDeletionRequestFactory(), None
        data = {
            'pin_validation_token': self.pin_validation_token,
            'reason': "",
            'detail_reason': "",
            'survey_submission_uid': '6ebb30b2-a920-4acb-965c-39be489de77a',
        }
        response = self.client.post('/api/customer-module/v1/delete-request', data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data'], 'success')
        self.assertEqual(response.json()['errors'], [])


class TestIsCustomerDeleteAllowed(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

    @mock.patch('juloserver.customer_module.views.views_api_v1.is_user_delete_allowed')
    def test_not_exists(self, mock_is_user_delete_allowed):
        mock_is_user_delete_allowed.return_value = (
            False,
            FailedAccountDeletionRequestStatuses.NOT_EXISTS,
        )

        url = '/api/customer-module/v1/delete-allowed'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertIsNone(response.json()['data'])
        self.assertEqual(response.json()['errors'][0], 'not_exists:user does not exists')

    @mock.patch('juloserver.customer_module.views.views_api_v1.is_user_delete_allowed')
    def test_active_loans(self, mock_is_user_delete_allowed):
        mock_is_user_delete_allowed.return_value = (
            False,
            FailedAccountDeletionRequestStatuses.ACTIVE_LOANS,
        )

        url = '/api/customer-module/v1/delete-allowed'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertIsNone(response.json()['data'])
        self.assertEqual(
            response.json()['errors'][0], 'active_loan:user have loans on disbursement'
        )

    @mock.patch('juloserver.customer_module.views.views_api_v1.is_user_delete_allowed')
    def test_not_eligible(self, mock_is_user_delete_allowed):
        mock_is_user_delete_allowed.return_value = (
            False,
            FailedAccountDeletionRequestStatuses.ACCOUNT_NOT_ELIGIBLE,
        )

        url = '/api/customer-module/v1/delete-allowed'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertIsNone(response.json()['data'])
        self.assertEqual(
            response.json()['errors'][0], 'not_eligible:user is not eligible to delete account'
        )

    @mock.patch('juloserver.customer_module.views.views_api_v1.is_user_delete_allowed')
    def test_allowed(self, mock_is_user_delete_allowed):
        mock_is_user_delete_allowed.return_value = True, None

        url = '/api/customer-module/v1/delete-allowed'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data'], {'delete_allowed': True})


@mock.patch('juloserver.customer_module.views.views_api_v1.get_ongoing_account_deletion_request')
class TestGetAccountDeletionRequest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()

        self.customer = CustomerFactory(user=self.user)
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

    def test_not_found(self, mock_get_ongoing_account_deletion_request):
        mock_get_ongoing_account_deletion_request.return_value = None
        response = self.client.get('/api/customer-module/v1/delete-request')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertIsNone(response.json()['data'])
        self.assertEqual(response.json()['errors'], [])

    def test_found(self, mock_get_ongoing_account_deletion_request):
        deletion_request = AccountDeletionRequestFactory(customer=self.customer)
        mock_get_ongoing_account_deletion_request.return_value = deletion_request

        response = self.client.get('/api/customer-module/v1/delete-request')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertIsNotNone(response.json()['data'])
        self.assertEqual(
            response.json()['data']['request_status'],
            deletion_request.request_status,
        )
        self.assertEqual(response.json()['errors'], [])


@mock.patch('juloserver.customer_module.views.views_api_v1.cancel_account_request_deletion')
class TestCancelAccountDeletionRequest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()

        self.customer = CustomerFactory(user=self.user)
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

    def test_failed(self, mock_cancel_account_request_deletion):
        mock_cancel_account_request_deletion.return_value = None

        response = self.client.delete('/api/customer-module/v1/delete-request')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertIsNone(response.json()['data'])
        self.assertEqual(response.json()['errors'][0], 'Failed to cancel account deletion request')

    def test_success(self, mock_cancel_account_request_deletion):
        mock_cancel_account_request_deletion.return_value = AccountFactory(customer=self.customer)

        response = self.client.delete('/api/customer-module/v1/delete-request')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data'], 'success')
        self.assertEqual(response.json()['errors'], [])


@patch('juloserver.customer_module.views.views_api_v1.CustomerDataChangeRequestSerializer')
@patch('juloserver.customer_module.views.views_api_v1.CustomerDataChangeRequestHandler')
class TestCustomerDataView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationJ1Factory()
        CustomerPinFactory(user=self.user)
        self.pin_token = PinValidationTokenFactory(user=self.user)
        self.body_data = {
            'pin_validation_token': self.pin_token.access_key,
        }
        self.user.set_password('123456')
        self.user.save()
        self.user.refresh_from_db()

        self.mock_handler = MagicMock()
        self.mock_handler.is_submitted.return_value = False
        self.mock_handler.last_approved_change_request.return_value = None
        self.mock_handler.convert_application_data_to_change_request.return_value = 'change_request'
        self.mock_handler.last_submitted_change_request.return_value = (
            'last_submitted_change_request'
        )
        self.mock_handler.get_permission_status.return_value = 'enabled'
        self.mock_handler.setting.payslip_income_multiplier = 1.0
        self.mock_handler.setting.supported_app_version_code = 2394
        self.mock_handler.setting.supported_payday_version_code = 2435

        self.mock_serializer = MagicMock()
        self.mock_serializer.data = {'customer': 'data'}
        self.mock_serializer.monthly_income_threshold.return_value = 10000

    def test_get_invalid_pin_token(self, mock_handler_class, mock_serializer_class):
        response = self.client.get('/api/customer-module/v1/customer-data/')
        self.assertEquals(400, response.status_code, response.content)

        invalid_token_body = {
            'pin_validation_token': 'invalid_token',
        }
        data, content_type = self.client._encode_data(invalid_token_body, format='json')
        response = self.client.generic(
            'GET',
            '/api/customer-module/v1/customer-data/',
            data=data,
            content_type=content_type,
        )
        self.assertEquals(401, response.status_code, response.content)

    @patch('juloserver.customer_module.views.views_api_v1.CustomerDataView.get_payday_change_data')
    def test_get_clean_data(
        self, mock_get_payday_change_data, mock_handler_class, mock_serializer_class
    ):
        mock_get_payday_change_data.return_value = None
        mock_handler_class.return_value = self.mock_handler
        mock_serializer_class.return_value = self.mock_serializer

        response = self.client.get(
            '/api/customer-module/v1/customer-data/',
            HTTP_X_PIN_TOKEN=self.pin_token.access_key,
        )
        expected_data = {
            'request_eligibility_state': 'enabled',
            'nudge_message': None,
            'validation_message': "",
            'customer_data': {'customer': 'data'},
            "form_rules": {
                "monthly_income_threshold": 10000,
            },
            "change_fields": [],
        }
        self.assertEquals(200, response.status_code, response.content)
        self.assertEquals(expected_data, response.json()['data'], response.content)

    # @patch('juloserver.julo.utils.delete_public_file_from_oss')
    # def test_get_payday_change_data_without_keep_payday(
    #     self, mock_handler_class, mock_serializer_class, mock_delete_public_file_from_oss
    # ):
    #     import json
    #     from juloserver.customer_module.views.views_api_v1 import CustomerDataView

    #     with patch(
    #         'juloserver.customer_module.views.views_api_v1.get_redis_client'
    #     ) as mock_redis_client:
    #         self.image = ImageFactory(
    #             image_type='payday_customer_change_request', image_source=self.application.id
    #         )
    #         mock_delete_public_file_from_oss.return_value = True
    #         mock_redis_client.return_value.set.return_value =
    #         mock_redis_client.return_value.get.return_value = json.dumps(
    #             {'payday_change_proof_image_id': self.image.id, 'payday': '2022-01-01'}
    #         )

    #         class_instance = CustomerDataView()

    #         customer_data = {}
    #         class_instance.get_payday_change_data('false', 1, customer_data)

    #         # Assert that the delete method was called with the correct arguments
    #         mock_redis_client.return_value.delete_key.assert_called_once_with('customer_data_payday_change_1')

    def test_get_payday_change_data_with_keep_payday(
        self, mock_handler_class, mock_serializer_class
    ):
        import json

        from juloserver.customer_module.views.views_api_v1 import CustomerDataView

        # Mock the redis client and its methods
        with patch(
            'juloserver.customer_module.views.views_api_v1.get_redis_client'
        ) as mock_get_redis_client:
            mock_redis_client = mock_get_redis_client.return_value
            mock_redis_client.get.return_value = json.dumps(
                {'payday_change_proof_image_id': '123', 'payday': '2022-01-01'}
            )

            class_instance = CustomerDataView()

            # Call the method being tested
            customer_data = {}
            class_instance.get_payday_change_data('true', 1, customer_data)

            self.assertEqual(customer_data['payday'], '2022-01-01')

    @patch('juloserver.customer_module.views.views_api_v1.CustomerDataView.get_payday_change_data')
    def test_get_clean_data_with_nudge_message(
        self, mock_get_payday_change_data, mock_handler_class, mock_serializer_class
    ):
        mock_get_payday_change_data.return_value = None
        self.mock_handler.is_submitted.return_value = True
        mock_handler_class.return_value = self.mock_handler
        mock_serializer_class.return_value = self.mock_serializer

        data, content_type = self.client._encode_data(self.body_data, format='json')
        response = self.client.generic(
            'GET',
            '/api/customer-module/v1/customer-data/',
            data=data,
            content_type=content_type,
        )
        expected_data = {
            'request_eligibility_state': 'enabled',
            'nudge_message': {
                "type": "warning",
                "message": (
                    "Perubahan data pribadi sedang diverifikasi. "
                    "Kamu akan menerima notifikasi setelah proses selesai."
                ),
                "closeable": False,
            },
            'validation_message': "",
            'customer_data': {'customer': 'data'},
            "form_rules": {
                "monthly_income_threshold": 10000,
            },
            "change_fields": [],
        }
        self.assertEquals(200, response.status_code, response.content)
        self.assertEquals(expected_data, response.json()['data'])

    def test_post_no_token(self, *args):
        response = self.client.post('/api/customer-module/v1/customer-data/')
        self.assertEquals(400, response.status_code, response.content)

        data = {
            'pin_validation_token': 'invalid_token',
        }
        response = self.client.post(
            '/api/customer-module/v1/customer-data/',
            data=data,
            format='json',
        )
        self.assertEquals(401, response.status_code, response.content)

    def test_post_not_allowed(self, mock_handler_class, *args):
        self.mock_handler.get_permission_status.return_value = 'disabled'
        mock_handler_class.return_value = self.mock_handler
        response = self.client.post(
            '/api/customer-module/v1/customer-data/',
            data=self.body_data,
            format='json',
        )
        self.assertEquals(400, response.status_code, response.content)
        self.assertEquals(
            ["Tidak dapat submit data. Silakan hubungi CS."],
            response.json()['errors'],
            response.content,
        )

    @patch(
        'juloserver.customer_module.services.customer_related.CustomerDataChangeRequestHandler.store_payday_change_from_redis_to_raw_data'
    )
    @patch('juloserver.customer_module.views.views_api_v1.CustomerDataView.get_payday_change_data')
    def test_post_allowed(
        self,
        mock_get_payday_change_data,
        mock_store_payday_change_from_redis_to_raw_data,
        mock_handler_class,
        mock_serializer_class,
    ):
        mock_get_payday_change_data.return_value = None
        mock_store_payday_change_from_redis_to_raw_data.return_value = None
        self.mock_handler.get_permission_status.return_value = 'enabled'
        self.mock_handler.create_change_request.return_value = True, CustomerDataChangeRequest(
            status='submitted',
        )
        self.mock_handler.is_submitted.return_value = True
        mock_handler_class.return_value = self.mock_handler
        mock_serializer_class.return_value = self.mock_serializer
        response = self.client.post(
            '/api/customer-module/v1/customer-data/',
            data=self.body_data,
            format='json',
        )
        self.assertEquals(201, response.status_code, response.content)
        expected_data = {
            'request_eligibility_state': 'enabled',
            'nudge_message': {
                "type": "warning",
                "message": (
                    "Perubahan data pribadi sedang diverifikasi. "
                    "Kamu akan menerima notifikasi setelah proses selesai."
                ),
                "closeable": False,
            },
            'validation_message': "",
            'customer_data': {'customer': 'data'},
            "form_rules": {
                "monthly_income_threshold": 10000,
            },
            "change_fields": [],
        }
        self.assertEquals(expected_data, response.json()['data'])


class TestCustomerProductLockView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.customer = CustomerFactory(user=self.user)
        from juloserver.julo.constants import FeatureNameConst as Fs2
        FeatureSettingFactory(
            feature_name=Fs2.SUSPEND_CHANGE_REASON_MAP_PRODUCT_LOCK_CODE,
            parameters={
            "bad_and_good_repeat_rules": "004_A",
                "bad_clcs_delinquent_fdc": "004_B",
                "bad_repayment_odin": "004_E",
                "bad_repeat_gross_rar": "004_F",
                "bad_repeat_suspend_lt50": "004_H",
                "bad_repeat_tpd40_rules": "004_C",
                "bad_repeat_tpd40_v2_rules": "004_D",
                "ftc_suspension": "004_G",
                "recession_company_name": "004_I"
            }
        )

    def test_submit_product_lock(self):
        data = {
            'product_locked_info_old': [
                {
                    'code': 1,
                    'reason_locked': AccountLockReason.INVALID_ACCOUNT_STATUS,
                },
                {
                    'code': 2,
                    'reason_locked': '004_A',
                },
            ],
            'product_locked_info_new': [
                {
                    'code': 1,
                    'reason_locked': AccountLockReason.INVALID_ACCOUNT_STATUS,
                },
            ],
        }
        response = self.client.post(
            '/api/customer-module/v1/submit-product-locked/', data=data, format='json'
        )
        self.assertIsNotNone(response.data['data']['customer_product_locked_id'])


class TestExperimentStored(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 100
        self.application.save()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.endpoint = '/api/customer-module/v1/experiment'
        self.payload = {
            "experiment": {"key": "experiment", "active": False},
            "result": {
                "in_experiment": False,
                "variation_id": 0,
                "value": "control",
                "hash_attribute": "customerId",
                "hash_value": str(self.customer.id),
                "key": "testing",
                "name": "testing",
                "bucket": 0.0,
                "passthrough": None,
            },
            'source': 'Growthbook',
            'experiment_code': ExperimentConst.BPJS_X100_EXPERIMENT,
        }
        self.experiment_setting = ExperimentSettingFactory(
            code=ExperimentConst.BPJS_X100_EXPERIMENT,
            criteria={},
            is_active=True,
        )

    def test_success_stored_data(self):
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], 'successfully')
        experiment_group = ExperimentGroup.objects.filter(
            experiment_setting=self.experiment_setting,
            application=self.application,
            customer=self.customer,
        ).last()
        self.assertIsNotNone(experiment_group)
        self.assertEqual(experiment_group.group, self.payload['result']['value'])
        self.assertEqual(experiment_group.source, 'Growthbook')

        # test with device hash_value
        android_id = '3123saeaeq'
        device = DeviceFactory(customer=self.customer, android_id=android_id)
        self.payload['result']['hash_attribute'] = 'deviceId'
        self.payload['result']['hash_value'] = android_id
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], 'successfully')
        experiment_group = ExperimentGroup.objects.filter(
            experiment_setting=self.experiment_setting,
            application=self.application,
            customer=self.customer,
        ).last()
        self.assertIsNotNone(experiment_group)
        self.assertEqual(experiment_group.group, self.payload['result']['value'])
        self.assertEqual(experiment_group.source, 'Growthbook')

    def test_failed_serializer_stored_data(self):
        self.payload['result'] = {}
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertTrue(response.status_code, 400)

    def test_failed_if_has_value_not_same_customer_id(self):
        self.payload['result']['hash_value'] = '1'
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertTrue(response.status_code, 400)

        # test with device hash_value
        android_id = '3123saeaeq'
        device_1 = DeviceFactory(customer=self.customer, android_id=android_id)
        device_2 = DeviceFactory(customer=self.customer, android_id='fake_android_id_2')
        self.payload['result']['hash_attribute'] = 'deviceId'
        self.payload['result']['hash_value'] = 'fake_id'
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, 400)


class TestCustomerGeolocation(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.login_attempt = LoginAttemptFactory(
            customer=self.customer,
            latitude=None,
            longitude=None,
            is_success=True,
            android_id='android-current-id',
        )
        self.endpoint = '/api/customer-module/v1/geolocation'
        self.payload = {'latitude': -6.175499, 'longitude': 106.820512, 'action_type': 'login'}

    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async.delay')
    @patch('juloserver.pin.tasks.trigger_login_success_signal.delay')
    def test_success_to_stored_data(
        self, mock_trigger_login_success, mock_generate_address_geolocation
    ):

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        assert mock_generate_address_geolocation.called
        login_attempt = LoginAttempt.objects.filter(customer=self.customer, is_success=True).last()
        self.assertEqual(response.json()['data']['latitude'], self.payload['latitude'])
        self.assertEqual(response.json()['data']['longitude'], self.payload['longitude'])
        self.assertEqual(login_attempt.latitude, self.payload['latitude'])
        self.assertEqual(login_attempt.longitude, self.payload['longitude'])

    @patch('juloserver.pin.tasks.trigger_login_success_signal.delay')
    def test_failed_to_stored_data(self, mock_trigger_login_success):
        self.payload['latitude'] = 0
        self.payload['longitude'] = 0
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.pin.tasks.trigger_login_success_signal.delay')
    def test_action_type_not_match_to_stored_data(self, mock_trigger_login_success):

        self.payload['action_type'] = 'register'
        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async.delay')
    @patch('juloserver.pin.tasks.trigger_login_success_signal.delay')
    def test_success_to_stored_data_with_some_case(
        self, mock_trigger_login_success, mock_generate_address_geolocation
    ):

        # without applicatoin data
        self.application.delete()
        response = self.client.post(self.endpoint, data=self.payload, format='json')

        self.assertEqual(response.status_code, 200)
        assert not mock_generate_address_geolocation.called
        login_attempt = LoginAttempt.objects.filter(customer=self.customer, is_success=True).last()
        self.assertEqual(response.json()['data']['latitude'], self.payload['latitude'])
        self.assertEqual(response.json()['data']['longitude'], self.payload['longitude'])
        self.assertEqual(login_attempt.latitude, self.payload['latitude'])
        self.assertEqual(login_attempt.longitude, self.payload['longitude'])

        # with have application data
        self.application = ApplicationFactory(customer=self.customer)
        address_geolocation = AddressGeolocationFactory(application=self.application)

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        assert not mock_generate_address_geolocation.called
        login_attempt = LoginAttempt.objects.filter(customer=self.customer, is_success=True).last()
        self.assertEqual(response.json()['data']['latitude'], self.payload['latitude'])
        self.assertEqual(response.json()['data']['longitude'], self.payload['longitude'])
        self.assertEqual(login_attempt.latitude, self.payload['latitude'])
        self.assertEqual(login_attempt.longitude, self.payload['longitude'])

    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async.delay')
    @patch('juloserver.pin.tasks.trigger_login_success_signal.delay')
    def test_success_to_stored_data_with_called_address_geolocation(
        self, mock_trigger_login_success, mock_generate_address_geolocation
    ):

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        assert mock_generate_address_geolocation.called
        login_attempt = LoginAttempt.objects.filter(customer=self.customer, is_success=True).last()
        self.assertEqual(response.json()['data']['latitude'], self.payload['latitude'])
        self.assertEqual(response.json()['data']['longitude'], self.payload['longitude'])
        self.assertEqual(login_attempt.latitude, self.payload['latitude'])
        self.assertEqual(login_attempt.longitude, self.payload['longitude'])


class TestCustomerDataUploadView(TestCase):
    """
    Test case for the CustomerDataUploadView class.

    This test case contains multiple test methods to test different scenarios of the data upload functionality.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_authenticate(user=self.user)
        self.url = '/api/customer-module/v1/upload-document/'

    def test_post_empty_input(self):
        """Test when input is empty."""
        response = self.client.post(self.url, {}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertIn('document_source', response.data['errors'][0])
        self.assertIn('document_file', response.data['errors'][0])
        self.assertIn('document_type', response.data['errors'][0])

    @patch("django.core.files.uploadhandler.MemoryFileUploadHandler.file_complete")
    def test_post_file_too_large(self, mock_file_complete):
        file_name = "test.png"
        file_content_type = "image/png"
        max_size = 6 * 1024 * 1024  # 6 MB

        mock_file_complete.return_value = InMemoryUploadedFile(
            file=b"",
            field_name=None,
            name=file_name,
            content_type=file_content_type,
            size=max_size + 1,
            charset=None,
        )

        file = SimpleUploadedFile(
            name=file_name,
            content=b"",
            content_type=file_content_type,
        )

        data = {
            'document_source': self.customer.id,
            'document_file': file,
            'document_type': CXDocumentType.PAYDAY_CHANGE_REQUEST,
        }

        response = self.client.post(self.url, data, format='multipart')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            'File is too large. Size should not exceed 5 MB',
            response.data['errors'][0]['document_file'][0],
        )
        mock_file_complete.assert_called_once()

    def test_post_invalid_document_type(self):
        """Test when document_type is invalid."""
        file_mock = MagicMock()
        file_mock.name = "test.pdf"
        file_mock.chunks.return_value = [b"Test content"]

        data = {
            'document_source': self.customer.id,
            'document_file': file_mock,
            'document_type': 'INVALID_TYPE',
        }
        response = self.client.post(self.url, data, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            'Document type not allowed', response.data['errors'][0]['document_type'][0]
        )

    def test_post_invalid_file_type(self):
        """Test when file type is invalid."""
        file_mock = MagicMock()
        file_mock.name = "test.exe"
        file_mock.chunks.return_value = [b"Test content"]

        data = {
            'document_source': self.customer.id,
            'document_file': file_mock,
            'document_type': CXDocumentType.PAYDAY_CHANGE_REQUEST,
        }
        response = self.client.post(self.url, data, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertEqual('Extension not allowed', response.data['errors'][0]['document_file'][0])

    @patch('juloserver.customer_module.views.views_api_v1.upload_file_to_oss')
    def test_post_oss_upload_failure(self, mock_upload):
        """Test when OSS upload fails."""
        mock_upload.side_effect = Exception("OSS upload failed")

        file_mock = MagicMock()
        file_mock.name = "test.pdf"
        file_mock.chunks.return_value = [b"Test content"]

        data = {
            'document_source': self.customer.id,
            'document_file': file_mock,
            'document_type': CXDocumentType.PAYDAY_CHANGE_REQUEST,
        }
        response = self.client.post(self.url, data, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertIn('Failed to process document upload', response.data['errors'][0]['error'])

    def test_post_unauthorized_user(self):
        """Test when user is not authenticated."""
        self.client.force_authenticate(user=None)
        data = {'document_file': "file.pdf", 'document_type': CXDocumentType.PAYDAY_CHANGE_REQUEST}
        response = self.client.post(self.url, data, format='multipart')
        self.assertEqual(response.status_code, 401)


class TestProcessUploadDocument(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.view = CustomerDataUploadView()

    def test_process_document_upload_successful(self):
        """
        Test case for successful document upload process.
        """
        # Create a mock file and customer
        mock_file = SimpleUploadedFile("test_file.txt", b"file_content")

        # Mock the necessary methods and objects
        with patch(
            'juloserver.customer_module.views.views_api_v1.upload_file_to_oss'
        ) as mock_upload, patch(
            'juloserver.customer_module.views.views_api_v1.CXDocument.objects.create'
        ) as mock_create:

            mock_create.return_value = MagicMock(id=1, document_url='test_url')

            # Create an instance of CustomerDataUploadView
            view = CustomerDataUploadView()

            document = view.process_document_upload(mock_file, 'test_type', self.customer.id)

        # Assertions
        self.assertIsNotNone(document)
        self.assertEqual(document.id, 1)
        self.assertEqual(document.document_url, 'test_url')
        mock_create.assert_called_once()
        mock_upload.assert_called_once()

    @patch('juloserver.customer_module.views.views_api_v1.CXDocument.objects.create')
    def test_process_document_upload_db_failure(self, mock_create):
        """Test process_document_upload when database creation fails"""
        mock_create.side_effect = Exception("Database error")
        file = SimpleUploadedFile("test.txt", b"file_content")
        with self.assertRaises(Exception):
            self.view.process_document_upload(
                file, CXDocumentType.PAYDAY_CHANGE_REQUEST, self.customer.id
            )

    def test_process_document_upload_file_close_failure(self):
        """Test process_document_upload when closing the file fails"""
        file = SimpleUploadedFile("test.txt", b"file_content")
        mock_document = MagicMock()
        mock_document.file.close.side_effect = Exception("Close failed")
        with patch(
            'juloserver.customer_module.views.views_api_v1.CXDocument.objects.create',
            return_value=mock_document,
        ):
            with self.assertRaises(Exception):
                self.view.process_document_upload(
                    file, CXDocumentType.PAYDAY_CHANGE_REQUEST, self.customer.id
                )

    def test_process_document_upload_file_delete_failure(self):
        """Test process_document_upload when deleting the local file fails"""
        file = SimpleUploadedFile("test.txt", b"file_content")
        with patch('os.remove', side_effect=OSError("Delete failed")):
            with self.assertRaises(OSError):
                self.view.process_document_upload(
                    file, CXDocumentType.PAYDAY_CHANGE_REQUEST, self.customer.id
                )

    def test_process_document_upload_file_write_failure(self):
        """Test process_document_upload when writing to local file fails"""
        file = SimpleUploadedFile("test.txt", b"file_content")
        with patch('builtins.open', side_effect=IOError("Write failed")):
            with self.assertRaises(IOError):
                self.view.process_document_upload(
                    file, CXDocumentType.PAYDAY_CHANGE_REQUEST, self.customer.id
                )

    @patch('juloserver.customer_module.views.views_api_v1.upload_file_to_oss')
    def test_process_document_upload_oss_failure(self, mock_upload):
        """Test process_document_upload when OSS upload fails"""
        mock_upload.side_effect = Exception("OSS upload failed")
        file = SimpleUploadedFile("test.txt", b"file_content")
        with self.assertRaises(Exception):
            self.view.process_document_upload(
                file, CXDocumentType.PAYDAY_CHANGE_REQUEST, self.customer.id
            )

    def test_process_document_upload_temp_dir_not_writable(self):
        """Test process_document_upload when temporary directory is not writable"""
        file = SimpleUploadedFile("test.txt", b"file_content")
        with patch('tempfile.gettempdir', return_value='/non_existent_dir'):
            with self.assertRaises(IOError):
                self.view.process_document_upload(
                    file, CXDocumentType.PAYDAY_CHANGE_REQUEST, self.customer.id
                )
