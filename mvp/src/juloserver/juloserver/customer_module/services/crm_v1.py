import logging
from typing import List, Optional, Union

from bulk_update.helper import bulk_update
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from juloserver.account.constants import AccountConstant
from juloserver.account.services.account_related import process_change_account_status
from juloserver.api_token.authentication import generate_new_token
from juloserver.customer_module.constants import (
    AccountDeletionRequestStatuses,
    AccountDeletionStatusChangeReasons,
    CustomerRemovalDeletionTypes,
    ConsentWithdrawal,
)
from juloserver.customer_module.tasks.account_deletion_tasks import (
    send_approved_deletion_request_success_email,
)
from juloserver.customer_module.utils.utils_crm_v1 import (
    check_if_customer_is_elgible_to_delete,
    get_customer_deletion_type,
    get_deletion_email_format,
    get_deletion_nik_format,
    get_deletion_phone_format,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    ApplicationFieldChange,
    ApplicationHistory,
    AuthUserFieldChange,
    Customer,
    CustomerFieldChange,
    CustomerRemoval,
)
from juloserver.julo.statuses import ApplicationStatusCodes, JuloOneCodes
from juloserver.customer_module.services.account_deletion import (
    customer_deleteable_application_check,
    get_allowed_product_line_for_deletion,
    get_deleteable_application,
    is_complete_deletion,
)
from juloserver.account.models import Account
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_realtime_basis,
)
from juloserver.customer_module.models import (
    ConsentWithdrawalRequest,
)
from juloserver.julo.exceptions import JuloInvalidStatusChange
from juloserver.customer_module.tasks.customer_related_tasks import (
    send_consent_withdraw_email,
)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def force_logout_user(customer):
    user = customer.user
    generate_new_token(user)


def deactivate_user(requested_user: User, customer: Customer, nik: str = None, phone: str = None):
    """
    - update the User table on deactivating the customer


    Args:
        requested_user (User): Get Agent user Object.
        customer (Customer): get Customer
        nik (str): get the customers nik.
        phone (str): get the customers phone.

    """

    field_changes = []
    user = customer.user

    if nik and user.username == nik:
        edited_username = get_deletion_nik_format(customer.id)
        field_changes.append(
            AuthUserFieldChange(
                user=user,
                customer=customer,
                field_name='username',
                old_value=user.username,
                new_value=edited_username,
                changed_by=requested_user,
            )
        )
        user.username = edited_username

    if phone and user.username == phone:
        edited_username = get_deletion_phone_format(customer.id)
        field_changes.append(
            AuthUserFieldChange(
                user=user,
                customer=customer,
                field_name='username',
                old_value=user.username,
                new_value=edited_username,
                changed_by=requested_user,
            )
        )
        user.username = edited_username

    if user.email:
        edited_email = get_deletion_email_format(user.email, customer.id)
        field_changes.append(
            AuthUserFieldChange(
                user=user,
                customer=customer,
                field_name='email',
                old_value=user.email,
                new_value=edited_email,
                changed_by=requested_user,
            )
        )
        user.email = edited_email

    field_changes.append(
        AuthUserFieldChange(
            user=user,
            customer=customer,
            field_name='is_active',
            old_value=user.is_active,
            new_value=False,
            changed_by=requested_user,
        )
    )
    user.is_active = False
    AuthUserFieldChange.objects.bulk_create(field_changes)
    user.save()


def update_customer_table_as_inactive(agent, customer, application):
    field_changes = []
    field_changes.append(
        CustomerFieldChange(
            customer=customer,
            application=application,
            field_name='can_reapply',
            old_value=customer.can_reapply,
            new_value=False,
            changed_by=agent,
        )
    )
    field_changes.append(
        CustomerFieldChange(
            customer=customer,
            application=application,
            field_name='is_active',
            old_value=customer.is_active,
            new_value=False,
            changed_by=agent,
        )
    )
    customer.can_reapply = False
    customer.is_active = False

    if customer.nik:
        edited_nik = get_deletion_nik_format(customer.id)
        field_changes.append(
            CustomerFieldChange(
                customer=customer,
                application=application,
                field_name='nik',
                old_value=customer.nik,
                new_value=edited_nik,
                changed_by=agent,
            )
        )
        customer.nik = edited_nik

    if customer.email:
        edited_email = get_deletion_email_format(customer.email, customer.id)
        field_changes.append(
            CustomerFieldChange(
                customer=customer,
                application=application,
                field_name='email',
                old_value=customer.email,
                new_value=edited_email,
                changed_by=agent,
            )
        )
        customer.email = edited_email

    if customer.phone:
        edited_phone = get_deletion_phone_format(customer.id)
        field_changes.append(
            CustomerFieldChange(
                customer=customer,
                application=application,
                field_name='phone',
                old_value=customer.phone,
                new_value=edited_phone,
                changed_by=agent,
            )
        )
        customer.phone = edited_phone
    CustomerFieldChange.objects.bulk_create(field_changes)
    customer.save()


def update_application_table_as_inactive(agent, applications):
    '''
    Deactivate the received applications

    Args:
        agent (User): action triggered by
        applications ([]Application): applications that want to be deactivated

    Return:
        []int: the deactivated application ids
        []int: unique product lines of the deleted application
    '''

    deleted_application_id = []
    field_changes = []
    history_changes = []
    product_lines = []
    allowed_product_line_deletion = get_allowed_product_line_for_deletion()
    for application in applications:
        if application.product_line_id not in allowed_product_line_deletion:
            continue

        if application.is_deleted:
            continue

        field_changes.append(
            ApplicationFieldChange(
                application=application,
                field_name='is_deleted',
                old_value=application.is_deleted,
                new_value=True,
                agent=agent,
            )
        )
        application.is_deleted = True

        if application.ktp:
            edited_ktp = get_deletion_nik_format(application.customer_id)
            field_changes.append(
                ApplicationFieldChange(
                    application=application,
                    field_name='ktp',
                    old_value=application.ktp,
                    new_value=edited_ktp,
                    agent=agent,
                )
            )
            application.ktp = edited_ktp

        if application.email:
            edited_email = get_deletion_email_format(application.email, application.customer_id)
            field_changes.append(
                ApplicationFieldChange(
                    application=application,
                    field_name='email',
                    old_value=application.email,
                    new_value=edited_email,
                    agent=agent,
                )
            )
            application.email = edited_email

        if application.mobile_phone_1:
            edited_phone = get_deletion_phone_format(application.customer_id)
            field_changes.append(
                ApplicationFieldChange(
                    application=application,
                    field_name='mobile_phone_1',
                    old_value=application.mobile_phone_1,
                    new_value=edited_phone,
                    agent=agent,
                )
            )
            application.mobile_phone_1 = edited_phone

        history_changes.append(
            ApplicationHistory(
                application=application,
                status_old=application.application_status_id,
                status_new=ApplicationStatusCodes.CUSTOMER_DELETED,
                changed_by=agent,
                change_reason='manual deletion',
            )
        )
        application.application_status_id = ApplicationStatusCodes.CUSTOMER_DELETED

        deleted_application_id.append(application.id)

        if application.product_line_id not in product_lines:
            product_lines.append(application.product_line_id)

    ApplicationFieldChange.objects.bulk_create(field_changes)
    ApplicationHistory.objects.bulk_create(history_changes)
    bulk_update(
        applications,
        update_fields=['ktp', 'is_deleted', 'email', 'mobile_phone_1', 'application_status_id'],
    )

    return deleted_application_id, product_lines


def process_revert_account_status_460(account, reason):
    old_status = account.accountstatushistory_set.filter(
        status_new=JuloOneCodes.ACCOUNT_DELETION_ON_REVIEW,
    ).last()
    if not old_status:
        logger.warning(
            {
                'action': 'process_revert_account_status_460',
                'message': """not reverting account's status:
                    there is no account_status_history for this account""",
                'customer_id': account.customer_id,
                'account_id': account.id,
            }
        )
        return

    process_change_account_status(
        account,
        old_status.status_old_id,
        change_reason=reason,
    )


def customer_deletion_process(user, customer, account, nik, phone, email, reason, agent=None):
    data = dict()
    is_customer_deleteable = customer_deleteable_application_check(customer)
    if not is_customer_deleteable:
        logger.warning(
            {
                'action': 'customer_deletion_process',
                'message': 'there is no application that can be deleted',
                'customer_id': customer.id,
            },
        )
        return data

    force_logout_user(customer)
    deleteable_applications = get_deleteable_application(customer)
    application = deleteable_applications.last()
    is_full_deletion = is_complete_deletion(customer)
    if is_full_deletion:
        deactivate_user(user, customer, nik, phone)
        update_customer_table_as_inactive(user, customer, application)

        if account:
            process_change_account_status(
                account=account,
                new_status_code=AccountConstant.STATUS_CODE.deactivated,
                change_reason=reason,
            )

    deactivated_app_ids, product_lines = update_application_table_as_inactive(
        user, deleteable_applications
    )
    if is_full_deletion or (deactivated_app_ids and len(deactivated_app_ids) > 0):
        for product_line in product_lines:
            product_line_app = (
                deleteable_applications.only('id')
                .filter(
                    product_line_id=product_line,
                )
                .order_by('-id')
                .first()
            )

            CustomerRemoval.objects.create(
                customer=customer,
                application_id=product_line_app.id,
                user=customer.user,
                reason=reason,
                nik=nik,
                email=email,
                phone=phone,
                added_by=agent,
                product_line_id=product_line,
            )

        data.update({'is_deleted': True, 'customer_id': customer.pk})
        if application:
            data.update({'application_id': application.pk})
        send_user_attributes_to_moengage_for_realtime_basis.delay(customer.id, 'is_deleted')

    send_approved_deletion_request_success_email.delay(customer.id)

    return data


def in_app_deletion_customer_requests(account_deletion_requests):
    for request in account_deletion_requests:
        try:
            customer = request.customer
            if customer.is_active is False:
                logger.error(
                    {
                        'method': 'inapp_account_deletion_deactivate_account',
                        'msg': 'customer not active',
                        'data': {'deletion_request_id': request.id, 'customer_id': customer.pk},
                    }
                )
                request.update_safely(request_status=AccountDeletionRequestStatuses.FAILED)
                continue

            user = customer.user
            account = customer.account

            status_id = None
            if account:
                status_id = account.status_id

            applications = customer.application_set.all()
            application = applications.last()

            if not check_if_customer_is_elgible_to_delete(customer, status_id, application):
                if account:
                    process_revert_account_status_460(
                        account, AccountDeletionStatusChangeReasons.CANCELED_BY_AGENT
                    )

                logger.error(
                    {
                        'method': 'inapp_account_deletion_deactivate_account',
                        'msg': 'Customer is not elgible',
                        'data': {
                            'deletion_request_id': request.id,
                            'customer_id': customer.pk,
                            'application_id': application.pk if application else None,
                        },
                    }
                )
                request.update_safely(request_status=AccountDeletionRequestStatuses.REVERTED)
                continue

            with transaction.atomic():
                reason = "Auto Approved In App Request"
                if request.verdict_reason:
                    reason = request.verdict_reason

                nik = customer.get_nik
                phone = customer.get_phone
                email = customer.get_email

                deletion_process = {}
                deletion_type = get_customer_deletion_type(customer)
                if deletion_type == CustomerRemovalDeletionTypes.SOFT_DELETE:
                    deletion_process = customer_soft_deletion_process(
                        user,
                        customer,
                        account,
                        nik,
                        phone,
                        email,
                        reason,
                        agent=request.agent,
                    )
                else:
                    deletion_process = customer_deletion_process(
                        user,
                        customer,
                        account,
                        nik,
                        phone,
                        email,
                        reason,
                        agent=request.agent,
                    )

                logger.info(
                    {
                        'method': 'delete_customer_account',
                        'data': deletion_process,
                    }
                )
                request.update_safely(request_status=AccountDeletionRequestStatuses.SUCCESS)
                send_approved_deletion_request_success_email.delay(customer.id)
        except JuloException as je:
            logger.exception(
                {
                    'method': 'inapp_account_deletion_deactivate_account',
                    'msg': 'julo exception is raised',
                    'error': str(je),
                    'data': {
                        'deletion_request_id': request.id,
                        'customer_id': customer.pk,
                    },
                }
            )
            if account:
                process_revert_account_status_460(
                    account, AccountDeletionStatusChangeReasons.CANCELED_BY_AGENT
                )

            request.update_safely(request_status=AccountDeletionRequestStatuses.FAILED)
            continue

        except Exception as e:
            logger.exception(
                {
                    'method': 'inapp_account_deletion_deactivate_account',
                    'msg': 'exception is raised',
                    'error': str(e),
                    'data': {
                        'deletion_request_id': request.id,
                        'customer_id': customer.pk,
                    },
                }
            )
            request.update_safely(request_status=AccountDeletionRequestStatuses.FAILED)
            get_julo_sentry_client().captureException()
            continue


def customer_soft_deletion_process(
    user,
    customer,
    account,
    nik,
    phone,
    email,
    reason,
    agent=None,
) -> dict:
    data = dict()
    is_customer_deleteable = customer_deleteable_application_check(customer)
    if not is_customer_deleteable:
        logger.warning(
            {
                'action': 'customer_soft_deletion_process',
                'message': 'there is no application that can be deleted',
                'customer_id': customer.id,
            },
        )
        return data

    force_logout_user(customer)
    deleteable_applications = get_deleteable_application(customer)
    application = deleteable_applications.last()
    is_full_deletion = is_complete_deletion(customer)
    if is_full_deletion:
        soft_deactivate_user(user, customer)
        soft_update_customer_table_as_inactive(user, customer, application)

        if account:
            process_change_account_status(
                account=account,
                new_status_code=AccountConstant.STATUS_CODE.deactivated,
                change_reason=reason,
                manual_change=True,
            )

    deactivated_app_ids, product_lines = soft_update_application_table_as_inactive(
        user, deleteable_applications, nik, phone, email
    )
    if is_full_deletion or (deactivated_app_ids and len(deactivated_app_ids) > 0):
        for product_line in product_lines:
            product_line_app = (
                deleteable_applications.only('id')
                .filter(
                    product_line_id=product_line,
                )
                .order_by('-id')
                .first()
            )

            CustomerRemoval.objects.create(
                customer=customer,
                application_id=product_line_app.id,
                user=customer.user,
                reason=reason,
                nik=nik,
                email=email,
                phone=phone,
                added_by=agent,
                product_line_id=product_line,
            )

        data.update({'is_deleted': True, 'customer_id': customer.pk})
        if application:
            data.update({'application_id': application.pk})
        send_user_attributes_to_moengage_for_realtime_basis.delay(customer.id, 'is_deleted')

    send_approved_deletion_request_success_email.delay(customer.id)

    return data


def soft_deactivate_user(
    requested_user: User,
    customer: Customer,
) -> None:
    """
    - Marked the customer as soft deleted
    Args:
        requested_user (User): Get Agent user Object.
        customer (Customer): get Customer
    """

    user = customer.user

    AuthUserFieldChange.objects.create(
        user=user,
        customer=customer,
        field_name='is_active',
        old_value=user.is_active,
        new_value=False,
        changed_by=requested_user,
    )
    user.is_active = False
    user.save()

    return None


def soft_update_customer_table_as_inactive(agent, customer, application) -> None:
    field_changes = []
    field_changes.append(
        CustomerFieldChange(
            customer=customer,
            application=application,
            field_name='can_reapply',
            old_value=customer.can_reapply,
            new_value=False,
            changed_by=agent,
        )
    )
    field_changes.append(
        CustomerFieldChange(
            customer=customer,
            application=application,
            field_name='is_active',
            old_value=customer.is_active,
            new_value=False,
            changed_by=agent,
        )
    )
    customer.can_reapply = False
    customer.is_active = False

    CustomerFieldChange.objects.bulk_create(field_changes)
    customer.save(update_fields=['can_reapply', 'is_active'])

    return None


def soft_update_application_table_as_inactive(
    agent,
    applications,
    original_nik,
    original_phone,
    original_email,
) -> List[int]:
    '''
    Deactivate the received applications

    Args:
        customer (Customer): The application's customer
        agent (User): action triggered by
        applications ([]Application): applications that want to be deactivated

    Return:
        []int: the deactivated application ids
        []int: unique product lines of the deleted application
    '''

    deleted_application_ids = []
    field_changes = []
    history_changes = []
    product_lines = []
    update_fields = []

    allowed_product_line_deletion = get_allowed_product_line_for_deletion()
    for application in applications:
        if application.product_line_id not in allowed_product_line_deletion:
            continue

        if application.is_deleted:
            continue

        if original_nik != application.ktp:
            field_changes.append(
                ApplicationFieldChange(
                    application=application,
                    field_name='ktp',
                    old_value=application.ktp,
                    new_value=original_nik,
                    agent=agent,
                )
            )
            if 'ktp' not in update_fields:
                update_fields.append('ktp')
            application.ktp = original_nik

        if original_phone != application.mobile_phone_1:
            field_changes.append(
                ApplicationFieldChange(
                    application=application,
                    field_name='mobile_phone_1',
                    old_value=application.mobile_phone_1,
                    new_value=original_phone,
                    agent=agent,
                )
            )
            if 'mobile_phone_1' not in update_fields:
                update_fields.append('mobile_phone_1')
            application.mobile_phone_1 = original_phone

        if original_email != application.email:
            field_changes.append(
                ApplicationFieldChange(
                    application=application,
                    field_name='email',
                    old_value=application.email,
                    new_value=original_email,
                    agent=agent,
                )
            )
            if 'email' not in update_fields:
                update_fields.append('email')
            application.email = original_email

        field_changes.append(
            ApplicationFieldChange(
                application=application,
                field_name='is_deleted',
                old_value=application.is_deleted,
                new_value=True,
                agent=agent,
            )
        )
        if 'is_deleted' not in update_fields:
            update_fields.append('is_deleted')
        application.is_deleted = True

        history_changes.append(
            ApplicationHistory(
                application=application,
                status_old=application.application_status_id,
                status_new=ApplicationStatusCodes.CUSTOMER_DELETED,
                changed_by=agent,
                change_reason='manual soft deletion',
            )
        )
        if 'application_status_id' not in update_fields:
            update_fields.append('application_status_id')
        application.application_status_id = ApplicationStatusCodes.CUSTOMER_DELETED

        deleted_application_ids.append(application.id)

        if application.product_line_id not in product_lines:
            product_lines.append(application.product_line_id)

    ApplicationFieldChange.objects.bulk_create(field_changes)
    ApplicationHistory.objects.bulk_create(history_changes)
    bulk_update(applications, update_fields=update_fields)

    return deleted_application_ids, product_lines


def process_revert_account_status(account: Account, status: str, reason: str) -> None:
    """
    Reverts the account status to a previous state based on the given status and reason.

    Args:
        account (Account): The account object.
        status (str): The status to revert to.
        reason (str): The reason for reverting the status.

    Returns:
        None
    """
    old_status = account.accountstatushistory_set.filter(
        status_new=status,
    ).last()
    if not old_status:
        logger.warning(
            {
                'action': 'process_revert_consent_withdrawal_status_' + str(status),
                'message': """not reverting account's status:
                    there is no account_status_history for this account""",
                'customer_id': account.customer_id,
                'account_id': account.id,
            }
        )
        return

    if old_status.status_old_id == JuloOneCodes.CONSENT_WITHDRAWAL_ON_REVIEW:
        old_status = account.accountstatushistory_set.filter(
            status_new=JuloOneCodes.CONSENT_WITHDRAWAL_ON_REVIEW,
        ).last()

        if not old_status:
            logger.warning(
                {
                    'action': 'process_revert_consent_withdrawal_status_' + str(status),
                    'message': """not reverting account's status:
                        there is no account_status_history for this account""",
                    'customer_id': account.customer_id,
                    'account_id': account.id,
                }
            )
            return

    process_change_account_status(
        account,
        old_status.status_old_id,
        change_reason=reason,
    )


def process_revert_applications_status(
    customer: Customer, status: int, change_reason: str, changed_by: Optional[str] = None
) -> None:
    """
    Reverts the status of applications belonging to a customer to a specified status.

    Args:
        customer (Customer): The customer object.
        status (int): The status to revert the applications to.
        change_reason (str): The reason for the status change.
        changed_by (str, optional): The user who initiated the status change. Defaults to None.
    """
    if not customer:
        return

    for application in customer.application_set.all():
        if application.application_status_id != status:
            continue

        last_app_status = ApplicationHistory.objects.filter(
            application=application,
        ).last()

        if not last_app_status:
            logger.info(
                {
                    'action': 'process_revert_applications_status_' + str(status),
                    'message': """not reverting application's status:
                        there is no application_history for this application""",
                    'customer_id': customer.id,
                    'account_id': application.id,
                }
            )
            return

        if last_app_status.status_old == ApplicationStatusCodes.CUSTOMER_ON_CONSENT_WITHDRAWAL:
            last_app_withdraw_request = application.applicationhistory_set.filter(
                status_new=ApplicationStatusCodes.CUSTOMER_ON_CONSENT_WITHDRAWAL,
            ).last()

            if not last_app_status:
                logger.warning(
                    {
                        'action': 'process_revert_applications_status_' + str(status),
                        'message': """not reverting application's status:
                            there is no application_history for this application""",
                        'customer_id': customer.id,
                        'account_id': application.id,
                    }
                )
                return

            ApplicationHistory.objects.create(
                application=application,
                status_old=last_app_status.status_new,
                status_new=last_app_withdraw_request.status_old,
                change_reason=change_reason,
                changed_by=changed_by,
            )
            application.update_safely(
                application_status_id=last_app_withdraw_request.status_old,
            )
        else:
            ApplicationHistory.objects.create(
                application=application,
                status_old=last_app_status.status_new,
                status_new=last_app_status.status_old,
                change_reason=change_reason,
                changed_by=changed_by,
            )
            application.update_safely(
                application_status_id=last_app_status.status_old,
            )


def get_latest_withdrawal_requests(customer_ids):
    customer_ids = list(customer_ids)
    if not customer_ids:
        return []

    query = """
        SELECT *
        FROM (
            SELECT DISTINCT ON (customer_id) *
            FROM consent_withdrawal_request
            WHERE status = 'requested' AND customer_id = ANY(%s)
            ORDER BY customer_id, request_id DESC
        ) AS latest_requests
        ORDER BY request_id DESC;
    """
    return list(ConsentWithdrawalRequest.objects.raw(query, [customer_ids]))


def approval_consent_withdrawal(
    customer: Customer,
    admin_reason: Optional[str],
    source: str,
    action_by: int,
) -> Union[ConsentWithdrawalRequest, None]:
    from juloserver.julo.services import process_application_status_change

    if not customer:
        return None

    action_attr = ConsentWithdrawal.MAPPING_ACTION_ATTRS["approve"]
    status_filter = (
        [action_attr["from_status"]]
        if not isinstance(action_attr["from_status"], list)
        else action_attr["from_status"]
    )

    current_request = ConsentWithdrawalRequest.objects.filter(customer_id=customer.id).last()
    if not current_request or current_request.status not in status_filter:
        logger.error(
            {
                'action': action_attr["log_error"],
                'message': action_attr["log_message"],
                'customer_id': customer.id,
                'current_request': current_request.status if current_request else None,
            }
        )
        return None

    withdrawal_request = ConsentWithdrawalRequest.objects.create(
        customer_id=customer.id,
        user_id=customer.user_id,
        email_requestor=current_request.email_requestor,
        status=action_attr["to_status"],
        source=source,
        application_id=current_request.application_id,
        reason=current_request.reason,
        detail_reason=current_request.detail_reason,
        action_by=action_by,
        admin_reason=admin_reason,
        action_date=timezone.localtime(timezone.now()),
    )

    account = customer.account_set.last()
    if account:
        process_change_account_status(
            account=account,
            new_status_code=action_attr["account_status"],
            change_reason=ConsentWithdrawal.StatusChangeReasons.APPROVE_BY_AGENT,
        )

    # Bulk process applications
    errors = 0
    has_applications = customer.application_set.exists()
    if has_applications:
        for application in customer.application_set.all():
            if (
                not application.is_julo_one_or_starter()
                or application.status == ApplicationStatusCodes.LOC_APPROVED
            ):
                continue
            try:
                if (
                    application.application_status_id
                    == ApplicationStatusCodes.CUSTOMER_ON_CONSENT_WITHDRAWAL
                ):
                    process_application_status_change(
                        application.id,
                        ApplicationStatusCodes.CUSTOMER_CONSENT_WITHDRAWED,
                        action_attr["reason"],
                    )
            except (JuloInvalidStatusChange, Exception) as e:
                sentry_client.captureException()
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
                errors += 1

    # Handle errors if any
    if errors > 0:
        withdrawal_request.delete()
        revert_message = (
            "cancelled consent withdrawal request because failed to update application status"
        )

        if account:
            process_revert_account_status(account, action_attr["account_status"], revert_message)

        if has_applications:
            process_revert_applications_status(
                customer, action_attr["application_status"], revert_message
            )

        return None

    send_consent_withdraw_email.delay("approve", customer_id=customer.id)
    return withdrawal_request
