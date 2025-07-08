import json
from datetime import datetime
from unittest import mock

from django.test import TestCase

from juloserver.customer_module.tasks.customer_related_tasks import (
    cleanup_payday_change_request_from_redis,
    populate_customer_xid,
    send_customer_data_change_request_notification_email,
    send_customer_data_change_request_notification_pn,
    sync_customer_data_with_application,
)
from juloserver.customer_module.tests.factories import CustomerDataChangeRequestFactory
from juloserver.julo.models import Customer, CustomerFieldChange
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
)


@mock.patch(
    'juloserver.customer_module.services.customer_related.CustomerDataChangeRequestNotification',
)
class TestSendCustomerDataChangeRequestNotificationEmail(TestCase):
    def setUp(self):
        self.change_request = CustomerDataChangeRequestFactory()

    def test_send_email(self, mock_change_request_notification):
        mock_change_request_notification.return_value.send_email.return_value = True
        change_request_id, result = send_customer_data_change_request_notification_email(
            self.change_request.id
        )
        self.assertEqual(change_request_id, self.change_request.id)
        self.assertTrue(result)
        mock_change_request_notification.assert_called_once_with(self.change_request)
        mock_change_request_notification.return_value.send_email.assert_called_once_with()


@mock.patch(
    'juloserver.customer_module.services.customer_related.CustomerDataChangeRequestNotification',
)
class TestSendCustomerDataChangeRequestNotificationPn(TestCase):
    def setUp(self):
        self.change_request = CustomerDataChangeRequestFactory()

    def test_send_email(self, mock_change_request_notification):
        mock_change_request_notification.return_value.send_pn.return_value = True
        change_request_id, result = send_customer_data_change_request_notification_pn(
            self.change_request.id
        )
        self.assertEqual(change_request_id, self.change_request.id)
        self.assertTrue(result)
        mock_change_request_notification.assert_called_once_with(self.change_request)
        mock_change_request_notification.return_value.send_pn.assert_called_once_with()


class TestPopulateCustomerXid(TestCase):
    def test_generate(self):
        existing_xid = CustomerFactory(
            customer_xid=384748392938,
        )
        for _ in range(5):
            CustomerFactory(
                customer_xid=None,
            )

        populate_customer_xid()

        # check for customer without customer_xid
        empty_xid_exists = Customer.objects.filter(customer_xid=None).exists()
        self.assertFalse(empty_xid_exists)

        # ensure that existing customer will not be affected
        existing_xid_result = Customer.objects.filter(customer_xid=384748392938).first()
        self.assertIsNotNone(existing_xid_result)
        self.assertEqual(existing_xid.id, existing_xid_result.id)


class TestCleanupPaydayChangeRequestFromRedis(TestCase):
    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.get_redis_client')
    @mock.patch(
        'juloserver.customer_module.services.customer_related.delete_document_payday_customer_change_request_from_oss'
    )
    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.logger')
    def test_cleanup_payday_change_request_from_redis(
        self, mock_logger, mock_delete_image, mock_redis_client
    ):
        # Mock Redis client and keys
        mock_redis_client.return_value.get_keys.return_value = [
            'payday_change_request:1',
            'payday_change_request:2',
        ]

        # Mock Redis data
        mock_redis_client.return_value.get.side_effect = [
            json.dumps({"payday_change_proof_image_id": 11}),
            json.dumps({"payday_change_proof_image_id": 12}),
        ]

        # Call the cleanup function
        cleanup_payday_change_request_from_redis()

        # Assert that the delete function is called with the correct image IDs
        mock_delete_image.assert_has_calls([mock.call(11), mock.call(12)])

        # Assert that the Redis keys are deleted
        mock_redis_client.return_value.delete_key.assert_has_calls(
            [mock.call('payday_change_request:1'), mock.call('payday_change_request:2')]
        )

        # Assert that the logger.info is called with the correct message
        mock_logger.info.assert_called_once_with(
            "Payday Change Request Cleanup Complete:\n"
            "- Successfully processed: 2\n"
            "- Errors encountered: 0"
        )

    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.get_redis_client')
    def test_cleanup_payday_change_request_from_redis_no_requests(self, mock_redis_client):
        # Mock Redis client and keys
        mock_redis_client.return_value.get_keys.return_value = []

        # Call the cleanup function
        cleanup_payday_change_request_from_redis()

        # Assert that the delete function and delete_key function are not called
        mock_redis_client.delete_key.assert_not_called()

    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.get_redis_client')
    @mock.patch(
        'juloserver.customer_module.services.customer_related.delete_document_payday_customer_change_request_from_oss'
    )
    def test_cleanup_payday_change_request_from_redis_invalid_json(
        self, mock_delete_image, mock_redis_client
    ):
        # Mock Redis client and keys
        mock_redis_client.return_value.get_keys.return_value = ['payday_change_request:1']

        # Mock invalid JSON data
        mock_redis_client.return_value.get.return_value = "invalid_json_data"

        # Call the cleanup function
        cleanup_payday_change_request_from_redis()

        # Assert that the delete function and delete_key function are not called
        mock_delete_image.assert_not_called()
        mock_redis_client.delete_key.assert_not_called()

    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.get_redis_client')
    @mock.patch(
        'juloserver.customer_module.services.customer_related.delete_document_payday_customer_change_request_from_oss'
    )
    def test_cleanup_payday_change_request_from_redis_error(
        self, mock_delete_image, mock_redis_client
    ):
        # Mock Redis client and keys
        mock_redis_client.return_value.get_keys.return_value = ['payday_change_request:1']

        # Mock Redis data
        mock_redis_client.return_value.get.return_value = json.dumps(
            {"payday_change_proof_image_id": 1}
        )

        # Mock error in delete_image function
        mock_delete_image.side_effect = Exception("Delete image error")

        # Call the cleanup function
        cleanup_payday_change_request_from_redis()

        # Assert that the delete function is called with the correct image ID
        mock_delete_image.assert_called_once_with(1)

        # Assert that the Redis key is deleted
        mock_redis_client.delete_key.assert_not_called()

    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.get_redis_client')
    @mock.patch(
        'juloserver.customer_module.services.customer_related.delete_document_payday_customer_change_request_from_oss'
    )
    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.logger')
    def test_cleanup_payday_change_request_from_redis_delete_image_exception(
        self, mock_logger, mock_delete_image, mock_redis_client
    ):
        """
        Test when an exception occurs while deleting the image.
        """
        # Mock Redis client and keys
        mock_redis_client.return_value.get_keys.return_value = ['payday_change_request:1']
        # Mock Redis data
        mock_redis_client.return_value.get.return_value = json.dumps(
            {"payday_change_proof_image_id": 123}
        )

        mock_delete_image.side_effect = Exception("Delete image failed")

        cleanup_payday_change_request_from_redis()

        mock_redis_client.return_value.get_keys.assert_called_once_with(
            'customer_data_payday_change:*'
        )
        mock_delete_image.assert_called_once_with(123)
        mock_logger.error.assert_called_once()
        mock_redis_client.return_value.delete_key.assert_not_called()

    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.get_redis_client')
    @mock.patch(
        'juloserver.customer_module.services.customer_related.delete_document_payday_customer_change_request_from_oss'
    )
    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.logger')
    def test_cleanup_payday_change_request_from_redis_empty_data(
        self, mock_logger, mock_delete_image, mock_redis_client
    ):
        """
        Test cleanup_payday_change_request_from_redis when keys exist but data is empty
        """
        # Mock Redis client and keys
        mock_redis_client.return_value.get_keys.return_value = [
            'payday_change_request:1',
            'payday_change_request:2',
        ]

        mock_redis_client.return_value.get.return_value = None

        result = cleanup_payday_change_request_from_redis()

        self.assertIsNone(result)
        mock_redis_client.return_value.get_keys.assert_called_once_with(
            'customer_data_payday_change:*'
        )
        self.assertEqual(mock_redis_client.return_value.get.call_count, 2)
        mock_delete_image.assert_not_called()
        mock_redis_client.return_value.delete_key.assert_not_called()
        mock_logger.info.assert_called_once_with(
            "Payday Change Request Cleanup Complete:\n"
            "- Successfully processed: 0\n"
            "- Errors encountered: 0"
        )

    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.get_redis_client')
    @mock.patch(
        'juloserver.customer_module.services.customer_related.delete_document_payday_customer_change_request_from_oss'
    )
    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.logger')
    def test_cleanup_payday_change_request_from_redis_invalid_json_2(
        self, mock_logger, mock_delete_image, mock_redis_client
    ):
        """
        Test when Redis contains invalid JSON data for a key.
        """
        # Mock Redis client and keys
        mock_redis_client.return_value.get_keys.return_value = ['payday_change_request:1']

        # Mock invalid JSON data
        mock_redis_client.return_value.get.return_value = "invalid_json_data"

        cleanup_payday_change_request_from_redis()

        mock_redis_client.return_value.get_keys.assert_called_once_with(
            'customer_data_payday_change:*'
        )
        mock_logger.error.assert_called_once_with(
            "Invalid JSON data for key: payday_change_request:1"
        )
        mock_delete_image.assert_not_called()

    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.get_redis_client')
    @mock.patch(
        'juloserver.customer_module.services.customer_related.delete_document_payday_customer_change_request_from_oss'
    )
    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.logger')
    def test_cleanup_payday_change_request_from_redis_missing_image_id(
        self, mock_logger, mock_delete_image, mock_redis_client
    ):
        """
        Test when Redis contains valid JSON but missing the required image_id.
        """
        mock_redis_client.return_value.get_keys.return_value = ['payday_change_request:1']
        mock_redis_client.return_value.get.return_value = json.dumps({"some_key": "some_value"})

        cleanup_payday_change_request_from_redis()

        mock_redis_client.return_value.get_keys.assert_called_once_with(
            'customer_data_payday_change:*'
        )
        mock_logger.error.assert_called_once()
        mock_delete_image.assert_not_called()

    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.get_redis_client')
    @mock.patch(
        'juloserver.customer_module.services.customer_related.delete_document_payday_customer_change_request_from_oss'
    )
    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.logger')
    def test_cleanup_payday_change_request_from_redis_no_keys(
        self, mock_logger, mock_delete_image, mock_redis_client
    ):
        """
        Test when there are no keys in Redis for payday change requests.
        """
        # Mock Redis client and keys
        mock_redis_client.return_value.get_keys.return_value = []

        cleanup_payday_change_request_from_redis()

        mock_redis_client.return_value.get_keys.assert_called_once_with(
            'customer_data_payday_change:*'
        )
        mock_logger.info.assert_called_once_with("No payday change requests found to clear")
        mock_delete_image.assert_not_called()

    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.get_redis_client')
    @mock.patch(
        'juloserver.customer_module.services.customer_related.delete_document_payday_customer_change_request_from_oss'
    )
    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.logger')
    def test_cleanup_payday_change_request_from_redis_with_valid_data(
        self, mock_logger, mock_delete_image, mock_redis_client
    ):
        """
        Test cleanup_payday_change_request_from_redis with valid data in Redis
        """

        # Mock Redis data
        mock_redis_client.return_value.get_keys.return_value = [
            'payday_change_request:1',
            'payday_change_request:2',
        ]
        mock_redis_client.return_value.get.side_effect = [
            json.dumps({"payday_change_proof_image_id": 1}),
            json.dumps({"payday_change_proof_image_id": 2}),
        ]

        cleanup_payday_change_request_from_redis()

        # Assert that the function processes all keys
        self.assertEqual(mock_redis_client.return_value.get.call_count, 2)
        self.assertEqual(mock_delete_image.call_count, 2)
        self.assertEqual(mock_redis_client.return_value.delete_key.call_count, 2)

    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.get_redis_client')
    @mock.patch('juloserver.customer_module.tasks.customer_related_tasks.logger')
    def test_cleanup_payday_change_request_when_no_keys_exist(self, mock_logger, mock_redis_client):
        """
        Test cleanup_payday_change_request_from_redis when no keys exist in Redis.
        """
        mock_redis_client.return_value.get_keys.return_value = []

        result = cleanup_payday_change_request_from_redis()

        mock_redis_client.return_value.get_keys.assert_called_once_with(
            'customer_data_payday_change:*'
        )
        mock_logger.info.assert_called_once_with("No payday change requests found to clear")
        self.assertIsNone(result)


class TestSyncCustomerDataWithApplication(TestCase):
    def setUp(self):
        # Create customer with no gender and dob
        self.customer = CustomerFactory(gender=None, dob=None)

        # Create application with filled gender and dob
        self.application = ApplicationFactory(
            customer=self.customer, gender="Pria", dob=datetime(1990, 1, 1).date()
        )

    def test_sync_with_empty_customer_data(self):
        """Test syncing when customer has no gender and dob data"""

        # Execute sync for gender and dob fields
        customer_id, sync_values = sync_customer_data_with_application(
            customer_id=self.customer.id, fields=['gender', 'dob']
        )

        # Verify response
        self.assertEqual(customer_id, self.customer.id)
        self.assertEqual(len(sync_values), 2)
        self.assertEqual(sync_values.get('gender'), "Pria")
        self.assertEqual(sync_values.get('dob'), datetime(1990, 1, 1).date())

        # Verify customer was updated
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.gender, "Pria")
        self.assertEqual(self.customer.dob, datetime(1990, 1, 1).date())

        # Verify field changes were recorded
        field_changes = CustomerFieldChange.objects.filter(
            customer=self.customer, application=self.application
        ).order_by('field_name')

        self.assertEqual(len(field_changes), 2)

        dob_change = field_changes[0]
        self.assertEqual(dob_change.field_name, 'dob')
        self.assertIsNone(dob_change.old_value)
        self.assertEqual(dob_change.new_value, '1990-01-01')

        gender_change = field_changes[1]
        self.assertEqual(gender_change.field_name, 'gender')
        self.assertIsNone(gender_change.old_value)
        self.assertEqual(gender_change.new_value, "Pria")

    def test_sync_with_existing_customer_data(self):
        """Test syncing when customer already has gender and dob data"""

        # Update customer with existing data
        self.customer.gender = "Wanita"
        self.customer.dob = datetime(1995, 1, 1).date()
        self.customer.save()

        # Execute sync
        customer_id, sync_values = sync_customer_data_with_application(
            customer_id=self.customer.id, fields=['gender', 'dob']
        )

        # Verify response
        self.assertEqual(customer_id, self.customer.id)
        self.assertEqual(len(sync_values), 2)
        self.assertEqual(sync_values.get('gender'), "Pria")
        self.assertEqual(sync_values.get('dob'), datetime(1990, 1, 1).date())

        # Verify customer was updated
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.gender, "Pria")
        self.assertEqual(self.customer.dob, datetime(1990, 1, 1).date())

        # Verify field changes were recorded
        field_changes = CustomerFieldChange.objects.filter(
            customer=self.customer, application=self.application
        ).order_by('field_name')

        self.assertEqual(len(field_changes), 2)

        dob_change = field_changes[0]
        self.assertEqual(dob_change.field_name, 'dob')
        self.assertEqual(dob_change.old_value, '1995-01-01')
        self.assertEqual(dob_change.new_value, '1990-01-01')

        gender_change = field_changes[1]
        self.assertEqual(gender_change.field_name, 'gender')
        self.assertEqual(gender_change.old_value, "Wanita")
        self.assertEqual(gender_change.new_value, "Pria")

    def test_sync_with_no_application(self):
        """Test syncing when customer has no application"""

        # Delete application
        self.application.delete()

        # Execute sync
        customer_id, sync_values = sync_customer_data_with_application(
            customer_id=self.customer.id, fields=['gender', 'dob']
        )

        # Verify no changes were made
        self.assertEqual(customer_id, self.customer.id)
        self.assertEqual(len(sync_values), 0)

        # Verify customer was not updated
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.gender)
        self.assertIsNone(self.customer.dob)

        # Verify no field changes were recorded
        field_changes = CustomerFieldChange.objects.filter(customer=self.customer)
        self.assertEqual(len(field_changes), 0)
