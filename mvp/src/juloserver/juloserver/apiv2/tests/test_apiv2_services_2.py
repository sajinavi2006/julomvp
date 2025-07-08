from __future__ import print_function

from builtins import str
from datetime import date, datetime
from datetime import timedelta

from django.db.utils import IntegrityError
from django.test.testcases import TestCase, override_settings
from django.utils import timezone
from geopy.exc import GeopyError
from mock import patch
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from juloserver.apiv2.services import (
    add_facebook_data,
    can_reapply_validation,
    check_application,
    check_eligible_mtl_extenstion,
    check_fraud_model_exp,
    check_iti_repeat,
    check_payslip_mandatory,
    checking_fraud_email_and_ktp,
    create_bank_validation_card,
    create_facebook_data_history,
    determine_product_line_v2,
    false_reject_min_exp,
    generate_address_from_geolocation,
    get_credit_score1,
    get_credit_score3,
    get_customer_app_actions,
    get_customer_category,
    get_eta_time_for_c_score_delay,
    get_experimental_probability_fpd,
    get_last_application,
    get_latest_app_version,
    get_product_lines,
    get_product_selections,
    get_referral_home_content,
    is_c_score_in_delay_period,
    is_customer_has_good_payment_histories,
    is_customer_paid_on_time,
    is_inside_premium_area,
    ready_to_score,
    remove_fdc_binary_check_that_is_not_in_fdc_threshold,
    store_credit_score_to_db,
    store_device_geolocation,
    switch_to_product_default_workflow,
    update_facebook_data,
    update_response_false_rejection,
    update_response_fraud_experiment,
    check_binary_result,
    override_score_for_failed_dynamic_check,
)
from juloserver.apiv2.tests.factories import (
    AutoDataCheckFactory,
    EtlJobFactory,
    PdCreditModelResultFactory,
    PdFraudModelResultFactory,
    PdIncomeTrustModelResultFactory,
    PdWebModelResultFactory,
)
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.julo.models import (
    ApplicationWorkflowSwitchHistory,
    CustomerFieldChange,
)
from juloserver.julo.tests.factories import (
    AddressGeolocationFactory,
    ApplicationExperimentFactory,
    ApplicationFactory,
    ApplicationHistoryFactory,
    AppVersionFactory,
    AuthUserFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CreditScoreFactory,
    CustomerAppActionFactory,
    CustomerFactory,
    DeviceFactory,
    ExperimentActionFactory,
    ExperimentFactory,
    FacebookDataFactory,
    FDCInquiryCheckFactory,
    FDCInquiryFactory,
    FDCInquiryLoanFactory,
    FeatureSettingFactory,
    FraudModelExperimentFactory,
    ITIConfigurationFactory,
    LoanFactory,
    MantriFactory,
    PartnerFactory,
    PaymentFactory,
    ProductCustomerCriteriaFactory,
    ProductLineFactory,
    WorkflowFactory,
)
from juloserver.loan_refinancing.tests.factories import LoanRefinancingRequestFactory
from juloserver.portal.object.product_profile.tests.test_product_profile_services import (
    ProductProfileFactory,
)


class TestDetermineProductLineV2(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.loan = LoanFactory()
        self.product_line = ProductLineFactory()

    def test_determine_product_line_v2_case_1(self):
        self.product_line.product_line_code = 20
        self.product_line.max_duration = 1
        self.product_line.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 123
        self.loan.save()

        result = determine_product_line_v2(self.customer, 30, 1)
        assert result == 30

    def test_determine_product_line_v2_case_2(self):
        self.product_line.product_line_code = 20
        self.product_line.max_duration = 1
        self.product_line.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 123
        self.loan.save()

        result = determine_product_line_v2(self.customer, 40, 1)
        assert result == 40

    def test_determine_product_line_v2_case_3(self):
        self.product_line.product_line_code = 20
        self.product_line.max_duration = 1
        self.product_line.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 123
        self.loan.save()

        result = determine_product_line_v2(self.customer, 52, 1)
        assert result == 52

    def test_determine_product_line_v2_case_4(self):
        self.product_line.product_line_code = 20
        self.product_line.max_duration = 1
        self.product_line.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 123
        self.loan.save()

        result = determine_product_line_v2(self.customer, 60, 1)
        assert result == 60

    def test_determine_product_line_v2_case_5(self):
        self.product_line.product_line_code = 20
        self.product_line.max_duration = 1
        self.product_line.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 123
        self.loan.save()

        result = determine_product_line_v2(self.customer, 70, 1)
        assert result == 70

    def test_determine_product_line_v2_case_6(self):
        self.product_line.product_line_code = 20
        self.product_line.max_duration = 1
        self.product_line.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 123
        self.loan.save()

        result = determine_product_line_v2(self.customer, 123, 1)
        assert result == 20

    def test_determine_product_line_v2_case_7(self):
        self.product_line.product_line_code = 20
        self.product_line.max_duration = 1
        self.product_line.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 123
        self.loan.save()

        result = determine_product_line_v2(self.customer, 123, 123)
        assert result == 10

    def test_determine_product_line_v2_case_8(self):
        self.product_line.product_line_code = 20
        self.product_line.max_duration = 1
        self.product_line.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.save()

        result = determine_product_line_v2(self.customer, 31, 1)
        assert result == 31

    def test_determine_product_line_v2_case_9(self):
        self.product_line.product_line_code = 20
        self.product_line.max_duration = 1
        self.product_line.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.save()

        result = determine_product_line_v2(self.customer, 41, 1)
        assert result == 41

    def test_determine_product_line_v2_case_10(self):
        self.product_line.product_line_code = 20
        self.product_line.max_duration = 1
        self.product_line.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.save()

        result = determine_product_line_v2(self.customer, 51, 1)
        assert result == 51

    def test_determine_product_line_v2_case_11(self):
        self.product_line.product_line_code = 20
        self.product_line.max_duration = 1
        self.product_line.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.save()

        result = determine_product_line_v2(self.customer, 60, 1)
        assert result == 60

    def test_determine_product_line_v2_case_12(self):
        self.product_line.product_line_code = 20
        self.product_line.max_duration = 1
        self.product_line.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.save()

        result = determine_product_line_v2(self.customer, 71, 1)
        assert result == 71

    def test_determine_product_line_v2_case_13(self):
        self.product_line.product_line_code = 20
        self.product_line.max_duration = 1
        self.product_line.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.save()

        result = determine_product_line_v2(self.customer, 123, 1)
        assert result == 21

    def test_determine_product_line_v2_case_14(self):
        self.product_line.product_line_code = 20
        self.product_line.max_duration = 1
        self.product_line.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.save()

        result = determine_product_line_v2(self.customer, 123, 123)
        assert result == 11


class TestReadyToScore(TestCase):
    def setUp(self):
        self.product_line = ProductLineFactory()
        self.application = ApplicationFactory()
        self.etljob1 = EtlJobFactory(id=123)
        self.etljob2 = EtlJobFactory(id=321)

    def test_ReadyToScore_case_1(self):
        self.etljob1.application_id = self.application.id
        self.etljob1.data_type = 'test123'
        self.etljob1.status = 'done'
        self.etljob1.save()

        result = ready_to_score(self.application.id)
        assert result == False

    def test_ReadyToScore_case_2(self):
        self.etljob1.application_id = self.application.id
        self.etljob1.data_type = 'dsd'
        self.etljob1.status = 'done'
        self.etljob1.save()

        result = ready_to_score(self.application.id)
        assert result == False

    def test_ReadyToScore_case_3(self):
        self.etljob1.application_id = self.application.id
        self.etljob1.data_type = 'dsd'
        self.etljob1.status = 'done'
        self.etljob1.save()

        self.etljob2.application_id = self.application.id
        self.etljob2.data_type = 'gmail'
        self.etljob2.status = 'done'
        self.etljob2.save()

        self.application.application_status_id = 100
        self.application.save()

        result = ready_to_score(self.application.id)
        assert result == False

    def test_ReadyToScore_case_4(self):
        self.etljob1.application_id = self.application.id
        self.etljob1.data_type = 'dsd'
        self.etljob1.status = 'done'
        self.etljob1.save()

        self.etljob2.application_id = self.application.id
        self.etljob2.data_type = 'gmail'
        self.etljob2.status = 'done'
        self.etljob2.save()

        self.application.application_status_id = 107
        self.application.save()

        result = ready_to_score(self.application.id)
        assert result == True


class TestGetCreditScore1(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.credit_score = CreditScoreFactory()
        self.partner = PartnerFactory()
        self.mantri = MantriFactory()

    def test_get_credit_score1_case_1(self):
        self.application.id = 1
        self.application.save()
        self.credit_score.application = self.application
        self.credit_score.save()

        result = get_credit_score1(self.application.id)
        assert str(result) == '1 - C'

    @patch('requests.get')
    @patch('juloserver.apiv2.services.ready_to_score')
    def test_get_credit_score1_case_2(self, mock_ready_to_score, mock_request):
        mock_ready_to_score.return_value = True
        mock_request.return_value.status_code = 123

        result = get_credit_score1(123)
        mock_request.assert_called_with(
            'http://localhost:8001/api/decision/v1/credit-score/123/',
            headers={'Authorization': 'Token password'},
        )
        assert result is None

    @patch('requests.get')
    @patch('juloserver.apiv2.services.ready_to_score')
    def test_get_credit_score1_case_3(self, mock_ready_to_score, mock_request):
        self.partner.name = 'grab'
        self.partner.save()

        self.application.id = 123
        self.application.partner = self.partner
        self.application.save()

        mock_ready_to_score.return_value = True
        mock_response_score_result = {
            'credit-score': 'C',
            'binary-rules': [
                {'failed_check': 'application_date_of_birth', 'error_message': 'error_test'}
            ],
        }
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = mock_response_score_result

        result = get_credit_score1(self.application.id)
        mock_request.assert_called_with(
            'http://localhost:8001/api/decision/v1/credit-score/123/',
            headers={'Authorization': 'Token password'},
        )
        assert str(result) == '123 - C'

    @patch('requests.get')
    @patch('juloserver.apiv2.services.ready_to_score')
    def test_get_credit_score1_case_4(self, mock_ready_to_score, mock_request):
        self.application.id = 123
        self.application.mantri = self.mantri
        self.application.save()
        mock_ready_to_score.return_value = True
        mock_request.return_value.status_code = 123
        mock_response_score_result = {'credit-score': 'B+', 'binary-rules': False}
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = mock_response_score_result

        result = get_credit_score1(123)
        mock_request.assert_called_with(
            'http://localhost:8001/api/decision/v1/credit-score/123/',
            headers={'Authorization': 'Token password'},
        )
        assert str(result) == '123 - B+'

    @patch('requests.get')
    @patch('juloserver.apiv2.services.ready_to_score')
    def test_get_credit_score1_case_5(self, mock_ready_to_score, mock_request):
        self.partner.name = 'grab'
        self.partner.save()

        self.application.id = 123
        self.application.partner = self.partner
        self.application.mantri = None
        self.application.save()
        mock_ready_to_score.return_value = True
        mock_request.return_value.status_code = 123
        mock_response_score_result = {'credit-score': 'B-', 'binary-rules': False}
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = mock_response_score_result

        result = get_credit_score1(123)
        mock_request.assert_called_with(
            'http://localhost:8001/api/decision/v1/credit-score/123/',
            headers={'Authorization': 'Token password'},
        )
        assert str(result) == '123 - B-'

    @patch('requests.get')
    @patch('juloserver.apiv2.services.ready_to_score')
    def test_get_credit_score1_case_6(self, mock_ready_to_score, mock_request):
        self.application.id = 123
        self.application.mantri = None
        self.application.save()
        mock_ready_to_score.return_value = True
        mock_request.return_value.status_code = 123
        mock_response_score_result = {'credit-score': 'B+', 'binary-rules': False}
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = mock_response_score_result

        result = get_credit_score1(123)
        mock_request.assert_called_with(
            'http://localhost:8001/api/decision/v1/credit-score/123/',
            headers={'Authorization': 'Token password'},
        )
        assert str(result) == '123 - B+'


class TestGetExperimentalProbabilityFpd(TestCase):
    def setUp(self):
        self.experiment = ExperimentFactory(id=123)
        self.experiment_action = ExperimentActionFactory(experiment=self.experiment)

    def test_TestGetExperimentalProbabilityFpd_case_1(self):
        self.experiment_action.type = 'CHANGE_CREDIT'
        self.experiment_action.experiment = self.experiment
        self.experiment_action.value = 1
        self.experiment_action.save()

        self.experiment.experimentaction_set = [self.experiment_action]
        self.experiment.save()

        result = get_experimental_probability_fpd(self.experiment)
        assert result == 1

    def test_TestGetExperimentalProbabilityFpd_case_2(self):
        self.experiment_action.type = 'CHANGE_CREDIT'
        self.experiment_action.experiment = self.experiment
        self.experiment_action.save()

        self.experiment.experimentaction_set = [self.experiment_action]
        self.experiment.save()

        result = get_experimental_probability_fpd(self.experiment)
        assert result == 0


class TestGetEtaTimeForCScoreDelay(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.application_history = ApplicationHistoryFactory()
        self.feature_setting = FeatureSettingFactory()

    @patch('juloserver.apiv2.services.timezone')
    def test_TestGetEtaTimeForCScoreDelay_case_1(self, mock_timezone):
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2020, month=12, day=1, hour=23, minute=59, second=59, microsecond=0, tzinfo=None
        )
        mock_timezone.localtime.return_value = mock_now
        result = get_eta_time_for_c_score_delay(self.application)
        assert str(result) == '2020-12-01 23:59:59'

    @patch('juloserver.apiv2.services.timezone')
    def test_TestGetEtaTimeForCScoreDelay_case_2(self, mock_timezone):
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2020, month=12, day=1, hour=23, minute=59, second=59, microsecond=0, tzinfo=None
        )
        mock_timezone.localtime.return_value = mock_now
        self.application_history.application = self.application
        self.application_history.status_new = 105
        self.application_history.save()

        result = get_eta_time_for_c_score_delay(self.application)
        assert str(result) == '2020-12-01 23:59:59'

    @patch('juloserver.apiv2.services.timezone')
    def test_TestGetEtaTimeForCScoreDelay_case_3(self, mock_timezone):
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2020, month=12, day=1, hour=23, minute=59, second=59, microsecond=0, tzinfo=None
        )
        mock_timezone.localtime.return_value = mock_now
        self.application_history.application = self.application
        self.application_history.status_new = 105
        self.application_history.save()

        self.feature_setting.feature_name = 'delay_scoring_and_notifications_for_C'
        self.feature_setting.is_active = True
        self.feature_setting.parameters = {'hours': '01:59', 'exact_time': True}
        self.feature_setting.save()

        result = get_eta_time_for_c_score_delay(self.application)
        assert str(result) == '2020-12-02 01:59:59'

    @patch('juloserver.apiv2.services.timezone')
    def test_TestGetEtaTimeForCScoreDelay_case_4(self, mock_timezone):
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2020, month=12, day=1, hour=23, minute=59, second=59, microsecond=0, tzinfo=None
        )
        mock_timezone.localtime.return_value = mock_now
        self.application_history.application = self.application
        self.application_history.status_new = 105
        self.application_history.save()

        self.feature_setting.feature_name = 'delay_scoring_and_notifications_for_C'
        self.feature_setting.is_active = True
        self.feature_setting.parameters = {'hours': '01:59', 'exact_time': False}
        self.feature_setting.save()

        result = get_eta_time_for_c_score_delay(self.application)
        assert str(result) == '2020-12-02 01:58:59'


class TestIsCScoreInDelayPeriod(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.credit_score = CreditScoreFactory()

    def test_TestIsCScoreInDelayPeriod_case_1(self):
        result = is_c_score_in_delay_period(self.application)
        assert result == False

    def test_TestIsCScoreInDelayPeriod_case_2(self):
        self.credit_score.score = 'b'
        self.credit_score.application = self.application
        self.credit_score.save()
        result = is_c_score_in_delay_period(self.application)
        assert result == False

    @patch('juloserver.apiv2.services.timezone')
    @patch('juloserver.apiv2.services.get_eta_time_for_c_score_delay')
    def test_TestIsCScoreInDelayPeriod_case_3(self, mock_get_time, mock_timezone):
        self.credit_score.score = 'c'
        self.credit_score.application = self.application
        self.credit_score.save()
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2020, month=12, day=1, hour=23, minute=59, second=59, microsecond=0, tzinfo=None
        )
        mock_timezone.localtime.return_value = mock_now

        mock_end_off_delay = timezone.localtime(timezone.now())
        mock_end_off_delay = mock_end_off_delay.replace(
            year=2020, month=12, day=30, hour=23, minute=59, second=59, microsecond=0, tzinfo=None
        )
        mock_get_time.return_value = mock_end_off_delay
        result = is_c_score_in_delay_period(self.application)
        assert result == True


class TestGetCreditScore3(TestCase):
    def setUp(self):
        self.application = ApplicationFactory(id=123321)
        self.credit_score = CreditScoreFactory()
        self.customer = CustomerFactory()
        self.loan = LoanFactory()
        self.pd_credit_model_result = PdCreditModelResultFactory()
        self.pd_web_model_result = PdWebModelResultFactory()
        self.experiment = ExperimentFactory(id=123, code=123)
        self.experiment1 = ExperimentFactory(id=124, code=124)
        self.feature_setting = FeatureSettingFactory(id=123)
        self.feature_setting1 = FeatureSettingFactory(id=124)
        self.feature_setting2 = FeatureSettingFactory(id=125)
        self.pd_fraud_model_result = PdFraudModelResultFactory()

    def test_TestGetCreditScore3_case_1(self):
        self.application.customer = self.customer
        self.application.partner = None
        self.application.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 123
        self.loan.save()

        result = get_credit_score3(self.application)
        assert result is None

    @patch('juloserver.apiv2.services.is_c_score_in_delay_period')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_TestGetCreditScore3_case_2(self, mock_check_app_cs_v20b, mock_c_score_in_delay):
        self.application.customer = self.customer
        self.application.partner = None
        self.application.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.application = self.application
        self.loan.save()

        mock_check_app_cs_v20b.return_value = True

        self.pd_web_model_result.application_id = self.application.id
        self.pd_web_model_result.save()

        self.credit_score.application_id = self.application.id
        self.credit_score.score = 'C'
        self.credit_score.save()

        mock_c_score_in_delay.return_value = False

        result = get_credit_score3(self.application, True)
        assert str(result) == '123321 - C'

    @patch('juloserver.apiv2.services.is_c_score_in_delay_period')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_TestGetCreditScore3_case_3(self, mock_check_app_cs_v20b, mock_c_score_in_delay):
        self.application.customer = self.customer
        self.application.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.save()

        mock_check_app_cs_v20b.return_value = True

        self.pd_web_model_result.application_id = self.application.id
        self.pd_web_model_result.save()

        self.credit_score.application_id = self.application.id
        self.credit_score.score = 'C'
        self.credit_score.save()

        mock_c_score_in_delay.return_value = True

        result = get_credit_score3(self.application, True, False)
        assert result is None

    @patch('juloserver.apiv2.services.post_anaserver')
    @patch('juloserver.apiv2.services.get_good_score')
    @patch('juloserver.apiv2.services.is_inside_premium_area')
    @patch('juloserver.apiv2.services.remove_fdc_binary_check_that_is_not_in_fdc_threshold')
    @patch('juloserver.apiv2.services.is_customer_has_good_payment_histories')
    @patch('juloserver.apiv2.services.timezone')
    @patch('juloserver.apiv2.services.is_c_score_in_delay_period')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_TestGetCreditScore3_case_4(
        self,
        mock_check_app_cs_v20b,
        mock_c_score_in_delay,
        mock_timezone,
        mock_customer_has_good_payment_histories,
        mock_remove_fdc_binary_check,
        mock_is_inside_premium_area,
        mock_get_good_score,
        mock_post_anaserver,
    ):
        mock_is_inside_premium_area.return_value = True
        self.application.customer = self.customer
        self.application.email = 'test@gmail.com'
        self.application.job_industry = ['test']
        self.application.partner = None
        self.application.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.save()

        mock_check_app_cs_v20b.return_value = True

        self.pd_web_model_result.application_id = self.application.id
        self.pd_web_model_result.save()

        mock_c_score_in_delay.return_value = True

        mock_now = timezone.now().date()
        mock_now = mock_now.replace(year=2020, month=12, day=1)

        self.experiment.is_active = True
        self.experiment.date_start = mock_now
        self.experiment.date_end = mock_now
        self.experiment.code = 'Is_Own_Phone_Experiment'
        self.experiment.save()

        self.feature_setting.feature_name = 'force_high_creditscore'
        self.feature_setting.is_active = True
        self.feature_setting.parameters = {'test@gmail.com': ''}
        self.feature_setting.save()

        mock_timezone.now.return_value.date.return_value = mock_now
        mock_timezone.localtime.return_value.date.return_value = mock_now

        mock_customer_has_good_payment_histories.return_value = True
        mock_remove_fdc_binary_check.return_value = ('basic_savings', 'basic_savings')
        mock_get_good_score.return_value = ('A-', [123], 'test123', 'test123', True, None)
        mock_post_anaserver.return_value = True
        result = get_credit_score3(self.application, False, True)
        assert str(result) == '123321 - A-'

    @patch('juloserver.apiv2.services.post_anaserver')
    @patch('juloserver.apiv2.services.is_inside_premium_area')
    @patch('juloserver.apiv2.services.remove_fdc_binary_check_that_is_not_in_fdc_threshold')
    @patch('juloserver.apiv2.services.is_customer_has_good_payment_histories')
    @patch('juloserver.apiv2.services.timezone')
    @patch('juloserver.apiv2.services.is_c_score_in_delay_period')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_TestGetCreditScore3_case_5(
        self,
        mock_check_app_cs_v20b,
        mock_c_score_in_delay,
        mock_timezone,
        mock_customer_has_good_payment_histories,
        mock_remove_fdc_binary_check,
        mock_is_inside_premium_area,
        mock_post_anaserver,
    ):
        self.application.customer = self.customer
        self.application.email = 'test@gmail.com'
        self.application.job_industry = ['test']
        self.application.partner = None
        self.application.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.save()

        mock_check_app_cs_v20b.return_value = True

        self.pd_web_model_result.application_id = self.application.id
        self.pd_web_model_result.save()

        mock_c_score_in_delay.return_value = True

        mock_now = timezone.now().date()
        mock_now = mock_now.replace(year=2020, month=12, day=1)

        self.experiment.is_active = True
        self.experiment.date_start = mock_now
        self.experiment.date_end = mock_now
        self.experiment.code = 'Is_Own_Phone_Experiment'
        self.experiment.save()

        self.feature_setting.feature_name = 'force_high_creditscore'
        self.feature_setting.is_active = True
        self.feature_setting.parameters = {'email': 'test123'}
        self.feature_setting.save()

        mock_timezone.now.return_value = timezone.now()
        mock_timezone.localtime.return_value.date.return_value = mock_now

        mock_customer_has_good_payment_histories.return_value = True
        mock_remove_fdc_binary_check.return_value = ('basic_savings', 'basic_savings')
        mock_is_inside_premium_area.return_value = True
        mock_post_anaserver.return_value = True
        result = get_credit_score3(self.application, True, True)
        assert str(result) == '123321 - C'

    @patch('juloserver.apiv2.services.post_anaserver')
    @patch('juloserver.apiv2.services.is_inside_premium_area')
    @patch('juloserver.apiv2.services.remove_fdc_binary_check_that_is_not_in_fdc_threshold')
    @patch('juloserver.apiv2.services.is_customer_has_good_payment_histories')
    @patch('juloserver.apiv2.services.timezone')
    @patch('juloserver.apiv2.services.is_c_score_in_delay_period')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_TestGetCreditScore3_case_6(
        self,
        mock_check_app_cs_v20b,
        mock_c_score_in_delay,
        mock_timezone,
        mock_customer_has_good_payment_histories,
        mock_remove_fdc_binary_check,
        mock_is_inside_premium_area,
        mock_post_anaserver,
    ):
        self.application.customer = self.customer
        self.application.email = 'test@gmail.com'
        self.application.job_industry = ['test']
        self.application.partner = None
        self.application.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.save()

        mock_check_app_cs_v20b.return_value = True

        self.pd_web_model_result.application_id = self.application.id
        self.pd_web_model_result.save()

        mock_c_score_in_delay.return_value = True

        mock_now = timezone.now().date()
        mock_now = mock_now.replace(year=2020, month=12, day=1)

        self.experiment.is_active = True
        self.experiment.date_start = mock_now
        self.experiment.date_end = mock_now
        self.experiment.code = 'Is_Own_Phone_Experiment'
        self.experiment.save()

        self.feature_setting.feature_name = 'force_high_creditscore'
        self.feature_setting.is_active = True
        self.feature_setting.parameters = {'email': 'test123'}
        self.feature_setting.save()

        mock_timezone.now.return_value = timezone.now()
        mock_timezone.localtime.return_value.date.return_value = mock_now

        mock_customer_has_good_payment_histories.return_value = True
        mock_remove_fdc_binary_check.return_value = ('fraud_form_partial_device', 'basic_savings')
        mock_is_inside_premium_area.return_value = True
        mock_post_anaserver.return_value = True
        result = get_credit_score3(self.application, True, False)
        assert result is None

    @patch('juloserver.apiv2.services.is_inside_premium_area')
    @patch('juloserver.apiv2.services.remove_fdc_binary_check_that_is_not_in_fdc_threshold')
    @patch('juloserver.apiv2.services.is_customer_has_good_payment_histories')
    @patch('juloserver.apiv2.services.timezone')
    @patch('juloserver.apiv2.services.is_c_score_in_delay_period')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_TestGetCreditScore3_case_7(
        self,
        mock_check_app_cs_v20b,
        mock_c_score_in_delay,
        mock_timezone,
        mock_customer_has_good_payment_histories,
        mock_remove_fdc_binary_check,
        mock_is_inside_premium_area,
    ):
        self.application.customer = self.customer
        self.application.email = 'test@gmail.com'
        self.application.job_industry = ['test']
        self.application.partner = None
        self.application.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.save()

        mock_check_app_cs_v20b.return_value = True

        mock_c_score_in_delay.return_value = True

        mock_now = timezone.now().date()
        mock_now = mock_now.replace(year=2020, month=12, day=1)

        self.experiment.is_active = True
        self.experiment.date_start = mock_now
        self.experiment.date_end = mock_now
        self.experiment.code = 'Is_Own_Phone_Experiment'
        self.experiment.save()

        self.feature_setting.feature_name = 'force_high_creditscore'
        self.feature_setting.is_active = True
        self.feature_setting.parameters = {'email': 'test123'}
        self.feature_setting.save()

        mock_timezone.now.return_value = timezone.now()
        mock_timezone.localtime.return_value.date.return_value = mock_now

        mock_customer_has_good_payment_histories.return_value = True
        mock_remove_fdc_binary_check.return_value = ('fraud_form_partial_device', 'basic_savings')
        mock_is_inside_premium_area.return_value = True

        result = get_credit_score3(self.application, True, False)
        assert result is None

    @patch('juloserver.apiv2.services.post_anaserver')
    @patch('juloserver.apiv2.services.get_advance_ai_service')
    @patch('juloserver.julo.clients.get_julo_advanceai_client')
    @patch('juloserver.apiv2.services.is_inside_premium_area')
    @patch('juloserver.apiv2.services.get_good_score')
    @patch('juloserver.apiv2.services.get_experimental_probability_fpd')
    @patch('juloserver.julo.services.is_credit_experiment')
    @patch('juloserver.apiv2.services.remove_fdc_binary_check_that_is_not_in_fdc_threshold')
    @patch('juloserver.apiv2.services.is_customer_has_good_payment_histories')
    @patch('juloserver.apiv2.services.timezone')
    @patch('juloserver.apiv2.services.is_c_score_in_delay_period')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_TestGetCreditScore3_case_8(
        self,
        mock_check_app_cs_v20b,
        mock_c_score_in_delay,
        mock_timezone,
        mock_customer_has_good_payment_histories,
        mock_remove_fdc_binary_check,
        mock_is_credit_experiment,
        mock_get_experimental_probability_fpd,
        mock_get_good_score,
        mock_is_inside_premium_area,
        mock_client,
        mock_ai_service,
        mock_post_anaserver,
    ):
        self.application.customer = self.customer
        self.application.email = 'test@gmail.com'
        self.application.job_industry = ['test']
        self.application.partner = None
        self.application.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.save()

        mock_check_app_cs_v20b.return_value = True

        self.pd_web_model_result.application_id = self.application.id
        self.pd_web_model_result.save()

        mock_c_score_in_delay.return_value = True

        mock_now = timezone.now().date()
        mock_now = mock_now.replace(year=2020, month=8, day=8)

        self.experiment.is_active = True
        self.experiment.date_start = mock_now
        self.experiment.date_end = mock_now
        self.experiment.code = 'Is_Own_Phone_Experiment'
        self.experiment.save()

        self.feature_setting.feature_name = 'force_high_creditscore'
        self.feature_setting.is_active = True
        self.feature_setting.parameters = {'email': 'test123'}
        self.feature_setting.save()

        self.feature_setting1.feature_name = 'advance_ai_blacklist_check'
        self.feature_setting1.category = 'experiment'
        self.feature_setting1.is_active = True
        self.feature_setting1.save()

        self.feature_setting2.feature_name = 'fraud_model_experiment'
        self.feature_setting2.category = 'experiment'
        self.feature_setting2.is_active = True
        self.feature_setting2.parameters = {'low_probability_fpd': 0.1, 'high_probability_fpd': 0.3}
        self.feature_setting2.save()

        mock_timezone.now.return_value = timezone.now()
        mock_timezone.localtime.return_value.date.return_value = mock_now

        mock_customer_has_good_payment_histories.return_value = True
        mock_remove_fdc_binary_check.return_value = ('test123', 'basic_savings')
        mock_is_inside_premium_area.return_value = True

        mock_response_have_experiment = {'is_experiment': True, 'experiment': ''}
        mock_is_credit_experiment.return_value = mock_response_have_experiment
        mock_get_experimental_probability_fpd.return_value = 1
        mock_get_good_score.return_value = ('A-', [123], 'test123', 'test123', True, None)

        self.pd_fraud_model_result.application_id = self.application.id
        self.pd_fraud_model_result.probability_fpd = 0.2
        self.pd_fraud_model_result.save()

        self.experiment1.is_active = True
        self.experiment1.date_start = mock_now
        self.experiment1.date_end = mock_now
        self.experiment1.code = 'FRAUD_MODEL_105'
        self.experiment1.save()
        mock_post_anaserver.return_value = True
        result = get_credit_score3(self.application, True, True)
        assert str(result) == '123321 - A-'

    @patch('juloserver.apiv2.services.post_anaserver')
    @patch('juloserver.apiv2.services.get_advance_ai_service')
    @patch('juloserver.julo.clients.get_julo_advanceai_client')
    @patch('juloserver.apiv2.services.is_inside_premium_area')
    @patch('juloserver.apiv2.services.get_good_score')
    @patch('juloserver.apiv2.services.get_experimental_probability_fpd')
    @patch('juloserver.julo.services.is_credit_experiment')
    @patch('juloserver.apiv2.services.remove_fdc_binary_check_that_is_not_in_fdc_threshold')
    @patch('juloserver.apiv2.services.is_customer_has_good_payment_histories')
    @patch('juloserver.apiv2.services.timezone')
    @patch('juloserver.apiv2.services.is_c_score_in_delay_period')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_TestGetCreditScore3_case_9(
        self,
        mock_check_app_cs_v20b,
        mock_c_score_in_delay,
        mock_timezone,
        mock_customer_has_good_payment_histories,
        mock_remove_fdc_binary_check,
        mock_is_credit_experiment,
        mock_get_experimental_probability_fpd,
        mock_get_good_score,
        mock_is_inside_premium_area,
        mock_client,
        mock_ai_service,
        mock_post_anaserver,
    ):
        self.application.customer = self.customer
        self.application.email = 'test@gmail.com'
        self.application.job_industry = ['test']
        self.application.partner = None
        self.application.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.save()

        mock_check_app_cs_v20b.return_value = True

        self.pd_web_model_result.application_id = self.application.id
        self.pd_web_model_result.save()

        mock_c_score_in_delay.return_value = True

        mock_now = timezone.now().date()
        mock_now = mock_now.replace(year=2020, month=8, day=8)

        self.experiment.is_active = True
        self.experiment.date_start = mock_now
        self.experiment.date_end = mock_now
        self.experiment.code = 'Is_Own_Phone_Experiment'
        self.experiment.save()

        self.feature_setting.feature_name = 'force_high_creditscore'
        self.feature_setting.is_active = True
        self.feature_setting.parameters = {'email': 'test123'}
        self.feature_setting.save()

        self.feature_setting1.feature_name = 'advance_ai_blacklist_check'
        self.feature_setting1.category = 'experiment'
        self.feature_setting1.is_active = True
        self.feature_setting1.save()

        self.feature_setting2.feature_name = 'fraud_model_experiment'
        self.feature_setting2.category = 'experiment'
        self.feature_setting2.is_active = True
        self.feature_setting2.parameters = {'low_probability_fpd': 0.1, 'high_probability_fpd': 0.3}
        self.feature_setting2.save()

        mock_timezone.now.return_value = timezone.now()
        mock_timezone.localtime.return_value.date.return_value = mock_now

        mock_customer_has_good_payment_histories.return_value = True
        mock_remove_fdc_binary_check.return_value = ('test123', 'basic_savings')
        mock_is_inside_premium_area.return_value = True

        mock_response_have_experiment = {'is_experiment': False, 'experiment': ''}
        mock_is_credit_experiment.return_value = mock_response_have_experiment
        mock_get_experimental_probability_fpd.return_value = 1
        mock_get_good_score.return_value = ('A-', [123], 'test123', 'test123', True, None)

        self.pd_fraud_model_result.application_id = self.application.id
        self.pd_fraud_model_result.probability_fpd = 0.2
        self.pd_fraud_model_result.save()

        self.experiment1.is_active = True
        self.experiment1.date_start = mock_now
        self.experiment1.date_end = mock_now
        self.experiment1.code = 'FRAUD_MODEL_105'
        self.experiment1.save()
        mock_post_anaserver.return_value = True
        result = get_credit_score3(self.application, True, True)
        assert str(result) == '123321 - A-'

    @patch('juloserver.apiv2.services.post_anaserver')
    @patch('juloserver.apiv2.services.get_advance_ai_service')
    @patch('juloserver.julo.clients.get_julo_advanceai_client')
    @patch('juloserver.apiv2.services.is_inside_premium_area')
    @patch('juloserver.apiv2.services.get_good_score')
    @patch('juloserver.apiv2.services.get_experimental_probability_fpd')
    @patch('juloserver.julo.services.is_credit_experiment')
    @patch('juloserver.apiv2.services.remove_fdc_binary_check_that_is_not_in_fdc_threshold')
    @patch('juloserver.apiv2.services.is_customer_has_good_payment_histories')
    @patch('juloserver.apiv2.services.timezone')
    @patch('juloserver.apiv2.services.is_c_score_in_delay_period')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_TestGetCreditScore3_case_10(
        self,
        mock_check_app_cs_v20b,
        mock_c_score_in_delay,
        mock_timezone,
        mock_customer_has_good_payment_histories,
        mock_remove_fdc_binary_check,
        mock_is_credit_experiment,
        mock_get_experimental_probability_fpd,
        mock_get_good_score,
        mock_is_inside_premium_area,
        mock_client,
        mock_ai_service,
        mock_post_anaserver,
    ):
        self.application.customer = self.customer
        self.application.email = 'test@gmail.com'
        self.application.job_industry = ['test']
        self.application.partner = None
        self.application.save()

        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.save()

        mock_check_app_cs_v20b.return_value = True

        self.pd_web_model_result.application_id = self.application.id
        self.pd_web_model_result.save()

        mock_c_score_in_delay.return_value = True

        mock_now = timezone.now().date()
        mock_now = mock_now.replace(year=2020, month=8, day=8)

        self.experiment.is_active = True
        self.experiment.date_start = mock_now
        self.experiment.date_end = mock_now
        self.experiment.code = 'Is_Own_Phone_Experiment'
        self.experiment.save()

        self.feature_setting.feature_name = 'force_high_creditscore'
        self.feature_setting.is_active = True
        self.feature_setting.parameters = {'email': 'test123'}
        self.feature_setting.save()

        self.feature_setting1.feature_name = 'advance_ai_blacklist_check'
        self.feature_setting1.category = 'experiment'
        self.feature_setting1.is_active = True
        self.feature_setting1.save()

        self.feature_setting2.feature_name = 'fraud_model_experiment'
        self.feature_setting2.category = 'experiment'
        self.feature_setting2.is_active = True
        self.feature_setting2.parameters = {'low_probability_fpd': 0.1, 'high_probability_fpd': 0.3}
        self.feature_setting2.save()

        mock_timezone.now.return_value = timezone.now()
        mock_timezone.localtime.return_value.date.return_value = mock_now

        mock_customer_has_good_payment_histories.return_value = True
        mock_remove_fdc_binary_check.return_value = ('test123', 'basic_savings')
        mock_is_inside_premium_area.return_value = True

        mock_response_have_experiment = {'is_experiment': True, 'experiment': ''}
        mock_is_credit_experiment.return_value = mock_response_have_experiment
        mock_get_experimental_probability_fpd.return_value = 1
        mock_get_good_score.return_value = ('A-', [123], 'test123', 'test123', True, None)

        self.pd_fraud_model_result.application_id = self.application.id
        self.pd_fraud_model_result.probability_fpd = 0.2
        self.pd_fraud_model_result.save()
        mock_post_anaserver.return_value = True
        result = get_credit_score3(self.application, True, True)
        assert str(result) == '123321 - C'


class TestStoreCreditScoreToDb(TestCase):
    def setUp(self):
        self.application = ApplicationFactory(id=123)
        self.credit_score = CreditScoreFactory()
        self.auto_data_check = AutoDataCheckFactory()
        self.pd_credit_model_result = PdCreditModelResultFactory()
        self.experiment = ExperimentFactory(id=123, code=123)
        self.credit_matrix = CreditMatrixFactory()

    @patch('juloserver.apiv2.services.is_inside_premium_area')
    def test_TestStoreCreditScoreToDb_case_1(self, mock_is_inside_premium_area):
        mock_is_inside_premium_area.return_value = True

        result = store_credit_score_to_db(
            self.application, [], 'C', 'test123', 'test', self.pd_credit_model_result, None
        )
        assert str(result) == '123 - C'

    @patch('juloserver.apiv2.services.is_inside_premium_area')
    def test_TestStoreCreditScoreToDb_case_2(self, mock_is_inside_premium_area):
        self.auto_data_check.application_id = self.application.id
        self.auto_data_check.data_to_check = 'inside_premium_area'
        self.auto_data_check.save()

        mock_is_inside_premium_area.return_value = True
        result = store_credit_score_to_db(
            self.application,
            [],
            'C',
            'test123',
            'test',
            self.pd_credit_model_result,
            None,
            self.credit_matrix.id,
            self.experiment,
        )
        assert str(result) == '123 - C'

    @patch('juloserver.apiv2.services.is_inside_premium_area')
    @patch('juloserver.apiv2.services.get_appsflyer_service')
    def test_TestStoreCreditScoreToDb_case_3(
        self, mock_get_appsflyer_service, mock_is_inside_premium_area
    ):
        mock_get_appsflyer_service.side_effect = IntegrityError()
        self.credit_score.application_id = self.application.id
        self.credit_score.save()

        mock_is_inside_premium_area.return_value = True
        result = store_credit_score_to_db(
            self.application,
            [],
            'C',
            'test123',
            'test',
            self.pd_credit_model_result,
            None,
            self.credit_matrix.id,
            self.experiment,
        )
        assert str(result) == '123 - C'

    @patch('juloserver.apiv2.services.is_inside_premium_area')
    @patch('juloserver.julo.models.Application.is_regular_julo_one')
    def test_TestStoreCreditScoreToDb_pgood_pass_dynamic_check(
        self, mock_is_inside_premium_area, mock_is_regular_julo_one
    ):
        mock_is_inside_premium_area.return_value = True
        mock_is_regular_julo_one.return_value = True

        self.pd_credit_model_result.application_id = self.application.id
        self.pd_credit_model_result.pgood = 0.65
        self.pd_credit_model_result.save()

        self.auto_data_check.application_id = self.application.id
        self.auto_data_check.data_to_check = 'dynamic_check'
        self.auto_data_check.is_okay = True
        self.auto_data_check.latest = True
        self.auto_data_check.save()

        result = store_credit_score_to_db(
            self.application,
            [],
            'B-',
            'test123',
            'test',
            self.pd_credit_model_result,
            None,
            self.credit_matrix.id,
            self.experiment,
        )
        assert str(result) == '123 - B-'

    @patch('juloserver.apiv2.services.is_inside_premium_area')
    @patch('juloserver.julo.models.Application.is_regular_julo_one')
    def test_TestStoreCreditScoreToDb_not_pass_dynamic_check(
        self, mock_is_inside_premium_area, mock_is_regular_julo_one
    ):
        mock_is_inside_premium_area.return_value = True
        mock_is_regular_julo_one.return_value = True

        self.pd_credit_model_result.application_id = self.application.id
        self.pd_credit_model_result.pgood = 0.65
        self.pd_credit_model_result.save()

        self.auto_data_check.application_id = self.application.id
        self.auto_data_check.data_to_check = 'dynamic_check'
        self.auto_data_check.is_okay = False
        self.auto_data_check.latest = True
        self.auto_data_check.save()

        score, score_tag = override_score_for_failed_dynamic_check(self.application, 'B-', 'test')

        result = store_credit_score_to_db(
            self.application,
            [],
            score,
            'test123',
            score_tag,
            self.pd_credit_model_result,
            None,
            self.credit_matrix.id,
            self.experiment,
        )
        assert str(result) == '123 - C'


class TestIsCustomerHasGoodPaymentHistories(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(id=123)
        self.loan = LoanFactory()

    def test_TestIsCustomerHasGoodPaymentHistories_case_1(self):
        self.loan.loan_status_id = 250
        self.loan.customer = self.customer
        self.loan.application = self.application
        self.loan.save()

        self.application.loan = self.loan
        self.application.customer = self.customer
        self.application.save()

        result = is_customer_has_good_payment_histories(self.customer)
        assert result == True


class TestIsCustomerPaidOnTime(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory()
        self.loan = LoanFactory()

    def test_TestIsCustomerPaidOnTime_case_1(self):
        self.loan.loan_status_id = 250
        self.loan.customer = self.customer
        self.loan.application = self.application
        self.loan.save()

        self.application.loan = self.loan
        self.application.customer = self.customer
        self.application.save()

        result = is_customer_paid_on_time(self.customer, self.application.id)
        assert result == False


class TestGetCustomerAppActions(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.customer_app_action = CustomerAppActionFactory(id=123)
        self.customer_app_action1 = CustomerAppActionFactory(id=124)
        self.app_version = AppVersionFactory(id=123)
        self.app_version1 = AppVersionFactory(id=124, status='latest', app_version='test123')

    def test_TestGetCustomerAppActions_case_1(self):
        self.customer_app_action.customer_id = self.customer.id
        self.customer_app_action.action = 'force_upgrade'
        self.customer_app_action.is_completed = False
        self.customer_app_action.save()

        self.customer_app_action1.customer_id = self.customer.id
        self.customer_app_action1.action = 'sell_off'
        self.customer_app_action1.is_completed = False
        self.customer_app_action1.save()

        result = get_customer_app_actions(self.customer, 'test123')
        assert result == {'actions': [u'sell_off']}

    def test_TestGetCustomerAppActions_case_2(self):
        self.customer_app_action.customer_id = self.customer.id
        self.customer_app_action.action = 'sell_off'
        self.customer_app_action.is_completed = False
        self.customer_app_action.save()

        self.app_version.status = 'not_supported'
        self.app_version.app_version = 'test1234'
        self.app_version.save()

        result = get_customer_app_actions(self.customer, 'test1234')
        assert result == {'actions': [u'sell_off', 'force_upgrade']}

    def test_TestGetCustomerAppActions_case_3(self):
        self.customer_app_action.customer_id = self.customer.id
        self.customer_app_action.action = 'sell_off'
        self.customer_app_action.is_completed = False
        self.customer_app_action.save()

        self.app_version.status = 'deprecated'
        self.app_version.app_version = 'test1234'
        self.app_version.save()

        result = get_customer_app_actions(self.customer, 'test1234')
        assert result == {'actions': [u'sell_off', 'warning_upgrade']}


class TestGenerateAddressFromGeolocation(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.address_geolocation = AddressGeolocationFactory(application=self.application)

    @patch('juloserver.apiv2.services.geopy.geocoders')
    def test_TestGenerateAddressFromGeolocation_case_1(self, mock_geopy_geocoders):
        mock_geopy_geocoders.GoogleV3.return_value.geocode.side_effect = GeopyError()

        result = generate_address_from_geolocation(self.address_geolocation)
        mock_geopy_geocoders.GoogleV3.return_value.geocode.assert_called_with('0.0, 0.0')
        assert result is None

    @patch('juloserver.apiv2.services.geopy.geocoders')
    def test_TestGenerateAddressFromGeolocation_case_2(self, mock_geopy_geocoders):
        mock_geopy_geocoders.GoogleV3.return_value.geocode.side_effect = Exception()

        result = generate_address_from_geolocation(self.address_geolocation)
        mock_geopy_geocoders.GoogleV3.return_value.geocode.assert_called_with('0.0, 0.0')
        assert result is None

    @patch('juloserver.apiv2.services.geopy.geocoders')
    def test_TestGenerateAddressFromGeolocation_case_3(self, mock_geopy_geocoders):
        mock_geopy_geocoders.GoogleV3.return_value.geocode.return_value = None

        result = generate_address_from_geolocation(self.address_geolocation)
        mock_geopy_geocoders.GoogleV3.return_value.geocode.assert_called_with('0.0, 0.0')
        assert result is None

    @patch('juloserver.apiv2.services.geopy.geocoders')
    def test_TestGenerateAddressFromGeolocation_case_4(self, mock_geopy_geocoders):
        mock_response_geocode = {
            'address_components': [
                {'long_name': 'test_123', 'types': 'administrative_area_level_4'}
            ]
        }
        mock_geopy_geocoders.GoogleV3.return_value.geocode.return_value.raw = mock_response_geocode

        result = generate_address_from_geolocation(self.address_geolocation)
        mock_geopy_geocoders.GoogleV3.return_value.geocode.assert_called_with('0.0, 0.0')
        assert result is None

    @patch('juloserver.apiv2.services.geopy.geocoders')
    def test_TestGenerateAddressFromGeolocation_case_5(self, mock_geopy_geocoders):
        mock_response_geocode = {
            'address_components': [
                {'long_name': 'test_123', 'types': 'administrative_area_level_3'}
            ]
        }
        mock_geopy_geocoders.GoogleV3.return_value.geocode.return_value.raw = mock_response_geocode

        result = generate_address_from_geolocation(self.address_geolocation)
        mock_geopy_geocoders.GoogleV3.return_value.geocode.assert_called_with('0.0, 0.0')
        assert result is None

    @patch('juloserver.apiv2.services.geopy.geocoders')
    def test_TestGenerateAddressFromGeolocation_case_6(self, mock_geopy_geocoders):
        mock_response_geocode = {
            'address_components': [
                {'long_name': 'test_123', 'types': 'administrative_area_level_2'}
            ]
        }
        mock_geopy_geocoders.GoogleV3.return_value.geocode.return_value.raw = mock_response_geocode

        result = generate_address_from_geolocation(self.address_geolocation)
        mock_geopy_geocoders.GoogleV3.return_value.geocode.assert_called_with('0.0, 0.0')
        assert result is None

    @patch('juloserver.apiv2.services.geopy.geocoders')
    def test_TestGenerateAddressFromGeolocation_case_7(self, mock_geopy_geocoders):
        mock_response_geocode = {
            'address_components': [
                {'long_name': 'test_123', 'types': 'administrative_area_level_1'}
            ]
        }
        mock_geopy_geocoders.GoogleV3.return_value.geocode.return_value.raw = mock_response_geocode

        result = generate_address_from_geolocation(self.address_geolocation)
        mock_geopy_geocoders.GoogleV3.return_value.geocode.assert_called_with('0.0, 0.0')
        assert result is None

    @patch('juloserver.apiv2.services.geopy.geocoders')
    def test_TestGenerateAddressFromGeolocation_case_8(self, mock_geopy_geocoders):
        mock_response_geocode = {
            'address_components': [{'long_name': 'test', 'types': 'postal_code'}]
        }
        mock_geopy_geocoders.GoogleV3.return_value.geocode.return_value.raw = mock_response_geocode

        result = generate_address_from_geolocation(self.address_geolocation)
        mock_geopy_geocoders.GoogleV3.return_value.geocode.assert_called_with('0.0, 0.0')
        assert result is None


class TestGetProductSelections(TestCase):
    def setUp(self):
        self.product_profile = ProductProfileFactory(code='123')
        self.application = ApplicationFactory()
        self.product_customer_crieria = ProductCustomerCriteriaFactory()

    @patch('juloserver.apiv2.services.date')
    def test_TestGetProductSelections_case_1(self, mock_date):
        self.application.dob = date.today()
        self.application.dob = self.application.dob.replace(year=2000, month=12, day=1)
        self.application.save()
        mock_today = date.today()
        mock_today = mock_today.replace(year=2020, month=8, day=13)

        mock_date.today.return_value = mock_today

        result = get_product_selections(self.application, 'test')
        self.assertIsNotNone(result)
        # assert result == [92L, 97L, 84L, 20L, 90L, 82L, 10L, 93L, 91L, 96L, 83L, 95L, 30L, 94L, 81L, 60L]

    @patch('juloserver.apiv2.services.date')
    def test_TestGetProductSelections_case_2(self, mock_date):
        self.application.dob = date.today()
        self.application.dob = self.application.dob.replace(year=2000, month=12, day=30)
        self.application.save()
        mock_today = date.today()
        mock_today = mock_today.replace(year=2020, month=12, day=1)

        mock_date.today.return_value = mock_today

        result = get_product_selections(self.application, 'test')
        self.assertIsNotNone(result)
        # assert result == [92L, 97L, 84L, 20L, 90L, 82L, 10L, 93L, 91L, 96L, 83L, 95L, 30L, 94L, 81L, 60L]


class TestGetLastApplication(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory()

    def test__case_1(self):
        self.application.customer = self.customer
        self.application.application_status_id = 180
        self.application.save()

        result = get_last_application(self.customer)
        assert result == self.application


class TestCheckFraudModelExp(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.fraud_model_experiment = FraudModelExperimentFactory()

    def test_TestCheckFraudModelExp_case_1(self):
        self.fraud_model_experiment.application = self.application
        self.fraud_model_experiment.is_fraud_experiment_period = True
        self.fraud_model_experiment.save()

        result = check_fraud_model_exp(self.application)
        assert result == True


class TestFalseRejectMinExp(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.experiment = ExperimentFactory(code='123')
        self.application_exp = ApplicationExperimentFactory()

    def test_TestFalseRejectMinExp_case_1(self):
        self.experiment.code = 'FALSE_REJECT_MINIMIZATION'
        self.experiment.save()

        self.application_exp.application = self.application
        self.application_exp.experiment = self.experiment
        self.application_exp.save()

        result = false_reject_min_exp(self.application)
        assert result == True


class TestCheckEligibleMtlExtenstion(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.credit_score = CreditScoreFactory()
        self.product_line = ProductLineFactory()

    def test_TestCheckEligibleMtlExtenstion_case_1(self):
        self.product_line.product_line_code = 10
        self.product_line.save()

        self.application.job_type = 'Pegawai negeri'
        self.application.product_line = self.product_line
        self.application.save()

        self.credit_score.application_id = self.application.id
        self.credit_score.score_tag = 'c_low_credit_score'
        self.credit_score.save()

        result = check_eligible_mtl_extenstion(self.application)
        assert result == True


class TestGetProductLines(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory()
        self.loan = LoanFactory()
        self.credit_score = CreditScoreFactory()
        self.credit_matrix = CreditMatrixFactory()
        self.product_line = ProductLineFactory()
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            interest=0.1, min_loan_amount=0, max_loan_amount=1, max_duration=1
        )

    @patch('juloserver.apiv2.services.get_score_product')
    @patch('juloserver.apiv2.services.get_credit_matrix')
    @patch('juloserver.apiv2.services.get_credit_score3')
    def test_TestGetProductLines_case_1(
        self, mock_get_credit_score3, mock_get_credit_matrix, mock_get_score_product
    ):
        self.credit_score.inside_premium_area = True
        self.credit_score.score = 'C'
        self.credit_score.score_tag = 'test'
        self.credit_score.save()

        self.application.job_type = ''
        self.application.job_industry = ['test']
        self.application.save()

        self.credit_matrix.is_salarized = False
        self.credit_matrix.credit_matrix_type = 'julo'
        self.credit_matrix.score = 'C'
        self.credit_matrix.is_premium_area = True
        self.credit_matrix.save()

        self.product_line.product_line_code = 20
        self.product_line.save()

        self.credit_matrix_product_line.credit_matrix = self.credit_matrix
        self.credit_matrix_product_line.product = self.product_line
        self.credit_matrix_product_line.save()

        mock_get_credit_score3.return_value = self.credit_score
        mock_get_credit_matrix.return_value = self.credit_matrix
        mock_get_score_product.return_value = self.credit_matrix_product_line

        result = get_product_lines(self.customer, self.application)
        assert mock_get_credit_score3.called
        assert mock_get_credit_matrix.called
        assert mock_get_score_product.called
        assert str(result[0]) == '20_STLFake'

    @patch('juloserver.apiv2.services.get_score_product')
    @patch('juloserver.apiv2.services.get_credit_matrix')
    @patch('juloserver.apiv2.services.get_credit_score3')
    def test_TestGetProductLines_case_2(
        self, mock_get_credit_score3, mock_get_credit_matrix, mock_get_score_product
    ):
        self.credit_score.inside_premium_area = False
        self.credit_score.score = 'C'
        self.credit_score.score_tag = 'test'
        self.credit_score.save()

        self.application.job_type = ''
        self.application.job_industry = ['test']
        self.application.save()

        self.credit_matrix.is_salarized = False
        self.credit_matrix.credit_matrix_type = 'julo'
        self.credit_matrix.score = 'C'
        self.credit_matrix.is_premium_area = True
        self.credit_matrix.save()

        self.product_line.product_line_code = 10
        self.product_line.non_premium_area_min_amount = 1
        self.product_line.non_premium_area_max_amount = 2
        self.product_line.save()

        self.credit_matrix_product_line.credit_matrix = self.credit_matrix
        self.credit_matrix_product_line.product = self.product_line
        self.credit_matrix_product_line.save()

        mock_get_credit_score3.return_value = self.credit_score
        mock_get_credit_matrix.return_value = self.credit_matrix
        mock_get_score_product.return_value = self.credit_matrix_product_line

        result = get_product_lines(self.customer, self.application)
        assert mock_get_credit_score3.called
        assert mock_get_credit_matrix.called
        assert mock_get_score_product.called
        assert str(result[0]) == '10_STLFake'


class TestCreateFacebookDataHistory(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.facebook_data = FacebookDataFactory(application=self.application)

    def test_TestCreateFacebookDataHistory_case_1(self):
        result = create_facebook_data_history(self.facebook_data)
        assert result.application == self.application


class TestAddFacebookData(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()

    def test_TestAddFacebookData_case_1(self):
        request_data = {
            'facebook_id': 123,
            'fullname': 'test fullname',
            'email': 'test@gmail.com',
            'dob': '2000-01-01',
            'gender': 'M',
            'friend_count': '1',
            'open_date': '2017-01-01',
        }
        result = add_facebook_data(self.application, request_data)
        assert result.facebook_id == request_data['facebook_id']


class TestUpdateFacebookData(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.facebook_data = FacebookDataFactory()

    def test_TestUpdateFacebookData_case_1(self):
        request_data = {
            'facebook_id': 123,
            'fullname': 'test fullname',
            'email': 'test@gmail.com',
            'dob': '2000-01-01',
            'gender': 'M',
            'friend_count': '1',
            'open_date': '2017-01-01',
        }
        self.facebook_data.application = self.application
        self.facebook_data.save()
        result = update_facebook_data(self.application, request_data)
        assert result.facebook_id == request_data['facebook_id']


class TestCheckApplication(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()

    def test_TestCheckApplication_case_1(self):
        result = check_application(self.application.id)
        assert result == self.application

    def test_TestCheckApplication_case_2(self):
        with self.assertRaises(ValidationError) as context:
            result = check_application(1)
        self.assertTrue('application with id 1 not found' in str(context.exception))


class TestSwitchToProductDefaultWorkflow(TestCase):
    def setUp(self):
        self.workflow = WorkflowFactory(name='Testing')
        self.application = ApplicationFactory(
            id=123, email='test@gmail.com', workflow=self.workflow
        )
        self.product_line = ProductLineFactory()

    @patch.object(ApplicationWorkflowSwitchHistory.objects, 'create')
    def test_TestSwitchToProductDefaultWorkflow_case_1(self, mock_create_app_workflow_history):
        self.application.product_line = self.product_line
        self.application.save()

        result = switch_to_product_default_workflow(self.application)
        assert mock_create_app_workflow_history.called

    @patch.object(ApplicationWorkflowSwitchHistory.objects, 'create')
    def test_TestSwitchToProductDefaultWorkflow_case_2(self, mock_create_app_workflow_history):
        self.application.product_line = self.product_line
        self.application.save()

        self.product_line.default_workflow = self.workflow
        self.product_line.save()

        result = switch_to_product_default_workflow(self.application)
        assert mock_create_app_workflow_history.called

    @patch.object(ApplicationWorkflowSwitchHistory.objects, 'create')
    def test_TestSwitchToProductDefaultWorkflow_case_3(self, mock_create_app_workflow_history):
        self.application.product_line = self.product_line
        self.application.workflow = None
        self.application.save()

        result = switch_to_product_default_workflow(self.application)
        assert not mock_create_app_workflow_history.called


class TestGetLatestAppVerion(TestCase):
    def setUp(self):
        self.app_version = AppVersionFactory()

    def test_TestGetLatestAppVerion_case_1(self):
        self.app_version.status = 'latest'
        self.app_version.app_version = 'test123'
        self.app_version.save()
        result = get_latest_app_version()
        assert result == 'test123'


class TestCheckPayslipMandatory(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.product_line = ProductLineFactory()

    @patch('juloserver.apiv2.services.get_salaried')
    @patch('juloserver.apiv2.services.check_iti_repeat')
    def test_TestCheckPayslipMandatory_case_1(self, mock_check_iti_repeat, mock_get_salaried):
        mock_check_iti_repeat.return_value = True
        mock_get_salaried.return_value = True

        self.product_line.product_line_code = 10
        self.product_line.save()

        self.application.product_line = self.product_line
        self.application.job_type = 'test123'
        self.application.save()

        result = check_payslip_mandatory(self.application.id)
        assert result == True

    def test_TestCheckPayslipMandatory_case_2(self):
        result = check_payslip_mandatory(1)
        assert result is None


class TestCheckItiRepeat(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.credit_score = CreditScoreFactory()
        self.pd_credit_model_result = PdCreditModelResultFactory()
        self.pd_income_trust_model_result = PdIncomeTrustModelResultFactory()
        self.iti_configuration = ITIConfigurationFactory()

    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_TestCheckItiRepeat_case_1(self, mock_check_app_cs_v20b):
        result = check_iti_repeat(123123123)
        assert not mock_check_app_cs_v20b.called
        assert result == {}

    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_TestCheckItiRepeat_case_2(self, mock_check_app_cs_v20b):
        mock_check_app_cs_v20b.return_value = True
        self.pd_credit_model_result.application_id = self.application.id
        self.pd_credit_model_result.credit_score_type = 'B'
        self.pd_credit_model_result.save()

        result = check_iti_repeat(self.application.id)
        mock_check_app_cs_v20b.assert_called_with(self.application)
        assert result == {}

    @patch('juloserver.apiv2.services.get_customer_category')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_TestCheckItiRepeat_case_3(self, mock_check_app_cs_v20b, mock_get_customer_category):
        mock_check_app_cs_v20b.return_value = True
        mock_get_customer_category.return_value = 'test123'
        self.pd_credit_model_result.application_id = self.application.id
        self.pd_credit_model_result.credit_score_type = 'B'
        self.pd_credit_model_result.save()

        self.credit_score.application = self.application
        self.credit_score.save()

        result = check_iti_repeat(self.application.id)
        mock_check_app_cs_v20b.assert_called_with(self.application)
        assert result is None

    @patch('juloserver.apiv2.services.get_salaried')
    @patch('juloserver.apiv2.services.get_customer_category')
    @patch('juloserver.apiv2.services.check_app_cs_v20b')
    def test_TestCheckItiRepeat_case_4(
        self, mock_check_app_cs_v20b, mock_get_customer_category, mock_get_salaried
    ):
        mock_check_app_cs_v20b.return_value = True
        mock_get_customer_category.return_value = 'test123'
        mock_get_salaried.return_value = True

        self.application.job_type = 'test'
        self.application.monthly_income = 100
        self.application.save()

        self.pd_credit_model_result.application_id = self.application.id
        self.pd_credit_model_result.credit_score_type = 'B'
        self.pd_credit_model_result.save()

        self.credit_score.application = self.application
        self.credit_score.inside_premium_area = True
        self.credit_score.save()

        self.iti_configuration.is_active = True
        self.iti_configuration.is_premium_area = True
        self.iti_configuration.is_salaried = True
        self.iti_configuration.customer_category = 'test123'
        self.iti_configuration.iti_version = 123
        self.iti_configuration.min_threshold = 0.0
        self.iti_configuration.max_threshold = 1.0
        self.iti_configuration.min_income = 100
        self.iti_configuration.max_income = 101
        self.iti_configuration.save()

        result = check_iti_repeat(self.application.id)
        mock_check_app_cs_v20b.assert_called_with(self.application)
        mock_get_customer_category.assert_called_with(self.application)
        mock_get_salaried.assert_called_with('test')
        assert result != None


class TestGetCustomerCategory(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.customer = CustomerFactory()
        self.loan = LoanFactory()

    def test_TestGetCustomerCategory_case_1(self):
        self.application.web_version = 'test123'
        self.application.save()

        result = get_customer_category(self.application)
        assert result == 'julo'

    def test_TestGetCustomerCategory_case_2(self):
        self.application.customer = self.customer
        self.application.save()

        self.loan.customer = self.customer
        self.loan.application = self.application
        self.loan.loan_status_id = 250
        self.loan.save()

        result = get_customer_category(self.application)
        assert result == 'julo_repeat'


class TestCanReapplyValidation(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)

    def test_TestCanReapplyValidation_case_1(self):
        self.customer.can_reapply = True
        self.customer.save()

        self.application.customer = self.customer
        self.application.application_status_id = 133
        self.application.save()

        result = can_reapply_validation(self.customer)
        assert result == True

    def test_when_previous_application_ever_190(self):
        """
        This test assumes that any bug that make previous 190
        application to change again.
        This case happened in customer 1005308919
        """
        self.customer.can_reapply = True
        self.customer.save()

        ApplicationHistoryFactory(
            application_id=self.application.id, status_old=150, status_new=190
        )
        ApplicationHistoryFactory(
            application_id=self.application.id, status_old=141, status_new=133
        )
        self.application.application_status_id = 133
        self.application.save()

        result = can_reapply_validation(self.customer)
        self.assertFalse(result)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestGetReferralHomeContent(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory()
        self.app_version = AppVersionFactory()
        self.application_history = ApplicationHistoryFactory()
        self.loan = LoanFactory()
        self.payment = PaymentFactory()

    def test_TestGetRefferalHomeContent_case_1(self):
        self.app_version.cdate = '2019-10-13'
        self.app_version.app_version = 'test123'
        self.app_version.save()

        result = get_referral_home_content(self.customer, self.application, 'test123')
        assert str(result) == '(False, {})'

    def test_TestGetRefferalHomeContent_case_2(self):
        self.app_version.cdate = '2019-10-15'
        self.app_version.app_version = 'test123'
        self.app_version.save()

        self.application_history.application_id = self.application.id
        self.application_history.status_new = 180
        self.application_history.save()

        self.customer.can_reapply = True
        self.customer.save()

        self.application.customer = self.customer
        self.application.save()

        self.loan.application = self.application
        self.loan.customer = self.customer
        self.loan.loan_status_id = 250
        self.loan.save()

        mock_paid_date = timezone.now()
        mock_paid_date = mock_paid_date.replace(
            year=2099, month=10, day=22, hour=23, minute=59, second=59, microsecond=0
        )

        self.payment.payment_number = 999
        self.payment.loan = self.loan
        self.payment.paid_date = mock_paid_date
        self.payment.save()

        result = get_referral_home_content(self.customer, self.application, 'test123')
        assert str(result) == '(False, {})'


class TestCreateBankValidationCard(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.loan = LoanFactory()
        self.name_bank_validation = NameBankValidationFactory()

    def test_TestCreateBankValidationCard_case_1(self):
        self.name_bank_validation.reason = "test123"
        self.name_bank_validation.save()
        self.loan.application = self.application
        self.loan.name_bank_validation_id = self.name_bank_validation.id
        self.loan.save()

        result = create_bank_validation_card(self.application, 'from_175')
        assert result == {
            'body': '',
            'header': 'Informasi Pengajuan',
            'bottomimage': '',
            'expired_time': None,
            'buttonurl': None,
            'topimage': None,
            'buttontext': None,
            'data': {'INVALID_REASON': 'NAME_INVALID'},
            'buttonstyle': None,
        }

    def test_TestCreateBankValidationCard_case_2(self):
        self.name_bank_validation.reason = "NAME_INVALID"
        self.name_bank_validation.save()
        self.loan.application = self.application
        self.loan.name_bank_validation_id = self.name_bank_validation.id
        self.loan.save()

        result = create_bank_validation_card(self.application, 'from_175')
        assert result == {
            'body': '',
            'header': 'Informasi Pengajuan',
            'bottomimage': '',
            'expired_time': None,
            'buttonurl': None,
            'topimage': None,
            'buttontext': None,
            'data': {'INVALID_REASON': 'NAME_INVALID'},
            'buttonstyle': None,
        }

    def test_TestCreateBankValidationCard_case_3(self):
        self.name_bank_validation.reason = "Failed to add bank account Bad Request"
        self.name_bank_validation.save()
        self.loan.application = self.application
        self.loan.name_bank_validation_id = self.name_bank_validation.id
        self.loan.save()

        result = create_bank_validation_card(self.application, 'from_175')
        assert result == {
            'body': '',
            'header': 'Informasi Pengajuan',
            'bottomimage': '',
            'expired_time': None,
            'buttonurl': None,
            'topimage': None,
            'buttontext': None,
            'data': {'INVALID_REASON': 'BANK_ACCOUNT_INVALID'},
            'buttonstyle': None,
        }


class TestUpdateResponseFalseRejection(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.experiment = ExperimentFactory(code=123)
        self.application_experiment = ApplicationExperimentFactory()

    def test_TestUpdateResponseFalseRejection_case_1(self):
        self.experiment.code = 'FALSE_REJECT_MINIMIZATION'
        self.experiment.save()

        self.application_experiment.application = self.application
        self.application_experiment.experiment = self.experiment
        self.application_experiment.save()

        response_data = {'product_lines': [{'product_line_code': 10}], 'products': ['test123']}
        result = update_response_false_rejection(self.application, response_data)
        assert result == {
            'products': ['test123', 10],
            'score': 'B-',
            'product_lines': [
                {
                    'max_duration': 2,
                    'max_amount': 1000000,
                    'product_line_code': 10,
                    'min_amount': 1000000,
                    'min_duration': 2,
                    'max_interest_rate': 0.07,
                    'min_interest_rate': 0.07,
                }
            ],
            'mtl_experiment_enable': True,
        }

    def test_TestUpdateResponseFalseRejection_case_2(self):
        self.experiment.code = 'FALSE_REJECT_MINIMIZATION'
        self.experiment.save()

        self.application_experiment.application = self.application
        self.application_experiment.experiment = self.experiment
        self.application_experiment.save()

        response_data = {'product_lines': [{'product_line_code': 10}], 'message': 'test123'}
        result = update_response_false_rejection(self.application, response_data)
        assert result == {
            'mtl_experiment_enable': True,
            'message': 'Peluang pengajuan Anda di-ACC cukup besar! Silakan pilih produk pinjaman di bawah ini & selesaikan pengajuannya.',
            'score': 'B-',
            'product_lines': [
                {
                    'max_duration': 2,
                    'max_amount': 1000000,
                    'product_line_code': 10,
                    'min_amount': 1000000,
                    'min_duration': 2,
                    'max_interest_rate': 0.07,
                    'min_interest_rate': 0.07,
                }
            ],
        }


class TestUpdateResponseFraudExperiment(TestCase):
    def setUp(self):
        pass

    def test_TestUpdateResponseFraudExperiment_case_1(self):
        response_data = {'product_lines': [{'product_line_code': 10}], 'products': ['test123']}
        result = update_response_fraud_experiment(response_data)
        assert result == {
            'products': [10],
            'score': 'B-',
            'product_lines': [
                {
                    'max_duration': 2,
                    'max_amount': 1000000,
                    'product_line_code': 10,
                    'min_amount': 1000000,
                    'min_duration': 2,
                    'max_interest_rate': 0.07,
                    'min_interest_rate': 0.07,
                }
            ],
            'mtl_experiment_enable': True,
        }

    def test_TestUpdateResponseFraudExperiment_case_2(self):
        response_data = {'product_lines': [{'product_line_code': 11}], 'products': ['test123']}
        result = update_response_fraud_experiment(response_data)
        assert result == {
            'products': [11],
            'score': 'B-',
            'product_lines': [
                {
                    'max_duration': 2,
                    'max_amount': 1000000,
                    'product_line_code': 11,
                    'min_amount': 1000000,
                    'min_duration': 2,
                    'max_interest_rate': 0.07,
                    'min_interest_rate': 0.07,
                }
            ],
            'mtl_experiment_enable': True,
        }

    def test_TestUpdateResponseFraudExperiment_case_3(self):
        response_data = {'product_lines': [{'product_line_code': 11}], 'message': 'test123'}
        result = update_response_fraud_experiment(response_data)
        assert result == {
            'mtl_experiment_enable': True,
            'message': 'Peluang pengajuan Anda di-ACC cukup besar! Silakan pilih produk pinjaman di bawah ini & selesaikan pengajuannya.',
            'score': 'B-',
            'product_lines': [
                {
                    'max_duration': 2,
                    'max_amount': 1000000,
                    'product_line_code': 11,
                    'min_amount': 1000000,
                    'min_duration': 2,
                    'max_interest_rate': 0.07,
                    'min_interest_rate': 0.07,
                }
            ],
        }


class TestRemoveFdcBinaryCheckThatIsNotInFdcThreshold(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.feature_setting = FeatureSettingFactory()
        self.fdc_inquiry = FDCInquiryFactory()
        self.credit_model_1 = PdCreditModelResultFactory()
        self.credit_model_2 = PdWebModelResultFactory()
        self.credit_model_3 = PdIncomeTrustModelResultFactory()
        self.fdc_inquiry_check = FDCInquiryCheckFactory()
        self.fdc_inquiry_loan = FDCInquiryLoanFactory()

    def test_TestRemoveFdcBinaryCheckThatIsNotInFdcThreshold_case_1(self):
        self.credit_model_1.pgood = True
        self.credit_model_1.save()

        result = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
            self.credit_model_1, ['test'], self.application
        )
        assert str(result) == "(['test'], None)"

    def test_TestRemoveFdcBinaryCheckThatIsNotInFdcThreshold_case_2(self):
        self.credit_model_1.pgood = True
        self.credit_model_1.save()

        self.feature_setting.feature_name = 'fdc_inquiry_check'
        self.feature_setting.is_active = True
        self.feature_setting.save()

        result = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
            self.credit_model_1, ['test'], self.application
        )
        assert str(result) == "(['test'], None)"

    def test_TestRemoveFdcBinaryCheckThatIsNotInFdcThreshold_case_3(self):
        self.credit_model_2.probability_fpd = 1
        self.credit_model_2.save()

        self.feature_setting.feature_name = 'fdc_inquiry_check'
        self.feature_setting.is_active = True
        self.feature_setting.save()

        self.fdc_inquiry.application_id = self.application.id
        self.fdc_inquiry.inquiry_status = 'success'
        self.fdc_inquiry.inquiry_date = date(2020, 1, 1)
        self.fdc_inquiry.save()

        result = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
            self.credit_model_2, ['fdc_inquiry_check'], self.application
        )
        assert str(result) == "([], True)"

    def test_TestRemoveFdcBinaryCheckThatIsNotInFdcThreshold_case_4(self):
        self.feature_setting.feature_name = 'fdc_inquiry_check'
        self.feature_setting.is_active = True
        self.feature_setting.save()

        self.fdc_inquiry.application_id = self.application.id
        self.fdc_inquiry.inquiry_status = 'success'
        self.fdc_inquiry.inquiry_date = date(2020, 1, 1)
        self.fdc_inquiry.save()

        result = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
            self.credit_model_3, ['fdc_inquiry_check'], self.application
        )
        assert str(result) == "(['fdc_inquiry_check'], None)"

    def test_TestRemoveFdcBinaryCheckThatIsNotInFdcThreshold_case_5(self):
        self.credit_model_2.probability_fpd = 1
        self.credit_model_2.pgood = 1
        self.credit_model_2.save()

        self.feature_setting.feature_name = 'fdc_inquiry_check'
        self.feature_setting.is_active = True
        self.feature_setting.save()

        self.fdc_inquiry.application_id = self.application.id
        self.fdc_inquiry.inquiry_status = 'success'
        self.fdc_inquiry.inquiry_date = date(2020, 1, 1)
        self.fdc_inquiry.save()

        self.fdc_inquiry_check.min_threshold = 1
        self.fdc_inquiry_check.max_threshold = 1.1
        self.fdc_inquiry_check.is_active = True
        self.fdc_inquiry_check.min_macet_pct = -1
        self.fdc_inquiry_check.save()

        result = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
            self.credit_model_2, ['fdc_inquiry_check'], self.application
        )
        assert str(result) == "(['fdc_inquiry_check'], False)"

    def test_TestRemoveFdcBinaryCheckThatIsNotInFdcThreshold_case_6(self):
        self.credit_model_2.probability_fpd = 1
        self.credit_model_2.save()

        self.feature_setting.feature_name = 'fdc_inquiry_check'
        self.feature_setting.is_active = True
        self.feature_setting.save()

        self.fdc_inquiry.application_id = self.application.id
        self.fdc_inquiry.inquiry_status = 'success'
        self.fdc_inquiry.inquiry_date = date(2020, 1, 1)
        self.fdc_inquiry.save()

        self.fdc_inquiry_check.min_threshold = 1
        self.fdc_inquiry_check.max_threshold = 1.1
        self.fdc_inquiry_check.is_active = True
        self.fdc_inquiry_check.inquiry_date = date(2020, 1, 1)
        self.fdc_inquiry_check.save()

        self.fdc_inquiry_loan.fdc_inquiry_id = self.fdc_inquiry.id
        self.fdc_inquiry_loan.tgl_pelaporan_data = date(2020, 8, 1)
        self.fdc_inquiry_loan.kualitas_pinjaman = 'Macet (>90)'
        self.fdc_inquiry_loan.save()

        result = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
            self.credit_model_2, ['test'], self.application
        )
        assert str(result) == "(['test'], True)"

    def test_TestRemoveFdcBinaryCheckThatIsNotInFdcThreshold_case_7(self):
        self.credit_model_2.probability_fpd = 1
        self.credit_model_2.save()

        self.feature_setting.feature_name = 'fdc_inquiry_check'
        self.feature_setting.is_active = True
        self.feature_setting.save()

        self.fdc_inquiry.application_id = self.application.id
        self.fdc_inquiry.inquiry_status = 'success'
        self.fdc_inquiry.inquiry_date = date(2020, 1, 1)
        self.fdc_inquiry.save()

        self.fdc_inquiry_check.min_threshold = 1
        self.fdc_inquiry_check.max_threshold = 1.1
        self.fdc_inquiry_check.is_active = True
        self.fdc_inquiry_check.inquiry_date = date(2020, 1, 1)
        self.fdc_inquiry_check.min_macet_pct = 2
        self.fdc_inquiry_check.min_tidak_lancar = 2
        self.fdc_inquiry_check.save()

        self.fdc_inquiry_loan.tgl_pelaporan_data = date(2020, 8, 1)
        self.fdc_inquiry_loan.kualitas_pinjaman = 'Tidak Lancar (30 sd 90 hari)'
        self.fdc_inquiry_loan.total = 1
        self.fdc_inquiry_loan.save()

        result = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
            self.credit_model_2, ['test'], self.application
        )
        assert str(result) == "(['test'], True)"

    @patch('juloserver.apiv2.services.timezone')
    def test_TestRemoveFdcBinaryCheckThatIsNotInFdcThreshold_case_8(self, mock_timezone):
        mock_now = timezone.localtime(timezone.now()).date()
        mock_now = mock_now.replace(year=2020, month=8, day=1)

        mock_timezone.now.return_value = timezone.now()
        mock_timezone.localtime.return_value.date.return_value = mock_now

        self.credit_model_2.probability_fpd = 1
        self.credit_model_2.save()

        self.feature_setting.feature_name = 'fdc_inquiry_check'
        self.feature_setting.is_active = True
        self.feature_setting.save()

        self.fdc_inquiry.application_id = self.application.id
        self.fdc_inquiry.inquiry_status = 'success'
        self.fdc_inquiry.inquiry_date = date(2020, 1, 1)
        self.fdc_inquiry.save()

        self.fdc_inquiry_check.min_threshold = 1
        self.fdc_inquiry_check.max_threshold = 1.1
        self.fdc_inquiry_check.is_active = True
        self.fdc_inquiry_check.inquiry_date = date(2020, 1, 1)
        self.fdc_inquiry_check.min_macet_pct = 2
        self.fdc_inquiry_check.min_tidak_lancar = 2
        self.fdc_inquiry_check.max_paid_pct = 3
        self.fdc_inquiry_check.save()

        self.fdc_inquiry_loan.fdc_inquiry = self.fdc_inquiry
        self.fdc_inquiry_loan.tgl_pelaporan_data = date(2020, 1, 2)
        self.fdc_inquiry_loan.tgl_jatuh_tempo_pinjaman = date(2020, 7, 1)
        self.fdc_inquiry_loan.kualitas_pinjaman = 'Lancar (<30 hari)'
        self.fdc_inquiry_loan.total = 1
        self.fdc_inquiry_loan.nilai_pendanaan = 100
        self.fdc_inquiry_loan.sisa_pinjaman_berjalan = 50
        self.fdc_inquiry_loan.save()

        result = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
            self.credit_model_2, ['test'], self.application
        )
        assert str(result) == "(['test'], True)"

    @patch('juloserver.apiv2.services.timezone')
    def test_TestRemoveFdcBinaryCheckThatIsNotInFdcThreshold_case_9(self, mock_timezone):
        mock_now = timezone.localtime(timezone.now()).date()
        mock_now = mock_now.replace(year=2020, month=8, day=1)

        mock_timezone.now.return_value = timezone.now()
        mock_timezone.localtime.return_value.date.return_value = mock_now

        self.credit_model_2.probability_fpd = 1
        self.credit_model_2.save()

        self.feature_setting.feature_name = 'fdc_inquiry_check'
        self.feature_setting.is_active = True
        self.feature_setting.save()

        self.fdc_inquiry.application_id = self.application.id
        self.fdc_inquiry.inquiry_status = 'success'
        self.fdc_inquiry.inquiry_date = date(2020, 1, 1)
        self.fdc_inquiry.save()

        self.fdc_inquiry_check.min_threshold = 1
        self.fdc_inquiry_check.max_threshold = 1.1
        self.fdc_inquiry_check.is_active = True
        self.fdc_inquiry_check.inquiry_date = date(2020, 1, 1)
        self.fdc_inquiry_check.min_macet_pct = 2
        self.fdc_inquiry_check.min_tidak_lancar = 2
        self.fdc_inquiry_check.save()

        self.fdc_inquiry_loan.fdc_inquiry = self.fdc_inquiry
        self.fdc_inquiry_loan.tgl_pelaporan_data = date(2020, 1, 2)
        self.fdc_inquiry_loan.tgl_jatuh_tempo_pinjaman = date(2020, 7, 1)
        self.fdc_inquiry_loan.kualitas_pinjaman = 'Tidak Lancar (30 sd 90 hari)'
        self.fdc_inquiry_loan.total = 1
        self.fdc_inquiry_loan.nilai_pendanaan = 100
        self.fdc_inquiry_loan.sisa_pinjaman_berjalan = 50
        self.fdc_inquiry_loan.save()

        result = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
            self.credit_model_2, ['test'], self.application
        )
        assert str(result) == "(['test'], True)"


class TestStoreDeviceGeolocation(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory()
        self.address_geolocation = AddressGeolocationFactory(
            application=self.application, latitude=123, longitude=124
        )
        self.device = DeviceFactory(id=123)

    @patch('juloserver.apiv2.services.DeviceGeolocationSerializer')
    def test_TestStoreDeviceGeolocation_case_1(self, mock_device_geolocation_serializer):
        self.device.customer = self.customer
        self.device.save()
        mock_device_geolocation_serializer.is_valid.return_value = True

        store_device_geolocation(
            self.customer, self.address_geolocation.latitude, self.address_geolocation.longitude
        )
        mock_device_geolocation_serializer.assert_called_with(
            data={'device': 123, 'latitude': 123, 'longitude': 124}
        )

    @patch('juloserver.apiv2.services.DeviceGeolocationSerializer')
    def test_TestStoreDeviceGeolocation_case_2(self, mock_device_geolocation_serializer):
        self.device.customer = self.customer
        self.device.save()
        mock_device_geolocation_serializer.return_value.is_valid.return_value = False

        store_device_geolocation(
            self.customer, self.address_geolocation.latitude, self.address_geolocation.longitude
        )
        mock_device_geolocation_serializer.assert_called_with(
            data={'device': 123, 'latitude': 123, 'longitude': 124}
        )


class TestIsInsidePremiumArea(TestCase):
    def setUp(self):
        pass

    def test_TestIsInsidePremiumArea_case_1(self):
        result = is_inside_premium_area(1)
        assert result is None


class TestBinaryFraudEmailandKtp(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)

    def test_case1(self):
        failed_checks = ['fraud_email', 'fraud_ktp']
        checking_fraud_email_and_ktp(self.application, failed_checks)
        self.customer.refresh_from_db()
        assert self.customer.nik is None
        assert self.customer.email is None
        result = CustomerFieldChange.objects.filter(customer=self.customer).count()
        self.assertNotEqual(result, 0)

    def test_case2(self):
        failed_checks = ['fraud_ktp']
        checking_fraud_email_and_ktp(self.application, failed_checks)
        self.customer.refresh_from_db()
        assert self.customer.nik is None
        assert self.customer.email is None
        result = CustomerFieldChange.objects.filter(customer=self.customer).count()
        self.assertNotEqual(result, 0)

    def test_case3(self):
        failed_checks = ['fraud_email']
        checking_fraud_email_and_ktp(self.application, failed_checks)
        self.customer.refresh_from_db()
        assert self.customer.nik is None
        assert self.customer.email is None
        result = CustomerFieldChange.objects.filter(customer=self.customer).count()
        self.assertNotEqual(result, 0)

    def test_case4(self):
        failed_checks = []
        self.customer.nik = '1231230909991231'
        self.customer.email = 'djasentjendry@julofinanc.com'
        self.customer.save()
        checking_fraud_email_and_ktp(self.application, failed_checks)
        assert self.customer.nik == '1231230909991231'
        assert self.customer.email == 'djasentjendry@julofinanc.com'
        result = CustomerFieldChange.objects.filter(customer=self.customer).count()
        self.assertEqual(result, 0)

    def test_case5(self):
        # test customer can't update from none to none value
        failed_checks = ['fraud_email']
        self.customer.nik = None
        self.customer.email = None
        self.customer.save()
        checking_fraud_email_and_ktp(self.application, failed_checks)
        result = CustomerFieldChange.objects.filter(customer=self.customer).count()
        self.assertEqual(result, 0)


class TestBinaryCheckResult(TestCase):
    def setUp(self):
        self.application = ApplicationFactory(id=123321)
        self.loan = LoanFactory()
        self.pd_credit_model_result = PdCreditModelResultFactory()
        self.pd_web_model_result = PdWebModelResultFactory()
        self.experiment = ExperimentFactory(id=123, code=123)
        self.experiment1 = ExperimentFactory(id=124, code=124)
        self.feature_setting = FeatureSettingFactory(id=123)
        self.feature_setting1 = FeatureSettingFactory(id=124)
        self.feature_setting2 = FeatureSettingFactory(id=125)
        self.pd_fraud_model_result = PdFraudModelResultFactory()

    @patch('juloserver.apiv2.services.get_credit_model_result')
    def test_first_check_failed(self, mock_get_credit_model_result):
        mock_get_credit_model_result.return_value = 'fake_result', 'julo'

        today = timezone.localtime(timezone.now()).date()
        ExperimentFactory(
            is_active=True,
            date_start=today - timedelta(days=1),
            date_end=today + timedelta(days=1),
            code='Is_Own_Phone_Experiment',
        )
        AutoDataCheckFactory(
            application_id=self.application.id, is_okay=False, data_to_check='basic_savings'
        )
        result = check_binary_result(self.application)
        self.assertFalse(result)

    @patch('juloserver.apiv2.services.get_credit_model_result')
    def test_pass(self, mock_get_credit_model_result):
        mock_get_credit_model_result.return_value = 'fake_result', 'julo'

        today = timezone.localtime(timezone.now()).date()
        ExperimentFactory(
            is_active=True,
            date_start=today - timedelta(days=1),
            date_end=today + timedelta(days=1),
            code='Is_Own_Phone_Experiment',
        )
        AutoDataCheckFactory(
            application_id=self.application.id, is_okay=True, data_to_check='basic_savings'
        )
        result = check_binary_result(self.application)
        self.assertTrue(result)
