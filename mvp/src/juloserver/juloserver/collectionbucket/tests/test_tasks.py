from django.test import TestCase
from juloserver.collectionbucket.tasks import *
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.julo.constants import AgentAssignmentTypeConst
from datetime import datetime
from juloserver.julo.tests.factories import (AuthUserFactory,
                                             CustomerFactory,
                                             LoanFactory,
                                             PaymentFactory,
                                             ApplicationFactory)
from juloserver.julo.models import StatusLookup, LoanStatusCodes, Payment
from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.disbursement.tests.factories import DisbursementFactory
#
# class TestTasks(TestCase):
#     def setUp(self):
#         self.user_auth = AuthUserFactory()
#         self.customer = CustomerFactory(user=self.user_auth)
#         self.account = AccountFactory(customer=self.customer)
#         self.application = ApplicationFactory(customer=self.customer, account=self.account)
#         self.account_payment = AccountPaymentFactory(account=self.account)
#         self.account_payment.status_id = 330
#         self.account_payment.save()
#         self.disbursement = DisbursementFactory()
#         self.loan = LoanFactory(account=self.account, customer=self.customer,
#                                 loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
#                                 initial_cashback=2000,
#                                 disbursement_id=self.disbursement.id)
#         self.payment1 = PaymentFactory(
#                 payment_status=self.account_payment.status,
#                 due_date=self.account_payment.due_date,
#                 account_payment=self.account_payment,
#                 loan=self.loan,
#                 change_due_date_interest=0,
#                 paid_date=datetime.today().date(),
#                 paid_amount=10000
#             )
#
#     def test_assign_collection_agent(self):
#         assign_collection_agent()