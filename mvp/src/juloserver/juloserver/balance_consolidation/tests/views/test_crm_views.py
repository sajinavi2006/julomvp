from unittest.mock import ANY

import pytest
import json

from django.utils import timezone
from django.test import TestCase
from django.contrib.auth.models import Group
from rest_framework.test import APIClient, APITestCase
from rest_framework.exceptions import ValidationError
from rest_framework.reverse import reverse

from mock import patch
from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory, \
    AccountPropertyFactory
from juloserver.balance_consolidation.models import BalanceConsolidationVerificationHistory
from juloserver.balance_consolidation.tests.factories import (
    BalanceConsolidationFactory,
    BalanceConsolidationVerificationFactory,
    FintechFactory,
)
from juloserver.cfs.tests.factories import AgentFactory, ImageFactory
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory,
)
from juloserver.graduation.models import GraduationCustomerHistory2
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.julo.tests.factories import (
    CustomerFactory,
    AuthUserFactory,
    GroupFactory,
    DocumentFactory,
    ApplicationFactory,
    FeatureSettingFactory,
    BankFactory,
    StatusLookupFactory,
    WorkflowFactory,
    ProductLineFactory,
    LoanFactory, ProductLookupFactory, CreditMatrixFactory, CurrentCreditMatrixFactory,
    CreditMatrixProductLineFactory,
)
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.moengage.services.use_cases import \
    send_user_attributes_to_moengage_for_balance_consolidation_verification
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.sales_ops.constants import SalesOpsRoles
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.balance_consolidation.constants import (
    BalanceConsolidationStatus,
    MessageBankNameValidation,
    BalconLimitIncentiveConst,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.balance_consolidation.services import ConsolidationVerificationStatusService


class TestBalanceConsolidationListView(TestCase):
    def setUp(self):
        self.user = AuthUserFactory(is_superuser=True, is_staff=True)
        self.client.force_login(self.user)
        self.agent = AgentFactory(user=self.user)
        self.customer = CustomerFactory()
        self.balance_consolidation = BalanceConsolidationFactory(customer=self.customer)
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation
        )

    def test_get_success_valid_user(self):
        group = GroupFactory(name=JuloUserRoles.BO_DATA_VERIFIER)
        self.user.groups.add(group)

        url = reverse('balance_consolidation_crm:balance_consolidation_verification_list')
        response = self.client.get(url)

        self.assertEquals(response.status_code, 200)

    def test_get_failed_invalid_user(self):
        url = reverse('balance_consolidation_crm:balance_consolidation_verification_list')
        user = AuthUserFactory()
        group = GroupFactory(name=JuloUserRoles.BO_FULL)
        user.groups.add(group)
        self.client.force_login(user)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)


class TestBalanceConsolidationLockStatus(TestCase):
    def setUp(self):
        self.user = AuthUserFactory(is_superuser=True, is_staff=True)
        self.agent = AgentFactory(user=self.user)
        self.client.force_login(self.user)
        self.customer = CustomerFactory()
        self.fintech = FintechFactory()
        self.document = DocumentFactory()
        self.balance_consolidation = BalanceConsolidationFactory(
            customer=self.customer, fintech=self.fintech, loan_agreement_document=self.document
        )
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation
        )
        self.data = {'balance_consolidation_id': self.balance_consolidation.id, 'lock_check': True}
        self.group = GroupFactory(name=JuloUserRoles.BO_DATA_VERIFIER)
        self.user.groups.add(self.group)

    @pytest.mark.skip(reason="Upcoming Feature")
    def test_post_missing_data(self):
        url = reverse('balance_consolidation_crm:lock-status')
        with self.assertRaises(ValidationError):
            self.client.post(url)

    @pytest.mark.skip(reason="Upcoming Feature")
    def test_post_lock_success(self):
        url = reverse('balance_consolidation_crm:lock-status')
        response = self.client.post(url, data=self.data)
        self.assertEquals(response.status_code, 200)
        self.assertEquals(response.json().get('message'), 'Record locked successfully')

    @pytest.mark.skip(reason="Upcoming Feature")
    def test_post_unlock_success(self):
        self.data['lock_check'] = False
        self.balance_consolidation_verification.update_safely(locked_by=self.agent)

        url = reverse('balance_consolidation_crm:lock-status')
        response = self.client.post(url, data=self.data)
        self.assertEquals(response.status_code, 200)
        self.assertEquals(response.json().get('message'), 'Record unlocked successfully')

    @pytest.mark.skip(reason="Upcoming Feature")
    def test_post_already_lock_failed(self):
        self.balance_consolidation_verification.update_safely(locked_by=AgentFactory())
        url = reverse('balance_consolidation_crm:lock-status')
        response = self.client.post(url, data=self.data)
        self.assertEquals(response.status_code, 403)
        self.assertEquals(response.json().get('message'), 'Record is already being locked')

    @pytest.mark.skip(reason="Upcoming Feature")
    def test_request_method_invalid(self):
        url = reverse('balance_consolidation_crm:lock-status')
        response = self.client.get(url)

    @pytest.mark.skip(reason="Upcoming Feature")
    def test_post_invalid_user(self):
        url = reverse('balance_consolidation_crm:lock-status')

        user = AuthUserFactory()
        group = GroupFactory(name=SalesOpsRoles.SALES_OPS)
        user.groups.add(group)
        self.client.force_login(user)

        response = self.client.post(url, data=self.data)
        self.assertEqual(response.status_code, 302)


class TestBalanceConsolidationValidateNameBank(TestCase):
    def setUp(self):
        self.user = AuthUserFactory(is_superuser=True, is_staff=True)
        self.agent = AgentFactory(user=self.user)
        self.client.force_login(self.user)
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.fintech = FintechFactory()
        self.document = DocumentFactory()
        self.balance_consolidation = BalanceConsolidationFactory(
            customer=self.customer, fintech=self.fintech, loan_agreement_document=self.document
        )
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation
        )
        self.name_bank_validation = NameBankValidationFactory(method="Xfers")
        self.balance_consolidation_verification.name_bank_validation = self.name_bank_validation
        self.balance_consolidation_verification.save()
        self.group = GroupFactory(name=JuloUserRoles.BO_DATA_VERIFIER)
        self.user.groups.add(self.group)

    def test_refresh_name_bank_validation(self):
        url = reverse('balance_consolidation_crm:ajax_bank_validation')
        url_1 = url + '?consolidation_verification_id={}'.format(
            self.balance_consolidation_verification.id
        )
        response = self.client.get(url_1)
        assert response.status_code == 200

        url_2 = url + '?consolidation_verification_id=1000'
        response = self.client.get(url_2)
        assert response.status_code == 404
        assert (
            response.json()['messages'] == MessageBankNameValidation.BALANCE_CONSOLIDATION_NOT_FOUND
        )

        self.balance_consolidation_verification.name_bank_validation = None
        self.balance_consolidation_verification.save()
        response = self.client.get(url_1)
        assert response.status_code == 404
        assert (
            response.json()['messages']
            == MessageBankNameValidation.Name_BANK_NOT_FOUND_AND_VERIFY_FIRST
        )

    @patch('juloserver.disbursement.services.get_service')
    def test_validate_name_bank_validation_failed(self, _mock_get_service):
        url = reverse('balance_consolidation_crm:ajax_bank_validation')
        data = {
            "consolidation_verification_id": self.balance_consolidation_verification.pk,
            "bank_name": "BANK SYARIAH MANDIRI",
            "account_number": "0832132132142",
            "name_in_bank": "Prod only",
            "validation_method": "Xfers",
        }
        mock_response = {
            'id': None,
            'status': 'NAME_INVALID',
            'validated_name': None,
            'reason': 'Failed to add bank account',
            'error_message': "Failed to add bank account;",
            'account_no': None,
            'bank_abbrev': None,
        }
        _mock_get_service.return_value.validate.return_value = mock_response
        response = self.client.post(url, data=data)
        assert response.status_code == 200
        self.balance_consolidation_verification.refresh_from_db()
        assert (
            self.balance_consolidation_verification.name_bank_validation.validation_status
            == 'NAME_INVALID'
        )

    @patch('juloserver.disbursement.services.get_service')
    def test_validate_name_bank_validation_success(self, _mock_get_service):
        url = reverse('balance_consolidation_crm:ajax_bank_validation')
        data = {
            "consolidation_verification_id": self.balance_consolidation_verification.pk,
            "bank_name": "BANK SYARIAH MANDIRI",
            "account_number": "0832132132142",
            "name_in_bank": "Prod only",
            "validation_method": "Xfers",
        }
        mock_response = {
            "id": 158893,
            "status": "SUCCESS",
            "validated_name": "PROD ONLY",
            "reason": "success",
            "error_message": "None",
            "account_no": "0832132132",
            "bank_abbrev": "MANDIRI_SYR",
        }
        _mock_get_service.return_value.validate.return_value = mock_response
        response = self.client.post(url, data=data)
        assert response.status_code == 200
        self.balance_consolidation_verification.refresh_from_db()
        assert (
            self.balance_consolidation_verification.name_bank_validation.validation_status
            == 'SUCCESS'
        )

    def test_get_invalid_user(self):
        url = reverse('balance_consolidation_crm:ajax_bank_validation')

        user = AuthUserFactory()
        group = GroupFactory(name=SalesOpsRoles.SALES_OPS)
        user.groups.add(group)
        self.client.force_login(user)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)


class TestUpdateBalanceConsolidationVerification(APITestCase):
    def setUp(self):
        self.client = APIClient()

        group = Group(name="bo_data_verifier")
        group.save()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.active_status_code = StatusLookupFactory(
            status_code=AccountConstant.STATUS_CODE.active
        )
        self.active_in_grace = StatusLookupFactory(
            status_code=AccountConstant.STATUS_CODE.active_in_grace
        )
        self.loan_status_code_active = StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)
        self.loan_status_code_failed = StatusLookupFactory(
            status_code=LoanStatusCodes.TRANSACTION_FAILED
        )
        self.loan_status_code_inactive = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        self.account = AccountFactory(customer=self.customer, status=self.active_status_code)
        self.account_property = AccountPropertyFactory(account=self.account, is_entry_level=True)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        agent = AgentFactory(user=self.user)
        self.user.groups.add(group)
        self.client.force_login(self.user)
        self.bank = BankFactory(bank_name='BCA')
        self.bank_account_category = BankAccountCategoryFactory(
            category='balance_consolidation', display_label='balance_consolidation'
        )
        self.image = ImageFactory(image_source=0)
        self.balance_consolidation = BalanceConsolidationFactory(
            customer=self.customer, loan_duration=3, signature_image=self.image
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status=NameBankValidationStatus.SUCCESS,
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank=self.bank,
            customer=self.customer,
            bank_account_category=self.bank_account_category,
            name_bank_validation=self.name_bank_validation,
        )
        self.user.save()
        self.account_limit = AccountLimitFactory(
            account=self.account,
            set_limit=1000000,
            available_limit=1000000
        )
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation
        )
        self.balance_consolidation_verification.name_bank_validation = self.name_bank_validation
        self.balance_consolidation_verification.locked_by = agent
        self.balance_consolidation_verification.save()
        ProductLookupFactory(product_line=self.product_line, late_fee_pct=0.05),
        self.product_lookup = ProductLookupFactory()
        TransactionMethodFactory(
            id=TransactionMethodCode.BALANCE_CONSOLIDATION.code,
            method=TransactionMethodCode.BALANCE_CONSOLIDATION.name,
        )
        self.credit_matrix = CreditMatrixFactory(
            credit_matrix_type='julo1_entry_level',
            is_salaried=True,
            is_premium_area=True,
            min_threshold=0.75,
            max_threshold=1,
            transaction_type='balance_consolidation',
            parameter=None,
            product=self.product_lookup
        )
        self.curent_credit_matrix = CurrentCreditMatrixFactory(
            credit_matrix=self.credit_matrix,
            transaction_type='balance_consolidation',
        )
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix, max_loan_amount=10000000, product=self.product_line
        )
        self.url = reverse(
            'balance_consolidation_crm:balance_consolidation_verification_update',
            kwargs={'verification_id': self.balance_consolidation_verification.id},
        )
        FeatureSettingFactory(
            feature_name=BalconLimitIncentiveConst.LIMIT_INCENTIVE_FS_NAME,
            category='balance_consolidation',
            is_active=True,
            parameters={
                'max_limit_incentive': 5_500_000,
                'min_set_limit': 1_000_000,
                'multiplier': 0.5,
                'bonus_incentive': 500_000,
            }
        )

    @patch('juloserver.balance_consolidation.services.is_product_locked_for_balance_consolidation')
    def test_update_success(self, mock_is_product_locked):
        req_data = {'status': BalanceConsolidationStatus.APPROVED, 'note': 'new note'}
        mock_is_product_locked.return_value = False

        resp = self.client.put(self.url, data=json.dumps(req_data), content_type="application/json")
        self.assertEqual(resp.status_code, 200)

        self.balance_consolidation_verification.refresh_from_db()
        self.assertEqual(
            self.balance_consolidation_verification.validation_status, req_data['status']
        )
        self.assertEqual(self.balance_consolidation_verification.note, req_data['note'])

        consolidation_services = ConsolidationVerificationStatusService(
            self.balance_consolidation_verification, self.account
        )
        consolidation_services.update_post_graduation()

        account_limit_histories = self.balance_consolidation_verification.account_limit_histories
        account_limit_histories_dict = account_limit_histories['upgrade']
        graduation = GraduationCustomerHistory2.objects.get(account_id=self.account.id)
        assert graduation.available_limit_history_id == \
               account_limit_histories_dict['available_limit']
        assert graduation.max_limit_history_id == account_limit_histories_dict['max_limit']
        assert graduation.set_limit_history_id == account_limit_histories_dict['set_limit']

    def test_update_non_exist_status(self):
        req_data = {'status': 'non_exist_status', 'note': 'new note'}

        resp = self.client.put(self.url, data=json.dumps(req_data), content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_not_found_verification(self):
        req_data = {'status': BalanceConsolidationStatus.APPROVED, 'note': 'new note'}
        url = reverse(
            'balance_consolidation_crm:balance_consolidation_verification_update',
            kwargs={'verification_id': 0},
        )

        resp = self.client.put(url, data=json.dumps(req_data), content_type="application/json")
        self.assertEqual(resp.status_code, 404)

    def test_update_lock_from_another_agent(self):
        self.balance_consolidation_verification.locked_by = AgentFactory()
        self.balance_consolidation_verification.save()

        req_data = {'status': BalanceConsolidationStatus.APPROVED, 'note': 'new note'}

        resp = self.client.put(self.url, data=json.dumps(req_data), content_type="application/json")
        self.assertEqual(resp.status_code, 401)

    def test_consolidation_verification_service(self):
        verification = self.balance_consolidation_verification
        verification.validation_status = BalanceConsolidationStatus.APPROVED
        verification.save()
        service = ConsolidationVerificationStatusService(
            verification, verification.balance_consolidation.customer.account
        )

        verification.refresh_from_db()
        self.account.refresh_from_db()
        service.update_status_abandoned()
        assert verification.validation_status == BalanceConsolidationStatus.ABANDONED

    @patch('juloserver.balance_consolidation.services.calculate_loan_amount')
    def test_update_success_cancelled_status(self, _mock_calculate_loan_amount):
        req_data = {'status': BalanceConsolidationStatus.CANCELLED, 'note': 'new note'}
        loan_amount = 100000
        _mock_calculate_loan_amount.return_value = loan_amount, None, None

        resp = self.client.put(self.url, data=json.dumps(req_data), content_type="application/json")
        self.assertEqual(resp.status_code, 200)

        self.balance_consolidation_verification.refresh_from_db()
        self.assertEqual(
            self.balance_consolidation_verification.validation_status, req_data['status']
        )
        self.assertEqual(self.balance_consolidation_verification.note, req_data['note'])

    @patch('juloserver.balance_consolidation.services.execute_after_transaction_safely')
    @patch('juloserver.balance_consolidation.signals.execute_after_transaction_safely')
    @patch('juloserver.balance_consolidation.services.is_product_locked_for_balance_consolidation')
    def test_send_event_moengage(
        self,
        mock_is_product_locked,
        mock_send_user_attrib,
        _execute_after_transaction_safely,
    ):
        mock_is_product_locked.return_value = False
        req_data = {'status': BalanceConsolidationStatus.APPROVED, 'note': 'new note'}

        self.client.put(self.url, data=json.dumps(req_data), content_type="application/json")
        mock_send_user_attrib.assert_called_once()
        assert _execute_after_transaction_safely.call_count == 3

    @patch('juloserver.balance_consolidation.signals.execute_after_transaction_safely')
    def test_not_send_event_moengage(self, mock_send_user_attrib):
        req_data = {'status': BalanceConsolidationStatus.ON_REVIEW, 'note': 'new note'}

        self.client.put(self.url, data=json.dumps(req_data), content_type="application/json")
        mock_send_user_attrib.assert_not_called()

    @patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_sent_moengage_balance_consolidation_verification(self, mock_send_to_moengage):
        self.balance_consolidation = BalanceConsolidationFactory(customer=self.customer)
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation,
            validation_status=BalanceConsolidationStatus.DRAFT
        )
        send_user_attributes_to_moengage_for_balance_consolidation_verification(
            self.customer.id, self.balance_consolidation_verification.id
        )
        expected_event_attribute = {
            "type": "event",
            "customer_id": self.customer.id,
            "device_id": ANY,
            "actions": [
                {
                    "action": "balance_consolidation",
                    "attributes": {
                        'balance_cons_validation_status': BalanceConsolidationStatus.DRAFT,
                        'change_reason': '',
                        'balance_cons_agent_id': None,
                    },
                    "platform": "ANDROID",
                    "current_time": ANY,
                    "user_timezone_offset": ANY,
                }
            ],
        }
        expected_user_attributes = {
            'type': 'customer',
            'customer_id': self.customer.id,
            'attributes':
                {
                    'customer_id': self.customer.id,
                    'platforms': [{
                        'platform': 'ANDROID',
                        'active': 'true'
                    }]
                }
        }
        mock_send_to_moengage.assert_called_once_with(
            [ANY],
            [
                expected_user_attributes,
                expected_event_attribute,
            ]
        )

    @patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_sent_moengage_balance_consolidation_verification_with_change_reason(
        self, mock_send_to_moengage
    ):
        self.balance_consolidation = BalanceConsolidationFactory(customer=self.customer)
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation,
            validation_status=BalanceConsolidationStatus.APPROVED,
        )
        self.balance_consolidation_verification_history = (
            BalanceConsolidationVerificationHistory.objects.create(
                balance_consolidation_verification=self.balance_consolidation_verification,
                field_name='validation_status',
                value_old=BalanceConsolidationStatus.ON_REVIEW,
                value_new=BalanceConsolidationStatus.APPROVED,
                change_reason='Pass checking',
            )
        )
        event_time = timezone.localtime(self.balance_consolidation_verification.udate)
        send_user_attributes_to_moengage_for_balance_consolidation_verification(
            self.customer.id, self.balance_consolidation_verification.id
        )
        expected_event_attribute = {
            "type": "event",
            "customer_id": self.customer.id,
            "device_id": self.application.device.gcm_reg_id,
            "actions": [
                {
                    "action": "balance_consolidation",
                    "attributes": {
                        'balance_cons_validation_status': BalanceConsolidationStatus.APPROVED,
                        'change_reason': 'Pass checking',
                        'balance_cons_agent_id': None,
                    },
                    "platform": "ANDROID",
                    "current_time": event_time.timestamp(),
                    "user_timezone_offset": event_time.utcoffset().seconds,
                }
            ],
        }
        expected_user_attributes = {
            'type': 'customer',
            'customer_id': self.customer.id,
            'attributes': {
                'customer_id': self.customer.id,
                'platforms': [{'platform': 'ANDROID', 'active': 'true'}],
            },
        }
        mock_send_to_moengage.assert_called_once_with(
            [ANY],
            [
                expected_user_attributes,
                expected_event_attribute,
            ],
        )

    @patch('juloserver.moengage.services.use_cases.send_to_moengage.delay')
    def test_sent_moengage_balance_consolidation_verification_without_change_reason(
        self, mock_send_to_moengage
    ):
        self.balance_consolidation = BalanceConsolidationFactory(customer=self.customer)
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation,
            validation_status=BalanceConsolidationStatus.ON_REVIEW,
        )
        self.balance_consolidation_verification_history = (
            BalanceConsolidationVerificationHistory.objects.create(
                balance_consolidation_verification=self.balance_consolidation_verification,
                field_name='validation_status',
                value_old=BalanceConsolidationStatus.DRAFT,
                value_new=BalanceConsolidationStatus.ON_REVIEW,
            )
        )
        event_time = timezone.localtime(self.balance_consolidation_verification.udate)
        send_user_attributes_to_moengage_for_balance_consolidation_verification(
            self.customer.id, self.balance_consolidation_verification.id
        )
        expected_event_attribute = {
            "type": "event",
            "customer_id": self.customer.id,
            "device_id": self.application.device.gcm_reg_id,
            "actions": [
                {
                    "action": "balance_consolidation",
                    "attributes": {
                        'balance_cons_validation_status': BalanceConsolidationStatus.ON_REVIEW,
                        'change_reason': '',
                        'balance_cons_agent_id': None,
                    },
                    "platform": "ANDROID",
                    "current_time": event_time.timestamp(),
                    "user_timezone_offset": event_time.utcoffset().seconds,
                }
            ],
        }
        expected_user_attributes = {
            'type': 'customer',
            'customer_id': self.customer.id,
            'attributes': {
                'customer_id': self.customer.id,
                'platforms': [{'platform': 'ANDROID', 'active': 'true'}],
            },
        }
        mock_send_to_moengage.assert_called_once_with(
            [ANY],
            [
                expected_user_attributes,
                expected_event_attribute,
            ],
        )
