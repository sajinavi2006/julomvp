from django.core.management.base import BaseCommand
from django.utils import timezone

from juloserver.autodebet.models import AutodebetAPILog
from juloserver.autodebet.constants import (
    VendorConst,
    BRIErrorCode,
    AutodebetStatuses,
)
from juloserver.moengage.tasks import send_event_autodebet_bri_expiration_handler_task


class Command(BaseCommand):
    help = 'Helps to update the autodebet account for the expired BRI linking'

    def handle(self, *args, **options):

        bri_expired_autodebet_api_logs = AutodebetAPILog.objects.filter(
            vendor=VendorConst.BRI,
            response__icontains=BRIErrorCode.INVALID_PAYMENT_METHOD_ERROR,
        ).select_related('account').distinct('account_id')

        for bri_expired_autodebet_api_log in bri_expired_autodebet_api_logs.iterator():
            autodebet_account = bri_expired_autodebet_api_log.account.autodebetaccount_set.filter(
                vendor=VendorConst.BRI
            ).last()
            if autodebet_account and autodebet_account.is_use_autodebet:
                autodebet_account.update_safely(
                    deleted_request_ts=timezone.localtime(timezone.now()),
                    deleted_success_ts=timezone.localtime(timezone.now()),
                    is_deleted_autodebet=True,
                    is_use_autodebet=False,
                    is_force_unbind=True,
                    status=AutodebetStatuses.REVOKED,
                )
                send_event_autodebet_bri_expiration_handler_task.delay(
                    bri_expired_autodebet_api_log.account_payment.id,
                    bri_expired_autodebet_api_log.account.customer.id
                )
