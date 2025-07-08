import logging
import os

import semver
from django.conf import settings
from django.db import transaction

from juloserver.account.constants import TransactionType
from juloserver.account.services.account_related import is_account_limit_sufficient
from juloserver.ecommerce.clients.juloshop import JuloShopClient
from juloserver.ecommerce.constants import (
    JuloShopTransactionStatus,
)
from juloserver.ecommerce.exceptions import JuloShopInvalidStatus
from juloserver.ecommerce.models import JuloShopTransaction, EcommerceConfiguration, \
    JuloShopStatusHistory
from juloserver.followthemoney.constants import SnapshotType
from juloserver.followthemoney.models import LenderTransactionMapping, LenderBalanceCurrent
from juloserver.followthemoney.services import update_lender_balance_current_for_disbursement
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import FeatureSetting
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.loan.services.loan_related import calculate_loan_amount, \
    update_loan_status_and_loan_history

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def get_juloshop_client():
    return JuloShopClient(
        base_url=settings.JULOSHOP_BASE_URL,
        juloshop_token=os.getenv('JULOSHOP_AUTHORIZATION')
    )


def create_juloshop_transaction(data_from_juloshop):
    application = data_from_juloshop['application']
    checkout_info = {
        "items": data_from_juloshop['items'],
        "recipientDetail": data_from_juloshop['recipientDetail'],
        "shippingDetail": data_from_juloshop['shippingDetail'],
        "totalProductAmount": data_from_juloshop["totalProductAmount"],
        "shippingFee": data_from_juloshop["shippingFee"],
        "insuranceFee": data_from_juloshop["insuranceFee"],
        "discount": data_from_juloshop["discount"],
        "finalAmount": data_from_juloshop["finalAmount"],
    }

    return JuloShopTransaction.objects.create(
        customer=application.customer,
        application=application,
        status=JuloShopTransactionStatus.DRAFT,
        seller_name=data_from_juloshop['sellerName'],
        product_total_amount=data_from_juloshop["totalProductAmount"],
        transaction_total_amount=data_from_juloshop["finalAmount"],
        checkout_info=checkout_info
    )


def check_juloshop_account_limit(juloshop_transaction):
    application = juloshop_transaction.application
    loan_amount, _, _ = calculate_loan_amount(
        application=application,
        loan_amount_requested=juloshop_transaction.transaction_total_amount,
        transaction_type=TransactionType.ECOMMERCE
    )
    if is_account_limit_sufficient(loan_amount, application.account_id):
        return True

    change_juloshop_transaction_status(
        juloshop_transaction,
        JuloShopTransactionStatus.FAILED,
        change_reason="Insufficient credit limit"
    )

    return False


def get_juloshop_transaction_details(transaction_xid, customer, application):
    julo_shop_transaction = JuloShopTransaction.objects.filter(
        transaction_xid=transaction_xid, customer=customer, application=application
    ).first()
    if not julo_shop_transaction:
        return {}

    julo_shop_extra_config = EcommerceConfiguration.objects.get(
        ecommerce_name='Julo Shop'
    ).extra_config
    julo_shop_extra_config_logos = julo_shop_extra_config['logos']

    seller_name = julo_shop_transaction.seller_name
    transaction_checkout_info = julo_shop_transaction.checkout_info
    seller_logo_url = julo_shop_extra_config_logos[seller_name]['url']
    items = transaction_checkout_info['items'][0]
    items['price'] = transaction_checkout_info['finalAmount']
    items['sellerLogo'] = seller_logo_url
    items['defaultImage'] = julo_shop_extra_config['default_images']['invalid_product_image']

    return {
        'items': items,
        'shipping_details': transaction_checkout_info['shippingDetail']
    }


def change_juloshop_transaction_status(juloshop_transaction, new_status,
                                       change_reason='system_triggered'):
    current_status = juloshop_transaction.status
    if (current_status, new_status) not in JuloShopTransactionStatus.status_changeable():
        raise JuloShopInvalidStatus

    with transaction.atomic():
        juloshop_transaction.update_safely(status=new_status)
        JuloShopStatusHistory.objects.create(
            transaction=juloshop_transaction,
            status_old=current_status,
            status_new=new_status,
            change_reason=change_reason,
        )


def get_juloshop_transaction(customer, juloshop_transaction_xid):
    return JuloShopTransaction.objects.get(
        transaction_xid=juloshop_transaction_xid,
        customer=customer,
    )


def get_juloshop_transaction_by_loan(loan):
    juloshop_transaction = JuloShopTransaction.objects.filter(loan=loan).last()
    if not juloshop_transaction:
        return None
    logger.info({
        'action': 'ecommerce.juloshop_service.get_juloshop_transaction_by_loan',
        'loan': loan.id,
    })
    return juloshop_transaction


def get_juloshop_loan_product_details(juloshop_transaction):
    if not juloshop_transaction:
        return {}

    checkout_info = juloshop_transaction.checkout_info
    item_details = checkout_info['items'][0]

    return item_details


def update_committed_amount_for_lender_balance_juloshop(juloshop_transaction):
    from juloserver.followthemoney.tasks import calculate_available_balance
    loan = juloshop_transaction.loan
    if loan is None:
        logger.info({
            'method': 'updated_committed_amount_for_lender_balance',
            'msg': 'failed to get loan with juloshop_transaction {}'.format(juloshop_transaction.id)
        })

        raise JuloException('Loan is not found')
    lender = loan.lender
    loan_amount = loan.loan_amount

    current_lender_balance = LenderBalanceCurrent.objects.select_for_update()\
                                                         .filter(lender=lender).last()

    if not current_lender_balance:
        logger.info({
            'method': 'updated_committed_amount_for_lender_balance',
            'msg': 'failed to update committed current balance',
            'error': 'loan have invalid lender id: {}'.format(lender.id)
        })
        raise JuloException('Loan does not have lender id')

    current_lender_committed_amount = current_lender_balance.committed_amount
    updated_committed_amount = current_lender_committed_amount + loan_amount
    updated_dict = {
        'loan_amount': loan_amount,
        'committed_amount': updated_committed_amount
    }

    calculate_available_balance.delay(
        current_lender_balance.id,
        SnapshotType.TRANSACTION,
        **updated_dict
    )

    ltm = LenderTransactionMapping.objects.filter(juloshop_transaction=juloshop_transaction)
    if not ltm:
        LenderTransactionMapping.objects.create(juloshop_transaction=juloshop_transaction)

    logger.info({
        'method': 'updated_committed_amount_for_lender_balance',
        'msg': 'success to update lender balance current',
        'juloshop_transaction_id': juloshop_transaction.id,
        'loan_id': loan.id
    })


def juloshop_disbursement_process(loan):
    from juloserver.loan.services.lender_related import (
        julo_one_loan_disbursement_success,
        julo_one_loan_disbursement_failed
    )
    juloshop_client = get_juloshop_client()
    juloshop_transaction = get_juloshop_transaction_by_loan(loan)
    update_loan_status_and_loan_history(
        loan.id,
        new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        change_reason="Loan approved by lender"
    )

    ltm = LenderTransactionMapping.objects.filter(
        juloshop_transaction=juloshop_transaction,
        lender_transaction_id__isnull=True
    )
    change_juloshop_transaction_status(juloshop_transaction, JuloShopTransactionStatus.PROCESSING)
    if not ltm:
        try:
            with transaction.atomic():
                update_committed_amount_for_lender_balance_juloshop(juloshop_transaction)
                update_lender_balance_current_for_disbursement(loan.id)
        except JuloException as e:
            change_juloshop_transaction_status(
                juloshop_transaction, JuloShopTransactionStatus.FAILED
            )
            logger.info({
                'method': 'juloshop_disbursement_process',
                'loan_id': loan.id,
                'msg': 'update_committed_amount_for_lender_balance_juloshop_failed',
                'error_msg': str(e)
            })
            return True

    is_success, errors = juloshop_client.sent_order_confirmation(
        juloshop_transaction.transaction_xid, juloshop_transaction.application.application_xid
    )
    if is_success:
        change_juloshop_transaction_status(juloshop_transaction, JuloShopTransactionStatus.SUCCESS)
        julo_one_loan_disbursement_success(loan)
    else:
        change_juloshop_transaction_status(
            juloshop_transaction, JuloShopTransactionStatus.FAILED, change_reason=errors
        )
        julo_one_loan_disbursement_failed(loan)


def is_application_eligible_for_juloshop(application_id):
    juloshop_whitelist = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.JULOSHOP_WHITELIST, is_active=True
    )
    if not juloshop_whitelist:
        return True

    application_ids = juloshop_whitelist.parameters.get('application_ids', [])
    return application_id in application_ids


def check_juloshop_app_version(app_version):
    return semver.match('7.10.0', ">%s" % app_version)
