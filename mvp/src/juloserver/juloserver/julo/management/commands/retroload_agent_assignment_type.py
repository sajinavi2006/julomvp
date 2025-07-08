from django.core.management.base import BaseCommand
from ...models import AgentAssignmentOld



class Command(BaseCommand):

    help = 'update the type field in agent assignment table'

    def handle(self, *args, **options):
        agents = AgentAssignmentOld.objects.all()
        for agent in agents:
            if agent.type == 'dpd1_dpd30':
                agent.type = 'dpd1_dpd29'
            elif agent.type == 'dpd31_dpd60':
                agent.type = 'dpd30_dpd59'
            elif agent.type == 'dpd61_dpd90':
                agent.type = 'dpd60_dpd89'
            else:
                agent.type = 'dpd90plus'
            agent.save()
