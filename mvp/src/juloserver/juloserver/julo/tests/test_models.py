from __future__ import absolute_import

import time
from builtins import object
from unittest.mock import (
    patch,
    MagicMock,
)

from django.db import IntegrityError
import mock
import pytest

from datetime import timedelta
from django.test import TestCase

from juloserver.julo.models import (
    StatusLookup,
    BankVirtualAccount,
    Payment,
    Loan,
    Application,
    Customer,
)
from juloserver.julo.models import Device, PaymentMethod
from juloserver.julo.statuses import LoanStatusCodes
from .factories import (
    CustomerFactory,
    AuthUserFactory,
    PartnerFactory,
)
from .factories import DeviceFactory
from .factories import LoanFactory
from .factories import OtpRequestFactory
from .factories import ApplicationFactory
from juloserver.account.tests.factories import AccountFactory
from .factories import BankFactory
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory
)
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.personal_data_verification.tests.factories import DukcapilResponseFactory
from ...application_flow.factories import ApplicationRiskyCheckFactory


@pytest.mark.django_db
class TestGetInstanceMixin(object):

    def test_get_or_none(self):

        # GIVEN a customer's device (let's say one device per customer)
        device = DeviceFactory()

        # WHEN calling the method by passing in customer
        queried_device = Device.objects.get_or_none(customer=device.customer)

        # THEN the return object is the customer object
        assert queried_device.imei == device.imei

        # WHEN calling the method by passing in some invalid customer
        queried_device = Device.objects.get_or_none(customer=8888888888)

        # THEN the return object is None
        assert queried_device is None


@pytest.mark.django_db
class TestLoanModel(object):

    def test_is_active(self):

        loan = LoanFactory()

        loan.loan_status = StatusLookup.objects.get(status_code=LoanStatusCodes.INACTIVE)
        loan.save()
        assert not loan.is_active

        loan.loan_status = StatusLookup.objects.get(status_code=LoanStatusCodes.PAID_OFF)
        loan.save()
        assert not loan.is_active

    def test_get_application(self):
        loan = LoanFactory()

        application = loan.get_application
        assert not application.account
        account = AccountFactory()
        loan.account = account
        loan.save()
        loan.refresh_from_db()
        application.account = account
        application.save()
        application.refresh_from_db()
        application = loan.get_application
        assert application.account

    def test_exclude_loan_julo_one(self):
        account = AccountFactory()
        loan = LoanFactory(account=account)
        loans = Loan.objects.all().exclude_julo_one()
        assert not loans

    def test_get_fund_id(self):
        loan = LoanFactory(disbursement_id=1)
        assert loan.fund_id == 1

    def test_is_cash_transaction(self):
        loan = LoanFactory(transaction_method_id=1)
        assert loan.is_cash_transaction

    def test_get_transaction_detail(self):
        customer = CustomerFactory()
        bank = BankFactory(
            bank_code='012',
            bank_name='BCA',
            xendit_bank_code='BCA',
            swift_bank_code='01',
            bank_name_frontend='BCA'
        )
        bank_account_category = BankAccountCategoryFactory(
            category='self',
            display_label='Pribadi',
            parent_category_id=1
        )
        name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=customer,
            bank=bank,
            name_bank_validation=name_bank_validation,
            account_number='12345',
            is_deleted=False
        )
        account = AccountFactory()
        ApplicationFactory(account=account)
        loan = LoanFactory(transaction_method_id=1,
                           bank_account_destination=bank_account_destination,
                           account=account)
        assert loan.transaction_detail == 'BCA, 12345'


@pytest.mark.django_db
class TestOtpRequestModel(object):

    def test_is_active(self):

        otp_request = OtpRequestFactory()
        assert otp_request.is_active

        otp_request = OtpRequestFactory()
        fake_cdate = otp_request.cdate - timedelta(minutes=15)
        otp_request.cdate = fake_cdate
        otp_request.save()
        assert not otp_request.is_active


class TestApplicationModel(TestCase):
    def test_device_scraped_data(self):
        application = ApplicationFactory()

        result = application.device_scraped_data
        self.assertIsNotNone(result)

    def test_crm_revamp_url_no_setting(self):
        application = ApplicationFactory()

        with self.settings(CRM_REVAMP_BASE_URL=None):
            ret_val = application.crm_revamp_url

        self.assertIsNone(ret_val)

    def test_crm_revamp_url_with_setting(self):
        application = ApplicationFactory()

        with self.settings(CRM_REVAMP_BASE_URL='https://localhost:8989/'):
            ret_val = application.crm_revamp_url

        self.assertEquals(
            'https://localhost:8989/app_status/change_status/' + str(application.id) + '/',
            ret_val
        )

    def test_dukcapil_eligible_no_dukcapil_response(self):
        application = ApplicationFactory()

        self.assertTrue(application.dukcapil_eligible())

    def test_dukcapil_eligible_with_invalid_dukcapil_response(self):
        application = ApplicationFactory()
        DukcapilResponseFactory(
            application=application,
            name=False,
            birthdate=False,
            birthplace=False,
            address_street=False,
            gender=False,
        )
        self.assertFalse(application.dukcapil_eligible())

    def test_has_suspicious_application_in_device_response(self):
        application = ApplicationFactory()
        ApplicationRiskyCheckFactory(application=application, is_sus_app_detected=True)

        self.assertTrue(application.has_suspicious_application_in_device)


@pytest.mark.django_db
class TestPaymentMethodModel(object):

    def test_payment_method_new_name(self):
        loan = LoanFactory()
        BankVirtualAccount.objects.create(
            loan=loan, bank_code_id='014', virtual_account_number=1234567)
        BankVirtualAccount.objects.create(
            loan=loan, bank_code_id='022', virtual_account_number=1234567)
        application_014 = PaymentMethod(
            bank_code='014', payment_method_name='test', loan=loan, virtual_account=1234567)
        application_022 = PaymentMethod(
            bank_code='022', payment_method_name='test', loan=loan, virtual_account=1234567)
        application_024 = PaymentMethod(bank_code='024', payment_method_name='test', loan=loan)

        assert application_014.payment_method_new_name == 'Bank BCA Offline'
        assert application_022.payment_method_new_name == 'Bank CIMB Offline'
        assert application_024.payment_method_new_name == 'test'

    def test_fullname_with_title(self):
        application = ApplicationFactory()

        application.fullname = 'Test NAME'
        application.gender = 'Wanita'
        result = application.fullname_with_title
        assert result == 'Ibu Test Name'
        application.gender = 'Pria'
        result = application.fullname_with_title
        assert result == 'Bapak Test Name'

    def test_first_name_with_title(self):
        application = ApplicationFactory()

        application.fullname = 'TESt NAME'
        application.gender = 'Wanita'
        result = application.first_name_with_title
        assert result == 'Ibu Test'
        application.gender = 'Pria'
        result = application.first_name_with_title
        assert result == 'Bapak Test'

    def test_first_name_with_title_short(self):
        application = ApplicationFactory()

        application.fullname = 'TESt NAME'
        application.gender = 'Wanita'
        result = application.first_name_with_title_short
        assert result == 'Ibu Test'
        application.gender = 'Pria'
        result = application.first_name_with_title_short
        assert result == 'Bpk Test'

    def test_first_name_only(self):
        application = ApplicationFactory()

        application.fullname = 'TESt NAME'
        result = application.first_name_only
        assert result == 'Test'

    def test_full_name_only(self):
        application = ApplicationFactory()

        application.fullname = 'TESt NAME'
        result = application.full_name_only
        assert result == 'Test Name'


@pytest.mark.django_db
class TestUpdateUdateField(object):
    def test_update_new_udate(self):
        device = DeviceFactory()
        udate = device.udate
        time.sleep(0.1)
        Device.objects.filter(id=device.id).update(device_model_name='test')
        queried_device = Device.objects.get_or_none(id=device.id)
        assert queried_device.udate > udate

    def test_update_new_udate_if_has_custom_queryset(self):
        application = ApplicationFactory()
        udate = application.udate
        time.sleep(0.1)
        Application.objects.filter(id=application.id).update(fullname='test')
        queried_application = Application.objects.get_or_none(id=application.id)
        assert queried_application.udate > udate


class TestCustomerManager(TestCase):
    def test_generate_xid(self):
        user = AuthUserFactory()
        customer = Customer.objects.create(user=user)

        self.assertIsNotNone(customer.customer_xid)
        self.assertTrue(customer.customer_xid > 10000000000000)

    def test_not_generate_xid_if_customer_xid_is_set(self):
        user = AuthUserFactory()
        customer = Customer.objects.create(user=user, customer_xid=123456789)

        self.assertEqual(123456789, customer.customer_xid)

    @patch('juloserver.julo.models.logger')
    @patch('juloserver.julo.models.SystemRandom')
    def test_generate_xid_duplicate_once(self, mock_random, mock_logger):
        mock_sys_rands = [MagicMock() for _ in range(3)]
        mock_sys_rands[0].randrange.return_value = 1
        mock_sys_rands[1].randrange.return_value = 1
        mock_sys_rands[2].randrange.return_value = 2
        mock_random.side_effect = mock_sys_rands

        Customer.objects.create(user=AuthUserFactory())
        customer = Customer.objects.create(user=AuthUserFactory())

        self.assertEquals(2, customer.customer_xid)
        mock_logger.exception.assert_not_called()

    @patch('juloserver.julo.models.logger')
    @patch('juloserver.julo.models.SystemRandom')
    def test_generate_xid_duplicate_3_times(self, mock_random, mock_logger):
        mock_sys_rands = [MagicMock() for _ in range(5)]
        mock_sys_rands[0].randrange.return_value = 1
        mock_sys_rands[1].randrange.return_value = 1
        mock_sys_rands[2].randrange.return_value = 1
        mock_sys_rands[3].randrange.return_value = 1
        mock_sys_rands[4].randrange.return_value = 2
        mock_random.side_effect = mock_sys_rands

        Customer.objects.create(user=AuthUserFactory())
        customer = Customer.objects.create(user=AuthUserFactory())

        self.assertIsNone(customer.customer_xid)
        mock_logger.exception.assert_called_once_with({
            "module": "julo",
            "action": "CustomerManager.generate_and_update_customer_xid",
            "message": "Cannot generate unique customer_xid. {}".format(customer.id),
            "customer_id": customer.id
        })


class TestCustomer(TestCase):
    def test_generated_customer_xid(self):
        customer = CustomerFactory()
        customer.update_safely(customer_xid=None)

        customer_xid = customer.generated_customer_xid
        self.assertIsNotNone(customer_xid)

    def test_generated_customer_xid_if_exists(self):
        customer = CustomerFactory(customer_xid=123456789)

        customer_xid = customer.generated_customer_xid
        self.assertEquals(123456789, customer_xid)


class TestPartnerXID(TestCase):
    def test_generated_partner_xid_not_none(self):
        partner = PartnerFactory(name='Ali baba')
        self.assertIsNotNone(partner.partner_xid)
        self.assertEqual(len(partner.partner_xid), 7)
        self.assertTrue(partner.partner_xid.startswith('ALIx'))

        # less than 3 chars
        partner = PartnerFactory(name='yu')
        self.assertIsNotNone(partner.partner_xid)
        self.assertEqual(len(partner.partner_xid), 7)
        self.assertTrue(partner.partner_xid.startswith('YUx'))

    def test_generated_partner_xid_exists(self):
        partner = PartnerFactory(partner_xid=123)
        self.assertEquals(123, partner.partner_xid)

    def test_existing_partner_xid(self):
        PartnerFactory(partner_xid='abc')
        with self.assertRaises(IntegrityError):
            PartnerFactory(partner_xid='abc')
