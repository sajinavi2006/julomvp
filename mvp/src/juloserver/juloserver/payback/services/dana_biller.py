import uuid
from typing import (
    Dict,
    Optional,
)
import json
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from juloserver.account_payment.services.payment_flow import process_repayment_trx
from juloserver.integapiv1.utils import (
    generate_signature_asymmetric,
    verify_asymmetric_signature,
)
from juloserver.julo.models import PaybackTransaction, PaymentMethod, FeatureSetting
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.services import get_oldest_payment_due
from juloserver.julo.services2.payment_method import get_application_primary_phone, get_active_loan
from juloserver.julo.utils import format_mobile_phone
from juloserver.moengage.tasks import update_moengage_for_payment_received_task
from juloserver.payback.constants import FeatureSettingNameConst
from juloserver.payback.models import DanaBillerInquiry, DanaBillerOrder, DanaBillerStatus
from juloserver.refinancing.services import j1_refinancing_activation
from juloserver.waiver.services.waiver_related import process_j1_waiver_before_payment
from juloserver.payback.tasks.dana_biller_tasks import send_slack_alert_dana_biller

from juloserver.payback.models import DanaBillerStatus

logger = logging.getLogger(__name__)


def generate_signature(data: Dict, private_key: str) -> str:
    minify_json = json.dumps(data, separators=(',', ':'))
    signature = generate_signature_asymmetric(private_key, minify_json)

    return signature


def verify_signature(data: Dict, public_key: str) -> Optional[bool]:
    logger.info(
        {
            "action": "juloserver.payback.services.dana_biller.verify_signature",
            "data": data,
        }
    )
    copy_data = data.copy()
    try:
        signature = copy_data['signature']
        del copy_data['signature']
    except KeyError:
        logger.warning(
            {
                "action": "juloserver.payback.services.dana_biller.verify_signature",
                "data": data,
                "error": "signature not exists"
            }
        )
        return
    minify_json = json.dumps(copy_data.get('request'), separators=(',', ':'))
    return verify_asymmetric_signature(public_key, signature, minify_json)


def get_dana_biller_status_by_code(code: str) -> Optional[DanaBillerStatus]:
    return DanaBillerStatus.objects.get_or_none(code=code)


def create_order(data):
    public_key = settings.DANA_BILLER_PUBLIC_KEY
    is_valid = verify_signature(data, public_key)
    if not is_valid:
        message = 'unauthorized'
        send_slack_alert_dana_biller.delay(
            data['request']['body']['requestId'], message
        )
        return message, False

    body = data['request']['body']
    request_id = body['requestId']
    extend_info = json.loads(body['extendInfo'])
    inquiry_id = extend_info.get('inquiryId', None)
    order_id = str(uuid.uuid4())
    timestamp = timezone.localtime(timezone.now())
    dana_biller_order = DanaBillerOrder.objects.filter(
        request_id=request_id
    ).last()
    dana_biller_inquiry = DanaBillerInquiry.objects.filter(
        inquiry_id=inquiry_id,
        dana_biller_status__is_success=True
    ).last()

    if not dana_biller_inquiry:
        return construct_create_order_for_failed_response(
            data,
            request_id, body['danaSellingPrice']['value'],
            body['destinationInfo']['primaryParam'],
            data['request']['head']['reqMsgId'],
            'Inquiry id not found',
            '30',
            order_id
        ), False

    account = dana_biller_inquiry.account
    account_payment = dana_biller_inquiry.account_payment
    amount = dana_biller_inquiry.amount
    payment_method = get_dana_biller_payment_method(account)

    if dana_biller_order:
        if dana_biller_order.dana_biller_status.is_success:
            return construct_response_create_order(
                request_id,
                dana_biller_inquiry.amount,
                payment_method.virtual_account,
                data['request']['head']['reqMsgId'],
                dana_biller_order.order_id
            ), True
        return construct_create_order_for_failed_response(
            data,
            request_id,
            dana_biller_inquiry.amount,
            payment_method.virtual_account,
            data['request']['head']['reqMsgId'],
            'Order exists but transaction failed',
            '30',
            dana_biller_order.order_id,
            dana_biller_inquiry
        ), False

    with transaction.atomic():
        loan = get_active_loan(payment_method)
        if not loan:
            return construct_create_order_for_failed_response(
                data,
                request_id,
                dana_biller_inquiry.amount,
                payment_method.virtual_account,
                data['request']['head']['reqMsgId'],
                'No active loan found',
                '30',
                order_id,
                dana_biller_inquiry
            ), False

        payment = get_oldest_payment_due(loan)
        payback_transaction = PaybackTransaction.objects.create(
            is_processed=False,
            customer=account.customer,
            payback_service='DANA Biller',
            status_desc='DANA Biller',
            transaction_id=request_id,
            transaction_date=timestamp,
            amount=amount,
            account=account,
            payment_method=payment_method,
            virtual_account=payment_method.virtual_account,
            loan=loan,
            payment=payment
        )
        try:
            j1_refinancing_activation(
                payback_transaction, account_payment, payback_transaction.transaction_date)
            process_j1_waiver_before_payment(
                account_payment, amount, payback_transaction.transaction_date)
            account_trx = process_repayment_trx(
                payback_transaction, note='payment with dana biller amount {}'.format(amount)
            )
        except Exception as e:
            account_trx = None

        if account_trx:
            update_moengage_for_payment_received_task.delay(account_trx.id)
            dana_biller_status = DanaBillerStatus.objects.filter(
                is_success=True,
                code=10,
                message='Success'
            ).last()
            DanaBillerOrder.objects.create(
                primary_param=json.dumps(data),
                request_id=request_id,
                dana_biller_inquiry=dana_biller_inquiry,
                payback_transaction=payback_transaction,
                dana_biller_status=dana_biller_status,
                order_id=order_id
            )

            response = construct_response_create_order(
                request_id,
                amount,
                payment_method.virtual_account,
                data['request']['head']['reqMsgId'],
                order_id
            )
            logger.info({
                'action': 'juloserver.payback.services.dana_biller.create_order',
                'request': data,
                'response': response,
                'message': 'Success'
            })
            return response, True

        return construct_create_order_for_failed_response(
            data,
            request_id,
            dana_biller_inquiry.amount,
            payment_method.virtual_account,
            data['request']['head']['reqMsgId'],
            'Transaction failed',
            '30',
            order_id,
            dana_biller_inquiry
        ), False


def construct_response_create_order(request_id, amount, primary_param, req_msg_id, order_id):
    timestamp = timezone.localtime(timezone.now())
    formatted_timestamp = timestamp.isoformat().split('.')[0] + '+' \
        + timestamp.isoformat().split('+')[1]

    if amount:
        amount = str(amount) + "00"

    data = {
        "response": {
            "head": {
                "version": "2.0",
                "function": "dana.digital.goods.order.create",
                "respTime": formatted_timestamp,
                "reqMsgId": req_msg_id
            },
            "body": {
                "order": {
                    "requestId": request_id,
                    "orderId": order_id,
                    "createdTime": formatted_timestamp,
                    "modifiedTime": formatted_timestamp,
                    "destinationInfo": {
                        "primaryParam": str(primary_param)
                    },
                    "orderStatus": {
                        "code": "10",
                        "status": "SUCCESS",
                        "message": "Success"
                    },
                    "product": {
                        "productId": PaymentMethodCodes.DANA_BILLER,
                        "price": {
                            "value": 0 if not amount else amount,
                            "currency": "IDR"
                        },
                        "availability": True
                    }
                }
            }
        }
    }
    data['signature'] = generate_signature(data['response'], settings.DANA_BILLER_PRIVATE_KEY)
    return data


def construct_create_order_for_failed_response(data, request_id, value, primary_param, req_msg_id,
                                               logger_message, code, order_id,
                                               dana_biller_inquiry=None):
    construct_create_order = construct_response_create_order(
        request_id,
        value,
        primary_param,
        req_msg_id,
        order_id
    )
    dana_biller_status = DanaBillerStatus.objects.get_or_none(
        code=code,
        message='General Error'
    )
    dana_biller_order = DanaBillerOrder.objects.filter(
        request_id=request_id,
        dana_biller_inquiry=dana_biller_inquiry
    ).exists()

    if not dana_biller_order:
        DanaBillerOrder.objects.create(
            primary_param=json.dumps(data),
            request_id=request_id,
            dana_biller_inquiry=dana_biller_inquiry,
            dana_biller_status=dana_biller_status,
            order_id=order_id
        )

    response_body = construct_create_order['response']['body']['order']['orderStatus']
    response_body.update({'code': code, 'status': 'FAILED', 'message': dana_biller_status.message})
    logger.info({
        'action': 'juloserver.payback.services.dana_biller.create_order',
        'request': data,
        'response': response_body,
        'message': logger_message
    })

    # send slack notification for failed order
    if code == '30':
        send_slack_alert_dana_biller.delay(request_id, logger_message)

    return construct_create_order


def get_dana_biller_payment_method(account):
    customer = account.customer
    application = account.application_set.last()
    mobile_phone_1 = get_application_primary_phone(application)

    if mobile_phone_1:
        mobile_phone_1 = format_mobile_phone(mobile_phone_1)
        if application.is_merchant_flow():
            mobile_phone_1 = mobile_phone_1[0] + '1' + mobile_phone_1[2:]
    virtual_account = "".join([
        PaymentMethodCodes.DANA_BILLER,
        mobile_phone_1
    ])

    payment_method, _ = PaymentMethod.objects.get_or_create(
        payment_method_code=PaymentMethodCodes.DANA_BILLER,
        payment_method_name="DANA Biller",
        customer=customer,
        is_shown=False,
        is_primary=False,
        virtual_account=virtual_account,
    )

    return payment_method
