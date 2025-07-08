from django.test import TestCase
from django.test import Client

from juloserver.account.tests.factories import AccountFactory
from juloserver.customer_module.tests.factories import BankAccountDestinationFactory
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (
    LoanFactory,
    CustomerFactory,
    ApplicationFactory,
    StatusLookupFactory,
    ProductLineFactory,
    BankFactory,
    GroupFactory,
)
from juloserver.julo.models import ProductLineCodes
from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.payment_point.constants import TransactionMethodCode


class TestLoanStatusDetailTestCase(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.user.groups.add(GroupFactory(name='bo_data_verifier'))

        self.client = Client()
        self.client.force_login(self.user)

        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)

        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.name_bank_validation = NameBankValidationFactory(
            validated_name='Test validated name'
        )
        self.bank = BankFactory(bank_name_frontend='Test bank display name')
        self.bank_account_destination = BankAccountDestinationFactory(
            customer=self.customer,
            name_bank_validation=self.name_bank_validation,
            account_number='1234567890',
            bank=self.bank,
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            application=self.application,
            bank_account_destination=self.bank_account_destination,
        )

    def test_show_bank_account_info_education_loan(self):
        # NOT SHOW BECAUSE LOAN IS NOT FOR EDUCATION
        response = self.client.get('/loan_status/details/{}'.format(self.loan.id))
        self.assertEqual(response.status_code, 200)
        response_content = response.content.decode()
        self.assertNotIn('Pemilik Rekening Tujuan', response_content)
        self.assertNotIn('Nomor Rekening Tujuan', response_content)
        self.assertNotIn('Bank Tujuan', response_content)

        # SHOW BECAUSE LOAN IS FOR EDUCATION
        self.loan.transaction_method_id = TransactionMethodCode.EDUCATION.code
        self.loan.save()
        response = self.client.get('/loan_status/details/{}'.format(self.loan.id))
        self.assertEqual(response.status_code, 200)
        response_content = response.content.decode()
        self.assertIn('Pemilik Rekening Tujuan', response_content)
        self.assertIn(
            '<strong>{}</strong>'.format(self.name_bank_validation.validated_name),
            response_content
        )
        self.assertIn('Nomor Rekening Tujuan', response_content)
        self.assertIn(
            '<strong>{}</strong>'.format(self.bank_account_destination.account_number),
            response_content
        )
        self.assertIn('Bank Tujuan', response_content)
        self.assertIn(
            '<strong>{}</strong>'.format(self.bank.bank_name_frontend),
            response_content
        )
