from __future__ import absolute_import

from unittest.mock import patch
from juloserver.customer_module.constants import AccountDeletionRequestStatuses
from juloserver.customer_module.tests.factories import AccountDeletionRequestFactory

import pytest
import datetime
import mock
from factory import Iterator
from mock import patch, MagicMock

from dateutil.relativedelta import relativedelta
from django.test.testcases import (
    TestCase,
    override_settings
)
from datetime import timedelta
from django.utils import timezone
from juloserver.julo.models import (StatusLookup,
                                    ProductLine,
                                    Application,
                                    Payment,
                                    SignatureVendorLog,
                                    MobileFeatureSetting,
                                    FDCRiskyHistory,
                                    EarlyPaybackOffer,
                                    EmailHistory,
                                    WlLevelConfig,
                                    FDCInquiry,
                                    FDCInquiryRun,
                                    CustomerFieldChange,
                                    ApplicationFieldChange,
                                    AuthUserFieldChange,
                                    CustomerRemoval,
                                    Skiptrace,
                                    CommsRetryFlag
                                    )
from juloserver.julo.services import get_oldest_payment_due
from juloserver.julo.statuses import (
    LoanStatusCodes,
    JuloOneCodes,
    PaymentStatusCodes,
)
from juloserver.julo.tasks import (
    send_automated_comm_sms_j1,
    send_automated_comm_sms_ptp_j1,
    send_automated_comms,
    send_automated_comms_ptp_sms,
    send_automated_robocall,
    update_payment_amount,
    update_late_fee_amount_task,
    record_fdc_risky_history,
    send_automated_comm_pn,
    send_pn_etl_done,
    send_submit_document_reminder_pm,
    run_send_warning_letters,
    run_fdc_api,
    send_manual_pn_for_unsent_moengage_sub_task,
    patch_delete_account,
    update_skiptrace_number,
    update_account_status_of_deleted_customers,
    populate_collection_risk_bucket_list,
    update_collection_risk_bucket_list_passed_minus_11,
)
from juloserver.julo.workflows2.tasks import record_digital_signature, do_advance_ai_id_check_task
from juloserver.julo.clients.centerix import JuloCenterixClient
from juloserver.loan_refinancing.constants import CovidRefinancingConst, Campaign
from juloserver.loan_refinancing.tests.factories import (
    LoanRefinancingRequestFactory, LoanRefinancingRequestCampaignFactory)
from juloserver.streamlined_communication.constant import (
    CommunicationPlatform,
    ExperimentConst,
)
from juloserver.streamlined_communication.models import StreamlinedMessage, \
    StreamlinedCommunication, PnAction

from juloserver.julo.tests.factories import (
    DocumentFactory,
    CreditScoreFactory,
    MobileFeatureSettingFactory,
    PTPFactory,
    PaymentFactory,
    CustomerFactory,
    LoanFactory,
    ApplicationFactory,
    EarlyPaybackOfferFactory,
    EmailHistoryFactory,
    CustomerCampaignParameterFactory,
    CampaignSettingFactory,
    DeviceFactory,
    FeatureSettingFactory,
    FaceRecognitionFactory,
    ProductLineFactory,
    JobTypeFactory,
    ApplicationJ1Factory,
    SmsHistoryFactory,
    StatusLookupFactory,
    SkiptraceFactory,
    WorkflowFactory,
    AuthUserFactory,
    ExperimentSettingFactory,
    CustomerRemovalFactory,
    CollectionRiskVerificationCallListFactory,
    CustomerHighLimitUtilizationFactory,
)
from juloserver.apiv2.models import PdCollectionModelResult
from juloserver.julo.tasks import expire_application_status

from django.test.utils import override_settings

from juloserver.julo.tasks2.campaign_tasks import (schedule_for_dpd_minus_to_centerix,
                                                   send_dpd_minus_to_centerix,
                                                   check_early_payback_offer_data,
                                                   update_data_early_payback_offer_subtask,
                                                   risk_customer_early_payoff_campaign,
                                                   send_email_early_payoff_subtask,
                                                   record_early_payback_offer,
                                                   send_email_early_payoff_campaign_on_8_am,
                                                   send_email_early_payoff_campaign_on_10_am)
from juloserver.julo.management.commands import retroload_early_payback_offer_data
from juloserver.julo.constants import (
    WorkflowConst,
    FeatureNameConst,
    CommsRetryFlagStatus
)
from juloserver.julo.product_lines import ProductLineCodes
from ..services2.advance_ai import AdvanceAiService
from ..tasks import create_accounting_cut_off_date_monthly_entry, inapp_account_deletion_deactivate_account_pending_status
from .factories import ApplicationHistoryFactory
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
    AccountwithApplicationFactory,
    ExperimentGroupFactory,
)
from juloserver.account_payment.tests.factories import (
    OldestUnpaidAccountPaymentFactory,
    AccountPaymentFactory,
)
from ...application_flow.factories import ApplicationTagFactory, ApplicationPathTagStatusFactory
from juloserver.promo.tests.factories import WaivePromoFactory
from juloserver.streamlined_communication.test.factories import (
    HolidayFactory,
    StreamlinedCommunicationFactory,
)
from juloserver.autodebet.tests.factories import AutodebetAccountFactory
from juloserver.api_token.models import ExpiryToken as Token
from unittest.mock import MagicMock as UnitTestMagicMock
from juloserver.account.constants import AccountConstant
from juloserver.minisquad.constants import ExperimentConst as MinisqiadExperimentConstant
from juloserver.julo.exceptions import JuloException
from juloserver.collectionbucket.models import CollectionRiskVerificationCallList


def update_payment_amount():
    unpaid_payments = Payment.objects.not_paid_active().values_list("id", flat=True)

    for unpaid_payment_id in unpaid_payments:
        update_late_fee_amount_task(unpaid_payment_id)
from juloserver.julo.statuses import ApplicationStatusCodes


@pytest.mark.django_db
@override_settings(SUSPEND_SIGNALS=True)
class TestTaskUpdateLateFeeAmount(TestCase):
    def setUp(self):
        self.status_220 = StatusLookup.objects.get(status_code=220)
        self.loan = LoanFactory(loan_status=self.status_220)
        application = Application.objects.get(id=self.loan.application.id)
        application.product_line = ProductLine.objects.get(product_line_code=10)
        application.save()
        self.account = AccountFactory()
        self.account_payment = AccountPaymentFactory(account=self.account)
        for i, payment in enumerate(self.loan.payment_set.all().order_by('due_date')):
            payment.payment_status = self.status_220
            payment.due_date = datetime.datetime.today() + relativedelta(months=i)
            payment.due_date -= relativedelta(days=10)
            payment.account_payment = self.account_payment
            payment.save(update_fields=['payment_status',
                                        'due_date',
                                        'udate',
                                        'account_payment'])

    @patch('juloserver.account.tasks.scheduled_tasks.get_redis_client')
    def test_late_fee_update(self, mock_get_redis_client):
        mock_redis_client = MagicMock()
        mock_lock = MagicMock()
        mock_get_redis_client.return_value = mock_redis_client
        mock_redis_client.lock.return_value = mock_lock
        mock_lock.__enter__.return_value = None
        mock_lock.__exit__.return_value = None
        update_payment_amount()
        first_payment = self.loan.payment_set.all().order_by('due_date')[0]
        self.assertEqual(first_payment.late_fee_applied, 1)
        self.assertNotEqual(first_payment.due_amount, 2250000)
        second_payment = self.loan.payment_set.all().order_by('due_date')[1]
        self.assertEqual(second_payment.late_fee_applied, 0)
        self.assertEqual(second_payment.due_amount, 2250000)

        first_payment.due_date -= relativedelta(days=1)
        first_payment.save(update_fields=['due_date', 'udate'])

        mock_get_redis_client.return_value = mock_redis_client
        mock_redis_client.lock.return_value = mock_lock
        mock_lock.__enter__.return_value = None
        mock_lock.__exit__.return_value = None
        update_payment_amount()
        first_payment = self.loan.payment_set.all().order_by('due_date')[0]
        self.assertEqual(first_payment.late_fee_applied, 1)
        self.assertNotEqual(first_payment.due_amount, 2250000)
        second_payment = self.loan.payment_set.all().order_by('due_date')[1]
        self.assertEqual(second_payment.late_fee_applied, 0)
        self.assertEqual(second_payment.due_amount, 2250000)


@pytest.mark.django_db
class TestTaskRecordSignatureVendorLog(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.application_id = self.loan.application.id
        MobileFeatureSettingFactory()
        document = DocumentFactory()
        self.signature_params_with_document = dict(vendor='Digisign', event='digisign_activation', response_code=201,
                                                   response_string='html', request_string='request string',
                                                   document=document)
        self.signature_params_without_document = dict(vendor='Digisign', event='digisign_activation', response_code=201,
                                                      response_string='html', request_string='request string')

    def test_record_digital_signature_with_document(self):
        before_insert_data = SignatureVendorLog.objects.count()
        record_digital_signature(self.application_id, self.signature_params_with_document)
        after_insert_data = SignatureVendorLog.objects.count()

        self.assertTrue(before_insert_data < after_insert_data)

    def test_record_digital_signature_without_document(self):
        before_insert_data = SignatureVendorLog.objects.count()
        record_digital_signature(self.application_id, self.signature_params_with_document)
        after_insert_data = SignatureVendorLog.objects.count()

        self.assertTrue(before_insert_data < after_insert_data)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestCampaignTask(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.loan = LoanFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.payment = PaymentFactory(loan=self.loan)
        self.early_payback_offer = EarlyPaybackOfferFactory()
        self.email_history = EmailHistoryFactory()
        self.campaign_setting = CampaignSettingFactory()
        WaivePromoFactory(
            loan=self.loan,
            payment=self.payment,
            promo_event_type='RISKY_CUSTOMER_EARLY_PAYOFF',
            remaining_installment_principal=10000,
            remaining_installment_interest=1000,
            remaining_late_fee=0,
        )
        EmailHistoryFactory(
            customer=self.loan.customer,
            payment=self.payment,
            application=self.loan.application,
            status='open',
            sg_message_id='0tP8UYRCS0S5iKV55WP9nQ',
            to_email='ari@julofinance.com',
            subject='promo 30% diskon',
            template_code='email_early_payback_1',
            message_content='diskon',
            cdate=datetime.datetime.today(),
        )
        CustomerCampaignParameterFactory(
            customer=self.loan.customer,
            campaign_setting=self.campaign_setting,
            effective_date=datetime.datetime.today().date(),
        )

    @patch.object(PdCollectionModelResult.objects, 'filter')
    @patch('juloserver.julo.tasks2.campaign_tasks.upload_payment_details')
    def test_schedule_for_dpd_minus_to_centerix_payment_not_found(self, mock_upload_centerix_data, mock_pd_collection_model_result_filter):
        mock_instance = MagicMock()
        del mock_instance.__bool__
        del mock_instance.__nonzero__
        mock_instance.__len__.return_value = 0

        mock_pd_collection_model_result_filter.return_value.order_by.return_value.values_list.return_value = None
        mock_pd_collection_model_result_filter.return_value.order_by.return_value = mock_instance
        schedule_for_dpd_minus_to_centerix()
        assert not mock_upload_centerix_data.called

    @patch.object(PdCollectionModelResult.objects, 'filter')
    @patch('juloserver.julo.tasks2.campaign_tasks.upload_payment_details')
    def test_schedule_for_dpd_minus_to_centerix(self, mock_upload_centerix_data, mock_pd_collection_model_result_filter):
        mock_pd_collection_model_result_filter.return_value.order_by.return_value.values_list.return_value = [self.payment.id]
        schedule_for_dpd_minus_to_centerix()
        mock_upload_centerix_data.assert_has_calls([
            mock.call(mock.ANY, "JULO_T-5_RISKY_CUSTOMERS"),
            mock.call(mock.ANY, "JULO_T-3_RISKY_CUSTOMERS"),
            mock.call(mock.ANY, "JULO_T-1_RISKY_CUSTOMERS")
            ])

    def test_retroload_early_payback_offer_data(self):
        retroload_early_payback_offer_data.Command().handle()
        self.assertEqual(2, EarlyPaybackOffer.objects.count())

    def test_send_dpd_minus_to_centerix(self):
        re = send_dpd_minus_to_centerix(10)
        assert re is None

    @patch('juloserver.julo.tasks2.campaign_tasks.update_data_early_payback_offer_subtask')
    def test_check_early_payback_offer_data_not_found(self, mock_update_data_early_payback_offer_subtask):
        re = check_early_payback_offer_data()
        assert re is None

    def test_update_data_early_payback_offer_subtask_email_history_not_found(self):
        update_data_early_payback_offer_subtask(self.early_payback_offer.id)
        self.assertFalse(self.early_payback_offer.paid_off_indicator)

    def test_check_eligible_early_payoff_campaign(self):
        risk_customer_early_payoff_campaign()
        self.assertEqual(2, EmailHistory.objects.count())

    def test_customer_is_in_r4_spec_campaign_and_early_payoff_campaign(self):
        loan_ref_req_campaign = LoanRefinancingRequestCampaignFactory(
            loan_id=self.loan.id,
            campaign_name=Campaign.R4_SPECIAL_FEB_MAR_20,
            expired_at=(datetime.datetime.today() + timedelta(days=2)).date(),
            status='Success'
        )
        loan_ref_req = LoanRefinancingRequestFactory(
            loan=self.loan,
            status='Expired',
            product_type='R4'
        )
        self.loan.loan_status_id = 230
        self.application.product_line_id = 10
        self.application.save()
        self.loan.application = self.application
        self.loan.save()

        application2 = ApplicationFactory()
        application2.product_line_id = 10
        application2.save()
        loan2 = LoanFactory(application=application2)
        loan2.loan_status_id = 230
        loan2.save()

        risk_customer_early_payoff_campaign()
        self.assertEqual(2, EmailHistory.objects.count())

    @patch('juloserver.julo.tasks2.campaign_tasks.send_email_early_payoff_subtask')
    def test_send_email_early_payoff_campaign_on_8_am(self, mock_send_email):
        # loan_ref_req_campaign is R4 special campaign
        loan_ref_req_campaign = LoanRefinancingRequestCampaignFactory(
            loan_id=self.loan.id,
            campaign_name=Campaign.R4_SPECIAL_FEB_MAR_20,
            expired_at=(datetime.datetime.today() + timedelta(days=2)).date(),
            status='Success'
        )
        customer = CustomerFactory()
        self.loan.customer = customer
        self.loan.loan_status_id = 230
        self.application.product_line_id = 10
        self.application.save()
        self.loan.application = self.application
        self.loan.save()
        customer_campaign_parameter = CustomerCampaignParameterFactory(
            customer=customer,
            effective_date=(datetime.datetime.today()-timedelta(days=7)).date()
        )
        send_email_early_payoff_campaign_on_8_am()
        mock_send_email.delay.assert_not_called()

    @patch('juloserver.julo.tasks2.campaign_tasks.send_email_early_payoff_subtask')
    def test_send_email_early_payoff_campaign_on_10_am(self, mock_send_email):
        # loan_ref_req_campaign is R4 special campaign
        loan_ref_req_campaign = LoanRefinancingRequestCampaignFactory(
            loan_id=self.loan.id,
            campaign_name=Campaign.R4_SPECIAL_FEB_MAR_20,
            expired_at=(datetime.datetime.today() + timedelta(days=2)).date()
        )
        customer = CustomerFactory()
        self.loan.customer = customer
        self.loan.loan_status_id = 230
        self.application.product_line_id = 10
        self.application.save()
        self.loan.application = self.application
        self.loan.save()
        customer_campaign_parameter = CustomerCampaignParameterFactory(
            customer=customer,
            effective_date=(datetime.datetime.today() - timedelta(days=10)).date()
        )
        send_email_early_payoff_campaign_on_10_am()
        mock_send_email.delay.assert_not_called()

    def test_send_email_early_payoff_subtask(self):
        start_promo = datetime.datetime.now().date()
        end_promo = start_promo + relativedelta(days=10)
        send_email_early_payoff_subtask(self.loan.id, start_promo, end_promo, True)
        self.assertEqual(2, EmailHistory.objects.count())

    def test_record_early_payback_offer(self):
        record_early_payback_offer(self.loan.id, 'sent_to_sendgrid')
        self.assertEqual(2, EarlyPaybackOffer.objects.count())


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestFDCTask(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory()
        self.loan = LoanFactory(application=self.application)
        self.payment = PaymentFactory(loan=self.loan)
        self.account = AccountFactory()

    def test_record_fdc_risky_history_not_found(self):
        re = record_fdc_risky_history(1)
        assert re is None

    def test_record_fdc_risky_history_not_found_inactive_loan(self):
        self.loan.update_safely(loan_status_id=LoanStatusCodes.INACTIVE)
        record_fdc_risky_history(self.application.id)
        fdc_risky_history_data = FDCRiskyHistory.objects.count()

    def test_record_fdc_risky_history_found_(self):
        self.loan.update_safely(loan_status_id=LoanStatusCodes.CURRENT)
        record_fdc_risky_history(self.application.id)
        fdc_risky_history_data = FDCRiskyHistory.objects.count()
        self.assertIsNotNone(fdc_risky_history_data)

    @patch('juloserver.julo.tasks.run_fdc_api.retry')
    @patch('juloserver.fdc.services.check_if_fdc_inquiry_exist_filtered_by_date')
    @patch('juloserver.julo.tasks.get_fdc_inquiry_queue_size')
    def test_run_fdc_api(self, mock_check_queue_size, mock_ana_inquiry_check, mock_retry_mechanism):
        FDCInquiryRun.objects.create()
        mock_check_queue_size.return_value = 0
        feature_setting = FeatureSettingFactory()
        feature_setting.feature_name = "fdc_configuration"
        feature_setting.is_active = True
        feature_setting.save()
        self.loan.loan_status = StatusLookup.objects.filter(status_code=LoanStatusCodes.CURRENT).first()
        self.loan.application.product_line.product_line_code = 10
        self.loan.save()
        self.account.status.status_code = JuloOneCodes.ACTIVE
        mock_ana_inquiry_check.return_value.values_list.return_value = True
        run_fdc_api()
        fdc_inquiry_count = FDCInquiry.objects.count()
        self.assertIsNotNone(fdc_inquiry_count)
        self.assertFalse(mock_retry_mechanism.called)


    @patch('juloserver.julo.tasks.timezone.localtime')
    @patch('juloserver.julo.tasks.get_julo_sentry_client')
    @patch('juloserver.julo.tasks.send_slack_bot_message')
    @patch('juloserver.julo.tasks.run_fdc_api.retry')
    @patch('juloserver.julo.tasks.check_if_fdc_inquiry_exist_filtered_by_date')
    @patch('juloserver.julo.tasks.get_fdc_inquiry_queue_size')
    def test_run_fdc_api_retry_mechanism(self, mock_check_queue_size, 
                                         mock_get_fdc_inquiry, 
                                         mock_retry_mechanism, 
                                         mock_slack_notif, 
                                         mock_sentry_client, 
                                         mock_today):
        FDCInquiryRun.objects.create()
        mock_check_queue_size.return_value = 0
        feature_setting = FeatureSettingFactory()
        feature_setting.feature_name = "fdc_configuration"

        feature_setting.parameters = {'outstanding_loan': True}
        feature_setting.is_active = True
        feature_setting.save()
        self.loan.loan_status = StatusLookup.objects.filter(status_code=LoanStatusCodes.CURRENT).first()
        self.loan.application.product_line.product_line_code = 10
        self.loan.save()
        mock_today.return_value = datetime.datetime(2020, 1, 1, 0, 0)
        self.account.status.status_code = JuloOneCodes.ACTIVE

        mock_get_fdc_inquiry.side_effect = JuloException()

        mock_retry_mechanism.side_effect = [JuloException(), JuloException(), JuloException(), JuloException()]
        mock_retry_mechanism.return_value = JuloException()

        with self.assertRaises(JuloException):
            run_fdc_api()

        # mock_get_fdc_inquiry.assert_called()
        mock_retry_mechanism.assert_called_with(exc=mock.ANY, countdown=600)
        # mock_retry_mechanism.assert_called_with(countdown=600, max_retries=3)
        # mock_slack_notif.assert_called_once()


class TestSendAutomatedCommPnTask(TestCase):
    def setUp(self):
        message_pn_with_action_buttons = StreamlinedMessage.objects.create(message_content="Test PN with Action Buttons")
        self.streamlined_communication= StreamlinedCommunication.objects.create(
            type='Payment Reminder',
            communication_platform=CommunicationPlatform.PN,
            template_code='MTL_T0',
            message=message_pn_with_action_buttons,
            product='mtl',
            dpd=5)
        self.pn_action = PnAction.objects.create(
            streamlined_communication=self.streamlined_communication,
            order=1,
            title="Hubungi Kami",
            action="email",
            target="collections@julo.co.id"
        )
        self.customer = CustomerFactory(
            can_notify=True
        )
        self.application = ApplicationFactory()
        self.loan = LoanFactory(application=self.application)
        self.device = DeviceFactory(customer=self.customer)
        application = Application.objects.get(id=self.loan.application.id)
        application.product_line = ProductLine.objects.get(product_line_code=10)
        application.device = self.device
        application.save()
        self.payment = PaymentFactory(loan=self.loan)
        payment = Payment.objects.get(id=self.payment.id)
        payment.due_date = datetime.datetime.today() - timedelta(days=5)
        payment.save()

    @patch('juloserver.julo.tasks.send_automated_comm_pn_subtask')
    @patch('juloserver.julo.tasks.check_payment_is_blocked_comms')
    def test_send_automated_comm_pn(
            self, mock_check_payment_is_blocked_comms, mock_send_automated_comm_pn_subtask):
        mock_check_payment_is_blocked_comms.return_value = False
        response = send_automated_comm_pn(self.streamlined_communication.id)
        assert response == None


class TestStopPNCreditScoreC(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory()
        self.loan = LoanFactory(application=self.application)
        self.payment = PaymentFactory(loan=self.loan)

    def test_send_pn_etl_done(self):
        send_pn_etl_done(self.application.id, 'message', credit_score='C')

    def test_send_submit_document_reminder_pm(self):
        send_submit_document_reminder_pm()


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestWarningLetter(TestCase):
    def setUp(self):
        self.today = timezone.localtime(timezone.now())
        self.loan = LoanFactory()
        wl_data = [
            WlLevelConfig(
                late_installment_count=1, wl_level=1,
            ),
            WlLevelConfig(
                late_installment_count=2,
                wl_level=2,
            ),
            WlLevelConfig(
                late_installment_count=3,
                wl_level=3,
            ),
            WlLevelConfig(
                late_installment_count=4,
                wl_level=4,
            ),
            WlLevelConfig(
                late_installment_count=5,
                wl_level=5,
            ),
            WlLevelConfig(
                late_installment_count=6,
                wl_level=6,
            )
        ]
        WlLevelConfig.objects.bulk_create(wl_data)

    def test_send_warning_letter(self):
        payment = get_oldest_payment_due(self.loan)
        payment.due_date = (timezone.localtime(timezone.now()) - timedelta(days=40)).date()
        payment.payment_number = 1
        payment.payment_status_id = 322
        payment.save()
        cdate = timezone.localtime(timezone.now()) - timedelta(days=2)
        loan_ref = LoanRefinancingRequestFactory(
            loan=self.loan, request_date=cdate.date(),
            status=CovidRefinancingConst.STATUSES.expired,
            expire_in_days=1,
            product_type=CovidRefinancingConst.PRODUCTS.r1
        )
        loan_ref.cdate = cdate
        loan_ref.save()
        run_send_warning_letters.delay()


class TestAccountingDateTask(TestCase):
    def setUp(self):
        pass

    @mock.patch('juloserver.julo.tasks.timezone.localtime')
    def test_create_accounting_cut_off_date_monthly_entry(self, mocked_today):
        mocked_today.return_value = datetime.datetime(2020, 9, 10, 11, 0)
        return_value = create_accounting_cut_off_date_monthly_entry()
        mocked_today.assert_called_once()
        self.assertIsNone(return_value)


class TestExpireApplicationStatus(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=150, status_new=160
        )
        self.application.application_status = StatusLookup.objects.get(status_code=160)

    @mock.patch('juloserver.julo.tasks.process_application_status_change')
    @mock.patch('juloserver.julo.tasks.timezone.localtime')
    def test_expire_application_status(self, mocked_today, mocked_process_change):
        mocked_today.return_value = datetime.datetime(2020, 9, 5, 0, 0)
        mocked_process_change.return_value = None
        self.application.sphp_exp_date = datetime.datetime(2020, 9, 6, 0, 0)
        status = {'days': 3, 'status_old': 160, 'status_to': 171, 'target': 'PARTNER'}
        expire_application_status(self.application.id, self.application.status, status)
        mocked_process_change.assert_called_once()

        mocked_process_change.reset_mock()
        status = {'days': 3, 'status_old': 141, 'status_to': 143, 'target': 'PARTNER'}
        self.application_history.cdate = datetime.datetime(2020, 9, 2, 0, 0)
        self.application_history.save()
        expire_application_status(self.application.id, self.application.status, status)
        mocked_process_change.assert_called_once()


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestDoAdvanceAiIdCheckTask(TestCase):

    def setUp(self) -> None:
        FaceRecognitionFactory(feature_name='face_recognition', is_active=False)
        ApplicationTagFactory(application_tag='is_sonic')
        self.j1 = ProductLineFactory(product_line_code=1)
        self.tag_sonic_1 = ApplicationPathTagStatusFactory(
            application_tag='is_sonic',
            status=1
        )
        self.tag_sonic_0 = ApplicationPathTagStatusFactory(
            application_tag='is_sonic',
            status=0
        )
        FeatureSettingFactory(
            feature_name='advance_ai_id_check',
            category='experiment',
            is_active=True
        )
        self.application = ApplicationFactory()
        self.application.application_status = StatusLookup.objects.filter(status_code=120).last()
        self.application.product_line = self.j1
        self.application.save()
        JobTypeFactory(job_type=self.application.job_type)
        ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=105,
            status_new=120,
        )
        self.credit_score = CreditScoreFactory(application_id=self.application.id)

    @patch('juloserver.julo.workflows2.tasks.run_sonic_model', return_value=None)
    @patch.object(AdvanceAiService, 'run_id_check', return_value='SUCCESS')
    @patch('juloserver.julo.services2.high_score.feature_high_score_full_bypass', return_value=None)
    @patch('juloserver.application_flow.services.is_experiment_application', return_value=True)
    @patch('juloserver.apiv2.services.check_iti_repeat', return_value=True)
    def test_has_is_sonic_1_when_in_pgood_threshold(self, mock_1, mock_2, mock_3, mock_4, mock_5):
        from juloserver.application_flow.models import ApplicationPathTag

        do_advance_ai_id_check_task(self.application.id)

        apt = ApplicationPathTag.objects.filter(
            application_id=self.application.id,
            application_path_tag_status=self.tag_sonic_1
        ).exists()
        self.assertTrue(apt)

    @patch('juloserver.julo.workflows2.tasks.run_sonic_model', return_value=None)
    @patch.object(AdvanceAiService, 'run_id_check', return_value='SUCCESS')
    @patch('juloserver.julo.services2.high_score.feature_high_score_full_bypass', return_value=None)
    @patch('juloserver.application_flow.services.is_experiment_application', return_value=True)
    @patch('juloserver.apiv2.services.check_iti_repeat', return_value=False)
    @patch('juloserver.julo.workflows2.tasks.check_salary_izi_data', return_value=True)
    @patch('juloserver.income_check.services.is_income_in_range', return_value=True)
    def test_has_is_sonic_1_when_below_threshold__has_izi_data__income_in_range(
            self, mock_1, mock_2, mock_3, mock_4, mock_5, mock_6, mock_7
    ):
        from juloserver.application_flow.models import ApplicationPathTag

        do_advance_ai_id_check_task(self.application.id)

        apt = ApplicationPathTag.objects.filter(
            application_id=self.application.id,
            application_path_tag_status=self.tag_sonic_1
        ).exists()
        self.assertTrue(apt)

    @patch(
        'juloserver.partnership.services.services.is_income_in_range_agent_assisted_partner',
        return_value=False,
    )
    @patch(
        'juloserver.partnership.leadgenb2b.onboarding.services.is_income_in_range_leadgen_partner',
        return_value=False,
    )
    @patch('juloserver.julo.workflows2.tasks.run_sonic_model', return_value=None)
    @patch.object(AdvanceAiService, 'run_id_check', return_value='SUCCESS')
    @patch('juloserver.julo.services2.high_score.feature_high_score_full_bypass', return_value=None)
    @patch('juloserver.application_flow.services.is_experiment_application', return_value=True)
    @patch('juloserver.apiv2.services.check_iti_repeat', return_value=False)
    @patch('juloserver.julo.workflows2.tasks.check_salary_izi_data', return_value=True)
    @patch('juloserver.income_check.services.is_income_in_range', return_value=False)
    def test_has_is_sonic_0_when_below_threshold__has_izi_data__income_not_in_range(
        self,
        mock_1,
        mock_2,
        mock_3,
        mock_4,
        mock_5,
        mock_6,
        mock_7,
        mock_8,
        mock_9,
    ):
        from juloserver.application_flow.models import ApplicationPathTag

        do_advance_ai_id_check_task(self.application.id)

        apt = ApplicationPathTag.objects.filter(
            application_id=self.application.id,
            application_path_tag_status=self.tag_sonic_0
        ).exists()
        self.assertTrue(apt)

    @patch('juloserver.julo.workflows2.tasks.run_sonic_model', return_value=None)
    @patch.object(AdvanceAiService, 'run_id_check', return_value='SUCCESS')
    @patch('juloserver.julo.services2.high_score.feature_high_score_full_bypass', return_value=None)
    @patch('juloserver.application_flow.services.is_experiment_application', return_value=True)
    @patch('juloserver.apiv2.services.check_iti_repeat', return_value=False)
    @patch('juloserver.julo.workflows2.tasks.check_salary_izi_data', return_value=False)
    @patch('juloserver.bpjs.services.check_submitted_bpjs', return_value=False)
    @patch('juloserver.boost.services.check_scrapped_bank', return_value=False)
    def test_no_is_sonic_when_below_threshold__no_izi_data(
            self, mock_1, mock_2, mock_3, mock_4, mock_5, mock_6, mock_7, mock_8
    ):
        from juloserver.application_flow.models import ApplicationPathTag
        from juloserver.application_flow.models import ApplicationPathTagStatus

        do_advance_ai_id_check_task(self.application.id)

        # Check has is_sonic with value 1
        apts = ApplicationPathTagStatus.objects.filter(
            application_tag='is_sonic',
            status__in=[0, 1]
        )
        apt = ApplicationPathTag.objects.filter(
            application_id=self.application.id,
            application_path_tag_status__in=apts
        ).exists()

        self.assertFalse(apt)


class TestSendAutomatedComms(TestCase):
    @patch('juloserver.julo.tasks.is_holiday')
    @patch('juloserver.julo.tasks.logger')
    def test_send_automated_comms_on_holiday(self, mock_logger, mock_is_holiday):
        mock_is_holiday.return_value = True
        send_automated_comms()
        mock_logger.info.assert_called_once_with({
            'action': 'streamlined_comms (robocall)',
            'is_holiday': True,
            'message': 'Skip sending robocall due to holiday.'
        })

    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1.apply_async')
    @patch('juloserver.julo.tasks.send_automated_comm_sms.apply_async')
    @patch('juloserver.julo.tasks.mark_voice_account_payment_reminder_grab.delay')
    @patch('juloserver.julo.tasks.mark_voice_payment_reminder.delay')
    def test_send_automated_comms_sms(
        self,
        mock_mark_voice_payment_reminder: UnitTestMagicMock,
        mock_mark_voice_account_payment_reminder_grab: UnitTestMagicMock,
        mock_send_automated_comm_sms,
        mock_send_automated_comm_sms_j1,
    ):
        default_streamlined_comm_data = {
            "communication_platform": CommunicationPlatform.SMS,
            "time_sent": '19:59',
            "is_automated": True,
            "extra_conditions": None,
            "dpd": -1,
            "ptp": None,
        }
        non_account_streamlined_comms = StreamlinedCommunicationFactory.create_batch(
            6,
            **default_streamlined_comm_data,
            product=Iterator([
                'mtl',
                'stl',
                'pedemtl',
                'pedestl',
                'bukalapak',
                'laku6',
            ])
        )
        account_streamlined_comms = StreamlinedCommunicationFactory.create_batch(
            2,
            **default_streamlined_comm_data,
            product=Iterator(['j1', 'jturbo'])
        )

        with patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime.datetime(2023, 1, 1, 2, 0, 0)
            send_automated_comms()

        mock_send_automated_comm_sms.assert_has_calls(
            any_order=True,
            calls=[
                mock.call((non_account_streamlined_comm.id,), countdown=mock.ANY)
                for non_account_streamlined_comm in non_account_streamlined_comms
            ]
        )
        self.assertEqual(6, mock_send_automated_comm_sms.call_count)

        mock_send_automated_comm_sms_j1.assert_has_calls(
            any_order=True,
            calls=[
                mock.call((account_streamlined_comm.id,), countdown=mock.ANY)
                for account_streamlined_comm in account_streamlined_comms
            ]
        )
        self.assertEqual(2, mock_send_automated_comm_sms_j1.call_count)


@patch('juloserver.julo.tasks.send_automated_comm_sms_ptp_j1.apply_async')
@patch('juloserver.julo.tasks.send_automated_comm_sms.apply_async')
class TestSendAutomatedCommsPTPSms(TestCase):
    def setUp(self):
        default_streamlined_comm_data = {
            "communication_platform": CommunicationPlatform.SMS,
            "time_sent": '23:59',
            "is_automated": True,
            "extra_conditions": None,
            "dpd": None,
            "ptp": -1,
        }
        self.non_account_streamlined_comms = StreamlinedCommunicationFactory.create_batch(
            6,
            **default_streamlined_comm_data,
            product=Iterator([
                'mtl',
                'stl',
                'pedemtl',
                'pedestl',
                'bukalapak',
                'laku6',
            ])
        )
        self.account_streamlined_comms = StreamlinedCommunicationFactory.create_batch(
            2,
            **default_streamlined_comm_data,
            product=Iterator(['j1', 'jturbo'])
        )

    def test_send_automated_comms_ptp_sms(
        self,
        mock_send_automated_comm_sms,
        send_automated_comm_sms_ptp_j1,
    ):
        with patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime.datetime(2023, 1, 1, 2, 0, 0)
            send_automated_comms_ptp_sms()

        mock_send_automated_comm_sms.has_calls(
            any_order=True,
            calls=[
                mock.call((non_account_streamlined_comm.id,), countdown=mock.ANY)
                for non_account_streamlined_comm in self.non_account_streamlined_comms
            ]
        )
        self.assertEqual(6, mock_send_automated_comm_sms.call_count)

        send_automated_comm_sms_ptp_j1.has_calls(
            any_order=True,
            calls=[
                mock.call((account_streamlined_comm.id,), countdown=mock.ANY)
                for account_streamlined_comm in self.account_streamlined_comms
            ]
        )
        self.assertEqual(2, send_automated_comm_sms_ptp_j1.call_count)



class TestSendAutomatedRobocall(TestCase):
    def setUp(self):
        self.streamlined_communication = StreamlinedCommunicationFactory(
            template_code='nexmo_robocall_j1_-3',
            attempts=3,
            call_hours='{11:0,12:1,13:0}',
            communication_platform=CommunicationPlatform.ROBOCALL,
            exclude_risky_customer=True,
            function_name="""
                        {send_voice_account_payment_reminder,retry_send_voice_account_payment_reminder1,
                        retry_send_voice_account_payment_reminder2}
                        """,
            dpd=-3,
            is_active=True,
            is_automated=True,
            time_out_duration=30,
            product='nexmo_j1',
            type='Payment Reminder',
            until_paid=False,
            show_in_android=True,
            show_in_web=True,
            partner_selection_action='exclude',
            partner_selection_list=['4', '19', '20', '24', '10', '9', '21', '12',
                                    '17', '22', '23', '27', '45', '28', '25', '11',
                                    '26', '41', '42', '29', '30', '31', '32', '33',
                                    '34', '35', '36', '37', '38', '39', '40', '43',
                                    '44', '46', '1', '53', '56', '55', '58', '60',
                                    '61', '62', '63']
        )

    @patch('juloserver.julo.services2.voice.send_voice_account_payment_reminder.apply_async')
    @patch('juloserver.julo.services2.voice.retry_send_voice_account_payment_reminder1.apply_async')
    @patch('juloserver.julo.services2.voice.retry_send_voice_account_payment_reminder2.apply_async')
    @patch('juloserver.julo.tasks.mark_voice_account_payment_reminder_grab.delay')
    @patch('juloserver.julo.tasks.mark_voice_payment_reminder.delay')
    def test_send_automated_robocall_streamlined_communication_functions_called_correctly(
        self, 
        mock_mark_voice_payment_reminder:UnitTestMagicMock, 
        mock_mark_voice_account_payment_reminder_grab:UnitTestMagicMock,
        mock_retry2, 
        mock_retry1, 
        mock_voice
    ):
        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 1, 12, 0, 0)
        ) as mock_timezone:
            send_automated_robocall()

        self.assertFalse(mock_voice.called)
        self.assertTrue(mock_retry1.called)
        self.assertTrue(mock_retry2.called)
        self.assertEqual(0, mock_voice.call_count)
        self.assertEqual(1, mock_retry1.call_count)
        self.assertEqual(2, mock_retry2.call_count)

    @patch('juloserver.julo.services2.voice.send_voice_account_payment_reminder.apply_async')
    @patch('juloserver.julo.services2.voice.retry_send_voice_account_payment_reminder1.apply_async')
    @patch('juloserver.julo.services2.voice.retry_send_voice_account_payment_reminder2.apply_async')
    @patch('juloserver.julo.tasks.mark_voice_account_payment_reminder_grab.delay')
    @patch('juloserver.julo.tasks.mark_voice_payment_reminder.delay')
    def test_send_automated_robocall_functions_arguments_correct(
        self, 
        mock_mark_voice_payment_reminder:UnitTestMagicMock, 
        mock_mark_voice_account_payment_reminder_grab:UnitTestMagicMock,
        mock_retry2, 
        mock_retry1, 
        mock_voice
    ):
        self.streamlined_communication.call_hours = '{15:1, 16:0, 17:0}'
        self.streamlined_communication.save()

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 1, 12, 0, 0)
        ) as mock_timezone:
            send_automated_robocall()
            mock_voice_args = mock_voice.call_args_list
            mock_retry1_args = mock_retry1.call_args_list
            mock_retry2_args = mock_retry2.call_args_list

        voice_hour = 13
        retry1_hour = 14
        retry2_hour = 15
        for attempt in range(3):
            self.assertTupleEqual(
                (attempt, voice_hour + attempt, [1], self.streamlined_communication.pk),
                mock_voice_args[attempt][0][0])
            self.assertTupleEqual(
                (attempt, retry1_hour + attempt, [1], self.streamlined_communication.pk),
                mock_retry1_args[attempt][0][0])
            self.assertTupleEqual(
                (attempt, retry2_hour + attempt, [1], self.streamlined_communication.pk),
                mock_retry2_args[attempt][0][0])

    @mock.patch('juloserver.julo.tasks.mark_voice_account_payment_reminder_grab.apply_async')
    def test_feature_setting_grab_robocall(self, mocked_marking):
        feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_ROBOCALL_SETTING,
            is_active=True,
            parameters={
                "default": {"outstanding_amount": 100000},
                "mark_schedule": "01:00",
                "robocall_batch_size": 1000}
        )
        streamlined_comms = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.ROBOCALL,
            is_automated=True,
            call_hours='{11:0,12:1,13:0}',
            product='nexmo_grab',
            function_name="""{send_voice_payment_reminder_grab,
                     retry_send_voice_payment_reminder_grab1,'
                     retry_send_voice_payment_reminder_grab2}""",
            dpd=6
        )
        streamlined_comms = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.ROBOCALL,
            is_automated=True,
            call_hours='{11:0,12:1,13:0}',
            product='nexmo_grab',
            function_name="""{send_voice_payment_reminder_grab,
                     retry_send_voice_payment_reminder_grab1,'
                     retry_send_voice_payment_reminder_grab2}""",
            dpd=3
        )
        send_automated_robocall()
        mocked_marking.assert_called()


class TestSendAutomatedCommSmsJ1(TestCase):
    def setUp(self):
        self.status_lookup_190 = StatusLookupFactory(status_code=190)
        self.customer = CustomerFactory(can_notify=True)
        self.product_line = ProductLineFactory(product_line_code=1, product_line_type='J1')
        self.account = AccountwithApplicationFactory(
            customer=self.customer,
            account_lookup=AccountLookupFactory(
                workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE)
            ),
            create_application__customer=self.customer,
            create_application__application_status=self.status_lookup_190
        )
        self.account_payment = AccountPaymentFactory(
            account=self.account,
            due_date=datetime.datetime(2022, 5, 8, 12, 0, 0)
        )
        self.oldest_unpaid_account_payment = OldestUnpaidAccountPaymentFactory(
            account_payment=self.account_payment,
            dpd=-1
        )
        self.oldest_unpaid_account_payment.cdate = datetime.datetime(2022, 5, 7, 12, 0, 0)
        self.oldest_unpaid_account_payment.save()

        self.streamlined_communication = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.SMS,
            template_code='j1_sms_dpd_-1',
            dpd=-1,
            is_automated=True,
            is_active=True,
            time_sent='16:0',
            product='j1'
        )
        self.cashback_exp = ExperimentSettingFactory(
            is_active=False,
            code=MinisqiadExperimentConstant.CASHBACK_NEW_SCHEME,
            is_permanent=False,
            criteria={
                "account_id_tail": {
                    "control": [0, 1, 2, 3, 4],
                    "experiment": [5, 6, 7, 8, 9]
                }
            }
        )

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    @patch('juloserver.julo.tasks.get_existing_autodebet_account')
    def test_send_automated_comm_sms_j1_normal_dpd_with_autodebet_scenarios(
        self, mock_get_autodebet, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        mock_process_sms.return_value = 'Dear customer, you are expected to pay in 1 day.'

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            # is_use_autodebet = True & is_deleted_autodebet = False
            autodebet = AutodebetAccountFactory(account=self.account, is_use_autodebet=True);
            mock_get_autodebet.return_value = autodebet

            streamlined_communication_autodebet = StreamlinedCommunicationFactory(
                communication_platform=CommunicationPlatform.SMS,
                template_code='j1_sms_autodebet_dpd_-1',
                dpd=-1,
                is_automated=True,
                is_active=True,
                time_sent='16:0',
                product='j1'
            )
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                streamlined_communication_autodebet.template_code,
                None,
                is_application=False
            )

            # is_use_autodebet = False & is_deleted_autodebet = False
            mock_subtask.reset_mock()
            autodebet.is_use_autodebet = False
            autodebet.save()
            mock_get_autodebet.return_value = autodebet
            # Flush out the entire table, since its not retry case check
            CommsRetryFlag.objects.all().delete()
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

            # is_use_autodebet = False & is_deleted_autodebet = True
            mock_subtask.reset_mock()
            autodebet.is_deleted_autodebet = True
            autodebet.save()
            mock_get_autodebet.return_value = autodebet
            # Flush out the entire table, since its not retry case check
            CommsRetryFlag.objects.all().delete()
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

            # is_use_autodebet = True & is_deleted_autodebet = True
            mock_subtask.reset_mock()
            autodebet.is_use_autodebet = True
            autodebet.save()
            mock_get_autodebet.return_value = None
            # Flush out the entire table, since its not retry case check
            CommsRetryFlag.objects.all().delete()
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

            # no autodebet
            mock_subtask.reset_mock()
            # Flush out the entire table, since its not retry case check
            CommsRetryFlag.objects.all().delete()
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    @patch('juloserver.julo.tasks.get_existing_autodebet_account')
    def test_send_automated_comm_sms_j1_dpd_lower_upper_expected_account_payment_scenarios(
        self, mock_get_autodebet, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        mock_process_sms.return_value = 'Dear customer, you are expected to pay in 1 day.'
        mock_get_autodebet.return_value = None

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            # dpd normal with dpd lower & dpd normal with dpd upper
            self.streamlined_communication.dpd_lower = -2
            self.streamlined_communication.save()
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

            mock_subtask.reset_mock()
            self.streamlined_communication.dpd_lower = None
            self.streamlined_communication.dpd_upper = 1
            self.streamlined_communication.save()
            # Flush out the entire table, since its not retry case check
            CommsRetryFlag.objects.all().delete()
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

            # only dpd upper
            mock_subtask.reset_mock()
            self.streamlined_communication.dpd = None
            self.streamlined_communication.save()
            # Flush out the entire table, since its not retry case check
            CommsRetryFlag.objects.all().delete()
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_not_called()

            # only dpd lower
            mock_subtask.reset_mock()
            self.streamlined_communication.dpd_upper = None
            self.streamlined_communication.dpd_lower = -2
            self.streamlined_communication.save()
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_not_called()

            # no dpd normal
            mock_subtask.reset_mock()
            self.streamlined_communication.dpd_upper = 1
            self.streamlined_communication.save()
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_not_called()

    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    def test_send_automated_comm_sms_j1_reject_autodebet_template_code(self, mock_subtask):
        streamlined_communication = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.SMS,
            template_code='j1_sms_autodebet_dpd_-1',
            dpd=-1,
            is_automated=True,
            is_active=True,
            time_sent='16:0',
            product='j1'
        )

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            send_automated_comm_sms_j1(streamlined_communication.id)

            mock_subtask.not_called()

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    @patch('juloserver.julo.tasks.get_existing_autodebet_account')
    def test_send_automated_comm_sms_j1_not_application_with_stream_lined_application_status_code(
        self, mock_get_autodebet, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        mock_process_sms.return_value = 'Dear customer, you are expected to pay in 1 day.'
        mock_get_autodebet.return_value = None
        status_lookup = StatusLookupFactory(status_code=170)

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            self.streamlined_communication.status_code = status_lookup
            self.streamlined_communication.save()

            new_customer = CustomerFactory(can_notify=True)
            new_second_customer = CustomerFactory(can_notify=True)
            new_account = AccountwithApplicationFactory(
                customer=new_customer,
                account_lookup=AccountLookupFactory(
                    workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE)
                ),
                create_application__customer=new_customer,
                create_application__product_line=self.product_line
            )
            ApplicationFactory(account=new_account, customer=new_second_customer)
            application = Application.objects.filter(account=new_account)
            for app in application:
                app.application_status = status_lookup
                app.save()
            new_account_payment = AccountPaymentFactory(
                account=new_account,
                due_date=datetime.datetime(2022, 5, 8, 12, 0, 0)
            )
            new_oldest_unpaid_account_payment = OldestUnpaidAccountPaymentFactory(
                account_payment=new_account_payment,
                dpd=-1
            )
            new_oldest_unpaid_account_payment.cdate = datetime.datetime(2022, 5, 7, 12, 0, 0)
            new_oldest_unpaid_account_payment.save()
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                new_account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    @patch('juloserver.julo.tasks.get_existing_autodebet_account')
    def test_send_automated_comm_sms_j1_not_application_with_stream_lined_loan_status_code(
        self, mock_get_autodebet, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        mock_process_sms.return_value = 'Dear customer, you are expected to pay in 1 day.'
        mock_get_autodebet.return_value = None
        status_lookup = StatusLookupFactory(status_code=211)

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            self.streamlined_communication.status_code = status_lookup
            self.streamlined_communication.save()
            LoanFactory.create_batch(2, account=self.account, loan_status=status_lookup)
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    @patch('juloserver.julo.tasks.get_existing_autodebet_account')
    def test_send_automated_comm_sms_j1_not_application_with_stream_lined_payment_status_code(
        self, mock_get_autodebet, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        mock_process_sms.return_value = 'Dear customer, you are expected to pay in 1 day.'
        mock_get_autodebet.return_value = None
        status_lookup = StatusLookupFactory(status_code=311)

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            self.streamlined_communication.status_code = status_lookup
            self.streamlined_communication.save()
            self.account_payment.status = status_lookup
            self.account_payment.save()

            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    def test_send_automated_comm_sms_j1_is_application_with_stream_lined_application_status_code(
        self, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        mock_process_sms.return_value = 'Dear customer, you are expected to pay in 1 day.'
        status_lookup = StatusLookupFactory(status_code=165)
        application = Application.objects.all().last()
        application.application_status = status_lookup
        application.save()
        self.streamlined_communication.status_code = status_lookup
        self.streamlined_communication.save()

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    @patch('juloserver.julo.tasks.get_existing_autodebet_account')
    def test_send_automated_comm_sms_j1_different_product_line(
        self, mock_get_autodebet, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        mock_process_sms.return_value = 'Dear customer, you are expected to pay in 1 day.'
        mock_get_autodebet.return_value = None
        application = Application.objects.filter(account=self.account).last()
        application.product_line = ProductLineFactory(product_line_code=2)
        application.save()

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            send_automated_comm_sms_j1(self.streamlined_communication.id)
            mock_subtask.assert_not_called()

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    @patch('juloserver.julo.tasks.get_existing_autodebet_account')
    def test_send_automated_comm_sms_j1_account_payment_has_active_ptp_record(
        self, mock_get_autodebet, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        mock_process_sms.return_value = 'Dear customer, you are 10 days late in payment.'
        mock_get_autodebet.return_value = None
        self.account_payment.due_date = datetime.datetime(2022, 5, 8)
        self.account_payment.save()
        self.oldest_unpaid_account_payment.dpd = 10
        self.oldest_unpaid_account_payment.cdate = datetime.datetime(2022, 5, 18, 7)
        self.oldest_unpaid_account_payment.save()
        streamlined_communication_dpd_10 = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.SMS,
            template_code='j1_sms_dpd_10',
            dpd=10,
            is_automated=True,
            is_active=True,
            time_sent='16:0',
            product='j1',
            type='Payment Reminder'
        )

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 18, 12, 0, 0)
        ):
            # Account payment has PTP
            ptp = PTPFactory(
                account_payment=self.account_payment,
                account=self.account,
                ptp_status=None,
                ptp_date=datetime.datetime(2022, 5, 17),
                payment=None,
                loan=None
            )
            ptp.cdate = datetime.datetime(2022, 5, 8)
            ptp.save()
            send_automated_comm_sms_j1(streamlined_communication_dpd_10.id)
            mock_subtask.assert_called()
            ptp.delete()
            mock_subtask.reset_mock()

            # Account payment has PTP Not Paid
            ptp_not_paid = PTPFactory(
                account_payment=self.account_payment,
                account=self.account,
                ptp_status='Not Paid',
                ptp_date=datetime.datetime(2022, 5, 18),
                payment=None,
                loan=None
            )
            ptp_not_paid.cdate = datetime.datetime(2022, 5, 6)
            ptp_not_paid.save()
            send_automated_comm_sms_j1(streamlined_communication_dpd_10.id)
            mock_subtask.assert_not_called()
            ptp_not_paid.delete()

            # Account payment has outdated PTP Partial
            ptp_partial = PTPFactory(
                account_payment=self.account_payment,
                account=self.account,
                ptp_status='Partial',
                ptp_date=datetime.datetime(2022, 5, 17),
                payment=None,
                loan=None
            )
            ptp_partial.cdate = datetime.datetime(2022, 5, 6)
            ptp_partial.save()
            # Flush out the entire table, since its not retry case check
            CommsRetryFlag.objects.all().delete()
            send_automated_comm_sms_j1(streamlined_communication_dpd_10.id)
            mock_subtask.assert_called()

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    @patch('juloserver.julo.tasks.get_existing_autodebet_account')
    def test_send_automated_comm_sms_j1_account_payment_has_inactive_ptp_record(
        self, mock_get_autodebet, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        mock_process_sms.return_value = 'Dear customer, you are 10 days late in payment.'
        mock_get_autodebet.return_value = None
        self.account_payment.due_date = datetime.datetime(2022, 5, 8)
        self.account_payment.save()
        self.oldest_unpaid_account_payment.dpd = 10
        self.oldest_unpaid_account_payment.cdate = datetime.datetime(2022, 5, 18, 7)
        self.oldest_unpaid_account_payment.save()
        streamlined_communication_dpd_10 = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.SMS,
            template_code='j1_sms_dpd_10',
            dpd=10,
            is_automated=True,
            is_active=True,
            time_sent='16:0',
            product='j1',
            type='Payment Reminder'
        )

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 18, 12, 0, 0)
        ) as mock_timezone:
            # Account payment has PTP Not Paid
            ptp = PTPFactory(
                account_payment=self.account_payment,
                account=self.account,
                ptp_status='Not Paid',
                ptp_date=datetime.datetime(2022, 5, 16),
                payment=None,
                loan=None
            )
            ptp.cdate = datetime.datetime(2022, 5, 8)
            ptp.save()
            send_automated_comm_sms_j1(streamlined_communication_dpd_10.id)
            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                streamlined_communication_dpd_10.template_code,
                streamlined_communication_dpd_10.type,
                is_application=False
            )

            # Account payment has PTP Paid
            mock_subtask.reset_mock()
            ptp.ptp_status = 'Paid'
            ptp.ptp_date = datetime.datetime(2022, 5, 19)
            ptp.save()
            self.account_payment.status_id = PaymentStatusCodes.PAID_LATE
            self.account_payment.save()
            # Flush out the entire table, since its not retry case check
            CommsRetryFlag.objects.all().delete()
            send_automated_comm_sms_j1(streamlined_communication_dpd_10.id)
            mock_subtask.assert_not_called()

            # Account payment has PTP Not Paid and PTP Partial
            mock_subtask.reset_mock()
            ptp.ptp_status = 'Not Paid'
            ptp.ptp_date = datetime.datetime(2022, 5, 16)
            ptp.cdate = datetime.datetime(2022, 5, 8)
            ptp.save()
            self.account_payment.status_id = PaymentStatusCodes.PAYMENT_DUE_TODAY
            self.account_payment.save()
            ptp_partial = PTPFactory(
                account_payment=self.account_payment,
                account=self.account,
                ptp_status='Partial',
                ptp_date=datetime.datetime(2022, 5, 16),
                payment=None,
                loan=None
            )
            ptp_partial.cdate = datetime.datetime(2022, 5, 17)
            ptp_partial.save()
            # Flush out the entire table, since its not retry case check
            CommsRetryFlag.objects.all().delete()
            send_automated_comm_sms_j1(streamlined_communication_dpd_10.id)
            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                streamlined_communication_dpd_10.template_code,
                streamlined_communication_dpd_10.type,
                is_application=False
            )
            ptp_partial.delete()

            # Account payment has PTP Not Paid and PTP Paid
            mock_subtask.reset_mock()
            ptp.ptp_date = datetime.datetime(2022, 5, 16)
            ptp.save()
            ptp_paid = PTPFactory(
                account_payment=self.account_payment,
                account=self.account,
                ptp_status='Paid',
                ptp_date=datetime.datetime(2022, 5, 16),
                payment=None,
                loan=None
            )
            ptp_paid.cdate = datetime.datetime(2022, 5, 15)
            ptp_paid.save()
            self.account_payment.status_id = PaymentStatusCodes.PAID_ON_TIME
            self.account_payment.save()
            # Flush out the entire table, since its not retry case check
            CommsRetryFlag.objects.all().delete()
            send_automated_comm_sms_j1(streamlined_communication_dpd_10.id)
            mock_subtask.assert_not_called()

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    @patch('juloserver.julo.tasks.get_existing_autodebet_account')
    def test_send_automated_comm_sms_j1_account_payment_has_sms_history(
        self, mock_get_autodebet, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        mock_process_sms.return_value = 'Dear customer, you are expected to pay in 1 day.'
        mock_get_autodebet.return_value = None

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            SmsHistoryFactory(
                account_payment=self.account_payment,
                customer=self.customer,
                template_code=self.streamlined_communication.template_code
            )
            send_automated_comm_sms_j1(self.streamlined_communication.id)
            mock_subtask.assert_not_called()

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    @patch('juloserver.julo.tasks.get_existing_autodebet_account')
    def test_send_automated_comm_sms_j1_account_payment_has_multiple_application(
        self, mock_get_autodebet, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        mock_process_sms.return_value = 'Dear customer, tomorrow is your payment deadline.'
        mock_get_autodebet.return_value = None
        ApplicationFactory(
            customer=self.customer,
            account=self.account
        )
        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            send_automated_comm_sms_j1(self.streamlined_communication.id)
            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    @patch('juloserver.julo.tasks.get_existing_autodebet_account')
    def test_send_automated_comm_sms_j1_normal_dpd_with_take_out_minus_7_experiment(
            self, mock_get_autodebet, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        mock_process_sms.return_value = 'Dear customer, you are expected to pay in 7 day.'
        ExperimentSettingFactory(
            code=ExperimentConst.SMS_MINUS_7_TAKE_OUT_EXPERIMENT,
            name= "sms_-7_take_out_experiment",
            type= "collection",
            criteria= {
                "account_id_tail": {
                    "control_group": [1, 3, 5, 7, 9],
                    "experiment_group": [0, 2, 4, 6, 8]
                },
            },
            start_date="2022-12-01 00:00:00+00",
            end_date="2023-03-01 00:00:00+00",
            is_active=True,
            is_permanent=False
        )
        with patch.object(
                timezone, 'now', return_value=datetime.datetime(2023, 1, 1, 12, 0, 0)
        ) as mock_timezone:
            odd_account = AccountwithApplicationFactory(
                id=9674321,
                customer=CustomerFactory(can_notify=True),
                account_lookup=AccountLookupFactory(
                    workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE)
                ),
                create_application__customer=self.customer,
                create_application__application_status=self.status_lookup_190
            )
            even_account = AccountwithApplicationFactory(
                id=9674322,
                customer=CustomerFactory(can_notify=True),
                account_lookup=AccountLookupFactory(
                    workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE)
                ),
                create_application__customer=self.customer,
                create_application__application_status=self.status_lookup_190
            )
            account_payment_odd_tail = AccountPaymentFactory(
                account=odd_account,
                due_date=datetime.datetime(2023, 1, 8, 12, 0, 0)
            )
            account_payment_even_tail = AccountPaymentFactory(
                account=even_account,
                due_date=datetime.datetime(2023, 1, 8, 12, 0, 0)
            )
            self.oldest_unpaid_account_payment = OldestUnpaidAccountPaymentFactory(
                account_payment=account_payment_odd_tail,
                dpd=-7
            )
            self.oldest_unpaid_account_payment = OldestUnpaidAccountPaymentFactory(
                account_payment=account_payment_even_tail,
                dpd=-7
            )
            # no autodebet
            streamlined_communication_config = StreamlinedCommunicationFactory(
                communication_platform=CommunicationPlatform.SMS,
                template_code='j1_sms_dpd_-7',
                dpd=-7,
                is_automated=True,
                is_active=True,
                time_sent='16:0',
                product='j1'
            )
            send_automated_comm_sms_j1(streamlined_communication_config.id)
            mock_subtask.assert_called_once_with(
                account_payment_odd_tail.id,
                mock_process_sms.return_value,
                streamlined_communication_config.template_code,
                None,
                is_application=False
            )

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    @patch('juloserver.julo.tasks.get_existing_autodebet_account')
    def test_send_automated_comm_sms_j1_for_jturbo_x190_normal_dpd_with_autodebet_scenarios(
        self, mock_get_autodebet, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        self.streamlined_communication.update_safely(
            product='jturbo',
            template_code='jturbo_sms_dpd_-1',
        )
        self.account.update_safely(
            account_lookup=AccountLookupFactory(
                workflow=WorkflowFactory(name=WorkflowConst.JULO_STARTER)
            ),
        )
        application = self.account.application_set.last()
        application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.TURBO)
        )

        mock_process_sms.return_value = 'Dear customer, you are expected to pay in 1 day.'

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            # is_use_autodebet = True & is_deleted_autodebet = False
            autodebet = AutodebetAccountFactory(
                account=self.account, is_use_autodebet=True
                );
            mock_get_autodebet.return_value = autodebet

            streamlined_communication_autodebet = StreamlinedCommunicationFactory(
                communication_platform=CommunicationPlatform.SMS,
                template_code='jturbo_sms_autodebet_dpd_-1',
                dpd=-1,
                is_automated=True,
                is_active=True,
                time_sent='16:0',
                product='jturbo'
            )
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                streamlined_communication_autodebet.template_code,
                None,
                is_application=False
            )

            # is_use_autodebet = False & is_deleted_autodebet = False
            mock_subtask.reset_mock()
            autodebet.is_use_autodebet = False
            autodebet.save()
            mock_get_autodebet.return_value = autodebet
            # Flush out the entire table, since its not retry case check
            CommsRetryFlag.objects.all().delete()
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

            # is_use_autodebet = False & is_deleted_autodebet = True
            mock_subtask.reset_mock()
            autodebet.is_deleted_autodebet = True
            autodebet.save()
            mock_get_autodebet.return_value = autodebet
            # Flush out the entire table, since its not retry case check
            CommsRetryFlag.objects.all().delete()
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

            # is_use_autodebet = True & is_deleted_autodebet = True
            mock_subtask.reset_mock()
            autodebet.is_use_autodebet = True
            autodebet.save()
            mock_get_autodebet.return_value = None
            # Flush out the entire table, since its not retry case check
            CommsRetryFlag.objects.all().delete()
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

            # no autodebet
            mock_subtask.reset_mock()
            # Flush out the entire table, since its not retry case check
            CommsRetryFlag.objects.all().delete()
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    @patch('juloserver.julo.tasks.get_existing_autodebet_account')
    def test_send_automated_comm_sms_j1_for_jturbo_x191(
        self, mock_get_autodebet, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        self.streamlined_communication.update_safely(
            product='jturbo',
            template_code='jturbo_sms_dpd_-1',
        )
        self.account.update_safely(
            account_lookup=AccountLookupFactory(
                workflow=WorkflowFactory(name=WorkflowConst.JULO_STARTER)
            ),
        )
        application = self.account.application_set.last()
        application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.TURBO),
            application_status=StatusLookupFactory(status_code=191)
        )

        mock_process_sms.return_value = 'Dear customer, you are expected to pay in 1 day.'

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            mock_get_autodebet.return_value = None
            send_automated_comm_sms_j1(self.streamlined_communication.id)
            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    @patch('juloserver.julo.tasks.get_existing_autodebet_account')
    def test_send_automated_comm_sms_j1_for_jturbo_x192(
        self, mock_get_autodebet, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        self.streamlined_communication.update_safely(
            product='jturbo',
            template_code='jturbo_sms_dpd_-1',
        )
        self.account.update_safely(
            account_lookup=AccountLookupFactory(
                workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE)
            ),
        )
        application = self.account.application_set.last()
        application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.TURBO),
            application_status=StatusLookupFactory(status_code=192)
        )
        ApplicationJ1Factory(account=self.account,)

        mock_process_sms.return_value = 'Dear customer, you are expected to pay in 1 day.'

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            mock_get_autodebet.return_value = None
            send_automated_comm_sms_j1(self.streamlined_communication.id)
            mock_subtask.assert_not_called()

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    def test_send_automated_comm_sms_j1_retry_mechanism_first_attempt(
        self, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        mock_process_sms.return_value = 'Dear customer, you are expected to pay in 1 day.'
        status_lookup = StatusLookupFactory(status_code=165)
        application = Application.objects.all().last()
        application.application_status = status_lookup
        application.save()
        self.streamlined_communication.status_code = status_lookup
        self.streamlined_communication.save()

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            send_automated_comm_sms_j1(self.streamlined_communication.id)

            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    def test_send_automated_comm_sms_j1_retry_mechanism_skip_retry_for_non_expired_flag(
        self, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        mock_process_sms.return_value = 'Dear customer, you are expected to pay in 1 day.'
        status_lookup = StatusLookupFactory(status_code=165)
        application = Application.objects.all().last()
        application.application_status = status_lookup
        application.save()
        self.streamlined_communication.status_code = status_lookup
        self.streamlined_communication.save()
        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            current_time = timezone.localtime(timezone.now())
            flag_key = 'send_automated_comm_sms_j1:{}'.format(self.streamlined_communication.id)
            retry_flag_obj = CommsRetryFlag.objects.create(
                flag_key=flag_key,
                flag_status=CommsRetryFlagStatus.START,
                expires_at=current_time.replace(hour=20, minute=0, second=0, microsecond=0)
            )
            send_automated_comm_sms_j1(self.streamlined_communication.id)
            mock_subtask.assert_not_called()

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    def test_send_automated_comm_sms_j1_retry_mechanism_retry_for_expired_flag(
        self, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        mock_process_sms.return_value = 'Dear customer, you are expected to pay in 1 day.'
        status_lookup = StatusLookupFactory(status_code=165)
        application = Application.objects.all().last()
        application.application_status = status_lookup
        application.save()
        self.streamlined_communication.status_code = status_lookup
        self.streamlined_communication.save()
        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            current_time = timezone.localtime(timezone.now())
            flag_key = 'send_automated_comm_sms_j1:{}'.format(self.streamlined_communication.id)
            retry_flag_obj = CommsRetryFlag.objects.create(
                flag_key=flag_key,
                flag_status=CommsRetryFlagStatus.ITERATION,
                expires_at=current_time.replace(hour=8, minute=0, second=0, microsecond=0)
            )
            send_automated_comm_sms_j1(self.streamlined_communication.id)
            mock_subtask.assert_called_once_with(
                self.account_payment.id,
                mock_process_sms.return_value,
                self.streamlined_communication.template_code,
                None,
                is_application=False
            )

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_j1_subtask.delay')
    @patch('juloserver.julo.tasks.process_sms_message_j1')
    def test_send_automated_comm_sms_j1_retry_mechanism_skip_retry_for_finished_flag(
        self, mock_process_sms, mock_subtask, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        mock_process_sms.return_value = 'Dear customer, you are expected to pay in 1 day.'
        status_lookup = StatusLookupFactory(status_code=165)
        application = Application.objects.all().last()
        application.application_status = status_lookup
        application.save()
        self.streamlined_communication.status_code = status_lookup
        self.streamlined_communication.save()
        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 5, 7, 12, 0, 0)
        ) as mock_timezone:
            current_time = timezone.localtime(timezone.now())
            flag_key = 'send_automated_comm_sms_j1:{}'.format(self.streamlined_communication.id)
            retry_flag_obj = CommsRetryFlag.objects.create(
                flag_key=flag_key,
                flag_status=CommsRetryFlagStatus.FINISH,
                expires_at=current_time.replace(hour=20, minute=0, second=0, microsecond=0)
            )
            send_automated_comm_sms_j1(self.streamlined_communication.id)
            mock_subtask.assert_not_called()


class TestSendAutomatedCommSmsPTPJ1(TestCase):
    def setUp(self):
        self.streamlined_communication = StreamlinedCommunicationFactory(
            communication_platform='SMS',
            template_code='j1_sms_ptp_-1',
            ptp=-1,
            time_sent='12:3',
            is_active=True,
            product='j1',
            is_automated=True
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.account = AccountwithApplicationFactory(
            create_application__product_line=self.product_line,
            account_lookup=AccountLookupFactory(
                workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE)
            )
        )
        self.account_payment = AccountPaymentFactory(
            account=self.account
        )
        self.ptp = PTPFactory(
            account_payment=self.account_payment,
            account=self.account,
            ptp_status='Not Paid',
            ptp_date=datetime.datetime(2022, 8, 1, 12, 0, 0),
            payment=None,
            loan=None
        )
        self.ptp.cdate = datetime.datetime(2022, 7, 15)
        self.ptp.save()

    @patch('juloserver.julo.tasks.logger')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_ptp_j1_subtask.delay')
    def test_send_automated_sms_ptp_j1_invalid_condition(self, mock_subtask, mock_logger):
        send_automated_comm_sms_ptp_j1(99)
        mock_subtask.assert_not_called()

        self.streamlined_communication.ptp = None
        self.streamlined_communication.save()
        send_automated_comm_sms_ptp_j1(self.streamlined_communication.id)
        mock_logger.info.assert_called_with({
            'action': 'send_automated_comm_sms_ptp_j1',
            'streamlined_comm': self.streamlined_communication,
            'template_code': self.streamlined_communication.template_code,
            'message': 'Dismissed for missing ptp',
        })

        mock_logger.reset_mock()
        self.streamlined_communication.ptp = -1
        self.streamlined_communication.is_automated = False
        self.streamlined_communication.save()
        send_automated_comm_sms_ptp_j1(self.streamlined_communication.id)
        mock_logger.info.assert_called_with({
            'action': 'send_automated_comm_sms_ptp_j1',
            'streamlined_comm': self.streamlined_communication,
            'template_code': self.streamlined_communication.template_code,
            'is_automated': False,
            'message': 'Dismissed for streamline not is_automated',
        })

    @patch('juloserver.julo.tasks.send_automated_comm_sms_ptp_j1_subtask.delay')
    def test_send_automated_sms_ptp_j1_streamlined_product_j1(self, mock_subtask):
        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 7, 31, 12, 0, 0)
        ) as mock_timezone:
            send_automated_comm_sms_ptp_j1(self.streamlined_communication.id)
            mock_subtask.assert_called_once_with(self.account_payment, self.streamlined_communication)

    @patch('juloserver.julo.tasks.send_automated_comm_sms_ptp_j1_subtask.delay')
    def test_send_automated_sms_ptp_j1_streamlined_product_jturbo(self, mock_subtask):
        self.streamlined_communication.update_safely(product='jturbo')
        jturbo_product_line = ProductLineFactory(product_line_code=ProductLineCodes.TURBO)
        account = AccountwithApplicationFactory(
            create_application__product_line=jturbo_product_line,
            account_lookup=AccountLookupFactory(
                workflow=WorkflowFactory(name=WorkflowConst.JULO_STARTER)
            )
        )
        account_payment = AccountPaymentFactory(
            account=account
        )
        ptp = PTPFactory(
            account_payment=account_payment,
            account=account,
            ptp_status='Not Paid',
            ptp_date=datetime.datetime(2022, 8, 1, 12, 0, 0),
            payment=None,
            loan=None
        )
        ptp.cdate = datetime.datetime(2022, 7, 15)
        ptp.save()
        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 7, 31, 12, 0, 0)
        ) as mock_timezone:
            send_automated_comm_sms_ptp_j1(self.streamlined_communication.id)
            mock_subtask.assert_called_once_with(account_payment, self.streamlined_communication)

    @patch('juloserver.julo.tasks.send_automated_comm_sms_ptp_j1_subtask.delay')
    def test_send_automated_sms_ptp_j1_streamlined_product_jturbo_x192(self, mock_subtask):
        self.streamlined_communication.update_safely(product='jturbo')
        jturbo_product_line = ProductLineFactory(product_line_code=ProductLineCodes.TURBO)
        account = AccountwithApplicationFactory(
            account_lookup=AccountLookupFactory(
                workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE)
            ),
            create_application__product_line=jturbo_product_line,
            create_application__application_status=StatusLookupFactory(status_code=192)
        )
        ApplicationJ1Factory(account=account)
        account_payment = AccountPaymentFactory(
            account=account
        )
        ptp = PTPFactory(
            account_payment=account_payment,
            account=account,
            ptp_status='Not Paid',
            ptp_date=datetime.datetime(2022, 8, 1, 12, 0, 0),
            payment=None,
            loan=None
        )
        ptp.cdate = datetime.datetime(2022, 7, 15)
        ptp.save()
        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 7, 31, 12, 0, 0)
        ) as mock_timezone:
            send_automated_comm_sms_ptp_j1(self.streamlined_communication.id)
            mock_subtask.assert_not_called()

    @patch('juloserver.julo.tasks.send_automated_comm_sms_ptp_j1_subtask.delay')
    def test_send_automated_sms_ptp_j1_account_payment_not_ptp(self, mock_subtask):
        self.ptp.delete()

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 7, 31, 12, 0, 0)
        ) as mock_timezone:
            send_automated_comm_sms_ptp_j1(self.streamlined_communication.id)
            mock_subtask.assert_not_called()

    @patch('juloserver.julo.tasks.logger')
    @patch('juloserver.julo.tasks.send_automated_comm_sms_ptp_j1_subtask.delay')
    @patch('juloserver.julo.tasks.is_ptp_payment_already_paid')
    def test_send_automated_sms_ptp_j1_paid_conditions(self, mock_is_ptp, mock_subtask, mock_logger):
        # PTP paid
        self.ptp.ptp_status = 'Paid'
        self.ptp.save()

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 7, 31, 12, 0, 0)
        ) as mock_timezone:
            send_automated_comm_sms_ptp_j1(self.streamlined_communication.id)

            mock_subtask.assert_not_called()
            mock_logger.info.assert_called_once_with({
                'action': 'send_automated_comm_sms_ptp_j1',
                'account_payment_id': self.account_payment.id,
                'message': "ptp already paid",
                'ptp_date': datetime.date(2022, 8, 1)
            })
            mock_is_ptp.assert_called_once_with(
                self.account_payment.id,
                datetime.date(2022, 8, 1),
                is_account_payment=True
            )

        # Account payment paid
        mock_is_ptp.reset_mock()
        self.account_payment.status_id = PaymentStatusCodes.PAID_ON_TIME
        self.account_payment.save()

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 7, 31, 12, 0, 0)
        ) as mock_timezone:
            send_automated_comm_sms_ptp_j1(self.streamlined_communication.id)

            mock_is_ptp.assert_not_called()
            mock_subtask.assert_not_called()

    @patch('juloserver.julo.tasks.send_automated_comm_sms_ptp_j1_subtask.delay')
    def test_send_automated_sms_ptp_j1_ptp_partial(self, mock_subtask):
        PTPFactory(
            account_payment=self.account_payment,
            account=self.account,
            ptp_status='Partial',
            ptp_amount=50000,
            ptp_date=datetime.datetime(2022, 8, 1, 12, 0, 0),
            payment=None,
            loan=None
        )

        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 7, 31, 12, 0, 0)
        ) as mock_timezone:
            send_automated_comm_sms_ptp_j1(self.streamlined_communication.id)
            mock_subtask.assert_called_once_with(self.account_payment, self.streamlined_communication)

    @patch('juloserver.julo.tasks.send_automated_comm_sms_ptp_j1_subtask.delay')
    def test_send_automated_sms_ptp_j1_ptp_anomaly(self, mock_subtask):
        """
        This testcase is to test anomaly in ops.ptp for data with cdate > ptp_date.
        This can be removed if the irregular condition is fixed.
        """
        with patch.object(
            timezone, 'now', return_value=datetime.datetime(2022, 8, 2, 12, 0, 0)
        ) as mock_timezone:
            anomaly_ptp = PTPFactory(
                account_payment=self.account_payment,
                account=self.account,
                ptp_status='Partial',
                ptp_amount=50000,
                ptp_date=datetime.datetime(2022, 8, 1, 12, 0, 0),
                payment=None,
                loan=None
            )
            anomaly_ptp.cdate = datetime.datetime(2022, 8, 2)
            anomaly_ptp.save()

            send_automated_comm_sms_ptp_j1(self.streamlined_communication.id)
            mock_subtask.assert_not_called()


class TestPatchDeleteAccount(TestCase):
    def setUp(self):
        self.user = AuthUserFactory(is_active=False)
        self.token, created = Token.objects.get_or_create(user=self.user)
        self.customer = CustomerFactory(user=self.user, can_reapply=False)
        self.application = ApplicationFactory(customer=self.customer)

        self.user_two = AuthUserFactory(is_active=False)
        self.token_two, created = Token.objects.get_or_create(user=self.user_two)
        self.customer_two = CustomerFactory(user=self.user_two, can_reapply=False)
        self.application_two = ApplicationFactory(customer=self.customer_two)

    def test_patch_delete_account_no_loan(self):

        patch_delete_account()
        self.user.refresh_from_db()
        self.token.refresh_from_db()
        self.customer.refresh_from_db()
        self.application.refresh_from_db()
        self.application_two.refresh_from_db()

        self.assertFalse(self.user.is_active)
        self.assertFalse(self.customer.can_reapply)
        self.assertFalse(self.customer.is_active)
        self.assertTrue(self.application.is_deleted)
        self.assertFalse(self.token.is_active)
        self.assertTrue(
            CustomerFieldChange.objects.filter(
            customer=self.customer,
            field_name='can_reapply',
            new_value=False,
        ).exists())
        self.assertTrue(
            CustomerFieldChange.objects.filter(
            customer=self.customer,
            field_name='is_active',
            new_value=False,
        ).exists())
        self.assertTrue(
            ApplicationFieldChange.objects.filter(
            application=self.application,
            field_name='is_deleted',
            new_value=True,
        ).exists())
        self.assertTrue(
            ApplicationFieldChange.objects.filter(
            application=self.application_two,
            field_name='is_deleted',
            new_value=True,
        ).exists())
        self.assertTrue(
            AuthUserFieldChange.objects.filter(
                user=self.user,
                field_name='is_active',
                new_value=False,
        ).exists())
        self.assertTrue(
            CustomerRemoval.objects.filter(
                customer=self.customer,
                user=self.user,
                reason="Patched using Retroload").exists())

    def test_patch_delete_account_having_loan(self):

        self.loan = LoanFactory(
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LOAN_120DPD))

        self.loan_two = LoanFactory(
            customer=self.customer_two,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT))

        patch_delete_account()

        self.assertFalse(
            CustomerRemoval.objects.filter(
                customer=self.customer,
                user=self.user,
                reason="Patched using Retroload").exists())

        self.assertFalse(
            CustomerRemoval.objects.filter(
                customer=self.customer_two,
                user=self.user_two,
                reason="Patched using Retroload").exists())


class UpdateSkiptraceNumberTest(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(
            customer = self.customer,
            mobile_phone_1 = '+62834567890',
            mobile_phone_2 = '+62834567892'
        )
        self.skiptraces = [SkiptraceFactory(
            customer=self.application.customer,
            contact_source = 'mobile_phone_1',
            phone_number = '+62834567891',
        ),SkiptraceFactory(
            customer=self.application.customer,
            contact_source = 'mobile_phone_2',
            phone_number = '+62834567892',
        )]

    def test_update_skiptrace_number(self):
        application = self.application
        contact_source = 'mobile_phone_1'

        # Call the function to be tested
        update_skiptrace_number(application.id, contact_source,application.mobile_phone_1)

        # Assert that a new Skiptrace object is created with the correct values
        skiptrace = Skiptrace.objects.get(
            customer=application.customer,
            contact_source=contact_source,
            phone_number=application.mobile_phone_1,
        )
        self.assertEqual(skiptrace.phone_number, application.mobile_phone_1)

        # Assert that old Skiptrace objects are updated correctly
        old_skiptraces = Skiptrace.objects.filter(
            customer=application.customer,
            contact_source=contact_source
        ).exclude(id=skiptrace.id)
        for old_skiptrace in old_skiptraces:
            self.assertEqual(old_skiptrace.contact_source, 'old' + contact_source)

    def test_skiptrace_not_created(self):
        application = self.application
        contact_source = 'mobile_phone_2'

        # Call the function to be tested
        update_skiptrace_number(application.id, contact_source,application.mobile_phone_2)

        # Assert that no Skiptrace object is updated
        skiptrace_count = Skiptrace.objects.filter(
            customer=application.customer,
            contact_source='old'+contact_source,
            phone_number=self.skiptraces[1].phone_number
        ).count()
        self.assertEqual(skiptrace_count, 0)
        
        self.assertEqual(self.skiptraces[1].contact_source, contact_source)


class TestUpdateAccountStatusOfDeletedCustomers(TestCase):
    def setUp(self):
        self.user = AuthUserFactory(is_active=False)
        self.token, created = Token.objects.get_or_create(user=self.user, is_active=False)
        self.customer = CustomerFactory(user=self.user, can_reapply=False, is_active=False)
        self.status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active_in_grace)
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_code
        )
        self.application = ApplicationFactory(customer=self.customer, is_deleted=True)
        self.customer_removal = CustomerRemovalFactory(
            customer=self.customer, user=self.user, application=self.application,
            reason="Patched using Retroload")
        
    def test_account_status_x410(self):
        update_account_status_of_deleted_customers()
        self.account.refresh_from_db()
        self.assertEquals(self.account.status_id, AccountConstant.STATUS_CODE.active_in_grace)
    
    def test_account_status_x430(self):
        self.status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.suspended)
        self.account.update_safely(status=self.status_code)
        update_account_status_of_deleted_customers()
        self.account.refresh_from_db()
        self.assertEquals(self.account.status_id, AccountConstant.STATUS_CODE.suspended)

    def test_account_status_x431(self):
        self.status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.deactivated)
        self.account.update_safely(status=self.status_code)
        update_account_status_of_deleted_customers()
        self.account.refresh_from_db()
        self.assertEquals(self.account.status_id, AccountConstant.STATUS_CODE.deactivated)

    def test_account_status_x432(self):
            self.status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.terminated)
            self.account.update_safely(status=self.status_code)
            update_account_status_of_deleted_customers()
            self.account.refresh_from_db()
            self.assertEquals(self.account.status_id, AccountConstant.STATUS_CODE.terminated)

    def test_account_status_x440(self):
            self.status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.fraud_reported)
            self.account.update_safely(status=self.status_code)
            update_account_status_of_deleted_customers()
            self.account.refresh_from_db()
            self.assertEquals(self.account.status_id, AccountConstant.STATUS_CODE.fraud_reported)

    def test_account_status_x441(self):
            self.status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.application_or_friendly_fraud)
            self.account.update_safely(status=self.status_code)
            update_account_status_of_deleted_customers()
            self.account.refresh_from_db()
            self.assertEquals(self.account.status_id, AccountConstant.STATUS_CODE.application_or_friendly_fraud)

    def test_account_status_x420(self):
        self.status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account.update_safely(status=self.status_code)
        update_account_status_of_deleted_customers()
        self.account.refresh_from_db()
        self.assertEquals(self.account.status_id, AccountConstant.STATUS_CODE.deactivated)

    def test_account_status_x420(self):
        self.status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account.update_safely(status=self.status_code)
        self.app_status_code = StatusLookupFactory(status_code=ApplicationStatusCodes.APPLICATION_DENIED)
        self.application.update_safely(application_status=self.app_status_code)
        update_account_status_of_deleted_customers()
        self.account.refresh_from_db()
        self.assertEquals(self.account.status_id, AccountConstant.STATUS_CODE.active)


class TestInappAccountDeletionDeactivateAccountPendingStatus(TestCase):
    @patch('juloserver.julo.tasks.in_app_deletion_customer_requests')
    @patch('juloserver.julo.tasks.ADJUST_AUTO_APPROVE_DATE_RELEASE', new=datetime.date.today() - timedelta(days=21))
    def test_success(self, mock_in_app_deletion_customer_requests):
        now = datetime.date.today()
        mock_in_app_deletion_customer_requests.return_value = None

        adr1 = AccountDeletionRequestFactory(
            request_status=AccountDeletionRequestStatuses.PENDING,
        )
        adr1.cdate = now - timedelta(days=20)
        adr1.save()

        adr2 = AccountDeletionRequestFactory(
            request_status=AccountDeletionRequestStatuses.PENDING,
        )
        adr2.cdate = now - timedelta(days=30)
        adr2.save()

        AccountDeletionRequestFactory(
            request_status=AccountDeletionRequestStatuses.PENDING,
        )

        inapp_account_deletion_deactivate_account_pending_status()
        for arg in mock_in_app_deletion_customer_requests.call_args[0][0]:
            self.assertIn(arg, [adr1, adr2])


class TestCollectionRistBucketList(TestCase):
    def setUp(self):
        self.status_220 = StatusLookup.objects.get(status_code=220)
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.loan = LoanFactory(loan_status=self.status_220, customer=self.customer, account=self.account)
        application = Application.objects.get(id=self.loan.application.id)
        application.product_line = ProductLine.objects.get(product_line_code=10)
        application.save()
        self.application = application
        for i, payment in enumerate(self.loan.payment_set.all().order_by('due_date')):
            payment.payment_status = self.status_220
            payment.due_date = datetime.datetime.today() + relativedelta(months=i)
            payment.due_date -= relativedelta(days=10)
            payment.account_payment = self.account_payment
            payment.save(update_fields=['payment_status',
                                        'due_date',
                                        'udate',
                                        'account_payment'])
        self.customer_high_limit_utilization = CustomerHighLimitUtilizationFactory(customer_id=self.customer.id)

    @patch('juloserver.account.models.Account.get_active_application')
    @patch('juloserver.julo.tasks.batch_pk_query_with_cursor_with_custom_db')
    def test_populate_collection_risk_bucket_list(self, mock_batch_query_cursor, mock_get_active_application):
        mock_batch_query_cursor.return_value = [[self.customer.id]]
        mock_get_active_application.return_value = self.application
        populate_collection_risk_bucket_list()
        self.assertTrue(CollectionRiskVerificationCallList.objects.filter(account=self.account).exists())

    @patch('juloserver.julo.tasks.batch_pk_query_with_cursor_with_custom_db')
    def test_update_collection_risk_bucket_list_passed_minus_11_true(self, mock_batch_query_cursor):
        # update dpd
        dpd_plus_1=timezone.localtime(timezone.now()) - timedelta(days=1)
        self.account_payment.due_date = dpd_plus_1
        self.account_payment.save()
        # create CollectionRiskVerificationCallList
        coll_rist_verif_list = CollectionRiskVerificationCallListFactory(
            customer=self.customer, 
            account=self.account,
            application=self.application,
            account_payment=self.account_payment,
        )

        mock_batch_query_cursor.return_value = [[self.customer.id]]
        update_collection_risk_bucket_list_passed_minus_11()
        coll_rist_verif_list.refresh_from_db()
        self.assertTrue(coll_rist_verif_list.is_passed_minus_11)

    @patch('juloserver.julo.tasks.batch_pk_query_with_cursor_with_custom_db')
    def test_update_collection_risk_bucket_list_passed_minus_11_false(self, mock_batch_query_cursor):
        # update dpd
        dpd_minus_13=timezone.localtime(timezone.now()) + timedelta(days=13)
        self.account_payment.due_date = dpd_minus_13
        self.account_payment.save()
        # create CollectionRiskVerificationCallList
        coll_rist_verif_list = CollectionRiskVerificationCallListFactory(
            customer=self.customer, 
            account=self.account,
            application=self.application,
            account_payment=self.account_payment,
        )

        mock_batch_query_cursor.return_value = [[self.customer.id]]
        update_collection_risk_bucket_list_passed_minus_11()
        coll_rist_verif_list.refresh_from_db()
        self.assertFalse(coll_rist_verif_list.is_passed_minus_11)
