from __future__ import division

import logging

from celery import task

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Loan
from juloserver.julo.services2.fraud_check import check_suspicious_ip
from juloserver.loan.services.loan_related import capture_suspicious_transaction_risk_check
from juloserver.antifraud.models.fraud_block import (
    FraudBlock,
)

from juloserver.antifraud.constant.binary_checks import StatusEnum as ABCStatus
from juloserver.account.models import Account

from juloserver.fraud_security.models import (
    FraudTelcoMaidTemporaryBlock,
)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@task(queue='fraud')
def suspicious_ip_loan_fraud_check(
    loan_id: int, ip_address: str, is_suspicious_ip=None, user_id=None
):
    loan = Loan.objects.filter(id=loan_id).last()
    if not is_suspicious_ip:
        if not ip_address:
            logger.warning('can not find ip address|loan={}'.format(loan.id))
            return

        logger.info(
            {'action': 'get_client_ip_address', 'ip_address': ip_address, 'user_id': user_id}
        )

        try:
            is_suspicious_ip = check_suspicious_ip(ip_address)
        except Exception:
            sentry_client.captureException()
            return

    loan_risk_check = capture_suspicious_transaction_risk_check(
        loan, 'is_vpn_detected', is_suspicious_ip
    )

    return loan_risk_check


@task(queue='fraud')
def event_loan_fraud_block(
    binary_check_status: ABCStatus,
    customer_id: int,
) -> None:

    if not customer_id:
        return

    account = Account.objects.filter(customer_id=customer_id).first()
    if not account:
        return

    if binary_check_status == ABCStatus.TELCO_MAID_LOCATION:
        FraudTelcoMaidTemporaryBlock.objects.create(account=account)
    elif binary_check_status == ABCStatus.FRAUD_REPORTED_LOAN:
        FraudBlock.objects.get_or_create(
            source=FraudBlock.Source.LOAN_FRAUD_BLOCK.value,
            customer_id=customer_id,
        )

    return
