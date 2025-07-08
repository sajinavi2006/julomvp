from django.conf import settings
from django.test.testcases import TestCase
from rest_framework.test import APIClient

from juloserver.digisign.constants import DocumentType, SigningStatus
from juloserver.digisign.tests.factories import DigisignDocumentFactory
from juloserver.followthemoney.constants import LoanAgreementType
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    StatusLookupFactory,
    ProductLineFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
)


class TestLoanAgreementDetailViewV3(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.product_line = ProductLineFactory()
        self.product_line.product_line_code = 1
        self.product_line.save()
        self.product_line.refresh_from_db()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.status_lookup = StatusLookupFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            cycle_day=1,
        )
        self.application = ApplicationFactory(
            customer=self.customer, product_line=self.product_line, email='test_email@gmail.com',
            account=self.account
        )
        self.loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            application=None,
            loan_xid=1000023456,
        )


    def test_loan_agreement_case_not_digisign(self):
        res = self.client.get('/api/loan/v4/agreement/loan/{}/'.format(self.loan.loan_xid))
        json_response = res.json()
        self.assertEqual(res.status_code, 200)

        # result
        default_img = '{}{}'.format(
            settings.STATIC_ALICLOUD_BUCKET_URL,
            'loan_agreement/default_document_logo.png'
        )
        expected_result = {
            "title": "Lihat Dokumen SKRTP dan RIPLAY",
            "types": [
                {
                    "type": LoanAgreementType.TYPE_RIPLAY,
                    "displayed_title": LoanAgreementType.TYPE_RIPLAY.upper(),
                    "text": LoanAgreementType.TEXT_RIPLAY,
                    "image": default_img,
                },
                {
                    "type": LoanAgreementType.TYPE_SKRTP,
                    "displayed_title": LoanAgreementType.TYPE_SKRTP.upper(),
                    "text": LoanAgreementType.TEXT_SKRTP,
                    "image": default_img,
                },
            ],
        }
        self.assertEqual(
            json_response['data']['loan_agreement'],
            expected_result,
        )

    def test_loan_agreement_case_digisign(self):
        DigisignDocumentFactory(
            document_type=DocumentType.LOAN_AGREEMENT_BORROWER,
            document_source=self.loan.id,
            signing_status=SigningStatus.COMPLETED
        )
        res = self.client.get('/api/loan/v4/agreement/loan/{}/'.format(self.loan.loan_xid))
        json_response = res.json()
        self.assertEqual(res.status_code, 200)

        # result
        default_img = '{}{}'.format(
            settings.STATIC_ALICLOUD_BUCKET_URL,
            'loan_agreement/default_document_logo.png'
        )
        expected_result = {
            "title": "Lihat Dokumen SKRTP dan RIPLAY",
            "types": [
                {
                    "type": LoanAgreementType.TYPE_RIPLAY,
                    "displayed_title": LoanAgreementType.TYPE_RIPLAY.upper(),
                    "text": LoanAgreementType.TEXT_RIPLAY,
                    "image": default_img,
                },
                {
                    "type": LoanAgreementType.TYPE_DIGISIGN_SKRTP,
                    "displayed_title": LoanAgreementType.TYPE_SKRTP.upper(),
                    "text": LoanAgreementType.TEXT_SKRTP,
                    "image": default_img,
                },
            ],
        }
        self.assertEqual(
            json_response['data']['loan_agreement'],
            expected_result,
        )


class TestLoanDetailsAndTemplateDocumentType(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.product_line = ProductLineFactory()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.application = ApplicationFactory(
            customer=self.customer, product_line=self.product_line, email='test_email@gmail.com',
            account=self.account
        )
        self.loan = LoanFactory(
            customer=self.customer,
            account=self.account,
        )
        self.loan.loan_xid = 1000023456
        self.loan.save()
        DigisignDocumentFactory(
            document_type=DocumentType.LOAN_AGREEMENT_BORROWER,
            document_source=self.loan.id,
            signing_status=SigningStatus.COMPLETED
        )

    def test_loan_content_with_document_type(self):
        response = self.client.get(
            '/api/loan/v4/agreement/content/1000023456?document_type={}'.format(
                LoanAgreementType.DIGISIGN_SKRTP
            )
        )
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data['data']['data_extension'], 'pdf')
