from builtins import str
from datetime import datetime
from django.conf import settings
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    FilterExpression,
    Filter,
    RunReportRequest,
    OrderBy,
    BatchRunReportsRequest,
)

from juloserver.google_analytics.models import GaBatchDownloadTask
from juloserver.google_analytics.constants import GaDownloadBatchStatus
from juloserver.julo.utils import post_anaserver

from juloserver.google_analytics.clients import GoogleAnalyticsClient

from juloserver.google_analytics.utils import chunks_dictionary


def process_raw_response_report_ga_data(response, ga_batch_download_task_id):
    ga_data = {}
    for report in response.reports:
        for row in report.rows:
            if not row.dimension_values[2].value.isnumeric():
                continue
            customer_id = int(row.dimension_values[2].value)
            key = "{}_{}".format(customer_id, row.dimension_values[1].value)
            event_date = datetime.strptime(row.dimension_values[0].value, '%Y%m%d%H')
            if key in ga_data:
                existing_event_date = datetime.strptime(ga_data[key]['event_date'], '%Y%m%d%H')
                if existing_event_date > event_date:
                    continue
                del ga_data[key]
            ga_data[key] = dict(
                event_date=row.dimension_values[0].value,
                event_name=row.dimension_values[1].value,
                ga_batch_download_task_id=ga_batch_download_task_id,
                customer_id=customer_id,
                app_version=row.dimension_values[3].value,
            )

    return ga_data


def download_google_analytics_data(ga_download_batch_task=None):
    if not ga_download_batch_task:
        ga_download_batch_task = GaBatchDownloadTask.objects.create()
        today = timezone.localtime(timezone.now()).date()
        yesterday = today - relativedelta(days=1)
        start_date = yesterday
    else:
        start_date = timezone.localtime(ga_download_batch_task.cdate).date()
    end_date = start_date
    try:
        batch_request = construct_batch_request(start_date, end_date)
        google_analytics_client = GoogleAnalyticsClient()
        response = google_analytics_client.batch_run_reports(batch_request)
        total_data = sum([len(report.rows) for report in response.reports])
        ga_download_batch_task.update_safely(
            status=GaDownloadBatchStatus.RETRIEVED, data_count=total_data
        )
        ga_data = process_raw_response_report_ga_data(response, ga_download_batch_task.id)
        ga_download_batch_task.update_safely(status=GaDownloadBatchStatus.PARSED)
        chunked_ga_data = list(chunks_dictionary(ga_data, 100))
        for chunk in chunked_ga_data:
            store_ga_data_to_ana(chunk)
        ga_download_batch_task.update_safely(status=GaDownloadBatchStatus.STORED)
    except Exception as e:
        ga_download_batch_task.update_safely(
            error_message=str(e), status=GaDownloadBatchStatus.FAILED
        )
        raise


def store_ga_data_to_ana(ga_data):
    url = '/api/amp/v1/google-analytics'
    response = post_anaserver(url, json=ga_data)

    return response


def construct_batch_request(start_date, end_date):
    start_date_string = datetime.strftime(start_date, '%Y-%m-%d')
    end_date_string = datetime.strftime(end_date, '%Y-%m-%d')
    property_id = 'properties/{}'.format(settings.GOOGLE_ANALYTICS_PROPERTY_ID)
    dimensions = ['dateHour', 'eventName', 'customUser:user_id_ga', 'appVersion']

    dimensions_ga4 = []
    for dimension in dimensions:
        dimensions_ga4.append(Dimension(name=dimension))
    metrics_ga4 = [Metric(name='eventCount')]

    event_names = ['first_open', 'app_remove', 'session_start']
    request_data = []
    for event_name in event_names:
        request = RunReportRequest(
            property=property_id,
            dimensions=dimensions_ga4,
            metrics=metrics_ga4,
            date_ranges=[DateRange(start_date=start_date_string, end_date=end_date_string)],
            dimension_filter=FilterExpression(
                filter=Filter(
                    field_name='eventName', string_filter=Filter.StringFilter(value=event_name)
                )
            ),
            order_bys=[
                OrderBy(
                    dimension=OrderBy.DimensionOrderBy(
                        dimension_name='dateHour',
                        order_type=OrderBy.DimensionOrderBy.OrderType.NUMERIC,
                    )
                )
            ],
        )
        request_data.append(request)

    batch_request = BatchRunReportsRequest(property=property_id, requests=request_data)

    return batch_request
