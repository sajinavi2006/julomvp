from django.test import TestCase
from mock import MagicMock, patch

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.followthemoney.constants import LenderName
from juloserver.followthemoney.factories import LenderBalanceCurrentFactory, LenderCurrentFactory
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CreditMatrixRepeatFactory,
    CustomerFactory,
    FeatureSettingFactory,
    ImageFactory,
    PartnerFactory,
    ProductLineFactory,
    ProductLookupFactory,
    StatusLookupFactory,
)
from juloserver.loan.constants import LoanErrorCodes, LoanFeatureNameConst, LoanTaxConst
from juloserver.loan.exceptions import (
    AccountLimitExceededException,
    AccountUnavailable,
    TransactionAmountExceeded,
    TransactionAmountTooLow,
)
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.qris.constants import QrisLinkageStatus, QrisProductName
from juloserver.qris.exceptions import (
    HasNotSignedWithLender,
    NoQrisLenderAvailable,
    QrisLinkageNotFound,
)
from juloserver.qris.models import QrisLinkageLenderAgreement
from juloserver.qris.services.view_related import QrisLimitEligibilityService
from juloserver.qris.tests.factories import QrisPartnerLinkageFactory


class TestQrisLimitEligibilityService(TestCase):
    def setUp(self):
        self.partner_user = AuthUserFactory()
        self.partner = PartnerFactory(
            user=self.partner_user,
            name=PartnerNameConstant.AMAR,
        )
        self.transaction_method = TransactionMethodFactory.qris_1()

        self.customer = CustomerFactory()
        self.linkage = QrisPartnerLinkageFactory(
            status=QrisLinkageStatus.SUCCESS,
            customer_id=self.customer.id,
            partner_id=self.partner.id,
            partner_callback_payload={"any": "any"},
        )

        self.available_limit = 100_000
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code,
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
            available_limit=self.available_limit,
        )

        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )

        self.provision_rate = 0.08
        self.product = ProductLookupFactory(origination_fee_pct=self.provision_rate)
        self.credit_matrix = CreditMatrixFactory(
            product=self.product,
        )
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.application.product_line,
        )
        self.credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self.transaction_method,
            version=1,
            interest=0.5,
            provision=self.provision_rate,
            max_tenure=6,
        )
        self.tax_percent = 0.1
        self.tax_fs = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": self.tax_percent,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )
        self.max_qris_requested_amount = 3_000_000
        self.min_qris_requested_amount = 1000
        self.qris_loan_eligibility_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_LOAN_ELIGIBILITY_SETTING,
            parameters={
                "max_requested_amount": self.max_qris_requested_amount,
                "min_requested_amount": self.min_qris_requested_amount,
            },
            is_active=True,
        )

        # create lender & signing
        self.lender_user = AuthUserFactory()
        self.lender = LenderCurrentFactory(
            lender_name=LenderName.BLUEFINC,
            user=self.lender_user,
        )
        self.lender_balance = LenderBalanceCurrentFactory(
            lender=self.lender,
            available_balance=10_000_000,
        )
        self.multi_lender_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_MULTIPLE_LENDER,
            parameters={
                "out_of_balance_threshold": 0,
                "lender_names_ordered_by_priority": [
                    self.lender.lender_name,
                ],
            },
        )
        self.signature_image = ImageFactory()
        QrisLinkageLenderAgreement.objects.create(
            qris_partner_linkage=self.linkage,
            lender_id=self.lender.id,
            signature_image_id=self.signature_image.id,
        )

    @patch("juloserver.qris.services.view_related.get_credit_matrix_repeat")
    @patch("juloserver.qris.services.view_related.get_credit_matrix_and_credit_matrix_product_line")
    def test_ok(self, mock_get_cm, mock_get_cm_repeat):
        mock_get_cm.return_value = self.credit_matrix, self.credit_matrix_product_line
        mock_get_cm_repeat.return_value = self.credit_matrix_repeat

        transaction_detail = {
            "feeAmount": 1000,
            "tipAmount": 1000,
            "transactionAmount": 1000,
            "merchantName": "abcd",
            "merchantCity": "abcd",
            "merchantCategoryCode": "abcd",
            "merchantCriteria": "abcd",
            "accquireId": "abcd",
            "accquirerName": "abcd",
            "terminalId": 123213,
        }

        totalAmount = self.available_limit / 2
        input_data = {
            "partnerUserId": self.linkage.to_partner_user_xid.hex,
            "totalAmount": totalAmount,
            "productId": QrisProductName.QRIS.code,
            "productName": QrisProductName.QRIS.name,
            "transactionDetail": transaction_detail,
        }

        service = QrisLimitEligibilityService(
            data=input_data,
            partner=self.partner,
        )

        result = service.perform_check()

        self.assertIsNone(result)

    @patch("juloserver.qris.services.view_related.get_credit_matrix_repeat")
    @patch("juloserver.qris.services.view_related.get_credit_matrix_and_credit_matrix_product_line")
    @patch('juloserver.qris.services.view_related.LoanAmountFormulaService')
    def test_insufficient_limit(self, mock_formula_service, mock_get_cm, mock_get_cm_repeat):
        mock_get_cm.return_value = self.credit_matrix, self.credit_matrix_product_line
        mock_get_cm_repeat.return_value = self.credit_matrix_repeat

        mock_obj = MagicMock()
        mock_formula_service.return_value = mock_obj
        mock_obj.final_amount = self.available_limit * 10

        transaction_detail = {
            "feeAmount": 1000,
            "tipAmount": 1000,
            "transactionAmount": 1000,
            "merchantName": "abcd",
            "merchantCity": "abcd",
            "merchantCategoryCode": "abcd",
            "merchantCriteria": "abcd",
            "accquireId": "abcd",
            "accquirerName": "abcd",
            "terminalId": 123213,
        }

        totalAmount = self.available_limit / 2
        input_data = {
            "partnerUserId": self.linkage.to_partner_user_xid.hex,
            "totalAmount": totalAmount,
            "productId": QrisProductName.QRIS.code,
            "productName": QrisProductName.QRIS.name,
            "transactionDetail": transaction_detail,
        }

        self.account_limit.available_limit = 0
        self.account_limit.save()

        service = QrisLimitEligibilityService(
            data=input_data,
            partner=self.partner,
        )

        with self.assertRaises(AccountLimitExceededException):
            service.perform_check()

        mock_get_cm.assert_called_once_with(
            application=self.application,
            is_self_bank_account=False,
            transaction_type=TransactionMethodCode.QRIS_1.name,
        )
        mock_get_cm_repeat.assert_called_once_with(
            customer_id=self.customer.id,
            product_line_id=self.credit_matrix_product_line.product.product_line_code,
            transaction_method_id=TransactionMethodCode.QRIS_1.code,
        )
        mock_formula_service.assert_called_once_with(
            method_code=TransactionMethodCode.QRIS_1.code,
            requested_amount=totalAmount,
            tax_rate=self.tax_percent,
            provision_rate=self.provision_rate,
        )


    def test_unavailable_account(self):
        transaction_detail = {
            "feeAmount": 1000,
            "tipAmount": 1000,
            "transactionAmount": 1000,
            "merchantName": "abcd",
            "merchantCity": "abcd",
            "merchantCategoryCode": "abcd",
            "merchantCriteria": "abcd",
            "accquireId": "abcd",
            "accquirerName": "abcd",
            "terminalId": 123213,
        }

        totalAmount = self.available_limit / 2
        input_data = {
            "partnerUserId": self.linkage.to_partner_user_xid.hex,
            "totalAmount": totalAmount,
            "productId": QrisProductName.QRIS.code,
            "productName": QrisProductName.QRIS.name,
            "transactionDetail": transaction_detail,
        }

        self.account.status_id = 430
        self.account.save()

        service = QrisLimitEligibilityService(
            data=input_data,
            partner=self.partner,
        )

        with self.assertRaises(AccountUnavailable):
            service.perform_check()

    def test_linkage_not_active(self):
        transaction_detail = {
            "feeAmount": 1000,
            "tipAmount": 1000,
            "transactionAmount": 1000,
            "merchantName": "abcd",
            "merchantCity": "abcd",
            "merchantCategoryCode": "abcd",
            "merchantCriteria": "abcd",
            "accquireId": "abcd",
            "accquirerName": "abcd",
            "terminalId": 123213,
        }

        totalAmount = self.available_limit / 2
        input_data = {
            "partnerUserId": self.linkage.to_partner_user_xid.hex,
            "totalAmount": totalAmount,
            "productId": QrisProductName.QRIS.code,
            "productName": QrisProductName.QRIS.name,
            "transactionDetail": transaction_detail,
        }

        self.linkage.status = QrisLinkageStatus.REQUESTED
        self.linkage.save()

        service = QrisLimitEligibilityService(
            data=input_data,
            partner=self.partner,
        )

        with self.assertRaises(QrisLinkageNotFound):
            service.perform_check()

    @patch("juloserver.qris.services.view_related.has_linkage_signed_with_current_lender")
    @patch("juloserver.qris.services.view_related.get_credit_matrix_repeat")
    @patch("juloserver.qris.services.view_related.get_credit_matrix_and_credit_matrix_product_line")
    def test_no_lender_available(self, mock_get_cm, mock_get_cm_repeat, mock_has_linkage_signed):
        mock_get_cm.return_value = self.credit_matrix, self.credit_matrix_product_line
        mock_get_cm_repeat.return_value = self.credit_matrix_repeat
        transaction_detail = {
            "feeAmount": 1000,
            "tipAmount": 1000,
            "transactionAmount": 1000,
            "merchantName": "abcd",
            "merchantCity": "abcd",
            "merchantCategoryCode": "abcd",
            "merchantCriteria": "abcd",
            "accquireId": "abcd",
            "accquirerName": "abcd",
            "terminalId": 123213,
        }

        totalAmount = self.available_limit / 2
        input_data = {
            "partnerUserId": self.linkage.to_partner_user_xid.hex,
            "totalAmount": totalAmount,
            "productId": QrisProductName.QRIS.code,
            "productName": QrisProductName.QRIS.name,
            "transactionDetail": transaction_detail,
        }

        service = QrisLimitEligibilityService(
            data=input_data,
            partner=self.partner,
        )

        mock_has_linkage_signed.side_effect = NoQrisLenderAvailable
        with self.assertRaises(NoQrisLenderAvailable):
            service.perform_check()

    @patch("juloserver.qris.services.view_related.has_linkage_signed_with_current_lender")
    @patch("juloserver.qris.services.view_related.get_credit_matrix_repeat")
    @patch("juloserver.qris.services.view_related.get_credit_matrix_and_credit_matrix_product_line")
    def test_lender_not_signed(self, mock_get_cm, mock_get_cm_repeat, mock_has_linkage_signed):
        mock_get_cm.return_value = self.credit_matrix, self.credit_matrix_product_line
        mock_get_cm_repeat.return_value = self.credit_matrix_repeat

        transaction_detail = {
            "feeAmount": 1000,
            "tipAmount": 1000,
            "transactionAmount": 1000,
            "merchantName": "abcd",
            "merchantCity": "abcd",
            "merchantCategoryCode": "abcd",
            "merchantCriteria": "abcd",
            "accquireId": "abcd",
            "accquirerName": "abcd",
            "terminalId": 123213,
        }

        totalAmount = self.available_limit / 2
        input_data = {
            "partnerUserId": self.linkage.to_partner_user_xid.hex,
            "totalAmount": totalAmount,
            "productId": QrisProductName.QRIS.code,
            "productName": QrisProductName.QRIS.name,
            "transactionDetail": transaction_detail,
        }

        service = QrisLimitEligibilityService(
            data=input_data,
            partner=self.partner,
        )

        mock_has_linkage_signed.return_value = False, self.lender

        with self.assertRaises(HasNotSignedWithLender):
            service.perform_check()

    def test_min_max_requested_amount(self):
        transaction_detail = {
            "feeAmount": 1000,
            "tipAmount": 1000,
            "transactionAmount": 1000,
            "merchantName": "abcd",
            "merchantCity": "abcd",
            "merchantCategoryCode": "abcd",
            "merchantCriteria": "abcd",
            "accquireId": "abcd",
            "accquirerName": "abcd",
            "terminalId": 123213,
        }

        # test max requested amount
        totalAmount = self.max_qris_requested_amount + 1
        input_data = {
            "partnerUserId": self.linkage.to_partner_user_xid.hex,
            "totalAmount": totalAmount,
            "productId": QrisProductName.QRIS.code,
            "productName": QrisProductName.QRIS.name,
            "transactionDetail": transaction_detail,
        }

        service = QrisLimitEligibilityService(
            data=input_data,
            partner=self.partner,
        )

        with self.assertRaises(TransactionAmountExceeded):
            service.perform_check()

        # tes min requested amount
        totalAmount = self.min_qris_requested_amount - 1
        input_data.update(
            {
                "totalAmount": totalAmount,
            }
        )

        with self.assertRaises(TransactionAmountTooLow):
            service.perform_check()
