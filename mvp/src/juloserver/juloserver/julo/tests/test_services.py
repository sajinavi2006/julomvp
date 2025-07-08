from __future__ import absolute_import
from builtins import str
from juloserver.account.models import ExperimentGroup, AccountCycleDayHistory
from juloserver.application_flow.models import ApplicationRiskyCheck
from juloserver.application_flow.services import suspicious_hotspot_app_fraud_check
from juloserver.application_flow.factories import ApplicationRiskyCheckFactory, ExperimentSettingFactory
import pytest
import mock
import json
from mock import patch, MagicMock
from datetime import datetime, timedelta
from mock_django.query import QuerySetMock

from django.test.testcases import TestCase, override_settings

from juloserver.loan.services.lender_related import payment_point_disbursement_process
from juloserver.followthemoney.models import LenderTransactionMapping
from juloserver.julo.formulas import filter_due_dates_by_experiment
from .factories import (
    AddressGeolocationFactory,
    ApplicationJ1Factory,
    LoanFactory,
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
    SkiptraceFactory,
    SepulsaTransactionFactory,
)
from .factories import PaymentFactory, RobocallTemplateFactory, PaybackTransactionFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.models import StatusLookup, Payment
from juloserver.streamlined_communication.test.factories import StreamlinedCommunicationFactory
from juloserver.julo.services2.voice import get_voice_template, excluding_risky_payment_dpd_minus
from juloserver.julo.constants import VoiceTypeStatus
from juloserver.julo.clients.voice_v2 import JuloVoiceClientV2
from juloserver.nexmo.tests.factories import RobocallCallingNumberChangerFactory
from juloserver.apiv2.models import PdCollectionModelResult, PdCollectionModelResultManager
from juloserver.loan_refinancing.tests.factories import (
    LoanRefinancingRequestFactory, WaiverRequestFactory)
from juloserver.payback.tests.factories import WaiverTempFactory
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.sdk.tests.factories import AxiataCustomerDataFactory
from juloserver.julo.tests.factories import (
    ProductLineFactory,
    PartnerOriginationDataFactory,
    StatusLookupFactory,
)
from juloserver.julo.models import ProductLine, DashboardBuckets

from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.tests.factories import (
    LoanFactory,
    PaymentFactory,
    ApplicationFactory,
    ReferralSystemFactory,
    ApplicationHistoryFactory,
    CreditScoreFactory,
    FeatureSettingFactory,
    CommsBlockedFactory,
    DeviceFactory,
    FruadHotspotFactory,
    PartnerFactory,
    PaymentMethodFactory
)
from juloserver.julo.services import *
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountPropertyFactory,
    AccountPropertyHistoryFactory,
    AccountTransactionFactory,
    WorkflowFactory
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.services import (
    autodialer_next_turn,
    update_application_checklist_collection,
)
from juloserver.cfs.tests.factories import CfsActionPointsFactory
from juloserver.julo.services2.sepulsa import SepulsaService
from juloserver.loan.services.loan_related import (
    get_first_payment_date_by_application,
    get_ldde_v2_status,
    check_ldde_v2,
    is_eligible_auto_adjust_due_date,
    get_auto_adjust_due_date,
)
from juloserver.payment_point.clients import get_julo_sepulsa_loan_client

from juloserver.dana.tests.factories import (
    DanaCustomerDataFactory,
    DanaApplicationReferenceFactory,
)
from juloserver.account.constants import LDDEReasonConst
from juloserver.account.services.account_related import (
    get_data_from_ana_calculate_cycle_day,
    calculate_cycle_day_from_ana,
)

from juloserver.julocore.tests import force_run_on_commit_hook
from juloserver.loan.constants import LoanFeatureNameConst

@pytest.mark.django_db
@override_settings(SUSPEND_SIGNALS=True)
class TestServicesProcessPartialPayment(TestCase):
    def setUp(self):
        self.status_210 = StatusLookup.objects.get(status_code=210)
        self.status_310 = StatusLookup.objects.get(status_code=310)
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory(customer=self.customer, application=self.application, loan_status=self.status_210)
        for payment in self.loan.payment_set.all():
            payment.payment_status = self.status_310
            payment.save(update_fields=['payment_status',
                                        'udate'])
        self.note = ""
        self.user = AuthUserFactory()
        self.paid_date_str = datetime.today().strftime('%d-%m-%Y')

        for i in range(1,11):
            CfsActionPointsFactory(id=i, multiplier=0.001, floor=5, ceiling=25, default_expiry=180)

    @patch('juloserver.julo.services.process_unassignment_when_paid')
    @patch('juloserver.cootek.tasks.cancel_phone_call_for_payment_paid_off')
    @patch('juloserver.minisquad.tasks2.delete_paid_payment_from_intelix_if_exists_async')
    @patch('juloserver.julo.services.send_push_notif_async')
    @mock.patch('juloserver.julo.clients.centerix.JuloCenterixClient.upload_centerix_payment_data')
    @mock.patch('juloserver.minisquad.services.insert_data_into_commission_table')
    def test_correct_payment(self,
        mocked_task1,
        mocked_task2, mock_task, mock_delete_task,
        mock_cancel_phone_call_for_payment_paid_off,
        mock_process_unassignment_when_paid):
        mocked_task1.return_value = True
        mocked_task2.return_value = True
        payment = self.loan.payment_set.all().order_by("due_date").first()

        partial_payment_amount = payment.due_amount

        process_partial_payment(payment, partial_payment_amount,
                                self.note, self.paid_date_str)

        payment.refresh_from_db()
        self.assertEqual(payment.payment_status.status_code, StatusLookup.PAID_ON_TIME_CODE)
        self.assertEqual(payment.due_amount, 0)

    @mock.patch('juloserver.julo.clients.centerix.JuloCenterixClient.upload_centerix_payment_data')
    @mock.patch('juloserver.minisquad.services.insert_data_into_commission_table')
    def test_under_paid(self, mocked_task1, mocked_task2):
        mocked_task1.return_value = True
        mocked_task2.return_value = True
        payment = self.loan.payment_set.all().order_by("due_date").first()

        under_paid_by = 1000
        partial_payment_amount = payment.due_amount - under_paid_by

        process_partial_payment(payment, partial_payment_amount,
                                self.note, self.paid_date_str)

        payment.refresh_from_db()
        self.assertEqual(payment.payment_status.status_code, StatusLookup.PAYMENT_NOT_DUE_CODE)
        self.assertEqual(payment.due_amount, under_paid_by)

    @patch('juloserver.julo.services.process_unassignment_when_paid')
    @patch('juloserver.cootek.tasks.cancel_phone_call_for_payment_paid_off')
    @patch('juloserver.minisquad.tasks2.delete_paid_payment_from_intelix_if_exists_async')
    @patch('juloserver.julo.services.send_push_notif_async')
    @mock.patch('juloserver.julo.clients.centerix.JuloCenterixClient.upload_centerix_payment_data')
    @mock.patch('juloserver.minisquad.services.insert_data_into_commission_table')
    def test_over_paid(self, mocked_task1, mocked_task2,
        mock_task, mock_delete_task,
        mock_cancel_phone_call_for_payment_paid_off,
        mock_process_unassignment_when_paid):
        mocked_task1.return_value = True
        mocked_task2.return_value = True
        payment = self.loan.payment_set.all().order_by("due_date").first()
        query = self.loan.payment_set.filter(due_date__gt=payment.due_date)
        second_payment = query.order_by("due_date").first()
        second_payment_orig_due = second_payment.due_amount

        over_paid_by = 1000
        partial_payment_amount = payment.due_amount + over_paid_by

        process_partial_payment(payment, partial_payment_amount,
                                self.note, self.paid_date_str)

        payment.refresh_from_db()
        second_payment.refresh_from_db()
        self.assertEqual(payment.payment_status.status_code, StatusLookup.PAID_ON_TIME_CODE)
        self.assertEqual(payment.due_amount, 0)
        self.assertEqual(second_payment.payment_status.status_code, StatusLookup.PAYMENT_NOT_DUE_CODE)
        self.assertEqual(second_payment.due_amount, second_payment_orig_due - over_paid_by)

    def test_get_google_calendar_attachment_with_generated_link(self):
        self.loan.julo_bank_name = 'Bank BCA'
        self.application.product_line.product_line_code = ProductLineCodes.MTL1
        # test with url_link
        attachment_dict_with, content_type_with, url_link = get_google_calendar_attachment(self.application,
                                                                                           is_generate_link=True)
        # test without url_link
        attachment_dict, content_type = get_google_calendar_attachment(self.application, is_generate_link=False)
        # test with url_link
        self.assertTrue(attachment_dict_with, None)
        self.assertTrue(content_type_with, None)
        self.assertTrue(url_link, None)
        # test without url_link
        self.assertTrue(attachment_dict, None)
        self.assertTrue(content_type, None)

    def test_get_next_unpaid_loan(self):
        self.loan.loan_status_id = 220
        self.loan.save()
        result = get_next_unpaid_loan(self.customer)
        assert result.id == self.loan.id

    @patch('juloserver.julo.services.process_unassignment_when_paid')
    @patch('juloserver.cootek.tasks.cancel_phone_call_for_payment_paid_off')
    @patch('juloserver.minisquad.tasks2.delete_paid_payment_from_intelix_if_exists_async')
    @patch('juloserver.julo.services.send_push_notif_async')
    @mock.patch('juloserver.referral.services.generate_customer_level_referral_code')
    @mock.patch('juloserver.julo.clients.centerix.JuloCenterixClient.upload_centerix_payment_data')
    @mock.patch('juloserver.minisquad.services.insert_data_into_commission_table')
    def test_over_paid_next_loan(
            self, mocked_task1, mocked_task2,
            mock_generate_customer_level_referral_code,
            mock_task,
            mock_delete_task,
            mock_cancel_phone_call_for_payment_paid_off,
            mock_process_unassignment_when_paid):
        mocked_task1.return_value = True
        mocked_task2.return_value = True
        loan_2 = LoanFactory(customer=self.customer)
        loan_2.loan_status_id = 220
        loan_2.save()
        payment = self.loan.payment_set.all().order_by("due_date").first()
        query = self.loan.payment_set.filter(due_date__gt=payment.due_date)
        second_payment = query.order_by("due_date").first()

        over_paid_by = 0
        partial_payment_amount = payment.due_amount + over_paid_by

        process_partial_payment(payment, partial_payment_amount,
                                self.note, self.paid_date_str, 0)

        payment.refresh_from_db()
        loan_2.refresh_from_db()
        self.assertEqual(payment.payment_status.status_code, StatusLookup.PAID_ON_TIME_CODE)
        self.assertEqual(payment.due_amount, 0)
        self.assertEqual(payment.loan.loan_status_id, 220)
        self.assertEqual(loan_2.loan_status_id, 220)


class TestServicesVoiceTemplate(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory(customer=self.customer, application=self.application)
        self.payment = PaymentFactory(loan=self.loan)
        self.streamline = StreamlinedCommunicationFactory()

    def test_get_voice_template_1(self):
        ncco_object_test_reminder = get_voice_template(VoiceTypeStatus.PAYMENT_REMINDER, self.payment.id,
                                                       self.streamline.id)
        self.assertIsNotNone(ncco_object_test_reminder)

    def test_get_voice_template_2(self):
        self.streamline.time_out_duration = None
        self.streamline.save()
        ncco_object_test_reminder = get_voice_template(VoiceTypeStatus.PAYMENT_REMINDER, self.payment.id,
                                                       self.streamline.id)
        self.assertIsNotNone(ncco_object_test_reminder)

    @mock.patch('django.template.loader.render_to_string')
    @mock.patch('juloserver.julo.services2.voice.parse_template_reminders')
    def test_get_voice_template_3(self, mocked_parse, mocked_render):
        mocked_parse.return_value = 'voice_reminder_T-5_MTL'
        mocked_render.return_value = "[{'action': 'record', 'eventUrl': " \
                                     "['https://api-dev.julofinance.com/api/integration/" \
                                     "v1/callbacks/voice-call-recording-callback']}, {u'action': u'talk'," \
                                     " u'text': u'Selamat siangIbu Deassy, angsuran JULO Anda 1620000 rupiah " \
                                     "akan jatuh tempodalam 5 hari.', u'voiceName': u'Damayanti'}, {u'action': " \
                                     "u'talk', u'text': u'Bayar sekarang dan dapatkan kesbek sebesar 1 kali.', " \
                                     "u'voiceName': u'Damayanti'}, {u'action': u'talk', u'text': u'Tekan 1 untuk " \
                                     "konfirmasi. Terima kasih', u'voiceName': u'Damayanti'}, {u'action': u'input', " \
                                     "u'maxDigits': 1, u'eventUrl': [u'https://api-dev.julofinance.com/api/" \
                                     "integration/v1/callbacks/voice-call/payment_reminder/4000001468'], " \
                                     "'timeOut': 3}]"
        ncco_object_test_reminder = get_voice_template(VoiceTypeStatus.PAYMENT_REMINDER, self.payment.id)
        self.assertIsNotNone(ncco_object_test_reminder)

    def test_get_voice_template_ptp(self):
        self.payment.ptp_robocall_template = RobocallTemplateFactory()
        self.payment.save()
        ncco_object_test_reminder = get_voice_template(VoiceTypeStatus.PTP_PAYMENT_REMINDER, self.payment.id)
        self.assertIsNotNone(ncco_object_test_reminder)

    @mock.patch('juloserver.julo.services2.voice.get_voice_template')
    def test_voice_record_ptp(self, mocked_template):
        self.payment.ptp_robocall_template = RobocallTemplateFactory()
        self.payment.save()
        self.robocall_calling_number_changer = RobocallCallingNumberChangerFactory
        mocked_template.return_value = "[{'action': 'record', 'eventUrl': " \
                                       "['https://api-dev.julofinance.com/api/integration/" \
                                       "v1/callbacks/voice-call-recording-callback']}, {u'action': u'talk'," \
                                       " u'text': u'Selamat siangIbu Deassy, angsuran JULO Anda 1620000 rupiah " \
                                       "akan jatuh tempodalam 5 hari.', u'voiceName': u'Damayanti'}, {u'action': " \
                                       "u'talk', u'text': u'Bayar sekarang dan dapatkan kesbek sebesar 1 kali.', " \
                                       "u'voiceName': u'Damayanti'}, {u'action': u'talk', u'text': u'Tekan 1 untuk " \
                                       "konfirmasi. Terima kasih', u'voiceName': u'Damayanti'}, {u'action': u'input', " \
                                       "u'maxDigits': 1, u'eventUrl': [u'https://api-dev.julofinance.com/api/" \
                                       "integration/v1/callbacks/voice-call/payment_reminder/4000001468'], " \
                                       "'timeOut': 3}]"
        voice_client = JuloVoiceClientV2(1, 2, 2, 3, 'sdf', 5, 6)
        voice_client.create_call = mock.Mock(return_value={
            "dtmf": None,
            "conversation_uuid": "5efe6463-e994-4b3d-b4bf-33a4f62a4472",
            "uuid": "f3624a46-ae73-4b18-82f3-5a2a6910d899",
            "status": "started",
            "direction": "outbound"
        })
        response = voice_client.ptp_payment_reminder('08234567890', self.payment.id)
        self.assertIsNotNone(response)

    def test_excluding_risky_payment_dpd_minus_case_payment_empty(self):
        payments = []
        result, _ = excluding_risky_payment_dpd_minus(payments)
        assert result == payments

    def test_excluding_risky_payment_dpd_minus(self):
        today = datetime.now().date()
        dpd = -5
        due_date = today - timedelta(dpd)
        self.payment.due_date = due_date
        self.payment.save()
        PdCollectionModelResult.objects.create(
            payment=self.payment,
            range_from_due_date=str(dpd),
            prediction_before_call=0.1,
            prediction_after_call=0.1,
            due_amount=10,
            sort_rank=5,
            model_version='Now or Never v2',
            prediction_date=today
        )
        payments = Payment.objects.filter(id=self.payment.id)
        result, _ = excluding_risky_payment_dpd_minus(payments)
        assert not result

    def test_excluding_risky_payment_dpd_minus_case_2(self):
        PdCollectionModelResult.objects.create(
            payment=self.payment,
            range_from_due_date='5',
            prediction_before_call=0.1,
            prediction_after_call=0.1,
            due_amount=10,
            sort_rank=5
        )
        payments = Payment.objects.filter(id=self.payment.id)
        result, _ = excluding_risky_payment_dpd_minus(payments)
        assert result and result[0].id == self.payment.id


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestProcessReceivedPayment(TestCase):
    def setUp(self):
        self.status_210 = StatusLookup.objects.get(status_code=210)
        self.status_310 = StatusLookup.objects.get(status_code=310)
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory(customer=self.customer, application=self.application,
                                loan_status=self.status_210)
        for payment in self.loan.payment_set.all().order_by("payment_number"):
            payment.payment_status = self.status_310
            payment.due_date = datetime.today().date()
            payment.paid_date = datetime.today().date()
            if payment.payment_number == 1:
                payment.paid_date = datetime.today().date() + relativedelta(days=4)
            if payment.payment_number == 2:
                payment.paid_date = datetime.today().date() + relativedelta(days=10)
            payment.save(update_fields=['payment_status', 'due_date', 'paid_date', 'udate'])
        self.note = ""
        self.user = AuthUserFactory()
        self.paid_date_str = datetime.today().strftime('%d-%m-%Y')

        for i in range(1,11):
            CfsActionPointsFactory(id=i, multiplier=0.001, floor=5, ceiling=25, default_expiry=180)


    @patch('juloserver.julo.services.send_push_notif_async')
    @patch('juloserver.julo.services.check_eligibility_of_covid_loan_refinancing')
    def test_refinancing_is_not_activated_and_get_cashback(self, mock_check_eligibility, mock_task):
        loan_ref_req = LoanRefinancingRequestFactory(loan=self.loan, status='Approved')
        payment = self.loan.payment_set.all().order_by("payment_number").last()
        self.loan.product.cashback_payment_pct = 0.01
        self.loan.product.save()
        mock_check_eligibility.return_value = False
        process_received_payment(payment)

        payment.refresh_from_db()
        self.assertEqual(payment.payment_status.status_code, StatusLookup.PAID_ON_TIME_CODE)
        self.assertNotEqual(int(payment.cashback_earned), 0)

        loan_ref_req.refresh_from_db()
        self.assertEqual(loan_ref_req.status, 'Approved')

    @patch('juloserver.julo.services.send_push_notif_async')
    def test_refinancing_is_not_activated_and_not_get_cashback(self, mock_task):
        loan_ref_req = LoanRefinancingRequestFactory(loan=self.loan, status='Approved')
        payment = self.loan.payment_set.all().order_by("payment_number").last()
        self.loan.product.cashback_payment_pct = 0.01
        process_received_payment(payment)

        payment.refresh_from_db()
        self.assertEqual(payment.payment_status.status_code, StatusLookup.PAID_ON_TIME_CODE)
        self.assertEqual(int(payment.cashback_earned), 0)

        loan_ref_req.refresh_from_db()
        self.assertEqual(loan_ref_req.status, 'Activated')

    @patch('juloserver.julo.services.send_push_notif_async')
    def test_refinancing_and_not_get_cashback(self, mock_task):
        loan_ref_req = LoanRefinancingRequestFactory(loan=self.loan, status='Activated')
        payment = self.loan.payment_set.all().order_by("payment_number").last()
        self.loan.product.cashback_payment_pct = 0.01
        process_received_payment(payment)

        payment.refresh_from_db()
        self.assertEqual(payment.payment_status.status_code, StatusLookup.PAID_ON_TIME_CODE)
        self.assertEqual(int(payment.cashback_earned), 0)

        loan_ref_req.refresh_from_db()
        self.assertEqual(loan_ref_req.status, 'Activated')

    @patch('juloserver.julo.services.send_push_notif_async')
    def test_not_refinancing_and_get_cashback(self, mock_task):
        payment = self.loan.payment_set.all().order_by("payment_number").last()
        self.loan.product.cashback_payment_pct = 0.01
        self.loan.product.save()
        process_received_payment(payment)

        payment.refresh_from_db()
        self.assertEqual(payment.payment_status.status_code, StatusLookup.PAID_ON_TIME_CODE)
        self.assertNotEqual(int(payment.cashback_earned), 0)

    @patch('juloserver.julo.services.send_push_notif_async')
    def test_refinancing_paid_grace_period_and_not_get_cashback(self, mock_task):
        loan_ref_req = LoanRefinancingRequestFactory(loan=self.loan, status='Activated')
        payment = self.loan.payment_set.get(payment_number=1)
        self.loan.product.cashback_payment_pct = 0.01
        process_received_payment(payment)

        payment.refresh_from_db()
        self.assertEqual(payment.payment_status.status_code, StatusLookup.PAID_WITHIN_GRACE_PERIOD_CODE)
        self.assertEqual(int(payment.cashback_earned), 0)

        loan_ref_req.refresh_from_db()
        self.assertEqual(loan_ref_req.status, 'Activated')

    @patch('juloserver.julo.services.send_push_notif_async')
    def test_refinancing_paid_late_and_not_get_cashback(self, mock_task):
        loan_ref_req = LoanRefinancingRequestFactory(loan=self.loan, status='Activated')
        payment = self.loan.payment_set.get(payment_number=2)
        self.loan.product.cashback_payment_pct = 0.01
        process_received_payment(payment)

        payment.refresh_from_db()
        self.assertEqual(payment.payment_status.status_code, StatusLookup.PAID_LATE_CODE)
        self.assertEqual(int(payment.cashback_earned), 0)

        loan_ref_req.refresh_from_db()
        self.assertEqual(loan_ref_req.status, 'Activated')

    @patch('juloserver.julo.services.send_push_notif_async')
    def test_refinancing_activated_before_and_not_waiver_request(self, mock_task):
        LoanRefinancingRequestFactory(
            loan=self.loan, status='Activated', product_type='R4')
        # create loan refinancing request current
        LoanRefinancingRequestFactory(
            loan=self.loan, status='Proposed', product_type='R6')
        payment = self.loan.payment_set.all().order_by("payment_number").last()
        WaiverTempFactory(loan=self.loan, status=WaiverConst.IMPLEMENTED_STATUS)

        self.loan.product.cashback_payment_pct = 0.01
        self.loan.product.save()
        # not waiver request
        process_received_payment(payment)

        payment.refresh_from_db()
        self.assertEqual(payment.payment_status.status_code, StatusLookup.PAID_ON_TIME_CODE)
        self.assertNotEqual(int(payment.cashback_earned), 0)

    @patch('juloserver.julo.services.send_push_notif_async')
    def test_refinancing_activated_before_and_has_waiver_request(self, mock_task):
        loan_ref_req_before = LoanRefinancingRequestFactory(
            loan=self.loan, status='Activated', product_type='R4')
        # create loan refinancing request current
        LoanRefinancingRequestFactory(
            loan=self.loan, status='Proposed', product_type='R6')
        payment = self.loan.payment_set.all().order_by("payment_number").first()

        waiver_temp = WaiverTempFactory(loan=self.loan, status=WaiverConst.IMPLEMENTED_STATUS)
        waiver_payment_temp = WaiverPaymentTemp.objects.filter(waiver_temp=waiver_temp).first()
        waiver_payment_temp.payment = payment
        waiver_payment_temp.save()

        self.loan.product.cashback_payment_pct = 0.01
        WaiverRequestFactory(
            loan=self.loan, program_name=loan_ref_req_before.product_type,
            last_payment_number=3)
        payment = self.loan.payment_set.filter(payment_number=2).first()
        payment.paid_date = payment.due_date - timedelta(days=1)
        payment.save()
        process_received_payment(payment)

        payment.refresh_from_db()
        self.assertEqual(payment.payment_status.status_code, StatusLookup.PAID_ON_TIME_CODE)
        self.assertEqual(int(payment.cashback_earned), 0)

    @patch('juloserver.julo.services.send_push_notif_async')
    def test_refinancing_activated_before_and_payment_in_valid_cashback_range(self, mock_task):
        loan_ref_req_before = LoanRefinancingRequestFactory(
            loan=self.loan, status='Activated', product_type='R4')
        # create loan refinancing request current
        LoanRefinancingRequestFactory(
            loan=self.loan, status='Proposed', product_type='R6')
        payment = self.loan.payment_set.all().order_by("payment_number").first()
        WaiverTempFactory(loan=self.loan)

        self.loan.product.cashback_payment_pct = 0.01
        self.loan.product.save()
        last_payment = self.loan.payment_set.all().order_by("payment_number").last()
        WaiverRequestFactory(
            loan=self.loan, program_name=loan_ref_req_before.product_type,
            last_payment_number=payment.payment_number)

        process_received_payment(last_payment)

        last_payment.refresh_from_db()
        self.assertEqual(last_payment.payment_status.status_code, StatusLookup.PAID_ON_TIME_CODE)
        self.assertNotEqual(int(last_payment.cashback_earned), 0)


# class TestFuncServiceMarkIsRobocallActiveOrNot(TestCase):
#     def test_condition_payment_status_on_time(self):
#         application = ApplicationFactory()

#         loan = LoanFactory(application=application)

#         payment = PaymentFactory(status=PaymentStatusCodes.PAID_ON_TIME, loan=loan)

#         payment_set = payment.loan.payment_set.all()

#         i = 0
#         for payment in payment_set:
#             payment.payment_number = i + 1
#             payment.save()

#             i += 1

#         payment.loan.application.product_line.product_line_code = ProductLineCodes.MTL1
#         payment.payment_status.status_code = PaymentStatusCodes.PAID_ON_TIME
#         payment.payment_number = 1
#         payment.is_robocall_active = False

#         # call the subject function
#         mark_is_robocall_active_or_inactive(payment)

#         payment_set = payment.loan.payment_set.all()

#         expected_result = [True] * (payment_set.count() - 1)

#         self.assertItemsEqual(payment_set.values_list('is_robocall_active', flat=True)[1:], expected_result)

    # in consistency result, also happen in staging and develop
    # def test_condition_payment_status_not_on_time(self):
    #     loan = LoanFactory()
    #
    #     payment = PaymentFactory(status=PaymentStatusCodes.PAID_LATE, loan=loan)
    #
    #     # call the subject function
    #     mark_is_robocall_active_or_inactive(payment)
    #
    #     payment_set = payment.loan.payment_set.all()
    #
    #     expected_result = [False] * payment_set.count()
    #     self.assertItemsEqual(payment_set.values_list('is_robocall_active', flat=True), expected_result)


class TestFuncServiceGetExtraContext(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_condition_cashback_multiplier(self):
        """TODO: performing test"""

    def test_condition_payment_cashback_amount(self):
        """TODO: performing test"""

    def test_condition_payment_cashback_amount_due_date_minus_2(self):
        """TODO: performing test"""

    def test_condition_payment_cashback_amount_due_date_minus_4(self):
        """TODO: performing test"""

    def test_condition_payment_details_url(self):
        """TODO: performing test"""

    def test_condition_how_pay_url(self):
        """TODO: performing test"""


class TestFuncServiceIsLastPaymentStatusNotPaid(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_condition_last_payment(self):
        """TODO: performing test"""

    def test_condition_not_last_payment(self):
        """TODO: performing test"""


class TestFuncServiceCheckRiskyCustomer(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_condition_risky(self):
        """TODO: performing test"""

    def test_condition_not_risky(self):
        """TODO: performing test"""


class TestFuncServiceGetPaymentURLFromPayment(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_condition_partner(self):
        """TODO: performing test"""

    def test_condition_not_partner(self):
        """TODO: performing test"""


class TestFuncServiceGetAndSaveFDCData(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_condition_fdc_request_normal(self):
        """TODO: performing test"""

    def test_condition_fdc_request_normal_but_not_ok(self):
        """TODO: performing test"""

    def test_condition_fdc_request_raise_exception(self):
        """TODO: performing test"""


class TestFuncServiceGetNexmoFromPhoneNumber(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_condition_is_robocall_calling_number_changer(self):
        """TODO: performing test"""

    def test_condition_not_robocall_calling_number_changer(self):
        """TODO: performing test"""


class TestFuncServiceStoreToTemporaryTable(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_without_big_control_structure(self):
        """TODO: performing test"""


class TestFuncServiceGetWarningLetterGoogleCalendarAttachment(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_without_big_control_structure(self):
        """TODO: performing test"""


class TestFuncServiceSuspectAccountNumberIsVA(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_condition_bank_account_number_none(self):
        """TODO: performing test"""

    def test_condition_bank_account_number_exists(self):
        """TODO: performing test"""

    def test_condition_bank_account_number_exists_within_bank_entry_lt_va(self):
        """TODO: performing test"""

    def test_condition_bank_account_number_exists_within_bank_entry_eq_va_but_in_exceptional_bank(self):
        """TODO: performing test"""


class TestFuncServiceFaspayPaymentInquiryStatement(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_without_big_control_structure(self):
        """TODO: performing test"""


class TestFuncServiceCEMB234Experiment(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_without_big_control_structure(self):
        """TODO: performing test"""


class TestFuncServiceSendPNPlayStoreRating(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_without_big_control_structure(self):
        """TODO: performing test"""


class TestFuncServiceCheckGoodCustomerOrNot(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_condition_has_application_and_days_lte_90_and_not_within_grace_period(self):
        """TODO: performing test"""

    def test_condition_has_no_application(self):
        """TODO: performing test"""


class TestFuncServiceCheckCustomerPromo(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_condition_promo_cashback(self):
        """TODO: performing test"""

    def test_condition_promo_not_cashback(self):
        """TODO: performing test"""


class TestFuncServiceCountPaymentDashboardBuckets(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_without_big_control_structure(self):
        """TODO: performing test"""

class TestFuncServiceAssignLenderInLoan(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_condition_with_loan(self):
        """TODO: performing test"""

    def test_condition_without_loan(self):
        """TODO: performing test"""


class TestFuncServiceGetFailedRobocallPayments(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_condition_local_time_wib(self):
        """TODO: performing test"""

    def test_condition_local_time_wit(self):
        """TODO: performing test"""

    def test_condition_local_time_wita(self):
        """TODO: performing test"""


class TestFuncServiceSortPaymentsByCollectionModel(TestCase):
    def setUp(self):
        """TODO: performing test setup"""

    def test_condition_(self):
        """TODO: performing test"""


class TestFuncServiceCheckReferralCashback(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceIsBankNameValidated(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceProcessBankAccountValidation(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceCheckEligibleForCampaignReferral(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceGetEmailSettingOptions(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceGetApplicationSPHP(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceGetHighestReapplyReason(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceGetPartnerApplicationStatusExpDate(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceGetExpiryDate(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceGetPdfContentFromHtml(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceCreateLoanAndPaymentsLaku6(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceGetLenderSphp(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceAutoDialerNextTurn(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceReverseRepaymentTransaction(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceSendEmailPaidOffGrab(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceSendEmailPaymentReminderGrab(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceFasPayPaymentProcessLoc(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceFasPayPaymentProcessLoan(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceGetLastStatement(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceFaspayPaymentInquiryLoc(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceFasPayPaymentInquiryLoan(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceProcessSepulsaTransactionFailed(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceActionCashbackSepulsaTransaction(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceUpdateLenderDisbursementCounter(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceGetAddressFromGeolocation(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceResetLenderDisburseCounter(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceUploadPaymentDetailsToCenterix(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceProcessChangeDueDate(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceProcessDeleteLateFee(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceExperimentationAutomateOffer(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceGetMonthlyIncomeByExperimentGroup(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceExperimentationCheckProbabilityFpdMetCriteria(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceExperimentationCheckLoanCountCriteria(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceExperimentationCheckThinFileCriteria(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceExperimentationCheckExpensePredictionCriteria(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceExperimentationCheckIncomeTrustIndexCriteria(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceExperimentationCheckIncomePredictionCriteria(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceExperimentationCheckReasonLastChangeStatusCriteria(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceExperimentationCheckCreditScoreCriteria(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceExperimentationCheckProductCriteria(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceExperimentationCheckApplicationXidCriteria(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceExperimentationCheckApplicationIdCriteria(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceIsCreditExperiment(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceExperimentation(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceRecordBulkDisbursementTransaction(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceEventEndYear(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceTriggerInfoApplicationPartner(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceTriggerInfoApplicationTokopedia(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceEnableOriginalPassword(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceDisableOriginalPassword(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceUpdateOffer(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceUpdateApplicationChecklistCollection(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceUpdateUndisclosedExpense(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceUpdateKtpRelations(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceUpdateApplicationField(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceUpdateApplicationChecklistData(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceGetUndisclosedExpenseDetail(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceGetApplicationCommentList(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceProcessDokuPayment(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceCheckUnprocessedDokuPayments(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceChooseNumberToRobocall(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServicePrimoUpdateSkiptrace(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceUpdateSkiptraceScore(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceProcessThumbnailUpload(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceProcessImageUpload(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceSendEmailCourtesy(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceSendEmailApplication(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceSendCustomEmailPaymentReminder(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServicesendDataToCollateralPartner(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceLinkToPartnerByProductLine(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceCreatePartnerAccountAttribution(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceGetPartnerAccountIdByPartnerRefferal(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceCheckPartnerAccountIdByApplication(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceSendCustomSmsPaymentReminder(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceProcessPaymentStatusChange(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceExperimentApplicationStatusChange(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceGetAllowedApplicationStatusesForOps(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceGetApplicationAllowedPath(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceCreateDataChecks(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceRunAutoDataChecksGps(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceRunAutoDataChecksFacebook(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceRunAutoDataChecks(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceUpdatePaymentInstallment(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceSimulateAdjustedPaymentInstallment(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceUpdateLoanAndPayments(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceCreateLoanAndPayments(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceChangeDueDates(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceChangeCycleDay(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServiceCreatePromoHistoryAndPaymentEvent(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestFuncServicePTPUpdate(TestCase):
    def setUp(self):
        """TODO: performing test setup"""


class TestPartnerApplicationStatusExpDate(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=150, status_new=160
        )
        self.application.application_status = StatusLookup.objects.get(status_code=160)

    def test_get_partner_application_status_exp_date(self):
        self.application.sphp_exp_date = datetime(2020, 9, 6, 0, 0)
        self.application.save()
        status = {'days': 3, 'status_old': 160, 'status_to': 171, 'target': 'PARTNER'}
        return_value = get_partner_application_status_exp_date(self.application)
        self.assertEqual(return_value, self.application.sphp_exp_date.date())


class TestGetGracePeriodDays(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.payment = self.loan.payment_set.first()

    def test_payment_j1(self):
        days = get_grace_period_days(None, True)
        self.assertEqual(days, Payment.GRACE_PERIOD_DAYS)

        self.loan.application = None
        days = get_grace_period_days(self.payment)
        self.assertEqual(days, Payment.GRACE_PERIOD_DAYS)

    def test_payment_non_j1(self):
        # not axiata
        days = get_grace_period_days(self.payment)
        self.assertEqual(days, Payment.GRACE_PERIOD_DAYS)

        ## axiata
        axiata_customer_data = AxiataCustomerDataFactory(
            application=self.loan.application, distributor='19')
        # not partner
        days = get_grace_period_days(self.payment)
        self.assertEqual(days, Payment.GRACE_PERIOD_DAYS)
        # partner, not feature setting
        PartnerOriginationDataFactory(id=19)
        days = get_grace_period_days(self.payment)
        self.assertEqual(days, Payment.GRACE_PERIOD_DAYS)
        # feature setting, parameter is empty
        feature_setting = FeatureSettingFactory(feature_name='axiata_distributor_grace_period')
        days = get_grace_period_days(self.payment)
        self.assertEqual(days, Payment.GRACE_PERIOD_DAYS)

        # set parameters
        feature_setting.parameters = {
            '19': {
                'name': 'test',
                'grace_period_days': 3,
                'is_active': True
            }
        }
        feature_setting.save()
        days = get_grace_period_days(self.payment)
        self.assertEqual(days, 3)


class TestPauseReminder(TestCase):

    def setUp(self):
        pass

    def test_check_account_payment_is_blocked_comms(self):
        today = timezone.localtime(timezone.now()).date()
        product_line = ProductLine.objects.filter(product_line_type='MTL1').first()
        loan = LoanFactory()
        loan.application.product_line = product_line
        loan.application.save()
        payment = loan.payment_set.order_by('payment_number').first()
        # not comms block
        result = check_payment_is_blocked_comms(payment, 'email')
        self.assertFalse(result)
        comms_blocked = CommsBlockedFactory(
            loan=loan, is_email_blocked=True, impacted_payments=[payment.id])
        # failed
        payment.due_date = today - timedelta(days=1)
        payment.save()
        result = check_payment_is_blocked_comms(payment, 'email')
        self.assertFalse(result)

        # success
        payment.due_date = today+timedelta(days=1)
        payment.save()
        result = check_payment_is_blocked_comms(payment, 'email')
        self.assertTrue(result)


class TestAccountPropertyUpdate(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.account_property = AccountPropertyFactory(account=self.account)
        self.account_property.is_proven = False
        self.account_property.proven_threshold = 10000
        self.account_property.save()
        self.account_property_history_first_time = AccountPropertyHistoryFactory(
            account_property=self.account_property,
            field_name='is_proven',
            value_old=False,
            value_new=True,
        )
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

    def test_update_is_proven_account_payment(self):
        update_is_proven_account_payment_level(self.account)
        self.account_property.refresh_from_db()
        self.assertFalse(self.account_property.is_proven)
        self.account_transaction = AccountTransactionFactory(
            account=self.account,
            transaction_type="payment",
            transaction_amount=9001,
            transaction_date=timezone.localtime(timezone.now()),
            accounting_date=timezone.localtime(timezone.now()),
            towards_principal=8000,
            towards_interest=1001,
            towards_latefee=0,
            can_reverse=True
        )

        update_is_proven_account_payment_level(self.account)
        self.account_property.refresh_from_db()
        self.assertTrue(self.account_property.is_proven)

    def test_update_bad_customer(self):
        self.account_property.is_proven = True
        self.account_property.proven_threshold = 10000
        self.account_property.save()
        update_is_proven_bad_customers(account=self.account)
        self.account_property.refresh_from_db()
        self.assertFalse(self.account_property.is_proven)


class TestGetDataApplicationChecklistCollection(TestCase):
    def setUp(self):
        pass

    def test_for_app_only(self):
        app = ApplicationFactory()
        create_application_checklist(app)
        result = get_data_application_checklist_collection(app, for_app_only=True)
        self.assertEqual(result['loan_purpose_desc']['statuses'], ['sd'])


class TestCheckFraudHotspot(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.setting = FeatureSettingFactory(feature_name='fraud_hotspot', is_active=True)

    def test_capture_device_geolocation(self):
        device = DeviceFactory()
        # device geolocation is not existed
        result = capture_device_geolocation(device, 3, 100, 'login')
        self.assertIsNotNone(result)

        # device geolocation is already existed
        result2 = capture_device_geolocation(device, 3, 100, 'login')
        self.assertEqual(result2.id, result.id)

    def test_check_fraud_hotspot(self):
        # feature setting is not existed
        result = check_fraud_hotspot_gps(10.801284, 106.714765)
        self.assertFalse(result)

        # feature setting is already existed
        # is fraud hotspot
        FruadHotspotFactory(
            latitude = 10.801479,
            longitude = 106.714033,
            radius = 1
        )
        result = check_fraud_hotspot_gps(10.801284, 106.714765)
        self.assertTrue(result)

        ## is not fraud hotspot
        result = check_fraud_hotspot_gps(10.797106, 106.703438)
        self.assertFalse(result)

        ## lat, long is string
        result = check_fraud_hotspot_gps('10.801284', '106.714765')
        self.assertTrue(result)

        ## lat, long is invalid
        self.assertRaises(JuloException, check_fraud_hotspot_gps, 'a', 106.714765)

    def test_disable_setting(self):
        self.setting.update_safely(is_active=False)

        # is fraud hotspot
        FruadHotspotFactory(
            latitude=10.801479,
            longitude=106.714033,
            radius=1
        )
        result = check_fraud_hotspot_gps(10.801284, 106.714765)
        self.assertFalse(result)

    @mock.patch('juloserver.julo.services.check_fraud_hotspot_gps')
    @mock.patch('juloserver.application_flow.services.capture_suspicious_app_risk_check')
    def test_fraud_hotspot_reverse_experiment(
            self, mock_capture_suspicious_app_risk_check, mock_check_fraud_hotspot_gps):
        address_geolocation = AddressGeolocationFactory(application=self.application)
        application_risky_check = ApplicationRiskyCheckFactory(
            application=self.application, is_fh_detected=True)
        app_id_last_two_digits = int(str(self.application.id)[-2:])
        current_date = timezone.localtime(timezone.now())
        fh_experiment = ExperimentSettingFactory(
            criteria={'test_group_last_two_digits_app_id':[app_id_last_two_digits]},
            code=ExperimentConst.FRAUD_HOTSPOT_REVERSE_EXPERIMENT, is_active=True,
            start_date=current_date, end_date=current_date + relativedelta(years=2))
        mock_check_fraud_hotspot_gps.return_value = False
        mock_capture_suspicious_app_risk_check.return_value = application_risky_check
        suspicious_hotspot_app_fraud_check(self.application)
        self.assertEqual(ExperimentGroup.objects.count(), 0)
        self.assertTrue('FH DETECTED' in application_risky_check.get_fraud_list())
        mock_check_fraud_hotspot_gps.return_value = True
        suspicious_hotspot_app_fraud_check(self.application)
        self.assertEqual(ExperimentGroup.objects.count(), 1)
        self.assertEqual(ExperimentGroup.objects.last().group, 'experiment')
        self.assertFalse('FH DETECTED' in application_risky_check.get_fraud_list())
        fh_experiment.criteria = {'test_group_last_two_digits_app_id':[]}
        fh_experiment.save()
        suspicious_hotspot_app_fraud_check(self.application)
        self.assertEqual(ExperimentGroup.objects.count(), 2)
        self.assertEqual(ExperimentGroup.objects.last().group, 'control')


class TestAutoDialerNextTurn(TestCase):
    def setUp(self):
        self.buckets = DashboardBuckets.objects.create()
        self.buckets.app_122 = 10
        self.buckets.save()

    @mock.patch('django.utils.timezone.localtime')
    def test_auto_dialer_next_turn(self, mock_time):
        now_time = datetime(2020, 5, 10)
        mock_time.return_value = now_time
        next_ts = autodialer_next_turn(122)
        self.assertEqual(next_ts, now_time + timedelta(hours=3))

        self.buckets.app_122 = 60
        self.buckets.save()
        next_ts = autodialer_next_turn(122)
        self.assertEqual(next_ts, now_time + timedelta(hours=3))

        self.buckets.app_124 = 10
        self.buckets.save()
        next_ts = autodialer_next_turn(124)
        self.assertEqual(next_ts, now_time + timedelta(hours=2))

        self.buckets.app_124_j1 = 10
        self.buckets.save()
        next_ts = autodialer_next_turn(124)
        self.assertEqual(next_ts, now_time + timedelta(hours=2))

        self.buckets.app_124 = 60
        self.buckets.save()
        next_ts = autodialer_next_turn(124)
        self.assertEqual(next_ts, now_time + timedelta(hours=2))

        self.buckets.app_124_j1 = 60
        self.buckets.save()
        next_ts = autodialer_next_turn(124)
        self.assertEqual(next_ts, now_time + timedelta(hours=2))

        self.buckets.app_141 = 10
        self.buckets.save()
        next_ts = autodialer_next_turn(141)
        self.assertEqual(next_ts, now_time + timedelta(hours=2))

        self.buckets.app_141_j1 = 10
        self.buckets.save()
        next_ts = autodialer_next_turn(141)
        self.assertEqual(next_ts, now_time + timedelta(hours=2))

        self.buckets.app_141 = 60
        self.buckets.save()
        next_ts = autodialer_next_turn(141)
        self.assertEqual(next_ts, now_time + timedelta(hours=2))

        self.buckets.app_141_j1 = 60
        self.buckets.save()
        next_ts = autodialer_next_turn(141)
        self.assertEqual(next_ts, now_time + timedelta(hours=2))


class TestValidateString(TestCase):

    def test_string_validation(self):

        raw_string = 'asdasdasdÓ'
        result = remove_character_by_regex(raw_string, '[^\x20-\x7E]')
        assert result == 'asdasdasd'

        raw_string = 'ÓasdasdasdÓ'
        result = remove_character_by_regex(raw_string, '[^\x20-\x7E]')
        assert result == 'asdasdasd'

        raw_string = 'ÓasdasÓdasdÓ'
        result = remove_character_by_regex(raw_string, '[^\x20-\x7E]')
        assert result == 'asdasdasd'

        raw_string = 'asdasdasd'
        result = remove_character_by_regex(raw_string, '[^\x20-\x7E]')
        assert result == 'asdasdasd'


class TestGetApplicationPhoneNumber(TestCase):
    def test_get_from_application(self):
        app = ApplicationJ1Factory(mobile_phone_1='0834567890')
        ret_val = get_application_phone_number(app)

        self.assertEqual('+62834567890', ret_val)

    def test_get_from_customer(self):
        customer = CustomerFactory(phone='0834567890')
        app = ApplicationJ1Factory(mobile_phone_1='', customer=customer)
        ret_val = get_application_phone_number(app)

        self.assertEqual('+62834567890', ret_val)

    def test_get_from_skiptrace(self):
        customer = CustomerFactory(phone='')
        app = ApplicationJ1Factory(mobile_phone_1='', customer=customer)
        SkiptraceFactory(
            contact_source='mobile_phone_1',
            phone_number='+62834567890',
            customer=customer,
        )
        ret_val = get_application_phone_number(app)

        self.assertEqual('+62834567890', ret_val)

    def test_no_phone_number(self):
        customer = CustomerFactory(phone='')
        app = ApplicationJ1Factory(mobile_phone_1='', customer=customer)

        with self.assertRaises(InvalidPhoneNumberError):
            get_application_phone_number(app)


    def test_invalid_skiptrace_phone_number(self):
        customer = CustomerFactory(phone='')
        app = ApplicationJ1Factory(mobile_phone_1='', customer=customer)
        SkiptraceFactory(
            contact_source='mobile_phone_1',
            phone_number='0834567890',
            customer=customer,
        )

        with self.assertRaises(InvalidPhoneNumberError):
            get_application_phone_number(app)

class TestGetApplicationPhoneNumberDana(TestCase):
    def setUp(self):
        self.product_line_dana = ProductLineFactory(
            product_line_code=700, product_line_type='DANA'
        )
        self.account = AccountFactory()
        self.customer = CustomerFactory()
        self.partner = PartnerFactory()
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier="Dana_customer303", account=self.account,
            customer=self.customer, partner=self.partner
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            email="user_087781540796+dana@julopartner.com",
            fullname=self.dana_customer_data.full_name,
            partner=self.dana_customer_data.partner,
            mobile_phone_1=self.dana_customer_data.mobile_number,
            product_line=self.product_line_dana,
            payday=1
        )

        DanaApplicationReferenceFactory(application_id=self.application.id)
        self.dana_customer_data.application = self.application
        self.dana_customer_data.save()

    def test_get_phone_number_for_product_line_code_dana(self):
        phone_number = get_application_phone_number(self.application)
        self.assertEqual('+62811111111', phone_number)

    def test_invalid_phone_number_for_product_line_code_dana(self):
        self.dana_customer_data.mobile_number = '0235727112998040'
        self.dana_customer_data.save()
        with self.assertRaises(InvalidPhoneNumberError):
            get_application_phone_number(self.application)

class TestUpdateHistoryTransactionSepulsa(TestCase):
    def setUp(self):
        self.sepulsa_transaction = SepulsaTransactionFactory()

    def test_update_sepulsa_transaction_history_with_no_response_code(self):
        sepulsa_service = SepulsaService()
        transaction_type = 'create_transaction'

        sepulsa_transaction = sepulsa_service.\
            update_sepulsa_transaction_with_history_accordingly(
                self.sepulsa_transaction, transaction_type, {})

        self.assertEqual(sepulsa_transaction.transaction_status, 'failed')
        histories = sepulsa_transaction.sepulsatransactionhistory_set
        self.assertIsNotNone(histories.exists())
        self.assertIsNotNone(histories.first().request_payload)

    def test_update_sepulsa_transaction_history_with_response_code_success(self):
        sepulsa_service = SepulsaService()
        transaction_type = 'create_transaction'
        payload = {
            'response_code': '00'
        }

        sepulsa_transaction = sepulsa_service.\
            update_sepulsa_transaction_with_history_accordingly(
                self.sepulsa_transaction, transaction_type, payload)

        self.assertEqual(sepulsa_transaction.transaction_status, 'success')
        histories = sepulsa_transaction.sepulsatransactionhistory_set
        self.assertIsNotNone(histories.exists())
        self.assertIsNotNone(histories.first().request_payload)

    def test_update_sepulsa_transaction_history_with_response_code_pending(self):
        sepulsa_service = SepulsaService()
        transaction_type = 'create_transaction'
        payload = {
            'response_code': '10'
        }

        sepulsa_transaction = sepulsa_service.\
            update_sepulsa_transaction_with_history_accordingly(
                self.sepulsa_transaction, transaction_type, payload)

        self.assertEqual(sepulsa_transaction.transaction_status, 'pending')
        histories = sepulsa_transaction.sepulsatransactionhistory_set
        self.assertIsNotNone(histories.exists())
        self.assertIsNotNone(histories.first().request_payload)


class TestRetryTransactionSepulsa(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.loan = LoanFactory(account=self.account)
        self.sepulsa_transaction = SepulsaTransactionFactory(
            transaction_status='failed',
            transaction_code=None,
            loan=self.loan,
            customer=self.customer
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DISBURSEMENT_AUTO_RETRY,
            category="disbursement",
            is_active=True
        )
        LenderTransactionMapping.objects.create(
            sepulsa_transaction=self.sepulsa_transaction,
            lender_transaction_id=None
        )

    @patch(
        'juloserver.loan.services.lender_related.prevent_double_calculate_account_payment_for_loan')
    @patch('juloserver.loan.tasks.lender_related.loan_payment_point_disbursement_retry_task')
    @patch('juloserver.loan.services.lender_related.get_julo_sepulsa_loan_client')
    @patch('juloserver.loan.services.lender_related.update_loan_status_and_loan_history')
    @patch('juloserver.loan.services.lender_related.SepulsaLoanService')
    def test_payment_point_disbursement_process_with_failed_transaction(
        self,
        mock_sepulsa_service,
        mock_update_loan_status_and_loan_history,
        mock_get_julo_sepulsa_loan_client,
        mock_loan_payment_point_disbursement_retry_task,
        mock_prevent_double_calculate_account_payment_for_loan):
        response = {
            "content": "450 Product Closed Temporarily",
            "serial_number": "",
            "token": "",
            "status": "",
            "transaction_id": "",
            "response_code": ""
        }
        mock_sepulsa_service.return_value.is_balance_enough_for_transaction.return_value = True
        mock_get_julo_sepulsa_loan_client.return_value.create_transaction.return_value = response

        payment_point_disbursement_process(self.sepulsa_transaction)
        mock_loan_payment_point_disbursement_retry_task.apply_async.assert_called()

    @patch('juloserver.loan.services.lender_related.julo_one_loan_disbursement_success')
    @patch('juloserver.loan.services.lender_related.get_julo_sepulsa_loan_client')
    @patch('juloserver.loan.services.lender_related.update_loan_status_and_loan_history')
    @patch('juloserver.loan.services.lender_related.SepulsaLoanService')
    def test_payment_point_disbursement_process_with_failed_transaction_success(
        self,
        mock_sepulsa_service,
        mock_update_loan_status_and_loan_history,
        mock_get_julo_sepulsa_loan_client,
        mock_julo_one_loan_disbursement_success,
        ):
        response = {
            "response_code": "00",
            "transaction_id": "624587",
            "status": "success"
        }
        mock_sepulsa_service.return_value.is_balance_enough_for_transaction.return_value = True
        mock_get_julo_sepulsa_loan_client.return_value.create_transaction.return_value = response

        payment_point_disbursement_process(self.sepulsa_transaction)
        mock_julo_one_loan_disbursement_success.assert_called()

    @patch('juloserver.loan.services.lender_related.process_sepulsa_transaction_failed')
    @patch('juloserver.loan.services.lender_related.julo_one_loan_disbursement_success')
    @patch('juloserver.loan.services.lender_related.get_julo_sepulsa_loan_client')
    @patch('juloserver.loan.services.lender_related.update_loan_status_and_loan_history')
    @patch('juloserver.loan.services.lender_related.SepulsaLoanService')
    def test_payment_point_disbursement_process_with_failed_transaction_pending(
        self,
        mock_sepulsa_service,
        mock_update_loan_status_and_loan_history,
        mock_get_julo_sepulsa_loan_client,
        mock_julo_one_loan_disbursement_success,
        mock_process_sepulsa_transaction_failed,
        ):
        response= {
            "response_code": "10",
            "transaction_id": "624587",
            "status": "pending"
        }
        mock_sepulsa_service.return_value.is_balance_enough_for_transaction.return_value = True
        mock_get_julo_sepulsa_loan_client.return_value.create_transaction.return_value = response

        payment_point_disbursement_process(self.sepulsa_transaction)
        mock_process_sepulsa_transaction_failed.assert_not_called()

    @patch('juloserver.julo.clients.sepulsa.JuloSepulsaClient.create_mobile_transaction')
    def test_response_failed_when_creating_sepulsa_transaction(
        self, mock_create_mobile_transaction):
        product = self.sepulsa_transaction.product
        product.type = 'mobile'
        product.category = 'paket_data'
        product.save()

        mock_response = MagicMock(status_code=450)
        mock_response.content.return_value = '450 Product Closed Temporarily'

        mock_create_mobile_transaction.return_value = mock_response
        sepulsa_client = get_julo_sepulsa_loan_client()
        response = sepulsa_client.create_transaction(self.sepulsa_transaction)

        self.assertEqual(response['content'], mock_response.content.decode())


class TestCalculateDueDateExperiment(TestCase):
    def setUp(self):
        self.customer_id = 1000310954
        self.customer = CustomerFactory()
        self.cycle_day = 2
        self.account = AccountFactory(
            customer=self.customer,
            is_ldde=True,
            cycle_day=self.cycle_day,
            is_payday_changed=False
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            payday=24,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.application.change_status(ApplicationStatusCodes.LOC_APPROVED)
        self.application.save()
        self.application.refresh_from_db()

        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.LDDE_V2_SETTING,
            category="disbursement",
            is_active=False,
            parameters={
                'ldde_version': {
                    'v1_last_digit_of_application_id': [1,2,3,4,5],
                    'v2_last_digit_of_application_id': [6,7,8,9,0],
                },
                'update_ldde_v2_after_months': 6
            }
        )
        self.auto_adjust_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.AUTO_ADJUST_DUE_DATE,
            category="loan",
            is_active=False,
            parameters={
                "auto_adjust_due_date_mapping": {
                    '26': 1,
                    '27': 1,
                    '28': 1,
                    '29': 2,
                    '30': 2,
                    '31': 3
                },
                "whitelist": {
                    "is_active": False,
                    "last_customer_digit": {'from': '00', 'to': '00'},
                    "customer_ids": []
                }
            }
        )

    def test_filter_due_dates_by_experiment(self):
        # 1. 2022-9-25 => 2022-10-31 with payday = 30
        payday = 30
        offerday = datetime(2022, 9, 25)
        due_date_expectation = datetime(2022, 10, 31)

        due_date_1 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_1, [due_date_expectation])

        # 2. 2022-9-24 => 2022-9-30 with payday = 30
        payday = 30
        offerday = datetime(2022, 9, 24)
        due_date_expectation = datetime(2022, 9, 30)

        due_date_2 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_2, [due_date_expectation])

        # 3. 2022-1-30 => 2022-2-28 with payday = 30
        payday = 30
        offerday = datetime(2022, 1, 30)
        due_date_expectation = datetime(2022, 2, 28)

        due_date_3 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_3, [due_date_expectation])

        # 4. 2022-2-22 => 2022-2-28 with payday = 30
        payday = 30
        offerday = datetime(2022, 2, 22)
        due_date_expectation = datetime(2022, 2, 28)

        due_date_4 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_4, [due_date_expectation])

        # 5. 2022-2-23 => 2022-3-31 with payday = 30
        payday = 30
        offerday = datetime(2022, 2, 23)
        due_date_expectation = datetime(2022, 3, 31)

        due_date_5 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_5, [due_date_expectation])

        # 6. 2024-2-23 => 2024-2-29 with payday = 30
        payday = 30
        offerday = datetime(2024, 2, 23)
        due_date_expectation = datetime(2024, 2, 29)

        due_date_6 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_6, [due_date_expectation])

        # 7. 2024-2-24 => 2024-3-31 with payday = 30
        payday = 30
        offerday = datetime(2024, 2, 24)
        due_date_expectation = datetime(2024, 3, 31)

        due_date_7 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_7, [due_date_expectation])

        # 8. 2024-1-22 => 2024-2-26 with payday = 25
        payday = 25
        offerday = datetime(2024, 1, 22)
        due_date_expectation = datetime(2024, 2, 26)

        due_date_8 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_8, [due_date_expectation])

        # 9. 2024-1-18 => 2024-1-26 with payday = 25
        payday = 25
        offerday = datetime(2024, 1, 18)
        due_date_expectation = datetime(2024, 1, 26)

        due_date_9 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_9, [due_date_expectation])

    @patch('juloserver.loan.services.loan_related.determine_first_due_dates_by_payday')
    def test_get_first_payment_date_by_application(self, mock_first_due_date):
        #payday = 24
        due_date = datetime(2022, 2, 25)
        mock_first_due_date.return_value = due_date

        get_first_payment_date_by_application(self.application)
        self.assertEqual(self.application.account.cycle_day, due_date.day)

        #payday = 30
        self.application.payday = 30
        self.application.save()
        due_date = datetime(2022, 2, 25)
        mock_first_due_date.return_value = due_date

        get_first_payment_date_by_application(self.application)
        self.assertEqual(self.application.account.cycle_day, 31)

        #payday = 29
        self.application.payday = 29
        self.application.save()
        due_date = datetime(2022, 2, 28)
        mock_first_due_date.return_value = due_date

        get_first_payment_date_by_application(self.application)
        self.assertEqual(self.application.account.cycle_day, 30)

        #payday = 28
        self.application.payday = 28
        self.application.save()
        due_date = datetime(2022, 2, 28)
        mock_first_due_date.return_value = due_date

        get_first_payment_date_by_application(self.application)
        self.assertEqual(self.application.account.cycle_day, 29)

    @patch('juloserver.loan.services.loan_related.determine_first_due_dates_by_payday')
    def test_get_first_payment_date_by_application_with_auto_adjust(
        self, mock_first_due_date
    ):
        self.auto_adjust_fs.update_safely(is_active=True)
        # Payday = 24
        due_date = datetime(2022, 2, 25)
        mock_first_due_date.return_value = due_date

        get_first_payment_date_by_application(self.application)
        self.assertEqual(self.application.account.cycle_day, due_date.day)

        # Payday = 30 -> 31, Auto adjust = 31 -> 3
        self.application.payday = 30
        self.application.save()
        due_date = datetime(2022, 2, 25)
        mock_first_due_date.return_value = due_date

        get_first_payment_date_by_application(self.application)
        self.assertEqual(self.application.account.cycle_day, 3)

        # Payday = 29 -> 30, Auto adjust = 30 -> 2
        self.application.payday = 29
        self.application.save()
        due_date = datetime(2022, 2, 28)
        mock_first_due_date.return_value = due_date

        get_first_payment_date_by_application(self.application)
        self.assertEqual(self.application.account.cycle_day, 2)

        # Payday = 26 -> 27, Auto adjust = 27 -> 1
        self.application.payday = 26
        self.application.save()
        due_date = datetime(2022, 2, 26)
        mock_first_due_date.return_value = due_date

        get_first_payment_date_by_application(self.application)
        self.assertEqual(self.application.account.cycle_day, 1)

    @patch('juloserver.loan.services.loan_related.determine_first_due_dates_by_payday')
    def test_get_first_payment_date_update_cycle_day_with_LDDE1(
        self, mock_first_due_date):
        # the account cycle day not exist
        payday = 25
        data = {}
        data_2 = data.copy()
        old_cycle_day = 16
        due_date = datetime(2022, 2, payday)
        mock_first_due_date.return_value = due_date
        self.account.cycle_day = old_cycle_day
        self.account.save()

        get_first_payment_date_by_application(self.application)
        self.account.refresh_from_db()
        account_cycle_day = AccountCycleDayHistory.objects.filter(account_id=self.account.pk).last()
        assert account_cycle_day.application_id == self.application.pk
        assert account_cycle_day.reason == LDDEReasonConst.LDDE_V1
        assert account_cycle_day.old_cycle_day == old_cycle_day
        assert account_cycle_day.new_cycle_day == self.account.cycle_day
        assert account_cycle_day.latest_flag == True
        assert json.loads(account_cycle_day.parameters) == data_2

        # the account cycle day history exists
        old_cycle_day = 12
        self.account.cycle_day = old_cycle_day
        self.account.save()
        self.application.save()
        get_first_payment_date_by_application(self.application)
        self.account.refresh_from_db()

        account_cycle_day = AccountCycleDayHistory.objects.filter(account_id=self.account.pk).last()
        account_cycle_1 = AccountCycleDayHistory.objects.filter(account_id=self.account.pk).first()
        total_histories = AccountCycleDayHistory.objects.filter(account_id=self.account.pk).count()
        latest_flag_count = AccountCycleDayHistory.objects.filter(
            account_id=self.account.pk, latest_flag=True).count()

        assert latest_flag_count == 1
        assert total_histories == 2
        assert account_cycle_day.reason == LDDEReasonConst.LDDE_V1
        assert account_cycle_day.old_cycle_day == old_cycle_day
        assert account_cycle_day.new_cycle_day == self.account.cycle_day
        assert account_cycle_day.latest_flag == True
        assert json.loads(account_cycle_day.parameters) == data_2
        assert account_cycle_day.end_date == None
        assert account_cycle_1.end_date != None

    @patch('juloserver.loan.services.loan_related.determine_first_due_dates_by_payday')
    def test_get_first_payment_date_update_cycle_day_with_LDDE1_with_auto_adjust(
        self, mock_first_due_date
    ):
        self.auto_adjust_fs.update_safely(is_active=True)
        self.application.payday = 27
        self.application.save()

        # The account cycle day not exist
        payday = 28
        old_cycle_day = 16
        due_date = datetime(2022, 2, payday)
        mock_first_due_date.return_value = due_date
        self.account.cycle_day = old_cycle_day
        self.account.save()

        get_first_payment_date_by_application(self.application)
        self.account.refresh_from_db()
        account_cycle_day = AccountCycleDayHistory.objects.filter(account_id=self.account.pk).last()
        self.assertEqual(account_cycle_day.application_id, self.application.pk)
        self.assertEqual(account_cycle_day.reason, LDDEReasonConst.LDDE_V1)
        self.assertEqual(account_cycle_day.old_cycle_day, old_cycle_day)
        self.assertEqual(account_cycle_day.new_cycle_day, self.account.cycle_day)
        self.assertEqual(account_cycle_day.latest_flag, True)
        self.assertEqual(json.loads(account_cycle_day.parameters), {})
        self.assertEqual(json.loads(account_cycle_day.auto_adjust_changes), {
            "ldde": {"old_cycle_day": 16, "new_cycle_day": 28},
            "auto_adjust": {"old_cycle_day": 28, "new_cycle_day": 1}
        })

        # The account cycle day history exists
        old_cycle_day = 12
        self.account.cycle_day = old_cycle_day
        self.account.save()
        self.application.save()
        get_first_payment_date_by_application(self.application)
        self.account.refresh_from_db()

        account_cycle_day = AccountCycleDayHistory.objects.filter(account_id=self.account.pk).last()
        account_cycle_1 = AccountCycleDayHistory.objects.filter(account_id=self.account.pk).first()
        total_histories = AccountCycleDayHistory.objects.filter(account_id=self.account.pk).count()
        latest_flag_count = AccountCycleDayHistory.objects.filter(
            account_id=self.account.pk, latest_flag=True).count()

        self.assertEqual(latest_flag_count, 1)
        self.assertEqual(total_histories, 2)
        self.assertEqual(account_cycle_day.reason, LDDEReasonConst.LDDE_V1)
        self.assertEqual(account_cycle_day.old_cycle_day, old_cycle_day)
        self.assertEqual(account_cycle_day.new_cycle_day, self.account.cycle_day)
        self.assertEqual(account_cycle_day.latest_flag, True)
        self.assertEqual(json.loads(account_cycle_day.parameters), {})
        self.assertEqual(json.loads(account_cycle_day.auto_adjust_changes), {
            "ldde": {"old_cycle_day": 12, "new_cycle_day": 28},
            "auto_adjust": {"old_cycle_day": 28, "new_cycle_day": 1}
        })
        self.assertIsNone(account_cycle_day.end_date)
        self.assertIsNotNone(account_cycle_1.end_date)

    def test_ldde_v2_feature_setting(self):
        application = ApplicationFactory(
            id=9998,
            customer=self.customer,
            account=self.account,
            payday=24,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application2 = ApplicationFactory(
            id=9991,
            customer=self.customer,
            account=self.account,
            payday=24,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
        )
        self.feature_setting.is_active = True
        self.feature_setting.save()
        is_ldde_v2 = get_ldde_v2_status(application.id)
        self.assertTrue(is_ldde_v2)
        is_not_ldde_v2 = get_ldde_v2_status(application2.id)
        self.assertFalse(is_not_ldde_v2)

        self.feature_setting.is_active = False
        self.feature_setting.save()
        # disabling the feature setting
        is_ldde_v2 = get_ldde_v2_status(application.id)
        self.assertFalse(is_ldde_v2)

    @patch('juloserver.loan.services.loan_related.get_data_from_ana_calculate_cycle_day')
    @patch('juloserver.loan.services.loan_related.determine_first_due_dates_by_payday')
    def test_get_first_payment_date_update_cycle_day_with_LDDE2(
        self, mock_first_due_date, mock_ana_cycle_day):
        # the account cycle day not exist
        payday = 25
        cycle_day_selection = 22
        data = {'payday': payday, 'cycle_day_selection': cycle_day_selection}
        data_2 = data.copy()
        mock_ana_cycle_day.return_value = data
        old_cycle_day = 16
        due_date = datetime(2022, 2, payday)
        mock_first_due_date.return_value = due_date
        self.account.cycle_day = old_cycle_day
        self.account.save()
        self.feature_setting.parameters = {
            'ldde_version': {
                'v1_last_digit_of_application_id': [],
                'v2_last_digit_of_application_id': [1,2,3,4,5,6,7,8,9,0],
            }
        }
        self.feature_setting.is_active = True
        self.feature_setting.save()

        get_first_payment_date_by_application(self.application)
        self.account.refresh_from_db()
        account_cycle_day = AccountCycleDayHistory.objects.filter(account_id=self.account.pk).last()
        assert account_cycle_day.application_id == self.application.pk
        assert account_cycle_day.reason == LDDEReasonConst.LDDE_V2
        assert account_cycle_day.old_cycle_day == old_cycle_day
        assert account_cycle_day.new_cycle_day == self.account.cycle_day
        assert account_cycle_day.latest_flag == True

        assert self.account.cycle_day == cycle_day_selection

    @patch('juloserver.loan.services.loan_related.get_data_from_ana_calculate_cycle_day')
    @patch('juloserver.loan.services.loan_related.determine_first_due_dates_by_payday')
    def test_get_first_payment_date_update_cycle_day_with_LDDE2_auto_adjust(
        self, mock_first_due_date, mock_ana_cycle_day
    ):
        # The account cycle day not exist
        payday = 25
        data = {'payday': payday, 'cycle_day_selection': 29}
        auto_adjust_changes = {
            "ldde": {"old_cycle_day": 16, "new_cycle_day": 29},
            "auto_adjust": {"old_cycle_day": 29, "new_cycle_day": 2}
        }
        mock_ana_cycle_day.return_value = data
        old_cycle_day = 16
        due_date = datetime(2022, 2, payday)
        mock_first_due_date.return_value = due_date
        self.account.cycle_day = old_cycle_day
        self.account.save()
        self.feature_setting.parameters = {
            'ldde_version': {
                'v1_last_digit_of_application_id': [],
                'v2_last_digit_of_application_id': [1,2,3,4,5,6,7,8,9,0],
            }
        }
        self.feature_setting.is_active = True
        self.feature_setting.save()
        self.auto_adjust_fs.update_safely(is_active=True)

        # Cycle day = 16 -> Ana cycle day selection = 29 -> Auto adjust = 2
        get_first_payment_date_by_application(self.application)
        self.account.refresh_from_db()
        account_cycle_day = AccountCycleDayHistory.objects.filter(account_id=self.account.pk).last()
        self.assertEqual(account_cycle_day.application_id, self.application.pk)
        self.assertEqual(account_cycle_day.reason, LDDEReasonConst.LDDE_V2)
        self.assertEqual(account_cycle_day.old_cycle_day, old_cycle_day)
        self.assertEqual(account_cycle_day.new_cycle_day, self.account.cycle_day)
        self.assertEqual(account_cycle_day.latest_flag, True)
        self.assertEqual(json.loads(account_cycle_day.parameters), data)
        self.assertEqual(json.loads(account_cycle_day.auto_adjust_changes), auto_adjust_changes)
        self.assertEqual(self.account.cycle_day, 2)

    @patch('juloserver.loan.services.loan_related.get_data_from_ana_calculate_cycle_day')
    @patch('juloserver.loan.services.loan_related.determine_first_due_dates_by_payday')
    def test_get_first_payment_date_update_cycle_day_with_LDDE2_with_pending_loan(
        self, mock_first_due_date, mock_ana_cycle_day):
        # the account cycle day not exist
        payday = 25
        data = {'payday': 20, 'cycle_day_selection': 20}
        data_2 = data.copy()
        mock_ana_cycle_day.return_value = data
        old_cycle_day = 16
        due_date = datetime(2022, 2, payday)
        mock_first_due_date.return_value = due_date
        self.account.cycle_day = old_cycle_day
        self.account.save()
        self.feature_setting.parameters = {
            'ldde_version': {
                'v1_last_digit_of_application_id': [],
                'v2_last_digit_of_application_id': [1,2,3,4,5,6,7,8,9,0],
            }
        }
        self.feature_setting.is_active = True
        self.feature_setting.save()
        # there was still pending loan, so it will go to v1 instead v2
        LoanFactory(account=self.account)

        get_first_payment_date_by_application(self.application)
        self.account.refresh_from_db()
        account_cycle_day = AccountCycleDayHistory.objects.filter(account_id=self.account.pk).last()
        assert account_cycle_day.application_id == self.application.pk
        assert account_cycle_day.reason == LDDEReasonConst.LDDE_V1
        assert account_cycle_day.old_cycle_day == old_cycle_day
        assert account_cycle_day.new_cycle_day == self.account.cycle_day
        assert account_cycle_day.latest_flag == True

    @patch('juloserver.loan.services.loan_related.get_data_from_ana_calculate_cycle_day')
    @patch('juloserver.loan.services.loan_related.determine_first_due_dates_by_payday')
    def test_get_first_payment_date_update_cycle_day_with_LDDE2_with_pending_loan_auto_adjust(
        self, mock_first_due_date, mock_ana_cycle_day
    ):
        # The account cycle day not exist
        self.application.payday = 27
        self.application.save()
        payday = 28

        data = {'payday': 20, 'cycle_day_selection': 22}
        auto_adjust_changes = {
            "ldde": {"old_cycle_day": 16, "new_cycle_day": 28},
            "auto_adjust": {"old_cycle_day": 28, "new_cycle_day": 1}
        }
        mock_ana_cycle_day.return_value = data
        old_cycle_day = 16
        due_date = datetime(2022, 2, payday)
        mock_first_due_date.return_value = due_date
        self.account.cycle_day = old_cycle_day
        self.account.save()
        self.feature_setting.parameters = {
            'ldde_version': {
                'v1_last_digit_of_application_id': [],
                'v2_last_digit_of_application_id': [1,2,3,4,5,6,7,8,9,0],
            }
        }
        self.feature_setting.is_active = True
        self.feature_setting.save()
        self.auto_adjust_fs.update_safely(is_active=True)

        # There was still pending loan, so it will go to v1 instead v2
        LoanFactory(account=self.account)

        # Payday = 27 -> 28 -> Auto adjust = 1
        get_first_payment_date_by_application(self.application)
        self.account.refresh_from_db()
        account_cycle_day = AccountCycleDayHistory.objects.filter(account_id=self.account.pk).last()
        self.assertEqual(account_cycle_day.application_id, self.application.pk)
        self.assertEqual(account_cycle_day.reason, LDDEReasonConst.LDDE_V1)
        self.assertEqual(account_cycle_day.old_cycle_day, old_cycle_day)
        self.assertEqual(account_cycle_day.new_cycle_day, self.account.cycle_day)
        self.assertEqual(account_cycle_day.latest_flag, True)
        self.assertEqual(json.loads(account_cycle_day.parameters), {})
        self.assertEqual(json.loads(account_cycle_day.auto_adjust_changes), auto_adjust_changes)

        self.assertEqual(self.account.cycle_day, 1)

    @patch('juloserver.loan.services.loan_related.get_data_from_ana_calculate_cycle_day')
    @patch('juloserver.loan.services.loan_related.determine_first_due_dates_by_payday')
    def test_get_first_payment_date_update_cycle_day_with_LDDE2_cycle_date_same(
        self, mock_first_due_date, mock_ana_cycle_day):
        # the account cycle day not exist
        payday = 25
        cycle_day_selection = 22
        data = {'payday': payday, 'cycle_day_selection': cycle_day_selection}
        data_2 = data.copy()
        mock_ana_cycle_day.return_value = data
        old_cycle_day = cycle_day_selection
        due_date = datetime(2022, 2, payday)
        mock_first_due_date.return_value = due_date
        self.account.cycle_day = old_cycle_day
        self.account.save()
        self.feature_setting.parameters = {
            'ldde_version': {
                'v1_last_digit_of_application_id': [],
                'v2_last_digit_of_application_id': [1,2,3,4,5,6,7,8,9,0],
            }
        }
        self.feature_setting.is_active = True
        self.feature_setting.save()

        get_first_payment_date_by_application(self.application)
        self.account.refresh_from_db()
        account_cycle_day = AccountCycleDayHistory.objects.filter(account_id=self.account.pk).last()
        assert account_cycle_day.application_id == self.application.pk
        assert account_cycle_day.reason == LDDEReasonConst.LDDE_V2
        assert account_cycle_day.old_cycle_day == old_cycle_day
        assert account_cycle_day.new_cycle_day == self.account.cycle_day
        assert account_cycle_day.latest_flag == True

        assert self.account.cycle_day == cycle_day_selection

    @patch('juloserver.loan.services.loan_related.get_data_from_ana_calculate_cycle_day')
    @patch('juloserver.loan.services.loan_related.determine_first_due_dates_by_payday')
    def test_get_first_payment_date_update_cycle_day_with_LDDE2_cycle_date_same_auto_adjust(
        self, mock_first_due_date, mock_ana_cycle_day
    ):
        # The account cycle day not exist
        payday = 25
        cycle_day_selection = 28
        data = {'payday': payday, 'cycle_day_selection': cycle_day_selection}
        auto_adjust_changes = {
            "ldde": {"old_cycle_day": 28, "new_cycle_day": 28},
            "auto_adjust": {"old_cycle_day": 28, "new_cycle_day": 1}
        }
        mock_ana_cycle_day.return_value = data
        old_cycle_day = cycle_day_selection
        due_date = datetime(2022, 2, payday)
        mock_first_due_date.return_value = due_date
        self.account.cycle_day = old_cycle_day
        self.account.save()
        self.feature_setting.parameters = {
            'ldde_version': {
                'v1_last_digit_of_application_id': [],
                'v2_last_digit_of_application_id': [1,2,3,4,5,6,7,8,9,0],
            }
        }
        self.feature_setting.is_active = True
        self.feature_setting.save()
        self.auto_adjust_fs.update_safely(is_active=True)

        # Cycle day = Ana cycle day selection = 28 -> Auto adjust = 1
        get_first_payment_date_by_application(self.application)
        self.account.refresh_from_db()
        account_cycle_day = AccountCycleDayHistory.objects.filter(account_id=self.account.pk).last()
        self.assertEqual(account_cycle_day.application_id, self.application.pk)
        self.assertEqual(account_cycle_day.reason, LDDEReasonConst.LDDE_V2)
        self.assertEqual(account_cycle_day.old_cycle_day, old_cycle_day)
        self.assertEqual(account_cycle_day.new_cycle_day, self.account.cycle_day)
        self.assertEqual(account_cycle_day.latest_flag, True)
        self.assertEqual(json.loads(account_cycle_day.parameters), data)
        self.assertEqual(json.loads(account_cycle_day.auto_adjust_changes), auto_adjust_changes)

        self.assertEqual(self.account.cycle_day, 1)

    @patch('juloserver.loan.services.loan_related.get_data_from_ana_calculate_cycle_day')
    @patch('juloserver.loan.services.loan_related.determine_first_due_dates_by_payday')
    def test_get_first_payment_date_update_cycle_day_with_LDDE2_without_payday(
        self, mock_first_due_date, mock_ana_cycle_day):
        # the account cycle day not exist
        payday = 1
        cycle_day_selection = 30
        data = {'payday': payday, 'cycle_day_selection': cycle_day_selection}
        data_2 = data.copy()
        mock_ana_cycle_day.return_value = data
        old_cycle_day = cycle_day_selection
        due_date = datetime(2022, 2, payday)
        mock_first_due_date.return_value = due_date
        self.account.cycle_day = old_cycle_day
        self.account.save()
        self.feature_setting.parameters = {
            'ldde_version': {
                'v1_last_digit_of_application_id': [],
                'v2_last_digit_of_application_id': [1,2,3,4,5,6,7,8,9,0],
            }
        }
        self.feature_setting.is_active = True
        self.feature_setting.save()

        get_first_payment_date_by_application(self.application)
        self.account.refresh_from_db()
        account_cycle_day = AccountCycleDayHistory.objects.filter(account_id=self.account.pk).last()
        assert account_cycle_day.application_id == self.application.pk
        assert account_cycle_day.reason == LDDEReasonConst.LDDE_V2
        assert account_cycle_day.old_cycle_day == old_cycle_day
        assert account_cycle_day.new_cycle_day == self.account.cycle_day
        assert account_cycle_day.latest_flag == True

        assert self.account.cycle_day == cycle_day_selection

    def test_check_ldde_v2(self):
        self.feature_setting.is_active = True
        self.feature_setting.save()

        application = ApplicationFactory(
            id=9998,
            customer=self.customer,
            account=self.account,
            payday=24,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        result = check_ldde_v2(application, self.account)

        # No history and no pending loan
        self.assertTrue(result)
        # this process insert history
        get_first_payment_date_by_application(self.application)

        history = AccountCycleDayHistory.objects.filter(account_id=self.account.pk).last()
        history.reason = LDDEReasonConst.LDDE_V2
        history.save()
        # fs will go to v1
        self.feature_setting.parameters = {
            'ldde_version': {
                'v1_last_digit_of_application_id': [1,2,3,4,5,6,7,8,9,0],
                'v2_last_digit_of_application_id': [],
            }
        }
        self.feature_setting.save()
        is_ldde_v2 = get_ldde_v2_status(application.id)
        self.assertFalse(is_ldde_v2)
        assert is_ldde_v2 == False

        result = check_ldde_v2(application, self.account)
        # v2 history and fs in v1
        self.assertTrue(result)

    def test_check_ldde_v2_no_update_when_be_in_range_time(self):
        # LDDE v2 don't update when cdate of history still be < months config
        self.feature_setting.is_active = True
        self.feature_setting.save()

        application = ApplicationFactory(
            id=9998,
            customer=self.customer,
            account=self.account,
            payday=24,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        AccountCycleDayHistory.objects.create(
            account_id=self.account.pk,
            reason = LDDEReasonConst.LDDE_V2,
            old_cycle_day=30,
            new_cycle_day=self.account.cycle_day,
            application=application
        )
        result = check_ldde_v2(application, self.account)

        # No history and no pending loan
        self.assertTrue(result)
        # this process insert history
        get_first_payment_date_by_application(self.application)

        assert 1 == AccountCycleDayHistory.objects.filter(account_id=self.account.pk).count()

    @patch('juloserver.loan.services.loan_related.get_data_from_ana_calculate_cycle_day')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    def test_check_ldde_v2_update_after_months(self, mock_time_zone, mock_ana_cycle_day):
        self.feature_setting.is_active = True
        self.feature_setting.save()

        mock_time_zone.return_value = datetime(2024, 7, 2)
        application = ApplicationFactory(
            id=9998,
            customer=self.customer,
            account=self.account,
            payday=24,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        account_history = AccountCycleDayHistory.objects.create(
            account_id=self.account.pk,
            reason = LDDEReasonConst.LDDE_V2,
            old_cycle_day=30,
            new_cycle_day=self.account.cycle_day,
            application=application
        )
        mock_ana_cycle_day.return_value = {'payday': 30, 'cycle_day_selection': self.cycle_day + 1}
        account_history.cdate = datetime(2024, 1, 1)
        account_history.save()
        result = check_ldde_v2(application, self.account)

        # No history and no pending loan
        self.assertTrue(result)
        # this process insert history
        get_first_payment_date_by_application(self.application)

        self.account.refresh_from_db()
        assert 2 == AccountCycleDayHistory.objects.filter(account_id=self.account.pk).count()
        assert self.account.cycle_day == self.cycle_day + 1

        status_220 = StatusLookup.objects.get(status_code=220)
        LoanFactory(
            customer=self.customer, application=self.application, loan_status=status_220
        )

        old_cycle_day = self.account.cycle_day
        mock_ana_cycle_day.return_value = {'payday': 30, 'cycle_day_selection': self.cycle_day + 2}
        get_first_payment_date_by_application(self.application)
        assert 2 == AccountCycleDayHistory.objects.filter(account_id=self.account.pk).count()
        assert self.account.cycle_day == old_cycle_day

    def test_get_data_from_ana_calculate_cycle_day(self):
        assert get_data_from_ana_calculate_cycle_day(self.application.pk) == {}
        assert calculate_cycle_day_from_ana({}) == {}
        fdc_data = {
            "application_id": self.application.pk,
            "dpd_max": 20,
            "tgl_jatuh_tempo_pinjaman": "2024-02-2",
            "tgl_penyaluran_dana": "2024-02-2"
        }
        assert calculate_cycle_day_from_ana(fdc_data) == {}

    @patch('juloserver.loan.services.loan_related.get_data_from_ana_calculate_cycle_day')
    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    def test_check_ldde_v2_on_progess_status(self, mock_time_zone, mock_ana_cycle_day):
        self.feature_setting.is_active = True
        self.feature_setting.save()

        mock_time_zone.return_value = datetime(2024, 7, 2)
        application = ApplicationFactory(
            id=9998,
            customer=self.customer,
            account=self.account,
            payday=24,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        account_history = AccountCycleDayHistory.objects.create(
            account_id=self.account.pk,
            reason=LDDEReasonConst.LDDE_V1,
            old_cycle_day=30,
            new_cycle_day=self.account.cycle_day,
            application=application,
        )
        mock_ana_cycle_day.return_value = {'payday': 30, 'cycle_day_selection': self.cycle_day + 1}
        account_history.cdate = datetime(2024, 1, 1)
        account_history.save()
        result = check_ldde_v2(application, self.account)

        # No history and no pending loan
        self.assertTrue(result)
        # this process insert history
        get_first_payment_date_by_application(self.application)

        self.account.refresh_from_db()

        loan = LoanFactory(
            customer=self.customer, application=self.application, account=self.account
        )
        loan.status_code = StatusLookupFactory(status_code=250)
        loan.save()
        for status in LoanStatusCodes.in_progress_status():
            loan.loan_status = StatusLookupFactory(status_code=status)
            loan.save()
            old_cycle_day = self.account.cycle_day
            mock_ana_cycle_day.return_value = {
                'payday': 30,
                'cycle_day_selection': self.cycle_day + 2,
            }
            get_first_payment_date_by_application(self.application)
            self.account.refresh_from_db()
            assert self.account.cycle_day == old_cycle_day


class TestCalculateDueDateExperimentJuloTurbo(TestCase):
    def setUp(self):
        self.customer_id = 1000310954
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            is_ldde=True,
            cycle_day=2,
            is_payday_changed=False
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            payday=24,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_STARTER),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.TURBO),
        )
        self.application.change_status(ApplicationStatusCodes.LOC_APPROVED)
        self.application.save()
        self.application.refresh_from_db()

    def test_filter_due_dates_by_experiment(self):
        # 1. 2022-9-25 => 2022-10-31 with payday = 30
        payday = 30
        offerday = datetime(2022, 9, 25)
        due_date_expectation = datetime(2022, 10, 31)

        due_date_1 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_1, [due_date_expectation])

        # 2. 2022-9-24 => 2022-9-30 with payday = 30
        payday = 30
        offerday = datetime(2022, 9, 24)
        due_date_expectation = datetime(2022, 9, 30)

        due_date_2 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_2, [due_date_expectation])

        # 3. 2022-1-30 => 2022-2-28 with payday = 30
        payday = 30
        offerday = datetime(2022, 1, 30)
        due_date_expectation = datetime(2022, 2, 28)

        due_date_3 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_3, [due_date_expectation])

        # 4. 2022-2-22 => 2022-2-28 with payday = 30
        payday = 30
        offerday = datetime(2022, 2, 22)
        due_date_expectation = datetime(2022, 2, 28)

        due_date_4 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_4, [due_date_expectation])

        # 5. 2022-2-23 => 2022-3-31 with payday = 30
        payday = 30
        offerday = datetime(2022, 2, 23)
        due_date_expectation = datetime(2022, 3, 31)

        due_date_5 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_5, [due_date_expectation])

        # 6. 2024-2-23 => 2024-2-29 with payday = 30
        payday = 30
        offerday = datetime(2024, 2, 23)
        due_date_expectation = datetime(2024, 2, 29)

        due_date_6 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_6, [due_date_expectation])

        # 7. 2024-2-24 => 2024-3-31 with payday = 30
        payday = 30
        offerday = datetime(2024, 2, 24)
        due_date_expectation = datetime(2024, 3, 31)

        due_date_7 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_7, [due_date_expectation])

        # 8. 2024-1-22 => 2024-2-26 with payday = 25
        payday = 25
        offerday = datetime(2024, 1, 22)
        due_date_expectation = datetime(2024, 2, 26)

        due_date_8 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_8, [due_date_expectation])

        # 9. 2024-1-18 => 2024-1-26 with payday = 25
        payday = 25
        offerday = datetime(2024, 1, 18)
        due_date_expectation = datetime(2024, 1, 26)

        due_date_9 = filter_due_dates_by_experiment(
            payday, offerday, self.customer_id)
        self.assertEquals(due_date_9, [due_date_expectation])

    @patch('juloserver.loan.services.loan_related.determine_first_due_dates_by_payday')
    def test_get_first_payment_date_by_application(self, mock_first_due_date):
        #payday = 24
        due_date = datetime(2022, 2, 25)
        mock_first_due_date.return_value = due_date

        get_first_payment_date_by_application(self.application)
        self.assertEqual(self.application.account.cycle_day, due_date.day)

        #payday = 30
        self.application.payday = 30
        self.application.save()
        due_date = datetime(2022, 2, 25)
        mock_first_due_date.return_value = due_date

        get_first_payment_date_by_application(self.application)
        self.assertEqual(self.application.account.cycle_day, 31)

        #payday = 29
        self.application.payday = 29
        self.application.save()
        due_date = datetime(2022, 2, 28)
        mock_first_due_date.return_value = due_date

        get_first_payment_date_by_application(self.application)
        self.assertEqual(self.application.account.cycle_day, 30)

        #payday = 28
        self.application.payday = 28
        self.application.save()
        due_date = datetime(2022, 2, 28)
        mock_first_due_date.return_value = due_date

        get_first_payment_date_by_application(self.application)
        self.assertEqual(self.application.account.cycle_day, 29)


class TestUpdateApplicationChecklistCollection(TestCase):
    def setUp(self) -> None:
        self.new_data = [
            {
                "field_name": "mobile_phone_1", "group": "-","agent": "", "type":"field",
                "undisclosed_expense": [], "value": "086670877919"
            },
            {
                "field_name": "mobile_phone_2", "group": "-", "agent": "", "type":"field",
                "undisclosed_expense": [], "value": "08667087790"
            }
        ]

    @patch('juloserver.julo.services.send_customer_data_change_by_agent_notification_task.delay')
    def test_sync_with_customer_data(
        self,
        mock_send_customer_data_change_by_agent_notification_task,
    ):
        application = ApplicationJ1Factory()

        update_application_checklist_collection(application, self.new_data)
        application.customer.refresh_from_db()
        self.assertEqual(application.mobile_phone_1, application.customer.phone)

    @patch('juloserver.julo.services.send_customer_data_change_by_agent_notification_task.delay')
    def test_not_sync_data(
        self,
        mock_send_customer_data_change_by_agent_notification_task,
    ):
        # application is not the last application of customer
        application = ApplicationFactory(mobile_phone_1='083923232333')
        application.customer.phone = '083923232444'
        application.customer.save()
        last_application = ApplicationFactory(customer=application.customer)
        update_application_checklist_collection(application, self.new_data)
        application.customer.refresh_from_db()
        self.assertEqual(application.mobile_phone_1, '086670877919')
        self.assertNotEqual(application.mobile_phone_1, application.customer.phone)

        # application workflow is excluded
        dana_workflow = WorkflowFactory(name=WorkflowConst.DANA)
        last_application.workflow = dana_workflow
        last_application.save()
        update_application_checklist_collection(last_application, self.new_data)
        last_application.customer.refresh_from_db()
        self.assertEqual(last_application.mobile_phone_1, '086670877919')
        self.assertNotEqual(last_application.mobile_phone_1, last_application.customer.phone)

        # success
        last_application.workflow = None
        last_application.save()
        update_application_checklist_collection(last_application, self.new_data)
        last_application.customer.refresh_from_db()
        self.assertEqual(last_application.mobile_phone_1, '086670877919')
        self.assertEqual(last_application.mobile_phone_1, last_application.customer.phone)


class TestCalculateDueDateOlfFlow(TestCase):
    def setUp(self):
        self.customer_id = 1000310954
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            is_ldde=False,
            cycle_day=2,
            is_payday_changed=True
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            payday=24,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.application.change_status(ApplicationStatusCodes.LOC_APPROVED)
        self.application.save()
        self.application.refresh_from_db()

    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    def test_get_first_payment_date_by_application_late(self, mock_offer_date):
        # payday = 28, cycle_day = 29, offer_date = 14 July => 29 July
        self.application.payday = 28
        self.account.cycle_day = 29
        mock_offer_date.return_value = datetime(2022, 7, 14)
        expected_date = datetime(2022, 7, 29).date()
        self.application.save()
        self.account.save()

        first_due_date = get_first_payment_date_by_application(self.application)
        self.assertEqual(first_due_date, expected_date)

        # payday = 10, cycle_day = 14, offer_date = 29 June => 14 July
        self.application.payday = 10
        self.account.cycle_day = 14
        mock_offer_date.return_value = datetime(2022, 6, 29)
        expected_date = datetime(2022, 7, 14).date()
        self.application.save()
        self.account.save()

        first_due_date = get_first_payment_date_by_application(self.application)
        self.assertEqual(first_due_date, expected_date)

        # payday = 30, cycle_day = 30, offer_date = 11 July => 30 July
        self.application.payday = 30
        self.account.cycle_day = 30
        mock_offer_date.return_value = datetime(2022, 7, 11)
        expected_date = datetime(2022, 7, 30).date()
        self.application.save()
        self.account.save()

        first_due_date = get_first_payment_date_by_application(self.application)
        self.assertEqual(first_due_date, expected_date)

        # payday = 27, cycle_day = 31, offer_date = 25 Sep => 31 Oct
        self.application.payday = 27
        self.account.cycle_day = 31
        mock_offer_date.return_value = datetime(2022, 9, 25)
        expected_date = datetime(2022, 10, 31).date()
        self.application.save()
        self.account.save()

        first_due_date = get_first_payment_date_by_application(self.application)
        self.assertEqual(first_due_date, expected_date)

        # payday = 28, cycle_day = 31, offer_date = 16 Sep => 31 Oct
        self.application.payday = 28
        self.account.cycle_day = 31
        mock_offer_date.return_value = datetime(2022, 9, 16)
        expected_date = datetime(2022, 10, 31).date()
        self.application.save()
        self.account.save()

        first_due_date = get_first_payment_date_by_application(self.application)
        self.assertEqual(first_due_date, expected_date)

        # payday = 30, cycle_day = 31, offer_date = 20 Oct => 30 Nov
        self.application.payday = 30
        self.account.cycle_day = 30
        mock_offer_date.return_value = datetime(2022, 10, 20)
        expected_date = datetime(2022, 11, 30).date()
        self.application.save()
        self.account.save()

        first_due_date = get_first_payment_date_by_application(self.application)
        self.assertEqual(first_due_date, expected_date)

    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    def test_get_first_payment_date_by_application_early(self, mock_offer_date):
        # payday = 20, cycle_day = 21, offer_date = 11 Aug => 21 Sept
        self.application.payday = 20
        self.account.cycle_day = 21
        mock_offer_date.return_value = datetime(2022, 8, 11)
        expected_date = datetime(2022, 9, 21).date()
        self.application.save()
        self.account.save()

        first_due_date = get_first_payment_date_by_application(self.application)
        self.assertEqual(first_due_date, expected_date)

        # payday = 7, cycle_day = 10, offer_date = 27 May => 10 July
        self.application.payday = 7
        self.account.cycle_day = 10
        mock_offer_date.return_value = datetime(2022, 5, 27)
        expected_date = datetime(2022, 7, 10).date()
        self.application.save()
        self.account.save()

        first_due_date = get_first_payment_date_by_application(self.application)
        self.assertEqual(first_due_date, expected_date)

        # payday = 5, cycle_day = 9, offer_date = 29 Sep => 9 Nov
        self.application.payday = 5
        self.account.cycle_day = 9
        mock_offer_date.return_value = datetime(2022, 9, 29)
        expected_date = datetime(2022, 11, 9).date()
        self.application.save()
        self.account.save()

        first_due_date = get_first_payment_date_by_application(self.application)
        self.assertEqual(first_due_date, expected_date)

        # payday = 10, cycle_day = 15, offer_date = 22 Sep => 15 Oct
        self.application.payday = 10
        self.account.cycle_day = 15
        mock_offer_date.return_value = datetime(2022, 9, 22)
        expected_date = datetime(2022, 10, 15).date()
        self.application.save()
        self.account.save()

        first_due_date = get_first_payment_date_by_application(self.application)
        self.assertEqual(first_due_date, expected_date)

        # payday = 1, cycle_day = 1, offer_date = 30 Sep => 1 Nov
        self.application.payday = 1
        self.account.cycle_day = 1
        mock_offer_date.return_value = datetime(2022, 9, 30)
        expected_date = datetime(2022, 11, 1).date()
        self.application.save()
        self.account.save()

        first_due_date = get_first_payment_date_by_application(self.application)
        self.assertEqual(first_due_date, expected_date)

    @patch('juloserver.loan.services.loan_related.timezone.localtime')
    def test_get_first_payment_date_by_application_holiday(self, mock_offer_date):
        # payday = 10, cycle_day = 16, offer_date = 15 April => 3 May
        self.application.payday = 10
        self.account.cycle_day = 16
        mock_offer_date.return_value = datetime(2022, 4, 15)
        expected_date = datetime(2022, 5, 16).date()
        self.application.save()
        self.account.save()

        first_due_date = get_first_payment_date_by_application(self.application)
        self.assertEqual(first_due_date, expected_date)

        # payday = 10, cycle_day = 2, offer_date = 15 April => 3 May
        self.application.payday = 10
        self.account.cycle_day = 2
        mock_offer_date.return_value = datetime(2022, 4, 15)
        expected_date = datetime(2022, 5, 2).date()
        self.application.save()
        self.account.save()

        first_due_date = get_first_payment_date_by_application(self.application)
        self.assertEqual(first_due_date, expected_date)

        # payday = 17, cycle_day = 25, offer_date = 25 Nov 2023 => 26 Dec 2023
        self.application.payday = 17
        self.account.cycle_day = 25
        mock_offer_date.return_value = datetime(2023, 11, 25)
        expected_date = datetime(2023, 12, 25).date()
        self.application.save()
        self.account.save()

        first_due_date = get_first_payment_date_by_application(self.application)
        self.assertEqual(first_due_date, expected_date)

    @patch('juloserver.julo.services.send_customer_data_change_by_agent_notification_task.delay')
    def test_create_history_change_payday_by_manually(
        self,
        mock_send_customer_data_change_by_agent_notification_task,
    ):
        old_cycle_day = self.account.cycle_day
        payday = 12
        self.new_data = [
            {
                "field_name": "payday", "group": "-","agent": "", "type":"field",
                "undisclosed_expense": [], "value": payday
            },
        ]
        update_application_checklist_collection(self.application, self.new_data)
        history = AccountCycleDayHistory.objects.filter(
            account_id=self.application.account_id,
            latest_flag=True, reason=LDDEReasonConst.Manual
        ).first()
        self.account.refresh_from_db()

        assert history.old_cycle_day == old_cycle_day
        assert history.new_cycle_day == self.account.cycle_day


class TestPTPCreation(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.agent = AuthUserFactory()

    @mock.patch('juloserver.minisquad.tasks2.google_calendar_task.'
                'set_google_calendar_payment_reminder_by_account_payment_id.delay')
    @mock.patch.object(PTP.objects, 'create', return_value=None)
    @mock.patch.object(PTP.objects, 'filter', return_value=None)
    def test_ptp_create_success_grab(self, mocked_ptp, mocked_ptp_create, mocked_calender):
        ptp_date = '2022-12-10'
        ptp_amount = '1500'
        ptp_create(self.account_payment, ptp_date,
                   ptp_amount, self.agent, is_julo_one=False, is_grab=True)
        mocked_ptp.assert_called()
        mocked_ptp_create.assert_called()
        mocked_calender.assert_not_called()

    @mock.patch('juloserver.minisquad.tasks2.google_calendar_task.'
                'set_google_calendar_payment_reminder_by_account_payment_id.delay')
    @mock.patch.object(PTP.objects, 'create', return_value=None)
    @mock.patch.object(PTP.objects, 'filter')
    def test_ptp_filter_success_grab(self, mocked_ptp_filter, mocked_ptp_create, mocked_calender):
        ptp_date = datetime(2022, 12, 12)
        ptp_amount = '1500'
        mocked_qs = mock.MagicMock()
        mocked_qs.last.return_value = object
        mocked_ptp_filter.return_value = mocked_qs
        ptp_create(self.account_payment, ptp_date,
                   ptp_amount, self.agent, is_julo_one=False, is_grab=True)
        mocked_ptp_create.assert_not_called()
        mocked_calender.assert_not_called()


class TestNotifyMoengage(TestCase):
    class PaymentMethodMock:
        def __init__(self, customer):
            self.customer_id = customer.id

    def setUp(self) -> None:
        self.customer = CustomerFactory()

    @patch('juloserver.moengage.services.use_cases.send_user_attributes_to_moengage_for_va_change')
    def test_handle_notify_moengage_after_payment_method_change(self, mock_send):
        pm = self.PaymentMethodMock(self.customer)
        handle_notify_moengage_after_payment_method_change(pm)
        force_run_on_commit_hook()
        mock_send.delay.assert_called()


class TestAutoAdjustDueDateCalculation(TestCase):
    def setUp(self):
        self.customer_id = 1000310954
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            is_ldde=True,
            cycle_day=28,
            is_payday_changed=False
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            payday=24,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
        )
        self.application.change_status(ApplicationStatusCodes.LOC_APPROVED)
        self.feature_setting = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.AUTO_ADJUST_DUE_DATE,
            category="loan",
            is_active=True,
            parameters={
                "auto_adjust_due_date_mapping": {
                    '26': 1,
                    '27': 1,
                    '28': 1,
                    '29': 2,
                    '30': 2,
                    '31': 2
                },
                "whitelist": {
                    "is_active": False,
                    "last_customer_digit": {'from': '00', 'to': '00'},
                    "customer_ids": []
                }
            }
        )

    def test_is_eligible_auto_adjust_due_date_whitelist(self):
        # Inactive whitelist -> True
        self.assertTrue(
            is_eligible_auto_adjust_due_date(
                self.customer_id, self.feature_setting.parameters["whitelist"]
            )
        )

        # Active but not in customer_ids or matched last digits -> False
        self.feature_setting.parameters["whitelist"]["is_active"] = True
        self.feature_setting.save()
        self.assertFalse(
            is_eligible_auto_adjust_due_date(
                self.customer_id, self.feature_setting.parameters["whitelist"]
            )
        )

        # Active and in customer_ids
        self.feature_setting.parameters["whitelist"]["customer_ids"] = [1000310954]
        self.feature_setting.save()
        self.assertTrue(
            is_eligible_auto_adjust_due_date(
                self.customer_id, self.feature_setting.parameters["whitelist"]
            )
        )

        # Active and matched last digits
        self.feature_setting.parameters["whitelist"]["customer_ids"] = []
        self.feature_setting.parameters["whitelist"]["last_customer_digit"]["to"] = '99'
        self.feature_setting.save()
        self.assertTrue(
            is_eligible_auto_adjust_due_date(
                self.customer_id, self.feature_setting.parameters["whitelist"]
            )
        )

    @mock.patch("django.utils.timezone.now")
    def test_auto_adjust_due_date(self, mock_now):
        # Adjust and no forward
        mock_now.return_value = timezone.datetime(2025, 5, 24, 0, 0, 0)
        mapping_config = self.feature_setting.parameters["auto_adjust_due_date_mapping"]

        self.account.update_safely(cycle_day=28)
        new_cycle_day, first_payment_date = get_auto_adjust_due_date(
            self.account, mapping_config
        )

        self.assertEqual(new_cycle_day, 1)
        self.assertEqual(first_payment_date, date(2025, 6, 1))

        # Adjust and forward
        mock_now.return_value = timezone.datetime(2025, 5, 27, 0, 0, 0)
        self.account.update_safely(cycle_day=28)
        new_cycle_day, first_payment_date = get_auto_adjust_due_date(
            self.account, mapping_config
        )

        self.assertEqual(new_cycle_day, 1)
        self.assertEqual(first_payment_date, date(2025, 7, 1))

    @mock.patch("django.utils.timezone.now")
    def test_auto_adjust_due_date_no_change(self, mock_now):
        # No adjust and no forward
        mock_now.return_value = timezone.datetime(2025, 5, 24, 0, 0, 0)
        mapping_config = self.feature_setting.parameters["auto_adjust_due_date_mapping"]

        self.account.update_safely(cycle_day=25)
        new_cycle_day, first_payment_date = get_auto_adjust_due_date(
            self.account, mapping_config
        )

        self.assertIsNone(new_cycle_day)
        self.assertEqual(first_payment_date, date(2025, 6, 25))

        # No adjust and forward
        mock_now.return_value = timezone.datetime(2025, 5, 28, 0, 0, 0)
        self.account.update_safely(cycle_day=2)
        new_cycle_day, first_payment_date = get_auto_adjust_due_date(
            self.account, mapping_config
        )

        self.assertIsNone(new_cycle_day)
        self.assertEqual(first_payment_date, date(2025, 7, 2))

    @mock.patch("juloserver.loan.services.loan_related.get_auto_adjust_due_date")
    def test_auto_adjust_due_date_fs_off_not_called(self, mock_auto_adjust):
        self.feature_setting.update_safely(is_active=False)
        get_first_payment_date_by_application(self.application)

        mock_auto_adjust.assert_not_called()

    @mock.patch("juloserver.loan.services.loan_related.get_auto_adjust_due_date")
    def test_auto_adjust_due_date_not_j1(self, mock_auto_adjust):
        self.application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.DANA)
        )
        get_first_payment_date_by_application(self.application)

        mock_auto_adjust.assert_not_called()

    @mock.patch("juloserver.loan.services.loan_related.get_auto_adjust_due_date")
    def test_auto_adjust_due_date_with_manual_change_not_called(self, mock_auto_adjust):
        self.account.update_safely(is_payday_changed=True)
        get_first_payment_date_by_application(self.application)

        mock_auto_adjust.assert_not_called()

    @mock.patch("juloserver.loan.services.loan_related.get_auto_adjust_due_date")
    @mock.patch("juloserver.loan.services.loan_related.is_eligible_auto_adjust_due_date")
    def test_auto_adjust_due_date_not_eligible_not_called(self, mock_is_eligible, mock_auto_adjust):
        mock_is_eligible.return_value = False
        get_first_payment_date_by_application(self.application)

        mock_auto_adjust.assert_not_called()

    @mock.patch("juloserver.loan.services.loan_related.get_auto_adjust_due_date")
    @mock.patch("juloserver.loan.services.loan_related.is_eligible_auto_adjust_due_date")
    def test_auto_adjust_due_date_called(self, mock_is_eligible, mock_auto_adjust):
        mock_is_eligible.return_value = True
        mock_auto_adjust.return_value = 28, date(2025, 6, 3)

        self.account.update_safely(is_payday_changed=False)
        get_first_payment_date_by_application(self.application)

        mock_auto_adjust.assert_called_once()
