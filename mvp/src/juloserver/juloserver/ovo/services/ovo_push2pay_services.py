import logging
import time
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.forms import model_to_dict
from django.utils import timezone

from juloserver.account.constants import CheckoutPaymentType
from juloserver.account_payment.constants import CheckoutRequestCons
from juloserver.account_payment.models import AccountPayment, CheckoutRequest
from juloserver.julo.models import PaybackTransaction, PaymentMethod, MobileFeatureSetting
from juloserver.julo.utils import generate_sha1_md5
from juloserver.ovo.clients import get_ovo_client
from juloserver.ovo.constants import (
    OvoConst,
    OvoTransactionStatus,
    OvoMobileFeatureName,
)
from juloserver.ovo.models import (
    OvoRepaymentTransaction,
    OvoRepaymentTransactionHistory,
)
from juloserver.ovo.tasks import store_experiment_data
from juloserver.ovo.utils import mask_phone_number_preserve_last_four_digits

logger = logging.getLogger(__name__)


def construct_transaction_data(account):
    now = timezone.localtime(timezone.now())
    account_payments = account.accountpayment_set.not_paid_active().order_by('due_date')

    if not account_payments:
        return {}, None, 'No payment due today'

    due_amount = account_payments.first().due_amount
    for idx, account_payment in enumerate(account_payments.iterator()):
        if account_payment.due_date <= now.date() and idx > 0:
            due_amount += account_payment.due_amount

    account_payment = account_payments.first()
    account_payment_xid = account_payment.account_payment_xid
    if not account_payment_xid:
        account_payment.update_safely(account_payment_xid=str(time.time()).replace('.', '')[:14])
        account_payment_xid = account_payment.account_payment_xid

    application = account.application_set.last()
    faspay_user_id = settings.FASPAY_USER_ID
    faspay_password = settings.FASPAY_PASSWORD
    signature_keystring = '{}{}{}'.format(faspay_user_id, faspay_password, account_payment_xid)
    julo_signature = generate_sha1_md5(signature_keystring)

    return (
        {
            'merchant_id': OvoConst.MERCHANT_ID,
            'merchant': OvoConst.MERCHANT_NAME,
            'bill_no': account_payment_xid,
            'bill_date': now.strftime("%Y-%m-%d %H:%M:%S"),
            'bill_expired': (now + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"),
            'bill_desc': 'JULO {} payment OVO Faspay'.format(account_payment_xid),
            'bill_currency': 'IDR',
            'bill_total': due_amount,
            'payment_channel': 812,
            'pay_type': 1,
            'cust_no': application.application_xid,
            'cust_name': application.fullname,
            'msisdn': application.mobile_phone_1,
            'email': application.email,
            'terminal': 10,
            'item': {'tenor': 0},
            'signature': julo_signature,
        },
        account_payment,
        '',
    )


def construct_checkout_experience_transaction_data(account, checkout_id):
    now = timezone.localtime(timezone.now())
    checkout_request = CheckoutRequest.objects.filter(
        id=checkout_id,
        status=CheckoutRequestCons.ACTIVE,
        expired_date__gt=timezone.localtime(timezone.now()),
        account_id=account,
    ).last()

    if not checkout_request:
        logger.info(
            {
                'action': 'juloserver.ovo.services.transaction_services.'
                'construct_checkout_experience_transaction_data',
                'data': {'account_id': account.id},
                'message': 'Checkout request not found',
            }
        )
        return {}, None, 'Checkout request not found'

    account_payments = account.accountpayment_set.not_paid_active().order_by('due_date')
    account_payment = account_payments.first() if account_payments else None

    if checkout_request.type != CheckoutPaymentType.REFINANCING:
        account_payment = AccountPayment.objects.get_or_none(
            pk=checkout_request.account_payment_ids[0]
        )

    amount = checkout_request.total_payments

    if not account_payment:
        logger.info(
            {
                'action': 'juloserver.ovo.services.transaction_services.'
                'construct_checkout_experience_transaction_data',
                'data': {'account_payment_id': checkout_request.account_payment_ids[0]},
                'message': 'Account payment not found',
            }
        )
        return {}, None, 'Account payment not found'

    account_payment_xid = account_payment.account_payment_xid
    if not account_payment_xid:
        account_payment.update_safely(account_payment_xid=str(time.time()).replace('.', '')[:14])
        account_payment_xid = account_payment.account_payment_xid

    application = account.application_set.last()
    faspay_user_id = settings.FASPAY_USER_ID
    faspay_password = settings.FASPAY_PASSWORD
    signature_keystring = '{}{}{}'.format(faspay_user_id, faspay_password, account_payment_xid)
    julo_signature = generate_sha1_md5(signature_keystring)

    return (
        {
            'merchant_id': OvoConst.MERCHANT_ID,
            'merchant': OvoConst.MERCHANT_NAME,
            'bill_no': account_payment_xid,
            'bill_date': now.strftime("%Y-%m-%d %H:%M:%S"),
            'bill_expired': (now + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"),
            'bill_desc': 'JULO {} payment OVO Faspay'.format(account_payment_xid),
            'bill_currency': 'IDR',
            'bill_total': amount,
            'payment_channel': 812,
            'pay_type': 1,
            'cust_no': application.application_xid,
            'cust_name': application.fullname,
            'msisdn': application.mobile_phone_1,
            'email': application.email,
            'terminal': 10,
            'item': {'tenor': 0},
            'signature': julo_signature,
        },
        account_payment,
        '',
    )


def create_transaction_data(account, checkout_id=None):
    is_checkout_experience = False
    if checkout_id:
        transaction_data, account_payment, message = construct_checkout_experience_transaction_data(
            account, checkout_id
        )
        is_checkout_experience = True
    else:
        transaction_data, account_payment, message = construct_transaction_data(account)

    if not message:
        ovo_client = get_ovo_client()
        response, error = ovo_client.create_transaction_data(transaction_data)

        if error:
            return {}, error

        input_params = dict(
            transaction_id=response['trx_id'],
            account_payment_xid=account_payment,
            status=OvoTransactionStatus.POST_DATA_SUCCESS,
            amount=transaction_data['bill_total'],
            is_checkout_experience=is_checkout_experience,
        )
        ovo_repayment_transaction = OvoRepaymentTransaction.objects.create(**input_params)
        store_transaction_data_history(input_params, ovo_repayment_transaction)
        mobile_feature_setting = MobileFeatureSetting.objects.filter(
            feature_name=OvoMobileFeatureName.OVO_REPAYMENT_COUNTDOWN
        ).last()
        duration = None
        if mobile_feature_setting:
            duration = mobile_feature_setting.parameters.get("countdown")
        data = {'transaction_id': ovo_repayment_transaction.transaction_id, 'duration': duration}
        return data, ''
    return {}, message


def store_transaction_data_history(
    input_params, ovo_repayment_transaction, ovo_repayment_transaction_old=None
):
    bulk_create_data = []
    for key, value in list(input_params.items()):
        data = OvoRepaymentTransactionHistory(
            ovo_repayment_transaction=ovo_repayment_transaction,
            field_name=key,
            value_old=""
            if ovo_repayment_transaction_old is None
            else ovo_repayment_transaction_old[key],
            value_new=value,
        )

        bulk_create_data.append(data)

    OvoRepaymentTransactionHistory.objects.bulk_create(bulk_create_data, batch_size=100)


def construct_push_to_pay_data(transaction_id, phone_number):
    ovo_repayment_transaction = OvoRepaymentTransaction.objects.get_or_none(
        transaction_id=transaction_id
    )

    if not ovo_repayment_transaction:
        return False, 'Transaction ID not found.'

    ovo_repayment_transaction.update_safely(
        phone_number=mask_phone_number_preserve_last_four_digits(str(phone_number))
    )
    faspay_user_id = settings.FASPAY_USER_ID
    faspay_password = settings.FASPAY_PASSWORD
    signature_keystring = '{}{}{}'.format(faspay_user_id, faspay_password, transaction_id)
    julo_signature = generate_sha1_md5(signature_keystring)

    return True, {'trx_id': transaction_id, 'ovo_number': phone_number, 'signature': julo_signature}


def push_to_pay(transaction_id, phone_number, flow_id=None):
    ovo_repayment_transaction = OvoRepaymentTransaction.objects.get_or_none(
        transaction_id=transaction_id
    )

    if not ovo_repayment_transaction:
        return False, 'Transaction ID not found.'

    payback_transaction = PaybackTransaction.objects.filter(transaction_id=transaction_id).last()
    if payback_transaction:
        return False, 'Payback transaction_id is exists.'

    payback_data = construct_payback_data(
        ovo_repayment_transaction.amount,
        ovo_repayment_transaction.account_payment_xid.account_payment_xid,
        transaction_id,
    )

    if not payback_data:
        return False, 'Account payment not found.'

    if flow_id:
        store_experiment_data.delay(
            ovo_repayment_transaction.account_payment_xid.account.customer_id, flow_id
        )

    status, transaction_data = construct_push_to_pay_data(transaction_id, phone_number)
    if not status:
        return False, transaction_data

    ovo_client = get_ovo_client()
    _, error = ovo_client.push_to_pay(transaction_data)

    if error:
        if error == 'ReadTimeout':
            return True, ''
        return False, error

    with transaction.atomic():
        ovo_repayment_transaction = OvoRepaymentTransaction.objects.select_for_update().get(
            transaction_id=transaction_id
        )

        if ovo_repayment_transaction.status == OvoTransactionStatus.PAYMENT_FAILED:
            current_repayment_transaction = model_to_dict(ovo_repayment_transaction)
            input_params = dict(status=OvoTransactionStatus.PAYMENT_FAILED)
            ovo_repayment_transaction.update_safely(**input_params)
            store_transaction_data_history(
                input_params, ovo_repayment_transaction, current_repayment_transaction
            )
        elif ovo_repayment_transaction.status != OvoTransactionStatus.SUCCESS:
            current_repayment_transaction = model_to_dict(ovo_repayment_transaction)
            input_params = dict(status=OvoTransactionStatus.PUSH_TO_PAY_SUCCESS)
            ovo_repayment_transaction.update_safely(**input_params)
            store_transaction_data_history(
                input_params, ovo_repayment_transaction, current_repayment_transaction
            )

    return True, ''


def notification_callback(status, signature, transaction_id, bill_no, bill_total):
    faspay_user_id = settings.FASPAY_USER_ID
    faspay_password = settings.FASPAY_PASSWORD
    ovo_repayment_transaction = OvoRepaymentTransaction.objects.get_or_none(
        transaction_id=transaction_id
    )

    if not ovo_repayment_transaction:
        return False, 'Transaction ID not found.'

    signature_keystring = '{}{}{}{}'.format(
        faspay_user_id,
        faspay_password,
        ovo_repayment_transaction.account_payment_xid.account_payment_xid,
        status,
    )
    transaction_signature = generate_sha1_md5(signature_keystring)

    if signature != transaction_signature:
        return False, 'Invalid signature.'

    logger.info(
        {
            'action': 'juloserver.ovo.services.services.notification_callback',
            'data': {
                'status': status,
                'signature': signature,
                'transaction_id': transaction_id,
                'bill_no': bill_no,
                'bill_total': bill_total,
                'ovo_repayment_id': ovo_repayment_transaction.id,
            },
        }
    )
    return True, 'success'


def get_ovo_payment_method(account, bank_code):
    customer = account.customer
    payment_method_code = OvoConst.PAYMENT_METHOD_CODE
    payment_method = PaymentMethod.objects.filter(
        customer=customer,
        payment_method_name=OvoConst.PAYMENT_METHOD_NAME,
        payment_method_code=payment_method_code,
        is_shown=True,
    ).last()

    if not payment_method:
        payment_method = PaymentMethod.objects.create(
            customer=customer,
            payment_method_name='OVO',
            payment_method_code=payment_method_code,
            is_shown=True,
            virtual_account="%s%s" % (payment_method_code, customer.phone),
            bank_code=bank_code,
        )

    return payment_method


def construct_payback_data(amount, bill_no, transaction_id):
    account_payment = AccountPayment.objects.get_or_none(account_payment_xid=bill_no)
    account = account_payment.account

    if not account_payment:
        return False

    transaction_date = timezone.localtime(timezone.now()).date()

    PaybackTransaction.objects.create(
        is_processed=False,
        customer=account_payment.account.customer,
        payback_service='OVO',
        status_desc='OVO',
        transaction_id=transaction_id,
        transaction_date=transaction_date,
        amount=amount,
        account=account_payment.account,
        payment_method=get_ovo_payment_method(account, None),
    )

    return True


def update_ovo_transaction_after_inquiry(ovo_repayment_transaction, input_params):
    current_repayment_transaction = model_to_dict(ovo_repayment_transaction)
    with transaction.atomic():
        ovo_repayment_transaction = OvoRepaymentTransaction.objects.select_for_update().get(
            pk=ovo_repayment_transaction.id
        )
        ovo_repayment_transaction.update_safely(**input_params)
        store_transaction_data_history(
            input_params, ovo_repayment_transaction, current_repayment_transaction
        )
