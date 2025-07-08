from django.contrib.auth.models import Group
from rest_framework.test import APITestCase

from juloserver.face_recognition.constants import FaceMatchingCheckConst
from juloserver.face_recognition.factories import FaceMatchingCheckFactory
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    FeatureSettingFactory,
    ImageFactory,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles


class TestFaceMatching(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.ADMIN_FULL)
        self.group.save()
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.application = ApplicationFactory(id=77777, fullname='hadiyan')
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.FACE_MATCHING_CHECK,
            parameters={
                'selfie_x_ktp': {
                    'is_active': True,
                    'logical_operator': '>=',
                    'similarity_threshold': 99.0,
                },
                'selfie_x_liveness': {
                    'is_active': True,
                    'logical_operator': '>=',
                    'similarity_threshold': 99.0,
                },
            },
        )
        self.image_selfie = ImageFactory(
            image_source=self.application.id,
            image_type='crop_selfie',
            url='company_proof_image.jpg',
        )
        self.selfie_to_ktp_target_image = ImageFactory(
            image_source=self.application.id,
            image_type='ktp_selfie',
            url='company_proof_image.jpg',
        )
        self.selfie_to_liveness_target_image = ImageFactory(
            image_source=self.application.id,
            image_type='liveness',
            url='company_proof_image.jpg',
        )
        self.ktp_face_matching_check = FaceMatchingCheckFactory(
            application=self.application,
            process=FaceMatchingCheckConst.Process.selfie_x_ktp.value,
            target_image=self.selfie_to_ktp_target_image,
        )
        self.liveness_face_matching_check = FaceMatchingCheckFactory(
            application=self.application,
            process=FaceMatchingCheckConst.Process.selfie_x_liveness.value,
            target_image=self.selfie_to_ktp_target_image,
        )

    def test_get_face_matching_info_with_invalid_application(self):
        # arrange
        url = '/api/fraud-portal/face-matching/?application_id=1231123'
        expected_response = {
            'success': False,
            'data': None,
            'errors': ['Application matching query does not exist.'],
        }

        # act
        response = self.client.get(url)

        # assert
        self.assertEqual(response.json(), expected_response)
        self.assertEqual(response.status_code, 400)

    def test_get_face_matching_info_with_inactivate_feature_setting(self):
        # arrange
        self.feature_setting.is_active = False
        self.feature_setting.save()
        url = '/api/fraud-portal/face-matching/?application_id=1231123'
        expected_response = {'success': True, 'data': [], 'errors': []}

        # act
        response = self.client.get(url)

        # assert
        self.assertEqual(response.json(), expected_response)
        self.assertEqual(response.status_code, 200)

    def test_get_face_matching_info_but_selfie_x_ktp_inactive(self):
        # arrange
        self.feature_setting.parameters = {
            'selfie_x_ktp': {
                'is_active': False,
                'logical_operator': '>=',
                'similarity_threshold': 99.0,
            },
            'selfie_x_liveness': {
                'is_active': True,
                'logical_operator': '>=',
                'similarity_threshold': 99.0,
            },
        }
        self.feature_setting.save()
        url = '/api/fraud-portal/face-matching/?application_id=77777'
        expected_response = {
            'success': True,
            'data': [
                {
                    'application_id': 77777,
                    'application_full_name': 'hadiyan',
                    'selfie_image_url': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717555253&Signature=e5prKqBz%2F%2B0QQbUZyJB%2FL59Xeh0%3D',
                    'selfie_to_ktp': {'is_feature_active': False},
                    'selfie_to_liveness': {
                        'is_feature_active': True,
                        'is_agent_verified': True,
                        'image_urls': [
                            'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717555253&Signature=e5prKqBz%2F%2B0QQbUZyJB%2FL59Xeh0%3D'
                        ],
                        'status': 1,
                    },
                }
            ],
            'errors': [],
        }

        # act
        response = self.client.get(url)
        actual_response_json = response.json()

        # assert
        self.assertTrue(actual_response_json["success"])

        data = actual_response_json["data"][0]
        self.assertEqual(data["application_id"], expected_response["data"][0]["application_id"])
        self.assertEqual(
            data["application_full_name"], expected_response["data"][0]["application_full_name"]
        )
        self.assertTrue(len(data["selfie_image_urls"]) > 1)

        selfie_to_ktp = data["selfie_to_ktp"]
        expected_selfie_to_ktp = expected_response["data"][0]["selfie_to_ktp"]
        self.assertEqual(
            selfie_to_ktp["is_feature_active"], expected_selfie_to_ktp["is_feature_active"]
        )

        selfie_to_liveness = data["selfie_to_liveness"]
        expected_selfie_to_liveness = expected_response["data"][0]["selfie_to_liveness"]
        self.assertEqual(
            selfie_to_liveness["is_feature_active"],
            expected_selfie_to_liveness["is_feature_active"],
        )
        self.assertEqual(
            selfie_to_liveness["is_agent_verified"],
            expected_selfie_to_liveness["is_agent_verified"],
        )
        self.assertTrue(selfie_to_liveness["image_urls"])
        self.assertEqual(selfie_to_liveness["status"], expected_selfie_to_liveness["status"])

        self.assertEqual(actual_response_json["errors"], expected_response["errors"])
        self.assertEqual(response.status_code, 200)

    def test_get_face_matching_info(self):
        # arrange
        url = '/api/fraud-portal/face-matching/?application_id=77777'
        expected_response = {
            'success': True,
            'data': [
                {
                    'application_id': 77777,
                    'application_full_name': 'hadiyan',
                    'selfie_image_url': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717555253&Signature=e5prKqBz%2F%2B0QQbUZyJB%2FL59Xeh0%3D',
                    'selfie_to_ktp': {
                        'is_feature_active': True,
                        'is_agent_verified': True,
                        'image_urls': [
                            'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717555253&Signature=e5prKqBz%2F%2B0QQbUZyJB%2FL59Xeh0%3D'
                        ],
                        'status': 1,
                    },
                    'selfie_to_liveness': {
                        'is_feature_active': True,
                        'is_agent_verified': True,
                        'image_urls': [
                            'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717555253&Signature=e5prKqBz%2F%2B0QQbUZyJB%2FL59Xeh0%3D'
                        ],
                        'status': 1,
                    },
                }
            ],
            'errors': [],
        }

        # act
        response = self.client.get(url)
        actual_response_json = response.json()
        # assert
        self.assertTrue(actual_response_json["success"])

        data = actual_response_json["data"][0]
        self.assertTrue(len(data["selfie_image_urls"]) > 1)
        self.assertEqual(data["application_id"], expected_response["data"][0]["application_id"])
        self.assertEqual(
            data["application_full_name"], expected_response["data"][0]["application_full_name"]
        )

        selfie_to_ktp = data["selfie_to_ktp"]
        expected_selfie_to_ktp = expected_response["data"][0]["selfie_to_ktp"]
        self.assertEqual(
            selfie_to_ktp["is_feature_active"], expected_selfie_to_ktp["is_feature_active"]
        )
        self.assertEqual(
            selfie_to_ktp["is_agent_verified"], expected_selfie_to_ktp["is_agent_verified"]
        )
        self.assertTrue(selfie_to_ktp["image_urls"])
        self.assertEqual(selfie_to_ktp["status"], expected_selfie_to_ktp["status"])

        selfie_to_liveness = data["selfie_to_liveness"]
        expected_selfie_to_liveness = expected_response["data"][0]["selfie_to_liveness"]
        self.assertEqual(
            selfie_to_liveness["is_feature_active"],
            expected_selfie_to_liveness["is_feature_active"],
        )
        self.assertEqual(
            selfie_to_liveness["is_agent_verified"],
            expected_selfie_to_liveness["is_agent_verified"],
        )
        self.assertTrue(selfie_to_liveness["image_urls"])
        self.assertEqual(selfie_to_liveness["status"], expected_selfie_to_liveness["status"])

        self.assertEqual(actual_response_json["errors"], expected_response["errors"])
        self.assertEqual(response.status_code, 200)
