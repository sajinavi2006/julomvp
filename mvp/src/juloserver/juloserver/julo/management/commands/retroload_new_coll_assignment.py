from builtins import str
from django.db import transaction
from django.utils import timezone
from datetime import timedelta, time
from django.core.management.base import BaseCommand
from juloserver.julo.models import (AgentAssignmentOld,
                                    CollectionAgentAssignment,
                                    Loan)
from juloserver.julo.statuses import LoanStatusCodes
from django.contrib.auth.models import User
from juloserver.julo.constants import AgentAssignmentTypeConst
from juloserver.portal.object.dashboard.constants import JuloUserRoles


class Command(BaseCommand):
    help = 'load AgentAssignment. from Agent Assignment to CollectionAgentAssignment'

    def handle(self, *args, **options):
        """
        this will move oldest unpaid payment for each loan in agent assignment table
        to the new collection_agent_assignment table and implement the new flow
        card https://juloprojects.atlassian.net/browse/END-260
        """
        assigned_loans = AgentAssignmentOld.objects.select_related('loan')\
                                                .filter(unassign_time__isnull=True,
                                                        collected_by__isnull=True)\
                                                .distinct('loan')\
                                                .order_by('loan', 'type')

        assigned_payment_ids = []
        for loan in assigned_loans:
            oldest_unpaid_payment = loan.loan.get_oldest_unpaid_payment()
            if oldest_unpaid_payment:
                assigned_payment_ids.append(oldest_unpaid_payment.id)

        assignments = AgentAssignmentOld.objects.filter(
            payment_id__in=assigned_payment_ids,
            unassign_time__isnull=True).order_by('payment_id', '-type', 'id')\
                                       .distinct('payment_id')\
                                       .values('loan_id',
                                               'payment_id',
                                               'assign_time',
                                               'type',
                                               'agent_id')
        self.stdout.write(self.style.WARNING(
            "Start Move Assignment for {} payments".format(len(assignments))))

        try:
            with transaction.atomic():
                new_assignments = []
                for assignment in assignments:
                    new_assignments.append(CollectionAgentAssignment(**assignment))
                CollectionAgentAssignment.objects.bulk_create(new_assignments)
        except Exception as e:
            self.stdout.write(self.style.ERROR(str(e)))

        self.stdout.write(self.style.SUCCESS(
            'Done Move Assignment for {} payments'.format(len(assignments))))
