import uuid

import mock
from django.forms import model_to_dict
from django.test import TestCase
from juloserver.account.tests.factories import AccountFactory, AccountLookupFactory
from juloserver.dana.constants import (
    DANA_ACCOUNT_LOOKUP_NAME,
    DANA_BANK_NAME,
    DANA_ONBOARDING_FIELD_TO_TRACK,
)
from juloserver.dana.models import DanaCustomerData
from juloserver.dana.tasks import (
    update_dana_account_payment_status,
    update_dana_account_payment_status_subtask,
    create_dana_customer_field_change_history,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.account_payment.models import AccountPayment
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.dana.tests.factories import DanaCustomerDataFactory, DanaApplicationReferenceFactory
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
    PartnerFactory,
    WorkflowFactory,
    ProductLineFactory,
)
from juloserver.portal.object.product_profile.tests.test_product_profile_services import (
    ProductProfileFactory,
)


class TestAccountPaymentScheduledTasks(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.workflow = WorkflowFactory(name=WorkflowConst.DANA, handler='DanaWorkflowHandler')
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(customer=self.customer, account_lookup=self.account_lookup)
        self.partner = PartnerFactory(name=PartnerNameConstant.DANA, is_active=True)
        ApplicationFactory(customer=self.customer, account=self.account, partner=self.partner)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment.status_id = 320
        self.account_payment.save()

    @mock.patch('juloserver.account_payment.models.AccountPayment.objects.status_tobe_update')
    def test_update_dana_account_payment_status(self, mock_account_payments):
        account_payments = AccountPayment.objects.all()
        mock_account_payments.return_value = account_payments
        update_dana_account_payment_status()

    def test_update_dana_account_payment_status_subtask(self):
        update_dana_account_payment_status_subtask(self.account_payment.id)
        self.account_payment.status_id = 330
        self.account_payment.save()
        update_dana_account_payment_status_subtask(self.account_payment.id)


class TestAccountBindHistory(TestCase):
    def setUp(self) -> None:
        self.user_auth = AuthUserFactory()
        self.partner = PartnerFactory(name=PartnerNameConstant.DANA, is_active=True)
        self.workflow = WorkflowFactory(name=WorkflowConst.DANA)
        self.account_lookup = AccountLookupFactory(
            partner=self.partner, workflow=self.workflow, name=DANA_ACCOUNT_LOOKUP_NAME
        )

        product_line_code = ProductLineCodes.DANA
        self.product_line = ProductLineFactory(
            product_line_type=DANA_ACCOUNT_LOOKUP_NAME, product_line_code=product_line_code
        )
        self.product_profile = ProductProfileFactory(
            name=DANA_ACCOUNT_LOOKUP_NAME,
            code=product_line_code,
        )

        self.customer = CustomerFactory()
        self.account = AccountFactory()
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='9999999999999',
            name_in_bank=DANA_BANK_NAME,
            validation_status=NameBankValidationStatus.SUCCESS,
            mobile_phone='087790909090',
            method='xfers',
        )
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=self.product_line,
            name_bank_validation=self.name_bank_validation,
            partner=self.partner,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            account=self.account,
            customer=self.customer,
            partner=self.partner,
            application=self.application,
            dana_customer_identifier="12345679237",
            credit_score=750,
            lender_product_id='LP001',
        )

    def test_create_dana_account_bind_history(self):
        from juloserver.julo.models import CustomerFieldChange

        old_data = DanaCustomerData.objects.get(id=self.dana_customer_data.id)
        new_data = DanaCustomerData.objects.get(id=self.dana_customer_data.id)
        new_data.credit_score = 500
        new_data.save()

        create_dana_customer_field_change_history(
            old_data=model_to_dict(old_data, fields=DANA_ONBOARDING_FIELD_TO_TRACK),
            new_data=model_to_dict(new_data, fields=DANA_ONBOARDING_FIELD_TO_TRACK),
            customer_id=self.dana_customer_data.customer_id,
        )
        customer_field_changes = CustomerFieldChange.objects.filter(
            application_id=None, customer_id=self.dana_customer_data.customer.id
        ).all()
        self.assertEqual(1, len(customer_field_changes))
