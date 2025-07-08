from builtins import str
import logging
import sys
from django.core.management.base import BaseCommand
from django.utils import timezone
from juloserver.collection_vendor.constant import CollectionAssignmentConstant
from juloserver.collection_vendor.models import (
    AgentAssignment,
    CollectionVendorAssignment,
    CollectionAssignmentHistory,
)
from juloserver.collection_vendor.services import (
    format_and_create_single_movement_history,
    create_record_movement_history,
)
from juloserver.julo.models import Payment
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.minisquad.constants import RedisKey
from juloserver.minisquad.services import (
    get_oldest_unpaid_account_payment_ids,
    get_oldest_payment_ids_loans)
from juloserver.account_payment.models import AccountPayment

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'Retroload double assignments on vendor'

    def handle(self, *args, **options):
        history_movement_record_data = []
        success_retro_account_payment_ids = []
        success_retro_payment_ids = []
        try:
            today_time = timezone.localtime(timezone.now())
            redisClient = get_redis_client()
            cached_oldest_account_payment_ids = redisClient.get_list(
                RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS)
            if not cached_oldest_account_payment_ids:
                oldest_account_payment_ids = get_oldest_unpaid_account_payment_ids()
            else:
                oldest_account_payment_ids = list(map(int, cached_oldest_account_payment_ids))
            cached_oldest_payment_ids = redisClient.get_list(RedisKey.OLDEST_PAYMENT_IDS)
            if not cached_oldest_payment_ids:
                oldest_payment_ids = get_oldest_payment_ids_loans(is_intelix=True)
            else:
                oldest_payment_ids = list(map(int, cached_oldest_payment_ids))
            # set is_active_assignment_false for not oldest account payment ids
            self.stdout.write(self.style.SUCCESS(
                'Start active assignment False for not oldest')
            )
            AgentAssignment.objects.filter(is_active_assignment=True).exclude(
                payment_id__in=oldest_payment_ids).update(
                is_active_assignment=False, unassign_time=today_time)
            CollectionVendorAssignment.objects.filter(is_active_assignment=True).exclude(
                payment_id__in=oldest_payment_ids).update(
                is_active_assignment=False, unassign_time=today_time)
            AgentAssignment.objects.filter(is_active_assignment=True).exclude(
                account_payment_id__in=oldest_account_payment_ids).update(
                is_active_assignment=False, unassign_time=today_time)
            CollectionVendorAssignment.objects.filter(is_active_assignment=True).exclude(
                account_payment_id__in=oldest_account_payment_ids).update(
                is_active_assignment=False, unassign_time=today_time)
            self.stdout.write(self.style.SUCCESS(
                'Start fix double assignment')
            )
            # fix double assignment
            double_account_payments = AccountPayment.objects.raw(
                "select * from (select account_payment_id, count(*) as c "
                "from ops.collection_vendor_assignment "
                "where is_active_assignment = True and payment_id "
                "is null group by account_payment_id) as foo where foo.c > 1;"
            )
            double_payments = Payment.objects.raw(
                "select * from (select payment_id, count(*) as c "
                "from ops.collection_vendor_assignment "
                "where is_active_assignment = True and account_payment_id "
                "is null group by payment_id ) as foo where foo.c > 1;"
            )
            # j1
            self.stdout.write(self.style.SUCCESS(
                'Start fix double assignment J1')
            )
            for account_payment_id in double_account_payments:
                vendor_assignments = CollectionVendorAssignment.objects.filter(
                    is_active_assignment=True, account_payment_id=account_payment_id
                ).order_by('cdate')
                if vendor_assignments.count() < 2:
                    continue
                account_payment = AccountPayment.objects.get(pk=account_payment_id)
                if account_payment.status_id in PaymentStatusCodes.paid_status_codes():
                    format_and_create_single_movement_history(
                        account_payment, None,
                        reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS['PAID'],
                        is_julo_one=True
                    )
                    vendor_assignments.update(
                        is_active_assignment=False, unassign_time=today_time)
                    success_retro_account_payment_ids.append(account_payment.id)
                    continue
                # keep first cdate for assignment
                last_vendor_assignment = vendor_assignments.last()
                last_vendor_assignment.update_safely(
                    is_active_assignment=False, unassign_time=today_time)
                format_and_create_single_movement_history(
                    account_payment, None,
                    reason="fix double assignment",
                    is_julo_one=True
                )
                history_movement_record_data.append(
                    CollectionAssignmentHistory(
                        account_payment=account_payment,
                        old_assignment=last_vendor_assignment.vendor,
                        assignment_reason="fix double assignment",
                    )
                )
                success_retro_account_payment_ids.append(account_payment.id)
            # mtl
            self.stdout.write(self.style.SUCCESS(
                'Start fix double assignment MTL')
            )
            for payment_id in double_payments:
                vendor_assignments = CollectionVendorAssignment.objects.filter(
                    is_active_assignment=True, payment_id=payment_id
                ).order_by('cdate')
                if vendor_assignments.count() < 2:
                    continue
                payment = Payment.objects.get(pk=payment_id)
                if payment.status_id in PaymentStatusCodes.paid_status_codes():
                    format_and_create_single_movement_history(
                        payment, None,
                        reason=CollectionAssignmentConstant.ASSIGNMENT_REASONS['PAID'],
                        is_julo_one=False
                    )
                    vendor_assignments.update(
                        is_active_assignment=False, unassign_time=today_time)
                    success_retro_payment_ids.append(payment.id)
                    continue
                # keep first cdate for assignment
                last_vendor_assignment = vendor_assignments.last()
                last_vendor_assignment.update_safely(
                    is_active_assignment=False, unassign_time=today_time)
                format_and_create_single_movement_history(
                    payment, None,
                    reason="fix double assignment",
                    is_julo_one=False
                )
                history_movement_record_data.append(
                    CollectionAssignmentHistory(
                        payment=payment,
                        old_assignment=last_vendor_assignment.vendor,
                        assignment_reason="fix double assignment",
                    )
                )
                success_retro_payment_ids.append(payment.id)
            create_record_movement_history(
                history_movement_record_data
            )
            self.stdout.write(self.style.SUCCESS("mtl"))
            self.stdout.write(self.style.SUCCESS(len(success_retro_payment_ids)))
            self.stdout.write(self.style.SUCCESS(success_retro_payment_ids))
            self.stdout.write(self.style.SUCCESS("j1"))
            self.stdout.write(self.style.SUCCESS(len(success_retro_account_payment_ids)))
            self.stdout.write(self.style.SUCCESS(success_retro_account_payment_ids))
            self.stdout.write(self.style.SUCCESS('Finish'))
        except Exception as e:
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error(error_msg)
            self.stdout.write(self.style.ERROR(error_msg))
