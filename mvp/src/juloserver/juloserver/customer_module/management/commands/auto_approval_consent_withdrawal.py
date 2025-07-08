import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Max
from django.utils import timezone

from juloserver.account.services.account_related import process_change_account_status
from juloserver.customer_module.constants import ConsentWithdrawal
from juloserver.customer_module.models import ConsentWithdrawalRequest
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloInvalidStatusChange
from juloserver.julo.models import Customer
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class Command(BaseCommand):
    help = (
        "Task to auto-approve consent withdrawal requests for customers "
        "who have not been approved yet."
    )

    def handle(self, *args, **options):
        """
        Task to auto-approve consent withdrawal requests for customers who have not
        been approved yet.
        """
        # Calculate the date 2 days ago
        two_days_ago = timezone.now() - timedelta(days=2)

        # First get the latest request ID for each customer
        latest_ids = (
            ConsentWithdrawalRequest.objects.values('customer_id')
            .annotate(latest_id=Max('id'))
            .values_list('latest_id', flat=True)
        )

        # Get the most recent for each customer who have status 'requested'
        # that created more than 2 days ago
        withdrawal_requests = ConsentWithdrawalRequest.objects.filter(
            id__in=latest_ids,
            status=ConsentWithdrawal.RequestStatus.REQUESTED,
            cdate__lte=two_days_ago,
        )

        action_attr = ConsentWithdrawal.MAPPING_ACTION_ATTRS["auto_approve"]
        # Process each request
        for withdrawal_request in withdrawal_requests:
            customer = Customer.objects.filter(id=withdrawal_request.customer_id).first()
            if not customer:
                logger.info(
                    {
                        "message": "Customer not found",
                        "action": "auto_approval_consent_withdrawal",
                        "withdrawal_request_id": withdrawal_request.id,
                    }
                )
                sentry_client.captureException()
                continue
            try:
                ConsentWithdrawalRequest.objects.create(
                    customer_id=customer.id,
                    user_id=customer.user_id,
                    email_requestor=withdrawal_request.email_requestor,
                    status=action_attr["to_status"],
                    source=withdrawal_request.source,
                    application_id=withdrawal_request.application_id,
                    reason=withdrawal_request.reason,
                    detail_reason=withdrawal_request.detail_reason,
                    action_by=0,
                    action_date=timezone.localtime(timezone.now()),
                )

                account = customer.account_set.last()
                if account:
                    process_change_account_status(
                        account=account,
                        new_status_code=action_attr["account_status"],
                        change_reason=ConsentWithdrawal.StatusChangeReasons.AUTO_APPROVE_REASON,
                    )

                # Bulk process applications
                for application in customer.application_set.all():
                    try:
                        if not application.is_julo_one_or_starter():
                            continue

                        if application.status == ApplicationStatusCodes.LOC_APPROVED:
                            continue
                        else:
                            process_application_status_change(
                                application.id,
                                ApplicationStatusCodes.CUSTOMER_CONSENT_WITHDRAWED,
                                action_attr["reason"],
                            )
                    except (JuloInvalidStatusChange, Exception) as e:
                        error_message = 'cannot update application status to withdraw consent data'
                        target_status = ApplicationStatusCodes.CUSTOMER_CONSENT_WITHDRAWED
                        logger.error(
                            {
                                'action': action_attr["log_error"],
                                'message': error_message,
                                'customer_id': customer.id,
                                'application_id': application.id,
                                'current_app_status': application.application_status_id,
                                'target_app_status': target_status,
                                "withdrawal_request_id": withdrawal_request.id,
                                'error': str(e),
                            }
                        )
                        sentry_client.captureException()
                        continue

            except Exception as e:
                logger.error(
                    {
                        "message": "Error auto-approving consent withdrawal request",
                        "action": "auto_approval_consent_withdrawal",
                        "withdrawal_request_id": withdrawal_request.id,
                        "error": str(e),
                    }
                )
                sentry_client.captureException()
                continue
