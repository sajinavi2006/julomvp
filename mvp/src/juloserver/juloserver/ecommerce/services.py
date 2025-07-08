import logging

from cuser.middleware import CuserMiddleware
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from urllib.parse import urlparse

from juloserver.account.constants import TransactionType
from juloserver.account.services.account_related import is_account_limit_sufficient
from juloserver.ecommerce.clients.iprice import IpriceClient
from juloserver.ecommerce.constants import (
    IpriceTransactionStatus,
    CategoryType,
    EcommerceConstant,
)
from juloserver.ecommerce.juloshop_service import is_application_eligible_for_juloshop
from juloserver.ecommerce.models import (
    EcommerceConfiguration,
    IpriceStatusHistory,
    IpriceTransaction,
)
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.models import BankAccountDestination
from juloserver.ecommerce.exceptions import IpriceInvalidPartnerUserId
from juloserver.julo.models import Application
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan.services.loan_related import calculate_loan_amount

logger = logging.getLogger(__name__)
PACKAGE_NAME = 'juloserver.ecommerce.services'
_iprice_client = None


def _get_iprice_client():
    """
    Get the singleton IpriceClient instance.
    """
    global _iprice_client
    if _iprice_client is None:
        _iprice_client = IpriceClient(
            base_url=settings.IPRICE_BASE_URL,
            pid=settings.IPRICE_PID,
        )
    return _iprice_client


def _reset_iprice_client():
    """
    Reset the singleton IpriceClient instance.
    Only used for testing.
    """
    global _iprice_client
    _iprice_client = None


def get_current_auth_user():
    """
    Get the current authenticated user from CuserMiddleware
    """
    user = CuserMiddleware.get_user()
    if isinstance(user, User):
        return user

    return None


def send_invoice_callback(iprice_transaction):
    """
    Send invoice callback to Iprice
    May have raise these exceptions:
    - rest_frameworks.ValidationException: if the response is invalid
    - requests.HttpError: if there is something wrong with the response.
    """
    client = _get_iprice_client()
    data = {
        "iprice_order_id": iprice_transaction.iprice_order_id,
        "application_id": iprice_transaction.application.application_xid,
        "loan_id": iprice_transaction.loan.loan_xid if iprice_transaction.loan_id else None,
        "transaction_status": iprice_transaction.current_status,
    }
    response_data = client.post_invoice_callback(data=data)
    if response_data.get('confirmation_status') == 'OK':
        return True

    logger.warning({
        'action': '{}.send_invoice_callback'.format(PACKAGE_NAME),
        'message': 'iPrice invoice callback status is not OK',
        'data': data,
        'response_data': response_data,
    })
    return False


def update_iprice_transaction_loan(iprice_transaction_id, loan):
    iprice_transaction = IpriceTransaction.objects.get(id=iprice_transaction_id,
                                                       customer_id=loan.customer_id,
                                                       current_status=IpriceTransactionStatus.DRAFT)
    admin_fee = loan.loan_amount - loan.loan_disbursement_amount

    if loan.loan_disbursement_amount != iprice_transaction.iprice_total_amount:
        exc_data = {
            'loan_id': loan.id,
            'loan_disbursement_amount': loan.loan_disbursement_amount,
            'iprice_transaction_id': iprice_transaction_id,
            'iprice_total_amount': iprice_transaction.iprice_total_amount,
        }
        raise Exception('Loan disbursement amount is not equal to iPrice total amount', exc_data)

    iprice_transaction.update_safely(
        loan=loan,
        admin_fee=admin_fee,
        transaction_total_amount=loan.loan_amount,
    )
    return iprice_transaction


def update_iprice_transaction_status(iprice_transaction, new_status,
                                     change_reason='system triggered'):

    if not isinstance(iprice_transaction, IpriceTransaction):
        iprice_transaction = IpriceTransaction.objects.get(id=iprice_transaction)

    old_status = iprice_transaction.current_status

    if old_status == new_status:
        logger.info({
            'action': '{}.update_iprice_transaction_status'.format(PACKAGE_NAME),
            'message': 'iPrice transaction status is already {}'.format(new_status),
            'old_status': old_status,
            'new_status': new_status,
            'iprice_transaction': iprice_transaction,
            'change_reason': change_reason,
        })
        return

    with transaction.atomic():
        auth_user = get_current_auth_user()
        iprice_transaction.update_safely(current_status=new_status)
        IpriceStatusHistory.objects.create(
            iprice_transaction=iprice_transaction,
            status_old=old_status,
            status_new=new_status,
            change_reason=change_reason,
            changed_by=auth_user,
        )

        send_invoice_callback(iprice_transaction)


def update_iprice_transaction_by_loan(loan, new_loan_status, change_reason='system triggered'):
    """
    This method is used to update iprice when there is new changes in loan status
    see: juloserver.loan.services.loan_related.update_loan_status_and_loan_history()
    """
    # iprice transaction will not be updated if the new_status is more than 220
    if new_loan_status > LoanStatusCodes.CURRENT:
        return

    iprice_transaction = IpriceTransaction.objects.get_or_none(loan_id=loan.id)

    # Not an iPrice transaction
    if iprice_transaction is None:
        return

    new_transaction_status = IpriceTransactionStatus.by_loan_status(new_loan_status)
    update_iprice_transaction_status(iprice_transaction.id, new_transaction_status, change_reason)


def prepare_ecommerce_data(customer):
    ecommerce_category = EcommerceConfiguration.objects.filter(
        is_active=True,
        category_type=CategoryType.ECOMMERCE,
    ).order_by('order_number')

    ecommerce_marketplace = EcommerceConfiguration.objects.filter(
        is_active=True,
        category_type=CategoryType.MARKET,
    ).order_by('order_number')

    application = customer.application_set.last()
    marketplace_data = []
    for x in ecommerce_marketplace:
        if x.ecommerce_name == EcommerceConstant.JULOSHOP and \
                not is_application_eligible_for_juloshop(application.id):
            continue

        if x.ecommerce_name == EcommerceConstant.IPRICE:
            parsed_url = urlparse(x.url)
            if parsed_url.query:
                #  if url already has some params: site.com/?a=123&b=etc
                x.url += "&"
            else:
                x.url += "?"

            x.url += "partner_user_id={}".format(application.application_xid)

        marketplace_data.append(x)

    return ecommerce_category, marketplace_data


def create_iprice_transaction(data_from_iprice):
    application_xid = data_from_iprice['partnerUserId']
    application = Application.objects.get_or_none(application_xid=application_xid)

    if not application:
        raise IpriceInvalidPartnerUserId

    customer = application.customer
    checkout_info = {
        "partnerUserId": data_from_iprice['partnerUserId'],
        "paymentType": data_from_iprice['paymentType'],
        "address": data_from_iprice['address'],
        "province": data_from_iprice['province'],
        "city": data_from_iprice['city'],
        "email": data_from_iprice['email'],
        "firstName": data_from_iprice['firstName'],
        "lastName": data_from_iprice['lastName'],
        "mobile": data_from_iprice['mobile'],
        "postcode": data_from_iprice['postcode'],
        "items": data_from_iprice['items'],
    }
    with transaction.atomic():
        transac = IpriceTransaction.objects.create(
            customer=customer,
            application=application,
            current_status=IpriceTransactionStatus.DRAFT,
            iprice_total_amount=data_from_iprice['grandAmount'],
            iprice_order_id=data_from_iprice['externalId'],
            fail_redirect_url=data_from_iprice['failRedirectUrl'],
            success_redirect_url=data_from_iprice['successRedirectUrl'],
            checkout_info=checkout_info,
        )

        IpriceStatusHistory.objects.create(
            iprice_transaction=transac,
            status_new=transac.current_status,
        )

    return transac


def check_account_limit(iprice_transaction):
    account_id = iprice_transaction.application.account_id
    loan_amount, _, _ = calculate_loan_amount(
        application=iprice_transaction.application,
        loan_amount_requested=iprice_transaction.iprice_total_amount,
        transaction_type=TransactionType.ECOMMERCE
    )
    if is_account_limit_sufficient(loan_amount, account_id):
        return True

    update_iprice_transaction_status(
        iprice_transaction,
        IpriceTransactionStatus.LOAN_REJECTED,
        change_reason="Insufficient credit limit"
    )
    return False


def get_iprice_transaction(customer, transaction_id, use_xid=False):
    if use_xid:
        return IpriceTransaction.objects.get_or_none(
            iprice_transaction_xid=transaction_id,
            customer=customer,
        )

    return IpriceTransaction.objects.get_or_none(
        id=transaction_id,
        customer=customer,
    )


def get_iprice_bank_destination():
    user = User.objects.get(username=PartnerConstant.IPRICE)
    bank_account_destination = BankAccountDestination.objects.get(
        bank_account_category__category=BankAccountCategoryConst.ECOMMERCE,
        customer=user.customer,
    )

    return bank_account_destination
