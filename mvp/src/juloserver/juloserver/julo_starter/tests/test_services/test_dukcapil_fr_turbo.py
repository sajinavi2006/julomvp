from django.contrib.auth.models import Group
from mock import patch
from rest_framework.test import APITestCase

from juloserver.account.constants import AccountConstant
from juloserver.face_recognition.constants import FaceMatchingCheckConst
from juloserver.face_recognition.factories import (
    FaceImageResultFactory,
    FaceSearchProcessFactory,
    FaceSearchResultFactory,
    FraudFaceSearchProcessFactory,
    FraudFaceSearchResultFactory,
    FaceMatchingCheckFactory,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
    FeatureSettingFactory,
)
from juloserver.julo_starter.services.services import (
    check_face_similarity_jturbo,
    check_fraud_face_similarity_jturbo,
    check_selfie_x_ktp_similarity_jturbo,
    check_selfie_x_liveness_similarity_jturbo,
    verify_face_checks_and_update_status_jturbo,
    check_face_similarity_result_with_x121_jturbo_threshold,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles


class TestFaceSimilarityResultx121(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(
            id=77777,
            fullname='hadiyan',
            birth_place="Palembang",
            marital_status="Jomblo",
            address_street_num="kalideres no 3",
            name_in_bank="haidyan",
            customer=self.customer,
            gender="Pria",
            monthly_income=2800000,
            last_month_salary='2011-12-09',
            employment_status='full time',
        )
        self.face_image_result = FaceImageResultFactory(application=self.application)
        self.face_search_process = FaceSearchProcessFactory(application=self.application)
        self.face_search_result = FaceSearchResultFactory(
            searched_face_image_id=self.face_image_result,
            face_search_process=self.face_search_process,
        )

    def test_check_face_similarity_results_with_score_above_threshold(self):
        similarity_threshold = 0.4
        result = check_face_similarity_jturbo(
            self.application,similarity_threshold
        )
        self.assertFalse(result)

    def test_check_face_similarity_results_with_score_below_threshold(self):
        similarity_threshold = 100
        result = check_face_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertTrue(result)

    def test_check_face_similarity_results_with_not_found_process(self):
        self.face_search_process.status = 'not_found'
        self.face_search_process.save()
        similarity_threshold = 0.4
        result = check_face_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertTrue(result)

    def test_check_face_similarity_results_without_face_search_process(self):
        self.face_search_process.delete()
        similarity_threshold = 100
        result = check_face_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertFalse(result)

    def test_check_face_similarity_results_without_face_search_result(self):
        self.face_search_result.delete()
        similarity_threshold = 0.4
        result = check_face_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertFalse(result)


class TestFraudFaceSimilarityResultx121(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(
            id=77777,
            fullname='hadiyan',
            birth_place="Palembang",
            marital_status="Jomblo",
            address_street_num="kalideres no 3",
            name_in_bank="haidyan",
            customer=self.customer,
            gender="Pria",
            monthly_income=2800000,
            last_month_salary='2011-12-09',
            employment_status='full time',
        )
        self.face_image_result = FaceImageResultFactory(application=self.application)
        self.fraud_face_search_process = FraudFaceSearchProcessFactory(
            application=self.application
        )
        self.fraud_face_search_result = FraudFaceSearchResultFactory(
            searched_face_image_id=self.face_image_result,
            face_search_process=self.fraud_face_search_process,
        )

    def test_check_face_fraud_similarity_results_with_score_above_threshold(self):
        similarity_threshold = 0.4
        result = check_fraud_face_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertFalse(result)

    def test_check_fraud_face_similarity_results_with_score_below_threshold(self):
        similarity_threshold = 100
        result = check_fraud_face_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertTrue(result)

    def test_check_face_similarity_results_with_not_found_process(self):
        self.fraud_face_search_process.status = 'not_found'
        self.fraud_face_search_process.save()
        similarity_threshold = 0.4
        result = check_fraud_face_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertTrue(result)

    def test_check_fraud_face_similarity_results_without_face_search_process(self):
        self.fraud_face_search_process.delete()
        similarity_threshold = 100
        result = check_fraud_face_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertFalse(result)

    def test_check_fraud_face_similarity_results_without_face_search_result(self):
        self.fraud_face_search_result.delete()
        similarity_threshold = 0.4
        result = check_face_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertFalse(result)


class TestSelfiexKTPSimilarityResultx121(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(id=77777, fullname='hadiyan')
        self.ktp_face_matching_check = FaceMatchingCheckFactory(
            application=self.application,
            process=FaceMatchingCheckConst.Process.selfie_x_ktp.value,
            metadata={"similarity_score": 80}
        )

    def test_check_selfie_x_ktp_similarity_results_with_score_above_threshold(self):
        similarity_threshold = 60
        result = check_selfie_x_ktp_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertTrue(result)

    def test_check_selfie_x_ktp_similarity_results_with_score_below_threshold(self):
        similarity_threshold = 90
        result = check_selfie_x_ktp_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertFalse(result)

    def test_check_selfie_x_ktp_similarity_results_without_data(self):
        self.ktp_face_matching_check.metadata = {}
        self.ktp_face_matching_check.save()
        similarity_threshold = 60
        result = check_selfie_x_ktp_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertFalse(result)

    def test_check_selfie_x_ktp_similarity_results_without_face_matching_check(self):
        self.ktp_face_matching_check.delete()
        similarity_threshold = 60
        result = check_selfie_x_ktp_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertFalse(result)


class TestSelfiexLivenessSimilarityResultx121(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(id=77777, fullname='hadiyan')
        self.ktp_face_matching_check = FaceMatchingCheckFactory(
            application=self.application,
            process=FaceMatchingCheckConst.Process.selfie_x_liveness.value,
            metadata={"similarity_score": 80}
        )

    def test_check_selfie_x_liveness_similarity_results_with_score_above_threshold(self):
        similarity_threshold = 60
        result = check_selfie_x_liveness_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertTrue(result)

    def test_check_selfie_x_liveness_similarity_results_with_score_below_threshold(self):
        similarity_threshold = 90
        result = check_selfie_x_liveness_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertFalse(result)

    def test_check_selfie_x_liveness_similarity_results_without_data(self):
        self.ktp_face_matching_check.metadata = {}
        self.ktp_face_matching_check.save()
        similarity_threshold = 60
        result = check_selfie_x_liveness_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertFalse(result)

    def test_check_selfie_x_liveness_similarity_results_without_face_matching_check(self):
        self.ktp_face_matching_check.delete()
        similarity_threshold = 60
        result = check_selfie_x_liveness_similarity_jturbo(
            self.application, similarity_threshold
        )
        self.assertFalse(result)


class TestSelfiexLivenessSimilarityResultx121(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(id=77777, fullname='hadiyan')
        self.face_similarity_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.FACE_SIMILARITY_THRESHOLD_JTURBO,
            category='fraud',
            is_active=True,
            parameters={"similar_face_threshold": 70, "fraud_face_threshold":70},
        )
        self.face_matching_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.FACE_MATCHING_SIMILARITY_THRESHOLD_JTURBO,
            category='fraud',
            is_active=True,
            parameters={"selfie_x_ktp_threshold": 70, "selfie_x_liveness_threshold":70},
        )

    @patch('juloserver.julo_starter.services.services.check_face_similarity_jturbo')
    @patch('juloserver.account.services.account_related.process_change_account_status')
    def test_verify_face_checks_face_similarity_false(
        self, mock_process_change_account_status, mock_check_face_similarity_jturbo
    ):
        mock_check_face_similarity_jturbo.return_value = False
        verify_face_checks_and_update_status_jturbo(self.application)

        mock_process_change_account_status.assert_called_once_with(
            self.application.account,
            AccountConstant.STATUS_CODE.inactive,
            change_reason='rejected by face similarity x121 JTurbo',
        )
        mock_process_change_account_status.assert_called_once()

    @patch('juloserver.julo_starter.services.services.check_face_similarity_jturbo')
    @patch('juloserver.julo_starter.services.services.check_fraud_face_similarity_jturbo')
    @patch('juloserver.account.services.account_related.process_change_account_status')
    def test_verify_face_checks_fraud_face_similarity_false(
        self, 
        mock_process_change_account_status,
        mock_check_fraud_face_similarity_jturbo,
        mock_check_face_similarity_jturbo
    ):
        mock_check_face_similarity_jturbo.return_value = True
        mock_check_fraud_face_similarity_jturbo.return_value = False
        verify_face_checks_and_update_status_jturbo(self.application)

        mock_process_change_account_status.assert_called_once_with(
            self.application.account,
            AccountConstant.STATUS_CODE.inactive,
            change_reason='rejected by fraud face similarity x121 JTurbo',
        )
        mock_process_change_account_status.assert_called_once()

    @patch('juloserver.julo_starter.services.services.check_face_similarity_jturbo')
    @patch('juloserver.julo_starter.services.services.check_fraud_face_similarity_jturbo')
    @patch('juloserver.julo_starter.services.services.check_selfie_x_ktp_similarity_jturbo')
    @patch('juloserver.account.services.account_related.process_change_account_status')
    def test_verify_face_checks_selfie_x_ktp_false(
        self, 
        mock_process_change_account_status,
        mock_check_selfie_x_ktp_similarity_jturbo,
        mock_check_fraud_face_similarity_jturbo,
        mock_check_face_similarity_jturbo
    ):
        mock_check_face_similarity_jturbo.return_value = True
        mock_check_fraud_face_similarity_jturbo.return_value = True
        mock_check_selfie_x_ktp_similarity_jturbo.return_value = False
        verify_face_checks_and_update_status_jturbo(self.application)

        mock_process_change_account_status.assert_called_once_with(
            self.application.account,
            AccountConstant.STATUS_CODE.inactive,
            change_reason='rejected by selfie x ktp x121 JTurbo',
        )
        mock_process_change_account_status.assert_called_once()

    @patch('juloserver.julo_starter.services.services.check_face_similarity_jturbo')
    @patch('juloserver.julo_starter.services.services.check_fraud_face_similarity_jturbo')
    @patch('juloserver.julo_starter.services.services.check_selfie_x_ktp_similarity_jturbo')
    @patch('juloserver.julo_starter.services.services.check_selfie_x_liveness_similarity_jturbo')
    @patch('juloserver.account.services.account_related.process_change_account_status')
    def test_verify_face_checks_selfie_x_liveness_false(
        self, 
        mock_process_change_account_status,
        mock_check_selfie_x_liveness_similarity_jturbo,
        mock_check_selfie_x_ktp_similarity_jturbo,
        mock_check_fraud_face_similarity_jturbo,
        mock_check_face_similarity_jturbo
    ):
        mock_check_face_similarity_jturbo.return_value = True
        mock_check_fraud_face_similarity_jturbo.return_value = True
        mock_check_selfie_x_ktp_similarity_jturbo.return_value = True
        mock_check_selfie_x_liveness_similarity_jturbo.return_value = False
        verify_face_checks_and_update_status_jturbo(self.application)

        mock_process_change_account_status.assert_called_once_with(
            self.application.account,
            AccountConstant.STATUS_CODE.inactive,
            change_reason='rejected by selfie x liveness x121 JTurbo',
        )
        mock_process_change_account_status.assert_called_once()

    @patch('juloserver.julo_starter.services.services.check_face_similarity_jturbo')
    @patch('juloserver.julo_starter.services.services.check_fraud_face_similarity_jturbo')
    @patch('juloserver.julo_starter.services.services.check_selfie_x_ktp_similarity_jturbo')
    @patch('juloserver.julo_starter.services.services.check_selfie_x_liveness_similarity_jturbo')
    @patch('juloserver.account.services.account_related.process_change_account_status')
    def test_verify_face_checks_all_true(
        self, 
        mock_process_change_account_status,
        mock_check_selfie_x_liveness_similarity_jturbo,
        mock_check_selfie_x_ktp_similarity_jturbo,
        mock_check_fraud_face_similarity_jturbo,
        mock_check_face_similarity_jturbo
    ):
        mock_check_face_similarity_jturbo.return_value = True
        mock_check_fraud_face_similarity_jturbo.return_value = True
        mock_check_selfie_x_ktp_similarity_jturbo.return_value = True
        mock_check_selfie_x_liveness_similarity_jturbo.return_value = True
        verify_face_checks_and_update_status_jturbo(self.application)

        mock_process_change_account_status.assert_called_once_with(
            self.application.account,
            AccountConstant.STATUS_CODE.active,
            change_reason='accepted by Dukcapil FR High',
        )
        mock_process_change_account_status.assert_called_once()

    @patch('juloserver.julo_starter.services.services.check_face_similarity_jturbo')
    @patch('juloserver.julo_starter.services.services.check_fraud_face_similarity_jturbo')
    @patch('juloserver.julo_starter.services.services.check_selfie_x_ktp_similarity_jturbo')
    @patch('juloserver.julo_starter.services.services.check_selfie_x_liveness_similarity_jturbo')
    @patch('juloserver.account.services.account_related.process_change_account_status')
    def test_verify_face_checks_face_similarity_fs_inactive(
        self, 
        mock_process_change_account_status,
        mock_check_selfie_x_liveness_similarity_jturbo,
        mock_check_selfie_x_ktp_similarity_jturbo,
        mock_check_fraud_face_similarity_jturbo,
        mock_check_face_similarity_jturbo
    ):
        self.face_similarity_fs.is_active = False
        self.face_similarity_fs.save()
        mock_check_face_similarity_jturbo.return_value = True
        mock_check_fraud_face_similarity_jturbo.return_value = True
        mock_check_selfie_x_ktp_similarity_jturbo.return_value = True
        mock_check_selfie_x_liveness_similarity_jturbo.return_value = False
        verify_face_checks_and_update_status_jturbo(self.application)

        mock_process_change_account_status.assert_called_once_with(
            self.application.account,
            AccountConstant.STATUS_CODE.inactive,
            change_reason='rejected by selfie x liveness x121 JTurbo',
        )
        mock_process_change_account_status.assert_called_once()

    @patch('juloserver.julo_starter.services.services.check_face_similarity_jturbo')
    @patch('juloserver.julo_starter.services.services.check_fraud_face_similarity_jturbo')
    @patch('juloserver.julo_starter.services.services.check_selfie_x_ktp_similarity_jturbo')
    @patch('juloserver.julo_starter.services.services.check_selfie_x_liveness_similarity_jturbo')
    @patch('juloserver.account.services.account_related.process_change_account_status')
    def test_verify_face_checks_face_matching_fs_inactive(
        self, 
        mock_process_change_account_status,
        mock_check_selfie_x_liveness_similarity_jturbo,
        mock_check_selfie_x_ktp_similarity_jturbo,
        mock_check_fraud_face_similarity_jturbo,
        mock_check_face_similarity_jturbo
    ):
        self.face_matching_fs.is_active = False
        self.face_matching_fs.save()
        mock_check_face_similarity_jturbo.return_value = False
        mock_check_fraud_face_similarity_jturbo.return_value = True
        mock_check_selfie_x_ktp_similarity_jturbo.return_value = True
        mock_check_selfie_x_liveness_similarity_jturbo.return_value = True
        verify_face_checks_and_update_status_jturbo(self.application)

        mock_process_change_account_status.assert_called_once_with(
            self.application.account,
            AccountConstant.STATUS_CODE.inactive,
            change_reason='rejected by face similarity x121 JTurbo',
        )
        mock_process_change_account_status.assert_called_once()

    @patch('juloserver.account.services.account_related.process_change_account_status')
    def test_verify_face_checks_all_fs_inactive(
        self, 
        mock_process_change_account_status,
    ):
        self.face_similarity_fs.is_active = False
        self.face_similarity_fs.save()
        self.face_matching_fs.is_active = False
        self.face_matching_fs.save()
        verify_face_checks_and_update_status_jturbo(self.application)

        mock_process_change_account_status.assert_called_once_with(
            self.application.account,
            AccountConstant.STATUS_CODE.active,
            change_reason='accepted by Dukcapil FR High',
        )
        mock_process_change_account_status.assert_called_once()


class TestFaceSimilarityResultx121Threshold(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(id=77777, fullname='hadiyan')

    @patch('juloserver.julo_starter.services.services.verify_face_checks_and_update_status_jturbo')
    def test_face_similarity_result_success(
        self,
        mock_verify_face_checks,
    ):
        check_face_similarity_result_with_x121_jturbo_threshold(self.application)
        mock_verify_face_checks.assert_called_once_with(self.application)

    @patch('juloserver.julo_starter.services.services.verify_face_checks_and_update_status_jturbo')
    @patch('juloserver.account.services.account_related.process_change_account_status')
    def test_face_similarity_result_with_exception(
        self,
        mock_process_change_account_status,
        mock_verify_face_checks,
    ):
        mock_verify_face_checks.side_effect = Exception('test')
        check_face_similarity_result_with_x121_jturbo_threshold(self.application)

        mock_process_change_account_status.assert_called_once_with(
            self.application.account,
            AccountConstant.STATUS_CODE.active,
            change_reason='accepted by Dukcapil FR High',
        )
