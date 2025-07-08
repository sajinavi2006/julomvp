import json
from celery import task
from typing import Optional, Dict
from requests import Response
from juloserver.julo.models import (
    PaybackTransaction,
    EmailHistory,
)
from juloserver.payback.models import PaybackAPILog
from juloserver.julo.clients import get_julo_email_client
from juloserver.payback.services.payback import process_success_email_content
from juloserver.pii_vault.constants import PiiSource
import logging
from juloserver.autodebet.utils import (
    detokenize_sync_primary_object_model,
    convert_bytes_to_dict_or_string,
)
from juloserver.payback.constants import EMAIL_EXCLUDED_PAYBACK_SERVICES
from juloserver.account_payment.services.collection_related import get_cashback_claim_experiment

logger = logging.getLogger(__name__)


@task(queue='repayment_normal', bind=True)
def send_email_payment_success_task(self, payback_id):
    payback = (
        PaybackTransaction.objects.select_related("payment_method", "customer")
        .only(
            "id",
            "transaction_id",
            "payback_service",
            "customer__customer_xid",
            "customer__id",
            "customer__email",
            "customer__fullname",
            "payment_method__payment_method_name",
        )
        .get(pk=payback_id)
    )
    # exclude several paybacks from non j1/jturbo product
    if (
        payback
        and payback.payback_service
        and payback.payback_service.lower() not in EMAIL_EXCLUDED_PAYBACK_SERVICES
        and "reversal" not in payback.payback_service.lower()
    ):
        customer = payback.customer
        detokenized_customer = detokenize_sync_primary_object_model(
            PiiSource.CUSTOMER,
            customer,
            customer.customer_xid,
            ['fullname', 'email'],
        )
        julo_email_client = get_julo_email_client()
        _, is_cashback_claim_experiment = get_cashback_claim_experiment(account=payback.account)

        email_subject, email_template, context = process_success_email_content(
            payback, detokenized_customer, is_cashback_claim_experiment
        )
        (_, headers, subject, msg, _,) = julo_email_client.email_payment_success_notification(
            context,
            detokenized_customer.email,
            template_code=email_template,
            subject=email_subject,
        )

        email_history = EmailHistory.objects.create(
            customer=customer,
            sg_message_id=headers["X-Message-Id"],
            to_email=detokenized_customer.email,
            subject=email_subject,
            message_content=msg,
            template_code=email_template,
        )

        logger.info(
            {
                "action": "send_email_payment_success_task",
                "customer_id": payback_id,
                "email_history_id": email_history.id,
                "template_code": email_template,
                "is_cashback_claim_experiment": is_cashback_claim_experiment,
            }
        )


@task(queue='repayment_low')
def store_payback_callback_log(
    request_data: bytes,
    response_data: bytes,
    http_status_code: int,
    url: str,
    vendor: str,
    customer_id: Optional[int] = None,
    loan_id: Optional[int] = None,
    account_payment_id: Optional[int] = None,
    payback_transaction_id: Optional[int] = None,
    error_message: Optional[str] = None,
    header: Optional[str] = None,
) -> None:
    if 'access-token' in url.lower():
        return
    PaybackAPILog.objects.create(
        vendor=vendor,
        http_status_code=http_status_code,
        request_type=url.upper(),
        request=convert_bytes_to_dict_or_string(request_data),
        response=convert_bytes_to_dict_or_string(response_data),
        customer_id=customer_id,
        loan_id=loan_id,
        account_payment_id=account_payment_id,
        payback_transaction_id=payback_transaction_id,
        error_message=error_message,
        header=header,
    )


@task(queue='repayment_low')
def store_payback_api_log(
    url: str,
    request_params: Dict,
    vendor: str,
    response: Optional[Response],
    return_response: Optional[Dict],
    customer_id: Optional[int] = None,
    loan_id: Optional[int] = None,
    account_payment_id: Optional[int] = None,
    payback_transaction_id: Optional[int] = None,
    error_message: Optional[str] = None,
    header: Optional[Dict] = None,
) -> None:
    if 'access-token' in url.lower():
        return
    try:
        data_header = request_params.pop('headers')
    except (KeyError, AttributeError):
        data_header = None
    if not header:
        header = data_header
    try:
        header.pop('Authorization')
    except (KeyError, AttributeError):
        pass
    data = request_params.get('data', request_params.get('json', {}))
    if isinstance(data, str):
        request_params['data'] = json.loads(data)
        if 'json' in request_params:
            request_params.pop('json')

    if not response:
        response_status = 400
    else:
        response_status = response.status_code

    request = json.dumps(request_params)

    PaybackAPILog.objects.create(
        vendor=vendor,
        http_status_code=response_status,
        request_type=url.upper(),
        request=request,
        response=json.dumps(return_response) if return_response else None,
        customer_id=customer_id,
        loan_id=loan_id,
        account_payment_id=account_payment_id,
        payback_transaction_id=payback_transaction_id,
        error_message=error_message,
        header=json.dumps(header),
    )
