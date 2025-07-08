import json
import logging
from datetime import timedelta
from typing import Union

from celery.task import task
from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.template.loader import get_template
from django.utils import timezone

from juloserver.customer_module.constants import (
    CUSTOMER_APPLICATION_MAP_FIELDS,
    ConsentWithdrawal,
)
from juloserver.customer_module.models import (
    ConsentWithdrawalRequest,
    CustomerDataChangeRequest,
    WebConsentWithdrawalRequest,
)
from juloserver.julo.clients import get_julo_email_client, get_julo_sentry_client
from juloserver.julo.exceptions import EmailNotSent, JuloInvalidStatusChange
from juloserver.julo.models import (
    Customer,
    CustomerFieldChange,
    EmailHistory,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import get_file_from_oss
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@task(queue="application_customer_sync")
def sync_customer_data_with_application(
    customer_id: int,
    fields: Union[list, None]=None,
) -> (int, dict):
    """
    Sync customer data with application data
    Args:
        customer_id (int): The customer primary key
        fields (list | None): List of fields that needs to be sync

    Returns:
        (int, dict): Tuple of customer id and sync values
    """
    customer = Customer.objects.get(id=customer_id)
    account = customer.account
    application = account.get_active_application() if account else customer.last_application
    application = application if application else customer.application_set.last()

    if not application:
        logger.info(
            {
                "message": "No application found for customer",
                "action": "sync_customer_data_with_application",
                "customer_id": customer_id,
            }
        )
        return customer_id, {}

    processing_fields = fields if fields else CUSTOMER_APPLICATION_MAP_FIELDS.keys()
    sync_values = {}
    field_changes = []
    for customer_field in processing_fields:
        if customer_field not in CUSTOMER_APPLICATION_MAP_FIELDS:
            continue

        application_value = getattr(application, CUSTOMER_APPLICATION_MAP_FIELDS[customer_field])
        customer_value = getattr(customer, customer_field)

        if application_value != customer_value:
            sync_values[customer_field] = application_value
            try:
                field_changes.append(
                    CustomerFieldChange(
                        customer=customer,
                        application=application,
                        field_name=customer_field,
                        old_value=customer_value,
                        new_value=(
                            application_value[:199]
                            if isinstance(application_value, str) and application_value is not None
                            else application_value
                        )
                    )
                )
                setattr(customer, customer_field, application_value)
            except Exception as e:
                logger.info(
                    {
                        "message": "Exception happens",
                        "action": "sync_customer_data_with_application",
                        "customer_id": customer_id,
                        "application_id": application.id,
                        "customer_field": customer_field,
                        "customer_value": application_value,
                        "application_value": customer_value,
                        "sync_values": sync_values,
                        "exception_msg": e,
                    }
                )

    if not sync_values:
        return customer_id, {}

    logger.info(
        {
            "message": "Success Syncing customer data with application",
            "action": "sync_customer_data_with_application",
            "customer_id": customer_id,
            "application": application.id,
            "sync_values": sync_values,
            "processing_fields": processing_fields,
        }
    )
    with transaction.atomic():
        customer.save(update_fields=list(sync_values.keys()))
        CustomerFieldChange.objects.bulk_create(field_changes)

    return customer_id, sync_values


@task(queue='application_low')
def send_customer_data_change_request_notification_email(customer_data_change_request_id: int):
    """
    Queue task to send customer data change request via Email

    Args:
        customer_data_change_request_id: int
    """
    from juloserver.customer_module.services.customer_related import (
        CustomerDataChangeRequestNotification,
    )

    change_request = CustomerDataChangeRequest.objects.get(id=customer_data_change_request_id)
    notification = CustomerDataChangeRequestNotification(change_request)
    return customer_data_change_request_id, notification.send_email()


@task(queue='application_low')
def send_customer_data_change_request_notification_pn(customer_data_change_request_id: int):
    """
    Queue task to send customer data change request via PN

    Args:
        customer_data_change_request_id: int
    """
    from juloserver.customer_module.services.customer_related import (
        CustomerDataChangeRequestNotification,
    )

    change_request = CustomerDataChangeRequest.objects.get(id=customer_data_change_request_id)
    notification = CustomerDataChangeRequestNotification(change_request)
    return customer_data_change_request_id, notification.send_pn()


@task(name='populate_customer_xid', queue='retrofix_normal')
def populate_customer_xid(limit_count=150_000):
    """
    Task to populate customer xid for customers who does not have customer xid

    Args:
        limit_count: Total data limit that will be processed each call, defaulted to 100.000
    """

    customers = Customer.objects.filter(customer_xid=None)[:limit_count]
    for customer in customers:
        try:
            Customer.objects.generate_and_update_customer_xid(customer)
        except Exception as e:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            logger.exception('populate_customer_xid, data={} | err={}'.format(customer, e))


@task(queue='normal')
def cleanup_payday_change_request_from_redis():
    from juloserver.customer_module.services.customer_related import (
        delete_document_payday_customer_change_request_from_oss,
    )

    """
    Clears the payday change requests stored in Redis.

    This task:
    1. Retrieves all payday change request keys from Redis
    2. Processes each request by deleting associated images from OSS
    3. Removes the corresponding Redis entries
    4. Logs success and error statistics

    Returns:
        dict: Summary of processing results
    """

    redis_client = get_redis_client()
    keys = redis_client.get_keys('customer_data_payday_change:*')
    if not keys:
        logger.info("No payday change requests found to clear")
        return

    processed_count = 0
    error_count = 0
    for key in keys:
        data = redis_client.get(key)
        if not data:
            continue
        try:
            json_data = json.loads(data)
            image_id = json_data["payday_change_proof_image_id"]
            delete_document_payday_customer_change_request_from_oss(int(image_id))
            redis_client.delete_key(key)
            processed_count += 1
        except json.JSONDecodeError:
            error_count += 1
            sentry_client.captureMessage(
                "Invalid JSON data customer payday change request",
                extra={
                    'key': key,
                    'data': data,
                },
            )
            logger.error("Invalid JSON data for key: " + key)
            continue
        except Exception as e:
            error_count += 1
            sentry_client.captureMessage(
                "Error processing key customer payday change request",
                extra={
                    'key': key,
                    'data': data,
                },
            )
            logger.error("Error processing key " + key + ": " + str(e))
            continue

    logger.info(
        "Payday Change Request Cleanup Complete:\n"
        "- Successfully processed: " + str(processed_count) + "\n"
        "- Errors encountered: " + str(error_count)
    )


@task(queue='application_high')
def auto_approval_consent_withdrawal():
    from juloserver.account.services.account_related import (
        process_change_account_status,
    )
    from juloserver.julo.services import process_application_status_change

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
                    logger.error(
                        {
                            'action': action_attr["log_error"],
                            'message': 'cannot update application status to withdraw consent data',
                            'customer_id': customer.id,
                            'application_id': application.id,
                            'current_app_status': application.application_status_id,
                            'target_app_status': ApplicationStatusCodes.CUSTOMER_CONSENT_WITHDRAWED,
                            "withdrawal_request_id": withdrawal_request.id,
                            'error': str(e),
                        }
                    )
                    sentry_client.captureException()
                    continue

            send_consent_withdraw_email.delay("auto_approve", customer_id=customer.id)

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


@task(queue='application_high')
def send_consent_withdraw_email(action, customer_id=None, email=None):
    """
    Queue task to send consent withdraw action success email

    Args:
        customer_id: int
    """
    action_attr = ConsentWithdrawal.MAPPING_ACTION_ATTRS[action]
    customer = None
    error_message = None

    if email:
        fullname = 'Pelanggan Setia Julo'
        gender = 'Bapak/Ibu'
    else:
        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            return

        detokenize_customers = detokenize_for_model_object(
            PiiSource.CUSTOMER,
            [
                {
                    'object': customer,
                }
            ],
            force_get_local_data=True,
        )
        customer = detokenize_customers[0]
        email = customer.email
        fullname = customer.get_fullname if customer.fullname else 'Pelanggan Setia Julo'

        gender_title = {'Pria': 'Bapak', 'Wanita': 'Ibu'}
        gender = gender_title.get(customer.gender, 'Bapak/Ibu')

    subject = action_attr["email_subject"]
    variable = {"title": gender, "fullname": fullname}
    template = get_template("consent_withdrawal/" + action_attr["email_template"] + ".html")
    html_content = template.render(variable)

    message_id = None
    try:
        status, _, headers = get_julo_email_client().send_email(
            subject,
            html_content,
            email,
            'cs@julofinance.com',
        )
        if status == 202:
            status = 'sent_to_sendgrid'
            error_message = None
        message_id = headers.get('X-Message-Id')
    except Exception as e:
        status = 'error'
        error_message = str(e)
        if not isinstance(e, EmailNotSent):
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            logger.exception(
                'send_consent_withdrawal_request_email_failed, data={} | err={}'.format(customer, e)
            )

    EmailHistory.objects.create(
        to_email=email,
        subject=subject,
        sg_message_id=message_id,
        template_code=action_attr["email_template"],
        customer=customer,
        status=str(status),
        error_message=error_message,
    )
    logger.info(
        {
            "message": "Success sending consent withdraw " + action + " email",
            "action": "success_send_consent_withdraw_" + action + "_email",
            "customer_id": customer_id,
            "status": status,
            "error_message": error_message,
        }
    )


def handle_web_consent_withdrawal_request(data: dict, ip_address: str):
    from juloserver.customer_module.services.customer_related import (
        delete_ktp_and_selfie_file_from_oss,
        forward_web_consent_withdrawal_request_to_ops,
    )

    """
    Handle web consent withdrawal request.

    Args:
        data (dict): Dictionary containing the following keys:
            - nik (str): National identification number of the customer.
            - phone (str): Phone number of the customer.
            - email (str): Email address of the customer.
            - fullname (str): Full name of the customer.
            - reason (str): Reason for consent withdrawal.
            - details (str): Additional reason detail for the consent withdrawal.
            - image_ktp_filepath (str): File path of the KTP image.
            - image_selfie_filepath (str): File path of the selfie image.

    Returns:
        None
    """

    try:
        # Try to get the customer based on nik, phone, and email
        customer = Customer.objects.get(
            nik=data["nik"],
            phone=data["phone"],
            email=data["email"],
        )

        detokenize_customers = detokenize_for_model_object(
            PiiSource.CUSTOMER,
            [
                {
                    'object': customer,
                }
            ],
            force_get_local_data=True,
        )
        customer = detokenize_customers[0]

    except Customer.DoesNotExist:
        WebConsentWithdrawalRequest.objects.create(
            full_name=data["fullname"],
            nik=data["nik"],
            phone=data["phone"],
            email=data["email"],
            reason=data["reason"],
            reason_detail=data["details"],
            ip_address=ip_address,
        )

        # Send failure email to the customer
        send_consent_withdraw_email.delay("reject", email=data["email"])

        # Delete ktp and selfie file from oss
        delete_ktp_and_selfie_file_from_oss(
            data["image_ktp_filepath"], data["image_selfie_filepath"]
        )

        return

    # Create a WebConsentWithdrawalRequest with customer_id
    WebConsentWithdrawalRequest.objects.create(
        nik=data["nik"],
        full_name=data["fullname"],
        phone=data["phone"],
        email=data["email"],
        reason=data["reason"],
        reason_detail=data["details"],
        customer_id=customer.id,
        ip_address=ip_address,
    )

    # Get images from blob
    image_ktp = get_file_from_oss(settings.OSS_PUBLIC_BUCKET, data["image_ktp_filepath"])
    image_selfie = get_file_from_oss(settings.OSS_PUBLIC_BUCKET, data["image_selfie_filepath"])

    # Forward the request to operations team cs@julo.co.id
    forward_web_consent_withdrawal_request_to_ops(
        fullname=data["fullname"],
        phone=data["phone"],
        email=data["email"],
        reason=data["reason"],
        reason_detail=data["details"],
        image_ktp=image_ktp,
        image_ktp_file_path=data["image_ktp_filepath"],
        image_selfie=image_selfie,
        image_selfie_file_path=data["image_selfie_filepath"],
    )

    # Send success email to the customer email
    send_consent_withdraw_email.delay("request", customer_id=customer.id)

    # Delete ktp and selfie file from oss
    delete_ktp_and_selfie_file_from_oss(data["image_ktp_filepath"], data["image_selfie_filepath"])

    return
