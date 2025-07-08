from builtins import str

import pytest
from django.core.exceptions import ObjectDoesNotExist
from django.test import TestCase, override_settings
from mock import Mock, patch

from juloserver.apiv1.services import *
from juloserver.julo.product_lines import ProductLineCodes, ProductLineNotFound
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationHistoryFactory,
    AwsFaceRecogLogFactory,
    BankApplicationFactory,
    CreditScoreFactory,
    CustomerFactory,
    KycRequestFactory,
    LoanFactory,
    LoanSelloffFactory,
    MobileFeatureSettingFactory,
    OfferFactory,
    PartnerFactory,
    PartnerLoanFactory,
    PaymentEventFactory,
    PaymentFactory,
    ProductLineFactory,
    StatusLookupFactory,
)
from juloserver.line_of_credit.tests.factories_loc import LineOfCreditFactory


class TestGetVoiceRecordScript(TestCase):
    def setUp(self):
        self.loan = LoanFactory()

    def test_get_voice_record_selector(self):
        # Test get_voice_record_script_loc was called
        self.loan.application.product_line_id = ProductLineCodes.LOC
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        with patch(
            'juloserver.apiv1.services.get_voice_record_script_loc', return_value=''
        ) as _serivce:
            get_voice_record_script(self.loan.application)
            _serivce.assert_called_once_with(self.loan.application)

        # Test get_voice_record_script_default was called
        self.loan.application.product_line_id = ProductLineCodes.AXIATA1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        with patch(
            'juloserver.apiv1.services.get_voice_record_script_default', return_value=''
        ) as _serivce:
            get_voice_record_script(self.loan.application)
            _serivce.assert_called_once_with(self.loan.application)

    def test_get_voice_record_script_default(self):
        loan_duration = ""
        template_data = {
            "TODAY_DATE": format_date(timezone.now().date(), 'd MMMM yyyy', locale='id_ID'),
            "FULL_NAME": self.loan.application.fullname,
            "DOB": format_date(self.loan.application.dob, 'd MMMM yyyy', locale='id_ID'),
            "LOAN_AMOUNT": display_rupiah(self.loan.loan_amount),
            "LOAN_DURATION": loan_duration,
        }
        script_format = (
            "Hari ini, tanggal %(TODAY_DATE)s, saya %(FULL_NAME)s lahir tanggal"
            " %(DOB)s mengajukan pinjaman melalui PT. JULO TEKNOLOGI FINANSIAL"
            " dan telah disetujui sebesar yang tertera pada Surat Perjanjian Hutang Piutang "
            "%(LOAN_DURATION)s. Saya berjanji untuk melunasi pinjaman sesuai dengan Surat"
            " Perjanjian Hutang Piutang yang telah saya tanda tangani."
        )
        # Test product line code is mtl or bri
        self.loan.application.product_line_id = ProductLineCodes.MTL1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        script = get_voice_record_script_default(self.loan.application)
        template_data["LOAN_DURATION"] = "selama %s bulan" % self.loan.loan_duration
        check_script = script_format % template_data
        assert check_script == script

        # Test product line code is bri
        self.loan.application.product_line_id = ProductLineCodes.BRI1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        script = get_voice_record_script_default(self.loan.application)
        template_data["LOAN_DURATION"] = "selama %s bulan" % self.loan.loan_duration
        check_script = script_format % template_data
        assert check_script == script

        # Test product line code is stl
        self.loan.application.product_line_id = ProductLineCodes.STL1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        script = get_voice_record_script_default(self.loan.application)
        formatted_due_date = format_date(
            self.loan.application.loan.payment_set.first().due_date, 'd MMMM yyyy', locale='id_ID'
        )
        template_data["LOAN_DURATION"] = "yang jatuh tempo pada tanggal %s" % formatted_due_date
        check_script = script_format % template_data
        assert check_script == script

        # Test product line code is grabfood
        self.loan.application.product_line_id = ProductLineCodes.GRABF1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        script = get_voice_record_script_default(self.loan.application)
        template_data["LOAN_DURATION"] = "selama %s minggu" % self.loan.loan_duration
        check_script = script_format % template_data
        assert check_script == script

        # Test product line code is grab
        self.loan.application.product_line_id = ProductLineCodes.GRAB1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        script = get_voice_record_script_default(self.loan.application)
        template_data["LOAN_DURATION"] = "dalam kurun waktu 5 minggu"
        check_script = (
            "Hari ini, tanggal %(TODAY_DATE)s, saya %(FULL_NAME)s lahir tanggal"
            " %(DOB)s mengajukan pinjaman melalui PT JULO TEKNOLOGI FINANSIAL."
            " Pinjaman sebesar %(LOAN_AMOUNT)s telah disetujui dan saya berjanji"
            " untuk melunasinya %(LOAN_DURATION)s sesuai dengan Perjanjian Hutang"
            " Piutang yang telah saya tanda tangani."
        ) % template_data
        assert check_script == script

        # Test product line not found
        self.loan.application.product_line_id = ProductLineCodes.LAKU1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        self.assertRaises(
            ProductLineNotFound, get_voice_record_script_default, self.loan.application
        )

    def test_get_voice_record_script_loc(self):
        self.loan.application.line_of_credit = LineOfCreditFactory(limit=10000)
        template_data = {
            "TODAY_DATE": format_date(timezone.now().date(), 'd MMMM yyyy', locale='id_ID'),
            "FULL_NAME": self.loan.application.fullname,
            "DOB": format_date(self.loan.application.dob, 'd MMMM yyyy', locale='id_ID'),
            "CREDIT_LIMIT": display_rupiah(self.loan.application.line_of_credit.limit),
        }
        script_format = (
            "Hari ini, tanggal %(TODAY_DATE)s, saya %(FULL_NAME)s lahir tanggal"
            " %(DOB)s mengaktifkan limit kredit JULO dan telah disetujui melalui"
            " PT. JULO TEKNOLOGI FINANSIAL sebesar %(CREDIT_LIMIT)s."
            " Saya berjanji untuk melunasi tagihan setiap bulan nya sesuai dengan Surat"
            " Perjanjian Hutang Piutang yang telah saya tanda tangani."
        )
        # Test product line code is mtl or bri
        self.loan.application.product_line_id = ProductLineCodes.LOC
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        script = get_voice_record_script_loc(self.loan.application)
        check_script = script_format % template_data
        assert check_script == script


class TestDetermineProductLine(TestCase):
    def setUp(self):
        self.product_line = ProductLineFactory()
        self.customer = CustomerFactory()

    def test_determine_product_line_no_any_paid_off_loan(self):
        # Test product line code is CTL
        product_line_code = ProductLineCodes.CTL1
        self.product_line.product_line_code = product_line_code
        data = {'product_line_code': product_line_code, 'loan_duration_request': 1}
        product_line = determine_product_line(self.customer, data)
        self.assertEqual(product_line, self.product_line)

        # Test product line STL
        product_line_code = ProductLineCodes.STL1
        self.product_line.product_line_code = product_line_code
        data['product_line_code'] = product_line_code
        product_line = determine_product_line(self.customer, data)
        self.assertEqual(product_line, self.product_line)

        # Test product line MTL
        product_line_code = ProductLineCodes.MTL1
        self.product_line.product_line_code = product_line_code
        data['product_line_code'] = product_line_code
        data['loan_duration_request'] = 6
        product_line = determine_product_line(self.customer, data)
        self.assertEqual(product_line, self.product_line)

    def test_determine_product_line_has_any_paid_off_loan(self):
        loan = LoanFactory()
        loan.loan_status_id = 250
        loan.save()
        # Test product line code is CTL
        product_line_code = ProductLineCodes.CTL2
        self.product_line.product_line_code = product_line_code
        data = {'product_line_code': product_line_code, 'loan_duration_request': 1}
        product_line = determine_product_line(loan.customer, data)
        self.assertEqual(product_line, self.product_line)

        # Test product line STL
        product_line_code = ProductLineCodes.STL2
        self.product_line.product_line_code = product_line_code
        data['product_line_code'] = product_line_code
        product_line = determine_product_line(loan.customer, data)
        self.assertEqual(product_line, self.product_line)

        # Test product line MTL
        product_line_code = ProductLineCodes.MTL2
        self.product_line.product_line_code = product_line_code
        data['product_line_code'] = product_line_code
        data['loan_duration_request'] = 6
        product_line = determine_product_line(loan.customer, data)
        self.assertEqual(product_line, self.product_line)

    def test_product_line_of_code_not_in_data(self):
        data = {'loan_duration_request': 1}
        product_line_code = ProductLineCodes.STL1
        self.product_line.product_line_code = product_line_code
        product_line = determine_product_line(self.customer, data)
        self.assertEqual(product_line, self.product_line)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestRenderAccountSummaryCards(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory()

    def test_user_has_not_submit_any_application(self):
        # without application id
        account_summary_cards = render_account_summary_cards(self.customer)
        self.assertEqual(account_summary_cards, [render_default_card()])

        # with an application_id
        account_summary_cards = render_account_summary_cards(self.customer, 9999999)
        self.assertEqual(account_summary_cards, [render_default_card()])

    def test_user_already_submitted_short_form_and_get_score_C(self):
        self.application.customer = self.customer
        self.application.application_status_id = 106
        self.application.save()

        with patch('juloserver.apiv1.services.timezone') as tz_mock:
            tz_mock.localtime.return_value = datetime(2018, 11, 15)
            self.application.application_status_id = 106
            self.application.save()
            credit_score = CreditScoreFactory()
            credit_score.application_id = self.application.id
            credit_score.save()
            with patch(
                'juloserver.apiv1.services.render_application_status_card', return_value=None
            ):
                account_summary_cards = render_account_summary_cards(
                    self.customer, self.application
                )
                self.assertEqual(account_summary_cards, [render_bfi_oct_promo_card()])

    def test_user_has_completed_application_and_waiting_for_partner_approval(self):
        self.application.customer = self.customer
        self.application.application_status_id = 129
        self.application.save()
        card = {}

        with patch('juloserver.apiv1.services.render_application_status_card', return_value=card):
            account_summary_cards = render_account_summary_cards(self.customer, self.application)
            self.assertEqual(account_summary_cards, [card])

    def test_user_has_approved_partner_loan(self):
        self.application.customer = self.customer
        self.application.application_status_id = 189
        self.application.save()
        card = {}

        with patch('juloserver.apiv1.services.render_application_status_card', return_value=card):
            account_summary_cards = render_account_summary_cards(self.customer, self.application)
            self.assertEqual(account_summary_cards, [card])

    def test_user_has_submitted_application_but_still_waiting_for_offers(self):
        self.application.customer = self.customer
        self.application.application_status_id = 162
        self.application.save()
        with patch('juloserver.apiv1.services.render_application_status_card', return_value={}):
            account_summary_cards = render_account_summary_cards(self.customer, self.application)
            self.assertEqual(account_summary_cards, [{}])

    def test_user_has_accpepted_an_offer(self):
        loan = LoanFactory()
        loan.application.application_status_id = 163
        loan.application.customer = loan.customer
        loan.application.save()

        # loan status code is inactive
        loan.loan_status_id = 210
        loan.save()
        with patch('juloserver.apiv1.services.render_application_status_card', return_value={}):
            account_summary_cards = render_account_summary_cards(loan.customer, loan.application)
            self.assertEqual(account_summary_cards, [{}])

        # loan status is paid off
        loan.loan_status_id = 250
        loan.save()
        with patch('juloserver.apiv1.services.render_loan_status_card', return_value={}):
            account_summary_cards = render_account_summary_cards(loan.customer, loan.application)
            self.assertEqual(account_summary_cards, [{}])

        # User already has started the loan and has payments
        payment = PaymentFactory()
        payment.loan_id = loan.id
        payment.save()
        loan.loan_status_id = 233
        loan.save()
        with patch('juloserver.apiv1.services.render_payment_status_cards', return_value=[{}]):
            account_summary_cards = render_account_summary_cards(loan.customer, loan.application)
            self.assertEqual(account_summary_cards, [{}])


class TestRenderLoanStatusCard(TestCase):
    def setUp(self):
        self.loan = LoanFactory()

    def test_loan_can_reapply(self):
        url_canreapply = 'http://www.julofinance.com/android/goto/reapply'
        can_reapply_desc = (
            'Untuk mengajukan kembali pinjaman yang baru, silahkan klik tombol Ajukan Pinjaman.'
        )
        btn_text = 'Ajukan Pinjaman Baru'
        self.loan.customer.can_reapply = True

        # product line of code is MTL
        self.loan.application.product_line_id = ProductLineCodes.MTL1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        msg = render_to_string(
            'MTL_' + str(LoanStatusCodes.PAID_OFF) + '.txt',
            {
                'total_cb_amt': display_rupiah(self.loan.cashback_earned_total),
                'can_reapply_desc': can_reapply_desc,
            },
        )
        check_card = construct_card(msg, 'INFORMASI PINJAMAN', None, url_canreapply, None, btn_text)

        card = render_loan_status_card(self.loan)
        self.assertEqual(card, check_card)

        # product line of code is STL
        self.loan.application.product_line_id = ProductLineCodes.STL1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        msg = render_to_string(
            'STL_' + str(LoanStatusCodes.PAID_OFF) + '.txt', {'can_reapply_desc': can_reapply_desc}
        )
        check_card = construct_card(msg, 'INFORMASI PINJAMAN', None, url_canreapply, None, btn_text)

        card = render_loan_status_card(self.loan)
        self.assertEqual(card, check_card)

        # product line of code is BRI
        self.loan.application.product_line_id = ProductLineCodes.BRI1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        msg = render_to_string(
            'STL_' + str(LoanStatusCodes.PAID_OFF) + '.txt',
            {
                'total_cb_amt': display_rupiah(self.loan.cashback_earned_total),
                'can_reapply_desc': can_reapply_desc,
            },
        )
        check_card = construct_card(msg, 'INFORMASI PINJAMAN', None, url_canreapply, None, btn_text)

        card = render_loan_status_card(self.loan)
        self.assertEqual(card, check_card)

        # product line of code is grab
        self.loan.application.product_line_id = ProductLineCodes.GRAB1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        msg = render_to_string(
            'GRAB_' + str(LoanStatusCodes.PAID_OFF) + '.txt',
        )
        check_card = construct_card(msg, 'INFORMASI PINJAMAN', None, url_canreapply, None, btn_text)

        card = render_loan_status_card(self.loan)
        self.assertEqual(card, check_card)

        # product line of code is grab food
        self.loan.application.product_line_id = ProductLineCodes.GRABF1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        msg = render_to_string('GRAB_' + str(LoanStatusCodes.PAID_OFF) + '.txt')
        check_card = construct_card(msg, 'INFORMASI PINJAMAN', None, url_canreapply, None, btn_text)

        card = render_loan_status_card(self.loan)
        self.assertEqual(card, check_card)

        # product line of is invalid
        self.loan.application.product_line_id = ProductLineCodes.AXIATA1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        card = render_loan_status_card(self.loan)
        self.assertIsNone(card)

    def test_loan_not_reapply(self):
        url_canreapply = None
        can_reapply_desc = 'Untuk mengajukan pinjaman baru, silahkan hubungi CS@julofinance.com.'
        btn_text = None
        self.loan.customer.can_reapply = False

        # product line of code is MTL
        self.loan.application.product_line_id = ProductLineCodes.MTL1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        msg = render_to_string(
            'MTL_' + str(LoanStatusCodes.PAID_OFF) + '.txt',
            {
                'total_cb_amt': display_rupiah(self.loan.cashback_earned_total),
                'can_reapply_desc': can_reapply_desc,
            },
        )
        check_card = construct_card(msg, 'INFORMASI PINJAMAN', None, url_canreapply, None, btn_text)

        card = render_loan_status_card(self.loan)
        self.assertEqual(card, check_card)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestRenderPaymentStatusCard(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.payment = PaymentFactory()

    def test_product_line_code_not_in_payment_home_screen(self):
        self.payment.loan = self.loan
        self.payment.save()
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])

        self.assertEqual(payment_status_cards, [])

    @patch('juloserver.apiv1.services.construct_card')
    def test_product_line_code_in_payment_home_screen(self, mock_construct_card):
        # product line code is MTL
        self.payment.loan = self.loan
        self.payment.loan.application.product_line_id = ProductLineCodes.MTL1
        self.payment.loan.application.save()
        self.payment.loan.application.refresh_from_db()
        # 2 < due days < 4
        self.payment.due_date = (datetime.now() + timedelta(days=3)).date()

        # payment not due and productline
        self.payment.payment_status_id = PaymentStatusCodes.PAYMENT_NOT_DUE
        self.payment.save()
        self.payment.refresh_from_db()

        check_card_payment_mtl = {'mtl': 'mtl'}
        check_card_payment_not_due = {'payment_not_due': 'payment_not_due'}
        mock_construct_card.side_effect = [check_card_payment_mtl, check_card_payment_not_due]
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])

        self.assertEqual(payment_status_cards, [check_card_payment_mtl, check_card_payment_not_due])

        # due days > 4
        self.payment.due_date = (datetime.now() + timedelta(days=5)).date()
        self.payment.payment_status_id = PaymentStatusCodes.DOWN_PAYMENT_DUE
        self.payment.save()
        self.payment.refresh_from_db()
        mock_construct_card.side_effect = [check_card_payment_mtl]
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])

        self.assertEqual(payment_status_cards, [check_card_payment_mtl])

    @patch('juloserver.apiv1.services.construct_card')
    def test_payment_not_due(self, mock_construct_card):
        # MTL case has been checked above
        self.payment.loan = self.loan
        self.payment.payment_status_id = 310
        self.payment.due_date = datetime.now().date()
        self.payment.save()
        check_card = {'text': 'text'}

        # product line is STL
        self.payment.loan.application.product_line_id = ProductLineCodes.STL1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is BRI
        self.payment.loan.application.product_line_id = ProductLineCodes.BRI1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is GRAB
        self.payment.loan.application.product_line_id = ProductLineCodes.GRAB1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is GRABFOOD
        self.payment.loan.application.product_line_id = ProductLineCodes.GRABF1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

    @patch('juloserver.apiv1.services.construct_card')
    def test_payment_due_in_3_days(self, mock_construct_card):
        self.payment.loan = self.loan
        self.payment.payment_status_id = 311
        self.payment.due_date = datetime.now().date()
        self.payment.save()
        check_card = {'text': 'text'}

        # product line is MTL
        self.payment.loan.application.product_line_id = ProductLineCodes.MTL1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is STL
        self.payment.loan.application.product_line_id = ProductLineCodes.STL1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is BRI
        self.payment.loan.application.product_line_id = ProductLineCodes.BRI1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is GRAB
        self.payment.loan.application.product_line_id = ProductLineCodes.GRAB1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is GRABFOOD
        self.payment.loan.application.product_line_id = ProductLineCodes.GRABF1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

    @patch('juloserver.apiv1.services.construct_card')
    def test_payment_due_to_day(self, mock_construct_card):
        self.payment.loan = self.loan
        self.payment.payment_status_id = 312
        self.payment.due_date = datetime.now().date()
        self.payment.save()
        check_card = {'text': 'text'}

        # product line is MTL
        self.payment.loan.application.product_line_id = ProductLineCodes.MTL1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is STL
        self.payment.loan.application.product_line_id = ProductLineCodes.STL1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is BRI
        self.payment.loan.application.product_line_id = ProductLineCodes.BRI1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is GRAB
        self.payment.loan.application.product_line_id = ProductLineCodes.GRAB1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is GRABFOOD
        self.payment.loan.application.product_line_id = ProductLineCodes.GRABF1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

    @patch('juloserver.apiv1.services.construct_card')
    def test_payment_1dpd(self, mock_construct_card):
        self.payment.loan = self.loan
        self.payment.payment_status_id = 320
        self.payment.due_date = (datetime.now() - timedelta(days=1)).date()
        self.payment.save()
        check_card = {'text': 'text'}

        # product line is MTL
        self.payment.loan.application.product_line_id = ProductLineCodes.MTL1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is STL
        self.payment.loan.application.product_line_id = ProductLineCodes.STL1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is BRI
        self.payment.loan.application.product_line_id = ProductLineCodes.BRI1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is GRAB
        self.payment.loan.application.product_line_id = ProductLineCodes.GRAB1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is GRABFOOD
        self.payment.loan.application.product_line_id = ProductLineCodes.GRABF1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

    @patch('juloserver.apiv1.services.construct_card')
    def test_payment_more_1dpd(self, mock_construct_card):
        self.payment.loan = self.loan
        self.payment.payment_status_id = 321
        self.payment.due_date = (datetime.now() - timedelta(days=15)).date()
        self.payment.save()
        check_card = {'text': 'text'}

        # product line is MTL
        self.payment.loan.application.product_line_id = ProductLineCodes.MTL1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is STL
        self.payment.loan.application.product_line_id = ProductLineCodes.STL1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        # due date + 10 days <= today <= due date+ 29 days
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])

        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])
        # the other case for STL
        self.payment.due_date = (datetime.now() - timedelta(days=1)).date()
        self.payment.save()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is BRI
        self.payment.loan.application.product_line_id = ProductLineCodes.BRI1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is GRAB
        self.payment.loan.application.product_line_id = ProductLineCodes.GRAB1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()

        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is GRAB and due data + 14 days <= today
        self.payment.due_date = (datetime.now() - timedelta(days=15)).date()
        self.payment.save()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is GRABFOOD
        self.payment.loan.application.product_line_id = ProductLineCodes.GRABF1
        self.payment.loan.application.save()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

    @patch('juloserver.apiv1.services.construct_card')
    def test_payment_paid_on_time(self, mock_construct_card):
        self.payment.loan = self.loan
        self.payment.payment_status_id = 330
        self.payment.due_date = (datetime.now() - timedelta(days=15)).date()
        self.payment.save()
        self.payment.refresh_from_db()
        check_card = {'text': 'text'}

        # product line is GRAB or GRABFOOD
        self.payment.paid_date = datetime.now().date()
        self.payment.save()
        self.loan.application.product_line_id = ProductLineCodes.GRAB1
        self.loan.application.save()
        self.loan.refresh_from_db()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line isn't GRAB or GRABFOOD and paid date + 7 days >= today
        self.payment.paid_date = (datetime.now() - timedelta(days=5)).date()
        self.payment.save()
        # product line is MTL
        self.loan.application.product_line_id = ProductLineCodes.MTL1
        self.loan.application.save()
        self.loan.refresh_from_db()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])
        # product line is STL
        self.loan.application.product_line_id = ProductLineCodes.MTL1
        self.loan.application.save()
        self.loan.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])
        # product line is BRI
        self.loan.application.product_line_id = ProductLineCodes.MTL1
        self.loan.application.save()
        self.loan.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

    @patch('juloserver.apiv1.services.construct_card')
    def test_payment_paid_within_grace_period_or_paid_late(self, mock_construct_card):
        self.payment.loan = self.loan
        self.payment.payment_status_id = 331
        self.payment.due_date = (datetime.now() - timedelta(days=15)).date()
        self.payment.save()
        self.payment.refresh_from_db()

        check_card = {'text': 'text'}

        # product line is GRAB or GRABFOOD
        self.payment.paid_date = datetime.now().date()
        self.payment.save()
        self.loan.application.product_line_id = ProductLineCodes.GRAB1
        self.loan.application.save()
        self.loan.refresh_from_db()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line isn't GRAB or GRABFOOD and paid date + 7 days >= today
        self.payment.paid_date = (datetime.now() - timedelta(days=5)).date()
        # product line is MTL
        self.payment.save()
        self.loan.application.product_line_id = ProductLineCodes.MTL1
        self.loan.application.save()
        self.loan.refresh_from_db()
        self.payment.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])

        # product line is STL
        self.loan.application.product_line_id = ProductLineCodes.STL1
        self.loan.application.save()
        self.loan.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])
        # product line is BRI
        self.loan.application.product_line_id = ProductLineCodes.BRI1
        self.loan.application.save()
        self.loan.refresh_from_db()
        mock_construct_card.return_value = check_card
        payment_status_cards = render_payment_status_cards(self.loan, [self.payment])
        self.assertEqual(payment_status_cards, [check_card])


class TestRenderApplicationStatusCard(TestCase):
    def setUp(self):
        self.loan = PartnerLoanFactory()
        self.application = ApplicationFactory()
        self.loan.application_id = self.application.id
        self.loan.save()

    @patch('juloserver.apiv1.services.process_streamlined_comm')
    def test_app_status_is_resubmit_and_app_ver_greater_or_equal_than_1_1_1(
        self, process_streamlined_comm
    ):
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
            )
        )
        app_history = ApplicationHistoryFactory()
        app_history.application_id = self.application.id
        face_recog_log = AwsFaceRecogLogFactory()
        app_history.save()

        # app version >= 1.1.1
        # pass face recog
        self.application.app_version = '1.1.1'
        face_recog_log.application_id = self.application.id
        face_recog_log.save()
        self.loan.save()
        button_text = "Unggah Dokumen"
        expired_time = get_expired_time(app_history)
        msg = "test msg"
        check_card = construct_card(
            msg,
            "INFORMASI PENGAJUAN",
            None,
            'http://www.julofinance.com/android/goto/appl_docs',
            None,
            button_text,
            None,
            expired_time,
        )
        process_streamlined_comm.return_value = msg
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # not pass face recog
        button_text = "Unggah Foto"
        # FaceRecordsStatus and UnindexedFaces are False
        face_recog_log.is_quality_check_passed = False
        face_recog_log.raw_response = {'FaceRecordsStatus': False, 'UnindexedFaces': False}
        face_recog_log.save()
        check_card = construct_card(
            msg,
            "INFORMASI PENGAJUAN",
            None,
            'http://www.julofinance.com/android/goto/appl_docs',
            None,
            button_text,
            None,
            expired_time,
        )
        process_streamlined_comm.return_value = msg
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # UnindexedFaces is True
        face_recog_log.raw_response['UnindexedFaces'] = True
        face_recog_log.save()
        check_card = construct_card(
            msg,
            "INFORMASI PENGAJUAN",
            None,
            'http://www.julofinance.com/android/goto/appl_docs',
            None,
            button_text,
            None,
            expired_time,
        )
        process_streamlined_comm.return_value = msg
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # FaceRecordsStatus is True and UnindexedFaces is False
        face_recog_log.raw_response = {'FaceRecordsStatus': True, 'UnindexedFaces': False}
        face_recog_log.save()
        check_card = construct_card(
            msg,
            "INFORMASI PENGAJUAN",
            None,
            'http://www.julofinance.com/android/goto/appl_docs',
            None,
            button_text,
            None,
            expired_time,
        )
        process_streamlined_comm.return_value = msg
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)

        # msg is None from process streamlined comm
        process_streamlined_comm.return_value = None
        check_card = construct_card(
            render_to_string('131_bad_image_quality.txt', None),
            "INFORMASI PENGAJUAN",
            None,
            'http://www.julofinance.com/android/goto/appl_docs',
            None,
            button_text,
            None,
            expired_time,
        )
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)

    @patch('juloserver.apiv1.services.process_streamlined_comm')
    def test_app_status_is_resubmit_and_app_ver_less_than_1_1_1(self, process_streamlined_comm):
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
            )
        )
        app_history = ApplicationHistoryFactory()
        app_history.application_id = self.application.id
        face_recog_log = AwsFaceRecogLogFactory()
        app_history.save()
        ctx = {'email': self.application.email}

        # app version < 1.1.1
        self.application.app_version = '1.1.0'
        # pass face recog
        face_recog_log.application_id = self.application.id
        face_recog_log.save()
        self.loan.save()
        expired_time = get_expired_time(app_history)
        # msg is not None
        msg = "test msg"
        check_card = construct_card(
            msg, "INFORMASI PENGAJUAN", None, None, None, None, None, expired_time
        )
        process_streamlined_comm.return_value = msg
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # msg is None
        msg = None
        check_card = construct_card(
            render_to_string('131_old.txt', ctx),
            "INFORMASI PENGAJUAN",
            None,
            None,
            None,
            None,
            None,
            expired_time,
        )
        process_streamlined_comm.return_value = msg
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)

        # not pass face recog
        msg = 'test_msg'
        # FaceRecordsStatus and UnindexedFaces are False
        face_recog_log.is_quality_check_passed = False
        face_recog_log.raw_response = {'FaceRecordsStatus': False, 'UnindexedFaces': False}
        face_recog_log.save()
        check_card = construct_card(
            msg, "INFORMASI PENGAJUAN", None, None, None, None, None, expired_time
        )
        process_streamlined_comm.return_value = msg
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # UnindexedFaces is True
        face_recog_log.raw_response['UnindexedFaces'] = True
        face_recog_log.save()
        check_card = construct_card(
            msg, "INFORMASI PENGAJUAN", None, None, None, None, None, expired_time
        )
        process_streamlined_comm.return_value = msg
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # FaceRecordsStatus is True and UnindexedFaces is False
        face_recog_log.raw_response = {'FaceRecordsStatus': True, 'UnindexedFaces': False}
        face_recog_log.save()
        check_card = construct_card(
            msg, "INFORMASI PENGAJUAN", None, None, None, None, None, expired_time
        )
        process_streamlined_comm.return_value = msg
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)

    @patch('juloserver.apiv2.services.get_credit_score3')
    def test_app_status_is_form_partial_and_not_credit_sorce(self, get_credit_score3):
        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_PARTIAL)
        )
        self.loan.save()
        get_credit_score3.return_value = None
        card = render_application_status_card(self.application, self.loan)
        check_card = construct_card(
            render_to_string('105_no_score.txt', None),
            "INFORMASI PENGAJUAN",
            None,
            None,
            None,
            None,
            None,
            None,
        )
        self.assertEqual(card, check_card)

    @patch('juloserver.apiv2.services.get_credit_score3')
    @patch('juloserver.apiv2.services.is_c_score_in_delay_period')
    @patch('juloserver.apiv1.services.process_streamlined_comm')
    def test_app_status_is_form_partial_and_credit_score(
        self, process_streamlined_comm, is_c_score_in_delay_period, get_credit_score3
    ):
        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_PARTIAL)
        )
        credit_score = CreditScoreFactory()
        credit_score.application_id = self.application.id
        credit_score.score_tag = 'c_failed_binary'
        credit_score.save()

        # -----------------------------------------------------------------------------------
        # with c mocked customer
        # without rating score feature setting
        # app version >=3.17.0
        # and customer not reviewed submitted
        self.application.app_version = '3.17.0'
        self.loan.save()
        check_card = construct_card(
            render_to_string('105_c_binary_failed.txt', None),
            "KRITIK DAN SARAN",
            None,
            'http://www.julofinance.com/android/goto/rating_in_apps',
            None,
            "Kritik dan Saran",
            None,
            None,
        )
        get_credit_score3.return_value = credit_score
        is_c_score_in_delay_period.return_value = False
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # and customer is review submitted
        self.application.customer.is_review_submitted = True
        get_credit_score3.return_value = credit_score
        is_c_score_in_delay_period.return_value = False
        card = render_application_status_card(self.application, self.loan)
        self.assertIsNone(card)

        # with rating score feature setting
        rating_score_feature_setting = MobileFeatureSettingFactory()
        rating_score_feature_setting.feature_name = 'mock_rating_page'
        rating_score_feature_setting.parameters['score_tags'] = ['c_failed_binary', None]
        rating_score_feature_setting.save()
        self.application.customer.is_review_submitted = False
        self.loan.save()
        get_credit_score3.return_value = credit_score
        is_c_score_in_delay_period.return_value = False
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)

        # -----------------------------------------------------------------------------------
        # with c mocked customer but c score is in delay period
        get_credit_score3.return_value = credit_score
        is_c_score_in_delay_period.return_value = True
        process_streamlined_comm.return_value = 'msg_test'
        card = render_application_status_card(self.application, self.loan)
        check_card = construct_card(
            'msg_test',
            'INFORMASI PENGAJUAN',
            None,
            'http://www.julofinance.com/android/goto/product',
            None,
            'Pilih Pinjaman',
        )
        self.assertEqual(card, check_card)

    @patch('juloserver.apiv1.services.process_streamlined_comm')
    def test_other_case(self, process_streamlined_comm):
        msg = 'msg_test'
        ## App status is not FORM_CREATED
        header = 'INFORMASI PENGAJUAN'
        # -----------------------------------------------
        # App status is FORM_SUBMITTED or APPLICATION_RESUBMISSION_REQUESTED
        self.application.partner = None
        self.application.save()

        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.FORM_SUBMITTED
            )
        )
        # msg is not None
        button_text = 'Unggah Dokumen'
        button_url = 'http://www.julofinance.com/android/goto/appl_docs'
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # msg is None
        process_streamlined_comm.return_value = None
        check_card = construct_card(
            render_to_string('110.txt', None), header, None, button_url, None, button_text
        )
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # template not exist
        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=99999999)  # invalid status code
        )
        card = render_application_status_card(self.application, self.loan)
        self.assertIsNone(card)
        # ----------------------------------------------------
        # App status is OFFER_MADE_TO_CUSTOMER
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER
            )
        )
        button_text = 'Penawaran Pinjaman'
        button_url = 'http://www.julofinance.com/android/goto/got_offers'
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # ----------------------------------------------------
        # App status in FORM_SUBMISSION_ABANDONED, FORM_PARTIAL_EXPIRED,
        # RESUBMISSION_REQUEST_ABANDONED,
        # APPLICATION_CANCELED_BY_CUSTOMER, VERIFICATION_CALLS_EXPIRED, OFFER_DECLINED_BY_CUSTOMER,
        # OFFER_EXPIRED, LEGAL_AGREEMENT_EXPIRED or DOWN_PAYMENT_EXPIRED
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED
            )
        )
        button_text = 'Ajukan Pinjaman Baru'
        button_url = 'http://www.julofinance.com/android/goto/reapply'
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # ----------------------------------------------------
        # App status is FORM_PARTIAL
        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_PARTIAL)
        )
        credit_score = CreditScoreFactory()
        credit_score.application_id = self.application.id
        credit_score.score_tag = 'c_failed_binary'
        credit_score.score = 'A'
        credit_score.save()
        self.application.save()
        button_text = 'Pilih Pinjaman'
        button_url = 'http://www.julofinance.com/android/goto/product'
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # ----------------------------------------------------
        # App status is APPLICANT_CALLS_SUCCESSFUL or OFFER_ACCEPTED_BY_CUSTOMER
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER
            )
        )
        button_text = 'Mohon tunggu telepon dari JULO'
        button_url = None
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # ----------------------------------------------------
        # App status in DOCUMENTS_SUBMITTED, SCRAPED_DATA_VERIFIED, DOCUMENTS_VERIFIED,
        # CALL_ASSESSMENT, PRE_REJECTION, APPLICATION_RESUBMITTED,
        # APPLICATION_FLAGGED_FOR_SUPERVISOR, VERIFICATION_CALLS_ONGOING
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.DOCUMENTS_SUBMITTED
            )
        )
        button_text = 'Mohon tunggu dan kembali dalam 1 hari kerja'
        button_url = None
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # ----------------------------------------------------
        # App status is KYC_IN_PROGRESS
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.KYC_IN_PROGRESS
            )
        )
        process_streamlined_comm.return_value = msg
        kyc = KycRequestFactory()
        kyc.application_id = self.application.id
        uker_name = BankApplicationFactory()
        uker_name.application_id = self.application.id
        uker_name.uker_name = 'uker_name_test;'
        # Kyc Request is not expired
        kyc.expiry_time = datetime.now() + timedelta(days=1)
        kyc.save()
        uker_name.save()
        button_text = 'Aktifkan Rekening'
        button_url = 'http://www.julofinance.com/android/goto/activate_evoucher'
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # Kyc Request is expired
        kyc.expiry_time = datetime.now() - timedelta(days=1)
        kyc.save()
        uker_name.save()
        button_text = 'Dapatkan Voucher Baru'
        button_url = 'http://www.julofinance.com/android/goto/regen_evoucher'
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # ----------------------------------------------------
        # App status is FUND_DISBURSAL_FAILED
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.FUND_DISBURSAL_FAILED
            )
        )
        button_text = 'Mohon hubungi JULO'
        button_url = 'http://www.julofinance.com/android/goto/contactus'
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # ----------------------------------------------------
        # App status is LEGAL_AGREEMENT_RESUBMISSION_REQUESTED or ACTIVATION_CALL_SUCCESSFUL
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL
            )
        )
        self.application.sphp_exp_date = datetime.now().date()
        button_text = 'Surat Perjanjian'
        button_url = 'http://www.julofinance.com/android/goto/agreement'
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # ----------------------------------------------------
        # App status is LEGAL_AGREEMENT_SUBMITTED
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED
            )
        )
        button_text = 'Silahkan cek jadwal pembayaran cicilan di halaman Aktivitas Pinjaman'
        button_url = None
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # ----------------------------------------------------
        # App status is LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING
            )
        )
        button_text = 'Lakukan pembayaran DP Anda'
        button_url = None
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # ----------------------------------------------------
        # App status is DOWN_PAYMENT_PAID
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.DOWN_PAYMENT_PAID
            )
        )
        # product line code is GRAB
        self.application.product_line_id = ProductLineCodes.GRAB1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        button_text = 'Silakan unggah kwitansi/bukti transfer di halaman Aktivitas Pinjaman'
        button_url = None
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # ----------------------------------------------------
        # App status is FUND_DISBURSAL_SUCCESSFUL
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
            )
        )
        partner = PartnerFactory(name='doku')
        self.application.partner = partner
        loan = LoanFactory()
        partner = PartnerFactory()
        self.application.partner = partner
        button_text = 'Aktivitas Pinjaman'
        button_url = 'http://www.julofinance.com/android/goto/loan_activity'
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, loan)
        self.assertEqual(card, check_card)
        # ----------------------------------------------------
        # App status is DIGISIGN_FACE_FAILED
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.DIGISIGN_FACE_FAILED
            )
        )
        button_text = 'Unggah Selfie'
        button_url = 'http://www.julofinance.com/android/goto/appl_docs'
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, None, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # ----------------------------------------------------
        # App status is OFFER_MADE_TO_CUSTOMER_CODE
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER
            )
        )
        offer = OfferFactory()
        offer.application_id = self.application.id
        offer.save()
        process_streamlined_comm.return_value = msg
        button_text = 'Penawaran Pinjaman'
        button_url = 'http://www.julofinance.com/android/goto/got_offers'
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # ----------------------------------------------------
        # App status is LEGAL_AGREEMENT_SIGNED
        self.application.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED
            )
        )
        button_text = 'Silahkan cek jadwal pembayaran cicilan di halaman Aktivitas Pinjaman'
        button_url = None
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        # product line code is MTL
        self.application.product_line_id = ProductLineCodes.MTL1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # product line code is STL
        self.application.product_line_id = ProductLineCodes.STL1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # product line code is BRI
        self.application.product_line_id = ProductLineCodes.BRI1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # product line code is GRAB
        self.application.product_line_id = ProductLineCodes.GRAB1
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # ----------------------------------------------------
        # App status is PARTNER_APPROVED
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.PARTNER_APPROVED
        )
        # product line code is GRAB
        self.application.product_line_id = ProductLineCodes.GRAB1

        self.loan.application.save()
        self.loan.application.refresh_from_db()
        button_text = None
        button_url = None
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)
        # ----------------------------------------------------
        # App status is LOC_APPROVED
        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        button_text = 'Ajukan Pinjaman Baru'
        button_url = 'http://www.julofinance.com/android/goto/reapply'
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, None, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)

        ## App status is not FORM_CREATED
        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_CREATED)
        )
        header = 'WELCOME'
        button_text = None
        button_url = None
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)

        ## Product line code is LOC
        self.application.product_line_id = ProductLineCodes.LOC
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL
        )
        self.loan.application.save()
        self.loan.application.refresh_from_db()
        header = 'INFORMASI PENGAJUAN'
        button_text = 'Pilih Pinjaman'
        button_url = 'http://www.julofinance.com/android/goto/product'
        process_streamlined_comm.return_value = msg
        check_card = construct_card(msg, header, None, button_url, None, button_text)
        card = render_application_status_card(self.application, self.loan)
        self.assertEqual(card, check_card)


class TestRenderApplicationStatusCardLoc(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.app_status = self.application.application_status.status_code

    def test_app_status_is_form_partial(self):
        self.app_status = ApplicationStatusCodes.FORM_PARTIAL
        btn_text, btn_url = render_application_status_card_loc(self.app_status)
        self.assertEqual(btn_text, 'Pilih Pinjaman')
        self.assertEqual(btn_url, 'http://www.julofinance.com/android/goto/product')

    def test_app_status_is_submit(self):
        """
        - App status is FORM_SUBMITTED
        - App status is APPLICATION_RESUBMISSION_REQUESTED
        """
        self.app_status = ApplicationStatusCodes.FORM_SUBMITTED
        btn_text, btn_url = render_application_status_card_loc(self.app_status)
        self.assertEqual(btn_text, 'Unggah Dokumen')
        self.assertEqual(btn_url, 'http://www.julofinance.com/android/goto/appl_docs')

    def test_app_status_is_fail(self):
        """
        - App status is FORM_SUBMISSION_ABANDONED
        - App status is RESUBMISSION_REQUEST_ABANDONED
        - App status is APPLICATION_CANCELED_BY_CUSTOMER
        - App status is VERIFICATION_CALLS_EXPIRED
        - App status is OFFER_DECLINED_BY_CUSTOMER
        - App status is LEGAL_AGREEMENT_EXPIRED
        - App status is DOWN_PAYMENT_EXPIRED
        """
        self.app_status = ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED
        btn_text, btn_url = render_application_status_card_loc(self.app_status)
        self.assertEqual(btn_text, 'Ajukan Pengaktifan Baru')
        self.assertEqual(btn_url, 'http://www.julofinance.com/android/goto/reapply')

    def test_app_status_is_still_waiting_approval(self):
        """
        App status is DOCUMENTS_SUBMITTED
        App status is SCRAPED_DATA_VERIFIED
        App status is DOCUMENTS_VERIFIED
        App status is PRE_REJECTION
        App status is APPLICATION_RESUBMITTED
        App status is APPLICATION_FLAGGED_FOR_SUPERVISOR
        App status is VERIFICATION_CALLS_ONGOING
        """
        self.app_status = ApplicationStatusCodes.DOCUMENTS_SUBMITTED
        btn_text, btn_url = render_application_status_card_loc(self.app_status)
        self.assertEqual(btn_text, 'Mohon tunggu dan kembali dalam 1 hari kerja')
        self.assertEqual(btn_url, None)

    def test_app_status_is_still_waiting_a_phone_call(self):
        """
        App status is APPLICANT_CALLS_SUCCESSFUL
        App status is OFFER_ACCEPTED_BY_CUSTOMER
        """
        self.app_status = ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL
        btn_text, btn_url = render_application_status_card_loc(self.app_status)
        self.assertEqual(btn_text, 'Mohon tunggu telepon dari JULO')
        self.assertEqual(btn_url, None)

    def test_app_status_is_activation_call_successful(self):
        self.app_status = ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL
        btn_text, btn_url = render_application_status_card_loc(self.app_status)
        self.assertEqual(btn_text, 'Surat Perjanjian')
        self.assertEqual(btn_url, 'http://www.julofinance.com/android/goto/agreement')

    def test_app_status_is_legal_agreement(self):
        """
        App status is LEGAL_AGREEMENT_SUBMITTED
        App status is LEGAL_AGREEMENT_SIGNED
        """
        self.app_status = ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED
        btn_text, btn_url = render_application_status_card_loc(self.app_status)
        self.assertEqual(
            btn_text, 'Silahkan pelajari penggunaan produk di aktivitas pinjaman non-tunai'
        )
        self.assertEqual(btn_url, None)

    def test_app_status_is_legal_agreement_and_dp_pending(self):
        self.app_status = ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING
        btn_text, btn_url = render_application_status_card_loc(self.app_status)
        self.assertEqual(btn_text, 'Lakukan pembayaran DP Anda')
        self.assertEqual(btn_url, None)

    def test_app_status_is_down_payment_paid(self):
        self.app_status = ApplicationStatusCodes.DOWN_PAYMENT_PAID
        btn_text, btn_url = render_application_status_card_loc(self.app_status)
        self.assertEqual(
            btn_text, 'Silakan unggah kwitansi/bukti transfer di halaman Aktivitas Pinjaman'
        )
        self.assertEqual(btn_url, None)

    def test_app_status_is_loc_approved(self):
        self.app_status = ApplicationStatusCodes.LOC_APPROVED
        btn_text, btn_url = render_application_status_card_loc(self.app_status)
        self.assertEqual(btn_text, 'Ajukan Pinjaman Baru')
        self.assertEqual(btn_url, 'http://www.julofinance.com/android/goto/reapply')


class TestRenderDealsCard(TestCase):
    def test_render_deal_card(self):
        msg = (
            u'Dapatkan <font color=#FF0000>DOUBLE CASHBACK</font> untuk setiap pembayaran tepat '
            u'waktu di bulan <b>April 2017</b>.<br>\n<br>\nJangan sampai ketinggalan!'
        )
        card = render_deals_card()
        check_card = construct_card(
            msg,
            'PROMO',
            None,
            None,
            'https://www.julofinance.com/images/newsfeed/banner_deal.jpg',
            None,
        )
        self.assertEqual(card, check_card)


class TestRenderBonusCard(TestCase):
    def test_render_bonus_card(self):
        customer = CustomerFactory()
        check_card = construct_card(
            render_to_string('bonus.txt', {'referral_code': customer.self_referral_code}),
            'REFERRAL BONUS',
            None,
            None,
            'https://www.julofinance.com/images/newsfeed/banner_referral_bonus.jpg',
            None,
        )
        self.assertEqual(render_bonus_card(customer), check_card)


class TestRenderDefaultCard(TestCase):
    def test_render_default_card(self):
        check_card = construct_card(
            render_to_string('default.txt', None),
            'WELCOME',
            None,
            'http://www.julofinance.com/android/goto/appl_forms',
            None,
            'Formulir Pengajuan',
        )
        self.assertEqual(render_default_card(), check_card)


class TestRenderBfiOctPromoCard(TestCase):
    def test_render_bfi_oct_promo_card(self):
        check_card = construct_card(
            render_to_string('promo_bfi_oct_2018.txt'),
            'Promo BFI',
            None,
            None,
            'https://www.julo.co.id/apps_banner/banner_promo_bfi_oct_2018.jpg',
            None,
        )
        self.assertEqual(render_bfi_oct_promo_card(), check_card)


class TestRenderSeasonCard(TestCase):
    @patch('juloserver.apiv1.services.date')
    def test_render_season_card(self, mock_date):
        # date(2017, 5, 26) <= now <= date(2017, 6, 18)
        check_card = construct_card(
            render_to_string('ramadhan.txt'),
            'Ramadhan',
            None,
            None,
            'https://www.julofinance.com/images/newsfeed/ramadan.jpg',
            None,
        )
        mock_date.today.return_value = date(2017, 6, 10)
        mock_date.side_effect = lambda y, m, d: date(y, m, d)

        self.assertEqual(render_season_card(), check_card)

        # date(2017, 6, 19) <= now <= date(2017, 7, 3)
        check_card = construct_card(
            render_to_string('eid.txt'),
            'Eid Mubarak',
            None,
            None,
            'https://www.julofinance.com/images/newsfeed/eid.jpg',
            None,
        )
        mock_date.today.return_value = date(2017, 6, 25)
        self.assertEqual(render_season_card(), check_card)

        # now is out of time range above
        mock_date.today.return_value = date(2017, 7, 25)
        self.assertEqual(render_season_card(), None)


class TestRenderSPHPCard(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)

    def test_app_is_none(self):
        card = render_sphp_card(self.customer, 9999999)
        self.assertIsNone(card)

    def test_application_status_code_is_not_fund_disursal_successful(self):
        self.application.application_status_id = ApplicationStatusCodes.FORM_CREATED
        self.application.save()
        card = render_sphp_card(self.customer, self.application)
        self.assertIsNone(card)

    def test_application_loan_status_code_is_paid_off(self):
        self.application.application_status_id = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        self.application.save()
        loan = LoanFactory(application=self.application)
        loan.loan_status_id = LoanStatusCodes.PAID_OFF
        loan.save()
        card = render_sphp_card(self.customer, self.application)
        self.assertIsNone(card)

    def test_success_case(self):
        self.application.application_status_id = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        self.application.save()
        loan = LoanFactory(application=self.application)
        msg = render_to_string('sphp.txt')
        check_card = construct_card(
            msg,
            'Surat Perjanjian Hutang Piutang (SPHP)',
            None,
            'http://www.julofinance.com/android/goto/agreement',
            None,
            'Lihat Surat Perjanjian',
        )
        card = render_sphp_card(self.customer, self.application)
        self.assertEqual(card, check_card)


@override_settings(SUSPEND_SIGNALS=True)
class TestRenderCampaignCard(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)

    @patch('juloserver.apiv1.services.date')
    @patch('juloserver.apiv1.services.construct_card')
    def test_render_campaign_card_in_first_time_range(self, mock_construct_card, mock_date):
        # date(2018, 5, 15) <= now <= date(2018, 6, 8)
        mock_date.today.return_value = date(2018, 6, 1)
        mock_date.side_effect = lambda y, m, d: date(y, m, d)
        # application status code is not FUND_DISBURSAL_SUCCESSFUL
        self.application.application_status_id = ApplicationStatusCodes.FORM_SUBMITTED
        self.application.partner = None
        self.application.save()
        card = render_campaign_card(self.customer, self.application.id)
        self.assertIsNone(card)
        # application loan status is PAID_OFF and app status is FUND_DISBURSAL_SUCCESSFUL
        self.application.application_status_id = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        self.application.save()
        loan = LoanFactory(application=self.application)
        loan.loan_status_id = LoanStatusCodes.PAID_OFF
        loan.save()
        card = render_campaign_card(self.customer, self.application.id)
        self.assertIsNone(card)
        # application loan status is not PAID_OFF and app status is FUND_DISBURSAL_SUCCESSFUL
        loan.loan_status_id = LoanStatusCodes.CURRENT
        loan.save()
        payment = PaymentFactory(loan=loan)
        payment.payment_status_id = PaymentStatusCodes.PAYMENT_1DPD
        payment.save()
        payment_event = PaymentEventFactory(payment=payment, event_type='lebaran_promo')
        check_card = {'test': 'test'}
        mock_construct_card.return_value = check_card
        card = render_campaign_card(self.customer, self.application.id)
        self.assertEqual(card, check_card)
        # payment event type is not lebaran_promo
        payment_event.event_type = 'payment'
        payment_event.save()
        card = render_campaign_card(self.customer, self.application.id)
        self.assertIsNone(card)

    @patch('juloserver.apiv1.services.date')
    @patch('juloserver.apiv1.services.construct_card')
    def test_render_campaign_card_in_second_time_range(self, mock_construct_card, mock_date):
        # date(2018, 5, 7) <= now <= date(2018, 6, 30)
        mock_date.today.return_value = date(2018, 5, 8)
        mock_date.side_effect = lambda y, m, d: date(y, m, d)
        # application is None
        self.assertIsNone(render_campaign_card(self.customer, 999999))
        # application partner is None
        self.assertIsNone(render_campaign_card(self.customer, self.application.id))
        # partner is not None and partner name is tokopedia and app status id is FORM_PARTIAL
        partner = PartnerFactory(name='tokopedia')
        self.application.partner = partner
        self.application.application_status_id = ApplicationStatusCodes.FORM_PARTIAL
        self.application.save()
        check_card = {'test': 'test'}
        mock_construct_card.return_value = check_card
        card = render_campaign_card(self.customer, self.application.id)
        self.assertEqual(card, check_card)
        # partner name is not tokopedia
        partner.name = 'fake_name'
        partner.save()
        self.assertIsNone(render_campaign_card(self.customer, self.application.id))

    def test_render_campaign_card_in_any_valid_time_range(self):
        self.assertIsNone(render_campaign_card(self.customer, 9999999))


class TestRenderLoanSellOffCard(TestCase):
    def setUp(self):
        self.loan = LoanFactory()

    @patch('juloserver.apiv1.services.construct_card')
    def test_loan_selloff_is_not_none(self, mock_construct_card):
        loan_selloff = LoanSelloffFactory(loan_id=self.loan.id)
        check_card = {'test': 'test'}
        mock_construct_card.return_value = check_card
        card = render_loan_sell_off_card(self.loan)
        self.assertEqual(card, check_card)

    def test_loan_selloff_is_none(self):
        self.assertRaises(ObjectDoesNotExist, render_loan_sell_off_card, self.loan)
