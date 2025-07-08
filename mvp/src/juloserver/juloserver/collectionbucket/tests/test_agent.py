import mock
from django.test import TestCase
from juloserver.collectionbucket.services.agent import *
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
from juloserver.collectionbucket.models import CollectionAgentTask

class TestAgent(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment.status_id = 330
        self.account_payment.save()
        self.disbursement = DisbursementFactory()
        self.loan = LoanFactory(account=self.account, customer=self.customer,
                                loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
                                initial_cashback=2000,
                                disbursement_id=self.disbursement.id)
        self.payment1 = PaymentFactory(
                payment_status=self.account_payment.status,
                due_date=self.account_payment.due_date,
                account_payment=self.account_payment,
                loan=self.loan,
                change_due_date_interest=0,
                paid_date=datetime.today().date(),
                paid_amount=10000
            )
        self.payment2 = PaymentFactory(
                payment_status=self.account_payment.status,
                due_date=self.account_payment.due_date,
                account_payment=self.account_payment,
                loan=self.loan,
                change_due_date_interest=0,
                paid_date=datetime.today().date(),
                paid_amount=20900
            )
        self.agent_service = AgentService()


    def test_get_range_payment_and_role_agent_by_type(self):
        _, _, role = get_range_payment_and_role_agent_by_type(AgentAssignmentTypeConst.DPD1_DPD10)
        self.assertEqual(role, JuloUserRoles.COLLECTION_BUCKET_1)

        _, _, role = get_range_payment_and_role_agent_by_type(AgentAssignmentTypeConst.DPD11_DPD40)
        self.assertEqual(role, JuloUserRoles.COLLECTION_BUCKET_2)

        _, _, role = get_range_payment_and_role_agent_by_type(AgentAssignmentTypeConst.DPD41_DPD70)
        self.assertEqual(role, JuloUserRoles.COLLECTION_BUCKET_3)

        _, _, role = get_range_payment_and_role_agent_by_type(AgentAssignmentTypeConst.DPD71_DPD90)
        self.assertEqual(role, JuloUserRoles.COLLECTION_BUCKET_4)

        _, _, role = get_range_payment_and_role_agent_by_type('bucket 5')
        self.assertEqual(role, JuloUserRoles.COLLECTION_BUCKET_5)
    

    def test_process_exclude_agent_assign(self):
        CollectionAgentTask.objects.create(payment_id=self.payment1.id, type='test_type')
        unassign_payments = process_exclude_agent_assign([self.payment1, self.payment2], 'test_type')
        assert unassign_payments != None
    
    def test_process_exclude_assign_agent_collection(self):
        users = User.objects.all()
        returned_users = process_exclude_assign_agent_collection(users)
    
    def test_get_last_paid_payment_agent(self):
        CollectionAgentTask.objects.create(loan=self.loan, payment_id=self.payment2.id,
                                           type=AgentAssignmentTypeConst.DPD91PLUS, assign_to_vendor=True,
                                           assign_time=datetime.now(), agent=self.user_auth, unassign_time=datetime.now())
        return_value = get_last_paid_payment_agent(self.loan, 'test_type')
    
    def test_min_assigned_agent(self):
        return_value = min_assigned_agent([{'agent':self.user_auth, 'count':5}])
        assert return_value != None
    
    def test_get_agent_assigned_count(self):
        CollectionAgentTask.objects.create(loan=self.loan, payment_id=self.payment2.id,
                                           type=AgentAssignmentTypeConst.DPD91PLUS, assign_to_vendor=True,
                                           assign_time=datetime.now(), agent=self.user_auth)
        agents_list = get_agent_assigned_count([self.user_auth], AgentAssignmentTypeConst.DPD91PLUS)
    
    def test_check_agent_is_inhouse(self):
        return_value = check_agent_is_inhouse(self.user_auth)
        assert return_value == True
    
    def test_insert_agent_task_to_db(self):
        assign_time = datetime.now()
        CollectionAgentTask.objects.create(loan=self.loan)
        insert_agent_task_to_db(self.loan, self.payment1, self.user_auth,
                                AgentAssignmentTypeConst.DPD91PLUS, assign_time)
    
    @mock.patch('juloserver.collectionbucket.services.agent.get_range_payment_and_role_agent_by_type')
    @mock.patch('juloserver.julo.models.Loan.get_oldest_unpaid_payment')
    def test_get_data_assign_agent(self, mocked_oldest_unpaid_payment,  mocked_range_payment):
        mocked_range_payment.return_value = (BucketConst.BUCKET_5_DPD, 9999, JuloUserRoles.COLLECTION_BUCKET_5)
        payment = self.payment2
        payment.payment_status_id = 320
        payment.save()
        mocked_oldest_unpaid_payment.return_value = payment
        return_payments, user_list = self.agent_service.get_data_assign_agent('test_type', [self.loan])
    
    def test_get_user_agent_only(self):
        self.agent_service.get_user_agent_only('test_role')
    
    @mock.patch('juloserver.collectionbucket.services.agent.get_last_paid_payment_agent')
    def test_process_assign_loan_agent(self, mocked_agent):
        mocked_agent.return_value = self.user_auth
        self.agent_service.process_assign_loan_agent([self.payment1, self.payment2], [self.user_auth], AgentAssignmentTypeConst.DPD91PLUS)

    def test_filter_payments_based_on_dpd_and_agent(self):
        CollectionAgentTask.objects.create(loan=self.loan, payment_id=self.payment2.id,
                                           type='dpd1_dpd10', assign_to_vendor=True,
                                           assign_time=datetime.now(), agent=self.user_auth)
        payments = Payment.objects.all()
        assigned_payments = self.agent_service. \
                            filter_payments_based_on_dpd_and_agent(self.user_auth, 'collection_bucket_1', payments)
        assert assigned_payments != None
    
    def test_get_bucket_history_agent(self):
        payment = self.agent_service.get_bucket_history_agent({'id':self.payment1.id})
        account_payment = self.agent_service.get_bucket_history_agent_account_payment({'id':self.account_payment.id})

    def test_get_agent(self):
        payments = self.agent_service.get_agent([{'id':self.payment1.id},{'id':self.payment2.id}])
        assert payments != None
        account_payments = self.agent_service.get_agent_account_payment([{'id':self.account_payment.id}])
        assert account_payments != None
    
    def test_get_current_payment_assignment(self):
        task = CollectionAgentTask.objects.create(loan=self.loan, payment_id=self.payment2.id,
                                           type='dpd1_dpd10', assign_to_vendor=True,
                                           assign_time=datetime.now(), agent=self.user_auth)
        assignment = self.agent_service.get_current_payment_assignment(self.payment1)
        assert assignment == task
    
    @mock.patch('juloserver.collectionbucket.services.agent.AgentService.get_current_payment_assignment')
    def test_unassign_payment(self, mocked_get_current_payment_assignment): 
        task = CollectionAgentTask.objects.create(loan=self.loan, payment_id=self.payment2.id,
                                           type='dpd1_dpd10', assign_to_vendor=True,
                                           assign_time=datetime.now(), agent=self.user_auth)
        mocked_get_current_payment_assignment.return_value = task
        self.agent_service.unassign_payment(self.payment1)
    
    def test_unassign_bucket2_payments_going_for_bucket3(self):
        self.agent_service.unassign_bucket2_payments_going_for_bucket3()