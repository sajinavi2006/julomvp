from mock import MagicMock, patch
from django.test.testcases import TestCase
from django.utils import timezone
from juloserver.loan_refinancing.tests.factories import (
    LoanRefinancingRequestFactory,
    WaiverRequestFactory,
)
from juloserver.cohort_campaign_automation.services.notification_related import (
    CohortCampaignAutomationEmail,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import (
    CustomerFactory,
    ApplicationFactory,
    PaymentMethodFactory,
)
from juloserver.loan.tests.factories import LoanFactory
from juloserver.cohort_campaign_automation.tests.factories import (
    CollectionCohortCampaignAutomationFactory,
    CollectionCohortCampaignEmailTemplateFactory,
)
from babel.dates import format_date


class TestSendEmail(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.loan = LoanFactory(account=self.account, customer=self.customer)
        self.loan_ref_req = LoanRefinancingRequestFactory(
            account=self.account,
            loan=self.loan,
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.virtual_account_postfix = '123456789'
        self.company_code = '10994'
        self.virtual_account = '{}{}'.format(self.company_code, self.virtual_account_postfix)
        self.payment_method = PaymentMethodFactory(
            customer=self.customer, virtual_account=self.virtual_account, loan=self.loan
        )
        self.waiver_request = WaiverRequestFactory(loan_refinancing_request=self.loan_ref_req)
        self.campaign_automation = CollectionCohortCampaignAutomationFactory(
            campaign_name='campaign_automation_test_2'
        )
        self.email_campaign = CollectionCohortCampaignEmailTemplateFactory(
            campaign_automation=self.campaign_automation,
            email_blast_date=timezone.localtime(timezone.now()),
            banner_url='http://localhost:8000/cohort-campaign-automation/create/',
            content_top='<p>Test</p>',
            content_middle='<p>Test middle</p>',
            content_footer='<p>Julo</p>',
        )
        self.campaign_automation_email = CohortCampaignAutomationEmail(
            loan_refinancing=self.loan_ref_req,
            campaign_email=self.email_campaign,
            template_raw_email='<html>test</html>',
            expiry_at=self.campaign_automation.end_date,
            api_key='api_key_test',
        )
        self.context = {
            'fullname_with_title': self.application.fullname_with_title,
            'total_payments': 'Rp 9.000.000',
            'prerequisite_amount': 'Rp 900.000',
            'va_number': self.payment_method.virtual_account,
            'bank_name': self.payment_method.payment_method_name,
            'banner_src': self.email_campaign.banner_url,
            'body_top_email': self.email_campaign.content_top,
            'body_mid_email': self.email_campaign.content_middle,
            'body_footer_email': self.email_campaign.content_footer,
            'expiry_at': format_date(
                self.campaign_automation.end_date, 'd MMMM yyyy', locale='id_ID'
            ),
        }

    @patch('juloserver.loan_refinancing.models.WaiverRequest.objects')
    def test_send_email(self, waiver_mock):
        self.waiver_request.outstanding_amount = 9000000
        waiver_mock.filter.return_value.last.return_value = self.waiver_request
        self.loan_ref_req.prerequisite_amount = 900000
        self.loan_ref_req.save()
        self.campaign_automation_email._email_client = MagicMock()
        self.campaign_automation_email._create_email_history = MagicMock()
        self.campaign_automation_email.send_email()
        self.campaign_automation_email._email_client.send_email_cohort_campaign_automation.assert_called_once_with(
            subject=self.campaign_automation_email._subject,
            email_to=self.campaign_automation_email._customer.email,
            template_raw=self.campaign_automation_email._template_raw_email,
            context=self.context,
            email_domain=self.campaign_automation_email._email_domain,
            api_key=self.campaign_automation_email._api_key,
        )
