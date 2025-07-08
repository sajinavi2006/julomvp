import json
import logging
from django.utils import timezone
from babel.dates import format_date

from juloserver.account_payment.models import CashbackClaimPayment
from juloserver.julo.models import (
    PaybackTransactionStatusHistory,
    PaybackTransaction,
    Customer,
    FeatureSetting,
    PaymentMethod,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.payback.models import GopayRepaymentTransaction, GopayAutodebetTransaction
from juloserver.payback.constants import GopayTransactionStatusConst
from juloserver.autodebet.models import AutodebetAPILog
from juloserver.autodebet.constants import VendorConst, GopayErrorCode
from juloserver.autodebet.services.autodebet_services import suspend_autodebet_insufficient_balance
from juloserver.autodebet.services.account_services import get_existing_autodebet_account
from juloserver.julo.models import PaymentEvent
from datetime import datetime, timedelta
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.account.models import AccountTransaction
from juloserver.account_payment.constants import CashbackClaimConst
from juloserver.julo.services2 import encrypt
from juloserver.streamlined_communication.models import StreamlinedCommunication


logger = logging.getLogger(__name__)


def create_pbt_status_history(transaction, old_status, new_status):
    return PaybackTransactionStatusHistory.objects.create(
        payback_transaction=transaction,
        old_status_code=old_status,
        new_status_code=new_status)


def record_transaction_data_for_autodebet_gopay(data):
    # importing here due to circular import
    from juloserver.moengage.tasks import send_event_autodebit_failed_deduction_task
    from juloserver.autodebet.tasks import (
        send_slack_notify_autodebet_gopay_failed_subscription_and_deduction)

    if not data:
        return None

    # update gopay autodebet transaction details
    autodebet_gopay_transaction = GopayAutodebetTransaction.objects.filter(
        subscription_id=data['subscription_id']
    ).last()

    if not autodebet_gopay_transaction:
        logger.error({
            'action': 'juloserver.payback.services.payback.'
                      'record_transaction_data_for_autodebet_gopay',
            'error': 'No autodebet_gopay_transaction is found for this {} subscription_id'.format(
                data['subscription_id']),
        })
        return None

    customer = autodebet_gopay_transaction.customer
    account_payment = autodebet_gopay_transaction.account_payment
    # record details in autodebet api log
    AutodebetAPILog.objects.create(
        vendor=VendorConst.GOPAY,
        http_status_code=data['status_code'],
        request_type='[POST]/GOPAY/CALLBACK',
        response=json.dumps(data) if data else None,
        account_id=customer.account.id,
        account_payment_id=account_payment.id,
    )

    amount = int(float(data['gross_amount']))
    if data['transaction_status'] == GopayTransactionStatusConst.DENY:
        autodebet_gopay_transaction.update_safely(
            transaction_id=data['order_id'],
            external_transaction_id=data['transaction_id'],
            status=data['transaction_status'],
            status_code=data['status_code'],
            status_desc=data['channel_response_message'],
            is_active=False
        )

        if data['channel_response_message'] in [
            GopayErrorCode.INSUFFICIENT_BALANCE,
            GopayErrorCode.NOT_ENOUGH_BALANCE,
        ]:
            autodebet_account = get_existing_autodebet_account(customer.account, VendorConst.GOPAY)
            suspend_autodebet_insufficient_balance(autodebet_account, VendorConst.GOPAY)

        send_slack_notify_autodebet_gopay_failed_subscription_and_deduction.delay(
            customer.account.id,
            account_payment.id,
            data['channel_response_message'],
            autodebet_gopay_transaction.subscription_id,
        )
        send_event_autodebit_failed_deduction_task.delay(
            account_payment.id,
            customer.id,
            VendorConst.GOPAY
        )
    else:
        is_partial = False
        if autodebet_gopay_transaction.amount != amount:
            is_partial = True
        autodebet_gopay_transaction.update_safely(
            transaction_id=data['order_id'],
            external_transaction_id=data['transaction_id'],
            status=data['transaction_status'],
            status_code=data['status_code'],
            is_active=False,
            paid_amount=amount,
            is_partial=is_partial
        )

    # record gopay repayment transaction details
    GopayRepaymentTransaction.objects.create(
        transaction_id=data['order_id'],
        external_transaction_id=data['transaction_id'],
        status=data['transaction_status'],
        amount=amount,
        source='gopay_autodebet',
        status_code=data['status_code'],
        status_message=data['status_message'],
        gopay_account=autodebet_gopay_transaction.gopay_account
    )

    # record payaback transaction details
    if data['transaction_status'] == GopayTransactionStatusConst.SETTLEMENT:
        transaction = PaybackTransaction.objects.filter(
            transaction_id=data['order_id'],
            payback_service='gopay_autodebet',
            is_processed=True
        ).last()
        if transaction:
            logger.info({
                'action': 'juloserver.payback.services.payback.'
                          'record_transaction_data_for_autodebet_gopay',
                'payback_transaction_id': transaction.id,
                'error': 'Transaction already exists for this {} order_id'.format(
                    data['order_id']),
            })
            return transaction
        else:
            payment_method = autodebet_gopay_transaction.customer.paymentmethod_set.filter(
                payment_method_name='Autodebet GOPAY'
            ).last()
            transaction = PaybackTransaction.objects.create(
                transaction_id=data['order_id'],
                customer=customer,
                payment_method=payment_method,
                payback_service='gopay_autodebet',
                amount=amount,
                account=customer.account,
                is_processed=False
            )

            return transaction

    return None


def get_email_payment_success_context(payback: PaybackTransaction, customer: Customer):
    from juloserver.account_payment.services.account_payment_related import (
        get_potential_cashback_by_account_payment,
    )
    from juloserver.account_payment.services.earning_cashback import (
        get_paramters_cashback_new_scheme,
    )
    customer = payback.customer
    cashback_exp_date = None
    cashback_amount = None
    partial_payment = None
    is_autodebet_offer = False
    payment_events = None
    unpaid_account_payment = payback.account.get_oldest_unpaid_account_payment()
    if (unpaid_account_payment and payback.amount > unpaid_account_payment.paid_amount) or (
        customer.last_application
        and customer.last_application.product_line_code != ProductLineCodes.J1
    ):
        cashback_amount = None
        partial_payment = None
    elif unpaid_account_payment and unpaid_account_payment.paid_amount != 0:
        # partial payment with cashback dpd < -2
        # transaction_date = payback.transaction_date
        due_date, percentage_mapping = get_paramters_cashback_new_scheme()
        cashback_parameters = dict(
            is_eligible_new_cashback=payback.account.is_cashback_new_scheme,
            due_date=due_date,
            percentage_mapping=percentage_mapping,
            account_status=payback.account.status_id,
        )
        cashback_amount = get_potential_cashback_by_account_payment(
            unpaid_account_payment,
            payback.account.cashback_counter,
            cashback_parameters=cashback_parameters,
        )
        partial_payment = True
        if str(cashback_amount) == '0' or "autodebet" in str(payback.payback_service).lower():
            cashback_amount = None
        elif isinstance(cashback_amount, int):
            cashback_amount = f"{cashback_amount:,}".replace(",", ".")
            cashback_exp_date = format_date(
                unpaid_account_payment.due_date - timedelta(days=2),
                format='d MMM yyyy',
                locale='id_ID',
            )
        else:
            cashback_amount = None
    # else full payment done

    payment_method_name = None
    payment_method = payback.payment_method
    if not payment_method and payback.transaction_id:
        payment_events = PaymentEvent.objects.filter(
            payment_receipt=payback.transaction_id,
        )
        payment_event = payment_events.last()
        if payment_event:
            payment_method = payment_event.payment_method

    if payment_method:
        payment_method_name = payment_method.payment_method_name.replace(' Biller', '').replace(
            ' Tokenization', ''
        )
    transaction_date = timezone.localtime(payback.transaction_date)

    email_success_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.EMAIL_PAYMENT_SUCCESS,
        is_active=True,
    ).last()
    if email_success_fs and email_success_fs.parameters.get('autodebet', None):
        dpd_start = email_success_fs.parameters["autodebet"].get('dpd_start')
        dpd_end = email_success_fs.parameters["autodebet"].get('dpd_end')
        if dpd_start is not None and dpd_end is not None:
            if not payment_events:
                account_trx = AccountTransaction.objects.filter(payback_transaction=payback).last()
                if account_trx:
                    payment_events = PaymentEvent.objects.filter(account_transaction=account_trx)
            if payment_events.exists():
                oldest_payment_event = (
                    payment_events.select_related('payment__account_payment')
                    .order_by('payment__account_payment__due_date')
                    .first()
                )
                today = timezone.localtime(timezone.now()).date()
                time_delta = today - oldest_payment_event.payment.account_payment.due_date
                dpd = time_delta.days
                if dpd >= dpd_start and dpd <= dpd_end:
                    is_autodebet_offer = True

    context = {
        "fullname": customer.fullname,
        "paid_amount": '{:,}'.format(payback.amount).replace(',', '.'),
        "payment_method_name": payment_method_name,
        "transaction_date": format_date(transaction_date, 'dd MMMM yyyy', locale='id_ID'),
        "cashback_exp_date": cashback_exp_date,
        "cashback_amount": cashback_amount,
        "partial_payment": partial_payment,
        "is_autodebet_offer": is_autodebet_offer,
    }

    return context


def get_cashback_amount_from_payback(payback):
    from juloserver.account_payment.services.account_payment_related import (
        get_potential_cashback_by_account_payment,
    )
    from juloserver.account_payment.services.earning_cashback import (
        get_paramters_cashback_new_scheme,
    )

    cashback_amount = None
    customer = payback.customer
    unpaid_account_payment = payback.account.get_oldest_unpaid_account_payment()
    if (unpaid_account_payment and payback.amount > unpaid_account_payment.paid_amount) or (
        customer.last_application
        and customer.last_application.product_line_code != ProductLineCodes.J1
    ):
        cashback_amount = None
    elif unpaid_account_payment and unpaid_account_payment.paid_amount != 0:
        due_date, percentage_mapping = get_paramters_cashback_new_scheme()
        cashback_parameters = dict(
            is_eligible_new_cashback=payback.account.is_cashback_new_scheme,
            due_date=due_date,
            percentage_mapping=percentage_mapping,
            account_status=payback.account.status_id,
        )
        cashback_amount = get_potential_cashback_by_account_payment(
            unpaid_account_payment,
            payback.account.cashback_counter,
            cashback_parameters=cashback_parameters,
        )
        if cashback_amount == 0 or "autodebet" in str(payback.payback_service).lower():
            cashback_amount = None
    return cashback_amount


def process_success_email_content(payback, customer, is_cashback_claim_experiment):
    email_subject_map = {
        'email_payment_success.html': 'Mantap, Pembayaran Tagihan JULOmu Berhasil',
        'email_payment_success_cashback.html': 'Pembayaran tagihanmu berhasil! Saatnya klaim cashback',
    }

    account = payback.account
    template_html = "email_payment_success.html"
    context = get_email_payment_success_context(payback, customer)

    if is_cashback_claim_experiment and account:
        latest_cashback_payment = None

        account_trx = AccountTransaction.objects.filter(payback_transaction=payback).last()
        if account_trx:
            latest_payment_event = PaymentEvent.objects.filter(
                account_transaction=account_trx
            ).last()
            if latest_payment_event:
                try:
                    latest_cashback_payment = CashbackClaimPayment.objects.filter(
                        payment_id=latest_payment_event.payment_id,
                        status=CashbackClaimConst.STATUS_ELIGIBLE,
                    ).latest('cdate')
                except CashbackClaimPayment.DoesNotExist:
                    pass

        if latest_cashback_payment:
            max_claim_date = latest_cashback_payment.max_claim_date
            cashback_amount_exp = (
                latest_cashback_payment.cashback_claim.total_cashback_amount
                if latest_cashback_payment.cashback_claim
                else latest_cashback_payment.cashback_amount
            )
            comm = (
                StreamlinedCommunication.objects.select_related('message__info_card_property')
                .filter(template_code="j1_cashback_claim")
                .first()
            )

            message = comm.message if comm else None
            info_card = message.info_card_property if message else None
            url = info_card.card_destination if info_card else None

            if url:
                encrypttext = encrypt()
                account_id_encrypted = encrypttext.encode_string(str(account.id))
                url += account_id_encrypted

            if max_claim_date is not None and cashback_amount_exp is not None and url:
                template_html = "email_payment_success_cashback.html"
                context['max_claim_date'] = max_claim_date
                context['cashback_amount'] = "{:,}".format(cashback_amount_exp).replace(",", ".")
                context['cashback_claim_url'] = url

    subject = email_subject_map.get(template_html, 'Mantap, Pembayaran Tagihan JULOmu Berhasil!')
    return subject, template_html, context


def check_payment_method_vendor(virtual_account_no):
    today = datetime.now()
    payment_switch = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.PAYMENT_METHOD_SWITCH, is_active=True
    ).last()

    # If no active payment switch feature, allow all methods
    if not payment_switch:
        return True

    payment_method = PaymentMethod.objects.filter(virtual_account=virtual_account_no).last()

    # If no payment method found, disallow
    if not payment_method:
        return False

    allowed_methods = {'Bank BRI', 'Bank MANDIRI', 'PERMATA Bank'}

    # If payment method is NOT in allowed list, skip vendor check
    if payment_method.payment_method_name not in allowed_methods:
        return True

    for schedule in payment_switch.parameters['schedule_switch']:
        if payment_method.payment_method_name == schedule['bank']:
            start_date = datetime.strptime(schedule['start_date'], '%Y-%m-%d %H:%M:%S')
            end_date = datetime.strptime(schedule['end_date'], '%Y-%m-%d %H:%M:%S')

            if start_date <= today <= end_date:
                if payment_method.vendor == schedule['vendor']:
                    return True
                return False

    # Otherwise, check if vendor matches any parameter configuration
    return any(
        payment_method.payment_method_name == param['bank']
        and payment_method.vendor == param['vendor']
        for param in payment_switch.parameters['payment_method']
    )
