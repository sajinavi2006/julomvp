from datetime import datetime, date, timedelta

from django.db.models import Sum, QuerySet
from django.test.testcases import TestCase

from django.utils import timezone

from unittest.mock import MagicMock
from mock import patch

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    AccountLookupFactory,
    AccountFactory,
)
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.constants import WorkflowConst, FeatureNameConst
from juloserver.dana.constants import DanaProductType
from juloserver.dana.onboarding.services import (
    check_fullname_with_DTTOT,
    check_customer_fraud,
    check_customer_delinquent,
    process_completed_application_data,
)
from juloserver.dana.models import DanaPaymentBill, DanaCustomerData
from juloserver.dana.loan.services import (
    create_payments_from_bill_detail,
    dana_max_creditor_check,
    dana_validate_dbr,
    dana_validate_dbr_in_bulk,
    update_available_limit_dana,
)
from juloserver.dana.tests.factories import (
    DanaCustomerDataFactory,
    DanaPaymentBillFactory,
    DanaAccountPaymentFactory,
    DanaLoanReferenceFactory,
)
from juloserver.dana.utils import round_half_up
from juloserver.dana.repayment.services import update_late_fee_amount
from juloserver.dana.repayment.tasks import trigger_update_late_fee_amount
from juloserver.julo.models import Payment, StatusLookup
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes, ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    FDCInquiryFactory,
    LoanFactory,
    ProductLineFactory,
    ProductLookupFactory,
    StatusLookupFactory,
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    WorkflowFactory,
    BlacklistCustomerFactory,
    PartnerFactory,
    PaymentFactory,
    FeatureSettingFactory,
)
from juloserver.loan.constants import DBRConst
from juloserver.partnership.tests.factories import PartnerLoanRequestFactory
from juloserver.payment_point.models import TransactionMethod


class TestUpdateAvailableLimitDanaService(TestCase):
    def setUp(self) -> None:
        self.user_auth = AuthUserFactory()
        self.user2 = AuthUserFactory()
        self.user3 = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user2, name=PartnerNameConstant.DANA)
        self.account = AccountFactory()
        self.account_limit = AccountLimitFactory(account=self.account)

        self.loan_decrease_limit = LoanFactory(
            account=self.account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE),
        )
        self.partner_loan_request_decrease = PartnerLoanRequestFactory(
            loan=self.loan_decrease_limit,
            loan_amount=self.loan_decrease_limit.loan_amount,
            partner=self.partner,
            loan_disbursement_amount=self.loan_decrease_limit.loan_disbursement_amount,
        )

        self.loan_increase_limit = LoanFactory(
            account=self.account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER),
        )
        self.partner_loan_request_increase = PartnerLoanRequestFactory(
            loan=self.loan_increase_limit,
            loan_amount=self.loan_increase_limit.loan_amount,
            partner=self.partner,
            loan_disbursement_amount=self.loan_increase_limit.loan_disbursement_amount,
        )

    def test_reduce_available_limit(self) -> None:
        current_account_limit = self.account_limit.available_limit
        update_available_limit_dana(self.loan_decrease_limit, self.loan_increase_limit)
        self.account_limit.refresh_from_db()
        self.assertEqual(
            self.account_limit.available_limit,
            current_account_limit - self.loan_decrease_limit.loan_amount,
        )

    def test_increase_available_limit(self) -> None:
        current_account_limit = self.account_limit.available_limit
        update_available_limit_dana(self.loan_increase_limit, self.partner_loan_request_increase)
        self.account_limit.refresh_from_db()
        self.assertEqual(
            self.account_limit.available_limit,
            current_account_limit + self.loan_decrease_limit.loan_amount,
        )


class TestCreatePaymentsFromBillDetailService(TestCase):
    def setUp(self) -> None:
        StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        self.loan = LoanFactory()
        self.loan.payment_set.all().delete()
        self.bill_details = [
            {
                "billId": "0000011",
                "periodNo": "1",
                "principalAmount": {"value": "22000.00", "currency": "IDR"},
                "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "totalAmount": {"value": "22000.00", "currency": "IDR"},
                "dueDate": "20221008",
            },
            {
                "billId": "0000012",
                "periodNo": "2",
                "principalAmount": {"value": "22000.00", "currency": "IDR"},
                "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "totalAmount": {"value": "22000.00", "currency": "IDR"},
                "dueDate": "20221008",
            },
            {
                "billId": "0000013",
                "periodNo": "3",
                "principalAmount": {"value": "22000.00", "currency": "IDR"},
                "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "totalAmount": {"value": "22000.00", "currency": "IDR"},
                "dueDate": "20221008",
            },
            {
                "billId": "0000014",
                "periodNo": "4",
                "principalAmount": {"value": "22000.00", "currency": "IDR"},
                "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "lateFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "totalAmount": {"value": "22000.00", "currency": "IDR"},
                "dueDate": "20221008",
            },
        ]

    def test_success_create_payment_and_dana_payment_bill(self) -> None:
        create_payments_from_bill_detail(self.bill_details, self.loan)
        n_bill_details = len(self.bill_details)
        n_payments = Payment.objects.filter(loan=self.loan).count()
        n_dana_payment_bills = DanaPaymentBill.objects.all().count()

        self.assertEqual(n_bill_details, n_payments)
        self.assertEqual(n_bill_details, n_dana_payment_bills)
        self.assertEqual(n_payments, n_dana_payment_bills)


class TestDanaServices(TestCase):
    def setUp(self) -> None:
        self.user_auth = AuthUserFactory()
        self.user2 = AuthUserFactory()
        self.user3 = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user2, name=PartnerNameConstant.DANA)
        self.customer = CustomerFactory(
            user=self.user_auth, nik='1601260506021276', phone='082231457590'
        )
        self.account_lookup = AccountLookupFactory()
        self.workflow = WorkflowFactory(name=WorkflowConst.DANA, handler='DanaWorkflowHandler')

        inactive_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.inactive)
        self.account = AccountFactory(customer=self.customer, status=inactive_status_code)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            ktp=self.customer.nik,
            mobile_phone_1=self.customer.phone,
            account=self.account,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier='111222333444',
            customer=self.customer,
            nik=self.customer.nik,
            mobile_number=self.customer.phone,
            partner=self.partner,
            full_name=self.customer.fullname,
            proposed_credit_limit=1_000_000,
            registration_time=timezone.localtime(timezone.now()),
        )

    @patch('juloserver.dana.onboarding.services.set_redis_key')
    def test_blacklist_customer(self, _: MagicMock) -> None:
        BlacklistCustomerFactory(
            citizenship='Indonesia', fullname_trim='test-user', name='Test User'
        )

        self.customer.fullname = 'Test user'
        self.customer.save(update_fields=['fullname'])

        # Blacklist
        is_blacklisted = check_fullname_with_DTTOT(self.customer.fullname)
        self.assertEquals(is_blacklisted, True)

        # Not blacklisted
        is_blacklisted = check_fullname_with_DTTOT('User 2')
        self.assertEquals(is_blacklisted, False)

    def test_check_customer_delinquent(self) -> None:
        # Not delinquent
        is_delinquent = check_customer_delinquent(self.dana_customer_data, self.application.id)
        self.assertEqual(is_delinquent, False)

        # Delinquent
        self.customer2 = CustomerFactory(
            user=self.user3, nik='160126050602120', phone='082231457590'
        )
        fraud_status = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active_in_grace)
        self.account2 = AccountFactory(customer=self.customer, status=fraud_status)
        self.application2 = ApplicationFactory(
            customer=self.customer2,
            workflow=self.workflow,
            ktp=self.dana_customer_data.nik,
            mobile_phone_1=self.dana_customer_data.mobile_number,
            account=self.account2,
        )

        is_delinquent = check_customer_delinquent(self.dana_customer_data, self.application.id)
        self.assertEqual(is_delinquent, True)

    @patch('juloserver.dana.onboarding.services.set_redis_key')
    def test_check_customer_fraud(self, _: MagicMock) -> None:
        # Not Fraud
        is_fraud = check_customer_fraud(self.dana_customer_data, self.application.id)
        self.assertEqual(is_fraud, False)

        # Fraud
        self.customer2 = CustomerFactory(
            user=self.user3, nik='160126050602120', phone='082231457590'
        )
        fraud_status = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.fraud_reported)
        self.account2 = AccountFactory(customer=self.customer, status=fraud_status)
        self.application2 = ApplicationFactory(
            customer=self.customer2,
            workflow=self.workflow,
            ktp=self.dana_customer_data.nik,
            mobile_phone_1='082231457212',
            account=self.account2,
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
            ),
        )
        is_fraud = check_customer_fraud(self.dana_customer_data, self.application.id)
        self.assertEqual(is_fraud, True)

        # Fraud because mobile phone 2 same in dana customer data
        self.application2.mobile_phone_2 = self.dana_customer_data.mobile_number
        self.application2.save(update_fields=['mobile_phone_2'])

        is_fraud = check_customer_fraud(self.dana_customer_data, self.application.id)
        self.assertEqual(is_fraud, True)

        # Fraud because spouse mobile phone
        self.application2.mobile_phone_2 = '0870000000000'
        self.application2.spouse_mobile_phone = self.dana_customer_data.mobile_number
        self.application2.save(update_fields=['mobile_phone_2', 'spouse_mobile_phone'])

        is_fraud = check_customer_fraud(self.dana_customer_data, self.application.id)
        self.assertEqual(is_fraud, True)

        # Fraud because kin mobile phone
        self.application2.spouse_mobile_phone = None
        self.application2.kin_mobile_phone = self.dana_customer_data.mobile_number
        self.application2.save(update_fields=['mobile_phone_2', 'kin_mobile_phone'])

        is_fraud = check_customer_fraud(self.dana_customer_data, self.application.id)
        self.assertEqual(is_fraud, True)


class TestDanaUpdateLateFeeAmount(TestCase):
    def setUp(self) -> None:
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.DANA_LATE_FEE,
            parameters={'late_fee': 0.0015},
            is_active=True,
            category='dana',
            description='This configuration is used to adjust dana late fee',
        )
        user = AuthUserFactory()
        self.user_partner = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user_partner, name="dana")

        self.status_lookup = StatusLookupFactory()

        workflow = WorkflowFactory(name=WorkflowConst.DANA, handler='DanaWorkflowHandler')
        customer = CustomerFactory(user=user)
        self.application = ApplicationFactory(
            customer=customer, workflow=workflow, partner=self.partner
        )
        self.account_lookup = AccountLookupFactory(
            workflow=workflow, name='DANA', payment_frequency='weekly'
        )
        self.account = AccountFactory(
            customer=customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            account=self.account,
            customer=customer,
            partner=self.partner,
            dana_customer_identifier="12345679237",
            dob=date(2023, 1, 1),
        )
        self.account_payment = DanaAccountPaymentFactory(
            late_fee_amount=3500, due_date=date.today() - timedelta(days=2), paid_late_fee=1000
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            loan_duration=4,
            loan_amount=1080000,
        )
        self.partner_loan = PartnerLoanRequestFactory(
            loan=self.loan,
            partner=self.partner,
            loan_amount=self.loan.loan_amount,
            loan_disbursement_amount=self.loan.loan_disbursement_amount,
        )
        self.payment = self.loan.payment_set.last()
        self.payment.payment_status = StatusLookup.objects.get(pk=PaymentStatusCodes.PAYMENT_180DPD)
        self.payment.due_date = self.account_payment.due_date
        self.payment.account_payment = self.account_payment
        self.payment.save(update_fields=['payment_status', 'due_date', 'account_payment'])
        self.payment.refresh_from_db()
        self.dana_payment_bill = DanaPaymentBillFactory(
            payment_id=self.payment.id, bill_id="1001001"
        )
        self.dana_loan_reference = DanaLoanReferenceFactory(
            customer_id=customer.id,
            loan=self.loan,
            late_fee_rate=0.15,
        )

    def test_update_late_fee_amount_task(self):
        # Calculation To compare late_fee_amount
        due_amount_before = self.payment.due_amount
        principal_amount = self.payment.installment_principal - self.payment.paid_principal
        interest_amount = self.payment.installment_interest - self.payment.paid_interest
        bill_amount = principal_amount + interest_amount
        late_fee = self.dana_loan_reference.late_fee_rate / 100
        raw_late_fee = bill_amount * late_fee
        rounded_late_fee = int(round_half_up(raw_late_fee))
        late_fee_amount = self.payment.late_fee_amount + rounded_late_fee

        # Run trigger_update_late_fee_amoun
        trigger_update_late_fee_amount()

        self.payment.refresh_from_db()

        # Get late fee amount
        new_late_fee_amount = self.payment.late_fee_amount
        # Compare late_fee_amount
        self.assertEqual(late_fee_amount, new_late_fee_amount)


class TestDanaMigrateDataLastApplicationToNewApplicationForPusdafil(TestCase):
    def setUp(self) -> None:
        self.user_auth = AuthUserFactory()
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name=PartnerNameConstant.DANA)
        self.customer = CustomerFactory(
            user=self.user_auth, nik='1601260506021271', phone='082231457590'
        )
        self.account_lookup = AccountLookupFactory()
        self.workflow = WorkflowFactory(name=WorkflowConst.DANA, handler='DanaWorkflowHandler')
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            ktp=self.customer.nik,
            mobile_phone_1=self.customer.phone,
            account=self.account,
            gender="Pria",
            address_kabupaten="JAKARTA SELATAN",
            address_provinsi="JAKARTA",
            address_kodepos="12345",
            marital_status="Cerai",
            job_type="Tidak bekerja",
            job_industry="Tidak bekerja",
            monthly_income=1000000,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier='111222333444',
            customer=self.customer,
            nik='1601260506021270',
            mobile_number=self.customer.phone,
            partner=self.partner,
            full_name=self.customer.fullname,
            proposed_credit_limit=1_000_000,
            registration_time=timezone.localtime(timezone.now()),
            lender_product_id=DanaProductType.CICIL,
        )
        self.dana_customer_data.application = self.application
        self.dana_customer_data.save()

    def test_success_migrate_all_data_to_new_application(self) -> None:
        """case if last application have completed data for required sending to pusdafil"""
        user_auth = AuthUserFactory()
        customer = CustomerFactory(user=user_auth, nik='1601260506021272', phone='082231457590')
        account = AccountFactory(customer=customer)
        application = ApplicationFactory(
            customer=customer,
            workflow=self.workflow,
            ktp=customer.nik,
            mobile_phone_1=customer.phone,
            account=account,
        )
        dana_customer_data = DanaCustomerData.objects.create(
            dana_customer_identifier='111222333444',
            customer=customer,
            nik='1601260506021270',
            mobile_number=customer.phone,
            partner=self.partner,
            full_name=customer.fullname,
            proposed_credit_limit=1_000_000,
            registration_time=timezone.localtime(timezone.now()),
            lender_product_id=DanaProductType.CASH_LOAN,
        )
        dana_customer_data.application = application
        dana_customer_data.save()
        process_completed_application_data(application.pk)
        application.refresh_from_db()
        self.assertEquals(application.gender, self.application.gender)
        self.assertEquals(application.address_kabupaten, self.application.address_kabupaten)
        self.assertEquals(application.address_provinsi, self.application.address_provinsi)
        self.assertEquals(application.address_kodepos, self.application.address_kodepos)
        self.assertEquals(application.marital_status, self.application.marital_status)
        self.assertEquals(application.job_type, self.application.job_type)
        self.assertEquals(application.job_industry, self.application.job_industry)
        self.assertEquals(application.monthly_income, self.application.monthly_income)

    def test_success_migrate_partial_data_to_new_application(self) -> None:
        """case if last application have partially completed data for required sending to pusdafil"""
        self.application.gender = None
        self.application.address_kabupaten = None
        self.application.address_provinsi = None
        self.application.address_kodepos = None
        self.application.save()
        user_auth = AuthUserFactory()
        customer = CustomerFactory(user=user_auth, nik='1601260506021272', phone='082231457590')
        account = AccountFactory(customer=customer)
        application = ApplicationFactory(
            customer=customer,
            workflow=self.workflow,
            ktp=customer.nik,
            mobile_phone_1=customer.phone,
            account=account,
        )
        dana_customer_data = DanaCustomerData.objects.create(
            dana_customer_identifier='111222333444',
            customer=customer,
            nik='1601260506021270',
            mobile_number=customer.phone,
            partner=self.partner,
            full_name=customer.fullname,
            proposed_credit_limit=1_000_000,
            registration_time=timezone.localtime(timezone.now()),
            lender_product_id="CASH_LOAN_JULO_01",
        )
        dana_customer_data.application = application
        dana_customer_data.save()
        process_completed_application_data(application.pk)
        application.refresh_from_db()
        self.assertNotEqual(application.gender, self.application.gender)
        self.assertNotEqual(application.address_kabupaten, self.application.address_kabupaten)
        self.assertNotEqual(application.address_provinsi, self.application.address_provinsi)
        self.assertNotEqual(application.address_kodepos, self.application.address_kodepos)
        self.assertEquals(application.marital_status, self.application.marital_status)
        self.assertEquals(application.job_type, self.application.job_type)
        self.assertEquals(application.job_industry, self.application.job_industry)
        self.assertEquals(application.monthly_income, self.application.monthly_income)

    def test_failed_migrate_data_application(self) -> None:
        """case if last application not have completed data for required sending to pusdafil"""
        self.application.gender = None
        self.application.address_kabupaten = None
        self.application.address_provinsi = None
        self.application.address_kodepos = None
        self.application.marital_status = None
        self.application.job_type = None
        self.application.job_industry = None
        self.application.monthly_income = None
        self.application.save()
        self.application.refresh_from_db()
        user_auth = AuthUserFactory()
        customer = CustomerFactory(user=user_auth, nik='1601260506021274', phone='082231457590')
        account = AccountFactory(customer=customer)
        application = ApplicationFactory(
            customer=customer,
            workflow=self.workflow,
            ktp=customer.nik,
            mobile_phone_1=customer.phone,
            account=account,
        )
        dana_customer_data = DanaCustomerData.objects.create(
            dana_customer_identifier='111222333444',
            customer=customer,
            nik='1601260506021270',
            mobile_number=customer.phone,
            partner=self.partner,
            full_name=customer.fullname,
            proposed_credit_limit=1_000_000,
            registration_time=timezone.localtime(timezone.now()),
            lender_product_id=DanaProductType.CASH_LOAN,
        )
        dana_customer_data.application = application
        dana_customer_data.save()
        process_completed_application_data(application.pk)
        application.refresh_from_db()
        self.assertNotEqual(application.gender, self.application.gender)
        self.assertNotEqual(application.address_kabupaten, self.application.address_kabupaten)
        self.assertNotEqual(application.address_provinsi, self.application.address_provinsi)
        self.assertNotEqual(application.address_kodepos, self.application.address_kodepos)
        self.assertNotEqual(application.marital_status, self.application.marital_status)
        self.assertNotEqual(application.job_type, self.application.job_type)
        self.assertNotEqual(application.job_industry, self.application.job_industry)
        self.assertNotEqual(application.monthly_income, self.application.monthly_income)


class TestDanaValidateDBR(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.DBR_RATIO_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "ratio_percentage": DBRConst.DEFAULT_INCOME_PERCENTAGE,
                "popup_banner": DBRConst.DEFAULT_POPUP_BANNER,
                "product_line_ids": DBRConst.DEFAULT_PRODUCT_LINE_IDS,
            },
        )

    def test_success_validate_dbr(self):
        monthly_income = 10000000
        application = ApplicationFactory(
            monthly_income=monthly_income,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.DANA),
        )
        application.application_status_id = 420
        application.save()
        repayment_plan_list = [
            {
                "periodNo": 1,
                "principalAmount": {"value": "25000.00", "currency": "IDR"},
                "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "totalAmount": {"value": "22000.00", "currency": "IDR"},
                "dueDate": "20240401",
            },
            {
                "periodNo": 2,
                "principalAmount": {"value": "22000.00", "currency": "IDR"},
                "interestFeeAmount": {"value": "22000.00", "currency": "IDR"},
                "totalAmount": {"value": "22000.00", "currency": "IDR"},
                "dueDate": "20240515",
            },
        ]

        is_eligible, _ = dana_validate_dbr(application, repayment_plan_list)
        self.assertEqual(is_eligible, True)

    def test_fail_validate_dbr_insuficient_salary(self):
        monthly_income = 50000
        application = ApplicationFactory(
            monthly_income=monthly_income,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.DANA),
        )
        application.application_status_id = 420
        application.save()
        repayment_plan_list = [
            {
                "periodNo": 1,
                "principalAmount": {"value": "50000.00", "currency": "IDR"},
                "interestFeeAmount": {"value": "50000.00", "currency": "IDR"},
                "totalAmount": {"value": "100000.00", "currency": "IDR"},
                "dueDate": "20240401",
            },
            {
                "periodNo": 2,
                "principalAmount": {"value": "50000.00", "currency": "IDR"},
                "interestFeeAmount": {"value": "50000.00", "currency": "IDR"},
                "totalAmount": {"value": "100000.00", "currency": "IDR"},
                "dueDate": "20240515",
            },
        ]

        is_eligible, _ = dana_validate_dbr(application, repayment_plan_list)
        self.assertEqual(is_eligible, False)


class TestDanaValidateDBRInBulk(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.DBR_RATIO_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "ratio_percentage": DBRConst.DEFAULT_INCOME_PERCENTAGE,
                "popup_banner": DBRConst.DEFAULT_POPUP_BANNER,
                "product_line_ids": DBRConst.DEFAULT_PRODUCT_LINE_IDS,
            },
        )

    def test_success_validate_dbr_in_bulk(self):
        monthly_income = 10000000
        application = ApplicationFactory(
            monthly_income=monthly_income,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.DANA),
        )
        application.application_status_id = 420
        application.save()
        installment_plan_list = [
            {
                "installmentPlanId": "installmentPlanIdBiweekly",
                "repaymentPlanList": [
                    {
                        "periodNo": "1",
                        "principalAmount": {"value": "12500.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "1000.00", "currency": "IDR"},
                        "totalAmount": {"value": "13500.00", "currency": "IDR"},
                        "dueDate": "20221013",
                    },
                    {
                        "periodNo": "2",
                        "principalAmount": {"value": "12500.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "1000.00", "currency": "IDR"},
                        "totalAmount": {"value": "13500.00", "currency": "IDR"},
                        "dueDate": "20221027",
                    },
                    {
                        "periodNo": "3",
                        "principalAmount": {"value": "12500.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "1000.00", "currency": "IDR"},
                        "totalAmount": {"value": "13500.00", "currency": "IDR"},
                        "dueDate": "20221113",
                    },
                    {
                        "periodNo": "4",
                        "principalAmount": {"value": "12500.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "1000.00", "currency": "IDR"},
                        "totalAmount": {"value": "13500.00", "currency": "IDR"},
                        "dueDate": "20221127",
                    },
                ],
            },
            {
                "installmentPlanId": "installmentPlanIdWeekly",
                "repaymentPlanList": [
                    {
                        "periodNo": "1",
                        "principalAmount": {"value": "50000.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "4000.00", "currency": "IDR"},
                        "totalAmount": {"value": "54000.00", "currency": "IDR"},
                        "dueDate": "20221013",
                    }
                ],
            },
            {
                "installmentPlanId": "installmentPlanIdMonthly1",
                "repaymentPlanList": [
                    {
                        "periodNo": "1",
                        "principalAmount": {"value": "50000.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "4000.00", "currency": "IDR"},
                        "totalAmount": {"value": "54000.00", "currency": "IDR"},
                        "dueDate": "20221108",
                    }
                ],
            },
        ]
        list_is_eligible, _ = dana_validate_dbr_in_bulk(application, installment_plan_list)
        self.assertEqual(list_is_eligible[0]["isEligible"], True)

    def test_fail_validate_dbr_in_bulk_insuficient_salary(self):
        monthly_income = 50000
        application = ApplicationFactory(
            monthly_income=monthly_income,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.DANA),
        )
        application.application_status_id = 420
        application.save()
        installment_plan_list = [
            {
                "installmentPlanId": "installmentPlanIdBiweekly",
                "repaymentPlanList": [
                    {
                        "periodNo": "1",
                        "principalAmount": {"value": "12500.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "1000.00", "currency": "IDR"},
                        "totalAmount": {"value": "13500.00", "currency": "IDR"},
                        "dueDate": "20221013",
                    },
                    {
                        "periodNo": "2",
                        "principalAmount": {"value": "12500.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "1000.00", "currency": "IDR"},
                        "totalAmount": {"value": "13500.00", "currency": "IDR"},
                        "dueDate": "20221027",
                    },
                    {
                        "periodNo": "3",
                        "principalAmount": {"value": "12500.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "1000.00", "currency": "IDR"},
                        "totalAmount": {"value": "13500.00", "currency": "IDR"},
                        "dueDate": "20221113",
                    },
                    {
                        "periodNo": "4",
                        "principalAmount": {"value": "12500.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "1000.00", "currency": "IDR"},
                        "totalAmount": {"value": "13500.00", "currency": "IDR"},
                        "dueDate": "20221127",
                    },
                ],
            },
            {
                "installmentPlanId": "installmentPlanIdWeekly",
                "repaymentPlanList": [
                    {
                        "periodNo": "1",
                        "principalAmount": {"value": "50000.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "4000.00", "currency": "IDR"},
                        "totalAmount": {"value": "54000.00", "currency": "IDR"},
                        "dueDate": "20221013",
                    }
                ],
            },
            {
                "installmentPlanId": "installmentPlanIdMonthly1",
                "repaymentPlanList": [
                    {
                        "periodNo": "1",
                        "principalAmount": {"value": "50000.00", "currency": "IDR"},
                        "interestFeeAmount": {"value": "4000.00", "currency": "IDR"},
                        "totalAmount": {"value": "54000.00", "currency": "IDR"},
                        "dueDate": "20221108",
                    }
                ],
            },
        ]

        list_is_eligible, _ = dana_validate_dbr_in_bulk(application, installment_plan_list)
        self.assertEqual(list_is_eligible[0]["isEligible"], False)


class TestDanaMaxCreditorCheck(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, nik='123321123321')
        self.customer_segment = 'activeus_a'
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        WorkflowFactory(name=WorkflowConst.LEGACY)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        AccountLimitFactory(account=self.account, available_limit=1000000)
        self.application.save()
        self.inactive_status = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        self.lender_approve_status = StatusLookupFactory(
            status_code=LoanStatusCodes.LENDER_APPROVAL
        )
        self.lender_reject_status = StatusLookupFactory(status_code=LoanStatusCodes.LENDER_REJECT)
        self.current_status = StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)
        self.fund_disbursal_status = StatusLookupFactory(
            status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_disbursement_amount=100000,
            loan_amount=105000,
            loan_status=self.lender_approve_status,
            product=ProductLookupFactory(product_line=self.product_line, cashback_payment_pct=0.05),
            transaction_method=TransactionMethod.objects.get(pk=1),
        )

        self.fdc_inquiry = FDCInquiryFactory(
            application_id=self.application.id, inquiry_status='success'
        )
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.CHECK_OTHER_ACTIVE_PLATFORMS_USING_FDC,
            parameters={
                "fdc_data_outdated_threshold_days": 3,
                "number_of_allowed_platforms": 3,
                "ineligible_alert_after_fdc_checking": {},
                "fdc_inquiry_api_config": {"max_retries": 3, "retry_interval_seconds": 30},
                "whitelist": {
                    "is_active": True,
                    "list_application_id": [self.application.pk],
                },
            },
            is_active=True,
        )
        self.user_partner = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user_partner, name="dana")
        self.dana_customer_data = DanaCustomerDataFactory(
            account=self.account,
            partner=self.partner,
            customer=self.customer,
            dana_customer_identifier="12345679237",
            dob=date(2023, 1, 1),
        )

    def test_success_check_has_active_loan(self):
        self.loan.loan_status = self.current_status
        self.loan.save()
        is_eligible = dana_max_creditor_check(self.dana_customer_data, self.application)
        self.assertEqual(is_eligible, True)

    @patch('juloserver.loan.services.loan_related.get_info_active_loan_from_platforms')
    def test_fail_check_exceed_creditor(self, mock_get_info_active_loan_from_platforms):
        self.loan.loan_status = self.inactive_status
        self.loan.save()
        mock_get_info_active_loan_from_platforms.return_value = (None, 10, 2)
        is_eligible = dana_max_creditor_check(self.dana_customer_data, self.application)
        self.assertEqual(is_eligible, False)
