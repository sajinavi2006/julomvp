from django.test.testcases import TestCase
import mock

from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.julo.constants import MobileFeatureNameConst, WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    MobileFeatureSettingFactory,
    AuthUserFactory,
    CustomerFactory,
    WorkflowFactory,
    ProductLineFactory,
    ApplicationFactory,
)
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.payment_point.constants import FeatureNameConst, TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod
from juloserver.payment_point.services.views_related import (
    construct_transaction_method_for_android,
    get_campaign_from_transaction_method,
    get_campaign_name,
    get_error_message,
)
from juloserver.julo.clients.sepulsa import SepulsaResponseCodes
from juloserver.payment_point.constants import SepulsaProductType, SepulsaProductCategory


class TestViewRelatedServices(TestCase):
    def setUp(self):
        self.method_self = TransactionMethod.objects.get(pk=1)
        self.method_other = TransactionMethod.objects.get(pk=2)
        self.pln_method = TransactionMethod.objects.get(pk=6)
        self.bpjs_kesehatan_method = TransactionMethod.objects.get(pk=7)
        self.jfinancing_method = TransactionMethodFactory.jfinancing()

        parameter = {
            1: {'is_active': False, 'limit_threshold': 0},
            2: {'is_active': False, 'limit_threshold': 0},
            3: {'is_active': False, 'limit_threshold': 0},
            4: {'is_active': False, 'limit_threshold': 0},
            5: {'is_active': False, 'limit_threshold': 0},
            6: {'is_active': False, 'limit_threshold': 0},
            7: {'is_active': True, 'limit_threshold': 0}
        }
        MobileFeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.TRANSACTION_METHOD_HIGHLIGHT,
            parameters=parameter
        )
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line_j1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application_j1 = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=self.product_line_j1,
        )
        AccountLimitFactory(account=self.account)

        self.baru_campaign = "Baru"
        self.campaign_fs = MobileFeatureSettingFactory(
            is_active=True,
            feature_name=MobileFeatureNameConst.TRANSACTION_METHOD_CAMPAIGN,
            parameters={
                TransactionMethodCode.JFINANCING.code: self.baru_campaign,
            },
        )

    @mock.patch('juloserver.loan.services.loan_related.is_julo_one_product_locked_and_reason')
    def test_construct_transaction_method_for_android(self, mocked_is_julo_one_product_locked):
        self.account.update_safely(status_id=420)
        mocked_is_julo_one_product_locked.return_value = False, None
        bpjs_params = construct_transaction_method_for_android(
            self.account, self.bpjs_kesehatan_method, True, '#DB4D3D'
        )
        self.assertEqual(bpjs_params["is_locked"], False)
        self.assertIsNotNone(bpjs_params["background_icon"])

        pln_params = construct_transaction_method_for_android(
            self.account, self.pln_method, True, '#DB4D3D'
        )
        self.assertEqual(pln_params["is_locked"], False)
        self.assertIsNone(pln_params["background_icon"])

        not_proven_ppob_params = construct_transaction_method_for_android(
            self.account, self.pln_method, False, '#DB4D3D'
        )
        self.assertEqual(not_proven_ppob_params["is_locked"], False)

        not_proven_self_params = construct_transaction_method_for_android(
            self.account, self.method_self, False, '#DB4D3D'
        )
        self.assertEqual(not_proven_self_params["is_locked"], False)

        not_proven_other_params = construct_transaction_method_for_android(
            self.account, self.method_other, False, '#DB4D3D'
        )
        self.assertEqual(not_proven_other_params["is_locked"], True)

        self.account.update_safely(status_id=430)
        suspended_ppob_params = construct_transaction_method_for_android(
            self.account, self.pln_method, True, '#DB4D3D'
        )
        self.assertEqual(suspended_ppob_params["is_locked"], True)

    def test_get_error_message(self):
        self.assertEqual(
            get_error_message(SepulsaResponseCodes.WRONG_NUMBER, SepulsaProductType.MOBILE),
            'Nomor Handphone tidak terdaftar'
        )
        self.assertEqual(
            get_error_message(SepulsaResponseCodes.WRONG_NUMBER, SepulsaProductType.BPJS),
            'Nomor BPJS tidak terdaftar'
        )
        self.assertEqual(
            get_error_message(SepulsaResponseCodes.WRONG_NUMBER, SepulsaProductType.ELECTRICITY),
            'Nomor meter/ ID pelanggan tidak terdaftar'
        )
        self.assertEqual(
            get_error_message(SepulsaResponseCodes.BILL_ALREADY_PAID, ""),
            'Tagihan sudah terbayarkan'
        )
        self.assertEqual(
            get_error_message(SepulsaResponseCodes.PRODUCT_ISSUE, ""),
            'Terjadi kesalahan pada sistem, cobalah beberapa saat lagi'
        )
        self.assertEqual(
            get_error_message(SepulsaResponseCodes.GENERAL_ERROR, SepulsaProductType.MOBILE),
            'Pastikan nomor HP yang kamu masukkan benar. '\
                'Jika sudah benar dan tagihan tidak muncul, artinya tagihanmu sudah terbayar.'
        )

    @mock.patch('juloserver.payment_point.services.views_related.is_product_locked_and_reason')
    def test_construct_transaction_method_campaign_field(self, mock_locked_reason):
        mock_locked_reason.return_value = False, ""

        is_proven = False
        lock_colour = "doesnt matter"
        data = construct_transaction_method_for_android(
            account=self.account,
            transaction_method=self.jfinancing_method,
            is_proven=is_proven,
            lock_colour=lock_colour,
        )

        self.assertEqual(
            data['campaign'],
            self.baru_campaign,
        )

    @mock.patch('juloserver.payment_point.services.views_related.is_customer_can_do_zero_interest')
    def test_get_campaign_name(self, mock_is_customer_zero_interest):
        """
        Transaction Method FS overrides zero interest campaign
        """
        mock_is_customer_zero_interest.return_value = True, {}

        campaign = get_campaign_name(
            is_locked=False,
            account=self.account,
            transaction_method=self.jfinancing_method,
        )

        # overrides zero interest
        self.assertEqual(
            campaign,
            self.baru_campaign,
        )

        # transaction is locked
        campaign = get_campaign_name(
            is_locked=True,
            account=self.account,
            transaction_method=self.jfinancing_method,
        )

        self.assertEqual(campaign, "")

    def test_campaign_from_transaction_method_jfinancing(self):
        input_campaign = 'abc'
        # test case paramter is empty dict
        self.campaign_fs.parameters = {}
        self.campaign_fs.save()

        result = get_campaign_from_transaction_method(
            self.jfinancing_method.id, campaign=input_campaign
        )
        self.assertEqual(result, input_campaign)

        # test case paramter is empty dict
        self.campaign_fs.parameters = None
        self.campaign_fs.save()

        result = get_campaign_from_transaction_method(
            self.jfinancing_method.id, campaign=input_campaign
        )
        self.assertEqual(result, input_campaign)
