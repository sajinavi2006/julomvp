import logging
from celery import task
from django.conf import settings
from django.db import transaction
from django.db.models.query import QuerySet
from dateutil.parser import parse
from django.utils import timezone
from datetime import timedelta, datetime

from juloserver.integapiv1.clients import get_faspay_snap_client
from juloserver.integapiv1.constants import FaspayPaymentChannelCode
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.ovo.services.ovo_tokenization_services import process_ovo_repayment
from juloserver.payback.services.gopay import GopayServices
from juloserver.julo.models import (
    PaybackTransaction,
    Device,
    FeatureSetting,
)
from juloserver.julo.utils import (
    have_pn_device,
    execute_after_transaction_safely,
)
from juloserver.julo.clients import (
    get_julo_va_bca_client,
    get_julo_pn_client,
    get_julo_bca_snap_client
)

from juloserver.account_payment.constants import RepaymentRecallPaymentMethod
from juloserver.account_payment.services.gopay import process_gopay_repayment_for_account
from juloserver.account_payment.services.faspay import (
    faspay_payment_process_account,
    faspay_snap_payment_process_account,
)

from juloserver.integapiv1.services import bca_process_payment

from juloserver.ovo.models import OvoRepaymentTransaction, OvoWalletAccount, OvoWalletTransaction
from juloserver.ovo.clients import get_ovo_client
from juloserver.ovo.services.ovo_push2pay_services import update_ovo_transaction_after_inquiry
from juloserver.ovo.constants import OvoTransactionStatus
from juloserver.account_payment.services.account_payment_related import (
    update_latest_payment_method,
)
from juloserver.account_payment.services.payment_flow import (
    update_collection_risk_bucket_paid_first_installment,
    reversal_update_collection_risk_bucket_paid_first_installment,
)
from juloserver.account_payment.services.collection_related import primary_ptp_update_for_j1
from juloserver.julo.clients import get_julo_sentry_client
from datetime import date
from juloserver.julo.clients import (
    get_doku_snap_client,
    get_doku_snap_ovo_client,
)
from juloserver.account_payment.services.doku import (
    doku_snap_payment_process_account,
)
from juloserver.julo.clients.constants import DOKUSnapResponseCode
from juloserver.julo.models import PaymentMethod
from juloserver.julo.payment_methods import PaymentMethodCodes, PartnerServiceIds
from juloserver.oneklik_bca.tasks import (
    reinquiry_payment_status as oneklik_reinquiry_payment_status,
)

logger = logging.getLogger(__name__)


@task(queue="repayment_high")
def check_repayment_process(customer_id: int, payback_transactions: QuerySet) -> None:
    logger.info(
        {
            "action": "juloserver.account_payment.tasks.repayment_tasks.check_repayment_process",
            "customer_id": customer_id,
        }
    )

    is_snap = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.BCA_INQUIRY_SNAP,
        is_active=True
    )

    for payback_transaction in payback_transactions:
        if payback_transaction.payback_service in RepaymentRecallPaymentMethod.gopay_channels():
            gopay_repayment_inquiry.delay(payback_transaction.id)
        elif payback_transaction.payback_service == RepaymentRecallPaymentMethod.BCA:
            if is_snap:
                bca_snap_repayment_inquiry.delay(payback_transaction.id)
            else:
                bca_repayment_inquiry.delay(payback_transaction.id)
        elif payback_transaction.payback_service == RepaymentRecallPaymentMethod.ONEKLIK_BCA:
            oneklik_reinquiry_payment_status.delay(payback_transaction.transaction_id)
        elif payback_transaction.payback_service == RepaymentRecallPaymentMethod.OVO:
            ovo_repayment_inquiry.delay(payback_transaction.id)
        elif payback_transaction.payback_service == RepaymentRecallPaymentMethod.FASPAY:
            faspay_snap_inquiry_payment_status.delay(payback_transaction.id)
        elif payback_transaction.payback_service == RepaymentRecallPaymentMethod.DOKU:
            doku_snap_inquiry_payment_status.delay(payback_transaction.id)
        elif payback_transaction.payback_service == RepaymentRecallPaymentMethod.OVO_TOKENIZATION:
            ovo_tokenization_inquiry_payment_status(payback_transaction.id)
        else:
            logger.warning(
                {
                    "action": "juloserver.account_payment.tasks."
                              "repayment_tasks.check_repayment_process",
                    "error": "payback service not eligible",
                    "payback_transaction_id": payback_transaction.id,
                    "payback_service": payback_transaction.service,
                    "customer_id": customer_id
                }
            )


@task(queue="repayment_high")
def gopay_repayment_inquiry(payback_id: int) -> None:
    logger.info(
        {
            "action": "juloserver.account_payment.tasks."
                      "repayment_tasks.gopay_repayment_inquiry",
            "payback_transaction_id": payback_id,
        }
    )
    with transaction.atomic():
        payback_transaction = PaybackTransaction.objects.select_for_update().get(pk=payback_id)
        gopay_service = GopayServices()
        response = gopay_service.get_transaction_status(payback_transaction.transaction_id)
        logger.info(
            {
                "action": "juloserver.account_payment.tasks."
                          "repayment_tasks.gopay_repayment_inquiry",
                "payback_transaction_id": payback_id,
                "response": response
            }
        )

        if "transaction_status" not in response or response["transaction_status"] != "settlement":
            logger.warning(
                {
                    "action": "juloserver.account_payment.tasks."
                              "repayment_tasks.gopay_repayment_inquiry",
                    "error": "transaction status is not settlement",
                    "payback_transaction_id": payback_id,
                    "response": response
                }
            )
            return
        payment_processed = process_gopay_repayment_for_account(payback_transaction, response)
        if payment_processed:
            execute_after_transaction_safely(
                lambda: send_pn_recall_repayment_success.delay(
                    payback_transaction.customer_id,
                    payback_transaction.amount,
                )
            )


@task(queue="repayment_high")
def bca_repayment_inquiry(payback_id):
    logger.info(
        {
            "action": "juloserver.account_payment.tasks.repayment_tasks.bca_repayment_inquiry",
            "payback_transaction_id": payback_id,
        }
    )
    payback_transaction = PaybackTransaction.objects.filter(id=payback_id).last()

    if payback_transaction.is_processed:
        return

    bca_client = get_julo_va_bca_client()
    transaction_status_list = bca_client. inquiry_status(payback_transaction.transaction_id)

    if not transaction_status_list:
        logger.warning({
            'action': 'juloserver.account_payment.tasks.repayment_tasks.bca_repayment_inquiry',
            'payback_transaction_id': payback_id,
            'transaction_id': payback_transaction.transaction_id,
            'response': transaction_status_list,
            'error': "empty response transaction data from bca"
        })
        return

    logger.info({
        'action': 'juloserver.account_payment.tasks.repayment_tasks.bca_repayment_inquiry',
        'transaction_id': payback_transaction.transaction_id,
        'response': transaction_status_list
    })

    transaction_status = transaction_status_list[0]

    if transaction_status.get('PaymentFlagStatus') != 'Success':
        logger.warning({
            'action': 'juloserver.account_payment.tasks.repayment_tasks.bca_repayment_inquiry',
            'payback_transaction_id': payback_id,
            'transaction_id': payback_transaction.transaction_id,
            'response': transaction_status_list,
            'error': "empty response transaction data from bca"
        })
        return

    trans_date = transaction_status['TransactionDate']
    transaction_status['TransactionDate'] = parse(trans_date).strftime('%d/%m/%Y %H:%M:%S')

    bca_process_payment(
        payback_transaction.payment_method,
        payback_transaction,
        transaction_status)
    send_pn_recall_repayment_success.delay(
        payback_transaction.customer_id,
        payback_transaction.amount,
    )


@task(queue="repayment_high")
def bca_snap_repayment_inquiry(payback_id):
    logger.info(
        {
            "action": "juloserver.account_payment.tasks.repayment_tasks.bca_repayment_inquiry",
            "payback_transaction_id": payback_id,
        }
    )
    payback_transaction = PaybackTransaction.objects.filter(id=payback_id).last()

    if payback_transaction.is_processed:
        return

    bca_client = get_julo_bca_snap_client(
        customer_id=payback_transaction.customer.id if payback_transaction.customer else None,
        loan_id=payback_transaction.loan.id if payback_transaction.loan else None,
        payback_transaction_id=payback_transaction.id,
    )
    virtual_account = payback_transaction.payment_method.virtual_account
    transaction_status_list, error = bca_client.inquiry_status_snap(
        virtual_account,
        payback_transaction.transaction_id)

    if error:
        logger.warning({
            'action': 'juloserver.account_payment.tasks.repayment_tasks.bca_snap_repayment_inquiry',
            'payback_transaction_id': payback_id,
            'transaction_id': payback_transaction.transaction_id,
            'response': transaction_status_list,
            'error': "empty response transaction data from bca"
        })
        return

    logger.info({
        'action': 'juloserver.account_payment.tasks.repayment_tasks.bca_snap_repayment_inquiry',
        'transaction_id': payback_transaction.transaction_id,
        'response': transaction_status_list
    })

    transaction_status = transaction_status_list

    if transaction_status.get('PaymentFlagStatus') != '00':
        logger.warning({
            'action': 'juloserver.account_payment.tasks.repayment_tasks.bca_snap_repayment_inquiry',
            'payback_transaction_id': payback_id,
            'transaction_id': payback_transaction.transaction_id,
            'response': transaction_status_list,
            'error': "empty response transaction data from bca"
        })
        return

    trans_date = transaction_status['transactionDate']
    transaction_status['transactionDate'] = parse(trans_date).strftime('%d/%m/%Y %H:%M:%S')

    bca_process_payment(
        payback_transaction.payment_method,
        payback_transaction,
        transaction_status)
    send_pn_recall_repayment_success.delay(
        payback_transaction.customer_id,
        payback_transaction.amount,
    )


@task(queue="repayment_high")
def ovo_repayment_inquiry(payback_id):
    logger.info(
        {
            "action": "juloserver.account_payment.tasks.repayment_tasks.ovo_repayment_inquiry",
            "payback_transaction_id": payback_id,
        }
    )
    payback_transaction = PaybackTransaction.objects.filter(id=payback_id).last()

    if payback_transaction.is_processed:
        return

    payment_method = payback_transaction.payment_method
    if not payment_method:
        logger.warning({
            'action': 'juloserver.account_payment.tasks.repayment_tasks.ovo_repayment_inquiry',
            'payback_transaction_id': payback_id,
            'transaction_id': payback_transaction.transaction_id,
            'error': 'payment method va not found',
        })
        return

    ovo_repayment_transaction = OvoRepaymentTransaction.objects.filter(
        transaction_id=payback_transaction.transaction_id
    ).last()

    if not ovo_repayment_transaction:
        logger.warning({
            'action': 'juloserver.account_payment.tasks.repayment_tasks.ovo_repayment_inquiry',
            'payback_transaction_id': payback_id,
            'transaction_id': payback_transaction.transaction_id,
            'error': "ovo repayment transaction is not found",
        })
        return

    account_payment_xid = ovo_repayment_transaction.account_payment_xid.account_payment_xid
    ovo_client = get_ovo_client()
    response, error = ovo_client.inquiry_payment_status(
        ovo_repayment_transaction.transaction_id, account_payment_xid
    )

    if error:
        logger.error({
            'action': 'juloserver.account_payment.tasks.repayment_tasks.ovo_repayment_inquiry',
            'payback_transaction_id': payback_id,
            'transaction_id': payback_transaction.transaction_id,
            'error': error,
        })
        return

    logger.info({
        'action': 'juloserver.account_payment.tasks.repayment_tasks.ovo_repayment_inquiry',
        'transaction_id': payback_transaction.transaction_id,
        'response': response
    })

    process_payment = False
    input_params = dict(status=OvoTransactionStatus.PAYMENT_FAILED)
    if response['payment_status_code'] == '2':
        note = 'payment with va %s %s' % (
            payment_method.virtual_account, payment_method.payment_method_name)
        process_payment = faspay_payment_process_account(payback_transaction, response, note)
        if process_payment:
            input_params = dict(status=OvoTransactionStatus.SUCCESS)

    update_ovo_transaction_after_inquiry(
        ovo_repayment_transaction,
        input_params,
    )
    if process_payment:
        send_pn_recall_repayment_success.delay(
            payback_transaction.customer_id,
            payback_transaction.amount,
        )


@task(queue="repayment_normal")
def send_pn_recall_repayment_success(customer_id, amount):
    device = Device.objects.filter(customer_id=customer_id).last()
    if not have_pn_device(device):
        logger.warning(
            {
                "action": "juloserver.account_payment.tasks."
                          "repayment_tasks.send_pn_recall_repayment_success",
                "error": "transaction status is not settlement",
                "customer_id": customer_id,
                "amount": amount,
            }
        )
        return False
    julo_pn_client = get_julo_pn_client()
    julo_pn_client.pn_recall_repayment_success(device.gcm_reg_id, amount)


@task(queue="repayment_normal")
def update_latest_payment_method_task(payback_transaction_id) -> None:
    update_latest_payment_method(payback_transaction_id)


@task(queue="collection_dialer_low")
def update_collection_risk_bucket_paid_first_installment_task(
    account_id: int, account_payment_id: int
) -> None:
    update_collection_risk_bucket_paid_first_installment(account_id, account_payment_id)


@task(queue="collection_dialer_low")
def reversal_update_collection_risk_bucket_paid_first_installment_task(account_id: int) -> None:
    reversal_update_collection_risk_bucket_paid_first_installment(account_id)


@task(queue='collection_dialer_normal')
def primary_ptp_update_for_j1_async(
    account_payment_id: int, ptp_date: date = None, total_paid_amount: int = 0
) -> None:
    fn_name = 'primary_ptp_update_for_j1_async'
    logger.info(
        {
            'action': fn_name,
            'account_payment_id': account_payment_id,
            'ptp_date': ptp_date,
            'total_paid_amount': total_paid_amount,
            'message': 'task begin',
        }
    )
    try:
        primary_ptp_update_for_j1(account_payment_id, ptp_date, total_paid_amount)
    except Exception as err:
        logger.error(
            {'action': fn_name, 'account_payment_id': account_payment_id, 'message': str(err)}
        )
        get_julo_sentry_client().captureException()
        return

    logger.info(
        {'action': fn_name, 'account_payment_id': account_payment_id, 'message': 'task finish'}
    )
    return


@task(queue="repayment_normal")
def faspay_snap_inquiry_payment_status(payback_id):
    payback_transaction = PaybackTransaction.objects.filter(id=payback_id).last()
    logger.info(
        {
            "action": "juloserver.account_payment.tasks.repayment_tasks."
            "faspay_snap_inquiry_payment_status",
            "payback_transaction_id": payback_id,
            'transaction_id': payback_transaction.transaction_id,
            'inquiry_request_id': payback_transaction.inquiry_request_id,
        }
    )

    if payback_transaction.is_processed:
        return

    payment_method = payback_transaction.payment_method
    if not payment_method:
        logger.warning(
            {
                'action': 'juloserver.account_payment.tasks.repayment_tasks.'
                'faspay_snap_inquiry_payment_status',
                'payback_transaction_id': payback_id,
                'transaction_id': payback_transaction.transaction_id,
                'inquiry_request_id': payback_transaction.inquiry_request_id,
                'error': 'payment method va not found',
            }
        )
        return

    payment_method_code = payment_method.payment_method_code
    # fmt: off
    customer_no = payment_method.virtual_account[len(payment_method_code):]
    # fmt: on
    channel_code = get_channel_code(payment_method)

    if payment_method.payment_method_code == settings.FASPAY_PREFIX_MAYBANK:
        payment_method_code = payment_method.virtual_account[:8]
        customer_no = payment_method.virtual_account[8:]
        channel_code = FaspayPaymentChannelCode.MAYBANK

    merchant_id = get_faspay_merchant_id(payment_method.payment_method_code)

    faspay_snap_client = get_faspay_snap_client(merchant_id)
    response, error = faspay_snap_client.inquiry_status(
        customer_no,
        payment_method.virtual_account,
        channel_code,
        payment_method_code,
        payback_transaction.transaction_id,
        payback_transaction.inquiry_request_id,
    )

    if error:
        logger.warning(
            {
                'action': 'juloserver.account_payment.tasks.repayment_tasks.'
                'faspay_snap_inquiry_payment_status',
                'payback_transaction_id': payback_id,
                'transaction_id': payback_transaction.transaction_id,
                'inquiry_request_id': payback_transaction.inquiry_request_id,
                'error': error,
            }
        )
        return

    if response['responseCode'] == '2002600':
        if response['virtualAccountData']['paymentFlagStatus'] == '00':
            note = 'payment with va {} {}'.format(
                payment_method.virtual_account, payment_method.payment_method_name
            )
            faspay_snap_payment_process_account(
                payback_transaction, response['virtualAccountData'], note
            )


def get_faspay_merchant_id(payment_method_code):
    payment_method_codes = {
        settings.FASPAY_PREFIX_INDOMARET: settings.FASPAY_SNAP_OUTBOUND_MERCHANT_ID_INDOMARET,
        settings.FASPAY_PREFIX_ALFAMART: settings.FASPAY_SNAP_OUTBOUND_MERCHANT_ID_ALAFMART,
        settings.FASPAY_PREFIX_PERMATA: settings.FASPAY_SNAP_OUTBOUND_MERCHANT_ID_PERMATA,
        settings.FASPAY_PREFIX_BNI: settings.FASPAY_SNAP_OUTBOUND_MERCHANT_ID,
        settings.FASPAY_PREFIX_BNI_V2: settings.FASPAY_SNAP_OUTBOUND_MERCHANT_ID_BNI_V2,
    }

    return payment_method_codes.get(payment_method_code, settings.FASPAY_SNAP_OUTBOUND_MERCHANT_ID)


def get_channel_code(payment_method):
    payment_method_codes = {
        settings.FASPAY_PREFIX_MAYBANK: FaspayPaymentChannelCode.MAYBANK,
        settings.FASPAY_PREFIX_MANDIRI: FaspayPaymentChannelCode.MANDIRI,
        settings.FASPAY_PREFIX_PERMATA: FaspayPaymentChannelCode.PERMATA,
        settings.FASPAY_PREFIX_BNI: FaspayPaymentChannelCode.BNI,
        settings.FASPAY_PREFIX_BNI_V2: FaspayPaymentChannelCode.BNI,
        settings.FASPAY_PREFIX_BRI: FaspayPaymentChannelCode.BRI,
        settings.FASPAY_PREFIX_INDOMARET: FaspayPaymentChannelCode.INDOMARET,
        settings.FASPAY_PREFIX_ALFAMART: FaspayPaymentChannelCode.ALFAMART,
    }

    return payment_method_codes.get(
        payment_method.payment_method_code, FaspayPaymentChannelCode.BCA
    )


def get_partner_service_id(payment_method: PaymentMethod) -> str:
    partner_service_ids = {
        PaymentMethodCodes.MANDIRI_DOKU: PartnerServiceIds.MANDIRI_DOKU,
        PaymentMethodCodes.BRI_DOKU: PartnerServiceIds.BRI_DOKU,
        PaymentMethodCodes.PERMATA_DOKU: PartnerServiceIds.PERMATA_DOKU,
    }

    partner_service_id = partner_service_ids.get(payment_method.payment_method_code, '')

    return partner_service_id


@task(queue='repayment_normal')
def faspay_snap_inquiry_transaction():
    start_dt = timezone.localtime(timezone.now()).date() - timedelta(days=7)
    end_dt = timezone.localtime(timezone.now()) - timedelta(hours=1)

    with transaction.atomic():
        payback_transaction_ids = (
            PaybackTransaction.objects.select_for_update()
            .filter(
                is_processed=False,
                cdate__range=(start_dt, end_dt),
                inquiry_request_id__isnull=False,
                payment_method__isnull=False,
                payback_service='faspay',
                payment__isnull=False,
                account__isnull=True,
                payment__payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
            )
            .values_list('id', flat=True)
        )

        account_payback_trx_ids = (
            PaybackTransaction.objects.select_for_update()
            .filter(
                is_processed=False,
                cdate__range=(start_dt, end_dt),
                inquiry_request_id__isnull=False,
                payment_method__isnull=False,
                payback_service='faspay',
                account__isnull=False,
            )
            .values_list('id', flat=True)
        )

        logger.info(
            {
                'action': 'juloserver.account_payment.tasks.repayment_tasks.'
                'faspay_snap_inquiry_transaction',
            }
        )

        for payback_id in list(payback_transaction_ids) + list(account_payback_trx_ids):
            faspay_snap_inquiry_payment_status.delay(payback_id)


@task(queue="repayment_normal")
def doku_snap_inquiry_payment_status(payback_id):
    logger.info(
        {
            "action": "juloserver.account_payment.tasks.repayment_tasks."
            "doku_snap_inquiry_payment_status",
            "payback_transaction_id": payback_id,
        }
    )

    payback_transaction = PaybackTransaction.objects.filter(id=payback_id).last()

    if payback_transaction.is_processed:
        return

    payment_method = payback_transaction.payment_method
    if not payment_method:
        logger.warning(
            {
                'action': 'juloserver.account_payment.tasks.repayment_tasks.'
                'doku_snap_inquiry_payment_status',
                'payback_transaction_id': payback_id,
                'transaction_id': payback_transaction.transaction_id,
                'error': 'payment method va not found',
            }
        )
        return

    doku_snap_client = get_doku_snap_client(
        customer_id=payback_transaction.customer.id if payback_transaction.customer else None,
        loan_id=payback_transaction.loan.id if payback_transaction.loan else None,
        payback_transaction_id=payback_transaction.id,
    )
    partner_service_id = get_partner_service_id(payment_method)
    customer_no = payment_method.virtual_account[len(partner_service_id):]

    response, error = doku_snap_client.inquiry_status(
        partner_service_id=partner_service_id,
        customer_no=customer_no,
        virtual_account_no=payment_method.virtual_account,
        transaction_id=payback_transaction.transaction_id,
    )

    if error:
        logger.warning(
            {
                'action': 'juloserver.account_payment.tasks.repayment_tasks.'
                'doku_snap_inquiry_payment_status',
                'payback_transaction_id': payback_id,
                'transaction_id': payback_transaction.transaction_id,
                'error': error,
            }
        )
        return

    if (
        response.get('responseCode') == DOKUSnapResponseCode.SUCCESS_INQUIRY_STATUS
        and response.get('virtualAccountData', {}).get('paymentFlagReason', {}).get('english')
        == 'Success'
    ):
        note = 'payment with va {} {}'.format(
            payment_method.virtual_account, payment_method.payment_method_name
        )
        doku_snap_payment_process_account(payback_transaction, response['virtualAccountData'], note)


@task(queue='bank_inquiry')
def doku_snap_inquiry_transaction():
    start_dt = timezone.localtime(timezone.now()).date()
    end_dt = timezone.localtime(timezone.now()) - timedelta(minutes=2)

    with transaction.atomic():
        payback_transaction_ids = PaybackTransaction.objects.filter(
            is_processed=False,
            cdate__range=(start_dt, end_dt),
            transaction_id__isnull=False,
            payment_method__isnull=False,
            payback_service=RepaymentRecallPaymentMethod.DOKU,
            payment__isnull=False,
            account__isnull=True,
            payment__payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
        ).values_list('id', flat=True)

        account_payback_trx_ids = PaybackTransaction.objects.filter(
            is_processed=False,
            cdate__range=(start_dt, end_dt),
            transaction_id__isnull=False,
            payment_method__isnull=False,
            payback_service=RepaymentRecallPaymentMethod.DOKU,
            account__isnull=False,
        ).values_list('id', flat=True)

        logger.info(
            {
                'action': 'juloserver.account_payment.tasks.repayment_tasks.'
                'doku_snap_inquiry_transaction',
            }
        )

        for payback_id in list(payback_transaction_ids) + list(account_payback_trx_ids):
            doku_snap_inquiry_payment_status.delay(payback_id)


@task(queue="repayment_normal")
def ovo_tokenization_inquiry_transaction():
    now = timezone.now()
    start_dt = now - timedelta(days=7)
    end_dt = now - timedelta(hours=1)

    with transaction.atomic():
        account_payback_trx_ids = (
            PaybackTransaction.objects.select_for_update()
            .filter(
                is_processed=False,
                cdate__range=(start_dt, end_dt),
                payment_method__isnull=False,
                payback_service=RepaymentRecallPaymentMethod.OVO_TOKENIZATION,
                account__isnull=False,
            )
            .values_list('id', flat=True)
        )

        logger.info(
            {
                'action': 'juloserver.account_payment.tasks.repayment_tasks.'
                'ovo_tokenization_inquiry_transaction',
            }
        )

        for payback_id in account_payback_trx_ids:
            ovo_tokenization_inquiry_payment_status.delay(payback_id)


@task(queue="repayment_normal")
def ovo_tokenization_inquiry_payment_status(payback_id):
    payback_transaction = PaybackTransaction.objects.filter(id=payback_id).last()

    logger.info(
        {
            "action": "juloserver.account_payment.tasks.repayment_tasks."
            "ovo_tokenization_inquiry_payment_status",
            "payback_transaction_id": payback_id,
            'transaction_id': payback_transaction.transaction_id,
            'inquiry_request_id': payback_transaction.inquiry_request_id,
        }
    )

    if payback_transaction.is_processed:
        return

    payment_method = payback_transaction.payment_method
    if not payment_method:
        logger.warning(
            {
                'action': 'juloserver.account_payment.tasks.repayment_tasks.'
                'ovo_tokenization_inquiry_payment_status',
                'payback_transaction_id': payback_id,
                'transaction_id': payback_transaction.transaction_id,
                'inquiry_request_id': payback_transaction.inquiry_request_id,
                'error': 'payment method va not found',
            }
        )
        return

    ovo_wallet_account = OvoWalletAccount.objects.filter(
        account_id=payback_transaction.account_id
    ).last()

    if not ovo_wallet_account:
        return

    ovo_wallet_transaction = OvoWalletTransaction.objects.filter(
        ovo_wallet_account=ovo_wallet_account,
        partner_reference_no=payback_transaction.transaction_id,
    ).last()

    if not ovo_wallet_transaction:
        return

    doku_client = get_doku_snap_ovo_client()
    response, error = doku_client.ovo_inquiry_payment(
        payback_transaction.transaction_id,
        ovo_wallet_transaction.amount,
        ovo_wallet_transaction.reference_no,
    )

    if response['responseCode'] == '2005500':
        transaction_date = (
            datetime.strptime(response['paidTime'], "%Y-%m-%dT%H:%M:%S%z")
            if response.get('paidTime')
            else timezone.localtime(timezone.now())
        )

        process_ovo_repayment(
            payback_id,
            transaction_date,
            int(float(response['transAmount']['value'])),
            response.get('originalReferenceNo'),
            response['latestTransactionStatus'],
            response['transactionStatusDesc'].upper(),
            ovo_wallet_transaction,
            'SALE'
        )
