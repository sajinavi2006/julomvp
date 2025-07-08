from django.test.testcases import TestCase

from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.services.bank_account_related import (
    get_other_bank_account_destination,
    get_self_bank_account_destination,
    is_ecommerce_bank_account,
)
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory,
)
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.ecommerce.tests.factories import EcommerceConfigurationFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    BankFactory,
    CustomerFactory,
)


class TestBankAccountDestination(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.bank = BankFactory(
            bank_code='012', bank_name='BCA', xendit_bank_code='BCA', swift_bank_code='01'
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='Pribadi', parent_category_id=1
        )
        self.bank_account_healthcare = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.HEALTHCARE,
            display_label='Healthcare',
            parent_category_id=1,
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        BankAccountDestinationFactory(
            bank_account_category=self.bank_account_healthcare,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        self.ecommerce_configuration = EcommerceConfigurationFactory()

    def test_get_self_bank_account_destination(self):
        bank_account_destination = get_self_bank_account_destination(self.customer)
        self.assertIsNotNone(bank_account_destination)

    def test_get_other_bank_account_destination(self):
        other_category = BankAccountCategoryFactory(
            category='other', display_label='lainnya', parent_category_id=2
        )
        self.bank_account_destination.bank_account_category = other_category
        self.bank_account_destination.save()
        self.bank_account_destination.refresh_from_db()
        bank_account_destination = get_other_bank_account_destination(self.customer)
        self.assertIsNotNone(bank_account_destination)
        for bank in bank_account_destination:
            assert bank.bank_account_category.category != BankAccountCategoryConst.HEALTHCARE

    def test_check_ecommerce_bank_account(self):
        ecommerce_category = BankAccountCategoryFactory(
            category=BankAccountCategoryConst.ECOMMERCE,
            display_label='e-commerce',
            parent_category_id=3,
        )
        self.bank_account_destination.bank_account_category = ecommerce_category
        self.bank_account_destination.description = self.ecommerce_configuration.ecommerce_name
        self.bank_account_destination.save()
        result = is_ecommerce_bank_account(self.bank_account_destination)
        self.assertTrue(result)
        self.bank_account_destination.description = 'wrong description'
        self.bank_account_destination.save()
        result = is_ecommerce_bank_account(self.bank_account_destination)
        self.assertFalse(result)
