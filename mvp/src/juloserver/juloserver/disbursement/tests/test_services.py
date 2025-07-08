from builtins import str
import mock
from mock import patch
from django.test.testcases import TestCase
import time
import requests

from django.test.utils import override_settings

from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.test import APITestCase
from juloserver.api_token.models import ExpiryToken as Token


from juloserver.julo.models import Customer
from juloserver.julo.models import Application

from juloserver.apiv1.constants import BankCodes
from juloserver.paylater.models import DisbursementSummary

from juloserver.julo.tests.factories import (
    ProductLineFactory,
    ProductLookupFactory,
    SepulsaProductFactory,
    FeatureSettingFactory,
    LoanFactory,
    CustomerFactory,
    ApplicationFactory,
    AuthUserFactory,
    BankFactory,
    WorkflowFactory,
)

from juloserver.disbursement.constants import (
    DisbursementVendors,
    DisbursementVendorStatus,
)
from juloserver.disbursement.services import ValidationProcess

from juloserver.julo.exceptions import JuloException
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.disbursement.exceptions import DisbursementServiceError
from .factories import NameBankValidationFactory, DisbursementFactory
from ..models import NameBankValidation
from ..services import *
from ..services.xfers import JTPXfersService
from ...customer_module.tests.factories import BankAccountDestinationFactory
from ...grab.models import PaymentGatewayVendor
from ...grab.tests.factories import PaymentGatewayBankCodeFactory
from ...julo.constants import WorkflowConst
from juloserver.payment_point.tests.factories import (
    XfersEWalletTransactionFactory,
    XfersProductFactory,
)
from faker import Faker

fake = Faker()


class TestServiceDisbursement(APITestCase):

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 150
        self.application.save()
        self.token, _created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.validation_id = 100
        self.bank_validation = NameBankValidationFactory(
            validation_id=self.validation_id,
            method='Xfers',
            account_number=123,
            name_in_bank='test',
            bank_code='BCA_SYR')
        self.bank = BankFactory(xfers_bank_code=self.bank_validation.bank_code)
        self.bank_account_destination = BankAccountDestinationFactory(
            bank=self.bank,
            name_bank_validation=self.bank_validation,
        )
        self.disbursement = DisbursementFactory(
            name_bank_validation=self.bank_validation,
            disburse_id=123456,
            method='Xfers',
            disbursement_type='loan_one')
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
            product_line_type='J1'
        )
        self.loan = LoanFactory(
            name_bank_validation_id=self.bank_validation.id,
            disbursement_id=self.disbursement.id,
            application=self.application,
            loan_xid=123456789,
            product=ProductLookupFactory(product_line=self.product_line),
        )
        self.application.name_bank_validation = self.bank_validation
        self.application.save()

    @mock.patch('juloserver.disbursement.services.xfers.get_jtp_xfers_client')
    def test_get_xfers_service(self, _mock_get_jtp_xfers_client):
        result = get_xfers_service(self.disbursement)
        assert isinstance(result, JTPXfersService)

    def test_get_validation_method(self):
        DisbursementTrafficControl.objects.create(
            rule_type='disbursement_traffic_rule',
            is_active=True,
            condition='#nth:0:0,1,2,3,4,5,6,7,8,9',
            success_value='xfers',
            key='application_id'
        )
        result = get_validation_method(self.application)
        assert result == 'Xfers'

    def test_get_validation_method_case_none_success_key(self):
        DisbursementTrafficControl.objects.create(
            rule_type='disbursement_traffic_rule',
            is_active=True,
            condition='#nth:0:0,1,2,3,4,5,6,7,8,9',
            key='application_id'
        )
        result = get_validation_method(self.application)
        assert result == 'Xfers'

    def test_is_bca_disbursement(self):
        DisbursementTrafficControl.objects.create(
            rule_type='disbursement_traffic_rule',
            is_active=True,
            condition='#nth:0:0,1,2,3,4,5,6,7,8,9',
            success_value="bca",
            key='application_id'
        )
        result = is_bca_disbursement(self.application)
        assert result

    def test_is_bca_disbursement_case_false(self):
        result = is_bca_disbursement(self.application)
        assert not result

    @patch('juloserver.disbursement.services.get_experiment_disbursement_method')
    def test_get_disbursement_method(self, mock_get_experiment_disbursement_method):
        mock_get_experiment_disbursement_method.return_value = None
        PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=PaymentGatewayVendor.objects.create(name="ayoconnect"),
            bank_id=self.bank.id,
            swift_bank_code=self.bank_validation.bank_code,
        )
        self.bank_validation.bank_code = 'bca'
        self.bank_validation.save()
        result = get_disbursement_method(self.bank_validation, self.application, self.loan.loan_xid)
        assert result == 'Bca'

        mock_get_experiment_disbursement_method.return_value = DisbursementVendors.AYOCONNECT
        result = get_disbursement_method(self.bank_validation, self.application, self.loan.loan_xid)
        assert result == DisbursementVendors.AYOCONNECT

    @patch('juloserver.disbursement.services.get_experiment_disbursement_method')
    def test_get_disbursement_method_ayc_ewallet_transaction(
        self, mock_get_experiment_disbursement_method
    ):
        mock_get_experiment_disbursement_method.return_value = None
        PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=PaymentGatewayVendor.objects.create(name="ayoconnect"),
            bank_id=self.bank.id,
            swift_bank_code=self.bank_validation.bank_code,
        )
        self.bank_validation.bank_code = 'bca'
        self.bank_validation.save()
        self.loan.transaction_method_id = TransactionMethodCode.DOMPET_DIGITAL.code
        self.loan.save()

        result = get_disbursement_method(self.bank_validation, self.application, self.loan.loan_xid)
        assert result == DisbursementVendors.AYOCONNECT

    @patch('juloserver.disbursement.services.get_experiment_disbursement_method')
    def test_get_disbursement_method_xfers_ewallet_transaction(
        self, mock_get_experiment_disbursement_method
    ):
        self.xfers_product = XfersProductFactory(sepulsa_product=SepulsaProductFactory())
        XfersEWalletTransactionFactory(
            loan=self.loan, customer=self.loan.customer, xfers_product=self.xfers_product
        )
        mock_get_experiment_disbursement_method.return_value = None
        PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=PaymentGatewayVendor.objects.create(name="ayoconnect"),
            bank_id=self.bank.id,
            swift_bank_code=self.bank_validation.bank_code,
        )
        self.bank_validation.bank_code = 'bca'
        self.bank_validation.save()
        self.loan.transaction_method_id = TransactionMethodCode.DOMPET_DIGITAL.code
        self.loan.save()

        result = get_disbursement_method(self.bank_validation, self.application, self.loan.loan_xid)
        assert result == DisbursementVendors.XFERS

    @patch('juloserver.disbursement.services.get_experiment_disbursement_method')
    def test_get_disbursement_method_case_2(self, mock_get_experiment_disbursement_method):
        # unsupported bank -> use Xfers
        mock_get_experiment_disbursement_method.return_value = None
        result = get_disbursement_method(self.bank_validation, self.application, self.loan.loan_xid)
        assert result == DisbursementVendors.XFERS

        # supported bank -> use vendor experiment
        PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=PaymentGatewayVendor.objects.create(name="ayoconnect"),
            bank_id=self.bank.id,
            swift_bank_code=self.bank_validation.bank_code,
        )
        mock_get_experiment_disbursement_method.return_value = None
        result = get_disbursement_method(self.bank_validation, self.application, self.loan.loan_xid)
        assert result == self.bank_validation.method

        mock_get_experiment_disbursement_method.return_value = DisbursementVendors.AYOCONNECT
        result = get_disbursement_method(self.bank_validation, self.application, self.loan.loan_xid)
        assert result == DisbursementVendors.AYOCONNECT

    def test_get_new_disbursement_flow_no_setting(self):
        result = get_new_disbursement_flow('test')
        assert result == ('test', False)

    @mock.patch('juloserver.disbursement.services.gen_probability')
    def test_get_new_disbursement_flow_not_found_method(self, mock_gen_probability):
        mock_gen_probability.return_value = False
        FeatureSetting.objects.create(
            feature_name='disbursement_traffic_manage',
            is_active=True,
            parameters={'test':'BCA'}
        )
        result = get_new_disbursement_flow('test')
        assert result == ('test', False)

    @mock.patch('juloserver.disbursement.services.gen_probability')
    def test_get_new_disbursement_flow_new_xfers(self, mock_gen_probability):
        mock_gen_probability.return_value = 'New_Xfers'
        FeatureSetting.objects.create(
            feature_name='disbursement_traffic_manage',
            is_active=True,
            parameters={'test':'BCA'}
        )
        result = get_new_disbursement_flow('test')
        assert result == ('Xfers', True)

    @mock.patch('juloserver.disbursement.services.gen_probability')
    def test_get_new_disbursement_flow_bca(self, mock_gen_probability):
        mock_gen_probability.return_value = 'BCA'
        FeatureSetting.objects.create(
            feature_name='disbursement_traffic_manage',
            is_active=True,
            parameters={'test':'BCA'}
        )
        result = get_new_disbursement_flow('test')
        assert result == ('Bca', False)

    def test_get_name_bank_validation_not_found(self):
        result = get_name_bank_validation(123456)
        assert result['id'] is None

    def test_get_name_bank_validation(self):
        result = get_name_bank_validation(self.bank_validation.id)
        assert result['id'] == self.bank_validation.id

    def test_get_disbursement_not_found(self):
        result = get_disbursement(123)
        assert result['id'] is None

    def test_get_disbursement(self):
        result = get_disbursement(self.disbursement.id)
        assert result['id'] == self.disbursement.id

    def test_get_multi_step_disbursement_not_found(self):
        result = get_multi_step_disbursement(111, 111)
        assert not result[0]

    @mock.patch('juloserver.disbursement.services.get_xfers_balance')
    def test_get_multi_step_disbursement_not_enough_money(self, _mock_get_xfers_balance):
        self.disbursement.step = None
        self.disbursement.save()
        result = get_multi_step_disbursement(self.disbursement.id, 111)
        assert not result[0]

    @mock.patch('juloserver.disbursement.services.get_xfers_balance')
    def test_get_multi_step_disbursement_not_found_history(self, mock_get_xfers_balance):
        mock_get_xfers_balance.return_value = 10000000
        self.disbursement.step = 2
        self.disbursement.save()
        result = get_multi_step_disbursement(self.disbursement.id, 111)
        assert result[0]

    @mock.patch('juloserver.disbursement.services.get_xfers_balance')
    def test_get_multi_step_disbursement_history_existing(self, mock_get_xfers_balance):
        Disbursement2History.objects.create(
            disbursement_id=self.disbursement.id,
            amount=10000,
            method='test',
            step=1)
        Disbursement2History.objects.create(
            disbursement_id=self.disbursement.id,
            amount=10000,
            method='test',
            step=2)
        mock_get_xfers_balance.return_value = 10000000
        self.disbursement.step = 2
        self.disbursement.save()
        result = get_multi_step_disbursement(self.disbursement.id, 111)
        assert result[0]

    @mock.patch('juloserver.disbursement.services.JTPXfersService')
    def test_get_xfers_balance(self, mock_jtpxfersservice_class):
        mock_jtpxfersservice_class.return_value.get_balance.side_effect = Exception('test')
        result = get_xfers_balance('jtp', 123)
        assert result is None

    @mock.patch('juloserver.disbursement.services.get_service')
    def test_get_julo_balance(self, mock_get_service):
        mock_get_service.return_value.get_balance.side_effect = Exception('test')
        result = get_julo_balance('xfers')
        assert result is None

    def test_trigger_name_in_bank_validation_bank_name_not_found(self):
        data_to_validate = {}
        data_to_validate['bank_name'] = 'test'
        data_to_validate['account_number'] = 'test'
        data_to_validate['name_in_bank'] = 'test'
        data_to_validate['name_bank_validation_id'] = 'test'
        data_to_validate['mobile_phone'] = 'test'
        data_to_validate['application'] = 'test'
        with self.assertRaises(BankNameNotFound):
            trigger_name_in_bank_validation(data_to_validate)

    @mock.patch('juloserver.disbursement.services.get_validation_method')
    def test_trigger_name_in_bank_validation_bank_validation_none(self, mock_get_validation_method):
        BankNameValidationLog.objects.create(
            application_id=self.application.id,
            account_number='test1',
            method='Xfers')
        mock_get_validation_method.return_value = 'Xfers'
        data_to_validate = {}
        data_to_validate['bank_name'] = 'BANK EXIMBANK'
        data_to_validate['account_number'] = 'test'
        data_to_validate['name_in_bank'] = 'test'
        data_to_validate['name_bank_validation_id'] = None
        data_to_validate['mobile_phone'] = 'test'
        data_to_validate['application'] = self.application
        result = trigger_name_in_bank_validation(data_to_validate, new_log=True)
        assert isinstance(result, ValidationProcess)

    @mock.patch('juloserver.disbursement.services.get_validation_method')
    def test_trigger_name_in_bank_validation(self, mock_get_validation_method):
        NameBankValidationHistory.objects.create(
            name_bank_validation_id=self.bank_validation.id,
            event='create',
            field_changes={
                'name_in_bank': 'test1',
                'account_number': 'test1',
                'method': 'Xfers',
            })
        mock_get_validation_method.return_value = 'Xfers'
        data_to_validate = {}
        data_to_validate['bank_name'] = 'BANK EXIMBANK'
        data_to_validate['account_number'] = 'test1'
        data_to_validate['name_in_bank'] = 'test1'
        data_to_validate['name_bank_validation_id'] = self.bank_validation.id
        data_to_validate['mobile_phone'] = 'test1'
        data_to_validate['application'] = self.application
        result = trigger_name_in_bank_validation(data_to_validate, new_log=True)
        assert isinstance(result, ValidationProcess)

    def test_get_ecommerce_disbursement_experiment_method(self):
        self.assertEqual(
            DisbursementVendors.XFERS, get_ecommerce_disbursement_experiment_method(self.loan)
        )

        parameters={
            DisbursementVendors.XFERS: {
                "status": DisbursementVendorStatus.ACTIVE,
                "loan_id": "#nth:-1:1,3,5,7,9"
            },
            DisbursementVendors.XENDIT: {
                "status": DisbursementVendorStatus.ACTIVE,
                "loan_id": "#nth:-1:0,2,4,6,8"
            }
        }
        feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.ECOMMERCE_EXPERIMENT,
            parameters=parameters,
        )
        loan = LoanFactory(
            id=7118,
            transaction_method_id=TransactionMethodCode.E_COMMERCE.code,
            loan_purpose="",
        )
        self.assertEqual(
            DisbursementVendors.XENDIT, get_ecommerce_disbursement_experiment_method(loan)
        )

        parameters[DisbursementVendors.XENDIT]['status'] = DisbursementVendorStatus.INACTIVE
        feature_setting.parameters = parameters
        feature_setting.save()
        self.assertEqual(
            DisbursementVendors.XFERS, get_ecommerce_disbursement_experiment_method(loan)
        )

    def test_is_xendit_use_step_one_disbursement(self):
        feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.XENDIT_STEP_ONE_DISBURSEMENT
        )
        self.assertEqual(True, is_xendit_use_step_one_disbursement())
        feature_setting.is_active = False
        feature_setting.save()
        self.assertEqual(False, is_xendit_use_step_one_disbursement())

    def test_check_xendit_whitelist(self):
        parameters_xw =  {'application_id': [2000010239]}
        feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.XENDIT_WHITELIST,
            parameters=parameters_xw,
            is_active=True,
        )
        application = ApplicationFactory(id=2000010239)
        self.assertEqual(
            True, check_xendit_whitelist(application, feature_setting)
        )
        application = ApplicationFactory(id=2000010232)
        self.assertEqual(
            False, check_xendit_whitelist(application, feature_setting)
        )

    def test_get_experiment_disbursement_method(self):
        fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.DISBURSEMENT_METHOD,
            parameters={
                "list_transaction_method_code_apply_ratio": [1, 2, 13],
                "disbursement_vendor": {
                    DisbursementVendors.XFERS: {
                        "whitelist": {
                            "is_active": False,
                            "list_application_id": [],
                        },
                        "is_active": False,
                        "list_last_digit_of_loan_id": [2, 4, 6, 8],
                    },
                    DisbursementVendors.AYOCONNECT: {
                        "whitelist": {
                            "is_active": False,
                            "list_application_id": [],
                        },
                        "is_active": False,
                        "list_last_digit_of_loan_id": [1, 3, 5, 7, 9],
                    },
                },
            },
            is_active=False,
        )

        # inactive feature setting
        method = get_experiment_disbursement_method(
            loan=Loan(
                id=1,
                transaction_method_id=1,
                application=Application(id=1),
            )
        )
        self.assertIsNone(method)

        # active feature setting
        fs.is_active = True
        fs.save()

        method = get_experiment_disbursement_method(
            loan=Loan(
                id=1,
                transaction_method_id=10,  # transaction method is not apply ratio
                application=Application(id=1),
            )
        )
        self.assertIsNone(method)

        # no active vendor
        fs.parameters['disbursement_vendor'][DisbursementVendors.XFERS]['is_active'] = False
        fs.parameters['disbursement_vendor'][DisbursementVendors.AYOCONNECT]['is_active'] = False
        fs.save()
        with self.assertRaises(DisbursementServiceError) as e:
            get_experiment_disbursement_method(
                loan=Loan(
                    id=1,
                    transaction_method_id=1,
                    application=Application(id=1),
                )
            )
        self.assertEqual(str(e.exception), 'No active vendors')

        # no active vendor, but active whitelist
        fs.parameters['disbursement_vendor'][DisbursementVendors.AYOCONNECT]['whitelist'] = {
            'is_active': True,
            'list_application_id': [123, 456],
        }
        fs.save()
        with self.assertRaises(DisbursementServiceError) as e:
            get_experiment_disbursement_method(
                loan=Loan(
                    id=1,
                    transaction_method_id=1,
                    application=Application(id=10),  # not exist in whitelist
                )
            )
        self.assertEqual(str(e.exception), 'No active vendors')

        method = get_experiment_disbursement_method(
            loan=Loan(
                id=1,
                transaction_method_id=1,
                application=Application(id=123),  # exist in whitelist
            )
        )
        self.assertEqual(method, DisbursementVendors.AYOCONNECT)

        # disable whitelist
        fs.parameters['disbursement_vendor'][DisbursementVendors.AYOCONNECT][
            'whitelist'
        ]['is_active'] = False
        fs.save()

        # only one vendor active
        fs.parameters['disbursement_vendor'][DisbursementVendors.XFERS]['is_active'] = True
        fs.save()
        method = get_experiment_disbursement_method(
            loan=Loan(
                id=10545,  # any
                transaction_method_id=1,  # exist in list apply ratio
                application=Application(id=1057414),  # any because whitelist is disabled
            )
        )
        self.assertEqual(method, DisbursementVendors.XFERS)

        # both vendor active
        fs.parameters['disbursement_vendor'][DisbursementVendors.AYOCONNECT]['is_active'] = True
        fs.save()
        method = get_experiment_disbursement_method(
            loan=Loan(
                id=1231246,  # last digit in list_last_digit_of_loan_id of Xfers
                transaction_method_id=1,  # exist in list apply ratio
                application=Application(id=1057414),  # any because whitelist is disabled
            )
        )
        self.assertEqual(method, DisbursementVendors.XFERS)
        method = get_experiment_disbursement_method(
            loan=Loan(
                id=1231245,  # last digit in list_last_digit_of_loan_id of Ayoconnect
                transaction_method_id=1,  # exist in list apply ratio
                application=Application(id=1057414),  # any because whitelist is disabled
            )
        )
        self.assertEqual(method, DisbursementVendors.AYOCONNECT)

        with self.assertRaises(DisbursementServiceError) as e:
            get_experiment_disbursement_method(
                loan=Loan(
                    id=1231240,  # last digit in not exist
                    transaction_method_id=1,  # exist in list apply ratio
                    application=Application(id=1057414),  # any because whitelist is disabled
                )
            )
        self.assertEqual(str(e.exception), 'Last digit of loan id not match with any vendor')

    def test_update_reason_for_multiple_disbursement(self):
        expected_reason = 'test'
        update_reason_for_multiple_disbursement(loan_ids=[self.loan.id], reason=expected_reason)
        self.disbursement.refresh_from_db()
        self.assertEqual(self.disbursement.reason, expected_reason)

    def test_get_disbursement_method_PG(self):
        PaymentGatewayVendor.objects.create(name="ayoconnect")
        user_auth = AuthUserFactory()
        customer = CustomerFactory(user=user_auth)
        application = ApplicationFactory(
            customer=customer, workflow=WorkflowFactory(name=WorkflowConst.GRAB)
        )
        application.application_status_id = 150
        application.save()
        validation_id = 200
        bank = BankFactory(bank_code=BankCodes.BCA)
        bank_validation = NameBankValidationFactory(
            validation_id=validation_id,
            method=NameBankValidationVendors.PAYMENT_GATEWAY,
            account_number=123,
            name_in_bank='test',
            bank_code=bank.bank_code,
        )

        bank_account_destination = BankAccountDestinationFactory(
            bank=bank,
            name_bank_validation=bank_validation,
        )
        disbursement = DisbursementFactory(
            name_bank_validation=bank_validation,
            disburse_id=123456,
            method=DisbursementVendors.AYOCONNECT,
            disbursement_type='loan_one',
        )
        product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB, product_line_type='GRAB'
        )
        loan = LoanFactory(
            name_bank_validation_id=bank_validation.id,
            disbursement_id=disbursement.id,
            application=application,
            loan_xid=123456789,
            product=ProductLookupFactory(product_line=product_line),
        )
        application.name_bank_validation = bank_validation
        application.save()

        result = get_disbursement_method(bank_validation, application)
        assert result == DisbursementVendors.PG

    @mock.patch('juloserver.disbursement.services.get_validation_method')
    def test_grab_trigger_name_in_bank_validation_with_XFERS(self, mock_get_validation_method):
        self.workflow_grab = WorkflowFactory(name=WorkflowConst.GRAB)
        self.application.workflow = self.workflow_grab
        self.application.save()

        bank = BankFactory(bank_code=BankCodes.BCA)

        NameBankValidationHistory.objects.create(
            name_bank_validation_id=self.bank_validation.id,
            event='create',
            field_changes={
                'name_in_bank': 'test1',
                'account_number': 'test1',
                'method': 'XFERS',
            },
        )
        data_to_validate = {}
        data_to_validate['bank_name'] = bank.bank_name
        data_to_validate['account_number'] = 'test1'
        data_to_validate['name_in_bank'] = 'test1'
        data_to_validate['name_bank_validation_id'] = self.bank_validation.id
        data_to_validate['mobile_phone'] = 'test1'
        data_to_validate['application'] = self.application
        result = trigger_name_in_bank_validation(data_to_validate, new_log=True)
        assert isinstance(result, ValidationProcess)
        self.bank_validation.refresh_from_db()
        self.assertFalse(mock_get_validation_method.called)
        self.assertEqual(self.bank_validation.method, NameBankValidationVendors.XFERS)


class TestTriggerDisburse(TestCase):
    def setUp(self):
        self.bank_validation = NameBankValidationFactory()
        self.disbursement = DisbursementFactory(external_id=fake.numerify(text="#%#%"))
        self.application = ApplicationFactory(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB),
            workflow=WorkflowFactory(name=WorkflowConst.GRAB),
            name_bank_validation=self.disbursement.name_bank_validation
        )
        self.loan = LoanFactory(
            name_bank_validation_id=self.bank_validation.id,
            disbursement_id=self.disbursement.id,
            application=self.application,
            loan_xid=self.disbursement.external_id,
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_AYOCONNECT_XFERS_FAILOVER,
            is_active=True
        )

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

    def test_case_4_disbursement_method_pg_service(self):
        data_to_disburse = {}
        data_to_disburse['name_bank_validation_id'] = self.bank_validation.id
        self.bank_validation.validation_status = 'SUCCESS'
        self.bank_validation.save()
        self.disbursement.method = DisbursementVendors.AYOCONNECT
        self.disbursement.retry_times = 3
        self.disbursement.save(update_fields=['retry_times', 'method', 'udate'])

        data_to_disburse['disbursement_id'] = self.disbursement.id

        trigger_disburse(data_to_disburse)
        self.disbursement.refresh_from_db()

        assert self.disbursement.method == DisbursementVendors.PG

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


class TestAyoconnectDisbursementProcess(TestCase):
    def setUp(self):
        disbursement = DisbursementFactory(external_id=10)
        self.svc = AyoconnectDisbursementProcess(disbursement)

    def test_success_parse_reason_disburse_failed(self):
        response_disburse = {
            "reason": '''Failed create disbursement, {'status_code': 412, 'error': {'code': 412, 'message': 'bad.request', 'responseTime': '20211015060602', 'transactionId': '01234567890123456789012345678912', 'referenceNumber': '027624209e6945678652abe61c91f49c', 'errors': [{'code': '0325', 'message': 'error.bad.request', 'details': "The request can't be processed by the server"}]}}'''
        }
        reason = self.svc.parse_reason_disburse_failed(response_disburse)
        self.assertTrue(isinstance(reason, dict))

    def test_failed_parse_reason_disburse(self):
        test_cases = [
            {'data': {'reason': '{\'status_code\': 200}'}, 'expected': None},
            {'data': {}, 'expected': None},
            {'data': {"message": "hello world!"}, 'expected': None},
            {'data': {"reason": '''Failed disbursement, {'status_code': 412, 'error': {'code': 412, 'message': 'bad.request'}}}'''}, 'expected': None}
        ]
        for test_case in test_cases:
            self.assertEqual(
                self.svc.parse_reason_disburse_failed(test_case['data']),
                test_case['expected']
            )

    def test_true_is_can_be_ignored(self):
        reason = {
            'status_code': 412,
            'error': {
                'code': 412,
                'message': 'bad.request',
                'responseTime': '20211015060602',
                'transactionId': '01234567890123456789012345678912',
                'referenceNumber': '027624209e6945678652abe61c91f49c',
                'errors': [
                    {
                        'code': '0325',
                        'message': 'error.bad.request',
                        'details': "The request can't be processed by the server"
                    }
                ]
            }
        }
        self.assertTrue(self.svc.is_can_be_ignored(reason_disburse=reason))

    def test_false_is_can_be_ignored(self):
        test_cases = [
            {
                'reason': {
                    'status_code': 412,
                    'error': {
                        'code': 412,
                        'message': 'bad.request',
                        'responseTime': '20211015060602',
                        'transactionId': '01234567890123456789012345678912',
                        'referenceNumber': '027624209e6945678652abe61c91f49c',
                        'errors': [
                            {
                                'code': '0321',
                                'message': 'error.bad.request',
                                'details': "The request can't be processed by the server"
                            }
                        ]
                    }
                },
                'expected': False
            },
            {
                'reason': {
                    'status_code': 400,
                    'error': {
                        'code': 400,
                        'message': 'bad.request',
                        'responseTime': '20211015060602',
                        'transactionId': '01234567890123456789012345678912',
                        'referenceNumber': '027624209e6945678652abe61c91f49c',
                        'errors': [
                            {
                                'code': '0325',
                                'message': 'error.bad.request',
                                'details': "The request can't be processed by the server"
                            }
                        ]
                    }
                },
                'expected': False
            },
            {
                'reason': {},
                'expected': False
            },
            {
                'reason': 'haha',
                'expected': False
            }
        ]

        for test in test_cases:
            result = self.svc.is_can_be_ignored(test["reason"])
            self.assertEqual(result, test["expected"])


class TestDisbursementProcess(TestCase):
    def setUp(self):
        self.bank = BankFactory(bank_code='test_dbm_bank_code', xfers_bank_code='BMW_BANK')
        self.name_bank_validation = NameBankValidationFactory(
            method='PG', account_number=123, name_in_bank='test', bank_code='test_dbm_bank_code'
        )
        self.disbursement = DisbursementFactory(
            external_id=10,
            method='Xfers',
            name_bank_validation=self.name_bank_validation,
        )
        self.svc = DisbursementProcess(self.disbursement)

    def test_get_data(self):
        # disbursement method is PG
        result = self.svc.get_data()
        self.assertEqual(result['bank_info']['bank_code'], 'BMW_BANK')

        # disbursement method is Xfers
        self.name_bank_validation.method = 'Xfers'
        self.name_bank_validation.bank_code = 'BMW_BANK'
        self.name_bank_validation.save()
        result = self.svc.get_data()
        self.assertEqual(result['bank_info']['bank_code'], 'BMW_BANK')
