import copy
import json

from mock import patch

from django.conf import settings
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from django.contrib.auth.models import Group

from juloserver.channeling_loan.constants.dbs_constants import JULO_ORG_ID_GIVEN_BY_DBS
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    LoanFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory
)
from juloserver.channeling_loan.constants import (
    FeatureNameConst as ChannelingFeatureNameConst,
    ChannelingConst,
    ChannelingLenderLoanLedgerConst,
    ChannelingStatusConst,
)
from juloserver.channeling_loan.tests.factories import (
    LenderOspAccountFactory,
    LenderOspTransactionFactory,
    ChannelingLoanStatusFactory,
)
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.followthemoney.factories import LenderCurrentFactory
from juloserver.channeling_loan.forms import CreditScoreConversionAdminForm


class TestChannelingCRMViews(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.user.groups.add(Group.objects.create(name='bo_finance'))
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.feature_setting = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG,
            is_active=True,
            parameters={
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
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": False,
                        "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": ["Saturday", "Sunday"],
                        "LIMIT": 1,
                    },
                    "force_update": {
                        "is_active": False,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {
                        "is_active": False,
                        "APPLICATIONS": []
                    }
                },
                ChannelingConst.PERMATA: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "permata_channeling",
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
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": False,
                        "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": ["Saturday", "Sunday"],
                        "LIMIT": 1,
                    },
                    "force_update": {
                        "is_active": False,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                },
            },
        )

    def test_get_loan_list(self):
        res = self.client.get("%s%s" % (
            '/channeling_loan/FAMA/list',
            '?status_now=False&datetime_range=23%2F12%2F2022+0%3A00+-+24%2F12%2F2022+0%3A00'
        ))
        self.assertEqual(res.status_code, 200)

    def test_download_loan_data(self):
        res = self.client.get(
            "%s%s"
            % (
                '/channeling_loan/PERMATA/download/disbursement',
                '?status_now=False&datetime_range=23%2F12%2F2022+0%3A00+-+24%2F12%2F2022+0%3A00',
            )
        )
        self.assertEqual(res.status_code, 200)

    def test_withdraw_batch_data(self):
        res = self.client.get(
            '/channeling_loan/lender_osp_transaction_list/',
        )
        self.assertEqual(res.status_code, 200)

    def test_withdraw_batch_detail(self):
        LenderOspTransactionFactory(
            id=5,
            balance_amount=2000000,
        )
        res = self.client.get(
            '/channeling_loan/lender_osp_transaction_detail/5',
        )
        self.assertEqual(res.status_code, 200)

    def test_withdraw_batch_insert(self):
        data = {
            "balance_amount": 2000000
        }
        res = self.client.post(
            '/channeling_loan/lender_osp_transaction_create/',
            data
        )
        self.assertEqual(res.status_code, 200)

    def test_repayment_batch_data(self):
        res = self.client.get(
            '/channeling_loan/lender_repayment_list/',
        )
        self.assertEqual(res.status_code, 200)

    def test_repayment_batch_detail(self):
        LenderOspTransactionFactory(
            id=5,
            balance_amount=2000000,
            transaction_type=ChannelingLenderLoanLedgerConst.REPAYMENT
        )
        res = self.client.get(
            '/channeling_loan/lender_repayment_detail/5',
        )
        self.assertEqual(res.status_code, 200)

    def test_repayment_batch_insert(self):
        data = {
            "balance_amount": 2000000
        }
        res = self.client.post(
            '/channeling_loan/lender_repayment_create/',
            data
        )
        self.assertEqual(res.status_code, 200)

    def test_get_balance_lender(self):
        LenderOspAccountFactory()
        res = self.client.get(
            '/channeling_loan/lender_osp_account_list/',
        )
        self.assertEqual(res.status_code, 200)

    def test_balance_lender_detail(self):
        LenderOspAccountFactory(id=9999)
        res = self.client.get(
            '/channeling_loan/lender_osp_account_edit/9999',
        )
        self.assertEqual(res.status_code, 200)

    def test_get_ar_switching_view(self):
        res = self.client.get('/channeling_loan/ar_switching')
        self.assertEqual(res.status_code, 200)

    def test_post_ar_switching_view(self):
        res = self.client.post(
            '/channeling_loan/ar_switching',
            {
                'lender_name': 'jtp',
                'url_field': '',
            }
        )
        self.assertEqual(res.status_code, 200)

        LenderCurrentFactory(lender_name='ar-switch-lender')
        FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.AR_SWITCHING_LENDER,
            is_active=True,
            parameters=(
                ('ar-switch-lender', 'AR switch lender'),
            )
        )

        res = self.client.post(
            '/channeling_loan/ar_switching',
            {
                'lender_name': 'ar-switch-lender',
                'url_field': 'https://docs.google.com/spreadsheets',
            }
        )
        self.assertEqual(res.status_code, 200)

        file_path = '{}/juloserver/channeling_loan/tests/mock_ar_switching.csv'.format(settings.BASE_DIR)
        with open(file_path) as file:
            res = self.client.post(
                '/channeling_loan/ar_switching',
                {
                    'lender_name': 'ar-switch-lender',
                    'file_field': file,
                }
            )
            self.assertEqual(res.status_code, 200)

    def test_failed_post_ar_switching_view(self):
        LenderCurrentFactory(lender_name='ar-switch-lender')
        FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.AR_SWITCHING_LENDER,
            is_active=True,
            parameters=(
                ('ar-switch-lender', 'AR switch lender'),
                ('new-switch-lender', 'AR switch lender'),
            )
        )

        file_path = '{}/juloserver/channeling_loan/tests/mock_ar_switching.txt'.format(settings.BASE_DIR)
        with open(file_path) as file:
            res = self.client.post(
                '/channeling_loan/ar_switching',
                {
                    'lender_name': 'new-switch-lender',
                    'file_field': file,
                }
            )
            self.assertEqual(res.status_code, 200)

        file_path = '{}/juloserver/channeling_loan/tests/mock_ar_switching.csv'.format(settings.BASE_DIR)
        with open(file_path) as file:
            res = self.client.post(
                '/channeling_loan/ar_switching',
                {
                    'lender_name': 'ar-switch-lender',
                    'file_field': file,
                    'url_field': 'https://docs.google.com/spreadsheets',
                }
            )
            self.assertEqual(res.status_code, 200)

    def test_get_write_off_view(self):
        res = self.client.get('/channeling_loan/write_off')
        self.assertEqual(res.status_code, 200)

    def test_post_write_off_view(self):
        res = self.client.post(
            '/channeling_loan/write_off',
            {
                'lender_name': 'jtp',
                'url_field': '',
            },
        )
        self.assertEqual(res.status_code, 200)

        LenderCurrentFactory(lender_name='write-off-lender')
        FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.LOAN_WRITE_OFF,
            is_active=True,
            parameters={
                "waiver": ['R4'],
                "restructure": [],
            },
        )

        res = self.client.post(
            '/channeling_loan/write_off',
            {
                'lender_name': 'write-off-lender',
                'url_field': 'https://docs.google.com/spreadsheets',
            },
        )
        self.assertEqual(res.status_code, 200)

        # reusing the ARS files
        file_path = '{}/juloserver/channeling_loan/tests/mock_ar_switching.csv'.format(
            settings.BASE_DIR
        )
        with open(file_path) as file:
            res = self.client.post(
                '/channeling_loan/write_off',
                {
                    'lender_name': 'write-off-lender',
                    'file_field': file,
                },
            )
            self.assertEqual(res.status_code, 200)


class TestDBSUpdateLoanStatusViewV1(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dbs_org_id = JULO_ORG_ID_GIVEN_BY_DBS
        self.dbs_callback_api_key = 'test-api-key'
        self.http_headers = {
            'HTTP_X_DBS_UUID': 'test-uuid',
            'HTTP_X_DBS_TIMESTAMP': '2023-05-15T14:30:45.123',
            'HTTP_X_DBS_ORG_ID': self.dbs_org_id,
            'HTTP_X_API_KEY': self.dbs_callback_api_key,
        }
        self.loan = LoanFactory(loan_xid=123)
        self.channeling_loan_status = ChannelingLoanStatusFactory(
            loan=self.loan,
            channeling_type=ChannelingConst.DBS,
            channeling_status=ChannelingStatusConst.PROCESS,
        )
        self.data = {
            "header": {
                "msgId": "f6e83bcc-9aa3-4f03-baf5-cba98a7d9769",
                "orgId": self.dbs_org_id,
                "timeStamp": "2023-10-15T15:07:26.123",
            },
            "data": {
                "loanApplicationStatusRequest": {
                    "contractNumber": self.loan.loan_xid,
                    "appStatus": "string",
                    "accountNumber": "string",
                    "interestRate": "string",
                    "principalAmount": 10000000.00,
                    "interestAmount": 1000.00,
                    "installmentAmount": 10000.00,
                    "adminFee": 1000.00,
                    "currency": "IDR",
                    "rejectReasons": [{"rejectCode": "string", "rejectDescription": "test reason"}],
                }
            },
        }
        self.minimized_data = {
            "header": {
                "msgId": "f6e83bcc-9aa3-4f03-baf5-cba98a7d9769",
                "orgId": self.dbs_org_id,
                "timeStamp": "2023-10-15T15:07:26.123",
            },
            "data": {
                "loanApplicationStatusRequest": {
                    "contractNumber": self.loan.loan_xid,
                    "appStatus": "string",
                }
            },
        }
        self.sample_error_response_data = {
            "header": {
                "msgId": "f6e83bcc-9aa3-4f03-baf5-cba98a7d9769",
                "timeStamp": "2023-10-15T15:07:26.123",
            },
            "data": {
                "error": {
                    "errorList": [
                        {
                            "code": "S997",
                            "message": "Please verify the input parameters",
                            "moreInfo": "CAPI15887604823577118",
                        }
                    ]
                }
            },
        }
        self.url = '/api/channeling_loan/v1/unsecuredLoans/statusUpdate'

    @patch('juloserver.channeling_loan.authentication.settings')
    @patch('juloserver.channeling_loan.services.dbs_services.encrypt_and_sign_dbs_data_with_gpg')
    def test_headers(self, mock_encrypt_and_sign_data_with_gpg, mock_settings):
        expected_response_body = 'encrypted_and_sign_body'
        mock_encrypt_and_sign_data_with_gpg.return_value = expected_response_body

        headers = {
            'X-DBS-uuid': 'test-uuid',
            'X-DBS-timestamp': '2023-05-15T14:30:45.123',
            'X-DBS-ORG_ID': self.dbs_org_id,
            'x-api-key': self.dbs_callback_api_key,
        }

        # Test missing required fields in headers
        mock_settings.DBS_CALLBACK_API_KEY = self.dbs_callback_api_key
        incomplete_headers = copy.deepcopy(headers)
        del incomplete_headers['X-DBS-uuid']
        incomplete_headers = {
            f"HTTP_{key.upper().replace('-', '_')}": value
            for key, value in incomplete_headers.items()
        }
        response = self.client.post(
            self.url, data='test', content_type='plain/text', **incomplete_headers
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.content.decode(), expected_response_body)
        mock_encrypt_and_sign_data_with_gpg.assert_called_once()
        _, kwargs = mock_encrypt_and_sign_data_with_gpg.call_args
        self.assertIn('Missing required headers', json.dumps(kwargs['data']))

        # Test invalid API key
        # mock_settings.DBS_CALLBACK_API_KEY = 'api-key'
        # invalid_api_key = copy.deepcopy(headers)
        # invalid_api_key['x-api-key'] = 'invalid-api-key'
        # response = self.client.post(self.url, data='test', content_type='plain/text', **incomplete_headers)
        # self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('juloserver.channeling_loan.authentication.settings')
    @patch(
        'juloserver.channeling_loan.services.dbs_services.DBSUpdateLoanStatusService.get_headers'
    )
    @patch('juloserver.channeling_loan.services.dbs_services.decrypt_dbs_data_with_gpg')
    @patch(
        'juloserver.channeling_loan.services.dbs_services.DBSUpdateLoanStatusService.'
        'get_channeling_loan_status'
    )
    @patch('juloserver.channeling_loan.services.dbs_services.approve_loan_for_channeling')
    @patch('juloserver.channeling_loan.services.dbs_services.encrypt_and_sign_dbs_data_with_gpg')
    def test_successful_update(
        self,
        mock_encrypt_and_sign_data_with_gpg,
        mock_approve,
        mock_get_status,
        mock_decrypt_dbs_data_with_gpg,
        mock_get_headers,
        mock_settings,
    ):
        expected_response_body = 'encrypted_and_sign_body'
        mock_encrypt_and_sign_data_with_gpg.return_value = expected_response_body
        mock_settings.DBS_CALLBACK_API_KEY = self.dbs_callback_api_key
        mock_get_headers.return_value = (True, self.http_headers)
        mock_get_status.return_value = (True, self.channeling_loan_status)

        # full data
        data = copy.deepcopy(self.data)
        data['data']['loanApplicationStatusRequest']['rejectReasons'] = []
        mock_decrypt_dbs_data_with_gpg.return_value = json.dumps(data)
        response = self.client.post(
            self.url, data='test', content_type='plain/text', **self.http_headers
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_decrypt_dbs_data_with_gpg.assert_called_once()
        mock_encrypt_and_sign_data_with_gpg.assert_called_once()
        _, kwargs = mock_encrypt_and_sign_data_with_gpg.call_args
        self.assertIn('loanApplicationStatusResponse', json.dumps(kwargs['data']))
        mock_approve.assert_called_once_with(
            loan=self.loan, channeling_type=ChannelingConst.DBS, approval_status='y', reason=None
        )

        # minimized data
        mock_approve.reset_mock()
        mock_decrypt_dbs_data_with_gpg.reset_mock()
        mock_encrypt_and_sign_data_with_gpg.reset_mock()
        data = copy.deepcopy(self.minimized_data)
        mock_decrypt_dbs_data_with_gpg.return_value = json.dumps(data)
        response = self.client.post(self.url, data, content_type='plain/text', **self.http_headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_decrypt_dbs_data_with_gpg.assert_called_once()
        mock_encrypt_and_sign_data_with_gpg.assert_called_once()
        _, kwargs = mock_encrypt_and_sign_data_with_gpg.call_args
        self.assertIn('loanApplicationStatusResponse', json.dumps(kwargs['data']))
        mock_approve.assert_called_once_with(
            loan=self.loan, channeling_type=ChannelingConst.DBS, approval_status='y', reason=None
        )

    @patch('juloserver.channeling_loan.authentication.settings')
    @patch(
        'juloserver.channeling_loan.services.dbs_services.DBSUpdateLoanStatusService.get_headers'
    )
    @patch('juloserver.channeling_loan.services.dbs_services.decrypt_dbs_data_with_gpg')
    @patch(
        'juloserver.channeling_loan.services.dbs_services.DBSUpdateLoanStatusService.'
        'get_channeling_loan_status'
    )
    @patch('juloserver.channeling_loan.services.dbs_services.approve_loan_for_channeling')
    @patch('juloserver.channeling_loan.services.dbs_services.encrypt_and_sign_dbs_data_with_gpg')
    def test_rejected_loan(
        self,
        mock_encrypt_and_sign_data_with_gpg,
        mock_approve,
        mock_get_status,
        mock_decrypt_dbs_data_with_gpg,
        mock_get_headers,
        mock_settings,
    ):
        expected_response_body = 'encrypted_and_sign_body'
        mock_encrypt_and_sign_data_with_gpg.return_value = expected_response_body
        mock_settings.DBS_CALLBACK_API_KEY = self.dbs_callback_api_key
        mock_get_headers.return_value = (True, self.http_headers)
        mock_get_status.return_value = (True, self.channeling_loan_status)

        # full data
        data = copy.deepcopy(self.data)
        mock_decrypt_dbs_data_with_gpg.return_value = json.dumps(data)
        response = self.client.post(
            self.url, data='test', content_type='plain/text', **self.http_headers
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_decrypt_dbs_data_with_gpg.assert_called_once()
        mock_encrypt_and_sign_data_with_gpg.assert_called_once()
        mock_approve.assert_called_once_with(
            loan=self.loan,
            channeling_type=ChannelingConst.DBS,
            approval_status='n',
            reason='test reason',
        )

        # minimized data
        mock_approve.reset_mock()
        mock_decrypt_dbs_data_with_gpg.reset_mock()
        mock_encrypt_and_sign_data_with_gpg.reset_mock()
        data = copy.deepcopy(self.minimized_data)
        data['data']['loanApplicationStatusRequest']['rejectReasons'] = [  # noqa
            {"rejectCode": "string", "rejectDescription": "test reason"}
        ]
        mock_decrypt_dbs_data_with_gpg.return_value = json.dumps(data)
        response = self.client.post(
            self.url, data='test', content_type='plain/text', **self.http_headers
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_decrypt_dbs_data_with_gpg.assert_called_once()
        mock_encrypt_and_sign_data_with_gpg.assert_called_once()
        mock_approve.assert_called_once_with(
            loan=self.loan,
            channeling_type=ChannelingConst.DBS,
            approval_status='n',
            reason='test reason',
        )

    @patch('juloserver.channeling_loan.authentication.settings')
    @patch(
        'juloserver.channeling_loan.services.dbs_services.DBSUpdateLoanStatusService.get_headers'
    )
    @patch('juloserver.channeling_loan.services.dbs_services.decrypt_dbs_data_with_gpg')
    @patch('juloserver.channeling_loan.services.dbs_services.encrypt_and_sign_dbs_data_with_gpg')
    def test_invalid_headers(
        self,
        mock_encrypt_and_sign_data_with_gpg,
        mock_decrypt_dbs_data_with_gpg,
        mock_get_headers,
        mock_settings,
    ):
        expected_response_body = 'encrypted_and_sign_body'
        mock_encrypt_and_sign_data_with_gpg.return_value = expected_response_body
        mock_settings.DBS_CALLBACK_API_KEY = self.dbs_callback_api_key
        mock_get_headers.return_value = (False, self.sample_error_response_data)

        response = self.client.post(
            self.url, data='test', content_type='plain/text', **self.http_headers
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_decrypt_dbs_data_with_gpg.assert_not_called()
        mock_encrypt_and_sign_data_with_gpg.assert_called_once()
        _, kwargs = mock_encrypt_and_sign_data_with_gpg.call_args
        self.assertIn('error', json.dumps(kwargs['data']))

    @patch('juloserver.channeling_loan.authentication.settings')
    @patch(
        'juloserver.channeling_loan.services.dbs_services.DBSUpdateLoanStatusService.get_headers'
    )
    @patch('juloserver.channeling_loan.services.dbs_services.decrypt_dbs_data_with_gpg')
    @patch(
        'juloserver.channeling_loan.services.dbs_services.DBSUpdateLoanStatusService.'
        'get_channeling_loan_status'
    )
    @patch('juloserver.channeling_loan.services.dbs_services.approve_loan_for_channeling')
    @patch('juloserver.channeling_loan.services.dbs_services.encrypt_and_sign_dbs_data_with_gpg')
    def test_invalid_loan_status(
        self,
        mock_encrypt_and_sign_data_with_gpg,
        mock_approve,
        mock_get_status,
        mock_decrypt_dbs_data_with_gpg,
        mock_get_headers,
        mock_settings,
    ):
        expected_response_body = 'encrypted_and_sign_body'
        mock_encrypt_and_sign_data_with_gpg.return_value = expected_response_body
        mock_settings.DBS_CALLBACK_API_KEY = self.dbs_callback_api_key
        mock_get_headers.return_value = (True, self.http_headers)
        mock_decrypt_dbs_data_with_gpg.return_value = json.dumps(self.minimized_data)
        mock_get_status.return_value = (False, self.sample_error_response_data)
        response = self.client.post(
            self.url, data='test', content_type='plain/text', **self.http_headers
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_decrypt_dbs_data_with_gpg.assert_called_once()
        mock_approve.assert_not_called()
        mock_encrypt_and_sign_data_with_gpg.assert_called_once()
        _, kwargs = mock_encrypt_and_sign_data_with_gpg.call_args
        self.assertIn('error', json.dumps(kwargs['data']))

    @patch('juloserver.channeling_loan.authentication.settings')
    @patch(
        'juloserver.channeling_loan.services.dbs_services.DBSUpdateLoanStatusService.get_headers'
    )
    @patch('juloserver.channeling_loan.services.dbs_services.decrypt_dbs_data_with_gpg')
    @patch(
        'juloserver.channeling_loan.services.dbs_services.DBSUpdateLoanStatusService.'
        'get_channeling_loan_status'
    )
    @patch('juloserver.channeling_loan.services.dbs_services.approve_loan_for_channeling')
    @patch('juloserver.channeling_loan.services.dbs_services.encrypt_and_sign_dbs_data_with_gpg')
    def test_invalid_request_body(
        self,
        mock_encrypt_and_sign_data_with_gpg,
        mock_approve,
        mock_get_status,
        mock_decrypt_dbs_data_with_gpg,
        mock_get_headers,
        mock_settings,
    ):
        expected_response_body = 'encrypted_and_sign_body'
        mock_encrypt_and_sign_data_with_gpg.return_value = expected_response_body
        mock_settings.DBS_CALLBACK_API_KEY = self.dbs_callback_api_key
        mock_get_headers.return_value = (True, self.http_headers)
        mock_get_status.return_value = (True, self.channeling_loan_status)

        invalid_data = {
            "data": {
                "loanApplicationStatusRequest": {
                    "applicationId": "test_loan_xid",
                    "status": "INVALID_STATUS",
                }
            }
        }

        mock_decrypt_dbs_data_with_gpg.return_value = json.dumps(invalid_data)

        response = self.client.post(
            self.url, data='test', content_type='plain/text', **self.http_headers
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_decrypt_dbs_data_with_gpg.assert_called_once()
        mock_approve.assert_not_called()
        mock_encrypt_and_sign_data_with_gpg.assert_called_once()
        _, kwargs = mock_encrypt_and_sign_data_with_gpg.call_args
        self.assertIn('error', json.dumps(kwargs['data']))

    @patch('juloserver.channeling_loan.authentication.settings')
    @patch(
        'juloserver.channeling_loan.services.dbs_services.DBSUpdateLoanStatusService.get_headers'
    )
    @patch('juloserver.channeling_loan.services.dbs_services.decrypt_dbs_data_with_gpg')
    @patch(
        'juloserver.channeling_loan.services.dbs_services.DBSUpdateLoanStatusService.'
        'get_channeling_loan_status'
    )
    @patch('juloserver.channeling_loan.services.dbs_services.approve_loan_for_channeling')
    @patch('juloserver.channeling_loan.services.dbs_services.encrypt_and_sign_dbs_data_with_gpg')
    def test_fail_decrypt_request_body(
        self,
        mock_encrypt_and_sign_data_with_gpg,
        mock_approve,
        mock_get_status,
        mock_decrypt_dbs_data_with_gpg,
        mock_get_headers,
        mock_settings,
    ):
        expected_response_body = 'encrypted_and_sign_body'
        mock_encrypt_and_sign_data_with_gpg.return_value = expected_response_body
        mock_settings.DBS_CALLBACK_API_KEY = self.dbs_callback_api_key
        mock_get_headers.return_value = (True, self.http_headers)
        mock_get_status.return_value = (True, self.channeling_loan_status)

        mock_decrypt_dbs_data_with_gpg.return_value = None

        response = self.client.post(
            self.url, data='test', content_type='plain/text', **self.http_headers
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_decrypt_dbs_data_with_gpg.assert_called_once()
        mock_approve.assert_not_called()
        mock_encrypt_and_sign_data_with_gpg.assert_called_once()
        _, kwargs = mock_encrypt_and_sign_data_with_gpg.call_args
        self.assertIn('error', json.dumps(kwargs['data']))


class TestCreditScoreConversionAdminViews(TestCase):
    def setUp(self):
        self.default_values = {
            'is_active': True,
            'description': 'Credit Score Conversion Mapping',
            'category': 'channeling_loan',
            'feature_name': ChannelingFeatureNameConst.CREDIT_SCORE_CONVERSION
        }
        self.parameters = {
            "BSS": [
                [0.9, 1.0, "A"],
                [0.8, 0.9, "B"],
                [0.6, 0.8, "C+"],
                [0, 0.6, "C-"]
            ]
        }
        self.setting = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CREDIT_SCORE_CONVERSION,
            is_active=True,
            description='Credit Score Conversion Mapping',
            category='channeling_loan',
            parameters={
                "BSS": [
                    [0.9, 1.0, "A"],
                    [0.6, 0.9, "B"],
                    [0, 0.6, "C"]
                ]
            }
        )

    def test_credit_score_valid(self):
        form_data = {
            **self.default_values,
            "parameters": json.dumps(self.parameters)
        }
        form = CreditScoreConversionAdminForm(data=form_data, instance=self.setting)
        self.assertTrue(form.is_valid())

    def test_credit_score_negative_range(self):
        self.parameters["BSS"] = [
            [0.9, 1.0, "A"],
            [-0.8, 0.9, "B"],
            [0.6, 0.8, "C+"],
            [0, 0.6, "C-"]
        ]

        form_data = {
            **self.default_values,
            "parameters": json.dumps(self.parameters)
        }
        form = CreditScoreConversionAdminForm(data=form_data, instance=self.setting)
        self.assertFalse(form.is_valid())
        self.assertIn("parameters", form.errors)

        error_msg = f"""
            Configration for BSS is not correct.\n
            Range boundary should be between 0 and 1.
        """
        self.assertEqual(
            error_msg.replace(" ", ""), form.errors["parameters"][0].replace(" ", "")
        )

    def test_credit_score_invalid_range(self):
        self.parameters["BSS"] = [
            [0.9, 1.0, "A"],
            [0.9, 0.9, "B"],
            [0.6, 0.9, "C+"],
            [0, 0.6, "C-"]
        ]

        form_data = {
            **self.default_values,
            "parameters": json.dumps(self.parameters)
        }
        form = CreditScoreConversionAdminForm(data=form_data, instance=self.setting)
        self.assertFalse(form.is_valid())
        self.assertIn("parameters", form.errors)

        error_msg = f"""
            Configration for BSS is not correct.\n
            `to_score` must be greater than `from_score`.
        """
        self.assertEqual(
            error_msg.replace(" ", ""), form.errors["parameters"][0].replace(" ", "")
        )

    def test_credit_score_overlapped_range(self):
        self.parameters["BSS"] = [
            [0.9, 1.0, "A"],
            [0.8, 0.9, "B"],
            [0.4, 0.8, "C+"],
            [0, 0.6, "C-"]
        ]

        form_data = {
            **self.default_values,
            "parameters": json.dumps(self.parameters)
        }
        form = CreditScoreConversionAdminForm(data=form_data, instance=self.setting)
        self.assertFalse(form.is_valid())
        self.assertIn("parameters", form.errors)

        error_msg = f"""
            Configration for BSS is not correct.\n
            Range shouldn't be overlapped.
        """
        self.assertEqual(
            error_msg.replace(" ", ""), form.errors["parameters"][0].replace(" ", "")
        )
