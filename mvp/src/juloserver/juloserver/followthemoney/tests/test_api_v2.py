from __future__ import print_function

import random

from django.conf import settings
from mock import patch, MagicMock
import mock
from rest_framework.test import APIClient, APITestCase


from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    DocumentFactory,
    LoanFactory,
    WorkflowFactory,
    ProductLookupFactory,
    PartnerFactory,
    StatusLookupFactory,
    ProductLineCodes,
    ProductLineFactory
)
from juloserver.followthemoney.factories import (
    LenderBucketFactory,
    LoanAgreementTemplateFactory,
    LenderCurrentFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory
)
from juloserver.standardized_api_response.utils import success_response


class TestCustomerSphpAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.account = AccountFactory()
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account)
        self.document = DocumentFactory()
        self.loan = LoanFactory(application=self.application, account=self.account)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestCustomerSphpAPIv2_application_not_found(self):
        self.application.application_xid = 123123
        self.application.save()

        self.loan.loan_xid = 1111111
        self.loan.loan_status_id = 220
        self.loan.save()

        response = self.client.get('/api/v2/customer/sphp/123123123/')
        assert response.status_code == 400
        assert response.json()['error_message'] == 'Loan Not Found'


    @patch('juloserver.followthemoney.views.application_v2_views.get_file_from_oss')
    def test_TestCustomerSphpAPIv2_success_application_xid(self, mock_get_file_from_oss):
        self.application.application_xid = 123123123
        self.application.save()

        self.document.document_source = self.application.id
        self.document.document_type = 'skrtp_julo'
        self.document.save()

        self.loan.loan_xid = 12312312322
        self.loan.loan_status_id = 220
        self.loan.save()

        mock_get_file_from_oss.return_value = ['success']

        response = self.client.get('/api/v2/customer/sphp/123123123/')
        assert response.status_code == 200

    @mock.patch('juloserver.loan.services.agreement_related.get_loan_agreement_template_julo_one')
    @mock.patch('juloserver.followthemoney.views.application_v2_views.get_file_from_oss')
    def test_TestCustomerSphpAPIv2_success_loan_xid(self, mock_get_file_from_oss, mock_get_loan_agreement_template_julo_one):
        self.application.application_xid = 123123123
        self.application.save()

        self.loan.loan_xid = 12312312322
        self.loan.customer = self.customer
        self.loan.loan_status_id = 220
        self.loan.save()

        self.document.document_source = self.loan.id
        self.document.loan_xid = self.loan.loan_xid
        self.document.document_type = 'skrtp_julo'
        self.document.filename = "test.pdf"
        self.document.save()

        mock_get_file_from_oss.return_value = ['success']
        mock_get_loan_agreement_template_julo_one.return_value = ('test', 'skrtp')

        response = self.client.get('/api/v2/customer/sphp/12312312322/')
        assert response.status_code == 200

    @mock.patch('juloserver.followthemoney.views.application_v2_views.get_file_from_oss')
    def test_TestCustomerSphpAPIv2_success_loan_xid_grab_document_exist(self, mock_get_file_from_oss):
        customer = CustomerFactory()

        workflow = WorkflowFactory(name='GrabWorkflow')
        account_lookup = AccountLookupFactory(
            workflow=workflow,
            name='GRAB'
        )
        account = AccountFactory(
            account_lookup=account_lookup,
            customer=customer
        )

        product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB)
        product_lookup = ProductLookupFactory(
            product_line=product_line, admin_fee=40000)
        application_status_code = StatusLookupFactory(code=190)
        application = ApplicationFactory(
            customer=customer,
            account=account,
            product_line=product_line,
            application_status=application_status_code,
            bank_name='bank_test',
            name_in_bank='name_in_bank',
            workflow=workflow
        )
        loan = LoanFactory(
            account=account,
            customer=customer,
            product=product_lookup,
            loan_xid=random.randint(3000000000, 3100000000)
        )
        loan.loan_status_id = 220
        document = DocumentFactory()
        document.document_source = loan.id
        document.document_type = 'sphp_grab'
        document.loan_xid = loan.loan_xid
        document.url = "test_document_url"
        document.filename = "document_filename"
        document.save()

        mock_get_file_from_oss.return_value = ['success']

        response = self.client.get('/api/v2/customer/sphp/{}/'.format(loan.loan_xid))
        assert response.status_code == 200


class TestLenderSphpAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.lender_bucket = LenderBucketFactory()
        self.document = DocumentFactory()
        self.loan = LoanFactory(lender=LenderCurrentFactory())
        self.loan_agreement_template = LoanAgreementTemplateFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestLenderSphpAPIv2_lender_bucket_not_found(self):
        self.application.application_xid = 123123123
        self.application.save()

        response = self.client.get('/api/v2/lender/sphp/123123123/')
        assert response.status_code == 400
        assert response.json()['error_message'] == 'lenderbucket Not Found'

    @mock.patch('juloserver.followthemoney.views.application_v2_views.get_file_from_oss')
    @mock.patch('juloserver.followthemoney.views.application_v2_views.get_summary_loan_agreement_template')
    def test_TestLenderSphpAPIv2_success_from_document(self, mock_get_summary_loan_agreement_template, mock_get_file_from_oss):
        self.application.application_xid = 123123123
        self.application.save()

        self.loan.application = self.application
        self.loan.save()

        self.lender_bucket.application_ids = {'approved': [self.application.id]}
        self.lender_bucket.save()

        self.document.document_source = self.lender_bucket.id
        self.document.document_type = 'summary_lender_sphp'
        self.document.save()

        mock_get_summary_loan_agreement_template.return_value = "<html></htlm>"
        mock_get_file_from_oss.return_value = ["success"]

        response = self.client.get('/api/v2/lender/sphp/123123123/')
        assert response.status_code == 200


class TestLenderSphpAgreementAPIv2(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.document = DocumentFactory()
        self.lender = LenderCurrentFactory()
        self.loan = LoanFactory(lender=self.lender)
        self.loan_agreement_template = LoanAgreementTemplateFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_TestLenderSphpAgrementAPIv2_loan_id_null(self):
        data = {
            'approved_loan_ids[]': [],
        }
        response = self.client.get('/api/v2/lender/preview-agreement/', data)
        assert response.status_code == 400

    def test_TestLenderSphpAgrementAPIv2_user_is_not_lender(self):
        data = {
            'approved_loan_ids[]': [9999999],
        }
        response = self.client.get('/api/v2/lender/preview-agreement/', data)
        assert response.status_code == 400
        assert response.json()['error_message'] == 'User is not a Lender'

    def test_TestLenderSphpAgrementAPIv2_loan_id_not_found(self):
        data = {
            'approved_loan_ids[]': [9999999],
        }
        self.lender.user = self.user
        self.lender.save()
        response = self.client.get('/api/v2/lender/preview-agreement/', data)
        assert response.status_code == 400
        assert response.json()['error_message'] == "Loan {} not found or belong to another lender".format({9999999})


    def test_TestLenderSphpAgrementAPIv2_loan_id_different_lender(self):
        data = {
            'approved_loan_ids[]': [self.loan.id],
        }
        self.lender.user = self.user
        self.lender.save()
        self.loan.lender = LenderCurrentFactory(id=123123)
        self.loan.save()
        response = self.client.get('/api/v2/lender/preview-agreement/', data)
        assert response.status_code == 400
        assert response.json()['error_message'] == 'Loan {} not found or belong to another lender'.format({self.loan.id})

    def test_TestLenderSphpAgrementAPIv2_success_from_document(self):
        data = {
            'approved_loan_ids[]': [self.loan.id],
        }
        self.lender.user = self.user
        self.lender.save()
        response = self.client.get('/api/v2/lender/preview-agreement/', data)
        assert response.status_code == 200
