import json
import mock
import time
from django.utils import timezone
from django.test.testcases import TestCase, override_settings
from django.conf import settings
from datetime import date, datetime, timedelta

from juloserver.account.tests.factories import (
    AccountLimitFactory,
    AccountLookupFactory,
    AccountPropertyFactory,
    AccountPropertyHistoryFactory,
    AccountStatusHistoryFactory,
    AccountTransactionFactory,
)
from juloserver.ana_api.models import CustomerSegmentationComms
from juloserver.ana_api.tests.factories import(
    CustomerSegmentationCommsFactory,
    QrisFunnelLastLogFactory,
)
from juloserver.autodebet.tests.factories import (
    AutodebetAccountFactory,
    AutodebetBRITransactionFactory,
    AutodebetAPILogFactory,
)
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.fraud_security.constants import (
    FraudFlagSource,
    FraudFlagTrigger,
    FraudFlagType,
)
from juloserver.fraud_security.tests.factories import FraudFlagFactory
from juloserver.moengage.services.data_constructors import (
    construct_data_for_loan_payment_reminders_event,
    construct_data_for_payment_reminders_event,
    construct_data_for_hi_season_reminders_event,
    construct_data_for_loan_status_reminders_event,
    construct_data_for_loan_status_reminders,
    construct_data_for_application_status_reminders,
    construct_user_attributes_account_level,
    construct_user_attributes_customer_level,
    construct_user_attributes_for_j1_customer,
    construct_application_status_change_event_data_for_j1_customer,
    construct_base_data_for_application_status_change,
    construct_user_attributes_account_level_available_limit_change,
    construct_user_attributes_customer_level_referral_change,
    construct_data_for_account_payment_comms_block,
    construct_user_attributes_for_comms_blocked, construct_data_for_payment_received_event,
    construct_event_attributes_for_promo_code_usage,
    construct_data_for_loan_status_change_j1_event,
    construct_data_for_autodebit_failed_deduction,
    construct_data_to_send_churn_users_to_moengage,
)
from juloserver.moengage.services.parser import parse_stream_data
from juloserver.moengage.services.pn_services import set_data_format_for_pn_streams
from juloserver.moengage.services.use_cases import (
    send_customer_segment_moengage_bulk,
    send_fraud_ato_device_change_event,
    send_julo_financing_event_to_moengage_bulk,
    send_qris_linkage_status_change_to_moengage,
    send_transaction_status_event_to_moengage,
    send_user_attributes_to_moengage_for_tailor_exp,
    update_moengage_for_account_status_change,
    update_moengage_for_loan_payment_reminders_event_bulk,
    update_moengage_for_payment_reminders_event_bulk,
    update_moengage_for_loan_status_reminders_event_bulk,
    update_moengage_for_hi_season_reminders_event_bulk,
    update_moengage_for_loan_status_change,
    update_moengage_for_application_status_change,
    update_moengage_for_payment_status_change,
    update_moengage_for_payment_due_amount_change,
    send_to_moengage,
    update_moengage_for_scheduled_events,
    update_moengage_for_refinancing_request_status_change,
    update_moengage_for_application_status_change_event,
    send_user_attributes_to_moengage_for_available_limit_created,
    send_user_attributes_to_moengage_for_self_referral_code_change,
    send_user_attributes_to_moengage_for_realtime_basis,
    send_event_for_active_loan_to_moengage,
    data_import_moengage_for_loan_status_change_event,
    update_moengage_for_user_linking_status,
    send_event_moengage_for_julo_card_status_change_event,
    send_churn_users_to_moengage_in_bulk_daily,
    send_user_attributes_to_moengage_after_freeze_unfreeze_cashback,
    send_user_attributes_to_moengage_after_graduation_downgrade,
    send_user_attributes_to_moengage_customer_suspended_unsuspended,
    send_loyalty_mission_progress_data_event_to_moengage,
    send_event_jfinancing_verification_status_change,
    send_qris_master_agreement_data_moengage_bulk,
)
from juloserver.moengage.models import (MoengageUpload, MoengageUploadBatch)
from juloserver.moengage.constants import (
    MoengageEventType,
    MoengageTaskStatus,
    MAX_EVENT,
    UpdateFields,
    MoengageLoanStatusEventType,
    MoengageJuloCardStatusEventType,
)
from juloserver.julo.tests.factories import (
    PaymentFactory, ApplicationFactory, StatusLookupFactory, LoanFactory, ApplicationHistoryFactory,
    WorkflowFactory, CreditScoreFactory, CustomerFactory, CommsBlockedFactory, PartnerFactory,
    ChurnUserFactory, ApplicationJ1Factory)
from juloserver.loan_refinancing.tests.factories import LoanRefinancingRequestFactory
from juloserver.moengage.services.get_parameters import get_application_history_cdate, get_credit_score_type
from juloserver.moengage.clients import MoEngageClient
from juloserver.julo.models import ApplicationHistory
from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.moengage.tests.factories import (
    MoengageUploadBatchFactory,
    MoengageUploadFactory,
)
from juloserver.moengage.services.data_constructors import (
    construct_base_data_for_account_payment_status_change)

from juloserver.julo.utils import run_commit_hooks
from juloserver.pn_delivery.models import PNDelivery, PNBlast
from juloserver.pn_delivery.services import update_pn_details_from_moengage_streams, update_pn
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory,
)
from juloserver.partnership.tests.factories import (
    PartnerOriginFactory,
    PartnershipApiLogFactory
)
from juloserver.credit_card.tests.test_views.test_view_api_v1 import (
    create_mock_credit_card_application,
)
from juloserver.credit_card.tests.factiories import CreditCardApplicationHistoryFactory
from juloserver.julo.statuses import CreditCardCodes
from unittest.mock import ANY
from juloserver.moengage.utils import format_money_to_rupiah
from juloserver.julo_financing.tests.factories import (
    JFinancingVerificationFactory,
    JFinancingCheckoutFactory,
)
from juloserver.julo_financing.constants import JFinancingStatus
from juloserver.moengage.exceptions import MoengageTypeNotFound
from juloserver.qris.tests.factories import QrisPartnerLinkageFactory


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestMoengageServices(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.loan = LoanFactory(application=self.application)
        self.payment = PaymentFactory(loan=self.loan)
        self.payment.due_date = datetime.now() - timedelta(days=2)
        self.payment.payment_status_id = 325
        self.payment.due_amount = 10000000
        self.payment.late_fee_amount = 50000
        self.payment.cashback_earned = 40000
        self.payment.save()
        self.payment_ids = [self.payment.id]
        self.moengage_upload_batch1 = MoengageUploadBatch.objects.create(
            type=MoengageEventType.LOAN_PAYMENT_REMINDER,
            data_count=len(self.payment_ids))
        self.moengage_upload_batch2 = MoengageUploadBatch.objects.create(
            type=MoengageEventType.PAYMENT_REMINDER,
            data_count=len(self.payment_ids))
        self.moengage_upload_batch3 = MoengageUploadBatch.objects.create(
            type=MoengageEventType.LOAN_STATUS_CHANGE,
            data_count=len(self.payment_ids))
        self.moengage_upload_batch4 = MoengageUploadBatch.objects.create(
            type=MoengageEventType.HI_SEASON_LOTTERY_REMINDER,
            data_count=len(self.payment_ids))
        self.moengage_upload = MoengageUpload.objects.create(
            type=MoengageEventType.PAYMENT_REMINDER,
            payment_id=self.payment.id,
            loan_id=self.payment.loan.id,
            application_id=self.payment.loan.application_id
        )
        self.loan_ref_req = LoanRefinancingRequestFactory(
            loan=self.loan,
            status='Expired',
            product_type='R4'
        )
        self.status = 120

    def test_construct_data_for_loan_payment_reminders_event(self):
        data = construct_data_for_loan_payment_reminders_event(self.payment.id)
        self.assertIsNotNone(data)

    def test_construct_data_for_payment_reminders_event(self):
        data = construct_data_for_payment_reminders_event(self.payment.id)
        self.assertIsNotNone(data)

    def test_construct_data_for_hi_season_reminders_event(self):
        data = construct_data_for_hi_season_reminders_event(self.payment.id)
        self.assertIsNotNone(data)


    def test_construct_data_for_loan_status_reminders_event(self):
        data = construct_data_for_loan_status_reminders_event(self.payment.id)
        self.assertIsNotNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_update_moengage_for_loan_payment_reminders_event_bulk(self, mocked_client, send_mock):
        data = update_moengage_for_loan_payment_reminders_event_bulk(self.payment_ids,
                                                                     self.moengage_upload_batch1.id)
        send_mock.assert_called_once()
        self.assertIsNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_update_moengage_for_payment_reminders_event_bulk(self, mocked_client, send_mock):
        data = update_moengage_for_payment_reminders_event_bulk(self.payment_ids,
                                                                self.moengage_upload_batch2.id)
        send_mock.assert_called_once()
        self.assertIsNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_update_moengage_for_loan_status_reminders_event_bulk(self, mocked_client, send_mock):
        data = update_moengage_for_loan_status_reminders_event_bulk(self.moengage_upload_batch3.id)
        self.assertIsNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_update_moengage_for_hi_season_reminders_event_bulk(self, mocked_client, send_mock):
        data = update_moengage_for_hi_season_reminders_event_bulk(self.payment_ids,
                                                                  self.moengage_upload_batch4.id)
        send_mock.assert_called_once()
        self.assertIsNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_update_moengage_for_loan_status_change(self, mocked_client):
        data = update_moengage_for_loan_status_change(self.loan.id)
        self.assertIsNone(data)

    def test_construct_data_for_loan_status_reminders(self):
        data = construct_data_for_loan_status_reminders(self.loan)
        self.assertIsNotNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_update_moengage_for_application_status_change(self, mocked_client):
        data = update_moengage_for_application_status_change(self.application.id,  self.status)
        self.assertIsNone(data)

    def test_construct_data_for_application_status_reminders(self):
        data = construct_data_for_application_status_reminders(self.application,  self.status)
        self.assertIsNotNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_update_moengage_for_refinancing_request_status_change(self, mocked_client):
        data = update_moengage_for_refinancing_request_status_change(self.loan_ref_req.id)
        self.assertIsNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_update_moengage_for_payment_status_change(self, mocked_client):
        data = update_moengage_for_payment_status_change(self.payment.id)
        self.assertIsNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    def test_update_moengage_for_payment_due_amount_change(self, mocked_client):
        data = update_moengage_for_payment_due_amount_change(self.payment.id, 0)
        self.assertIsNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.update_moengage_for_loan_payment_reminders_event_bulk')
    @mock.patch('juloserver.moengage.services.use_cases.update_moengage_for_payment_reminders_event_bulk')
    @mock.patch('juloserver.moengage.services.use_cases.update_moengage_for_loan_status_reminders_event_bulk')
    @mock.patch('juloserver.moengage.services.use_cases.update_moengage_for_hi_season_reminders_event_bulk')
    def test_update_moengage_for_scheduled_events(self,
                                                  mocked_upload_hi_season_reminder,
                                                  mocked_upload_laon_status_reminder,
                                                  mocked_upload_payment_reminder,
                                                  mocked_upload_loan_payment_reminder):
        mocked_upload_hi_season_reminder.return_value = None
        mocked_upload_laon_status_reminder.return_value = None
        mocked_upload_payment_reminder.return_value = None
        mocked_upload_loan_payment_reminder.return_value = None
        data = update_moengage_for_scheduled_events()
        self.assertIsNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.apply_async')
    @mock.patch('juloserver.moengage.services.use_cases.construct_user_attributes_for_realtime_basis')
    def test_send_user_attributes_to_moengage_for_realtime_basis(
            self, mock_user_attributes, mock_send_to_moengage):
        account_payment = AccountPaymentFactory()
        mock_user_attributes.return_value = {}
        send_user_attributes_to_moengage_for_realtime_basis(account_payment.account.customer.id)
        mock_send_to_moengage.assert_called()


    @mock.patch('juloserver.moengage.services.use_cases.construct_user_attributes_for_realtime_basis')
    def test_send_user_attributes_to_moengage_for_realtime_basis_on_wallet_change(self, mock_construct):
        customer = CustomerFactory()
        mock_construct.return_value = {
            'type': 'customer',
            'customet_id': customer.id,
            'attributes': {},
        }
        send_user_attributes_to_moengage_for_realtime_basis(
            customer_id=customer.id,
            update_field=UpdateFields.CASHBACK,
        )
        mock_construct.assert_called_with(
            customer,
            update_field=UpdateFields.CASHBACK,
            daily_update=False,
        )

    @mock.patch('juloserver.moengage.services.use_cases.send_user_attributes_to_moengage_for_realtime_basis')
    def test_change_wallet_balance_with_moengage(self, mock_send_realtime):
        customer = CustomerFactory()
        customer.change_wallet_balance(
            change_accruing=0,
            change_available=50_000,
            reason='Hasta la vista, babe...',
        )
        run_commit_hooks(self=self)
        mock_send_realtime.delay.assert_called_once_with(
            customer_id=customer.id,
            update_field=UpdateFields.CASHBACK,
        )

    @mock.patch('juloserver.moengage.services.use_cases.construct_user_attributes_for_realtime_basis')
    def test_send_user_attributes_to_moengage_for_realtime_basis_on_promo_code_usage(self, mock_construct):
        customer = CustomerFactory()
        mock_construct.return_value = {
            'type': 'customer',
            'customet_id': customer.id,
            'attributes': {},
        }
        send_user_attributes_to_moengage_for_realtime_basis(
            customer_id=customer.id,
            update_field='promo_code',
        )
        mock_construct.assert_called_with(
            customer,
            update_field='promo_code',
            daily_update=False,
        )


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestApplicationStatusEvents(TestCase):
    def setUp(self):
        self.workflow = WorkflowFactory(name="JuloOneWorkflow")
        self.status = StatusLookupFactory(status_code=100)
        self.credit_score = CreditScoreFactory()
        self.application1 = ApplicationFactory()
        self.application1.application_status = self.status
        self.application1.workflow = self.workflow
        self.customer1 = self.application1.customer
        self.customer1.dob = datetime.today().date() - timedelta(days=365*30)
        self.customer1.save()
        self.application1.save()
        self.application2 = ApplicationFactory()
        self.application2.application_status = self.status
        self.application2.workflow = self.workflow
        self.application2.save()
        self.application3 = ApplicationFactory()
        self.application3.application_status = self.status
        self.application3.workflow = self.workflow
        self.application3.save()
        self.days_on_status = [1,2,3]
        self.cdates = [timezone.now() - timedelta(days=d) for d in self.days_on_status]

    @mock.patch('juloserver.moengage.services.get_parameters.JuloOneService.is_high_c_score')
    @mock.patch('juloserver.moengage.services.get_parameters.JuloOneService.is_c_score')
    @mock.patch('juloserver.moengage.services.get_parameters.feature_high_score_full_bypass')
    def test_get_credit_score_type(self, mock_high, mock_is_c, mock_high_c):
        response = get_credit_score_type(self.application1)
        assert response == ""
        self.credit_score.application = self.application1
        self.credit_score.save()
        mock_high.return_value = True
        response = get_credit_score_type(self.application1)
        assert response == "High"

        mock_is_c.return_value = True
        mock_high.return_value = False
        response = get_credit_score_type(self.application1)
        assert response == "Low C"

        mock_high_c.return_value = True
        mock_high.return_value = mock_is_c.return_value = False
        response = get_credit_score_type(self.application1)
        assert response == "High C"

    def test_get_application_history_cdate(self):
        application_history = ApplicationHistoryFactory(application_id=self.application1.id)
        application_history.status_new = 100
        application_history.cdate = self.cdates[0]
        application_history.save()
        self.application1.refresh_from_db()
        response = get_application_history_cdate(self.application1)
        self.assertIn(self.cdates[0].strftime("%Y-%m-%d"), response)

    def test_construct_user_attributes_for_j1_customer(self):
        self.application1.refresh_from_db()
        data = construct_user_attributes_for_j1_customer(self.application1, self.application1.status)
        self.assertIsNotNone(data)

    def test_construct_application_status_change_event_data_for_j1_customer(self):
        self.application1.refresh_from_db()
        data = construct_user_attributes_for_j1_customer(self.application1, self.application1.status)
        self.assertIsNotNone(data)

    def test_construct_base_data_for_application_status_change(self):
        self.application1.refresh_from_db()
        data = construct_base_data_for_application_status_change(self.application1.id)
        self.assertIsNotNone(data)

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    @mock.patch('juloserver.moengage.services.data_constructors.get_application_history_cdate')
    def test_update_moengage_for_application_status_change_event(self, mocked_cdate, mocked_client,
                                                                 send_mock):
        self.application1.refresh_from_db()
        mocked_cdate.return_value = datetime.today().strftime("%Y-%m-%d %H:%M:%S")
        mocked_moengage_client = mock.MagicMock()
        mocked_moengage_client.send_event.return_value = {
                                        "status": "success",
                                        "message": "Your request has been accepted and "
                                                   "will be processed soon."
                                     }
        mocked_client.return_value = mocked_moengage_client
        response = update_moengage_for_application_status_change_event(status=100,
                                                                       application_id=self.application1.id)
        moengage_upload = MoengageUpload.objects.filter(application_id=self.application1.id)
        self.assertIsNotNone(moengage_upload)


    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    @mock.patch('juloserver.moengage.services.use_cases.get_julo_moengage_client')
    @mock.patch('juloserver.moengage.services.data_constructors.get_application_history_cdate')
    def test_update_moengage_for_application_status_change_batched_event(self, mocked_cdate, mocked_client,
                                                                 send_mock):
        self.application1.refresh_from_db()
        application_history1 = ApplicationHistoryFactory(application_id=self.application1.id)
        application_history1.status_new = 100
        application_history1.cdate = self.cdates[0]
        application_history1.save()

        application_history2 = ApplicationHistoryFactory(application_id=self.application2.id)
        application_history2.status_new = 100
        application_history2.cdate = self.cdates[0]
        application_history2.save()

        application_history3 = ApplicationHistoryFactory(application_id=self.application3.id)
        application_history3.status_new = 100
        application_history3.cdate = self.cdates[0]
        application_history3.save()

        application_ids = ApplicationHistory.objects.filter(
            status_new=100,
            cdate__date__in=self.cdates,
            application__workflow=self.workflow,
            application__application_status_id=100).values_list('application_id', flat=True)

        assert application_ids.count() == 3
        mocked_moengage_client = mock.MagicMock()
        mocked_moengage_client.send_event.return_value = {
                                        "status": "success",
                                        "message": "Your request has been accepted and "
                                                   "will be processed soon."
                                     }
        mocked_client.return_value = mocked_moengage_client
        response = update_moengage_for_application_status_change_event(status=100,
                                                                       days_on_status=self.days_on_status)
        moengage_uploads = MoengageUpload.objects.filter(application_id__in=[self.application1.id,
                                                                             self.application2.id,
                                                                             self.application3.id])
        assert  3 == moengage_uploads.count()
        upload_batch = MoengageUploadBatch.objects.filter().last()
        self.assertIsNotNone(upload_batch)
        assert 3 == upload_batch.data_count

    @mock.patch('juloserver.moengage.services.use_cases.construct_user_attributes_account_level_available_limit_change')
    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.apply_async')
    def test_send_user_attributes_to_moengage_for_available_limit_created(
            self, mock1, mock2):
        moe_upload = MoengageUploadFactory(customer_id=self.customer1.id, type='realtime_basis')
        mock2.return_value = {'test': 'test'}
        send_user_attributes_to_moengage_for_available_limit_created(
            self.customer1, None, 10000000
        )
        mock1.assert_called()

    @mock.patch(
        'juloserver.moengage.services.use_cases.construct_user_attributes_customer_level_referral_change')
    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.apply_async')
    def test_send_user_attributes_to_moengage_for_self_referral_code_change(
            self, mock1, mock2):
        moe_upload = MoengageUploadFactory(customer_id=self.customer1.id, type='realtime_basis')
        mock2.return_value = {'test': 'test'}
        send_user_attributes_to_moengage_for_self_referral_code_change(self.customer1.id)
        mock1.assert_called()

    @mock.patch(
        'juloserver.moengage.services.use_cases.construct_user_attributes_for_realtime_basis')
    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.apply_async')
    def test_send_user_attributes_to_moengage_for_realtime_basis(
            self, mock1, mock2):
        mock2.return_value = {}
        moe_upload = MoengageUploadFactory(customer_id=self.customer1.id, type='realtime_basis')
        send_user_attributes_to_moengage_for_realtime_basis(self.customer1.id)
        mock1.assert_called()
        mock2.assert_called()


class TestDataStructors(TestCase):

    def setUp(self):
        pass

    def test_construct_user_attributes_account_level_available_limit_change(self):
        customer = CustomerFactory()
        account1 = AccountFactory()
        account2 = AccountFactory()
        # account not found
        user_attributes = construct_user_attributes_account_level_available_limit_change(
            customer, account1, 1000000
        )
        attributes = {
            "platforms": [{
                "platform": "ANDROID",
                "active": "true"}]
        }
        user_attributes_check = {
            "type": "customer",
            "customer_id": customer.id,
            "attributes": attributes
        }
        self.assertEqual(user_attributes, user_attributes_check)
        # not index
        account1.customer = customer
        account1.save()
        self.assertRaises(ValueError,
                          construct_user_attributes_account_level_available_limit_change,
                          customer, account2, 1000000)
        # success
        user_attributes = construct_user_attributes_account_level_available_limit_change(
            customer, account1, 1000000
        )
        attributes['account1_available_limit'] = 1000000
        attributes['account1_available_limit_text'] = format_money_to_rupiah(1000000)
        self.assertEqual(user_attributes, user_attributes_check)

    def test_construct_user_attributes_customer_level_referral_change(self):
        customer = CustomerFactory(self_referral_code='test')
        user_attributes = construct_user_attributes_customer_level_referral_change(
            customer, 'self_referral_code'
        )
        attributes = {
            "platforms": [{
                "platform": "ANDROID",
                "active": "true"}],
            "self_referral_code": "test"
        }
        user_attributes_check = {
            "type": "customer",
            "customer_id": customer.id,
            "attributes": attributes
        }
        self.assertEqual(user_attributes, user_attributes_check)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestPaymentReceivedService(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.account_property = AccountPropertyFactory(account=self.account)
        self.account_property.is_proven = False
        self.account_property.proven_threshold = 10000
        self.account_property.save()
        self.account_property_history = AccountPropertyHistoryFactory(
            account_property=self.account_property,
            field_name='is_proven',
            value_old=True,
            value_new=False,
        )
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_transaction = AccountTransactionFactory(
            account=self.account,
            transaction_type="payment",
            transaction_amount=1000,
            transaction_date=timezone.localtime(timezone.now()),
            accounting_date=timezone.localtime(timezone.now()),
            towards_principal=900,
            towards_interest=100,
            towards_latefee=0,
            can_reverse=True
        )
        self.last_paid_account_payment_id = 126743667
        self.data = {u'app_name': u'julo',
                u'events': [{u'device_attributes': {
                 u'moengage_device_id': u'9fecab4b-f71b-453a-b928-c10c41086c50'
                },
                    u'event_attributes': {
                        u'campaign_channel': u'PUSH',
                        u'campaign_id': u'6045b42a2bcde46e78047268',
                        u'campaign_name': u'test payment event campaign',
                        u'campaign_type': u'SMART_TRIGGER'},
                    u'event_code': u'NOTIFICATION_RECEIVED_MOE',
                    u'event_name': u'Notification Received Android',
                    u'event_source': u'MOENGAGE',
                    u'event_time': 1615260594,
                    u'event_type': u'CAMPAIGN_EVENT',
                    u'event_uuid': u'91d574ff-c061-445d-bb92-390e174013b8',
                    u'push_id': u'dUyHvERKQYaEEq170VIkm1:U-mibjot-3MfVu9',
                    u'uid': u'1000029354',
                    u'user_attributes': {
                        u'account1_payment_id': 2515,
                        u'application_id': 2000029992,
                        u'loan_status_code': 220,
                        u'mobile_phone_1': u'62895895893',
                        u'moengage_user_id': u'5fb159f45f9d400358de32f2',
                        u'payment_id': 4000052183.0}}],
                u'moe_request_id': u'e25ba6a6-5917-4e30-86fd-9fd9747073a3',
                u'source': u'MOENGAGE'}

        self.last_paid_account_payment_id_2 = 126743123
        self.data_2 = {u'app_name': u'julo',
                u'events': [{u'device_attributes': {
                 u'moengage_device_id': u'9fecab4b-f71b-453a-b928-c10c41086c50'
                },
                    u'event_attributes': {
                        u'campaign_channel': u'PUSH',
                        u'campaign_id': u'6045b42a2bcde46e78047269',
                        u'campaign_name': u'test payment event campaign',
                        u'campaign_type': u'SMART_TRIGGER'},
                    u'event_code': u'NOTIFICATION_RECEIVED_MOE',
                    u'event_name': u'Notification Received Android',
                    u'event_source': u'MOENGAGE',
                    u'event_time': 1615260594,
                    u'event_type': u'CAMPAIGN_EVENT',
                    u'event_uuid': u'91d574ff-c061-445d-bb92-390e174013b8',
                    u'push_id': u'dUyHvERKQYaEEq170VIkm1:U-mibjot-3MfVu9',
                    u'uid': u'1000029355',
                    u'user_attributes': {
                        u'account1_payment_id': 2515,
                        u'application_id': 2000029992,
                        u'loan_status_code': 220,
                        u'mobile_phone_1': u'62895895893',
                        u'moengage_user_id': u'5fb159f45f9d400358de32f2',
                        u'payment_id': 4000052183.0}}],
                u'moe_request_id': u'e25ba6a6-5917-4e30-86fd-9fd9747073a3',
                u'source': u'MOENGAGE'}
        self.pn_blast =  PNBlast.objects.create(
            schedule_time=timezone.now(),
            title='23546',
            name='sdhsgfh',
            status='active',
            content='35wteryeu',
            redirect_page=0
        )

    def test_construct_data_for_payment_received_event(self):
        event_type = 'payment_received_smart_trigger'
        data = construct_data_for_payment_received_event(self.account_transaction, event_type)
        self.assertEqual(data["actions"][0]["action"], event_type)

    def test_update_pn_details_from_moengage_streams(self):
        data = parse_stream_data(self.data['events'][0], 'PN')
        refactored_data = set_data_format_for_pn_streams(
            data, self.last_paid_account_payment_id, True)
        update_pn_details_from_moengage_streams(refactored_data)
        pn_delivery = PNDelivery.objects.filter(account_payment_id=self.last_paid_account_payment_id)
        self.assertIsNotNone(pn_delivery)

    def test_update_pn_details_from_moengage_streams_pn_delivery_exist(self):
        PNDelivery.objects.create(
            fcm_id='q35624856348ty',
            title='afdgsh',
            body='hihig',
            status='received',
            pn_blast=self.pn_blast,
            campaign_id='6045b42a2bcde46e78047268',
            customer_id=1000029354,
            account_payment_id=self.last_paid_account_payment_id
        )
        data = parse_stream_data(self.data['events'][0], 'PN')
        refactored_data = set_data_format_for_pn_streams(
            data, self.last_paid_account_payment_id, True)
        update_pn_details_from_moengage_streams(refactored_data)
        pn_delivery = PNDelivery.objects.filter(account_payment_id=self.last_paid_account_payment_id)
        self.assertIsNotNone(pn_delivery)

    def test_update_pn(self):
        data_2 = parse_stream_data(self.data_2['events'][0], 'PN')
        update_pn(data_2, True, self.last_paid_account_payment_id_2)
        pn_delivery = PNDelivery.objects.filter(
            account_payment_id=self.last_paid_account_payment_id_2)
        self.assertIsNotNone(pn_delivery)

    def test_update_pn_pn_delivery_exist(self):
        PNDelivery.objects.create(
            fcm_id='q35624856348ty',
            title='afdgsh',
            body='hihig',
            status='received',
            pn_blast=self.pn_blast,
            campaign_id='6045b42a2bcde46e78047269',
            customer_id=1000029355,
            account_payment_id=self.last_paid_account_payment_id_2
        )
        data_2 = parse_stream_data(self.data_2['events'][0], 'PN')
        update_pn(data_2, True, self.last_paid_account_payment_id_2)
        pn_delivery = PNDelivery.objects.filter(
            account_payment_id=self.last_paid_account_payment_id_2)
        self.assertIsNotNone(pn_delivery)


class TestDataConstructor(TestCase):
    def setUp(self):
        pass

    def test_construct_data_for_account_payment_comms_block(self):
        today = timezone.localtime(timezone.now()).date()
        account_payment = AccountPaymentFactory(due_date=today+timedelta(days=3))
        comms_blocked = CommsBlockedFactory(
            account=account_payment.account, is_email_blocked=True,
            impacted_payments=[account_payment.id])
        user_attributes = construct_data_for_account_payment_comms_block(
            account_payment.account.customer, account_payment)
        self.assertEqual(user_attributes['account1_is_email_blocked'], True)
        self.assertEqual(user_attributes['account1_is_sms_blocked'], False)
        self.assertEqual(user_attributes['account1_is_pn_blocked'], False)

    @mock.patch(
        'juloserver.moengage.services.data_constructors.construct_data_for_account_payment_comms_block')
    def test_construct_user_attributes_for_comms_blocked(
            self, mock_construct_data):
        account_payment = AccountPaymentFactory()
        mock_construct_data.return_value = {'test': 'success'}
        user_attributes = construct_user_attributes_for_comms_blocked(
            account_payment.account.customer, account_payment)
        self.assertEqual(user_attributes, {
            "type": "customer",
            "customer_id": account_payment.account.customer.id,
            "attributes": {
                "platforms": [{
                    "platform": "ANDROID",
                    "active": "true"}],
                "test": "success"
            }
        })

    @mock.patch('juloserver.cashback.services.get_expired_date_and_cashback')
    def test_construct_user_attributes_contains_cashback_expired(self, mock_get_expired_date_and_cash):
        customer = CustomerFactory()
        mock_get_expired_date_and_cash.return_value = date(2023, 12, 31), 1000
        data = construct_user_attributes_customer_level(customer=customer, update_field=UpdateFields.CASHBACK)
        self.assertIn('next_cashback_expiry_date',data)
        self.assertIn('next_cashback_expiry_total_amount',data)


class TestAddAttribute(TestCase):
    def setUp(self):
        pass

    def test_construct_user_attributes_account_string_id(self):
        customer = CustomerFactory()

        account_lookup = AccountLookupFactory(moengage_mapping_number=1)
        account = AccountFactory(customer=customer, account_lookup=account_lookup)
        data = construct_user_attributes_account_level(customer=customer)
        self.assertEquals(str(account.id), data['account1_account_id_string'])


class TestCustomerWalletChangeUsedAllCashback(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()

    @mock.patch('juloserver.moengage.services.use_cases.send_user_attributes_to_moengage_for_realtime_basis')
    @mock.patch('django.utils.timezone.now')
    def test_send_when_change_wallet_balance(self, mock_now, mock_send_realtime):
        mock_now.return_value = datetime(2023, 7, 10, 0, 0, 0)
        self.customer.change_wallet_balance(0, 50_000, 'testing')
        run_commit_hooks(self)
        mock_send_realtime.delay.assert_called_once_with(
            customer_id=self.customer.id,
            update_field=UpdateFields.CASHBACK,
        )

    @mock.patch('juloserver.moengage.services.use_cases.send_user_attributes_to_moengage_for_realtime_basis')
    @mock.patch('django.utils.timezone.now')
    def test_cashback_construct_data(self, mock_now, mock_send_realtime):
        mock_now.return_value = datetime(2023, 7, 10, 0, 0, 0)
        self.customer.change_wallet_balance(50_000, 50_000, 'testing')
        attributes = construct_user_attributes_customer_level(
            self.customer,
            update_field=UpdateFields.CASHBACK
        )
        self.assertEqual(50_000, attributes.get('next_cashback_expiry_total_amount'))
        self.assertIsNotNone(attributes.get('next_cashback_expiry_date'))


@mock.patch('juloserver.moengage.clients.MoEngageClient.send_event')
class TestSendToMoengage(TestCase):
    def setUp(self):
        self.moengage_upload = MoengageUploadFactory(status='pending')

    @classmethod
    def setUpTestData(cls):
        cls.customer_data = {
            "customer_id": 1000001350,
            "type": "event",
            "actions": [
                {
                    "action": "Payment_Reminders",
                    "attributes": {
                        "cashback_amount": 0,
                        "due_date": "2020-09-14T00:00:00.000000Z",
                        "payment_level_dpd": -6,
                        "bank_name": "BANK RAKYAT INDONESIA (PERSERO), Tbk (BRI)",
                        "bank_account_number": "XXXXXXXXXX8541",
                        "payment_id": 4000000303,
                        "product_type": 10,
                        "payment_details_url": "go.onelink.me/zOQD/howtopay",
                        "payment_status_code": 321,
                        "due_amount": 666443,
                        "payment_number": 2,
                        "va_number": "31932220733124",
                        "va_method_name": "ALFAMART"
                    },
                    "current_time": 1599566128.828946,
                    "user_timezone_offset": 25200,
                    "platform": "ANDROID"
                }
            ],
            "device_id": "67757-456465456"
        }
        cls.success_response_data =  {
            "status": "success",
            "message": "Your request has been accepted and "
                       "will be processed soon."
         }

    def test_success_send(self, mocked_upload):
        moengage_upload_ids = [self.moengage_upload.id]
        data_to_send = [
            self.customer_data
        ]
        mocked_upload.return_value = self.success_response_data
        send_to_moengage(moengage_upload_ids, data_to_send)

        self.moengage_upload.refresh_from_db()
        self.assertEqual('success', self.moengage_upload.status)


@mock.patch('juloserver.moengage.services.use_cases.construct_user_attributes_for_realtime_basis')
@mock.patch('juloserver.moengage.services.use_cases.get_redis_client')
@mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
class TestSendUserAttributesToMoengageForTailorExp(TestCase):
    def test_send_to_moengage(
        self, mock_send_to_moengage, mock_get_redis_client,
        mock_construct_user_attributes_for_realtime_basis,
    ):
        moengage_batch_factory = MoengageUploadBatchFactory()
        account_payments = AccountPaymentFactory.create_batch(3)
        mock_get_redis_client.return_value.get.return_value = str([
            {'account_payment': ap.id, 'segment': 'test-segment'} for ap in account_payments
        ])
        mock_construct_user_attributes_for_realtime_basis.return_value = {
            'type': 'customer',
            'attributes': {}
        }

        send_user_attributes_to_moengage_for_tailor_exp(moengage_batch_factory.id)

        self.assertEqual(3, MoengageUpload.objects.count())
        self.assertEqual(1, mock_send_to_moengage.call_count)


class TestSendEventToMoengage(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.loan = LoanFactory(
            application=self.application,
            loan_status=StatusLookupFactory(status_code=220),
            customer=self.customer,
        )
        self.payment = PaymentFactory(loan=self.loan)

    def test_send_event_after_loan_status_changed_to_moengage(self):
        send_event_for_active_loan_to_moengage.delay(
            self.loan. id,
            self.loan.status,
            MoengageEventType.PROMO_CODE_USAGE
        )

        moe_upload_data = MoengageUpload.objects.get(
            loan=self.loan,
        )

        self.assertIsNotNone(moe_upload_data)
        self.assertEqual(moe_upload_data.type, MoengageEventType.PROMO_CODE_USAGE)

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_send_to_moengage_function_is_called(self, mock_send_to_moengage):
        send_event_for_active_loan_to_moengage.delay(
            self.loan.id,
            self.loan.status,
            MoengageEventType.PROMO_CODE_USAGE
        )

        mock_send_to_moengage.assert_called_once()

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_send_to_moengage_function_is_not_called(self, mock_send_to_moengage):
        self.loan.loan_status = StatusLookupFactory(status_code=210)
        self.loan.save()

        mock_send_to_moengage.assert_not_called()

    def test_construct_event_attributes_for_active_loan(self):
        event_name = MoengageEventType.PROMO_CODE_USAGE
        event_data = construct_event_attributes_for_promo_code_usage(self.loan, event_name)

        self.assertIsNotNone(event_data)

    def test_construct_event_attributes_for_product_name_type_x210(self):
        transaction_method = TransactionMethodFactory(
            id=TransactionMethodCode.E_COMMERCE.code,
            method=TransactionMethodCode.E_COMMERCE,
            fe_display_name='E-Commerce'
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=BankAccountCategoryFactory(
                category=BankAccountCategoryConst.ECOMMERCE
            ),
            customer=self.customer,
            description='Shopee',
            account_number='0081237656128',
        )
        self.loan.transaction_method = transaction_method
        self.loan.bank_account_destination = bank_account_destination
        self.loan.loan_status = StatusLookupFactory(status_code=210)
        self.loan.save()
        event_type = 'STATUS_' + str(self.loan.status)
        event_name = getattr(MoengageLoanStatusEventType, event_type)
        event_data = construct_data_for_loan_status_change_j1_event(
            self.loan,
            event_name
        )
        self.assertIsNotNone(event_data)

    def test_construct_event_attributes_for_every_product_name_type_x216(self):
        transaction_method = TransactionMethodFactory(
            id=12089371,
            method=TransactionMethodCode.PASCA_BAYAR,
            fe_display_name='Kartu Pascabayar'
        )
        self.loan.transaction_method = transaction_method
        self.loan.loan_status = StatusLookupFactory(status_code=216)
        self.loan.save()
        event_type = 'STATUS_' + str(self.loan.status)
        event_name = getattr(MoengageLoanStatusEventType, event_type)
        event_data = construct_data_for_loan_status_change_j1_event(
            self.loan,
            event_name
        )
        self.assertIsNotNone(event_data)

    @mock.patch('juloserver.moengage.services.use_cases.get_cashback_experiment')
    @mock.patch(
        'juloserver.moengage.services.use_cases.construct_user_attributes_for_realtime_basis'
    )
    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_send_event_of_every_transaction_methods_to_moengage_x210(
        self,
        mock_send_to_moengage,
        mock_construct_user_attributes_for_realtime_basis,
        mock_cashback,
    ):
        transaction_method = TransactionMethodFactory(
            id=2737891,
            method=TransactionMethodCode.PULSA_N_PAKET_DATA,
            fe_display_name='Pulsa & Data'
        )
        self.loan.transaction_method = transaction_method
        self.loan.save()
        mock_construct_user_attributes_for_realtime_basis.return_value = {
            'type': 'customer',
            'attributes': {},
        }
        mock_cashback.return_value = False
        data_import_moengage_for_loan_status_change_event(
            self.loan.id,
            self.loan.status,
        )

        mock_send_to_moengage.assert_called_once()

    @mock.patch('juloserver.moengage.services.use_cases.get_cashback_experiment')
    @mock.patch(
        'juloserver.moengage.services.use_cases.construct_user_attributes_for_realtime_basis'
    )
    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_send_event_of_every_transaction_methods_to_moengage_x216(
        self,
        mock_send_to_moengage,
        mock_construct_user_attributes_for_realtime_basis,
        mock_cashback,
    ):
        transaction_method = TransactionMethodFactory(
            id=23718273,
            method=TransactionMethodCode.SELF,
            fe_display_name='Tarik Dana'
        )
        self.loan.transaction_method = transaction_method
        self.loan.save()
        mock_construct_user_attributes_for_realtime_basis.return_value = {
            'type': 'customer',
            'attributes': {},
        }
        mock_cashback.return_value = False
        data_import_moengage_for_loan_status_change_event(
            self.loan.id,
            self.loan.status,
        )

        mock_send_to_moengage.assert_called_once()

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.apply_async')
    def test_update_moengage_for_user_linking_status_for_empty_partner_origin_id(
            self, mock_send_to_moengage):
        self.account = AccountFactory()
        self.partner = PartnerFactory(name='test1')
        MoengageUploadFactory(type=MoengageEventType.REALTIME_BASIS)
        self.loan.account = self.account
        self.loan.save()
        update_moengage_for_user_linking_status(
            self.loan.account.id,
            '',
        )
        mock_send_to_moengage.assert_not_called()

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.apply_async')
    def test_update_moengage_for_user_linking_status(self, mock_send_to_moengage):
        self.account = AccountFactory()
        self.partner = PartnerFactory(name='test1')
        MoengageUploadFactory(type=MoengageEventType.REALTIME_BASIS)
        partnership_api_log = PartnershipApiLogFactory(
            partner=self.partner
        )
        partner_origin = PartnerOriginFactory(
            partner=self.partner,
            partner_origin_name='Blibli',
            partnership_api_log=partnership_api_log
        )
        self.loan.account = self.account
        self.loan.save()
        update_moengage_for_user_linking_status(
            self.loan.account.id,
            partner_origin.id,
        )
        mock_send_to_moengage.assert_called_once()

    def test_update_moengage_for_user_linking_status_with_invalid_account(self):
        self.assertEqual(update_moengage_for_user_linking_status(500, ''), False)

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_julo_card_status_change_should_success(
            self, mock_send_to_moengage
    ):
        credit_card_application = create_mock_credit_card_application(
            CreditCardCodes.CARD_ACTIVATED
        )
        credit_card_application_history = CreditCardApplicationHistoryFactory(
            credit_card_application=credit_card_application,
            status_old=StatusLookupFactory(status_code=CreditCardCodes.CARD_VALIDATED),
            status_new=StatusLookupFactory(status_code=CreditCardCodes.CARD_ACTIVATED),
            changed_by=self.customer.user,
            change_reason='change_by_customer'
        )
        send_event_moengage_for_julo_card_status_change_event(
            credit_card_application_history.id
        )
        mock_send_to_moengage.assert_called_once()
        self.assertTrue(
            MoengageUpload.objects.filter(
                type=getattr(MoengageJuloCardStatusEventType, 'STATUS_580'),
                customer_id=credit_card_application.account.customer.id
            ).exists()
        )

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_julo_card_status_change_should_failed_when_status_is_not_eligible(
            self, mock_send_to_moengage
    ):
        credit_card_application = create_mock_credit_card_application(
            CreditCardCodes.CARD_CLOSED
        )
        credit_card_application_history = CreditCardApplicationHistoryFactory(
            credit_card_application=credit_card_application,
            status_old=StatusLookupFactory(status_code=CreditCardCodes.CARD_BLOCKED),
            status_new=StatusLookupFactory(status_code=CreditCardCodes.CARD_CLOSED),
            changed_by=self.customer.user,
            change_reason='change_by_customer'
        )
        send_event_moengage_for_julo_card_status_change_event(
            credit_card_application_history.id
        )
        mock_send_to_moengage.assert_not_called()
        self.assertFalse(
            MoengageUpload.objects.filter(
                customer_id=credit_card_application.account.customer.id
            ).exists()
        )


class TestAutodebitFailedDeduction(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account_payment = AccountPaymentFactory()
        self.autodebit_account = AutodebetAccountFactory()
        self.autodebit_bri_transaction = AutodebetBRITransactionFactory()
        self.autodebit_bri_transaction.autodebet_account = self.autodebit_account
        self.autodebit_bri_transaction.account_payment = self.account_payment
        self.autodebit_bri_transaction.save()

        self.autodebit_api_log = AutodebetAPILogFactory()
        self.autodebit_api_log.account_payment_id = self.account_payment.id
        self.autodebit_api_log.save()

    def test_construct_data_for_autodebit_failed_deduction(self):
        autodebit_failed_data_constructor = construct_data_for_autodebit_failed_deduction(
            self.account_payment.id,
            self.customer,
            'BNI',
            MoengageEventType.AUTODEBIT_FAILED_DEDUCTION,
        )
        self.assertFalse(autodebit_failed_data_constructor)

        self.autodebit_bri_transaction.status = 'FAILED'
        self.autodebit_bri_transaction.description = 'INSUFFICIENT_BALANCE'
        self.autodebit_bri_transaction.save()

        autodebit_failed_data_constructor = construct_data_for_autodebit_failed_deduction(
            self.account_payment.id,
            self.customer,
            'BRI',
            MoengageEventType.AUTODEBIT_FAILED_DEDUCTION,
        )
        self.assertTrue(autodebit_failed_data_constructor)

        self.autodebit_api_log.http_status_code = 400
        self.autodebit_api_log.error_message = '402 Client Error: Payment Required for url: https://api.klikbca.com:443/fund-collection'
        self.autodebit_api_log.save()
        autodebit_failed_data_constructor = construct_data_for_autodebit_failed_deduction(
            self.account_payment.id,
            self.customer,
            'BCA',
            MoengageEventType.AUTODEBIT_FAILED_DEDUCTION,
        )
        self.assertTrue(autodebit_failed_data_constructor)


@mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
class TestSendFraudAtoDeviceChangeEvent(TestCase):
    def setUp(self):
        self.loan = LoanFactory(
            loan_amount=50000,
            transaction_method_id=TransactionMethodCode.OTHER.code,
        )
        self.fraud_flag = FraudFlagFactory(
            fraud_type=FraudFlagType.ATO_DEVICE_CHANGE,
            flag_source_type=FraudFlagSource.LOAN,
            flag_source_id=self.loan.id,
            trigger=FraudFlagTrigger.LOAN_CREATION,
        )
        self.event_time = timezone.localtime(self.fraud_flag.cdate)

    def test_send_event(self, mock_send_to_moengage_delay):
        send_fraud_ato_device_change_event(self.fraud_flag.id)
        moengage_upload = MoengageUpload.objects.last()

        expected_event_data = [{
            "type": "event",
            "customer_id": self.loan.customer_id,
            "device_id": None,
            "actions": [
                {
                    "action": 'fraud_ato_device_change_block',
                    "attributes": {
                        "loan_id": self.loan.id,
                        "loan_amount": 50000,
                        "event_triggered_date": self.event_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "product_type": "Kirim Dana",
                        "product_name": "Kirim Dana"
                    },
                    "platform": "ANDROID",
                    "current_time": self.fraud_flag.cdate.timestamp(),
                    "user_timezone_offset": 25200,
                }
            ],
        }]
        mock_send_to_moengage_delay.assert_called_once_with(
            [moengage_upload.id],
            expected_event_data,
        )


@mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
class TestUpdateMoengageForAccountStatusChange(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.status_420 = StatusLookupFactory(
            status_code=420,
            status="Active",
        )
        cls.status_450 = StatusLookupFactory(
            status_code=450,
            status="Fraud Suspicious",
        )
        cls.account_lookup = AccountLookupFactory(
            name='Test Account Lookup',
            moengage_mapping_number=9,
        )

    def test_450_event(self, mock_send_to_moengage):
        now = datetime(2023, 1, 10, 10, 11, 12)
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = now
            account_history = AccountStatusHistoryFactory(
                account=AccountFactory(
                    status=self.status_450,
                    account_lookup=self.account_lookup,
                ),
                status_new=self.status_450,
                status_old=self.status_420,
                change_reason="Test change reason",
            )
        account = account_history.account

        update_moengage_for_account_status_change(account_history.id)

        me_upload = MoengageUpload.objects.get(type='BEx450')
        expected_user_attribute = {
            "type": "customer",
            "customer_id": account.customer_id,
            "attributes": {
                "customer_id": account.customer_id,
                "account_status_code": 450,
                "account9_account_id_string": str(account.id),
                "account9_account_status_code": 450,
            }
        }
        expected_event_attribute = {
            "type": "event",
            "customer_id": account.customer_id,
            "actions": [{
                "action": 'BEx450',
                "attributes": {
                    "account_id": account.id,
                    "account_lookup_name": "Test Account Lookup",
                    "old_status_code": 420,
                    "old_status_name": "Active",
                    "new_status_code": 450,
                    "new_status_name": "Fraud Suspicious",
                    "reason": "Test change reason",
                },
                "platform": "ANDROID",
                "current_time": now.timestamp(),
                "user_timezone_offset": 25200,
            }]
        }
        mock_send_to_moengage.assert_called_once_with(
            [me_upload.id],
            [
                expected_user_attribute,
                expected_event_attribute,
            ]
        )

    def test_no_event(self, mock_send_to_moengage):
        account_history = AccountStatusHistoryFactory(
            account=AccountFactory(
                status=StatusLookupFactory(status_code=999),
                account_lookup=self.account_lookup,
            ),
            status_new=StatusLookupFactory(status_code=999),
            change_reason="Test change reason",
        )
        account = account_history.account

        update_moengage_for_account_status_change(account_history.id)

        me_upload = MoengageUpload.objects.get(type='account_status_change')
        expected_user_attribute = {
            "type": "customer",
            "customer_id": account.customer_id,
            "attributes": {
                "customer_id": account.customer_id,
                "account_status_code": 999,
                "account9_account_id_string": str(account.id),
                "account9_account_status_code": 999,
            }
        }
        mock_send_to_moengage.assert_called_once_with([me_upload.id], [expected_user_attribute])


class TestForSendChurnUsersToMoengageInBulkDaily(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.churn_customer = ChurnUserFactory(customer_id=self.customer.id)
        self.moengage_upload_batch = MoengageUploadBatch.objects.create(
            type=MoengageEventType.IS_CHURN_EXPERIMENT,
            data_count=1)

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_send_churn_user_to_moengage(self, mock_send_to_moengage):
        send_churn_users_to_moengage_in_bulk_daily([self.churn_customer.id], self.moengage_upload_batch.id)
        churn_customer_id = self.customer.id
        attributes = {'customer_id': churn_customer_id,
                      'predict_date': self.churn_customer.predict_date.strftime('%Y-%m-%d'),
                      'pchurn': self.churn_customer.pchurn,
                      'experiment_group': self.churn_customer.experiment_group,
                      'model_version': self.churn_customer.model_version,
                      }
        expected_user_attributes = {
            "type": "customer",
            "customer_id": churn_customer_id,
            "attributes": attributes
        }
        expected_event_attribute = {
            "type": "event",
            "customer_id": churn_customer_id,
            "device_id": '',
            "actions": [{
                "action": "is_churn_experiment",
                "attributes": expected_user_attributes,
                "platform": "ANDROID",
                "current_time": ANY,
                "user_timezone_offset": ANY,
            }]
        }
        mock_send_to_moengage.assert_called_once_with(
            [ANY],
            [
                expected_user_attributes,
                expected_event_attribute,
            ]
        )


@mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
class TestSendMEAfterGraduation(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationJ1Factory(customer=self.customer, account=self.account)
        self.account_limit = AccountLimitFactory(account=self.account, set_limit=2000000)

    @mock.patch('juloserver.moengage.services.data_constructors.timezone')
    def test_send_user_attributes_to_moengage_after_graduation(self, mock_now,
                                                               mock_send_to_moengage):
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2022, month=10, day=20, hour=15, minute=0, second=0, microsecond=0
        )
        send_user_attributes_to_moengage_after_graduation_downgrade(
            self.account_limit.id, self.account_limit.set_limit, 2345000, True,
            graduation_date=mock_now
        )

        me_upload = MoengageUpload.objects.filter(
            type=MoengageEventType.GRADUATION, customer_id=self.customer.id
        ).last()

        self.assertIsNotNone(me_upload)
        mock_send_to_moengage.assert_called_once()

    def test_send_user_attributes_to_moengage_after_downgrade(self, mock_send_to_moengage):
        send_user_attributes_to_moengage_after_graduation_downgrade(
            self.account_limit.id, self.account_limit.set_limit, 1655000, False
        )

        me_upload = MoengageUpload.objects.filter(
            type=MoengageEventType.DOWNGRADE, customer_id=self.customer.id
        ).last()

        self.assertIsNotNone(me_upload)
        mock_send_to_moengage.assert_called_once()


@mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
class TestSendMEAfterReferralCashback(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)

    def test_send_user_attributes_to_moengage_after_freeze_unfreeze_cashback(
        self, mock_send_to_moengage
    ):
        send_user_attributes_to_moengage_after_freeze_unfreeze_cashback(
            self.customer.id, 340000, 'referee', 'unfreeze'
        )

        me_upload = MoengageUpload.objects.filter(
            type=MoengageEventType.REFERRAL_CASHBACK, customer_id=self.customer.id
        ).last()

        self.assertIsNotNone(me_upload)
        mock_send_to_moengage.assert_called_once()


@mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
class TestSendUserAttributesToMoengageCustomerSuspendedUnsuspended(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)

    def test_send_user_attributes_to_moengage_customer_suspended_unsuspended(
            self, mock_send_to_moengage
    ):
        send_user_attributes_to_moengage_customer_suspended_unsuspended(
            self.customer.id, is_suspended=False, reason='bad_repeat_tpd40_rules'
        )

        me_upload = MoengageUpload.objects.filter(
            type=MoengageEventType.CUSTOMER_SUSPENDED, customer_id=self.customer.id
        ).last()

        self.assertIsNotNone(me_upload)
        mock_send_to_moengage.assert_called_once()


class TestBulkSendCustomerSegmentation(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        CustomerSegmentationCommsFactory(
            customer_id=self.customer.id,
            extra_params={'name': 'test'}
        )
        self.moengage_upload_batch = MoengageUploadBatch.objects.create(
            type=MoengageEventType.CUSTOMER_SEGMENTATION,
            data_count=1
        )

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_bulk_send_customer_segmentation_moengage(self, mock_send_to_moengage):

        self.segment = CustomerSegmentationComms.objects.last()
        send_customer_segment_moengage_bulk([self.customer.id], self.moengage_upload_batch.id)
        attributes = {
            'customer_id': self.customer.id,
            "platforms": [{"platform": "ANDROID", "active": "true"}],
            'customer_segment': self.segment.customer_segment,
            'schema_amount': self.segment.schema_amount,
            'default_monthly_installment': self.segment.default_monthly_installment,
            'np_monthly_installment': self.segment.np_monthly_installment,
            'np_provision_amount': self.segment.np_provision_amount,
            'np_monthly_interest_amount': self.segment.np_monthly_interest_amount,
            'promo_code_churn': self.segment.promo_code_churn,
            'is_np_lower': self.segment.is_np_lower,
            'is_create_loan': self.segment.is_create_loan,
            'customer_segment_group': self.segment.customer_segment_group,
            'churn_group': self.segment.churn_group,
            'name': 'test'
        }
        expected_user_attributes = {
            "type": "customer",
            "customer_id": self.customer.id,
            "attributes": attributes,
        }
        mock_send_to_moengage.assert_called_once_with(
            [ANY],
            [expected_user_attributes],
        )


class TestSendTransactionStatusEvent(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.loan = LoanFactory(
            application=self.application,
            loan_status=StatusLookupFactory(status_code=220),
            customer=self.customer,
        )

    @mock.patch('juloserver.moengage.services.use_cases.construct_data_moengage_user_attributes')
    @mock.patch('juloserver.moengage.services.use_cases.construct_moengage_event_data')
    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_send_transaction_status_event_to_moengage(
        self,
        mock_send_to_moengage,
        mock_construct_moengage_event_data,
        mock_construct_data_moengage_user_attributes,
    ):

        fake_data1 = {"i used to think": "my life was a tragedy"}
        fake_data2 = {"but now i realized": "its a comedy"}

        mock_construct_data_moengage_user_attributes.return_value = fake_data1
        mock_construct_moengage_event_data.return_value = fake_data2

        # call func
        send_transaction_status_event_to_moengage(
            customer_id=self.customer.id,
            loan_xid=self.loan.loan_xid,
            loan_status_code=self.loan.loan_status_id,
        )

        # assertions
        mock_construct_moengage_event_data.assert_called_once_with(
            event_type=MoengageEventType.LOAN_TRANSACTION_STATUS,
            customer_id=self.customer.id,
            event_attributes={
                'loan_xid': self.loan.loan_xid,
                'loan_status_code': self.loan.loan_status_id,
            },
        )
        mock_send_to_moengage.assert_called_once_with(
            [ANY],
            [fake_data1, fake_data2],
        )


class TestSendQRISLinkageStatusEvent(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.partner = PartnerFactory(name='amar')
        self.linkage = QrisPartnerLinkageFactory(
            customer_id=self.customer.id,
            partner_id=self.partner.id
        )

    @mock.patch(
        'juloserver.moengage.services.use_cases.construct_qris_linkage_status_change_event_data'
    )
    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_send_qris_linkage_status_change_to_moengage(
        self,
        mock_send_to_moengage,
        mock_construct_qris_linkage_status_change_data,
    ):

        user_attributes = {"fake": "data"}
        event_data = {"fake2": "data2"}
        fake_data = (user_attributes, event_data)

        mock_construct_qris_linkage_status_change_data.return_value = fake_data

        # call func
        send_qris_linkage_status_change_to_moengage(
            linkage_id=self.linkage.id,
        )

        mock_construct_qris_linkage_status_change_data.assert_called_once_with(
            customer_id=self.customer.id,
            partner_id=self.partner.id,
            event_type=MoengageEventType.QRIS_LINKAGE_STATUS,
        )

        upload_record = MoengageUpload.objects.filter(
            customer_id=self.customer.id,
            type=MoengageEventType.QRIS_LINKAGE_STATUS,
        ).last()

        self.assertIsNotNone(upload_record)

        # assertions
        mock_send_to_moengage.assert_called_once_with(
            [upload_record.id],
            [user_attributes, event_data],
        )


class TestSendQRISMAStatus(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.qris_funnel_last_log = QrisFunnelLastLogFactory(
            customer_id=self.customer.id,
            read_master_agreement_date=date.today(),
            visit_lending_page_date = date.today(),
            open_master_agreement_date = date.today()
        )

    @mock.patch('juloserver.moengage.services.use_cases.construct_data_moengage_user_attributes')
    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_send_sign_master_agreement_status_event_to_moengage(
        self,
        mock_send_to_moengage,
        mock_construct_data_moengage_user_attributes,
    ):

        fake_data = {"i used to think": "my life was a tragedy"}

        mock_construct_data_moengage_user_attributes.return_value = fake_data

        # call func
        send_qris_master_agreement_data_moengage_bulk(
            customer_ids=[self.customer.id],
            upload_batch_id=1
        )

        # assertions

        mock_send_to_moengage.assert_called_once_with(
            [ANY],
            [fake_data],
        )


@mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
class TestSendLoyaltyMissionProgressDataEventToMoengage(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)

    def test_send_loyalty_mission_progress_data_event_to_moengage(
        self, mock_send_to_moengage
    ):
        mission_progress_data = [
            {'mission_progress_id': 3, 'status': 'completed'},
            {'mission_progress_id': 4, 'status': 'in_progress'},
            {'mission_progress_id': 5, 'status': 'in_progress'},
            {'mission_progress_id': 2, 'status': 'claimed'}
        ]
        send_loyalty_mission_progress_data_event_to_moengage(
            self.customer.id, mission_progress_data
        )

        me_upload = MoengageUpload.objects.filter(
            type=MoengageEventType.LOYALTY_MISSION, customer_id=self.customer.id
        ).last()

        self.assertIsNotNone(me_upload)
        mock_send_to_moengage.assert_called_once()


class TestSendJuloFinancingBulk(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.loan = LoanFactory(
            application=self.application,
            loan_status=StatusLookupFactory(status_code=220),
            customer=self.customer,
        )

    @mock.patch('juloserver.moengage.services.use_cases.construct_julo_financing_event_data')
    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_send_julo_financing_event_to_moengage_bulk(
        self, mock_send_to_moengage, mock_construct
    ):
        expected_user_attrs = {"nobita": "shizuka"}
        expected_event_data = {"luffy": "nami"}

        mock_construct.return_value = expected_user_attrs, expected_event_data

        send_julo_financing_event_to_moengage_bulk([self.customer.id])
        upload_batch = MoengageUploadBatch.objects.filter(
            type=MoengageEventType.JULO_FINANCING,
            status='all_dispatched',
        ).first()
        self.assertIsNotNone(upload_batch)

        upload_record = MoengageUpload.objects.filter(
            type=MoengageEventType.JULO_FINANCING,
            customer_id=self.customer.id,
            moengage_upload_batch_id=upload_batch.id,
        ).first()

        self.assertIsNotNone(upload_record)

        mock_construct.assert_called_once_with(
            event_type=MoengageEventType.JULO_FINANCING,
            customer_id=self.customer.id,
        )
        mock_send_to_moengage.assert_called_once_with(
            moengage_upload_ids=[ANY], data_to_send=[expected_user_attrs, expected_event_data]
        )


class TestSendJFinancingVerificationStatus(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.application.application_status = StatusLookupFactory(status_code=190)
        self.application.save()
        self.loan = LoanFactory(
            application=self.application,
            loan_status=StatusLookupFactory(status_code=220),
            customer=self.customer,
        )
        self.checkout = JFinancingCheckoutFactory(
            customer=self.customer, courier_name="test", courier_tracking_id="123231213"
        )
        self.verification = JFinancingVerificationFactory(
            j_financing_checkout=self.checkout,
            loan=self.loan,
            validation_status=JFinancingStatus.ON_REVIEW,
        )

    @mock.patch('juloserver.moengage.services.data_constructors.timezone.now')
    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_send_julo_financing_event_when_change_status(
        self, mock_send_to_moengage, mock_time_zone_now
    ):
        event_time = timezone.localtime(datetime(2024, 8, 9))
        mock_time_zone_now.return_value = event_time
        list_statuses = [
            JFinancingStatus.ON_REVIEW,
            JFinancingStatus.ON_DELIVERY,
            JFinancingStatus.COMPLETED,
        ]

        for status in list_statuses:
            expected_event_attr = {
                "type": "event",
                "customer_id": self.customer.id,
                "device_id": self.application.device.gcm_reg_id,
                "actions": [
                    {
                        "action": "test",
                        "attributes": {},
                        "platform": "ANDROID",
                        "current_time": event_time.timestamp(),
                        "user_timezone_offset": event_time.utcoffset().seconds,
                    }
                ],
            }
            expected_user_attr = {
                'type': 'customer',
                'customer_id': self.customer.id,
                'attributes': {
                    'customer_id': self.customer.id,
                    'platforms': [{'platform': 'ANDROID', 'active': 'true'}],
                },
            }
            self.verification.validation_status = status
            self.verification.save()
            if status == JFinancingStatus.ON_REVIEW:
                event_type = MoengageEventType.JFINANCING_TRANSACTION
                expected_event_attr['actions'][0]['attributes'] = {
                    "j_financing_product_name": self.checkout.j_financing_product.name
                }
            if status == JFinancingStatus.ON_DELIVERY:
                event_type = MoengageEventType.JFINANCING_DELIVERY
                expected_event_attr['actions'][0]['attributes'] = {
                    "courier_name": self.checkout.courier_name,
                    "tracking_id": self.checkout.courier_tracking_id,
                }
            if status == JFinancingStatus.COMPLETED:
                event_type = MoengageEventType.JFINANCING_COMPLETED
                expected_event_attr['actions'][0]['attributes'] = {
                    "j_financing_product_name": self.checkout.j_financing_product.name
                }

            expected_event_attr['actions'][0]['action'] = event_type
            send_event_jfinancing_verification_status_change(self.customer.pk, self.verification.pk)
            upload_record = MoengageUpload.objects.filter(
                type=event_type,
                customer_id=self.customer.id,
            ).first()

            self.assertIsNotNone(upload_record)
            mock_send_to_moengage.assert_called_with(
                [upload_record.id], [expected_user_attr, expected_event_attr]
            )

    @mock.patch('juloserver.moengage.services.data_constructors.timezone.now')
    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_send_julo_financing_event_with_verification_status_not_exist(
        self, mock_send_to_moengage, mock_time_zone_now
    ):
        event_time = timezone.localtime(datetime(2024, 8, 9))
        mock_time_zone_now.return_value = event_time
        list_statuses = [
            JFinancingStatus.INITIAL,
            JFinancingStatus.CONFIRMED,
            JFinancingStatus.CANCELED,
        ]

        for status in list_statuses:
            with self.assertRaises(MoengageTypeNotFound):
                self.verification.validation_status = status
                self.verification.save()
                send_event_jfinancing_verification_status_change(
                    self.customer.pk, self.verification.pk
                )
