import json
from django.test import TestCase, override_settings
from mock import patch
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
    WorkflowFactory,
    ProductLineFactory,
    ExperimentSettingFactory,
    TokoScoreResultFactory,
    CreditMatrixFactory,
    CurrentCreditMatrixFactory,
)
from juloserver.apiv2.tests.factories import AutoDataCheckFactory
from juloserver.julo.constants import (
    WorkflowConst,
    ProductLineCodes,
    ExperimentConst,
)
from juloserver.tokopedia.services.match_criteria_service import process_match_criteria
from juloserver.tokopedia.services.common_service import (
    is_allowed_to_check_by_limit,
    increase_total_of_passed,
    set_path_tag_criteria_to_application,
)
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.ana_api.tests.factories import (
    PdApplicationFraudModelResultFactory,
)
from juloserver.tokopedia.exceptions import (
    TokoScoreException,
    TokoScoreCreditMatrixException,
)
from juloserver.tokopedia.services.common_service import (
    is_passed_tokoscore,
    fetch_credit_matrix_and_move_application,
)
from juloserver.tokopedia.constants import TokoScoreConst
from juloserver.julo.constants import ApplicationStatusCodes
from juloserver.application_flow.constants import JuloOneChangeReason


class TestMatchCriteria(TestCase):
    def setUp(self):

        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, nik=3173051512980141)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            id=1,
            customer=self.customer,
            workflow=self.workflow,
            email='testing@julofinance.com',
            mobile_phone_1='083822825220',
        )
        self.application.update_safely(application_status_id=ApplicationStatusCodes.FORM_PARTIAL)
        self.configuration_criteria = {
            'threshold': 650,
            'require_match': True,
            'require_active': True,
            'limit_total_of_application': 5000,
            'criteria_1': {
                'fdc': 'pass',
                'mycroft': {'bottom_threshold': 0.8},
                'heimdall': {'upper_threshold': 0.51, 'bottom_threshold': 0.45},
            },
            'criteria_2': {
                'fdc': 'not_found',
                'mycroft': {'bottom_threshold': 0.8},
                'heimdall': {'upper_threshold': 0.85, 'bottom_threshold': 0.75},
            },
            'criteria_3': {
                'fdc': 'pass',
                'mycroft': {'upper_threshold': 0.8, 'bottom_threshold': 0.7},
                'heimdall': {'upper_threshold': 1, 'bottom_threshold': 0.51},
            },
        }
        self.configuration = ExperimentSettingFactory(
            code=ExperimentConst.TOKO_SCORE_EXPERIMENT,
            is_active=True,
            is_permanent=False,
            criteria=self.configuration_criteria,
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=30),
        )
        self.auto_data_check_fdc = AutoDataCheckFactory(
            application_id=self.application.id, is_okay=True, data_to_check='fdc_inquiry_check'
        )
        self.heimdall = PdCreditModelResultFactory(
            application_id=self.application.id,
            pgood=0.8,
            has_fdc=True,
        )
        self.mycroft_data = PdApplicationFraudModelResultFactory(
            application_id=self.application.id,
            pgood=0.9,
        )
        self.toko_score_result = TokoScoreResultFactory(
            application_id=self.application.id,
            request_score_id=TokoScoreConst.SCORE_ID,
            score_type=TokoScoreConst.REVIVE_SCORE_TYPE,
            score='800.000000',
            request_message_id='20231211.17022861059571357',
            is_match=True,
            is_active=True,
            request_status='success',
        )
        self.credit_matrix = CreditMatrixFactory(
            min_threshold=0.45,
            max_threshold=0.51,
            score='B--',
            credit_matrix_type="julo1",
            is_premium_area=False,
            is_salaried=False,
            version=152,
            score_tag='B-- : 0.45 - 0.51',
            parameter='feature:shopee_whitelist',
            transaction_type='self',
        )
        self.current_credit_matrix = CurrentCreditMatrixFactory(credit_matrix=self.credit_matrix)

        self.credit_matrix_c = CreditMatrixFactory(
            min_threshold=0,
            max_threshold=0.7,
            score='C',
            credit_matrix_type="julo1",
            is_premium_area=False,
            is_salaried=False,
            version=19,
            score_tag='c_low_credit_score',
            parameter=None,
            transaction_type='self',
        )
        self.current_credit_matrix_c = CurrentCreditMatrixFactory(
            credit_matrix=self.credit_matrix_c
        )

    def test_not_match_criteria(self):

        with self.assertRaises(TokoScoreException):
            _ = process_match_criteria(
                application_id=self.application.id,
                configuration=self.configuration,
            )

    def test_have_match_criteria_with_criteria_1(self):
        """
        Match criteria 1
        """
        self.heimdall.pgood = 0.46
        self.heimdall.save()

        self.mycroft_data.update_safely(pgood=0.8)
        result = process_match_criteria(
            application_id=self.application.id,
            configuration=self.configuration,
        )
        self.assertEqual(result, 'criteria_1')

    def test_have_match_criteria_with_criteria_1_overwrite(self):
        """
        Match criteria 1
        """
        self.heimdall.pgood = 0.46
        self.heimdall.save()

        self.mycroft_data.update_safely(pgood=0.8)
        with self.assertRaises(TokoScoreException):
            _ = process_match_criteria(
                application_id=self.application.id,
                configuration=self.configuration,
                is_available_fdc_check=False,
            )

        # is fdc_check is None will get data from auto_data_check
        result = process_match_criteria(
            application_id=self.application.id,
            configuration=self.configuration,
            is_available_fdc_check=None,
        )
        self.assertEqual(result, 'criteria_1')

        # if fdc_check is back to True
        result = process_match_criteria(
            application_id=self.application.id,
            configuration=self.configuration,
            is_available_fdc_check=True,
        )
        self.assertEqual(result, 'criteria_1')

    def test_have_match_criteria_with_criteria_2(self):
        """
        Match criteria 2
        """
        self.heimdall.pgood = 0.76
        self.heimdall.has_fdc = False
        self.heimdall.save()
        self.mycroft_data.update_safely(pgood=0.8)
        result = process_match_criteria(
            application_id=self.application.id,
            configuration=self.configuration,
        )
        self.assertEqual(result, 'criteria_2')

    def test_have_match_criteria_with_criteria_3(self):
        """
        Match criteria 3
        """
        self.heimdall.pgood = 0.51
        self.heimdall.save()
        self.mycroft_data.update_safely(pgood=0.7)
        result = process_match_criteria(
            application_id=self.application.id,
            configuration=self.configuration,
        )
        self.assertEqual(result, 'criteria_3')

    def test_is_allowed_for_checking(self):

        # increase the limit
        current_total = increase_total_of_passed(self.application)

        is_allowed_to_check = is_allowed_to_check_by_limit(
            self.application.id,
        )
        self.assertTrue(is_allowed_to_check)
        self.configuration.refresh_from_db()
        action = json.loads(self.configuration.action)
        self.assertEqual(action.get(TokoScoreConst.KEY_TOTAL_OF_PASSED), 1)
        self.assertEqual(current_total, 1)

    @patch('juloserver.tokopedia.services.common_service.is_have_tokopedia_apps', return_value=True)
    @patch('django.utils.timezone.now')
    def test_is_passed_toko_score_with_even_app(
        self,
        mock_datetime,
        mock_is_have_tokopedia_app,
    ):

        mock_datetime.return_value = datetime.now() + timedelta(days=2)
        # update to odd id
        self.application.id = 2
        self.application.save()
        result = is_passed_tokoscore(self.application)
        self.assertFalse(result)

    @patch('juloserver.tokopedia.services.common_service.is_have_tokopedia_apps', return_value=True)
    @patch('django.utils.timezone.now')
    def test_is_passed_toko_score_with_expired_experiment(
        self,
        mock_datetime,
        mock_is_have_tokopedia_app,
    ):

        mock_datetime.return_value = datetime.now() + timedelta(days=31)
        result = is_passed_tokoscore(self.application)
        self.assertFalse(result)

    @patch('juloserver.tokopedia.services.common_service.is_have_tokopedia_apps', return_value=True)
    @patch('juloserver.tokopedia.services.common_service.set_path_tag_status_to_application')
    @patch('juloserver.tokopedia.services.common_service.is_passed_criteria', return_value=True)
    @patch('juloserver.tokopedia.services.common_service.get_score')
    def test_scenario_passed_with_status_success(
        self,
        mock_toko_score_result,
        mocking_criteria,
        mock_set_path_tag,
        mock_is_have_tokopedia_app,
    ):

        mock_toko_score_result.return_value = self.toko_score_result
        result = is_passed_tokoscore(self.application)
        self.assertEqual(result, TokoScoreConst.KEY_PASSED)
        mock_set_path_tag.assert_called_once_with(
            self.application,
            TokoScoreConst.KEY_PASSED,
        )

    @patch('juloserver.tokopedia.services.common_service.is_have_tokopedia_apps', return_value=True)
    @patch('juloserver.tokopedia.services.common_service.set_path_tag_status_to_application')
    @patch('juloserver.tokopedia.services.common_service.is_passed_criteria', return_value=True)
    @patch('juloserver.tokopedia.services.common_service.get_score')
    def test_scenario_passed_with_status_failed(
        self,
        mock_toko_score_result,
        mocking_criteria,
        mock_set_path_tag,
        mock_is_have_tokopedia_app,
    ):
        # update to below threshold
        self.toko_score_result.update_safely(score='300.000000')

        mock_toko_score_result.return_value = self.toko_score_result
        result = is_passed_tokoscore(self.application)
        self.assertEqual(result, TokoScoreConst.KEY_NOT_PASSED)
        mock_set_path_tag.assert_called_once_with(
            self.application,
            TokoScoreConst.KEY_NOT_PASSED,
        )

    @patch('juloserver.tokopedia.services.credit_matrix_service.fetch_credit_matrix_with_parameter')
    @patch(
        'juloserver.tokopedia.services.credit_matrix_service.is_inside_premium_area',
        return_value=False,
    )
    @patch('juloserver.tokopedia.services.credit_matrix_service.get_salaried', return_value=False)
    @patch('juloserver.tokopedia.services.common_service.process_application_status_change')
    def test_scenario_passed_when_get_credit_matrix(
        self,
        mock_change_status,
        mock_salaried,
        mock_inside_premium_area,
        mock_fetch_credit_matrix,
    ):

        # set criteria 1
        self.heimdall.pgood = 0.47
        self.heimdall.save()
        self.mycroft_data.update_safely(pgood=0.8)

        mock_fetch_credit_matrix.return_value = self.credit_matrix
        credit_matrix = fetch_credit_matrix_and_move_application(
            application=self.application,
            key_for_passed=TokoScoreConst.KEY_PASSED,
            move_status=True,
            origin_credit_matrix=self.credit_matrix_c,
        )
        self.assertEqual(self.credit_matrix.score, credit_matrix.score)
        mock_change_status.assert_called_once_with(
            application_id=self.application.id,
            new_status_code=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            change_reason=JuloOneChangeReason.REVIVE_BY_TOKOSCORE,
        )

    @patch('juloserver.tokopedia.services.credit_matrix_service.fetch_credit_matrix_with_parameter')
    @patch(
        'juloserver.tokopedia.services.credit_matrix_service.is_inside_premium_area',
        return_value=False,
    )
    @patch('juloserver.tokopedia.services.credit_matrix_service.get_salaried', return_value=False)
    @patch('juloserver.tokopedia.services.common_service.process_application_status_change')
    def test_scenario_passed_but_move_status_false(
        self,
        mock_change_status,
        mock_salaried,
        mock_inside_premium_area,
        mock_fetch_credit_matrix,
    ):
        # set criteria 1
        self.heimdall.pgood = 0.47
        self.heimdall.save()
        self.mycroft_data.update_safely(pgood=0.8)

        mock_fetch_credit_matrix.return_value = self.credit_matrix
        credit_matrix = fetch_credit_matrix_and_move_application(
            application=self.application,
            key_for_passed=TokoScoreConst.KEY_PASSED,
            move_status=False,
            origin_credit_matrix=self.credit_matrix_c,
        )
        self.assertEqual(self.credit_matrix.score, credit_matrix.score)
        mock_change_status.assert_not_called()

        credit_matrix = fetch_credit_matrix_and_move_application(
            application=self.application,
            key_for_passed=TokoScoreConst.KEY_NOT_PASSED,
            move_status=False,
            origin_credit_matrix=self.credit_matrix_c,
        )
        self.assertIsNone(credit_matrix)
        mock_change_status.assert_not_called()

    @patch('juloserver.tokopedia.services.credit_matrix_service.fetch_heimdall_score')
    @patch('juloserver.tokopedia.services.credit_matrix_service.build_credit_matrix_parameters')
    @patch('juloserver.tokopedia.services.credit_matrix_service.get_credit_matrix')
    @patch(
        'juloserver.tokopedia.services.credit_matrix_service.is_inside_premium_area',
        return_value=False,
    )
    @patch('juloserver.tokopedia.services.credit_matrix_service.get_salaried', return_value=False)
    @patch('juloserver.tokopedia.services.common_service.process_application_status_change')
    def test_scenario_not_match_credit_matrix(
        self,
        mock_change_status,
        mock_salaried,
        mock_inside_premium_area,
        mock_data_credit_limit,
        mock_build_credit_matrix_param,
        mock_heimdall_score,
    ):
        self.credit_matrix.update_safely(
            parameter=None,
        )
        mock_data_credit_limit.return_value = None

        credit_matrix = fetch_credit_matrix_and_move_application(
            application=self.application,
            key_for_passed=TokoScoreConst.KEY_PASSED,
            move_status=True,
            origin_credit_matrix=self.credit_matrix_c,
        )
        mock_change_status.assert_not_called()
        self.assertEqual(credit_matrix.score, self.credit_matrix_c.score)

    def test_criteria_for_path_tag(self):

        tag_name = set_path_tag_criteria_to_application(
            application=self.application, criteria_passed='criteria_1'
        )
        self.assertEqual(tag_name, 'is_fail_heimdall_whitelisted_rescored')

        tag_name = set_path_tag_criteria_to_application(
            application=self.application, criteria_passed='criteria_2'
        )
        self.assertEqual(tag_name, 'is_no_fdc_whitelisted_rescored')

        tag_name = set_path_tag_criteria_to_application(
            application=self.application, criteria_passed='criteria_3'
        )
        self.assertEqual(tag_name, 'is_fail_mycroft_whitelisted_rescored')

        # invalid case will raise to sentry failure to set path tag
        with self.assertRaises(TokoScoreException):
            _ = set_path_tag_criteria_to_application(
                application=self.application, criteria_passed='criteria_4'
            )

        tag_name = set_path_tag_criteria_to_application(
            application=self.application, criteria_passed=None
        )
        self.assertFalse(tag_name)
