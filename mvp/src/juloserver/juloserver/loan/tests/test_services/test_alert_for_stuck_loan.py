from mock import patch, MagicMock

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (
    LoanFactory,
    StatusLookupFactory,
    FeatureSettingFactory,
)

from django.test.testcases import TestCase
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.loan.services.alert_for_stuck_loan import (
    count_number_of_loans_by_status,
    construct_slack_message_alert_for_stuck_loan,
    send_alert_for_stuck_loan_through_slack,
)


class TestAlertForStuckLoan(TestCase):
    def setUp(self):
        # Create sample loans with different statuses
        self.loan_status_210 = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE,
        )
        self.loan_status_218 = StatusLookupFactory(
            status_code=LoanStatusCodes.FUND_DISBURSAL_FAILED,
        )
        self.sample_count_loan_status = {
            LoanStatusCodes.INACTIVE: 22,
            LoanStatusCodes.FUND_DISBURSAL_FAILED: 44,
        }

    @patch('juloserver.loan.services.alert_for_stuck_loan.connection')
    def test_count_number_of_loans_by_status(self, mock_db_connection):
        # count with an empty list of statuses
        self.assertEqual(count_number_of_loans_by_status([], []), {})

        # test with list not empty
        expected_result = [(1, 'data1'), (2, 'data2')]
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = expected_result
        # Mock the __enter__ method of the cursor to return the mock cursor
        mock_db_connection.cursor.return_value.__enter__.return_value = mock_cursor

        result = count_number_of_loans_by_status(
            [LoanStatusCodes.INACTIVE, LoanStatusCodes.FUND_DISBURSAL_FAILED],
            [ProductLineCodes.J1, ProductLineCodes.TURBO],
        )

        assert result == dict(expected_result)

    def test_construct_slack_message_alert_for_stuck_loan(self):
        # Sample data for testing

        list_user_id_to_tag_when_exceed_threshold = ['U1', 'U2']

        message = construct_slack_message_alert_for_stuck_loan(
            count_loan_status={},
            threshold_to_tag_member=100,
            list_user_id_to_tag_when_exceed_threshold=list_user_id_to_tag_when_exceed_threshold,
        )
        # no loan stuck
        self.assertIn("- No loan stuck", message)
        # not exceed threshold
        self.assertNotIn("Please help to check", message)

        message = construct_slack_message_alert_for_stuck_loan(
            count_loan_status=self.sample_count_loan_status,
            threshold_to_tag_member=100,
            list_user_id_to_tag_when_exceed_threshold=list_user_id_to_tag_when_exceed_threshold,
        )
        for loan_status, count in self.sample_count_loan_status.items():
            self.assertIn("- Status `{}` has `{}` loans\n".format(loan_status, count), message)
        # not exceed threshold
        self.assertNotIn("Please help to check", message)

        message = construct_slack_message_alert_for_stuck_loan(
            count_loan_status=self.sample_count_loan_status,
            threshold_to_tag_member=10,
            list_user_id_to_tag_when_exceed_threshold=list_user_id_to_tag_when_exceed_threshold,
        )
        # exceed threshold
        self.assertIn("Please help to check", message)

    @patch('juloserver.loan.services.alert_for_stuck_loan.send_slack_bot_message')
    @patch(
        'juloserver.loan.services.alert_for_stuck_loan.'
        'construct_slack_message_alert_for_stuck_loan'
    )
    @patch('juloserver.loan.services.alert_for_stuck_loan.count_number_of_loans_by_status')
    def test_send_alert_for_stuck_loan_through_slack(
        self, mock_count_loan, mock_construct_message, mock_send_slack_message
    ):
        mock_count_loan.return_value = self.sample_count_loan_status
        mock_construct_message.return_value = 'Mocked Slack Message'

        # test with no feature setting
        send_alert_for_stuck_loan_through_slack()
        mock_construct_message.asset_not_called()
        mock_send_slack_message.asset_not_called()

        feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.ALERT_FOR_STUCK_LOAN,
            is_active=False,
            parameters={
                "list_stuck_loan_status": [
                    LoanStatusCodes.INACTIVE,  # 210
                    LoanStatusCodes.FUND_DISBURSAL_FAILED,  # 218
                ],
                "slack_channel_name": "alerts_stuck_loan",
                "threshold_to_tag_member": 100,
                "list_user_id_to_tag_when_exceed_threshold": ['U1', 'U2'],
                "product_line_applied": [ProductLineCodes.J1, ProductLineCodes.TURBO],
            },
        )

        # test with inactive feature setting
        send_alert_for_stuck_loan_through_slack()
        mock_construct_message.asset_not_called()
        mock_send_slack_message.asset_not_called()

        feature_setting.is_active = True
        feature_setting.save()
        # test with active feature setting
        send_alert_for_stuck_loan_through_slack()
        mock_construct_message.assert_called_once_with(
            count_loan_status=self.sample_count_loan_status,
            threshold_to_tag_member=feature_setting.parameters['threshold_to_tag_member'],
            list_user_id_to_tag_when_exceed_threshold=feature_setting.parameters[
                'list_user_id_to_tag_when_exceed_threshold'
            ],
        )
        mock_send_slack_message.assert_called_once_with(
            channel=feature_setting.parameters['slack_channel_name'], message='Mocked Slack Message'
        )
