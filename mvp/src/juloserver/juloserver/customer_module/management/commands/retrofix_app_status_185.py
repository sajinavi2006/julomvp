import logging
from django.core.management.base import BaseCommand
from django.db.models import Q
from juloserver.customer_module.constants import (
    AccountDeletionRequestStatuses,
    AccountDeletionStatusChangeReasons,
)

from juloserver.customer_module.models import AccountDeletionRequest
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.models import Application

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Correcting app status customer that have pending deletion request'

    def handle(self, *args, **options):
        pending_request_customer_ids = AccountDeletionRequest.objects.filter(
            request_status=AccountDeletionRequestStatuses.PENDING,
        ).values_list('customer_id', flat=True)

        applications = Application.objects.filter(
            Q(product_line_id=ProductLineCodes.J1)
            | Q(workflow_id__name=WorkflowConst.JULO_STARTER),
            customer_id__in=pending_request_customer_ids,
        ).exclude(application_status_id=ApplicationStatusCodes.CUSTOMER_ON_DELETION)

        for application in applications.iterator():
            try:
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.CUSTOMER_ON_DELETION,
                    AccountDeletionStatusChangeReasons.REQUEST_REASON,
                )
            except Exception as e:
                err_msg = {
                    'action': 'request_account_deletion',
                    'message': 'cannot update application status to deletion',
                    'customer_id': application.customer_id,
                    'application_id': application.id,
                    'current_app_status': application.application_status_id,
                    'target_app_status': ApplicationStatusCodes.CUSTOMER_ON_DELETION,
                    'error': str(e),
                }

                self.stdout.write(str(err_msg))
                logger.error(err_msg)

        self.stdout.write(self.style.SUCCESS('=========Finish========='))
