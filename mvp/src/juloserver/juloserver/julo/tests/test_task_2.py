from __future__ import print_function
from builtins import str
from datetime import datetime, date

import pytz
from mock import patch, ANY

from dateutil.relativedelta import relativedelta
from django.test.testcases import TestCase, override_settings
from datetime import timedelta
from django.utils import timezone

import juloserver.julo.tasks
from juloserver.julo.services import process_application_status_change
from juloserver.julo.tasks import mark_form_partial_expired_subtask

from juloserver.followthemoney.factories import (
    LenderCurrentFactory,
    LenderBucketFactory
)

from juloserver.julo.tests.factories import (
    CustomerFactory,
    LoanFactory,
    PaymentFactory,
    ApplicationFactory,
    OfferFactory,
    ApplicationHistoryFactory,
    DeviceFactory,
    CreditScoreFactory,
    ImageFactory,
    VoiceRecordFactory,
    DocumentFactory,
    PartnerFactory,
    DokuTransactionFactory,
    ProductLineFactory,
    SkiptraceFactory,
    KycRequestFactory,
    SmsHistoryFactory,
    PartnerReportEmailFactory,
    FeatureSettingFactory, WorkflowFactory,
    ExperimentSettingFactory,
    ExperimentFactory, ExperimentTestGroupFactory
)

from juloserver.julo.statuses import LoanStatusCodes
from ..constants import WorkflowConst, FeatureNameConst

from ..models import (
    Payment,
    Application,
    EmailHistory,
    SmsHistory, DashboardBuckets, StatusLookup,

)

from juloserver.utilities.tests.factories import SlackEWABucketFactory

from ..exceptions import JuloException, SmsNotSent

from ..tasks import (
    update_payment_status,
    update_late_fee_amount_task,
    update_payment_amount,
    update_loans_on_141,
    mark_offer_expired,
    mark_sphp_expired_subtask,
    mark_sphp_expired,
    mark_form_partial_expired_subtask,
    mark_form_partial_expired,
    send_submit_document_reminder_am_subtask,
    send_submit_document_reminder_am,
    send_submit_document_reminder_pm,
    send_resubmission_request_reminder_am,
    send_resubmission_request_reminder_pm,
    send_phone_verification_reminder_am_subtask,
    send_phone_verification_reminder_am,
    send_phone_verification_reminder_pm,
    send_accept_offer_reminder_am,
    send_accept_offer_reminder_pm,
    send_sign_sphp_reminder_am,
    send_sign_sphp_reminder_pm,
    upload_image,
    upload_voice_record,
    upload_document,
    create_thumbnail_and_upload,
    expire_application_status,
    trigger_application_status_expiration,
    trigger_send_email_follow_up_daily,
    send_email_follow_up,
    trigger_send_follow_up_email_100_daily,
    send_email_follow_up_100,
    checking_doku_payments_peridically,
    create_application_checklist_async,
    checking_application_checklist,
    trigger_robocall,
    mark_is_robocall_active,
    send_data_to_collateral_partner_async,
    send_pn_etl_done,
    send_sms_update_ptp,
    reminder_activation_code,
    send_resubmission_request_reminder_pn,
    expire_application_status_131,
    reminder_email_application_status_105_subtask,
    reminder_email_application_status_105,
    pn_app_105_subtask,
    scheduled_reminder_push_notif_application_status_105,
    scheduled_application_status_info,
    refresh_crm_dashboard,
    partner_daily_report_mailer,
    scheduling_can_apply,
    execute_can_reapply,
    trigger_send_follow_up_100_on_6_hours_subtask,
    trigger_send_follow_up_100_on_6_hours,
    tasks_assign_collection_agent,
    send_sms_reminder_138_subtask,
    send_email_bni_va_generation_limit_alert,
)
from ...application_flow.constants import JuloOneChangeReason
from juloserver.julo.product_lines import ProductLineCodes


class TestPayment(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.payment = PaymentFactory()
        self.application = ApplicationFactory(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.AXIATA1)
        )
        self.doku_transaction = DokuTransactionFactory()

    @patch('juloserver.julo.tasks.update_payment_status_subtask')
    def test_update_payment_status(self, mock_update_payment_status_subtask):
        today = timezone.localtime(timezone.now()).date()
        self.loan.loan_status_id = 220
        self.loan.save()
        self.payment.loan = self.loan
        self.payment.due_date = today
        self.payment.payment_status_id = 311
        self.payment.save()
        update_payment_status()
        unpaid_payments = Payment.objects.status_tobe_update().exclude(loan__loan_status=LoanStatusCodes.SELL_OFF)
        for unpaid_payment_id in unpaid_payments.values_list("id", flat=True):
            mock_update_payment_status_subtask.delay.assert_called_with(unpaid_payment_id)

    @patch('juloserver.julo.tasks.update_late_fee_amount')
    def test_update_late_fee_amount_task(self, mock_update_late_fee_amount):
        update_late_fee_amount_task(1)
        mock_update_late_fee_amount.assert_called_with(1)

    @patch('juloserver.julo.tasks.update_late_fee_amount_task')
    def test_update_payment_amount(self, mock_update_late_fee_amount_task):
        self.loan.update_safely(application=self.application)
        self.payment.loan = self.loan
        self.payment.due_date = timezone.localtime(timezone.now()).date() - timedelta(days=2)
        self.payment.payment_status_id = 327
        self.payment.save()
        unpaid_payments = Payment.objects.not_paid_active_overdue().values_list("id", flat=True)
        update_payment_amount()
        for unpaid_payment_id in unpaid_payments.values_list("id", flat=True):
            mock_update_late_fee_amount_task.delay.assert_called_with(unpaid_payment_id)

    @patch('juloserver.julo.tasks.update_loan_and_payments')
    def test_update_loans_on_141(self, mock_update_loan_and_payments):
        self.application.application_status_id = 141
        self.application.save()
        self.loan.application = self.application
        self.loan.save()
        update_loans_on_141()
        mock_update_loan_and_payments.assert_called_with(self.application.loan)

    @patch('juloserver.julo.tasks.check_unprocessed_doku_payments')
    def test_checking_doku_payments_peridically(self, mock_check_unprocessed_doku_payments):
        self.doku_transaction.transaction_date = datetime(2020, 12, 1, 0, 0, 0, 0)
        self.doku_transaction.save()
        checking_doku_payments_peridically()
        mock_check_unprocessed_doku_payments.assert_called_with('20201130170000+0000')


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestSphp(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.loan = LoanFactory()
        self.payment = PaymentFactory()
        self.application = ApplicationFactory()
        self.offer = OfferFactory()
        self.apphistory = ApplicationHistoryFactory()
        self.device = DeviceFactory()
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry'
        )
        self.experiment_test_group = ExperimentTestGroupFactory(
            type='application_id',
            value="#nth:-1:1",
            experiment_id=self.experiment.id
        )
        self.mark_expiry_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.JULO_CORE_EXPIRY_MARKS,
            parameters={
                'x105_to_x106': 14,
                'x120_to_x106': 4,
                'x127_to_x106': 100,
                'x155_to_x106': 60,
            }
        )

    @patch('juloserver.julo.tasks.process_application_status_change')
    def test_mark_offer_expired(self, mock_process_application_status_change):
        self.application.application_status_id = 140
        self.application.save()
        self.loan.application = self.application
        self.loan.save()
        self.offer.application = self.application
        self.offer.save()
        mark_offer_expired()
        self.offer.is_accepted = False
        self.offer.offer_exp_date = date.today()
        self.offer.save()
        mark_offer_expired()
        self.offer.offer_exp_date = date.today() - timedelta(days=1)
        self.offer.save()
        mark_offer_expired()
        mock_process_application_status_change.assert_called_with(self.application.id,143,change_reason='system_triggered')

    @patch('juloserver.julo.tasks.process_application_status_change')
    def test_mark_sphp_expired_subtask(self, mock_process_application_status_change):
        mock_exp_date = date.today() - timedelta(days=2)
        self.customer.email = 'test@gmail.com'
        self.customer.save()

        self.application.id = 123123123
        self.application.sphp_exp_date = mock_exp_date
        self.application.customer = self.customer
        self.application.email = self.customer.email
        self.application.save()
        mark_sphp_expired_subtask(123123123, mock_exp_date)
        mock_process_application_status_change.assert_called_with(self.application.id,171,change_reason='system_triggered')

    @patch('juloserver.julo.tasks.mark_sphp_expired_subtask')
    def test_mark_sphp_expired(self, mock_mark_sphp_expired_subtask):
        today = date.today()
        self.application.application_status_id = 160
        self.application.sphp_exp_date = today
        self.application.save()
        mark_sphp_expired()
        mock_mark_sphp_expired_subtask.delay.assert_called_with(self.application.id, today)

    @patch('juloserver.julo.tasks.process_application_status_change')
    def test_mark_form_partial_expired_subtask(self, mock_process_application_status_change):

        update_date = timezone.now() - relativedelta(days=15)
        self.application.application_status_id = 100
        self.credit_score = CreditScoreFactory(
            application_id=self.application.id,
            score='C'
        )
        self.application.save()
        mark_form_partial_expired_subtask(self.application.id, update_date, self.application.application_status_id)
        mock_process_application_status_change.assert_called_with(self.application.id, 106, 'system_triggered')

    @patch('juloserver.julo.tasks.process_application_status_change')
    def test_mark_form_partial_expired_subtask_not_called(self, mock_process_application_status_change):
        update_date = timezone.now()
        self.apphistory.application_id = self.application.id
        self.apphistory.status_new = 100
        self.apphistory.save()
        mark_form_partial_expired_subtask(self.application.id, update_date, self.application.application_status_id)
        mock_process_application_status_change.assert_not_called()

        update_date = timezone.now() - relativedelta(days=13)
        mark_form_partial_expired_subtask(
            self.application.id,
            update_date,
            self.application.application_status_id,
            WorkflowConst.JULO_ONE,
        )
        mock_process_application_status_change.assert_not_called()

    @patch('juloserver.julo.tasks.mark_form_partial_expired_subtask')
    def test_mark_form_partial_expired(self, mock_mark_form_partial_expired_subtask):

        # update_date = timezone.now().date()
        update_date = timezone.now() - relativedelta(days=15)
        self.application.application_status_id = 105
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application.sphp_exp_date = update_date
        self.application.cdate = update_date
        self.application.save()
        mark_form_partial_expired()
        assert mock_mark_form_partial_expired_subtask.delay.called

    @patch('juloserver.julo.tasks.process_application_status_change')
    def test_mark_form_partial_expired_subtask_to_14days(self, mock_process_application_status_change):

        # Testcase updated to accommodate change from 90 days expiration days to 14 days
        update_date = timezone.now() - relativedelta(days=15)
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application.application_status_id = 100
        self.credit_score = CreditScoreFactory(
            application_id=self.application.id,
            score='C'
        )
        self.application.save()

        mark_form_partial_expired_subtask(
            self.application.id,
            update_date,
            self.application.application_status_id,
            WorkflowConst.JULO_ONE,
        )
        mock_process_application_status_change.assert_called_with(self.application.id, 106, 'system_triggered')

        # with flow in application history is exists
        update_date = timezone.now() - relativedelta(days=5)
        self.apphistory.application_id = self.application.id
        self.apphistory.status_new = 100
        self.apphistory.save()
        mark_form_partial_expired_subtask(
            self.application.id,
            update_date,
            self.application.application_status_id,
            WorkflowConst.JULO_ONE,
        )
        mock_process_application_status_change.assert_called_with(self.application.id, 106, 'system_triggered')

    @patch('juloserver.julo.tasks.process_application_status_change')
    def test_mark_form_partial_expired_subtask_to_14days_good_score(self, mock_process_application_status_change):
        update_date = timezone.now() - relativedelta(days=15)
        self.credit_score = CreditScoreFactory(
            application_id=self.application.id,
            score='A'
        )
        self.application.creditscore = self.credit_score
        self.application.save()

        mark_form_partial_expired_subtask(
            self.application.id,
            update_date,
            self.application.application_status_id,
            WorkflowConst.JULO_ONE,
        )

        mock_process_application_status_change.assert_not_called()

    @patch('juloserver.julo.tasks.process_application_status_change')
    def test_moved_mark_form_partial_expired_subtask_case_good_score(self, mock_process_application_status_change):
        update_date = timezone.now() - relativedelta(days=91)
        self.application.application_status_id = 105
        self.credit_score = CreditScoreFactory(
            application_id=self.application.id,
            score='A'
        )
        self.application.save()
        mark_form_partial_expired_subtask(
            self.application.id,
            update_date,
            self.application.application_status_id,
            WorkflowConst.JULO_ONE,
        )
        mock_process_application_status_change.assert_called_with(self.application.id, 106, 'system_triggered')

    @patch('juloserver.julo.tasks.process_application_status_change')
    def test_not_moved_mark_form_partial_expired_subtask_case_good_score(self, mock_process_application_status_change):
        update_date = timezone.now() - relativedelta(days=50)
        self.application.application_status_id = 105
        self.credit_score = CreditScoreFactory(
            application_id=self.application.id,
            score='A'
        )
        mark_form_partial_expired_subtask(
            self.application.id,
            update_date,
            self.application.application_status_id,
            WorkflowConst.JULO_ONE,
        )
        mock_process_application_status_change.assert_not_called()

    @patch('juloserver.julo.tasks.mark_form_partial_expired_subtask.delay')
    def test_moved_mark_form_partial_expired_primary_task(self, mock_subtask):

        # case for application not have workflow
        self.application.application_status_id = 105
        self.application.save()
        self.application.refresh_from_db()
        mark_form_partial_expired()
        mock_subtask.assert_not_called()

        # case if application have workflow
        update_date = timezone.now() - relativedelta(days=15)
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application.cdate = update_date
        self.application.save()
        self.application.refresh_from_db()
        mark_form_partial_expired()
        mock_subtask.assert_called_with(
            self.application.id,
            self.application.udate,
            105,
            WorkflowConst.JULO_ONE,
        )

    @patch('juloserver.julo.tasks.process_application_status_change')
    def test_mark_form_partial_expired_subtask_x120(self, mock_process_application_status_change):
        update_date = timezone.now() - relativedelta(days=1)
        self.application.application_status_id = 120
        self.application.save()
        # self.credit_score = CreditScoreFactory(
        #     application_id=self.application.id,
        #     score='A'
        # )

        mark_form_partial_expired_subtask(
            self.application.id,
            update_date,
            self.application.application_status_id,
            WorkflowConst.JULO_ONE,
        )
        mock_process_application_status_change.assert_not_called()

        update_date = timezone.now() - relativedelta(days=4)
        mark_form_partial_expired_subtask(
            self.application.id,
            update_date,
            self.application.application_status_id,
            WorkflowConst.JULO_ONE,
        )
        mock_process_application_status_change.assert_called_once_with(
            self.application.id,
            106,
            "system_triggered"
        )





@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestRemainder(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.loan = LoanFactory()
        self.payment = PaymentFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.offer = OfferFactory()
        self.apphistory = ApplicationHistoryFactory()
        self.device = DeviceFactory()
        self.creditscore = CreditScoreFactory()

    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_send_submit_document_reminder_am_subtask(self, mock_julo_pn_client):
        self.application.device = self.device
        self.application.save()
        send_submit_document_reminder_am_subtask(self.application.id)
        mock_julo_pn_client.return_value.reminder_upload_document.assert_called_with(self.device.gcm_reg_id,self.application.id)

    @patch('juloserver.julo.tasks.send_submit_document_reminder_am_subtask')
    def test_send_submit_document_reminder_am(self, mock_send_submit_document_reminder_am_subtask):
        self.creditscore.score = 'B'
        self.creditscore.application_id = self.application.id
        self.creditscore.save()

        self.application.application_status_id = 105
        self.application.creditscore = self.creditscore
        self.application.save()

        self.apphistory.application_id = self.application.id
        self.apphistory.status_new = 105
        self.apphistory.cdate = timezone.localtime(timezone.now()) - relativedelta(days=2)
        self.apphistory.save()
        send_submit_document_reminder_am()
        mock_send_submit_document_reminder_am_subtask.delay.assert_called_with(self.application.id)

    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_send_submit_document_reminder_pm(self, mock_julo_pn_client):
        self.creditscore.score = 'B'
        self.creditscore.application_id = self.application.id
        self.creditscore.save()

        self.application.device = self.device
        self.application.application_status_id = 105
        self.application.creditscore = self.creditscore
        self.application.save()

        self.apphistory.application_id = self.application.id
        self.apphistory.status_new = 105
        self.apphistory.cdate = timezone.localtime(timezone.now()) - relativedelta(days=10)
        self.apphistory.save()
        send_submit_document_reminder_pm()
        mock_julo_pn_client.return_value.reminder_upload_document.assert_called_with(self.device.gcm_reg_id,self.application.id)

    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_send_resubmission_request_reminder_am(self, mock_julo_pn_client):
        self.application.device = self.device
        self.application.application_status_id = 131
        self.application.creditscore = self.creditscore
        self.application.save()

        self.apphistory.application_id = self.application.id
        self.apphistory.status_new = 131
        self.apphistory.cdate = timezone.localtime(timezone.now()) - relativedelta(days=2)
        self.apphistory.save()
        send_resubmission_request_reminder_am()
        mock_julo_pn_client.return_value.reminder_docs_resubmission.assert_called_with(self.device.gcm_reg_id,self.application.id)

    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_send_resubmission_request_reminder_pm(self, mock_julo_pn_client):
        self.application.device = self.device
        self.application.application_status_id = 131
        self.application.save()

        self.apphistory.application_id = self.application.id
        self.apphistory.status_new = 131
        self.apphistory.cdate = timezone.localtime(timezone.now()) - relativedelta(days=9)
        self.apphistory.save()
        send_resubmission_request_reminder_pm()
        mock_julo_pn_client.return_value.reminder_docs_resubmission.assert_called_with(self.device.gcm_reg_id,self.application.id)

    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_send_phone_verification_reminder_am_subtask(self, mock_julo_pn_client):
        self.application.device = self.device
        self.application.application_status_id = 138
        self.application.save()

        self.apphistory.application_id = self.application.id
        self.apphistory.status_new = 138
        self.apphistory.cdate = timezone.localtime(timezone.now()) - relativedelta(days=2)
        self.apphistory.save()
        send_phone_verification_reminder_am_subtask(self.application.id, self.device.id, self.device.gcm_reg_id)
        mock_julo_pn_client.return_value.reminder_verification_call_ongoing.assert_called_with(self.device.gcm_reg_id,self.application.id)

    @patch('juloserver.julo.tasks.send_phone_verification_reminder_am_subtask')
    def test_send_phone_verification_reminder_am(self, mock_send_phone_verification_reminder_am_subtask):
        self.application.device = self.device
        self.application.application_status_id = 138
        self.application.save()
        send_phone_verification_reminder_am()
        mock_send_phone_verification_reminder_am_subtask.delay.assert_called_with(self.application.id, self.device.id, self.device.gcm_reg_id)

    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_send_phone_verification_reminder_pm(self, mock_julo_pn_client):
        self.application.device = self.device
        self.application.application_status_id = 138
        self.application.save()

        self.apphistory.application_id = self.application.id
        self.apphistory.status_new = 138
        self.apphistory.cdate = timezone.localtime(timezone.now()) - relativedelta(days=9)
        self.apphistory.save()
        send_phone_verification_reminder_pm()
        mock_julo_pn_client.return_value.reminder_verification_call_ongoing.assert_called_with(self.device.gcm_reg_id,self.application.id)

    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_send_accept_offer_reminder_am(self, mock_julo_pn_client):
        self.application.device = self.device
        self.application.application_status_id = 140
        self.application.save()

        self.apphistory.application_id = self.application.id
        self.apphistory.status_new = 140
        self.apphistory.cdate = timezone.localtime(timezone.now()) - relativedelta(days=2)
        self.apphistory.save()
        send_accept_offer_reminder_am()
        mock_julo_pn_client.return_value.inform_offers_made.assert_called_with(self.application.fullname, self.device.gcm_reg_id,self.application.id)

    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_send_accept_offer_reminder_pm(self, mock_julo_pn_client):
        self.application.device = self.device
        self.application.application_status_id = 140
        self.application.save()

        self.apphistory.application_id = self.application.id
        self.apphistory.status_new = 140
        self.apphistory.cdate = timezone.localtime(timezone.now()) - relativedelta(days=9)
        self.apphistory.save()
        send_accept_offer_reminder_pm()
        mock_julo_pn_client.return_value.inform_offers_made.assert_called_with(self.application.fullname,self.device.gcm_reg_id,self.application.id)

    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_send_sign_sphp_reminder_am(self, mock_julo_pn_client):
        self.application.device = self.device
        self.application.application_status_id = 160
        self.application.save()

        self.apphistory.application_id = self.application.id
        self.apphistory.status_new = 160
        self.apphistory.cdate = timezone.localtime(timezone.now()) - relativedelta(days=2)
        self.apphistory.save()
        send_sign_sphp_reminder_am()
        mock_julo_pn_client.return_value.inform_legal_document.assert_called_with(self.application.fullname,self.device.gcm_reg_id,self.application.id)

    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_send_sign_sphp_reminder_pm(self, mock_julo_pn_client):
        self.application.device = self.device
        self.application.application_status_id = 160
        self.application.save()

        self.apphistory.application_id = self.application.id
        self.apphistory.status_new = 160
        self.apphistory.cdate = timezone.localtime(timezone.now()) - relativedelta(days=9)
        self.apphistory.save()
        send_sign_sphp_reminder_pm()
        mock_julo_pn_client.return_value.inform_legal_document.assert_called_with(self.application.fullname, self.device.gcm_reg_id,self.application.id)


class TestUploadFile(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.image = ImageFactory()
        self.doc = DocumentFactory()
        self.voice_rec = VoiceRecordFactory()
        self.voice_rec_1 = VoiceRecordFactory()
        self.lender_current = LenderCurrentFactory()
        self.lender_bucket = LenderBucketFactory()

    @patch('juloserver.julo.tasks.process_image_upload')
    def test_upload_image(self, mock_process_image_upload):
        upload_image(123123123)
        mock_process_image_upload.assert_called_with(None, True, False)
        upload_image(self.image.id)
        mock_process_image_upload.assert_called_with(self.image, True, False)

    @patch('juloserver.julo.tasks.upload_file_to_oss')
    def test_upload_voice_record(self, mock_upload_file_to_oss):

        self.voice_rec.application_id = self.application.id
        self.voice_rec.tmp_path = './test/test123.zip'
        self.voice_rec.save()
        self.voice_rec_1.application_id = self.application.id
        self.voice_rec_1.save()

        with patch('django.utils.timezone.now') as mock_now:
            now = datetime(2020, 11, 26, tzinfo=pytz.UTC)
            mock_now.return_value = now

            upload_voice_record(self.voice_rec.id)
            self.voice_rec.refresh_from_db()
            time_stamp = now.strftime("%Y-%m-%d_%H:%M:%S")
            dest_name = "cust_{}/application_{}/sphp_{}.{}".format(
                self.customer.id, self.application.id, time_stamp, 'zip'
            )
            mock_upload_file_to_oss.assert_called_with('julofiles-localhost',
                                                       ANY,
                                                       dest_name)

    @patch('juloserver.julo.tasks.upload_file_to_oss')
    def test_upload_document(self, mock_upload_file_to_oss):
        res = upload_document(123123,'./test')
        assert res is None
        self.doc.document_source = 123
        self.doc.save()
        with self.assertRaises(JuloException) as Context:
            upload_document(self.doc.id,'./test',True)
        self.assertTrue('Lender id 123 not found' in str(Context.exception))
        self.doc.document_source = self.lender_current.id
        self.doc.save()
        upload_document(self.doc.id, './test', True)
        self.doc.document_source = 123
        self.doc.save()
        with self.assertRaises(JuloException) as Context:
            upload_document(self.doc.id,'./test', False, True)
        self.assertTrue('LenderBucket id 123 not found' in str(Context.exception))
        self.doc.document_source = self.lender_bucket.id
        self.doc.save()
        upload_document(self.doc.id, './test', False, True)
        self.doc.document_source = 123
        self.doc.save()
        with self.assertRaises(JuloException) as Context:
            upload_document(self.doc.id,'./test', False, False)
        self.assertTrue('Application id 123 not found' in str(Context.exception))
        self.doc.document_source = self.application.id
        self.doc.save()
        print('1',self.doc.url)
        upload_document(self.doc.id, './test', False, False)
        self.doc.refresh_from_db()
        print('2',self.doc.url)

    @patch('juloserver.julo.tasks.process_thumbnail_upload')
    def test_create_thumbnail_and_upload(self, mock_process_thumbnail_upload):
        create_thumbnail_and_upload(self.image)
        mock_process_thumbnail_upload.assert_called_with(self.image)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestApplication(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.loan = LoanFactory()
        self.payment = PaymentFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.apphistory = ApplicationHistoryFactory()
        self.partner = PartnerFactory()
        self.slack_ewa_bucket = SlackEWABucketFactory()
        self.feature_setting = FeatureSettingFactory()

    @patch('juloserver.julo.tasks.process_application_status_change')
    def test_expire_application_status(self, mock_process_application_status_change):
        res = expire_application_status(self.application.id, self.application.status, 123)
        self.apphistory.application_id = self.application.id
        self.apphistory.status_new = 123
        self.apphistory.cdate = '2000-01-01'
        self.apphistory.save()
        assert res is None
        mock_status = {
            'target': 'PARTNER',
            'days': 1,
            'status_old': 321,
            'status_to': 333,

        }
        expire_application_status(self.application.id, 123, mock_status)
        mock_process_application_status_change.assert_called_with(self.application.id,
                                                                  333,'status_expired',
                                                                  note='change_status_from : 321to :333')

    @patch('juloserver.julo.tasks.expire_application_status')
    def test_trigger_application_status_expiration(self, mock_expire_application_status):
        self.application.application_status_id = 141
        self.application.partner = self.partner
        self.application.save()
        trigger_application_status_expiration()
        mock_status = {
            'status_old': 141,
            'status_to': 143,
            'days': 5,
            'target': 'PARTNER'
        }
        mock_expire_application_status.delay.assert_called_with(self.application.id,
                                                                141,
                                                                mock_status)

    @patch('juloserver.julo.tasks.create_application_checklist')
    def test_create_application_checklist_async(self, mock_create_application_checklist):
        create_application_checklist_async(self.application.id)
        mock_create_application_checklist.assert_called_with(self.application)

    @patch('juloserver.julo.tasks.create_application_checklist_async')
    def test_checking_application_checklist(self, mock_create_application_checklist_async):
        self.application.application_status_id = 105
        self.application.save()
        self.application.update_safely(
            udate=timezone.localtime(timezone.now()) - relativedelta(minutes=11))
        self.application.refresh_from_db()
        print('tc udate',self.application.udate)
        checking_application_checklist()
        # assert mock_create_application_checklist_async.delay.called

    @patch('juloserver.julo.tasks.send_data_to_collateral_partner')
    def test_send_data_to_collateral_partner_async(self, mock_send_data_to_collateral_partner):
        send_data_to_collateral_partner_async(self.application.id)
        mock_send_data_to_collateral_partner.assert_called_with(self.application)

    @patch('juloserver.julo.tasks.process_application_status_change')
    @patch('juloserver.julo.tasks.filter_due_dates_by_pub_holiday')
    @patch('juloserver.julo.tasks.filter_due_dates_by_weekend')
    def test_expire_application_status_131(self, mock_filter_due_dates_by_weekend,
                                           mock_filter_due_dates_by_pub_holiday,
                                           mock_process_application_status_change):
        self.mark_expiry_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.JULO_CORE_EXPIRY_MARKS,
            parameters={
                'x131_to_x136': 3
            }
        )
        self.application.application_status_id = 131
        self.application.save()
        expire_application_status_131()
        self.apphistory.application = self.application
        self.apphistory.status_new = 131
        self.apphistory.cdate = timezone.now().date() - timedelta(days=90)
        self.apphistory.save()
        expire_application_status_131()
        mock_process_application_status_change.assert_called_with(self.application.id, 136,
                                                                  'status_expired',
                                                                  note='change_status_from : 131to :136')

        # application is J1
        self.application.application_status_id = 131
        self.application.product_line_id = 1
        self.application.save()
        self.apphistory.application = self.application
        self.apphistory.status_new = 131
        self.apphistory.cdate = timezone.now().date() - timedelta(days=3)
        self.apphistory.save()
        expire_application_status_131()
        mock_process_application_status_change.assert_called_with(
            self.application.id, 136, 'status_expired', note='change_status_from : 131to :136'
        )

        #
        mock_filter_due_dates_by_pub_holiday.side_effect = JuloException()
        res = expire_application_status_131()
        self.assertFalse(res)        # application is GRAB
        self.application.application_status_id = 131
        self.application.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.application.save()
        self.apphistory.application = self.application
        self.apphistory.status_new = 131
        self.apphistory.cdate = timezone.now().date() - timedelta(days=3)
        self.apphistory.save()
        expire_application_status_131()
        mock_process_application_status_change.assert_called_with(
            self.application.id, 136, 'status_expired', note='change_status_from : 131to :136'
        )
        mock_filter_due_dates_by_pub_holiday.side_effect = JuloException()
        res = expire_application_status_131()
        self.assertFalse(res)

    @patch('juloserver.julo.tasks.reminder_email_application_status_105_subtask')
    def test_reminder_email_application_status_105(self, mock_reminder_email_application_status_105_subtask):
        self.application.application_status_id = 105
        self.application.save()
        reminder_email_application_status_105()
        assert mock_reminder_email_application_status_105_subtask.delay.called

    @patch('juloserver.monitors.notifications.get_slack_client')
    def test_scheduled_application_status_info(self, mock_get_slack_client):
        self.slack_ewa_bucket.disable = False
        self.slack_ewa_bucket.save()
        scheduled_application_status_info()


    @patch('juloserver.julo.tasks.trigger_send_follow_up_100_on_6_hours_subtask')
    def test_trigger_send_follow_up_100_on_6_hours(self, mock_trigger_send_follow_up_100_on_6_hours_subtask):
        self.application.application_status_id = 100
        self.application.cdate = timezone.now() - timedelta(hours=7)
        self.application.save()
        trigger_send_follow_up_100_on_6_hours()
        assert mock_trigger_send_follow_up_100_on_6_hours_subtask.delay.called

    @patch('juloserver.julo.tasks.get_agent_service')
    def test_tasks_assign_collection_agent(self, mock_get_agent_service):
        self.feature_setting.feature_name = 'agent_assignment_dpd1_dpd29'
        self.feature_setting.category = 'agent'
        self.feature_setting.is_active = True
        self.feature_setting.save()
        mock_get_agent_service.return_value.get_data_assign_agent.return_value = 'test_payment', 'test_agent', 'test_last_agent'
        tasks_assign_collection_agent()


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestEmail(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.loan = LoanFactory()
        self.payment = PaymentFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.apphistory = ApplicationHistoryFactory()
        self.partner = PartnerFactory()
        self.credit_score = CreditScoreFactory()
        self.partner_report_email = PartnerReportEmailFactory()

    @patch('juloserver.julo.tasks.send_email_follow_up')
    def test_trigger_send_email_follow_up_daily(self, mock_send_email_follow_up):
        self.application.application_status_id = 110
        self.application.save()
        self.apphistory.application_id = self.application.id
        self.apphistory.status_new = 110
        self.apphistory.cdate = timezone.now() - relativedelta(days=3)
        self.apphistory.save()
        trigger_send_email_follow_up_daily()
        mock_send_email_follow_up.delay.assert_called_with(self.application.id)

    @patch('juloserver.julo.tasks.get_julo_email_client')
    def test_send_email_follow_up(self, mock_email_client):
        self.application.application_status_id = 110
        self.application.save()
        res = send_email_follow_up(self.application.id)
        assert res is None
        self.apphistory.application_id = self.application.id
        self.apphistory.status_new = 110
        self.apphistory.change_reason = 'test_change_reason'
        self.apphistory.cdate = timezone.now() - relativedelta(days=3)
        self.apphistory.save()
        mock_header = {
            'X-Message-Id': 'test_x-message-id'
        }
        mock_email_client.return_value.email_notification_110.return_value = 202,mock_header,'subject','msg'
        send_email_follow_up(self.application.id)
        email_hist_obj = EmailHistory.objects.get_or_none(sg_message_id='test_x-message-id',
                                                          template_code='email_notif_110')
        self.assertIsInstance(email_hist_obj,EmailHistory)
        self.application.application_status_id = 138
        self.application.save()
        self.apphistory.application_id = self.application.id
        self.apphistory.status_new = 138
        self.apphistory.save()
        mock_email_client.return_value.email_notification_138.return_value = 202, mock_header, 'subject', 'msg'
        send_email_follow_up(self.application.id)
        email_hist_obj = EmailHistory.objects.get_or_none(sg_message_id='test_x-message-id',
                                                          template_code='email_test_change_reason')
        self.assertIsInstance(email_hist_obj, EmailHistory)

    @patch('juloserver.julo.tasks.send_email_follow_up_100')
    def test_trigger_send_follow_up_email_100_daily(self, mock_send_email_follow_up_100):
        yesterday = timezone.now().date() - relativedelta(days=1)
        self.customer.cdate = yesterday
        self.customer.save()
        self.application.customer = self.customer
        self.application.application_status_id = 100
        self.application.save()
        trigger_send_follow_up_email_100_daily()
        mock_send_email_follow_up_100.delay.assert_called_with(self.customer.id,'100v')

    @patch('juloserver.julo.tasks.get_julo_email_client')
    def test_send_email_follow_up_100(self, mock_email_client):
        self.application.application_status_id = 110
        self.application.save()
        mock_header = {
            'X-Message-Id': 'test_x-message-id'
        }
        mock_email_client.return_value.email_notification_110.return_value = (202,mock_header,'subject','msg')
        send_email_follow_up_100(self.customer.id,'110')
        email_hist_obj = EmailHistory.objects.get_or_none(sg_message_id='test_x-message-id',
                                                          template_code='email_notif_110')
        self.assertIsInstance(email_hist_obj, EmailHistory)

    @patch('juloserver.julo.tasks.get_julo_email_client')
    def test_reminder_email_application_status_105_subtask(self, mock_julo_email_client):
        self.customer.email = 'test@gmail.com'
        self.customer.save()
        self.application.customer = self.customer
        self.application.save()
        reminder_email_application_status_105_subtask(self.application.id)
        self.apphistory.application = self.application
        self.apphistory.status_new = self.application.application_status_id
        self.apphistory.cdate = timezone.now().date() - timedelta(days=1)
        self.apphistory.save()
        reminder_email_application_status_105_subtask(self.application.id)
        self.credit_score.application_id = self.application.id
        self.credit_score.score = 'B-'
        self.credit_score.save()
        mock_header = {
            'X-Message-Id': 'test_x-message-id'
        }
        mock_julo_email_client.return_value.email_reminder_105.return_value = 202,mock_header,'subject','msg'
        reminder_email_application_status_105_subtask(self.application.id)
        email_hist_obj = EmailHistory.objects.get_or_none(sg_message_id='test_x-message-id',
                                                          template_code='email_reminder_105')
        self.assertIsInstance(email_hist_obj, EmailHistory)
        self.customer.email = None
        self.customer.save()
        reminder_email_application_status_105_subtask(self.application.id)

    @patch('juloserver.julo.tasks.get_julo_email_client')
    def test_partner_daily_report_mailer(self, mock_julo_email_client):
        self.partner_report_email.partner = self.partner
        self.partner_report_email.is_active = True
        self.partner_report_email.email_subject = 'test'
        self.partner_report_email.email_content = 'test'
        self.partner_report_email.email_recipients = 'test 123'
        self.partner_report_email.save()
        mock_header = {
            'X-Message-Id': 'test_x-message-id'
        }
        mock_julo_email_client.return_value.email_partner_daily_report.return_value = 202,mock_header
        partner_daily_report_mailer()
        email_hist_obj = EmailHistory.objects.get_or_none(sg_message_id='test_x-message-id',
                                                          template_code='send_email_partner_daily_report')
        self.assertIsInstance(email_hist_obj, EmailHistory)

    @patch('juloserver.julo.tasks.send_sms_135_21year')
    def test_scheduling_can_apply(self, mock_send_sms_135_21year):
        self.customer.can_reapply_date = timezone.now().date()
        self.customer.save()
        self.partner.name = 'test'
        self.partner.save()
        self.application.customer = self.customer
        self.application.partner = self.partner
        self.application.save()
        self.apphistory.application = self.application
        self.apphistory.change_reason = 'application_date_of_birth'
        self.apphistory.save()
        scheduling_can_apply()

    @patch('juloserver.julo.tasks.get_julo_email_client')
    def test_trigger_send_follow_up_100_on_6_hours_subtask(self, mock_julo_email_client):
        mock_header = {
            "X-Message-Id": 'test_x-message-id'
        }
        mock_julo_email_client.return_value.send_email.return_value = 202,{},mock_header
        trigger_send_follow_up_100_on_6_hours_subtask((self.application.id,self.application.email))
        email_hist_obj = EmailHistory.objects.get_or_none(sg_message_id='test_x-message-id',
                                                          template_code='email_notif_100_on_6_hours')
        self.assertIsInstance(email_hist_obj, EmailHistory)

    @patch('juloserver.julo.tasks.get_julo_email_client')
    def test_send_email_bni_va_generation_limit_alert(self, mock_julo_email_client):
        mock_header = {
            "X-Message-Id": 'test_x-message-id'
        }
        mock_julo_email_client.return_value.email_bni_va_generation_limit_alert.return_value = 202,mock_header,"Test Message"
        send_email_bni_va_generation_limit_alert(980000)
        email_hist_obj = EmailHistory.objects.get_or_none(sg_message_id='test_x-message-id',
                                                          template_code='email_bni_va_generation_limit_alert')
        self.assertIsInstance(email_hist_obj, EmailHistory)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestRobocall(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory()
        self.product_line = ProductLineFactory()
        self.payment1 = PaymentFactory()
        self.payment2 = PaymentFactory()
        self.st = SkiptraceFactory()

    @patch('juloserver.julo.tasks.choose_number_to_robocall')
    @patch('juloserver.julo.tasks.get_julo_autodialer_client')
    @patch('juloserver.julo.tasks.get_julo_sentry_client')
    def test_trigger_robocall(self, mock_julo_sentry_client, mock_julo_autodialer_client, mock_choose_number_to_robocall):
        self.product_line.product_line_code = 10
        self.product_line.save()
        self.application.product_line = self.product_line
        self.application.save()
        self.loan.application = self.application
        self.loan.save()
        self.payment1.is_robocall_active = True
        self.payment1.loan = self.loan
        self.payment1.due_date = date.today() + relativedelta(days=3)
        self.payment1.save()
        trigger_robocall()
        mock_choose_number_to_robocall.return_value = ('08123456789', self.st.id)
        trigger_robocall()

    def test_mark_is_robocall_active(self):
        self.payment1.loan = self.loan
        self.payment1.payment_status_id = 330
        self.payment1.payment_number = 2
        self.payment1.save()
        self.payment2.loan = self.loan
        self.payment2.payment_status_id = 330
        self.payment2.payment_number = 2
        self.payment2.save()
        print(self.payment1.is_robocall_active)
        print(self.payment2.is_robocall_active)
        mark_is_robocall_active()
        self.payment1.refresh_from_db()
        self.payment2.refresh_from_db()
        print(self.payment1.is_robocall_active)
        print(self.payment2.is_robocall_active)


class TestPN(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.device = DeviceFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory()
        self.credit_score = CreditScoreFactory()
        self.app_hist = ApplicationHistoryFactory()

    @patch('juloserver.julo.clients.pn.get_julo_nemesys_client')
    def test_send_pn_etl_done(self, mock_get_julo_nemesys_client):
        send_pn_etl_done(self.application.id,True,'B')

    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_send_resubmission_request_reminder_pn(self, mock_julo_pn_client):
        self.application.application_status_id = 131
        self.application.device = self.device
        self.application.save()
        self.app_hist.application_id = self.application.id
        self.app_hist.status_new = 131
        self.app_hist.cdate = timezone.now() - timedelta(hours=30)
        self.app_hist.save()
        send_resubmission_request_reminder_pn()
        mock_julo_pn_client.return_value.reminder_docs_resubmission.assert_called_with(self.device.gcm_reg_id, self.application.id)

    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_pn_app_105_subtask(self, mock_julo_pn_client):
        pn_app_105_subtask(self.application.id, self.device.id, self.device.gcm_reg_id)
        self.credit_score.score = 'B'
        self.credit_score.application = self.application
        self.credit_score.save()
        pn_app_105_subtask(self.application.id, self.device.id, self.device.gcm_reg_id)
        self.credit_score.score = 'b-'
        self.credit_score.application = self.application
        self.credit_score.save()
        pn_app_105_subtask(self.application.id, self.device.id, self.device.gcm_reg_id)
        mock_julo_pn_client.return_value.reminder_app_status_105.assert_called_with(self.device.gcm_reg_id, self.application.id, 'B-')

    @patch('juloserver.julo.tasks.pn_app_105_subtask')
    def test_scheduled_reminder_push_notif_application_status_105(self, mock_pn_app_105_subtask):
        self.application.application_status_id = 105
        self.application.device = self.device
        self.application.udate = timezone.now().date()
        self.application.save()
        scheduled_reminder_push_notif_application_status_105()
        assert mock_pn_app_105_subtask.delay.called


class TestSMS(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory()
        self.payment = PaymentFactory(loan=self.loan)
        self.credit_score = CreditScoreFactory()
        self.kyc_req = KycRequestFactory()
        self.sms_hist = SmsHistoryFactory()
        self.app_hist = ApplicationHistoryFactory()
        self.device = DeviceFactory()

    @patch('juloserver.julo.tasks.create_sms_history')
    @patch('juloserver.julo.tasks.get_julo_sms_client')
    def test_send_sms_update_ptp(self, mock_julo_sms_client, mock_create_sms_hist):
        self.customer.can_notify = False
        self.customer.save()
        self.loan.application = self.application
        self.loan.save()
        self.payment.loan = self.loan
        self.payment.save()
        res = send_sms_update_ptp(self.payment.id)
        self.assertIsNone(res)
        mock_response = {
            'status': '123',
            'message-id': '123',
            'error-text': 'test error',
            'to': '08123456789',
            'julo_sms_vendor': 'test'
        }
        self.customer.can_notify = True
        self.customer.save()
        self.loan.application = self.application
        self.loan.save()
        self.payment.loan = self.loan
        self.payment.save()
        mock_julo_sms_client.return_value.sms_payment_ptp_update.return_value = 'msg', mock_response, 'test_template'
        with self.assertRaises(SmsNotSent) as Context:
            send_sms_update_ptp(self.payment.id)
        assert Context.exception.args[0]['sms_client_method_name'] == 'sms_payment_ptp_update'
        assert Context.exception.args[0]['error_text'] == 'test error'
        mock_response['status'] = '0'
        mock_julo_sms_client.return_value.sms_payment_ptp_update.return_value = 'msg',mock_response,'test_template'
        mock_create_sms_hist.return_value = self.sms_hist
        send_sms_update_ptp(self.payment.id)
        assert mock_create_sms_hist.called

    @patch('juloserver.julo.tasks.logger')
    def test_reminder_activation_code(self, mock_logger):
        self.kyc_req.expiry_time = timezone.now() - timedelta(days=1)
        self.kyc_req.save()
        reminder_activation_code()
        mock_logger.info.assert_called_with(
            {"action": "reminder_activation_code", "message": '2 Hari Lagi'})
        self.kyc_req.expiry_time = timezone.now() - timedelta(days=2)
        self.kyc_req.save()
        reminder_activation_code()
        mock_logger.info.assert_called_with(
            {"action": "reminder_activation_code", "message": '1 Hari Lagi'})
        self.kyc_req.expiry_time = timezone.now() - timedelta(days=3)
        self.kyc_req.save()
        reminder_activation_code()
        mock_logger.info.assert_called_with(
            {"action": "reminder_activation_code", "message":
                'Hari ini E-code Form akan kadarluasa pada jam {} : {} '.format(
                    self.kyc_req.expiry_time.hour, self.kyc_req.expiry_time.minute)})


class TestEntryLevel(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.loan = LoanFactory()
        self.payment = PaymentFactory()
        self.application = ApplicationFactory()
        self.offer = OfferFactory()
        four_days_ago = timezone.now() - relativedelta(days=4)
        self.apphistory = ApplicationHistoryFactory(cdate=four_days_ago,status_new=105)
        self.device = DeviceFactory()
        self.mark_expiry_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.JULO_CORE_EXPIRY_MARKS,
            parameters={
                'x105_to_x106': 14,
                'x120_to_x106': 4,
                'x127_to_x106': 100,
                'x155_to_x106': 60,
            }
        )

    @patch('juloserver.julo.tasks.process_application_status_change')
    def test_mark_form_partial_expired_subtask_case1(self,mock_process_application_status_change):
        self.credit_score = CreditScoreFactory(
            application_id=self.application.id,
            score='B-'
        )
        update_date = timezone.now() - relativedelta(days=91)
        self.application.application_status_id = 105
        application_status = StatusLookup.objects.filter(
            status_code=105
        ).last()
        self.application.application_status = application_status

        self.application.save()
        mark_form_partial_expired_subtask(self.application.id, update_date, self.application.application_status_id)
        mock_process_application_status_change.assert_called_with(self.application.id, 106,'system_triggered')

    @patch('juloserver.julo.tasks.process_application_status_change')
    def test_mark_form_partial_expired_subtask_case2(self, mock_process_application_status_change):
        update_date = timezone.now() - relativedelta(days=4)
        self.application = ApplicationFactory()
        self.credit_score = CreditScoreFactory(
            application_id=self.application.id,
            score='C'
        )
        self.application.application_status_id = 105
        application_status = StatusLookup.objects.filter(
            status_code=105
        ).last()
        self.application.application_status = application_status

        self.application.save()
        mark_form_partial_expired_subtask(self.application.id, update_date, self.application.application_status_id)
        mock_process_application_status_change.assert_not_called()


class TestCanReapplyTask(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.loan = LoanFactory()
        self.payment = PaymentFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.apphistory = ApplicationHistoryFactory()
        self.partner = PartnerFactory()
        self.credit_score = CreditScoreFactory()
        self.partner_report_email = PartnerReportEmailFactory()

        self.customer.can_reapply_date = timezone.now().date()
        self.customer.save()

        self.partner.name = 'test'
        self.partner.save()

        self.application.customer = self.customer
        self.application.partner = self.partner
        self.application.save()

        self.apphistory.application = self.application
        self.apphistory.change_reason = 'application_date_of_birth'
        self.apphistory.save()

    @patch("juloserver.julo.tasks.execute_can_reapply.delay")
    def test_scheduling_can_reapply_call_task(self, mock_execute_can_reapply):
        scheduling_can_apply()
        mock_execute_can_reapply.assert_called_with(self.customer.id)

    @patch("juloserver.julo.tasks.execute_can_reapply.delay")
    def test_execute_can_reapply_today(self, mock_execute_can_reapply):
        # CASE: customer with can_reapply_date = today
        self.customer.can_reapply = False
        self.customer.save()

        scheduling_can_apply()
        mock_execute_can_reapply.assert_called_with(self.customer.id)

        execute_can_reapply(self.customer.id)
        self.customer.refresh_from_db()

        self.assertTrue(self.customer.can_reapply)
        self.assertIsNone(self.customer.disabled_reapply_date)
        self.assertIsNone(self.customer.can_reapply_date)

    @patch("juloserver.julo.tasks.execute_can_reapply.delay")
    def test_execute_can_reapply_yesterday(self, mock_execute_can_reapply):
        # CASE: customer with can_reapply_date = yesterday
        self.customer.can_reapply = False
        self.customer.can_reapply_date = timezone.now().date() - timedelta(days=1)
        self.customer.save()

        scheduling_can_apply()
        mock_execute_can_reapply.assert_called_with(self.customer.id)

        execute_can_reapply(self.customer.id)
        self.customer.refresh_from_db()

        self.assertTrue(self.customer.can_reapply)
        self.assertIsNone(self.customer.disabled_reapply_date)
        self.assertIsNone(self.customer.can_reapply_date)

    @patch("juloserver.julo.tasks.execute_can_reapply.delay")
    def test_execute_can_reapply_tomorrow(self, mock_execute_can_reapply):
        # CASE: customer with can_reapply_date = tomorrow
        self.customer.can_reapply = False
        self.customer.can_reapply_date = timezone.now().date() + timedelta(days=1)
        self.customer.save()

        scheduling_can_apply()
        mock_execute_can_reapply.assert_not_called()

    def test_execute_can_reapply_application_deleted(self):
        # CASE: customer that have application but the application.is_deleted = False
        self.customer.can_reapply = False
        self.customer.save()

        self.application.is_deleted = False
        self.application.save()

        self.apphistory.application = self.application
        self.apphistory.save()

        execute_can_reapply(self.customer.id)
        self.customer.refresh_from_db()

        self.assertTrue(self.customer.can_reapply)
        self.assertIsNone(self.customer.disabled_reapply_date)
        self.assertIsNone(self.customer.can_reapply_date)

        # CASE: customer that have application but the application.is_deleted = True
        self.customer.can_reapply_date = timezone.now().date()
        self.customer.can_reapply = False
        self.customer.save()

        self.application.is_deleted = True
        self.application.save()

        self.apphistory.application = self.application
        self.apphistory.save()

        execute_can_reapply(self.customer.id)
        self.customer.refresh_from_db()

        self.assertTrue(self.customer.can_reapply)
        self.assertIsNone(self.customer.disabled_reapply_date)
        self.assertIsNone(self.customer.can_reapply_date)

        # CASE: customer that have no application history
        self.customer.can_reapply_date = timezone.now().date()
        self.customer.can_reapply = False
        self.customer.save()

        self.application = None
        self.apphistory = None

        execute_can_reapply(self.customer.id)
        self.customer.refresh_from_db()

        self.assertTrue(self.customer.can_reapply)
        self.assertIsNone(self.customer.disabled_reapply_date)
        self.assertIsNone(self.customer.can_reapply_date)
