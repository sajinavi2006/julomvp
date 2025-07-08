from builtins import str
from mock import patch, ANY

from juloserver.followthemoney.constants import LoanAgreementType
from juloserver.followthemoney.models import LoanAgreementTemplate
from rest_framework.test import APITestCase
from rest_framework.reverse import reverse
from rest_framework import status
from juloserver.julo.tests.factories import PartnerFactory, AuthUserFactory, DocumentFactory, \
    CustomerFactory, \
    ProductLineFactory, ApplicationFactory, OfferFactory, StatusLookupFactory, ProductLookupFactory, \
    LoanFactory, \
    PaymentFactory, FeatureSettingFactory, WorkflowFactory
from ..factories import LenderCurrentFactory, LenderBucketFactory, LoanAgreementTemplateFactory, \
    ApplicationHistoryFactory
from juloserver.account.tests.factories import AccountFactory, AccountLookupFactory
from juloserver.core.utils import JuloFakerProvider
from juloserver.julo.constants import WorkflowConst
from factory import LazyAttribute
from faker import Faker

fake = Faker()
fake.add_provider(JuloFakerProvider)


class TestLenderLoan(APITestCase):

    def create_user(self):
        user = AuthUserFactory(username='test')
        self.client.force_authenticate(user)
        partner = PartnerFactory(user=user)
        return user, partner

    def test_loan_agreement_view(self):
        data = dict(application_xid=123456789)
        url = reverse('loan_agreement')
        user, partner = self.create_user()
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        customer = CustomerFactory(user=user)
        product_line = ProductLineFactory(product_line_code=12345)
        application = ApplicationFactory(customer=customer, partner=partner, product_line=product_line,
                                         application_xid=123456789)
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        DocumentFactory(application_xid=123456789)
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_lender_approval_view(self):
        url = reverse('lender_approvel')
        user, partner = self.create_user()
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def disbursement_and_cancel(self, url):
        user, partner = self.create_user()
        data = dict(bucket=4)
        lender_bucket = LenderBucketFactory(partner=partner)
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data['bucket'] = lender_bucket.id
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_disbursement_view(self):
        url = reverse('followthemoney_disbursement')
        self.disbursement_and_cancel(url)

    def test_cancel_view(self):
        url = reverse('followthemoney_cancel')
        self.disbursement_and_cancel(url)

    def test_loan_agreement(self):
        url = reverse('followthemoney_agreement')
        user, partner = self.create_user()
        customer = CustomerFactory(user=user)
        product_line = ProductLineFactory(product_line_code=12345)
        application = ApplicationFactory(customer=customer, partner=partner, product_line=product_line)
        data = dict(application_xid=application.application_xid)
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        DocumentFactory()
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_history(self):
        user, partner = self.create_user()
        response = self.client.get(
            '/api/followthemoney/v1/history/?limit=1&last_lender_transaction_id1')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        LenderCurrentFactory(user=user)
        response = self.client.get(
            '/api/followthemoney/v1/history/?limit=1&last_lender_transaction_id1')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_loan_detail(self):
        user, partner = self.create_user()
        response = self.client.get('/api/followthemoney/v1/loan_detail/?limit=1')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        lender = LenderCurrentFactory(user=user)
        response = self.client.get(
            '/api/followthemoney/v1/loan_detail/?limit=1')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        product_line = ProductLineFactory(product_line_code=12345)
        product_look_up = ProductLookupFactory(product_line=product_line)
        LoanFactory(lender=lender, product=product_look_up)
        response = self.client.get('/api/followthemoney/v1/loan_detail/?limit=1')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']['items']), 1)

        # filter by product_line_code
        response = self.client.get(
            '/api/followthemoney/v1/loan_detail/'
            '?product_line_code={}'.format(product_line.product_line_code)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']['items']), 1)
        response = self.client.get('/api/followthemoney/v1/loan_detail/?product_line_code=1')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['msg'], 'Lender tidak memiliki pinjaman')

        # disable hide_partner_loan fs
        fs = FeatureSettingFactory(
            feature_name='hide_partner_loan',
            category='followthemoney',
            is_active=False,
            parameters={
                'hidden_product_line_codes': [999]
            }
        )
        response = self.client.get('/api/followthemoney/v1/loan_detail/?limit=1')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']['items']), 1)

        # enable hide_partner_loan fs but hidden_product_line_codes does not contain 12345
        fs.is_active = True
        fs.save()
        response = self.client.get('/api/followthemoney/v1/loan_detail/?limit=1')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']['items']), 1)

        # enable hide_partner_loan fs and hidden_product_line_codes contain 12345
        fs.parameters = {'hidden_product_line_codes': [999, product_line.product_line_code]}
        fs.save()
        response = self.client.get('/api/followthemoney/v1/loan_detail/?limit=1')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['msg'], 'Lender tidak memiliki pinjaman')

    @patch('juloserver.followthemoney.views.j1_views.get_loan_level_details')
    def test_loan_detail_with_limit_parameter(self, mock_get_loan_details):
        # setup
        user, _ = self.create_user()
        lender = LenderCurrentFactory(user=user)
        product_line = ProductLineFactory(product_line_code=12345)
        product_look_up = ProductLookupFactory(product_line=product_line)
        LoanFactory(lender=lender, product=product_look_up)

        # happy limit
        limit = 10
        response = self.client.get('/api/followthemoney/v1/loan_detail/?limit={}'.format(limit))
        mock_get_loan_details.assert_called_once_with(
            lender.id,
            ANY,
            limit,
            ANY,
            ANY,
        )
        mock_get_loan_details.reset_mock()

        # special cases
        expected_limit = 25
        limits = [
            '',
            None,
            0,
            '0',
            -1,
            1_000_000,
        ]
        for limit in limits:
            response = self.client.get('/api/followthemoney/v1/loan_detail/?limit={}'.format(limit))
            mock_get_loan_details.assert_called_once_with(
                lender.id,
                ANY,
                expected_limit,
                ANY,
                ANY,
            )
            mock_get_loan_details.reset_mock()

    def test_list_loan_detail_grab(self):
        user, partner = self.create_user()
        response = self.client.get('/api/followthemoney/v1/loan_detail/?limit=1')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        lender = LenderCurrentFactory(user=user, lender_name='ska2')
        response = self.client.get(
            '/api/followthemoney/v1/loan_detail/?limit=1')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        workflow_grab = WorkflowFactory(name=WorkflowConst.GRAB)
        account_lookup_grab = AccountLookupFactory(workflow=workflow_grab)
        customer_grab = CustomerFactory()
        account_grab = AccountFactory(
            customer=customer_grab,
            account_lookup=account_lookup_grab
        )
        # self.account_payment = AccountPaymentFactory(account=self.account)
        # self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        application_grab = ApplicationFactory(
            customer=customer_grab,
            partner=partner,
            account=account_grab,
            workflow=workflow_grab,
            application_xid=LazyAttribute(lambda o: fake.random_int(
                10000000, 20000000))
        )
        product_line = ProductLineFactory(product_line_code=12345)
        product_look_up = ProductLookupFactory(product_line=product_line)
        LoanFactory(lender=lender, product=product_look_up, customer=customer_grab,
                    application=application_grab, partner=partner)
        response = self.client.get('/api/followthemoney/v1/loan_detail/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']['items']), 1)

    def test_loan_lender_agreement(self):
        url = '/api/followthemoney/v1/lla_docs/123456789'
        user, partner = self.create_user()
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        product_line = ProductLineFactory(product_line_code=12345)
        product_look_up = ProductLookupFactory(product_line=product_line)
        customer = CustomerFactory(user=user)
        application = ApplicationFactory(customer=customer, partner=partner, product_line=product_line,
                                         application_xid=123456789)
        offer = OfferFactory(application=application, product=product_look_up)
        payment_status = StatusLookupFactory(status_code=2)
        lender = LenderCurrentFactory(user=user)
        loan = LoanFactory(customer=customer, application=application, offer=offer, loan_status=payment_status,
                           product=product_look_up, lender=lender)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # LoanAgreementTemplateFactory(lender=lender)
        # ApplicationHistoryFactory(application=application)
        # PaymentFactory(loan=loan, payment_status=payment_status)
        # response = self.client.get(url)
        # self.assertEqual(response.status_code, status.HTTP_200_OK)
