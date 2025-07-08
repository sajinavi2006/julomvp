from mock import patch

from django.test import TestCase

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.followthemoney.constants import LenderName, LenderStatus
from juloserver.followthemoney.factories import LenderBalanceCurrentFactory, LenderCurrentFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.loan.constants import LoanFeatureNameConst
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.qris.exceptions import NoQrisLenderAvailable
from juloserver.qris.services.feature_settings import QrisProgressBarSetting
from juloserver.qris.services.view_related import (
    AmarRegisterLoginCallbackService,
    QrisTenureRangeService,
)
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.tests.factories import (
    ApplicationFactory,
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
from juloserver.qris.constants import QrisLinkageStatus
from juloserver.qris.models import QrisPartnerLinkage
from juloserver.qris.services.view_related import AmarUserStateService, get_qris_user_state_service
from juloserver.qris.tests.factories import (
    QrisLinkageLenderAgreementFactory,
    QrisPartnerLinkageFactory,
    QrisUserStateFactory,
)


class TestAmarUserStateService(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.partner = PartnerFactory(
            name=PartnerNameConstant.AMAR,
        )
        status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=status_code)
        self.account_limit = AccountLimitFactory(account=self.account, available_limit=10000)

        self.amar_faq_link = "queen of meereen"
        self.qris_faq_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_FAQ,
            is_active=True,
            parameters={
                PartnerNameConstant.AMAR: {
                    'faq_link': self.amar_faq_link,
                },
            },
        )

        # set up multi lender
        self.blue_finc_lender = LenderCurrentFactory(
            lender_name=LenderName.BLUEFINC,
        )
        self.out_of_balance_threshold = 500_000
        self.blue_finc_balance = LenderBalanceCurrentFactory(
            lender=self.blue_finc_lender,
        )
        self.multi_lender_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_MULTIPLE_LENDER,
            is_active=True,
            parameters={
                "out_of_balance_threshold": self.out_of_balance_threshold,
                "lender_names_ordered_by_priority": [
                    self.blue_finc_lender.lender_name,
                ],
            },
        )

        self.qris_progress_bar_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_PROGRESS_BAR,
            is_active=False,
            parameters={
                "disappear_after_success": {
                    "is_active": True,
                    "active_seconds_after_success": QrisProgressBarSetting.DEFAULT_ACTIVE_SECONDS_AFTER_SUCCESS,  # one day
                },
                "progress_detail": {
                    QrisProgressBarSetting.STATUS_DEFAULT: {
                        "percentage": "25",
                        "messages": {
                            "title": "xxx",
                            "body": "xxx",
                            "footer": "xxx",
                        },
                    },
                    QrisLinkageStatus.REQUESTED: {
                        "percentage": "50",
                        "messages": {
                            "title": "xxx",
                            "body": "xxx",
                            "footer": "xxx",
                        },
                    },
                    QrisLinkageStatus.REGIS_FORM: {
                        "percentage": "75",
                        "messages": {
                            "title": "xxx",
                            "body": "xxx",
                            "footer": "xxx",
                        },
                    },
                    QrisLinkageStatus.FAILED: {
                        "percentage": "75",
                        "messages": {
                            "title": "xxx",
                            "body": "xxx",
                            "footer": "xxx",
                        },
                    },
                    QrisLinkageStatus.SUCCESS: {
                        "percentage": "100",
                        "messages": {
                            "title": "xxx",
                            "body": "xxx",
                            "footer": "xxx",
                        },
                    },
                },
            },
        )

    def test_get_response(self):
        service = get_qris_user_state_service(
            customer_id=self.customer.id, partner_name=self.partner.name
        )

        self.assertEqual(type(service), AmarUserStateService)

        # first call, no linkage, hasn't signed lender
        response = service.get_response()

        empty_response = {
            "email": "",
            "phone": "",
            "nik": "",
            "is_linkage_active": False,
            "signature_id": "",
            "to_partner_xid": "",
            "faq_link": self.amar_faq_link,
            "to_sign_lender": self.blue_finc_lender.lender_name,
            "registration_progress_bar": {
                "is_active": False,
                "percentage": "",
                "messages": {"title": "", "body": "", "footer": ""},
            },
        }

        self.assertEqual(response, empty_response)

        linkage = QrisPartnerLinkage.objects.filter(
            customer_id=self.customer.id,
            partner_id=self.partner.id,
            status=QrisLinkageStatus.REQUESTED,
        ).last()

        self.assertIsNone(linkage)

        # second call, but no image signature
        linkage = QrisPartnerLinkageFactory(
            customer_id=self.customer.id,
            status=QrisLinkageStatus.REQUESTED,
            partner_id=self.partner.id,
        )
        QrisUserStateFactory(
            qris_partner_linkage=linkage,
        )

        service = get_qris_user_state_service(
            customer_id=self.customer.id, partner_name=self.partner.name
        )
        response = service.get_response()
        self.assertEqual(response, empty_response)

    def test_response_success(self):

        # init
        image = ImageFactory()
        linkage = QrisPartnerLinkageFactory(
            customer_id=self.customer.id,
            status=QrisLinkageStatus.REQUESTED,
            partner_id=self.partner.id,
        )
        user_state = QrisUserStateFactory(
            qris_partner_linkage=linkage,
        )

        user_state.signature_image = image
        user_state.save()

        linkage.status = QrisLinkageStatus.SUCCESS
        linkage.save()

        self.blue_finc_balance.available_balance = self.out_of_balance_threshold
        self.blue_finc_balance.save()

        # sign with lender
        QrisLinkageLenderAgreementFactory(
            qris_partner_linkage=linkage,
            lender_id=self.blue_finc_lender.id,
            signature_image_id=image.id,
        )

        service = get_qris_user_state_service(
            customer_id=self.customer.id, partner_name=self.partner.name
        )
        response = service.get_response()

        expected_response = {
            "email": self.customer.email,
            "phone": self.customer.phone,
            "nik": self.customer.nik,
            "is_linkage_active": True,
            "signature_id": str(image.id),
            "to_partner_xid": linkage.to_partner_user_xid.hex,
            "faq_link": self.amar_faq_link,
            "available_limit": self.account_limit.available_limit,
            "to_sign_lender": "",
            "registration_progress_bar": {
                "is_active": False,
                "percentage": "",
                "messages": {"title": "", "body": "", "footer": ""},
            },
        }

        self.assertEqual(response, expected_response)

    def test_lender_unavailable(self):
        """
        Test lender out of money
        """
        # set up lender out of money
        self.blue_finc_balance.available_balance = -100
        self.blue_finc_balance.save()

        # CASE I, without linkage
        service = get_qris_user_state_service(
            customer_id=self.customer.id, partner_name=self.partner.name
        )

        self.assertEqual(type(service), AmarUserStateService)

        # first call, no linkage, hasn't signed lender
        # still get lender to sign
        response = service.get_response()
        self.assertEqual(
            response['to_sign_lender'],
            self.blue_finc_lender.lender_name,
        )

        # case II, with linkage -> throw error
        image = ImageFactory()
        linkage = QrisPartnerLinkageFactory(
            customer_id=self.customer.id,
            status=QrisLinkageStatus.REQUESTED,
            partner_id=self.partner.id,
        )
        user_state = QrisUserStateFactory(
            qris_partner_linkage=linkage,
        )

        user_state.signature_image = image
        user_state.save()

        linkage.status = QrisLinkageStatus.SUCCESS
        linkage.save()

        with self.assertRaises(NoQrisLenderAvailable):
            service = get_qris_user_state_service(
                customer_id=self.customer.id, partner_name=self.partner.name
            )
            service.get_response()

    @patch("juloserver.qris.services.view_related.has_linkage_signed_with_current_lender")
    @patch("juloserver.qris.services.view_related.is_success_linkage_older_than")
    def test_registration_progress_bar(
        self, mock_is_success_linkage_older_than, mock_has_linkage_signed
    ):

        progress_detail_data = self.qris_progress_bar_fs.parameters['progress_detail']

        # CASE NO LINKAGE
        mock_has_linkage_signed.return_value = True, "any lender"

        # expired, no linkage (might never happen, since no linkage, can not expire)
        mock_is_success_linkage_older_than.return_value = True
        self.qris_progress_bar_fs.is_active = True
        self.qris_progress_bar_fs.parameters['disappear_after_success']['is_active'] = True
        self.qris_progress_bar_fs.save()

        service = get_qris_user_state_service(
            customer_id=self.customer.id, partner_name=self.partner.name
        )
        data = service.get_response()

        self.assertEqual(
            data['registration_progress_bar'],
            {
                "is_active": True,
                "percentage": progress_detail_data[QrisProgressBarSetting.STATUS_DEFAULT][
                    'percentage'
                ],
                "messages": {
                    "title": progress_detail_data[QrisProgressBarSetting.STATUS_DEFAULT][
                        'messages'
                    ]['title'],
                    "body": progress_detail_data[QrisProgressBarSetting.STATUS_DEFAULT]['messages'][
                        'body'
                    ],
                    "footer": progress_detail_data[QrisProgressBarSetting.STATUS_DEFAULT][
                        'messages'
                    ]['footer'],
                },
            },
        )

        # still not expired, but no linkage
        mock_is_success_linkage_older_than.return_value = False
        self.qris_progress_bar_fs.parameters['disappear_after_success']['is_active'] = False
        self.qris_progress_bar_fs.save()

        service = get_qris_user_state_service(
            customer_id=self.customer.id, partner_name=self.partner.name
        )
        data = service.get_response()
        self.assertEqual(
            data['registration_progress_bar'],
            {
                "is_active": True,
                "percentage": progress_detail_data[QrisProgressBarSetting.STATUS_DEFAULT][
                    'percentage'
                ],
                "messages": {
                    "title": progress_detail_data[QrisProgressBarSetting.STATUS_DEFAULT][
                        'messages'
                    ]['title'],
                    "body": progress_detail_data[QrisProgressBarSetting.STATUS_DEFAULT]['messages'][
                        'body'
                    ],
                    "footer": progress_detail_data[QrisProgressBarSetting.STATUS_DEFAULT][
                        'messages'
                    ]['footer'],
                },
            },
        )

        # re-init service, case with linkage status 'requested'
        linkage = QrisPartnerLinkageFactory(
            customer_id=self.customer.id,
            status=QrisLinkageStatus.REQUESTED,
            partner_id=self.partner.id,
        )
        user_state = QrisUserStateFactory(
            qris_partner_linkage=linkage,
        )
        image = ImageFactory()
        user_state.signature_image = image
        user_state.save()

        service = get_qris_user_state_service(
            customer_id=self.customer.id, partner_name=self.partner.name
        )
        data = service.get_response()

        # assert
        self.assertEqual(
            data['registration_progress_bar'],
            {
                "is_active": True,
                "percentage": progress_detail_data[QrisLinkageStatus.REQUESTED]['percentage'],
                "messages": {
                    "title": progress_detail_data[QrisLinkageStatus.REQUESTED]['messages']['title'],
                    "body": progress_detail_data[QrisLinkageStatus.REQUESTED]['messages']['body'],
                    "footer": progress_detail_data[QrisLinkageStatus.REQUESTED]['messages'][
                        'footer'
                    ],
                },
            },
        )

        # assert case strange/unexpected status => get default messages
        linkage.status = QrisLinkageStatus.IGNORED
        linkage.save()

        service = get_qris_user_state_service(
            customer_id=self.customer.id, partner_name=self.partner.name
        )
        data = service.get_response()
        progress_detail_data = self.qris_progress_bar_fs.parameters['progress_detail']
        self.assertEqual(
            data['registration_progress_bar'],
            {
                "is_active": True,
                "percentage": progress_detail_data['default']['percentage'],
                "messages": {
                    "title": progress_detail_data['default']['messages']['title'],
                    "body": progress_detail_data['default']['messages']['body'],
                    "footer": progress_detail_data['default']['messages']['footer'],
                },
            },
        )


class TestAmarRegisterLoginCallbackService(TestCase):
    def setUp(self):
        self.to_partner_user_xid = "2a196a04bf5f45a18187136a6d1706ff"
        self.status = "accepted"
        self.account_number = "1503566938"
        self.type = "new"

    @patch("juloserver.qris.services.view_related.process_callback_register_from_amar_task.delay")
    def test_happy_case(self, mock_process_callback):

        input_data = {
            "partnerCustomerId": self.to_partner_user_xid,
            "status": self.status,
            "accountNumber": self.account_number,
            "type": self.type,
        }

        service = AmarRegisterLoginCallbackService(
            data=input_data,
        )

        service.process_callback()

        mock_process_callback.assert_called_once_with(
            to_partner_user_xid=self.to_partner_user_xid,
            amar_status=self.status,
            payload=input_data,
        )


class TestQrisTenureService(TestCase):
    def setUp(self):
        self.max_tenure = 10
        self.min_tenure = 4
        self.customer = CustomerFactory()
        self.transaction_method = TransactionMethodFactory.qris_1()

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
            max_duration=8,
            min_duration=2,
        )
        self.fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_TENURE_FROM_LOAN_AMOUNT,
            parameters={
                "loan_amount_tenure_map": [
                    (10_000, 19_999, 999),
                    (20_000, 30_000, 4),
                    (15_000, 25_000, 4),
                    (90_001, 100_000, 5),
                    (29_999, 40_000, -1),
                ]
            },
            is_active=True,
        )

    @patch(
        "juloserver.loan.services.loan_creation.get_credit_matrix_and_credit_matrix_product_line"
    )
    def test_case_fs_inactive(self, mock_get_cmpl):
        mock_get_cmpl.return_value = self.credit_matrix, self.credit_matrix_product_line
        self.fs.is_active = False
        self.fs.save()
        service = QrisTenureRangeService(
            customer=self.customer,
        )

        # inactive, => default 1 => min tenure from CMPL

        # sorted duration, then from_amount
        expected_response = [
            {
                "from_amount": 10_001,
                "to_amount": 19_999,
                "duration": self.credit_matrix_product_line.min_duration,  # 2
                "monthly_interest_rate": 0.04,
                "provision_fee_rate": 0.08,
            },
            {
                "from_amount": 15_001,
                "to_amount": 25_000,
                "duration": self.credit_matrix_product_line.min_duration,  # 2
                "monthly_interest_rate": 0.04,
                "provision_fee_rate": 0.08,
            },
            {
                "from_amount": 20_001,
                "to_amount": 30_000,
                "duration": self.credit_matrix_product_line.min_duration,  # 2
                "monthly_interest_rate": 0.04,
                "provision_fee_rate": 0.08,
            },
            {
                "from_amount": 30_000,
                "to_amount": 40_000,
                "duration": self.credit_matrix_product_line.min_duration,  # 2
                "monthly_interest_rate": 0.04,
                "provision_fee_rate": 0.08,
            },
            {
                "from_amount": 90_002,
                "to_amount": 100_000,
                "duration": self.credit_matrix_product_line.min_duration,  # 2
                "monthly_interest_rate": 0.04,
                "provision_fee_rate": 0.08,
            },
        ]

        response = service.get_response()
        self.assertEqual(
            response['tenure_range'],
            expected_response,
        )

    @patch(
        "juloserver.loan.services.loan_creation.get_credit_matrix_and_credit_matrix_product_line"
    )
    def test_ok_cm(self, mock_get_cmpl):
        mock_get_cmpl.return_value = self.credit_matrix, self.credit_matrix_product_line
        service = QrisTenureRangeService(
            customer=self.customer,
        )

        # response is sorted by duration first, then from amount
        expected_response = [
            {
                "from_amount": 30_000,
                "to_amount": 40_000,
                "duration": self.credit_matrix_product_line.min_duration,  # 2
                "monthly_interest_rate": 0.04,
                "provision_fee_rate": 0.08,
            },
            {
                "from_amount": 15_001,
                "to_amount": 25_000,
                "duration": 4,
                "monthly_interest_rate": 0.04,
                "provision_fee_rate": 0.08,
            },
            {
                "from_amount": 20_001,
                "to_amount": 30_000,
                "duration": 4,
                "monthly_interest_rate": 0.04,
                "provision_fee_rate": 0.08,
            },
            {
                "from_amount": 90_002,
                "to_amount": 100_000,
                "duration": 5,
                "monthly_interest_rate": 0.04,
                "provision_fee_rate": 0.08,
            },
            {
                "from_amount": 10_001,
                "to_amount": 19_999,
                "duration": self.credit_matrix_product_line.max_duration,  # 8
                "monthly_interest_rate": 0.04,
                "provision_fee_rate": 0.08,
            },
        ]
        response = service.get_response()
        self.assertEqual(
            response['tenure_range'],
            expected_response,
        )

    @patch("juloserver.loan.services.loan_creation.get_credit_matrix_repeat")
    @patch(
        "juloserver.loan.services.loan_creation.get_credit_matrix_and_credit_matrix_product_line"
    )
    def test_ok_cm_repeat(self, mock_get_cmpl, mock_get_cm_repeat):
        mock_get_cmpl.return_value = self.credit_matrix, self.credit_matrix_product_line

        max_tenure = 10
        min_tenure = 3
        cm_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self.transaction_method,
            version=1,
            interest=0.5,
            provision=self.provision_rate,
            max_tenure=max_tenure,
            min_tenure=min_tenure,
        )
        mock_get_cm_repeat.return_value = cm_repeat

        expected_response = [
            {
                "from_amount": 30_000,
                "to_amount": 40_000,
                "duration": min_tenure,  # 3
                "monthly_interest_rate": 0.5,
                "provision_fee_rate": 0.08,
            },
            {
                "from_amount": 15_001,
                "to_amount": 25_000,
                "duration": 4,
                "monthly_interest_rate": 0.5,
                "provision_fee_rate": 0.08,
            },
            {
                "from_amount": 20_001,
                "to_amount": 30_000,
                "duration": 4,
                "monthly_interest_rate": 0.5,
                "provision_fee_rate": 0.08,
            },
            {
                "from_amount": 90_002,
                "to_amount": 100_000,
                "duration": 5,
                "monthly_interest_rate": 0.5,
                "provision_fee_rate": 0.08,
            },
            {
                "from_amount": 10_001,
                "to_amount": 19_999,
                "duration": max_tenure,
                "monthly_interest_rate": 0.5,
                "provision_fee_rate": 0.08,
            },
        ]

        service = QrisTenureRangeService(
            customer=self.customer,
        )

        response = service.get_response()
        self.assertEqual(
            response['tenure_range'],
            expected_response,
        )
