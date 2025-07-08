import json

from django.contrib.auth.models import Group
from rest_framework.test import APIClient, APITestCase
from rest_framework.reverse import reverse
from django.test import TestCase

from mock import patch
from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    AccountPropertyFactory,
)
from juloserver.cfs.tests.factories import AgentFactory
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    CustomerFactory,
    AuthUserFactory,
    ApplicationFactory,
    StatusLookupFactory,
    WorkflowFactory,
    ProductLineFactory,
    LoanFactory,
    ProductLookupFactory,
    LenderFactory,
    AccountingCutOffDateFactory,
)
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo_financing.tests.factories import *
from juloserver.julo_financing.constants import JFinancingStatus
from juloserver.loan.tasks.lender_related import julo_one_disbursement_trigger_task
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.account.tests.factories import AccountLimitFactory
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history


class TestJFinancingProcessLoan(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        AccountingCutOffDateFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
            ever_entered_B5=True,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.DRAFT),
            transaction_method=TransactionMethodFactory(
                id=TransactionMethodCode.JFINANCING.code,
                method=TransactionMethodCode.JFINANCING.name,
            ),
            lender=LenderFactory(lender_name='jtp'),
        )
        self.product_quantity = 10
        self.product = JFinancingProductFactory(quantity=self.product_quantity)
        checkout_info = {
            "address": "test",
            "address_detail": "test",
            "full_name": "test",
            "phone_number": "08321321321",
        }
        checkout = JFinancingCheckoutFactory(
            customer=self.customer, additional_info=checkout_info, j_financing_product=self.product
        )
        self.verification = JFinancingVerificationFactory(
            j_financing_checkout=checkout, loan=self.loan
        )
        self.available_limit = 10000000
        self.account_limit = AccountLimitFactory(
            account=self.account, available_limit=self.available_limit
        )
        StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        self.current_status = StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)

    def test_process_loan_successfully(self):
        self.loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL)
        self.loan.save()
        julo_one_disbursement_trigger_task(self.loan.pk)
        self.loan.refresh_from_db()
        assert self.loan.loan_status == self.current_status

    def test_update_failed_loan_status(self):
        self.loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL)
        self.loan.save()
        update_loan_status_and_loan_history(
            loan_id=self.loan.id,
            new_status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER,
            change_reason="Cancelled",
        )
        self.verification.validation_status = JFinancingStatus.CANCELED
        self.product.refresh_from_db()
        assert self.product.quantity == self.product_quantity + 1

        self.loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.DRAFT)
        self.loan.save()
        self.account_limit.available_limit = self.available_limit
        self.account_limit.save()
        update_loan_status_and_loan_history(
            loan_id=self.loan.id,
            new_status_code=LoanStatusCodes.INACTIVE,
            change_reason="Cancelled",
        )
        self.loan.refresh_from_db()
        self.account_limit.refresh_from_db()
        assert self.available_limit - self.loan.loan_amount == self.account_limit.available_limit


class TestUpdateJuloFinancingVerification(APITestCase):
    def setUp(self):
        self.client = APIClient()

        group = Group(name=JuloUserRoles.JFinancingAdmin)
        group.save()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.active_status_code = StatusLookupFactory(
            status_code=AccountConstant.STATUS_CODE.active
        )
        self.active_in_grace = StatusLookupFactory(
            status_code=AccountConstant.STATUS_CODE.active_in_grace
        )
        self.loan_status_code_active = StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)
        self.loan_status_code_failed = StatusLookupFactory(
            status_code=LoanStatusCodes.TRANSACTION_FAILED
        )
        self.loan_status_code_inactive = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        self.account = AccountFactory(customer=self.customer, status=self.active_status_code)
        self.account_property = AccountPropertyFactory(account=self.account, is_entry_level=True)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        agent = AgentFactory(user=self.user)

        self.user.groups.add(group)
        self.client.force_login(self.user)
        self.account_limit = AccountLimitFactory(account=self.account, available_limit=10_000_000)
        self.product_lookup = ProductLookupFactory()
        TransactionMethodFactory(
            id=TransactionMethodCode.BALANCE_CONSOLIDATION.code,
            method=TransactionMethodCode.BALANCE_CONSOLIDATION.name,
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.DRAFT),
            transaction_method=TransactionMethodFactory(
                id=TransactionMethodCode.JFINANCING.code,
                method=TransactionMethodCode.JFINANCING.name,
            ),
        )
        self.product_quantity = 10
        self.product = JFinancingProductFactory(quantity=self.product_quantity)
        checkout_info = {
            "address": "test",
            "address_detail": "test",
            "full_name": "test",
            "phone_number": "08321321321",
        }
        self.checkout = JFinancingCheckoutFactory(
            customer=self.customer, additional_info=checkout_info, j_financing_product=self.product
        )
        self.verification = JFinancingVerificationFactory(
            j_financing_checkout=self.checkout, loan=self.loan, locked_by_id=agent.pk
        )

        self.url = reverse(
            'julo_financing_crm:verification_detail_update',
            kwargs={'verification_id': self.verification.id},
        )

    @patch('juloserver.julo_financing.services.crm_services.execute_after_transaction_safely')
    @patch('juloserver.julo_financing.services.crm_services.accept_julo_sphp')
    def test_update_success(self, mock_accept_julo_sphp, _mock_execute_after_transaction_safely):
        req_data = {'status': JFinancingStatus.CONFIRMED, 'note': 'new note'}

        resp = self.client.put(self.url, data=json.dumps(req_data), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        assert _mock_execute_after_transaction_safely.call_count == 0

        mock_accept_julo_sphp.assert_called()
        self.verification.validation_status = JFinancingStatus.CONFIRMED

        # CONFIRMED to ON DELIVERY
        # Courier not update => failed
        req_data = {'status': JFinancingStatus.ON_DELIVERY, 'note': 'new note'}

        resp = self.client.put(self.url, data=json.dumps(req_data), content_type="application/json")
        self.assertEqual(resp.status_code, 400)

        # has courier exists
        self.checkout.courier_name = 'test'
        self.checkout.courier_tracking_id = '12321321312'
        self.checkout.save()
        req_data = {'status': JFinancingStatus.ON_DELIVERY, 'note': 'new note'}

        resp = self.client.put(self.url, data=json.dumps(req_data), content_type="application/json")
        self.assertEqual(resp.status_code, 200)

        self.verification.refresh_from_db()
        assert self.verification.validation_status == JFinancingStatus.ON_DELIVERY
        assert _mock_execute_after_transaction_safely.call_count == 1
        req_data = {'status': JFinancingStatus.COMPLETED, 'note': 'new note'}

        resp = self.client.put(self.url, data=json.dumps(req_data), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.verification.refresh_from_db()
        assert self.verification.validation_status == JFinancingStatus.COMPLETED
        assert _mock_execute_after_transaction_safely.call_count == 2

    def test_update_non_exist_status(self):
        req_data = {'status': 'non_exist_status', 'note': 'new note'}

        resp = self.client.put(self.url, data=json.dumps(req_data), content_type="application/json")
        self.assertEqual(resp.status_code, 400)

        # Wrong path status
        req_data = {'status': JFinancingStatus.ON_DELIVERY, 'note': 'new note'}
        resp = self.client.put(self.url, data=json.dumps(req_data), content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_not_found_verification(self):
        req_data = {'status': JFinancingStatus.CONFIRMED, 'note': 'new note'}
        url = reverse(
            'julo_financing_crm:verification_detail_update',
            kwargs={'verification_id': 0},
        )

        resp = self.client.put(url, data=json.dumps(req_data), content_type="application/json")
        self.assertEqual(resp.status_code, 404)

    def test_update_lock_from_another_agent(self):
        self.verification.locked_by = AgentFactory()
        self.verification.save()

        req_data = {'status': JFinancingStatus.CONFIRMED, 'note': 'new note'}

        resp = self.client.put(self.url, data=json.dumps(req_data), content_type="application/json")
        self.assertEqual(resp.status_code, 404)
