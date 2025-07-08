from builtins import object
import logging
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from ..constants import (AgentAssignmentTypeConst,
                         FeatureNameConst)
from ..models import (Agent,
                      CollectionAgentAssignment,
                      FeatureSetting,
                      Loan)
from ..statuses import (LoanStatusCodes,)
from juloserver.julo.partners import PartnerConstant
from juloserver.portal.object.dashboard.constants import JuloUserRoles

logger = logging.getLogger(__name__)

DPD1_DPD29 = AgentAssignmentTypeConst.DPD1_DPD29
DPD30_DPD59 = AgentAssignmentTypeConst.DPD30_DPD59
DPD60_DPD89 = AgentAssignmentTypeConst.DPD60_DPD89
DPD90PLUS = AgentAssignmentTypeConst.DPD90PLUS
DPD1_DPD15 = AgentAssignmentTypeConst.DPD1_DPD15
DPD16_DPD29 = AgentAssignmentTypeConst.DPD16_DPD29
DPD30_DPD44 = AgentAssignmentTypeConst.DPD30_DPD44
DPD45_DPD59 = AgentAssignmentTypeConst.DPD45_DPD59
COLLECTION_AGENT_2 = JuloUserRoles.COLLECTION_AGENT_2
COLLECTION_AGENT_3 = JuloUserRoles.COLLECTION_AGENT_3
COLLECTION_AGENT_4 = JuloUserRoles.COLLECTION_AGENT_4
COLLECTION_AGENT_5 = JuloUserRoles.COLLECTION_AGENT_5
COLLECTION_AGENT_2A = JuloUserRoles.COLLECTION_AGENT_2A
COLLECTION_AGENT_2B = JuloUserRoles.COLLECTION_AGENT_2B
COLLECTION_AGENT_3A = JuloUserRoles.COLLECTION_AGENT_3A
COLLECTION_AGENT_3B = JuloUserRoles.COLLECTION_AGENT_3B
COLLECTION_SUPERVISOR = JuloUserRoles.COLLECTION_SUPERVISOR
PARTNER_AGENT_SUFFIXES = ['asiacollect', 'telmark', 'mbacollection', 'collmatra']
agent_map = {
    DPD1_DPD29: 'agent_2',
    DPD1_DPD15: 'agent_2a',
    DPD16_DPD29: 'agent_2b',
    DPD30_DPD59: 'agent_3',
    DPD30_DPD44: 'agent_3a',
    DPD45_DPD59: 'agent_3b',
    DPD60_DPD89: 'agent_4',
    DPD90PLUS: 'agent_5'
}


def process_exclude_agent_assign(payments, type):
    """
    exclude loan that already assigned to agent
    """
    payment_ids = list([x.id for x in payments])
    assignments = CollectionAgentAssignment.objects.filter(
        payment_id__in=payment_ids, type=type, unassign_time__isnull=True)
    assigned_payments = list(assignments.order_by('payment_id')\
                                        .distinct('payment_id')\
                                        .values_list('payment_id', flat=True))
    # populate unassigned payments
    unassign_payments = []
    for payment in payments:
        if payment.id not in assigned_payments:
            unassign_payments.append(payment)

    last_agent = assignments.order_by('id').last().agent if assignments else None
    return unassign_payments, last_agent


def process_exclude_assign_agent_collection(users):
    users = users.exclude(groups__name=COLLECTION_SUPERVISOR)
    users = users.exclude(agent__user_extension__in=PARTNER_AGENT_SUFFIXES)
    return users


def selected_range_payment_and_role_agent_by_type(type):
    if type == DPD1_DPD29:
        range1, range2, role = 1, 29, COLLECTION_AGENT_2
    elif type == DPD30_DPD59:
        range1, range2, role = 30, 59, COLLECTION_AGENT_3
    elif type == DPD60_DPD89:
        range1, range2, role = 60, 89, COLLECTION_AGENT_4
    elif type == DPD1_DPD15:
        range1, range2, role = 1, 15, COLLECTION_AGENT_2A
    elif type == DPD16_DPD29:
        range1, range2, role = 16, 29, COLLECTION_AGENT_2B
    elif type == DPD30_DPD44:
        range1, range2, role = 30, 44, COLLECTION_AGENT_3A
    elif type == DPD45_DPD59:
        range1, range2, role = 45, 59, COLLECTION_AGENT_3B
    else:
        range1, range2, role = 90, 9999, COLLECTION_AGENT_5
    today = timezone.localtime(timezone.now()).date()
    start_date = today - timedelta(days=range1)
    end_date = today - timedelta(days=range2)
    return start_date, end_date, role


def convert_range_day_to_agentassignment_type(range_day):
    if 1 <= range_day <= 29:
        # check split bucket 2a and 2b active or not
        active_split_2a = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AGENT_ASSIGNMENT_DPD1_DPD15,
            is_active=True,
            category="agent").last()
        active_split_2b = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AGENT_ASSIGNMENT_DPD16_DPD29,
            is_active=True,
            category="agent").last()
        if active_split_2a and active_split_2b:
            if range_day <= 15:
                return DPD1_DPD15
            elif 16 <= range_day <= 29:
                return DPD16_DPD29
        return DPD1_DPD29
    if 30 <= range_day <= 59:
        # check split bucket 3a and 3b active or not
        active_split_3a = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AGENT_ASSIGNMENT_DPD30_DPD44,
            is_active=True,
            category="agent").last()
        active_split_3b = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AGENT_ASSIGNMENT_DPD45_DPD59,
            is_active=True,
            category="agent").last()
        if active_split_3a and active_split_3b:
            if 30 <= range_day <= 44:
                return DPD30_DPD44
            elif 45 <= range_day <= 59:
                return DPD45_DPD59
        return DPD30_DPD59
    if 60 <= range_day <= 89:
        return DPD60_DPD89
    if range_day > 89:
        return DPD90PLUS


def convert_usergroup_to_agentassignment_type(usergroup):
    if usergroup == COLLECTION_AGENT_2:
        return DPD1_DPD29
    elif usergroup == COLLECTION_AGENT_3:
        return DPD30_DPD59
    elif usergroup == COLLECTION_AGENT_4:
        return DPD60_DPD89
    elif usergroup == COLLECTION_AGENT_5:
        return DPD90PLUS
    elif usergroup == COLLECTION_AGENT_2A:
        return DPD1_DPD15
    elif usergroup == COLLECTION_AGENT_2B:
        return DPD16_DPD29
    elif usergroup == COLLECTION_AGENT_3A:
        return DPD30_DPD44
    elif usergroup == COLLECTION_AGENT_3B:
        return DPD45_DPD59


def convert_featurename_to_agentassignment_type(feature_name):
    if feature_name == FeatureNameConst.AGENT_ASSIGNMENT_DPD1_DPD29:
        return DPD1_DPD29
    elif feature_name == FeatureNameConst.AGENT_ASSIGNMENT_DPD30_DPD59:
        return DPD30_DPD59
    elif feature_name == FeatureNameConst.AGENT_ASSIGNMENT_DPD60_DPD89:
        return DPD60_DPD89
    elif feature_name == FeatureNameConst.AGENT_ASSIGNMENT_DPD90PLUS:
        return DPD90PLUS
    elif feature_name == FeatureNameConst.AGENT_ASSIGNMENT_DPD1_DPD15:
        return DPD1_DPD15
    elif feature_name == FeatureNameConst.AGENT_ASSIGNMENT_DPD16_DPD29:
        return DPD16_DPD29
    elif feature_name == FeatureNameConst.AGENT_ASSIGNMENT_DPD30_DPD44:
        return DPD30_DPD44
    elif feature_name == FeatureNameConst.AGENT_ASSIGNMENT_DPD45_DPD59:
        return DPD45_DPD59


def convert_agentassignment_type_to_usergroup(agent_assignment_type):
    if agent_assignment_type == DPD1_DPD29:
        return COLLECTION_AGENT_2
    elif agent_assignment_type == DPD30_DPD59:
        return COLLECTION_AGENT_3
    elif agent_assignment_type == DPD60_DPD89:
        return COLLECTION_AGENT_4
    elif agent_assignment_type == DPD90PLUS:
        return COLLECTION_AGENT_5
    elif agent_assignment_type == DPD1_DPD15:
        return COLLECTION_AGENT_2A
    elif agent_assignment_type == DPD16_DPD29:
        return COLLECTION_AGENT_2B
    elif agent_assignment_type == DPD30_DPD44:
        return COLLECTION_AGENT_3A
    elif agent_assignment_type == DPD45_DPD59:
        return COLLECTION_AGENT_3B


def get_vendor_agent_by_type(type, vendor):
    role = convert_agentassignment_type_to_usergroup(type)
    username = '{}{}'.format(vendor, role[-1])
    proper_agent = Agent.objects.filter(
        user_extension=vendor,
        user__groups__name=role,
        user__username=username).last()
    if not proper_agent:
        return None
    return proper_agent.user


def get_payment_type_vendor_agent(payments, vendor):
    payment_type_list = []
    for payment in payments:
        payment_data = {}
        if 1 <= payment.due_late_days <= 29:
            payment_data['payment'] = payment
            payment_data['type'] = DPD1_DPD29
            payment_data['agent'] = get_vendor_agent_by_type(DPD1_DPD29, vendor)
            payment_type_list.append(payment_data)
        elif 30 <= payment.due_late_days <= 59:
            payment_data['payment'] = payment
            payment_data['type'] = DPD30_DPD59
            payment_data['agent'] = get_vendor_agent_by_type(DPD30_DPD59, vendor)
            payment_type_list.append(payment_data)
        elif 60 <= payment.due_late_days <= 89:
            payment_data['payment'] = payment
            payment_data['type'] = DPD60_DPD89
            payment_data['agent'] = get_vendor_agent_by_type(DPD60_DPD89, vendor)
            payment_type_list.append(payment_data)
        elif payment.due_late_days > 89:
            payment_data['payment'] = payment
            payment_data['type'] = DPD90PLUS
            payment_data['agent'] = get_vendor_agent_by_type(DPD90PLUS, vendor)
            payment_type_list.append(payment_data)
    return payment_type_list


def min_assigned_agent(agents_count):
    """
    Returns agent having minimum no of loans assigned.
    :param agents_count: List of dict User object (Agents) and payment assigned count
    :param rr_agent_count: count of previous agent assignments
    :return: User object (Agent)
    """
    min_agent_count = min(agents_count, key=lambda x: x['count'])
    return min_agent_count['agent']


def get_agent_assigned_count(agents, type):
    agents_count = []
    agent_assignments = CollectionAgentAssignment.objects.filter(
        unassign_time__isnull=True,
        type=type).order_by('loan', '-payment')\
                  .distinct('loan')
    for agent in agents:
        agents_count.append({
            'agent': agent,
            'count': agent_assignments.filter(agent=agent).count()
        })
    return agents_count


class AgentService(object):

    def get_data_assign_agent(self, type):
        """
        retrieve unassign payments to be assign
        bucket movement, next oldest unpaid payment
        """
        start_date, end_date, agent_role = selected_range_payment_and_role_agent_by_type(type)
        loans = Loan.objects.prefetch_related('payment_set', 'agentassignment_set')\
                            .not_paid_active()\
                            .exclude(application__partner__name__in=PartnerConstant.form_partner())
        payments = []
        for loan in loans:
            oldest_unpaid_payment = loan.payment_set.not_paid_active()\
                                                    .order_by('payment_number')\
                                                    .first()
            if not oldest_unpaid_payment:
                continue
            elif end_date <= oldest_unpaid_payment.due_date <= start_date:
                payments.append(oldest_unpaid_payment)

        if not payments:
            return None, None, None
        payments, last_agent = process_exclude_agent_assign(payments, type)
        users = User.objects.filter(groups__name=agent_role, is_active=True).order_by('id')
        user_list = process_exclude_assign_agent_collection(users)
        return payments, list(user_list), last_agent

    def get_agent(self, payments):
        for payment in payments:
            payment['agent_2'] = {'id': '', 'username': ''}
            payment['agent_3'] = {'id': '', 'username': ''}
            payment['agent_4'] = {'id': '', 'username': ''}
            payment['agent_5'] = {'id': '', 'username': ''}
            payment['agent_type'] = ''
            payment = self.get_bucket_history_agent(payment)
        return payments

    def get_active_type(self, type):
        if type == DPD1_DPD15:
            active_split_2a = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.AGENT_ASSIGNMENT_DPD1_DPD15,
                is_active=True,
                category="agent").last()
            if not active_split_2a:
                type = DPD1_DPD29
            return type
        elif type == DPD16_DPD29:
            active_split_2b = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.AGENT_ASSIGNMENT_DPD16_DPD29,
                is_active=True,
                category="agent").last()
            if not active_split_2b:
                type = DPD1_DPD29
            return type
        elif type == DPD30_DPD44:
            active_split_3a = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.AGENT_ASSIGNMENT_DPD30_DPD44,
                is_active=True,
                category="agent").last()
            if not active_split_3a:
                type = DPD30_DPD59
            return type
        elif type == DPD45_DPD59:
            active_split_3b = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.AGENT_ASSIGNMENT_DPD45_DPD59,
                is_active=True,
                category="agent").last()
            if not active_split_3b:
                type = DPD30_DPD59
            return type
        return type

    def filter_payments_by_agent_and_type(self, payments, agent, type):
        type = self.get_active_type(type)
        assignments = CollectionAgentAssignment.objects.filter(
            type=type, agent=agent, unassign_time__isnull=True).order_by('id')
        payment_agents = [assignment.payment_id for assignment in assignments]
        payments = payments.filter(id__in=payment_agents)
        if type in [DPD1_DPD29, DPD1_DPD15, DPD16_DPD29]:
            payments = payments.exclude(
                loan__loan_status__status_code__gte=LoanStatusCodes.LOAN_30DPD)
        elif type in [DPD30_DPD59, DPD30_DPD44, DPD45_DPD59]:
            payments = payments.exclude(
                loan__loan_status__status_code__gte=LoanStatusCodes.LOAN_60DPD)
        elif type == DPD60_DPD89:
            payments = payments.exclude(
                loan__loan_status__status_code__gte=LoanStatusCodes.LOAN_90DPD)
        return payments

    def filter_payments_by_agent_id(self, payments, agent_id):
        assignments = CollectionAgentAssignment.objects.filter(
            agent_id=agent_id, unassign_time__isnull=True).order_by('id')
        payment_agents = [assignment.payment_id for assignment in assignments]
        payments = payments.filter(id__in=payment_agents)
        return payments
    
    def filter_account_payments_by_agent_id(self, account_payments, agent_id):
        assignments = CollectionAgentAssignment.objects.filter(
            agent_id=agent_id, unassign_time__isnull=True).order_by('id')
        payment_agents = [assignment.payment_id for assignment in assignments]
        account_payments = account_payments.filter(payment__id__in=payment_agents)
        return account_payments

    def filter_applications_by_agent_id(self, applications, agent_id):
        agent_loan_ids = CollectionAgentAssignment.objects.filter(
            agent_id=agent_id, unassign_time__isnull=True).order_by('id').values_list('loan_id')
        applications = applications.filter(account__loan__id__in=[loan_id[0] for loan_id in agent_loan_ids])
        return applications


    def get_or_none_agent_to_assign_by_loan(self, loan, type):
        # today = timezone.now()
        agent = CollectionAgentAssignment.objects\
                                         .filter(loan=loan,
                                                 type=type,
                                                 unassign_time__isnull=True)\
                                         .order_by('id')\
                                         .last()
        return agent.agent if agent else None

    def get_or_none_partner_agent_by_payment(self, payment, type):
        partner_agent_1 = Q(agent__username__startswith='asiacollect')
        partner_agent_2 = Q(agent__username__startswith='mbacollection')
        partner_agent_3 = Q(agent__username__startswith='telmark')
        partner_agent_4 = Q(agent__username__startswith='collmatra')
        assignment = CollectionAgentAssignment.objects.prefetch_related('agent')\
                                                      .filter(payment=payment,
                                                              unassign_time__isnull=True)\
                                                      .filter(partner_agent_1 |
                                                              partner_agent_2 |
                                                              partner_agent_3 |
                                                              partner_agent_4)\
                                                      .order_by('id').last()
        if assignment:
            agent = assignment.agent
            agent_username = agent.username
            vendor = agent_username.split(agent_username[-1])[0]
            role = convert_agentassignment_type_to_usergroup(type)
            username = '{}{}'.format(vendor, role[-1])
            proper_agent = Agent.objects.filter(
                user_extension=vendor,
                user__groups__name=role,
                user__username=username).last()
            if proper_agent:
                return proper_agent.user
        return None

    def process_assign_loan_agent(self, payments, agents, last_agent, type):
        """
        Check whether assignment is handled by partner agent or not
        if not check whether assignment is handled by in house agent or not
        if not possibly its new agent assignment, assign a new agent for that
        """
        length_user_list = len(agents)
        # get last agent index
        user_index = -1
        if last_agent in agents:
            user_index = agents.index(last_agent)
        agents_count = get_agent_assigned_count(agents, type)

        # assign_agent in loan
        for payment in payments:
            if user_index == length_user_list - 1:
                user_index = 0
            else:
                user_index += 1
            with transaction.atomic():
                loan = payment.loan
                # to get agent partner if payment is handled by agent in status before
                assign_to_agent = self.get_or_none_partner_agent_by_payment(payment, type)
                rr_found_agent = assign_to_agent

                if not assign_to_agent:
                    rr_found_agent = min_assigned_agent(agents_count)
                    # below is old rule
                    # to get agent that already handle previous payment in bucket
                    # assign_to_agent = self.get_or_none_agent_to_assign_by_loan(loan, type)
                    # if assign_to_agent:
                    #    rr_found_agent = min_assigned_agent(agents_count)

                    # if not assign_to_agent:
                    #     assign random agent for payment first time into bucket
                    #     assign_to_agent = agents[user_index]
                    #     find agent with least payments assigned
                    #     rr_found_agent = min_assigned_agent(agents_count)

                assign_time = timezone.localtime(timezone.now())
                # unassign previous assignment bucket
                CollectionAgentAssignment.objects.filter(
                    loan=loan,
                    unassign_time__isnull=True
                ).update(unassign_time=assign_time)
                # create assignment for loan
                CollectionAgentAssignment.objects.create(loan=loan,
                                                         payment=payment,
                                                         agent=rr_found_agent,
                                                         type=type,
                                                         assign_time=assign_time)
                # update agent_count
                for agent_count in agents_count:
                    if agent_count['agent'] == rr_found_agent:
                        agent_count['count'] += 1

    def process_set_agent_collect(self, payment):
        # check range days
        today = timezone.localtime(timezone.now()).date()
        range = payment.due_late_days
        # ignore agent collect for not overdue payment
        if range < 1:
            return

        # check agent assignment
        loan = payment.loan
        assignments = CollectionAgentAssignment.objects.filter(
            loan=loan, unassign_time__isnull=True).order_by('payment_id')

        if not assignments:
            return

        # check already collect
        type = convert_range_day_to_agentassignment_type(range)
        agent_assignment_collected = assignments.filter(
            payment=payment, type=type, collected_by__isnull=False,
            collect_date__isnull=False).order_by('payment_id')
        if agent_assignment_collected:
            return

        # check collect today
        assignment = assignments.filter(payment=payment, type=type).last()
        agent_assignment_today = assignments.filter(collect_date=today).last()

        # create assignment to default agent when payment is not have assigment
        if not assignment:
            default_agent = User.objects.get(pk=settings.DEFAULT_USER_ID)
            assignment = CollectionAgentAssignment.objects.create(
                loan=loan,
                payment=payment,
                agent=default_agent,
                type=type,
                assign_time=timezone.now())
        if agent_assignment_today:
            agent = agent_assignment_today.agent
        else:
            agent = assignment.agent
        assignment.collected_by = agent
        assignment.collect_date = today
        assignment.save()

    def get_bucket_history_agent(self, payment):
        assignments = CollectionAgentAssignment.objects\
                                               .select_related('agent')\
                                               .filter(payment=payment['id'])\
                                               .order_by('type', '-cdate')\
                                               .distinct('type')\
                                               .values('type',
                                                       'agent_id',
                                                       'agent__username')
        for assignment in assignments:
            payment[agent_map[assignment['type']]] = dict(
                id=assignment['agent_id'],
                username=assignment['agent__username'])
            payment['agent_type'] = assignment['type']
        return payment

    def get_current_payment_assignment(self, payment, range_day=None):
        """
            get active payment assignment
        """
        hour = timezone.localtime(timezone.now()).hour
        assignments = CollectionAgentAssignment.objects.filter(
            loan=payment.loan,
            unassign_time__isnull=True).order_by('id')
        if range_day is None:
            range_day = payment.due_late_days

        if range_day not in (30, 60, 90) and hour < 5:
            type = convert_range_day_to_agentassignment_type(range_day)
            assignment = assignments.filter(type=type).last()
        else:
            assignment = assignments.last()
        return assignment

    def get_previous_assignment(self, loan, event_date):
        assignment = CollectionAgentAssignment.objects.filter(loan=loan)\
                                                      .filter(Q(unassign_time__date=event_date) | \
                                                              Q(unassign_time__isnull=True))\
                                                      .order_by('id').last()
        return assignment

    def get_agent_collect(self, payment, event_date):
        range_day = (event_date - payment.due_date).days
        assignment = self.get_current_payment_assignment(payment, range_day)
        if not assignment:
            previous_assignment = self.get_previous_assignment(payment.loan, event_date)
            if not previous_assignment:
                try:
                    default_agent = User.objects.get(pk=settings.DEFAULT_USER_ID)
                except User.DoesNotExist:
                    return
                return default_agent
            return previous_assignment.agent

        return assignment.agent

    def unassign_payment(self, payment, event_date=None):
        range_day = None
        if event_date is not None:
            range_day = (event_date - payment.due_date).days
        assignment = self.get_current_payment_assignment(payment, range_day)
        if not assignment:
            return

        current_time = timezone.now()
        assignment.update_safely(unassign_time=current_time)
        logger.info({
            'unassign_payment': assignment.payment_id,
            'agent': assignment.agent_id,
            'unassign_time': current_time
        })
