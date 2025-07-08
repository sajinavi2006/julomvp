from django.test.testcases import TestCase
from django.conf import settings

from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import (
    GlobalPaymentMethodFactory,
    PaymentMethodFactory,
    CustomerFactory,
    LoanFactory,
    PaymentMethodLookupFactory,
    AuthUserFactory,
    WorkflowFactory,
    ApplicationFactory,
    FeatureSettingFactory,
    StatusLookupFactory,
    LenderFactory,
)
from juloserver.julo.services2.payment_method import aggregate_payment_methods
from juloserver.julo.services2.payment_method import update_mf_payment_method_is_shown_mf_flag
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.models import PaymentMethod
from juloserver.julo.services2.payment_method import (
    filter_payment_methods_by_lender,
    get_main_payment_method,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.banks import BankCodes


class TestAggregatePaymentMethod(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.loan = LoanFactory(customer=self.customer)
        FeatureSettingFactory(
            feature_name='order_payment_methods_by_groups',
            is_active=True,
            parameters={
                "autodebet_group": [],
                "bank_va_group": ["bank bca", "bank bri", "bank mandiri", "permata bank", "bank maybank"],
                "e_wallet_group": ["gopay", "gopay tokenization", "ovo", "ovo tokenization"],
                "new_repayment_channel_group": {"end_date": "",
                                                "new_repayment_channel": []
                                            },
                "retail_group": ["indomaret", "alfamart"],
                "direct_debit_group": ["oneklik bca"],
            }
        )

    def test_global_setting_is_priority(self):
        payment_method_code = PaymentMethodCodes.BCA
        payment_method_name = 'Bank BCA 1'
        bank_name = 'BCA bank'

        global_setting = GlobalPaymentMethodFactory(
            feature_name='BCA', is_active=True, is_priority=True, impacted_type='Primary',
            payment_method_code=payment_method_code, payment_method_name=payment_method_name)
        payment_method = PaymentMethodFactory(
            payment_method_name=payment_method_name, is_primary=True,
            payment_method_code=payment_method_code,
            customer=self.customer, loan=self.loan, is_shown=False,
            sequence=1
        )
        payment_methods = PaymentMethod.objects.all()
        # payment method lookup is not existed
        result = aggregate_payment_methods(payment_methods, [global_setting], bank_name)
        self.assertEqual(len(result), 0)

        # the global setting is impacted to primary payment method
        PaymentMethodLookupFactory(code=payment_method_code, name=payment_method_name)
        payment_methods = PaymentMethod.objects.all()
        result = aggregate_payment_methods(payment_methods, [global_setting], bank_name)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['is_shown'], True)

        # the global setting is impacted to backup payment method
        payment_method_code = '123'
        new_payment_method_code = PaymentMethodCodes.PERMATA1
        old_payment_method_code = PaymentMethodCodes.MAYBANK
        global_setting.impacted_type = 'Backup'
        payment_method.is_primary = False
        global_setting.save()
        payment_method.save()
        payment_methods = PaymentMethod.objects.all()
        result = aggregate_payment_methods(payment_methods, [global_setting], bank_name)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['is_shown'], True)

        # payment method bank code is BCA
        payment_method.bank_code = '014'
        payment_method.save()
        old_permata_payment_method = PaymentMethodFactory(
            payment_method_name=payment_method_name, is_primary=False,
            payment_method_code=old_payment_method_code,
            customer=self.customer, loan=self.loan, is_shown=True,
            bank_code='013', sequence=2
        )
        payment_methods = PaymentMethod.objects.filter(
            pk__in={old_permata_payment_method.id, payment_method.id}
        ).order_by('-sequence')
        result = aggregate_payment_methods(payment_methods, [global_setting], bank_name)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['is_shown'], True)
        self.assertEqual(result[0]['payment_method_code'], old_payment_method_code)

        # payment method is permata
        payment_method.bank_code = '013'
        payment_method.payment_method_code = new_payment_method_code
        payment_method.save()
        payment_methods = PaymentMethod.objects.filter(pk=payment_method.id)
        result = aggregate_payment_methods(payment_methods, [global_setting], 'PERMATA Bank')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['is_shown'], True)
        ## payment method is old permata
        payment_methods = PaymentMethod.objects.filter(pk__in={payment_method.id, old_permata_payment_method.id})
        result = aggregate_payment_methods(
            payment_methods, [global_setting], 'PERMATA Bank')
        self.assertEqual(len(result), 2)
        if result[0]['payment_method_code'] == old_payment_method_code:
            self.assertEqual(result[0]['payment_method_code'], old_payment_method_code)
        else:
            self.assertEqual(result[1]['payment_method_code'], old_payment_method_code)

        # payment method is BRI
        payment_method.bank_code = '002'
        payment_method.save()
        payment_methods = PaymentMethod.objects.filter(pk=payment_method.id)
        result = aggregate_payment_methods(payment_methods, [global_setting], 'BRI Bank')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['is_shown'], True)

        # the global setting is not shown
        payment_method_code = '123'
        global_setting.is_active = False
        global_setting.save()

        payment_methods = PaymentMethod.objects.filter(pk=payment_method.id)
        result = aggregate_payment_methods(payment_methods, [global_setting], bank_name)
        self.assertEqual(len(result), 0)

    def test_global_setting_is_not_priority(self):
        # individual setting is true
        payment_method_code = '1234'
        payment_method_name = 'Bank BCA 2'
        PaymentMethodLookupFactory(code=payment_method_code, name=payment_method_name)

        global_setting = GlobalPaymentMethodFactory(
            feature_name='BCA', is_active=False, impacted_type='Primary',
            payment_method_code=payment_method_code, payment_method_name=payment_method_name)
        payment_method = PaymentMethodFactory(
            payment_method_name=payment_method_name, is_primary=True,
            payment_method_code=payment_method_code,
            customer=self.customer, loan=self.loan, is_shown=True, edited_by=self.customer.user
        )
        bank_name = 'BCA bank'
        payment_methods = PaymentMethod.objects.all()
        result = aggregate_payment_methods(payment_methods, [global_setting], bank_name)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['is_shown'], True)

        # individual setting is false
        payment_method.edited_by = None
        payment_method.save()
        payment_methods = PaymentMethod.objects.all()
        result = aggregate_payment_methods(payment_methods, [global_setting], bank_name)
        self.assertEqual(len(result), 0)

    def test_not_global_setting(self):
        # individual setting is true
        payment_method_code = '12345'
        payment_method_name = 'Bank BCA 3'
        PaymentMethodLookupFactory(code=payment_method_code, name=payment_method_name)

        payment_method = PaymentMethodFactory(
            payment_method_name=payment_method_name, is_primary=True,
            payment_method_code=payment_method_code,
            customer=self.customer, loan=self.loan, is_shown=True, edited_by=self.customer.user
        )
        bank_name = 'BCA bank'
        payment_methods = PaymentMethod.objects.all()
        result = aggregate_payment_methods(payment_methods, [], bank_name)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['is_shown'], True)

        # individual setting is false
        payment_method.edited_by = None
        payment_method.save()
        payment_methods = PaymentMethod.objects.all()
        result = aggregate_payment_methods(payment_methods, [], bank_name)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['is_shown'], True)

    def test_global_setting_not_impacted_type(self):
        payment_method_code = '12346'
        payment_method_name = 'Gopay'
        PaymentMethodLookupFactory(code=payment_method_code, name=payment_method_name)

        global_setting = GlobalPaymentMethodFactory(
            feature_name='Gopay', is_active=True, impacted_type=None,
            payment_method_code=payment_method_code, payment_method_name=payment_method_name)
        payment_method = PaymentMethodFactory(
            payment_method_name=payment_method_name, is_primary=True,
            payment_method_code=payment_method_code,
            customer=self.customer, loan=self.loan, is_shown=False,
            bank_code=None
        )
        bank_name = 'BCA bank'
        payment_methods = PaymentMethod.objects.all()
        result = aggregate_payment_methods(payment_methods, [global_setting], bank_name)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['is_shown'], True)

    def test_global_setting_is_empty(self):
        PaymentMethodLookupFactory(code='1234567', name='Bank BCA 4')
        payment_method = PaymentMethodFactory(
            payment_method_name='Bank BCA 4', is_primary=True,
            payment_method_code='1234567',
            customer=self.customer, loan=self.loan, is_shown=True,
            bank_code=None
        )
        payment_methods = PaymentMethod.objects.all()
        result = aggregate_payment_methods(payment_methods, [], 'BCA bank')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['is_shown'], True)


class TestUpdatePaymentMethod(TestCase):
    def setUp(self):
        user = AuthUserFactory()
        workflow = WorkflowFactory(
            name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW,
            handler='MerchantFinancingWorkflowHandler'
        )
        self.customer = CustomerFactory(user=user)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=workflow,
            application_xid=2554907666,
        )
        self.payment_method_code1 = PaymentMethodCodes.OLD_INDOMARET
        self.payment_method_code2 = settings.FASPAY_PREFIX_OLD_ALFAMART
        self.is_shown_mf = True

    def test_update_mf_payment_method_is_shown_mf_flag(self):
        result = update_mf_payment_method_is_shown_mf_flag(self.payment_method_code1, self.is_shown_mf)
        self.assertEqual(result, True)

        result = update_mf_payment_method_is_shown_mf_flag(
            self.payment_method_code2, self.is_shown_mf
        )
        self.assertEqual(result, True)


class TestFilterPaymentMethodsByLender(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.status = StatusLookupFactory()
        self.status.status_code = 220
        self.status.save()
        self.lender = LenderFactory()
        self.account = AccountFactory(customer=self.customer)
        self.loan = LoanFactory(customer=self.customer, lender=self.lender, account=self.account)
        self.payment_method = PaymentMethodFactory(
            payment_method_name='Indomaret',
            is_primary=True,
            payment_method_code=PaymentMethodCodes.INDOMARET,
            is_shown=True,
            customer=self.customer,
        )
        self.payment_method = PaymentMethodFactory(
            payment_method_name='Alfamart',
            is_primary=False,
            payment_method_code=PaymentMethodCodes.ALFAMART,
            is_shown=True,
            customer=self.customer,
        )
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.HIDE_PAYMENT_METHODS_BY_LENDER,
            is_active=True,
            parameters=[
                {"lender_id": self.lender.id, "payment_method_codes": [PaymentMethodCodes.ALFAMART]}
            ],
        )

    def test_filter_payment_methods_by_lender_hide_alfamart(self):
        payment_methods = PaymentMethod.objects.all()
        result = filter_payment_methods_by_lender(payment_methods, self.customer)
        self.assertEqual(len(result), 1)

    def test_filter_payment_methods_by_lender_inactive_feature_setting(self):
        self.fs.update_safely(is_active=False)
        payment_methods = PaymentMethod.objects.all()
        result = filter_payment_methods_by_lender(payment_methods, self.customer)
        self.assertEqual(len(result), 2)


class TestGetMainPaymentMethod(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.status = StatusLookupFactory()
        self.status.status_code = 220
        self.status.save()
        self.lender = LenderFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account, bank_name='BRI'
        )
        self.loan = LoanFactory(customer=self.customer, lender=self.lender, account=self.account)
        PaymentMethodFactory(
            payment_method_name='Indomaret',
            is_primary=True,
            payment_method_code=PaymentMethodCodes.INDOMARET,
            is_shown=True,
            customer=self.customer,
        )
        PaymentMethodFactory(
            payment_method_name='Alfamart',
            is_primary=False,
            payment_method_code=PaymentMethodCodes.ALFAMART,
            is_shown=True,
            customer=self.customer,
        )
        PaymentMethodFactory(
            payment_method_name='BCA',
            is_primary=False,
            payment_method_code=PaymentMethodCodes.BCA,
            bank_code=BankCodes.BCA,
            is_shown=True,
            customer=self.customer,
            sequence=2,
        )
        PaymentMethodFactory(
            payment_method_name='BNI',
            is_primary=False,
            payment_method_code=PaymentMethodCodes.BNI,
            bank_code=BankCodes.BNI,
            is_shown=True,
            customer=self.customer,
            sequence=1,
        )
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.HIDE_PAYMENT_METHODS_BY_LENDER,
            is_active=True,
            parameters=[
                {
                    "lender_id": self.lender.id,
                    "payment_method_codes": [PaymentMethodCodes.INDOMARET],
                }
            ],
        )

    def test_get_main_payment_method_show_bni(self):
        payment_method = get_main_payment_method(self.customer)
        self.assertEqual(payment_method.payment_method_code, PaymentMethodCodes.BNI)

    def test_get_main_payment_method_show_primary(self):
        self.fs.update_safely(is_active=False)
        payment_method = get_main_payment_method(self.customer)
        self.assertEqual(payment_method.payment_method_code, PaymentMethodCodes.INDOMARET)
