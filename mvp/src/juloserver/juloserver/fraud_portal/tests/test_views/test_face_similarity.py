from django.contrib.auth.models import Group
from rest_framework import status
from rest_framework.test import APITestCase

from juloserver.face_recognition.factories import (
    FaceCollectionFactory,
    FaceImageResultFactory,
    FaceSearchProcessFactory,
    FaceSearchResultFactory,
    FraudFaceSearchResultFactory,
    FraudFaceSearchProcessFactory,
    IndexedFaceFraudFactory,
    IndexedFaceFactory,
)
from juloserver.geohash.tests.factories import AddressGeolocationGeohashFactory
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import Image
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    FeatureSettingFactory,
    ImageFactory,
    AddressGeolocationFactory,
    CustomerFactory,
    ApplicationJ1Factory,
    ApplicationHistoryFactory,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles


class TestFaceSimilarity(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.ADMIN_FULL)
        self.group.save()
        self.user.groups.add(self.group)
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.application = ApplicationFactory(id=77777, fullname='hadiyan')
        self.fraud_face_match_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUDSTER_FACE_MATCH,
            parameters={
                "fraud_face_match_settings": {
                    "logical_operator": ">=",
                    "max_face_matches": 10,
                    "similarity_threshold": 99.7,
                }
            },
        )
        self.similar_face_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.FACE_RECOGNITION,
            parameters={
                "aws_settings": {
                    "max_faces": 10,
                    "attributes": ["ALL"],
                    "quality_filter": "LOW",
                    "max_faces_indexed": 1,
                    "face_match_threshold": 75,
                    "quality_filter_indexed": "NONE",
                    "face_comparison_threshold": 80,
                },
                "max_retry_count": 2,
                "max_face_matches": 4,
                "face_recognition_settings": {
                    "crop_padding": 0.1,
                    "allowed_faces": 2,
                    "image_dimensions": 480,
                    "sharpness_threshold": 60,
                    "brightness_threshold": 40,
                    "similarity_threshold": 101,
                },
            },
        )
        self.selfie_geohash_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.SELFIE_GEOHASH_CRM_IMAGE_LIMIT, parameters={"days": 30}
        )
        self.application_selfie_image = ImageFactory(
            image_source=self.application.id,
            image_type='crop_selfie',
            url='company_proof_image.jpg',
        )
        self.application_selfie_image2 = ImageFactory(
            image_source=self.application.id,
            image_type='selfie',
            image_status=Image.CURRENT,
            url='company_proof_image.jpg',
        )
        self.face_image_result = FaceImageResultFactory(application=self.application)
        self.fraud_face_search_process = FraudFaceSearchProcessFactory(
            application=self.application, status='found'
        )
        self.fraud_face_collection = FaceCollectionFactory(face_collection_name='fraud_face_match')
        self.fraud_face_search_result = FraudFaceSearchResultFactory(
            face_collection=self.fraud_face_collection,
            searched_face_image_id=self.face_image_result,
            face_search_process=self.fraud_face_search_process,
            matched_face_image_id=self.application_selfie_image,
        )
        self.indexed_face_fraud = IndexedFaceFraudFactory(
            application=self.application, image=self.application_selfie_image
        )
        self.application_ktp_image = ImageFactory(
            image_source=self.application.id,
            image_type='ktp',
            url='company_proof_image.jpg',
        )
        self.face_search_process = FaceSearchProcessFactory(
            application=self.application, status='ketemu'
        )

    def test_get_face_similarity_only_has_fraud_face_data(self):
        # arrange
        url = '/api/fraud-portal/face-similarity/?application_id=77777'
        expected_response = {
            'success': True,
            'data': [
                {
                    'application_id': 77777,
                    'application_full_name': 'hadiyan',
                    'selfie_image_urls': [
                        'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717990791&Signature=cEYrPRtZQIFdCOsUlPd96CX3ljc%3D'
                    ],
                    'face_comparison': {
                        'fraud_face': [
                            {
                                'application_id': 77777,
                                'matched_selfie': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717990791&Signature=cEYrPRtZQIFdCOsUlPd96CX3ljc%3D',
                                'matched_ktp': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717990791&Signature=cEYrPRtZQIFdCOsUlPd96CX3ljc%3D',
                            }
                        ],
                        'similar_face': [],
                    },
                    'face_comparison_by_geohash': [],
                }
            ],
            'errors': [],
        }

        # act
        response = self.client.get(url)
        # pdb.set_trace()

        # assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_response_json = response.json()
        self.assertTrue(actual_response_json["success"])

        data = actual_response_json["data"][0]
        self.assertEqual(
            data["application_full_name"], expected_response["data"][0]["application_full_name"]
        )
        self.assertTrue(len(data["selfie_image_urls"]) > 1)

        face_comparison_data = actual_response_json["data"][0]["face_comparison"]
        self.assertEqual(face_comparison_data["fraud_face_status"], 'found')
        self.assertTrue(len(face_comparison_data["fraud_face"]) > 0)
        self.assertEqual(face_comparison_data["similarity_face_status"], 'ketemu')
        self.assertTrue(len(face_comparison_data["similar_face"]) == 0)

        face_comparison_by_geohash_data = actual_response_json["data"][0][
            "face_comparison_by_geohash"
        ]
        self.assertEqual([], face_comparison_by_geohash_data)

    def test_get_face_similarity_without_geohash_data(self):
        # arrange
        self.face_search_result = FaceSearchResultFactory(
            searched_face_image_id=self.face_image_result,
            face_search_process=self.face_search_process,
            matched_face_image_id=self.application_selfie_image,
        )
        self.indexed_face_fraud = IndexedFaceFactory(
            face_collection=self.fraud_face_collection,
            image=self.application_selfie_image,
            application=self.application,
        )
        url = '/api/fraud-portal/face-similarity/?application_id=77777'
        expected_response = {
            'success': True,
            'data': [
                {
                    'application_id': 77777,
                    'application_full_name': 'hadiyan',
                    'selfie_image_urls': [
                        'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717999826&Signature=nZS5HZPGR5p3uG9jDT4kNWj%2FKSc%3D',
                        'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717999826&Signature=nZS5HZPGR5p3uG9jDT4kNWj%2FKSc%3D',
                    ],
                    'face_comparison': {
                        'fraud_face': [
                            {
                                'application_id': 77777,
                                'matched_selfie': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717999826&Signature=nZS5HZPGR5p3uG9jDT4kNWj%2FKSc%3D',
                                'matched_ktp': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717999826&Signature=nZS5HZPGR5p3uG9jDT4kNWj%2FKSc%3D',
                            }
                        ],
                        'similar_face': [
                            {
                                'application_id': 77777,
                                'matched_selfie': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717999826&Signature=nZS5HZPGR5p3uG9jDT4kNWj%2FKSc%3D',
                                'matched_ktp': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717999826&Signature=nZS5HZPGR5p3uG9jDT4kNWj%2FKSc%3D',
                            }
                        ],
                    },
                    'face_comparison_by_geohash': [],
                }
            ],
            'errors': [],
        }

        # act
        response = self.client.get(url)

        # assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_response_json = response.json()
        self.assertTrue(actual_response_json["success"])

        data = actual_response_json["data"][0]
        self.assertEqual(
            data["application_full_name"], expected_response["data"][0]["application_full_name"]
        )
        self.assertTrue(len(data["selfie_image_urls"]) > 1)

        face_comparison_data = actual_response_json["data"][0]["face_comparison"]
        self.assertEqual(face_comparison_data["fraud_face_status"], 'found')
        self.assertTrue(len(face_comparison_data["fraud_face"]) > 0)
        self.assertEqual(face_comparison_data["similarity_face_status"], 'ketemu')
        self.assertTrue(len(face_comparison_data["similar_face"]) > 0)

        face_comparison_by_geohash_data = actual_response_json["data"][0][
            "face_comparison_by_geohash"
        ]
        self.assertEqual([], face_comparison_by_geohash_data)

    def test_get_face_similarity(self):
        # arrange
        self.application_2 = ApplicationJ1Factory(customer=self.customer)
        ApplicationHistoryFactory(application_id=self.application_2.id, status_new=105)
        self.face_search_process = FaceSearchProcessFactory(
            application=self.application, status='ga ketemu'
        )
        self.face_search_result = FaceSearchResultFactory(
            searched_face_image_id=self.face_image_result,
            face_search_process=self.face_search_process,
            matched_face_image_id=self.application_selfie_image,
        )
        self.indexed_face_fraud = IndexedFaceFactory(
            face_collection=self.fraud_face_collection,
            image=self.application_selfie_image,
            application=self.application,
        )
        self.address_geolocation = AddressGeolocationFactory(application=self.application)
        self.address_geo_location = AddressGeolocationGeohashFactory(
            address_geolocation=self.address_geolocation,
            geohash6='123456',
        )
        self.address_geolocation_2 = AddressGeolocationFactory(application=self.application_2)
        self.address_geo_location_2 = AddressGeolocationGeohashFactory(
            address_geolocation=self.address_geolocation_2,
            geohash6='123456',
        )
        self.image_2 = ImageFactory(
            image_type="selfie", image_source=self.application_2.pk, url="test_1.jpg"
        )
        url = '/api/fraud-portal/face-similarity/?application_id=77777'
        expected_response = {
            'success': True,
            'data': [
                {
                    'application_id': 77777,
                    'application_full_name': 'hadiyan',
                    'selfie_image_urls': [
                        'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1718001349&Signature=xbCPrHgIreI%2FuBsJ0EojglmyUcY%3D',
                        'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1718001349&Signature=xbCPrHgIreI%2FuBsJ0EojglmyUcY%3D',
                    ],
                    'face_comparison': {
                        'fraud_face': [
                            {
                                'application_id': 77777,
                                'matched_selfie': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1718001349&Signature=xbCPrHgIreI%2FuBsJ0EojglmyUcY%3D',
                                'matched_ktp': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1718001349&Signature=xbCPrHgIreI%2FuBsJ0EojglmyUcY%3D',
                            }
                        ],
                        'similar_face': [
                            {
                                'application_id': 77777,
                                'matched_selfie': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1718001349&Signature=xbCPrHgIreI%2FuBsJ0EojglmyUcY%3D',
                                'matched_ktp': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1718001349&Signature=xbCPrHgIreI%2FuBsJ0EojglmyUcY%3D',
                            }
                        ],
                    },
                    'face_comparison_by_geohash': [
                        {
                            'application_id': 1,
                            'image_url': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/test_1.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1718001991&Signature=7pePtHguLTOlrRXUm2XywjeokZA%3D',
                        }
                    ],
                }
            ],
            'errors': [],
        }

        # act
        response = self.client.get(url)

        # assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_response_json = response.json()
        self.assertTrue(actual_response_json["success"])

        data = actual_response_json["data"][0]
        self.assertEqual(
            data["application_full_name"], expected_response["data"][0]["application_full_name"]
        )
        self.assertTrue(len(data["selfie_image_urls"]) > 1)

        face_comparison_data = actual_response_json["data"][0]["face_comparison"]
        self.assertEqual(face_comparison_data["fraud_face_status"], 'found')
        self.assertTrue(len(face_comparison_data["fraud_face"]) > 0)
        self.assertEqual(face_comparison_data["similarity_face_status"], 'ga ketemu')
        self.assertTrue(len(face_comparison_data["similar_face"]) > 0)

        face_comparison_by_geohash_data = actual_response_json["data"][0][
            "face_comparison_by_geohash"
        ]
        self.assertTrue(len(face_comparison_by_geohash_data) > 0)
