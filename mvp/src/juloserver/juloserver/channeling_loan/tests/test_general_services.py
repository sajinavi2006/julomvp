import mock
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import patch, Mock, MagicMock

from bulk_update.helper import bulk_update
from django.conf import settings
from django.http import HttpResponse
from django.test.testcases import TestCase
from django.utils import timezone

from dateutil.relativedelta import relativedelta

from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.channeling_loan.clients import (
    get_bss_channeling_client,
    get_bss_va_client,
    get_dbs_sftp_client,
)
from juloserver.channeling_loan.constants import (
    FeatureNameConst as ChannelingFeatureNameConst,
    ChannelingConst,
    ChannelingStatusConst,
    GeneralIneligible,
    FAMAChannelingConst,
    ChannelingLoanApprovalFileConst,
)
from juloserver.channeling_loan.exceptions import (
    ChannelingLoanApprovalFileNotFound,
    ChannelingLoanApprovalFileDocumentNotFound,
)
from juloserver.channeling_loan.models import (
    ChannelingLoanHistory,
    ChannelingLoanApprovalFile,
    ChannelingLoanPayment,
    ChannelingLoanStatus,
    ChannelingLoanStatusHistory,
    ChannelingLoanAPILog,
)
from juloserver.channeling_loan.services.general_services import (
    get_channeling_loan_configuration,
    get_channeling_loan_priority_list,
    get_editable_ineligibilities_config,
    get_general_channeling_ineligible_conditions,
    get_selected_channeling_type,
    get_channeling_loan_status,
    is_account_had_installment_paid_off,
    update_channeling_loan_status,
    generate_channeling_loan_status,
    get_channeling_eligibility_status,
    generate_channeling_status,
    application_risk_acceptance_ciriteria_check,
    loan_risk_acceptance_criteria_check,
    validate_custom_rac,
    loan_from_partner,
    get_interest_rate_config,
    get_channeling_days_in_year,
    recalculate_channeling_payment_interest,
    channeling_buyback_process,
    update_loan_lender,
    calculate_new_lender_balance,
    calculate_old_lender_balance,
    success_channeling_process,
    process_loan_for_channeling,
    approve_loan_for_channeling,
    initiate_channeling_loan_status,
    is_account_had_loan_paid_off,
    is_account_status_entered_gt_420,
    filter_loan_adjusted_rate,
    get_channeling_daily_duration,
    get_fama_channeling_admin_fee,
    SFTPProcess,
    encrypt_data_and_upload_to_sftp_server,
    decrypt_data,
    download_latest_file_from_sftp_server,
    download_latest_fama_approval_file_from_sftp_server,
    convert_fama_approval_content_from_txt_to_csv,
    get_filename_counter_suffix_length,
    get_next_filename_counter_suffix,
    filter_loan_adjusted_rate,
    upload_approval_file_to_oss_and_create_document,
    get_process_approval_response_time_delay_in_minutes,
    mark_approval_file_processed,
    get_latest_approval_file_object,
    execute_new_approval_response_process,
    get_response_approval_file,
    bulk_update_channeling_loan_status,
    validate_bss_custom_rac,
    create_channeling_loan_api_log,
    get_channeling_loan_status_by_loan_xid,
    check_common_failed_channeling,
    upload_channeling_file_to_oss_and_slack,
    convert_dbs_approval_content_from_txt_to_csv,
    get_credit_score_conversion,
    is_payment_due_date_day_in_exclusion_day,
)
from juloserver.channeling_loan.tests.factories import (
    ChannelingLoanStatusFactory,
    ChannelingEligibilityStatusFactory,
    ChannelingLoanPaymentFactory,
    ChannelingLoanSendFileTrackingFactory,
    ChannelingLoanApprovalFileFactory,
    ChannelingLoanCityAreaFactory,
    ChannelingBScoreFactory,
)
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.tests.factories import (
    LoanFactory,
    ApplicationFactory,
    FeatureSettingFactory,
    ImageFactory,
    PartnerFactory,
    PaymentFactory,
    StatusLookupFactory,
    CustomerFactory,
    DocumentFactory,
    ProductLineFactory,
    LenderTransactionTypeFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountStatusHistoryFactory,
)
from juloserver.followthemoney.constants import LenderTransactionTypeConst
from juloserver.followthemoney.models import LenderTransactionType
from juloserver.followthemoney.factories import (
    LenderCurrentFactory,
    LenderBalanceCurrentFactory,
)
from juloserver.disbursement.tests.factories import DisbursementFactory

from juloserver.partnership.tests.factories import PartnerLoanRequestFactory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod

from juloserver.loan.models import LoanAdjustedRate
from juloserver.julo.models import Payment, Document
from juloserver.channeling_loan.services.interest_services import (
    ChannelingInterest,
    DBSInterest,
)
from juloserver.cfs.tests.factories import PdClcsPrimeResultFactory
from juloserver.personal_data_verification.tests.factories import (
    DukcapilResponseFactory,
)


class TestGeneralServices(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.current_ts = timezone.localtime(timezone.now())
        cls.feature_setting = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG,
            is_active=False,
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
                        "MIN_OS_AMOUNT_FTC": 0,
                        "MAX_OS_AMOUNT_FTC": 10000000,
                        "MIN_OS_AMOUNT_REPEAT": 0,
                        "MAX_OS_AMOUNT_REPEAT": 12000000,
                        "MAX_RATIO": 0.3,
                        "MAX_TENOR": 9,
                        "MIN_TENOR": 1,
                        "MIN_INCOME": 2000000,
                        "MIN_WORKTIME": 3,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "MOTHER_NAME_FULLNAME": False,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "DUKCAPIL_CHECK": False,
                        "VERSION": 2,
                        "FTC_FDC": 0.9,
                        "FTC_NON_FDC": 0.95,
                        "NON_FTC": 0.75,
                    },
                    "cutoff": {
                        "is_active": False,
                        "OPENING_TIME": {"hour": 7, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 19, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": [],
                        "LIMIT": None,
                        "CHANNEL_AFTER_CUTOFF": False,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {
                        "is_active": False,
                    }
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
                        "MIN_OS_AMOUNT_FTC": 0,
                        "MAX_OS_AMOUNT_FTC": 30000000,
                        "MIN_OS_AMOUNT_REPEAT": 0,
                        "MAX_OS_AMOUNT_REPEAT": 80000000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": None,
                        "MIN_TENOR": None,
                        "MIN_INCOME": None,
                        "MIN_WORKTIME": 24,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "MOTHER_NAME_FULLNAME": False,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "DUKCAPIL_CHECK": False,
                        "VERSION": 2,
                        "FTC_FDC": 0,
                        "FTC_NON_FDC": 0,
                        "NON_FTC": 0,
                    },
                    "cutoff": {
                        "is_active": True,
                        "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": ["Saturday", "Sunday"],
                        "LIMIT": 50,
                        "CHANNEL_AFTER_CUTOFF": False,
                    },
                    "force_update": {
                        "is_active": False,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {
                        "is_active": False,
                    }
                },
                ChannelingConst.FAMA: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "fama_channeling",
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
                        "MIN_OS_AMOUNT_FTC": 0,
                        "MAX_OS_AMOUNT_FTC": 30000000,
                        "MIN_OS_AMOUNT_REPEAT": 0,
                        "MAX_OS_AMOUNT_REPEAT": 80000000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": None,
                        "MIN_TENOR": None,
                        "MIN_INCOME": None,
                        "MIN_WORKTIME": 24,
                        "TRANSACTION_METHOD": [1, 2, 3, 4, 5, 6, 7, 12, 11, 16],
                        "INCOME_PROVE": True,
                        "MOTHER_NAME_FULLNAME": False,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "DUKCAPIL_CHECK": False,
                        "VERSION": 2,
                        "FTC_FDC": 0,
                        "FTC_NON_FDC": 0,
                        "NON_FTC": 0,
                    },
                    "cutoff": {
                        "is_active": True,
                        "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": ["Saturday", "Sunday"],
                        "LIMIT": 1,
                        "CHANNEL_AFTER_CUTOFF": False,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {
                        "is_active": False,
                    }
                },
                ChannelingConst.BNI: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "bni_channeling",
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
                        "MIN_OS_AMOUNT_FTC": 0,
                        "MAX_OS_AMOUNT_FTC": 30000000,
                        "MIN_OS_AMOUNT_REPEAT": 0,
                        "MAX_OS_AMOUNT_REPEAT": 80000000,
                        "MAX_RATIO": 0.3,
                        "MAX_TENOR": 9,
                        "MIN_TENOR": 1,
                        "MIN_INCOME": 2000000,
                        "MIN_WORKTIME": 3,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "DUKCAPIL_CHECK": False,
                        "VERSION": 2,
                        "FTC_FDC": 0.9,
                        "FTC_NON_FDC": 0.95,
                        "NON_FTC": 0.75,
                    },
                    "cutoff": {
                        "is_active": False,
                        "OPENING_TIME": {"hour": 7, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 19, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": [],
                        "LIMIT": None,
                        "CHANNEL_AFTER_CUTOFF": False,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {
                        "is_active": False,
                    },
                },
                ChannelingConst.SMF: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "smf_channeling",
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
                        "MIN_OS_AMOUNT_FTC": 0,
                        "MAX_OS_AMOUNT_FTC": 30000000,
                        "MIN_OS_AMOUNT_REPEAT": 0,
                        "MAX_OS_AMOUNT_REPEAT": 80000000,
                        "MAX_RATIO": 0.3,
                        "MAX_TENOR": 9,
                        "MIN_TENOR": 1,
                        "MIN_INCOME": 2000000,
                        "MIN_WORKTIME": 3,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "MOTHER_NAME_FULLNAME": False,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "DUKCAPIL_CHECK": False,
                        "VERSION": 2,
                        "FTC_FDC": 0.9,
                        "FTC_NON_FDC": 0.95,
                        "NON_FTC": 0.75,
                    },
                    "cutoff": {
                        "is_active": False,
                        "OPENING_TIME": {"hour": 7, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 19, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": [],
                        "LIMIT": None,
                        "CHANNEL_AFTER_CUTOFF": False,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {
                        "is_active": False,
                    },
                },
            }
        )
        cls.priority_feature = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_PRIORITY,
            is_active=False,
            parameters=ChannelingConst.LIST
        )

        cls.ineligibilities_feature = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_EDITABLE_INELIGIBILITIES,
            is_active=True,
            parameters={
                GeneralIneligible.ACCOUNT_STATUS_MORE_THAN_420_AT_SOME_POINT.name: True,
                GeneralIneligible.LOAN_HAS_INTEREST_BENEFIT.name: True,
                GeneralIneligible.HAVENT_PAID_OFF_A_LOAN.name: True,
                GeneralIneligible.HAVENT_PAID_OFF_AN_INSTALLMENT.name: False,
            }
        )

        cls.disbursement = DisbursementFactory()
        cls.partner = PartnerFactory()
        cls.lender = LenderCurrentFactory(xfers_token="xfers_tokenforlender", user=cls.partner.user)
        cls.account = AccountFactory()
        cls.customer = CustomerFactory(fullname="Jane Doe", mother_maiden_name="Jane Doe")
        cls.loan = LoanFactory(
            application=None,
            account=cls.account,
            lender=cls.lender,
            disbursement_id=cls.disbursement.id,
            fund_transfer_ts=timezone.localtime(timezone.now()),
            transaction_method_id=1,
        )
        cls.application = ApplicationFactory(
            account=cls.account,
            customer=cls.customer,
            fullname=cls.customer.fullname,
            marital_status="Menikah",
            last_education="SD",
            address_kabupaten="Kab. Bekasi",
            address_kodepos="17511",
        )
        LenderBalanceCurrentFactory(lender=cls.lender, available_balance=2 * cls.loan.loan_amount)
        ChannelingLoanCityAreaFactory(city_area="Kab. Bekasi", city_area_code="0102")
        cls.clcs_prime_result = PdClcsPrimeResultFactory(
            customer_id=cls.application.customer_id,
            clcs_prime_score=0.94,
            partition_date=cls.current_ts,
        )
        cls.feature_setting_rac_exclude_mother_maiden_name = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.EXCLUDE_MOTHER_MAIDEN_NAME_FAMA,
            is_active=False,
            parameters=['MAMA', 'IBU', 'MAMA']
        )

    def setUp(self):
        self.channeling_client = get_bss_channeling_client()
        self.va_client = get_bss_va_client()

    def test_get_channeling_loan_configuration(self):
        self.assertIsNone(get_channeling_loan_configuration())

        self.feature_setting.update_safely(is_active=True)
        feature_setting = get_channeling_loan_configuration()
        self.assertEqual(len(feature_setting), 5)

        self.assertIsNotNone(get_channeling_loan_configuration(ChannelingConst.BSS))
        self.assertIsNone(get_channeling_loan_configuration(ChannelingConst.BJB))

    def test_get_channeling_loan_priority_list(self):
        self.assertEqual(get_channeling_loan_priority_list(), [])

        self.priority_feature.update_safely(is_active=True)
        self.assertEqual(
            get_channeling_loan_priority_list(),
            ['BSS', 'BJB', 'FAMA', 'BCAD', 'PERMATA', 'DBS', 'SMF', 'BNI'],
        )

    def test_get_selected_channeling_type(self):
        type_list, _ = get_selected_channeling_type(self.loan, self.current_ts)
        self.assertIsNone(type_list)

        self.priority_feature.update_safely(
            is_active=True, parameters=['BSS', 'BJB', 'FAMA', 'FAKEBANK']
        )
        type_list, _ = get_selected_channeling_type(self.loan, self.current_ts)
        self.assertIsNone(type_list)

        changed_date = self.current_ts.replace(hour=8, minute=0, year=2022, month=12, day=20)

        self.feature_setting.update_safely(is_active=True)
        type_list, _ = get_selected_channeling_type(self.loan, changed_date)
        self.assertEqual(type_list, ['BSS', 'FAMA'])

        existing_parameters = self.feature_setting.parameters
        existing_parameters['BJB']['whitelist']['is_active'] = True
        existing_parameters['BJB']['whitelist']['APPLICATIONS'] = [
            str(self.application.id)
        ]
        self.feature_setting.update_safely(parameters=existing_parameters)
        type_list, _ = get_selected_channeling_type(self.loan, changed_date)
        self.assertEqual(type_list, ['BSS', 'BJB', 'FAMA'])

        existing_parameters = self.feature_setting.parameters
        existing_parameters['FAMA']['cutoff']['INACTIVE_DATE'] = ['2022/12/20']
        self.feature_setting.update_safely(parameters=existing_parameters)
        type_list, _ = get_selected_channeling_type(self.loan, changed_date)
        self.assertEqual(type_list, ['BSS', 'BJB'])

        ChannelingLoanStatusFactory(
            channeling_eligibility_status=ChannelingEligibilityStatusFactory(
                application=self.application
            ),
            loan=self.loan,
            channeling_type="FAMA"
        )
        ChannelingLoanStatusFactory(
            channeling_eligibility_status=ChannelingEligibilityStatusFactory(
                application=self.application
            ),
            loan=self.loan,
            channeling_type="FAMA"
        )
        type_list, _ = get_selected_channeling_type(self.loan, changed_date)
        self.assertEqual(type_list, ['BSS', 'BJB'])

        self.priority_feature.update_safely(
            is_active=True, parameters=['FAKEBANK', 'NEWBANK']
        )
        type_list, _ = get_selected_channeling_type(self.loan, changed_date)
        self.assertIsNone(type_list)

    def test_get_channeling_loan_status(self):
        self.assertIsNone(get_channeling_loan_status(None, None))

        ChannelingLoanStatusFactory(
            channeling_eligibility_status=ChannelingEligibilityStatusFactory(
                application=self.application
            ),
            loan=self.loan,
        )
        self.assertIsNotNone(get_channeling_loan_status(self.loan, 'pending'))

    def test_update_channeling_loan_status(self):
        self.assertIsNone(update_channeling_loan_status(None, None, None))

        channeling_loan_status = ChannelingLoanStatusFactory(
            channeling_eligibility_status=ChannelingEligibilityStatusFactory(
                application=self.application
            ),
            loan=self.loan,
        )
        self.assertIsNone(update_channeling_loan_status(channeling_loan_status.id, 'pending', None))

        update_channeling_loan_status(channeling_loan_status.id, 'process', None)
        channeling_loan_status.refresh_from_db()
        self.assertEqual(channeling_loan_status.channeling_status, 'process')

    def test_bulk_update_channeling_loan_status(self):
        old_status = 'pending'
        status1 = ChannelingLoanStatusFactory(channeling_status=old_status)
        status2 = ChannelingLoanStatusFactory(channeling_status=old_status)
        status3 = ChannelingLoanStatusFactory(channeling_status=old_status)

        status_ids = [status1.id, status2.id, status3.id]
        new_status = 'process'
        change_reason = 'Test reason'
        change_by_id = 1

        # TEST EMPTY LIST
        bulk_update_channeling_loan_status(channeling_loan_status_id=[], new_status=new_status)
        self.assertEqual(ChannelingLoanStatusHistory.objects.count(), 0)

        # TEST NOT-EMPTY LIST
        bulk_update_channeling_loan_status(
            channeling_loan_status_id=status_ids,
            new_status=new_status,
            change_reason=change_reason,
            change_by_id=change_by_id,
        )

        # Check if statuses are updated
        updated_statuses = ChannelingLoanStatus.objects.filter(id__in=status_ids)
        for status in updated_statuses:
            self.assertEqual(status.channeling_status, new_status)
            self.assertEqual(status.reason, change_reason)

        # Check if history is created
        history_entries = ChannelingLoanStatusHistory.objects.filter(
            channeling_loan_status__in=updated_statuses
        )
        self.assertEqual(history_entries.count(), 3)

        for entry in history_entries:
            self.assertEqual(entry.old_status, old_status)
            self.assertEqual(entry.new_status, new_status)
            self.assertEqual(entry.change_reason, change_reason)
            self.assertEqual(entry.change_by_id, change_by_id)

    def test_generate_channeling_loan_status(self):
        channeling_eligibility_status = ChannelingEligibilityStatusFactory(
            application=self.application
        )
        channeling_loan_status = initiate_channeling_loan_status(
            self.loan, channeling_eligibility_status.channeling_type, ""
        )
        self.assertIsNone(
            generate_channeling_loan_status(
                channeling_loan_status, channeling_eligibility_status, 10, None
            )
        )

        self.feature_setting.update_safely(is_active=True)
        self.assertIsNotNone(
            generate_channeling_loan_status(
                channeling_loan_status, channeling_eligibility_status, 10, None
            )
        )

        self.assertIsNone(
            generate_channeling_loan_status(None, channeling_eligibility_status, 10, None)
        )

    def test_get_channeling_eligibility_status(self):
        self.assertIsNone(get_channeling_eligibility_status(None, None, None))

        self.assertIsNone(get_channeling_eligibility_status(self.loan, None, None))

        channeling_eligibility_status = ChannelingEligibilityStatusFactory(
            application=self.application
        )
        self.assertIsNone(
            get_channeling_eligibility_status(
                self.loan, "BSS", self.feature_setting.parameters['BSS']
            )
        )

        channeling_eligibility_status.update_safely(
            channeling_type='BJB', eligibility_status="eligible"
        )
        self.assertIsNotNone(
            get_channeling_eligibility_status(
                self.loan, "BJB", self.feature_setting.parameters['BJB']
            )
        )

    def test_generate_channeling_status(self):
        self.assertIsNotNone(
            generate_channeling_status(
                self.application, "BSS", True, "eligible", 2
            )
        )

    @pytest.mark.skip(reason="Flaky caused by 29 Feb")
    def test_application_risk_acceptance_ciriteria_check(self):
        self.application.update_safely(
            job_type="Pegawai asal",
            job_start=self.current_ts - relativedelta(months=1),
            monthly_income=100000
        )

        status, message, version = application_risk_acceptance_ciriteria_check(
            self.application, "FAKEBANK", None
        )
        self.assertEqual(status, False)
        self.assertEqual(message, 'RAC not set')
        self.assertEqual(version, 0)

        status, message, version = application_risk_acceptance_ciriteria_check(
            self.application, "BSS", self.feature_setting.parameters['BSS']
        )
        self.assertEqual(status, False)
        self.assertEqual(message, 'Mother maiden name not set')
        self.assertEqual(version, 2)

        self.application.customer.update_safely(
            mother_maiden_name="mother name", dob=self.current_ts - relativedelta(years=18)
        )
        status, message, version = application_risk_acceptance_ciriteria_check(
            self.application, "BSS", self.feature_setting.parameters['BSS']
        )
        self.assertEqual(status, False)
        self.assertEqual(message, 'Cannot pass minimum customer age, 18')
        self.assertEqual(version, 2)

        self.application.customer.update_safely(dob=self.current_ts - relativedelta(years=70))
        status, message, version = application_risk_acceptance_ciriteria_check(
            self.application, "BSS", self.feature_setting.parameters['BSS']
        )
        self.assertEqual(status, False)
        self.assertEqual(message, 'Cannot pass maximum customer age, 70')
        self.assertEqual(version, 2)

        self.application.customer.update_safely(dob=self.current_ts - relativedelta(years=25))
        status, message, version = application_risk_acceptance_ciriteria_check(
            self.application, "BSS", self.feature_setting.parameters['BSS']
        )
        self.assertEqual(status, False)
        self.assertEqual(message, 'Pegawai asal job_type not accepted')
        self.assertEqual(version, 2)

        self.application.update_safely(job_type="Pegawai negeri")
        status, message, version = application_risk_acceptance_ciriteria_check(
            self.application, "BSS", self.feature_setting.parameters['BSS']
        )
        self.assertEqual(status, False)
        self.assertEqual(message, 'Cannot pass minimum work time, 1')
        self.assertEqual(version, 2)

        self.application.update_safely(
            job_start=self.current_ts.replace(year=self.current_ts.year - 1)
        )
        status, message, version = application_risk_acceptance_ciriteria_check(
            self.application, "BSS", self.feature_setting.parameters['BSS']
        )
        self.assertEqual(status, False)
        self.assertEqual(message, 'Cannot pass minimum income, 100000')
        self.assertEqual(version, 2)

        self.application.update_safely(monthly_income=3000000)
        status, message, version = application_risk_acceptance_ciriteria_check(
            self.application, "BSS", self.feature_setting.parameters['BSS']
        )
        self.assertEqual(status, False)
        self.assertEqual(message, "Customer don't have any income prove")
        self.assertEqual(version, 2)

        ImageFactory(image_source=self.application.id, image_type='bank_statement')
        status, message, version = application_risk_acceptance_ciriteria_check(
            self.application, "BSS", self.feature_setting.parameters['BSS']
        )
        self.assertEqual(status, False)
        self.assertEqual(message, "Customer don't have ktp or selfie image")
        self.assertEqual(version, 2)

        ImageFactory(image_source=self.application.id, image_type='ktp_self')
        ImageFactory(image_source=self.application.id, image_type='selfie')
        status, message, version = application_risk_acceptance_ciriteria_check(
            self.application, "BSS", self.feature_setting.parameters['BSS']
        )
        self.assertEqual(status, True)
        self.assertEqual(message, "")
        self.assertEqual(version, 2)

        # Dukcapil check
        self.feature_setting.parameters['BSS']['rac']['DUKCAPIL_CHECK'] = True
        status, message, _ = application_risk_acceptance_ciriteria_check(
            self.application, "BSS", self.feature_setting.parameters['BSS']
        )
        self.assertEqual(status, False)
        self.assertEqual(message, "Customer don't pass dukcapil check")

        dukcapil_response = DukcapilResponseFactory(
            application=self.application,
            name=False,
            gender=False,
            birthdate=True,
            birthplace=False,
            address_street=False,
            address_kabupaten=True,
        )

        status, message, _ = application_risk_acceptance_ciriteria_check(
            self.application, "BSS", self.feature_setting.parameters['BSS']
        )
        self.assertEqual(status, False)
        self.assertEqual(message, "Customer don't pass dukcapil check")

        dukcapil_response.update_safely(name=True, birthdate=True)

        status, message, _ = application_risk_acceptance_ciriteria_check(
            self.application, "BSS", self.feature_setting.parameters['BSS']
        )
        self.assertEqual(status, True)
        self.assertEqual(message, "")

        loan_config = self.feature_setting.parameters['BNI']
        first_payment = self.loan.payment_set.first()
        first_payment.due_date = timezone.localtime(
            self.current_ts.replace(year=2023, month=4, day=10)
        ).date()
        first_payment.save()

        self.loan.customer.monthly_income = 1000000
        self.loan.customer.phone = '081234567890'
        self.loan.customer.address_kodepos = '12345'
        self.loan.customer.fullname = "name1"
        self.loan.customer.mother_maiden_name = "name2"
        self.loan.customer.kin_name = 'kin'
        self.loan.customer.kin_mobile_phone = '081234567891'
        self.loan.customer.spouse_name = 'spouse'
        self.loan.customer.spouse_mobile_phone = '081234567892'
        self.loan.customer.save()

        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, True)
        self.assertEqual(message, '')

        self.loan.customer.fullname = "name1"
        self.loan.customer.mother_maiden_name = "name1"
        self.loan.customer.save()

        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, 'Username same with Mother maiden name')

        self.loan.customer.mother_maiden_name = "name"
        self.loan.customer.monthly_income = 999_999
        self.loan.customer.save()
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, 'monthly_income is not valid')

        self.loan.customer.monthly_income = 100_000_000_000
        self.loan.customer.save()
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, 'monthly_income is not valid')

        self.loan.customer.monthly_income = 1_000_000
        self.loan.customer.phone = '08123456789'
        self.loan.customer.save()
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, 'phone_number is not valid')

        self.loan.customer.phone = '0812345678901234'
        self.loan.customer.save()
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, 'phone_number is not valid')

        self.loan.customer.phone = None
        self.loan.customer.save()
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, 'phone_number is not valid')

        self.loan.customer.phone = '081234567890'
        self.loan.customer.address_kodepos = '00000'
        self.loan.customer.save()
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, 'zipcode is not valid')

        self.loan.customer.phone = '081234567890'
        self.loan.customer.address_kodepos = '1234'
        self.loan.customer.save()
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, 'zipcode is not valid')

        self.loan.customer.address_kodepos = None
        self.loan.customer.save()
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, 'zipcode is not valid')

        self.loan.customer.address_kodepos = '12345'
        self.loan.customer.kin_name = 'kin'
        self.loan.customer.kin_mobile_phone = ''
        self.loan.customer.save()
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, 'kin_mobile_phone is not valid')

        self.loan.customer.kin_name = 'kin'
        self.loan.customer.kin_mobile_phone = '081234567891123123'
        self.loan.customer.save()
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, 'kin_mobile_phone is not valid')

        self.loan.customer.kin_name = 'kin'
        self.loan.customer.kin_mobile_phone = '081234567891'
        self.loan.customer.save()
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, True)

        self.loan.customer.spouse_name = 'spouse'
        self.loan.customer.spouse_mobile_phone = ''
        self.loan.customer.save()
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, 'spouse_mobile_phone is not valid')

        self.loan.customer.spouse_name = 'spouse'
        self.loan.customer.spouse_mobile_phone = '081234567891123123'
        self.loan.customer.save()
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, 'spouse_mobile_phone is not valid')

        self.loan.customer.spouse_name = 'spouse'
        self.loan.customer.spouse_mobile_phone = '081234567892'
        self.loan.customer.save()
        first_payment = self.loan.payment_set.first()
        first_payment.due_date = timezone.localtime(
            self.current_ts.replace(year=2023, month=5, day=10)
        ).date()
        first_payment.save()
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, 'first payment cannot be more than 30 days')

        first_payment = self.loan.payment_set.first()
        first_payment.due_date = timezone.localtime(
            self.current_ts.replace(year=2023, month=4, day=10)
        ).date()
        first_payment.save()
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BNI", loan_config)
        self.assertEqual(status, True)

    def test_loan_risk_acceptance_criteria_check(self):
        self.loan.update_safely(installment_amount=100000)
        self.application.update_safely(monthly_income=1000000)

        loan_config = self.feature_setting.parameters['BSS']
        status, message, = loan_risk_acceptance_criteria_check(
            self.loan, "FAKEBANK", None
        )
        self.assertEqual(status, False)
        self.assertEqual(message, 'RAC not set')

        status, message = loan_risk_acceptance_criteria_check(self.loan, "BSS", loan_config)
        self.assertEqual(status, True)
        self.assertEqual(message, '')

        self.loan.update_safely(loan_amount=100000)
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BSS", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, 'Cannot pass minimum loan, 100000')

        self.loan.update_safely(loan_amount=20000000)
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BSS", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, 'Cannot pass maximum loan, 20000000')

        loan_config['rac']['TENOR'] = 'Daily'
        self.loan.update_safely(loan_amount=3000000)
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BSS", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, "Tenor type shouldn't Monthly")

        loan_config['rac']['TENOR'] = 'Monthly'
        loan_config['rac']['MIN_TENOR'] = 2
        self.loan.update_safely(loan_duration=1)
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BSS", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, "Cannot pass minimum tenor, 1")

        self.loan.update_safely(loan_duration=10)
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BSS", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, "Cannot pass maximum tenor, 10")

        self.loan.update_safely(loan_duration=3, installment_amount=1000000)
        self.application.update_safely(monthly_income=1000000)
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BSS", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, "Cannot pass maximum ratio, 1.0")

        self.loan.update_safely(loan_duration=3, installment_amount=1000000)
        self.application.update_safely(monthly_income=10000000)
        day = self.loan.payment_set.last().due_date.day
        loan_config['due_date']['is_active'] = True
        loan_config['due_date']['EXCLUSION_DAY'] = [
            day,
        ]
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BSS", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, "Exclusion by due date, [%s]" % day)

        self.loan.update_safely(
            loan_duration=3,
            installment_amount=1000000,
            transaction_method_id=TransactionMethodFactory(id=999),
        )
        loan_config['due_date']['is_active'] = False
        self.application.update_safely(monthly_income=4000000)
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BSS", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, "Transaction method not allowed, 999")

        self.loan.update_safely(transaction_method_id=1)
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BSS", loan_config)
        self.assertEqual(status, True)

        loan_config['rac']['MOTHER_NAME_FULLNAME'] = True
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BSS", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, "Mother name cannot be the same as fullname")

        loan_config['rac']['MOTHER_NAME_FULLNAME'] = False
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BSS", loan_config)
        self.assertEqual(status, True)

        self.application.update_safely(address_kodepos='')
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BSS", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, "Dati2 code and zip code cannot be empty")

        self.application.update_safely(address_kodepos='17511', address_kabupaten='Kab. Bekasis')
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BSS", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, "Dati2 code and zip code cannot be empty")

        self.application.update_safely(address_kodepos='', address_kabupaten='')
        status, message = loan_risk_acceptance_criteria_check(self.loan, "BSS", loan_config)
        self.assertEqual(status, False)
        self.assertEqual(message, "Dati2 code and zip code cannot be empty")

    def test_validate_custom_rac(self):
        # if not j1_product_line:
        rac_configuration = self.feature_setting.parameters["SMF"]["rac"]
        j1_product_line = ProductLineFactory(product_line_code=1)
        self.loan.product.product_line = j1_product_line
        self.loan.product.save()
        status, _ = validate_custom_rac(self.loan, "SMF", rac_configuration)
        self.assertEqual(status, True)

        # if not not_j1_product_line:
        not_j1_product_line = ProductLineFactory(product_line_code=99)
        self.loan.product.product_line = not_j1_product_line
        self.loan.product.save()
        status, message = validate_custom_rac(self.loan, "SMF", rac_configuration)
        self.assertEqual(status, False)
        self.assertEqual(message, "Loan is not J1")

    def test_loan_from_partner(self):
        self.assertEqual(loan_from_partner(self.loan), False)
        partner_loan_request = PartnerLoanRequestFactory(
            loan=self.loan,
            partner=PartnerFactory(),
            distributor=None,
            loan_amount=self.loan.loan_amount,
            loan_disbursement_amount=self.loan.loan_disbursement_amount,
            loan_original_amount=self.loan.loan_amount,
            partner_origin_name=None,
        )
        self.assertEqual(loan_from_partner(self.loan), True)
        partner_loan_request.delete()

    def test_get_interest_rate_config(self):
        interest_percentage, risk_premium_percentage, total_percentage = get_interest_rate_config(
            "CSS", None
        )
        self.assertIsNone(interest_percentage)
        self.assertIsNone(risk_premium_percentage)
        self.assertIsNone(total_percentage)


        interest_percentage, risk_premium_percentage, total_percentage = get_interest_rate_config(
            "BSS", self.feature_setting.parameters['BSS']
        )
        self.assertEqual(interest_percentage, (15 / 100 / 360))
        self.assertEqual(risk_premium_percentage, (18 / 100 / 360))
        self.assertEqual(total_percentage, (33 / 100 / 360))

    def test_get_interest_rate_config_daily(self):
        interest_percentage, risk_premium_percentage, total_percentage = get_interest_rate_config(
            "BSS", self.feature_setting.parameters['BSS'], False
        )
        self.assertEqual(interest_percentage, (15 / 100))
        self.assertEqual(risk_premium_percentage, (18 / 100))
        self.assertEqual(total_percentage, (33 / 100))

    def test_get_channeling_days_in_year(self):
        self.feature_setting.update_safely(is_active=True)
        days_in_year = get_channeling_days_in_year("FAMA", None)
        self.assertEqual(days_in_year, 360)

    def test_get_channeling_days_in_year_inactive(self):
        days_in_year = get_channeling_days_in_year("FAMA", None)
        self.assertEqual(days_in_year, None)

    def test_recalculate_channeling_payment_interest(self):
        self.assertIsNone(recalculate_channeling_payment_interest(self.loan, "BSS", None))

        existing_loan_payment = ChannelingLoanPaymentFactory(
            payment=self.loan.payment_set.first()
        )
        self.assertIsNotNone(
            recalculate_channeling_payment_interest(
                self.loan, "BSS", self.feature_setting.parameters['BSS']
            )
        )
        existing_loan_payment.delete()
        self.assertIsNotNone(
            recalculate_channeling_payment_interest(
                self.loan, "BSS", self.feature_setting.parameters['BSS']
            )
        )

    @mock.patch('juloserver.channeling_loan.services.general_services.success_channeling_process')
    def test_channeling_buyback_process(self, mock_success_channeling_process):
        status, message = channeling_buyback_process(self.loan, "BSS", None)
        self.assertEqual(status, False)
        self.assertEqual(message, "Channeling configuration not set")

        bss_config = self.feature_setting.parameters['BSS']
        status, message = channeling_buyback_process(self.loan, "BSS", bss_config)
        self.assertEqual(status, False)
        self.assertEqual(message, "Lender not found")

        partner = PartnerFactory()
        LenderCurrentFactory(
            lender_name=bss_config['general']['BUYBACK_LENDER_NAME'],
            xfers_token="xfers_tokenforlender",
            user=partner.user,
        )
        status, message = channeling_buyback_process(self.loan, "BSS", bss_config)
        self.assertEqual(status, False)
        self.assertEqual(message, "TransactionType not found")

        LenderTransactionType.objects.create(
            transaction_type=LenderTransactionTypeConst.CHANNELING_BUYBACK
        )
        mock_success_channeling_process.return_value = (ChannelingStatusConst.FAILED, "Channeling status data missing")
        status, message = channeling_buyback_process(self.loan, "BSS", bss_config)
        self.assertEqual(status, False)
        self.assertEqual(message, "Channeling status data missing")

        mock_success_channeling_process.return_value = (ChannelingStatusConst.SUCCESS, None)
        status, message = channeling_buyback_process(self.loan, "BSS", bss_config)
        self.assertEqual(status, True)
        self.assertIsNone(message)

    def test_update_loan_lender(self):
        partner = PartnerFactory()
        old_lender, channeling_loan_history = update_loan_lender(
            self.loan, LenderCurrentFactory(
                lender_name='new_lender', xfers_token="xfers_tokenforlender", user=partner.user,
            ), 'BSS', 'force success'
        )
        self.assertIsNotNone(old_lender)
        self.assertIsNotNone(channeling_loan_history)

    @mock.patch('juloserver.disbursement.clients.xfers.XfersClient.get_julo_account_info')
    def test_calculate_lender_balance(self, mock_calculate_balance):
        self.loan.update_safely(lender=self.lender)
        partner = PartnerFactory()
        _, channeling_loan_history = update_loan_lender(
            self.loan, LenderCurrentFactory(
                lender_name='new_lender', xfers_token="xfers_tokenforlender", user=partner.user,
            ), 'BSS', 'force success'
        )
        mock_calculate_balance.return_value = {
            'available_balance': 10000000000
        }
        calculate_new_lender_balance(
            self.loan.id, self.loan.loan_amount, self.lender, channeling_loan_history,
            LenderTransactionType.objects.create(
                transaction_type=LenderTransactionTypeConst.CHANNELING
            )
        )
        calculate_old_lender_balance(
            self.loan.id, self.loan.loan_amount, self.lender, channeling_loan_history,
            LenderTransactionType.objects.create(
                transaction_type=LenderTransactionTypeConst.CHANNELING
            )
        )

    @mock.patch(
        'juloserver.channeling_loan.services.general_services.'
        'generate_new_summary_lender_and_julo_one_loan_agreement'
    )
    @mock.patch('juloserver.disbursement.clients.xfers.XfersClient.get_julo_account_info')
    def test_success_channeling_process(
        self, mock_calculate_balance, mock_generate_new_summary_lender_and_julo_one_loan_agreement
    ):
        mock_calculate_balance.return_value = {'available_balance': 10000000000}
        status, message = success_channeling_process(
            self.loan, self.lender,
            LenderTransactionType.objects.create(
                transaction_type=LenderTransactionTypeConst.CHANNELING
            ), self.loan.loan_amount, ChannelingStatusConst.FAILED, 'process'
        )
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(message, "Channeling status data missing")

        ChannelingLoanStatusFactory(
            channeling_eligibility_status=ChannelingEligibilityStatusFactory(
                application=self.application
            ),
            loan=self.loan,
            channeling_type="BSS"
        )
        status, message = success_channeling_process(
            self.loan, self.lender,
            LenderTransactionType.objects.create(
                transaction_type=LenderTransactionTypeConst.CHANNELING
            ), self.loan.loan_amount, 'pending', ChannelingStatusConst.SUCCESS
        )
        self.assertEqual(status, ChannelingStatusConst.SUCCESS)
        self.assertIsNone(message)
        mock_generate_new_summary_lender_and_julo_one_loan_agreement.assert_called_once_with(
            loan=self.loan,
            lender=self.lender,
            channeling_type=ChannelingConst.BSS,
        )

    @mock.patch(
        'juloserver.channeling_loan.services.fama_services.update_fama_eligibility_rejected_by_dpd'
    )
    @mock.patch('juloserver.disbursement.clients.xfers.XfersClient.get_julo_account_info')
    def test_rejected_cause_dpd(self, mock_calculate_balance, mock_update_channeling_eligibility):
        mock_calculate_balance.return_value = {'available_balance': 10000000000}
        ChannelingLoanStatusFactory(
            channeling_eligibility_status=ChannelingEligibilityStatusFactory(
                application=self.application
            ),
            loan=self.loan,
            channeling_type="FAMA",
        )

        success_channeling_process(
            self.loan,
            self.lender,
            LenderTransactionType.objects.create(
                transaction_type=LenderTransactionTypeConst.CHANNELING
            ),
            self.loan.loan_amount,
            'pending',
            ChannelingStatusConst.REJECT,
            reason='Customer has history for DPD over the max in the last few months, ',
        )
        mock_update_channeling_eligibility.assert_called_once()

    @patch("juloserver.channeling_loan.services.general_services.update_channeling_loan_status")
    @patch('juloserver.disbursement.clients.xfers.XfersClient.get_julo_account_info')
    def test_rejected_not_dpd(self, mock_calculate_balance, mock_update_channeling_loan_status):
        mock_calculate_balance.return_value = {'available_balance': 10000000000}
        cls = ChannelingLoanStatusFactory(
            channeling_eligibility_status=ChannelingEligibilityStatusFactory(
                application=self.application
            ),
            loan=self.loan,
            channeling_type="FAMA",
        )

        success_channeling_process(
            self.loan,
            self.lender,
            LenderTransactionType.objects.create(
                transaction_type=LenderTransactionTypeConst.CHANNELING
            ),
            self.loan.loan_amount,
            'pending',
            ChannelingStatusConst.REJECT,
            reason='Dati2 errorr, ',
        )
        mock_update_channeling_loan_status.assert_called_once_with(
            cls.id,
            ChannelingStatusConst.REJECT,
            change_reason='Dati2 errorr, ',
        )

    @patch("juloserver.channeling_loan.services.general_services.update_channeling_loan_status")
    @patch('juloserver.disbursement.clients.xfers.XfersClient.get_julo_account_info')
    def test_rejected_dpd_not_fama(
        self, mock_calculate_balance, mock_update_channeling_loan_status
    ):
        mock_calculate_balance.return_value = {'available_balance': 10000000000}
        cls = ChannelingLoanStatusFactory(
            channeling_eligibility_status=ChannelingEligibilityStatusFactory(
                application=self.application
            ),
            loan=self.loan,
            channeling_type="BSS",
        )

        success_channeling_process(
            self.loan,
            self.lender,
            LenderTransactionType.objects.create(
                transaction_type=LenderTransactionTypeConst.CHANNELING
            ),
            self.loan.loan_amount,
            'pending',
            ChannelingStatusConst.REJECT,
            reason='DPD',
        )
        mock_update_channeling_loan_status.assert_called_once_with(
            cls.id,
            ChannelingStatusConst.REJECT,
            change_reason='DPD',
        )

    def test_process_loan_for_channeling(self):
        status, message = process_loan_for_channeling(self.loan)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(message, "Channeling loan status data missing")

        ChannelingLoanStatusFactory(
            channeling_eligibility_status=ChannelingEligibilityStatusFactory(
                application=self.application
            ),
            loan=self.loan,
            channeling_type="BSS"
        )
        status, message = process_loan_for_channeling(self.loan)
        self.assertEqual(status, ChannelingStatusConst.SUCCESS)
        self.assertIsNone(message)

    @mock.patch('juloserver.disbursement.clients.xfers.XfersClient.get_julo_account_info')
    def test_approve_loan_for_channeling(self, mock_calculate_balance):
        mock_calculate_balance.return_value = {'available_balance': 10000000000}
        bss_config = self.feature_setting.parameters['BSS']
        status, message = approve_loan_for_channeling(self.loan, 'y', 'BSS', None)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(message, "Channeling configuration not set")

        status, message = approve_loan_for_channeling(None, 'y', 'BSS', bss_config)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(message, "Loan not found")

        status, message = approve_loan_for_channeling(self.loan, 'y', 'BSS', bss_config)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(message, "Lender not found")

        cl_partner = PartnerFactory()
        channeling_lender = LenderCurrentFactory(
            lender_name=bss_config['general']['LENDER_NAME'],
            xfers_token="xfers_tokenforlender",
            user=cl_partner.user,
        )
        hl_partner = PartnerFactory()
        helicap = LenderCurrentFactory(
            lender_name='helicap',
            xfers_token="xfers_tokenforlender",
            user=hl_partner.user,
        )
        status, message = approve_loan_for_channeling(self.loan, 'y', 'BSS', bss_config)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(message, "Channeling transaction not found")

        LenderTransactionType.objects.create(
            transaction_type=LenderTransactionTypeConst.CHANNELING
        )
        self.loan.update_safely(lender=helicap)
        status, message = approve_loan_for_channeling(self.loan, 'y', 'BSS', bss_config)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(message, "Lender excluded")

        self.loan.update_safely(lender=channeling_lender)
        status, message = approve_loan_for_channeling(self.loan, 'y', 'BSS', bss_config)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(message, "Lender balance not found")

        LenderBalanceCurrentFactory(lender=channeling_lender, available_balance=self.loan.loan_amount - 1)
        status, message = approve_loan_for_channeling(self.loan, 'y', 'BSS', bss_config)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(message, "Lender balance is less than loan amount")

        channeling_lender.lenderbalancecurrent.update_safely(available_balance=2 * self.loan.loan_amount)
        channeling_loan_status = ChannelingLoanStatusFactory(
            channeling_eligibility_status=ChannelingEligibilityStatusFactory(
                application=self.application
            ),
            loan=self.loan,
            channeling_type="BSS"
        )
        status, message = approve_loan_for_channeling(self.loan, 'y', 'BSS', bss_config)
        self.assertEqual(status, ChannelingStatusConst.FAILED)
        self.assertEqual(message, "Channeling loan status data missing")

        channeling_loan_status.update_safely(channeling_status='process')
        status, message = approve_loan_for_channeling(self.loan, 'n', 'BSS', bss_config)
        self.assertEqual(status, ChannelingStatusConst.SUCCESS)
        self.assertIsNotNone(message)

    @mock.patch(
        'juloserver.channeling_loan.services.general_services.get_channeling_loan_configuration'
    )
    def test_fama_channeling_payment_interest_monthly_tarik_dana(
        self, mock_get_channeling_loan_configuration
    ):
        """
        loan 3mil, duration 6 month with 10% interest
        expected output
        Installment 514,684
        Principal [
            489,684
            493,765
            497,880
            502,029
            506,212
            510,431
        ]
        Interest [
            25,000
            20,919
            16,805
            12,656
            8,472
            4,252
        ]
        """

        self.loan.fund_transfer_ts = self.current_ts.replace(
            hour=8, minute=0, year=2023, month=3, day=10
        )
        self.loan.loan_amount = 3000000
        # because transaction method data already generated in
        # src/juloserver/conftest.py::generate_initial_data::data_seed_for_transaction_method
        self.loan.transaction_method = TransactionMethod.objects.get(
            id=TransactionMethodCode.SELF.code
        )
        mock_get_channeling_loan_configuration.return_value = {
            "general": {
                "INTEREST_PERCENTAGE": 10,
                "DAYS_IN_YEAR": 360,
            }
        }
        payments = [
            PaymentFactory(
                id=99999911,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=4, day=10)
                ).date(),
            ),
            PaymentFactory(
                id=99999912,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=5, day=9)
                ).date(),
            ),
            PaymentFactory(
                id=99999913,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=6, day=8)
                ).date(),
            ),
            PaymentFactory(
                id=99999914,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=7, day=7)
                ).date(),
            ),
            PaymentFactory(
                id=99999915,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=8, day=6)
                ).date(),
            ),
            PaymentFactory(
                id=99999916,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=9, day=5)
                ).date(),
            ),
        ]
        self.loan.loan_duration = 6
        self.loan.save()
        channeling_interest = ChannelingInterest(
            self.loan, ChannelingConst.FAMA, 0.1, 360, list(payments)
        )
        result = channeling_interest.pmt_channeling_payment_interest()
        expected_result = {
            99999911: 25000.0,
            99999912: 20919.0,
            99999913: 16805.0,
            99999914: 12656.0,
            99999915: 8472.0,
            99999916: 4252.0,
        }
        self.assertEqual(result, expected_result)

    def test_fama_channeling_payment_interest_monthly_risk_premium(self):
        """
        loan 3mil, duration 6 month with 10% interest
        expected output
        Installment 514,684
        Principal [
            489,684
            493,765
            497,880
            502,029
            506,212
            510,431
        ]
        Interest [
            25,000
            20,919
            16,805
            12,656
            8,472
            4,252
        ]
        """

        self.loan.fund_transfer_ts = self.current_ts.replace(
            hour=8, minute=0, year=2023, month=3, day=10
        )
        self.loan.loan_amount = 3000000
        self.loan.loan_disbursement_amount = 3000000
        self.loan.transaction_method = TransactionMethodFactory(
            id=TransactionMethodCode.E_COMMERCE.code
        )
        payments = [
            PaymentFactory(
                id=99999911,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=4, day=10)
                ).date(),
            ),
            PaymentFactory(
                id=99999912,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=5, day=9)
                ).date(),
            ),
            PaymentFactory(
                id=99999913,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=6, day=8)
                ).date(),
            ),
            PaymentFactory(
                id=99999914,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=7, day=7)
                ).date(),
            ),
            PaymentFactory(
                id=99999915,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=8, day=6)
                ).date(),
            ),
            PaymentFactory(
                id=99999916,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=9, day=5)
                ).date(),
            ),
        ]
        self.feature_setting.update_safely(is_active=True)
        self.feature_setting.parameters[ChannelingConst.FAMA]['general'][
            'INTEREST_PERCENTAGE'
        ] = 5.5
        self.feature_setting.parameters[ChannelingConst.FAMA]['general'][
            'RISK_PREMIUM_PERCENTAGE'
        ] = 4.5
        self.feature_setting.save()
        (_, _, total_interest_percentage) = get_interest_rate_config(
            ChannelingConst.FAMA, None, False
        )
        self.loan.loan_duration = 6
        self.loan.save()
        channeling_interest = ChannelingInterest(
            self.loan, ChannelingConst.FAMA, total_interest_percentage, 360, list(payments)
        )
        result = channeling_interest.pmt_channeling_payment_interest()
        expected_result = {
            99999911: 25000.0,
            99999912: 20919.0,
            99999913: 16805.0,
            99999914: 12656.0,
            99999915: 8472.0,
            99999916: 4252.0,
        }
        self.assertEqual(result, expected_result)

    def test_pmt_monthly_interest(self):
        loan_amount = 3_000_000
        payments = [
            PaymentFactory(
                id=99999911,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=4, day=10)
                ).date(),
            ),
            PaymentFactory(
                id=99999912,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=5, day=9)
                ).date(),
            ),
            PaymentFactory(
                id=99999913,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=6, day=8)
                ).date(),
            ),
            PaymentFactory(
                id=99999914,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=7, day=7)
                ).date(),
            ),
            PaymentFactory(
                id=99999915,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=8, day=6)
                ).date(),
            ),
            PaymentFactory(
                id=99999916,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=9, day=5)
                ).date(),
            ),
        ]
        annual_interest = 10
        self.loan.fund_transfer_ts = self.current_ts.replace(
            hour=8, minute=0, year=2023, month=3, day=5
        )
        self.loan.loan_duration = 6
        self.loan.save()
        channeling_interest = ChannelingInterest(
            self.loan, ChannelingConst.FAMA, annual_interest, 360, list(payments)
        )
        channeling_loan_payments, interest_dict = channeling_interest.pmt_monthly_interest(1000000)
        first_channeling_loan_payment = channeling_loan_payments[0]
        last_channeling_loan_payment = channeling_loan_payments[-1]
        self.assertEqual(last_channeling_loan_payment.actual_daily_interest, 0)
        self.assertNotEqual(first_channeling_loan_payment.actual_daily_interest, 0)

    def test_is_account_had_loan_paid_off(self):
        self.assertFalse(is_account_had_loan_paid_off(self.account))

        LoanFactory(
            account=self.account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
        )
        self.assertTrue(is_account_had_loan_paid_off(self.account))

    def test_is_account_status_entered_gt_420(self):
        self.assertFalse(is_account_status_entered_gt_420(self.account))

        AccountStatusHistoryFactory(account=self.account, status_old_id=420, status_new_id=432)
        self.assertTrue(is_account_status_entered_gt_420(self.account))

    def test_is_account_had_installment_paid_off(self):
        # payment not paid yet
        payment = PaymentFactory(loan=self.loan)
        payment.payment_status_id = PaymentStatusCodes.PAYMENT_NOT_DUE
        payment.save()

        result = is_account_had_installment_paid_off(self.account)
        self.assertFalse(result)

        payment = PaymentFactory(loan=self.loan)

        for code in PaymentStatusCodes.paid_status_codes():
            payment.payment_status_id = code
            payment.save()
            result = is_account_had_installment_paid_off(self.account)
            self.assertTrue(result)


    def test_get_channeling_loan_config_for_ineligibilities(self):
        ineligibilites = get_editable_ineligibilities_config()
        expected = {
            "HAVENT_PAID_OFF_LOAN": True,
            "LOAN_HAS_INTEREST_BENEFIT": True,
            "HAVENT_PAID_OFF_AN_INSTALLMENT": False,
            "ACCOUNT_STATUS_MORE_THAN_420_AT_SOME_POINT": True,
        }
        self.assertEqual(ineligibilites, expected)

        # case inactive
        self.ineligibilities_feature.update_safely(is_active=False)

        ineligibilites = get_editable_ineligibilities_config()
        self.assertEqual(ineligibilites, None)

    @patch('juloserver.channeling_loan.services.general_services.get_editable_ineligibilities_config')
    def test_get_general_channeling_ineligible_conditions(self, mock_get_general):
        # case inactive
        mock_get_general.return_value = None
        all_ineligible_conditions = [
            GeneralIneligible.LOAN_NOT_FOUND,
            # GeneralIneligible.LOAN_ADJUSTED_RATE,
            GeneralIneligible.ZERO_INTEREST_LOAN_NOT_ALLOWED,
            GeneralIneligible.HAVENT_PAID_OFF_A_LOAN,
            GeneralIneligible.HAVENT_PAID_OFF_AN_INSTALLMENT,
            GeneralIneligible.ACCOUNT_STATUS_MORE_THAN_420_AT_SOME_POINT,
            GeneralIneligible.AUTODEBIT_INTEREST_BENEFIT,
            GeneralIneligible.LOAN_HAS_INTEREST_BENEFIT,
            GeneralIneligible.LOAN_FROM_PARTNER,
        ]

        result = get_general_channeling_ineligible_conditions(self.loan)
        self.assertEqual(all_ineligible_conditions, list(result.keys()))

        # case active
        mock_get_general.return_value = {
            "HAVENT_PAID_OFF_LOAN": False,
            "LOAN_HAS_INTEREST_BENEFIT": False,
            "HAVENT_PAID_OFF_AN_INSTALLMENT": True,
            "ACCOUNT_STATUS_MORE_THAN_420_AT_SOME_POINT": True,
        }
        result = get_general_channeling_ineligible_conditions(self.loan)
        all_ineligible_conditions.remove(GeneralIneligible.HAVENT_PAID_OFF_A_LOAN)
        all_ineligible_conditions.remove(GeneralIneligible.LOAN_HAS_INTEREST_BENEFIT)
        self.assertEqual(all_ineligible_conditions, list(result.keys()))

    @mock.patch(
        'juloserver.channeling_loan.services.general_services.get_channeling_loan_configuration'
    )
    def test_permata_channeling_payment_interest_monthly(
        self, mock_get_channeling_loan_configuration
    ):
        """
        loan 3mil, duration 6 month with 10% interest
        expected output
        Installment 514,684
        Principal [
            489,684
            493,765
            497,880
            502,029
            506,212
            510,431
        ]
        Interest [
            25,000
            20,919
            16,805
            12,656
            8,472
            4,254
        ]
        """

        self.loan.fund_transfer_ts = self.current_ts.replace(
            hour=8, minute=0, year=2023, month=3, day=10
        )
        self.loan.loan_amount = 3000000
        # because transaction method data already generated in
        # src/juloserver/conftest.py::generate_initial_data::data_seed_for_transaction_method
        self.loan.transaction_method = TransactionMethod.objects.get(
            id=TransactionMethodCode.SELF.code
        )
        mock_get_channeling_loan_configuration.return_value = {
            "general": {
                "INTEREST_PERCENTAGE": 10,
                "DAYS_IN_YEAR": 360,
            }
        }
        payments = [
            PaymentFactory(
                id=99999911,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=4, day=10)
                ).date(),
            ),
            PaymentFactory(
                id=99999912,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=5, day=9)
                ).date(),
            ),
            PaymentFactory(
                id=99999913,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=6, day=8)
                ).date(),
            ),
            PaymentFactory(
                id=99999914,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=7, day=7)
                ).date(),
            ),
            PaymentFactory(
                id=99999915,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=8, day=6)
                ).date(),
            ),
            PaymentFactory(
                id=99999916,
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=9, day=5)
                ).date(),
            ),
        ]
        self.loan.loan_duration = 6
        self.loan.save()
        channeling_interest = ChannelingInterest(
            self.loan, ChannelingConst.PERMATA, 0.1, 360, list(payments)
        )
        result = channeling_interest.pmt_channeling_payment_interest()
        expected_result = {
            99999911: 25000.0,
            99999912: 20919.0,
            99999913: 16805.0,
            99999914: 12656.0,
            99999915: 8472.0,
            99999916: 4252.0,
        }
        self.assertEqual(result, expected_result)
        channeling_inserted = ChannelingLoanPayment.objects.filter(
            channeling_type=ChannelingConst.PERMATA
        ).exists()
        self.assertTrue(channeling_inserted)

    def test_get_channeling_daily_duration(self):
        payments = [
            PaymentFactory(
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=4, day=10)
                ).date()
            ),
            PaymentFactory(
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=5, day=9)
                ).date()
            ),
            PaymentFactory(
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=6, day=8)
                ).date()
            ),
            PaymentFactory(
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=7, day=7)
                ).date()
            ),
            PaymentFactory(
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=8, day=6)
                ).date()
            ),
            PaymentFactory(
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=9, day=5)
                ).date()
            ),
        ]
        self.loan.fund_transfer_ts = self.current_ts.replace(
            hour=8, minute=0, year=2023, month=4, day=10
        )
        self.loan.save()
        result = get_channeling_daily_duration(self.loan, payments)
        diff = 149
        self.assertEqual(result, diff)

    def test_get_fama_channeling_admin_fee(self):
        Payment.objects.all().delete()
        self.loan.fund_transfer_ts = self.current_ts.replace(
            hour=8, minute=0, year=2023, month=4, day=10
        )
        self.loan.loan_amount = 1000000
        self.loan.transaction_method_id = 1
        self.loan.save()
        channeling_loan_status = ChannelingLoanStatusFactory(
            channeling_eligibility_status=ChannelingEligibilityStatusFactory(
                application=self.application
            ),
            loan=self.loan,
            channeling_interest_amount=50000,
        )
        payments = [
            PaymentFactory(
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=4, day=10)
                ).date(),
                loan=self.loan,
                payment_number=1,
            ),
            PaymentFactory(
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=5, day=9)
                ).date(),
                loan=self.loan,
                payment_number=2,
            ),
            PaymentFactory(
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=6, day=8)
                ).date(),
                loan=self.loan,
                payment_number=3,
            ),
            PaymentFactory(
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=7, day=7)
                ).date(),
                loan=self.loan,
                payment_number=4,
            ),
            PaymentFactory(
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=8, day=6)
                ).date(),
                loan=self.loan,
                payment_number=5,
            ),
            PaymentFactory(
                due_date=timezone.localtime(
                    self.current_ts.replace(year=2023, month=9, day=5)
                ).date(),
                loan=self.loan,
                payment_number=6,
            ),
        ]
        for payment in payments:
            interest_fee = 0
            daily_fee = 0
            if payment.payment_number == 1:
                interest_fee = 50_000
                daily_fee = 20_000
            temp = ChannelingLoanPaymentFactory(
                payment=self.loan.payment_set.first(),
                interest_amount=interest_fee,
                actual_daily_interest=daily_fee,
                channeling_type=ChannelingConst.FAMA,
            )

        LoanAdjustedRate.objects.create(
            loan=self.loan,
            adjusted_monthly_interest_rate=0.03,
            adjusted_provision_rate=0,
            max_fee=0,
            simple_fee=0,
        )

        channeling_loan_config = self.feature_setting.parameters[ChannelingConst.FAMA]
        result = get_fama_channeling_admin_fee(channeling_loan_status, channeling_loan_config)
        self.assertEqual(int(result), -30_000)

    def test_upload_to_sftp_server(self):
        mock_client = Mock()

        SFTPProcess(sftp_client=mock_client).upload(content='sample', remote_path='test.txt')
        mock_client.upload.assert_called_once_with(content='sample', remote_path='test.txt')

        mock_client.reset_mock()
        SFTPProcess(sftp_client=mock_client).upload(content=b'sample', remote_path='test.txt')
        mock_client.upload.assert_called_once_with(content=b'sample', remote_path='test.txt')

    def test_download_from_sftp_server(self):
        mock_client = Mock()
        SFTPProcess(sftp_client=mock_client).download(remote_path='test.txt')
        mock_client.download.assert_called_once_with(remote_path='test.txt')

    def test_get_list_dir_from_sftp_server(self):
        mock_client = Mock()
        SFTPProcess(sftp_client=mock_client).list_dir(remote_dir_path='test')
        mock_client.list_dir.assert_called_once_with(remote_dir_path='test')

    def test_validate_bss_custom_rac(self):
        rac_configuration = self.feature_setting.parameters["BSS"]["rac"]

        self.loan.application_id2 = self.application.id
        self.customer = CustomerFactory()
        self.loan.customer = self.customer
        self.loan.save()
        self.application.customer = self.customer
        self.application.save()

        # TC 1: max age not exceeded
        result, reason = validate_bss_custom_rac(self.loan, rac_configuration)
        self.assertTrue(result)
        self.assertEqual(reason, "")

        # TC 2: FTC max os amount not exceeded
        result, reason = validate_bss_custom_rac(self.loan, rac_configuration)
        self.assertTrue(result)
        self.assertEqual(reason, "")

        # TC 3: NON FTC max os amount not exceeded
        result, reason = validate_bss_custom_rac(self.loan, rac_configuration)
        self.assertTrue(result)
        self.assertEqual(reason, "")

        self.channeling_loan_payment = ChannelingLoanPaymentFactory(
            payment=self.loan.payment_set.first(),
            principal_amount=self.loan.loan_amount,
            interest_amount=0.5 * self.loan.loan_amount,
            actual_daily_interest=0,
            channeling_type=ChannelingConst.FAMA,
        )

        self.loan.loan_amount = 11_000_000
        self.loan.save()

        # TC 4: FTC max os amount exceeded
        result, reason = validate_bss_custom_rac(self.loan, rac_configuration)
        self.assertFalse(result)
        self.assertEqual(reason, "Cannot pass max os amount, config 10000000, actual 11000000")

        self.loan2 = LoanFactory(
            application=self.loan.get_application,
            customer=self.loan.customer,
            account=self.account,
            lender=self.lender,
            fund_transfer_ts=timezone.localtime(timezone.now()) + timedelta(days=1),
        )
        self.channeling_loan_payment2 = ChannelingLoanPaymentFactory(
            payment=self.loan2.payment_set.first(),
            principal_amount=self.loan2.loan_amount,
            interest_amount=0.5 * self.loan2.loan_amount,
            actual_daily_interest=0,
            channeling_type=ChannelingConst.BSS,
        )

        # TC 5: NON FTC max os amount exceeded
        result, reason = validate_bss_custom_rac(self.loan, rac_configuration)
        self.assertFalse(result)
        self.assertEqual(reason, "Cannot pass max os amount, config 12000000, actual 20000000")

        # TC 6: max age exceeded
        self.customer.dob = date(1916, 10, 3)
        self.customer.save()
        result, reason = validate_bss_custom_rac(self.loan, rac_configuration)
        self.assertFalse(result)

    @patch('juloserver.channeling_loan.services.general_services.encrypt_content_with_gpg')
    @patch('juloserver.channeling_loan.services.general_services.SFTPProcess')
    @patch('juloserver.channeling_loan.services.general_services.settings')
    def test_encrypt_data_and_upload_to_fama_sftp_server(
        self,
        mock_settings,
        mock_sftp_process,
        mock_encrypt_content_with_gpg,
    ):
        mock_settings.ENVIRONMENT = 'test'
        sftp_client = Mock()

        mock_encrypt_content_with_gpg.return_value = True, 'encrypted data'
        encrypt_data_and_upload_to_sftp_server(
            gpg_recipient='test',
            gpg_key_data='test',
            sftp_client=sftp_client,
            content='sample',
            filename='test.txt',
        )
        mock_sftp_process().upload.assert_called_once_with(
            content='encrypted data', remote_path='test.txt'
        )

        mock_sftp_process().upload.reset_mock()

        mock_encrypt_content_with_gpg.return_value = False, 'error'
        encrypt_data_and_upload_to_sftp_server(
            gpg_recipient='test',
            gpg_key_data='test',
            sftp_client=sftp_client,
            content='sample',
            filename='test.txt',
        )
        mock_sftp_process().upload.assert_not_called()

    @patch('juloserver.channeling_loan.services.general_services.decrypt_content_with_gpg')
    @patch('juloserver.channeling_loan.services.general_services.settings')
    def test_decrypt_data(self, mock_settings, mock_decrypt_content_with_gpg):
        mock_settings.ENVIRONMENT = 'test'

        mock_decrypt_content_with_gpg.return_value = True, b'decrypted data'
        result = decrypt_data(
            filename='test.txt',
            content='sample',
            passphrase='sample',
            gpg_recipient='test',
            gpg_key_data='test',
        )
        self.assertEqual(result, 'decrypted data')

        mock_decrypt_content_with_gpg.return_value = False, b'error'
        result = decrypt_data(
            filename='test.txt',
            content='sample',
            passphrase='sample',
            gpg_recipient='test',
            gpg_key_data='test',
        )
        self.assertIsNone(result)

    @patch('juloserver.channeling_loan.services.general_services.get_channeling_loan_configuration')
    def test_get_filename_counter_suffix_length(self, mock_get_channeling_loan_configuration):
        mock_get_channeling_loan_configuration.return_value = {
            'filename_counter_suffix': {
                'is_active': True,
                'LENGTH': 3,
            }
        }
        self.assertEqual(get_filename_counter_suffix_length("mock_channeling_type"), 3)
        mock_get_channeling_loan_configuration.assert_called_once_with("mock_channeling_type")

        mock_get_channeling_loan_configuration.return_value = {
            'filename_counter_suffix': {
                'is_active': False,
                'LENGTH': 3,
            }
        }
        self.assertIsNone(get_filename_counter_suffix_length("mock_channeling_type"))

        mock_get_channeling_loan_configuration.return_value = None
        self.assertIsNone(get_filename_counter_suffix_length("mock_channeling_type"))

    @patch(
        'juloserver.channeling_loan.services.general_services.get_filename_counter_suffix_length'
    )
    def test_get_next_filename_counter_suffix(self, mock_get_filename_counter_suffix_length):
        channeling_type = "FAMA"
        action_type = "disbursement"
        current_ts = datetime(2024, 6, 18, 10, 30, 0)

        mock_get_filename_counter_suffix_length.return_value = 3
        suffix = get_next_filename_counter_suffix(channeling_type, action_type, current_ts)
        self.assertEqual(suffix, "001")  # 0 + 1, padded to length 3
        mock_get_filename_counter_suffix_length.assert_called_once_with(channeling_type)

        mock_get_filename_counter_suffix_length.reset_mock()
        channeling_loan_send_file_tracking = ChannelingLoanSendFileTrackingFactory(
            channeling_type=channeling_type,
            action_type=action_type,
        )
        channeling_loan_send_file_tracking.cdate = current_ts
        channeling_loan_send_file_tracking.save()
        suffix = get_next_filename_counter_suffix(channeling_type, action_type, current_ts)
        self.assertEqual(suffix, "002")  # 1 + 1, padded to length 3
        mock_get_filename_counter_suffix_length.assert_called_once_with(channeling_type)

        mock_get_filename_counter_suffix_length.reset_mock()
        mock_get_filename_counter_suffix_length.return_value = None
        suffix = get_next_filename_counter_suffix(channeling_type, action_type, current_ts)
        self.assertEqual(suffix, "")
        mock_get_filename_counter_suffix_length.assert_called_once_with(channeling_type)

    def test_validate_custom_rac_fama(self):
        # j1_product_line = ProductLine.objects.filter(pk=1)
        # if not j1_product_line:
        # FAMA feature setting `EXCLUDE_MOTHER_MAIDEN_NAME_FAMA` not active
        rac_configuration = self.feature_setting.parameters["FAMA"]["rac"]
        status, msg = validate_custom_rac(self.loan, "FAMA", rac_configuration)
        self.assertEqual(status, True)
        self.assertEqual(msg, '')

        # FAMA feature setting `EXCLUDE_MOTHER_MAIDEN_NAME_FAMA` active, and mother name got restricted
        self.feature_setting_rac_exclude_mother_maiden_name.is_active=True
        self.feature_setting_rac_exclude_mother_maiden_name.save()
        self.loan.customer.mother_maiden_name='MAMA'
        self.loan.customer.save()
        status, msg = validate_custom_rac(self.loan, "FAMA", rac_configuration)
        self.assertEqual(status, False)
        self.assertEqual(msg, 'Restricted mother maiden name')

        # FAMA feature setting `EXCLUDE_MOTHER_MAIDEN_NAME_FAMA` active, empty mother maiden name
        self.feature_setting_rac_exclude_mother_maiden_name.is_active = True
        self.feature_setting_rac_exclude_mother_maiden_name.save()
        self.loan.customer.mother_maiden_name = None
        self.loan.customer.save()
        status, msg = validate_custom_rac(self.loan, "FAMA", rac_configuration)
        self.assertEqual(status, False)
        self.assertEqual(msg, 'Empty mother maiden name')

        # FAMA feature setting `EXCLUDE_MOTHER_MAIDEN_NAME_FAMA` active, and mother name got restricted
        self.feature_setting_rac_exclude_mother_maiden_name.is_active = True
        self.feature_setting_rac_exclude_mother_maiden_name.save()
        self.loan.customer.mother_maiden_name = 'MaMa'
        self.loan.customer.save()
        status, msg = validate_custom_rac(self.loan, "FAMA", rac_configuration)
        self.assertEqual(status, False)
        self.assertEqual(msg, 'Restricted mother maiden name')

        # FAMA feature setting `EXCLUDE_MOTHER_MAIDEN_NAME_FAMA` active,
        # Given mother maiden has first name is mama and the last name is budi will return true
        self.feature_setting_rac_exclude_mother_maiden_name.is_active = True
        self.feature_setting_rac_exclude_mother_maiden_name.save()
        self.loan.customer.mother_maiden_name = 'Mama Budi'
        self.loan.customer.save()
        status, msg = validate_custom_rac(self.loan, "FAMA", rac_configuration)
        self.assertEqual(status, True)
        self.assertEqual(msg, '')

    def test_create_channeling_loan_api_log(self):
        valid_data = {
            'channeling_type': 'DBS',
            'application_id': '12345',
            'loan_id': 1,
            'request_type': 'SEND_LOAN',
            'http_status_code': 200,
            'request': '{"test": "data"}',
        }

        """Test successful"""
        log = create_channeling_loan_api_log(**valid_data)
        self.assertIsInstance(log, ChannelingLoanAPILog)
        self.assertEqual(log.channeling_type, valid_data['channeling_type'])
        self.assertEqual(log.application_id, valid_data['application_id'])
        self.assertEqual(log.loan_id, valid_data['loan_id'])
        self.assertEqual(log.request_type, valid_data['request_type'])
        self.assertEqual(log.http_status_code, valid_data['http_status_code'])
        self.assertEqual(log.request, valid_data['request'])
        self.assertEqual(log.response, '')  # Default value
        self.assertEqual(log.error_message, '')  # Default value

        """Test successful with optional fields"""
        data = {
            **valid_data,
            'response': '{"status": "success"}',
            'error_message': 'Some error occurred',
        }
        log = create_channeling_loan_api_log(**data)
        self.assertEqual(log.response, data['response'])
        self.assertEqual(log.error_message, data['error_message'])

        # test fail because of missing required field
        invalid_data = valid_data.copy()
        del invalid_data['channeling_type']
        with self.assertRaises(ValueError):
            create_channeling_loan_api_log(**invalid_data)

    def test_get_channeling_loan_status_by_loan_xid(self):
        loan1 = LoanFactory(loan_xid=1111111)
        loan2 = LoanFactory(loan_xid=2222222)

        channeling_loan_status1 = ChannelingLoanStatusFactory(
            loan=loan1,
            channeling_type=ChannelingConst.DBS,
            channeling_status=ChannelingStatusConst.PROCESS,
        )
        channeling_loan_status1.created_at = timezone.now()
        channeling_loan_status1.save()
        channeling_loan_status2 = ChannelingLoanStatusFactory(
            loan=loan1,
            channeling_type=ChannelingConst.DBS,
            channeling_status=ChannelingStatusConst.SUCCESS,
        )
        channeling_loan_status2.created_at = timezone.now() + timezone.timedelta(hours=1)
        channeling_loan_status2.save()
        channeling_loan_status3 = ChannelingLoanStatusFactory(
            loan=loan2,
            channeling_type=ChannelingConst.BSS,
            channeling_status=ChannelingStatusConst.PROCESS,
        )
        channeling_loan_status3.created_at = timezone.now()
        channeling_loan_status3.save()

        # Test retrieving an existing status
        status = get_channeling_loan_status_by_loan_xid(
            loan_xid="1111111", channeling_type=ChannelingConst.DBS
        )
        self.assertIsNotNone(status)
        self.assertEqual(status, channeling_loan_status2)  # Should return the latest status
        self.assertEqual(status.channeling_status, ChannelingStatusConst.SUCCESS)

        # Test retrieving a non-existent status
        status = get_channeling_loan_status_by_loan_xid(
            loan_xid="3333333", channeling_type=ChannelingConst.DBS
        )
        self.assertIsNone(status)

        # Test retrieving with wrong channeling type
        status = get_channeling_loan_status_by_loan_xid(loan_xid="1111111", channeling_type="other")
        self.assertIsNone(status)

        # Test retrieving status for a different loan
        status = get_channeling_loan_status_by_loan_xid(
            loan_xid="2222222", channeling_type=ChannelingConst.BSS
        )
        self.assertIsNotNone(status)
        self.assertEqual(status, channeling_loan_status3)

    def test_check_common_failed_channeling(self):
        lender_name = "TEST_LENDER"
        excluded_lender_name = "TEST_EXCLUDED_LENDER"
        config = {
            'general': {'LENDER_NAME': lender_name, 'EXCLUDE_LENDER_NAME': [excluded_lender_name]}
        }
        lender = LenderCurrentFactory(lender_name=lender_name)
        loan = LoanFactory(loan_amount=1000, lender=lender)

        """Test when lender doesn't exist"""
        result = check_common_failed_channeling(
            loan=loan,
            config={'general': {'LENDER_NAME': 'NON_EXISTENT_LENDER', 'EXCLUDE_LENDER_NAME': []}},
        )
        self.assertEqual(result, "Lender not found: NON_EXISTENT_LENDER")

        """Test when channeling transaction type doesn't exist"""
        result = check_common_failed_channeling(loan=loan, config=config)
        self.assertEqual(result, "Channeling transaction not found")

        # init transaction type
        LenderTransactionTypeFactory(transaction_type=LenderTransactionTypeConst.CHANNELING)

        """Test when loan's lender is in excluded list"""
        excluded_lender = LenderCurrentFactory(lender_name=excluded_lender_name)
        loan_with_excluded_lender = LoanFactory(loan_amount=1000, lender=excluded_lender)
        result = check_common_failed_channeling(loan=loan_with_excluded_lender, config=config)
        self.assertEqual(result, "Lender excluded: TEST_EXCLUDED_LENDER")

        """Test when lender balance doesn't exist"""
        result = check_common_failed_channeling(loan=loan, config=config)
        self.assertEqual(result, "Lender balance not found")

        """Test when lender balance is less than loan amount"""
        lender_balance = LenderBalanceCurrentFactory(
            lender=lender, available_balance=500  # Less than loan amount
        )
        result = check_common_failed_channeling(loan=loan, config=config)
        self.assertEqual(result, "Lender balance is less than loan amount")

        """Test when all conditions are met"""
        lender_balance.available_balance = 2000  # More than loan amount
        lender_balance.save()
        result = check_common_failed_channeling(loan=loan, config=config)
        self.assertIsNone(result)

    @patch("juloserver.channeling_loan.services.general_services.send_notification_to_slack")
    @patch("juloserver.channeling_loan.services.general_services.upload_file_as_bytes_to_oss")
    def test_upload_channeling_file_to_oss_and_slack(self, mock_upload, mock_send):
        txt_content = '8884947951|2024-12-15|-9000|306|\n8884947951|2024-11-16|-7500|306'
        filename = 'test_upload_channeling_file_to_oss_and_slack.txt'
        document_remote_filepath = "channeling_loan/lender_{}/{}".format(self.lender.id, filename)

        upload_channeling_file_to_oss_and_slack(
            content=txt_content,
            document_remote_filepath=document_remote_filepath,
            lender_id=self.lender.id,
            filename=filename,
            document_type='channeling_loan_repayment_file',
            channeling_type=ChannelingConst.DBS,
            channeling_action_type='repayment',
            slack_channel=settings.DBS_SLACK_NOTIFICATION_CHANNEL,
        )

        mock_upload.assert_called_once()
        mock_send.assert_called_once()

    def test_is_payment_due_date_day_in_exclusion_day(self):
        self.loan.payment_set.all().delete()

        exclusion_day = ['9', '10']
        is_has_exclusion_day = is_payment_due_date_day_in_exclusion_day(self.loan, exclusion_day)
        self.assertEqual(is_has_exclusion_day, True)

        exclusion_day = ['27', '28']
        is_has_exclusion_day = is_payment_due_date_day_in_exclusion_day(self.loan, exclusion_day)
        self.assertEqual(is_has_exclusion_day, False)


class TestUpdateLoanLender(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.lender = LenderCurrentFactory(lender_name='JTP')
        self.current_ts = timezone.localtime(timezone.now())

    def test_date_valid_range_when_update_loan_lender(self):
        _, channeling_loan_history1 = update_loan_lender(
            self.loan, self.lender, 'test', 'test', False
        )

        self.assertEqual(channeling_loan_history1.date_valid_from, channeling_loan_history1.cdate)
        self.assertEqual(channeling_loan_history1.date_valid_to, None)

        previous_history = ChannelingLoanHistory.objects.filter(loan=self.loan).last()

        _, channeling_loan_history2 = update_loan_lender(
            self.loan, self.lender, 'test', 'test', False
        )

        previous_history.refresh_from_db()

        # Assert that the date_valid_to of the previous history has been updated
        self.assertEqual(previous_history.date_valid_from, channeling_loan_history1.cdate)
        self.assertEqual(previous_history.date_valid_to, channeling_loan_history2.cdate)
        self.assertEqual(channeling_loan_history2.date_valid_from, channeling_loan_history2.cdate)
        self.assertEqual(channeling_loan_history2.date_valid_to, None)

    def test_is_void_update_loan_lender(self):
        original_lender = self.lender
        new_lender1 = LenderCurrentFactory(lender_name='JH')
        new_lender2 = LenderCurrentFactory(lender_name='Pascal')

        self.loan.lender = original_lender
        self.loan.save()

        # If loan lender changes in the same month and go back to original  then:
        # All the void checkbox should be False
        # CASE March : JTP > JH > PASCAL :: all is_void=false
        update_loan_lender(
            self.loan, new_lender1, 'test', 'test', False
        )
        update_loan_lender(
            self.loan, new_lender2, 'test', 'test', False
        )
        channeling_loan_histories = ChannelingLoanHistory.objects.all()
        channeling_loan_history_list = []
        for channeling_loan_history in channeling_loan_histories:
            self.assertFalse(channeling_loan_history.is_void)
            channeling_loan_history.date_valid_from = channeling_loan_history.date_valid_from - relativedelta(months=1)
            channeling_loan_history_list.append(channeling_loan_history)

        bulk_update(channeling_loan_history_list, update_fields=['date_valid_from'])

        # All the void checkbox should be True
        # CASE April : PASCAL > JTP > JH > PASCAL :: all is_void=true
        update_loan_lender(
            self.loan, new_lender2, 'test', 'test', False
        )
        update_loan_lender(
            self.loan, original_lender, 'test', 'test', False
        )
        update_loan_lender(
            self.loan, new_lender1, 'test', 'test', False
        )
        update_loan_lender(
            self.loan, new_lender2, 'test', 'test', False
        )

        channeling_loan_histories = ChannelingLoanHistory.objects.filter(
            date_valid_from__month=self.current_ts.month,
            date_valid_from__year=self.current_ts.year,
        ).all()
        channeling_loan_history_list = []
        for channeling_loan_history in channeling_loan_histories:
            self.assertTrue(channeling_loan_history.is_void)

        # Case2
        # in the same month:
        # JTP > JH > PASCAL > JH :: all is_void=false
        new_loan = LoanFactory()

        new_loan.lender = original_lender
        new_loan.save()

        update_loan_lender(
            new_loan, self.lender, 'test', 'test', False
        )

        update_loan_lender(
            new_loan, new_lender1, 'test', 'test', False
        )

        update_loan_lender(
            new_loan, new_lender2, 'test', 'test', False
        )

        update_loan_lender(
            new_loan, new_lender1, 'test', 'test', False
        )

        channeling_loan_histories = ChannelingLoanHistory.objects.filter(
            loan=new_loan
        )
        for channeling_loan_history in channeling_loan_histories:
            self.assertFalse(channeling_loan_history.is_void)


class TestLoanAdjusted(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.loan = LoanFactory(
            application=self.application,
            account=self.account,
            fund_transfer_ts=timezone.localtime(timezone.now()),
        )
        self.ineligibilities_feature = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_EDITABLE_INELIGIBILITIES,
            is_active=True,
            parameters={
                GeneralIneligible.ACCOUNT_STATUS_MORE_THAN_420_AT_SOME_POINT.name: True,
                GeneralIneligible.LOAN_HAS_INTEREST_BENEFIT.name: True,
                GeneralIneligible.HAVENT_PAID_OFF_A_LOAN.name: True,
                GeneralIneligible.HAVENT_PAID_OFF_AN_INSTALLMENT.name: True,
            },
        )
        self.feature_setting = FeatureSettingFactory(
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
                        "MAX_RATIO": None,
                        "MAX_TENOR": 9,
                        "MIN_TENOR": 1,
                        "MIN_INCOME": 2000000,
                        "MIN_WORKTIME": 3,
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "INCLUDE_LOAN_ADJUSTED": False,
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
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                },
                ChannelingConst.FAMA: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "fama_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 14,
                        "RISK_PREMIUM_PERCENTAGE": 18,
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
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "INCLUDE_LOAN_ADJUSTED": False,
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
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                },
            },
        )

    def test_filter_loan_adjusted_rate(self):
        channeling_type_list = [ChannelingConst.BSS, ChannelingConst.FAMA]
        result = filter_loan_adjusted_rate(self.loan, channeling_type_list, None)
        self.assertEqual(result, channeling_type_list)

        loan_adjusted_rate = LoanAdjustedRate.objects.create(
            loan=self.loan,
            adjusted_monthly_interest_rate=0.3,
            adjusted_provision_rate=0,
            max_fee=0,
            simple_fee=0,
        )
        result = filter_loan_adjusted_rate(self.loan, channeling_type_list, None)
        self.assertEqual(result, [])

        self.feature_setting.parameters[ChannelingConst.BSS]['rac']['INCLUDE_LOAN_ADJUSTED'] = True
        self.feature_setting.save()
        result = filter_loan_adjusted_rate(self.loan, channeling_type_list, None)
        self.assertEqual(result, [ChannelingConst.BSS])

        # test case interest is same for FAMA
        # BSS interest is larger (15%), so it wont get selected for this case
        fama_interest = self.feature_setting.parameters[ChannelingConst.FAMA]['general'][
            'INTEREST_PERCENTAGE'
        ]
        loan_adjusted_rate.adjusted_monthly_interest_rate = fama_interest / 100 / 12
        loan_adjusted_rate.save()
        self.feature_setting.parameters[ChannelingConst.FAMA]['rac']['INCLUDE_LOAN_ADJUSTED'] = True
        self.feature_setting.save()
        result = filter_loan_adjusted_rate(self.loan, channeling_type_list, None)
        self.assertEqual(result, [ChannelingConst.FAMA])

        # no lender
        fama_interest = self.feature_setting.parameters[ChannelingConst.FAMA]['general'][
            'INTEREST_PERCENTAGE'
        ]
        loan_adjusted_rate.adjusted_monthly_interest_rate = (fama_interest - 10) / 100 / 12
        loan_adjusted_rate.save()
        self.feature_setting.parameters[ChannelingConst.FAMA]['rac']['INCLUDE_LOAN_ADJUSTED'] = True
        self.feature_setting.save()
        result = filter_loan_adjusted_rate(self.loan, channeling_type_list, None)
        self.assertEqual(result, [])
        self.ineligibilities_feature.parameters[GeneralIneligible.LOAN_ADJUSTED_RATE.name] = False
        self.ineligibilities_feature.save()

        result = filter_loan_adjusted_rate(self.loan, channeling_type_list, None)
        self.assertEqual(result, channeling_type_list)


class TestDownloadApprovalServices(TestCase):
    @patch('juloserver.channeling_loan.services.general_services.SFTPProcess')
    def test_download_latest_fama_approval_file_from_sftp_server(self, mock_sftp_process):
        mock_sftp_process().list_dir.return_value = []
        filename, content = download_latest_fama_approval_file_from_sftp_server(
            FAMAChannelingConst.DISBURSEMENT
        )
        mock_sftp_process().list_dir.assert_called_once_with(remote_dir_path='Disbursement/Report')
        self.assertIsNone(filename)
        self.assertIsNone(content)

        mock_sftp_process().list_dir.reset_mock()

        mock_sftp_process().list_dir.return_value = ['example1.txt.gpg', 'example2.txt.gpg']
        mock_sftp_process().download.return_value = 'XXXXXXXXXX'
        filename, content = download_latest_fama_approval_file_from_sftp_server(
            FAMAChannelingConst.DISBURSEMENT
        )
        mock_sftp_process().list_dir.assert_called_once_with(remote_dir_path='Disbursement/Report')
        mock_sftp_process().download.assert_called_once_with(
            remote_path='Disbursement/Report/example2.txt.gpg'
        )
        self.assertEqual(filename, 'example2.txt.gpg')
        self.assertEqual(content, 'XXXXXXXXXX')

    @patch('juloserver.channeling_loan.services.general_services.SFTPProcess')
    def test_download_latest_file_from_sftp_server(self, mock_sftp_process):
        mock_sftp_process().list_dir.return_value = []
        filename, content = download_latest_file_from_sftp_server(
            get_dbs_sftp_client(), "REPAYMENT/REQUEST"
        )
        mock_sftp_process().list_dir.assert_called_once_with(remote_dir_path="REPAYMENT/REQUEST")
        self.assertIsNone(filename)
        self.assertIsNone(content)

        mock_sftp_process().list_dir.reset_mock()

        mock_sftp_process().list_dir.return_value = ['example1.txt.gpg', 'example2.txt.gpg']
        mock_sftp_process().download.return_value = 'XXXXXXXXXX'
        filename, content = download_latest_file_from_sftp_server(
            get_dbs_sftp_client(), "REPAYMENT/REQUEST"
        )
        mock_sftp_process().list_dir.assert_called_once_with(remote_dir_path="REPAYMENT/REQUEST")
        mock_sftp_process().download.assert_called_once_with(
            remote_path='REPAYMENT/REQUEST/example2.txt.gpg'
        )
        self.assertEqual(filename, 'example2.txt.gpg')
        self.assertEqual(content, 'XXXXXXXXXX')

    def test_convert_fama_approval_content_from_txt_to_csv(self):
        result = convert_fama_approval_content_from_txt_to_csv(content='')
        self.assertEqual(result, '')

        content = """JUL|JULO|20240531|2|97120.00"""
        result = convert_fama_approval_content_from_txt_to_csv(content=content)
        self.assertEqual(result, 'Application_XID,disetujui,reason\r\n')

        content = """JUL|JULO|20240531|2|97120.00
    8314060707||prod only|49870.00|20240531|Reject|Interest does not match,
    8314060708||prod only|50000.00|20240531|Approve|sample,"""
        result = convert_fama_approval_content_from_txt_to_csv(content=content)
        self.assertEqual(
            result,
            'Application_XID,disetujui,reason\r\n8314060707,n,Interest does not match;\r\n8314060708,y,sample;\r\n',
        )

    def test_convert_dbs_approval_content_from_txt_to_csv(self):
        result = convert_dbs_approval_content_from_txt_to_csv(content='')
        self.assertEqual(result, '')

        content = """002581P000081655706R   REJECT CUSTOMER RISK RATING             JLO000081655706                                                                                      R28                                 Reject
        002581P000081674320A                                           JLO000081674320  0000000860006479858                                                                                                     Approved
        002581P000081672059D   Xdays ESL                               JLO000081672059                                                                                      R62                                 Reject"""
        result = convert_dbs_approval_content_from_txt_to_csv(content=content)

        expected_result = "Application_XID,disetujui,Org,Type,"
        expected_result += "Application Number,Application Status,Reject Description,"
        expected_result += "DBS VisionPLUS Loan Account Number,REJECT CODE\r\n"
        expected_result += (
            "000081655706,n,002,581,P000081655706,R,REJECT CUSTOMER RISK RATING,,R28\r\n"
        )
        expected_result += "000081674320,y,002,581,P000081674320,A,,0000000860006479858,\r\n"
        expected_result += "000081672059,n,002,581,P000081672059,D,Xdays ESL,,R62\r\n"

        self.assertEqual(result, expected_result)

    @patch('juloserver.channeling_loan.services.general_services.upload_file_as_bytes_to_oss')
    def test_upload_approval_file_to_oss_and_create_document(self, mock_upload):
        channeling_type = 'test_channel'
        file_type = 'test_file_type'
        filename = 'test_file.pdf'
        approval_file_id = 123
        content = b'test content'

        expected_remote_filepath = '{}/{}/{}/{}'.format(
            ChannelingLoanApprovalFileConst.DOCUMENT_TYPE, channeling_type, file_type, filename
        )

        document_pk = upload_approval_file_to_oss_and_create_document(
            channeling_type=channeling_type,
            file_type=file_type,
            filename=filename,
            approval_file_id=approval_file_id,
            content=content,
        )

        # Check if the OSS upload function was called with correct arguments
        mock_upload.assert_called_once_with(
            bucket_name=settings.OSS_MEDIA_BUCKET,
            file_bytes=content,
            remote_filepath=expected_remote_filepath,
        )

        # Check if the document was created in the database
        document = Document.objects.get(pk=document_pk)
        self.assertEqual(document.document_source, approval_file_id)
        self.assertEqual(document.document_type, ChannelingLoanApprovalFileConst.DOCUMENT_TYPE)
        self.assertEqual(document.filename, filename)
        self.assertEqual(document.url, expected_remote_filepath)

    @patch('juloserver.channeling_loan.services.general_services.get_channeling_loan_configuration')
    def test_get_process_approval_response_time_delay_in_minutes(self, mock_get_config):
        # Test case 1: Configuration exists and has the specific key
        mock_get_config.return_value = {'process_approval_response': {'DELAY_MINS': 3}}
        result = get_process_approval_response_time_delay_in_minutes('channel_type_1')
        self.assertEqual(result, 3)

        # Test case 2: Configuration exists but doesn't have the specific key
        mock_get_config.return_value = {'another_config': True}
        result = get_process_approval_response_time_delay_in_minutes('channel_type_2')
        self.assertEqual(
            result,
            ChannelingLoanApprovalFileConst.PROCESS_APPROVAL_FILE_DELAY_MINS,
        )

        # Test case 3: Configuration doesn't exist
        mock_get_config.return_value = None
        result = get_process_approval_response_time_delay_in_minutes('channel_type_3')
        self.assertIsNone(result)

        # Check if the mock function was called with correct arguments
        mock_get_config.assert_called_with('channel_type_3')

    def test_mark_approval_file_processed(self):
        approval_file = ChannelingLoanApprovalFileFactory()

        # Test marking as processed without document_id
        mark_approval_file_processed(approval_file_id=approval_file.id)
        approval_file.refresh_from_db()
        self.assertTrue(approval_file.is_processed)
        self.assertIsNone(approval_file.document_id)

        # Try to mark it as processed again
        mark_approval_file_processed(approval_file.id)
        approval_file.refresh_from_db()
        self.assertTrue(approval_file.is_processed)
        self.assertIsNone(approval_file.document_id)

        approval_file.is_processed = False
        approval_file.save()

        # Test marking as processed with document_id
        document_id = 123
        mark_approval_file_processed(approval_file_id=approval_file.id, document_id=document_id)
        approval_file.refresh_from_db()
        self.assertTrue(approval_file.is_processed)
        self.assertEqual(approval_file.document_id, document_id)

        # Test with non-existent approval file id
        non_existent_id = 9999
        with self.assertRaises(ChannelingLoanApprovalFileNotFound) as context:
            mark_approval_file_processed(non_existent_id)

        self.assertIn(
            'approval_file_id = {} not found'.format(non_existent_id),
            str(context.exception),
        )

    def test_get_latest_approval_file_object(self):
        channeling_type = "FAMA"
        file_type = "disbursement"

        # Create files with different creation times
        ChannelingLoanApprovalFile.objects.all().delete()
        file1 = ChannelingLoanApprovalFileFactory(
            channeling_type=channeling_type,
            file_type=file_type,
        )
        file1.cdate = timezone.now() - timezone.timedelta(minutes=30)
        file1.save()
        file2 = ChannelingLoanApprovalFileFactory(
            channeling_type=channeling_type,
            file_type=file_type,
        )
        file2.cdate = timezone.now() - timezone.timedelta(minutes=15)
        file2.save()
        file3 = ChannelingLoanApprovalFileFactory(
            channeling_type=channeling_type,
            file_type=file_type,
            cdate=timezone.now() - timezone.timedelta(minutes=5),
        )
        file3.cdate = timezone.now() - timezone.timedelta(minutes=5)
        file3.save()

        # Test getting the latest file within a 20-minute range
        result = get_latest_approval_file_object(
            channeling_type=channeling_type, file_type=file_type, time_delay_in_minutes=50
        )
        self.assertEqual(result, file3)

        # Test when all files are outside the time range
        result = get_latest_approval_file_object(
            channeling_type=channeling_type, file_type=file_type, time_delay_in_minutes=4
        )
        self.assertIsNone(result)

        # Test with a different channeling type
        result = get_latest_approval_file_object(
            channeling_type="different_channel", file_type=file_type, time_delay_in_minutes=60
        )
        self.assertIsNone(result)

        # Test with a different file type
        result = get_latest_approval_file_object(
            channeling_type=channeling_type, file_type="different_file", time_delay_in_minutes=60
        )
        self.assertIsNone(result)

    @patch('juloserver.channeling_loan.tasks.process_permata_approval_response')
    @patch('juloserver.channeling_loan.tasks.process_fama_approval_response')
    def test_execute_new_approval_response_process(self, mock_process_fama, mock_process_permata):
        file_type = 'disbursement'

        execute_new_approval_response_process(
            channeling_type=ChannelingConst.FAMA, file_type=file_type
        )
        # Check if a new ChannelingLoanApprovalFile was created
        approval_file = ChannelingLoanApprovalFile.objects.last()
        self.assertIsNotNone(approval_file)
        self.assertEqual(approval_file.channeling_type, ChannelingConst.FAMA)
        self.assertEqual(approval_file.file_type, file_type)
        # Check if the process_fama_approval_response task was called
        mock_process_fama.delay.assert_called_once_with(
            file_type=file_type, approval_file_id=approval_file.id
        )
        mock_process_permata.delay.assert_not_called()

        mock_process_fama.reset_mock()
        execute_new_approval_response_process(
            channeling_type=ChannelingConst.PERMATA, file_type=file_type
        )
        # Check if a new ChannelingLoanApprovalFile was created
        approval_file = ChannelingLoanApprovalFile.objects.last()
        self.assertIsNotNone(approval_file)
        self.assertEqual(approval_file.channeling_type, ChannelingConst.PERMATA)
        self.assertEqual(approval_file.file_type, file_type)
        # Check if the process_permata_approval_response task was called
        mock_process_fama.delay.assert_not_called()
        mock_process_permata.delay.assert_called_once_with(
            file_type=file_type, approval_file_id=approval_file.id
        )

    @patch('juloserver.channeling_loan.services.general_services.get_file_from_oss')
    @patch('juloserver.channeling_loan.services.general_services.response_file')
    def test_get_response_approval_file_success(self, mock_response_file, mock_get_file_from_oss):
        document = DocumentFactory(url='test/path/file.txt', filename='test_file.txt')

        mock_file_stream = MagicMock()
        mock_file_stream.content_type = 'text/plain'
        mock_file_stream.read.return_value = b'file content'
        mock_get_file_from_oss.return_value = mock_file_stream

        mock_response = HttpResponse()
        mock_response_file.return_value = mock_response

        # happy case
        response = get_response_approval_file(approval_file_document_id=document.id)
        self.assertEqual(response, mock_response)
        mock_get_file_from_oss.assert_called_once_with(
            bucket_name=settings.OSS_MEDIA_BUCKET, remote_filepath=document.url
        )
        mock_response_file.assert_called_once_with(
            content_type='text/plain', content=b'file content', filename='test_file.txt'
        )

        # non-existing approval_file_document_id
        non_existent_id = 9999
        with self.assertRaises(ChannelingLoanApprovalFileDocumentNotFound) as context:
            get_response_approval_file(approval_file_document_id=non_existent_id)

        self.assertIn('document_id={} not found'.format(non_existent_id), str(context.exception))


class TestCreditScoreConversionServices(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.fs = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CREDIT_SCORE_CONVERSION,
            is_active=True,
            parameters={
                ChannelingConst.BSS: [
                    [0.9, 1.0, "A"],
                    [0.7, 0.9, "B"],
                    [0, 0.7, "C"]
                ]
            }
        )

    def test_get_credit_score_conversion(self):
        # Inactive FS
        self.fs.update_safely(is_active=False)
        self.assertIsNone(
            get_credit_score_conversion(self.customer.id, ChannelingConst.BSS)
        )

        self.fs.update_safely(is_active=True)
        channeling_bscore = ChannelingBScoreFactory(
            predict_date=date(2025, 6, 3),
            customer_id=self.customer.id,
            channeling_type=ChannelingConst.BSS,
            model_version="v1",
            pgood=0
        )
        # Unsupported lender
        self.assertIsNone(
            get_credit_score_conversion(self.customer.id, ChannelingConst.FAMA)
        )

        # Successfully get conversion
        channeling_bscore.update_safely(pgood=0.95)
        self.assertEqual(
            get_credit_score_conversion(self.customer.id, ChannelingConst.BSS), "A"
        )
        channeling_bscore.update_safely(pgood=0.9)
        self.assertEqual(
            get_credit_score_conversion(self.customer.id, ChannelingConst.BSS), "B"
        )

