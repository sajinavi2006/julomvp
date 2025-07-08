from unittest.mock import patch
from django.test.testcases import TestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.email_delivery.services import (
    email_history_kwargs_for_account_payment,
    update_email,
    update_email_details,
)
from juloserver.email_delivery.utils import email_status_prioritization
from juloserver.julo.models import EmailHistory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    EmailHistoryFactory,
)


class TestUpdateEmailDetails(TestCase):
    @patch('juloserver.email_delivery.services.update_email')
    def test_update_email_details_with_bounce_event_code(self, mock_update_email):
        parsed_data = {
            'event_code': 'MOE_EMAIL_SOFT_BOUNCE',
            'event_source': 'MOENGAGE',
            'customer_id': '1004000000',
            'reason': '452 4.2.2 The email account that you tried to reach is over quota. Please direct the recipient to https://support.google.com/mail/?p=OverQuotaTemp az10-20020a05620a170a00b0076caee4b64esi3374683qkb.262 - gsmtp',
            'to_email': 'testing@gmail.com',
            'application_id': 2007000000,
            'payment_id': None,
            'account_payment_id': None,
            'account1_payment_id': None,
            'account2_payment_id': None,
            'account3_payment_id': None,
            'account4_payment_id': None,
            'account5_payment_id': None,
            'template_code': 'Testing Campaign',
            'campaign_id': '652f5c69c7cc537afb0d2854',
            'email_subject': 'Unit Testing Campaign Subject'
        }

        update_email_details(parsed_data, is_stream=True)
        mock_update_email.assert_called_once_with(
            parsed_data,
            'soft_bounce'
        )


class TestUpdateEmail(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory()
        self.email_history = EmailHistoryFactory(
            application=self.application,
            customer=self.customer,
            payment=None,
            template_code='Testing Campaign',
            to_email='testing@gmail.com',
            campaign_id='652f5c69c7cc537afb0d2854',
            status='processed',
        )
        self.parsed_data = {
            'event_code': 'MOE_EMAIL_SOFT_BOUNCE',
            'event_source': 'MOENGAGE',
            'customer_id': self.customer.id,
            'reason': '452 4.2.2 The email account that you tried to reach is over quota. Please direct the recipient to https://support.google.com/mail/?p=OverQuotaTemp az10-20020a05620a170a00b0076caee4b64esi3374683qkb.262 - gsmtp',
            'to_email': 'testing@gmail.com',
            'application_id': self.application.id,
            'payment_id': None,
            'account_payment_id': None,
            'account1_payment_id': None,
            'account2_payment_id': None,
            'account3_payment_id': None,
            'account4_payment_id': None,
            'account5_payment_id': None,
            'template_code': 'Testing Campaign',
            'campaign_id': '652f5c69c7cc537afb0d2854',
            'email_subject': 'Unit Testing Campaign Subject',
        }

    @patch('juloserver.email_delivery.services.logger')
    def test_update_email_with_status_soft_bounce(self, mock_logger):
        update_email(self.parsed_data, 'soft_bounce')
        mock_logger.info.assert_called_once_with({
            'action': 'update_email',
            'message': 'Recording bounce reason for bounced email by MoEngage.',
            'email_history': self.email_history.id,
            'reason': '452 4.2.2 The email account that you tried to reach is over quota. Please direct the recipient to https://support.google.com/mail/?p=OverQuotaTemp az10-20020a05620a170a00b0076caee4b64esi3374683qkb.262 - gsmtp'
        })

        self.email_history.refresh_from_db()
        self.assertEqual('soft_bounce', self.email_history.status)

    @patch('juloserver.email_delivery.services.logger')
    def test_update_email_soft_bounce_with_no_email_history(self, mock_logger):
        self.email_history.delete()

        update_email(self.parsed_data, 'soft_bounce')

        new_email_history = EmailHistory.objects.last()
        self.assertEqual(new_email_history.application.id, self.application.id)
        self.assertEqual(new_email_history.customer.id, self.customer.id)
        self.assertEqual(new_email_history.template_code, 'Testing Campaign')
        self.assertEqual(new_email_history.to_email, 'testing@gmail.com')
        self.assertEqual(new_email_history.campaign_id, '652f5c69c7cc537afb0d2854')
        self.assertEqual(new_email_history.status, 'soft_bounce')

        mock_logger.info.assert_called_once_with(
            {
                'action': 'update_email',
                'message': 'Recording bounce reason for bounced email by MoEngage.',
                'email_history': new_email_history.id,
                'reason': '452 4.2.2 The email account that you tried to reach is over quota. Please direct the recipient to https://support.google.com/mail/?p=OverQuotaTemp az10-20020a05620a170a00b0076caee4b64esi3374683qkb.262 - gsmtp',
            }
        )

    @patch('juloserver.email_delivery.services.logger')
    def test_update_email_with_lower_priority_status(self, mock_logger):
        '''
        The status should remain unchanged because the spam status is lower than soft_bounce.
        You can find further details regarding priority in the constants.py file
        located at src/juloserver/juloserver/email_delivery/.
        '''
        new_status = 'spam'
        old_status = 'soft_bounce'
        processed_status = email_status_prioritization(old_status, new_status)
        update_email(self.parsed_data, processed_status)

        self.email_history.refresh_from_db()
        self.assertEqual('soft_bounce', self.email_history.status)

        mock_logger.info.assert_called_once_with(
            {
                'action': 'update_email',
                'message': 'Recording bounce reason for bounced email by MoEngage.',
                'email_history': self.email_history.id,
                'reason': '452 4.2.2 The email account that you tried to reach is over quota. Please direct the recipient to https://support.google.com/mail/?p=OverQuotaTemp az10-20020a05620a170a00b0076caee4b64esi3374683qkb.262 - gsmtp',
            }
        )


class TestEmailHistoryKwargsForAccountPayment(TestCase):
    def test_email_history_kwargs_for_account_payment(self):
        application = ApplicationFactory()
        customer = application.customer
        customer.current_application_id = application.id
        customer.save()
        account = AccountFactory(customer=customer)
        account_payment = AccountPaymentFactory(account=account)
        ret_val = email_history_kwargs_for_account_payment(account_payment.id)

        self.assertEqual(ret_val['account_payment_id'], account_payment.id)
        self.assertEqual(ret_val['application_id'], application.id)
        self.assertEqual(ret_val['customer_id'], customer.id)
        self.assertEqual(ret_val['source'], 'inhouse')
