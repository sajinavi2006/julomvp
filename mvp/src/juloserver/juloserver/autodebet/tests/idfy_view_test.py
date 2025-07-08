from rest_framework.test import APIClient, APITestCase
from mock import ANY, patch

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
    FeatureSettingFactory,
)


class AutodebetIDFyInstructionPageAPI(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBIT_IDFY_INSTRUCTION_PAGE,
            parameters={
                "instructions": [
                    "Kamera dan mikrofon HP kamu berfungsi dengan baik",
                    "Kamu berada di area yang tidak terlalu berisik",
                    "Informasi yang kamu berikan akurat, sesuai dengan data yang telah kamu kirim sebelumnya",
                ],
                "info": {
                    "title": "Jam Operasional Video Call (WIB)",
                    "message": "Senin-Minggu/Libur Nasional: 08:00-20:00",
                },
            },
            is_active=True,
        )

    def test_idfy_instruction_page_success(self):
        url = '/api/autodebet/v1/video/entry-page/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


class AutodebetIDFyCreateProfileAPI(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
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

    @patch('juloserver.autodebet.views.views_api_v1.create_idfy_profile')
    def test_idfy_create_profile_success(self, mock_create_idfy_profile):
        mock_create_idfy_profile.return_value = (
            "https://capture.kyc-idn.idfy.com/captures?t=VYEBseA820fQ",
            "63a015e3-c00d-4ba2-b555-02386679471e",
        )
        url = '/api/autodebet/v1/video/create-profile'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    @patch('juloserver.autodebet.views.views_api_v1.create_idfy_profile')
    def test_idfy_create_profile_failed(self, mock_create_idfy_profile):
        mock_create_idfy_profile.return_value = None, None
        url = '/api/autodebet/v1/video/create-profile'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)


class AutodebetIDFyCallback(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()

    @patch('juloserver.autodebet.views.views_api_v1.proceed_the_status_complete_response')
    def test_idfy_callback_completed_success(self, proceed_the_status_complete_response):
        url = '/webhook/autodebet/idfy/v1/video/callback'
        data = {
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
                            "status_reason": None,
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
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.autodebet.views.views_api_v1.proceed_the_status_dropoff_response')
    def test_idfy_callback_dropoff_success(self, proceed_the_status_dropoff_response):
        url = '/webhook/autodebet/idfy/v1/video/callback/session-drop-off'
        data = {
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

        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 200)
