from django.db.models import QuerySet
from typing import Union, List, Optional
from datetime import datetime
from juloserver.julo.models import (
    Application,
    Loan,
    CustomerFieldChange,
    ApplicationFieldChange,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.account.constants import AccountConstant
from juloserver.julo.exceptions import JuloException
from django.db.models import Q
from juloserver.customer_module.constants import (
    CustomerRemovalDeletionTypes,
    pending_loan_status_codes,
)
from juloserver.customer_module.constants import (
    loan_status_not_allowed,
    forbidden_account_status,
    forbidden_application_status_account_deletion,
    soft_delete_application_status_account_deletion,
    soft_delete_account_status_account_deletion,
)
from juloserver.customer_module.constants import (
    InAppAccountDeletionMessagesConst,
    InAppAccountDeletionTitleConst,
)
from juloserver.account.models import AccountStatusHistory
from juloserver.julo.statuses import JuloOneCodes
from juloserver.julo.statuses import ApplicationStatusCodes
import logging

from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)


def get_nik_from_applications(applications: Union[QuerySet, List[Application]]) -> Optional[str]:
    """
    Args:
        applications (ApplicationQuerySet): list of All Applications of customer
    Returns:
        (string): if the ktp of customer exists in any of the applications.
        (None): if ktp dosen't exists in any of those applications.
    """
    if not applications.exists():
        return None
    for application in applications:
        if application.ktp:
            return application.ktp
    return None


def get_email_from_applications(applications: Union[QuerySet, List[Application]]) -> Optional[str]:
    """
    Args:
        applications (ApplicationQuerySet): list of All Applications of customer
    Returns:
        (string): if the email of customer exists in any of the applications.
        (None): if email dosen't exists in any of those applications.
    """
    if not applications.exists():
        return None
    for application in applications:
        if application.email:
            return application.email
    return None


def get_phone_from_applications(applications: Union[QuerySet, List[Application]]) -> Optional[str]:
    """
    Args:
        applications (ApplicationQuerySet): list of All Applications of customer
    Returns:
        (string): if the phone of customer exists in any of the applications.
        (None): if phone dosen't exists in any of those applications.
    """
    if not applications.exists():
        return None
    for application in applications:
        if application.mobile_phone_1:
            return application.mobile_phone_1
    return None


def get_active_loan_ids(customer):
    unpaid_loan = Loan.objects.filter(
        customer=customer, loan_status_id__gte=220, loan_status_id__lt=250
    )
    if unpaid_loan:
        loan_ids = []
        for loan in unpaid_loan:
            loan_ids.append(loan.id)
        return tuple(loan_ids)
    return None


def is_account_status_deleteable(status_id):

    if not status_id:
        return False

    allowed_status = [
        AccountConstant.STATUS_CODE.active,
        AccountConstant.STATUS_CODE.account_deletion_on_review,
    ]
    if status_id in allowed_status:
        return True

    if status_id in soft_delete_account_status_account_deletion:
        return True

    return False


def is_account_status_soft_deleteable(status_id):
    if status_id in soft_delete_account_status_account_deletion:
        return True

    return False


def is_application_status_soft_deleteable(status_id):
    if status_id in soft_delete_application_status_account_deletion:
        return True

    return False


def get_deletion_nik_format(customer_id):
    '''
    Get new NIK format for deleted user by customer_id

    Args:
        customer_id (int): The customer's id of the user

    Return:
        string: The new formatted nik
    '''

    return '444444' + str(customer_id)


def get_deletion_email_format(email, customer_id):
    '''
    Get new email format for deleted user by customer_id

    Args:
        email (string): The customer's original email that will be formatted
        customer_id (int): The customer's id of the user

    Return:
        string: The new formatted email
    '''
    if not email:
        return None

    try:
        domain_name = email.split('@')[1]

        return 'deleteduser{}@{}'.format(customer_id, domain_name)
    except IndexError as e:
        sentry = get_julo_sentry_client()
        sentry.capture_exception(e)


def get_deletion_phone_format(customer_id):
    '''
    Get new phone format for deleted user by customer_id

    Args:
        customer_id (int): The customer's id of the user

    Return:
        string: The new formatted phone number
    '''

    return '44' + str(customer_id)


def get_original_value(customer_id, applications, new_value):
    field_change = CustomerFieldChange.objects.filter(
        customer_id=customer_id, new_value=new_value
    ).values('old_value')

    if not field_change:
        field_change = (
            ApplicationFieldChange.objects.filter(application__in=applications, new_value=new_value)
            .values('old_value')
            .distinct()
        )

    return field_change.first()


def get_pending_loan_amount(account):
    pending_loans = AccountPayment.objects.filter(account=account).exclude(
        status=pending_loan_status_codes
    )
    loan_amount = 0
    for loans in pending_loans:
        loan_amount += loans.due_amount
    return loan_amount


def check_if_customer_is_elgible_to_delete(customer, account_status_id, application):
    '''
    Checks if the customer is eligible for a deletion via inapp account deletion request

    Args:
        customer (Customer): Customer model that want to be checked
        account_status_id (Int): The status of the customer's account
        application (Application): Active application of the customer
    '''

    active_loans = Loan.objects.filter(
        customer=customer, loan_status_id__in=loan_status_not_allowed
    )
    data = {
        'title': InAppAccountDeletionTitleConst.GENERAL_REJECTED,
    }
    if active_loans.exists():
        data.update(
            {
                'msg': InAppAccountDeletionMessagesConst.ACTIVE_LOAN,
            }
        )
        return False, data

    if account_status_id in forbidden_account_status:
        data.update(
            {
                'msg': InAppAccountDeletionMessagesConst.FORBIDDEN_ACCOUNT_STATUS,
            }
        )
        return False, data

    if application and (application.status in forbidden_application_status_account_deletion):
        data.update(
            {
                'msg': InAppAccountDeletionMessagesConst.FORBIDDEN_APPLICATION_STATUS,
            }
        )
        return False, data

    return True, None


def get_old_account_status(account):
    if not account:
        return None

    old_status = (
        AccountStatusHistory.objects.filter(
            account=account, status_new=JuloOneCodes.ACCOUNT_DELETION_ON_REVIEW
        )
        .values('status_old')
        .last()
    )
    if not old_status:
        raise JuloException('Customer does not have x460 status')

    return old_status.get('status_old')


def get_customer_deletion_type(customer):
    '''
    Check which flow does the customer should be deleted with.

    Parameters:
        customer (Customer): The customer that is going to be deleted

    Return:
        string: CustomerRemovalDeletionTypes constant
    '''
    from juloserver.customer_module.services.account_deletion import (
        get_allowed_product_line_for_deletion,
    )

    if (
        customer.account
        and customer.account.status_id in soft_delete_account_status_account_deletion
    ):
        return CustomerRemovalDeletionTypes.SOFT_DELETE

    allowed_product_line_deletion = get_allowed_product_line_for_deletion()
    is_soft_delete_application_status_exists = (
        customer.application_set.regular_not_deletes()
        .filter(
            application_status_id__in=soft_delete_application_status_account_deletion,
            product_line_id__in=allowed_product_line_deletion,
        )
        .exists()
    )
    if is_soft_delete_application_status_exists:
        return CustomerRemovalDeletionTypes.SOFT_DELETE

    is_soft_deleted_application_exists = customer.application_set.filter(
        Q(applicationhistory__status_new=ApplicationStatusCodes.CUSTOMER_DELETED)
        & Q(applicationhistory__status_old__in=soft_delete_application_status_account_deletion),
        is_deleted=True,
    ).exists()
    if is_soft_deleted_application_exists:
        return CustomerRemovalDeletionTypes.SOFT_DELETE

    return CustomerRemovalDeletionTypes.HARD_DELETE


def is_application_status_deleteable(status_id):
    if not status_id:
        return True

    if status_id in [
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
    ]:
        return False

    return True


def get_timestamp_format_for_email(timestamp: datetime = None) -> str:
    if timestamp is None:
        timestamp = datetime.now()

    formatted_time = timestamp.strftime('%d-%m-%Y | %H:%M:%S WIB')

    return formatted_time
