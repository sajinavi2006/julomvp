import json
import math
from unittest import skip

import mock
import hashlib
from past.utils import old_div
import pytest
import random
from faker import Faker
import datetime
from django.test import TestCase
from django.utils import timezone
from unittest.mock import MagicMock
from datetime import timedelta
from freezegun import freeze_time

from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory,
)
from juloserver.followthemoney.factories import LenderBalanceCurrentFactory
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.julo.formulas import round_rupiah_grab
from juloserver.grab.services.crs_failed_validation_services import (
    CRSFailedValidationService,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.grab.constants import (
    GrabWriteOffStatus,
    GrabApplicationConstants,
    grab_rejection_mapping_statuses,
    GRAB_FAILED_3MAX_CREDITORS_CHECK,
    INFO_CARD_AJUKAN_PINJAMAN_LAGI_DESC,
    GrabFeatureNameConst,
    GrabMasterLockReasons,
)
from juloserver.grab.exceptions import GrabLogicException
from juloserver.account_payment.tests.factories import PaymentFactory, AccountPaymentFactory
from unittest.mock import ANY
from juloserver.grab.clients.paths import GrabPaths
from juloserver.grab.services.services import (
    GrabCommonService,
    check_existing_customer_status,
    change_phone_number_grab,
    GrabAuthService,
    check_active_loans_pending_j1_mtl,
    can_reapply_application_grab, get_expiry_date_grab, GrabLoanService, GrabApplicationService,
    GrabAPIService,
    validate_email_application,
    validate_email,
    validate_nik,
    validate_phone_number,
    get_sphp_context_grab,
    verify_grab_loan_offer,
    get_additional_check_for_rejection_grab,
    validate_loan_request,
    check_grab_reapply_eligibility,
    get_sphp_template_grab,
    get_account_summary_loan_status,
    get_loans,
    block_users_other_than_grab,
    get_missed_called_otp_creation_active_flags,
    get_latest_available_otp_request_grab,
    add_grab_loan_promo_code,
    update_grab_loan_promo_code_with_loan_id,
    EmergencyContactService,
    GrabRestructureHistoryLogService
)
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.account.tests.factories import (
    AccountLookupFactory,
    AccountFactory,
    AccountLimitFactory,
    AccountTransactionFactory
)
from juloserver.disbursement.tests.factories import (
    NameBankValidationFactory,
    BankNameValidationLogFactory
)
from juloserver.julo.tests.factories import (
    ApplicationExperimentFactory,
    AuthUserFactory,
    ExperimentFactory,
    FeatureSettingFactory,
    ApplicationFactory,
    CustomerFactory,
    LoanFactory,
    StatusLookupFactory,
    ProductLine,
    WorkflowFactory,
    OtpRequestFactory,
    DocumentFactory,
    BankFactory,
    ProductLineFactory,
    ProductLookupFactory,
    PartnerFactory,
    ApplicationHistoryFactory,
    PaymentEventFactory,
    LoanHistoryFactory,
    LenderFactory,
    LoanHistoryFactory,
    MobileFeatureSettingFactory,
    CommsProviderLookupFactory,
    SmsHistoryFactory
)
from juloserver.apiv2.tests.factories import AutoDataCheckFactory
from juloserver.loan.services.lender_related import julo_one_disbursement_process
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod
from juloserver.otp.constants import (
    OTPType,
    FeatureSettingName,
    MisCallOTPStatus,
    SessionTokenAction,
    CitcallRetryGatewayType,
)
from juloserver.otp.models import MisCallOTP
from juloserver.pin.tests.factories import CustomerPinFactory
from juloserver.streamlined_communication.test.factories import (
    StreamlinedCommunicationFactory,
    InfoCardPropertyFactory,
    StreamlinedMessageFactory
)
from juloserver.streamlined_communication.constant import CommunicationPlatform, CardProperty
from juloserver.grab.tests.factories import (
    GrabCustomerDataFactory,
    GrabLoanInquiryFactory,
    GrabLoanDataFactory,
    GrabAPILogFactory,
    GrabLoanOfferFactory,
    GrabPromoCodeFactory,
    GrabLoanPromoCodeFactory,
    EmergencyContactApprovalLinkFactory,
    GrabFeatureSettingFactory,
)
from juloserver.grab.models import (
    GrabCustomerData,
    GrabAPILog,
    GrabLoanOffer,
    GrabLoanData,
    GrabLoanInquiry,
    GrabExperiment,
    GrabLoanOfferArchival,
    GrabMisCallOTPTracker,
    GrabLoanPromoCode,
    EmergencyContactApprovalLink,
    GrabMasterLock,
    GrabRestructreHistoryLog
)
from juloserver.julo.models import (
    ApplicationFieldChange,
    ApplicationHistory,
    CustomerFieldChange,
    OtpRequest,
    Payment,
    StatusLookup,
    WorkflowStatusPath,
    EmailHistory,
    LoanHistory,
    FeatureSetting,
    SmsHistory,
    Application,
    Customer
)
from juloserver.grab.clients.request_constructors import GrabRequestDataConstructor
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
    AccountLimitFactory
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.grab.exceptions import GrabLogicException, GrabApiException
from juloserver.customer_module.tests.factories import (
    BankAccountDestinationFactory,
    BankAccountCategoryFactory
)
from juloserver.account.tests.factories import AccountLimitFactory
from juloserver.julo.statuses import PaymentStatusCodes, ApplicationStatusCodes, LoanStatusCodes
from juloserver.grab.communication.email import trigger_sending_email_sphp, \
    send_grab_restructure_email
from juloserver.julo.clients.email import JuloEmailClient
from juloserver.loan.services.sphp import check_predisbursal_check_grab, accept_julo_sphp
from juloserver.julo.exceptions import JuloException
from juloserver.grab.services.services import update_loan_status_for_grab_invalid_bank_account
from juloserver.grab.services.loan_related import (
    check_grab_auth_success, get_change_reason_and_loan_status_change_mapping_grab,
    compute_payment_installment_grab, compute_final_payment_principal_grab,
    get_loan_repayment_amount
)
from juloserver.grab.constants import (
    GrabErrorMessage,
    GrabAuthAPIErrorCodes,
    GrabBankValidationStatus
)
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.grab.services.bank_rejection_flow import GrabChangeBankAccountService
from juloserver.disbursement.models import (
    NameBankValidation,
    NameBankValidationHistory,
    BankNameValidationLog
)
from juloserver.grab.utils import MockValidationProcessService
from juloserver.customer_module.models import BankAccountDestination
from juloserver.grab.serializers import GrabApplicationV2Serializer
from juloserver.grab.tasks import (
    generate_ajukan_pinjaman_lagi_info_card,
)
from juloserver.grab.script import (
    generate_belum_bisa_melanjukan_aplikasi_info_card
)
from juloserver.application_form.constants import EmergencyContactConst
from juloserver.grab.services.crs_failed_validation_services import CRSFailedValidationService
from http import HTTPStatus
from django.conf import settings

fake = Faker()


class TestGrabFeatureSettings(TestCase):
    def setUp(self):
        self.feature_settings = FeatureSettingFactory()
        self.feature_settings.feature_name = FeatureNameConst.GRAB_STOP_REGISTRATION
        self.feature_settings.save()
        self.phone = '628525443990'
        self.pin = '000000'
        self.user = AuthUserFactory()
        self.user.set_password(self.pin)
        self.user.save()
        self.token = '906d4e43a3446cecb4841cf41c10c91c9610c8a5519437c913ab9144b71054f915752a69d' \
                     '0220619666ac3fc1f27f7b4934a6a4b2baa2f85b6533c663ca6d98f976328625f756e79a7cc' \
                     '543770b6945c1a5aaafd066ceed10204bf85c07c2fae81118d990d7c5fafcb98f8708f540d6d' \
                     '8971764c12b9fb912c7d1c3b1db1f931'
        self.customer = CustomerFactory(phone=self.phone, user=self.user)
        self.grab_customer_data = GrabCustomerDataFactory(
            phone_number=self.phone,
            customer=self.customer,
            grab_validation_status=True,
            otp_status='VERIFIED',
            token=self.token
        )
        self.application_grab = ApplicationFactory(customer=self.customer)
        self.application_grab.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.application_grab.update_safely(
            workflow=WorkflowFactory(name=WorkflowConst.GRAB),
            application_status=StatusLookupFactory(status_code=106)
        )

    def test_feature_setting_api_active(self):
        return_value = GrabCommonService.get_grab_feature_setting()
        assert_value = {'grab_customer_registeration': True}
        self.assertDictEqual(return_value, assert_value)

    def test_feature_setting_api_off(self):
        self.feature_settings.update_safely(is_active=False)
        return_value = GrabCommonService.get_grab_feature_setting()
        assert_value = {'grab_customer_registeration': False}
        self.assertDictEqual(return_value, assert_value)

    def test_feature_setting_api_off_disable_ajukan_button(self):
        return_value = GrabAPIService.application_status_check(self.customer)
        self.assertEqual(return_value.get('activate_loan_button'), False)

    def test_feature_setting_api_off_disable_create_loan(self):
        with pytest.raises(Exception) as err_info:
            GrabLoanService().apply(self.customer, self.user, 'DAX_ID_CL02', 1000000, 120)
        self.assertEqual(str(err_info.value),'grab modal registration not active')

    def test_feature_setting_api_off_disable_loan_offer(self):
        with pytest.raises(Exception) as err_info:
            GrabLoanService().get_loan_offer('test_token', '085225443889')
        self.assertEqual(str(err_info.value), 'Can\'t getting offer at the moment')


class TestGrabReapplyCondition(TestCase):
    def setUp(self):
        self.customer_mtl = CustomerFactory(id=125612347)
        self.customer_j1 = CustomerFactory(id=125612348)
        self.customer_jturbo = CustomerFactory(id=fake.random_int(min=1))
        product_line = ProductLine.objects.get_or_none(product_line_code=10)
        product_line_jturbo = ProductLine.objects.get_or_none(product_line_code=2)
        self.application_mtl = ApplicationFactory(
            customer=self.customer_mtl,
            product_line=product_line)
        self.application_j1 = ApplicationFactory(
            customer=self.customer_j1)
        self.application_jturbo = ApplicationFactory(
            customer=self.customer_jturbo, product_line=product_line_jturbo
        )
        self.application_j1.workflow = WorkflowFactory(name='JuloOneWorkflow')
        self.application_j1.application_status = StatusLookupFactory(status_code=106)
        self.application_j1.save()
        self.application_mtl.application_status = StatusLookupFactory(status_code=106)
        self.application_mtl.workflow = WorkflowFactory(name='CashLoanWorkflow')
        self.application_mtl.save()
        self.application_jturbo.application_status = StatusLookupFactory(status_code=106)
        self.application_jturbo.workflow = WorkflowFactory(name='JuloOneWorkflow')
        self.application_jturbo.save()

    def test_check_existing_customer_status_mtl(self):
        return_value = check_existing_customer_status(self.customer_mtl)
        self.assertTrue(return_value)

        self.application_mtl.application_status = StatusLookupFactory(status_code=180)
        self.application_mtl.save()
        return_value = check_existing_customer_status(self.customer_mtl)
        # self.assertFalse(return_value)

        self.loan_mtl = LoanFactory(application=self.application_mtl,
                                    customer=self.customer_mtl)
        self.application_mtl.application_status = StatusLookupFactory(status_code=106)
        self.application_mtl.save()
        return_value = check_existing_customer_status(self.customer_mtl)
        self.assertTrue(return_value)

        self.application_mtl.application_status = StatusLookupFactory(status_code=141)
        self.application_mtl.save()
        return_value = check_existing_customer_status(self.customer_mtl)
        self.assertFalse(return_value)

    def test_check_existing_customer_status_j1(self):
        return_value = check_existing_customer_status(self.customer_j1)
        self.assertTrue(return_value)

        self.application_j1.application_status = StatusLookupFactory(status_code=190)
        self.application_j1.save()
        return_value = check_existing_customer_status(self.customer_j1)
        self.assertFalse(return_value)

    def test_check_existing_customer_status_jturbo(self):
        return_value = check_existing_customer_status(self.customer_jturbo)
        self.assertTrue(return_value)

        self.application_jturbo.application_status = StatusLookupFactory(status_code=190)
        self.application_jturbo.save()

        return_value = check_existing_customer_status(self.customer_jturbo)
        self.assertFalse(return_value)


class TestGrabInfoCard(TestCase):
    def create_pilih_pinjaman_lagi_info_card(self):
        generate_ajukan_pinjaman_lagi_info_card()
        generate_belum_bisa_melanjukan_aplikasi_info_card()

    def setup_grab_application_and_loan(self, loan_status):
        self.application2 = ApplicationFactory(
            customer=self.customer2)
        self.application2.workflow = WorkflowFactory(name='GrabWorkflow')
        self.application2.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application2.save()

        if loan_status != 0:
            self.loan = LoanFactory(application=self.application2)
            self.loan.loan_status = StatusLookupFactory(status_code=loan_status)
            self.loan.save()

        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(
            account_lookup=self.account_lookup,
            customer=self.customer2
        )
        self.account.save()
        self.application2.account = self.account
        self.application2.save()

        if loan_status != 0:
            self.account.loan_set = [self.loan]

        if not GrabCustomerData.objects.filter(customer=self.customer2).exists():
            self.grab_customer_data = GrabCustomerDataFactory(
                customer=self.customer2,
                otp_status=GrabCustomerData.VERIFIED,
                grab_validation_status=True
            )


    def setUp(self):
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB)

        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line, admin_fee=40000)

        self.customer_j1 = CustomerFactory(id=125612349)
        self.application_j1 = ApplicationFactory(
            customer=self.customer_j1)
        self.application_j1.workflow = WorkflowFactory(name='JuloOneWorkflow')
        self.application_j1.application_status = StatusLookupFactory(status_code=106)
        self.application_j1.save()
        self.streamlined_comms = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            extra_conditions=CardProperty.GRAB_INFO_CARD_JULO_CUSTOMER
        )
        self.streamlined_comms_failed = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            extra_conditions=CardProperty.GRAB_INFO_CARD_JULO_CUSTOMER_FAILED
        )
        self.customer = CustomerFactory(id=125612360)
        self.application = ApplicationFactory(
            customer=self.customer)
        self.application.workflow = WorkflowFactory(name='GrabWorkflow')
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED)
        self.application.save()
        self.streamlined_comms_ = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            extra_conditions=CardProperty.GRAB_BANK_ACCOUNT_REJECTED,
            status=ApplicationStatusCodes.APPLICATION_DENIED,
            status_code=self.application.application_status
        )
        self.streamlined_comms_grab_phone_number_check = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            extra_conditions=CardProperty.GRAB_PHONE_NUMBER_CHECK_FAILED,
            status=ApplicationStatusCodes.APPLICATION_DENIED,
            status_code=self.application.application_status
        )
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_new=ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason='bank account not under own name'
        )

        self.customer1 = CustomerFactory(id=125612356)
        self.application1 = ApplicationFactory(
            customer=self.customer1)
        self.application1.workflow = WorkflowFactory(name='GrabWorkflow')
        self.application1.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED)
        self.application1.save()
        self.streamlined_comms1 = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            extra_conditions=CardProperty.GRAB_INFO_CARD_REAPPLY,
            status=ApplicationStatusCodes.APPLICATION_DENIED,
            status_code=self.application.application_status
        )
        self.application_history1 = ApplicationHistoryFactory(
            application_id=self.application1.id,
            status_new=ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason='customer_triggered'
        )

        self.customer2 = CustomerFactory(id=125612357)
        self.application2 = ApplicationFactory(
            customer=self.customer2)
        self.application2.workflow = WorkflowFactory(name='GrabWorkflow')
        self.application2.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED)
        self.application2.save()
        self.streamlined_comms2 = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            extra_conditions=CardProperty.GRAB_INFO_CARD,
            status=ApplicationStatusCodes.APPLICATION_DENIED,
            status_code=self.application2.application_status
        )
        self.customer3 = CustomerFactory(id=125612390)
        self.application3 = ApplicationFactory(
            customer=self.customer3)
        self.application3.workflow = WorkflowFactory(name='GrabWorkflow')
        self.application3.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL)
        self.application3.save()
        self.streamlined_comms3_ = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            extra_conditions=CardProperty.GRAB_FAILED_3MAX_CREDITORS_CHECK,
            status=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
            status_code=self.application3.application_status
        )
        self.application_history3 = ApplicationHistoryFactory(
            application_id=self.application3.id,
            status_new=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
            change_reason=GRAB_FAILED_3MAX_CREDITORS_CHECK
        )
        self.account_lookup3 = AccountLookupFactory(workflow=self.application1.workflow)
        self.account3 = AccountFactory(
            account_lookup=self.account_lookup3,
            customer=self.customer3
        )
        self.loan3 = LoanFactory(
            account=self.account3,
            customer=self.customer3,
            application=self.application3,
            loan_amount=10000000,
            loan_xid=1000003067,
        )
        self.account_payment3 = AccountPaymentFactory(
            account=self.account3,
            due_date=timezone.localtime(timezone.now()) + timedelta(days=20),
            is_collection_called=False,
        )
        self.info_card = InfoCardPropertyFactory(card_type='1')
        self.streamlined_message = StreamlinedMessageFactory(
            message_content="content",
            info_card_property=self.info_card
        )
        self.streamlined_comms4_ = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.INFO_CARD,
            is_active=True,
            extra_conditions=CardProperty.GRAB_FAILED_3MAX_CREDITORS_BOTTOM_SHEET,
            status=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
            status_code=self.application3.application_status,
            message=self.streamlined_message,
        )

    @mock.patch('juloserver.grab.services.services.format_info_card_for_android')
    @mock.patch('juloserver.grab.services.services.check_existing_customer_status')
    def test_info_card_j1(self, mocked_status, mocked_infocard):
        card_due_date = '-'
        card_due_amount = '-'
        card_cashback_amount = '-'
        card_cashback_multiplier = '-'
        card_dpd = '-'
        available_context = {
            'card_title': self.application_j1.bpk_ibu,
            'card_full_name': self.application_j1.full_name_only,
            'card_first_name': self.application_j1.first_name_only,
            'card_due_date': card_due_date,
            'card_due_amount': card_due_amount,
            'card_cashback_amount': card_cashback_amount,
            'card_cashback_multiplier': str(card_cashback_multiplier) + 'x',
            'card_dpd': card_dpd
        }

        mocked_status.return_value = True
        mocked_infocard.return_value = None
        infocard = GrabCommonService.get_info_card(customer=self.customer_j1)
        mocked_status.assert_called_once()
        mocked_infocard.assert_called_with(self.streamlined_comms, available_context)
        self.assertIsNotNone(infocard)

        mocked_status.reset_mock()
        mocked_status.return_value = False
        infocard = GrabCommonService.get_info_card(customer=self.customer_j1)
        mocked_status.assert_called_once()
        mocked_infocard.assert_called_with(self.streamlined_comms_failed, available_context)
        self.assertIsNotNone(infocard)

    @mock.patch('juloserver.grab.services.services.format_info_card_for_android')
    @mock.patch('juloserver.grab.services.services.can_reapply_application_grab')
    @mock.patch('juloserver.grab.services.services.check_grab_reapply_eligibility')
    def test_info_card_with_135(self, mocked_reapply_eligibility, mocked_reapply_application_grab,
                                mocked_infocard):
        card_due_date = '-'
        card_due_amount = '-'
        card_cashback_amount = '-'
        card_cashback_multiplier = '-'
        card_dpd = '-'
        available_context = {
            'card_due_date': card_due_date,
            'card_due_amount': card_due_amount,
            'card_cashback_amount': card_cashback_amount,
            'card_cashback_multiplier': str(card_cashback_multiplier) + 'x',
            'card_dpd': card_dpd
        }

        mocked_reapply_application_grab.return_value = True
        infocard = GrabCommonService.get_info_card(customer=self.customer)
        mocked_reapply_eligibility.assert_called_once()
        mocked_reapply_application_grab.assert_called_once()
        available_context['card_title'] = self.application.bpk_ibu
        available_context['card_full_name'] = self.application.full_name_only
        available_context['card_first_name'] = self.application.first_name_only
        mocked_infocard.assert_called_with(self.streamlined_comms_, available_context)
        self.assertIsNotNone(infocard)

        mocked_reapply_eligibility.reset_mock()
        mocked_reapply_application_grab.reset_mock()
        mocked_reapply_application_grab.return_value = True
        infocard = GrabCommonService.get_info_card(customer=self.customer1)
        mocked_reapply_eligibility.assert_called_once()
        mocked_reapply_application_grab.assert_called_once()
        available_context['card_title'] = self.application1.bpk_ibu
        available_context['card_full_name'] = self.application1.full_name_only
        available_context['card_first_name'] = self.application1.first_name_only
        mocked_infocard.assert_called_with(self.streamlined_comms1, available_context)
        self.assertIsNotNone(infocard)

        mocked_reapply_eligibility.reset_mock()
        mocked_reapply_application_grab.reset_mock()
        mocked_reapply_application_grab.return_value = False
        infocard = GrabCommonService.get_info_card(customer=self.customer2)
        mocked_reapply_eligibility.assert_called_once()
        mocked_reapply_application_grab.assert_called_once()
        available_context['card_title'] = self.application2.bpk_ibu
        available_context['card_full_name'] = self.application2.full_name_only
        available_context['card_first_name'] = self.application2.first_name_only
        mocked_infocard.assert_called_with(self.streamlined_comms2, available_context)
        self.assertIsNotNone(infocard)

    @mock.patch('juloserver.grab.services.services.format_info_card_for_android')
    @mock.patch('juloserver.grab.services.services.can_reapply_application_grab')
    @mock.patch('juloserver.grab.services.services.check_grab_reapply_eligibility')
    def test_info_card_with_135_grab_phone_number_check(
        self,
        mocked_reapply_eligibility,
        mocked_reapply_application_grab,
        mocked_infocard
    ):
        card_due_date = '-'
        card_due_amount = '-'
        card_cashback_amount = '-'
        card_cashback_multiplier = '-'
        card_dpd = '-'
        available_context = {
            'card_due_date': card_due_date,
            'card_due_amount': card_due_amount,
            'card_cashback_amount': card_cashback_amount,
            'card_cashback_multiplier': str(card_cashback_multiplier) + 'x',
            'card_dpd': card_dpd
        }

        self.application_history.change_reason = "grab_phone_number_check"
        self.application_history.save()

        mocked_reapply_application_grab.return_value = True
        infocard = GrabCommonService.get_info_card(customer=self.customer)
        mocked_reapply_eligibility.assert_called_once()
        mocked_reapply_application_grab.assert_called_once()
        available_context['card_title'] = self.application.bpk_ibu
        available_context['card_full_name'] = self.application.full_name_only
        available_context['card_first_name'] = self.application.first_name_only
        mocked_infocard.assert_called_with(
            self.streamlined_comms_grab_phone_number_check,
            available_context
        )

    @mock.patch('juloserver.grab.services.services.format_info_card_for_android')
    def test_info_card_with_180(self,
                                mocked_infocard):
        card_due_date = '-'
        card_due_amount = '-'
        card_cashback_amount = '-'
        card_cashback_multiplier = '-'
        card_dpd = '-'
        available_context = {
            'card_due_date': card_due_date,
            'card_due_amount': card_due_amount,
            'card_cashback_amount': card_cashback_amount,
            'card_cashback_multiplier': str(card_cashback_multiplier) + 'x',
            'card_dpd': card_dpd
        }

        infocard = GrabCommonService.get_info_card(customer=self.customer3)
        available_context['card_title'] = self.application3.bpk_ibu
        available_context['card_full_name'] = self.application3.full_name_only
        available_context['card_first_name'] = self.application3.first_name_only
        mocked_infocard.assert_called_with(self.streamlined_comms3_, available_context)
        self.assertIsNotNone(infocard)

    @mock.patch('juloserver.grab.services.services.format_bottom_sheet_for_grab')
    @mock.patch('juloserver.grab.services.services.format_info_card_for_android')
    def test_info_card_with_180_bottom_sheet(self,
                                             mocked_infocard,
                                             mocked_bottom_sheet):
        card_due_date = '-'
        card_due_amount = '-'
        card_cashback_amount = '-'
        card_cashback_multiplier = '-'
        card_dpd = '-'
        available_context = {
            'card_due_date': card_due_date,
            'card_due_amount': card_due_amount,
            'card_cashback_amount': card_cashback_amount,
            'card_cashback_multiplier': str(card_cashback_multiplier) + 'x',
            'card_dpd': card_dpd
        }

        infocard = GrabCommonService.get_info_card(customer=self.customer3)
        available_context['card_title'] = self.application3.bpk_ibu
        available_context['card_full_name'] = self.application3.full_name_only
        available_context['card_first_name'] = self.application3.first_name_only
        mocked_infocard.assert_called_with(self.streamlined_comms3_, available_context)
        mocked_bottom_sheet.assert_called_with(self.streamlined_comms4_, available_context)
        self.assertIsNotNone(infocard)

    @mock.patch("juloserver.grab.services.services.GrabCommonService.should_show_ajukan_pinjaman_lagi_info_card")
    @mock.patch('juloserver.grab.services.services.check_existing_customer_status')
    def test_ajukan_pinjaman_lagi_info_card(self, mock_status, mock_show_ajukan_pinjaman_info_card):
        mock_show_ajukan_pinjaman_info_card.return_value = True

        self.create_pilih_pinjaman_lagi_info_card()
        self.setup_grab_application_and_loan(250)

        infocard = GrabCommonService.get_info_card(customer=self.customer2)
        self.assertNotEqual(len(infocard['cards']), 0)

    @mock.patch("juloserver.grab.services.services.GrabCommonService.should_show_ajukan_pinjaman_lagi_info_card")
    @mock.patch('juloserver.grab.services.services.check_existing_customer_status')
    def test_ajukan_pinjaman_lagi_info_card_no_loan(self, mock_status, mock_show_ajukan_pinjaman_info_card):
        mock_show_ajukan_pinjaman_info_card.return_value = True

        self.create_pilih_pinjaman_lagi_info_card()
        self.setup_grab_application_and_loan(0)

        infocard = GrabCommonService.get_info_card(customer=self.customer2)
        self.assertNotEqual(len(infocard['cards']), 0)

    @mock.patch('juloserver.grab.services.services.GrabCommonService.is_crs_validation_error')
    @mock.patch(
        "juloserver.grab.services.services.GrabCommonService.should_show_ajukan_pinjaman_lagi_info_card"
    )
    @mock.patch('juloserver.grab.services.services.check_existing_customer_status')
    def test_belum_bisa_melanjukan_aplikasi_info_card(
        self, mock_status, mock_show_ajukan_pinjaman_info_card, mock_is_crs_validation_error
    ):
        mock_show_ajukan_pinjaman_info_card.return_value = False
        mock_is_crs_validation_error.return_value = True

        self.create_pilih_pinjaman_lagi_info_card()
        self.setup_grab_application_and_loan(250)

        infocard = GrabCommonService.get_info_card(customer=self.customer2)
        self.assertNotEqual(len(infocard['cards']), 0)
        belum_bisa_melanjukan_aplikasi_infocard = False
        for card in infocard['cards']:
            if 'Kamu Belum Bisa Melanjutkan Aplikasi' in card.get('title').get('text'):
                belum_bisa_melanjukan_aplikasi_infocard = True
        self.assertTrue(belum_bisa_melanjukan_aplikasi_infocard)

    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_loan_have_valid_log")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_application_valid")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_grab_customer_valid")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_loan_status_valid")
    def test_ajukan_pinjaman_lagi_no_feature_settings(
        self,
        mock_is_loan_valid,
        mock_is_grab_cust_valid,
        mock_is_application_valid,
        mock_is_loan_have_valid_log
    ):
        mock_is_loan_valid.return_value = True
        mock_is_grab_cust_valid.return_value = True
        mock_is_application_valid.return_value = True
        mock_is_loan_have_valid_log.return_value = True

        self.create_pilih_pinjaman_lagi_info_card()
        self.setup_grab_application_and_loan(250)

        infocard = GrabCommonService.get_info_card(customer=self.customer2)
        self.assertNotEqual(len(infocard['cards']), 0)

    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_loan_have_valid_log")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_application_valid")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_grab_customer_valid")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_loan_status_valid")
    def test_ajukan_pinjaman_lagi_feature_setting_on_disable_registration(
        self,
        mock_is_loan_valid,
        mock_is_grab_cust_valid,
        mock_is_application_valid,
        mock_is_loan_have_valid_log
    ):
        mock_is_loan_valid.return_value = True
        mock_is_grab_cust_valid.return_value = True
        mock_is_application_valid.return_value = True
        mock_is_loan_have_valid_log.return_value = True

        FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_STOP_REGISTRATION,
            is_active=True
        )

        self.create_pilih_pinjaman_lagi_info_card()
        self.setup_grab_application_and_loan(250)

        infocard = GrabCommonService.get_info_card(customer=self.customer2)
        self.assertEqual(len(infocard['cards']), 0)

    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_loan_have_valid_log")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_application_valid")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_grab_customer_valid")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_loan_status_valid")
    def test_ajukan_pinjaman_lagi_invalid_loan_log(
        self,
        mock_is_loan_valid,
        mock_is_grab_cust_valid,
        mock_is_application_valid,
        mock_is_loan_have_valid_log
    ):
        mock_is_loan_valid.return_value = True
        mock_is_grab_cust_valid.return_value = True
        mock_is_application_valid.return_value = True
        mock_is_loan_have_valid_log.return_value = False

        FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_STOP_REGISTRATION,
            is_active=True
        )

        self.create_pilih_pinjaman_lagi_info_card()
        self.setup_grab_application_and_loan(250)

        infocard = GrabCommonService.get_info_card(customer=self.customer2)
        self.assertEqual(len(infocard['cards']), 0)

    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_loan_have_valid_log")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_application_valid")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_grab_customer_valid")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_loan_status_valid")
    def test_ajukan_pinjaman_lagi_invalid_application(
        self,
        mock_is_loan_valid,
        mock_is_grab_cust_valid,
        mock_is_application_valid,
        mock_is_loan_have_valid_log
    ):
        mock_is_loan_valid.return_value = True
        mock_is_grab_cust_valid.return_value = True
        mock_is_application_valid.return_value = False
        mock_is_loan_have_valid_log.return_value = True

        FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_STOP_REGISTRATION,
            is_active=True
        )

        self.create_pilih_pinjaman_lagi_info_card()
        self.setup_grab_application_and_loan(250)

        infocard = GrabCommonService.get_info_card(customer=self.customer2)
        self.assertEqual(len(infocard['cards']), 0)

    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_loan_have_valid_log")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_application_valid")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_grab_customer_valid")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_loan_status_valid")
    def test_ajukan_pinjaman_invalid_grab_customer(
        self,
        mock_is_loan_valid,
        mock_is_grab_cust_valid,
        mock_is_application_valid,
        mock_is_loan_have_valid_log
    ):
        mock_is_loan_valid.return_value = True
        mock_is_grab_cust_valid.return_value = False
        mock_is_application_valid.return_value = True
        mock_is_loan_have_valid_log.return_value = True

        FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_STOP_REGISTRATION,
            is_active=True
        )

        self.create_pilih_pinjaman_lagi_info_card()
        self.setup_grab_application_and_loan(250)

        infocard = GrabCommonService.get_info_card(customer=self.customer2)
        self.assertEqual(len(infocard['cards']), 0)

    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_loan_have_valid_log")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_application_valid")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_grab_customer_valid")
    @mock.patch("juloserver.grab.services.services.GrabCommonService.is_loan_status_valid")
    def test_ajukan_pinjaman_lagi_invalid_loan_status(
        self,
        mock_is_loan_valid,
        mock_is_grab_cust_valid,
        mock_is_application_valid,
        mock_is_loan_have_valid_log
    ):
        mock_is_loan_valid.return_value = False
        mock_is_grab_cust_valid.return_value = True
        mock_is_application_valid.return_value = True
        mock_is_loan_have_valid_log.return_value = True

        FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_STOP_REGISTRATION,
            is_active=True
        )

        self.create_pilih_pinjaman_lagi_info_card()
        self.setup_grab_application_and_loan(250)

        infocard = GrabCommonService.get_info_card(customer=self.customer2)
        self.assertEqual(len(infocard['cards']), 0)

    @mock.patch('juloserver.grab.services.services.check_existing_customer_status')
    def test_ajukan_pinjaman_lagi_info_card_with_no_valid_loan_status(self, mock_status):
        self.create_pilih_pinjaman_lagi_info_card()
        for loan_status in [210, 211, 212, 213, 218]:
            self.setup_grab_application_and_loan(loan_status)
            infocard = GrabCommonService.get_info_card(customer=self.customer2)
            self.assertEqual(len(infocard['cards']), 0)

    @mock.patch('juloserver.grab.services.services.check_existing_customer_status')
    def test_ajukan_pinjaman_lagi_info_card_blocked_user(self, mock_status):
        self.create_pilih_pinjaman_lagi_info_card()
        self.setup_grab_application_and_loan(250)

        if self.grab_customer_data:
            self.grab_customer_data.is_customer_blocked_for_loan_creation = True
            self.grab_customer_data.save()
            self.grab_customer_data.refresh_from_db()
        else:
            self.grab_customer_data = GrabCustomerDataFactory(
                customer=self.customer2,
                otp_status=GrabCustomerData.VERIFIED,
                grab_validation_status=True,
                is_customer_blocked_for_loan_creation=True
            )

        infocard = GrabCommonService.get_info_card(customer=self.customer2)
        self.assertEqual(len(infocard['cards']), 0)

    def test_is_loan_status_valid(self):
        service = GrabCommonService

        test_cases = [
            {'loan_status': None, 'expected_result': True},
            {'loan_status': LoanStatusCodes.INACTIVE, 'expected_result': False},
            {'loan_status': LoanStatusCodes.LENDER_APPROVAL, 'expected_result': False},
            {'loan_status': LoanStatusCodes.FUND_DISBURSAL_ONGOING, 'expected_result': False},
            {'loan_status': LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING, 'expected_result': False},
            {'loan_status': LoanStatusCodes.FUND_DISBURSAL_FAILED, 'expected_result': False},
            {'loan_status': LoanStatusCodes.PAID_OFF, 'expected_result': True},
        ]

        for test in test_cases:
            if not test['loan_status']:
                self.loan = None
            else:
                self.setup_grab_application_and_loan(test['loan_status'])

            self.assertEqual(service.is_loan_status_valid(self.loan), test['expected_result'])

    def test_is_grab_customer_valid(self):
        service = GrabCommonService

        grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer2,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True,
            is_customer_blocked_for_loan_creation=False
        )

        self.assertTrue(service.is_grab_customer_valid(self.customer2.id))

        grab_customer_data.is_customer_blocked_for_loan_creation = True
        grab_customer_data.save()

        self.assertFalse(service.is_grab_customer_valid(self.customer2.id))

    def test_is_application_valid(self):
        service = GrabCommonService
        self.setup_grab_application_and_loan(250)
        self.assertFalse(service.is_application_valid(self.application))

        with freeze_time("2024-01-01"):
            app_history = ApplicationHistoryFactory(
                application_id=self.application.id,
                status_new=ApplicationStatusCodes.LOC_APPROVED
            )
            self.application.applicationhistory_set = [app_history]

        self.assertTrue(service.is_application_valid(self.application))


class TestGrabChangePhoneNumber(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.old_phone = '6281234568791'
        self.old_phone_otp = '6281234568793'
        self.new_phone = '6281234568792'
        self.new_phone_otp = '6281234568794'
        self.customer = CustomerFactory(phone=self.old_phone)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.application.save()
        self.pin = CustomerPinFactory(user=self.customer.user, last_failure_time=self.now)
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer, phone_number=self.old_phone,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True
        )

    @mock.patch('juloserver.grab.services.services.timezone.now')
    def test_change_phone_number(self, mock_now):
        mock_now.return_value = self.now
        response_data = {
            "update_customer": True
        }
        self.assertFalse(GrabCustomerData.objects.filter(phone_number=self.new_phone).exists())
        self.old_otp = OtpRequestFactory(
            is_used=True, phone_number=self.old_phone,
            customer=self.customer
        )
        self.new_otp = OtpRequestFactory(
            is_used=True, phone_number=self.new_phone,
            customer=self.customer
        )
        return_value = change_phone_number_grab(self.customer, self.old_phone, self.new_phone)
        self.assertDictEqual(return_value, response_data)

        self.assertTrue(ApplicationFieldChange.objects.filter(
            application=self.application,
            field_name='mobile_phone_1'
        ).exists())
        self.assertTrue(CustomerFieldChange.objects.filter(
            customer=self.customer,
            field_name='phone'
        ).exists())
        self.assertTrue(GrabCustomerData.objects.filter(phone_number=self.new_phone).exists())

    @mock.patch('juloserver.grab.services.services.send_sms_otp_token')
    def test_phone_otp(self, mocked_otp):
        mocked_otp.delay.return_value = None
        return_data = GrabAuthService.change_phonenumber_request_otp(
            self.old_phone_otp, "16001548654216", self.customer)
        self.assertTrue("request_id" in return_data)
        self.assertTrue(OtpRequest.objects.filter(
            is_used=False, phone_number=self.old_phone_otp,
            customer=self.customer
        ).exists())

        return_data = GrabAuthService.change_phonenumber_request_otp(
            self.new_phone_otp, "16001548654216", self.customer)
        self.assertTrue("request_id" in return_data)
        self.assertTrue(OtpRequest.objects.filter(
            is_used=False, phone_number=self.new_phone_otp,
            customer=self.customer
        ).exists())

        old_otp = OtpRequest.objects.filter(
            is_used=False, phone_number=self.old_phone_otp,
            customer=self.customer
        ).last()
        old_otp_token = old_otp.otp_token
        old_request_id = old_otp.request_id

        new_otp = OtpRequest.objects.filter(
            is_used=False, phone_number=self.new_phone_otp,
            customer=self.customer
        ).last()
        new_otp_token = new_otp.otp_token
        new_request_id = new_otp.request_id

        response_old = GrabAuthService.change_phonenumber_confirm_otp(
            self.customer, old_otp_token, old_request_id, self.old_phone_otp)
        self.assertDictEqual(response_old, {"is_otp_success": True})

        response_new = GrabAuthService.change_phonenumber_confirm_otp(
            self.customer, new_otp_token, new_request_id, self.new_phone_otp)
        self.assertDictEqual(response_new, {"is_otp_success": True})


class TestGrabReapply(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow
        )
        self.application.application_status = StatusLookupFactory(status_code=106)
        self.application_1 = ApplicationFactory(
            customer=self.customer,
            product_line_code=10
        )
        self.application_1.application_status = StatusLookupFactory(status_code=111)
        self.application_1.product_line = ProductLine.objects.filter(product_line_code=10).last()
        self.application.save()
        self.application_1.save()

        self.workflow_grab = WorkflowFactory(name=WorkflowConst.GRAB)
        self.application_grab = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_grab
        )
        self.application_grab.application_status = StatusLookupFactory(status_code=106)
        self.application_grab.save()

    def test_grab_reapply(self):
        return_value = check_active_loans_pending_j1_mtl(self.customer)
        self.assertTrue(return_value)

        self.application.application_status = StatusLookupFactory(status_code=190)
        self.application.save()
        return_value = check_active_loans_pending_j1_mtl(self.customer)
        self.assertFalse(return_value)

        self.application.application_status = StatusLookupFactory(status_code=106)
        self.application.save()
        self.application_1.application_status = StatusLookupFactory(status_code=111)
        self.application_1.save()
        return_value = check_active_loans_pending_j1_mtl(self.customer)
        self.assertTrue(return_value)

        self.application_1.application_status = StatusLookupFactory(status_code=180)
        self.loan = LoanFactory(application=self.application_1)
        self.loan.loan_status = StatusLookupFactory(status_code=250)
        self.loan.save()
        return_value = check_active_loans_pending_j1_mtl(self.customer)
        self.assertTrue(return_value)

        self.application_1.application_status = StatusLookupFactory(status_code=180)
        self.application_1.save()
        self.loan.loan_status = StatusLookupFactory(status_code=220)
        self.loan.save()
        return_value = check_active_loans_pending_j1_mtl(self.customer)
        self.assertFalse(return_value)

    def test_update_grab_loan_promo_code_with_loan_id(self):
        self.loan = LoanFactory(application=self.application_1)
        self.promo_code = GrabPromoCodeFactory(
            promo_code=111111,
            title="test",
            active_date='2024-01-04',
            expire_date=timezone.localtime(timezone.now()).date()
        )
        update_grab_loan_promo_code_with_loan_id(66666, self.loan.id)
        self.assertFalse(GrabLoanPromoCode.objects.filter(promo_code=self.promo_code,
                                                          loan_id=self.loan.id).exists())

        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer
        )
        grab_loan_inquiry = GrabLoanInquiryFactory(grab_customer_data=self.grab_customer_data)
        self.grab_loan_data = GrabLoanDataFactory(grab_loan_inquiry=grab_loan_inquiry)

        GrabLoanPromoCodeFactory(promo_code=self.promo_code,
                                 grab_loan_data_id=self.grab_loan_data.id)

        update_grab_loan_promo_code_with_loan_id(self.grab_loan_data.id, self.loan.id)
        self.assertTrue(GrabLoanPromoCode.objects.filter(promo_code=self.promo_code,
                                                         loan_id=self.loan.id).exists())
        self.promo_code = GrabPromoCodeFactory(
            promo_code=1111111,
            title="test",
            active_date='2024-01-03',
            expire_date='2024-01-05',
        )
        GrabLoanPromoCodeFactory(promo_code=self.promo_code,
                                 grab_loan_data_id=self.grab_loan_data.id)
        update_grab_loan_promo_code_with_loan_id(self.grab_loan_data.id, self.loan.id)
        self.assertFalse(GrabLoanPromoCode.objects.filter(promo_code=self.promo_code,
                                                          loan_id=self.loan.id).exists())

    def test_grab_can_reapply_flag(self):
        return_value = can_reapply_application_grab(self.customer)
        self.assertTrue(return_value)

        self.application_grab.application_status = StatusLookupFactory(status_code=133)
        self.application_grab.save()
        return_value = can_reapply_application_grab(self.customer)
        self.assertFalse(return_value)

        self.application_grab.application_status = StatusLookupFactory(status_code=137)
        self.application_grab.save()
        return_value = can_reapply_application_grab(self.customer)
        self.assertTrue(return_value)

        self.application_grab.application_status = StatusLookupFactory(status_code=135)
        self.application_grab.save()
        return_value = can_reapply_application_grab(self.customer)
        self.assertTrue(return_value)

        self.application_grab.application_status = StatusLookupFactory(status_code=105)
        self.application_grab.save()
        return_value = can_reapply_application_grab(self.customer)
        self.assertFalse(return_value)

        self.application_grab.application_status = StatusLookupFactory(status_code=100)
        self.application_grab.save()
        return_value = can_reapply_application_grab(self.customer)
        self.assertFalse(return_value)

        self.application_grab.application_status = StatusLookupFactory(status_code=135)
        self.application_grab.save()
        return_value = can_reapply_application_grab(self.customer)
        self.assertTrue(return_value)

        self.auto_data_check = AutoDataCheckFactory()
        self.auto_data_check.application_id = self.application_grab.id
        self.auto_data_check.data_to_check = "application_date_of_birth"
        self.auto_data_check.is_okay = False
        self.auto_data_check.save()
        self.application_grab.application_status = StatusLookupFactory(status_code=135)
        self.application_grab.save()
        return_value = can_reapply_application_grab(self.customer)
        self.assertTrue(return_value)

        self.auto_data_check.data_to_check = "fdc_inquiry_check"
        self.auto_data_check.save()
        self.application_grab.application_status = StatusLookupFactory(status_code=135)
        self.application_grab.save()
        return_value = can_reapply_application_grab(self.customer)
        self.assertTrue(return_value)

        self.auto_data_check.data_to_check = "grab_application_check"
        self.auto_data_check.save()
        self.application_grab.application_status = StatusLookupFactory(status_code=135)
        self.application_grab.save()
        return_value = can_reapply_application_grab(self.customer)
        self.assertFalse(return_value)

        self.auto_data_check.data_to_check = "blacklist_customer_check"
        self.auto_data_check.save()
        self.application_grab.application_status = StatusLookupFactory(status_code=135)
        self.application_grab.save()
        return_value = can_reapply_application_grab(self.customer)
        self.assertFalse(return_value)


class TestGrabServices1(TestCase):
    @mock.patch('juloserver.julo.models.XidLookup.get_new_xid')
    def setUp(self, mock_get_new_xid):
        mock_get_new_xid.return_value = "121212"
        self.mobile_phone = '6281245789865'
        self.token = '906d4e43a3446cecb4841cf41c10c91c9610c8a5519437c913ab9144b71054f915752a69d' \
                     '0220619666ac3fc1f27f7b4934a6a4b2baa2f85b6533c663ca6d98f976328625f756e79a7cc' \
                     '543770b6945c1a5aaafd066ceed10204bf85c07c2fae81118d990d7c5fafcb98f8708f540d6d' \
                     '8971764c12b9fb912c7d1c3b1db1f931'
        self.hashed_phone_number = '7358b08205b13f3ec8967ea7f1c331a40cefdeda0cef8bf8b9ca7acefd9564a2'
        self.customer = CustomerFactory(phone=self.mobile_phone)
        self.grab_customer_data = GrabCustomerDataFactory(
            phone_number=self.mobile_phone,
            customer=self.customer,
            grab_validation_status=True,
            otp_status='VERIFIED',
            token=self.token,
            hashed_phone_number=self.hashed_phone_number
        )
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(
            account_lookup=self.account_lookup,
            customer=self.customer
        )
        self.workflow_path = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=211, status_next=214, workflow=self.workflow_path)
        WorkflowStatusPathFactory(status_previous=211, status_next=219, workflow=self.workflow_path)
        WorkflowStatusPathFactory(status_previous=210, status_next=216, workflow=self.workflow_path)
        WorkflowStatusPathFactory(status_previous=211, status_next=216, workflow=self.workflow_path)
        WorkflowStatusPathFactory(status_previous=220, status_next=230, workflow=self.workflow_path)
        WorkflowStatusPathFactory(status_previous=0, status_next=100,
                                  workflow=self.workflow, is_active=True)
        WorkflowStatusPathFactory(status_previous=100, status_next=105,
                                  workflow=self.workflow, is_active=True)

        self.account_limit = AccountLimitFactory(account=self.account)

        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB)
        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line, admin_fee=40000)
        self.name_bank_validation = NameBankValidationFactory(bank_code='HELLOQWE')
        self.bank = BankFactory(xfers_bank_code='HELLOQWE')
        self.application_status_code = StatusLookupFactory(code=190)
        self.partner = PartnerFactory(name="grab")
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            application_status=self.application_status_code,
            mobile_phone_1=self.mobile_phone,
            bank_name='bank_test',
            name_in_bank='name_in_bank'
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            name_bank_validation_id=self.name_bank_validation.id,
            product=self.product_lookup
        )
        self.txn_id = 'abc123'
        self.document = DocumentFactory(loan_xid=self.loan.loan_xid, document_type='sphp_julo')
        self.feature_settings = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_STOP_REGISTRATION,
            is_active=False
        )
        self.slo_feature_setting = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.GRAB_SMALLER_LOAN_OPTION,
            parameters={
                'min_loan_amount': 3500000,
                'range_to_max_gen_loan_amount': 2000000,
                'loan_option_range': ['30%', '60%'],
                'loan_tenure': 180
            },
            is_active=True,
            category="grab",
            description="setting for grab smaller loan options experiment"
        )

    def test_get_expiry_date_grab(self):
        expiry_date = get_expiry_date_grab(self.application)
        self.assertIsNone(expiry_date)

        self.application.application_status = StatusLookupFactory(status_code=131)
        self.application.save()
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_new=131,
            status_old=124
        )
        expiry_date = get_expiry_date_grab(self.application)
        self.assertIsNotNone(expiry_date)
        self.application.application_status = StatusLookupFactory(status_code=100)
        self.application.save()
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_new=100,
            status_old=0
        )
        expiry_date = get_expiry_date_grab(self.application)
        self.assertIsNotNone(expiry_date)

        self.loan.sphp_exp_date = timezone.now().date()
        self.loan.loan_status = StatusLookupFactory(status_code=210)
        self.loan.save()
        self.application.application_status = StatusLookupFactory(status_code=190)
        self.application.save()
        expiry_date = get_expiry_date_grab(self.application)
        self.assertIsNotNone(expiry_date)

        self.loan.loan_status = StatusLookupFactory(status_code=211)
        self.loan.save()
        self.application.application_status = StatusLookupFactory(status_code=190)
        self.application.save()
        expiry_date = get_expiry_date_grab(self.application)
        self.assertIsNone(expiry_date)

    @mock.patch('juloserver.grab.services.services.GrabClient')
    def test_get_loan_offer(self, mocked_client):
        mocked_client.get_loan_offer.return_value = \
            {
                "msg_id": "7eab2027d4be41ef86a98ff60c542c9d",
                "success": True, "version": "1",
                "data": [
                    {"program_id": "DAX_ID_CL02", "max_loan_amount": "1000000",
                     "min_loan_amount": "500000", "weekly_installment_amount":"1000000",
                     "loan_duration": 180, "min_tenure": 60, "tenure_interval": 30,
                     "frequency_type": "DAILY", "fee_type": "FLAT", "fee_value": "40000",
                     "interest_type": "SIMPLE_INTEREST", "interest_value": "3",
                     "penalty_type": "FLAT", "penalty_value": "2000000"}]}
        response = GrabLoanService().get_loan_offer(self.token, self.mobile_phone)
        self.assertTrue(len(response) >= 1)

        mocked_client.get_loan_offer.return_value = \
            {
                "msg_id": "7eab2027d4be41ef86a98ff60c542c9d",
                "success": True, "version": "1",
                "data": [
                    {"program_id": "DAX_ID_CL02", "max_loan_amount": "1000000",
                     "min_loan_amount": "500000", "weekly_installment_amount": "1000000",
                     "loan_duration": 180, "min_tenure": 60, "tenure_interval": 30,
                     "frequency_type": "DAILY", "fee_type": "FLAT", "fee_value": "40000",
                     "interest_type": "SIMPLE_INTEREST", "interest_value": "3",
                     "penalty_type": "FLAT", "penalty_value": "2000000"}]}

        response = GrabLoanService().get_loan_offer(self.token, self.mobile_phone)
        self.assertTrue(len(response) == 1)
        for loan_offer in response:
            total_daily_repayment =int(loan_offer.get('daily_repayment')) * \
                int(loan_offer.get('tenure'))
            self.assertTrue(total_daily_repayment > int(loan_offer.get('max_loan_amount')))

    @mock.patch('juloserver.grab.services.services.GrabClient')
    def test_get_loan_offer_2(self, mocked_client):
        for i in range (1, 6):
            program_id = "DAX_ID_CL-{}".format(i)
            mocked_client.get_loan_offer.return_value = \
                {
                    "msg_id": "7eab2027d4be41ef86a98ff60c542c9d",
                    "success": True, "version": "1",
                    "data": [
                        {"program_id": program_id, "max_loan_amount": "1000000",
                        "min_loan_amount": "500000", "weekly_installment_amount":"1000000",
                        "loan_duration": 180, "min_tenure": 60, "tenure_interval": 30,
                        "frequency_type": "DAILY", "fee_type": "FLAT", "fee_value": "40000",
                        "interest_type": "SIMPLE_INTEREST", "interest_value": "3",
                        "penalty_type": "FLAT", "penalty_value": "2000000"}]}
            response = GrabLoanService().get_loan_offer(self.token, self.mobile_phone)
            self.assertEqual(len(response), 1)

        grab_loan_offer = GrabLoanOffer.objects.filter(
            grab_customer_data=self.grab_customer_data.id
        )
        self.assertEqual(grab_loan_offer.count(), 1)
        self.assertEqual(grab_loan_offer.last().program_id, program_id)

        grab_loan_offer_archival = GrabLoanOfferArchival.objects.filter(
            grab_customer_data=self.grab_customer_data.id
        )
        self.assertEqual(grab_loan_offer_archival.count(), 5)
        programs_id = ["DAX_ID_CL-{}".format(i) for i in range(1, 6)]
        for loan_offer_archival in grab_loan_offer_archival.iterator():
            self.assertTrue(loan_offer_archival.program_id in programs_id)


    @mock.patch('juloserver.grab.services.services.GrabClient')
    def test_get_loan_offer_profile_not_found(self, mocked_client):
        mocked_client.get_loan_offer.return_value = \
            {
                "msg_id": "6670b4124b2f4c7192dc12bf9fdd3563",
                "success": False,
                "error":
                    {
                        "code": "4002",
                        "message": "UserProfileNotFound"
                    }
            }
        self.grab_customer_data.customer = None
        self.grab_customer_data.save()
        response = GrabLoanService().get_loan_offer(self.token, self.mobile_phone)
        self.assertTrue(len(response) == 0)

        mocked_client.get_loan_offer.return_value = \
            {
                "msg_id": "6670b4124b2f4c7192dc12bf9fdd3563",
                "success": False,
                "error":
                    {
                        "code": "4002",
                        "message": "UserProfileNotFound"
                    }
            }
        self.grab_customer_data.customer = self.customer
        self.grab_customer_data.save()
        with self.assertRaises(GrabLogicException) as context:
            response = GrabLoanService().get_loan_offer(self.token, self.mobile_phone)

    def test_get_payment_plans(self):
        GrabLoanOfferFactory(
            grab_customer_data=self.grab_customer_data,
            program_id="DAX_ID_CL02",
            interest_value=3,
            fee_value=40000,
            min_tenure=60,
            tenure=180,
            tenure_interval=30,
            weekly_installment_amount=1000000,
            min_loan_amount=500000,
            max_loan_amount=1000000
        )
        responses = GrabLoanService().get_payment_plans(
            self.token, self.mobile_phone, 'DAX_ID_CL02', '1000000', '3', '40000',
            60, 180, 30, ' 1000000', '500000', '1000000')
        self.assertTrue(len(responses) > 0)

    def test_get_payment_plans_2(self):
        payload = {
            "program_id": "ID-DAX-CL-9-MONTHS",
            "loan_amount": 1200000,
            "phone_number": "6281229969301",
            "interest_rate": "3",
            "upfront_fee": "50000",
            "min_tenure": 60,
            "tenure": 270,
            "tenure_interval": 30,
            "offer_threshold": "24000",
            "max_loan_amount": 1200000,
            "min_loan_amount": "500000"
        }

        GrabLoanOfferFactory(
            grab_customer_data=self.grab_customer_data,
            program_id="ID-DAX-CL-9-MONTHS",
            interest_value=3,
            fee_value=50000,
            min_tenure=60,
            tenure=270,
            tenure_interval=30,
            weekly_installment_amount=24000,
            min_loan_amount=500000,
            max_loan_amount=1200000
        )

        responses = GrabLoanService().get_payment_plans(
            self.token,
            self.mobile_phone,
            payload.get("program_id"),
            payload.get("loan_amount"),
            payload.get("interest_rate"),
            payload.get("upfront_fee"),
            payload.get("min_tenure"),
            payload.get("tenure"),
            payload.get("tenure_interval"),
            payload.get("offer_threshold"),
            payload.get("min_loan_amount"),
            payload.get("max_loan_amount"))

        expected_result = [
            {
                'tenure': 270,
                'daily_repayment': 3293,
                'repayment_amount': 889000,
                'loan_disbursement_amount': 650000,
                'weekly_instalment_amount': 18148.14814814815,
                'loan_amount': 700000,
                'smaller_loan_option_flag': False
            },
            {
                'tenure': 240,
                'daily_repayment': 3359,
                'repayment_amount': 806000,
                'loan_disbursement_amount': 600000,
                'weekly_instalment_amount': 18958.333333333336,
                'loan_amount': 650000,
                'smaller_loan_option_flag': False
            },
            {
                'tenure': 210,
                'daily_repayment': 3170,
                'repayment_amount': 665500,
                'loan_disbursement_amount': 500000,
                'weekly_instalment_amount': 18333.333333333336,
                'loan_amount': 550000,
                'smaller_loan_option_flag': False
            },
            {
                'tenure': 180,
                'daily_repayment': 3278,
                'repayment_amount': 590000,
                'loan_disbursement_amount': 450000,
                'weekly_instalment_amount': 19444.444444444445,
                'loan_amount': 500000,
                'smaller_loan_option_flag': False
            }
        ]

        self.assertEqual(responses, expected_result)

    def test_get_payment_plans_3(self):
        payload = {
            "program_id": "DAX_ID_CL02",
            "loan_amount": 9900000,
            "phone_number": "6281229969301",
            "interest_rate": "4",
            "upfront_fee": "20000",
            "min_tenure": 30,
            "tenure": 180,
            "tenure_interval": 30,
            "offer_threshold": "385000",
            "max_loan_amount": 9900000,
            "min_loan_amount": "500000"
        }

        GrabLoanOfferFactory(
            grab_customer_data=self.grab_customer_data,
            program_id="DAX_ID_CL02",
            interest_value=4,
            fee_value=20000,
            min_tenure=30,
            tenure=180,
            tenure_interval=30,
            weekly_installment_amount=385000,
            min_loan_amount=500000,
            max_loan_amount=9900000
        )

        responses = GrabLoanService().get_payment_plans(
            self.token,
            self.mobile_phone,
            payload.get("program_id"),
            payload.get("loan_amount"),
            payload.get("interest_rate"),
            payload.get("upfront_fee"),
            payload.get("min_tenure"),
            payload.get("tenure"),
            payload.get("tenure_interval"),
            payload.get("offer_threshold"),
            payload.get("min_loan_amount"),
            payload.get("max_loan_amount"))

        expected_result = [
            {
                'tenure': 180,
                'daily_repayment': 54767,
                'repayment_amount': 9858000,
                'loan_disbursement_amount': 7930000,
                'weekly_instalment_amount': 309166.6666666666,
                'loan_amount': 7950000,
                'smaller_loan_option_flag': False
            },
            {
                'tenure': 180,
                'daily_repayment': 37338,
                'repayment_amount': 6720840,
                'loan_disbursement_amount': 5400000,
                'weekly_instalment_amount': 210777.77777777775,
                'loan_amount': 5420000,
                'smaller_loan_option_flag': True
            },
            {
                'tenure': 180,
                'daily_repayment': 24112,
                'repayment_amount': 4340160,
                'loan_disbursement_amount': 3480000,
                'weekly_instalment_amount': 136111.11111111112,
                'loan_amount': 3500000,
                'smaller_loan_option_flag': True
            },
            {
                'tenure': 180,
                'daily_repayment': 50565,
                'repayment_amount': 9101700,
                'loan_disbursement_amount': 7320000,
                'weekly_instalment_amount': 285444.4444444445,
                'loan_amount': 7340000,
                'smaller_loan_option_flag': True
            },
            {
                'tenure': 150,
                'daily_repayment': 54800,
                'repayment_amount': 8220000,
                'loan_disbursement_amount': 6830000,
                'weekly_instalment_amount': 319666.6666666666,
                'loan_amount': 6850000,
                'smaller_loan_option_flag': False
            },
            {
                'tenure': 120,
                'daily_repayment': 54617,
                'repayment_amount': 6554000,
                'loan_disbursement_amount': 5630000,
                'weekly_instalment_amount': 329583.3333333334,
                'loan_amount': 5650000,
                'smaller_loan_option_flag': False
            },
            {
                'tenure': 90,
                'daily_repayment': 54756,
                'repayment_amount': 4928000,
                'loan_disbursement_amount': 4380000,
                'weekly_instalment_amount': 342222.22222222225,
                'loan_amount': 4400000,
                'smaller_loan_option_flag': False
            },
            {
                'tenure': 60,
                'daily_repayment': 54900,
                'repayment_amount': 3294000,
                'loan_disbursement_amount': 3030000,
                'weekly_instalment_amount': 355833.3333333334,
                'loan_amount': 3050000,
                'smaller_loan_option_flag': False
            },
            {
                'tenure': 30,
                'daily_repayment': 53734,
                'repayment_amount': 1612000,
                'loan_disbursement_amount': 1530000,
                'weekly_instalment_amount': 361666.6666666666,
                'loan_amount': 1550000,
                'smaller_loan_option_flag': False
            }
        ]

        for response in responses:
            self.assertTrue(response in expected_result)

    def test_invalid_tenure_get_payment_plans(self):
        payload = {
            "program_id": "ID-DAX-CL-9-MONTHS",
            "loan_amount": 1200000,
            "phone_number": "6281229969301",
            "interest_rate": "3",
            "upfront_fee": "50000",
            "min_tenure": 60,
            "tenure": 270,
            "tenure_interval": 30,
            "offer_threshold": "24000",
            "max_loan_amount": 1200000,
            "min_loan_amount": "500000"
        }

        GrabLoanOfferFactory(
            grab_customer_data=self.grab_customer_data,
            program_id="ID-DAX-CL-9-MONTHS",
            interest_value=3,
            fee_value=50000,
            min_tenure=60,
            tenure=270,
            tenure_interval=30,
            weekly_installment_amount=24000,
            min_loan_amount=500000,
            max_loan_amount=1200000
        )

        with self.assertRaises(GrabLogicException) as context:
            GrabLoanService().get_payment_plans(
                self.token,
                self.mobile_phone,
                payload.get("program_id"),
                payload.get("loan_amount"),
                payload.get("interest_rate"),
                payload.get("upfront_fee"),
                payload.get("min_tenure"),
                10,
                payload.get("tenure_interval"),
                payload.get("offer_threshold"),
                payload.get("min_loan_amount"),
                payload.get("max_loan_amount"))

    def test_choose_payment_plan(self):
        GrabLoanOfferFactory(
            grab_customer_data=self.grab_customer_data,
            program_id="ID-DAX-CL-9-MONTHS",
            interest_type="SIMPLE_INTEREST",
            interest_value=3,
            fee_type="FLAT",
            fee_value=50000,
            min_tenure=60,
            tenure=270,
            tenure_interval=30,
            weekly_installment_amount=24000,
            min_loan_amount=500000,
            max_loan_amount=1200000,
            penalty_type="FLAT",
            penalty_value=4000
        )

        loan_offer = GrabLoanOffer.objects.last()
        payment_plan_response = GrabLoanService().get_payment_plans(
            self.token,
            self.mobile_phone,
            loan_offer.program_id,
            loan_offer.max_loan_amount,
            loan_offer.interest_value,
            loan_offer.fee_value,
            loan_offer.min_tenure,
            loan_offer.tenure,
            loan_offer.tenure_interval,
            loan_offer.weekly_installment_amount,
            loan_offer.min_loan_amount,
            loan_offer.max_loan_amount,
        )

        GrabLoanService().record_payment_plans(
            grab_customer_data_id=self.grab_customer_data.id,
            program_id=loan_offer.program_id,
            payment_plans=payment_plan_response,
        )

        data = {
            'phone_number': self.mobile_phone,
            'program_id': loan_offer.program_id,
            'max_loan_amount': loan_offer.max_loan_amount,
            'min_loan_amount': loan_offer.min_loan_amount,
            'frequency_type': 'DAILY',
            'loan_disbursement_amount': 550000,
            'penalty_type': 'FLAT',
            'penalty_value': 40000,
            'amount_plan': 600000,
            'tenure_plan': 180,
            'interest_type_plan': 'SIMPLE_INTEREST',
            'interest_value_plan': 4.0,
            'instalment_amount_plan': 3933,
            'fee_type_plan': 'FLAT',
            'fee_value_plan': 40000.0,
            'total_repayment_amount_plan': 590000,
            'weekly_installment_amount': 1000000,
            'smaller_loan_option_flag': False,
            'promo_code': 'test'
        }
        response = GrabLoanService().choose_payment_plan(self.token, data)
        self.assertIsNotNone(response)
        self.assertDictEqual(response, {"is_payment_plan_set": True})

    def test_choose_payment_plans_2(self):
        # now the choose payment should be based on program_id and tenure
        loan_offer = GrabLoanOfferFactory(
            grab_customer_data=self.grab_customer_data,
            program_id="ID-DAX-CL-9-MONTHS",
            interest_type="SIMPLE_INTEREST",
            interest_value=3,
            fee_type="FLAT",
            fee_value=50000,
            min_tenure=60,
            tenure=270,
            tenure_interval=30,
            weekly_installment_amount=24000,
            min_loan_amount=500000,
            max_loan_amount=1200000,
            penalty_type="FLAT",
            penalty_value=4000
        )

        payment_plan_response = GrabLoanService().get_payment_plans(
            self.token,
            self.mobile_phone,
            loan_offer.program_id,
            loan_offer.max_loan_amount,
            loan_offer.interest_value,
            loan_offer.fee_value,
            loan_offer.min_tenure,
            loan_offer.tenure,
            loan_offer.tenure_interval,
            loan_offer.weekly_installment_amount,
            loan_offer.min_loan_amount,
            loan_offer.max_loan_amount,
        )

        GrabLoanService().record_payment_plans(
            grab_customer_data_id=self.grab_customer_data.id,
            program_id=loan_offer.program_id,
            payment_plans=payment_plan_response,
        )

        data = {
            'phone_number': self.mobile_phone,
            'program_id': loan_offer.program_id,
            'max_loan_amount': loan_offer.max_loan_amount,
            'min_loan_amount': loan_offer.min_loan_amount,
            'frequency_type': 'DAILY',
            'loan_disbursement_amount': '550000',
            'penalty_type': 'FLAT',
            'penalty_value': 40000,
            'amount_plan': 600000,
            'tenure_plan': 180,
            'interest_type_plan': 'SIMPLE_INTEREST',
            'interest_value_plan': 4.0,
            'instalment_amount_plan': 3933,
            'fee_type_plan': 'FLAT',
            'fee_value_plan': 40000.0,
            'total_repayment_amount_plan': 590000,
            'weekly_installment_amount': 1000000,
            'smaller_loan_option_flag': False,
            'promo_code': 'test'
        }

        response = GrabLoanService().choose_payment_plan(self.token, data)
        self.assertIsNotNone(response)
        self.assertDictEqual(response, {"is_payment_plan_set": True})

        loan_inquiry = GrabLoanInquiry.objects.get(
            grab_customer_data_id=self.grab_customer_data.id,
            program_id=data.get("program_id")
        )

        self.assertEqual(
            loan_inquiry.total_repayment_amount_plan,
            590000.0
        )

    @mock.patch("juloserver.grab.services.services.process_update_grab_experiment_by_grab_customer_data")
    def test_choose_payment_plans_3(self, mock_update_grab_experiment):
        GrabLoanOfferFactory(
            grab_customer_data=self.grab_customer_data,
            program_id="DAX_ID_CL02",
            interest_value=4,
            fee_value=20000,
            min_tenure=30,
            tenure=180,
            tenure_interval=30,
            weekly_installment_amount=385000,
            min_loan_amount=500000,
            max_loan_amount=9900000,
            penalty_type= "FLAT",
            penalty_value=2000000,
            interest_type="SIMPLE_INTEREST",
            fee_type="FLAT"
        )

        loan_offer = GrabLoanOffer.objects.last()
        payment_plan_response = GrabLoanService().get_payment_plans(
            self.token,
            self.mobile_phone,
            loan_offer.program_id,
            loan_offer.max_loan_amount,
            loan_offer.interest_value,
            loan_offer.fee_value,
            loan_offer.min_tenure,
            loan_offer.tenure,
            loan_offer.tenure_interval,
            loan_offer.weekly_installment_amount,
            loan_offer.min_loan_amount,
            loan_offer.max_loan_amount,
        )

        GrabLoanService().record_payment_plans(
            grab_customer_data_id=self.grab_customer_data.id,
            program_id=loan_offer.program_id,
            payment_plans=payment_plan_response,
        )

        data = {
            "phone_number": self.mobile_phone,
            "program_id": "DAX_ID_CL02",
            "max_loan_amount": 9900000,
            "min_loan_amount": 500000,
            "frequency_type": "DAILY",
            "penalty_type": "FLAT",
            "penalty_value": "2000000",
            "amount_plan": 5420000,
            "tenure_plan": 180,
            "interest_type_plan": "SIMPLE_INTEREST",
            "interest_value_plan": "4",
            "instalment_amount_plan": 37337,
            "fee_type_plan": "FLAT",
            "fee_value_plan": "20000",
            "total_repayment_amount_plan": 9858000,
            "loan_disbursement_amount": 5400000,
            "weekly_installment_amount": 210777.77777777775,
            "smaller_loan_option_flag": True,
            'promo_code': 'test'
        }

        response = GrabLoanService().choose_payment_plan(self.token, data)
        mock_update_grab_experiment.assert_called()
        grab_loan_inquiry = GrabLoanInquiry.objects.get(grab_customer_data=self.grab_customer_data)
        grab_loan_data = GrabLoanData.objects.get(grab_loan_inquiry=grab_loan_inquiry)
        self.assertEqual(grab_loan_data.selected_amount, data.get("amount_plan"))
        self.assertEqual(grab_loan_data.selected_instalment_amount,
                         data.get("instalment_amount_plan"))

    def test_add_grab_loan_promo_code(self):
        self.promo_code = GrabPromoCodeFactory(
            promo_code=111111,
            title="test",
            active_date='2024-01-04',
            expire_date=timezone.localtime(timezone.now()).date()
        )
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer
        )
        grab_loan_inquiry = GrabLoanInquiryFactory(grab_customer_data=self.grab_customer_data)
        self.grab_loan_data = GrabLoanDataFactory(grab_loan_inquiry=grab_loan_inquiry)
        add_grab_loan_promo_code(66666, self.grab_loan_data.id)
        self.assertFalse(GrabLoanPromoCode.objects.filter(promo_code=self.promo_code,
                                                          grab_loan_data_id=self.grab_loan_data.id).exists())

        add_grab_loan_promo_code(self.promo_code.promo_code, self.grab_loan_data.id)
        self.assertTrue(GrabLoanPromoCode.objects.filter(promo_code=self.promo_code,
                                                         grab_loan_data_id=self.grab_loan_data.id).exists())

    def test_get_grab_registeration_reapply_status(self):
        response = GrabApplicationService.get_grab_registeration_reapply_status(self.customer)
        self.assertDictEqual(response, {
            "j1_loan_selected": False,
            "grab_customer_exist": True,
            "grab_customer_token": self.token
        })

        grab_loan_inquiry = GrabLoanInquiryFactory(grab_customer_data=self.grab_customer_data)
        response = GrabApplicationService.get_grab_registeration_reapply_status(self.customer)
        self.assertDictEqual(response, {
            "j1_loan_selected": False,
            "grab_customer_exist": True,
            "grab_customer_token": self.token
        })

        GrabLoanDataFactory(grab_loan_inquiry=grab_loan_inquiry)
        response = GrabApplicationService.get_grab_registeration_reapply_status(self.customer)
        self.assertDictEqual(response, {
            "j1_loan_selected": True,
            "grab_customer_exist": True,
            "grab_customer_token": self.token
        })

    def test_rejected_grab_registeration_reapply_status(self):
        """
        first registration :
        - redirect register -> input phone exist -> validation -> redirect login
        reapply j1 :
        - login -> reaply -> input phone exist -> validation -> login
        """
        new_token = '906d4e43a3446cecb4841cf41c10c91c9610c8a5519437c913ab9144b71054f915752a69d' \
                    '0220619666ac3fc1f27f7b4934a6a4b2baa2f85b6533c663ca6d98f976328625f756e79a7cc' \
                    '543770b6945c1a5aaafd066ceed10204bf85c07c2fae81118d990d7c5fafcb98f8708f540d6d' \
                    '8971764c12b9fb912c7d1c3b1db1f932'
        new_hashed_phone_number = '7358b08205b13f3ec8967ea7f1c331a40cefdeda0cef8bf8b9ca7acefd9564a2'
        new_customer = CustomerFactory(phone=self.mobile_phone)

        """
        grab customer data exist is False and need to login instead
        even customer are using the same phone
        """
        response = GrabApplicationService.get_grab_registeration_reapply_status(new_customer)
        self.assertDictEqual(response, {
            "j1_loan_selected": False,
            "grab_customer_exist": False,
            "grab_customer_token": None
        })

        # let say the customer have grab customer data when reapply
        self.grab_customer_data = GrabCustomerDataFactory(
            phone_number=new_customer.phone,
            customer=new_customer,
            grab_validation_status=True,
            otp_status='VERIFIED',
            token=new_token,
            hashed_phone_number=new_hashed_phone_number
        )
        response = GrabApplicationService.get_grab_registeration_reapply_status(new_customer)
        self.assertDictEqual(response, {
            "j1_loan_selected": False,
            "grab_customer_exist": True,
            "grab_customer_token": new_token
        })

    def test_application_status_check(self):
        response = GrabAPIService.application_status_check(self.customer)
        self.assertIsNotNone(response)

    def test_application_status_check_131_success(self):
        status_131 = StatusLookupFactory(status_code=131)
        self.customer_131 = CustomerFactory()
        self.grab_customer_data_131 = GrabCustomerDataFactory(
            customer=self.customer_131)
        self.application_131 = ApplicationFactory(
            application_status=status_131, customer=self.customer_131)
        self.application_history_status_131 = ApplicationHistoryFactory(
            application_id=self.application_131.id,
            status_new=131,
            status_old=124,
            change_reason='KTP blurry'
        )
        self.application_131.application_status = status_131
        self.application_131.save()
        response = GrabAPIService.application_status_check(self.customer_131)
        self.assertEqual(response["document_resubmission_image_list"], [
            {
                "image_type": "ktp_self",
                "text": "KTP"
            }
        ])
        self.assertEqual(response["document_resubmission_message"],
                         "Upload ulang KTP. Pastikan foto Dokumen dan Selfie terlihat jelas.")

        self.application_history_status_131.change_reason = "KTP blurry"
        self.application_history_status_131.save()

        response = GrabAPIService.application_status_check(self.customer_131)
        self.assertEqual(response["document_resubmission_image_list"], [
            {
                "image_type": "ktp_self",
                "text": "KTP"
            }
        ])
        self.assertEqual(response["document_resubmission_message"],
                         "Upload ulang KTP. Pastikan foto Dokumen dan Selfie terlihat jelas.")

        self.application_history_status_131.change_reason = "SIM needed"
        self.application_history_status_131.save()

        response = GrabAPIService.application_status_check(self.customer_131)
        self.assertEqual(response["document_resubmission_image_list"], [
            {
                "image_type": "drivers_license_ops",
                "text": "SIM"
            }
        ])
        self.assertEqual(response["document_resubmission_message"],
                         "Upload ulang SIM. Pastikan foto Dokumen dan Selfie terlihat jelas.")

        self.application_history_status_131.change_reason = "NPWP needed"
        self.application_history_status_131.save()

        response = GrabAPIService.application_status_check(self.customer_131)
        self.assertEqual(response["document_resubmission_image_list"], [
            {
                "image_type": "Foto NPWP",
                "text": "NPWP"
            }
        ])
        self.assertEqual(response["document_resubmission_message"],
                         "Upload ulang NPWP. Pastikan foto Dokumen dan Selfie terlihat jelas.")

        self.application_history_status_131.change_reason = "NPWP needed, SIM needed"
        self.application_history_status_131.save()

        response = GrabAPIService.application_status_check(self.customer_131)
        self.assertEqual(response["document_resubmission_image_list"], [
            {
                "image_type": "drivers_license_ops",
                "text": "SIM"
            },
            {
                "image_type": "Foto NPWP",
                "text": "NPWP"
            }
        ])
        self.assertEqual(response["document_resubmission_message"],
                         "Upload ulang SIM / NPWP. Pastikan foto Dokumen dan Selfie terlihat jelas.")

        self.application_history_status_131.change_reason = "KTP needed, SIM needed"
        self.application_history_status_131.save()

        response = GrabAPIService.application_status_check(self.customer_131)
        self.assertEqual(response["document_resubmission_image_list"], [
            {
                "image_type": "drivers_license_ops",
                "text": "SIM"
            },
            {
                "image_type": "ktp_self",
                "text": "KTP"
            }
        ])
        self.assertEqual(response["document_resubmission_message"],
                         "Upload ulang SIM / KTP. Pastikan foto Dokumen dan Selfie terlihat jelas.")

        self.application_history_status_131.change_reason = "random"
        self.application_history_status_131.save()

        response = GrabAPIService.application_status_check(self.customer_131)
        self.assertEqual(response["document_resubmission_image_list"], [])
        self.assertEqual(response["document_resubmission_message"],
                         "Mohon cek email Anda untuk mengirim dokumen yang diperlukan.")

    def test_test_application_status_check_131_failed(self):
        self.customer_131 = CustomerFactory()
        self.grab_customer_data_131 = GrabCustomerDataFactory(
            customer=self.customer_131)
        self.application_131 = ApplicationFactory(customer=self.customer_131)
        self.application_131.application_status = StatusLookupFactory(status_code=106)
        self.application_131.save()
        response = GrabAPIService.application_status_check(self.customer_131)
        self.assertNotIn('document_resubmission_image_list', response)
        self.assertNotIn('document_resubmission_message', response)

    def test_validate_data_functions(self):
        email = 'abcd_duplicate@julo.co.id'
        phone = '62814789654789'
        result = validate_email_application(email, self.customer)
        result_email = validate_email(email, self.customer)
        self.assertTrue(result == email)
        self.assertTrue(result_email, email)

        nik = '1601260506021276'
        result = validate_nik(nik)
        self.assertTrue(nik == result)

        result_phone = validate_phone_number(phone)
        self.assertTrue(result_phone == phone)

    def test_get_sphp_context_grab(self):
        result = get_sphp_context_grab(self.loan.id)
        self.assertIsNotNone(result)

    @mock.patch('juloserver.grab.services.services.GrabClient')
    def test_verify_grab_loan_offer(self, mocked_client):
        mocked_client.get_loan_offer.return_value = \
            {
                "msg_id": "7eab2027d4be41ef86a98ff60c542c9d",
                "success": True, "version": "1",
                "data": [
                    {"program_id": "DAX_ID_CL02", "max_loan_amount": "1000000",
                     "min_loan_amount": "500000", "weekly_installment_amount": "1000000",
                     "loan_duration": 180, "min_tenure": 60, "tenure_interval": 30,
                     "frequency_type": "DAILY", "fee_type": "FLAT", "fee_value": "40000",
                     "interest_type": "SIMPLE_INTEREST", "interest_value": "3",
                     "penalty_type": "FLAT", "penalty_value": "2000000"}]}
        response = verify_grab_loan_offer(self.application)
        self.assertTrue(response)

        mocked_client.get_loan_offer.return_value = \
            {
                "msg_id": "7eab2027d4be41ef86a98ff60c542c9d",
                "success": True, "version": "1",
                "data": [
                    {"program_id": "DAX_ID_CL02", "max_loan_amount": "0",
                     "min_loan_amount": "500000", "weekly_installment_amount": "1000000",
                     "loan_duration": 180, "min_tenure": 60, "tenure_interval": 30,
                     "frequency_type": "DAILY", "fee_type": "FLAT", "fee_value": "40000",
                     "interest_type": "SIMPLE_INTEREST", "interest_value": "3",
                     "penalty_type": "FLAT", "penalty_value": "2000000"}]}
        response = verify_grab_loan_offer(self.application)
        self.assertFalse(response)

    @mock.patch('requests.get')
    def test_verify_grab_loan_offer_api_response_failure(self, mocked_client):
        mocked_response = mock.MagicMock()
        mocked_response.status_code = 500
        mocked_client.return_value = mocked_response
        response = verify_grab_loan_offer(self.application)
        self.assertFalse(response)

    @mock.patch('juloserver.grab.services.services.process_application_status_change')
    def test_reapply(self, mocked_status_change):
        grab_loan_inquiry_1 = GrabLoanInquiryFactory(grab_customer_data=self.grab_customer_data)
        self.application.application_status = StatusLookupFactory(status_code=106)
        self.application.save()
        mocked_status_change.return_value = None
        response = GrabAuthService.reapply(self.customer)
        self.assertIsNotNone(response)
        self.assertTrue(response['application']['application_number'] == 2)
        latest_application = self.application.customer.application_set.last()
        self.assertEqual(latest_application.company_name, GrabApplicationConstants.COMPANY_NAME_DEFAULT)
        self.assertEqual(latest_application.job_type, GrabApplicationConstants.JOB_TYPE_DEFAULT)
        self.assertEqual(latest_application.job_industry, GrabApplicationConstants.JOB_INDUSTRY_DEFAULT)
        mocked_status_change.assert_called_once()

    @skip(reason="Flaky")
    @mock.patch('juloserver.grab.services.services.process_application_status_change')
    def test_reapply_application_135(self, mocked_status_change):
        mocked_status_change.return_value = None

        self.grab_loan_inquiry = GrabLoanInquiryFactory(
            grab_customer_data=self.grab_customer_data)
        self.grab_loan_data = GrabLoanDataFactory(
            loan=self.loan,
            grab_loan_inquiry=self.grab_loan_inquiry
        )

        # creating valid app with status 135 and change reason because of bank rejection
        GrabLoanInquiryFactory(grab_customer_data=self.grab_customer_data)
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED)
        self.application.bank_name = '666_bank'
        self.application.bank_account_number = '666'
        self.application.kin_relationship = 'Orang tua'
        self.application.close_kin_mobile_phone = '081260036278'
        self.application.close_kin_name = 'yowman'
        self.application.last_education = 'SLTA'
        self.application.marital_status = 'Lajang'
        self.application.email = 'testingemail@gmail.com'
        self.application.save()
        response = GrabAuthService.reapply(self.customer)
        self.assertIsNotNone(response)
        self.assertTrue(response['application']['application_number'] == 2)
        latest_application = self.application.customer.application_set.last()
        self.assertEqual(latest_application.company_name, GrabApplicationConstants.COMPANY_NAME_DEFAULT)
        self.assertEqual(latest_application.job_type, GrabApplicationConstants.JOB_TYPE_DEFAULT)
        self.assertEqual(latest_application.job_industry, GrabApplicationConstants.JOB_INDUSTRY_DEFAULT)
        mocked_status_change.assert_called_once()

        bank_rejection_reason = GrabApplicationService.get_bank_rejection_reason()
        self.application_history_135 = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_new=135,
            status_old=124,
            change_reason='KTP blurry, {}'.format(bank_rejection_reason.mapping_status)
        )

        # change status code manually for reapply case
        latest_application = self.customer.application_set.last()
        latest_application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        latest_application.save()

        # load form
        application_service = GrabApplicationService()
        latest_application_data =application_service.get_latest_application(self.customer)
        application_service.save_failed_latest_app_to_new_app(self.customer)
        response = application_service.get_application_details_long_form(self.customer, 4)
        # make sure the current step is 4
        self.assertEqual(response.get('current_step'), 4)

        # submit the new app
        serializer = GrabApplicationV2Serializer(data=response, src_customer_id=self.customer.id)
        serializer.is_valid(raise_exception=True)
        resp = application_service.submit_grab_application(
            self.customer,
            serializer.validated_data,
            response,
            2
        )
        self.assertEqual(resp.get('application_id'),
                         latest_application_data.get('latest_application').id)
        self.assertEqual(resp.get('is_grab_application_saved'), True)

        latest_application = latest_application_data.get('latest_application')
        latest_application.refresh_from_db()
        self.assertEqual(latest_application.bank_name, '666_bank')
        self.assertEqual(latest_application.bank_account_number, '666')

    def test_update_customer_phone(self):
        GrabAuthService.update_customer_phone(self.customer, self.grab_customer_data)
        customer = Customer.objects.filter(id=self.customer.id).last()
        self.assertEqual(customer.phone, self.grab_customer_data.phone_number)

        self.customer.phone = '081245789865'
        self.customer.save()
        self.customer.refresh_from_db()
        GrabAuthService.update_customer_phone(self.customer, self.grab_customer_data)
        customer = Customer.objects.filter(id=self.customer.id).last()
        self.assertEqual(customer.phone, self.grab_customer_data.phone_number)

        self.customer.phone = '6281245789867'
        self.customer.save()
        self.customer.refresh_from_db()
        GrabAuthService.update_customer_phone(self.customer, self.grab_customer_data)
        customer = Customer.objects.filter(id=self.customer.id).last()
        self.assertEqual(customer.phone, self.grab_customer_data.phone_number)

    @mock.patch('juloserver.grab.services.services.trigger_application_creation_grab_api.delay')
    def test_register_success(self, mocked_trigger_creation):
        mobile_phone_1 = '6281578954216'
        token_for_gcd = 'token_for_grab_customer_data'
        grab_customer_data = GrabCustomerDataFactory(
            phone_number=mobile_phone_1,
            grab_validation_status=True,
            otp_status='VERIFIED',
            token=token_for_gcd
        )
        nik = '1601260506021294'
        mocked_trigger_creation.return_value = None
        response = GrabAuthService.register(token_for_gcd, nik, mobile_phone_1, '123123')
        self.assertIsNotNone(response['customer_id'])
        mocked_trigger_creation.assert_called()

    @mock.patch('juloserver.grab.services.services.trigger_application_creation_grab_api.delay')
    def test_register_success_j1(self, mocked_trigger_creation):
        mobile_phone_1 = '6281578954220'
        customer_j1 = CustomerFactory()
        application_j1 = ApplicationFactory(
            customer=customer_j1,
        )
        application_j1.workflow = WorkflowFactory(name='JuloOneWorkflow')
        application_j1.application_status = StatusLookupFactory(status_code=106)
        application_j1.save()
        token_for_gcd = 'token_for_grab_customer_data1'
        grab_customer_data = GrabCustomerDataFactory(
            phone_number=mobile_phone_1,
            grab_validation_status=True,
            otp_status='VERIFIED',
            token=token_for_gcd
        )
        nik = '1601260506021295'
        mocked_trigger_creation.return_value = None
        response = GrabAuthService.register(token_for_gcd, nik, mobile_phone_1, '123123')
        self.assertIsNotNone(response['customer_id'])
        mocked_trigger_creation.assert_called()

    def test_get_agreement_summary(self):
        self.grab_loan_inquiry = GrabLoanInquiryFactory(
            grab_customer_data=self.grab_customer_data)
        self.grab_loan_data = GrabLoanDataFactory(
            loan=self.loan,
            grab_loan_inquiry=self.grab_loan_inquiry
        )
        bank_account_category = BankAccountCategoryFactory(
            category='self',
            display_label='Pribadi',
            parent_category_id=1
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False
        )
        self.loan.bank_account_destination = bank_account_destination
        self.loan.save()
        response = GrabLoanService().get_agreement_summary(self.loan.loan_xid)
        self.assertIsNotNone(response)

    def test_get_pre_loan_response(self):
        self.grab_loan_inquiry = GrabLoanInquiryFactory(
            grab_customer_data=self.grab_customer_data)
        self.grab_loan_data = GrabLoanDataFactory(
            loan=self.loan,
            grab_loan_inquiry=self.grab_loan_inquiry
        )
        response = GrabApplicationService.get_pre_loan_response(
            self.customer, self.application)
        self.assertIsNotNone(response)

    def test_get_grab_home_page_data(self):
        self.grab_customer_data.customer = self.customer
        self.grab_customer_data.save()
        self.application.workflow = self.workflow
        self.application.save()
        result = GrabAPIService().get_grab_home_page_data(
            self.hashed_phone_number, 0, 10)
        self.assertIsNotNone(result)

    def test_get_additional_check_for_rejection_grab(self):
        self.application.application_status = StatusLookupFactory(status_code=131)
        self.application.save()
        self.application_history_131 = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_new=131,
            status_old=124,
            change_reason='KTP blurry'
        )
        response = get_additional_check_for_rejection_grab(self.application)
        self.assertIsNotNone(response)

        self.application.application_status = StatusLookupFactory(status_code=135)
        self.application.save()
        self.application_history_135 = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_new=135,
            status_old=121,
            change_reason='application_date_of_birth'
        )
        response = get_additional_check_for_rejection_grab(self.application)
        self.assertIsNotNone(response)

    def test_validate_loan_request(self):
        self.grab_loan_inquiry = GrabLoanInquiryFactory(grab_customer_data=self.grab_customer_data)
        self.grab_loan_data = GrabLoanDataFactory(
            loan=self.loan, grab_loan_inquiry=self.grab_loan_inquiry
        )
        GrabAPILogFactory(
            customer_id=self.customer.id,
            loan_id=self.loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=200,
        )
        self.loan.loan_status = StatusLookupFactory(status_code=220)
        self.loan.save()
        with self.assertRaises(GrabLogicException) as context:
            validate_loan_request(self.customer)

        GrabAPILogFactory(
            customer_id=self.customer.id,
            loan_id=self.loan.id,
            query_params=GrabPaths.DISBURSAL_CREATION,
            http_status_code=200,
        )
        response = validate_loan_request(self.customer)
        self.assertIsNone(response)


    @mock.patch('juloserver.grab.services.services.update_loan_status_for_grab_invalid_bank_account')
    @mock.patch('juloserver.grab.services.services.GrabClient.get_pre_disbursal_check')
    def test_get_bank_check_data(self, mocked_client, mocked_cancel_loan):
        self.bank.bank_name = 'bank_name'
        self.bank.save()
        mocked_value = mock.MagicMock()
        mocked_cancel_loan.return_value = None
        mocked_value.content = json.dumps({
            "msg_id": "30a4c02637674cde8477d1f832a7386f", "version": "1.0",
            "success": True, "error": {"error_code": 0, "dev_message": ""},
            "data": {"msg_id": "30a4c02637674cde8477d1f832a7386f", "code": False,
                     "reason": None}
        })
        mocked_client.return_value = mocked_value
        response = GrabCommonService.get_bank_check_data(
            self.customer, 'bank_name', '123456789', self.application.id)
        mocked_client.assert_called()
        self.assertIsNone(response)
        mocked_cancel_loan.assert_called()

    def test_get_pre_loan_detail(self):
        fee_value = 40000
        self.grab_loan_inquiry = GrabLoanInquiryFactory(
            grab_customer_data=self.grab_customer_data,
            loan_disbursement_amount=self.loan.loan_amount - fee_value,
        )
        self.grab_loan_data = GrabLoanDataFactory(
            loan=self.loan,
            grab_loan_inquiry=self.grab_loan_inquiry
        )
        GrabLoanOfferFactory(
            grab_customer_data=self.grab_customer_data,
            program_id=self.grab_loan_data.program_id,
            interest_value=3,
            fee_value=fee_value,
            min_tenure=60,
            tenure=180,
            tenure_interval=30,
            weekly_installment_amount=1000000,
            min_loan_amount=500000,
            max_loan_amount=1000000,
        )
        response = GrabLoanService().get_pre_loan_detail(self.customer)
        self.assertIsNotNone(response)
        self.assertEqual(
            response.get('loan_offer'),
            {
                'tenure': 180,
                'program_id': 'TEST_PROGRAM_ID',
                'max_loan_amount': 1000000.0,
                'min_loan_amount': 500000.0,
                'phone_number': '6281245789865',
                'interest_value': 3.0,
                'weekly_installment_amount': 1000000.0,
                'min_tenure': 60,
                'tenure_interval': 30,
                'loan_disbursement_amount': 960000.0,
            },
        )

    def test_get_pre_loan_detail_with_missing_grab_loan_offer(self):
        self.grab_loan_inquiry = GrabLoanInquiryFactory(grab_customer_data=self.grab_customer_data)
        self.grab_loan_data = GrabLoanDataFactory(
            loan=self.loan, grab_loan_inquiry=self.grab_loan_inquiry
        )
        response = GrabLoanService().get_pre_loan_detail(self.customer)
        self.assertIsNotNone(response)
        self.assertEqual(
            response.get('loan_offer'),
            {},
        )

    def test_get_pre_loan_detail_without_bank_detail(self):
        self.grab_loan_inquiry = GrabLoanInquiryFactory(grab_customer_data=self.grab_customer_data)
        self.grab_loan_data = GrabLoanDataFactory(
            loan=self.loan, grab_loan_inquiry=self.grab_loan_inquiry
        )
        GrabLoanOfferFactory(
            grab_customer_data=self.grab_customer_data,
            program_id=self.grab_loan_data.program_id,
            interest_value=3,
            fee_value=40000,
            min_tenure=60,
            tenure=180,
            tenure_interval=30,
            weekly_installment_amount=1000000,
            min_loan_amount=500000,
            max_loan_amount=1000000,
        )

        # remove bank details
        self.application.update_safely(bank_name=None, name_in_bank=None)

        response = GrabLoanService().get_pre_loan_detail(self.customer)
        self.assertIsNotNone(response)
        self.assertEqual(
            response.get('loan_offer'),
            {
                'tenure': 180,
                'program_id': 'TEST_PROGRAM_ID',
                'max_loan_amount': 1000000.0,
                'min_loan_amount': 500000.0,
                'phone_number': '6281245789865',
                'interest_value': 3.0,
                'weekly_installment_amount': 1000000.0,
                'min_tenure': 60,
                'tenure_interval': 30,
                'loan_disbursement_amount': 960000.0,
            },
        )
        self.assertIsNone(response.get('loan').get('disbursed_to'))

    def test_get_application_review(self):
        response = GrabApplicationService.get_application_review(self.customer)
        self.assertIsNotNone(response)

    @mock.patch('juloserver.grab.services.services.GrabClient.get_pre_disbursal_check')
    def test_loan_apply(self, mocked_client):
        program_id = 'PROGRAM_ID'
        self.grab_loan_inquiry = GrabLoanInquiryFactory(
            grab_customer_data=self.grab_customer_data,
            max_loan_amount=5000000,
            min_loan_amount=300000,
            program_id=program_id,
            interest_value=4.0,
            fee_value=40000
        )
        self.grab_loan_data = GrabLoanDataFactory(
            selected_amount=1000000,
            grab_loan_inquiry=self.grab_loan_inquiry,
            loan=None
        )
        self.grab_grab_api_log = GrabAPILogFactory(
            application_id=self.application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200,
            customer_id=self.customer.id
        )
        self.account_limit.available_limit = 5000000
        self.account_limit.save()
        self.product_lookup.admin_fee = 40000
        self.product_lookup.interest_rate = 0.04
        self.product_lookup.save()
        self.loan.loan_status = StatusLookupFactory(status_code=216)
        self.loan.save()
        bank_account_category = BankAccountCategoryFactory(
            category='self',
            display_label='Pribadi',
            parent_category_id=1
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False
        )
        mocked_value = mock.MagicMock()
        mocked_value.content = json.dumps({
            "msg_id": "30a4c02637674cde8477d1f832a7386f", "version": "1.0",
            "success": True, "error": {"error_code": 0, "dev_message": ""},
            "data": {"msg_id": "30a4c02637674cde8477d1f832a7386f", "code": False,
                     "reason": None}
        })

        GrabLoanOfferFactory(
            grab_customer_data=self.grab_customer_data,
            program_id=program_id,
            interest_type="SIMPLE_INTEREST",
            interest_value=4,
            fee_type='FLAT',
            fee_value=50000,
            min_tenure=60,
            tenure=180,
            tenure_interval=30,
            weekly_installment_amount=223000,
            min_loan_amount=500000,
            max_loan_amount=10000000,
            penalty_type='FLAT',
            penalty_value=40000
        )
        mocked_client.return_value = mocked_value
        response = GrabLoanService().apply(self.customer, self.customer.user, program_id,
                                         1000000, 180)
        loan = response.get('loan')
        self.assertIsNotNone(response)

        self.grab_loan_data.refresh_from_db()
        self.assertIsNotNone(self.grab_loan_data.loan, loan)

        installment_amount = round_rupiah_grab(
            math.floor(
                (old_div(loan.loan_amount, loan.loan_duration))
                + old_div((self.grab_loan_inquiry.interest_value * loan.loan_amount), 30)
            )
        )
        self.assertEqual(response.get('installment_amount'), installment_amount)
        self.assertEqual(response.get('monthly_interest'), self.grab_loan_inquiry.interest_value)

    @mock.patch('juloserver.grab.services.services.GrabClient.get_pre_disbursal_check')
    def test_loan_apply_multiple_bank_account_destination(self, mocked_client):
        program_id = 'PROGRAM_ID'
        self.grab_loan_inquiry = GrabLoanInquiryFactory(
            grab_customer_data=self.grab_customer_data,
            max_loan_amount=5000000,
            min_loan_amount=300000,
            program_id=program_id,
            interest_value=4.0,
            fee_value=40000
        )
        self.grab_loan_data = GrabLoanDataFactory(
            selected_amount=1000000,
            grab_loan_inquiry=self.grab_loan_inquiry,
            loan=None
        )
        self.grab_grab_api_log = GrabAPILogFactory(
            application_id=self.application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200,
            customer_id=self.customer.id
        )
        self.account_limit.available_limit = 5000000
        self.account_limit.save()
        self.product_lookup.admin_fee = 40000
        self.product_lookup.interest_rate = 0.04
        self.product_lookup.save()
        self.loan.loan_status = StatusLookupFactory(status_code=216)
        self.loan.save()
        bank_account_category = BankAccountCategoryFactory(
            category='self',
            display_label='Pribadi',
            parent_category_id=1
        )

        last_account_number = None
        for i in range(5):
                account_number = random.randint(100, 200)
                last_account_number = account_number
                BankAccountDestinationFactory(
                bank_account_category=bank_account_category,
                customer=self.customer,
                bank=self.bank,
                name_bank_validation=self.name_bank_validation,
                account_number=account_number,
                is_deleted=False
            )
        mocked_value = mock.MagicMock()
        mocked_value.content = json.dumps({
            "msg_id": "30a4c02637674cde8477d1f832a7386f", "version": "1.0",
            "success": True, "error": {"error_code": 0, "dev_message": ""},
            "data": {"msg_id": "30a4c02637674cde8477d1f832a7386f", "code": False,
                     "reason": None}
        })

        GrabLoanOfferFactory(
            grab_customer_data=self.grab_customer_data,
            program_id=program_id,
            interest_type="SIMPLE_INTEREST",
            interest_value=4,
            fee_type='FLAT',
            fee_value=50000,
            min_tenure=60,
            tenure=180,
            tenure_interval=30,
            weekly_installment_amount=223000,
            min_loan_amount=500000,
            max_loan_amount=10000000,
            penalty_type='FLAT',
            penalty_value=40000
        )
        mocked_client.return_value = mocked_value
        response = GrabLoanService().apply(self.customer, self.customer.user, program_id,
                                         1000000, 180)
        self.assertIsNotNone(response)

        self.assertEqual(
            int(response.get('loan').bank_account_destination.account_number),
            last_account_number
        )

    @mock.patch('juloserver.grab.services.services.GrabClient.get_pre_disbursal_check')
    def test_loan_apply_application_data_missing(self, mocked_client):
        mobile_phone = '628454984524'
        customer = CustomerFactory(phone=mobile_phone)
        account = AccountFactory(
            account_lookup=self.account_lookup,
            customer=customer
        )
        application = ApplicationFactory(
            customer=customer,
            account=account,
            product_line=self.product_line,
            application_status=self.application_status_code,
            mobile_phone_1=mobile_phone,
            bank_name='bank_test',
            name_in_bank='name_in_bank'
        )
        account_limit = AccountLimitFactory(account=account)
        grab_customer_data = GrabCustomerDataFactory(
            phone_number=mobile_phone,
            customer=customer,
            grab_validation_status=True,
            otp_status='VERIFIED',
            hashed_phone_number="hashed_phone_number_test1"
        )
        grab_loan_inquiry = GrabLoanInquiryFactory(
            grab_customer_data=grab_customer_data,
            max_loan_amount=5000000,
            min_loan_amount=300000,
            program_id='PROGRAM_ID',
            interest_value=4.0,
            fee_value=40000
        )
        grab_loan_data = GrabLoanDataFactory(
            selected_amount=1000000,
            grab_loan_inquiry=grab_loan_inquiry,
            loan=None
        )
        account_limit.available_limit = 5000000
        account_limit.save()
        name_bank_validation = NameBankValidationFactory(bank_code='TESTBANK')
        bank_account_category = BankAccountCategoryFactory(
            category='self',
            display_label='Pribadi',
            parent_category_id=1
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=customer,
            bank=self.bank,
            name_bank_validation=name_bank_validation,
            account_number='12211221122',
            is_deleted=False
        )
        self.product_lookup.admin_fee = 40000
        self.product_lookup.interest_rate = 0.04
        self.product_lookup.save()
        mocked_value = mock.MagicMock()
        mocked_value.content = json.dumps({
            "msg_id": "30a4c02637674cde8477d1f832a7386f", "version": "1.0",
            "success": True, "error": {"error_code": 0, "dev_message": ""},
            "data": {"msg_id": "30a4c02637674cde8477d1f832a7386f", "code": False,
                     "reason": None}
        })
        mocked_client.return_value = mocked_value
        with self.assertRaises(GrabLogicException):
            response = GrabLoanService().apply(customer, customer.user, 'PROGRAM_ID',
                                             1000000, 180)

    @mock.patch('juloserver.grab.services.services.GrabClient.get_pre_disbursal_check')
    def test_failed_loan_apply_invalid_tenure(self, mocked_client):
        program_id = 'PROGRAM_ID'
        self.grab_loan_inquiry = GrabLoanInquiryFactory(
            grab_customer_data=self.grab_customer_data,
            max_loan_amount=5000000,
            min_loan_amount=300000,
            program_id=program_id,
            interest_value=4.0,
            fee_value=40000
        )
        self.grab_loan_data = GrabLoanDataFactory(
            selected_amount=1000000,
            grab_loan_inquiry=self.grab_loan_inquiry,
            loan=None
        )
        self.grab_grab_api_log = GrabAPILogFactory(
            application_id=self.application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200,
            customer_id=self.customer.id
        )
        self.account_limit.available_limit = 5000000
        self.account_limit.save()
        self.product_lookup.admin_fee = 40000
        self.product_lookup.interest_rate = 0.04
        self.product_lookup.save()
        self.loan.loan_status = StatusLookupFactory(status_code=216)
        self.loan.save()
        bank_account_category = BankAccountCategoryFactory(
            category='self',
            display_label='Pribadi',
            parent_category_id=1
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False
        )
        mocked_value = mock.MagicMock()
        mocked_value.content = json.dumps({
            "msg_id": "30a4c02637674cde8477d1f832a7386f", "version": "1.0",
            "success": True, "error": {"error_code": 0, "dev_message": ""},
            "data": {"msg_id": "30a4c02637674cde8477d1f832a7386f", "code": False,
                     "reason": None}
        })

        GrabLoanOfferFactory(
            grab_customer_data=self.grab_customer_data,
            program_id=program_id,
            interest_type="SIMPLE_INTEREST",
            interest_value=4,
            fee_type='FLAT',
            fee_value=50000,
            min_tenure=60,
            tenure=180,
            tenure_interval=30,
            weekly_installment_amount=223000,
            min_loan_amount=500000,
            max_loan_amount=10000000,
            penalty_type='FLAT',
            penalty_value=40000
        )
        mocked_client.return_value = mocked_value
        with self.assertRaises(GrabLogicException):
            GrabLoanService().apply(
                self.customer,
                self.customer.user,
                program_id,
                1000000,
                2000
            )

    @mock.patch('juloserver.grab.services.services.GrabClient.get_loan_offer')
    def test_check_grab_reapply_eligibility(self, mocked_client):
        mocked_value = {
            "msg_id": "980c46a8299a4db391c85535d3145ab3", "success": True,
            "version": "1", "data": [
                {
                    "program_id": "DAX_ID_CL02", "max_loan_amount": "1000000",
                    "min_loan_amount": "500000", "weekly_installment_amount": "1000000",
                    "loan_duration": 180, "min_tenure": 60, "tenure_interval": 30,
                    "frequency_type": "DAILY", "fee_type": "FLAT", "fee_value": "40000",
                    "interest_type": "SIMPLE_INTEREST", "interest_value": "3",
                    "penalty_type": "FLAT", "penalty_value": "2000000"}]}
        mocked_client.return_value = mocked_value
        response = check_grab_reapply_eligibility(self.application.id)
        self.assertTrue(response)

    def test_get_loan_transaction_detail(self):
        self.grab_loan_inquiry = GrabLoanInquiryFactory(
            grab_customer_data=self.grab_customer_data)
        self.grab_loan_data = GrabLoanDataFactory(
            loan=self.loan,
            grab_loan_inquiry=self.grab_loan_inquiry
        )
        response = GrabApplicationService.get_pre_loan_response(
            self.customer)
        self.assertIsNotNone(response)

    def test_update_loan_status_for_grab_invalid_bank_account(self) -> None:
        self.loan_1 = LoanFactory(
            account=self.account,
            customer=self.customer,
            name_bank_validation_id=self.name_bank_validation.id,
            product=self.product_lookup,
            loan_status=StatusLookupFactory(status_code=210)
        )
        self.loan_2 = LoanFactory(
            account=self.account,
            customer=self.customer,
            name_bank_validation_id=self.name_bank_validation.id,
            product=self.product_lookup,
            loan_status=StatusLookupFactory(status_code=210)
        )
        update_loan_status_for_grab_invalid_bank_account(self.application.id)
        self.loan_1.refresh_from_db()
        self.loan_2.refresh_from_db()
        self.assertEqual(self.loan_1.loan_status_id, 216)
        self.assertEqual(self.loan_2.loan_status_id, 216)

    def test_success_get_grab_loan_offer_from_redis(self):
        grab_loan_offer_obj = GrabLoanOfferFactory(
            grab_customer_data=self.grab_customer_data,
            program_id="test"
        )
        class MockRedis(mock.Mock):
            def get(key, decode):
                grab_loan_offer_dict = grab_loan_offer_obj.__dict__
                grab_loan_offer_data = {}
                for key, value in grab_loan_offer_dict.items():
                    if key.startswith("_") or key in ['cdate', 'udate']:
                        continue
                    grab_loan_offer_data[key] = value
                return json.dumps(grab_loan_offer_data)

        grab_loan_service = GrabLoanService()
        grab_loan_service.redis_client = MockRedis()
        result = grab_loan_service.get_grab_loan_offer_from_redis(
            grab_loan_offer_obj.grab_customer_data.id,
            grab_loan_offer_obj.program_id
        )
        self.assertTrue(isinstance(result, GrabLoanOffer))

    def test_failed_get_grab_loan_offer_from_redis(self):
        class MockRedis(mock.Mock):
            def get(key, decode):
                return "hello world"

        grab_loan_offer_obj = GrabLoanOfferFactory(grab_customer_data=self.grab_customer_data,
                                                   program_id="test")
        grab_loan_service = GrabLoanService()
        grab_loan_service.redis_client = MockRedis()
        result = grab_loan_service.get_grab_loan_offer_from_redis(
            grab_loan_offer_obj.grab_customer_data.id,
            grab_loan_offer_obj.program_id
        )
        self.assertEqual(result, None)

    def test_get_payment_plans_with_one_additional_loan_options(self):
        GrabLoanOfferFactory(
            grab_customer_data=self.grab_customer_data,
            program_id="ID-DAX-CL-9-MONTHS",
            interest_value=4,
            fee_value=50000,
            min_tenure=60,
            tenure=180,
            tenure_interval=30,
            weekly_installment_amount=223000,
            min_loan_amount=500000,
            max_loan_amount=4900000
        )

        responses = GrabLoanService().get_payment_plans(
            self.token,
            self.mobile_phone,
            'ID-DAX-CL-9-MONTHS',
            '4900000',
            '4',
            '50000',
            60,
            180,
            30,
            '223000',
            '500000',
            '4900000')
        self.assertEqual(len(responses), 6)
        self.assertTrue(int(responses[1].get('loan_amount')) < int(responses[2].get('loan_amount')))
        self.assertTrue(responses[1].get('smaller_loan_option_flag'))

    def test_get_payment_plans_with_more_than_one_additional_loan_options(self):
        GrabLoanOfferFactory(
            grab_customer_data=self.grab_customer_data,
            program_id="ID-DAX-CL-9-MONTHS",
            interest_value=4,
            fee_value=50000,
            min_tenure=60,
            tenure=180,
            tenure_interval=30,
            weekly_installment_amount=223000,
            min_loan_amount=500000,
            max_loan_amount=10000000
        )

        responses = GrabLoanService().get_payment_plans(
            self.token,
            self.mobile_phone,
            'ID-DAX-CL-9-MONTHS',
            '10000000',
            '4',
            '50000',
            60,
            180,
            30,
            '223000',
            '500000',
            '10000000')
        self.assertEqual(len(responses), 7)
        self.assertTrue(responses[1].get('smaller_loan_option_flag'))
        self.assertTrue(responses[2].get('smaller_loan_option_flag'))

    def test_flag_grab_customer_with_additional_options(self):
        GrabLoanOfferFactory(
            grab_customer_data=self.grab_customer_data,
            program_id="ID-DAX-CL-9-MONTHS",
            interest_type="SIMPLE_INTEREST",
            interest_value=4,
            fee_type='FLAT',
            fee_value=50000,
            min_tenure=60,
            tenure=180,
            tenure_interval=30,
            weekly_installment_amount=223000,
            min_loan_amount=500000,
            max_loan_amount=10000000,
            penalty_type='FLAT',
            penalty_value=40000
        )

        payment_plan_response = GrabLoanService().get_payment_plans(
            self.token,
            self.mobile_phone,
            'ID-DAX-CL-9-MONTHS',
            '10000000',
            '4',
            '50000',
            60,
            180,
            30,
            '223000',
            '500000',
            '10000000')
        self.assertEqual(len(payment_plan_response), 7)

        grab_customer_data = GrabCustomerData.objects.get_or_none(
            phone_number=self.mobile_phone,
            grab_validation_status=True,
            token=self.token,
            otp_status=GrabCustomerData.VERIFIED
        )

        GrabLoanService().record_payment_plans(
            grab_customer_data_id=grab_customer_data.id,
            program_id='ID-DAX-CL-9-MONTHS',
            payment_plans=payment_plan_response,
        )
        grab_experiment = GrabExperiment.objects.filter(
            grab_customer_data=grab_customer_data).last()
        self.assertIsNotNone(grab_experiment)
        self.assertEqual(grab_experiment.experiment_name, 'smaller_loan_option')
        self.assertIsNotNone(grab_experiment.parameters.get('additional_loan_options_count'))

        data = {
            'phone_number': self.mobile_phone,
            'program_id': 'ID-DAX-CL-9-MONTHS',
            'max_loan_amount': 1000000.0,
            'min_loan_amount': 500000.0,
            'frequency_type': 'DAILY',
            'loan_disbursement_amount': '5650000',
            'penalty_type': 'FLAT',
            'penalty_value': 40000,
            'amount_plan': 1000000,
            'tenure_plan': 180,
            'interest_type_plan': 'SIMPLE_INTEREST',
            'interest_value_plan': 4.0,
            'instalment_amount_plan': 1000000,
            'fee_type_plan': 'FLAT',
            'fee_value_plan': 40000.0,
            'total_repayment_amount_plan': 5704000,
            'weekly_installment_amount': 221666.6666666667,
            'smaller_loan_option_flag': True,
            'promo_code': 'test',
        }

        choose_payment_plan_response = GrabLoanService().choose_payment_plan(self.token, data)
        grab_experiment.refresh_from_db()
        self.assertIsNotNone(choose_payment_plan_response)
        self.assertDictEqual(choose_payment_plan_response, {"is_payment_plan_set": True})
        self.assertIsNotNone(grab_experiment.parameters.get('loan_offer'))

        grab_loan_inquiry = GrabLoanInquiry.objects.get(grab_customer_data=self.grab_customer_data)
        grab_loan_data = GrabLoanData.objects.get(grab_loan_inquiry=grab_loan_inquiry)
        self.assertEqual(
            grab_loan_data.selected_amount, payment_plan_response[0].get("loan_amount")
        )
        self.assertEqual(
            grab_loan_data.selected_instalment_amount,
            payment_plan_response[0].get("daily_repayment"),
        )

    def test_payment_plans_should_not_have_loan_amount_less_than_grab_loan_offer(self):
        min_loan_amount_offer = '500000'
        # fee_type = models.CharField(max_length=30)
        # interest_type = models.CharField(max_length=30)
        # penalty_type = models.CharField(max_length=30)
        # penalty_value = models.FloatField(blank=True, null=True)
        # frequency_type = models.CharField(max_length=15)
        GrabLoanOffer.objects.create(
            grab_customer_data=self.grab_customer_data,
            program_id='ID-DAX-CL-9-MONTHS',
            max_loan_amount='500000',
            min_loan_amount=min_loan_amount_offer,
            weekly_installment_amount='30355',
            tenure=120,
            min_tenure=30,
            tenure_interval=30,
            interest_value='5',
            fee_value='75000',
        )
        responses = GrabLoanService().get_payment_plans(
            self.token,
            self.mobile_phone,
            'ID-DAX-CL-9-MONTHS',
            '500000',
            '5',
            '75000',
            30,
            120,
            30,
            '30355',
            min_loan_amount_offer,
            '500000'
        )
        self.assertEqual(len(responses), 0)

    def test_application_status_check_ecc_rejected(self):
        self.application.update_safely(is_kin_approved=EmergencyContactConst.CONSENT_REJECTED)
        response = GrabAPIService.application_status_check(self.customer)
        self.assertIsNotNone(response)
        self.assertEqual(response.get('ecc_reject'), True)


class TestGrabLogin(TestCase):
    def setUp(self) -> None:
        self.mobile_phone = '6281245789865'
        self.nik = '1601260506021284'
        self.pin = '123456'
        self.user = AuthUserFactory()
        self.user.set_password(self.pin)
        self.user.save()
        self.token = '906d4e43a3446cecb4841cf41c10c91c9610c8a5519437c913ab9144b71054f915752a69d' \
                     '0220619666ac3fc1f27f7b4934a6a4b2baa2f85b6533c663ca6d98f976328625f756e79a7cc' \
                     '543770b6945c1a5aaafd066ceed10204bf85c07c2fae81118d990d7c5fafcb98f8708f540d6d' \
                     '8971764c12b9fb912c7d1c3b1db1f931'
        self.customer = CustomerFactory(phone=self.mobile_phone, nik=self.nik, user=self.user)
        self.grab_customer_data = GrabCustomerDataFactory(
            phone_number=self.mobile_phone,
            customer=self.customer,
            grab_validation_status=True,
            otp_status='VERIFIED',
            token=self.token
        )
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.workflowpath = WorkflowStatusPath(
            status_previous=129,
            status_next=139,
            type='graveyard',
            workflow=self.workflow,
            is_active=True
        )
        self.workflowpath.save()
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(account_lookup=self.account_lookup)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.ctl_product_line = ProductLineFactory(product_line_code=ProductLineCodes.CTL1)
        self.name_bank_validation = NameBankValidationFactory(bank_code='HELLOQWE')
        self.bank = BankFactory(xfers_bank_code='HELLOQWE')
        self.application_status_code = StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.pending_application_status_code = StatusLookupFactory(status_code=StatusLookup.PENDING_PARTNER_APPROVAL)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            application_status=self.application_status_code,
            mobile_phone_1=self.mobile_phone,
            workflow=self.workflow
        )
        self.ctl_application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.ctl_product_line,
            application_status=self.pending_application_status_code,
            mobile_phone_1=self.mobile_phone,
            workflow=self.workflow
        )
        self.experiment = ExperimentFactory(status_old=129, status_new=139)
        self.app_experiment = ApplicationExperimentFactory(application=self.ctl_application, experiment=self.experiment)
        self.user_pin = CustomerPinFactory(user=self.customer.user)
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            name_bank_validation_id=self.name_bank_validation.id
        )
        self.txn_id = 'abc123'
        self.document = DocumentFactory(loan_xid=self.loan.loan_xid, document_type='sphp_julo')
        self.product_line1 = ProductLineFactory(product_line_code=ProductLineCodes.MF)

    @mock.patch('juloserver.grab.services.services.get_redis_client')
    def test_grab_login_failure(self, _: MagicMock) -> None:

        invalid_pin = '123457'
        with self.assertRaises(GrabLogicException):
            GrabAuthService.login(self.nik, invalid_pin)

    @mock.patch('juloserver.grab.services.services.get_redis_client')
    @mock.patch('juloserver.grab.services.services.process_application_status_change')
    @mock.patch('django.utils.timezone.localtime')
    @mock.patch('juloserver.grab.services.services.GrabAuthService._reset_pin_failure')
    @mock.patch('juloserver.grab.services.services.make_never_expiry_token')
    def test_grab_login_success(self, _: MagicMock,
                                mock_application_status_change: MagicMock,
                                mocked_time: MagicMock, failure_pin: MagicMock,
                                never_expiry_token: MagicMock) -> None:
        datetime_now = datetime.datetime(2022, 9, 10, 16, 00)
        mocked_time.side_effect = [
            datetime_now,
            datetime_now,
            datetime_now,
            datetime_now,
        ]

        # workaround update app status code for ctl apps to 129
        ctl_application_set = self.customer.application_set.filter(
            product_line__product_line_code__in=ProductLineCodes.ctl(),
        )
        for ctl_app in ctl_application_set:
            ctl_app.application_status_id = ApplicationStatusCodes.PENDING_PARTNER_APPROVAL
            ctl_app.save()
        self.customer.refresh_from_db()
        response = GrabAuthService.login(self.nik, self.pin)
        self.assertEqual(response['nik'], self.customer.nik)
        self.assertEqual(response['phone_number'], self.mobile_phone)

        # check if ctl apps being expired
        updated_ctl_app_set = self.customer.application_set.filter(
            product_line__product_line_code__in=ProductLineCodes.ctl(),
        )
        last_app_history = ApplicationHistory.objects.last()
        for updated_ctl_app in updated_ctl_app_set:
            self.assertEqual(last_app_history.status_new, updated_ctl_app.status)
            self.assertEqual(last_app_history.status_new, ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED)

    @mock.patch('juloserver.grab.services.services.get_redis_client')
    def test_grab_login_failure_with_empty_pin(self, _: MagicMock) -> None:
        with self.assertRaises(GrabLogicException):
            GrabAuthService.login(self.nik, '')

    @mock.patch('juloserver.grab.services.services.get_redis_client')
    @mock.patch('django.utils.timezone.localtime')
    @mock.patch('juloserver.grab.services.services.GrabAuthService._reset_pin_failure')
    @mock.patch('juloserver.grab.services.services.make_never_expiry_token')
    def test_grab_login_fail_due_to_other_partner(
            self, _: MagicMock,
            mocked_time: MagicMock, failure_pin: MagicMock,
            never_expiry_token: MagicMock) -> None:
        datetime_now = datetime.datetime(2022, 9, 10, 16, 00)
        mocked_time.side_effect = [
            datetime_now,
            datetime_now,
            datetime_now,
            datetime_now,
        ]
        self.ctl_application.product_line = self.product_line1
        self.ctl_application.application_status_id = ApplicationStatusCodes.FORM_CREATED
        self.ctl_application.save()

        with self.assertRaises(GrabLogicException) as e:
            GrabAuthService.login(self.nik, self.pin)

    def test_block_users_other_than_grab(self) -> None:
        self.assertTrue(block_users_other_than_grab(self.user))
        self.ctl_application.product_line = self.product_line1
        self.ctl_application.application_status_id = ApplicationStatusCodes.FORM_CREATED
        self.ctl_application.save()
        self.assertFalse(block_users_other_than_grab(self.user))

        # test for 107 status
        self.ctl_application.update_safely(
            application_status_id=ApplicationStatusCodes.OFFER_REGULAR
        )
        self.assertFalse(block_users_other_than_grab(self.user))

        # test for 108 status
        self.ctl_application.update_safely(
            application_status_id=ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK
        )
        self.assertFalse(block_users_other_than_grab(self.user))

        # test for 109 status
        self.ctl_application.update_safely(
            application_status_id=ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED
        )
        self.assertFalse(block_users_other_than_grab(self.user))


class TestGrabEmailTemplate(TestCase):
    def setUp(self) -> None:
        self.mobile_phone = '6281245789159'
        self.token = '906d4e43a3446cecb4841cf41c10c91c9610c8a5519437c913ab9144b71054f915752a69d' \
                     '0220619666ac3fc1f27f7b4934a6a4b2baa2f85b6533c663ca6d98f976328625f756e79a7cc' \
                     '543770b6945c1a5aaafd066ceed10204bf85c07c2fae81118d990d7c5fafcb98f8708f540d6d' \
                     '8971764c12b9fb912c7fgdgdgfdfdg'
        self.hashed_phone_number = '7358b08205b13f3ec8967ea7f1c331a40cefdeda0cef8bf8b9ca7acefd95sfgdgf'
        self.customer = CustomerFactory(phone=self.mobile_phone)
        self.grab_customer_data = GrabCustomerDataFactory(
            phone_number=self.mobile_phone,
            customer=self.customer,
            grab_validation_status=True,
            otp_status='VERIFIED',
            token=self.token,
            hashed_phone_number=self.hashed_phone_number
        )
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(
            account_lookup=self.account_lookup,
            customer=self.customer
        )

        self.account_limit = AccountLimitFactory(account=self.account)

        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB)
        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line, admin_fee=40000)
        self.name_bank_validation = NameBankValidationFactory(bank_code='HELLOQWE')
        self.name_bank_validation_paid_off = NameBankValidationFactory(bank_code='PAIDOFF')
        self.bank = BankFactory(xfers_bank_code='HELLOQWE')
        self.application_status_code = StatusLookupFactory(code=190)
        self.partner = PartnerFactory(name="grab")
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            application_status=self.application_status_code,
            mobile_phone_1=self.mobile_phone,
            bank_name='bank_test',
            name_in_bank='name_in_bank'
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            name_bank_validation_id=self.name_bank_validation.id,
            product=self.product_lookup
        )
        self.txn_id = 'abc123'
        self.paid_off_payment_status = StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)
        self.paid_off_loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            name_bank_validation_id=self.name_bank_validation_paid_off.id,
            product=self.product_lookup
        )

    @mock.patch('juloserver.loan.services.views_related.get_manual_signature_url_grab')
    def test_grab_sphp_template_email_success(self, mocked_get_manual_signature) -> None:
        mocked_get_manual_signature.return_value = "link"
        body = get_sphp_template_grab(self.loan.id, type="email")
        self.assertIsNotNone(body)

    @mock.patch('juloserver.loan.services.views_related.get_manual_signature_url_grab')
    def test_grab_sphp_template_email_failed(self, mocked_get_manual_signature) -> None:
        mocked_get_manual_signature.return_value = "link"
        body = get_sphp_template_grab(0, type="email")
        self.assertIsNone(body)

    @mock.patch('juloserver.loan.services.views_related.get_manual_signature_url_grab')
    def test_grab_sphp_template_document_success(self, mocked_get_manual_signature) -> None:
        mocked_get_manual_signature.return_value = "link"
        body = get_sphp_template_grab(self.loan.id, type="document")
        self.assertIsNotNone(body)

    @mock.patch('juloserver.loan.services.views_related.get_manual_signature_url_grab')
    def test_grab_sphp_template_document_failed(self, mocked_get_manual_signature) -> None:
        mocked_get_manual_signature.return_value = "link"
        body = get_sphp_template_grab(0, type="document")
        self.assertIsNone(body)

    @mock.patch('juloserver.loan.services.views_related.get_manual_signature_url_grab')
    def test_grab_sphp_template_android_success(self, mocked_get_manual_signature) -> None:
        mocked_get_manual_signature.return_value = None
        body = get_sphp_template_grab(self.loan.id, type="android")
        self.assertIsNotNone(body)

    @mock.patch('juloserver.loan.services.views_related.get_manual_signature_url_grab')
    def test_grab_sphp_template_android_failed(self, mocked_get_manual_signature) -> None:
        mocked_get_manual_signature.return_value = None
        body = get_sphp_template_grab(0, type="android")
        self.assertIsNone(body)

    @mock.patch('juloserver.grab.communication.email.GrabUtils.create_digital_signature')
    @mock.patch('juloserver.grab.communication.email.upload_document')
    @mock.patch('juloserver.grab.communication.email.send_grab_restructure_email')
    @mock.patch('juloserver.grab.communication.email.pdfkit.from_string')
    @mock.patch('juloserver.grab.communication.email.get_sphp_template_grab')
    def test_trigger_sending_email_sphp(
            self, mocked_template, mocked_pdf, mocked_send_email, mocked_upload,
            mocked_digi_sign) -> None:
        mocked_template.return_value = "BODY"
        mocked_pdf.return_value = None
        mocked_digi_sign.return_value = ('mocked_faked_digital_hash', 1, datetime.datetime(2023, 1, 1))
        mocked_send_email.return_value = None
        mocked_upload.return_value = None
        trigger_sending_email_sphp(self.loan.id)
        mocked_send_email.assert_called_with(self.loan, self.application, ANY, ANY)
        mocked_upload.assert_called()
        mocked_pdf.assert_called_with("BODY", ANY)
        mocked_template.assert_called_with(self.loan.id, type="email")

    @mock.patch('juloserver.grab.communication.email.base64.b64encode')
    @mock.patch.object(JuloEmailClient, 'send_email')
    def test_send_grab_restructure_email(self, mock_send_email, mocked_encode):
        mock_send_email.return_value = [200, 'OK', {"X-Message-Id": 100}]
        magic_mock_encode = mock.MagicMock()
        magic_mock_encode.decode.return_value = "Contents"
        mocked_encode.return_value = magic_mock_encode
        with mock.patch(
                'juloserver.grab.communication.email.open',
                mock.mock_open(), create=True
        ):
            send_grab_restructure_email(
                self.loan, self.application, 'path/to/home/sample.pdf', 'sample.pdf')
        attachment_dict = {
            "content": "Contents",
            "filename": 'sample.pdf',
            "type": "application/pdf"
        }
        subject = "Program Keringanan Cicilan Harian GrabModal powered by JULO"
        mock_send_email.assert_called_with(
            subject,
            ANY,
            self.loan.customer.email,
            email_from='cs@julo.co.id',
            email_cc=None,
            name_from='JULO',
            reply_to=ANY,
            attachment_dict=attachment_dict,
            content_type="text/html"
        )
        email_history = EmailHistory.objects.get_or_none(
            customer=self.loan.customer,
            sg_message_id=100,
            to_email=self.loan.customer.email,
            subject=subject,
        )
        self.assertIsInstance(email_history, EmailHistory)

    @mock.patch('juloserver.loan.services.views_related.get_manual_signature_url_grab')
    def test_grab_sphp_template_document_success_with_paid_off_loan(self, mocked_url) -> None:
        mocked_url.return_value = "Link"
        payments = Payment.objects.filter(loan_id=self.paid_off_loan)
        for payment in payments:
            payment.payment_status = self.paid_off_payment_status
            payment.save()
        self.paid_off_loan.refresh_from_db()
        body = get_sphp_template_grab(self.paid_off_loan.id, type="document")
        self.assertIsNotNone(body)


class TestGrabLoanSubmissionPredisbursalCheck(TestCase):
    def setUp(self) -> None:
        self.mobile_phone = '6281245789171'
        self.customer = CustomerFactory(phone=self.mobile_phone)
        self.grab_customer_data = GrabCustomerDataFactory(
            phone_number=self.mobile_phone,
            customer=self.customer,
            grab_validation_status=True,
            otp_status='VERIFIED'
        )
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(
            account_lookup=self.account_lookup,
            customer=self.customer
        )
        self.workflow_path = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=210, status_next=216, workflow=self.workflow_path)

        self.account_limit = AccountLimitFactory(account=self.account)

        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB)
        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line, admin_fee=40000)
        self.name_bank_validation = NameBankValidationFactory(bank_code='HELLOQWE')
        self.name_bank_validation_paid_off = NameBankValidationFactory(bank_code='PAIDOFF')
        self.bank = BankFactory(xfers_bank_code='HELLOQWE')
        self.application_status_code = StatusLookupFactory(code=190)
        self.partner = PartnerFactory(name="grab")
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            application_status=self.application_status_code,
            mobile_phone_1=self.mobile_phone,
            bank_name='bank_test',
            name_in_bank='name_in_bank'
        )
        self.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            name_bank_validation_id=self.name_bank_validation.id,
            product=self.product_lookup,
            loan_status=self.loan_status
        )

    @mock.patch('juloserver.grab.services.services.GrabClient.get_pre_disbursal_check')
    def test_check_predisbursal_check_grab_pass(self, mocked_client) -> None:
        self.loan.loan_status = self.loan_status
        self.loan.save()
        mocked_value = mock.MagicMock()
        mocked_value.content = json.dumps({
            "msg_id": "30a4c02637674cde8477d1f832a7386f", "version": "1.0",
            "success": True, "error": {"error_code": 0, "dev_message": ""},
            "data": {"msg_id": "30a4c02637674cde8477d1f832a7386f", "code": False,
                     "reason": None}
        })
        mocked_client.return_value = mocked_value
        return_value = check_predisbursal_check_grab(self.loan)
        self.assertIsNone(return_value)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, 210)

    @mock.patch('juloserver.grab.services.services.GrabClient.get_pre_disbursal_check')
    def test_check_predisbursal_check_grab_failed_1(self, mocked_client) -> None:
        mocked_value = mock.MagicMock()
        mocked_value.content = json.dumps({
            "msg_id": "30a4c02637674cde8477d1f832a7386f", "version": "1.0",
            "success": True, "error": {"error_code": 0, "dev_message": ""},
            "data": {"msg_id": "30a4c02637674cde8477d1f832a7386f", "code": True,
                     "reason": None}
        })
        mocked_client.return_value = mocked_value
        with self.assertRaises(JuloException) as context:
            check_predisbursal_check_grab(self.loan)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, 216)

    @mock.patch('juloserver.grab.services.services.GrabClient.get_pre_disbursal_check')
    def test_check_predisbursal_check_grab_failed_2(self, mocked_client) -> None:
        self.loan.loan_status = self.loan_status
        self.loan.save()
        mocked_value = mock.MagicMock()
        mocked_value.content = json.dumps({
            "msg_id": "30a4c02637674cde8477d1f832a7386f", "version": "1.0",
            "success": True, "error": {"error_code": 0, "dev_message": ""}
        })
        mocked_client.return_value = mocked_value
        with self.assertRaises(GrabApiException) as context:
            check_predisbursal_check_grab(self.loan)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, 216)


class TestGrabWriteOffStatuses(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account)
        self.loan = LoanFactory(account=self.account)
        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)
        self.loan_2 = LoanFactory(account=self.account)
        self.grab_loan_data_2 = GrabLoanDataFactory(loan=self.loan_2)

    def test_get_account_summary_loan_status_ewo_off(self):
        loans = get_loans(loan_xid=self.loan.loan_xid)
        loan = loans[0]
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.CURRENT)
        loan.update_safely(loan_status=loan_status)
        loan_status_response = get_account_summary_loan_status(
            loan, False, False, False)
        self.assertEqual(loan_status_response, 'Current')

        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.LOAN_90DPD)
        loan.update_safely(loan_status=loan_status)
        loan_status_response = get_account_summary_loan_status(
            loan, False, True, False)
        self.assertEqual(loan_status_response, '90dpd')

        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.LOAN_90DPD)
        loan.update_safely(loan_status=loan_status)
        loan_status_response = get_account_summary_loan_status(
            loan, False, False, False)
        self.assertEqual(loan_status_response, '90dpd')

        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.LOAN_180DPD)
        dpd = 181
        loan.update_safely(loan_status=loan_status)
        loan_status_response = get_account_summary_loan_status(
            loan, False, True, False, dpd)
        self.assertEqual(loan_status_response, GrabWriteOffStatus.WRITE_OFF_180_DPD)

        loans = get_loans(loan_xid=self.loan_2.loan_xid)
        loan_2 = loans[0]
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.LOAN_150DPD)
        dpd = 95
        loan_2.update_safely(loan_status=loan_status)
        LoanHistory.objects.filter(loan=loan_2).delete()
        loan_history = LoanHistoryFactory(
            loan=loan_2, status_old=236, status_new=237)
        loan_history.cdate = timezone.localtime(
                timezone.now() - datetime.timedelta(days=2))
        loan_history.save()
        loans = get_loans(loan_xid=self.loan_2.loan_xid)
        loan_2 = loans[0]
        loan_status_response = get_account_summary_loan_status(
            loan_2, False, True, False, dpd)
        self.assertEqual(loan_status_response, GrabWriteOffStatus.WRITE_OFF_180_DPD)

        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.LOAN_150DPD)
        dpd = 95
        LoanHistory.objects.filter(loan=loan_2).delete()
        loan_2.update_safely(loan_status=loan_status)
        loans = get_loans(loan_xid=self.loan_2.loan_xid)
        loan_2 = loans[0]
        loan_history = LoanHistoryFactory(
            loan=loan_2, status_old=236, status_new=237)
        loan_history.cdate = timezone.localtime(
                timezone.now() - datetime.timedelta(days=2))
        loan_history = LoanHistoryFactory(
            loan=loan_2, status_old=237, status_new=236)
        loan_history.cdate = timezone.localtime(
                timezone.now() - datetime.timedelta(hours=32))
        loan_history.save()
        loan_status_response = get_account_summary_loan_status(
            loan_2, False, True, False, dpd)
        self.assertEqual(loan_status_response, '150dpd')

        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.LOAN_150DPD)
        dpd = 95
        LoanHistory.objects.filter(loan=loan_2).delete()
        loan_2.update_safely(loan_status=loan_status)
        loan_history = LoanHistoryFactory(
            loan=loan_2, status_old=236, status_new=237)
        loan_history.cdate = timezone.localtime(
                timezone.now() - datetime.timedelta(days=5))
        loan_history.save()
        loan_history = LoanHistoryFactory(
            loan=loan_2, status_old=237, status_new=236)
        loan_history.cdate = timezone.localtime(
                timezone.now() - datetime.timedelta(hours=5))
        loan_history.save()
        loans = get_loans(loan_xid=self.loan_2.loan_xid)
        loan_2 = loans[0]
        loan_status_response = get_account_summary_loan_status(
            loan_2, False, True, False, dpd)
        self.assertEqual(loan_status_response, GrabWriteOffStatus.WRITE_OFF_180_DPD)

        dpd = 180
        loans = get_loans(loan_xid=self.loan.loan_xid)
        loan = loans[0]
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.LOAN_180DPD)
        loan.update_safely(loan_status=loan_status)
        loan_status_response = get_account_summary_loan_status(
            loan, False, True, False, dpd)
        self.assertEqual(loan_status_response, '180dpd')

        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.LOAN_90DPD)
        loan.update_safely(loan_status=loan_status)
        self.grab_loan_data.update_safely(is_early_write_off=True)
        loan_status_response = get_account_summary_loan_status(
            loan, True, False, False)
        self.assertEqual(loan_status_response, GrabWriteOffStatus.EARLY_WRITE_OFF)

        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.PAID_OFF)
        loan.update_safely(loan_status=loan_status)
        last_payment = loan.prefetch_payments[-1]
        account_transaction = AccountTransactionFactory(transaction_type='waive_principal', account=loan.account)
        PaymentEventFactory(
            added_by=loan.customer.user,
            payment=last_payment,
            event_due_amount=last_payment.due_amount,
            account_transaction=account_transaction
        )

        loan_status_response = get_account_summary_loan_status(
            loan, False, False, True)
        self.assertEqual(loan_status_response, GrabWriteOffStatus.MANUAL_WRITE_OFF)

        loan_status_response = get_account_summary_loan_status(
            loan, False, False, False)
        self.assertEqual(loan_status_response, GrabWriteOffStatus.LEGACY_WRITE_OFF)


class TestMoveAuthCall(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(customer=self.customer,
                                      account_lookup=self.account_lookup)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        self.loan = LoanFactory(
            account=self.account,
            loan_status=loan_status,
            transaction_method=TransactionMethod.objects.get(id=1),
        )
        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)

    @mock.patch('juloserver.loan.services.sphp.loan_lender_approval_process_task.delay')
    def test_accept_julo_sphp_failed_missing_auth(self, mocked_approval):
        mocked_approval.return_value = None
        GrabAPILog.objects.filter(
            loan_id=self.loan.id, query_params=GrabPaths.LOAN_CREATION, http_status_code=200
        ).delete()
        self.loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        self.loan.save()
        return_value = accept_julo_sphp(self.loan, 'JULO')
        self.assertFalse(return_value)
        mocked_approval.assert_not_called()

    @mock.patch('juloserver.loan.services.sphp.loan_lender_approval_process_task.delay')
    def test_accept_julo_sphp_failed_500_auth(self, mocked_approval):
        grab_api_log = GrabAPILogFactory(
            customer_id=self.customer.id,
            loan_id=self.loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=500
        )
        GrabAPILog.objects.filter(
            loan_id=self.loan.id, query_params=GrabPaths.LOAN_CREATION, http_status_code=200
        ).delete()
        self.loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        self.loan.save()
        mocked_approval.return_value = None
        return_value = accept_julo_sphp(self.loan, 'JULO')
        self.assertFalse(return_value)
        mocked_approval.assert_not_called()

    @mock.patch('juloserver.loan.services.sphp.loan_lender_approval_process_task.delay')
    def test_accept_julo_sphp_failed_400_auth(self, mocked_approval):
        grab_api_log = GrabAPILogFactory(
            customer_id=self.customer.id,
            loan_id=self.loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=400
        )
        GrabAPILog.objects.filter(
            loan_id=self.loan.id, query_params=GrabPaths.LOAN_CREATION, http_status_code=200
        ).delete()
        mocked_approval.return_value = None
        self.loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        self.loan.save()
        return_value = accept_julo_sphp(self.loan, 'JULO')
        self.assertFalse(return_value)
        mocked_approval.assert_not_called()

    @mock.patch('juloserver.loan.services.sphp.loan_lender_approval_process_task.delay')
    def test_accept_julo_sphp_success_auth(self, mocked_approval, *args):
        grab_api_log = GrabAPILogFactory(
            customer_id=self.customer.id,
            loan_id=self.loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=200
        )
        mocked_approval.return_value = None
        return_value = accept_julo_sphp(self.loan, 'JULO')
        self.assertEqual(return_value, 211)
        mocked_approval.assert_called()

    @mock.patch('juloserver.loan.services.sphp.loan_lender_approval_process_task.delay')
    @mock.patch('juloserver.loan.services.sphp.risky_change_phone_activity_check')
    def test_accept_julo_sphp_success_auth_risky_change_phone_detected(
            self, risky_phone_mock, mocked_approval, *args):
        grab_api_log = GrabAPILogFactory(
            customer_id=self.customer.id,
            loan_id=self.loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=200
        )
        risky_phone_mock.return_value = True
        mocked_approval.return_value = None
        return_value = accept_julo_sphp(self.loan, 'JULO')
        self.assertEqual(return_value, 211)
        mocked_approval.assert_not_called()

    def test_check_auth_called_service_no_call(self):
        customer = CustomerFactory()
        account = AccountFactory(
            account_lookup=self.account_lookup, customer=customer)
        loan = LoanFactory(customer=customer, account=account)
        return_value = check_grab_auth_success(loan.id)
        self.assertFalse(return_value)

    def test_check_auth_called_service_different_workflow(self):
        customer = CustomerFactory()
        workflow = WorkflowFactory(name='J1Workflow')
        account_lookup = AccountLookupFactory(workflow=workflow)
        account = AccountFactory(
            account_lookup=account_lookup, customer=customer)
        loan = LoanFactory(customer=customer, account=account)
        return_value = check_grab_auth_success(loan.id)
        self.assertFalse(return_value)

    def test_check_auth_called_success(self):
        customer = CustomerFactory()
        account = AccountFactory(
            account_lookup=self.account_lookup, customer=customer)
        loan = LoanFactory(customer=customer, account=account)
        grab_api_log = GrabAPILogFactory(
            customer_id=customer.id,
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=200
        )
        return_value = check_grab_auth_success(loan.id)
        self.assertTrue(return_value)

    def test_get_change_reason_and_loan_status_change_mapping_grab_4001(self):
        change_reason_check = GrabErrorMessage.AUTH_ERROR_MESSAGE_4001
        status_code, change_reason = (
            get_change_reason_and_loan_status_change_mapping_grab(4001))
        self.assertEqual(status_code, 219)
        self.assertEqual(change_reason, change_reason_check)

    def test_get_change_reason_and_loan_status_change_mapping_grab_4002(self):
        change_reason_check = GrabErrorMessage.AUTH_ERROR_MESSAGE_4002
        status_code, change_reason = (
            get_change_reason_and_loan_status_change_mapping_grab(4002))
        self.assertEqual(status_code, 219)
        self.assertEqual(change_reason, change_reason_check)

    def test_get_change_reason_and_loan_status_change_mapping_grab_4006(self):
        change_reason_check = GrabErrorMessage.AUTH_ERROR_MESSAGE_4006
        status_code, change_reason = (
            get_change_reason_and_loan_status_change_mapping_grab(4006))
        self.assertEqual(status_code, 219)
        self.assertEqual(change_reason, change_reason_check)

    def test_get_change_reason_and_loan_status_change_mapping_grab_4008(self):
        change_reason_check = GrabErrorMessage.AUTH_ERROR_MESSAGE_4008
        status_code, change_reason = (
            get_change_reason_and_loan_status_change_mapping_grab(4008))
        self.assertEqual(status_code, 219)
        self.assertEqual(change_reason, change_reason_check)

    def test_get_change_reason_and_loan_status_change_mapping_grab_4011(self):
        change_reason_check = GrabErrorMessage.AUTH_ERROR_MESSAGE_4011
        status_code, change_reason = (
            get_change_reason_and_loan_status_change_mapping_grab(4011))
        self.assertEqual(status_code, 219)
        self.assertEqual(change_reason, change_reason_check)

    def test_get_change_reason_and_loan_status_change_mapping_grab_4014(self):
        change_reason_check = GrabErrorMessage.AUTH_ERROR_MESSAGE_4014
        status_code, change_reason = (
            get_change_reason_and_loan_status_change_mapping_grab(4014))
        self.assertEqual(status_code, 219)
        self.assertEqual(change_reason, change_reason_check)

    def test_get_change_reason_and_loan_status_change_mapping_grab_4015(self):
        change_reason_check = GrabErrorMessage.AUTH_ERROR_MESSAGE_4015
        status_code, change_reason = (
            get_change_reason_and_loan_status_change_mapping_grab(4015))
        self.assertEqual(status_code, 219)
        self.assertEqual(change_reason, change_reason_check)

    def test_get_change_reason_and_loan_status_change_mapping_grab_4025(self):
        change_reason_check = GrabErrorMessage.AUTH_ERROR_MESSAGE_4025
        status_code, change_reason = (
            get_change_reason_and_loan_status_change_mapping_grab(4025))
        self.assertEqual(status_code, 219)
        self.assertEqual(change_reason, change_reason_check)

    def test_get_change_reason_and_loan_status_change_mapping_grab_5001(self):
        change_reason_check = GrabErrorMessage.AUTH_ERROR_MESSAGE_5001
        status_code, change_reason = (
            get_change_reason_and_loan_status_change_mapping_grab(5001))
        self.assertEqual(status_code, 219)
        self.assertEqual(change_reason, change_reason_check)

    def test_get_change_reason_and_loan_status_change_mapping_grab_5002(self):
        change_reason_check = GrabErrorMessage.AUTH_ERROR_MESSAGE_5002
        status_code, change_reason = (
            get_change_reason_and_loan_status_change_mapping_grab(5002))
        self.assertEqual(status_code, 219)
        self.assertEqual(change_reason, change_reason_check)

    def test_get_change_reason_and_loan_status_change_mapping_grab_default(self):
        change_reason_check = GrabErrorMessage.AUTH_ERROR_MESSAGE_API_ERROR
        status_code, change_reason = (
            get_change_reason_and_loan_status_change_mapping_grab(6000))
        self.assertEqual(status_code, 219)
        self.assertEqual(change_reason, change_reason_check)

    @mock.patch('juloserver.loan.services.lender_related.julo_one_disbursement_process')
    def test_grab_disbursement_trigger_task_auth_failed(self, mocked_disbursement_process):
        from juloserver.loan.tasks.lender_related import grab_disbursement_trigger_task
        customer = CustomerFactory()
        account = AccountFactory(
            account_lookup=self.account_lookup, customer=customer)
        AccountLimitFactory(account=account)
        ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        lender = LenderFactory()
        LenderBalanceCurrentFactory(
            lender=lender,
            available_balance=1000000000
        )
        loan = LoanFactory(
            customer=customer, account=account, lender=lender,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL)
        )
        GrabAPILogFactory(
            customer_id=customer.id,
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=400
        )
        mocked_disbursement_process.return_value = None
        with self.assertRaises(JuloException):
            grab_disbursement_trigger_task(loan.id)
        mocked_disbursement_process.assert_not_called()
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)
        self.assertTrue(LoanHistory.objects.filter(loan=loan, status_new=219).exists())

    @mock.patch('juloserver.loan.services.lender_related.julo_one_disbursement_process')
    def test_grab_disbursement_trigger_task_success(self, mocked_disbursement_process):
        from juloserver.loan.tasks.lender_related import grab_disbursement_trigger_task
        customer = CustomerFactory()
        account = AccountFactory(
            account_lookup=self.account_lookup, customer=customer)
        ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        AccountLimitFactory(account=account)
        lender = LenderFactory()
        LenderBalanceCurrentFactory(
            lender=lender,
            available_balance=1000000000
        )
        loan = LoanFactory(
            customer=customer, account=account, lender=lender,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL)
        )
        GrabAPILogFactory(
            customer_id=customer.id,
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=200
        )
        mocked_disbursement_process.return_value = None
        grab_disbursement_trigger_task(loan.id)
        mocked_disbursement_process.assert_called()
        self.loan.refresh_from_db()
        self.assertFalse(LoanHistory.objects.filter(loan=loan, status_new=219).exists())

    @mock.patch('juloserver.loan.services.lender_related.process_disburse')
    def test_julo_one_disbursement_process_auth_success(self, mocked_disbursement_process):
        customer = CustomerFactory()
        account = AccountFactory(
            account_lookup=self.account_lookup, customer=customer)
        ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        AccountLimitFactory(account=account)
        lender = LenderFactory()
        LenderBalanceCurrentFactory(
            lender=lender,
            available_balance=1000000000
        )
        bank_account_destination = BankAccountDestinationFactory(customer=customer)
        loan = LoanFactory(
            customer=customer, account=account, lender=lender,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL),
            bank_account_destination=bank_account_destination
        )
        GrabAPILogFactory(
            customer_id=customer.id,
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=200
        )
        mocked_disbursement_process.return_value = None

        julo_one_disbursement_process(loan)
        mocked_disbursement_process.assert_called()

    @mock.patch('juloserver.loan.services.lender_related.process_disburse')
    def test_julo_one_disbursement_process_auth_failure(self, mocked_disbursement_process):
        customer = CustomerFactory()
        account = AccountFactory(
            account_lookup=self.account_lookup, customer=customer)
        ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        AccountLimitFactory(account=account)
        lender = LenderFactory()
        LenderBalanceCurrentFactory(
            lender=lender,
            available_balance=1000000000
        )
        bank_account_destination = BankAccountDestinationFactory(customer=customer)
        loan = LoanFactory(
            customer=customer, account=account, lender=lender,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL),
            bank_account_destination=bank_account_destination
        )
        GrabAPILogFactory(
            customer_id=customer.id,
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=400
        )
        mocked_disbursement_process.return_value = None
        with self.assertRaises(JuloException):
            julo_one_disbursement_process(loan)
        mocked_disbursement_process.assert_not_called()

    @mock.patch('juloserver.loan.services.loan_related.GrabClient.submit_cancel_loan')
    def test_update_loan_status_and_loan_history_for_expired(self, mocked_grab_client):
        customer = CustomerFactory()
        account = AccountFactory(
            account_lookup=self.account_lookup, customer=customer)
        ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        AccountLimitFactory(account=account)
        lender = LenderFactory()
        LenderBalanceCurrentFactory(
            lender=lender,
            available_balance=1000000000
        )
        bank_account_destination = BankAccountDestinationFactory(customer=customer)
        loan = LoanFactory(
            customer=customer, account=account, lender=lender,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL),
            bank_account_destination=bank_account_destination
        )
        GrabAPILogFactory(
            customer_id=customer.id,
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=200
        )
        mocked_grab_client.return_value = None
        update_loan_status_and_loan_history(loan.id, 217)
        mocked_grab_client.assert_called()

    @mock.patch('juloserver.loan.services.loan_related.GrabClient.submit_cancel_loan')
    def test_update_loan_status_and_loan_history_for_210(self, mocked_grab_client):
        customer = CustomerFactory()
        account = AccountFactory(
            account_lookup=self.account_lookup, customer=customer)
        ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        AccountLimitFactory(account=account)
        lender = LenderFactory()
        LenderBalanceCurrentFactory(
            lender=lender,
            available_balance=1000000000
        )
        bank_account_destination = BankAccountDestinationFactory(customer=customer)
        loan = LoanFactory(
            customer=customer, account=account, lender=lender,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL),
            bank_account_destination=bank_account_destination
        )
        GrabAPILogFactory(
            customer_id=customer.id,
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=200
        )
        mocked_grab_client.return_value = None
        update_loan_status_and_loan_history(loan.id, 210)
        mocked_grab_client.assert_not_called()


class TestGrabChangeBankAccountService(TestCase):
    def setUp(self):
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.phone_number = "628456812565"
        self.customer = CustomerFactory(
            user=self.user,
            phone=self.phone_number
        )
        self.grab_customer_data = GrabCustomerDataFactory(
            customer=self.customer,
            otp_status=GrabCustomerData.VERIFIED,
            grab_validation_status=True,
            phone_number=self.phone_number
        )
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )

        self.bank_name = "test_bank_name"
        self.bank_code = "BCA"
        self.bank = BankFactory(
            bank_code=self.bank_code,
            bank_name=self.bank_name,
            is_active=True,
            swift_bank_code="ABSWIFTCD",
            xfers_bank_code=self.bank_code
        )

        self.bank_account_number = '1212122231'
        self.application = ApplicationFactory(
            workflow=self.workflow,
            bank_name=self.bank.bank_name,
            bank_account_number=self.bank_account_number,
            customer=self.customer,
            account=self.account,
            name_in_bank=self.customer.fullname
        )
        self.bank_category = BankAccountCategoryFactory(
            category='self',
            display_label='Pribadi',
            parent_category_id=1
        )

        self.old_name_bank_validation = NameBankValidationFactory(
            bank_code="BCA",
            account_number=123,
            name_in_bank=self.customer.fullname,
            method="xfers",
            validation_status=NameBankValidationStatus.SUCCESS,
            mobile_phone=self.phone_number,
            attempt=0,
            validation_id=123
        )
        self.application.name_bank_validation = self.old_name_bank_validation
        self.application.bank_account_number = self.old_name_bank_validation.account_number

        self.validation_id = 1234
        self.method = 'Xfers'
        self.name_bank_validation = NameBankValidationFactory(
            bank_code="BCA",
            account_number=self.bank_account_number,
            name_in_bank=self.customer.fullname,
            method=self.method,
            validation_status=NameBankValidationStatus.SUCCESS,
            mobile_phone=self.phone_number,
            attempt=0,
            validation_id=self.validation_id
        )

        self.bank_name_validation_log = BankNameValidationLogFactory(
            validation_id=self.validation_id,
            validation_status=NameBankValidationStatus.SUCCESS,
            validated_name=self.customer.fullname,
            account_number=self.bank_account_number,
            method=self.method,
            application=self.application,
            reason="",
        )

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED
        )
        self.application.save()

    def test_success_is_valid_application(self):
        svc = GrabChangeBankAccountService()
        app, is_valid = svc.is_valid_application(self.application.id, self.customer)
        self.assertEqual(app, self.application)
        self.assertEqual(is_valid, True)

    def test_success_is_valid_application_with_status_190(self):
        svc = GrabChangeBankAccountService()
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()

        app, is_valid = svc.is_valid_application(self.application.id, self.customer)
        self.assertEqual(app, self.application)
        self.assertEqual(is_valid, True)

    def test_is_valid_application_not_found(self):
        unknow_app = ApplicationFactory()
        with self.assertRaises(GrabLogicException):
            svc = GrabChangeBankAccountService()
            svc.is_valid_application(unknow_app.id, self.customer)

    def test_is_valid_application_not_owned_by_correct_user(self):
        customer = CustomerFactory()
        with self.assertRaises(GrabLogicException):
            svc = GrabChangeBankAccountService()
            svc.is_valid_application(self.application.id, customer)

    def test_is_valid_application_application_not_grab(self):
        workflow = WorkflowFactory(name="test")
        self.application.workflow = workflow
        self.application.save()

        with self.assertRaises(GrabLogicException):
            svc = GrabChangeBankAccountService()
            svc.is_valid_application(self.application.id, self.customer)

    def test_is_valid_application_application_not_eligible_for_update_bank_account(self):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS
        )
        self.application.save()
        with self.assertRaises(GrabLogicException):
            svc = GrabChangeBankAccountService()
            svc.is_valid_application(self.application.id, self.customer)

    def test_failed_is_valid_application_with_application_status_190_has_active_loan(self):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()

        loan_status = StatusLookupFactory(status_code=StatusLookup.LENDER_APPROVAL)
        product_line = ProductLineFactory()
        LoanFactory(
            customer=self.customer,
            product=ProductLookupFactory(product_line=product_line, late_fee_pct=0.05),
            loan_status=loan_status,
            account=self.account,
            application=self.application
        )

        with self.assertRaises(GrabLogicException):
            svc = GrabChangeBankAccountService()
            svc.is_valid_application(self.application.id, self.customer)

    @mock.patch('juloserver.disbursement.services.get_service')
    def test_trigger_grab_name_bank_validation_success(self, mock_get_service):
        mock_service = MockValidationProcessService(
            data_to_return={
                "status": NameBankValidationStatus.SUCCESS,
                "validated_name": self.customer.fullname.lower(),
                "id": 1234,
                "reason": "",
                "error_message": ""
            }
        )
        mock_get_service.return_value = mock_service

        svc = GrabChangeBankAccountService()
        resp = svc.trigger_grab_name_bank_validation(self.application, self.bank_name,
                                              self.bank_account_number)

        name_bank_validation_obj = NameBankValidation.objects.get_or_none(
            id=resp["name_bank_validation_id"])
        self.assertTrue(name_bank_validation_obj is not None)

        name_bank_validation_history = NameBankValidationHistory.objects.filter(
            name_bank_validation=name_bank_validation_obj)
        self.assertEqual(name_bank_validation_history.count(), 2)

        self.assertTrue(BankNameValidationLog.objects.filter(
            application=self.application,
            validation_id=1234
        ).exists())

    @mock.patch('juloserver.disbursement.services.get_service')
    def test_trigger_grab_name_bank_validation_invalid_method_empty(self, mock_get_service):
        self.application.method = ""
        self.application.save()

        mock_service = MockValidationProcessService(
            data_to_return={
                "status": NameBankValidationStatus.SUCCESS,
                "validated_name": self.customer.fullname.lower(),
                "id": 1234,
                "reason": "",
                "error_message": ""
            }
        )
        mock_get_service.return_value = mock_service

        svc = GrabChangeBankAccountService()
        resp = svc.trigger_grab_name_bank_validation(self.application, self.bank_name,
                                              self.bank_account_number)

        name_bank_validation_obj = NameBankValidation.objects.get_or_none(
            id=resp["name_bank_validation_id"])
        self.assertTrue(name_bank_validation_obj is not None)

        name_bank_validation_history = NameBankValidationHistory.objects.filter(
            name_bank_validation=name_bank_validation_obj)
        self.assertEqual(name_bank_validation_history.count(), 2)

        self.assertTrue(BankNameValidationLog.objects.filter(
            application=self.application,
            validation_id=1234
        ).exists())

    @mock.patch('juloserver.disbursement.services.get_service')
    def test_trigger_grab_name_bank_validation_invalid_name_in_bank(self, mock_get_service):
        mock_service = MockValidationProcessService(
            data_to_return={
                "status": NameBankValidationStatus.SUCCESS,
                "validated_name": "another name",
                "id": 1234,
                "reason": "",
                "error_message": ""
            }
        )
        mock_get_service.return_value = mock_service

        svc = GrabChangeBankAccountService()
        resp = svc.trigger_grab_name_bank_validation(self.application, self.bank_name,
                                              self.bank_account_number)

        name_bank_validation_obj = NameBankValidation.objects.get_or_none(
            id=resp["name_bank_validation_id"])
        self.assertTrue(name_bank_validation_obj is not None)

        self.assertEqual(name_bank_validation_obj.validation_status,
                         NameBankValidationStatus.NAME_INVALID)

        name_bank_validation_history = NameBankValidationHistory.objects.filter(
            name_bank_validation=name_bank_validation_obj)
        self.assertEqual(name_bank_validation_history.count(), 2)

        self.assertTrue(BankNameValidationLog.objects.filter(
            application=self.application,
            validation_id=1234
        ).exists())

    def test_is_name_bank_validation_valid_sucess(self):
        svc = GrabChangeBankAccountService()
        name_bank_validation, is_valid = svc.is_name_bank_validation_valid(
            self.name_bank_validation.id, self.application.id
        )
        self.assertEqual(is_valid, True)
        self.assertEqual(name_bank_validation, self.name_bank_validation)

    def test_is_name_bank_validation_valid_not_found(self):
        svc = GrabChangeBankAccountService()
        name_bank_validation, is_valid = svc.is_name_bank_validation_valid(
            123, self.application.id
        )
        self.assertEqual(is_valid, False)
        self.assertEqual(name_bank_validation, None)

    def test_is_name_bank_validation_valid_bank_name_validation_log_not_found(self):
        name_bank_validation = NameBankValidationFactory()
        svc = GrabChangeBankAccountService()
        name_bank_validation, is_valid = svc.is_name_bank_validation_valid(
            name_bank_validation.id, self.application.id
        )
        self.assertEqual(is_valid, False)
        self.assertEqual(name_bank_validation, None)

    def test_is_name_bank_validation_valid_name_bank_validation_is_not_the_latest(self):
        validation_id = '666'
        name_bank_validation = NameBankValidationFactory(
            bank_code="BCA",
            account_number=self.bank_account_number,
            name_in_bank=self.customer.fullname,
            method=self.method,
            validation_status=NameBankValidationStatus.SUCCESS,
            mobile_phone=self.phone_number,
            attempt=0,
            validation_id=validation_id
        )

        BankNameValidationLogFactory(
            validation_id=validation_id,
            validation_status=NameBankValidationStatus.SUCCESS,
            validated_name=self.customer.fullname,
            account_number=self.bank_account_number,
            method=self.method,
            application=self.application,
            reason="",
        )

        svc = GrabChangeBankAccountService()
        result, is_valid = svc.is_name_bank_validation_valid(
            self.name_bank_validation.id, self.application.id
        )
        self.assertEqual(is_valid, False)
        self.assertEqual(result, None)

        result, is_valid = svc.is_name_bank_validation_valid(
            name_bank_validation.id, self.application.id
        )
        self.assertEqual(is_valid, True)
        self.assertEqual(result, name_bank_validation)

    def test_get_name_bank_validation_status_initiated(self):
        self.name_bank_validation.validation_status = NameBankValidationStatus.INITIATED
        self.name_bank_validation.save()
        svc = GrabChangeBankAccountService()
        result = svc.get_name_bank_validation_status(
            self.name_bank_validation.id,
            self.application.id
        )
        self.assertEqual(result["validation_status"], GrabBankValidationStatus.IN_PROGRESS)

    def test_get_name_bank_validation_status_sucess(self):
        svc = GrabChangeBankAccountService()
        result = svc.get_name_bank_validation_status(
            self.name_bank_validation.id,
            self.application.id
        )
        self.assertEqual(result["validation_status"], GrabBankValidationStatus.SUCCESS)

    def test_get_name_bank_validation_status_failed(self):
        self.name_bank_validation.validation_status = NameBankValidationStatus.FAILED
        self.name_bank_validation.save()
        svc = GrabChangeBankAccountService()
        result = svc.get_name_bank_validation_status(
            self.name_bank_validation.id,
            self.application.id
        )
        self.assertEqual(result["validation_status"], GrabBankValidationStatus.FAILED)

    @mock.patch("juloserver.grab.services.bank_rejection_flow.GrabChangeBankAccountService.is_name_bank_validation_valid")
    def test_get_name_bank_validation_status_invalid_name_bank_validation(self, mock_invalid_name_bank_validation):
        mock_invalid_name_bank_validation.return_value = None, False

        with self.assertRaises(GrabLogicException):
            svc = GrabChangeBankAccountService()
            svc.get_name_bank_validation_status(
                self.name_bank_validation.id,
                self.application.id
            )

    def test_get_name_bank_validation_status_failed_no_bank(self):
        self.name_bank_validation.bank_code = "hohohohoh"
        self.name_bank_validation.save()
        svc = GrabChangeBankAccountService()

        with self.assertRaises(GrabLogicException):
            svc.get_name_bank_validation_status(
                self.name_bank_validation.id,
                self.application.id
            )

    def test_update_bank_application(self):
        self.application.bank_name = "test bank"
        self.application.save()
        self.application.refresh_from_db()

        old_data = {
            "bank_name": "test bank",
            "bank_account_number": self.application.bank_account_number,
            "name_bank_validation_id": str(self.application.name_bank_validation_id)
        }

        self.assertNotEqual(self.application.name_bank_validation_id, self.name_bank_validation.id)
        self.assertNotEqual(self.application.bank_name, self.name_bank_validation.bank_name)
        self.assertNotEqual(self.application.bank_account_number,
                            self.name_bank_validation.account_number)


        mock_validation_status_data = {
            "name_bank_validation_id": self.name_bank_validation.id,
            "bank_name": self.name_bank_validation.bank_name,
            "bank_account_number": self.name_bank_validation.account_number
        }

        svc = GrabChangeBankAccountService()
        is_success, err_msg = svc.update_bank_application(self.application,
                                                          mock_validation_status_data)
        self.assertEqual(is_success, True)
        self.assertEqual(err_msg, None)
        self.application.refresh_from_db()

        self.assertEqual(self.application.name_bank_validation_id, self.name_bank_validation.id)
        self.assertEqual(self.application.bank_name, self.name_bank_validation.bank_name)
        self.assertEqual(self.application.bank_account_number,
                            self.name_bank_validation.account_number)

        new_data = {
            'bank_name': self.application.bank_name,
            'bank_account_number': self.application.bank_account_number,
            "name_bank_validation_id": str(self.application.name_bank_validation_id)
        }

        # why 3? it's because we update 3 field at application object
        application_field_change_count = ApplicationFieldChange.objects.filter(
            application=self.application).count()
        self.assertEqual(application_field_change_count, 3)

        application_field_change = ApplicationFieldChange.objects.filter(
            application=self.application
        )

        for field_change in application_field_change:
            field_name = field_change.field_name
            if field_name in old_data:
                self.assertEqual(field_change.old_value, old_data[field_name])
                self.assertEqual(field_change.new_value, new_data[field_name])

    def test_update_bank_application_invalid_validatation_status_data(self):
        mock_validation_status_data = {
            "name_bank_validation_id": self.name_bank_validation.id,
            "bank_name": self.name_bank_validation.bank_name,
        }

        svc = GrabChangeBankAccountService()
        is_success, err_msg = svc.update_bank_application(self.application,
                                                          mock_validation_status_data)
        self.assertEqual(is_success, False)
        self.assertTrue("key error" in err_msg.lower())

    def test_create_new_bank_destination(self):
        self.assertEqual(
            BankAccountDestination.objects.filter(customer=self.customer).count(),
            0
        )

        svc = GrabChangeBankAccountService()
        svc.bank = self.bank
        svc.name_bank_validation = self.name_bank_validation

        svc.create_new_bank_destination(self.customer)

        self.assertEqual(
            BankAccountDestination.objects.filter(customer=self.customer).count(),
            1
        )

    def test_create_new_bank_destination_no_bank(self):
        svc = GrabChangeBankAccountService()
        svc.name_bank_validation = self.name_bank_validation

        with self.assertRaises(GrabLogicException):
            svc.create_new_bank_destination(self.customer)

    def test_create_new_bank_destination_no_name_bank_validation(self):
        svc = GrabChangeBankAccountService()
        svc.bank = self.bank

        with self.assertRaises(GrabLogicException):
            svc.create_new_bank_destination(self.customer)

    def test_create_new_bank_destination_no_bank_account_category(self):
        svc = GrabChangeBankAccountService()
        svc.bank = self.bank
        svc.name_bank_validation = self.name_bank_validation
        self.bank_category.delete()

        with self.assertRaises(GrabLogicException):
            svc.create_new_bank_destination(self.customer)


class TestGrabMissedCallOtp(TestCase):
    def setUp(self):
        self.phone_number = "6284568125621"
        self.grab_customer_data = GrabCustomerDataFactory(
            otp_status=GrabCustomerData.UNVERIFIED,
            grab_validation_status=True,
            phone_number=self.phone_number,
            token="token_system",
        )
        self.mobile_feature_settings = MobileFeatureSettingFactory(
            feature_name=FeatureSettingName.COMPULSORY,
            is_active=True,
            parameters={
                "mobile_phone_1": {
                    "otp_max_request": 3,
                    "otp_max_validate": 3,
                    "otp_resend_time_sms": 1,
                    "otp_resend_time_miscall": 30,
                },
                "wait_time_seconds": 1440,
            },
        )

    @mock.patch('juloserver.grab.services.services.get_citcall_client')
    def test_request_miscall_otp_new_request(self, mocked_citcall):
        request_id = "1600013232432"
        mocked_client = mock.MagicMock()
        mocked_client.request_otp.return_value = {
            "trxid": "transaction_id",
            "rc": "respond_code_vendor",
            "token": "123433292",
        }
        mocked_citcall.return_value = mocked_client
        return_value = GrabAuthService.request_miscall_otp(
            self.phone_number, request_id, "token_system"
        )
        self.assertIsNotNone(return_value)
        self.assertEqual(return_value['request_id'], mock.ANY)
        self.assertTrue(
            MisCallOTP.objects.filter(
                otp_request_status=MisCallOTPStatus.PROCESSED,
                request_id="transaction_id",
                respond_code_vendor="respond_code_vendor",
                miscall_number="123433292",
            ).exists()
        )
        self.assertTrue(
            OtpRequest.objects.filter(
                phone_number=self.phone_number,
                otp_service_type=OTPType.MISCALL,
                action_type=SessionTokenAction.PHONE_REGISTER,
            ).exists()
        )
        miscall_otp = MisCallOTP.objects.filter(
            otp_request_status=MisCallOTPStatus.PROCESSED,
            request_id="transaction_id",
            respond_code_vendor="respond_code_vendor",
            miscall_number="123433292",
        ).last()
        otp_request = OtpRequest.objects.filter(
            phone_number=self.phone_number,
            otp_service_type=OTPType.MISCALL,
            action_type=SessionTokenAction.PHONE_REGISTER,
        ).last()
        self.assertTrue(
            GrabMisCallOTPTracker.objects.filter(
                miscall_otp=miscall_otp, otp_request=otp_request
            ).exists()
        )
        mocked_citcall.assert_called()
        mocked_client.request_otp.assert_called_with(
            format_e164_indo_phone_number(self.phone_number), CitcallRetryGatewayType.INDO, mock.ANY
        )

    def test_create_new_otp_request_missed_call(self):
        request_id = "1600013232432"
        return_value = GrabAuthService.create_new_otp_request_missed_call(
            request_id, self.phone_number
        )
        self.assertEqual(type(return_value), OtpRequest)
        self.assertEqual(OTPType.MISCALL, return_value.otp_service_type)

    @mock.patch('django.utils.timezone.localtime')
    def test_get_miscalledotp_creation_active_flags_invalid_otp(self, mocked_current_time):
        existing_otp_request_1 = OtpRequestFactory(
            cdate=(datetime.datetime.now() - datetime.timedelta(minutes=1)),
            phone_number=self.phone_number,
            otp_service_type=OTPType.MISCALL,
            action_type=SessionTokenAction.PHONE_REGISTER,
            is_used=False,
        )
        current_time = datetime.datetime.now() - datetime.timedelta(seconds=100)
        previous_otp_time = datetime.datetime.now() - datetime.timedelta(seconds=260)
        previous_otp_time_2 = datetime.datetime.now() - datetime.timedelta(seconds=380)
        mocked_current_time.side_effect = [
            current_time,
            previous_otp_time,
            current_time,
            previous_otp_time_2,
        ]
        existing_otp_request_2 = get_latest_available_otp_request_grab(
            [OTPType.MISCALL], self.phone_number
        )
        self.assertEqual(existing_otp_request_1, existing_otp_request_2)
        create_new_otp, is_resent_otp = get_missed_called_otp_creation_active_flags(
            existing_otp_request_1, 150, 300, 1
        )
        self.assertTrue(create_new_otp)
        self.assertTrue(is_resent_otp)

    @mock.patch('django.utils.timezone.localtime')
    def test_get_miscalledotp_creation_active_flags_validotp(self, mocked_current_time):
        existing_otp_request_1 = OtpRequestFactory(
            cdate=(datetime.datetime.now() - datetime.timedelta(minutes=10)),
            phone_number=self.phone_number,
            otp_service_type=OTPType.MISCALL,
            action_type=SessionTokenAction.PHONE_REGISTER,
            is_used=False,
        )
        current_time = datetime.datetime.now() - datetime.timedelta(seconds=0)
        previous_otp_time = datetime.datetime.now() - datetime.timedelta(seconds=180)
        previous_otp_time_2 = datetime.datetime.now() - datetime.timedelta(seconds=380)
        mocked_current_time.side_effect = [
            current_time,
            previous_otp_time,
            current_time,
            previous_otp_time_2,
        ]
        existing_otp_request_2 = get_latest_available_otp_request_grab(
            [OTPType.MISCALL], self.phone_number
        )
        self.assertEqual(existing_otp_request_1, existing_otp_request_2)
        create_new_otp, is_resent_otp = get_missed_called_otp_creation_active_flags(
            existing_otp_request_1, 180, 300, 1
        )
        self.assertFalse(create_new_otp)
        self.assertFalse(is_resent_otp)

    @mock.patch('django.utils.timezone.localtime')
    def test_get_miscalledotp_creation_active_flags_valid_create_otp(self, mocked_current_time):
        current_time = datetime.datetime.now() - datetime.timedelta(seconds=100)
        previous_otp_time = datetime.datetime.now() - datetime.timedelta(seconds=260)
        previous_otp_time_2 = datetime.datetime.now() - datetime.timedelta(seconds=380)
        mocked_current_time.side_effect = [
            current_time,
            previous_otp_time,
            current_time,
            previous_otp_time_2,
        ]
        create_new_otp, is_resent_otp = get_missed_called_otp_creation_active_flags(
            None, 150, 300, 1
        )
        self.assertTrue(create_new_otp)
        self.assertFalse(is_resent_otp)

    @mock.patch('django.utils.timezone.localtime')
    def test_get_miscalledotp_creation_active_flags_invalid_create(self, mocked_current_time):
        existing_otp_request = OtpRequestFactory(
            cdate=(datetime.datetime.now() - datetime.timedelta(minutes=5)),
            phone_number=self.phone_number,
            otp_service_type=OTPType.MISCALL,
            action_type=SessionTokenAction.PHONE_REGISTER,
            is_used=False,
        )
        current_time = datetime.datetime.now() - datetime.timedelta(seconds=310)
        previous_otp_time = datetime.datetime.now() - datetime.timedelta(seconds=260)
        previous_otp_time_2 = datetime.datetime.now() - datetime.timedelta(seconds=380)
        mocked_current_time.side_effect = [
            current_time,
            previous_otp_time,
            current_time,
            previous_otp_time_2,
        ]

        create_new_otp, is_resent_otp = get_missed_called_otp_creation_active_flags(
            existing_otp_request, 150, 300, 1
        )
        self.assertFalse(create_new_otp)
        self.assertFalse(is_resent_otp)


class TestEmergencyContactService(TestCase):
    def get_mock_redis_client(self):
        class MockRedis(object):
            def srem(self, key, *values):
                pass

            def smembers(self, key):
                return ['haha'.encode()]

            def sadd(self, key, data):
                pass

        return MockRedis()

    def get_mock_sms_client(self):
        class MockJuloSmsClient(object):
            CommsProviderLookupFactory(provider_name="whatsapp_service")
            def send_sms(self, phone_number, message, is_otp=False):
                return message, {
                    "messages": [
                        {
                            "to": "666",
                            "message": "message",
                            "status": 1,
                            "julo_sms_vendor": "whatsapp_service",
                            "message-id": 666
                        }
                    ]
                }

        return MockJuloSmsClient()

    def setUp(self):
        self.applications = []
        for _ in range(10):
            self.applications.append(ApplicationFactory())

    def test_generate_unique_link(self):
        temp_unique_link = set()
        service = EmergencyContactService(redis_client=None, sms_client=None)
        for application in self.applications:
            unique_link = service.generate_unique_link(
                application_id=application.id,
                application_kin_name=application.kin_name
            )
            self.assertTrue(unique_link not in temp_unique_link)
            temp_unique_link.add(unique_link)

    def test_save_application_id_to_redis(self):
        redis_client = self.get_mock_redis_client()
        service = EmergencyContactService(redis_client=redis_client, sms_client=None)
        for application in self.applications:
            service.save_application_id_to_redis(application.id)

    def test_pop_application_ids_from_redis(self):
        redis_client = self.get_mock_redis_client()
        service = EmergencyContactService(redis_client=redis_client, sms_client=None)
        for _ in service.pop_application_ids_from_redis():
            pass

    @freeze_time("2024-01-01")
    def test_set_expired_time(self):
        service = EmergencyContactService(redis_client=None, sms_client=None)
        result = service.set_expired_time(4)
        self.assertEqual(timezone.localtime(timezone.now()) + timedelta(hours=4), result)

    @mock.patch("juloserver.grab.services.services.shorten_url")
    def test_send_sms_to_ec(self, mock_shorten_url):
        mock_shorten_url.return_value = "google.com"
        service = EmergencyContactService(
            redis_client=None,
            sms_client=self.get_mock_sms_client()
        )
        unique_link = service.generate_unique_link(
            application_id=self.applications[0].id,
            application_kin_name=self.applications[0].kin_name
        )
        hashed_unique_link = service.hashing_unique_link(unique_link)
        self.assertTrue(
            service.send_sms_to_ec(
                self.applications[0].id,
                unique_link=unique_link,
                hashed_unique_link=hashed_unique_link
            )
        )
        self.assertNotEqual([], list(SmsHistory.objects.all()))
        mock_shorten_url.assert_called()

    def test_hashing_unique_link(self):
        service = EmergencyContactService(
            redis_client=None,
            sms_client=None
        )
        unique_link = "emergency-contact-testing"
        hashed_unique_link = service.hashing_unique_link(unique_link)
        self.assertTrue(service.validate_hashing(unique_link, hashed_unique_link))

    def test_hashing_unique_link_invalid_hashing_value(self):
        service = EmergencyContactService(
            redis_client=None,
            sms_client=None
        )
        unique_link = "emergency-contact-testing"
        hashed_unique_link = "random-stringasdf23"
        self.assertFalse(service.validate_hashing(unique_link, hashed_unique_link))

        # try hashing without secret key
        unique_link = "emergency-contact-testing"
        hash_object = hashlib.sha256()
        hash_object.update(unique_link.encode('utf-8'))
        hashed_unique_link = hash_object.hexdigest()
        self.assertFalse(service.validate_hashing(unique_link, hashed_unique_link))

    def test_is_ec_approval_link_valid(self):
        application = ApplicationFactory()
        unique_link = "test-unique-link"
        ec_approval_link = EmergencyContactApprovalLinkFactory()
        ec_approval_link.unique_link = unique_link
        ec_approval_link.application_id = application.id
        ec_approval_link.expiration_date = timezone.localtime(timezone.now() + timedelta(hours=5))
        ec_approval_link.save()

        service = EmergencyContactService(redis_client=None, sms_client=None)
        app_id, is_valid = service.is_ec_approval_link_valid(unique_link)
        self.assertEqual(app_id, application.id)
        self.assertTrue(is_valid)

    def test_is_ec_approval_link_valid_invalid_unique_link(self):
        application = ApplicationFactory()
        unique_link = "test-unique-link"
        ec_approval_link = EmergencyContactApprovalLinkFactory()
        ec_approval_link.unique_link = unique_link
        ec_approval_link.application_id = application.id
        ec_approval_link.expiration_date = timezone.localtime(timezone.now() + timedelta(hours=5))
        ec_approval_link.save()

        service = EmergencyContactService(redis_client=None, sms_client=None)
        _, is_valid = service.is_ec_approval_link_valid("not-valid")
        self.assertTrue(not is_valid)

    def test_proccess_ec_response(self):
        service = EmergencyContactService(redis_client=None, sms_client=None)

        for response in [{'response': 1}, {'response': 2}]:
            application = ApplicationFactory()
            self.assertEqual(application.is_kin_approved, None)

            service.proccess_ec_response(application.id, response)
            application.refresh_from_db()
            self.assertEqual(application.is_kin_approved, response['response'])

    @freeze_time("2024-01-01T20:00:00+07:00")
    def test_get_expired_emergency_approval_link_queryset(self):
        service = EmergencyContactService(redis_client=None, sms_client=None)
        for i in range(5):
            ec = EmergencyContactApprovalLinkFactory()
            ec.unique_link = 'unique-link-{}'.format(i)
            ec.expiration_date = timezone.localtime(timezone.now()) - timedelta(days=1)
            ec.save()

        qs = service.get_expired_emergency_approval_link_queryset()
        self.assertTrue(qs.exists())

    @freeze_time("2024-01-01T20:00:00+07:00")
    def test_get_expired_emergency_approval_link_queryset_no_exists(self):
        service = EmergencyContactService(redis_client=None, sms_client=None)
        for i in range(5):
            ec = EmergencyContactApprovalLinkFactory()
            ec.unique_link = 'unique-link-{}'.format(i)
            ec.expiration_date = timezone.localtime(timezone.now()) + timedelta(hours=1)
            ec.save()

        qs = service.get_expired_emergency_approval_link_queryset()
        self.assertFalse(qs.exists())

    @freeze_time("2024-01-01T20:00:00+07:00")
    def test_auto_reject_ec_consent(self):
        service = EmergencyContactService(redis_client=None, sms_client=None)
        ec_ids = []
        application_ids = []
        for i in range(5):
            application = ApplicationFactory()
            ec = EmergencyContactApprovalLinkFactory()
            ec_ids.append(ec.id)
            application_ids.append(application.id)
            ec.unique_link = 'unique-link-{}'.format(i)
            ec.expiration_date = timezone.localtime(timezone.now()) - timedelta(days=1)
            ec.application_id = application.id
            ec.save()

        qs = EmergencyContactApprovalLink.objects.filter(id__in=ec_ids)
        self.assertFalse(qs.filter(is_used=True).exists())

        applications = Application.objects.filter(id__in=application_ids, is_kin_approved=2)
        self.assertFalse(applications.exists())


        service.auto_reject_ec_consent(expired_ec_approval_link_qs=qs)

        qs = EmergencyContactApprovalLink.objects.filter(id__in=ec_ids)
        self.assertEqual(qs.filter(is_used=True).count(), len(ec_ids))

        applications = Application.objects.filter(id__in=application_ids, is_kin_approved=2)
        self.assertEqual(applications.count(), len(application_ids))

    def test_is_ec_received_sms_before(self):
        customer = CustomerFactory()
        kin_mobile_phone = "+62812233386602"
        app = ApplicationFactory(customer=customer)
        app.kin_mobile_phone = kin_mobile_phone
        app.save()

        service = EmergencyContactService(redis_client=None, sms_client=None)
        self.assertFalse(service.is_ec_received_sms_before(app.id))
        SmsHistoryFactory(
            application=app,
            customer=customer,
            to_mobile_phone=kin_mobile_phone,
            template_code="grab_emergency_contact"
        )
        self.assertTrue(service.is_ec_received_sms_before(app.id))

    def test_is_ec_received_sms_before_with_hour(self):
        customer = CustomerFactory()
        kin_mobile_phone = "+62812233386602"
        app = ApplicationFactory(customer=customer)
        app.kin_mobile_phone = kin_mobile_phone
        app.save()

        service = EmergencyContactService(redis_client=None, sms_client=None)
        sms_history = SmsHistoryFactory(
            application=app,
            customer=customer,
            to_mobile_phone=kin_mobile_phone,
            template_code="grab_emergency_contact"
        )
        sms_history.cdate = timezone.localtime(timezone.now()) - timedelta(hours=24)
        sms_history.save()

        self.assertFalse(service.is_ec_received_sms_before(app.id, 24))
        self.assertTrue(service.is_ec_received_sms_before(app.id, 25))

    def test_get_ec_that_need_to_resend_sms(self):
        application = ApplicationFactory()
        unique_link = "test-unique-link"
        ec_approval_link = EmergencyContactApprovalLinkFactory()
        ec_approval_link.unique_link = unique_link
        ec_approval_link.application_id = application.id
        ec_approval_link.expiration_date = timezone.localtime(timezone.now() + timedelta(hours=5))
        ec_approval_link.save()

        service = EmergencyContactService(redis_client=None, sms_client=None)
        counter = 0
        for qs in service.get_ec_that_need_to_resend_sms():
            counter += 1
            self.assertNotEqual(len(qs), 0)
        self.assertNotEqual(counter, 0)

    def test_get_ec_that_need_to_resend_sms_sms_history_created_before_in_24_hours(self):
        customer = CustomerFactory()
        kin_mobile_phone = "+62812233386602"

        application = ApplicationFactory(customer=customer)
        unique_link = "test-unique-link"
        ec_approval_link = EmergencyContactApprovalLinkFactory()
        ec_approval_link.unique_link = unique_link
        ec_approval_link.application_id = application.id
        ec_approval_link.expiration_date = timezone.localtime(timezone.now() + timedelta(hours=5))
        ec_approval_link.save()

        SmsHistoryFactory(
            application=application,
            customer=customer,
            to_mobile_phone=kin_mobile_phone,
            template_code="grab_emergency_contact"
        )

        service = EmergencyContactService(redis_client=None, sms_client=None)
        counter = 0
        for qs in service.get_ec_that_need_to_resend_sms():
            counter += 1
            self.assertEqual(len(qs), 0)
        self.assertEqual(counter, 1)

    def test_get_ec_that_need_to_resend_sms_sms_history_created_before_more_than_24_hours(self):
        customer = CustomerFactory()
        kin_mobile_phone = "+62812233386602"

        application = ApplicationFactory(customer=customer)
        unique_link = "test-unique-link"
        ec_approval_link = EmergencyContactApprovalLinkFactory()
        ec_approval_link.unique_link = unique_link
        ec_approval_link.application_id = application.id
        ec_approval_link.expiration_date = timezone.localtime(timezone.now() + timedelta(hours=5))
        ec_approval_link.save()

        with freeze_time("2024-01-01"):
            SmsHistoryFactory(
                application=application,
                customer=customer,
                to_mobile_phone=kin_mobile_phone,
                template_code="grab_emergency_contact"
            )

        service = EmergencyContactService(redis_client=None, sms_client=None)
        counter = 0
        for qs in service.get_ec_that_need_to_resend_sms():
            counter += 1
            self.assertNotEqual(len(qs), 0)
        self.assertNotEqual(counter, 0)


class TestGrabPayments(TestCase):
    def setUp(self):
        self.loan_amount = 1363636
        self.loan_duration_days = 60
        self.monthly_interest_rate = 5

        self.loan_amount1 = 1000000
        self.loan_duration_days1 = 180
        self.monthly_interest_rate1 = 4

    def test_compute_payment_installment_grab(self):
        installment_principal, derived_interest, installment_amount = (
            compute_payment_installment_grab(self.loan_amount, self.loan_duration_days, self.monthly_interest_rate)
        )
        self.assertEqual(installment_principal, 22727)
        self.assertEqual(derived_interest, 2273)
        self.assertEqual(installment_amount, 25000)

        principal, interest, installment = compute_final_payment_principal_grab(
            self.loan_amount,
            self.loan_duration_days,
            self.monthly_interest_rate,
            installment_principal,
            derived_interest
        )

        self.assertEqual(principal, 22743)
        self.assertEqual(interest, 2257)
        self.assertEqual(installment, 25000)

    def test_get_loan_repayment_amount(self):
        repayment_amount = (
            get_loan_repayment_amount(self.loan_amount1, self.loan_duration_days1, self.monthly_interest_rate1)
        )
        self.assertEqual(repayment_amount, 1240000)


class TestGrabRestructureHistoryLogService(TestCase):
    def setUp(self):
        from juloserver.grab.tests.utils import ensure_grab_restructure_history_log_table_exists

        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB)

        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line, admin_fee=40000)

        ensure_grab_restructure_history_log_table_exists()

    def test_create_restructure_entry_bulk(self):
        data = []
        loan_ids = []
        for _ in range(5):
            loan = LoanFactory()
            loan_ids.append(loan.id)
            data.append({
                "loan_id": loan.id,
                "restructure_date": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S+0700")
            })

        service = GrabRestructureHistoryLogService()
        service.create_restructure_history_entry_bulk(datas=data, is_restructured=True)
        self.assertEqual(
            GrabRestructreHistoryLog.objects.filter(
                loan_id__in=loan_ids, is_restructured=True).count(),
            len(loan_ids)
        )

    def test_create_restructure_revert_entry_bulk(self):
        data = []
        loan_ids = []
        for _ in range(5):
            loan = LoanFactory()
            loan_ids.append(loan.id)
            data.append({
                "loan_id": loan.id,
                "restructure_date": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S+0700")
            })

        service = GrabRestructureHistoryLogService()
        service.create_restructure_history_entry_bulk(datas=data, is_restructured=False)
        self.assertEqual(
            GrabRestructreHistoryLog.objects.filter(
                loan_id__in=loan_ids, is_restructured=False).count(),
            len(loan_ids)
        )
