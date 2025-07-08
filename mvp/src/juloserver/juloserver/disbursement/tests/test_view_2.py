from builtins import str
from mock import patch

from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.disbursement.constants import (
    DisbursementStatus,
    DisbursementVendors,
    XenditDisbursementStep,
)
from juloserver.disbursement.services import (
    DisbursementProcess,
    DisbursementServiceError,
    NewXfersDisbursementProcess,
    ValidationProcess,
    XenditDisbursementProcess,
    get_disbursement_process_by_id,
    get_list_disbursement_method,
    get_list_validation_method,
    get_name_bank_validation_by_bank_account,
    get_name_bank_validation_process_by_id,
    trigger_disburse,
)
from juloserver.disbursement.services.xendit import XenditService

from juloserver.julo.tests.factories import (
    LoanFactory,
    ApplicationFactory,
    ProductLineFactory,
    ProductLookupFactory,
    SepulsaProductFactory,
    BankFactory,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.loan.tests.factories import TransactionMethodFactory

from .factories import NameBankValidationFactory, DisbursementFactory
from juloserver.followthemoney.factories import LenderCurrentFactory
from juloserver.payment_point.tests.factories import (
    XfersEWalletTransactionFactory,
    XfersProductFactory,
)
from juloserver.grab.models import PaymentGatewayBankCode, PaymentGatewayVendor
from juloserver.customer_module.tests.factories import BankAccountDestinationFactory


class TestTriggerDisburse(TestCase):

    def setUp(self):
        self.bank_validation = NameBankValidationFactory()
        self.disbursement = DisbursementFactory()
        self.app = ApplicationFactory(name_bank_validation=self.bank_validation)
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
            product_line_type='J1'
        )
        self.loan = LoanFactory(
            name_bank_validation_id=self.bank_validation.id,
            disbursement_id=self.disbursement.id,
            application=self.app,
            loan_xid=123,
            product=ProductLookupFactory(product_line=self.product_line),
        )
        self.lender = LenderCurrentFactory(is_only_escrow_balance=True)

    def test_case_1_name_bank_validation_none(self):
        data_to_disburse = {}
        data_to_disburse['name_bank_validation_id'] = 0

        try:
            trigger_disburse(data_to_disburse)

        except DisbursementServiceError as error:
            assert str(error) == 'could not disburse loan before validate bank account'

    def test_case_2_name_bank_validation_not_success(self):
        data_to_disburse = {}
        data_to_disburse['name_bank_validation_id'] = self.bank_validation.id
        self.bank_validation.validation_status = 'FAILED'
        self.bank_validation.save()

        try:
            trigger_disburse(data_to_disburse)

        except DisbursementServiceError as error:
            assert str(error) == 'could not disburse loan to invalid bank account'

    def test_case_3_disbursement_id_not_found(self):
        data_to_disburse = {}
        data_to_disburse['name_bank_validation_id'] = self.bank_validation.id
        self.bank_validation.validation_status = 'SUCCESS'
        self.bank_validation.save()

        data_to_disburse['disbursement_id'] = 123

        try:
            trigger_disburse(data_to_disburse)

        except DisbursementServiceError as error:
            assert str(error) == 'disbursement 123 not found'

    def test_case_4_disbursement_name_bank_id_different(self):
        data_to_disburse = {}
        data_to_disburse['name_bank_validation_id'] = self.bank_validation.id
        self.bank_validation.validation_status = 'SUCCESS'
        self.bank_validation.save()

        data_to_disburse['disbursement_id'] = self.disbursement.id

        trigger_disburse(data_to_disburse)
        self.disbursement.refresh_from_db()

        assert self.disbursement.name_bank_validation.id == self.bank_validation.id

    @patch('juloserver.disbursement.services.get_disbursement_method')
    def test_case_5_get_disbursement_method(self,mock_get_disbursement_method):
        mock_get_disbursement_method.return_value = self.bank_validation.method

        data_to_disburse = {}
        data_to_disburse['name_bank_validation_id'] = self.bank_validation.id
        self.bank_validation.validation_status = 'SUCCESS'
        self.bank_validation.save()

        data_to_disburse['disbursement_id'] = None
        data_to_disburse['amount'] = 100
        data_to_disburse['external_id'] = 123
        data_to_disburse['type'] = 'loan'

        trigger_disburse(data_to_disburse)

        assert mock_get_disbursement_method.called

    @patch('juloserver.disbursement.services.get_new_disbursement_flow')
    def test_case_6_get_disbursement_flow(self,mock_get_new_disbursement_flow):
        mock_get_new_disbursement_flow.return_value = self.bank_validation.method, True

        data_to_disburse = {}
        data_to_disburse['name_bank_validation_id'] = self.bank_validation.id
        self.bank_validation.validation_status = 'SUCCESS'
        self.bank_validation.save()

        data_to_disburse['disbursement_id'] = None
        data_to_disburse['amount'] = 100
        data_to_disburse['external_id'] = 123
        data_to_disburse['type'] = 'loan'

        trigger_disburse(data_to_disburse)

        assert mock_get_new_disbursement_flow.called

    def test_case_7_disbursement_method_xfers(self):
        data_to_disburse = {}
        data_to_disburse['name_bank_validation_id'] = self.bank_validation.id
        self.bank_validation.validation_status = 'SUCCESS'
        self.bank_validation.method = 'Xendit'
        self.bank_validation.save()

        data_to_disburse['disbursement_id'] = self.disbursement.id
        self.disbursement.method = 'Xfers'
        self.disbursement.save()

        try:
            trigger_disburse(data_to_disburse)

        except DisbursementServiceError as error:
            assert str(error) == 'cannot disburse use xfers method for xendit validation'

    @patch('juloserver.disbursement.services.get_disbursement_by_obj')
    def test_case_8_call_get_disbursement_by_obj(self,mock_get_disbursement_by_obj):
        mock_get_disbursement_by_obj.return_value = None
        data_to_disburse = {}

        data_to_disburse['name_bank_validation_id'] = self.bank_validation.id
        self.bank_validation.validation_status = 'SUCCESS'
        self.bank_validation.save()
        data_to_disburse['disbursement_id'] = self.disbursement.id

        trigger_disburse(data_to_disburse)
        mock_get_disbursement_by_obj.assert_called_with(self.disbursement)

    @patch('juloserver.disbursement.services.get_new_disbursement_flow')
    def test_case_8_ewallet_transaction_with_step_2(self, mock_get_new_disbursement_flow):
        mock_get_new_disbursement_flow.return_value = self.bank_validation.method, True

        self.xfers_product = XfersProductFactory(sepulsa_product=SepulsaProductFactory())
        XfersEWalletTransactionFactory(
            loan=self.loan, customer=self.loan.customer, xfers_product=self.xfers_product
        )
        self.loan.lender_id = self.lender.pk
        self.loan.save()
        data_to_disburse = {}
        data_to_disburse['name_bank_validation_id'] = self.bank_validation.id
        self.bank_validation.validation_status = 'SUCCESS'
        self.bank_validation.save()

        data_to_disburse['disbursement_id'] = None
        data_to_disburse['amount'] = 100
        data_to_disburse['external_id'] = self.loan.loan_xid
        data_to_disburse['type'] = 'loan'

        disbursement_service = trigger_disburse(data_to_disburse)

        assert disbursement_service.disbursement.step == 2

    @patch('juloserver.disbursement.services.get_ecommerce_disbursement_experiment_method')
    @patch('juloserver.disbursement.services.is_xendit_use_step_one_disbursement')
    def test_case_xendit_experiment(self, xendit_step_one, get_experiment_method):
        xendit_step_one.return_value = False
        get_experiment_method.return_value = DisbursementVendors.XENDIT
        # loan from 211
        ecommerce_method = TransactionMethodFactory.ecommerce()
        loan = LoanFactory(
            loan_amount=800000,
            loan_disbursement_amount = 750000,
            transaction_method=ecommerce_method,
        )
        self.bank_validation.validation_status = 'SUCCESS'
        self.bank_validation.method = 'Xfers'
        self.bank_validation.save()
        data_to_disburse = {
            'disbursement_id': loan.disbursement_id, # None
            'name_bank_validation_id': self.bank_validation.id,
            'amount': loan.loan_disbursement_amount,
            'external_id': loan.loan_xid,
            'type': 'loan',
            'original_amount': loan.loan_amount
        }
        disburse_obj = trigger_disburse(data_to_disburse)
        self.assertEqual(disburse_obj.__class__, XenditDisbursementProcess)


class TestGetNameBankValidationProcessById(TestCase):

    def setUp(self):
        self.bank_validation = NameBankValidationFactory()
        self.disbursement = DisbursementFactory()

    def test_name_bank_validation_not_found(self):
        name_bank_validation_id = 0

        try:
            get_name_bank_validation_process_by_id(name_bank_validation_id)

        except DisbursementServiceError as error:
            assert str(error) == 'name bank validation process not found'


    @patch('juloserver.disbursement.services.ValidationProcess')
    def test_call_ValidationProcess(self,mock_ValidationProcess):
        mock_ValidationProcess.return_value = None
        name_bank_validation_id = self.bank_validation.id

        get_name_bank_validation_process_by_id(name_bank_validation_id)
        mock_ValidationProcess.assert_called_with(self.bank_validation)


class TestDisbursementProcessById(TestCase):

    def setUp(self):
        self.bank_validation = NameBankValidationFactory()
        self.disbursement = DisbursementFactory()

    def test_disbursement_process_not_found(self):
        disbursement_id = 0

        try:
            get_disbursement_process_by_id(disbursement_id)

        except DisbursementServiceError as error:
            assert str(error) == 'disbursement process not found'


    @patch('juloserver.disbursement.services.DisbursementProcess')
    def test_call_DisbursementProcess(self,mock_DisbursementProcess):
        mock_DisbursementProcess.return_value = None
        disbursement_id = self.disbursement.id

        get_disbursement_process_by_id(disbursement_id)
        mock_DisbursementProcess.assert_called_with(self.disbursement)


class TestGetListValidationMethod(TestCase):

    def test_call_get_list_validation_method(self):

        result = get_list_validation_method()
        assert result == ['Instamoney', 'Xfers', 'PG']


class TestGetListDisbursementMehtod(TestCase):

    def test_xendit_BCA_in_bankname(self):
        bank_name = 'BCA'
        validation_method = 'Xendit'

        result = get_list_disbursement_method(bank_name,validation_method)
        assert result == ['Instamoney', 'Bca'] and isinstance(result,list)

    def test_instamoney_BCA_in_bankname(self):
        bank_name = 'BCA'
        validation_method = 'Instamoney'

        result = get_list_disbursement_method(bank_name,validation_method)
        assert result == ['Instamoney', 'Bca'] and isinstance(result,list)

    def test_xfers_BCA_in_bankname(self):
        bank_name = 'BCA'
        validation_method = 'Xfers'

        result = get_list_disbursement_method(bank_name,validation_method)
        assert result == ['Xfers', 'Instamoney', 'Bca'] and isinstance(result,list)

    def test_xendit_BCA_not_in_bankname(self):
        bank_name = ''
        validation_method = 'Xendit'

        result = get_list_disbursement_method(bank_name,validation_method)
        assert result == ['Instamoney'] and isinstance(result,list)

    def test_instamoney_BCA_not_in_bankname(self):
        bank_name = ''
        validation_method = 'Instamoney'

        result = get_list_disbursement_method(bank_name,validation_method)
        assert result == ['Instamoney'] and isinstance(result,list)

    def test_xfers_BCA_not_in_bankname(self):
        bank_name = ''
        validation_method = 'Xfers'

        result = get_list_disbursement_method(bank_name,validation_method)
        assert result == ['Instamoney', 'Xfers'] and isinstance(result,list)

    def test_validation_method_none(self):
        bank_name = ''
        validation_method = None

        result = get_list_disbursement_method(bank_name,validation_method)
        assert result == [] and isinstance(result,list)


class TestGetNameBankValidationByBankAccount(TestCase):

    def setUp(self):
        self.bank_validation = NameBankValidationFactory(
            account_number='123',
            name_in_bank='test'
        )

    def test_bank_not_found(self):
        bank_name = 'abc'
        account_number = ''
        name_in_bank = ''

        try:
            get_name_bank_validation_by_bank_account (bank_name,account_number,name_in_bank)

        except DisbursementServiceError as error:
            assert str(error) == 'bank abc not found'

    def test_bank_found_not_nbv(self):
        bank_name = 'BANK CENTRAL ASIA, Tbk (BCA)'
        account_number = ''
        name_in_bank = ''

        result = get_name_bank_validation_by_bank_account (bank_name,account_number,name_in_bank)
        assert result == None

    def test_bank_found_return_nbv(self):
        bank_name = 'BANK CENTRAL ASIA, Tbk (BCA)'
        account_number = self.bank_validation.account_number
        name_in_bank = self.bank_validation.name_in_bank
        self.bank_validation.bank_code = 'BCA'
        self.bank_validation.validation_status = 'SUCCESS'
        self.bank_validation.save()

        result = get_name_bank_validation_by_bank_account(bank_name,account_number,name_in_bank)
        assert not result == None


class TestValidationProcess(TestCase):

    def setUp(self):
        self.bank_validation = NameBankValidationFactory()

    def test_init(self):
        result = ValidationProcess(self.bank_validation)

        assert result.name_bank_validation == self.bank_validation

    @patch('juloserver.disbursement.services.get_service')
    def test_validate_skipped_statuses(self, mock_get_service):
        self.bank_validation.validation_status='SUCCESS'
        self.bank_validation.save()

        result = ValidationProcess(self.bank_validation)
        result = result.validate()

        assert result == True

    @patch('juloserver.disbursement.services.get_service')
    def test_validate_method_empty(self, mock_get_service):
        self.bank_validation.method=''
        self.bank_validation.save()
        try:
            result = ValidationProcess(self.bank_validation)
            result = result.validate()

        except DisbursementServiceError as error:
            assert str(error) == 'method name bank validation could not be Empty!!'

    @patch('juloserver.disbursement.services.get_service')
    def test_validate_no_log(self, mock_get_service):
        self.bank_validation.method = 'Xendit'
        self.bank_validation.name_in_bank = 'test'
        self.bank_validation.validaion_id = 'test'
        self.bank_validation.reason = 'test'
        self.bank_validation.save()

        mock_response_validate_data = {
            'status': 'SUCCESS',
            'validated_name':'test1',
            'id':self.bank_validation.validation_id,
            'reason':self.bank_validation.reason,
            'error_message': 'Bank account name and name provided have to be similar'
            }

        mock_get_service.return_value.validate.return_value = mock_response_validate_data

        result = ValidationProcess(self.bank_validation)
        result = result.validate()
        assert mock_get_service.return_value.validate.called
        assert result == True

    @patch('juloserver.disbursement.services.get_service')
    def test_validate_with_log(self, mock_get_service):
        self.bank_validation.method = 'Xendit'
        self.bank_validation.name_in_bank = 'test'
        self.bank_validation.validaion_id = 'test'
        self.bank_validation.reason = 'test'
        self.bank_validation.validation_status_old = False
        self.bank_validation.save()

        mock_response_validate_data = {
            'status': 'SUCCESS',
            'validated_name':'test1',
            'id':self.bank_validation.validation_id,
            'reason':self.bank_validation.reason,
            'error_message': 'Bank account name and name provided have to be similar'
            }

        mock_get_service.return_value.validate.return_value = mock_response_validate_data

        result = ValidationProcess(self.bank_validation,self.bank_validation)
        result_validate = result.validate()

        assert mock_get_service.return_value.validate.called
        assert result_validate == True
        assert result.log_name_bank_validation == self.bank_validation

    def test_is_success_true(self):
        self.bank_validation.validation_status = 'SUCCESS'
        self.bank_validation.save()

        result = ValidationProcess(self.bank_validation)
        result = result.is_success()

        assert result == True

    def test_is_success_false(self):
        self.bank_validation.validation_status = 'FAILED'
        self.bank_validation.save()

        result = ValidationProcess(self.bank_validation)
        result = result.is_success()

        assert result == False

    def test_is_failed_true(self):
        self.bank_validation.validation_status = 'FAILED'
        self.bank_validation.save()

        result = ValidationProcess(self.bank_validation)
        result = result.is_failed()

        assert result == True


    def test_is_failed_false(self):
        self.bank_validation.validation_status = 'SUCCESS'
        self.bank_validation.save()

        result = ValidationProcess(self.bank_validation)
        result = result.is_failed()

        assert result == False


    def test_change_method(self):
        self.bank_validation.method = 'Xendit'
        self.bank_validation.bank_code = 'BCA'
        self.bank_validation.save()

        result = ValidationProcess(self.bank_validation)
        result.change_method(self.bank_validation.method)

        assert result.name_bank_validation.method == self.bank_validation.method


    @patch('juloserver.disbursement.services.get_service')
    def test_update_status(self, mock_get_service):

        self.bank_validation.validation_status = 'FAILED'
        self.bank_validation.method = 'Xendit'
        self.bank_validation.name_in_bank = 'test'
        self.bank_validation.reason = 'test'
        self.bank_validation.save()

        mock_response_process_callback_validation = {
            'status': 'SUCCESS',
            'validated_name':self.bank_validation.name_in_bank,
            'reason':self.bank_validation.reason
        }

        mock_get_service.return_value.process_callback_validation.return_value = mock_response_process_callback_validation

        result = ValidationProcess(self.bank_validation)
        result.update_status(mock_response_process_callback_validation)

        assert mock_get_service.called
        assert self.bank_validation.validation_status == mock_response_process_callback_validation['status']


    def test_get_id(self):
        result = ValidationProcess(self.bank_validation)
        result = result.get_id()

        assert result == self.bank_validation.id


    def test_get_data(self):
        self.bank_validation.bank_code = 'BCA'
        self.bank_validation.account_number = '123'
        self.bank_validation.name_in_bank = 'test'
        self.bank_validation.method = 'Xendit'
        self.bank_validation.validation_id = '123'
        self.bank_validation.validated_name = 'test'
        self.bank_validation.reason = 'test'
        self.bank_validation.save()

        result = ValidationProcess(self.bank_validation)
        result = result.get_data()

        assert result['id'] == self.bank_validation.id


    def test_is_valid_method_true(self):
        self.bank_validation.method = 'Xendit'
        self.bank_validation.save()

        result = ValidationProcess(self.bank_validation)
        result = result.is_valid_method('Xendit')

        assert result == True

    def test_is_valid_method_false(self):
        self.bank_validation.method = 'Xendit'
        self.bank_validation.save()

        result = ValidationProcess(self.bank_validation)
        result = result.is_valid_method('Xfers')

        assert result == False


    def test_update_fields(self):
        self.bank_validation.name_in_bank = ''
        self.bank_validation.save()

        result = ValidationProcess(self.bank_validation)
        result.update_fields(['name_in_bank'],['test'])

        assert result.name_bank_validation.name_in_bank == 'test'


    def test_get_method(self):
        result = ValidationProcess(self.bank_validation)
        result = result.get_method()

        assert result == self.bank_validation.method


class TestDisbursementProcess(TestCase):

    def setUp(self):
        self.disbursement = DisbursementFactory()


    def test_init(self):
        result = DisbursementProcess(self.disbursement)

        assert result.disbursement == self.disbursement


    @patch('juloserver.disbursement.services.get_service')
    def test_disburse_skipped_status(self, mock_get_service):
        self.disbursement.disburse_status = 'PENDING'
        self.disbursement.save()

        result = DisbursementProcess(self.disbursement)
        result = result.disburse()

        assert result == True
        assert not mock_get_service.called


    @patch('juloserver.disbursement.services.get_service')
    def test_disburse_insufficient_balance(self, mock_get_service):
        self.disbursement.disburse_status = 'SUCCESS'
        self.disbursement.method = 'Xendit'
        self.disbursement.save()

        mock_response_check_balance = ['INSUFICIENT BALANCE', False]

        mock_get_service.return_value.check_balance.return_value = mock_response_check_balance

        result = DisbursementProcess(self.disbursement)
        result = result.disburse()

        assert result == True
        assert not mock_get_service.return_value.disburse.called


    @patch('juloserver.disbursement.services.get_service')
    def test_disburse_sufficient_balance(self, mock_get_service):
        self.disbursement.disburse_status = 'SUCCESS'
        self.disbursement.method = 'Xendit'
        self.disbursement.save()

        mock_response_check_balance = ['sufficient balance', True]

        mock_response_disburse = {
            'status':self.disbursement.disburse_status,
            'id':self.disbursement.id,
            'reason':self.disbursement.reason,
            'reference_id':self.disbursement.reference_id
        }

        mock_get_service.return_value.check_balance.return_value = mock_response_check_balance

        mock_get_service.return_value.disburse.return_value = mock_response_disburse

        result = DisbursementProcess(self.disbursement)
        result = result.disburse()

        assert result == True
        assert mock_get_service.return_value.disburse.called


    def test_is_pending_true(self):
        self.disbursement.disburse_status = 'PENDING'
        self.disbursement.save()

        result = DisbursementProcess(self.disbursement)
        result = result.is_pending()

        assert result == True


    def test_is_pending_False(self):
        self.disbursement.disburse_status = 'SUCCESS'
        self.disbursement.save()

        result = DisbursementProcess(self.disbursement)
        result = result.is_pending()

        assert result == False


    def test_is_success_true(self):
        self.disbursement.disburse_status = 'COMPLETED'
        self.disbursement.save()

        result = DisbursementProcess(self.disbursement)
        result = result.is_success()

        assert result == True


    def test_is_success_false(self):
        self.disbursement.disburse_status = 'PENDING'
        self.disbursement.save()

        result = DisbursementProcess(self.disbursement)
        result = result.is_success()

        assert result == False

    def test_is_failed_true(self):
        self.disbursement.disburse_status = 'FAILED'
        self.disbursement.save()

        result = DisbursementProcess(self.disbursement)
        result = result.is_failed()

        assert result == True


    def test_is_failed_false(self):
        self.disbursement.disburse_status = 'SUCCESS'
        self.disbursement.save()

        result = DisbursementProcess(self.disbursement)
        result = result.is_failed()

        assert result == False


    def test_change_method_fail(self):
        self.disbursement.disburse_status = 'PENDING'
        self.disbursement.save()

        try:
            DisbursementProcess(self.disbursement).change_method('')

        except DisbursementServiceError as error:
            assert str(error) == 'Cannot change method PENDING/COMPLETED disbursement'


    @patch('juloserver.disbursement.services.get_service')
    def test_change_method_success(self, mock_get_service):
        self.disbursement.disburse_status = 'SUCCESS'
        self.disbursement.method = 'Xfers'
        self.disbursement.save()

        result = DisbursementProcess(self.disbursement)
        result.change_method('Xendit')

        assert result.disbursement.method == 'Xendit'


    @patch('juloserver.disbursement.services.get_service')
    def test_update_status(self, mock_get_service):

        self.disbursement.disburse_status = 'FAILED'
        self.disbursement.method = 'Xendit'
        self.disbursement.reason = 'test'
        self.disbursement.save()

        mock_response_process_callback_disbursement = {
            'status': 'SUCCESS',
            'reason':self.disbursement.reason
        }

        mock_get_service.return_value.process_callback_disbursement.return_value = mock_response_process_callback_disbursement

        result = DisbursementProcess(self.disbursement)
        result.update_status(mock_response_process_callback_disbursement)

        assert mock_get_service.called
        assert self.disbursement.disburse_status == mock_response_process_callback_disbursement['status']


    def test_update_fields(self):
        self.disbursement.reason = ''
        self.disbursement.save()

        result = DisbursementProcess(self.disbursement)
        result.update_fields(['reason'],['test'])

        assert result.disbursement.reason == 'test'


    def test_get_id(self):
        result = DisbursementProcess(self.disbursement)
        result = result.get_id()

        assert result == self.disbursement.id


    def test_get_data_method_non_bca(self):
        self.disbursement.name_bank_validation.id
        self.disbursement.name_bank_validation.bank_code = 'MANDIRI'
        self.disbursement.external_id ='test'
        self.disbursement.method = 'Xendit'
        self.disbursement.amount = '123'
        self.disbursement.disburse_id = '123'
        self.disbursement.disburse_status = 'test'
        self.disbursement.retry_times = 0
        self.disbursement.reason = 'test'
        self.disbursement.name_bank_validation.account_number = '123'
        self.disbursement.name_bank_validation.validated_name= 'test'
        self.disbursement.save()

        result = DisbursementProcess(self.disbursement)
        result = result.get_data()

        assert result['id'] == self.disbursement.id


    def test_get_data_method_bca(self):
        self.disbursement.name_bank_validation.id
        self.disbursement.external_id ='test'
        self.disbursement.method = 'Bca'
        self.disbursement.amount = '123'
        self.disbursement.disburse_id = '123'
        self.disbursement.disburse_status = 'test'
        self.disbursement.retry_times = 0
        self.disbursement.reason = 'test'
        self.disbursement.name_bank_validation.account_number = '123'
        self.disbursement.name_bank_validation.validated_name= 'test'
        self.disbursement.save()

        result = DisbursementProcess(self.disbursement)
        result = result.get_data()

        assert result['id'] == self.disbursement.id


    def test_is_valid_method_true(self):
        self.disbursement.method = 'Xendit'
        self.disbursement.save()

        result = DisbursementProcess(self.disbursement)
        result = result.is_valid_method('Xendit')

        assert result == True


    def test_is_valid_method_false(self):
        self.disbursement.method = 'Xendit'
        self.disbursement.save()

        result = DisbursementProcess(self.disbursement)
        result = result.is_valid_method('Xfers')

        assert result == False


    def test_get_method(self):
        self.disbursement.method = 'Xendit'
        self.disbursement.save()

        result = DisbursementProcess(self.disbursement)
        result = result.get_method()

        assert result == 'Xendit'


    def test_get_type(self):
        self.disbursement.disbursement_type = 'loan'
        self.disbursement.save()

        result = DisbursementProcess(self.disbursement)
        result = result.get_type()

        assert result == 'loan'

    def test_get_data_method_ayoconnect(self):
        self.disbursement.name_bank_validation.id
        self.disbursement.name_bank_validation.bank_code = 'MANDIRI'
        self.disbursement.external_id = 'test'
        self.disbursement.method = DisbursementVendors.AYOCONNECT
        self.disbursement.amount = '123'
        self.disbursement.disburse_id = '123'
        self.disbursement.disburse_status = 'test'
        self.disbursement.retry_times = 0
        self.disbursement.reason = 'test'
        self.disbursement.name_bank_validation.account_number = '123'
        self.disbursement.name_bank_validation.validated_name = 'test'
        self.disbursement.save()

        bank = BankFactory(bank_name='BCA')
        BankAccountDestinationFactory(
            bank=bank,
            name_bank_validation=self.disbursement.name_bank_validation,
        )
        ayoconnect_payment_gateway_vendor = PaymentGatewayVendor.objects.create(name="ayoconnect")
        PaymentGatewayBankCode.objects.create(
            payment_gateway_vendor=ayoconnect_payment_gateway_vendor,
            bank_id=bank.id,
            swift_bank_code="CENAIDJA",
            is_active=True,
        )

        result = DisbursementProcess(self.disbursement)
        result = result.get_data()

        assert result['id'] == self.disbursement.id


class TestNewXfersDisbursementProcess(TestCase):

    def setUp(self):
        self.disbursement = DisbursementFactory()


    @patch('juloserver.disbursement.services.get_xfers_service')
    def test_disburse_insufficient_balance(self,mock_get_xfers_service):

        mock_get_xfers_service.return_value.check_balance.return_value = ['INSUFICIENT BALANCE', False]

        mock_get_xfers_service.return_value.get_step.return_value = 2

        result = NewXfersDisbursementProcess(self.disbursement)
        result = result.disburse()

        history2 = self.disbursement.disbursement2history_set.first()

        self.assertIsNotNone(history2)
        assert result == True
        assert mock_get_xfers_service.called


    @patch('juloserver.disbursement.services.get_xfers_service')
    def test_disburse_sufficient_balance(self,mock_get_xfers_service):
        self.disbursement.disburse_status = 'SUCCESS'
        self.disbursement.reason = 'test'
        self.disbursement.reference_id = '123'
        self.disbursement.response_time = timezone.localtime(timezone.now())
        self.disbursement.save()

        mock_get_xfers_service.return_value.check_balance.return_value = ['sufficient balance', True]

        mock_get_xfers_service.return_value.get_step.return_value = 2

        mock_get_xfers_service.return_value.disburse.return_value = {
            'status':self.disbursement.disburse_status,
            'id':self.disbursement.id,
            'reason':self.disbursement.reason,
            'reference_id':self.disbursement.reference_id,
            'response_time':self.disbursement.response_time
        }

        result = NewXfersDisbursementProcess(self.disbursement)
        result = result.disburse()

        assert result == True
        assert mock_get_xfers_service.called


class TestXenditDisbursementProcess(TestCase):
    def setUp(self):
        self.disbursement = DisbursementFactory(
            step=XenditDisbursementStep.SECOND_STEP,
            method=DisbursementVendors.XENDIT,
        )
        self.amount = 100_000_000

    @patch.object(XenditService, 'check_balance')
    def test_disburse_insufficient(self, xendit_check_balance):
        self.disbursement.amount = self.amount
        xendit_check_balance.return_value = (DisbursementStatus.INSUFICIENT_BALANCE, False)
        process = XenditDisbursementProcess(self.disbursement)
        process.disburse()

        self.assertEqual(
            self.disbursement.reason,
            DisbursementStatus.INSUFICIENT_BALANCE,
        )

        self.assertEqual(
            self.disbursement.disburse_status,
            DisbursementStatus.FAILED,
        )

    @patch.object(XenditService, 'check_balance')
    @patch.object(XenditService, 'disburse')
    def test_disburse_sucess(self, xendit_service_disburse, xendit_check_balance):
        response_id = "1234123213"
        external_id = 'godisdeath'
        xendit_check_balance.return_value = 'enough balance', True
        xendit_service_disburse.return_value = {
            "id": response_id,
            "amount": self.amount,
            "external_id": external_id,
            "response_time": timezone.localtime(timezone.now()),
            "reason": 'sucess',
            "status": DisbursementStatus.PENDING,
        }
        process = XenditDisbursementProcess(self.disbursement)
        process.disburse()

        self.assertEqual(
            self.disbursement.disburse_status,
            DisbursementStatus.PENDING,
        )

        self.assertEqual(
            self.disbursement.reference_id,
            response_id,
        )
        self.assertEqual(self.disbursement.disburse_id, external_id)
