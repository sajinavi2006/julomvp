from celery import task
from juloserver.payment_point.models import PdamOperator


@task(queue="loan_low")
def update_pdam_operators(operator_data):
    bulk_operator_data = []
    for operator in operator_data:
        if not PdamOperator.objects.filter(code=operator['code']).exists():
            bulk_operator_data.append(
                PdamOperator(
                    code=operator['code'],
                    description=operator['description'],
                    enabled=operator['enabled'],
                )
            )
    PdamOperator.objects.bulk_create(bulk_operator_data, batch_size=100)
