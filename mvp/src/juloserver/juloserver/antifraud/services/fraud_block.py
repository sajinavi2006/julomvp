from typing import List

from juloserver.account.models import Account
from juloserver.antifraud.models.fraud_block import FraudBlock


def is_fraud_blocked(
    account: Account,
    sources: List[FraudBlock.Source],
) -> bool:

    if not account:
        return False

    if not sources:
        return False

    return FraudBlock.objects.filter(
        customer_id=account.customer_id,
        source__in=[source.value for source in sources],
        is_active=True,
    ).exists()


def deactivate_fraud_block(
    account: Account,
    sources: List[FraudBlock.Source],
) -> None:
    if not account:
        return

    if not sources:
        return

    FraudBlock.objects.filter(
        customer_id=account.customer_id,
        source__in=[source.value for source in sources],
        is_active=True,
    ).update(is_active=False)

    return
