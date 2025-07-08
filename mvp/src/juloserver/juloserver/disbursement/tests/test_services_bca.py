from mock import patch, MagicMock
from django.test.testcases import TestCase
from juloserver.disbursement.exceptions import BcaApiError
from juloserver.disbursement.services.bca import BcaService

from .factories import NameBankValidationFactory
from .factories import DisbursementFactory

class TestBcaService(TestCase):
    def setUp(self):
        self.disbursement = DisbursementFactory()
        self.name_bank_validation = NameBankValidationFactory()


    @patch('juloserver.disbursement.services.bca.get_bca_client')
    def test_BcaService_init(self, mock_client):
        result = BcaService()
        assert mock_client.called


    @patch('juloserver.disbursement.services.bca.get_bca_client')
    def test_BcaService_check_balance_case_1(self, mock_client):
        mock_client.return_value.get_balance.side_effect = BcaApiError('error_test')

        result = BcaService()
        result = result.check_balance(100)

        assert mock_client.called
        assert mock_client.return_value.get_balance.called
        assert result == ('error_test',False)


    @patch('juloserver.disbursement.services.bca.get_bca_client')
    def test_BcaService_check_balance_case_2(self, mock_client):
        mock_response_get_balance = {
            'AccountDetailDataSuccess':[{
                'AvailableBalance': 110
            }]
        }
        mock_client.return_value.get_balance.return_value = mock_response_get_balance

        result = BcaService()
        result = result.check_balance(100)

        assert mock_client.called
        assert mock_client.return_value.get_balance.called
        assert result == ('sufficient balance', True)


    @patch('juloserver.disbursement.services.bca.get_bca_client')
    def test_BcaService_check_balance_case_3(self, mock_client):
        mock_response_get_balance = {
            'AccountDetailDataSuccess':[{
                'AvailableBalance': 100
            }]
        }
        mock_client.return_value.get_balance.return_value = mock_response_get_balance

        result = BcaService()
        result = result.check_balance(100)

        assert mock_client.called
        assert mock_client.return_value.get_balance.called
        assert result == ('INSUFICIENT BALANCE',False)


    @patch('juloserver.disbursement.services.bca.get_bca_client')
    def test_BcaService_disburse_case_1(self, mock_client):
        self.name_bank_validation.account_number = 'test123'
        self.name_bank_validation.save()

        self.disbursement.name_bank_validation = self.name_bank_validation
        self.disbursement.external_id = 'test123'
        self.disbursement.amount = 100
        self.disbursement.disbursement_type = 'loan'
        self.disbursement.save()

        mock_response_transfer = {
            'TransactionID':'test123',
            'Amount':100,
            'Status':'Success'
        }
        mock_client.return_value.transfer.return_value = mock_response_transfer

        result = BcaService()
        result = result.disburse(self.disbursement)
        assert mock_client.called
        assert mock_client.return_value.transfer.called
        assert result == {'reason': '', 'status': 'COMPLETED', 'amount': 100, 'id': 'test123'}


    @patch('juloserver.disbursement.services.bca.get_bca_client')
    def test_BcaService_disburse_case_2(self, mock_client):
        self.name_bank_validation.account_number = 'test123'
        self.name_bank_validation.save()

        self.disbursement.name_bank_validation = self.name_bank_validation
        self.disbursement.external_id = 'test123'
        self.disbursement.amount = 100
        self.disbursement.disbursement_type = 'loan'
        self.disbursement.save()

        mock_response_transfer = {
            'TransactionID':'test123',
            'Amount':100,
            'Status':'Test'
        }
        mock_client.return_value.transfer.return_value = mock_response_transfer

        result = BcaService()
        result = result.disburse(self.disbursement)
        assert mock_client.called
        assert mock_client.return_value.transfer.called
        assert result == {'reason': '', 'status': 'Test', 'amount': 100, 'id': 'test123'}


    @patch('juloserver.disbursement.services.bca.get_bca_client')
    def test_BcaService_disburse_case_3(self, mock_client):
        self.name_bank_validation.account_number = 'test123'
        self.name_bank_validation.save()

        self.disbursement.name_bank_validation = self.name_bank_validation
        self.disbursement.external_id = 'test123'
        self.disbursement.amount = 100
        self.disbursement.disbursement_type = 'loan'
        self.disbursement.save()

        mock_response_error = {
            'transaction_id':'test123',
            'message':'error_test',
            'status':503
        }
        mock_client.return_value.transfer.side_effect = BcaApiError(mock_response_error)

        result = BcaService()
        result = result.disburse(self.disbursement)
        assert mock_client.called
        assert mock_client.return_value.transfer.called
        assert result == {'reason': 'error_test', 'status': 'PENDING', 'amount': 100, 'id': 'test123'}


    @patch('juloserver.disbursement.services.bca.get_bca_client')
    def test_BcaService_disburse_case_4(self, mock_client):
        self.name_bank_validation.account_number = 'test123'
        self.name_bank_validation.save()

        self.disbursement.name_bank_validation = self.name_bank_validation
        self.disbursement.external_id = 'test123'
        self.disbursement.amount = 100
        self.disbursement.disbursement_type = 'loan'
        self.disbursement.save()

        mock_response_error = {
            'transaction_id':'test123',
            'message':'error_test',
            'status':'test'
        }
        mock_client.return_value.transfer.side_effect = BcaApiError(mock_response_error)

        result = BcaService()
        result = result.disburse(self.disbursement)
        assert mock_client.called
        assert mock_client.return_value.transfer.called
        assert result == {'reason': 'error_test', 'status': 'FAILED', 'amount': 100, 'id': 'test123'}


    @patch('juloserver.disbursement.services.bca.get_bca_client')
    def test_BcaService_disburse_case_5(self, mock_client):
        self.name_bank_validation.account_number = 'test123'
        self.name_bank_validation.save()

        self.disbursement.name_bank_validation = self.name_bank_validation
        self.disbursement.external_id = 'test123'
        self.disbursement.amount = 100
        self.disbursement.disbursement_type = 'cashback'
        self.disbursement.save()

        mock_response_transfer = {
            'TransactionID':'test123',
            'Amount':100,
            'Status':'Success'
        }
        mock_client.return_value.transfer.return_value = mock_response_transfer

        result = BcaService()
        result = result.disburse(self.disbursement)
        assert mock_client.called
        assert mock_client.return_value.transfer.called
        assert result == {'reason': '', 'status': 'COMPLETED', 'amount': 100, 'id': 'test123'}


    @patch('juloserver.disbursement.services.bca.get_bca_client')
    def test_BcaService_disburse_case_6(self, mock_client):
        self.name_bank_validation.account_number = 'test123'
        self.name_bank_validation.save()

        self.disbursement.name_bank_validation = self.name_bank_validation
        self.disbursement.external_id = 'test123'
        self.disbursement.amount = 100
        self.disbursement.disbursement_type = 'loan_one'
        self.disbursement.save()

        mock_response_transfer = {
            'TransactionID':'test123',
            'Amount':100,
            'Status':'Success'
        }
        mock_client.return_value.transfer.return_value = mock_response_transfer

        result = BcaService()
        result = result.disburse(self.disbursement)
        assert mock_client.called
        assert mock_client.return_value.transfer.called
        assert result == {'reason': '', 'status': 'COMPLETED', 'amount': 100, 'id': 'test123'}


    @patch('juloserver.disbursement.services.bca.get_bca_client')
    def test_BcaService_get_statements_case_1(self, mock_client):
        mock_data = {
            'Data':'test'
        }
        start_date = '2020-12-01'
        end_date = '2020-12-30'
        mock_client.return_value.get_statements.return_value = mock_data

        result = BcaService()
        result = result.get_statements(start_date,end_date)

        assert mock_client.called
        mock_client.return_value.get_statements.assert_called_with(start_date,end_date)
        assert result == mock_data['Data']


    @patch('juloserver.disbursement.services.bca.get_bca_client')
    def test_BcaService_process_callback_disbursement_case_1(self, mock_client):
        mock_data = {
            'TransactionAmount':100,
            'reference_id':'test123'
        }

        result = BcaService()
        result = result.process_callback_disbursement(mock_data)
        assert mock_client.called
        assert result == {'status': 'COMPLETED', 'reason': 'Sucess Disburse via Bca', 'external_id': 'test123', 'amount': 100}


    @patch('juloserver.disbursement.services.bca.get_bca_client')
    def test_BcaService_get_balance_case_1(self, mock_client):
        mock_response_data = {
            'AccountDetailDataSuccess':[{
                'AvailableBalance':100
            }]
        }
        mock_client.return_value.get_balance.return_value = mock_response_data
        result = BcaService()
        result = result.get_balance()
        assert mock_client.called
        assert mock_client.return_value.get_balance.called
        assert result == 100


    @patch('juloserver.disbursement.services.bca.get_bca_client')
    def test_BcaService_filter_disburse_id_from_statements_case_1(self, mock_client):
        mock_statements = [{
            'Trailer':'JULO-Disburse,test123'
        }]
        result = BcaService()
        result = result.filter_disburse_id_from_statements(mock_statements)
        assert mock_client.called
        assert result == ['test123']