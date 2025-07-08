import mock
import requests
import unittest

from django.conf import settings
from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.channeling_loan.clients import (
    get_bss_channeling_client,
    get_bss_va_client,
)
from juloserver.channeling_loan.constants import (
    BSSDataField,
    FeatureNameConst as ChannelingFeatureNameConst,
    ChannelingConst,
    ChannelingStatusConst,
    BSSChannelingConst,
)
from juloserver.channeling_loan.services.bss_services import (
    change_city_to_dati_code,
    construct_bss_customer_data,
    reconstruct_response_format,
    replace_special_chars_for_fields,
    send_loan_for_channeling_to_bss,
    check_disburse_transaction,
    construct_bss_disbursement_data,
    sanitize_bss_disbursement_data,
)
from juloserver.channeling_loan.models import (
    ChannelingLoanStatus,
    ChannelingEligibilityStatus,
    ChannelingLoanAPILog,
)

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    LoanFactory,
    ApplicationFactory,
    FeatureSettingFactory,
    PartnerFactory,
)
from juloserver.channeling_loan.tests.factories import ChannelingLoanCityAreaFactory
from juloserver.account.tests.factories import AccountFactory, AccountwithApplicationFactory
from juloserver.followthemoney.constants import LenderTransactionTypeConst
from juloserver.followthemoney.models import LenderTransactionType
from juloserver.followthemoney.factories import (
    LenderCurrentFactory,
    LenderBalanceCurrentFactory,
)
from juloserver.disbursement.tests.factories import DisbursementFactory
from juloserver.channeling_loan.utils import BSSCharacterTool


class TestBSSServices(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.all_feature_setting = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG,
            is_active=True,
            parameters={
                ChannelingConst.BSS: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "bss_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 15,
                        "RISK_PREMIUM_PERCENTAGE": 18,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.API_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": 59,
                        "MIN_AGE": 21,
                        "JOB_TYPE": ["Pegawai swasta", "Pegawai negeri", "Pengusaha"],
                        "MAX_LOAN": 15000000,
                        "MIN_LOAN": 500000,
                        "MAX_RATIO": 0.3,
                        "MAX_TENOR": 9,
                        "MIN_TENOR": 1,
                        "MIN_INCOME": 2000000,
                        "MIN_WORKTIME": 3,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": False,
                        "OPENING_TIME": {"hour": 7, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 19, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": [],
                        "LIMIT": None,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {"is_active": False},
                },
                ChannelingConst.BJB: {
                    "is_active": False,
                    "general": {
                        "LENDER_NAME": "bjb_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 14,
                        "RISK_PREMIUM_PERCENTAGE": 0,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.MANUAL_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": None,
                        "MIN_AGE": None,
                        "JOB_TYPE": [],
                        "MAX_LOAN": 20000000,
                        "MIN_LOAN": 1000000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": None,
                        "MIN_TENOR": None,
                        "MIN_INCOME": None,
                        "MIN_WORKTIME": 24,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": True,
                        "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": ["Saturday", "Sunday"],
                        "LIMIT": 50,
                    },
                    "force_update": {
                        "is_active": False,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {"is_active": False},
                },
                ChannelingConst.FAMA: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "fama_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 14,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.MANUAL_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": None,
                        "MIN_AGE": None,
                        "JOB_TYPE": [],
                        "MAX_LOAN": 20000000,
                        "MIN_LOAN": 1000000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": None,
                        "MIN_TENOR": None,
                        "MIN_INCOME": None,
                        "MIN_WORKTIME": 24,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": True,
                        "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": ["Saturday", "Sunday"],
                        "LIMIT": 1,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {"is_active": False},
                },
            },
        )
        cls.disbursement = DisbursementFactory()
        cls.partner = PartnerFactory()
        cls.lender = LenderCurrentFactory(xfers_token="xfers_tokenforlender", user=cls.partner.user)
        cls.account = AccountFactory()
        cls.loan = LoanFactory(
            application=None,
            account=cls.account,
            lender=cls.lender,
            disbursement_id=cls.disbursement.id,
            fund_transfer_ts=timezone.localtime(timezone.now()),
        )
        LenderBalanceCurrentFactory(lender=cls.lender, available_balance=2*cls.loan.loan_amount)
        cls.application = ApplicationFactory(
            account=cls.account,
            marital_status="Menikah",
            last_education="SD",
            address_kabupaten="Kab. Bekasi",
        )
        cls.feature_setting = FeatureSettingFactory(feature_name="bss_channeling_mock_response")
        cls.today = timezone.localtime(timezone.now())
        FeatureSettingFactory(
            feature_name="mock_available_balance",
            is_active=True,
            parameters={"available_balance": 1000000000}
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.BSS_CHANNELING,
            is_active=True,
            parameters={}
        )
        LenderTransactionType.objects.create(transaction_type=LenderTransactionTypeConst.CHANNELING)
        cls.channeling_eligibility_status = ChannelingEligibilityStatus.objects.create(
            application=cls.application,
            channeling_type=ChannelingConst.BSS,
            eligibility_status=ChannelingStatusConst.ELIGIBLE,
        )
        cls.channeling_loan_status = ChannelingLoanStatus.objects.create(
            channeling_eligibility_status=cls.channeling_eligibility_status,
            loan=cls.loan,
            channeling_type=ChannelingConst.BSS,
            channeling_status=ChannelingStatusConst.PENDING,
            channeling_interest_amount=0.5*cls.loan.loan_amount
        )

    def setUp(self):
        self.channeling_client = get_bss_channeling_client()
        self.va_client = get_bss_va_client()

    def test_client_channeling_response_logger(self):
        self.channeling_client.channeling_response_logger(
            "BSS", "post", {}, "error message", self.loan, None
        )
        self.assertEqual(
            self.channeling_client.mock_response("10", "disburse")['status'],
            BSSChannelingConst.OK_STATUS
        )
        self.assertEqual(
            self.channeling_client.mock_response("20", "disburse")['status'],
            BSSChannelingConst.OK_STATUS
        )
        self.assertEqual(
            self.channeling_client.mock_response("30", "disburse")['status'],
            BSSChannelingConst.OK_STATUS
        )
        self.assertEqual(
            self.channeling_client.mock_response("40", "disburse")['status'],
            BSSChannelingConst.OK_STATUS
        )

    @mock.patch('requests.post')
    def test_send_request(self, mock_request):
        def json_func():
            return self.channeling_client.mock_response("00", "disburse")

        self.channeling_client.mock_response("40", "disburse")
        self.channeling_client.mock_response("20", "disburse")
        self.channeling_client.mock_response("30", "disburse")

        mock_response = requests.Response()
        mock_response.status_code = 200
        mock_response.json = json_func
        mock_response.request = requests.request
        mock_request.return_value = mock_response

        self.feature_setting.parameters[self.loan.id] = "10"
        self.feature_setting.save()

        channeling_response = self.channeling_client.send_request(
            "disburse", "post", self.loan, construct_bss_disbursement_data(self.loan))
        status, _, _ = reconstruct_response_format(channeling_response)
        self.assertEqual(status, BSSChannelingConst.OK_STATUS)

        self.channeling_client.channeling_response_logger(
            "BSS", "[POST] disburse", channeling_response, "error message", self.loan, None)
        is_exists = ChannelingLoanAPILog.objects.filter(
            loan=self.loan,
            request_type="[POST] disburse",
            http_status_code="404",
            error_message="error message",
        ).exists()
        self.assertEqual(is_exists, True)

    def test_change_city_to_dati_code(self):
        ChannelingLoanCityAreaFactory(
            city_area = "Kota Jakarta Pusat",
            city_area_code = "0391"
        )
        ChannelingLoanCityAreaFactory(
            city_area = "Kota antah berantah",
            city_area_code = "9999"
        )

        self.assertEqual(change_city_to_dati_code("Kota Jakarta Pusat"), "0391")
        self.assertEqual(change_city_to_dati_code("Kota antah berantah"), "9999")

    def test_reconstruct_response_format(self):
        _, _, error = reconstruct_response_format({"error": "Test error", "status": "error"})
        self.assertEqual(error, "Test error")

    @mock.patch('juloserver.channeling_loan.services.bss_services.validate_bss_disbursement_data')
    @mock.patch(
        'juloserver.channeling_loan.services.general_services.'
        'generate_new_summary_lender_and_julo_one_loan_agreement'
    )
    @mock.patch('juloserver.channeling_loan.clients.bss.BSSChannelingClient.send_request')
    def test_send_loan_for_channeling_to_bss(
        self,
        mock_request,
        mock_generate_new_summary_lender_and_julo_one_loan_agreement,
        mock_validate_bss_disbursement_data,
    ):
        ChannelingLoanCityAreaFactory(
            city_area = "Kab. Bekasi",
            city_area_code = "0102"
        )
        mock_validate_bss_disbursement_data.return_value = None

        status, message, _ = send_loan_for_channeling_to_bss(None, None)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(message, "Loan not found")

        feature_setting = self.all_feature_setting.parameters['BSS']
        status, _, _ = send_loan_for_channeling_to_bss(self.loan, feature_setting)
        self.assertEqual(status, ChannelingStatusConst.FAILED)

        partner = PartnerFactory()
        lender = LenderCurrentFactory(
            lender_name=feature_setting['general']['LENDER_NAME'],
            xfers_token="xfers_tokenfornewlender",
            user=partner.user,
        )
        LenderBalanceCurrentFactory(lender=lender, available_balance=self.loan.loan_amount*2)
        mock_request.return_value = {"error": "Failed to do disbursement", "status": "error"}
        status, message, _ = send_loan_for_channeling_to_bss(self.loan, feature_setting)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(message, "Failed to do disbursement")

        mock_request.return_value = self.channeling_client.mock_response("00", "disburse")
        self.channeling_loan_status.channeling_status = ChannelingStatusConst.PENDING
        self.channeling_loan_status.save()
        status, _, _ = send_loan_for_channeling_to_bss(self.loan, feature_setting)
        self.assertEqual(status, ChannelingStatusConst.SUCCESS)
        mock_generate_new_summary_lender_and_julo_one_loan_agreement.assert_called_once_with(
            loan=self.loan, lender=lender, channeling_type=ChannelingConst.BSS
        )

        mock_request.return_value = self.channeling_client.mock_response("99", "disburse")
        self.channeling_loan_status.channeling_status = ChannelingStatusConst.PENDING
        self.channeling_loan_status.save()
        status, message, retry_interval = send_loan_for_channeling_to_bss(self.loan, feature_setting)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(message, "undefined condition")
        self.assertEqual(retry_interval, 0)

        mock_request.return_value = self.channeling_client.mock_response("99", "disburse")
        self.channeling_loan_status.channeling_status = ChannelingStatusConst.PENDING
        self.channeling_loan_status.save()
        bss_channeling_retry = FeatureSettingFactory(
            feature_name=FeatureNameConst.BSS_CHANNELING_RETRY,
            is_active=True,
            parameters={"minutes": 10}
        )
        status, message, retry_interval = send_loan_for_channeling_to_bss(self.loan, feature_setting)
        self.assertEqual(status, ChannelingStatusConst.RETRY)
        self.assertEqual(message, "Continue retry process")
        self.assertEqual(retry_interval, 10)
        bss_channeling_retry.delete()

    @mock.patch('juloserver.channeling_loan.services.bss_services.success_channeling_process')
    @mock.patch('juloserver.channeling_loan.clients.bss.BSSChannelingClient.send_request')
    def test_send_loan_for_channeling_to_bss_zip_code(
        self,
        mock_request,
        mock_success_channeling_process,
    ):
        ChannelingLoanCityAreaFactory(city_area="Kab. Bekasi", city_area_code="0102")
        mock_success_channeling_process.return_value = ChannelingStatusConst.SUCCESS, ""

        feature_setting = self.all_feature_setting.parameters['BSS']
        partner = PartnerFactory()
        lender = LenderCurrentFactory(
            lender_name=feature_setting['general']['LENDER_NAME'],
            xfers_token="xfers_tokenfornewlender",
            user=partner.user,
        )
        LenderBalanceCurrentFactory(lender=lender, available_balance=self.loan.loan_amount * 2)

        mock_request.return_value = self.channeling_client.mock_response("00", "disburse")
        self.channeling_loan_status.channeling_status = ChannelingStatusConst.PENDING
        self.channeling_loan_status.save()

        self.application.birth_place = "Jakarta"
        self.application.address_kodepos = "12345"
        self.application.save()
        status, error_msg, _ = send_loan_for_channeling_to_bss(self.loan, feature_setting)
        self.assertEqual(status, ChannelingStatusConst.SUCCESS)

        self.application.birth_place = "Jakart2"
        self.application.address_kodepos = "12345"
        self.channeling_loan_status.channeling_status = ChannelingStatusConst.PENDING
        self.channeling_loan_status.save()
        self.application.save()
        status, error_msg, _ = send_loan_for_channeling_to_bss(self.loan, feature_setting)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(error_msg, "Birthplace cannot contain number")

        self.application.birth_place = "Jakarta Selatan _?"
        self.application.address_kodepos = "12345"
        self.channeling_loan_status.channeling_status = ChannelingStatusConst.PENDING
        self.channeling_loan_status.save()
        self.application.save()
        status, error_msg, _ = send_loan_for_channeling_to_bss(self.loan, feature_setting)
        self.assertEqual(status, ChannelingStatusConst.SUCCESS)

        # make sure UT still executed when birthplace is empty
        self.application.birth_place = None
        self.application.address_kodepos = "12345"
        self.channeling_loan_status.channeling_status = ChannelingStatusConst.PENDING
        self.channeling_loan_status.save()
        self.application.save()
        status, error_msg, _ = send_loan_for_channeling_to_bss(self.loan, feature_setting)
        self.assertEqual(status, ChannelingStatusConst.SUCCESS)

        self.application.birth_place = "Jakarta"
        self.application.address_kodepos = "00000"
        self.channeling_loan_status.channeling_status = ChannelingStatusConst.PENDING
        self.channeling_loan_status.save()
        self.application.save()
        status, error_msg, _ = send_loan_for_channeling_to_bss(self.loan, feature_setting)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(error_msg, "Zip code cannot be 00000")

    def test_sanitize_bss_disbursement_data(self):
        disbursement_data = {
            BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('fullname'): "fullname. fullname!",
            BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('custname'): "_____name",
            BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('phoneno'): "+6281-123-543-643",
            BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('mobileno'): "+6281-123-543-643",
            # BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('birthdate'): "2024-02-02",
            BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('mothername'): "mot-her na-me.",
        }
        sanitize_bss_disbursement_data(disbursement_data)

        self.assertEqual(
            disbursement_data.get(BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('fullname')),
            "fullname fullname",
        )
        self.assertEqual(
            disbursement_data.get(BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('custname')), "name"
        )
        self.assertEqual(
            disbursement_data.get(BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('phoneno')),
            "6281123543643",
        )
        self.assertEqual(
            disbursement_data.get(BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('mobileno')),
            "6281123543643",
        )
        self.assertEqual(
            disbursement_data.get(BSSChannelingConst.BSS_CUSTOMER_DATA_KEY.get('mothername')),
            "mother name",
        )

    @mock.patch('juloserver.channeling_loan.clients.bss.BSSChannelingClient.send_request')
    def test_check_disburse_transaction(self, mock_request):
        mock_request.return_value = self.channeling_client.mock_response("00", "disburse")
        self.assertEqual(
            check_disburse_transaction(self.loan, 0), (ChannelingStatusConst.FAILED, "Unconfigurize retry feature", 0))

        mock_request.return_value = {"error": "Failed to check disbursement", "status": "error"}
        _, message, retry_interval = check_disburse_transaction(self.loan, 1)
        self.assertEqual(message, "Unconfigurize retry feature")

    def test_validation_construct_bss_customer_data_success(self):
        result = construct_bss_disbursement_data(self.loan)
        self.assertTrue(result)

    def test_validation_construct_bss_customer_data_failed_mobile_no(self):
        self.application.mobile_phone_1 = None
        self.application.save()
        with self.assertRaises(Exception) as e:
            construct_bss_disbursement_data(self.loan)
        self.assertIn(
            "field mobileno is required",
            str(e.exception),
        )

    def test_validation_construct_bss_customer_data_failed_income(self):
        self.application.monthly_income = None
        self.application.save()
        with self.assertRaises(Exception) as e:
            construct_bss_disbursement_data(self.loan)
        self.assertIn(
            "field grossincome is required",
            str(e.exception),
        )


class TestConstructBssCustomerData(TestCase):
    def setUp(self) -> None:
        self.account = AccountwithApplicationFactory()
        self.app = self.account.application_set.last()
        self.app.application_status_id = 190
        self.app.customer = self.account.customer
        self.app.save()

        self.loan = LoanFactory(
            account=self.account,
            application=self.app,
            customer=self.account.customer,
        )
        self.char_tool = BSSCharacterTool()

    def test_construct_with_special_characters_address_field(self):
        """
        Only test address field
        """
        bad_string = "Address 1/2/3/4 !"
        self.app.address_kelurahan = bad_string
        self.app.address_kecamatan = bad_string
        self.app.address_kabupaten = bad_string
        self.app.marital_status = "Lajang"
        self.app.save()

        data = construct_bss_customer_data(self.loan, self.app)
        allowed_chars = self.char_tool.allowed_chars

        fields = BSSDataField.customer_address()

        for field in fields:
            self.assertTrue(all(char in allowed_chars for char in data[field]))

        # other fields like name are not changed
        self.assertEqual(data["customerdata[custname]"], self.app.fullname)


class TestReplaceSpecialCharsForField(unittest.TestCase):
    def setUp(self):
        self.tool = BSSCharacterTool()

    def test_replace_special_chars_for_fields(self):
        """
        test replace bad chars for specific fields
        """
        bad_data = {
            "one": "you're like a dream come true!",
            "two": "just wanna be with u/",
            "three": "girl it's plain to see",
        }

        # only for fields one and three
        data = replace_special_chars_for_fields(data=bad_data, fields=['one', 'three'])

        allowed_chars = self.tool.allowed_chars
        self.assertTrue(char in allowed_chars for char in data['one'])
        self.assertTrue(char in allowed_chars for char in data['three'])

        # assert 'two' not changed
        self.assertEqual(bad_data['two'], data['two'])
