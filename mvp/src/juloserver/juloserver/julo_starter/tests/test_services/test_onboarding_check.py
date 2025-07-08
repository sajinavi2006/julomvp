import pytest
import mock

from datetime import date, timedelta
from mock import patch
from requests.models import Response
from rest_framework.test import APIClient, APITestCase

import juloserver.julo_starter.services.onboarding_check
from juloserver.bpjs.tests.factories import BpjsApiLogFactory
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    CustomerFactory,
    MobileFeatureSettingFactory,
    FDCInquiryFactory,
    FDCInquiryLoanFactory,
    OnboardingEligibilityCheckingFactory,
    DeviceFactory,
    FeatureSettingFactory,
    WorkflowFactory,
    StatusLookupFactory,
    ProductLineFactory,
    AddressGeolocationFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.julo.constants import (
    WorkflowConst,
    ProductLineCodes,
)
from juloserver.julo_starter.services.onboarding_check import *
from juloserver.julo_starter.tasks.eligibility_tasks import *
from django.test.testcases import TestCase
from juloserver.julo_starter.services.onboarding_check import is_email_for_whitelists


class TestEligibilityChecking(APITestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, nik=3173051512980141)
        self.mfs = MobileFeatureSettingFactory(feature_name='bpjs_direct')
        self.fdc_inquiry = FDCInquiryFactory(customer_id=self.customer.id)
        self.onboarding_check = OnboardingEligibilityCheckingFactory(
            customer=self.customer,
            fdc_inquiry_id=self.fdc_inquiry.id,
        )
        self.device = DeviceFactory(customer=self.customer)
        FeatureSettingFactory(feature_name='bpjs_mock_response_set', is_active=False)
        FeatureSettingFactory(feature_name='fdc_mock_response_set', is_active=False)

    @patch(
        'juloserver.julo_starter.services.onboarding_check.get_config_sphinx_no_bpjs',
        return_value=True,
    )
    def test_check_process_eligibility(self, mocking_get_config_sphinx_no_bpjs):
        customer_id = self.customer.id

        self.onboarding_check.fdc_check = 1
        self.onboarding_check.save()

        # case if feature setting is active
        response = check_process_eligible(customer_id)
        assert response['process_eligibility_checking'] == 'finished'
        assert response['is_eligible'] == 'passed'

        self.onboarding_check.fdc_check = 3
        self.onboarding_check.save()

        response = check_process_eligible(customer_id)
        assert response['process_eligibility_checking'] == 'finished'
        assert response['is_eligible'] == 'offer_regular'

        self.onboarding_check.fdc_check = 2
        self.onboarding_check.save()

        response = check_process_eligible(customer_id)
        assert response['process_eligibility_checking'] == 'finished'
        assert response['is_eligible'] == 'not_passed'

        self.onboarding_check.delete()

        response = check_process_eligible(customer_id)
        assert response['process_eligibility_checking'] == 'no_data'
        assert response['is_eligible'] == 'no_data'

    @patch('juloserver.julo_starter.services.onboarding_check.verify_nik')
    def test_process_eligibility_checking(self, mock_verify):
        eligible = eligibility_checking(self.customer)
        mock_verify.return_value = True
        assert eligible == True

        eligible = eligibility_checking(None)
        assert eligible == False

    @pytest.mark.skip(reason="Flaky")
    @patch('juloserver.julo_starter.services.onboarding_check.get_and_save_fdc_data')
    def test_process_eligibility_check_fdc(self, mock_fdc):
        # case no fdc
        self.fdc_inquiry.status = "Not Found"
        self.fdc_inquiry.save()

        fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.customer.nik}
        onboarding_checking = process_eligibility_check(fdc_inquiry_data, 1, 0)
        mock_fdc.return_value = True

        assert onboarding_checking.fdc_check == 3

        # case fpd good
        self.fdc_inquiry.status = "Found"
        self.fdc_inquiry.save()

        fdc_inquiry_loan = FDCInquiryLoanFactory(fdc_inquiry_id=self.fdc_inquiry.id)
        fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.customer.nik}

        onboarding_checking = process_eligibility_check(fdc_inquiry_data, 1, 0)
        mock_fdc.return_value = True

        assert onboarding_checking.fdc_check == 1

        # case dpd macet
        fdc_inquiry_loan = FDCInquiryLoanFactory(
            fdc_inquiry_id=self.fdc_inquiry.id,
            kualitas_pinjaman='Macet (>90)',
            dpd_terakhir=91,
        )
        fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.customer.nik}

        onboarding_checking = process_eligibility_check(fdc_inquiry_data, 1, 0)
        mock_fdc.return_value = True

        assert onboarding_checking.fdc_check == 2

        # case dpd tidak lancar
        fdc_inquiry_loan = FDCInquiryLoanFactory(
            fdc_inquiry_id=self.fdc_inquiry.id,
            kualitas_pinjaman='Tidak Lancar (30 sd 90 hari)',
            dpd_terakhir=30,
        )
        fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.customer.nik}

        onboarding_checking = process_eligibility_check(
            fdc_inquiry_data,
            1,
            0,
        )
        mock_fdc.return_value = True

        assert onboarding_checking.fdc_check == 2

        # case fail jatuh tempo & sisa pinjaman berjalan
        fdc_inquiry_loan = FDCInquiryLoanFactory(
            fdc_inquiry_id=self.fdc_inquiry.id,
            kualitas_pinjaman='Lancar (<30 hari)',
            tgl_jatuh_tempo_pinjaman=date.today() - timedelta(days=1),
            sisa_pinjaman_berjalan=100000,
            dpd_terakhir=0,
        )
        fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.customer.nik}

        onboarding_checking = process_eligibility_check(
            fdc_inquiry_data,
            1,
            0,
        )
        mock_fdc.return_value = True

        assert onboarding_checking.fdc_check == 2

    def test_process_eligibility_check_for_jturbo_j360(self):
        application = ApplicationFactory(customer=self.customer)
        onboarding_checking = process_eligibility_check(
            fdc_inquiry_data={},
            reason=1,
            retry=0,
            is_fdc_eligible=False,
            customer_id=self.customer.id,
            application_id=application.id,
        )
        self.assertEqual(onboarding_checking.customer_id, self.customer.id)
        self.assertEqual(onboarding_checking.fdc_check, None)

    # @patch('juloserver.julo_starter.services.onboarding_check.retrieve_and_store_bpjs_direct')
    # @patch('juloserver.julo_starter.services.onboarding_check.get_and_save_fdc_data')
    # def test_process_eligibility_check_bpjs(self, mock_fdc, mock_bpjs):
    #     # case bpjs good
    #     self.fdc_inquiry.status = "Found"
    #     self.fdc_inquiry.save()
    #
    #     fdc_inquiry_loan = FDCInquiryLoanFactory(
    #         fdc_inquiry_id=self.fdc_inquiry.id,
    #         tgl_jatuh_tempo_pinjaman=date.today(),
    #         sisa_pinjaman_berjalan=0,
    #         dpd_terakhir=0,
    #     )
    #     fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.customer.nik}
    #
    #     response = (
    #         b"{'ret': '0', 'msg': 'Sukses',"
    #         b"'score': {'namaLengkap': 'TIDAK SESUAI',"
    #         b"'nomorIdentitas': 'SESUAI', 'tglLahir': 'TIDAK SESUAI',"
    #         b"'jenisKelamin': 'SESUAI', 'handphone': '', 'email': '',"
    #         b"'namaPerusahaan': 'TIDAK SESUAI', 'paket': 'SESUAI',"
    #         b"'upahRange': 'TIDAK SESUAI', 'blthUpah': 'TIDAK SESUAI'},"
    #         b"'CHECK_ID': '22110800574994'}"
    #     )
    #     bpjs_log = BpjsApiLogFactory(customer=self.customer, response=response)
    #
    #     onboarding_checking = process_eligibility_check(fdc_inquiry_data, 1, 0)
    #     mock_fdc.return_value = True
    #     mock_bpjs.return_value = response
    #
    #     assert onboarding_checking.bpjs_check == 1
    #
    #     # case bpjs bad
    #     self.fdc_inquiry.status = "Found"
    #     self.fdc_inquiry.save()
    #
    #     fdc_inquiry_loan = FDCInquiryLoanFactory(
    #         fdc_inquiry_id=self.fdc_inquiry.id,
    #         tgl_jatuh_tempo_pinjaman=date.today(),
    #         sisa_pinjaman_berjalan=0,
    #         dpd_terakhir=0,
    #     )
    #     fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.customer.nik}
    #
    #     response = (
    #         b"{'ret': '0', 'msg': 'Sukses',"
    #         b"'score': {'namaLengkap': 'TIDAK SESUAI',"
    #         b"'nomorIdentitas': 'SESUAI', 'tglLahir': 'TIDAK SESUAI',"
    #         b"'jenisKelamin': 'SESUAI', 'handphone': '', 'email': '',"
    #         b"'namaPerusahaan': 'TIDAK SESUAI', 'paket': 'SESUAI',"
    #         b"'upahRange': 'SESUAI', 'blthUpah': 'TIDAK SESUAI'},"
    #         b"'CHECK_ID': '22110800574994'}"
    #     )
    #     bpjs_log = BpjsApiLogFactory(customer=self.customer, response=response)
    #
    #     onboarding_checking = process_eligibility_check(fdc_inquiry_data, 1, 0)
    #     mock_fdc.return_value = True
    #
    #     mock_bpjs.return_value = response
    #
    #     assert onboarding_checking.bpjs_check == 2
    #
    #     # case bpjs not found
    #     self.fdc_inquiry.status = "Found"
    #     self.fdc_inquiry.save()
    #
    #     fdc_inquiry_loan = FDCInquiryLoanFactory(
    #         fdc_inquiry_id=self.fdc_inquiry.id,
    #         tgl_jatuh_tempo_pinjaman=date.today(),
    #         sisa_pinjaman_berjalan=0,
    #         dpd_terakhir=0,
    #     )
    #     fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.customer.nik}
    #
    #     response = b"{'ret': '-2', 'msg': 'Data not Found'," b"'CHECK_ID': '22110800574994'}"
    #     bpjs_log = BpjsApiLogFactory(customer=self.customer, response=response)
    #
    #     onboarding_checking = process_eligibility_check(fdc_inquiry_data, 1, 0)
    #     mock_fdc.return_value = True
    #     mock_bpjs.return_value = response
    #
    #     assert onboarding_checking.bpjs_check == 3

    @patch('juloserver.julo_starter.services.onboarding_check.process_eligibility_check')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.trigger_eligibility_check_pn_subtask')
    def test_trigger_eligibility_check_pn_subtask(
        self, mock_trigger_eligibility_check_pn_subtask, mock_process_run_eligibility_check
    ):
        mock_process_run_eligibility_check.return_value = self.onboarding_check
        fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.customer.nik}
        run_eligibility_check(fdc_inquiry_data, 1)
        mock_trigger_eligibility_check_pn_subtask.delay.assert_called_with(
            self.fdc_inquiry.customer_id
        )

    @patch('juloserver.julo_starter.services.onboarding_check.process_eligibility_check')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.trigger_eligibility_check_pn_subtask')
    def test_trigger_eligibility_check_not_send_pn_subtask(
        self, mock_trigger_eligibility_check_pn_subtask, mock_process_run_eligibility_check
    ):
        mock_process_run_eligibility_check.return_value = self.onboarding_check
        fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.customer.nik}
        run_eligibility_check(
            fdc_inquiry_data,
            1,
            customer_id=self.customer.id,
            application_id=None,
            is_send_pn=False,
        )
        mock_trigger_eligibility_check_pn_subtask.delay.assert_not_called()

    @patch('juloserver.julo_starter.services.onboarding_check.check_process_eligible')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.get_julo_pn_client')
    def test_trigger_eligibility_check_pn_subtask_payloads(
        self, mock_julo_pn_client, mock_check_process_eligible
    ):
        # pn for passed eligibility check
        mock_check_process_eligible.return_value = {
            'is_eligible': 'passed',
            'process_eligibility_checking': 'finished',
        }
        trigger_eligibility_check_pn_subtask(self.fdc_inquiry.customer_id)
        mock_julo_pn_client.return_value.pn_julo_starter_eligibility.assert_called_with(
            self.device.gcm_reg_id, 'pn_eligibility_ok'
        )

        # pn j1 offer eligibility check
        mock_check_process_eligible.return_value = {
            'is_eligible': 'offer_regular',
            'process_eligibility_checking': 'finished',
        }
        trigger_eligibility_check_pn_subtask(self.fdc_inquiry.customer_id)
        mock_julo_pn_client.return_value.pn_julo_starter_eligibility.assert_called_with(
            self.device.gcm_reg_id, 'pn_eligibility_j1_offer'
        )

        # pn for rejected eligibility check
        mock_check_process_eligible.return_value = {
            'is_eligible': 'not_passed',
            'process_eligibility_checking': 'finished',
        }
        trigger_eligibility_check_pn_subtask(self.fdc_inquiry.customer_id)
        mock_julo_pn_client.return_value.pn_julo_starter_eligibility.assert_called_with(
            self.device.gcm_reg_id, 'pn_eligbility_rejected'
        )

    # @patch('juloserver.julo_starter.services.onboarding_check.retrieve_and_store_bpjs_direct')
    # @patch('juloserver.julo_starter.services.onboarding_check.get_and_save_fdc_data')
    # def test_process_eligibility_for_j1_last_application(self, mock_fdc, mock_bpjs):
    #
    #     self.application = ApplicationFactory(
    #         customer=self.customer,
    #         workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
    #         product_line_code=ProductLineFactory(product_line_code=ProductLineCodes.J1),
    #     )
    #     self.application.update_safely(
    #         application_status_id=106,
    #     )
    #
    #     self.customer.can_reapply = True
    #     self.customer.save()
    #
    #     # case fdc is not good
    #     self.fdc_inquiry.status = "Not Found"
    #     self.fdc_inquiry.save()
    #
    #     fdc_inquiry_loan = FDCInquiryLoanFactory(
    #         fdc_inquiry_id=self.fdc_inquiry.id,
    #         tgl_jatuh_tempo_pinjaman=date.today(),
    #         sisa_pinjaman_berjalan=0,
    #         dpd_terakhir=0,
    #     )
    #     fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.customer.nik}
    #
    #     response = (
    #         b"{'ret': '0', 'msg': 'Sukses',"
    #         b"'score': {'namaLengkap': 'TIDAK SESUAI',"
    #         b"'nomorIdentitas': 'SESUAI', 'tglLahir': 'TIDAK SESUAI',"
    #         b"'jenisKelamin': 'SESUAI', 'handphone': '', 'email': '',"
    #         b"'namaPerusahaan': 'TIDAK SESUAI', 'paket': 'SESUAI',"
    #         b"'upahRange': 'TIDAK SESUAI', 'blthUpah': 'TIDAK SESUAI'},"
    #         b"'CHECK_ID': '22110800574994'}"
    #     )
    #     bpjs_log = BpjsApiLogFactory(customer=self.customer, response=response)
    #
    #     onboarding_checking = process_eligibility_check(fdc_inquiry_data, 1, 0)
    #     mock_fdc.return_value = True
    #     mock_bpjs.return_value = response
    #
    #     self.customer.refresh_from_db()
    #     # keep result from can_reapply should be True
    #     self.assertTrue(self.customer.can_reapply)
    #
    #     # case bpjs bad
    #     self.fdc_inquiry.status = "Found"
    #     self.fdc_inquiry.save()
    #
    #     fdc_inquiry_loan = FDCInquiryLoanFactory(
    #         fdc_inquiry_id=self.fdc_inquiry.id,
    #         tgl_jatuh_tempo_pinjaman=date.today(),
    #         sisa_pinjaman_berjalan=0,
    #         dpd_terakhir=0,
    #     )
    #     fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.customer.nik}
    #
    #     response = (
    #         b"{'ret': '0', 'msg': 'Sukses',"
    #         b"'score': {'namaLengkap': 'TIDAK SESUAI',"
    #         b"'nomorIdentitas': 'SESUAI', 'tglLahir': 'TIDAK SESUAI',"
    #         b"'jenisKelamin': 'SESUAI', 'handphone': '', 'email': '',"
    #         b"'namaPerusahaan': 'TIDAK SESUAI', 'paket': 'SESUAI',"
    #         b"'upahRange': 'SESUAI', 'blthUpah': 'TIDAK SESUAI'},"
    #         b"'CHECK_ID': '22110800574994'}"
    #     )
    #     bpjs_log = BpjsApiLogFactory(customer=self.customer, response=response)
    #
    #     onboarding_checking = process_eligibility_check(fdc_inquiry_data, 1, 0)
    #     mock_fdc.return_value = True
    #
    #     mock_bpjs.return_value = response
    #
    #     self.assertEqual(onboarding_checking.bpjs_check, 2)
    #     self.customer.refresh_from_db()
    #     # keep result from can_reapply should be True
    #     self.assertTrue(self.customer.can_reapply)
    #
    #     # case bpjs not found
    #     self.fdc_inquiry.status = "Found"
    #     self.fdc_inquiry.save()
    #
    #     fdc_inquiry_loan = FDCInquiryLoanFactory(
    #         fdc_inquiry_id=self.fdc_inquiry.id,
    #         tgl_jatuh_tempo_pinjaman=date.today(),
    #         sisa_pinjaman_berjalan=0,
    #         dpd_terakhir=0,
    #     )
    #     fdc_inquiry_data = {'id': self.fdc_inquiry.id, 'nik': self.customer.nik}
    #
    #     response = b"{'ret': '-2', 'msg': 'Data not Found'," b"'CHECK_ID': '22110800574994'}"
    #     bpjs_log = BpjsApiLogFactory(customer=self.customer, response=response)
    #
    #     onboarding_checking = process_eligibility_check(fdc_inquiry_data, 1, 0)
    #     mock_fdc.return_value = True
    #     mock_bpjs.return_value = response
    #
    #     self.assertEqual(onboarding_checking.bpjs_check, 3)
    #     self.customer.refresh_from_db()
    #     # keep result from can_reapply should be True
    #     self.assertTrue(self.customer.can_reapply)


class TestWhiteListEmail(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, nik=3173051512980141)
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.JTURBO_BYPASS,
            is_active=True,
            parameters=[
                'testing+01@julofinance.com',
                'testing+02@julofinance.com',
            ],
        )

    def test_case_if_setting_is_not_active(self):
        self.fs.update_safely(is_active=False)
        self.customer.update_safely(email='testing@julofinance.com')

        result = is_email_for_whitelists(self.customer)
        self.assertFalse(result)

    def test_case_if_setting_is_active_success(self):
        self.customer.update_safely(email='testing+01@julofinance.com')

        result = is_email_for_whitelists(self.customer)
        self.assertTrue(result)

    def test_case_if_setting_is_active_failed(self):
        self.customer.update_safely(email='testing@julofinance.com')

        result = is_email_for_whitelists(self.customer)
        self.assertFalse(result)

    def test_case_if_setting_lower_case(self):
        self.customer.update_safely(email='Testing+01@julofinance.com')

        result = is_email_for_whitelists(self.customer)
        self.assertTrue(result)


class TestCheckBPJSandDukcapilForTurbo(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.status105 = StatusLookupFactory(status_code=105)
        starter_workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application = ApplicationFactory(customer=self.customer, workflow=starter_workflow)
        self.application.application_status = self.status105
        self.application.save()
        self.credit_model = PdCreditModelResultFactory(application_id=self.application.id)
        WorkflowStatusPathFactory(workflow=starter_workflow, status_previous=105, status_next=107)
        WorkflowStatusPathFactory(workflow=starter_workflow, status_previous=105, status_next=108)
        WorkflowStatusPathFactory(workflow=starter_workflow, status_previous=105, status_next=135)

    @patch(
        'juloserver.julo_starter.services.onboarding_check.check_dukcapil_for_turbo',
        return_value=True,
    )
    @patch(
        'juloserver.julo_starter.services.onboarding_check.check_bpjs_for_turbo',
    )
    @patch('juloserver.julo_starter.tasks.app_tasks.trigger_push_notif_check_scoring')
    def test_check_dukcapil_and_bpjs_flow(self, mock_pn, mock_bpjs_check, mock_dukcapil_check):
        # Case BPJS check = 1
        mock_bpjs_check.return_value = 1
        result = check_bpjs_and_dukcapil_for_turbo(self.application)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 108)

        # Case BPJS check = 2
        mock_bpjs_check.return_value = 2
        self.application.update_safely(application_status_id=105, refresh=True)
        result = check_bpjs_and_dukcapil_for_turbo(self.application)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 135)
        mock_pn.delay.assert_called_with(self.application.id, 'dukcapil_false')

    @patch('juloserver.julo_starter.tasks.app_tasks.trigger_push_notif_check_scoring')
    @patch(
        'juloserver.julo_starter.services.onboarding_check.check_dukcapil_for_turbo',
        return_value=True,
    )
    @patch('juloserver.julo_starter.services.onboarding_check.check_bpjs_for_turbo')
    def test_check_dukcapil_and_bpjs_flow_bpjs_not_found(
        self, mock_bpjs_check, mock_dukcapil_check, mock_pn
    ):
        # Setup Feature Setting
        fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.SPHINX_NO_BPJS_THRESHOLD,
            is_active=True,
            parameters={
                "holdout": 0,
                "high_score_operator": ">=",
                "high_score_threshold": 0.85,
                "medium_score_operator": ">",
                "medium_score_threshold": 0.8,
            },
        )

        # Case setup
        mock_bpjs_check.return_value = 3
        self.credit_model.pgood = 0.87
        self.credit_model.save()
        result = check_bpjs_and_dukcapil_for_turbo(self.application)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 108)

        # Offer to j1
        self.application.update_safely(application_status_id=105)
        self.credit_model.pgood = 0.79
        self.credit_model.save()
        result = check_bpjs_and_dukcapil_for_turbo(self.application)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 107)

        # Will proceed to holdout
        self.application.update_safely(application_status_id=105)
        self.credit_model.pgood = 0.83
        self.credit_model.save()
        result = check_bpjs_and_dukcapil_for_turbo(self.application)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 107)

        # Case if feature setting is not active
        fs.update_safely(is_active=False, refresh=True)
        self.application.update_safely(application_status_id=105)
        self.credit_model.pgood = 0.83
        self.credit_model.save()
        result = check_bpjs_and_dukcapil_for_turbo(self.application)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 107)

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]

    def increment_redis(self, key):
        increment = int(self.redis_data[key]) + 1
        return str(increment)

    @mock.patch('juloserver.application_flow.services.get_redis_client')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.trigger_pn_emulator_detection')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.process_fraud_check')
    @patch(
        'juloserver.julo_starter.services.onboarding_check.check_dukcapil_for_turbo',
        return_value=True,
    )
    def test_case_with_holdout_mechanism_for_108(
        self, mock_dukcapil, mock_fraud, mock_emulator_pn, mock_redis_client
    ):
        """
        Case with holdout is 30, So this representative for:
        30% from population will go proceed binary check
        70% from population will go proceed to offer j1
        """

        from juloserver.application_flow.constants import CacheKey

        self.redis_data = {}

        fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.SPHINX_NO_BPJS_THRESHOLD,
            is_active=True,
            parameters={
                "holdout": 30,
                "high_score_operator": ">=",
                "high_score_threshold": 0.85,
                "medium_score_operator": ">",
                "medium_score_threshold": 0.8,
            },
        )

        OnboardingEligibilityCheckingFactory(
            customer=self.customer,
            application=self.application,
            fdc_check=1,
            bpjs_check=3,
        )
        mock_fraud.return_value = False

        # set redis
        redis_mock = mock.MagicMock()
        redis_mock.set.side_effect = self.set_redis(CacheKey.BPJS_NO_FOUND_HOLDOUT_COUNTER, "1")
        redis_mock.get.side_effect = self.get_redis(
            CacheKey.BPJS_NO_FOUND_HOLDOUT_COUNTER,
        )
        redis_mock.increment.side_effect = self.increment_redis(
            CacheKey.BPJS_NO_FOUND_HOLDOUT_COUNTER,
        )
        mock_redis_client.return_value = redis_mock

        # counter 3
        self.application.update_safely(application_status_id=105, refresh=True)
        self.credit_model.pgood = 0.83
        self.credit_model.save()
        result = check_bpjs_and_dukcapil_for_turbo(self.application)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 108)

    @mock.patch('juloserver.application_flow.services.get_redis_client')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.trigger_pn_emulator_detection')
    @patch('juloserver.julo_starter.tasks.eligibility_tasks.process_fraud_check')
    @patch(
        'juloserver.julo_starter.services.onboarding_check.check_dukcapil_for_turbo',
        return_value=True,
    )
    def test_case_with_holdout_mechanism_for_offfer_to_j1(
        self, mock_dukcapil, mock_fraud, mock_emulator_pn, mock_redis_client
    ):
        """
        Case with holdout is 30, So this representative for:
        30% from population will go proceed binary check
        70% from population will go proceed to offer j1
        """

        from juloserver.application_flow.constants import CacheKey

        self.redis_data = {}
        fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.SPHINX_NO_BPJS_THRESHOLD,
            is_active=True,
            parameters={
                "holdout": 30,
                "high_score_operator": ">=",
                "high_score_threshold": 0.85,
                "medium_score_operator": ">",
                "medium_score_threshold": 0.8,
            },
        )

        OnboardingEligibilityCheckingFactory(
            customer=self.customer,
            application=self.application,
            fdc_check=1,
            bpjs_check=3,
        )
        mock_fraud.return_value = False

        # set redis
        redis_mock = mock.MagicMock()
        redis_mock.set.side_effect = self.set_redis(CacheKey.BPJS_NO_FOUND_HOLDOUT_COUNTER, "3")
        redis_mock.get.side_effect = self.get_redis(
            CacheKey.BPJS_NO_FOUND_HOLDOUT_COUNTER,
        )
        redis_mock.increment.side_effect = self.increment_redis(
            CacheKey.BPJS_NO_FOUND_HOLDOUT_COUNTER,
        )
        mock_redis_client.return_value = redis_mock

        self.application.update_safely(application_status_id=105, refresh=True)
        self.credit_model.pgood = 0.83
        self.credit_model.save()
        result = check_bpjs_and_dukcapil_for_turbo(self.application)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 107)
