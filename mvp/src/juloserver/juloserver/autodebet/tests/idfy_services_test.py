from django.test.testcases import TestCase
from mock import ANY, patch, Mock
from datetime import datetime

from juloserver.julo.constants import (
    FeatureNameConst,
    WorkflowConst,
)
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
    FeatureSettingFactory,
    WorkflowFactory,
    AutodebetIdfyVideoCallFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.autodebet.services.idfy_service import (
    create_idfy_profile,
    proceed_the_status_complete_response,
    proceed_the_status_dropoff_response,
)
from juloserver.autodebet.models import AutodebetIdfyVideoCall
from juloserver.autodebet.constants import LabelFieldsIDFyConst
from juloserver.julo.clients.idfy import (
    IDfyProfileCreationError,
    IDfyTimeout,
    IDfyOutsideOfficeHour,
)


class AutodebetIDFyCreateProfileServices(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
        )
        self.fs_config_id = FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBET_IDFY_CONFIG_ID,
            is_active=True,
            parameters={'config_id': '1234-1234-1234-1234'},
            description='Config ID for IDfy Autodebet',
            category='IDFy',
        )
        self.fs_office_hour = FeatureSettingFactory(
            feature_name=FeatureNameConst.IDFY_VIDEO_CALL_HOURS,
            is_active=True,
            parameters={
                'weekdays': {
                    'open': {
                        'hour': 8,
                        'minute': 0,
                    },
                    'close': {
                        'hour': 20,
                        'minute': 0,
                    },
                },
                'holidays': {
                    'open': {
                        'hour': 8,
                        'minute': 0,
                    },
                    'close': {
                        'hour': 20,
                        'minute': 30,
                    },
                },
            },
        )

    @patch('django.utils.timezone.now')
    @patch('requests.request')
    def test_create_profile_success(self, mock_http_request, mock_timezone):
        mock_timezone.return_value = datetime(2024, 5, 26, 8, 0, 0)
        mock_response = Mock()

        # success case
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "capture_expires_at": None,
            "capture_link": "https://capture.kyc.idfy.com/captures?t=test",
            "profile_id": "test",
        }
        mock_http_request.return_value = mock_response

        video_call_url, profile_id = create_idfy_profile(self.customer)
        video_call_record = AutodebetIdfyVideoCall.objects.filter(profile_id=profile_id).last()
        self.assertIsNotNone(video_call_url)
        self.assertIsNotNone(profile_id)
        self.assertIsNotNone(video_call_record)

    @patch('django.utils.timezone.now')
    @patch("requests.request")
    def test_create_profile_still_capture_pending(self, mock_http_request, mock_timezone):
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)
        mock_response = Mock()

        mock_response.status_code = 200
        mock_http_request.return_value = mock_response

        AutodebetIdfyVideoCallFactory(
            reference_id="1234-1234-1234-1234",
            account=self.account,
            status=LabelFieldsIDFyConst.KEY_CAPTURE_PENDING,
            profile_url="https://capture.kyc.idfy.com/captures?t=test",
            profile_id="test",
        )

        video_call_url, profile_id = create_idfy_profile(self.customer)

        self.assertEquals(video_call_url, "https://capture.kyc.idfy.com/captures?t=test")
        self.assertEquals(profile_id, "test")

    @patch('django.utils.timezone.now')
    @patch("requests.request")
    def test_failed_create_profile(self, mock_http_request, mock_timezone):
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)
        mock_response = Mock()

        mock_response.status_code = 422
        mock_http_request.return_value = mock_response
        with self.assertRaises(IDfyProfileCreationError):
            create_idfy_profile(self.customer)

    @patch('django.utils.timezone.now')
    @patch("requests.request")
    def test_server_error_create_profile(self, mock_http_request, mock_timezone):
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)
        mock_response = Mock()

        mock_response.status_code = 503
        mock_http_request.return_value = mock_response
        with self.assertRaises(IDfyTimeout):
            create_idfy_profile(self.customer)

    @patch('django.utils.timezone.now')
    def test_failed_out_of_office(self, mock_timezone):
        mock_timezone.return_value = datetime(2023, 10, 10, 7, 0, 0)

        with self.assertRaises(IDfyOutsideOfficeHour):
            create_idfy_profile(self.customer)


class AutodebetIDFyCallbackServices(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
        )
        self.autodebet_idfy_record = AutodebetIdfyVideoCallFactory(
            reference_id="f01322ac-4854-443c-875e-b7c1f2dd8aed",
            account=self.account,
            status=LabelFieldsIDFyConst.KEY_CAPTURE_PENDING,
            profile_url="https://capture.kyc.idfy.com/captures?t=936445b8-febe-459f-a9dc-332886c5f8ab",
            profile_id="936445b8-febe-459f-a9dc-332886c5f8ab",
        )
        self.data = {
            "config": {"id": "7ae03032-e507-4faa-a1ad-c9c1dc4cc546", "overrides": None},
            "device_info": {
                "final_ipv4": "35.241.2.90",
                "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            },
            "profile_data": {
                "completed_at": "2024-06-11T16:22:22Z",
                "created_at": "2024-06-11T15:06:06Z",
                "email": [],
                "mobile_number": [],
                "notes": "asasa",
                "performed_by": [
                    {
                        "account_id": "302bc86b-c0fa-4a64-99ef-784db221e098",
                        "action": "video_call",
                        "email": "vriza.wahyu@julofinance.com",
                        "performed_at": "2024-06-11T16:17:25Z",
                    },
                    {
                        "account_id": "302bc86b-c0fa-4a64-99ef-784db221e098",
                        "action": "review",
                        "email": "vriza.wahyu@julofinance.com",
                        "performed_at": "2024-06-11T16:22:22Z",
                    },
                ],
                "purged_at": None,
            },
            "profile_id": "936445b8-febe-459f-a9dc-332886c5f8ab",
            "reference_id": "f01322ac-4854-443c-875e-b7c1f2dd8aed",
            "resources": {
                "documents": [],
                "images": [],
                "text": [
                    {
                        "attr": "name",
                        "location": {},
                        "metadata": {},
                        "ref_id": "nil.nil.name.0.nil",
                        "source": 0,
                        "tags": None,
                        "type": None,
                        "value": {"first_name": "Test", "last_name": "JULO"},
                    }
                ],
                "videos": [
                    {
                        "attr": "agent",
                        "location": {},
                        "metadata": {"offset": 0},
                        "ref_id": "nil.nil.agent.2.nil",
                        "source": 2,
                        "tags": None,
                        "type": None,
                        "value": "https://storage.googleapis.com/0a211f15c921.kyc-idn.idfy.com/a665a0d5-8f40-48fa-b237-46e97fb3d87c?Expires=1718124749&GoogleAccessId=canis-profiles-gateway%40idfy-vs-indonesia.iam.gserviceaccount.com&Signature=GwyrhYSyikp6Bp8qsDW6aKXWfDwBLB5JRLvy3yRTO1%2FFfTkbSEJ7qBgioyi3wxnz3e7qmHKToMA06Uhvc4gnBIszNyOYAiOtEVt1iby2JKLaT415aN2K5KjR6PxCjddkgoGjMKaylsJeGK6cEOfnSIHFyCZv2R5AyujO8OOgVco4KEwYU%2B3RujpJlJJBvGG5rVDCZ7LRzxc2uxofTolKJPN1Z9u0CdaDsmCaAWIUyyK%2FKm%2BpXnVazSYbCFmmwfrDhxwEKb8PLkNObQSpRwkf%2B4n%2Bs4pRCGvGLNIV3OJxfkZ1NUyXfwrjO9L38UL%2BmC4KqCBiuuf%2B%2F%2BxHvDpVwo5tjg%3D%3D",
                    },
                    {
                        "attr": "customer",
                        "location": {},
                        "metadata": {"offset": 1},
                        "ref_id": "nil.nil.customer.2.nil",
                        "source": 2,
                        "tags": None,
                        "type": None,
                        "value": "https://storage.googleapis.com/0a211f15c921.kyc-idn.idfy.com/ebcc3244-bb8c-400b-8d82-13737960ea6a?Expires=1718124749&GoogleAccessId=canis-profiles-gateway%40idfy-vs-indonesia.iam.gserviceaccount.com&Signature=G0yj%2B%2B%2FHZyZ6ZWgUFQVyli6atSwnaIj0cHf9k5BWGIowFNRIB0rFyig%2F8xYuBtuBXq7bxrBWOfavz6BICuK7r0Uk8zJBxmHmn9mou6Qt%2BKzJOwieEjOmUpDI%2F%2FWm5NA4bJcszwHglVhes3syrGLpvOKwbjrr6H6ABelXBt6k7ud047yKaSrnOlqIOy8DcWqYK0v%2FOkQfV%2F6mT5kCtOy3p6FKyeMdk85Gn4nYSdi9iGGMzj2DB1AYvLbCfeTO%2B3BjHReJiNluqRDLaSPMQURjnmfDjmkkvFvW88qyWYb2NbpnArtKQ%2BRr0aa6kypEw0E6mxufr%2FpPxmgTZ2mpY%2FgGHw%3D%3D",
                    },
                ],
            },
            "reviewer_action": "approved",
            "schema_version": "1.0.0",
            "status": "completed",
            "status_description": {"code": None, "comments": None, "reason": None},
            "status_detail": None,
            "tag": None,
            "tasks": [
                {
                    "key": "vkyc.assisted_vkyc",
                    "resources": ["nil.nil.customer.2.nil", "nil.nil.agent.2.nil"],
                    "result": {
                        "automated_response": None,
                        "manual_response": {
                            "performed_by": {
                                "account_id": "302bc86b-c0fa-4a64-99ef-784db221e098",
                                "action": "video_call",
                                "email": "vriza.wahyu@julofinance.com",
                                "performed_at": "2024-06-11T16:17:25Z",
                            },
                            "skill_config": {},
                            "status": "verified",
                            "status_reason": "approved",
                        },
                    },
                    "status": "completed",
                    "task_id": "40c811f6-a19f-4009-bda9-538f708f2632",
                    "task_type": "vkyc.assisted_vkyc",
                    "tasks": [
                        {
                            "tasks": [
                                {
                                    "key": "verify_qa_f165",
                                    "question": "Please ask the customer whether the customer has tried the auto-debit process earlier or not?",
                                    "resources": [],
                                    "result": {
                                        "automated_response": None,
                                        "manual_response": {"value": "Yes"},
                                    },
                                    "status": "completed",
                                    "task_id": "baa086e5-b6e5-49cc-a92a-77db0f3ce190",
                                    "task_type": "verify.qa",
                                }
                            ]
                        },
                        {
                            "tasks": [
                                {
                                    "key": "verify_qa_ce85",
                                    "question": "Has customer understood the entire process?",
                                    "resources": [],
                                    "result": {
                                        "automated_response": None,
                                        "manual_response": {"value": "Yes"},
                                    },
                                    "status": "completed",
                                    "task_id": "d2edec53-3cd1-4b37-83fa-126c0d80212f",
                                    "task_type": "verify.qa",
                                }
                            ]
                        },
                        {
                            "tasks": [
                                {
                                    "key": "verify_qa_c173",
                                    "question": "Has customer given confirmation of when they will do the journey?",
                                    "resources": [],
                                    "result": {
                                        "automated_response": None,
                                        "manual_response": {"value": "Yes"},
                                    },
                                    "status": "completed",
                                    "task_id": "8161d10c-3126-4ec5-aee7-3e8ef28b7b50",
                                    "task_type": "verify.qa",
                                }
                            ]
                        },
                        {
                            "tasks": [
                                {
                                    "key": "verify_qa_d1f0",
                                    "question": "Have you informed customer, they can use the video call option again if they are still unable to setup the auto-debit option?",
                                    "resources": [],
                                    "result": {
                                        "automated_response": None,
                                        "manual_response": {"value": "Yes"},
                                    },
                                    "status": "completed",
                                    "task_id": "99e6a862-782a-4e7a-9f71-9b38586c927e",
                                    "task_type": "verify.qa",
                                }
                            ]
                        },
                    ],
                }
            ],
            "version": "v1.1",
        }

        self.data_dropoff = {
            "config": {"id": "7ae03032-e507-4faa-a1ad-c9c1dc4cc546"},
            "pending_resources": {"images": [], "text": [], "videos": []},
            "profile_data": {
                "created_at": "2023-06-13T09:51:28Z",
                "email_ids": [],
                "mobile_numbers": [],
            },
            "profile_id": "936445b8-febe-459f-a9dc-332886c5f8ab",
            "reference_id": "f01322ac-4854-443c-875e-b7c1f2dd8aed",
            "reason": "customer_drop",
            "session_status": "incomplete",
            "status": "capture_pending",
            "tag": "Partner:XY",
            "video_call": {"agent_remark": None, "status": None},
        }

    def test_proceed_status_complete_success(self):
        proceed_the_status_complete_response(self.data)

        idfy_record = AutodebetIdfyVideoCall.objects.filter(
            reference_id=self.data['reference_id'],
        ).last()

        self.assertIsNotNone(idfy_record)
        self.assertEqual(self.data['status'], idfy_record.status)
        self.assertEqual("approved", idfy_record.reject_reason)

    def test_proceed_status_complete_failed(self):
        self.data['reference_id'] = '1234-1234-1234'
        with self.assertRaises(Exception):
            proceed_the_status_complete_response(self.data)

    def test_proceed_status_dropoff_success(self):
        proceed_the_status_dropoff_response(self.data_dropoff)

        idfy_record = AutodebetIdfyVideoCall.objects.filter(
            reference_id=self.data_dropoff['reference_id'],
        ).last()

        self.assertIsNotNone(idfy_record)
        self.assertEqual(self.data_dropoff['status'], idfy_record.status)

    def test_proceed_status_dropoff_failed(self):
        self.data_dropoff['reference_id'] = '1234-1234-1234'
        with self.assertRaises(Exception):
            proceed_the_status_dropoff_response(self.data_dropoff)
