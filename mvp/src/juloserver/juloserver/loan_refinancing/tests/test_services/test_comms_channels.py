from datetime import datetime, timedelta

from django.utils import timezone
from mock import patch, MagicMock
from django.test import TestCase
from juloserver.loan_refinancing.services.notification_related import (
    CovidLoanRefinancingEmail, CovidLoanRefinancingSMS, CovidLoanRefinancingPN)
from juloserver.loan_refinancing.services.comms_channels import (
    send_loan_refinancing_request_reminder_minus_2,
    send_loan_refinancing_request_reminder_minus_1,
    send_proactive_refinancing_reminder, send_loan_refinancing_request_offer_selected_notification,
    send_loan_refinancing_robocall_reminder_minus_3,
    send_loan_refinancing_request_reminder_offer_selected_1,
    send_loan_refinancing_request_reminder_offer_selected_2,
    send_loan_refinancing_request_approved_notification,
    send_loan_refinancing_request_activated_notification,
    send_loan_refinancing_requested_status_campaign_reminder_minus_2,
    send_loan_refinancing_requested_status_campaign_reminder_minus_1
)
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.loan_refinancing.tests.factories import (
    LoanRefinancingRequestFactory, LoanRefinancingRequestCampaignFactory,
    LoanRefinancingOfferFactory)
from juloserver.loan_refinancing.constants import Campaign
from juloserver.julo.utils import display_rupiah
from babel.dates import format_date


class TestCovidLoanRefinancingComms(TestCase):
    def setUp(self):
        self.loan_ref_req = LoanRefinancingRequestFactory(product_type="R4")

    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_email_covid_refinancing_reminder_to_pay_minus_2')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_sms_covid_refinancing_reminder_to_pay_minus_2')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_pn_covid_refinancing_reminder_to_pay_minus_2')
    def test_send_loan_refinancing_request_reminder_minus_2(
            self, mock_send_pn, mock_send_sms, mock_send_email):
        self.loan_ref_req.comms_channel_1 = CovidRefinancingConst.COMMS_CHANNELS.email
        self.loan_ref_req.comms_channel_2 = CovidRefinancingConst.COMMS_CHANNELS.sms
        self.loan_ref_req.comms_channel_3 = CovidRefinancingConst.COMMS_CHANNELS.pn
        self.loan_ref_req.save()
        send_loan_refinancing_request_reminder_minus_2(self.loan_ref_req)
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
        self.loan_ref_req.comms_channel_1 = CovidRefinancingConst.COMMS_CHANNELS.email
        self.loan_ref_req.comms_channel_2 = CovidRefinancingConst.COMMS_CHANNELS.sms
        self.loan_ref_req.comms_channel_3 = CovidRefinancingConst.COMMS_CHANNELS.pn
        self.loan_ref_req.save()
        send_loan_refinancing_request_reminder_minus_1(self.loan_ref_req)
        mock_send_pn.apply_async.assert_called_once_with((self.loan_ref_req.id,), countdown=3600)
        mock_send_sms.apply_async.assert_called_once_with((self.loan_ref_req.id,), countdown=7200)
        mock_send_email.delay.assert_called_once_with(self.loan_ref_req.id)

    @patch('juloserver.loan_refinancing.services.comms_channels.send_proactive_robocall_reminder')
    @patch('juloserver.loan_refinancing.services.comms_channels.timezone.localtime')
    def test_send_proactive_robocall(self, mocked_localtime, mocked_task):
        today = timezone.now()
        new_period = today.replace(hour=10)
        mocked_localtime.return_value = new_period
        send_proactive_refinancing_reminder(self.loan_ref_req, 'robocall', 2)

        new_period = today.replace(hour=12)
        mocked_localtime.return_value = new_period
        send_proactive_refinancing_reminder(self.loan_ref_req, 'robocall', 2)
        assert mocked_task.delay.called

    @patch('juloserver.loan_refinancing.services.comms_channels.send_proactive_email_reminder')
    def test_send_proactive_sms(self, mocked_task):
        send_proactive_refinancing_reminder(self.loan_ref_req, 'email', 2)
        assert mocked_task.delay.called

    def test_send_loan_refinancing_request_offer_selected_notification(self):
        self.loan_ref_req.comms_channel_1 = CovidRefinancingConst.COMMS_CHANNELS.email
        self.loan_ref_req.save()
        send_loan_refinancing_request_offer_selected_notification(self.loan_ref_req)

    @patch('juloserver.loan_refinancing.services.comms_channels.'
           'send_robocall_refinancing_reminder_minus_3')
    @patch('juloserver.loan_refinancing.services.comms_channels.timezone.localtime')
    def test_send_loan_refinancing_robocall_reminder_minus_3(self, mocked_localtime, mocked_task):
        today = timezone.now()
        new_period = today.replace(hour=10)
        mocked_localtime.return_value = new_period
        send_loan_refinancing_robocall_reminder_minus_3(self.loan_ref_req)

        new_period = today.replace(hour=12)
        mocked_localtime.return_value = new_period
        send_loan_refinancing_robocall_reminder_minus_3(self.loan_ref_req)
        assert mocked_task.delay.called

    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_email_refinancing_offer_selected_minus_1')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_sms_covid_refinancing_reminder_offer_selected_1')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_pn_covid_refinancing_reminder_offer_selected_1')
    def test_send_loan_refinancing_request_reminder_offer_selected_1(self,
                                                                     mocked_pn,
                                                                     mocked_sms,
                                                                     mocked_email):
        self.loan_ref_req.comms_channel_1 = CovidRefinancingConst.COMMS_CHANNELS.email
        self.loan_ref_req.comms_channel_2 = CovidRefinancingConst.COMMS_CHANNELS.sms
        self.loan_ref_req.comms_channel_3 = CovidRefinancingConst.COMMS_CHANNELS.pn
        self.loan_ref_req.save()
        send_loan_refinancing_request_reminder_offer_selected_1(self.loan_ref_req)
        assert mocked_pn.apply_async.called
        assert mocked_sms.apply_async.called
        assert mocked_email.delay.called

    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_email_refinancing_offer_selected_minus_2')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_sms_covid_refinancing_reminder_offer_selected_2')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_pn_covid_refinancing_reminder_offer_selected_2')
    def test_send_loan_refinancing_request_reminder_offer_selected_2(self,
                                                                     mocked_pn,
                                                                     mocked_sms,
                                                                     mocked_email):
        self.loan_ref_req.comms_channel_1 = CovidRefinancingConst.COMMS_CHANNELS.email
        self.loan_ref_req.comms_channel_2 = CovidRefinancingConst.COMMS_CHANNELS.sms
        self.loan_ref_req.comms_channel_3 = CovidRefinancingConst.COMMS_CHANNELS.pn
        self.loan_ref_req.save()
        send_loan_refinancing_request_reminder_offer_selected_2(self.loan_ref_req)
        assert mocked_pn.apply_async.called
        assert mocked_sms.apply_async.called
        assert mocked_email.delay.called

    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_email_covid_refinancing_activated')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_pn_covid_refinancing_activated')
    def test_send_loan_refinancing_request_activated_notification_reactive(self,
                                                                           mocked_pn,
                                                                           mocked_email):
        self.loan_ref_req.channel = CovidRefinancingConst.CHANNELS.reactive
        self.loan_ref_req.comms_channel_1 = CovidRefinancingConst.COMMS_CHANNELS.email
        self.loan_ref_req.comms_channel_3 = CovidRefinancingConst.COMMS_CHANNELS.pn
        self.loan_ref_req.save()
        send_loan_refinancing_request_activated_notification(self.loan_ref_req)
        assert mocked_pn.apply_async.called
        assert mocked_email.apply_async.called

    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_email_covid_refinancing_activated')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_pn_covid_refinancing_activated')
    def test_send_loan_refinancing_request_activated_notification_proactive(self,
                                                                           mocked_pn,
                                                                           mocked_email):
        self.loan_ref_req.channel = CovidRefinancingConst.CHANNELS.proactive
        self.loan_ref_req.save()
        send_loan_refinancing_request_activated_notification(self.loan_ref_req)
        assert mocked_pn.apply_async.called
        assert mocked_email.apply_async.called

    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_email_covid_refinancing_approved')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_pn_covid_refinancing_approved')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_sms_covid_refinancing_approved')
    def test_send_loan_refinancing_request_approved_notification_reactive(self,
                                                                          mocked_sms,
                                                                          mocked_pn,
                                                                          mocked_email):
        self.loan_ref_req.channel = CovidRefinancingConst.CHANNELS.reactive
        self.loan_ref_req.comms_channel_1 = CovidRefinancingConst.COMMS_CHANNELS.email
        self.loan_ref_req.comms_channel_3 = CovidRefinancingConst.COMMS_CHANNELS.pn
        self.loan_ref_req.comms_channel_2 = CovidRefinancingConst.COMMS_CHANNELS.sms
        self.loan_ref_req.save()
        send_loan_refinancing_request_approved_notification(self.loan_ref_req)
        assert mocked_pn.delay.called
        assert mocked_email.delay.called
        assert mocked_sms.delay.called

    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_email_covid_refinancing_approved')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_pn_covid_refinancing_approved')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_sms_covid_refinancing_approved')
    def test_send_loan_refinancing_request_approved_notification_proactive(self,
                                                                           mocked_sms,
                                                                           mocked_pn,
                                                                           mocked_email):
        self.loan_ref_req.channel = CovidRefinancingConst.CHANNELS.proactive
        self.loan_ref_req.save()
        send_loan_refinancing_request_approved_notification(self.loan_ref_req)
        assert mocked_pn.delay.called
        assert mocked_email.delay.called
        assert mocked_sms.delay.called

    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_email_requested_status_campaign_reminder_to_pay_minus_2')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_pn_requested_status_campaign_reminder_to_pay_minus_2')
    def test_send_loan_refinancing_requested_status_campaign_reminder_minus_2(
            self, mock_send_pn, mock_send_email):
        self.loan_ref_req.status = 'Requested'
        self.loan_ref_req.save()
        send_loan_refinancing_requested_status_campaign_reminder_minus_2(self.loan_ref_req)
        mock_send_pn.apply_async.assert_called_once_with((self.loan_ref_req.id,), countdown=3600)
        mock_send_email.delay.assert_called_once_with(self.loan_ref_req.id)

    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_email_requested_status_campaign_reminder_to_pay_minus_1')
    @patch(
        'juloserver.loan_refinancing.services.comms_channels.'
        'send_pn_requested_status_campaign_reminder_to_pay_minus_1')
    def test_send_loan_refinancing_requested_status_campaign_reminder_minus_1(
            self, mock_send_pn, mock_send_email):
        self.loan_ref_req.status = 'Requested'
        self.loan_ref_req.save()
        send_loan_refinancing_requested_status_campaign_reminder_minus_1(self.loan_ref_req)
        mock_send_pn.apply_async.assert_called_once_with((self.loan_ref_req.id,), countdown=3600)
        mock_send_email.delay.assert_called_once_with(self.loan_ref_req.id)
