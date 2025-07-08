from builtins import str
from django.db import transaction
from django.utils import timezone
from datetime import timedelta, time
from django.core.management.base import BaseCommand
from juloserver.julo.models import AgentAssignmentOld, Loan
from juloserver.julo.statuses import LoanStatusCodes
from django.contrib.auth.models import User
from juloserver.julo.constants import AgentAssignmentTypeConst
from juloserver.portal.object.dashboard.constants import JuloUserRoles

def get_agent_by_index(current_index, agents):
    length_agent = len(agents)
    # assign_agent in loan
    if current_index == length_agent - 1:
        current_index = 0
    else:
        current_index += 1
    return current_index, agents[current_index]

def create_agent_assignment(application, loan, payments, agents, type, today, current_index):
    if not payments:
        return current_index
    current_index, agent = get_agent_by_index(current_index, agents)
    for payment in payments:
        AgentAssignmentOld.objects.create(
                    application= application,
                    loan= loan,
                    payment= payment,
                    agent= agent,
                    type= type,
                    assign_time= today)
    return current_index

class Command(BaseCommand):
    help = 'load AgentAssignmentOld. from field loan.agent_2 and loan.agent_3'

    def handle(self, *args, **options):
        agent_assignment = AgentAssignmentOld.objects.first()
        if agent_assignment:
            self.stdout.write(self.style.SUCCESS('Already Record'))
            return

        DPD1_DPD29 = AgentAssignmentTypeConst.DPD1_DPD29
        DPD30_DPD59 = AgentAssignmentTypeConst.DPD30_DPD59
        DPD60_DPD89 = AgentAssignmentTypeConst.DPD60_DPD89
        DPD90PLUS = AgentAssignmentTypeConst.DPD90PLUS
        list_loan_id_late_active = [
            LoanStatusCodes.LOAN_1DPD,
            LoanStatusCodes.LOAN_5DPD,
            LoanStatusCodes.LOAN_30DPD,
            LoanStatusCodes.LOAN_60DPD,
            LoanStatusCodes.LOAN_90DPD,
            LoanStatusCodes.LOAN_120DPD,
            LoanStatusCodes.LOAN_150DPD,
            LoanStatusCodes.LOAN_180DPD]
        loans = Loan.objects.select_related('application').filter(loan_status__status_code__in=list_loan_id_late_active)
        agents_2 = User.objects.filter(groups__name=JuloUserRoles.COLLECTION_AGENT_2, is_active=True).order_by('id')
        agents_3 = User.objects.filter(groups__name=JuloUserRoles.COLLECTION_AGENT_3, is_active=True).order_by('id')
        agents_4 = User.objects.filter(groups__name=JuloUserRoles.COLLECTION_AGENT_4, is_active=True).order_by('id')
        agents_5 = User.objects.filter(groups__name=JuloUserRoles.COLLECTION_AGENT_5, is_active=True).order_by('id')
        index_agent_2 = -1
        index_agent_3 = -1
        index_agent_4 = -1
        index_agent_5 = -1

        try:
            with transaction.atomic():
                for loan in loans:
                    today = timezone.localtime(timezone.now()).date()
                    application = loan.application
                    payments = loan.payment_set.all().overdue()
                    if not payments:
                        continue
                    index_agent_2 = create_agent_assignment(application, loan, payments, agents_2, DPD1_DPD29, today, index_agent_2)
                    thirty_days_ago = today - timedelta(days=29)
                    sixty_days_ago = today - timedelta(days=59)
                    ninety_days_ago = today - timedelta(days=89)
                    agent_3_payments = payments.filter(due_date__lt=thirty_days_ago)
                    agent_4_payments = payments.filter(due_date__lt=sixty_days_ago)
                    agent_5_payments = payments.filter(due_date__lt=ninety_days_ago)
                    index_agent_3 = create_agent_assignment(application, loan, agent_3_payments, agents_3, DPD30_DPD59, today, index_agent_3)
                    index_agent_4 = create_agent_assignment(application, loan, agent_4_payments, agents_4, DPD60_DPD89, today, index_agent_4)
                    index_agent_5 = create_agent_assignment(application, loan, agent_5_payments, agents_5, DPD90PLUS, today, index_agent_5)
        except Exception as e:
            self.stdout.write(self.style.ERROR(str(e)))

        self.stdout.write(self.style.SUCCESS('Done'))
