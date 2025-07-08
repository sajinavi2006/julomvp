import mock
from django.test import TestCase
from django.test import TestCase
from django.utils import timezone
from mock import patch

from juloserver.julo.clients import get_julo_pn_client, get_julo_sms_client, get_julo_email_client
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import ProductLine
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import ApplicationFactory, LoanFactory, PaymentMethodFactory
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.loan_refinancing.models import LoanRefinancingMainReason, LoanRefinancingSubReason
from juloserver.loan_refinancing.tests.factories import LoanRefinancingRequestFactory, \
    CollectionOfferExtensionConfigurationFactory, LoanRefinancingFactory
from juloserver.streamlined_communication.constant import PageType


class TestClients(TestCase):
    def setUp(self):
        mtl_product = ProductLine.objects.get(pk=ProductLineCodes.MTL1)
        application = ApplicationFactory(product_line=mtl_product)
        self.customer = application.customer
        loan = LoanFactory(application=application, customer=self.customer)
        PaymentMethodFactory(customer=application.customer, is_primary=True, loan=loan)

        self.loan_ref_req = LoanRefinancingRequestFactory(
            product_type="R1",
            loan=loan,
            expire_in_days=5,
            prerequisite_amount=50000
        )

        self.procative_loan_ref_req = LoanRefinancingRequestFactory(
            product_type="R1",
            loan=loan,
            expire_in_days=5
        )

        self.loan_ref = LoanRefinancingFactory(
            loan=self.loan_ref_req.loan,
            refinancing_request_date=timezone.now().date(),
            refinancing_active_date=timezone.now().date(),
            loan_refinancing_main_reason=LoanRefinancingMainReason.objects.last(),
            loan_refinancing_sub_reason=LoanRefinancingSubReason.objects.last(),
            tenure_extension=9
        )

        self.coll_ext_conf = CollectionOfferExtensionConfigurationFactory(
            product_type='R4',
            remaining_payment=2,
            max_extension=3,
            date_start=timezone.localtime(timezone.now()).date(),
            date_end=timezone.localtime(timezone.now()).date(),
        )

    def test_loan_refinancing_notification(self):
        pn_cl = get_julo_pn_client()
        data = {'dummy_key': 'dummy_value'}
        with patch.object(pn_cl, 'send_downstream_message') as mocked_send_pn:
            pn_cl.loan_refinancing_notification(self.loan_ref_req,
                                                data,
                                                'dummy_template')
            mocked_send_pn.assert_called_with(
                registration_ids=[None],
                data={'dummy_key': 'dummy_value',
                      'destination_page': PageType.HOME,
                      'click_action': 'com.julofinance.juloapp_HOME'},
                template_code='dummy_template')

    def test_loan_refinancing_sms(self):
        sms_cl = get_julo_sms_client()
        with patch.object(sms_cl, 'send_sms') as mocked_send_sms:
            mocked_send_sms.return_value = (
                'message',
                {'messages': [{'status': '0',
                               'message-id': '4351',
                               'julo_sms_vendor': 'monty',
                               'is_otp': False}]
                 })
            sms_cl.loan_refinancing_sms(
                self.loan_ref_req, 'message', 'dummy_template')
            mocked_send_sms.assert_called_once()

    def test_email_base(self):
        email_cl = get_julo_email_client()
        with patch.object(email_cl, 'send_email') as mocked_send_email:
            mocked_send_email.return_value = 'status', 'body', 'headers'
            email_cl.email_base(
                self.loan_ref_req,
                'subject',
                'covid_refinancing/covid_reactive_product_activated_email.html'
            )
            mocked_send_email.assert_called_once()

    def test_email_proactive_refinancing_reminder(self):
        email_cl = get_julo_email_client()
        with patch.object(email_cl, 'send_email') as mocked_send_email:
            mocked_send_email.return_value = 'status', 'body', 'headers'
            email_cl.email_proactive_refinancing_reminder(
                self.loan_ref_req, 'subject', 'emailsent_offer_first_email')
            mocked_send_email.assert_called_once()

    def test_email_refinancing_offer_selected(self):
        email_cl = get_julo_email_client()
        with patch.object(email_cl, 'send_email') as mocked_send_email:
            mocked_send_email.return_value = 'status', 'body', 'headers'
            email_cl.email_refinancing_offer_selected(
                self.loan_ref_req, 'subject', 'emailsent_offer_first_email')
            mocked_send_email.assert_called_once()

    def test_email_reminder_refinancing(self):
        email_cl = get_julo_email_client()
        with patch.object(email_cl, 'send_email') as mocked_send_email:
            mocked_send_email.return_value = 'status', 'body', 'headers'
            email_cl.email_reminder_refinancing(
                self.loan_ref_req, 'subject',
                'covid_refinancing/covid_reactive_product_activated_email.html',
                timezone.now().date()
            )
            mocked_send_email.assert_called_once()
