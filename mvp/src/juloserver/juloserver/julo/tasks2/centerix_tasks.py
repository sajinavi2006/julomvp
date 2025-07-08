import logging

from celery import task
from juloserver.julo.clients import get_julo_centerix_client


@task(name='upload_data_to_centerix_async')
def upload_data_to_centerix_async(payment_id, payment_method_id):
    centerix_client = get_julo_centerix_client()

    centerix_client.upload_centerix_payment_data(payment_id, payment_method_id)
