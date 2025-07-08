from celery import task
from .services import check_data_integrity
from .services import check_data_integrity_hourly


@task(name='check_data_integrity_async')
def check_data_integrity_async():
    check_data_integrity()


@task(name='check_data_integrity_hourly_async')
def check_data_integrity_hourly_async():
    check_data_integrity_hourly()
