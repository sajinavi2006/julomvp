import json
from datetime import datetime, timedelta

from factory import Iterator
from mock import patch

from babel.dates import format_date
from dateutil.relativedelta import relativedelta
from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.cfs.services.crm_services import (
    change_pending_state_assignment,
    update_agent_verification, record_monthly_income_value_change,
)
from juloserver.account.constants import AccountConstant
from juloserver.application_flow.factories import BankStatementProviderLogFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    PartnerFactory,
    ProductLineFactory,
    StatusLookupFactory,
    ImageFactory,
    FeatureSettingFactory,
    LoanFactory,
    PaymentFactory,
    WorkflowFactory,
    ReferralSystemFactory, ApplicationHistoryFactory, FDCInquiryFactory, FDCInquiryLoanFactory,
    InitialFDCInquiryLoanDataFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory, AccountPropertyFactory, AccountLimitFactory, CreditLimitGenerationFactory
)
from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.payment_point.constants import TransactionMethodCode
from .factories import (
    CashbackBalanceFactory,
    CfsActionFactory,
    CfsActionAssignmentFactory,
    CfsAssignmentVerificationFactory,
    AgentFactory,
    CfsTierFactory,
    CfsActionPointsFactory,
    PdClcsPrimeResultFactory,
    TotalActionPointsFactory,
    TotalActionPointsHistoryFactory,
    CfsActionPointsAssignmentFactory,
)
from juloserver.cfs.models import (
    CfsActionAssignment,
    TotalActionPoints,
    TotalActionPointsHistory,
    CfsAssignmentVerification,
)
from juloserver.cfs.constants import (
    CfsActionPointsActivity,
    ImageUploadType,
    CfsProgressStatus,
    TierId,
    VerifyAction,
    VerifyStatus,
    CfsStatus,
    EtlJobType,
    CustomerCfsAction,
    CfsActionType,
    CfsActionId,
    CfsMissionWebStatus,
)
from juloserver.cfs.services.core_services import (
    convert_to_mission_response,
    get_mission_enable_state,
    get_all_cfs_actions_infos_dict,
    claim_cfs_rewards,
    create_or_update_cfs_action_assignment,
    create_cfs_assignment_verification,
    create_cfs_action_assignment_verify_address,
    create_cfs_action_assignment_connect_bank,
    create_cfs_action_assignment_connect_bpjs,
    check_distance_more_than_1_km,
    get_customer_tier_info,
    get_customer_j_score_histories,
    check_lock_by_customer_tier,
    get_cfs_status,
    get_cfs_missions,
    bulk_update_total_points_and_create_history,
    process_post_connect_bank,
    get_cfs_transaction_note,
    get_latest_action_point_by_month,
    detect_create_or_update_cfs_action,
    get_expiry_date,
)
from juloserver.cfs.services.easy_income_services import (
    get_data_for_easy_income_eligible_and_status,
    get_perfios_url,
)
from juloserver.cfs.tests.factories import EasyIncomeEligibleFactory
from juloserver.apiv2.tests.factories import (
    PdCreditModelResultFactory,
    EtlJobFactory,
    PdWebModelResultFactory
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.disbursement.tests.factories import DisbursementFactory
from juloserver.julo.models import StatusLookup, CustomerWalletHistory, ApplicationFieldChange
from juloserver.account.models import AccountProperty
from juloserver.julo.constants import (
    FeatureNameConst,
    WorkflowConst,
)
from juloserver.apiv2.models import EtlJob
from juloserver.cfs.exceptions import CfsFeatureNotEligible, InvalidStatusChange
from juloserver.cfs.tasks import (
    update_graduate_entry_level, create_or_update_cfs_action_assignment_bca_autodebet,
)
from juloserver.autodebet.tests.factories import (
    AutodebetBenefitFactory, AutodebetAccountFactory,
)
from juloserver.autodebet.constants import AutodebetStatuses, AutodebetVendorConst
from juloserver.moengage.constants import MoengageEventType
from juloserver.moengage.services.data_constructors import \
    construct_data_for_cfs_mission_verification_change


class TestCfsServices(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user,
            fullname='customer name 1'
        )
        self.cashback_balance = CashbackBalanceFactory(customer=self.customer)
        self.client.force_login(self.user)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.agent = AgentFactory(user=self.user)
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.app_version = '1.1.1'
        self.application.save()
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.CFS,
            parameters={
                'faqs': {
                    'header': 'header',
                    'topics': [{
                        'question': 'question test 1',
                        'answer': 'answer test 1'
                    }]
                },
                "graduation_rules": [
                    {
                        "max_late_payment": 0,
                        "max_account_limit": 300000,
                        "max_grace_payment": 1,
                        "min_account_limit": 100000,
                        "new_account_limit": 500000,
                        "min_percentage_limit_usage": 300,
                        "min_percentage_paid_amount": 100
                    },
                    {
                        "max_late_payment": 0,
                        "max_account_limit": 500000,
                        "max_grace_payment": 1,
                        "min_account_limit": 500000,
                        "new_account_limit": 1000000,
                        "min_percentage_limit_usage": 200,
                        "min_percentage_paid_amount": 100
                    }
                ],
                "is_active_graduation": True,
            }
        )
        self.action = CfsActionFactory(
            id=13,
            is_active=True,
            action_code='share_to_social_media',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000,
            app_version='6.0.0',
        )
        self.image = ImageFactory(
            image_type=ImageUploadType.PAYSTUB,
            image_source=self.application.id
        )
        today = timezone.localtime(timezone.now()).date()
        self.account_property = AccountPropertyFactory(account=self.account, is_entry_level=True)
        PdClcsPrimeResultFactory(
            customer_id=self.customer.id, partition_date=today, clcs_prime_score=0.5
        )
        CfsTierFactory(id=1, name='Starter', point=100, icon='123.pnj', cashback_multiplier=0.5)
        CfsTierFactory(id=2, name='Advanced', point=300, icon='123.pnj', cashback_multiplier=0.5)
        CfsTierFactory(id=3, name='Pro', point=600, icon='123.pnj', cashback_multiplier=0.5)
        CfsTierFactory(id=4, name='Champion', point=1000, icon='123.pnj', cashback_multiplier=0.5)

    def test_application_not_eligible_for_cfs(self):
        self.application.update_safely(
            partner=PartnerFactory(name='grab'),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB),
        )
        self.assertRaises(CfsFeatureNotEligible, get_cfs_status, self.application)

        # julo turbo
        self.application.update_safely(
            workflow=WorkflowFactory(name=WorkflowConst.CREDIT_CARD)
        )
        self.assertFalse(self.application.eligible_for_cfs)

        self.application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.JULO_STARTER)
        )
        self.assertFalse(self.application.eligible_for_cfs)

    @patch('django.utils.timezone.now')
    @patch('juloserver.julo.signals.execute_after_transaction_safely')
    def test_get_status_with_entry_level(self, mock_execute_after_transaction_safely,
                                         mock_timezone):
        mock_timezone.return_value = datetime(2022, 9, 30, 0, 0, 0)
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id, status_new=ApplicationStatusCodes.LOC_APPROVED
        )
        mock_timezone.return_value = timezone.localtime(timezone.now())
        self.account_limit = AccountLimitFactory(account=self.account, set_limit=100000)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment.status_id = 332
        self.account_payment.save()
        self.disbursement = DisbursementFactory()
        self.loan = LoanFactory(
            account=self.account, customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            initial_cashback=2000,
            disbursement_id=self.disbursement.id,
            application=self.application
        )
        self.payment = PaymentFactory(
            due_date=self.account_payment.due_date,
            account_payment=self.account_payment,
            loan=self.loan,
            change_due_date_interest=0,
            paid_date=datetime.today().date(),
        )
        self.payment.payment_status = self.account_payment.status
        self.payment.paid_amount = 20000
        self.payment.save()

        graduation_rules = self.feature_setting.parameters['graduation_rules']
        # can't pass with payment late
        is_success = update_graduate_entry_level(self.account.id, graduation_rules)
        self.assertFalse(is_success)

        # can't pass with loan < 220
        self.payment.status_id = 330  # update paid on time
        self.payment.save()
        self.loan.loan_status_id = 212
        self.loan.save()
        is_success = update_graduate_entry_level(self.account.id, graduation_rules)
        self.assertFalse(is_success)

        mock_execute_after_transaction_safely.assert_called()
        get_cfs_status(self.application)
        account_property = AccountProperty.objects.filter(account=self.account).last()
        self.assertTrue(account_property.is_entry_level)

    @patch('juloserver.julo.signals.execute_after_transaction_safely')
    def test_turn_off_graduation(self, mock_execute_after_transaction_safely):
        parameters = self.feature_setting.parameters
        parameters['is_active_graduation'] = False
        self.feature_setting.parameters = parameters
        self.feature_setting.save()
        self.disbursement = DisbursementFactory()
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.loan = LoanFactory(
            account=self.account, customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.PAID_OFF),
            initial_cashback=2000,
            disbursement_id=self.disbursement.id,
            application=self.application
        )
        self.payment = PaymentFactory(
            payment_status=self.account_payment.status,
            due_date=self.account_payment.due_date,
            account_payment=self.account_payment,
            loan=self.loan,
            change_due_date_interest=0,
            paid_date=datetime.today().date(),
            paid_amount=100000
        )
        self.payment.save()
        self.account_limit = AccountLimitFactory(account=self.account, set_limit=100000)
        cfs_status = get_cfs_status(self.application)
        self.assertIsNone(cfs_status.get('j_score'))
        mock_execute_after_transaction_safely.assert_not_called()

    @patch('django.utils.timezone.now')
    def test_get_status_with_pass_entry_level(self, mock_timezone):
        mock_timezone.return_value = datetime(2022, 9, 30, 0, 0, 0)
        feature_setting_2 = FeatureSettingFactory(
            feature_name='graduation_fdc_check',
            is_active=True
        )
        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        fdc_inquiry = FDCInquiryFactory(application_id=self.application.id)
        fdc_inquiry_loan = FDCInquiryLoanFactory.create_batch(
            5, fdc_inquiry_id=fdc_inquiry.id, is_julo_loan=False,
            dpd_terakhir=Iterator([1, 1, 1, 1, 1]), status_pinjaman='Outstanding'
        )
        init_fdc_inquiry_loan_data = InitialFDCInquiryLoanDataFactory(
            fdc_inquiry=fdc_inquiry, initial_outstanding_loan_count_x100=10
        )
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id, status_new=ApplicationStatusCodes.LOC_APPROVED
        )
        mock_timezone.return_value = timezone.localtime(timezone.now())
        self.account_property.is_entry_level = True
        self.account_property.save()
        self.account_limit = AccountLimitFactory(
            account=self.account, max_limit=100000, set_limit=100000, available_limit=100000,
            used_limit=100000
        )
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment.status_id = 331  # at least 1 grace payment
        self.account_payment.save()
        self.disbursement = DisbursementFactory()
        self.loan = LoanFactory(
            account=self.account, customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.PAID_OFF),
            initial_cashback=2000,
            disbursement_id=self.disbursement.id,
            application=self.application,
        )
        self.payment = PaymentFactory(
            due_date=self.account_payment.due_date,
            account_payment=self.account_payment,
            loan=self.loan,
            change_due_date_interest=0,
            paid_date=datetime.today().date(),
        )
        self.payment.payment_status = self.account_payment.status
        self.payment.paid_amount = 100000
        self.payment.save()
        self.credit_limit_generation = CreditLimitGenerationFactory(
            account=self.account, application=self.application,
            log='{"simple_limit": 17532468, "reduced_limit": 15779221, '
                '"limit_adjustment_factor": 0.9, "max_limit (pre-matrix)": 500000, '
                '"set_limit (pre-matrix)": 500000}',
            max_limit=500000,
            set_limit=500000
        )
        update_graduate_entry_level(
            self.account.id, self.feature_setting.parameters['graduation_rules']
        )
        cfs_status = get_cfs_status(self.application)
        self.assertFalse(cfs_status['is_entry_level'])
        self.assertEqual(cfs_status['status'], CfsStatus.ACTIVE)
        self.account_limit.refresh_from_db()
        self.assertEqual(
            (
                self.account_limit.set_limit,
                self.account_limit.max_limit,
                self.account_limit.available_limit
            ),
            (
                500000,
                500000,
                400000
            )
        )

    def test_get_mission_enable_state(self):
        self.feature_setting.is_active = False
        self.feature_setting.save()
        is_enable = get_mission_enable_state(self.application)
        self.assertFalse(is_enable)
        self.feature_setting.is_active = True
        self.feature_setting.save()
        is_enable = get_mission_enable_state(self.application)
        self.assertTrue(is_enable)

    def test_get_all_mission_infos(self):
        cfs_actions_infos_dict = get_all_cfs_actions_infos_dict()
        self.assertEqual(len(cfs_actions_infos_dict.keys()), 1)

    @patch('juloserver.boost.services.get_boost_mobile_feature_settings')
    def test_get_cfs_missions(self, mock_boost_mobile_setting):
        mock_boost_mobile_setting.return_value.parameters = {
            "bank": {
                'is_active': True,
            },
            "bpjs": {
                'is_active': True,
            },
        }
        self.account.app_version = '6.0.0'
        _, on_going_missions, _ = get_cfs_missions(self.application)
        self.assertEqual(len(on_going_missions), 1)

    @patch('juloserver.boost.services.get_boost_mobile_feature_settings')
    def test_get_cfs_mission_repeat(self, mock_boost_mobile_setting):
        CfsActionAssignmentFactory(
            action=self.action,
            customer=self.customer,
            progress_status=CfsProgressStatus.CLAIMED,
            expiry_date=timezone.localtime(datetime.now() - relativedelta(days=1)),
        )
        self.account.app_version = '6.0.0'
        mock_boost_mobile_setting.return_value.parameters = {
            "bank": {
                'is_active': True,
            },
            "bpjs": {
                'is_active': True,
            },
        }
        _, on_going_missions, _ = get_cfs_missions(self.application)
        mission = on_going_missions[0]
        self.assertEqual(mission['progress_status'], CfsProgressStatus.START)

    @patch('juloserver.entry_limit.services.is_entry_level_type')
    @patch('juloserver.boost.services.get_boost_mobile_feature_settings')
    def test_get_cfs_missions_unnecessary_queries(self, mock_boost_mobile_setting, mock_entry_level):
        self.account.app_version = '6.0.0'
        mock_entry_level.return_value = False
        mock_boost_mobile_setting.return_value.parameters = {
            "bank": {
                'is_active': True,
            },
            "bpjs": {
                'is_active': True,
            },
        }

        # 1 query from get_all_cfs_actions_infos_dict()
        # 1 from get_distinct_latest_assignments_action()
        # 0 from get_boost_mobile_feature_settings() -- 'cause mock
        # 1 from MobileFeatureSetting.objects.get
        # 1 from ReferralSystem
        # 3 from get_customer_tier_info(
        #    1 from Total Action points,
        #    1 from get_clcs_prime_score,
        #    0 from is_entry_level_type -- 'cause mock
        #    1 from CfsTier,
        # )
        # 0 from show_referral_code() because this test doesn't hit this
        # 1 from get feature setting bca auto debet
        # 1 from account autodebet
        # 1 from autodebet benefit
        # total:
        n = 9
        with self.assertNumQueries(n):
            get_cfs_missions(self.application)

    @patch('juloserver.boost.services.get_boost_mobile_feature_settings')
    def test_get_cfs_missions_with_app_version_account(self, mock_boost_mobile_setting):
        mock_boost_mobile_setting.return_value.parameters = {
            "bank": {
                'is_active': True,
            },
            "bpjs": {
                'is_active': True,
            },
        }
        # invalid app version
        self.account.app_version = '5.1.1'
        self.account.save()
        _, on_going_missions, _ = get_cfs_missions(self.application)
        self.assertEqual(len(on_going_missions), 0)

        # pass app version
        self.account.app_version = '6.0.0'
        self.account.save()
        _, on_going_missions, _ = get_cfs_missions(self.application)
        self.assertEqual(len(on_going_missions), 1)

    @patch('juloserver.cfs.services.core_services.show_referral_code')
    @patch('juloserver.boost.services.get_boost_mobile_feature_settings')
    def test_get_special_missions(self, mock_boost_mobile_setting, mock_show_referral_code):
        mock_boost_mobile_setting.return_value.parameters = {
            "bank": {
                'is_active': True,
            },
            "bpjs": {
                'is_active': True,
            },
        }
        ReferralSystemFactory()
        self.action = CfsActionFactory(
            id=1,
            is_active=True,
            action_code='referral',
            app_version='6.0.0',
            action_type=CfsActionType.UNLIMITED,
        )
        self.customer.update_safely(self_referral_code='test_code')
        self.account.app_version = '6.0.0'
        self.account.save()
        mock_show_referral_code.return_value = False
        special_missions, _, _ = get_cfs_missions(self.application)
        self.assertEqual(len(special_missions), 0)

        mock_show_referral_code.return_value = True
        special_missions, _, _ = get_cfs_missions(self.application)
        self.assertEqual(len(special_missions), 1)

    @patch('juloserver.cfs.services.core_services.send_cfs_ga_event')
    def test_claim_cfs_reward_with_not_agent_verify(self, mock_send_cfs_ga_event):
        self.action = CfsActionFactory(
            id=12,
            is_active=True,
            action_code='verify_address',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000
        )
        self.cfs_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.action,
            progress_status=CfsProgressStatus.UNCLAIMED,
            repeat_action_no=1,
            cashback_amount=1000,
            extra_data={
                'multiplier': 1.5
            }
        )
        is_success = claim_cfs_rewards(self.cfs_action_assignment.id, self.customer)
        self.assertTrue(is_success)

    @patch('juloserver.cfs.services.core_services.send_cfs_ga_event')
    def test_claim_cfs_reward_with_agent_verify(self, mock_send_cfs_ga_event):
        self.action = CfsActionFactory(
            id=4,
            is_active=True,
            action_code='upload_utilities_bill',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000
        )
        self.cfs_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.action,
            progress_status=CfsProgressStatus.PENDING,
            repeat_action_no=1,
            cashback_amount=1000,
            extra_data={
                'multiplier': 1.5
            }
        )
        assignment_verification = CfsAssignmentVerificationFactory(
            cfs_action_assignment=self.cfs_action_assignment,
            extra_data={
                'image': self.image.id,
            }
        )
        agent_note = '123456'
        update_agent_verification(
            assignment_verification.id,
            self.agent,
            agent_note=agent_note
        )
        assignment_verification.refresh_from_db()
        self.assertEqual(
            agent_note,
            assignment_verification.message
        )
        change_pending_state_assignment(
            self.application,
            self.cfs_action_assignment,
            assignment_verification,
            CfsProgressStatus.UNCLAIMED,
            VerifyAction.APPROVE,
            self.agent
        )
        assignment_verification.refresh_from_db()
        self.assertEqual(
            assignment_verification.verify_status,
            VerifyStatus.APPROVE
        )

        is_success = claim_cfs_rewards(
            self.cfs_action_assignment.id,
            self.customer
        )
        self.assertTrue(is_success)
        transaction = CustomerWalletHistory.objects.filter(customer=self.customer).first()
        transaction_note = get_cfs_transaction_note(transaction.id)
        self.assertEqual(transaction_note, 'Cashback Tambah Bukti Tagihan Kebutuhan')
        self.cfs_action_assignment.refresh_from_db()
        self.assertEqual(
            get_expiry_date(self.action.default_expiry),
            timezone.localtime(self.cfs_action_assignment.expiry_date).date()
        )

    def test_get_cfs_action_assignment_by_id(self):
        self.cfs_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.action,
            progress_status=CfsProgressStatus.PENDING,
            repeat_action_no=1,
            extra_data={
                'cashback_amount': 5000,
            }
        )
        action_assignment = CfsActionAssignment.objects.filter(
            id=self.cfs_action_assignment.id
        ).first()
        self.assertIsNotNone(action_assignment)

    @patch('juloserver.cfs.services.core_services.send_cfs_ga_event')
    def test_create_cfs_action_assignment(self, mock_send_cfs_ga_event):
        action_assignment = create_or_update_cfs_action_assignment(
            self.application,
            self.action.id,
            CfsProgressStatus.UNCLAIMED
        )
        self.assertIsNotNone(action_assignment)

    def test_create_cfs_assignment_verification(self):
        self.cfs_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.action,
            progress_status=CfsProgressStatus.PENDING,
            repeat_action_no=1,
            extra_data={
                'cashback_amount': 5000,
            }
        )
        cfs_action_assignment = create_cfs_assignment_verification(
            self.cfs_action_assignment,
            self.account,
            image_ids=[self.image.id]
        )
        self.assertIsNotNone(cfs_action_assignment)

    @patch('juloserver.cfs.services.core_services.send_cfs_ga_event')
    @patch('juloserver.cfs.services.core_services.check_distance_more_than_1_km')
    def test_create_cfs_action_assignment_verify_address(self,
                                                         mock_check_distance_more_than_1_km,
                                                         mock_send_cfs_ga_event
                                                         ):
        mock_check_distance_more_than_1_km.return_value = True, {
            "device_lat": -6.2243538,
            "device_long": 106.843988,
            "application_address_lat": -6.2243538,
            "application_address_long": 106.843988,
            "distance_in_km": 8.6,
            "decision": True,
        }

        self.action = CfsActionFactory(
            id=12,
            is_active=True,
            action_code='verify_address',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/222.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=500,
            repeat_occurrence_cashback_amount=100
        )

        data = {
            "application": self.application,
            "latitude": -6.2243538,
            "longitude": 106.843988
        }

        is_success, action_assignment = create_cfs_action_assignment_verify_address(**data)
        self.assertTrue(is_success)

    @patch('juloserver.cfs.services.core_services.send_cfs_ga_event')
    @patch('juloserver.cfs.services.core_services.check_distance_more_than_1_km')
    def test_do_mission_verify_address_with_wrong_distance(self,
                                                           mock_check_distance_more_than_1_km,
                                                           mock_send_cfs_ga_event
                                                           ):
        mock_check_distance_more_than_1_km.return_value = False, {
            "device_lat": 65.9667,
            "device_long": -18.5333,
            "application_address_lat": 65.9667,
            "application_address_long": -18.5333,
            "distance_in_km": 0.6,
            "decision": False,
        }

        self.action = CfsActionFactory(
            id=12,
            is_active=True,
            action_code='verify_address',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/222.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=500,
            repeat_occurrence_cashback_amount=100
        )

        data = {
            "application": self.application,
            "latitude": 65.9667,
            "longitude": -18.5333
        }

        is_success, action_assignment = create_cfs_action_assignment_verify_address(**data)
        self.assertFalse(is_success)
        self.assertEqual(action_assignment.progress_status, CfsProgressStatus.FAILED)

        mock_check_distance_more_than_1_km.return_value = True, {
            "device_lat": -6.2243538,
            "device_long": 106.843988,
            "application_address_lat": -6.2243538,
            "application_address_long": 106.843988,
            "distance_in_km": 8.6,
            "decision": True,
        }

        data = {
            "application": self.application,
            "latitude": -6.2243538,
            "longitude": 106.843988
        }

        is_success, action_assignment = create_cfs_action_assignment_verify_address(**data)
        self.assertTrue(is_success)
        self.assertTrue(action_assignment.progress_status, CfsProgressStatus.UNCLAIMED)

    @patch('juloserver.cfs.services.core_services.AddressFraudPrevention')
    def test_check_distance_more_than_1_km(self, mock_address_fraud_prevention):
        mock_data = {
                "lat": -6.2243538,
                "long": 106.843988
            }, {"test": "test"}

        mock_address_fraud_prevention().get_geocoding_by_address_here_maps.return_value = mock_data
        mock_address_fraud_prevention().calculate_distance.return_value = 1

        status_distance, result_distance = check_distance_more_than_1_km(
            self.application,
            -6.2243538,
            106.843999
        )

        self.assertTrue(status_distance)
        self.assertIsNotNone(result_distance)

    @patch('juloserver.cfs.services.core_services.send_cfs_ga_event')
    def test_create_cfs_action_assignment_connect_bank(self, mock_send_cfs_ga_event):
        self.action = CfsActionFactory(
            id=2,
            is_active=True,
            action_code='connect_bank',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000
        )
        data = {
            "application": self.application,
            "bank_name": "bri",
            "progress_status": CfsProgressStatus.START
        }
        action_assignment = create_cfs_action_assignment_connect_bank(**data)
        self.assertIsNotNone(action_assignment)

        self.etl_job = EtlJobFactory(id=123, status=EtlJob.LOAD_SUCCESS, job_type=EtlJobType.CFS)
        self.etl_job.save()
        data = {
            "application": self.application,
            "etl_job": self.etl_job,
        }
        is_success = process_post_connect_bank(**data)
        self.assertTrue(is_success)
        self.assertIsNotNone(CfsAssignmentVerification.objects.filter(
            cfs_action_assignment=action_assignment
        ))

    @patch('juloserver.cfs.services.core_services.send_cfs_ga_event')
    def test_create_cfs_action_assignment_connect_bpjs(self, mock_send_cfs_ga_event):
        self.action = CfsActionFactory(
            id=3,
            is_active=True,
            action_code='connect_bpjs',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000
        )
        data = {
            "application": self.application,
            "progress_status": CfsProgressStatus.PENDING
        }
        action_assignment = create_cfs_action_assignment_connect_bpjs(**data)
        self.assertIsNotNone(action_assignment)

    def test_is_eligible_cfs(self):
        result = self.application.eligible_for_cfs
        self.assertTrue(result)

        self.application.partner = PartnerFactory()
        self.application.save()
        result = self.application.eligible_for_cfs
        self.assertTrue(result)

        self.application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        )
        result = self.application.eligible_for_cfs
        self.assertFalse(result)

        # julo turbo
        self.application.update_safely(
            workflow=WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        )
        self.assertTrue(self.application.eligible_for_cfs)

    def test_detect_create_or_update_cfs_action(self):
        customer_action, latest_action_assignment = detect_create_or_update_cfs_action(
            self.customer, self.action.id, CfsProgressStatus.UNCLAIMED
        )
        self.assertEqual(customer_action, CustomerCfsAction.CREATE)
        current_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            repeat_action_no=1,
            action=self.action,
            progress_status=CfsProgressStatus.UNCLAIMED,
            cashback_amount=10000,
            extra_data={
                'multiplier': 1.212,
            },
        )
        customer_action, latest_action_assignment = detect_create_or_update_cfs_action(
            self.customer, self.action.id, CfsProgressStatus.CLAIMED
        )
        self.assertEqual(customer_action, CustomerCfsAction.UPDATE)
        self.assertEqual(latest_action_assignment, current_assignment)
        current_assignment.progress_status = CfsProgressStatus.CLAIMED
        current_assignment.expiry_date = datetime(2020, 5, 17).date()
        current_assignment.save()
        customer_action, _ = detect_create_or_update_cfs_action(
            self.customer, self.action.id, CfsProgressStatus.UNCLAIMED
        )
        self.assertEqual(customer_action, CustomerCfsAction.CREATE)

    def test_do_mission_bca_autodebet(self):
        self.action = CfsActionFactory(
            id=14,
            is_active=True,
            action_code='bca_autodebet',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            action_type="onetime",
            first_occurrence_cashback_amount=0,
            repeat_occurrence_cashback_amount=0,
            app_version='6.0.0',
        )
        cfs_action_assignment = create_or_update_cfs_action_assignment_bca_autodebet(
            self.customer.id, CfsProgressStatus.PENDING
        )
        self.assertEqual(cfs_action_assignment.progress_status, CfsProgressStatus.PENDING)
        with self.assertRaises(InvalidStatusChange):
            create_or_update_cfs_action_assignment_bca_autodebet(
                self.customer.id, CfsProgressStatus.PENDING
            )

        cfs_action_assignment = create_or_update_cfs_action_assignment_bca_autodebet(
            self.customer.id, CfsProgressStatus.CLAIMED
        )
        self.assertEqual(cfs_action_assignment.progress_status, CfsProgressStatus.CLAIMED)

    def test_construct_data_for_cfs_mission_change(self):
        self.action = CfsActionFactory(
            id=4,
            is_active=True,
            action_code='upload_utilities_bill',
            title='Upload bukti tagihan kebutuhan',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000
        )
        self.cfs_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.action,
            progress_status=CfsProgressStatus.PENDING,
            repeat_action_no=1,
            cashback_amount=1000,
            extra_data={
                'multiplier': 1.5
            }
        )
        assignment_verification = CfsAssignmentVerificationFactory(
            cfs_action_assignment=self.cfs_action_assignment,
            extra_data={
                'image': self.image.id,
            },
            verify_status=VerifyStatus.REFUSE
        )
        _, event_data = construct_data_for_cfs_mission_verification_change(
            self.application,
            assignment_verification,
            MoengageEventType.CFS_AGENT_CHANGE_MISSION
        )
        event_time = timezone.localtime(assignment_verification.cdate)
        expected_response_event_data = {
            'type': 'event',
            'customer_id': self.customer.id,
            'device_id': self.application.device.gcm_reg_id,
            'actions': [{
                'action': MoengageEventType.CFS_AGENT_CHANGE_MISSION,
                'attributes': {
                    'status': 'refused',
                    'cfs_action_code': 'upload_utilities_bill',
                    'cfs_action_title': 'Upload bukti tagihan kebutuhan',
                    'cfs_action_id': 4,
                },
                'platform': 'ANDROID',
                'current_time': event_time.timestamp(),
                'user_timezone_offset': event_time.utcoffset().seconds
            }]
        }
        self.assertEqual(event_data, expected_response_event_data)


class TestCustomerTierScore(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        CfsTierFactory(id=1, name='Starter', point=100, tarik_dana=True)
        CfsTierFactory(id=2, name='Advanced', point=300, tarik_dana=True)
        CfsTierFactory(id=3, name='Pro', point=600, tarik_dana=True)
        CfsTierFactory(id=4, name='Champion', point=1000, tarik_dana=True)
        self.cfs_action_points = CfsActionPointsFactory(
            id=1, description='transact', multiplier=0.001, floor=5, ceiling=25, default_expiry=180
        )
        today = timezone.localtime(timezone.now()).date()
        PdCreditModelResultFactory(application_id=self.application.id, pgood=0.8)
        PdClcsPrimeResultFactory(
            customer_id=self.customer.id, partition_date=today, clcs_prime_score=0.5
        )
        self.status = StatusLookupFactory()
        self.status.status_code = 220
        self.status.save()
        self.loan = LoanFactory(customer=self.customer, loan_status=self.status)
        self.payment = PaymentFactory(loan=self.loan)
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.CFS,
            parameters={
                'jscore_messages': [
                    {
                        'max_value': 100000,
                        'min_value': 0,
                        'message': 'Selemat! Jscore kamu bertambah. Yuk, pertahankan dan '
                                   'tingkatkan lagi skor kredit kamu!',
                    },
                    {
                        'max_value': -1,
                        'min_value': -100,
                        'message': 'Yuk, tetap bayar tepat waktu untuk pertahankan Jscore kamu',
                    },
                    {
                        'max_value': -101,
                        'min_value': -300,
                        'message': 'Wah Jscore kamu berpotensi menurun. Tingkatkan transaksi dan '
                                   'bayar tepat waktu agar Jscore stabil',
                    },
                    {
                        'max_value': -301,
                        'min_value': -100000,
                        'message': 'Duh! Jscore kamu menurun, nih. Perbaiki score dengan '
                                   'bertransaksi dan jangan telat bayar tagihan.',
                    },
                ]
            }
        )

    def test_get_customer_j_score(self):
        j_score, _ = get_customer_tier_info(self.application)
        self.assertIsNotNone(j_score)

    def test_get_customer_j_score_histories(self):
        self.cfs_action_point_assignment = CfsActionPointsAssignmentFactory(
            customer_id=self.customer.id,
            loan_id=self.loan.id,
            payment_id=self.payment.id,
            cfs_action_points_id=self.cfs_action_points.id
        )
        TotalActionPointsHistoryFactory(
            customer_id=self.customer.id,
            cfs_action_point_assignment_id=self.cfs_action_point_assignment.id,
            partition_date=timezone.localtime(timezone.now()).date(),
            new_point=10,
            change_reason='action_points'
        )
        j_score_histories = get_customer_j_score_histories(self.application)
        self.assertNotEqual(len(j_score_histories), 0)

    def test_check_lock_by_customer_tier(self):
        is_locked = check_lock_by_customer_tier(self.account, TransactionMethodCode.OTHER.code)
        self.assertTrue(is_locked)

        self.application.update_safely(
            partner=PartnerFactory(name='grab'),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB),
        )
        is_locked = check_lock_by_customer_tier(self.account, TransactionMethodCode.OTHER.code)
        self.assertFalse(is_locked)

    def test_get_tier_case_negative_jscore(self):
        TotalActionPointsFactory(customer=self.customer, point=-10000)
        jscore, tier = get_customer_tier_info(self.application)
        self.assertLess(jscore, 0)
        self.assertEqual(tier.id, TierId.STARTER)

    @patch('juloserver.entry_limit.services.is_entry_level_type')
    def test_get_tier_case_entry_level(self, mock_is_entry_level_type):
        mock_is_entry_level_type.return_value = True
        TotalActionPointsFactory(customer=self.customer, point=600)
        _, tier = get_customer_tier_info(self.application)
        self.assertEqual(tier.id, TierId.STARTER)

    def test_get_latest_action_point_by_month(self):
        cfs_action_point_assignment = CfsActionPointsAssignmentFactory(
            customer_id=self.customer.id,
            loan_id=self.loan.id,
            payment_id=self.payment.id,
            cfs_action_points_id=self.cfs_action_points.id
        )
        today = timezone.localtime(timezone.now()).date()
        TotalActionPointsHistoryFactory(
            customer_id=self.customer.id,
            cfs_action_point_assignment_id=cfs_action_point_assignment.id,
            partition_date=today,
            new_point=10,
            change_reason='action_points'
        )
        previous_month = (timezone.localtime(timezone.now()) - relativedelta(months=1)).date()
        TotalActionPointsHistoryFactory(
            customer_id=self.customer.id,
            cfs_action_point_assignment_id=cfs_action_point_assignment.id,
            partition_date=previous_month,
            new_point=10,
            change_reason='action_points'
        )
        latest_action_point_by_month = get_latest_action_point_by_month(self.customer)
        self.assertEqual(len(latest_action_point_by_month), 2)
        self.assertTrue(today.replace(day=1) in latest_action_point_by_month)
        self.assertTrue(previous_month.replace(day=1) in latest_action_point_by_month)


class TestConvertToMissionResponse(TestCase):
    def setUp(self):
        super().setUp()
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.action = CfsActionFactory(
            id=13,
            is_active=True,
            action_code='share_to_social_media',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000,
            app_version='1.1.1',
            tag_info={
                'name': 'test_tag',
                'is_active': True,
            },
            title='title test',
        )
        self.tier = CfsTierFactory(id=2, name='Advanced', point=300, cashback_multiplier=2)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )

    def test_ongoing_missions(self):
        current_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            repeat_action_no=1,
            action=self.action,
            progress_status=CfsProgressStatus.START,
            cashback_amount=10000,
            extra_data={
                'multiplier': 1.212,
            },
        )

        response = convert_to_mission_response(
            self.tier, self.action, current_assignment)

        expected_response = {
            'title': self.action.title,
            'display_order': self.action.display_order,
            'action_code': self.action.action_code,
            'icon': self.action.icon,
            'app_link': self.action.app_link,
            'progress_status': current_assignment.progress_status,
            'action_assignment_id': current_assignment.id,
            'cashback_amount': current_assignment.cashback_amount,
            'multiplier': self.tier.cashback_multiplier,
            'tag_info': {
                'name': 'test_tag',
            }
        }
        self.assertEqual(expected_response, response)

        self.action.tag_info['is_active'] = False
        self.action.save()
        response = convert_to_mission_response(
            self.tier, self.action, current_assignment)
        expected_response = {
            'title': self.action.title,
            'display_order': self.action.display_order,
            'action_code': self.action.action_code,
            'icon': self.action.icon,
            'app_link': self.action.app_link,
            'progress_status': current_assignment.progress_status,
            'action_assignment_id': current_assignment.id,
            'cashback_amount': current_assignment.cashback_amount,
            'multiplier': self.tier.cashback_multiplier,
            'tag_info': {}
        }
        self.assertEqual(expected_response, response)

    def test_completed_missions(self):
        current_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            repeat_action_no=1,
            action=self.action,
            progress_status=CfsProgressStatus.CLAIMED,
            cashback_amount=10000,
            extra_data={
                'multiplier': 1.212,
            },
        )
        response = convert_to_mission_response(
            self.tier, self.action, current_assignment)

        expected_response = {
            'title': self.action.title,
            'display_order': self.action.display_order,
            'action_code': self.action.action_code,
            'icon': self.action.icon,
            'app_link': self.action.app_link,
            'progress_status': current_assignment.progress_status,
            'action_assignment_id': current_assignment.id,
            'cashback_amount': current_assignment.cashback_amount,
            'completed_time': format_date(current_assignment.udate.date(), 'dd MMMM yyyy', locale='id_ID'),
            'multiplier': current_assignment.extra_data['multiplier'],
            'tag_info': {
                'name': 'test_tag',
            }
        }
        self.assertEqual(expected_response, response)


class TestActionPoints(TestCase):
    def setUp(self):
        self.user1 = AuthUserFactory()
        self.customer1 = CustomerFactory(user=self.user1)
        self.user2 = AuthUserFactory()
        self.customer2 = CustomerFactory(user=self.user2)
        CfsActionPointsFactory(id=CfsActionPointsActivity.FRAUDSTER, multiplier=-0.1,
                               floor=-10000, ceiling=-1000, default_expiry=270)

    def test_bulk_create_points_and_history(self):
        amount = 100
        data = [
            {
                'customer_id': self.customer1.id,
                'amount': amount,
                'assignment_info': {}
            },
            {
                'customer_id': self.customer2.id,
                'amount': amount,
                'assignment_info': {}
            }
        ]
        customer1_point = 500
        total_point_customer1 = TotalActionPoints.objects.create(
            customer=self.customer1, point=customer1_point)

        bulk_update_total_points_and_create_history(data, CfsActionPointsActivity.FRAUDSTER)
        history_counts = TotalActionPointsHistory.objects.all().count()
        total_point_customer2 = TotalActionPoints.objects.filter(customer=self.customer2).first()
        total_point_customer1.refresh_from_db()
        self.assertEqual(history_counts, 2)
        self.assertIsNotNone(total_point_customer2)

        customer1_points_changed = total_point_customer2.point  # same amount so should be same
        self.assertEqual(total_point_customer1.point, customer1_point + customer1_points_changed)


class TestBcaAutodebet(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user,
            fullname='customer name 1'
        )
        self.client.force_login(self.user)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.agent = AgentFactory(user=self.user)
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        PdWebModelResultFactory(application_id=self.application.id, pgood=1)
        self.application.app_version = '1.1.1'
        self.application.save()
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.CFS,
        )
        self.action = CfsActionFactory(
            id=14,
            is_active=True,
            action_code='bca_autodebet',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            action_type="onetime",
            first_occurrence_cashback_amount=0,
            repeat_occurrence_cashback_amount=0,
            app_version='6.0.0',
        )
        self.bca_autodebet = FeatureSettingFactory(
            is_active=True,
            feature_name='autodebet_bca',
            parameters={"minimum_amount": 20000},
        )
        self.benefit_value = AutodebetBenefitFactory(
            account_id=self.account.id, pre_assigned_benefit='cashback', benefit_value=10000
        )
        self.tier = CfsTierFactory(id=2, name='Advanced', point=300, cashback_multiplier=2)

    @patch('juloserver.boost.services.get_boost_mobile_feature_settings')
    def test_bca_autodebet_missions(self, mock_boost_mobile_setting):
        mock_boost_mobile_setting.return_value.parameters = {
            "bank": {
                'is_active': True,
            },
            "bpjs": {
                'is_active': True,
            },
        }
        self.account.app_version = '6.0.0'
        _, on_going_missions, _ = get_cfs_missions(self.application)
        self.assertIsNone(on_going_missions[0].get('multiplier'))
        self.assertEqual(len(on_going_missions), 1)
        self.assertEqual(on_going_missions[0]['action_code'], 'bca_autodebet')

        AutodebetAccountFactory(
            account=self.account,
            status=AutodebetStatuses.PENDING_REVOCATION,
            activation_ts=datetime(2022, 9, 30),
            vendor=AutodebetVendorConst.BCA
        )
        _, _, completed_missions = get_cfs_missions(self.application)
        self.assertIsNone(completed_missions[0].get('multiplier'))
        self.assertEqual(completed_missions[0]['action_code'], 'bca_autodebet')

        self.cfs_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.action,
            progress_status=CfsProgressStatus.CLAIMED,
            repeat_action_no=1,
            cashback_amount=1000,
            extra_data={
                'multiplier': 1.5
            }
        )
        special_missions, on_going_missions, completed_missions = get_cfs_missions(self.application)
        self.assertEqual(len(completed_missions), 1)
        self.assertEqual(len(on_going_missions), 0)
        self.assertEqual(completed_missions[0]['action_code'], 'bca_autodebet')


class TestRecordMonthlyIncome(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(monthly_income=100000)
        self.action = CfsActionFactory(
            id=5,
            is_active=True,
            action_code=CfsActionId.UPLOAD_SALARY_SLIP,
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000,
            app_version='6.0.0',
        )
        self.image = ImageFactory(
            image_type=ImageUploadType.PAYSTUB,
            image_source=self.application.id
        )

    def test_record_monthly_income_value_change(self):
        action_assignment = CfsActionAssignmentFactory(
            customer=self.customer, action=self.action,
            progress_status=CfsProgressStatus.START
        )
        assignment_verification = CfsAssignmentVerificationFactory(
            cfs_action_assignment=action_assignment, verify_status=VerifyStatus.REFUSE
        )
        record_monthly_income_value_change(assignment_verification, 100000, 200000)
        assignment_verification.refresh_from_db()
        expected_record = {
            'monthly_income': {
                'value_old': 100000,
                'value_new': 200000,
            }
        }
        self.assertEqual(assignment_verification.monthly_income, 200000)
        self.assertEqual(expected_record, assignment_verification.extra_data)


class TestEasyIncomeEligible(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(monthly_income=100000)
        self.upload_salary_slip_action = CfsActionFactory(
            id=5,
            is_active=True,
            action_code='upload_salary_slip',
            default_expiry=90,
        )
        self.upload_bank_statement_action = CfsActionFactory(
            id=6,
            is_active=True,
            action_code='upload_bank_statement',
            default_expiry=90,
        )
        self.upload_credit_card = CfsActionFactory(
            id=15,
            is_active=True,
            action_code='upload_credit_card',
            default_expiry=180,
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.CFS,
            parameters={'easy_income_eligible_data_delay_days': 7},
            is_active=True,
        )

    @patch('django.utils.timezone.localtime')
    def test_get_data_easy_income_eligible_and_status_data_table(self, mock_localtime):
        now = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        mock_localtime.return_value = now

        ret_data = get_data_for_easy_income_eligible_and_status(self.customer)
        self.assertFalse(ret_data['is_eligible'])

        easy_income_eligible = EasyIncomeEligibleFactory(
            customer_id=self.customer.id,
            expiry_date=now,
        )
        ret_data = get_data_for_easy_income_eligible_and_status(self.customer)
        self.assertTrue(ret_data['is_eligible'])

        easy_income_eligible.expiry_date = None
        easy_income_eligible.save()
        ret_data = get_data_for_easy_income_eligible_and_status(self.customer)
        self.assertTrue(ret_data['is_eligible'])

        easy_income_eligible.expiry_date = now - timedelta(days=1)
        easy_income_eligible.save()
        ret_data = get_data_for_easy_income_eligible_and_status(self.customer)
        self.assertFalse(ret_data['is_eligible'])

        easy_income_eligible.expiry_date = now + timedelta(days=1)
        easy_income_eligible.save()
        ret_data = get_data_for_easy_income_eligible_and_status(self.customer)
        self.assertTrue(ret_data['is_eligible'])

        easy_income_eligible.customer_id += 1
        easy_income_eligible.save()
        ret_data = get_data_for_easy_income_eligible_and_status(self.customer)
        self.assertFalse(ret_data['is_eligible'])


    @patch('django.utils.timezone.localtime')
    def test_get_data_easy_income_eligible_and_start_status(self, mock_localtime):
        now = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        mock_localtime.return_value = now

        EasyIncomeEligibleFactory(
            customer_id=self.customer.id,
            data_date=now,
        )
        ret_data = get_data_for_easy_income_eligible_and_status(self.customer)
        self.assertTrue(ret_data['is_eligible'])
        self.assertEqual(ret_data['status'], CfsMissionWebStatus.START)


    @patch('django.utils.timezone.localtime')
    def test_get_data_easy_income_eligible_and_in_progress_status(self, mock_localtime):
        now = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        mock_localtime.return_value = now

        EasyIncomeEligibleFactory(
            customer_id=self.customer.id,
            data_date=now,
        )

        upload_bank_statement_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.upload_bank_statement_action,
            repeat_action_no=1,
            cashback_amount=10000,
            progress_status=CfsProgressStatus.PENDING
        )
        CfsAssignmentVerificationFactory(
            cfs_action_assignment=upload_bank_statement_action_assignment
        )
        ret_data = get_data_for_easy_income_eligible_and_status(self.customer)
        self.assertTrue(ret_data['is_eligible'])
        self.assertEqual(ret_data['status'], CfsMissionWebStatus.IN_PROGRESS)

        upload_salary_slip_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.upload_salary_slip_action,
            repeat_action_no=1,
            cashback_amount=5000,
            progress_status=CfsProgressStatus.PENDING
        )
        CfsAssignmentVerificationFactory(
            cfs_action_assignment=upload_salary_slip_action_assignment
        )
        self.assertTrue(ret_data['is_eligible'])
        self.assertEqual(ret_data['status'], CfsMissionWebStatus.IN_PROGRESS)


    @patch('django.utils.timezone.localtime')
    def test_get_data_easy_income_eligible_and_approved_status(self, mock_localtime):
        now = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        mock_localtime.return_value = now

        EasyIncomeEligibleFactory(
            customer_id=self.customer.id,
            data_date=now,
        )

        upload_bank_statement_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.upload_bank_statement_action,
            repeat_action_no=1,
            cashback_amount=10000,
            progress_status=CfsProgressStatus.UNCLAIMED,
            expiry_date=datetime(2024, 6, 10, 0, 0, 0, tzinfo=timezone.utc)
        )
        CfsAssignmentVerificationFactory(
            cfs_action_assignment=upload_bank_statement_action_assignment,
            verify_status=VerifyStatus.APPROVE
        )
        ret_data = get_data_for_easy_income_eligible_and_status(self.customer)
        self.assertFalse(ret_data['is_eligible'])
        self.assertEqual(ret_data['status'], CfsMissionWebStatus.APPROVED)

        upload_salary_slip_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.upload_salary_slip_action,
            repeat_action_no=1,
            cashback_amount=5000,
            progress_status=CfsProgressStatus.UNCLAIMED,
            expiry_date=datetime(2024, 6, 10, 0, 0, 0, tzinfo=timezone.utc)
        )
        CfsAssignmentVerificationFactory(
            cfs_action_assignment=upload_salary_slip_action_assignment,
            verify_status=VerifyStatus.APPROVE
        )
        ret_data = get_data_for_easy_income_eligible_and_status(self.customer)
        self.assertFalse(ret_data['is_eligible'])
        self.assertEqual(ret_data['status'], CfsMissionWebStatus.APPROVED)


    @patch('django.utils.timezone.localtime')
    def test_get_data_easy_income_and_eligible_rejected_status(self, mock_localtime):
        now = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc)
        mock_localtime.return_value = now

        EasyIncomeEligibleFactory(
            customer_id=self.customer.id,
            data_date=now,
        )

        upload_bank_statement_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.upload_bank_statement_action,
            repeat_action_no=1,
            cashback_amount=10000,
            progress_status=CfsProgressStatus.START
        )
        CfsAssignmentVerificationFactory(
            cfs_action_assignment=upload_bank_statement_action_assignment,
            verify_status=VerifyStatus.REFUSE
        )
        ret_data = get_data_for_easy_income_eligible_and_status(self.customer)
        self.assertTrue(ret_data['is_eligible'])
        self.assertEqual(ret_data['status'], CfsMissionWebStatus.START)

        upload_salary_slip_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.upload_salary_slip_action,
            repeat_action_no=1,
            cashback_amount=5000,
            progress_status=CfsProgressStatus.START
        )
        CfsAssignmentVerificationFactory(
            cfs_action_assignment=upload_salary_slip_action_assignment,
            verify_status=VerifyStatus.REFUSE
        )
        ret_data = get_data_for_easy_income_eligible_and_status(self.customer)
        self.assertTrue(ret_data['is_eligible'])
        self.assertEqual(ret_data['status'], CfsMissionWebStatus.START)


class TestPerfiosUrl(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(monthly_income=100000)

    def test_get_perfios_url_success_1(self):
        redirect_url = 'https://dcp.perfios.com/init'
        log_json = json.dumps({"status": "SUCCESS", "redirectUrl": redirect_url})
        BankStatementProviderLogFactory(
            application_id=self.application.id,
            provider='perfios',
            log=log_json,
        )

        url = get_perfios_url(self.application)
        self.assertEqual(url, redirect_url)

    @patch('juloserver.application_flow.services2.bank_statement.Perfios.get_token')
    def test_get_perfios_url_success_2(self, mock_perfios_get_token):
        redirect_url = 'https://dcp.perfios.com/redirect_url'
        mock_perfios_get_token.return_value = redirect_url, None

        url = get_perfios_url(self.application)
        self.assertEqual(url, redirect_url)

    def test_get_perfios_url_fail_1(self):
        redirect_url = 'https://dcp.perfios.com/init'
        log_json = json.dumps({"status": "in_progress", "redirectUrl": redirect_url})
        BankStatementProviderLogFactory(
            application_id=self.application.id,
            provider='perfios',
            log=log_json,
        )

        url = get_perfios_url(self.application)
        self.assertEqual(url, '')

    @patch('juloserver.application_flow.services2.bank_statement.Perfios.get_token')
    def test_get_perfios_url_fail_2(self, mock_perfios_get_token):
        redirect_url = 'https://dcp.perfios.com/init'
        log_json = json.dumps({"status": "SUCCESS", "redirectUrl": redirect_url})
        BankStatementProviderLogFactory(
            application_id=self.application.id,
            provider='aaaa',
            log=log_json,
        )
        mock_perfios_get_token.return_value = '', None

        url = get_perfios_url(self.application)
        self.assertEqual(url, '')
