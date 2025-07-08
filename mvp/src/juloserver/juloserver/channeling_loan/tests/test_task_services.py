import mock

from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.channeling_loan.services.task_services import (
    construct_channeling_url_reader,
    get_ar_switching_lender_list,
    send_consolidated_error_msg,
)


class TestTaskServices(TestCase):
    @classmethod
    def setUpTestData(cls):
        pass

    @mock.patch('pandas.read_csv')
    @mock.patch('pandas.read_excel')
    def test_construct_channeling_url_reader(self, mock_read_csv, mock_read_excel):
        mock_read_csv.return_value = "return value"
        mock_read_excel.return_value = "return value"

        self.assertIsNone(construct_channeling_url_reader('http://a.pdf'))
        self.assertIsNotNone(
            construct_channeling_url_reader('https://docs.google.com/spreadsheets')
        )
        self.assertIsNotNone(
            construct_channeling_url_reader('https://drive.google.com/spreadsheets')
        )
        self.assertIsNotNone(construct_channeling_url_reader('http://a.xls'))
        self.assertIsNotNone(construct_channeling_url_reader('http://a.csv'))

    def test_get_ar_switching_lender_list(self):
        self.assertIsNotNone(get_ar_switching_lender_list())

    @mock.patch('juloserver.channeling_loan.services.task_services.send_notification_to_slack')
    def test_send_consolidated_error_msg(self, mock_slack):
        batch = "AR Switch by richard.andrew batch:202504021636"

        send_consolidated_error_msg(batch, 10, 2)
        mock_slack.assert_called_once()
