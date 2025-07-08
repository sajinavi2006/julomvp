from django.core.management.base import BaseCommand
from django.utils import timezone
from juloserver.collection_vendor.models import (
    CollectionVendor,
    CollectionVendorAssignment,
    AgentAssignment
)
from juloserver.minisquad.services import (
    get_oldest_payment_ids_loans, get_oldest_unpaid_account_payment_ids)
from juloserver.collection_vendor.services import (
    format_and_create_single_movement_history)
from juloserver.collection_vendor.task import (
    assign_agent_for_julo_one_bucket_5,
    assign_agent_for_bucket_5)
from django.db import transaction


def check_active_vendor_assignment(payment_id, is_julo_one=False):
    today = timezone.localtime(timezone.now())
    if not is_julo_one:
        vendor_assignments = CollectionVendorAssignment.objects.filter(
            is_active_assignment=True,
            payment_id=payment_id
        )
    else:
        vendor_assignments = CollectionVendorAssignment.objects.filter(
            is_active_assignment=True,
            account_payment=payment_id
        )

    active_vendor_assigments = vendor_assignments.filter(
        vendor__is_active=True
    )

    deactivate_vendor_assignments = vendor_assignments.filter(
        vendor__is_active=False
    )

    if deactivate_vendor_assignments:
        deactivate_vendor_assignments.update(
            is_active_assignment=False, unassign_time=today, collected_ts=today
        )

    if active_vendor_assigments:
        return True

    return False


class Command(BaseCommand):
    help = 'retroload_bca_va_for_axiata_and_icare'

    def handle(self, *args, **options):
        today = timezone.localtime(timezone.now())
        deactivate_vendor_ids = CollectionVendor.objects.filter(is_active=False).values_list('id', flat=True)

        oldest_account_payment_ids = get_oldest_unpaid_account_payment_ids()
        j1_vendor_assignment_accounts = CollectionVendorAssignment.objects.filter(
            vendor_id__in=deactivate_vendor_ids,
            account_payment_id__isnull=False,
            account_payment_id__in=oldest_account_payment_ids,
            is_active_assignment=True
        ).distinct('account_payment_id')

        agent_ids = AgentAssignment.objects.filter(agent__is_active=True).values_list('agent_id', flat=True)

        count_data = j1_vendor_assignment_accounts.count()
        count_agent = agent_ids.count()

        if count_agent == 0:
            return

        count_for_each_agent = count_data / count_agent
        round_count_for_each_agent = round(count_for_each_agent)

        max_assigment = 1
        agent_index = 0

        for vendor_assignment in j1_vendor_assignment_accounts.iterator():
            with transaction.atomic():
                account_payment_id = vendor_assignment.account_payment_id
                if count_data <= count_agent:
                    agent_user_id = agent_ids[agent_index]
                    agent_index += 1
                    is_active = check_active_vendor_assignment(account_payment_id, True)
                    if is_active:
                        continue
                    assign_agent_for_julo_one_bucket_5.delay(agent_user_id, account_payment_id)

                    format_and_create_single_movement_history(
                        vendor_assignment.account_payment, None,
                        reason='retrofix_deactivate_vendor',
                        is_julo_one=True
                    )
                    continue
                elif max_assigment <= round_count_for_each_agent:
                    agent_user_id = agent_ids[agent_index]
                    if agent_index >= len(agent_ids):
                        agent_user_id = agent_ids.last()
                    max_assigment += 1
                    is_active = check_active_vendor_assignment(account_payment_id, True)
                    if is_active:
                        continue
                    assign_agent_for_julo_one_bucket_5.delay(agent_user_id, account_payment_id)
                    vendor_assignment.update_safely(
                        is_active_assignment=False, unassign_time=today, collected_ts=today)
                    format_and_create_single_movement_history(
                        vendor_assignment.account_payment, None,
                        reason='retrofix_deactivate_vendor',
                        is_julo_one=True
                    )
                    continue
                else:
                    max_assigment = 1
                    agent_index += 1
                    agent_user_id = agent_user_id = agent_ids[agent_index]
                    is_active = check_active_vendor_assignment(account_payment_id, True)
                    if is_active:
                        continue
                    assign_agent_for_julo_one_bucket_5.delay(agent_user_id, account_payment_id)
                    vendor_assignment.update_safely(
                        is_active_assignment=False, unassign_time=today, collected_ts=today)
                    format_and_create_single_movement_history(
                        vendor_assignment.account_payment, None,
                        reason='retrofix_deactivate_vendor',
                        is_julo_one=True
                    )

        oldest_payment_ids = get_oldest_payment_ids_loans()
        mtl_vendor_assignment_accounts = CollectionVendorAssignment.objects.filter(
            vendor_id__in=deactivate_vendor_ids,
            account_payment_id__isnull=True,
            payment_id__in=oldest_payment_ids,
            is_active_assignment=True
        ).distinct('payment_id')

        count_data = mtl_vendor_assignment_accounts.count()

        count_for_each_agent = count_data / count_agent
        round_count_for_each_agent = round(count_for_each_agent)

        max_assigment = 1
        agent_index = 0

        for vendor_assignment in mtl_vendor_assignment_accounts.iterator():
            with transaction.atomic():
                loan_id = vendor_assignment.payment.loan_id
                payment_id = vendor_assignment.payment_id
                if count_data <= count_agent:
                    agent_user_id = agent_ids[agent_index]
                    agent_index += 1
                    check_active_vendor_assignment(payment_id, False)
                    is_active = assign_agent_for_bucket_5.delay(agent_user_id, loan_id)
                    if is_active:
                        continue
                    vendor_assignment.update_safely(
                        is_active_assignment=False, unassign_time=today, collected_ts=today)
                    format_and_create_single_movement_history(
                        vendor_assignment.payment, None,
                        reason='retrofix_deactivate_vendor',
                        is_julo_one=False
                    )
                    continue
                elif max_assigment <= round_count_for_each_agent:
                    agent_user_id = agent_ids[agent_index]
                    if agent_index >= len(agent_ids):
                        agent_user_id = agent_ids.last()
                    max_assigment += 1
                    is_active = check_active_vendor_assignment(payment_id, False)
                    if is_active:
                        continue
                    assign_agent_for_bucket_5.delay(agent_user_id, account_payment_id)
                    vendor_assignment.update_safely(
                        is_active_assignment=False, unassign_time=today, collected_ts=today)
                    format_and_create_single_movement_history(
                        vendor_assignment.payment, None,
                        reason='retrofix_deactivate_vendor',
                        is_julo_one=False
                    )
                    continue
                else:
                    max_assigment = 1
                    agent_index += 1
                    agent_user_id = agent_user_id = agent_ids[agent_index]
                    is_active = check_active_vendor_assignment(payment_id, False)
                    if is_active:
                        continue
                    assign_agent_for_bucket_5.delay(agent_user_id, account_payment_id)
                    vendor_assignment.update_safely(
                        is_active_assignment=False, unassign_time=today, collected_ts=today)
                    format_and_create_single_movement_history(
                        vendor_assignment.payment, None,
                        reason='retrofix_deactivate_vendor',
                        is_julo_one=False)

        self.stdout.write(self.style.SUCCESS('Successfully retro load existing data'))
