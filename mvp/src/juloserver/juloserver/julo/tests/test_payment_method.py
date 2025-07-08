from django.test.testcases import TestCase
from django.conf import settings
from datetime import datetime
from django.utils import timezone
from dateutil.relativedelta import relativedelta
import mock
from juloserver.julo.tests.factories import (
    GlobalPaymentMethodFactory, PaymentMethodFactory,
    CustomerFactory, LoanFactory,
    PaymentMethodLookupFactory, AuthUserFactory,
    WorkflowFactory, ApplicationFactory,
    PartnerFactory, PaymentMethodLookupFactory,
    StatusLookupFactory, PaymentMethodFactory, FeatureSettingFactory)
from juloserver.partnership.tests.factories import (
    DistributorFactory,
    MerchantDistributorCategoryFactory
)
from juloserver.merchant_financing.tests.factories import MerchantFactory
from juloserver.line_of_credit.tests.factories_loc import (
    VirtualAccountSuffixFactory, 
    MandiriVirtualAccountSuffixFactory,
    BniVirtualAccountSuffixFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory
)
from juloserver.julo.services2.payment_method import (
    generate_customer_va_for_julo_one, 
    create_or_update_gopay_payment_method, 
    get_disable_payment_methods,
)
from juloserver.julo.constants import (
    WorkflowConst, 
    FeatureNameConst,
)
from juloserver.julo.payment_methods import PaymentMethodManager, PaymentMethodCodes
from juloserver.julo.banks import BankCodes
from juloserver.julo.models import PaymentMethod
from juloserver.julo.tests.factories import FeatureSettingFactory


class TestGetPaymentMethod(TestCase):

    def setUp(self):
        user = AuthUserFactory()
        workflow = WorkflowFactory(
            name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW,
            handler='MerchantFinancingWorkflowHandler'
        )
        self.customer = CustomerFactory(user=user)
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=workflow,
            name='Merchant Financing',
            payment_frequency='weekly'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        partner = PartnerFactory(user=user)
        self.distributor = DistributorFactory(
            partner=partner,
            user=partner.user,
            distributor_category=MerchantDistributorCategoryFactory(),
            name='distributor abcd',
            address='jakarta',
            email='testingdistributorabcd@gmail.com',
            phone_number='08183152326',
            type_of_business='warung',
            npwp='123050410292712',
            nib='223050410592712',
            bank_account_name='distributor',
            bank_account_number='123456',
            bank_name='BCA',
            distributor_xid=128956,
        )
        self.merchant = MerchantFactory(
            nik='3283020101916011',
            shop_name='merchant 89',
            distributor=self.distributor,
            merchant_xid=2554387997,
            business_rules_score=0.5
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=workflow,
            application_xid=2054907666,
            merchant=self.merchant,
            account=self.account
        )
        VirtualAccountSuffixFactory()
        MandiriVirtualAccountSuffixFactory()
        BniVirtualAccountSuffixFactory()
        self.loan = LoanFactory(customer=self.customer, application=self.application)
        PaymentMethodLookupFactory(is_shown_mf=True)
        self.payment_method_name = 'BCA'
        self.payment_method_code = PaymentMethodCodes.BCA

        PaymentMethodFactory(
            loan=self.loan,
            payment_method_name=self.payment_method_name,
            payment_method_code=self.payment_method_code,
            customer=self.customer)

    def test_get_payment_code_for_payment_method(self):
        result = PaymentMethodManager.get_payment_code_for_payment_method(settings.FASPAY_PREFIX_OLD_ALFAMART)
        self.assertEqual(result, True)

        result = PaymentMethodManager.get_payment_code_for_payment_method(BankCodes.BCA)
        self.assertEqual(result, True)

        result = PaymentMethodManager.get_payment_code_for_payment_method(BankCodes.BTN)
        self.assertEqual(result, False)

    def test_generate_customer_va_for_julo_one(self):
        result = generate_customer_va_for_julo_one(self.application)
        self.assertIsNone(result)

    def test_get_all_payment_method(self):
        result = PaymentMethodManager.get_all_payment_methods()
        self.assertGreater(len(result), 0)

    def test_create_or_update_gopay_payment_method(self):
        create_or_update_gopay_payment_method(self.customer, 'PENDING')
        self.assertFalse(PaymentMethod.objects.filter(
            customer=self.customer, 
            payment_method_code=PaymentMethodCodes.GOPAY_TOKENIZATION,
            payment_method_name='GoPay Tokenization',
            is_shown=False
        ).exists())

        create_or_update_gopay_payment_method(self.customer, 'PENDING', self.application.mobile_phone_1)
        self.assertTrue(PaymentMethod.objects.filter(
            customer=self.customer, 
            payment_method_code=PaymentMethodCodes.GOPAY_TOKENIZATION,
            payment_method_name='GoPay Tokenization',
            is_shown=False,
            sequence=None
        ).exists())

        old_gopay_payment_method=PaymentMethodFactory(
            payment_method_code='1002', 
            customer=self.customer,
            payment_method_name='Gopay',
            is_shown=True,
            sequence=7)   
        create_or_update_gopay_payment_method(self.customer, 'ENABLED', self.application.mobile_phone_1)
        self.assertTrue(PaymentMethod.objects.filter(
            customer=self.customer, 
            payment_method_code=PaymentMethodCodes.GOPAY_TOKENIZATION,
            payment_method_name='GoPay Tokenization',
            is_shown=True,
            sequence=7
        ).exists())
        self.assertTrue(PaymentMethod.objects.filter(
            customer=self.customer, 
            payment_method_code=PaymentMethodCodes.GOPAY,
            payment_method_name='Gopay',
            is_shown=False,
            sequence=None
        ).exists())

        new_gopay_payment_method = PaymentMethodFactory(
            payment_method_code='1004', 
            customer=self.customer,
            payment_method_name='GoPay Tokenization',
            is_shown=False,
            sequence=None)
        create_or_update_gopay_payment_method(self.customer, 'ENABLED')
        self.assertTrue(PaymentMethod.objects.filter(
            customer=self.customer, 
            payment_method_code=PaymentMethodCodes.GOPAY_TOKENIZATION,
            payment_method_name='GoPay Tokenization',
            is_shown=True,
            sequence=7
        ).exists())
        self.assertTrue(PaymentMethod.objects.filter(
            customer=self.customer, 
            payment_method_code=PaymentMethodCodes.GOPAY,
            payment_method_name='Gopay',
            is_shown=False,
            sequence=None
        ).exists())

        new_gopay_payment_method.is_shown = True
        new_gopay_payment_method.save()
        old_gopay_payment_method.is_shown = False
        old_gopay_payment_method.save()
        create_or_update_gopay_payment_method(self.customer, 'DISABLED')
        self.assertTrue(PaymentMethod.objects.filter(
            customer=self.customer, 
            payment_method_code=PaymentMethodCodes.GOPAY_TOKENIZATION,
            payment_method_name='GoPay Tokenization',
            is_shown=False,
            sequence=None
        ).exists())
        self.assertTrue(PaymentMethod.objects.filter(
            customer=self.customer, 
            payment_method_code=PaymentMethodCodes.GOPAY,
            payment_method_name='Gopay',
            is_shown=True,
            sequence=7
        ).exists())

    def test_block_bni_va_generation_for_julo_one(self):
        FeatureSettingFactory(
            feature_name='block_bni_va_auto_generation',
            is_active=True,
            parameters={}
        )
        self.distributor.bank_name = 'BNI'
        self.distributor.save()
        self.application.bank_name = 'BNI'
        self.application.save()
        result = generate_customer_va_for_julo_one(self.application)
        self.assertIsNone(result)
        self.assertFalse(PaymentMethod.objects.filter(
            customer=self.customer, 
            payment_method_code=PaymentMethodCodes.BNI,
        ).exists())

    def test_get_disable_payment_methods(self):
        now = timezone.localtime(timezone.now()).replace(day=7, month=8, year=2023, hour=12, minute=30)
        today = datetime.strptime(datetime.strftime(now, '%d-%m-%y %H:%M'), '%d-%m-%y %H:%M')
        with mock.patch('django.utils.timezone.now') as mock_today:
            mock_today.return_value = today
            feature_setting = FeatureSettingFactory(
                feature_name=FeatureNameConst.DISABLE_PAYMENT_METHOD,
                is_active=True,
                parameters={
                    "disable_start_date_time": datetime.strftime(today - relativedelta(days=1), '%d-%m-%Y %H:%M'), 
                    "disable_end_date_time": datetime.strftime(today + relativedelta(days=1), '%d-%m-%Y %H:%M'),
                    "payment_method_name":[]
                }
            )
            self.assertEqual(get_disable_payment_methods(), [])
            feature_setting.parameters["payment_method_name"] = ['PERMATA Bank']
            feature_setting.save()
            self.assertEqual(get_disable_payment_methods(), ['PERMATA Bank'])
            feature_setting.parameters["disable_start_date_time"] = '08-08-2023 12:30'
            feature_setting.save()
            self.assertEqual(get_disable_payment_methods(), [])
