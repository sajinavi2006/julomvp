import mock
from django.test import TestCase
import json

from juloserver.google_analytics.services import download_google_analytics_data
from juloserver.google_analytics.models import GaBatchDownloadTask
from juloserver.google_analytics.constants import GaDownloadBatchStatus


class MockReportGoogleAnalytics(object):
    class Reports(object):
        rows = [1]

    reports = [Reports()]


class TestGoogleAnalytics(TestCase):
    @mock.patch('juloserver.google_analytics.clients.GoogleAnalyticsClient.batch_run_reports')
    @mock.patch('juloserver.google_analytics.services.construct_batch_request')
    @mock.patch('juloserver.google_analytics.services.process_raw_response_report_ga_data')
    @mock.patch('juloserver.google_analytics.services.store_ga_data_to_ana')
    def test_download_data_google_analytics(
        self,
        mock_store_ga_data_to_ana,
        mock_process_raw_response_report_ga_data,
        mock_construct_batch_request,
        mock_batch_run_reports,
    ):
        response_data = {'error_message': None}
        json_response = json.dumps(response_data)
        mock_store_ga_data_to_ana.return_value.status_code = 201
        mock_store_ga_data_to_ana.return_value.content = json_response
        mock_batch_run_reports.return_value = MockReportGoogleAnalytics()
        mock_construct_batch_request.return_value = object
        mock_process_raw_response_report_ga_data.return_value = {
            '1_app_remove': {
                'event_date': '2020-01-01',
                'event_name': 'app_remove',
                'ga_batch_download_task_id': 1,
                'customer_id': 1,
            }
        }
        download_google_analytics_data()
        self.assertTrue(
            GaBatchDownloadTask.objects.filter(status=GaDownloadBatchStatus.STORED).exists()
        )
