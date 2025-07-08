from celery import task
from juloserver.julo.constants import AgentAssignmentTypeConst
from juloserver.julo.models import Loan
from juloserver.julo.partners import PartnerConstant
from .services import get_agent_service_for_bucket

# @task(name="assign_collection_agent")
# def assign_collection_agent():
#     agent_assignment_buckets = (AgentAssignmentTypeConst.DPD11_DPD40,
#                                 AgentAssignmentTypeConst.DPD41_DPD70,
#                                 AgentAssignmentTypeConst.DPD71_DPD90,
#                                 AgentAssignmentTypeConst.DPD91PLUS)
#
#     active_loans = Loan.objects.prefetch_related('payment_set')\
#                     .not_paid_active()\
#                     .exclude(application__partner__name__in=PartnerConstant.form_partner())
#     agent_service = get_agent_service_for_bucket()
#
#     for assignment_type in agent_assignment_buckets:
#         payments, agents = agent_service.get_data_assign_agent(assignment_type,
#                                                                active_loans)
#
#         if payments and agents:
#             agent_service.process_assign_loan_agent(payments, agents, assignment_type)
#
#     agent_service.unassign_bucket2_payments_going_for_bucket3()
