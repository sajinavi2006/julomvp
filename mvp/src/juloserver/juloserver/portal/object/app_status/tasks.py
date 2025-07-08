from celery import task

from .services import update_payment_bucket_1to5_in_cache

@task(name='interval_update_payment_bucket_count')
def interval_update_payment_bucket_count():
    """
    Deprecated
    """
    update_payment_bucket_1to5_in_cache()
