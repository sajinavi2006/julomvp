from juloserver.julo.models import Customer
from celery import task
from juloserver.google_analytics.services import (
    download_google_analytics_data,
)
from juloserver.google_analytics.clients import GoogleAnalyticsClient
from juloserver.google_analytics.models import GaBatchDownloadTask
from juloserver.google_analytics.constants import GaDownloadBatchStatus


@task(queue='application_normal')
def trigger_google_analytics_data_download():
    download_google_analytics_data()


@task(queue='application_normal')
def trigger_retry_failed_download_google_analytics_data():
    ga_download_batch_tasks = GaBatchDownloadTask.objects.filter(
        status=GaDownloadBatchStatus.FAILED
    )
    for ga_download_batch_task in ga_download_batch_tasks:
        download_google_analytics_data(ga_download_batch_task)


@task(name='send_event_to_ga_task')
def send_event_to_ga_task(customer, event):
    google_analytics_client = GoogleAnalyticsClient()
    google_analytics_client.send_event_to_ga(customer, event)


@task(queue='application_normal')
def send_event_to_ga_task_async(**kwargs):
    customer_id = kwargs.get('customer_id')
    customer = Customer.objects.get_or_none(pk=customer_id)
    event = kwargs.get('event')
    extra_params = kwargs.get('extra_params', {})

    if kwargs.get('version', 'v1') == 'v2':
        from juloserver.application_flow.services import get_extra_params_dynamic_events
        application = customer.get_active_or_last_application
        extra_params = get_extra_params_dynamic_events(application)

    if customer:
        google_analytics_client = GoogleAnalyticsClient()
        google_analytics_client.send_event_to_ga(customer, event, extra_params)
