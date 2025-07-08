from celery import task
from juloserver.antifraud.models.fraud_block import FraudBlock


@task(queue='fraud')
def deactivate_fraud_block(
    customer_id: int,
) -> None:

    if not customer_id:
        return

    FraudBlock.objects.filter(
        customer_id=customer_id,
        is_active=True,
    ).update(is_active=False)

    return
