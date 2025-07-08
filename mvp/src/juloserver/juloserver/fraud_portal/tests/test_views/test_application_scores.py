from django.contrib.auth.models import Group
from rest_framework.test import APITestCase

from juloserver.ana_api.tests.factories import PdCreditEarlyModelResultFactory
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.application_flow.factories import (
    ShopeeScoringFactory,
    MycroftResultFactory,
    MycroftThresholdFactory,
)
from juloserver.face_recognition.factories import (
    FaceSearchProcessFactory,
    FaceImageResultFactory,
    FaceSearchResultFactory,
)
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CreditScoreFactory,
)
from juloserver.liveness_detection.tests.factories import (
    ActiveLivenessDetectionFactory,
    PassiveLivenessDetectionFactory,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles


class TestApplicationScores(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.ADMIN_FULL)
        self.group.save()
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.application = ApplicationFactory(id=77777, fullname='hadiyan')
        self.shopee_scoring_factory = ShopeeScoringFactory(
            application=self.application, is_passed=True
        )
        self.mycroft_threshold_factory = MycroftThresholdFactory(score=0.6, logical_operator='>=')
        self.mycroft_result = MycroftResultFactory(
            application=self.application,
            mycroft_threshold=self.mycroft_threshold_factory,
            score=0.9,
        )
        self.credit_score = CreditScoreFactory(application_id=self.application.id)
        self.active_liveness_detection = ActiveLivenessDetectionFactory(
            application=self.application
        )
        self.passive_liveness_detection = PassiveLivenessDetectionFactory(
            application=self.application
        )
        self.pd_credit_model = PdCreditModelResultFactory(application_id=self.application.id)
        self.pd_credit_early_model = PdCreditEarlyModelResultFactory(
            application_id=self.application.id
        )
        self.face_image_result = FaceImageResultFactory(application=self.application)
        self.face_search_process = FaceSearchProcessFactory(application=self.application)
        self.face_search_result = FaceSearchResultFactory(
            searched_face_image_id=self.face_image_result,
            face_search_process=self.face_search_process,
        )

    def test_get_application_scores_with_invalid_application(self):
        # arrange
        url = '/api/fraud-portal/application-scores/?application_id=1231123'
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

    def test_get_application_scores_but_doesnt_have_scores(self):
        # arrange
        ApplicationFactory(id=777771, fullname='delberth')
        url = '/api/fraud-portal/application-scores/?application_id=777771'
        expected_response = {
            'success': True,
            'data': [
                {
                    'application_id': 777771,
                    'application_full_name': 'delberth',
                    'shopee_score': None,
                    'application_similarity_score': None,
                    'mycroft_score': None,
                    'credit_score': None,
                    'active_liveness_score': None,
                    'passive_liveness_score': None,
                    'heimdall_score': None,
                    'orion_score': None,
                }
            ],
            'errors': [],
        }

        # act
        response = self.client.get(url)

        # assert
        self.assertEqual(response.json(), expected_response)
        self.assertEqual(response.status_code, 200)

    def test_get_application_scores(self):
        # arrange
        url = '/api/fraud-portal/application-scores/?application_id=77777'
        expected_response = {
            'success': True,
            'data': [
                {
                    'application_id': 77777,
                    'application_full_name': 'hadiyan',
                    'shopee_score': True,
                    'application_similarity_score': 99.27,
                    'mycroft_score': 0.9,
                    'credit_score': 'C',
                    'active_liveness_score': 1.0,
                    'passive_liveness_score': 1.0,
                    'heimdall_score': 0.6,
                    'orion_score': 0.5,
                }
            ],
            'errors': [],
        }

        # act
        response = self.client.get(url)

        # assert
        self.assertEqual(response.json(), expected_response)
        self.assertEqual(response.status_code, 200)

    def test_get_application_scores_with_multiple_applications(self):
        # arrange
        application = ApplicationFactory(id=777772, fullname='calvin')
        ShopeeScoringFactory(application=application, is_passed=True)
        MycroftThresholdFactory(score=0.6, logical_operator='>=')
        MycroftResultFactory(
            application=application, mycroft_threshold=self.mycroft_threshold_factory, score=1.2
        )
        CreditScoreFactory(application_id=application.id, score="B-")
        ActiveLivenessDetectionFactory(application=application)
        PassiveLivenessDetectionFactory(application=application)
        PdCreditModelResultFactory(id=321, application_id=application.id)
        PdCreditEarlyModelResultFactory(application_id=application.id)
        face_image_result = FaceImageResultFactory(application=application)
        face_search_process = FaceSearchProcessFactory(application=application)
        FaceSearchResultFactory(
            searched_face_image_id=face_image_result,
            face_search_process=face_search_process,
            similarity=88.8,
        )
        url = '/api/fraud-portal/application-scores/?application_id=77777,777772'
        expected_response = {
            'success': True,
            'data': [
                {
                    'application_id': 77777,
                    'application_full_name': 'hadiyan',
                    'shopee_score': True,
                    'application_similarity_score': 99.27,
                    'mycroft_score': 0.9,
                    'credit_score': 'C',
                    'active_liveness_score': 1.0,
                    'passive_liveness_score': 1.0,
                    'heimdall_score': 0.6,
                    'orion_score': 0.5,
                },
                {
                    'application_id': 777772,
                    'application_full_name': 'calvin',
                    'shopee_score': True,
                    'application_similarity_score': 88.8,
                    'mycroft_score': 1.2,
                    'credit_score': 'B-',
                    'active_liveness_score': 1.0,
                    'passive_liveness_score': 1.0,
                    'heimdall_score': 0.6,
                    'orion_score': 0.5,
                },
            ],
            'errors': [],
        }

        # act
        response = self.client.get(url)

        # assert
        self.assertEqual(response.json(), expected_response)
        self.assertEqual(response.status_code, 200)
