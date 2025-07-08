from django.test import TestCase
from django.utils import timezone

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.followthemoney.constants import LenderStatus
from juloserver.followthemoney.factories import LenderBalanceCurrentFactory, LenderCurrentFactory
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    DocumentFactory,
    FeatureSettingFactory,
    ImageFactory,
    PartnerFactory,
)
from juloserver.loan.constants import LoanFeatureNameConst
from juloserver.qris.constants import QrisLinkageStatus
from juloserver.qris.exceptions import NoQrisLenderAvailable
from juloserver.qris.models import QrisLinkageLenderAgreement
from juloserver.qris.services.core_services import (
    get_current_available_qris_lender,
    get_qris_lender_from_lender_name,
    has_linkage_signed_with_current_lender,
    is_qris_customer_signed_with_lender,
    is_qris_linkage_signed_with_lender,
    is_success_linkage_older_than,
    retroload_blue_finc_lender_qris_lender_agreement,
    update_linkage_status,
)
from juloserver.qris.services.feature_settings import (
    QrisFAQSetting,
    QrisFAQSettingHandler,
    QrisTenureFromLoanAmountHandler,
    QrisTenureFromLoanAmountSetting,
)
from juloserver.qris.tests.factories import (
    QrisPartnerLinkageFactory,
    QrisPartnerLinkageHistoryFactory,
    QrisUserStateFactory,
)


class TestQrisFAQHandler(TestCase):
    def setUp(self):
        self.amar_faq_link = "What Is Dead May Never Die"
        self.fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_FAQ,
            is_active=True,
            parameters={
                PartnerNameConstant.AMAR: {
                    'faq_link': self.amar_faq_link,
                },
            },
        )

    def test_case_inactive(self):
        self.fs.is_active = False
        self.fs.save()

        handler = QrisFAQSettingHandler()
        self.assertEqual(
            handler.get_amar_faq_link(),
            QrisFAQSetting.DEFAULT_AMAR_FAQ_LINK,
        )

    def test_case_active(self):
        self.fs.is_active = True
        self.fs.save()

        handler = QrisFAQSettingHandler()
        self.assertEqual(
            handler.get_amar_faq_link(),
            self.amar_faq_link,
        )

    def test_case_active_but_bad_fs(self):
        self.fs.parameters = {}

        self.fs.is_active = True
        self.fs.save()

        handler = QrisFAQSettingHandler()
        self.assertEqual(
            handler.get_amar_faq_link(),
            QrisFAQSetting.DEFAULT_AMAR_FAQ_LINK,
        )

        self.fs.parameters = {'amar': ''}
        self.fs.save()

        handler = QrisFAQSettingHandler()
        self.assertEqual(
            handler.get_amar_faq_link(),
            QrisFAQSetting.DEFAULT_AMAR_FAQ_LINK,
        )


class TestQrisTenureFromLoanAmountHandler(TestCase):
    def setUp(self):
        self.fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_TENURE_FROM_LOAN_AMOUNT,
            parameters={
                "loan_amount_tenure_map": [
                    (0, 500_000, 1),
                    (500_000, 1_000_000, 2),
                ]
            },
            is_active=True,
        )

    def test_case_inactive(self):
        self.fs.is_active = False
        self.fs.save()

        tenure_2_amount = 600_000
        handler = QrisTenureFromLoanAmountHandler(
            amount=tenure_2_amount,
        )
        self.assertEqual(
            handler.get_tenure(),
            QrisTenureFromLoanAmountSetting.DEFAULT_TENURE,
        )

    def test_case_out_of_range(self):
        small_amount = -1000
        big_amount = 999_999_999

        handler = QrisTenureFromLoanAmountHandler(
            amount=small_amount,
        )
        self.assertEqual(
            handler.get_tenure(),
            QrisTenureFromLoanAmountSetting.DEFAULT_TENURE,
        )

        handler = QrisTenureFromLoanAmountHandler(
            amount=big_amount,
        )

        self.assertEqual(
            handler.get_tenure(),
            QrisTenureFromLoanAmountSetting.DEFAULT_TENURE,
        )

    def test_happy_case(self):
        amount = 500_001

        handler = QrisTenureFromLoanAmountHandler(
            amount=amount,
        )
        self.assertEqual(handler.get_tenure(), 2)


class TestRetroloadBluefincLender(TestCase):
    """
    Unitest for retroload script that will be run once
    Delete this test class in the future won't cause issue
    """

    def setUp(self):
        # create signed states
        self.partner = PartnerFactory(
            name=PartnerNameConstant.AMAR,
        )
        self.blue_finc_lender = LenderCurrentFactory(
            lender_name='blue_finc_lender',
        )

        # user 1
        self.document_1 = DocumentFactory()
        self.customer_1 = CustomerFactory()
        self.signature_1 = ImageFactory()
        self.linkage_1 = QrisPartnerLinkageFactory(
            customer_id=self.customer_1.id,
            status=QrisLinkageStatus.SUCCESS,
            partner_id=self.partner.id,
        )
        self.state_1 = QrisUserStateFactory(
            qris_partner_linkage=self.linkage_1,
            signature_image=self.signature_1,
            master_agreement_id=self.document_1.id,
        )

        # user 2
        self.document_2 = DocumentFactory()
        self.customer_2 = CustomerFactory()
        self.signature_2 = ImageFactory()
        self.linkage_2 = QrisPartnerLinkageFactory(
            customer_id=self.customer_2.id,
            status=QrisLinkageStatus.SUCCESS,
            partner_id=self.partner.id,
        )
        self.state_2 = QrisUserStateFactory(
            qris_partner_linkage=self.linkage_2,
            signature_image=self.signature_2,
            master_agreement_id=self.document_2.id,
        )

    def test_case_run_first_time(self):
        retroload_blue_finc_lender_qris_lender_agreement()

        is_exist_agreement_user_1 = QrisLinkageLenderAgreement.objects.filter(
            lender_id=self.blue_finc_lender.id,
            qris_partner_linkage=self.linkage_1,
            signature_image_id=self.signature_1.id,
            master_agreement_id=self.document_1.id,
        ).exists()

        self.assertTrue(is_exist_agreement_user_1)

        is_exist_agreement_user_2 = QrisLinkageLenderAgreement.objects.filter(
            lender_id=self.blue_finc_lender.id,
            qris_partner_linkage=self.linkage_2,
            signature_image_id=self.signature_2.id,
            master_agreement_id=self.document_2.id,
        ).exists()

        self.assertTrue(is_exist_agreement_user_2)

        # create user 3
        self.document_3 = DocumentFactory()
        self.customer_3 = CustomerFactory()
        self.signature_3 = ImageFactory()
        self.linkage_3 = QrisPartnerLinkageFactory(
            customer_id=self.customer_3.id,
            status=QrisLinkageStatus.SUCCESS,
            partner_id=self.partner.id,
        )
        self.state_3 = QrisUserStateFactory(
            qris_partner_linkage=self.linkage_3,
            signature_image=self.signature_3,
            master_agreement_id=self.document_3.id,
        )

        # running second time won't throw error

        retroload_blue_finc_lender_qris_lender_agreement()
        is_exist_agreement_user_3 = QrisLinkageLenderAgreement.objects.filter(
            lender_id=self.blue_finc_lender.id,
            qris_partner_linkage=self.linkage_3,
            signature_image_id=self.signature_3.id,
            master_agreement_id=self.document_3.id,
        ).exists()

        self.assertTrue(is_exist_agreement_user_3)


class TestQrisMultipleLenderFunctions(TestCase):
    def setUp(self):
        self.partner = PartnerFactory(
            name=PartnerNameConstant.AMAR,
        )
        self.signature_1 = ImageFactory()
        self.customer_1 = CustomerFactory()
        self.success_linkage = QrisPartnerLinkageFactory(
            customer_id=self.customer_1.id,
            status=QrisLinkageStatus.SUCCESS,
            partner_id=self.partner.id,
        )
        self.state_1 = QrisUserStateFactory(
            qris_partner_linkage=self.success_linkage,
            signature_image=self.signature_1,
        )

        self.signature_2 = ImageFactory()
        self.customer_2 = CustomerFactory()
        self.inactive_linkage = QrisPartnerLinkageFactory(
            customer_id=self.customer_2.id,
            status=QrisLinkageStatus.INACTIVE,
            partner_id=self.partner.id,
        )
        self.state_2 = QrisUserStateFactory(
            qris_partner_linkage=self.inactive_linkage,
            signature_image=self.signature_2,
        )

        self.out_of_balance_threshold = 500_000

        # blue finc lender
        self.blue_finc_lender = LenderCurrentFactory(
            lender_name='blue_finc_lender',
            lender_status=LenderStatus.ACTIVE,
        )
        self.blue_finc_balance = LenderBalanceCurrentFactory(
            lender=self.blue_finc_lender,
            available_balance=self.out_of_balance_threshold + 1,
        )

        # super bank
        self.super_bank = LenderCurrentFactory(
            lender_name='superbank',
            lender_status=LenderStatus.ACTIVE,
        )
        self.super_bank_balance = LenderBalanceCurrentFactory(
            lender=self.super_bank,
            available_balance=self.out_of_balance_threshold + 1,
        )

        # legend_capital_lender
        self.legend_capital_lender = LenderCurrentFactory(
            lender_name='legend_capital_lender',
            lender_status=LenderStatus.ACTIVE,
        )
        self.legend_capital_balance = LenderBalanceCurrentFactory(
            lender=self.legend_capital_lender,
            available_balance=self.out_of_balance_threshold + 1,
        )

        # fs
        self.multi_lender_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_MULTIPLE_LENDER,
            is_active=True,
            parameters={
                "out_of_balance_threshold": self.out_of_balance_threshold,
                "lender_names_ordered_by_priority": [
                    'blue_finc_lender',
                    'superbank',
                    'legend_capital_lender',
                ],
            },
        )

    def test_get_current_available_qris_lender_test_fs(self):
        """
        Test when FS is off or bad parameters
        """
        self.multi_lender_fs.parameters['lender_names_ordered_by_priority'] = [
            'blue_finc_lender',
        ]
        self.multi_lender_fs.save()
        self.blue_finc_balance.available_balance = 0
        self.blue_finc_balance.save()

        with self.assertRaises(NoQrisLenderAvailable):
            get_current_available_qris_lender(linkage=self.success_linkage)

        self.blue_finc_balance.available_balance = self.out_of_balance_threshold + 1
        self.blue_finc_balance.save()

        self.assertEqual(
            get_current_available_qris_lender(linkage=self.success_linkage),
            self.blue_finc_lender,
        )

    def test_get_current_available_qris_lender_case_linkage_active(self):
        """
            name      status      balance

        #1:
            bluefinc  inactive    enough
            superbank active      enough
            legend    active      enough
            => superbank

        #2:
            bluefinc  inactive    enough
            superbank active      not-enough
            legend    active      enough
            => legend

        #3:
            bluefinc  inactive    enough
            superbank active      not-enough
            legend    active      not-enough
            => bluefinc

        #4:
            bluefinc  inactive    enough
            superbank active      not-enough
            legend    inactive    enough
            => bluefinc

        #5:
            bluefinc  inactive    not-enough
            superbank active      not-enough
            legend    inactive    enough
            => no lender (linkage active), bluefinc (unactive linkage)

        #6:
            bluefinc  inactive    not-enough
            superbank active      not-enough
            legend    inactive    not-enough
            => no lender (linkage active), bluefinc (unactive)

        #7:
            bluefinc  inactive    enough
            superbank inactive    enough
            legend    inactive    enough
            => bluefinc

        """
        # 1
        self.blue_finc_lender.lender_status = LenderStatus.INACTIVE
        self.blue_finc_lender.save()

        self.assertEqual(
            get_current_available_qris_lender(self.success_linkage),
            self.super_bank,
        )
        self.assertEqual(
            get_current_available_qris_lender(self.inactive_linkage),
            self.super_bank,
        )

        # 2
        self.super_bank_balance.available_balance = self.out_of_balance_threshold - 1
        self.super_bank_balance.save()

        self.assertEqual(
            get_current_available_qris_lender(self.success_linkage),
            self.legend_capital_lender,
        )
        self.assertEqual(
            get_current_available_qris_lender(self.inactive_linkage),
            self.legend_capital_lender,
        )

        # 3
        self.legend_capital_balance.available_balance = self.out_of_balance_threshold - 1
        self.legend_capital_balance.save()

        self.assertEqual(
            get_current_available_qris_lender(self.success_linkage),
            self.blue_finc_lender,
        )
        self.assertEqual(
            get_current_available_qris_lender(self.inactive_linkage),
            self.blue_finc_lender,
        )

        # 4
        self.legend_capital_balance.available_balance = self.out_of_balance_threshold + 1
        self.legend_capital_lender.lender_status = LenderStatus.INACTIVE

        self.legend_capital_lender.save()
        self.legend_capital_balance.save()

        self.assertEqual(
            get_current_available_qris_lender(self.success_linkage),
            self.blue_finc_lender,
        )
        self.assertEqual(
            get_current_available_qris_lender(self.inactive_linkage),
            self.blue_finc_lender,
        )

        # 5
        self.blue_finc_balance.available_balance = self.out_of_balance_threshold - 1
        self.blue_finc_balance.save()

        with self.assertRaises(NoQrisLenderAvailable):
            get_current_available_qris_lender(self.success_linkage)

        self.assertEqual(
            get_current_available_qris_lender(self.inactive_linkage),
            self.blue_finc_lender,
        )
        self.assertEqual(
            get_current_available_qris_lender(linkage=None),
            self.blue_finc_lender,
        )

        # 6
        self.legend_capital_balance.available_balance = self.out_of_balance_threshold - 1
        self.legend_capital_lender.save()

        with self.assertRaises(NoQrisLenderAvailable):
            get_current_available_qris_lender(self.success_linkage)

        self.assertEqual(
            get_current_available_qris_lender(self.inactive_linkage),
            self.blue_finc_lender,
        )
        self.assertEqual(
            get_current_available_qris_lender(linkage=None),
            self.blue_finc_lender,
        )

        # 7
        self.blue_finc_lender.lender_status = LenderStatus.INACTIVE
        self.legend_capital_lender.lender_status = LenderStatus.INACTIVE
        self.super_bank.lender_status = LenderStatus.INACTIVE

        self.blue_finc_lender.save()
        self.legend_capital_lender.save()
        self.super_bank.save()

        self.legend_capital_balance.available_balance = self.out_of_balance_threshold + 1
        self.blue_finc_balance.available_balance = self.out_of_balance_threshold + 1
        self.super_bank_balance.available_balance = self.out_of_balance_threshold + 1

        self.blue_finc_balance.save()
        self.legend_capital_balance.save()
        self.super_bank_balance.save()

        self.assertEqual(
            get_current_available_qris_lender(self.success_linkage),
            self.blue_finc_lender,
        )
        self.assertEqual(
            get_current_available_qris_lender(self.inactive_linkage),
            self.blue_finc_lender,
        )

    def test_is_qris_linkage_signed_with_lender(self):

        QrisLinkageLenderAgreement.objects.create(
            qris_partner_linkage=self.success_linkage,
            signature_image_id=self.signature_1.id,
            lender_id=self.blue_finc_lender.id,
        )

        result = is_qris_linkage_signed_with_lender(
            linkage_id=self.success_linkage.id,
            lender_id=self.blue_finc_lender.id,
        )

        self.assertTrue(result)

    def test_is_qris_customer_signed_with_lender(self):

        QrisLinkageLenderAgreement.objects.create(
            qris_partner_linkage=self.success_linkage,
            signature_image_id=self.signature_1.id,
            lender_id=self.blue_finc_lender.id,
        )

        result = is_qris_customer_signed_with_lender(
            customer_id=self.customer_1.id,
            partner_id=self.partner.id,
            lender_id=self.blue_finc_lender.id,
        )

        self.assertTrue(result)

    def test_has_linkage_signed_with_current_lender(self):
        # hasn't signed
        self.multi_lender_fs.parameters['lender_names_ordered_by_priority'] = [
            'superbank',
        ]
        self.multi_lender_fs.save()

        is_signed, current_lender = has_linkage_signed_with_current_lender(
            linkage=self.success_linkage
        )

        self.assertFalse(is_signed)

        self.assertEqual(
            current_lender,
            self.super_bank,
        )

        # signed with blue finc
        self.multi_lender_fs.parameters['lender_names_ordered_by_priority'] = [
            'blue_finc_lender',
        ]
        self.multi_lender_fs.save()
        QrisLinkageLenderAgreement.objects.create(
            qris_partner_linkage=self.success_linkage,
            signature_image_id=self.signature_1.id,
            lender_id=self.blue_finc_lender.id,
        )

        is_signed, current_lender = has_linkage_signed_with_current_lender(
            linkage=self.success_linkage
        )

        self.assertTrue(is_signed)

        self.assertEqual(
            current_lender,
            self.blue_finc_lender,
        )

        # inactive
        is_signed, current_lender = has_linkage_signed_with_current_lender(
            linkage=self.inactive_linkage
        )

        self.assertFalse(is_signed)

        self.assertEqual(
            current_lender,
            self.blue_finc_lender,
        )

        # None linkage
        is_signed, current_lender = has_linkage_signed_with_current_lender(linkage=None)

        self.assertFalse(is_signed)

        self.assertEqual(
            current_lender,
            self.blue_finc_lender,
        )

    def test_get_qris_lender_from_lender_name(self):
        self.multi_lender_fs.parameters['lender_names_ordered_by_priority'] = [
            'blue_finc_lender',
        ]

        lender = get_qris_lender_from_lender_name('blue_finc_lender')
        self.assertEqual(
            lender,
            self.blue_finc_lender,
        )

        lender = get_qris_lender_from_lender_name('fakelender')
        self.assertEqual(lender, None)


class TestQrisProgressBarExpired(TestCase):
    def setUp(self):
        # amar partner
        self.amar_user_auth = AuthUserFactory()
        self.amar_customer = CustomerFactory(user=self.amar_user_auth)
        self.partner = PartnerFactory(name=PartnerNameConstant.AMAR, user=self.amar_user_auth)

        self.customer = CustomerFactory()

    def test_is_qris_progress_bar_expired(self):
        linkage = QrisPartnerLinkageFactory(
            customer_id=self.customer.id,
            status=QrisLinkageStatus.SUCCESS,
            partner_id=self.partner.id,
        )
        now = timezone.localtime(timezone.now())

        seconds_in_a_day = 60 * 60 * 24
        seconds_in_23_hours = 60 * 60 * 23
        seconds_in_an_hour = 60 * 60 * 1
        seconds_in_30_hours = 60 * 60 * 30

        one_day_ago = now - timezone.timedelta(seconds=seconds_in_a_day)

        linkage_history = QrisPartnerLinkageHistoryFactory(
            field='status',
            qris_partner_linkage=linkage,
            value_old='any',
            value_new=QrisLinkageStatus.SUCCESS,
        )
        linkage_history.cdate = one_day_ago
        linkage_history.save()

        # is older than 2 days => False
        is_older = is_success_linkage_older_than(
            seconds_since_success=seconds_in_a_day * 2,
            linkage_id=linkage.id,
        )

        self.assertEqual(is_older, False)

        # is older than 30 hours => False
        is_older = is_success_linkage_older_than(
            seconds_since_success=seconds_in_30_hours,
            linkage_id=linkage.id,
        )

        self.assertEqual(is_older, False)

        # is older than 1 hour => True
        is_older = is_success_linkage_older_than(
            seconds_since_success=seconds_in_an_hour,
            linkage_id=linkage.id,
        )

        self.assertEqual(is_older, True)

        # is older than 23 hours => True
        is_older = is_success_linkage_older_than(
            seconds_since_success=seconds_in_23_hours,
            linkage_id=linkage.id,
        )

        self.assertEqual(is_older, True)


class TestUpdateLinkageStatus(TestCase):
    def setUp(self):
        # amar partner
        self.amar_user_auth = AuthUserFactory()
        self.amar_customer = CustomerFactory(user=self.amar_user_auth)
        self.partner = PartnerFactory(name=PartnerNameConstant.AMAR, user=self.amar_user_auth)

        self.customer = CustomerFactory()

        self.linkage = QrisPartnerLinkageFactory(
            customer_id=self.customer.id,
            status=QrisLinkageStatus.REQUESTED,
            partner_id=self.partner.id,
        )

    def test_update_linkage_status_regis_form_to_success(self):
        self.linkage.status = QrisLinkageStatus.REGIS_FORM
        self.linkage.save()

        update_result = update_linkage_status(
            linkage=self.linkage,
            to_status=QrisLinkageStatus.SUCCESS,
        )

        self.assertEqual(update_result, True)

        self.linkage.refresh_from_db()

        self.assertEqual(self.linkage.status, QrisLinkageStatus.SUCCESS)

        status_history = self.linkage.histories.filter(field='status').last()
        self.assertIsNotNone(status_history)

    def test_update_linkage_status_regis_form_to_failed(self):
        self.linkage.status = QrisLinkageStatus.REGIS_FORM
        self.linkage.save()

        update_result = update_linkage_status(
            linkage=self.linkage,
            to_status=QrisLinkageStatus.FAILED,
        )

        self.assertEqual(update_result, True)

        self.linkage.refresh_from_db()

        self.assertEqual(self.linkage.status, QrisLinkageStatus.FAILED)

        status_history = self.linkage.histories.filter(field='status').last()
        self.assertIsNotNone(status_history)

    def test_update_linkage_status_requested_to_regis_form(self):
        self.linkage.status = QrisLinkageStatus.REQUESTED
        self.linkage.save()

        update_result = update_linkage_status(
            linkage=self.linkage,
            to_status=QrisLinkageStatus.REGIS_FORM,
        )

        self.assertEqual(update_result, True)

        self.linkage.refresh_from_db()

        self.assertEqual(self.linkage.status, QrisLinkageStatus.REGIS_FORM)

        status_history = self.linkage.histories.filter(field='status').last()
        self.assertIsNotNone(status_history)

    def test_update_linkage_status_regis_form_to_requested(self):
        self.linkage.status = QrisLinkageStatus.REGIS_FORM
        self.linkage.save()

        update_result = update_linkage_status(
            linkage=self.linkage,
            to_status=QrisLinkageStatus.REQUESTED,
        )

        self.assertEqual(update_result, False)

        self.linkage.refresh_from_db()

        self.assertEqual(self.linkage.status, QrisLinkageStatus.REGIS_FORM)

        status_history = self.linkage.histories.filter(field='status').last()
        self.assertIsNone(status_history)
