from django.test import TestCase
from unittest.mock import patch, Mock
from juloserver.customer_module.tasks.notification import (
    send_email_with_html_task,
    send_customer_data_change_by_agent_notification_task,
)
from juloserver.customer_module.constants import AgentDataChange


class TestSendEmailWithHtmlTask(TestCase):
    @patch('juloserver.customer_module.tasks.notification.send_email_with_html')
    def test_happy_path(
        self,
        mock_send_email_with_html,
    ):
        resp = send_email_with_html_task(
            "subject",
            "html_content",
            "recipient_email",
            "sender_email",
            "template_code",
        )
        mock_send_email_with_html.assert_called_once_with(
            subject="subject",
            html_content="html_content",
            recipient_email="recipient_email",
            sender_email="sender_email",
            template_code="template_code",
            attachments=None,
            fullname=None,
        )

    @patch('juloserver.customer_module.tasks.notification.send_email_with_html')
    def test_happy_path_with_attachment(
        self,
        mock_send_email_with_html,
    ):
        resp = send_email_with_html_task(
            "subject",
            "html_content",
            "recipient_email",
            "sender_email",
            "template_code",
            attachments=[],
        )
        mock_send_email_with_html.assert_called_once_with(
            subject="subject",
            html_content="html_content",
            recipient_email="recipient_email",
            sender_email="sender_email",
            template_code="template_code",
            attachments=[],
            fullname=None,
        )

    @patch('juloserver.customer_module.tasks.notification.send_email_with_html')
    def test_happy_path_with_fullname(
        self,
        mock_send_email_with_html,
    ):
        resp = send_email_with_html_task(
            "subject",
            "html_content",
            "recipient_email",
            "sender_email",
            "template_code",
            fullname="fullname",
        )
        mock_send_email_with_html.assert_called_once_with(
            subject="subject",
            html_content="html_content",
            recipient_email="recipient_email",
            sender_email="sender_email",
            template_code="template_code",
            attachments=None,
            fullname="fullname",
        )


class TestSendCustomerDataChangeByAgentNotificationTask(TestCase):
    @patch('juloserver.customer_module.tasks.notification.FeatureSetting.objects.filter')
    @patch('juloserver.customer_module.tasks.notification.Customer.objects.get')
    @patch(
        'juloserver.customer_module.tasks.notification.send_customer_field_change_phone_number_notification'
    )
    def test_happy_path_phone_number(
        self,
        mock_send_customer_field_change_phone_number_notification,
        mock_get_customer,
        mock_mobile_feature_setting,
    ):
        mock_get_customer.return_value = Mock()
        mock_mobile_feature_setting.return_value = Mock()

        send_customer_data_change_by_agent_notification_task(
            customer_id=0,
            field_changed=AgentDataChange.Field.Phone,
            previous_value=0,
            new_value=1,
        )
        mock_send_customer_field_change_phone_number_notification.assert_called_once()

    @patch('juloserver.customer_module.tasks.notification.FeatureSetting.objects.filter')
    @patch('juloserver.customer_module.tasks.notification.Customer.objects.get')
    @patch(
        'juloserver.customer_module.tasks.notification.send_customer_field_change_email_notification'
    )
    def test_happy_path_email(
        self,
        mock_send_customer_field_change_email_notification,
        mock_get_customer,
        mock_mobile_feature_setting,
    ):
        mock_get_customer.return_value = Mock()
        mock_mobile_feature_setting.return_value = Mock()

        send_customer_data_change_by_agent_notification_task(
            customer_id=0,
            field_changed=AgentDataChange.Field.Email,
            previous_value=0,
            new_value=1,
        )
        mock_send_customer_field_change_email_notification.assert_called_once()

    @patch('juloserver.customer_module.tasks.notification.FeatureSetting.objects.filter')
    @patch('juloserver.customer_module.tasks.notification.Customer.objects.get')
    @patch(
        'juloserver.customer_module.tasks.notification.send_customer_field_change_bank_account_number_notification'
    )
    def test_happy_path_bank_account_number(
        self,
        mock_send_customer_field_change_bank_account_number_notification,
        mock_get_customer,
        mock_mobile_feature_setting,
    ):
        mock_get_customer.return_value = Mock()
        mock_mobile_feature_setting.return_value = Mock()

        send_customer_data_change_by_agent_notification_task(
            customer_id=0,
            field_changed=AgentDataChange.Field.BankAccountNumber,
            previous_value=0,
            new_value=1,
        )
        mock_send_customer_field_change_bank_account_number_notification.assert_called_once()

    @patch('juloserver.customer_module.tasks.notification.FeatureSetting.objects.filter')
    @patch(
        'juloserver.customer_module.tasks.notification.send_customer_field_change_phone_number_notification'
    )
    def test_mobile_feature_setting_inactive(
        self,
        mock_send_customer_field_change_phone_number_notification,
        mock_mobile_feature_setting,
    ):
        mock_empty = Mock()
        mock_empty.last.return_value = None
        mock_mobile_feature_setting.return_value = mock_empty

        send_customer_data_change_by_agent_notification_task(
            customer_id=0,
            field_changed=AgentDataChange.Field.Phone,
            previous_value=0,
            new_value=1,
        )
        assert not mock_send_customer_field_change_phone_number_notification.called
