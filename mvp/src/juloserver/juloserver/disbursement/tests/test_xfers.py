from builtins import str
from mock import patch, MagicMock
from django.test.testcases import TestCase, override_settings
from django.db import models
from requests.exceptions import ReadTimeout

from juloserver.julo.tests.factories import LoanFactory, PartnerFactory, FeatureSettingFactory
from juloserver.followthemoney.factories import LenderReversalTransactionFactory
from juloserver.followthemoney.factories import LenderReversalTransactionHistoryFactory
from juloserver.followthemoney.factories import LenderCurrentFactory
from juloserver.followthemoney.factories import LenderBankAccountFactory

from juloserver.disbursement.services import JTFXfersService
from juloserver.disbursement.services import JTPXfersService

from juloserver.disbursement.services.xfers import (
    XfersConst,
    XfersService,
    is_xfers_retry_http_status_code,
)

from juloserver.disbursement.exceptions import XfersApiError
from juloserver.julo.constants import FeatureNameConst

from .factories import NameBankValidationFactory
from .factories import DisbursementFactory


class TestXfersService(TestCase):

    def setUp(self):
        self.name_bank_validation = NameBankValidationFactory()
        self.disbursement = DisbursementFactory()


    @patch('juloserver.disbursement.services.xfers.get_default_xfers_client')
    def test_XfersService_validate_case_1(self, mock_get_default_xfers_client):

        result = XfersService()
        result.validate(self.name_bank_validation)
        assert mock_get_default_xfers_client.called


    @patch('juloserver.disbursement.services.xfers.get_default_xfers_client')
    def test_XfersService_validate_case_2(self, mock_get_default_xfers_client):
        mock_get_default_xfers_client.return_value.add_bank_account.side_effect = XfersApiError('Test')

        result = XfersService()
        result.validate(self.name_bank_validation)
        assert mock_get_default_xfers_client.called

    @patch('juloserver.disbursement.services.xfers.get_default_xfers_client')
    def test_XfersService_check_balance_case_1(self, mock_get_default_xfers_client):
        result = XfersService()
        result = result.check_balance(100)
        assert result == ('INSUFICIENT BALANCE', False)


    @patch('juloserver.disbursement.services.xfers.get_default_xfers_client')
    def test_XfersService_check_balance_case_2(self, mock_get_default_xfers_client):

        mock_response_julo_account_info = {
            'available_balance': 99
        }

        mock_get_default_xfers_client.return_value.get_julo_account_info.return_value = mock_response_julo_account_info

        result = XfersService()
        result = result.check_balance(100)
        assert result == ('INSUFICIENT BALANCE', False)


    @patch('juloserver.disbursement.services.xfers.get_default_xfers_client')
    def test_XfersService_check_balance_case_3(self, mock_get_default_xfers_client):
        mock_get_default_xfers_client.return_value.get_julo_account_info.side_effect = XfersApiError('Test')

        result = XfersService()
        result = result.check_balance(100)
        assert result == ('Test', False)


    @patch('juloserver.disbursement.services.xfers.get_default_xfers_client')
    def test_XfersService_disburse_case_1(self, mock_get_default_xfers_client):
        self.name_bank_validation.validation_id = 'test'
        self.name_bank_validation.save()

        self.disbursement.name_bank_validation = self.name_bank_validation
        self.disbursement.external_id = '123'
        self.disbursement.retry_times = 6
        self.disbursement.save()

        result = XfersService()
        result = result.disburse(self.disbursement)
        assert result['status'] == 'PENDING'


    @patch('juloserver.disbursement.services.xfers.get_default_xfers_client')
    def test_XfersService_disburse_case_2(self, mock_get_default_xfers_client):
        mock_get_default_xfers_client.return_value.submit_withdraw.side_effect = XfersApiError('Test')

        result = XfersService()
        result = result.disburse(self.disbursement)
        assert result['status'] == 'FAILED'


    @patch('juloserver.disbursement.services.xfers.XfersConst')
    def test_XfersService_process_callback_disbursement_case_1(self, mock_XfersConst):
        data = {
            'status':'PENDING',
            'failure_reason':'test',
            'amount':'test',
            'idempotency_id':'0123456789test'
        }
        mock_XfersConst.return_value.MAP_STATUS = 'SUCCESS'

        result = XfersService()
        result = result.process_callback_disbursement(data)
        assert result['external_id'] == '0123456789'

    @patch('juloserver.disbursement.services.xfers.get_default_xfers_client')
    def test_XfersService_get_balance_case_1(self, mock_get_default_xfers_client):
        mock_get_default_xfers_client.return_value.get_julo_account_info.return_value = {
            'available_balance': 100
        }
        result = XfersService()
        result = result.get_balance()
        assert result == 100


    def test_XfersService_check_disburse_status_case_1(self):
        self.disbursement.reference_id = None
        self.disbursement.save()

        result = XfersService()
        result = result.check_disburse_status(self.disbursement)
        assert result == (True,'disbursement process failed with reference_id is null')


    @patch('juloserver.disbursement.services.xfers.get_default_xfers_client')
    def test_XfersService_check_disburse_status_case_2(self, mock_get_default_xfers_client):
        self.disbursement.reference_id = 1
        self.disbursement.disburse_id = 1
        self.disbursement.save()
        mock_response_withdraw_status = {
            'idempotency_id':0
        }
        mock_get_default_xfers_client.return_value.get_withdraw_status.return_value = mock_response_withdraw_status

        result = XfersService()
        result = result.check_disburse_status(self.disbursement)

        assert result == (False, mock_response_withdraw_status)


    @patch('juloserver.disbursement.services.xfers.get_default_xfers_client')
    def test_XfersService_check_disburse_status_case_3(self, mock_get_default_xfers_client):
        self.disbursement.reference_id = 1
        self.disbursement.disburse_id = 1
        self.disbursement.save()
        mock_response_withdraw_status = {
            'idempotency_id':1,
            'status':'failed'
        }
        mock_get_default_xfers_client.return_value.get_withdraw_status.return_value = mock_response_withdraw_status

        result = XfersService()
        result = result.check_disburse_status(self.disbursement)

        assert result == (True, mock_response_withdraw_status)


    @patch('juloserver.disbursement.services.xfers.get_default_xfers_client')
    def test_XfersService_check_disburse_status_case_4(self, mock_get_default_xfers_client):
        self.disbursement.reference_id = 1
        self.disbursement.disburse_id = 1
        self.disbursement.save()
        mock_response_withdraw_status = {
            'idempotency_id':1,
            'status':'test'
        }
        mock_get_default_xfers_client.return_value.get_withdraw_status.return_value = mock_response_withdraw_status

        result = XfersService()
        result = result.check_disburse_status(self.disbursement)

        assert result == (False, mock_response_withdraw_status)


    def test_XfersService_get_reason_case_1(self):
        result = XfersService()
        result = result.get_reason('COMPLETED','test')
        assert result == 'success'


    def test_XfersService_get_reason_case_2(self):
        result = XfersService()
        result = result.get_reason('test1','test2')
        assert result == 'test2'


@override_settings(SUSPEND_SIGNALS=True)
class TestJTFXfersService(TestCase):
    def setUp(self):
        partner = PartnerFactory()
        self.name_bank_validation = NameBankValidationFactory()
        self.disbursement = DisbursementFactory()
        self.loan = LoanFactory()
        self.lender_current = LenderCurrentFactory(user=partner.user)
        self.lender_reversal_trx = LenderReversalTransactionFactory(source_lender=self.lender_current)
        self.lender_reversal_trx_history = LenderReversalTransactionHistoryFactory(
            lender_reversal_transaction=self.lender_reversal_trx)
        self.lender_bank_account = LenderBankAccountFactory(lender=self.lender_current)

    @patch('requests.sessions.Session.get')
    def test_JTFXfersService_check_balance_case_1(self, get_jtf_xfers_client):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {'available_balance': 100000}
        get_jtf_xfers_client.return_value.get_julo_account_info.return_value = response
        result = JTFXfersService()
        result = result.check_balance(self.disbursement)

        assert result[1] == False


    @patch('juloserver.disbursement.services.xfers.get_jtf_xfers_client')
    def test_JTFXfersService_check_balance_case_2(self, mock_get_jtf_xfers_client):
        mock_get_jtf_xfers_client.return_value.get_julo_account_info.side_effect = XfersApiError('Test')

        result = JTFXfersService()
        result = result.check_balance(self.disbursement)
        assert result == ('Test', False)


    @patch('juloserver.disbursement.services.xfers.get_jtf_xfers_client')
    def test_JTFXfersService_check_balance_case_3(self,mock_get_jtf_xfers_client):
        self.disbursement.amount = 10
        self.disbursement.save()
        mock_get_jtf_xfers_client.return_value.get_julo_account_info.return_value = {
            'available_balance':9
        }

        result = JTFXfersService()
        result = result.check_balance(self.disbursement)

        assert result == ('INSUFICIENT BALANCE', False)


    def test_JTFXfersService_disburse_case_1(self):
        try:
            result = JTFXfersService()
            result = result.disburse(self.disbursement)
        except XfersApiError as error:
            assert str(error) == 'Wrong step of xfers flow'


    @patch('juloserver.disbursement.services.xfers.get_jtf_xfers_client')
    def test_JTFXfersService_disburse_case_2(self, mock_get_jtf_xfers_client):
        self.disbursement.step = 1
        self.disbursement.disburse_status = 'COMPLETED'
        self.disbursement.save()

        result = JTFXfersService()
        result = result.disburse(self.disbursement)

        assert mock_get_jtf_xfers_client.called
        assert result['status'] == 'PENDING'

    @patch('juloserver.disbursement.services.xfers.is_xfers_retry_http_status_code')
    @patch('juloserver.disbursement.services.xfers.get_jtf_xfers_client')
    def test_JTFXfersService_disburse_case_3(
        self, mock_get_jtf_xfers_client, mock_is_xfers_retry_http_status_code
    ):
        self.disbursement.step = 1
        self.disbursement.disburse_status = 'COMPLETED'
        self.disbursement.save()
        mock_get_jtf_xfers_client.return_value.submit_withdraw.side_effect = XfersApiError('Test')
        mock_is_xfers_retry_http_status_code.return_value = True

        result = JTFXfersService()
        result = result.disburse(self.disbursement)
        assert mock_get_jtf_xfers_client.called
        assert result['status'] == 'FAILED'

    @patch('juloserver.disbursement.services.xfers.get_jtf_xfers_client')
    def test_JTFXfersService_disburse_case_readtimeout(self, mock_get_jtf_xfers_client):
        self.disbursement.step = 2
        self.disbursement.save()
        mock_get_jtf_xfers_client.return_value.submit_withdraw.side_effect = ReadTimeout

        result = JTFXfersService()
        result = result.disburse(self.disbursement)
        assert mock_get_jtf_xfers_client.called
        self.assertEqual(result['status'], 'PENDING')
        self.assertEqual(result['reason'], XfersConst.READ_TIMEOUT)

    @patch('juloserver.disbursement.services.xfers.is_xfers_retry_http_status_code')
    @patch('juloserver.disbursement.services.xfers.get_jtf_xfers_client')
    def test_JTFXfersService_disburse_case_check_retry(
        self, mock_get_jtf_xfers_client, mock_is_xfers_retry_http_status_code
    ):
        self.disbursement.step = 2
        self.disbursement.save()
        mock_get_jtf_xfers_client.return_value.submit_withdraw.side_effect = XfersApiError(
            'Test', http_code=400
        )

        mock_is_xfers_retry_http_status_code.return_value = False
        result = JTFXfersService().disburse(self.disbursement)
        assert mock_get_jtf_xfers_client.called
        self.assertEqual(result['status'], 'PENDING')

        mock_is_xfers_retry_http_status_code.return_value = True
        result = JTFXfersService().disburse(self.disbursement)
        assert mock_get_jtf_xfers_client.called
        self.assertEqual(result['status'], 'FAILED')

    def test_JTFXfersService_get_step_case_1(self):
        result = JTFXfersService()
        result = result.get_step()

    @patch('requests.get')
    def test_JTFXfersService_get_balance_case_1(self, mock_get):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {'available_balance': 100}
        mock_get.return_value = response
        result = JTFXfersService()
        try:
            result = result.get_balance()
        except Exception as error:
            assert str(error)


    def test_JTFXfersService_withdraw_to_lender_case_1(self):
        try:
            result = JTFXfersService()
            result.withdraw_to_lender(self.lender_reversal_trx)

        except XfersApiError as error:
            assert str(error) == 'Wrong step of xfers flow'


    def test_JTFXfersService_withdraw_to_lender_case_2(self):
        self.lender_reversal_trx_history.lender_reversal_transaction = self.lender_reversal_trx
        self.lender_reversal_trx_history.save()

        self.lender_reversal_trx.lenderreversaltransactionhistory_set = [self.lender_reversal_trx_history]
        self.lender_reversal_trx.save()

        try:
            result = JTFXfersService()
            result.withdraw_to_lender(self.lender_reversal_trx)

        except XfersApiError as error:
            assert str(error) == 'Wrong step of xfers flow'


    @patch('juloserver.disbursement.services.xfers.XfersService.validate')
    def test_JTFXfersService_withdraw_to_lender_case_3(self, mock_validate):
        self.lender_reversal_trx_history.lender_reversal_transaction = self.lender_reversal_trx
        self.lender_reversal_trx_history.status = 'completed'
        self.lender_reversal_trx_history.save()

        self.name_bank_validation.validated_name = 'test'
        self.name_bank_validation.save()

        #repayment_va
        self.lender_bank_account.lender = self.lender_current
        self.lender_bank_account.bank_account_type = 'repayment_va'
        self.lender_bank_account.bank_account_status = 'active'
        self.lender_bank_account.bank_name = 'BANK CENTRAL ASIA, Tbk (BCA)'
        self.lender_bank_account.save()

        self.lender_current.lenderbankaccount_set = [self.lender_bank_account]
        self.lender_current.save()

        self.lender_reversal_trx.lenderreversaltransactionhistory_set = [self.lender_reversal_trx_history]
        self.lender_reversal_trx.step = 1

        #dest_lender
        self.lender_reversal_trx.destination_lender = self.lender_current
        self.lender_reversal_trx.save()

        mock_response_validate = {
            'status':'FAILED',
            'id':self.name_bank_validation.id,
            'validated_name':self.name_bank_validation.validated_name,
            'reason':'test',
            'error_message': 'Bank account name and name provided have to be similar'
        }

        mock_validate.return_value = mock_response_validate

        result = JTFXfersService()
        result = result.withdraw_to_lender(self.lender_reversal_trx)

        assert mock_validate.called
        assert result['status'] == 'failed'


    @patch('juloserver.disbursement.clients.xfers.XfersClient.submit_withdraw')
    @patch('juloserver.disbursement.clients.xfers.XfersClient.get_user_token')
    @patch('juloserver.disbursement.services.xfers.XfersService.validate')
    def test_JTFXfersService_withdraw_to_lender_case_4(self, mock_validate, mock_get_user_token, mock_submit_withdraw):
        self.lender_reversal_trx_history.lender_reversal_transaction = self.lender_reversal_trx
        self.lender_reversal_trx_history.status = 'completed'
        self.lender_reversal_trx_history.save()

        self.name_bank_validation.validated_name = 'test'
        self.name_bank_validation.validation_id = 'test123'
        self.name_bank_validation.save()

        #repayment_va
        self.lender_bank_account.lender = self.lender_current
        self.lender_bank_account.bank_account_type = 'repayment_va'
        self.lender_bank_account.bank_account_status = 'active'
        self.lender_bank_account.bank_name = 'BANK CENTRAL ASIA, Tbk (BCA)'
        self.lender_bank_account.save()

        self.lender_current.lenderbankaccount_set = [self.lender_bank_account]
        self.lender_current.save()

        self.lender_reversal_trx.lenderreversaltransactionhistory_set = [self.lender_reversal_trx_history]
        self.lender_reversal_trx.step = 1

        #dest_lender
        self.lender_reversal_trx.destination_lender = self.lender_current
        self.lender_reversal_trx.save()

        mock_response_validate = {
            'status':'SUCCESS',
            'id':self.name_bank_validation.id,
            'validated_name':self.name_bank_validation.validated_name,
            'reason':'test',
            'error_message': 'Bank account name and name provided have to be similar'
        }

        mock_response_token = {
            'user_api_token':'test'
        }

        mock_response_submit_withdraw = {
            'withdrawal_request':{
                'id':'test123'
            }
        }


        mock_validate.return_value = mock_response_validate
        mock_get_user_token.return_value = mock_response_token
        mock_submit_withdraw.return_value = mock_response_submit_withdraw

        result = JTFXfersService()
        result = result.withdraw_to_lender(self.lender_reversal_trx)

        assert mock_validate.called
        assert mock_get_user_token.called
        assert mock_submit_withdraw.called

    @patch('requests.sessions.Session.post')
    @patch('juloserver.disbursement.services.xfers.get_default_xfers_client')
    @patch('juloserver.disbursement.clients.xfers.XfersClient.get_user_token')
    @patch('juloserver.disbursement.services.xfers.XfersService.validate')
    def test_JTFXfersService_withdraw_to_lender_case_5(self, mock_validate, mock_get_user_token, mock_get_default_xfers_client, mock_post):
        self.lender_reversal_trx_history.lender_reversal_transaction = self.lender_reversal_trx
        self.lender_reversal_trx_history.status = 'completed'
        self.lender_reversal_trx_history.save()

        self.name_bank_validation.validated_name = 'test'
        self.name_bank_validation.validation_id = 'test123'
        self.name_bank_validation.save()

        #repayment_va
        self.lender_bank_account.lender = self.lender_current
        self.lender_bank_account.bank_account_type = 'repayment_va'
        self.lender_bank_account.bank_account_status = 'active'
        self.lender_bank_account.bank_name = 'BANK CENTRAL ASIA, Tbk (BCA)'
        self.lender_bank_account.save()

        self.lender_current.lenderbankaccount_set = [self.lender_bank_account]
        self.lender_current.save()

        self.lender_reversal_trx.lenderreversaltransactionhistory_set = [self.lender_reversal_trx_history]
        self.lender_reversal_trx.step = 1

        #dest_lender
        self.lender_reversal_trx.destination_lender = self.lender_current
        self.lender_reversal_trx.save()

        mock_response_validate = {
            'status':'SUCCESS',
            'id':self.name_bank_validation.id,
            'validated_name':self.name_bank_validation.validated_name,
            'reason':'test',
            'error_message': 'Bank account name and name provided have to be similar'
        }

        mock_response_token = {
            'user_api_token':'test'
        }


        mock_validate.return_value = mock_response_validate
        mock_get_user_token.return_value = mock_response_token

        result = JTFXfersService()
        result = result.withdraw_to_lender(self.lender_reversal_trx)

        assert mock_validate.called
        assert mock_get_user_token.called
        assert result['status'] == 'failed'

    def test_is_xfers_retry_http_status_code(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DISBURSEMENT_AUTO_RETRY,
            parameters={'list_xfers_retry_http_status_code': [400, 401, 500]}
        )
        self.assertTrue(is_xfers_retry_http_status_code(401))
        self.assertFalse(is_xfers_retry_http_status_code(504))

#############################################################################################

@patch('juloserver.disbursement.services.xfers.get_jtp_xfers_client')
@override_settings(SUSPEND_SIGNALS=True)
class TestJTPXfersService(TestCase):
    def setUp(self):
        partner = PartnerFactory()
        self.name_bank_validation = NameBankValidationFactory()
        self.disbursement = DisbursementFactory()
        self.loan = LoanFactory()
        self.lender_current = LenderCurrentFactory(
            xfers_token='test123',
            user=partner.user
        )
        self.lender_reversal_trx = LenderReversalTransactionFactory(source_lender=self.lender_current)
        self.lender_reversal_trx_history = LenderReversalTransactionHistoryFactory(
            lender_reversal_transaction=self.lender_reversal_trx)
        self.lender_bank_account = LenderBankAccountFactory(lender=self.lender_current)


    def test_JTPXfersService_check_balance_case_1(self, mock_jtp_client):
        mock_jtp_client.return_value.get_julo_account_info.side_effect = XfersApiError('Test')

        result = JTPXfersService(self.lender_current.id)
        result = result.check_balance(self.disbursement)
        assert result == ('Test', False)


    def test_JTPXfersService_check_balance_case_2(self, mock_jtp_client):
        self.disbursement.original_amount = 9
        self.disbursement.save()

        mock_response_julo_account_info = {
            'available_balance':10
        }

        mock_jtp_client.return_value.get_julo_account_info.return_value = mock_response_julo_account_info

        result = JTPXfersService(self.lender_current.id)
        result = result.check_balance(self.disbursement)
        assert result == ('sufficient balance', True)


    def test_JTPXfersService_check_balance_case_3(self, mock_jtp_client):
        self.disbursement.original_amount = 10
        self.disbursement.save()

        mock_response_julo_account_info = {
            'available_balance':10
        }

        mock_jtp_client.return_value.get_julo_account_info.return_value = mock_response_julo_account_info

        result = JTPXfersService(self.lender_current.id)
        result = result.check_balance(self.disbursement)
        assert result == ('INSUFICIENT BALANCE', False)


    def test_JTPXfersService_disburse_case_1(self, mock_jtp_client):
        try:
            result = JTPXfersService(self.lender_current.id)
            result = result.disburse(self.disbursement)
        except XfersApiError as error:
            assert str(error) == 'Wrong step of xfers flow'


    def test_JTPXfersService_disburse_case_2(self, mock_jtp_client):
        self.disbursement.step = 1
        self.disbursement.disburse_status = 'INITIATED'
        self.disbursement.save()

        result = JTPXfersService(self.lender_current.id)
        result = result.disburse(self.disbursement)
        assert result['status'] == 'PENDING'

    @patch('juloserver.disbursement.services.xfers.is_xfers_retry_http_status_code')
    def test_JTPXfersService_disburse_case_3(
        self, mock_is_xfers_retry_http_status_code, mock_jtp_client,
    ):
        self.disbursement.step = 1
        self.disbursement.disburse_status = 'INITIATED'
        self.disbursement.save()

        mock_jtp_client.return_value.submit_charge_jtp.side_effect = XfersApiError('Test')
        mock_is_xfers_retry_http_status_code.return_value = True

        result = JTPXfersService(self.lender_current.id)
        result = result.disburse(self.disbursement)
        assert result['status'] == 'FAILED'

    @patch('juloserver.disbursement.services.xfers.is_xfers_retry_http_status_code')
    def test_JTPXfersService_disburse_case_check_retry(
        self, mock_is_xfers_retry_http_status_code, mock_jtp_client
    ):
        self.disbursement.step = 1
        self.disbursement.save()
        mock_jtp_client.return_value.submit_charge_jtp.side_effect = XfersApiError(
            'Test', http_code=400
        )

        mock_is_xfers_retry_http_status_code.return_value = False
        result = JTPXfersService(self.lender_current.id).disburse(self.disbursement)
        assert mock_jtp_client.called
        self.assertEqual(result['status'], 'PENDING')

        mock_is_xfers_retry_http_status_code.return_value = True
        result = JTPXfersService(self.lender_current.id).disburse(self.disbursement)
        assert mock_jtp_client.called
        self.assertEqual(result['status'], 'FAILED')

    def test_JTPXfersService_get_balance_case_1(self, mock_jtp_client):
        mock_response_julo_account_info = {
            'available_balance':10
        }
        mock_jtp_client.return_value.get_julo_account_info.return_value = mock_response_julo_account_info

        result = JTPXfersService(self.lender_current.id)
        result = result.get_balance()
        assert result == mock_response_julo_account_info['available_balance']


    def test_JTPXfersService_charge_reversal_from_lender_case_1(self, mock_jtp_client):
        result = JTPXfersService(self.lender_current.id)
        result = result.charge_reversal_from_lender(self.lender_reversal_trx, True)
        assert result['status'] == 'pending'


    @patch('juloserver.followthemoney.withdraw_view.services.update_lender_balance')
    def test_JTPXfersService_charge_reversal_from_lender_case_2(self, mock_update_lender_bal, mock_jtp_client):
        self.lender_reversal_trx.source_lender = self.lender_current
        self.lender_reversal_trx.amount = 10
        self.lender_reversal_trx.save()

        result = JTPXfersService(self.lender_current.id)
        result = result.charge_reversal_from_lender(self.lender_reversal_trx)
        assert mock_update_lender_bal.called
        assert result['status'] == 'pending'


    @patch('juloserver.followthemoney.withdraw_view.services.update_lender_balance')
    def test_JTPXfersService_charge_reversal_from_lender_case_3(self, mock_update_lender_bal, mock_jtp_client):
        mock_jtp_client.return_value.submit_charge_jtp.side_effect = XfersApiError('Test')

        result = JTPXfersService(self.lender_current.id)
        result = result.charge_reversal_from_lender(self.lender_reversal_trx)
        assert result['status'] == 'failed'
        assert mock_jtp_client.return_value.submit_charge_jtp.called
