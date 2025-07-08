import random
import string
from builtins import object, range
from datetime import datetime

import mock
import pytest
from django.conf import settings
from django.utils import timezone
from factory import LazyAttribute, SubFactory
from factory.django import DjangoModelFactory
from faker import Faker
from mock import patch
from mock_django.query import QuerySetMock
from rest_framework.test import APITestCase
from django.test import TestCase

from juloserver.apiv2.credit_matrix2 import get_credit_matrix, get_good_score
from juloserver.apiv2.models import PdCreditModelResult
from juloserver.apiv2.services import *
from juloserver.core.utils import JuloFakerProvider
from juloserver.julo.models import (
    Application,
    AppVersion,
    CreditScore,
    Customer,
    CustomerAppAction,
    Device,
    ProductLine,
    ApplicationScrapeAction,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CreditMatrixFactory,
    CustomerFactory,
    ProductLineFactory,
    FDCInquiryFactory,
    FDCInquiryLoanFactory,
    CreditScoreFactory,
    WorkflowFactory,
    ProductLineFactory,
    CustomerAppActionFactory,
    FeatureSettingFactory,
    ApplicationHistoryFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory

from juloserver.julo.constants import (
    WorkflowConst,
    ProductLineCodes,
)
from juloserver.apiv2.services import calculate_total_credit
from juloserver.apiv2.tests.factories import (
    PdCreditModelResultFactory,
    EtlStatusFactory,
)
from juloserver.apiv2.tasks import generate_credit_score
from juloserver.application_flow.services2.credit_score_dsd import general_check_for_scoring
from juloserver.application_flow.constants import ApplicationDsdMessageConst

fake = Faker()
fake.add_provider(JuloFakerProvider)

UNIGUE_NUMBER = 1000


def unique_number():
    global UNIGUE_NUMBER
    UNIGUE_NUMBER += 1
    return UNIGUE_NUMBER


class AuthUserFactory(DjangoModelFactory):
    class Meta(object):
        model = settings.AUTH_USER_MODEL

    username = LazyAttribute(lambda o: fake.random_username())


class CustomerFactory(DjangoModelFactory):
    class Meta(object):
        model = Customer

    user = SubFactory(AuthUserFactory)

    fullname = LazyAttribute(lambda o: fake.name())
    email = LazyAttribute(lambda o: fake.random_email())
    is_email_verified = False
    phone = LazyAttribute(lambda o: fake.phone_number())
    is_phone_verified = False
    country = ''
    self_referral_code = ''
    email_verification_key = 'email_verification_key'
    email_key_exp_date = datetime.today()
    reset_password_key = ''
    reset_password_exp_date = None


class StatusLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = 'julo.StatusLookup'
        django_get_or_create = ('status_code',)

    status_code = 0


class DeviceFactory(DjangoModelFactory):
    class Meta(object):
        model = Device

    customer = SubFactory(CustomerFactory)

    gcm_reg_id = LazyAttribute(
        lambda o: ''.join(random.choice('abcdefGHIKLM0123456789') for _ in range(32))
    )
    android_id = LazyAttribute(
        lambda o: ''.join(random.choice(string.hexdigits) for _ in range(16))
    )
    imei = LazyAttribute(lambda o: ''.join(random.choice(string.digits) for _ in range(15)))


@pytest.mark.django_db
class TestCustomerAppAction(object):
    def test_customer_app_action(self):
        # create latest entry app_version, to prevent function breaking
        AppVersion.objects.create(app_version='99.9.9', status='latest')
        # create customer, test for only one force_upgrade as return
        customer = CustomerFactory()
        CustomerAppAction.objects.create(customer=customer, action='force_upgrade')
        AppVersion.objects.create(app_version='2.0.0', status='not_supported')
        actions = get_customer_app_actions(customer.id, '2.0.0')
        assert actions == ({'actions': ['force_upgrade']})
        # create customer, test for all three actions, asserting order
        customer2 = CustomerFactory()
        CustomerAppAction.objects.create(customer=customer2, action='force_logout')
        CustomerAppAction.objects.create(customer=customer2, action='force_upgrade')
        CustomerAppAction.objects.create(customer=customer2, action='rescrape')
        actions2 = get_customer_app_actions(customer2.id, '2.0.0')
        assert actions2 == ({'actions': ['force_upgrade', 'force_logout', 'rescrape']})
        # create customer with all three actions completed, should not return anything
        customer3 = CustomerFactory()
        CustomerAppAction.objects.create(
            customer=customer3, action='force_logout', is_completed=True
        )
        CustomerAppAction.objects.create(
            customer=customer3, action='force_upgrade', is_completed=True
        )
        CustomerAppAction.objects.create(customer=customer3, action='rescrape', is_completed=True)
        actions3 = get_customer_app_actions(customer3.id)
        assert actions3 == ({'actions': None})
        # create customer with force upgrade, simulate new app relogin, test for is_completed True and no action
        customer4 = CustomerFactory()
        CustomerAppAction.objects.create(customer=customer4, action='force_upgrade')
        actions4 = get_customer_app_actions(customer4.id, '99.9.9')
        cust_action_4 = CustomerAppAction.objects.get_or_none(
            customer=customer4, action='force_upgrade', is_completed=True
        )
        assert cust_action_4
        assert actions4 == ({'actions': None})


class TestFunctions(object):

    # def test_convert_credit_score(self):
    #     test_cases = ((0.3, 350, 800, 485),
    #                   (0, 350, 800, 350),
    #                   (1, 350, 800, 800),
    #                   (0.9, 350, 800, 755),
    #                   (1, 1, 100, 100))
    #
    #     for score, min_resulting_score, max_resulting_score, expected_score in test_cases:
    #         calculated_score = convert_credit_score(score, min_resulting_score, max_resulting_score)
    #         assert calculated_score == expected_score
    #
    # def test_get_product_selections_by_checks(self):
    #     all_checks = [
    #         'application_date_of_birth',
    #         'job_not_black_listed',
    #         'form_partial_location',
    #         'scraped_data_existence',
    #         'form_partial_income',
    #         'fraud_form_partial_device',
    #         'fraud_form_partial_hp_own',
    #         'fraud_form_partial_hp_kin',
    #         'email_delinquency_24_months',
    #         'email_rejection_30_days',
    #         'sms_delinquency_24_months',
    #         'sms_rejection_30_days',
    #     ]
    #
    #     grab_bypass_checks = [
    #         'email_delinquency_24_months',
    #         'email_rejection_30_days',
    #         'sms_delinquency_24_months',
    #         'sms_rejection_30_days',
    #     ]
    #
    #     test_cases = (([], [10, 20, 30, 40, 50]),
    #                   (all_checks, [30]),
    #                   (grab_bypass_checks, [30, 50]))
    #
    #     for failed_checks, expected_pl in test_cases:
    #         result_pl = get_product_selections_by_checks(failed_checks)
    #         assert result_pl == expected_pl
    #
    # def test_get_product_selections_by_score(self):
    #     test_cases = ((0, []),
    #                   (0.1, [10, 20, 30, 40, 50]),
    #                   (0.3, [10, 20, 30, 40, 50]),
    #                   (0.5, [10, 20, 30, 40, 50]),
    #                   (1, []))
    #
    #     for score, expected_pl in test_cases:
    #         result_pl = get_product_selections_by_score(score)
    #         assert result_pl == expected_pl
    #
    # def test_convert_to_credit_grade(self):
    #     test_cases = [
    #         (0.89, "A-"),
    #         (0.90, "A-"),
    #         (0.91, "A"),
    #         (1, "A"),
    #     ]
    #     for score, expected_grade in test_cases:
    #         actual_grade = convert_to_credit_grade(score)
    #         assert actual_grade == expected_grade
    pass


# @patch ('juloserver.julo.models.CreditScore')
# @patch ('juloserver.julo.models.Application')
# @patch ('juloserver.apiv2.models.PdCreditModelResult')
# @patch ('juloserver.apiv2.models.AutoDataCheck')
class TestCreditScore2(object):
    def test_credit_score2(self):
        class DummyApplication(object):
            id = 2000000001
            customer = 1000000001
            device = 'testdevice'
            application_status = 100
            product_line = 10
            loan_amount_request = 2000000
            loan_duration_request = 4
            loan_purpose = 'PENDIDIKAN'
            loan_purpose_desc = 'Biaya pendidikan'
            marketing_source = 'Facebook'
            referral_code = ''
            is_own_phone = True
            fullname = 'test name'
            dob = '1989-02-19'
            gender = 'Wanita'
            ktp = '3271065902890002'
            address_street_num = 12
            address_provinsi = 'Jawa Barat'
            address_kabupaten = 'Bogor'
            address_kecamatan = 'Tanah Sareal'
            address_kelurahan = 'Kedung Badak'
            address_kodepos = '16164'
            occupied_since = '2014-02-01'
            home_status = ''
            landlord_mobile_phone = ''
            mobile_phone_1 = '081218926858'
            has_whatsapp_1 = True
            mobile_phone_2 = ''
            has_whatsapp_2 = ''
            email = 'febby@julofinance.com'
            bbm_pin = ''
            twitter_username = ''
            instagram_username = ''
            marital_status = ''
            dependent = 3
            spouse_name = 'spouse name'
            spouse_dob = '1990-02-02'
            spouse_mobile_phone = '0811144247'
            spouse_has_whatsapp = True
            kin_name = 'kin name'
            kin_dob = '1990-02-02'
            kin_gender = 'Pria'
            kin_mobile_phone = '08777788929'
            kin_relationship = ''
            job_type = 'Pegawai swasta'
            job_industry = ''
            job_function = ''
            job_description = ''
            company_name = ''
            company_phone_number = ''
            work_kodepos = ''
            job_start = '2015-11-02'
            monthly_income = 4000000
            income_1 = 3500000
            income_2 = 500000
            income_3 = 200000
            last_education = 'SMA'
            college = ''
            major = ''
            graduation_year = '2007'
            gpa = '2.84'
            has_other_income = True
            other_income_amount = 200000
            other_income_source = ''
            monthly_housing_cost = 1000000
            monthly_expenses = 2000000
            total_current_debt = 230000
            vehicle_type_1 = 'Sepeda Motor'
            vehicle_ownership_1 = 'Mencicil'
            bank_name = 'BCA'
            bank_branch = 'sudirman'
            bank_account_number = '1234567890'
            is_term_accepted = True
            is_verification_agreed = True
            is_document_submitted = None
            is_sphp_signed = None
            sphp_exp_date = '2017-09-08'
            application_xid = 3
            app_version = ''

        class MockCreditScore(object):
            id = 1
            application = DummyApplication()

            score = 'B+'
            message = 'test message'
            products_str = [10, 20, 30, 40, 50]

            def get_or_none(self, app_id=None):
                return 'A'

        class MockCreditModelResult(object):
            id = 1

            cdate = timezone.localtime(timezone.now())
            application_id = 2000000001
            customer_id = 1000000001

            version = 1
            probability_fpd = 0.65

            def filter(self, application_id=None):
                return MockCreditModelResult()

            def last(self):
                return None

        # test getting v1 creditscore
        with patch.object(CreditScore.objects, 'get_or_none', return_value=MockCreditScore()):
            creditscore = get_credit_score2(2000000001)
            assert creditscore is not None
        # test getting nonexisting creditmodelresult
        with patch.object(CreditScore.objects, 'get_or_none', return_value=None):
            with patch.object(
                PdCreditModelResult.objects, 'filter', return_value=MockCreditModelResult()
            ):
                creditscore2 = get_credit_score2(2000000001)
                assert creditscore2 is None


class TestCustomCreditMatrix(APITestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory()
        self.credit_matrix = CreditMatrixFactory()

    def test_evaluate_custom_logic(self):
        test_cases = [
            (
                u'job_industry:banking or repeat_time:>3',
                {'repeat_time': 4, 'job_industry': 'banking'},
                True,
            ),
            (
                u'job_industry:banking and repeat_time:>3',
                {'repeat_time': 4, 'job_industry': 'banking'},
                True,
            ),
            (
                u'job_industry:banking or repeat_time:>3',
                {'repeat_time': 0, 'job_industry': 'banking'},
                True,
            ),
            (
                u'job_industry:banking and repeat_time:>3',
                {'repeat_time': 0, 'job_industry': 'banking'},
                False,
            ),
            (
                u'job_industry:banking or repeat_time:>3',
                {'repeat_time': 4, 'job_industry': 'health'},
                True,
            ),
            (
                u'job_industry:banking and repeat_time:>3',
                {'repeat_time': 4, 'job_industry': 'health'},
                False,
            ),
            (
                u'job_industry:banking or repeat_time:>3',
                {'repeat_time': 0, 'job_industry': 'health'},
                False,
            ),
            (
                u'job_industry:banking and repeat_time:>3',
                {'repeat_time': 0, 'job_industry': 'health'},
                False,
            ),
        ]
        for rule, customer_data, expected_result in test_cases:
            assert evaluate_custom_logic(rule, customer_data) is expected_result

    @mock.patch('juloserver.apiv2.services.evaluate_custom_logic')
    def test_queryset_custom_matrix_processing(self, mocked_logic_fnct):
        credit_list = []
        for i in range(4):
            credit_mock = mock.MagicMock(spec=CreditMatrix)
            credit_mock.id = i + 1
            credit_mock.parameter = u'job_industry:banking or repeat_time:>3'
            credit_list.append(credit_mock)
        self.query_set = QuerySetMock(
            CreditMatrix, credit_list[0], credit_list[1], credit_list[2], credit_list[3]
        )
        data_1 = {'repeat_time': 4, 'job_industry': 'banking'}
        mocked_logic_fnct.return_value.side_effect = [True, False, True]
        query_set = queryset_custom_matrix_processing(self.query_set, data_1)
        self.assertIsNotNone(query_set)

    @mock.patch('juloserver.apiv2.credit_matrix2.get_salaried')
    @mock.patch('juloserver.apiv2.services.queryset_custom_matrix_processing')
    def test_get_credit_matrix(self, mocked_processing, mocked_salaried):
        credit_list = []
        for i in range(4):
            credit_mock = mock.MagicMock(spec=CreditMatrix)
            credit_mock.id = i + 1
            credit_mock.parameter = u'job_industry:banking or repeat_time:>3'
            credit_list.append(credit_mock)
        self.query_set = QuerySetMock(
            CreditMatrix, credit_list[0], credit_list[1], credit_list[2], credit_list[3]
        )
        mocked_set = mock.MagicMock(side_effect=CreditMatrix())
        mocked_set.order_by.return_value = self.credit_matrix
        mocked_processing.return_value = (mocked_set, True)
        mocked_salaried.return_value = True
        parameters = {
            'repeat_time': 0,
            'job_type': u'Pegawai swasta',
            'credit_matrix_type': 'julo',
            'job_industry': u'banking',
            'score': u'A-',
            'is_premium_area': True,
            'score_tag': None,
        }
        credit_matrix_1 = get_credit_matrix(parameters)
        mocked_processing.return_value = (mocked_set, False)
        credit_matrix_2 = get_credit_matrix(parameters)
        self.assertIsNotNone(credit_matrix_1)
        self.assertIsNotNone(credit_matrix_2)

    @mock.patch('juloserver.apiv2.credit_matrix2.get_credit_matrix')
    def test_get_good_score(self, mocked_credit_matrix):
        custom_parameter = {'repeat_time': 0, 'job_industry': u'banking'}
        probabilty = 0.9
        job_type = u'Bank'
        mocked_credit_matrix.return_value = self.credit_matrix
        is_premium_area = False
        is_fdc = False
        score = get_good_score(probabilty, job_type, custom_parameter, is_premium_area, is_fdc)
        self.assertIsNotNone(score)

    @mock.patch('juloserver.apiv2.services.AutoDataCheck.objects')
    def test_is_premium_area(self, mocked_query):
        class MockAutoDataCheck(object):
            is_okay = True

        application = self.application
        mocked_query.filter.return_value.last.return_value = MockAutoDataCheck
        response = is_inside_premium_area(application.id)
        self.assertTrue(response)


class TestCalculationFDCLoan(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.today = timezone.localtime(timezone.now()).date()
        self.fdc_inquiry = FDCInquiryFactory(
            application_id=self.application.id,
            customer_id=self.customer.id,
            inquiry_date=self.today,
        )

    def create_data_loan_factory(self, list_data):

        for data in list_data:
            FDCInquiryLoanFactory(
                fdc_inquiry_id=self.fdc_inquiry.id, dpd_terakhir=data, tgl_pelaporan_data=self.today
            )

    def test_data_result_total_credit(self):

        # create data row
        list_data = [0, 5, 31, 91]
        self.create_data_loan_factory(list_data)
        total_credit, total_bad_credit = calculate_total_credit(
            self.fdc_inquiry, self.application.id
        )
        self.assertEqual(total_credit, len(list_data))
        self.assertEqual(total_bad_credit, 1)

    def test_data_is_result_is_empty(self):
        total_credit, total_bad_credit = calculate_total_credit(
            self.fdc_inquiry, self.application.id
        )
        self.assertEqual(total_credit, 0)
        self.assertEqual(total_bad_credit, 0)

    def test_data_result_total_credit_some_case(self):

        # create data row
        list_data = [0, 5, 30, 50, 60, 90, 91, 100]
        self.create_data_loan_factory(list_data)
        total_credit, total_bad_credit = calculate_total_credit(
            self.fdc_inquiry, self.application.id
        )
        self.assertEqual(total_credit, len(list_data))
        self.assertEqual(total_bad_credit, 2)


class TestGenerateCreditScore(TestCase):
    def setUp(self):

        self.customer = CustomerFactory()
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.FORM_PARTIAL,
            )
        )
        self.credit_score = CreditScoreFactory(
            application_id=self.application.id,
            score='C',
        )
        self.pd_credit_model_score = PdCreditModelResultFactory(
            application_id=self.application.id, pgood=0.49
        )
        self.etl_status = EtlStatusFactory(
            application_id=self.application.id,
            executed_tasks=[
                'dsd_extract_zipfile_task,' 'dsd_sms_parse_task,' 'dsd_phonebook_parse_task'
            ],
            meta_data=['folder_path:1'],
        )
        self.customer_app_action = CustomerAppActionFactory(
            customer_id=self.customer.id, action='rescrape', is_completed=True
        )
        WorkflowStatusPathFactory(
            status_previous=105,
            status_next=106,
            type='happy',
            is_active=True,
            workflow=self.workflow_j1,
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name='trigger_rescrape_and_force_logout',
            parameters={
                'rescrape': True,
                'force_logout': False,
            },
            is_active=True,
        )
        self.application_history = ApplicationHistoryFactory(
            status_old=ApplicationStatusCodes.FORM_CREATED,
            status_new=ApplicationStatusCodes.FORM_PARTIAL,
            application_id=self.application.id,
        )

    @patch(
        'juloserver.application_flow.services2.credit_score_dsd.process_application_status_change'
    )
    @patch('django.utils.timezone.now')
    def test_case_success_generate_credit_score_not_move_106(
        self, mock_timezone, mock_process_status_change
    ):

        now = datetime(2024, 6, 12, 11, 0, 0)
        mock_timezone.return_value = now
        get_today = timezone.localtime(timezone.now())
        cdate_action = get_today - timedelta(hours=1)
        cdate_app = get_today - timedelta(hours=2)

        self.application.update_safely(cdate=cdate_app)
        self.customer_app_action.update_safely(
            cdate=cdate_action,
            is_completed=False,
        )

        self.pd_credit_model_score.delete()
        self.credit_score.delete()
        self.etl_status.delete()

        # check status condition
        result, flag, message = general_check_for_scoring(self.application, is_need_to_moved=True)
        self.assertFalse(result)
        self.assertEqual(flag, ApplicationDsdMessageConst.FLAG_WAIT_FEW_HOURS)

        generate_credit_score()
        mock_process_status_change.assert_not_called()

    @patch('juloserver.application_flow.services2.credit_score_dsd.hit_ana_server_without_dsd')
    @patch(
        'juloserver.application_flow.services2.credit_score_dsd.process_application_status_change',
        return_value=True,
    )
    @patch('django.utils.timezone.now')
    def test_case_skip_the_process_more_than_12_hours(
        self,
        mock_timezone,
        mock_process_status_change,
        mock_anaserver_dsd,
    ):

        now = datetime(2024, 6, 12, 11, 0, 0)
        mock_timezone.return_value = now
        get_today = timezone.localtime(timezone.now())
        cdate_action = get_today - timedelta(hours=13)
        cdate_app = get_today - timedelta(hours=15)
        cdate_app_history = cdate_app + timedelta(minutes=10)

        self.application.update_safely(cdate=cdate_app)
        self.application_history.update_safely(cdate=cdate_app_history)
        self.customer_app_action.update_safely(
            cdate=cdate_action,
            is_completed=False,
        )
        self.customer.update_safely(can_reapply=True)

        self.pd_credit_model_score.delete()
        self.credit_score.delete()
        self.etl_status.delete()

        # check status condition
        result, flag, message = general_check_for_scoring(self.application, is_need_to_moved=True)
        self.assertFalse(result)
        self.assertEqual(flag, ApplicationDsdMessageConst.FLAG_NOT_AVAILABLE_FDC)

        generate_credit_score()
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.can_reapply)
        self.assertIsNotNone(self.customer.can_reapply_date)

        # for application JTurbo should be didnt hit anaserver
        self.application.update_safely(
            workflow=WorkflowFactory(name=WorkflowConst.JULO_STARTER),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.JULO_STARTER),
        )

        # check status condition
        result, flag, message = general_check_for_scoring(self.application, is_need_to_moved=True)
        self.assertFalse(result)
        self.assertEqual(flag, ApplicationDsdMessageConst.FLAG_NOT_AVAILABLE_FDC)

        generate_credit_score()
        mock_anaserver_dsd.assert_not_called()

    @patch('juloserver.application_flow.services2.credit_score_dsd.hit_ana_server_without_dsd')
    @patch(
        'juloserver.application_flow.services2.credit_score_dsd.check_fdc_data',
        return_value=(True, None),
    )
    @patch(
        'juloserver.application_flow.services2.credit_score_dsd.process_application_status_change'
    )
    @patch('django.utils.timezone.now')
    def test_case_skip_the_process_more_than_12_hours_hit_ana_server(
        self,
        mock_timezone,
        mock_process_status_change,
        mock_fdc,
        mock_hit_ana_server_dsd,
    ):
        now = datetime(2024, 6, 12, 11, 0, 0)
        mock_timezone.return_value = now
        get_today = timezone.localtime(timezone.now())
        cdate_action = get_today - timedelta(hours=13)
        cdate_app = get_today - timedelta(hours=15)

        self.application.update_safely(cdate=cdate_app)
        self.customer_app_action.update_safely(
            cdate=cdate_action,
            is_completed=False,
        )

        self.pd_credit_model_score.delete()
        self.credit_score.delete()
        self.etl_status.delete()

        # check status condition
        result, flag, message = general_check_for_scoring(self.application, is_need_to_moved=True)
        self.assertTrue(result)
        self.assertEqual(flag, ApplicationDsdMessageConst.FLAG_SUCCESS_ALL_CHECK)

        generate_credit_score()
        mock_process_status_change.assert_not_called()
        assert mock_hit_ana_server_dsd.called
        customer_app_action = CustomerAppAction.objects.filter(customer=self.customer)
        self.assertEqual(customer_app_action.count(), 1)

    @patch('juloserver.application_flow.services2.credit_score_dsd.hit_ana_server_without_dsd')
    @patch(
        'juloserver.application_flow.services2.credit_score_dsd.check_fdc_data',
        return_value=(True, None),
    )
    @patch(
        'juloserver.application_flow.services2.credit_score_dsd.process_application_status_change'
    )
    @patch('django.utils.timezone.now')
    def test_case_not_have_customer_app_action(
        self,
        mock_timezone,
        mock_process_status_change,
        mock_fdc,
        mock_hit_ana_server_dsd,
    ):
        now = datetime(2024, 6, 12, 11, 0, 0)
        mock_timezone.return_value = now
        get_today = timezone.localtime(timezone.now())
        cdate_action = get_today - timedelta(hours=13)
        cdate_app = get_today - timedelta(hours=15)

        self.application.update_safely(cdate=cdate_app)
        self.customer_app_action.delete()

        self.pd_credit_model_score.delete()
        self.credit_score.delete()
        self.etl_status.delete()

        # check status condition
        result, flag, message = general_check_for_scoring(self.application, is_need_to_moved=True)
        self.assertFalse(result)
        self.assertEqual(flag, ApplicationDsdMessageConst.FLAG_WAIT_FEW_MINUTES)

        generate_credit_score()
        mock_process_status_change.assert_not_called()
        mock_hit_ana_server_dsd.assert_not_called()
        customer_app_action = CustomerAppAction.objects.filter(
            customer=self.customer, action='rescrape'
        )
        self.assertEqual(customer_app_action.count(), 1)
