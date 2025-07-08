from builtins import str
from datetime import timedelta

from celery import task
import logging
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from juloserver.julo.clients.sepulsa import get_sepulsa_transaction_general
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import SepulsaTransaction
from juloserver.julo.services import action_cashback_sepulsa_transaction, \
    process_sepulsa_transaction_failed
from juloserver.loyalty.services.point_redeem_services import check_and_refunded_transfer_dana
from juloserver.payment_point.services.sepulsa import SepulsaLoanService
from juloserver.julo.services2.sepulsa import SepulsaService
from juloserver.line_of_credit.services import LineOfCreditPurchaseService
from juloserver.payment_point.constants import SepulsaProductCategory

logger = logging.getLogger(__name__)


def failed_transaction_handler(sepulsa_transaction_id):
    with transaction.atomic():
        sepulsa_transaction = SepulsaTransaction.objects.select_for_update().get(
            pk=sepulsa_transaction_id)
        process_sepulsa_transaction_failed(sepulsa_transaction)


@task(queue="loan_high")
def check_transaction_sepulsa_loan():
    sepulsa_service = SepulsaLoanService()
    julo_sepulsa_client = sepulsa_service.julo_sepulsa_client
    sentry_client = get_julo_sentry_client()
    sepulsa_transactions = SepulsaTransaction.objects.filter(
        loan__isnull=False, transaction_status='pending'
    )
    for sepulsa_transaction in sepulsa_transactions:
        # placed select_for_update() inside loop to prevent rows locked to long
        with transaction.atomic():
            sepulsa_transaction = SepulsaTransaction.objects.select_for_update().get(
                pk=sepulsa_transaction.id
            )
            now = timezone.localtime(timezone.now())
            after_15_m = sepulsa_transaction.cdate + timedelta(minutes=15)
            if now < after_15_m:
                continue
            try:
                if sepulsa_transaction.product.category == SepulsaProductCategory.TRAIN_TICKET:
                    response, _ = sepulsa_service.get_train_transaction_detail(
                        sepulsa_transaction.transaction_code
                    )
                else:
                    response = julo_sepulsa_client.get_transaction_detail(sepulsa_transaction)
                if response["response_code"] == sepulsa_transaction.response_code:
                    continue

                sepulsa_transaction = sepulsa_service.\
                    update_sepulsa_transaction_with_history_accordingly(
                        sepulsa_transaction, "update_transaction_via_task", response
                    )
                action_cashback_sepulsa_transaction(
                    "update_transaction_via_task", sepulsa_transaction
                )
            except Exception as e:
                logger.info({"action": "check_transaction_sepulsa", "message": str(e)})
                sentry_client.captureException()
                continue

    timeout_sepulsa_trxs = SepulsaTransaction.objects.filter(
        loan__isnull=False, transaction_status__isnull=True, transaction_code__isnull=True)
    for sepulsa_trx in timeout_sepulsa_trxs:
        now = timezone.localtime(timezone.now())
        after_15_m = sepulsa_trx.cdate + timedelta(minutes=15)
        if now < after_15_m:
            continue
        if not sepulsa_trx.order_id:
            continue
        try:
            response = julo_sepulsa_client.get_transaction_detail_by_order_id(sepulsa_trx)
            if 'list' not in response:
                continue
            if not response['list']:
                failed_transaction_handler(sepulsa_trx.id)
                continue

            trx_data = response['list'][-1]
            sepulsa_trx = sepulsa_service.update_sepulsa_transaction_with_history_accordingly(
                sepulsa_trx, "update_transaction_via_task", trx_data
            )
            action_cashback_sepulsa_transaction(
                "update_transaction_via_task", sepulsa_trx
            )

        except Exception as e:
            logger.info({"action": "check_transaction_sepulsa",
                         "sepulsa_transaction_id": sepulsa_trx.id, "message": str(e)})
            sentry_client.captureException()
            continue


@task(queue="loan_high")
def reset_transaction_sepulsa_loan_break():
    sepulsa_transactions = SepulsaTransaction.objects.filter(loan__isnull=False).filter(
        Q(transaction_status__isnull=True) | Q(is_order_created=False))
    for sepulsa_transaction in sepulsa_transactions:
        failed_transaction_handler(sepulsa_transaction.id)


@task(queue='loan_high')
def check_transaction_sepulsa():
    sentry_client = get_julo_sentry_client()
    sepulsa_transactions = SepulsaTransaction.objects.filter(
        loan__isnull=True, transaction_status='pending'
    )
    for sepulsa_transaction in sepulsa_transactions:
        # placed select_for_update() inside loop to prevent rows locked to long
        with transaction.atomic():
            sepulsa_transaction = SepulsaTransaction.objects.select_for_update().get(
                pk=sepulsa_transaction.id
            )
            now = timezone.localtime(timezone.now())
            after_15_m = sepulsa_transaction.cdate + timedelta(minutes=15)
            if now < after_15_m:
                continue
            try:
                response = get_sepulsa_transaction_general(sepulsa_transaction)
                if response["response_code"] == sepulsa_transaction.response_code:
                    continue
                sepulsa_service = SepulsaService()
                sepulsa_transaction = sepulsa_service.\
                    update_sepulsa_transaction_with_history_accordingly(
                        sepulsa_transaction, "update_transaction_via_task", response
                    )
                if sepulsa_transaction.line_of_credit_transaction:
                    loc_transaction = LineOfCreditPurchaseService()
                    loc = sepulsa_transaction.line_of_credit_transaction.line_of_credit
                    loc_transaction.action_loc_sepulsa_transaction(
                        loc, "update_transaction_via_task", sepulsa_transaction
                    )
                else:
                    if sepulsa_transaction.is_instant_transfer_to_dana:
                        check_and_refunded_transfer_dana(sepulsa_transaction)
                    else:
                        action_cashback_sepulsa_transaction(
                            "update_transaction_via_task", sepulsa_transaction
                        )
            except Exception as e:
                logger.info({"action": "check_transaction_sepulsa", "message": str(e)})
                sentry_client.captureException()
                continue


@task(queue='loan_high')
def reset_transaction_sepulsa_break():
    sepulsa_transactions = SepulsaTransaction.objects.filter(loan__isnull=True).filter(
        Q(transaction_status__isnull=True) | Q(is_order_created=False))
    for sepulsa_transaction in sepulsa_transactions:
        # placed select_for_update() inside loop to prevent rows locked to long
        with transaction.atomic():
            sepulsa_transaction = SepulsaTransaction.objects.select_for_update().get(
                pk=sepulsa_transaction.id)
            process_sepulsa_transaction_failed(sepulsa_transaction)
