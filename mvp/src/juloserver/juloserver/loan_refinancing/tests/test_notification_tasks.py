import mock
from mock import patch
from datetime import datetime, timedelta
from django.utils import timezone

from django.test.utils import override_settings

from juloserver.julo.exceptions import JuloException
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.tests.factories import CustomerFactory, ApplicationFactory, \
    LoanFactory, PaymentMethodFactory, PaymentFactory
from juloserver.julo.models import SmsHistory, CommsProviderLookup, ProductLine, EmailHistory, \
    StatusLookup
from django.test.testcases import TestCase

from juloserver.loan_refinancing.services.loan_related import get_unpaid_payments
from juloserver.loan_refinancing.tasks import send_sms_notification, \
    send_email_covid_refinancing_activated, send_email_covid_refinancing_approved, \
    send_sms_covid_refinancing_offer_selected, send_email_covid_refinancing_reminder, \
    send_reminder_email_opt, send_email_covid_refinancing_opt, send_email_pending_covid_refinancing, \
    send_email_covid_refinancing_reminder_to_pay_minus_2, \
    send_email_covid_refinancing_reminder_to_pay_minus_1, send_proactive_email_reminder, \
    send_email_refinancing_offer_selected, send_email_refinancing_offer_selected_minus_1, \
    send_email_refinancing_offer_selected_minus_2
from juloserver.loan_refinancing.constants import (
    CovidRefinancingConst,
    LoanRefinancingConst,
    Campaign
)
from juloserver.loan_refinancing.tests.factories import (
    LoanRefinancingRequestFactory,
    LoanRefinancingOfferFactory,
    CollectionOfferExtensionConfigurationFactory,
    LoanRefinancingRequestCampaignFactory
)
from juloserver.loan_refinancing.tasks.notification_tasks import (
    send_all_refinancing_request_reminder_to_pay_minus_2,
    send_all_refinancing_request_reminder_to_pay_minus_1,
    send_all_refinancing_offer_reminder_for_requested_status_campaign_minus_2,
    send_all_refinancing_offer_reminder_for_requested_status_campaign_minus_1
)
from juloserver.loan_refinancing.models import LoanRefinancingRequestCampaign
from django.db.models.expressions import RawSQL


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestUploadIntelixTasks(TestCase):

    def setUp(self):
        self.customer = CustomerFactory()
        self.provider = CommsProviderLookup.objects.create(provider_name='dummy_provider')
        self.phone = "+6285756450098"
        self.dummy_text = 'dummy text message'
        self.template_code = 'dummy_template_code'

    @mock.patch('juloserver.loan_refinancing.tasks.notification_tasks.get_julo_sms_client')
    def test_send_sms_notification_success(self, mocked_sms_client):
        mocked_sms_client.return_value.prefix_change_notification.return_value = (
            self.dummy_text,
            {"status": "0", "to": self.phone, "message-id": "123456", "julo_sms_vendor": self.provider.provider_name}
        )

        send_sms_notification.delay(self.customer.id, self.phone, self.dummy_text, self.template_code)
        sms_history = SmsHistory.objects.get_or_none(template_code=self.template_code)
        self.assertIsNotNone(sms_history)

    @mock.patch('juloserver.loan_refinancing.tasks.notification_tasks.get_julo_sms_client')
    def test_send_sms_notification_success_otp(self, mocked_sms_client):
        mocked_sms_client.return_value.prefix_change_notification.return_value = (
            self.dummy_text,
            {"status": "0", "to": self.phone,
             "message-id": "123456",
             "julo_sms_vendor": self.provider.provider_name,
             "is_otp": True
             }
        )

        send_sms_notification.delay(self.customer.id, self.phone, self.dummy_text, self.template_code)
        sms_history = SmsHistory.objects.get_or_none(template_code=self.template_code)
        self.assertIsNotNone(sms_history)
        self.assertTrue(sms_history.is_otp)

    @mock.patch('juloserver.loan_refinancing.tasks.notification_tasks.get_julo_sms_client')
    def test_send_sms_notification_failed(self, mocked_sms_client):
        from juloserver.julo.exceptions import SmsNotSent
        error_text = "gagal kirim sms"
        mocked_sms_client.return_value.prefix_change_notification.return_value = (
            self.dummy_text,
            {"status": "5", "to": self.phone,
             "message-id": "123456", "julo_sms_vendor": self.provider.provider_name,
             "error_text": error_text}
        )

        with self.assertRaises(Exception) as context:
            send_sms_notification.delay(self.customer.id, self.phone, self.dummy_text, self.template_code)

        self.assertEqual(SmsNotSent, type(context.exception))

    @mock.patch('juloserver.loan_refinancing.tasks.notification_tasks.get_julo_sms_client')
    def test_send_sms_notification_wrong_provider(self, mocked_sms_client):
        mocked_sms_client.return_value.prefix_change_notification.return_value = (
            self.dummy_text,
            {"status": "0", "to": self.phone, "message-id": "123456", "julo_sms_vendor": 'wrong provider'}
        )

        send_sms_notification.delay(self.customer.id, self.phone, self.dummy_text, self.template_code)
        sms_history = SmsHistory.objects.get_or_none(template_code=self.template_code)
        self.assertIsNone(sms_history)


class TestRefinancingRequestNotification(TestCase):
    def setUp(self):
        mtl_product = ProductLine.objects.get(pk=ProductLineCodes.MTL1)
        application = ApplicationFactory(product_line=mtl_product)
        loan = LoanFactory(application=application)
        PaymentMethodFactory(customer=application.customer, is_primary=True)

        self.loan_ref_req = LoanRefinancingRequestFactory(
            product_type="R4",
            loan=loan
        )

    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_email_covid_refinancing_reminder_to_pay_minus_2')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_sms_covid_refinancing_reminder_to_pay_minus_2')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_pn_covid_refinancing_reminder_to_pay_minus_2')
    def test_send_all_refinancing_request_reminder_to_pay_minus_2(
            self, mock_send_pn, mock_send_sms, mock_send_email):
        self.loan_ref_req.status = 'Approved'
        self.loan_ref_req.comms_channel_1 = CovidRefinancingConst.COMMS_CHANNELS.email
        self.loan_ref_req.comms_channel_2 = CovidRefinancingConst.COMMS_CHANNELS.sms
        self.loan_ref_req.comms_channel_3 = CovidRefinancingConst.COMMS_CHANNELS.pn
        self.loan_ref_req.expire_in_days = 4
        self.loan_ref_req.save()
        self.loan_ref_req.refresh_from_db()
        loan_ref_offer = LoanRefinancingOfferFactory(
            loan_refinancing_request=self.loan_ref_req,
            is_accepted=True,
            offer_accepted_ts=timezone.now().date() - timedelta(days=2)
        )
        send_all_refinancing_request_reminder_to_pay_minus_2()
        mock_send_pn.apply_async.assert_called_once_with((self.loan_ref_req.id,), countdown=3600)
        mock_send_sms.apply_async.assert_called_once_with((self.loan_ref_req.id,), countdown=7200)
        mock_send_email.delay.assert_called_once_with(self.loan_ref_req.id)

    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_email_covid_refinancing_reminder_to_pay_minus_1')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_sms_covid_refinancing_reminder_to_pay_minus_1')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_pn_covid_refinancing_reminder_to_pay_minus_1')
    def test_send_loan_refinancing_request_reminder_minus_1(
            self, mock_send_pn, mock_send_sms, mock_send_email):
        self.loan_ref_req.status = 'Approved'
        self.loan_ref_req.comms_channel_1 = CovidRefinancingConst.COMMS_CHANNELS.email
        self.loan_ref_req.comms_channel_2 = CovidRefinancingConst.COMMS_CHANNELS.sms
        self.loan_ref_req.comms_channel_3 = CovidRefinancingConst.COMMS_CHANNELS.pn
        self.loan_ref_req.expire_in_days = 3
        self.loan_ref_req.save()
        self.loan_ref_req.refresh_from_db()
        loan_ref_offer = LoanRefinancingOfferFactory(
            loan_refinancing_request=self.loan_ref_req,
            is_accepted=True,
            offer_accepted_ts=timezone.now().date() - timedelta(days=2)
        )
        send_all_refinancing_request_reminder_to_pay_minus_1()
        mock_send_pn.apply_async.assert_called_once_with((self.loan_ref_req.id,), countdown=3600)
        mock_send_sms.apply_async.assert_called_once_with((self.loan_ref_req.id,), countdown=7200)
        mock_send_email.delay.assert_called_once_with(self.loan_ref_req.id)

    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_email_requested_status_campaign_reminder_to_pay_minus_2')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_pn_requested_status_campaign_reminder_to_pay_minus_2')
    def test_send_all_refinancing_offer_reminder_for_requested_status_campaign_minus_2(
            self, mock_send_pn, mock_send_email):
        self.loan_ref_req.status = 'Requested'
        self.loan_ref_req.comms_channel_1 = CovidRefinancingConst.COMMS_CHANNELS.email
        self.loan_ref_req.comms_channel_2 = CovidRefinancingConst.COMMS_CHANNELS.pn
        self.loan_ref_req.expire_in_days = 4
        self.loan_ref_req.request_date=timezone.now().date() - timedelta(days=2)
        loan_ref_req_cam = LoanRefinancingRequestCampaignFactory(
            loan_id=self.loan_ref_req.loan_id,
            loan_refinancing_request=self.loan_ref_req,
            campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
            expired_at = (datetime.today() + timedelta(days=2)).date()
        )
        loan_ref_req_cam.save()
        self.loan_ref_req.save()
        self.loan_ref_req.refresh_from_db()
        send_all_refinancing_offer_reminder_for_requested_status_campaign_minus_2()
        mock_send_pn.apply_async.assert_called_once_with((self.loan_ref_req.id,), countdown=3600)
        mock_send_email.delay.assert_called_once_with(self.loan_ref_req.id)

    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_email_requested_status_campaign_reminder_to_pay_minus_1')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_pn_requested_status_campaign_reminder_to_pay_minus_1')
    def test_send_all_refinancing_offer_reminder_for_requested_status_campaign_minus_1(
            self, mock_send_pn, mock_send_email):
        self.loan_ref_req.status = 'Requested'
        self.loan_ref_req.comms_channel_1 = CovidRefinancingConst.COMMS_CHANNELS.email
        self.loan_ref_req.comms_channel_2 = CovidRefinancingConst.COMMS_CHANNELS.pn
        self.loan_ref_req.expire_in_days = 2
        self.loan_ref_req.request_date=timezone.now().date() - timedelta(days=1)
        loan_ref_req_cam = LoanRefinancingRequestCampaignFactory(
            loan_id=self.loan_ref_req.loan_id,
            loan_refinancing_request=self.loan_ref_req,
            campaign_name=Campaign.COHORT_CAMPAIGN_NAME,
            expired_at = (datetime.today() + timedelta(days=1)).date()
        )
        loan_ref_req_cam.save()
        self.loan_ref_req.save()
        self.loan_ref_req.refresh_from_db()
        send_all_refinancing_offer_reminder_for_requested_status_campaign_minus_1()
        mock_send_pn.apply_async.assert_called_once_with((self.loan_ref_req.id,), countdown=3600)
        mock_send_email.delay.assert_called_once_with(self.loan_ref_req.id)


class TestRefinancingRequestNotificationWaiverProduct(TestCase):
    def setUp(self):
        mtl_product = ProductLine.objects.get(pk=ProductLineCodes.MTL1)
        application = ApplicationFactory(product_line=mtl_product)
        loan = LoanFactory(application=application)
        PaymentMethodFactory(customer=application.customer, is_primary=True)

        self.loan_ref_req = LoanRefinancingRequestFactory(
            product_type="R4",
            loan=loan,
            expire_in_days=5,
            comms_channel_1="Email",
        )

        self.coll_ext_conf = CollectionOfferExtensionConfigurationFactory(
            product_type='R4',
            remaining_payment=2,
            max_extension=3,
            date_start=timezone.localtime(timezone.now()).date(),
            date_end=timezone.localtime(timezone.now()).date(),
        )

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_covid_refinancing_activated(self, mocked_email_client):
        mocked_email_client.return_value.email_base.return_value = (
            202, {'X-Message-Id': 'covid_refinancing_activated123'},
            'dummy_subject', 'dummy_message', 'dummy_template')

        send_email_covid_refinancing_activated(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='covid_refinancing_activated123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_covid_refinancing_approved(self, mocked_email_client):
        mocked_email_client.return_value.email_covid_refinancing_approved_for_r4.return_value = (
            202, {'X-Message-Id': 'covid_refinancing_approved123'},
            'dummy_subject', 'dummy_message')

        send_email_covid_refinancing_approved(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='covid_refinancing_approved123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_covid_refinancing_reminder(self, mocked_email_client):
        mocked_email_client.return_value.email_reminder_refinancing.return_value = (
            202, {'X-Message-Id': 'send_email_covid_refinancing_reminder123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        send_email_covid_refinancing_reminder(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_covid_refinancing_reminder123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_covid_refinancing_opt(self, mocked_email_client):
        mocked_email_client.return_value.email_covid_refinancing_opt.return_value = (
            202, {'X-Message-Id': 'send_email_covid_refinancing_opt123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        self.loan_ref_req.update_safely(status='Proposed')
        send_email_covid_refinancing_opt(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_covid_refinancing_opt123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    @patch('juloserver.loan_refinancing.services.refinancing_product_related.'
           'get_max_tenure_extension_r1')
    def test_send_email_pending_covid_refinancing(self, mocked_max_tenure, mocked_email_client):
        mocked_email_client.return_value.email_covid_pending_refinancing_approved_for_all_product.\
            return_value = (
            202, {'X-Message-Id': 'send_email_pending_covid_refinancing123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        mocked_max_tenure.return_value = 9
        self.loan_ref_req.update_safely(product_type='R1')
        send_email_pending_covid_refinancing(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_pending_covid_refinancing123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_covid_refinancing_reminder_to_pay_minus_2(self, mocked_email_client):
        self.loan_ref_req.status = CovidRefinancingConst.STATUSES.approved
        self.loan_ref_req.save()
        mocked_email_client.return_value.email_base.return_value = (
            202, {'X-Message-Id': 'send_email_covid_refinancing_reminder_to_pay_minus_2123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        send_email_covid_refinancing_reminder_to_pay_minus_2(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_covid_refinancing_reminder_to_pay_minus_2123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_covid_refinancing_reminder_to_pay_minus_1(self, mocked_email_client):
        self.loan_ref_req.status = CovidRefinancingConst.STATUSES.approved
        self.loan_ref_req.save()
        mocked_email_client.return_value.email_base.return_value = (
            202, {'X-Message-Id': 'send_email_covid_refinancing_reminder_to_pay_minus_1123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        send_email_covid_refinancing_reminder_to_pay_minus_1(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_covid_refinancing_reminder_to_pay_minus_1123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_proactive_email_reminder(self, mocked_email_client):
        mocked_email_client.return_value.email_proactive_refinancing_reminder.return_value = (
            202, {'X-Message-Id': 'send_proactive_email_reminder123'},
            'dummy_subject', 'dummy_message', 'dummy_template')

        self.loan_ref_req.update_safely(
            status=CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email)
        loan_ref_req = self.loan_ref_req
        loan_ref_req.update_safely(
            channel=CovidRefinancingConst.CHANNELS.proactive)
        send_proactive_email_reminder(loan_ref_req.id, "email", 2)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_proactive_email_reminder123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_refinancing_offer_selected_for_proactive_channel(self, mocked_email_client):
        mocked_email_client.return_value.email_refinancing_offer_selected.return_value = (
            202, {'X-Message-Id': 'send_email_refinancing_offer_selected123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        self.loan_ref_req.channel='Proactive'
        self.loan_ref_req.save()
        send_email_refinancing_offer_selected(self.loan_ref_req.id)
        email_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_refinancing_offer_selected123')
        self.assertIsNotNone(email_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_refinancing_offer_selected_for_reactive_channel(self, mocked_email_client):
        mocked_email_client.return_value.email_refinancing_offer_selected.return_value = (
            202, {'X-Message-Id': 'send_email_refinancing_offer_selected123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        self.loan_ref_req.channel='Reactive'
        self.loan_ref_req.save()
        send_email_refinancing_offer_selected(self.loan_ref_req.id)
        email_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_refinancing_offer_selected123')
        self.assertIsNotNone(email_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_refinancing_offer_selected_minus_1(self, mocked_email_client):
        mocked_email_client.return_value.email_refinancing_offer_selected.return_value = (
            202, {'X-Message-Id': 'send_email_refinancing_offer_selected_minus_1123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        send_email_refinancing_offer_selected_minus_1(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_refinancing_offer_selected_minus_1123')
        self.assertIsNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_refinancing_offer_selected_minus_2(self, mocked_email_client):
        mocked_email_client.return_value.email_refinancing_offer_selected.return_value = (
            202, {'X-Message-Id': 'send_email_refinancing_offer_selected_minus_2123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        send_email_refinancing_offer_selected_minus_2(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_refinancing_offer_selected_minus_2123')
        self.assertIsNone(sms_history)

class TestRefinancingRequestNotificationR1(TestCase):
    def setUp(self):
        mtl_product = ProductLine.objects.get(pk=ProductLineCodes.MTL1)
        application = ApplicationFactory(product_line=mtl_product)
        self.loan = LoanFactory(application=application)
        dpd_1_status = StatusLookup.objects.get(pk=PaymentStatusCodes.PAYMENT_1DPD)
        for payment in self.loan.payment_set.all():
            payment.update_safely(
                payment_status=dpd_1_status,
            )
        PaymentMethodFactory(customer=application.customer, is_primary=True)

        self.loan_ref_req = LoanRefinancingRequestFactory(
            product_type='R1',
            loan=self.loan,
            expire_in_days=5,
            loan_duration=self.loan.loan_duration,
            form_submitted_ts= timezone.now(),
            comms_channel_1="Email",
        )

        self.coll_ext_conf = CollectionOfferExtensionConfigurationFactory(
            product_type='R1',
            remaining_payment=2,
            max_extension=3,
            date_start=timezone.localtime(timezone.now()).date(),
            date_end=timezone.localtime(timezone.now()).date(),
        )

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_covid_refinancing_activated(self, mocked_email_client):
        mocked_email_client.return_value.email_covid_refinancing_activated_for_all_product\
            .return_value = (202, {'X-Message-Id': 'covid_refinancing_activated123'},
                             'dummy_subject', 'dummy_message', 'dummy_template')

        send_email_covid_refinancing_activated(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='covid_refinancing_activated123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.refinancing_product_related.'
           'get_max_tenure_extension_r1')
    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    @patch('juloserver.loan_refinancing.services.loan_related.get_unpaid_payments')
    def test_send_email_covid_refinancing_approved(self, mocked_get_payments,
                                                   mocked_email_client, mocked_max_tenure):
        mocked_get_payments.return_value = self.loan_ref_req.loan.payment_set.all()
        mocked_email_client.return_value.email_covid_refinancing_approved_for_all_product.return_value = (
            202, {'X-Message-Id': 'covid_refinancing_approved123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        mocked_max_tenure.return_value = 9
        send_email_covid_refinancing_approved(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='covid_refinancing_approved123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_covid_refinancing_reminder(self, mocked_email_client):
        mocked_email_client.return_value.email_reminder_refinancing.return_value = (
            202, {'X-Message-Id': 'send_email_covid_refinancing_reminder123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        send_email_covid_refinancing_reminder(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_covid_refinancing_reminder123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_covid_refinancing_opt(self, mocked_email_client):
        mocked_email_client.return_value.email_covid_refinancing_opt.return_value = (
            202, {'X-Message-Id': 'send_email_covid_refinancing_opt123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        self.loan_ref_req.update_safely(status='Proposed')
        send_email_covid_refinancing_opt(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_covid_refinancing_opt123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.refinancing_product_related.'
           'get_max_tenure_extension_r1')
    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    @patch('juloserver.loan_refinancing.services.loan_related.get_unpaid_payments')
    def test_send_email_pending_covid_refinancing(self, mocked_get_payments,
                                                  mocked_email_client,
                                                  mocked_max_tenure):
        mocked_get_payments.return_value = self.loan_ref_req.loan.payment_set.all()
        mocked_email_client.return_value.email_covid_pending_refinancing_approved_for_all_product\
            .return_value = (
            202, {'X-Message-Id': 'send_email_pending_covid_refinancing123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        mocked_max_tenure.return_value = 9
        self.loan_ref_req.update_safely(product_type='R1')
        send_email_pending_covid_refinancing(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_pending_covid_refinancing123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_covid_refinancing_reminder_to_pay_minus_2(self, mocked_email_client):
        self.loan_ref_req.status = CovidRefinancingConst.STATUSES.approved
        self.loan_ref_req.save()
        mocked_email_client.return_value.email_base.return_value = (
            202, {'X-Message-Id': 'send_email_covid_refinancing_reminder_to_pay_minus_2123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        send_email_covid_refinancing_reminder_to_pay_minus_2(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_covid_refinancing_reminder_to_pay_minus_2123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_covid_refinancing_reminder_to_pay_minus_1(self, mocked_email_client):
        self.loan_ref_req.status = CovidRefinancingConst.STATUSES.approved
        self.loan_ref_req.save()
        mocked_email_client.return_value.email_base.return_value = (
            202, {'X-Message-Id': 'send_email_covid_refinancing_reminder_to_pay_minus_1123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        send_email_covid_refinancing_reminder_to_pay_minus_1(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_covid_refinancing_reminder_to_pay_minus_1123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_covid_refinancing_reminder_to_pay_minus_1(self, mocked_email_client):
        self.loan_ref_req.status = CovidRefinancingConst.STATUSES.approved
        self.loan_ref_req.save()
        mocked_email_client.return_value.email_base.return_value = (
            202, {'X-Message-Id': 'send_email_covid_refinancing_reminder_to_pay_minus_1123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        send_email_covid_refinancing_reminder_to_pay_minus_1(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_covid_refinancing_reminder_to_pay_minus_1123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_proactive_email_reminder(self, mocked_email_client):
        mocked_email_client.return_value.email_proactive_refinancing_reminder.return_value = (
            202, {'X-Message-Id': 'send_proactive_email_reminder123'},
            'dummy_subject', 'dummy_message', 'dummy_template')

        self.loan_ref_req.update_safely(
            status=CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email)
        loan_ref_req = self.loan_ref_req
        loan_ref_req.update_safely(
            channel=CovidRefinancingConst.CHANNELS.proactive)
        send_proactive_email_reminder(loan_ref_req.id, "email", 2)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_proactive_email_reminder123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_refinancing_offer_selected(self, mocked_email_client):
        mocked_email_client.return_value.email_refinancing_offer_selected.return_value = (
            202, {'X-Message-Id': 'send_email_refinancing_offer_selected123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        send_email_refinancing_offer_selected(self.loan_ref_req.id)
        email_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_refinancing_offer_selected123')
        self.assertIsNotNone(email_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_refinancing_offer_selected_minus_1(self, mocked_email_client):
        mocked_email_client.return_value.email_refinancing_offer_selected.return_value = (
            202, {'X-Message-Id': 'send_email_refinancing_offer_selected_minus_1123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        send_email_refinancing_offer_selected_minus_1(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_refinancing_offer_selected_minus_1123')
        self.assertIsNotNone(sms_history)

    @patch('juloserver.loan_refinancing.services.notification_related.get_julo_email_client')
    def test_send_email_refinancing_offer_selected_minus_2(self, mocked_email_client):
        mocked_email_client.return_value.email_refinancing_offer_selected.return_value = (
            202, {'X-Message-Id': 'send_email_refinancing_offer_selected_minus_2123'},
            'dummy_subject', 'dummy_message', 'dummy_template')
        send_email_refinancing_offer_selected_minus_2(self.loan_ref_req.id)
        sms_history = EmailHistory.objects.get_or_none(
            sg_message_id='send_email_refinancing_offer_selected_minus_2123')
        self.assertIsNotNone(sms_history)