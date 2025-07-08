from builtins import object
import logging
import re

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import (
    Q,
    ExpressionWrapper,
    IntegerField,
    F)
from django.utils import timezone
from juloserver.julo.constants import AgentAssignmentTypeConst, BucketConst
from juloserver.julo.models import (Agent,
                                    Loan,
                                    Payment)
from juloserver.julo.statuses import (LoanStatusCodes,
                                      PaymentStatusCodes)
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from dateutil.relativedelta import relativedelta
from juloserver.minisquad.models import CollectionHistory
from django.core.exceptions import ObjectDoesNotExist
from ..models import CollectionAgentTask

PARTNER_AGENT_SUFFIXES = ['asiacollect', 'telmark', 'mbacollection', 'collmatra', 'selaras']
AGENT_ASSIGNTMENT_DICT = {
    JuloUserRoles.COLLECTION_BUCKET_1: AgentAssignmentTypeConst.DPD1_DPD10,
    JuloUserRoles.COLLECTION_BUCKET_2: AgentAssignmentTypeConst.DPD11_DPD40,
    JuloUserRoles.COLLECTION_BUCKET_3: AgentAssignmentTypeConst.DPD41_DPD70,
    JuloUserRoles.COLLECTION_BUCKET_4: AgentAssignmentTypeConst.DPD71_DPD90,
    JuloUserRoles.COLLECTION_BUCKET_5: AgentAssignmentTypeConst.DPD91PLUS,
}

DPD1_DPD10 = AgentAssignmentTypeConst.DPD1_DPD10
DPD11_DPD40 = AgentAssignmentTypeConst.DPD11_DPD40
DPD41_DPD70 = AgentAssignmentTypeConst.DPD41_DPD70

agent_map = {
    AgentAssignmentTypeConst.DPD1_DPD10: 'collection_bucket_1',
    AgentAssignmentTypeConst.DPD11_DPD40: 'collection_bucket_2',
    AgentAssignmentTypeConst.DPD41_DPD70: 'collection_bucket_3',
    AgentAssignmentTypeConst.DPD71_DPD90: 'collection_bucket_4',
    AgentAssignmentTypeConst.DPD91PLUS: 'collection_bucket_5'
}

logger = logging.getLogger(__name__)


def get_range_payment_and_role_agent_by_type(type):
    if type == AgentAssignmentTypeConst.DPD1_DPD10:
        return BucketConst.BUCKET_1_DPD['from'], BucketConst.BUCKET_1_DPD[
            'to'], JuloUserRoles.COLLECTION_BUCKET_1
    if type == AgentAssignmentTypeConst.DPD11_DPD40:
        return BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD[
            'to'], JuloUserRoles.COLLECTION_BUCKET_2
    if type == AgentAssignmentTypeConst.DPD41_DPD70:
        return BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD[
            'to'], JuloUserRoles.COLLECTION_BUCKET_3
    if type == AgentAssignmentTypeConst.DPD71_DPD90:
        return BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD[
            'to'], JuloUserRoles.COLLECTION_BUCKET_4

    return BucketConst.BUCKET_5_DPD, 9999, JuloUserRoles.COLLECTION_BUCKET_5


def process_exclude_agent_assign(payments, type):
    """
    exclude loan that already assigned to agent
    """
    payment_ids = list([x.id for x in payments])
    assignments = CollectionAgentTask.objects.filter(
        payment_id__in=payment_ids, type=type, unassign_time__isnull=True)
    assigned_payments = list(assignments.distinct('payment_id')
                            .values_list('payment_id', flat=True))
    # populate unassigned payments
    unassign_payments = []

    for payment in payments:
        if payment.id not in assigned_payments:
            unassign_payments.append(payment)

    return unassign_payments


def process_exclude_assign_agent_collection(users):
    partner_agent_1 = Q(username__startswith='asiacollect')
    partner_agent_2 = Q(username__startswith='mbacollection')
    partner_agent_3 = Q(username__startswith='selaras')
    partner_agent_4 = Q(username__startswith='colmatra')

    users = users.exclude(groups__name=JuloUserRoles.COLLECTION_SUPERVISOR)\
                 .exclude(partner_agent_1 |
                          partner_agent_2 |
                          partner_agent_3 |
                          partner_agent_4)

    return users


def get_last_paid_payment_agent(loan, assignment_type):
    today = timezone.localtime(timezone.now()).date()
    assignment = CollectionAgentTask.objects.filter(loan=loan,
                                                    type=AgentAssignmentTypeConst.DPD91PLUS,
                                                    assign_to_vendor=True,
                                                    unassign_time__isnull=False)\
                                            .last()

    if not assignment:
        return None

    payment = assignment.payment

    if payment.payment_status_id < PaymentStatusCodes.PAID_ON_TIME:
        return None

    max_assign_to_vendor_date = (assignment.assign_time).date() + relativedelta(days=90)

    if today > max_assign_to_vendor_date:
        if not assignment.unassign_time:
            assignment.update_safely(unassign_time=today)

        return None

    agent = assignment.agent
    agent_username = agent.username
    vendor = agent_username.split(agent_username[-1])[0]
    _, _, role = get_range_payment_and_role_agent_by_type(assignment_type)
    username = '{}{}'.format(vendor, role[-1])
    proper_agent = User.objects.filter(groups__name=role,
                                       username=username)\
                               .last()

    if proper_agent:
        return proper_agent
    else:
        return None


def min_assigned_agent(agents_count):
    """
    Returns agent having minimum no of loans assigned or vendor agent if the payment
    is on bucket 5.
    :param agents_count: List of dict User object (Agents) and payment assigned count
    :param rr_agent_count: count of previous agent assignments
    :return: User object (Agent)
    """

    min_agent_count = min(agents_count, key=lambda x: x['count'])

    return min_agent_count['agent']


def get_agent_assigned_count(agents, type):
    agent_assignments = CollectionAgentTask.objects\
                            .filter(unassign_time__isnull=True,
                                    type=type).distinct('loan')

    agents_list = [{'agent': agent, 'count': agent_assignments.filter
                    (agent=agent).count()} for agent in agents]

    return agents_list


def update_agent_count(agent_list, agent):
    """To update agent counts while the assignment process is running

    Arguments:
        agent_list {[list]} -- List of agents
        agent {[obj]} -- Object of agent
    """
    for agent_count in agent_list:
        if agent_count['agent'] == agent:
            agent_count['count'] += 1


def check_agent_is_inhouse(agent):
    """Check if agent is vendor inhouse

    Arguments:
        agent {obj} -- object of agent

    Returns:
        boolean --
    """
    username = agent.username
    agent_prefix = re.findall('([a-z])', username)
    agent_prefix = ''.join(agent_prefix)
    PARTNER_AGENT_SUFFIXES.extend(('simcollection',
                                    'telmarkjogja',
                                    'mbacollection',
                                    'asiacollect',
                                    'selaras',
                                    'colmatra'))

    if agent_prefix not in PARTNER_AGENT_SUFFIXES:
        return True
    else:
        return False


def insert_agent_task_to_db(loan, payment, agent, type, assign_time):
    """insert agent task to collection_agent_task while unassign previous
    assignment

    Arguments:
        loan {[obj]} -- object of loan
        payment {[obj]} -- object of payment
        agent {[obj]} -- object of user
        type {[string]} -- Type of Agent Assignment based on dpd
        assign_time {[datetime]} -- The time when task is assigned
    """
    # unassign previous assignment bucket
    CollectionAgentTask.objects.filter(loan=loan,
                                       unassign_time__isnull=True)\
                               .update(unassign_time=assign_time)

    actual_agent = None
    assign_to_vendor = False

    if not check_agent_is_inhouse(agent):
        actual_agent = agent
        assign_to_vendor = True

    CollectionAgentTask.objects.create(loan=loan,
                                       payment=payment,
                                       agent=agent,
                                       type=type,
                                       assign_time=assign_time,
                                       actual_agent=actual_agent,
                                       assign_to_vendor=assign_to_vendor)


class AgentService(object):
    def get_data_assign_agent(self, type, loans):
        """
        retrieve unassigned payments to be assign
        bucket movement, next oldest unpaid payment
        """
        start_range, end_range, agent_role = get_range_payment_and_role_agent_by_type(type)
        payments = []

        today_date = timezone.localtime(timezone.now()).date()

        for loan in loans:
            oldest_unpaid_payment = loan.get_oldest_unpaid_payment()

            if not oldest_unpaid_payment:
                continue

            start_late_date = oldest_unpaid_payment.due_date + relativedelta(days=start_range)
            end_late_date = oldest_unpaid_payment.due_date + relativedelta(days=end_range)

            if start_late_date <= today_date <= end_late_date:
                payments.append(oldest_unpaid_payment)

        if not payments:
            return None, None

        payments = process_exclude_agent_assign(payments, type)

        # only bucket 2 that is included in round robin due to minisquad
        if agent_role == JuloUserRoles.COLLECTION_BUCKET_2:
            users = User.objects.filter(groups__name=agent_role, is_active=True)
            user_list = process_exclude_assign_agent_collection(users)
        else:
            user_list = self.get_user_agent_only(agent_role)

        return payments, list(user_list)

    def get_user_agent_only(self, role):
        partner_agent_1 = Q(username__startswith='asiacollect')
        partner_agent_2 = Q(username__startswith='mbacollection')
        partner_agent_3 = Q(username__startswith='selaras')
        partner_agent_4 = Q(username__startswith='collmatra')

        # telmarkjogja and simcollection are excluded because they are
        # only on bucket 2

        partner_agent_5 = Q(username__startswith='telmarkjogja')
        partner_agent_6 = Q(username__startswith='simcollection')

        return User.objects.filter(groups__name=role)\
                           .filter(partner_agent_1 |
                                   partner_agent_2 |
                                   partner_agent_3 |
                                   partner_agent_4)\
                           .exclude(partner_agent_5,
                                    partner_agent_6)

    # def get_or_none_partner_agent_by_payment(self, payment, type):
    #     partner_agent_1 = Q(agent__username__startswith='asiacollect')
    #     partner_agent_2 = Q(agent__username__startswith='mbacollection')
    #     partner_agent_3 = Q(agent__username__startswith='telmark')
    #     partner_agent_4 = Q(agent__username__startswith='collmatra')
    #     assignment = CollectionAgentTask.objects.prefetch_related('agent')\
    #                                     .filter(payment=payment,
    #                                             unassign_time__isnull=True)\
    #                                     .filter(partner_agent_1 |
    #                                             partner_agent_2 |
    #                                             partner_agent_3 |
    #                                             partner_agent_4)\
    #                                     .order_by('id').last()

    #     if assignment:
    #         agent = assignment.agent
    #         agent_username = agent.username
    #         vendor = agent_username.split(agent_username[-1])[0]
    #         _, _, role = get_range_payment_and_role_agent_by_type(type)
    #         username = '{}{}'.format(vendor, role[-1])
    #         proper_agent = User.objects.filter(groups__name=role,
    #                                            user__username=username)\
    #                                    .last()

    #         if proper_agent:
    #             return proper_agent

    #     return None

    def process_assign_loan_agent(self, payments, agents, type):
        """
        Check whether assignment is handled by partner agent or not
        if not check whether assignment is handled by in house agent or not
        if not possibly its new agent assignment, assign a new agent for that
        """

        agent_list = get_agent_assigned_count(agents, type)
        assign_time = timezone.localtime(timezone.now())

        # assign_agent in loan
        for payment in payments:
            with transaction.atomic():
                loan = payment.loan

                # to get agent partner if payment is handled by agent on bucket 5
                rr_found_agent = get_last_paid_payment_agent(loan, type)

                if not rr_found_agent and \
                        type == AgentAssignmentTypeConst.DPD11_DPD40:
                    rr_found_agent = min_assigned_agent(agent_list)

                if rr_found_agent is None:
                    continue

                # create assignment for loan
                insert_agent_task_to_db(loan,
                                        payment,
                                        rr_found_agent,
                                        type,
                                        assign_time)

                # update agent_count
                update_agent_count(agent_list, rr_found_agent)

    def filter_payments_based_on_dpd_and_agent(self, agent, role, payments):
        assignment_type = AGENT_ASSIGNTMENT_DICT[role]
        agent_assignments = CollectionAgentTask.objects\
                                .filter(type=assignment_type,
                                        agent=agent,
                                        unassign_time__isnull=True)\
                                .values_list('payment_id', flat=True)

        assigned_payments = payments.filter(id__in=agent_assignments)

        return assigned_payments

    def get_bucket_history_agent(self, payment):
        try:
            collection_history = CollectionHistory.objects.values('squad__squad_name',
                                                                  'agent_id',
                                                                  'agent__username',
                                                                  'squad__group__name',
                                                                  'id')\
                                                          .filter(payment_id=payment['id'],
                                                                  last_current_status=True).last()
        except ObjectDoesNotExist:
            collection_history = None

        if collection_history is not None:
            payment[collection_history['squad__group__name']] = dict(id=collection_history['id'],
                                                                    squad=collection_history['squad__squad_name'],
                                                                    username=collection_history['agent__username'])

        return payment
    

    def get_bucket_history_agent_account_payment(self, account_payment):
        try:
            collection_history = CollectionHistory.objects.values('squad__squad_name',
                                                                  'agent_id',
                                                                  'agent__username',
                                                                  'squad__group__name',
                                                                  'id')\
                                                          .filter(account_payment_id=account_payment['id'],
                                                                  last_current_status=True).last()
        except ObjectDoesNotExist:
            collection_history = None

        if collection_history is not None:
            account_payment[collection_history['squad__group__name']] = dict(id=collection_history['id'],
                                                                    squad=collection_history['squad__squad_name'],
                                                                    username=collection_history['agent__username'])

        return account_payment



    def get_agent(self, payments):
        for payment in payments:
            payment['collection_bucket_1'] = {'id': '', 'username': '', 'squad': ''}
            payment['collection_bucket_2'] = {'id': '', 'username': '', 'squad': ''}
            payment['collection_bucket_3'] = {'id': '', 'username': '', 'squad': ''}
            payment['collection_bucket_4'] = {'id': '', 'username': '', 'squad': ''}
            payment['collection_bucket_5'] = {'id': '', 'username': '', 'squad': ''}
            payment['collection_bucket_type'] = ''

            payment = self.get_bucket_history_agent(payment)

        return payments
    
    def get_agent_account_payment(self, account_payments):
        for payment in account_payments:
            payment['collection_bucket_1'] = {'id': '', 'username': '', 'squad': ''}
            payment['collection_bucket_2'] = {'id': '', 'username': '', 'squad': ''}
            payment['collection_bucket_3'] = {'id': '', 'username': '', 'squad': ''}
            payment['collection_bucket_4'] = {'id': '', 'username': '', 'squad': ''}
            payment['collection_bucket_5'] = {'id': '', 'username': '', 'squad': ''}
            payment['collection_bucket_type'] = ''

            payment = self.get_bucket_history_agent_account_payment(payment)

        return account_payments


    def get_current_payment_assignment(self, payment):
        assignment = CollectionAgentTask.objects.filter(
            loan=payment.loan,
            unassign_time__isnull=True).last()

        return assignment

    def unassign_payment(self, payment):
        assignment = self.get_current_payment_assignment(payment)
        if not assignment:
            return

        current_time = timezone.now()
        assignment.update_safely(unassign_time=current_time)
        logger.info({
            'unassign_payment': assignment.payment_id,
            'agent': assignment.agent_id,
            'unassign_time': current_time
        })

    def unassign_bucket2_payments_going_for_bucket3(self):
        """unassign payments from bucket 2 that already passed dpd
        """
        today = timezone.localtime(timezone.now())
        payments = Payment.objects.annotate(
            dpd=ExpressionWrapper(
                today.date() - F('due_date'),
                output_field=IntegerField())).filter(
                    dpd__gte=41,
                    payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME)\
            .values_list('id', flat=True)

        CollectionAgentTask.objects.filter(
            payment__in=payments,
            unassign_time__isnull=True,
            type=AgentAssignmentTypeConst.DPD11_DPD40
        ).update(
            unassign_time=today
        )
