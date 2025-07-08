from datetime import date
from dateutil.relativedelta import relativedelta
from django.test.testcases import TestCase

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    FeatureSettingFactory,
    PartnerFactory,
    ProductLineFactory,
)
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.account_payment.models import AccountPayment
from juloserver.account.tests.factories import (
    AccountFactory,
    AddressFactory,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.loan.constants import DBRConst
from juloserver.julo.product_lines import ProductLineCodes

from juloserver.loan.services.dbr_ratio import (
    get_dbr_status_and_param_after_whitelist,
    get_dbr_data,
    LoanDbrSetting,
)
from juloserver.loan.models import AnaBlacklistDbr
from juloserver.dana.tests.factories import DanaCustomerDataFactory
from juloserver.customer_module.tests.factories import CustomerDataChangeRequestFactory
from juloserver.customer_module.constants import CustomerDataChangeRequestConst


class TestDbrRatio(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.DBR_RATIO_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "blacklist": {"is_active": True},
                "ratio_percentage": DBRConst.DEFAULT_INCOME_PERCENTAGE,
                "popup_banner": DBRConst.DEFAULT_POPUP_BANNER,
                "product_line_ids": DBRConst.DEFAULT_PRODUCT_LINE_IDS,
            },
        )

    def construct_submit_data(self, **kwargs):
        data = {
            'address_street_num': 'Jl. Gandaria I No. 1',
            'address_provinsi': 'DKI Jakarta',
            'address_kabupaten': 'Jakarta Selatan',
            'address_kecamatan': 'Kebayoran Baru',
            'address_kelurahan': 'Gandaria Utara',
            'address_kodepos': '12140',
            'address_latitude': 1.2,
            'address_longitude': 3.4,
            'job_type': 'Pegawai negeri',
            'job_industry': 'perbankan',
            'job_description': 'mengelola uang',
            'company_name': 'PT. Bank Julo',
            'company_phone_number': '0211234567',
            'payday': 15,
            'monthly_income': 10000000,
            'monthly_expenses': 5000000,
            'monthly_housing_cost': 2000000,
            'total_current_debt': 1000000,
            'app_version': '1.0.0',
            'android_id': '1234567890',
            'latitude': 1.0,
            'longitude': 2.0,
        }
        data.update(**kwargs)
        return data

    def test_feature_setting(self):
        self.feature_setting.is_active = True
        self.feature_setting.save()
        is_dbr_active, dbr_fs = get_dbr_status_and_param_after_whitelist()
        self.assertTrue(is_dbr_active)
        self.assertEqual(dbr_fs.get("ratio_percentage", 0), DBRConst.DEFAULT_INCOME_PERCENTAGE)

    def test_feature_setting_inactive(self):
        self.feature_setting.is_active = False
        self.feature_setting.save()
        is_dbr_active, dbr_fs = get_dbr_status_and_param_after_whitelist()
        self.assertFalse(is_dbr_active)
        self.assertEqual(dbr_fs.get("ratio_percentage", 0), DBRConst.DEFAULT_INCOME_PERCENTAGE)

    def test_feature_setting_whitelist(self):
        application = ApplicationFactory()
        self.feature_setting.parameters["whitelist"]["list_application_ids"] = [application.id]
        self.feature_setting.parameters["whitelist"]["is_active"] = True
        self.feature_setting.save()
        is_dbr_active, dbr_fs = get_dbr_status_and_param_after_whitelist(application.id)
        self.assertTrue(is_dbr_active)
        self.assertEqual(dbr_fs.get("ratio_percentage", 0), DBRConst.DEFAULT_INCOME_PERCENTAGE)

        application2 = ApplicationFactory()
        is_dbr_active, dbr_fs = get_dbr_status_and_param_after_whitelist(application2.id)
        self.assertFalse(is_dbr_active)
        self.assertEqual(dbr_fs.get("ratio_percentage", 0), DBRConst.DEFAULT_INCOME_PERCENTAGE)

    def test_get_dbr_data_no_loan(self):
        monthly_income = 10_000_000
        application = ApplicationFactory(
            monthly_income=monthly_income,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application.application_status_id = 420
        application.save()
        status, max_monthly_payment, map_account_payment, banner = get_dbr_data(application)
        max_monthly_payment = monthly_income * DBRConst.DEFAULT_INCOME_PERCENTAGE / 100
        self.assertEqual(status, True)
        self.assertEqual(max_monthly_payment, max_monthly_payment)

    def test_get_dbr_data_no_loan_no_j1(self):
        monthly_income = 10_000_000
        application = ApplicationFactory(
            monthly_income=monthly_income,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.JTURBO),
        )
        application.application_status_id = 420
        application.save()
        status, max_monthly_payment, map_account_payment, banner = get_dbr_data(application)
        max_monthly_payment = monthly_income * DBRConst.DEFAULT_INCOME_PERCENTAGE / 100
        self.assertEqual(status, False)

    def test_get_dbr_data_some_loan(self):
        monthly_income = 10_000_000
        account_payments = AccountPayment.objects.filter(account=self.account)
        for account_payment in account_payments:
            account_payment.delete()

        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=1),
            due_amount=290_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=2),
            due_amount=350_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=3),
            due_amount=325_000,
        )

        application = ApplicationFactory(
            monthly_income=monthly_income,
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application.application_status_id = 420
        application.save()
        max_monthly_payment = monthly_income * DBRConst.DEFAULT_INCOME_PERCENTAGE / 100
        status, max_monthly_payment_new, map_account_payment, banner = get_dbr_data(application)
        self.assertEqual(status, True)
        self.assertEqual(max_monthly_payment, max_monthly_payment_new)

    def test_get_dbr_data_customer_data_change(self):
        monthly_income = 10_000_000
        account_payments = AccountPayment.objects.filter(account=self.account)
        for account_payment in account_payments:
            account_payment.delete()

        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=1),
            due_amount=290_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=2),
            due_amount=350_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=3),
            due_amount=325_000,
        )

        application = ApplicationFactory(
            monthly_income=monthly_income,
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        data = self.construct_submit_data()
        customer_data_change_1 = CustomerDataChangeRequestFactory(
            address=AddressFactory(
                detail=data['address_street_num'],
                provinsi=data['address_provinsi'],
                kabupaten=data['address_kabupaten'],
                kecamatan=data['address_kecamatan'],
                kelurahan=data['address_kelurahan'],
                kodepos=data['address_kodepos'],
                latitude=123,
                longitude=1,
            ),
            job_type=data['job_type'],
            job_industry=data['job_industry'],
            job_description=data['job_description'],
            company_name=data['company_name'],
            company_phone_number=data['company_phone_number'],
            payday=data['payday'],
            monthly_income=15_000_000,
            monthly_expenses=data['monthly_expenses'],
            monthly_housing_cost=data['monthly_housing_cost'],
            total_current_debt=data['total_current_debt'],
            app_version=data['app_version'],
            android_id=data['android_id'],
            latitude=data['latitude'],
            longitude=data['longitude'],
            status=CustomerDataChangeRequestConst.SubmissionStatus.APPROVED,
            source=CustomerDataChangeRequestConst.Source.APP,
            application=application,
        )

        application.application_status_id = 420
        application.monthly_income = 20_000_000
        application.save()

        # application monthly income larger than CustomerDataChangeRequestFactory
        max_monthly_payment = 20_000_000 * DBRConst.DEFAULT_INCOME_PERCENTAGE / 100
        status, max_monthly_payment_new, _, _ = get_dbr_data(application)
        self.assertEqual(status, True)
        self.assertEqual(max_monthly_payment, max_monthly_payment_new)

        # application monthly income smaller than CustomerDataChangeRequestFactory
        application.monthly_income = 10_000_000
        application.save()
        max_monthly_payment = 15_000_000 * DBRConst.DEFAULT_INCOME_PERCENTAGE / 100
        status, max_monthly_payment_new, _, _ = get_dbr_data(application)
        self.assertEqual(status, True)
        self.assertEqual(max_monthly_payment, max_monthly_payment_new)

        customer_data_change_2 = CustomerDataChangeRequestFactory(
            address=AddressFactory(
                detail=data['address_street_num'],
                provinsi=data['address_provinsi'],
                kabupaten=data['address_kabupaten'],
                kecamatan=data['address_kecamatan'],
                kelurahan=data['address_kelurahan'],
                kodepos=data['address_kodepos'],
                latitude=123,
                longitude=1,
            ),
            job_type=data['job_type'],
            job_industry=data['job_industry'],
            job_description=data['job_description'],
            company_name=data['company_name'],
            company_phone_number=data['company_phone_number'],
            payday=data['payday'],
            monthly_income=12_000_000,
            monthly_expenses=data['monthly_expenses'],
            monthly_housing_cost=data['monthly_housing_cost'],
            total_current_debt=data['total_current_debt'],
            app_version=data['app_version'],
            android_id=data['android_id'],
            latitude=data['latitude'],
            longitude=data['longitude'],
            status=CustomerDataChangeRequestConst.SubmissionStatus.APPROVED,
            source=CustomerDataChangeRequestConst.Source.APP,
            application=application,
        )
        self.assertEqual(status, True)
        self.assertEqual(max_monthly_payment, max_monthly_payment_new)

        # application monthly income smaller than CustomerDataChangeRequestFactory
        application.monthly_income = 10_000_000
        application.save()
        max_monthly_payment = 15_000_000 * DBRConst.DEFAULT_INCOME_PERCENTAGE / 100
        status, max_monthly_payment_new, _, _ = get_dbr_data(application)
        self.assertEqual(status, True)
        self.assertEqual(max_monthly_payment, max_monthly_payment_new)

        # make sure work when source is not APP
        customer_data_change_1.source = CustomerDataChangeRequestConst.Source.ADMIN
        customer_data_change_1.save()
        customer_data_change_2.source = CustomerDataChangeRequestConst.Source.ADMIN
        customer_data_change_2.save()
        application.monthly_income = 10_000_000
        application.save()
        max_monthly_payment = 15_000_000 * DBRConst.DEFAULT_INCOME_PERCENTAGE / 100
        status, max_monthly_payment_new, _, _ = get_dbr_data(application)
        self.assertEqual(status, True)
        self.assertEqual(max_monthly_payment, max_monthly_payment_new)

    def test_get_dbr_data_exceed_monthly(self):
        # our current os only 50%, so 5.5 are 55%, thus exceeding limit
        account_payments = AccountPayment.objects.filter(account=self.account)
        for account_payment in account_payments:
            account_payment.delete()

        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=1),
            due_amount=5_500_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=2),
            due_amount=5_500_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=3),
            due_amount=5_500_000,
        )
        application = ApplicationFactory(
            monthly_income=10_000_000,
            customer=self.customer,
            account=self.account,
        )
        application.application_status_id = 420
        application.save()
        status, max_monthly_payment, map_account_payment, banner = get_dbr_data(application)
        self.assertEqual(status, False)
        self.assertEqual(max_monthly_payment, 0)

    def test_get_dbr_data_exceed_monthly_with_dana(self):
        # our current is only 50%, and this test case will exceed with dana + j1
        application = ApplicationFactory(
            monthly_income=10_000_000,
            customer=self.customer,
            account=self.account,
        )
        application.application_status_id = 420
        application.save()
        dana_customer = CustomerFactory()
        dana_account = AccountFactory(customer=dana_customer)
        dana_application = ApplicationFactory(
            monthly_income=10_000_000,
            customer=dana_customer,
            account=dana_account,
        )
        dana_application.application_status_id = 420
        dana_application.save()
        dana_customer_data = DanaCustomerDataFactory(
            account=dana_account,
            customer=dana_customer,
            application=dana_application,
            dana_customer_identifier="12345679237",
            credit_score=750,
            nik=application.ktp,
            partner=PartnerFactory(name=PartnerNameConstant.DANA, is_active=True),
        )
        # Dana account payment list
        AccountPaymentFactory(
            account=dana_account,
            due_date=date.today() + relativedelta(months=1),
            due_amount=2_000_000,
        )
        AccountPaymentFactory(
            account=dana_account,
            due_date=date.today() + relativedelta(months=2),
            due_amount=1_500_000,
        )
        AccountPaymentFactory(
            account=dana_account,
            due_date=date.today() + relativedelta(months=3),
            due_amount=3_500_000,
        )

        account_payments = AccountPayment.objects.filter(account=self.account)
        for account_payment in account_payments:
            account_payment.delete()

        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=1),
            due_amount=2_500_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=2),
            due_amount=2_500_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=3),
            due_amount=3_500_000,
        )
        status, max_monthly_payment, map_account_payment, banner = get_dbr_data(application)
        self.assertEqual(status, False)
        self.assertEqual(max_monthly_payment, 0)

    def test_get_dbr_data_pay_button(self):
        monthly_income = 10_000_000
        account_payments = AccountPayment.objects.filter(account=self.account)
        for account_payment in account_payments:
            account_payment.delete()

        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=1),
            due_amount=290_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=2),
            due_amount=350_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=3),
            due_amount=325_000,
        )

        application = ApplicationFactory(
            monthly_income=monthly_income,
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application.application_status_id = 420
        application.save()
        status, max_monthly_payment_new, map_account_payment, banner = get_dbr_data(application)
        self.assertEqual(status, True)

        buttons = banner.get(DBRConst.BUTTON_KEY)
        pay_button_idx = None
        for idx, button in enumerate(buttons):
            if button['title'] == DBRConst.PAY_BUTTON_TITLE:
                pay_button_idx = idx

        self.assertEqual(banner[DBRConst.BUTTON_KEY][pay_button_idx]['is_active'], True)

    def test_get_dbr_data_pay_button_switched_off(self):
        monthly_income = 10_000_000
        account_payments = AccountPayment.objects.filter(account=self.account)
        for account_payment in account_payments:
            account_payment.delete()

        application = ApplicationFactory(
            monthly_income=monthly_income,
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application.application_status_id = 420
        application.save()
        status, max_monthly_payment_new, map_account_payment, banner = get_dbr_data(application)
        self.assertEqual(status, True)

        buttons = banner.get(DBRConst.BUTTON_KEY)
        pay_button_idx = None
        for idx, button in enumerate(buttons):
            if button['title'] == DBRConst.PAY_BUTTON_TITLE:
                pay_button_idx = idx

        self.assertEqual(banner[DBRConst.BUTTON_KEY][pay_button_idx]['is_active'], False)

    def test_get_dbr_data_pay_button_default_off(self):
        monthly_income = 10_000_000
        account_payments = AccountPayment.objects.filter(account=self.account)
        for account_payment in account_payments:
            account_payment.delete()

        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=1),
            due_amount=290_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=2),
            due_amount=350_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=date.today() + relativedelta(months=3),
            due_amount=325_000,
        )
        buttons = self.feature_setting.parameters["popup_banner"]["buttons"]
        pay_button_idx = None
        for idx, button in enumerate(buttons):
            if button['title'] == DBRConst.PAY_BUTTON_TITLE:
                pay_button_idx = idx

        self.feature_setting.parameters["popup_banner"]["buttons"][pay_button_idx][
            'is_active'
        ] = False
        self.feature_setting.save()

        application = ApplicationFactory(
            monthly_income=monthly_income,
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application.application_status_id = 420
        application.save()
        status, max_monthly_payment_new, map_account_payment, banner = get_dbr_data(application)
        self.assertEqual(status, True)

        buttons = banner.get(DBRConst.BUTTON_KEY)
        pay_button_idx = None
        for idx, button in enumerate(buttons):
            if button['title'] == DBRConst.PAY_BUTTON_TITLE:
                pay_button_idx = idx

        self.assertEqual(banner[DBRConst.BUTTON_KEY][pay_button_idx]['is_active'], False)

    def test_is_dbr_exceeded(self):
        monthly_income = 10_000_000
        account_payments = AccountPayment.objects.filter(account=self.account)
        for account_payment in account_payments:
            account_payment.delete()

        first_payment_date = date.today() + relativedelta(days=35)
        AccountPaymentFactory(
            account=self.account,
            due_date=first_payment_date + relativedelta(days=1),
            due_amount=4_000_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=first_payment_date + relativedelta(months=1),
            due_amount=290_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=first_payment_date + relativedelta(months=2),
            due_amount=350_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=first_payment_date + relativedelta(months=3),
            due_amount=325_000,
        )
        application = ApplicationFactory(
            monthly_income=monthly_income,
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application.application_status_id = 420
        application.save()
        loan_dbr = LoanDbrSetting(application, True)
        first_payment_amount = 500_000
        payment_amount = 400_000
        duration = 5

        is_exceeded = loan_dbr.is_dbr_exceeded(
            duration=duration,
            payment_amount=payment_amount,
            first_payment_date=first_payment_date,
            first_payment_amount=first_payment_amount,
        )
        self.assertFalse(is_exceeded)

    def test_is_dbr_exceeded_first_month_only(self):
        monthly_income = 10_000_000
        account_payments = AccountPayment.objects.filter(account=self.account)
        for account_payment in account_payments:
            account_payment.delete()

        first_payment_date = date.today() + relativedelta(days=35)
        AccountPaymentFactory(
            account=self.account,
            due_date=first_payment_date + relativedelta(days=1),
            due_amount=4_000_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=first_payment_date + relativedelta(months=1),
            due_amount=4_000_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=first_payment_date + relativedelta(months=2),
            due_amount=4_000_000,
        )
        AccountPaymentFactory(
            account=self.account,
            due_date=first_payment_date + relativedelta(months=3),
            due_amount=4_000_000,
        )
        application = ApplicationFactory(
            monthly_income=monthly_income,
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application.application_status_id = 420
        application.save()
        loan_dbr = LoanDbrSetting(application, True)
        first_payment_amount = 1_200_000
        payment_amount = 700_000
        duration = 5

        is_exceeded = loan_dbr.is_dbr_exceeded(
            duration=duration,
            payment_amount=payment_amount,
            first_payment_date=first_payment_date,
            first_payment_amount=first_payment_amount,
        )
        self.assertTrue(is_exceeded)

    def test_feature_setting_blacklist(self):
        # UT 1: Whitelist and blacklist OFF
        # expectation : DBR is active
        application = ApplicationFactory()
        is_dbr_active, dbr_fs = get_dbr_status_and_param_after_whitelist(
            application.id, application.customer_id
        )
        self.assertTrue(is_dbr_active)
        self.assertEqual(dbr_fs.get("ratio_percentage", 0), DBRConst.DEFAULT_INCOME_PERCENTAGE)

        # UT 2: Blacklist on, Whitelist OFF and loan is blacklisted
        # expectation : DBR is inactive active
        self.feature_setting.parameters["blacklist"]["is_active"] = True
        self.feature_setting.save()
        AnaBlacklistDbr.objects.create(customer_id=application.customer_id)
        is_dbr_active, dbr_fs = get_dbr_status_and_param_after_whitelist(
            application.id, application.customer_id
        )
        self.assertFalse(is_dbr_active)
        self.assertEqual(dbr_fs.get("ratio_percentage", 0), DBRConst.DEFAULT_INCOME_PERCENTAGE)

        # UT 3: Blacklist on, Whitelist OFF but loan is not blacklisted
        # expectation : DBR is active
        application2 = ApplicationFactory()
        is_dbr_active, dbr_fs = get_dbr_status_and_param_after_whitelist(
            application2.id, application2.customer_id
        )
        self.assertTrue(is_dbr_active)
        self.assertEqual(dbr_fs.get("ratio_percentage", 0), DBRConst.DEFAULT_INCOME_PERCENTAGE)

        # UT 4: Blacklist on, Whitelist ON, loan is whitelisted and blacklisted
        # expectation : DBR is inactive
        self.feature_setting.parameters["whitelist"]["list_application_ids"] = [application.id]
        self.feature_setting.parameters["whitelist"]["is_active"] = True
        self.feature_setting.save()
        is_dbr_active, dbr_fs = get_dbr_status_and_param_after_whitelist(
            application.id, application.customer_id
        )
        self.assertTrue(is_dbr_active)
        self.assertEqual(dbr_fs.get("ratio_percentage", 0), DBRConst.DEFAULT_INCOME_PERCENTAGE)

        # UT 5: Blacklist on, Whitelist ON, loan is not whitelisted but blacklisted
        # expectation : DBR is inactive
        self.feature_setting.parameters["whitelist"]["list_application_ids"] = [application2.id]
        self.feature_setting.parameters["whitelist"]["is_active"] = True
        self.feature_setting.save()
        is_dbr_active, dbr_fs = get_dbr_status_and_param_after_whitelist(
            application.id, application.customer_id
        )
        self.assertFalse(is_dbr_active)
        self.assertEqual(dbr_fs.get("ratio_percentage", 0), DBRConst.DEFAULT_INCOME_PERCENTAGE)

        # UT 6: Blacklist off, Whitelist ON, loan is whitelisted and blacklisted
        # expectation : DBR is active
        self.feature_setting.parameters["whitelist"]["list_application_ids"] = [application2.id]
        self.feature_setting.parameters["whitelist"]["is_active"] = True
        self.feature_setting.save()
        is_dbr_active, dbr_fs = get_dbr_status_and_param_after_whitelist(
            application.id, application.customer_id
        )
        self.assertFalse(is_dbr_active)
        self.assertEqual(dbr_fs.get("ratio_percentage", 0), DBRConst.DEFAULT_INCOME_PERCENTAGE)

        # UT 7: Blacklist on, Whitelist ON, loan is whitelisted and not blacklisted
        # expectation : DBR is inactive
        self.feature_setting.parameters["whitelist"]["list_application_ids"] = [application2.id]
        self.feature_setting.parameters["whitelist"]["is_active"] = True
        self.feature_setting.save()
        is_dbr_active, dbr_fs = get_dbr_status_and_param_after_whitelist(
            application2.id, application2.customer_id
        )
        self.assertTrue(is_dbr_active)
        self.assertEqual(dbr_fs.get("ratio_percentage", 0), DBRConst.DEFAULT_INCOME_PERCENTAGE)
