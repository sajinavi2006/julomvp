import json
import time
from datetime import (
    datetime,
)
from unittest import mock

import mock
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from juloserver.comms.constants import EventConst
from juloserver.comms.models import CommsRequestEvent
from juloserver.comms.services.email_service import (
    EmailAddress,
    EmailContent,
)
from juloserver.comms.tasks import (
    add_comms_request_event,
    save_email_callback,
    send_email_via_rmq,
)
from juloserver.comms.tests.factories import CommsRequestFactory
from juloserver.julo.models import EmailHistory
from juloserver.julo.tests.factories import EmailHistoryFactory


@mock.patch('juloserver.comms.tasks.email.publish_send_email')
@mock.patch('juloserver.comms.tasks.email.get_redis_client')
class TestSendEmailViaRMQ(TestCase):
    def test_redis_not_found(self, mock_redis_client, mock_publish_send_email):
        mock_redis_client.return_value.get.return_value = None
        send_email_via_rmq("test_id", "redis_key", 2)

        mock_redis_client.return_value.get.assert_called_once_with("redis_key")
        mock_publish_send_email.has_no_call()

    def test_success_format(self, mock_redis_client, mock_publish_send_email):
        raw_obj = {
            "request_id": "json_id",
            "to_email": {"email": "from@example.com", "name": "From"},
            "content": {"subject": "test subject", "content": "Example Test", "type": "text/html"},
            "from_email": None,
            "cc_emails": None,
            "bcc_emails": None,
        }
        mock_redis_client.return_value.get.return_value = json.dumps(raw_obj)
        send_email_via_rmq("test_id", "redis_key", 2)

        mock_redis_client.return_value.get.assert_called_once_with("redis_key")
        mock_publish_send_email.assert_called_once_with(
            retry_num=2,
            to_email=EmailAddress("from@example.com", "From"),
            from_email=None,
            content=EmailContent("test subject", "Example Test"),
            cc_emails=None,
            bcc_emails=None,
            request_id="json_id",
        )

    def test_invalid_format(self, mock_redis_client, mock_publish_send_email):
        raw_obj = {
            "request_id": "json_id",
            "to_email": {"email": "from@example.com", "name": "From"},
            "content": {"subject": "test subject", "content": "Example Test", "type": "text/html"},
        }
        mock_redis_client.return_value.get.return_value = json.dumps(raw_obj)

        with self.assertRaises(Exception):
            send_email_via_rmq("test_id", "redis_key", 2)

        mock_redis_client.return_value.get.assert_called_once_with("redis_key")
        mock_publish_send_email.has_no_call()


class TestAddCommRequestEvent(TestCase):
    def test_success_create(self):
        comms_request = CommsRequestFactory(request_id="test_request_id")
        event_at = datetime(2021, 1, 1, 12, 39, 59, tzinfo=timezone.utc)
        ret_comm_request_id, ret_event, ret_event_at = add_comms_request_event(
            comms_request_id=comms_request.id,
            event=EventConst.SENDING,
            event_at=event_at,
            remarks="remarks",
        )

        self.assertEqual(comms_request.id, ret_comm_request_id)
        self.assertEqual(EventConst.SENDING, ret_event)
        self.assertEqual(event_at, ret_event_at)

        event = CommsRequestEvent.objects.filter(comms_request_id=ret_comm_request_id).last()
        self.assertEqual(comms_request.id, event.comms_request_id)
        self.assertEqual(EventConst.SENDING, event.event)
        self.assertEqual(event_at, event.event_at)

    def test_update_email_history(self):
        comms_request = CommsRequestFactory(request_id="test_request_id")
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2021, 1, 1, 11, 39, 59, tzinfo=timezone.utc)
            EmailHistoryFactory(sg_message_id=comms_request.request_id, status=EventConst.SENDING)
        event_at = datetime(2020, 1, 1, 12, 39, 59, tzinfo=timezone.utc)
        add_comms_request_event(
            comms_request_id=comms_request.id,
            event=EventConst.SENT,
            event_at=event_at,
            remarks="remarks",
        )

        email_history = EmailHistory.objects.filter(sg_message_id=comms_request.request_id).last()
        self.assertEqual(EventConst.SENT, email_history.status)

    def test_update_email_history_status_not_registered(self):
        comms_request = CommsRequestFactory(request_id="test_request_id")
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2021, 1, 1, 11, 39, 59, tzinfo=timezone.utc)
            EmailHistoryFactory(sg_message_id=comms_request.request_id, status=EventConst.SENDING)
        event_at = datetime(2021, 1, 1, 12, 39, 59, tzinfo=timezone.utc)
        add_comms_request_event(
            comms_request_id=comms_request.id,
            event="unknown",
            event_at=event_at,
            remarks="remarks",
        )

        email_history = EmailHistory.objects.filter(sg_message_id=comms_request.request_id).last()
        self.assertEqual("unknown", email_history.status)

    def test_not_update_email_history(self):
        comms_request = CommsRequestFactory(request_id="test_request_id")
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2021, 1, 1, 11, 39, 59, tzinfo=timezone.utc)
            EmailHistoryFactory(sg_message_id=comms_request.request_id, status="unknown_status")
        event_at = datetime(2022, 1, 1, 12, 39, 59, tzinfo=timezone.utc)
        add_comms_request_event(
            comms_request_id=comms_request.id,
            event=EventConst.SENT,
            event_at=event_at,
            remarks="remarks",
        )

        email_history = EmailHistory.objects.filter(sg_message_id=comms_request.request_id).last()
        self.assertEqual("unknown_status", email_history.status)


class TestSaveEmailCallback(TestCase):
    def test_save_email_callback(self):
        CommsRequestFactory(request_id="test_request_id")
        email_callback_dto = {
            "email_request_id": "test_request_id",
            "status": "delivered",
            "event_at": int(time.time()),
        }
        request_id, status = save_email_callback(email_callback_dto)

        comms_request_event = CommsRequestEvent.objects.filter(
            comms_request__request_id=email_callback_dto["email_request_id"]
        ).last()
        self.assertEqual(email_callback_dto["status"], comms_request_event.event)
        self.assertEqual(
            email_callback_dto["event_at"],
            comms_request_event.event_at.timestamp(),
        )
        self.assertEqual(email_callback_dto["email_request_id"], request_id)
        self.assertEqual("delivered", status)

    def test_save_email_callback_not_found(self):
        email_callback_dto = {
            "email_request_id": "test_request_id",
            "status": EventConst.SENDING,
            "event_at": int(time.time()),
        }
        request_id, status = save_email_callback(email_callback_dto)
        self.assertEqual(email_callback_dto["email_request_id"], request_id)
        self.assertEqual("request_id not found", status)
        self.assertEqual(0, CommsRequestEvent.objects.count())

    def test_invalid_request_body(self):
        email_callback_dto = {
            "email_request_id": "test_request_id",
            "status": "delivered",
            "event_at": None,
        }
        with self.assertRaises(ValidationError):
            save_email_callback(email_callback_dto)
