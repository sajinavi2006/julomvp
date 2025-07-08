import pytz
from datetime import datetime
from unittest import skip

from django.test.testcases import TestCase
from mock import patch
from juloserver.julo.statuses import LoanStatusCodes
from rest_framework.test import APIClient

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import (
    AccountFactory,
    CreditLimitGenerationFactory,
    AccountLimitFactory,
)
from juloserver.credit_card.constants import (
    FeatureNameConst as JuloCardFeatureNameConst,
)
from juloserver.credit_card.models import JuloCardWhitelistUser
from juloserver.credit_card.tests.factiories import JuloCardWhitelistUserFactory
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory,
)
from juloserver.disbursement.tests.factories import (
    BankNameValidationLogFactory,
    NameBankValidationFactory,
)
from juloserver.limit_validity_timer.tests.factories import LimitValidityTimerCampaignFactory
from juloserver.graduation.constants import CustomerSuspendRedisConstant
from juloserver.graduation.tests.factories import CustomerSuspendFactory, \
    CustomerSuspendHistoryFactory
from juloserver.julo.constants import (
    FeatureNameConst,
    WorkflowConst,
    ApplicationStatusCodes,
    MobileFeatureNameConst,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    BankFactory,
    CreditScoreFactory,
    CustomerFactory,
    FeatureSettingFactory,
    LoanFactory,
    MobileFeatureSettingFactory,
    PaymentMethodFactory,
    ProductLineFactory,
    WorkflowFactory,
    MasterAgreementTemplateFactory,
    ApplicationUpgradeFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    StatusLookupFactory,
    OtpRequestFactory,
    ProductLockInAppBottomSheetFSFactory,
)
from juloserver.loan.tests.factories import (
    TransactionCategoryFactory,
    TransactionMethodFactory,
)
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod
from juloserver.pin.tests.factories import (
    CustomerPinFactory,
    TemporarySessionFactory,
    PinValidationTokenFactory,
)
from juloserver.julo.models import Application
from django.utils import timezone
from datetime import timedelta


class TestCreditInfoVersion3(TestCase):
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
        self.master_agreement = MasterAgreementTemplateFactory()
        self.fake_redis = MockRedisHelper()
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
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.CFS,
            parameters={
                'faqs': {
                    'header': 'header',
                    'topics': [{'question': 'question test 1', 'answer': 'answer test 1'}],
                }
            },
        )
        FeatureSettingFactory(
            is_active=True,
            feature_name='master_agreement_setting',
        )
        self.transaction_category = TransactionCategoryFactory(fe_display_name="Belanja")
        self.transaction_method_julo_card = TransactionMethodFactory(
            id=TransactionMethodCode.CREDIT_CARD.code,
            method=TransactionMethodCode.CREDIT_CARD.name,
            transaction_category=self.transaction_category,
        )
        self.transaction_method_train_ticket = TransactionMethodFactory(
            id=TransactionMethodCode.TRAIN_TICKET.code,
            method=TransactionMethodCode.TRAIN_TICKET.name,
            transaction_category=self.transaction_category,
        )
        last_transaction_method = TransactionMethod.objects.order_by('id').last()
        for i in range(1, 11):
            TransactionMethodFactory(
                id=last_transaction_method.id + i,
                method='method test {}'.format(i),
                transaction_category=self.transaction_category,
                order_number=i,
            )
        JuloCardWhitelistUserFactory(
            application=self.account.last_application,
        )
        self.feature_setting_julo_card_whitelist = FeatureSettingFactory(
            is_active=True,
            feature_name=JuloCardFeatureNameConst.JULO_CARD_WHITELIST,
        )
        self.feature_setting_train_ticket_whitelist = MobileFeatureSettingFactory(
            is_active=True,
            feature_name=MobileFeatureNameConst.TRANSACTION_METHOD_WHITELIST,
            parameters={
                TransactionMethodCode.TRAIN_TICKET.name: {
                    "application_ids": [self.account.last_application.id]
                },
            },
        )

    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of')
    def test_credit_info(self, mock_proven_graduate):
        mock_proven_graduate.return_value = True
        response = self.client.get('/api/customer-module/v3/credit-info/')
        assert response.status_code == 200

    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of')
    def test_credit_info_whitelist_user_julo_card(self, mock_proven_graduate):
        self.transaction_method_julo_card.update_safely(order_number=1)
        mock_proven_graduate.return_value = True
        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200)
        response = response.json()
        self.assertNotEqual(
            list(
                filter(
                    lambda product: product['code'] == TransactionMethodCode.CREDIT_CARD.code,
                    response['data']['product'],
                )
            ),
            [],
        )
        belanja_category = list(
            filter(
                lambda product: product['category'] == self.transaction_category.fe_display_name,
                response['data']['all_products'],
            )
        )
        self.assertNotEqual(
            list(
                filter(
                    lambda product: product['code'] == TransactionMethodCode.CREDIT_CARD.code,
                    belanja_category[0]['product'],
                )
            ),
            [],
        )
        # exclude julo card from response product
        transaction_method = (
            TransactionMethod.objects.filter(order_number__isnull=False)
            .order_by('order_number')
            .last()
        )
        self.transaction_method_julo_card.update_safely(
            order_number=transaction_method.order_number + 10
        )
        response = self.client.get('/api/customer-module/v3/credit-info/')
        response = response.json()
        self.assertEqual(
            list(
                filter(
                    lambda product: product['code'] == TransactionMethodCode.CREDIT_CARD.code,
                    response['data']['product'],
                )
            ),
            [],
        )
        belanja_category = list(
            filter(
                lambda product: product['category'] == self.transaction_category.fe_display_name,
                response['data']['all_products'],
            )
        )
        self.assertNotEqual(
            list(
                filter(
                    lambda product: product['code'] == TransactionMethodCode.CREDIT_CARD.code,
                    belanja_category[0]['product'],
                )
            ),
            [],
        )

    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of')
    def test_credit_info_non_whitelist_user_julo_card(self, mock_proven_graduate):
        self.transaction_method_julo_card.update_safely(order_number=1)
        JuloCardWhitelistUser.objects.all().delete()
        mock_proven_graduate.return_value = True
        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        self.assertEqual(
            list(
                filter(
                    lambda product: product['code'] == TransactionMethodCode.CREDIT_CARD.code,
                    response['data']['product'],
                )
            ),
            [],
        )
        belanja_category = list(
            filter(
                lambda product: product['category'] == self.transaction_category.fe_display_name,
                response['data']['all_products'],
            )
        )
        self.assertEqual(
            list(
                filter(
                    lambda product: product['code'] == TransactionMethodCode.CREDIT_CARD.code,
                    belanja_category[0]['product'],
                )
            ),
            [],
        )

    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of')
    def test_credit_info_feature_setting_julo_card_whitelist_off(self, mock_proven_graduate):
        self.feature_setting_julo_card_whitelist.update_safely(is_active=False)
        self.transaction_method_julo_card.update_safely(order_number=1)
        JuloCardWhitelistUser.objects.all().delete()
        mock_proven_graduate.return_value = True
        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        self.assertNotEqual(
            list(
                filter(
                    lambda product: product['code'] == TransactionMethodCode.CREDIT_CARD.code,
                    response['data']['product'],
                )
            ),
            [],
        )
        belanja_category = list(
            filter(
                lambda product: product['category'] == self.transaction_category.fe_display_name,
                response['data']['all_products'],
            )
        )
        self.assertNotEqual(
            list(
                filter(
                    lambda product: product['code'] == TransactionMethodCode.CREDIT_CARD.code,
                    belanja_category[0]['product'],
                )
            ),
            [],
        )

    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of')
    def test_credit_info_whitelist_user_train_ticket(self, mock_proven_graduate):
        self.transaction_method_train_ticket.update_safely(order_number=1)
        mock_proven_graduate.return_value = True
        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200)
        response = response.json()
        self.assertNotEqual(
            list(
                filter(
                    lambda product: product['code'] == TransactionMethodCode.TRAIN_TICKET.code,
                    response['data']['product'],
                )
            ),
            [],
        )
        belanja_category = list(
            filter(
                lambda product: product['category'] == self.transaction_category.fe_display_name,
                response['data']['all_products'],
            )
        )
        self.assertNotEqual(
            list(
                filter(
                    lambda product: product['code'] == TransactionMethodCode.TRAIN_TICKET.code,
                    belanja_category[0]['product'],
                )
            ),
            [],
        )
        # exclude train ticket from response product
        transaction_method = (
            TransactionMethod.objects.filter(order_number__isnull=False)
            .order_by('order_number')
            .last()
        )
        self.transaction_method_train_ticket.update_safely(
            order_number=transaction_method.order_number + 10
        )
        response = self.client.get('/api/customer-module/v3/credit-info/')
        response = response.json()
        self.assertEqual(
            list(
                filter(
                    lambda product: product['code'] == TransactionMethodCode.TRAIN_TICKET.code,
                    response['data']['product'],
                )
            ),
            [],
        )
        belanja_category = list(
            filter(
                lambda product: product['category'] == self.transaction_category.fe_display_name,
                response['data']['all_products'],
            )
        )
        self.assertNotEqual(
            list(
                filter(
                    lambda product: product['code'] == TransactionMethodCode.TRAIN_TICKET.code,
                    belanja_category[0]['product'],
                )
            ),
            [],
        )

    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of')
    def test_credit_info_non_whitelist_user_train_ticket(self, mock_proven_graduate):
        self.transaction_method_train_ticket.update_safely(order_number=1)
        self.feature_setting_train_ticket_whitelist.update_safely(
            parameters={
                TransactionMethodCode.TRAIN_TICKET.name: {"application_ids": []},
            }
        )
        mock_proven_graduate.return_value = True
        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        self.assertEqual(
            list(
                filter(
                    lambda product: product['code'] == TransactionMethodCode.TRAIN_TICKET.code,
                    response['data']['product'],
                )
            ),
            [],
        )
        belanja_category = list(
            filter(
                lambda product: product['category'] == self.transaction_category.fe_display_name,
                response['data']['all_products'],
            )
        )
        self.assertEqual(
            list(
                filter(
                    lambda product: product['code'] == TransactionMethodCode.TRAIN_TICKET.code,
                    belanja_category[0]['product'],
                )
            ),
            [],
        )

    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of')
    def test_credit_info_feature_setting_train_ticket_whitelist_off(self, mock_proven_graduate):
        self.feature_setting_train_ticket_whitelist.update_safely(is_active=False)
        self.transaction_method_train_ticket.update_safely(order_number=1)
        mock_proven_graduate.return_value = True
        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        self.assertNotEqual(
            list(
                filter(
                    lambda product: product['code'] == TransactionMethodCode.TRAIN_TICKET.code,
                    response['data']['product'],
                )
            ),
            [],
        )
        belanja_category = list(
            filter(
                lambda product: product['category'] == self.transaction_category.fe_display_name,
                response['data']['all_products'],
            )
        )
        self.assertNotEqual(
            list(
                filter(
                    lambda product: product['code'] == TransactionMethodCode.TRAIN_TICKET.code,
                    belanja_category[0]['product'],
                )
            ),
            [],
        )

    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of')
    def test_credit_info_no_application(self, mock_proven_graduate):
        mock_proven_graduate.return_value = False
        self.account = None
        self.application = None
        self.credit_score = None
        self.loan = None

        response = self.client.get('/api/customer-module/v3/credit-info/')

        assert response.status_code == 200

    @patch.object(Application, 'is_julo_starter', return_value=True)
    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of', return_value=True)
    def test_credit_info_with_application_jturbo(self, mock_proven_graduate, is_jturbo):
        self.account_limit = AccountLimitFactory(
            account=self.account,
            set_limit=50000,
            available_limit=0,
            used_limit=0,
            latest_credit_score=self.credit_score,
        )
        self.credit_score.score = 'C'
        self.credit_score.save()

        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(len(response.json()['data']['product']), 1)

    @patch('juloserver.customer_module.views.views_api_v3.determine_js_workflow', return_value=None)
    @patch.object(Application, 'is_julo_starter', return_value=True)
    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of', return_value=True)
    def test_credit_info_with_credit_limit_application_jturbo(
        self,
        mock_proven_graduate,
        is_jturbo,
        js_workflow,
    ):
        self.credit_score.score = 'C'
        self.credit_score.save()

        # application JTurbo
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
        )
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.product_line = ProductLineFactory(product_line_code=2)
        self.application.save()

        self.application_j1 = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=1),
        )

        # create application upgrade
        self.application_upgrade = ApplicationUpgradeFactory(
            application_id=self.application_j1.id,
            application_id_first_approval=self.application.id,
            is_upgrade=1,
        )

        self.credit_matrix = CreditMatrixFactory()
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix, max_loan_amount=10000000
        )

        # create credit limit generation
        self.customer_limit_generation = CreditLimitGenerationFactory(
            account=self.account,
            application=self.application,
            credit_matrix=self.credit_matrix,
            max_limit=1000000,
            set_limit=1000000,
            log='{"simple_limit": 0, "max_limit (pre-matrix)": 0, "set_limit (pre-matrix)": 0, '
            '"limit_adjustment_factor": 0.8, "reduced_limit": 0}',
        )

        # credit limit generation for j1
        self.customer_limit_generation_j1 = CreditLimitGenerationFactory(
            account=self.account,
            application=self.application_j1,
            credit_matrix=self.credit_matrix,
            max_limit=1000000,
            set_limit=1000000,
            log='{"simple_limit": 0, "max_limit (pre-matrix)": 0, "set_limit (pre-matrix)": 0, '
            '"limit_adjustment_factor": 0.8, "reduced_limit": 0}',
        )

        self.account_limit = AccountLimitFactory(
            account=self.account,
            set_limit=1000000,
            available_limit=1000000,
            used_limit=0,
            latest_credit_score=self.credit_score,
        )

        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(len(response.json()['data']['product']), 1)
        self.assertIsNotNone(response.json()['data']['creditInfo']['credit_score'])
        self.assertIsNotNone(response.json()['data']['creditInfo']['set_limit'])
        self.assertIsNotNone(response.json()['data']['creditInfo']['available_limit'])
        self.assertEqual(response.json()['data']['creditInfo']['set_limit'], 1000000)

    @patch('juloserver.customer_module.views.views_api_v3.determine_js_workflow', return_value=None)
    @patch.object(Application, 'is_julo_starter', return_value=False)
    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of', return_value=True)
    def test_credit_info_with_credit_limit_app_limit_generation(
        self,
        mock_proven_graduate,
        is_jturbo,
        js_workflow,
    ):
        self.credit_score.score = 'C'
        self.credit_score.save()

        # application JTurbo
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED
        )
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.product_line = ProductLineFactory(product_line_code=2)
        self.application.save()

        self.application_j1 = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=1),
            account=self.account,
        )

        # create application upgrade
        self.application_upgrade = ApplicationUpgradeFactory(
            application_id=self.application_j1.id,
            application_id_first_approval=self.application.id,
            is_upgrade=1,
        )

        self.credit_matrix = CreditMatrixFactory()
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix, max_loan_amount=10000000
        )

        # create credit limit generation
        self.customer_limit_generation = CreditLimitGenerationFactory(
            account=self.account,
            application=self.application,
            credit_matrix=self.credit_matrix,
            max_limit=1000000,
            set_limit=1000000,
            log='{"simple_limit": 0, "max_limit (pre-matrix)": 0, "set_limit (pre-matrix)": 0, '
            '"limit_adjustment_factor": 0.8, "reduced_limit": 0}',
        )

        # credit limit generation for j1
        self.customer_limit_generation_j1 = CreditLimitGenerationFactory(
            account=self.account,
            application=self.application_j1,
            credit_matrix=self.credit_matrix,
            max_limit=15000000,
            set_limit=15000000,
            log='{"simple_limit": 0, "max_limit (pre-matrix)": 0, "set_limit (pre-matrix)": 0, '
            '"limit_adjustment_factor": 0.8, "reduced_limit": 0}',
        )

        self.application_j1.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )

        self.account_limit = AccountLimitFactory(
            account=self.account,
            set_limit=15000000,
            available_limit=15000000,
            used_limit=0,
            latest_credit_score=self.credit_score,
        )

        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(len(response.json()['data']['product']), 1)
        self.assertIsNotNone(response.json()['data']['creditInfo']['credit_score'])
        self.assertIsNotNone(response.json()['data']['creditInfo']['set_limit'])
        self.assertIsNotNone(response.json()['data']['creditInfo']['available_limit'])
        self.assertEqual(response.json()['data']['creditInfo']['set_limit'], 15000000)

    @patch('juloserver.customer_module.views.views_api_v3.determine_js_workflow', return_value=None)
    @patch.object(Application, 'is_julo_starter', return_value=True)
    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of', return_value=True)
    def test_credit_info_with_credit_limit_in_progress_j1(
        self,
        mock_proven_graduate,
        is_jturbo,
        js_workflow,
    ):
        self.credit_score.score = 'C'
        self.credit_score.save()

        # application JTurbo
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
        )
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.product_line = ProductLineFactory(product_line_code=2)
        self.application.save()

        self.application_j1 = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=1),
            account=self.account,
        )

        # create application upgrade
        self.application_upgrade = ApplicationUpgradeFactory(
            application_id=self.application_j1.id,
            application_id_first_approval=self.application.id,
            is_upgrade=1,
        )

        self.credit_matrix = CreditMatrixFactory()
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix, max_loan_amount=10000000
        )

        # create credit limit generation
        self.customer_limit_generation = CreditLimitGenerationFactory(
            account=self.account,
            application=self.application,
            credit_matrix=self.credit_matrix,
            max_limit=1000000,
            set_limit=1000000,
            log='{"simple_limit": 0, "max_limit (pre-matrix)": 0, "set_limit (pre-matrix)": 0, '
            '"limit_adjustment_factor": 0.8, "reduced_limit": 0}',
        )

        # credit limit generation for j1
        self.customer_limit_generation_j1 = CreditLimitGenerationFactory(
            account=self.account,
            application=self.application_j1,
            credit_matrix=self.credit_matrix,
            max_limit=300000,
            set_limit=300000,
            log='{"simple_limit": 0, "max_limit (pre-matrix)": 0, "set_limit (pre-matrix)": 0, '
            '"limit_adjustment_factor": 0.8, "reduced_limit": 0}',
        )

        self.application_j1.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
            )
        )

        self.account_limit = AccountLimitFactory(
            account=self.account,
            set_limit=300000,
            available_limit=300000,
            used_limit=0,
            latest_credit_score=self.credit_score,
        )
        loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE),
        )
        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(len(response.json()['data']['product']), 1)
        self.assertIsNotNone(response.json()['data']['creditInfo']['credit_score'])
        self.assertIsNotNone(response.json()['data']['creditInfo']['set_limit'])
        self.assertIsNotNone(response.json()['data']['creditInfo']['available_limit'])
        self.assertEqual(response.json()['data']['creditInfo']['set_limit'], 1000000)
        self.assertEqual(response.json()['data']['loan_agreement_xid'], loan.loan_xid)

        # loan is JFinancing, loan_agreement_xid should be None
        loan.transaction_method_id = TransactionMethodCode.JFINANCING.code
        loan.save()
        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['loan_agreement_xid'], None)

        loan.transaction_method_id = TransactionMethodCode.QRIS_1.code
        loan.save()
        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['loan_agreement_xid'], None)

        # loan is JFinancing, x209 => loan_agreement_xid is not None
        loan.transaction_method_id = TransactionMethodCode.JFINANCING.code
        loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.DRAFT)
        loan.save()
        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.json()['data']['loan_agreement_xid'], None)

    @patch('juloserver.customer_module.views.views_api_v3.determine_js_workflow', return_value=None)
    @patch.object(Application, 'is_julo_starter', return_value=False)
    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of', return_value=True)
    def test_credit_info_with_credit_limit_in_approved_j1(
        self,
        mock_proven_graduate,
        is_jturbo,
        js_workflow,
    ):
        self.credit_score.score = 'C'
        self.credit_score.save()

        # application JTurbo
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED
        )
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.product_line = ProductLineFactory(product_line_code=2)
        self.application.save()

        self.application_j1 = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=1),
            account=self.account,
        )

        # create application upgrade
        self.application_upgrade = ApplicationUpgradeFactory(
            application_id=self.application_j1.id,
            application_id_first_approval=self.application.id,
            is_upgrade=1,
        )

        self.credit_matrix = CreditMatrixFactory()
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix, max_loan_amount=10000000
        )

        # create credit limit generation
        self.customer_limit_generation = CreditLimitGenerationFactory(
            account=self.account,
            application=self.application,
            credit_matrix=self.credit_matrix,
            max_limit=1000000,
            set_limit=1000000,
            log='{"simple_limit": 0, "max_limit (pre-matrix)": 0, "set_limit (pre-matrix)": 0, '
            '"limit_adjustment_factor": 0.8, "reduced_limit": 0}',
        )

        # credit limit generation for j1
        self.customer_limit_generation_j1 = CreditLimitGenerationFactory(
            account=self.account,
            application=self.application_j1,
            credit_matrix=self.credit_matrix,
            max_limit=300000,
            set_limit=300000,
            log='{"simple_limit": 0, "max_limit (pre-matrix)": 0, "set_limit (pre-matrix)": 0, '
            '"limit_adjustment_factor": 0.8, "reduced_limit": 0}',
        )

        self.application_j1.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )

        self.account_limit = AccountLimitFactory(
            account=self.account,
            set_limit=1000000,
            available_limit=1000000,
            used_limit=0,
            latest_credit_score=self.credit_score,
        )

        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(len(response.json()['data']['product']), 1)
        self.assertIsNotNone(response.json()['data']['creditInfo']['credit_score'])
        self.assertIsNotNone(response.json()['data']['creditInfo']['set_limit'])
        self.assertIsNotNone(response.json()['data']['creditInfo']['available_limit'])
        self.assertEqual(response.json()['data']['creditInfo']['set_limit'], 1000000)

    @patch('juloserver.customer_module.views.views_api_v3.determine_js_workflow', return_value=None)
    @patch.object(Application, 'is_julo_starter', return_value=False)
    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of', return_value=True)
    def test_credit_info_limit_hit_with_default_product(
        self,
        mock_proven_graduate,
        is_jturbo,
        js_workflow,
    ):
        # case not have credit score
        self.credit_score.delete()

        # application JTurbo
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED
        )
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.product_line = ProductLineFactory(product_line_code=2)
        self.application.save()

        self.application_j1 = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=1),
            account=self.account,
        )

        self.application_j1.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_CREATED)
        )

        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(len(response.json()['data']['product']), 1)


    @patch('juloserver.customer_module.views.views_api_v3.determine_js_workflow', return_value=None)
    @patch.object(Application, 'is_julo_starter', return_value=False)
    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of', return_value=True)
    def test_credit_info_limit_with_pdam_app_version_is_lock(
            self,
            mock_proven_graduate,
            is_jturbo,
            js_workflow,
    ):
        # case not have credit score
        self.credit_score.delete()

        # application JTurbo
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED
        )
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.product_line = ProductLineFactory(product_line_code=2)
        self.application.save()

        self.application_j1 = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=1),
            account=self.account,
        )

        self.application_j1.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_CREATED)
        )
        self.status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account.update_safely(
            app_version='6.3.0',
            status=self.status_code
        )
        MobileFeatureSettingFactory(
            feature_name='julo_one_product_lock',
            parameters={
                "pdam": {
                    "app_version": "6.4.0",
                    "locked": True
                }, },
        )
        # pdam product lock by mobile feature setting
        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200)

        pdam_product = [
            i for i in response.json()['data']['product']
            if i['code'] == TransactionMethodCode.PDAM.code
        ][0]
        self.assertTrue(pdam_product['is_locked'])
        self.assertEqual(pdam_product['reason_locked'], '005')

    @patch('juloserver.customer_module.views.views_api_v3.determine_js_workflow', return_value=None)
    @patch.object(Application, 'is_julo_starter', return_value=False)
    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of', return_value=True)
    def test_credit_info_limit_with_pdam_app_version_is_unlock(
            self,
            mock_proven_graduate,
            is_jturbo,
            js_workflow,
    ):
        # case not have credit score
        self.credit_score.delete()

        # application JTurbo
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED
        )
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.product_line = ProductLineFactory(product_line_code=2)
        self.application.save()

        self.application_j1 = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=1),
            account=self.account,
        )

        self.application_j1.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_CREATED)
        )
        self.status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account.update_safely(
            app_version='6.5.0',
            status=self.status_code
        )
        MobileFeatureSettingFactory(
            feature_name='julo_one_product_lock',
            parameters={
                "pdam": {
                    "app_version": "1.2.0",
                    "locked": True
                }, },
        )
        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200)

        res_products = response.json()['data']['product']
        self.assertTrue(all(item['is_locked'] == False for item in res_products))

        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200)
        pdam_product = [
            i for i in response.json()['data']['product']
            if i['code'] == TransactionMethodCode.PDAM.code
        ][0]
        self.assertFalse(pdam_product['is_locked'])

    @patch('juloserver.customer_module.views.views_api_v3.determine_js_workflow', return_value=None)
    @patch.object(Application, 'is_julo_starter', return_value=False)
    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of', return_value=True)
    def test_credit_info_limit_with_pdam_app_version_ios_is_lock(
            self,
            mock_proven_graduate,
            is_jturbo,
            js_workflow,
    ):
        # case not have credit score
        self.credit_score.delete()

        # application JTurbo
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED
        )
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.product_line = ProductLineFactory(product_line_code=2)
        self.application.save()

        self.application_j1 = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=1),
            account=self.account,
        )

        self.application_j1.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_CREATED)
        )
        self.status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account.update_safely(app_version='1.1.1', status=self.status_code)
        MobileFeatureSettingFactory(
            feature_name='julo_one_product_lock',
            parameters={
                "pdam": {
                    "ios_app_version": "6.4.0",
                    "locked": True
                }, },
        )
        # pdam product lock by mobile feature setting
        ios_header = {
            "HTTP_X_DEVICE_ID": "E78E234E-4981-4BB7-833B-2B6CEC2F56DF",
            "HTTP_X_PLATFORM": "iOS",
            "HTTP_X_PLATFORM_VERSION": '18.1',
            "HTTP_X_APP_VERSION": '6.3.0',
        }
        response = self.client.get('/api/customer-module/v3/credit-info/', **ios_header)
        self.assertEqual(response.status_code, 200)

        pdam_product = [
            i for i in response.json()['data']['product']
            if i['code'] == TransactionMethodCode.PDAM.code
        ][0]
        self.assertTrue(pdam_product['is_locked'])
        self.assertEqual(pdam_product['reason_locked'], '005')

    @patch('juloserver.customer_module.views.views_api_v3.determine_js_workflow', return_value=None)
    @patch.object(Application, 'is_julo_starter', return_value=False)
    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of', return_value=True)
    def test_credit_info_limit_with_pdam_app_version_ios_is_unlock(
            self,
            mock_proven_graduate,
            is_jturbo,
            js_workflow,
    ):
        # case not have credit score
        self.credit_score.delete()

        # application JTurbo
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED
        )
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.product_line = ProductLineFactory(product_line_code=2)
        self.application.save()

        self.application_j1 = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=1),
            account=self.account,
        )

        self.application_j1.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_CREATED)
        )
        self.status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account.update_safely(app_version='1.1.1', status=self.status_code)
        MobileFeatureSettingFactory(
            feature_name='julo_one_product_lock',
            parameters={
                "pdam": {
                    "ios_app_version": "1.2.0",
                    "locked": True
                }, },
        )
        # pdam product lock by mobile feature setting
        ios_header = {
            "HTTP_X_DEVICE_ID": "E78E234E-4981-4BB7-833B-2B6CEC2F56DF",
            "HTTP_X_PLATFORM": "iOS",
            "HTTP_X_PLATFORM_VERSION": '18.1',
            "HTTP_X_APP_VERSION": '6.3.0',
        }
        response = self.client.get('/api/customer-module/v3/credit-info/', **ios_header)
        self.assertEqual(response.status_code, 200)

        pdam_product = [
            i for i in response.json()['data']['product']
            if i['code'] == TransactionMethodCode.PDAM.code
        ][0]
        self.assertFalse(pdam_product['is_locked'])


    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of')
    @patch('juloserver.graduation.services.get_redis_client')
    def test_credit_info_with_customer_suspend(
        self,
        mock_get_redis_client,
        mock_proven_graduate,
    ):
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
        mock_get_redis_client.return_value = self.fake_redis
        mock_proven_graduate.return_value = True
        CustomerSuspendFactory(customer_id=self.customer.id)
        CustomerSuspendHistoryFactory(
            customer_id=self.customer.id, change_reason='bad_and_good_repeat_rules'
        )
        ProductLockInAppBottomSheetFSFactory()
        # application JTurbo
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_UPGRADE_ACCEPTED
        )
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.product_line = ProductLineFactory(product_line_code=2)
        self.application.save()
        self.account.status_id = AccountConstant.STATUS_CODE.active
        self.account.save()
        self.application_j1 = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=1),
            account=self.account,
        )

        self.application_j1.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_CREATED)
        )
        customer_suspend_key = CustomerSuspendRedisConstant.CUSTOMER_SUSPEND.format(
            self.customer.id
        )
        self.assertEquals(self.fake_redis.get(customer_suspend_key), None)
        response = self.client.get('/api/customer-module/v3/credit-info/')
        self.assertEqual(response.status_code, 200)
        # default = semua product
        products = response.json()['data']['product']
        self.assertNotEqual(len(products), 1)
        for product in products:
            if product['code'] == -3:  # semua product
                continue
            self.assertTrue(product['is_locked'])
            self.assertEqual(product['reason_locked'], '004_A')
            self.assertEqual(product['lock_in_app_bottom_sheet'], {
                'body': 'Kamu terdeteksi telat membayar tagihan di JULO dan aplikasi lainnya. \n'
                        'Lunasi tagihan di JULO dan aplikasi lainnya dan tunggu maks. '
                        '30 hari agar bisa mulai transaksi lagi, ya!',
                'title': 'Kamu Belum Bisa Transaksi',
                'button': 'Mengerti'
            })
        self.assertEquals(self.fake_redis.get(customer_suspend_key), '004_A')

    @patch('juloserver.customer_module.views.views_api_v3.is_graduate_of', return_value=True)
    def test_customer_capped_limit(self, mock_graduate):
        capped_limit = 8000000

        self.application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.application.is_kin_approved = 0
        self.application.onboarding_id = 9
        self.application.save()
        self.application.refresh_from_db()

        self.customer.update_safely(customer_capped_limit=capped_limit, refresh=True)

        response = self.client.get('/api/customer-module/v3/credit-info/')
        data = response.json()['data']
        self.assertEqual(data['customer_capped_limit'], capped_limit)


class TestBankAccountDestinationEcommerce(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        self.bank = BankFactory(
            bank_code='012', bank_name='BCA', xfers_bank_code='BCA', swift_bank_code='01'
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='ecommerce', parent_category_id=1
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
            description='tokopedia',
        )

    def test_create_bank_account_destination(self):
        session = TemporarySessionFactory(user=self.user)
        data = {
            "session_token": session.access_key,
            "bank_code": "BCA",
            "account_number": "12345",
            "category_id": self.bank_account_category.id,
            "customer_id": self.customer.id,
            "name_in_bank": "budi",
            "validated_id": 8699,
            "reason": "success",
        }

        BankNameValidationLogFactory(
            validation_id=data["validated_id"],
            validation_status="SUCCESS",
            validated_name=data['name_in_bank'],
            account_number=data["account_number"],
            method="Xfers",
            application=self.application,
            reason=data["reason"],
        )

        # valid token
        res = self.client.post(
            '/api/customer-module/v3/bank-account-destination', data=data, format='json'
        )
        session.refresh_from_db()
        assert res.status_code == 200
        assert session.is_locked == True

        # invalid token
        data['session_token'] = 'failed_token'
        res = self.client.post(
            '/api/customer-module/v3/bank-account-destination', data=data, format='json'
        )
        assert res.status_code == 403

    def test_create_bank_account_destination_with_invalid_validated_id(self):
        session = TemporarySessionFactory(user=self.user)
        data = {
            "session_token": session.access_key,
            "bank_code": "BCA",
            "account_number": "12345",
            "category_id": self.bank_account_category.id,
            "customer_id": self.customer.id,
            "name_in_bank": "budi",
            "validated_id": "this is random validated_id",
            "reason": "success",
        }

        # valid token
        res = self.client.post(
            '/api/customer-module/v3/bank-account-destination', data=data, format='json'
        )
        session.refresh_from_db()
        assert res.status_code == 400
        assert res.json()['errors'] == ['id validasi tidak valid']


class TestVerifyAccountDestination(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        self.bank = BankFactory(
            bank_code='012', bank_name='BCA', xfers_bank_code='BCA', swift_bank_code='01'
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='ecommerce', parent_category_id=1
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
            description='tokopedia',
        )
        self.loan = LoanFactory(customer=self.customer, account=self.account)
        self.payment_method = PaymentMethodFactory(
            customer=self.customer, virtual_account='12345', loan=self.loan
        )

    @skip('Outdated endpoint. Removed in urls.py')
    @patch('juloserver.customer_module.views.views_api_v2.XfersService')
    @patch('juloserver.pin.decorators.pin_services.send_sms_otp')
    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    def test_verify_bank_account_destination(
        self, mock_validate_login_otp, mock_send_sms_otp, mock_xfer_service
    ):
        data = {
            "ecommerce_id": "BCA",
            "description": "nothing",
            "category_id": self.bank_account_category.id,
            "bank_code": "BCA",
            "account_number": "12345",
            "customer_id": self.customer.id,
        }
        # no otp token
        application = ApplicationFactory(customer=self.customer)
        application.application_status_id = 120
        application.save()
        msf = MobileFeatureSettingFactory(
            feature_name='mobile_phone_1_otp',
            parameters={'wait_time_seconds': 400, 'otp_max_request': 3, 'otp_resend_time': 180},
        )
        mock_xfer_service().validate.return_value = {
            'reason': 'SUCCESS',
            'validated_name': 'BCA',
            'account_no': '11111',
            'bank_abbrev': 'BCA',
            'id': '11111111111',
            'status': 'success',
        }
        res = self.client.post('/api/customer-module/v3/verify-bank-account', data=data)
        mock_send_sms_otp.assert_called()
        assert res.status_code == 203

        # inlcude with otp token
        data['otp_token'] = '123123'
        mock_validate_login_otp.return_value = True, ''
        res = self.client.post(
            '/api/customer-module/v3/verify-bank-account', data=data, format='json'
        )
        session_token = res.json()['data'].get('session_token')
        assert res.status_code == 209
        assert session_token

        # include_with_session_token
        data['session_token'] = session_token
        res = self.client.post(
            '/api/customer-module/v3/verify-bank-account', data=data, format='json'
        )
        assert res.status_code, 200


class TestPreventAddExistingBankAccount(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        loan = LoanFactory()
        self.payment_method = PaymentMethodFactory(loan=loan, customer=self.customer)
        self.bank = BankFactory(
            bank_code='012', bank_name='BCA', xfers_bank_code='BCA', swift_bank_code='01'
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='ecommerce', parent_category_id=1
        )

    @skip('Outdated endpoint. Removed in urls.py')
    @patch('juloserver.pin.decorators.pin_services.validate_login_otp')
    def test_prevent_add_existing_bank_account(self, mock_validate_login_otp):
        data = {
            "ecommerce_id": "BCA",
            "description": "nothing",
            "category_id": self.bank_account_category.id,
            "bank_code": "BCA",
            "account_number": "12345",
            "customer_id": self.customer.id,
        }

        # inlcude with otp token
        mock_validate_login_otp.return_value = True, ''
        res = self.client.post(
            '/api/customer-module/v3/verify-bank-account', data=data, format='json'
        )
        session_token = res.json()['data'].get('session_token')
        assert res.status_code == 209
        assert session_token

        data = {
            'account_number': '123456789',
            'id': '11111111111',
            'session_token': session_token,
            "bank_code": "BCA",
            "customer_id": self.customer.id,
        }
        res = self.client.post(
            '/api/customer-module/v3/verify-bank-account', data=data, format='json'
        )
        assert res.status_code == 417


class TestChangePhoneNumber(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.user.set_password('123456')
        self.user.save()
        self.pin = CustomerPinFactory(user=self.user)
        self.user1 = AuthUserFactory()

        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user, phone='1234567890')
        self.customer1 = CustomerFactory(user=self.user1, phone='9876543210')
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.otp_settings = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            is_active=False,
            parameters={
                'mobile_phone_1': {
                    'otp_max_request': 3,
                    'otp_resend_time_sms': 180,
                    'otp_resend_time_miscall': 180,
                }
            },
        )

    @patch(
        'juloserver.customer_module.views.views_api_v3.unbind_customers_gopay_tokenization_account_linking'
    )
    def test_change_phone_number(self, mock_unbind_customers_gopay_tokenization_account_linking):
        data = {}
        res = self.client.post('/api/customer-module/v3/change-phone', data=data, format='json')
        assert res.status_code == 400

        data = {
            "new_phone_number": "1233445566",
        }
        res = self.client.post('/api/customer-module/v3/change-phone', data=data, format='json')
        assert res.status_code == 400

        data = {
            "new_phone_number": "1233445566",
            "pin": "123456",
            "username": self.customer.phone,
        }
        mock_unbind_customers_gopay_tokenization_account_linking.return_value = 'Gopay', None
        res = self.client.post('/api/customer-module/v3/change-phone', data=data, format='json')
        assert res.status_code == 200

        data = {
            "new_phone_number": "9876543210",
            "pin": "123456",
            "username": self.customer.phone,
        }
        res = self.client.post('/api/customer-module/v3/change-phone', data=data, format='json')
        assert res.status_code == 400

        self.otp_settings.is_active = True
        self.otp_settings.save()
        now = timezone.localtime(timezone.now())
        expire_time = now + timedelta(minutes=15)
        new_phone_number = "1233445566"

        self.otp_request = OtpRequestFactory(
            customer=self.customer,
            action_type='change_phone_number',
            phone_number=new_phone_number,
            is_used=True,
        )

        self.temp_session = TemporarySessionFactory(
            user=self.customer.user,
            expire_at=expire_time,
            is_locked=False,
            otp_request=self.otp_request,
        )

        data = {
            "new_phone_number": new_phone_number,
            "pin": "123456",
            "username": self.customer.phone,
        }
        res = self.client.post('/api/customer-module/v3/change-phone', data=data, format='json')
        assert res.status_code == 200


class TestChangeEmail(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        CustomerPinFactory(user=self.user)
        self.user.set_password('123456')
        self.user.save()
        self.user.refresh_from_db()

    def test_change_email(self):
        data = {'email': 'newemail@gmail.com', 'pin': '123456'}
        pin_token = PinValidationTokenFactory(user=self.user)

        # otp feature is off
        ## wrong pin validation token
        data['pin_validation_token'] = 'wrong_token'
        response = self.client.post(
            '/api/customer-module/v3/change-email', data=data, format='json'
        )
        assert response.status_code == 401

        ## success
        data['pin_validation_token'] = pin_token.access_key
        response = self.client.post(
            '/api/customer-module/v3/change-email', data=data, format='json'
        )
        assert response.status_code == 200

        # check expected data in DB
        expectedEmail = 'newemail@gmail.com'
        self.application.refresh_from_db()
        self.customer.refresh_from_db()
        self.user.refresh_from_db()
        pin_token.refresh_from_db()
        self.assertEqual(expectedEmail, self.user.email)
        self.assertEqual(expectedEmail, self.application.email)
        self.assertEqual(expectedEmail, self.customer.email)
        self.assertFalse(pin_token.is_active)

        # otp_feature is on
        msf = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={'wait_time_seconds': 400, 'otp_max_request': 3, 'otp_resend_time_sms': 180},
        )
        pin_token.is_active = True
        pin_token.save()
        response = self.client.post(
            '/api/customer-module/v3/change-email', data=data, format='json'
        )
        assert response.status_code == 400

        # invalid session token
        data['session_token'] = 'dasdasdasd7827321837'
        response = self.client.post(
            '/api/customer-module/v2/change-email', data=data, format='json'
        )
        assert response.status_code == 403

        # success
        session = TemporarySessionFactory(user=self.customer.user)
        data['session_token'] = session.access_key
        data['email'] = 'test_email@gmail.com'
        response = self.client.post(
            '/api/customer-module/v2/change-email', data=data, format='json'
        )
        assert response.status_code == 200


class TestLimitValidityTimerView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            application_status=StatusLookupFactory(status_code=190),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_disbursement_amount=100000,
            loan_amount=105000,
            loan_status=StatusLookupFactory(status_code=220),
        )
        self.campaign_1 = LimitValidityTimerCampaignFactory(
            start_date=datetime(2024, 3, 15, 13, 30, 30, tzinfo=pytz.UTC),
            end_date=datetime(2024, 3, 30, 17, 30, 30, tzinfo=pytz.UTC),
            campaign_name='campaign_1',
            content=dict(
                title="Title of campaign 1",
                body="Body of campaign 1",
                button="Button 1"
            ),
            minimum_available_limit=500000,
            transaction_method_id=TransactionMethodCode.OTHER.code,
            is_active=True
        )
        self.campaign_2 = LimitValidityTimerCampaignFactory(
            start_date=datetime(2024, 3, 16, 13, 30, 30, tzinfo=pytz.UTC),
            end_date=datetime(2024, 3, 29, 17, 30, 30, tzinfo=pytz.UTC),
            campaign_name='campaign_2',
            content=dict(
                title="Title of campaign 2",
                body="Body of campaign 2",
                button="Button 2"
            ),
            minimum_available_limit=800000,
            is_active=True
        )

    @patch('juloserver.limit_validity_timer.services.get_redis_client')
    @patch('django.utils.timezone.now')
    def test_account_has_no_validity_timer_campaign(self, mock_now, mock_redis_client):
        mock_now.return_value = datetime(2024, 3, 20, 12, 23, 30)
        mock_redis_client.return_value.exists.return_value = False

        self.account.update_safely(status_id=420)
        self.account_limit.update_safely(available_limit=1000000)

        res = self.client.get('/api/customer-module/v3/limit-timer')
        self.assertIsNone(res.json()['data'])

        mock_redis_client.return_value.exists.return_value = True
        mock_redis_client.return_value.sismember.return_value = True
        self.campaign_2.update_safely(deeplink_url=None)

        res = self.client.get('/api/customer-module/v3/limit-timer')
        self.assertIsNone(res.json()['data'])

    @patch('juloserver.limit_validity_timer.services.get_redis_client')
    @patch('django.utils.timezone.now')
    def test_account_has_validity_timer_campaign(self, mock_now, mock_redis_client):
        mock_now.return_value = datetime(2024, 3, 20, 12, 23, 30)
        mock_redis_client.return_value.exists.return_value = True
        mock_redis_client.return_value.sismember.return_value = True

        self.account.update_safely(status_id=420)
        self.account_limit.update_safely(available_limit=1000000)
        self.campaign_2.update_safely(deeplink_url='julo://referral')

        res = self.client.get('/api/customer-module/v3/limit-timer')
        expected_data = {
            "end_time": "2024-03-29T17:30:30Z",
            "campaign_name": "campaign_2",
            "information": {
                "title": "Title of campaign 2",
                "body": "Body of campaign 2",
                "button": "Button 2",
                "deeplink_url": "julo://referral"
            },
            "pop_up_message": None
        }
        self.assertEqual(res.json()['data'], expected_data)
