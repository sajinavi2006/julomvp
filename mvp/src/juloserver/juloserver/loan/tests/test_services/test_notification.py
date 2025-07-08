
import mock
from mock import patch
from datetime import datetime, timedelta
from django.utils import timezone

from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    LoanFactory,
    ProductLineFactory,
    StatusLookupFactory,
)

from django.test.testcases import TestCase

from juloserver.account.constants import AccountConstant
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.product_lines import ProductLineCodes

from juloserver.loan.services.notification import *

class TestLoanNotification(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.suspended),
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
        )


    @patch('juloserver.loan.services.notification.get_julo_email_client')
    @patch('juloserver.account_payment.services.'
            'earning_cashback.get_cashback_experiment')
    def test_send_sphp_email(self, mock_cashback_experiment, mocked_email_client):
        mocked_email_client.return_value.email_sphp.return_value = [
            202, {'X-Message-Id': 'email_notify_loan_sphp'},
            'dummy_subject', 'dummy_message', 'dummy_template']
        mock_cashback_experiment.retrun_value = True

        LoanEmail(self.loan).send_sphp_email()


    @patch('juloserver.account_payment.services.earning_cashback.get_cashback_experiment')
    @patch('juloserver.loan.services.notification.get_julo_email_client')
    def test_send_sphp_email_cashback_template(self, mocked_email_client, mock_get_cashback_experiment):
        mocked_email_client.return_value.email_sphp.return_value = [
            202, {'X-Message-Id': 'email_notify_loan_sphp'},
            'dummy_subject', 'dummy_message', 'dummy_template']
        mock_get_cashback_experiment.return_value = True

        LoanEmail(self.loan).send_sphp_email()
        self.assertTemplateUsed(template_name="sphp_email_with_cashback.html")
