from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from juloserver.julo.constants import AgentAssignmentTypeConst
from juloserver.julo.models import Agent
from juloserver.julo.models import AgentAssignmentOld
from juloserver.julo.services2.agent import convert_agentassignment_type_to_usergroup


class Command(BaseCommand):
    help = 'retroactively reassign collection vendor agent'

    def handle(self, *args, **options):
        DPD30_DPD59 = AgentAssignmentTypeConst.DPD30_DPD59
        DPD60_DPD89 = AgentAssignmentTypeConst.DPD60_DPD89
        DPD90PLUS = AgentAssignmentTypeConst.DPD90PLUS
        vendors = ['telmark', 'asiacollect', 'mbacollection']
        type_list = [DPD30_DPD59, DPD60_DPD89, DPD90PLUS]
        partner_agent_1 = Q(agent__username__startswith='asiacollect')
        partner_agent_2 = Q(agent__username__startswith='mbacollection')
        partner_agent_3 = Q(agent__username__startswith='telmark')
        agent_assignments = AgentAssignmentOld.objects.filter(
            type__in=type_list, unassign_time__isnull=True).filter(
                    partner_agent_1 | partner_agent_2 | partner_agent_3)

        today = timezone.now()
        for agent_assignment in agent_assignments:
            try:
                agent_assignment.unassign_time = today
                agent_assignment.save()
                agent_username = agent_assignment.agent.username
                vendor = agent_username.split(agent_username[-1])[0]
                role = convert_agentassignment_type_to_usergroup(agent_assignment.type)
                proper_agent = Agent.objects.filter(user_extension=vendor, user__groups__name=role).last()
                new_agent_assignment = AgentAssignmentOld.objects.create(application= agent_assignment.application,
                                                                     loan= agent_assignment.loan,
                                                                     payment=agent_assignment.payment,
                                                                     agent= proper_agent.user,
                                                                     type= agent_assignment.type,
                                                                     assign_time= today)

                self.stdout.write(self.style.SUCCESS(
                    'success reassign agent payment {} loan {} from agent {} to {}'.format(
                    agent_assignment.payment.id, agent_assignment.loan.id, agent_username, proper_agent.user.username)))
            except Exception as e:
                self.stdout.write(self.style.ERROR('failed reassign payment {} - {}'.format(
                    agent_assignment.payment.id, e)))

        self.stdout.write(self.style.SUCCESS('Retrofix Vendor Agent Assignment Done'))
