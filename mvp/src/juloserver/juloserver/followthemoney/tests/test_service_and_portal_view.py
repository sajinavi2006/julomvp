from builtins import str
import os

from django.contrib.auth.hashers import make_password
from mock import patch, MagicMock

from django.test import TestCase, override_settings

from django.conf import settings

from juloserver.julo.models import Bank
from ..factories import *
from juloserver.julo.tests.factories import PaymentMethodFactory, ApplicationFactory, LoanFactory
from juloserver.julo.tests.factories import PaymentEventFactory, PaymentFactory, PartnerFactory, CustomerFactory

from juloserver.portal.object.lender.utils import StatementParserFactory

from ..services import *



@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestFollowTheMoneyMainServices(TestCase):

    def setUp(self):
        self.application = ApplicationFactory()
        self.lender = LenderCurrentFactory()
        self.lender_bank = LenderBankAccountFactory(
            lender=self.lender,
            bank_account_type='repayment_va')
        self.loan = LoanFactory(lender=self.lender)
        self.payment_permata = PaymentFactory(
            loan=self.loan,
            installment_principal=50000000)
        self.payment_bca = PaymentFactory(loan=self.loan)
        self.payment_icare = PaymentFactory(loan=self.loan)
        self.permata_va = 1234
        self.bca_va = 4321
        self.payment_method_permata = PaymentMethodFactory(virtual_account=self.permata_va)
        self.payment_method_bca = PaymentMethodFactory(virtual_account=self.bca_va)
        self.payment_event_icare = PaymentEventFactory(
            event_type='payment',
            event_payment=100000000,
            payment=self.payment_icare
        )
        self.payment_event_permata = PaymentEventFactory(
            event_type='payment',
            payment_method=self.payment_method_permata,
            event_payment=100000000,
            payment=self.payment_permata
        )
        self.payment_void = PaymentEventFactory(
            event_type='payment_void',
            payment_method=self.payment_method_permata,
            event_payment=-1
        )
        self.payment_void_icare = PaymentEventFactory(
            event_type='payment_void',
            payment=self.payment_icare,
            event_payment=-1
        )
        PaymentEventFactory(
            event_type='payment',
            payment=self.payment_icare,
            reversal=self.payment_void_icare
        )
        PaymentEventFactory(
            event_type='payment',
            payment_method=self.payment_method_permata,
            reversal=self.payment_void
        )
        self.payment_event_bca = PaymentEventFactory(
            event_type='payment',
            payment_method=self.payment_method_bca,
            payment=self.payment_bca)
        self.lender_repayment_transaction = LenderRepaymentTransactionFactory(lender=self.lender)
        self.user = InventorUserFactory(username='test', password=make_password('password@123'))
        self.partner = PartnerFactory(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.repayment_transaction = RepaymentTransactionFactory(partner=self.partner, customer=self.customer,
                                                                 loan=self.loan, payment=self.payment_bca)
        self.lender_reversal_transaction = LenderReversalTransactionFactory(source_lender=self.lender,
                                                                            voided_payment_event=self.payment_event_icare)

    @patch('juloserver.followthemoney.services.get_transaction_detail')
    @patch('juloserver.followthemoney.services.get_redis_client')
    def test_get_transfer_order(self, mock_get_redis_client, mock_get_transaction_detail):
        mock_cached_va = "{'permata': [%d], 'bca':[%d]}" % (self.permata_va, self.bca_va)
        mock_get_redis_client.return_value.get.return_value = mock_cached_va

        mock_get_transaction_detail.return_value = (True, True)
        result = get_transfer_order('fake_redis_key')
        assert len(list(result.keys())) == 1

    @patch('juloserver.followthemoney.services.get_transaction_detail')
    @patch('juloserver.followthemoney.services.get_redis_client')
    def test_get_transfer_order_adjust_interest(
            self, mock_get_redis_client, mock_get_transaction_detail):
        mock_cached_va = "{'permata': [%d], 'bca':[%d]}" % (self.permata_va, self.bca_va)
        mock_get_redis_client.return_value.get.return_value = mock_cached_va
        self.payment_permata.installment_principal = 100000000
        self.payment_permata.save()

        mock_get_transaction_detail.return_value = (True, True)
        result = get_transfer_order('fake_redis_key')
        assert len(list(result.keys())) == 1

    @patch('juloserver.followthemoney.services.get_transaction_detail')
    @patch('juloserver.followthemoney.services.get_redis_client')
    def test_get_transfer_order_cached_not_found(
            self, mock_get_redis_client, mock_get_transaction_detail):
        mock_cached_va = None
        mock_get_redis_client.return_value.get.return_value = mock_cached_va

        mock_get_transaction_detail.return_value = (True, True)
        result = get_transfer_order('fake_redis_key')
        assert result is None

    @patch('juloserver.followthemoney.services.get_last_transaction')
    @patch('juloserver.followthemoney.services.get_transaction_detail')
    @patch('juloserver.followthemoney.services.get_redis_client')
    def test_get_transfer_order_ltm_not_found(
            self, mock_get_redis_client, mock_get_transaction_detail,
            _mock_get_last_transaction):
        mock_cached_va = "{'permata': [%d]}" % (999)
        self.lender_bank.bank_account_type = 'test'
        self.lender_bank.save()
        mock_get_redis_client.return_value.get.return_value = mock_cached_va
        mock_get_transaction_detail.return_value = (False, True)
        result = get_transfer_order('fake_redis_key')
        assert not result

    def test_create_repayment_data(self):
        Bank.objects.create(bank_name='BCA', swift_bank_code='testing')
        result = create_repayment_data(
            100,
            'test',
            'BCA',
            'test',
            'test',
            'test',
            'test',
            'test',
        )
        assert result['beneficiary_bank_code'] == 'testing'

    @patch('juloserver.followthemoney.services.get_transfer_order')
    def test_get_repayment_transaction_data(self, mock_get_transfer_order):
        mock_get_transfer_order.return_value = {
            1: {
                'displayed_amount': ''
            },
            100: {
                'displayed_amount': '9999',
                'account_number': 'test',
                'bank_name': 'test',
                'account_name': 'test',
                'service_fee': 100,
                'repayment_detail': {'permata': {
                    'transfer_amount': 'test',
                    'paid_principal': 'test',
                    'paid_interest': 'test',
                    'original_amount': 'test',
                    'transaction_mapping_ids': 'test',
                    'total_service_fee': 'test',
                }}
            }
        }
        lender_target = MagicMock()
        lender_target.id = 100
        result = get_repayment_transaction_data(lender_target, filtering=True)
        assert result is not None

    @patch('juloserver.followthemoney.services.get_transfer_order')
    def test_get_repayment_transaction_data_no_data(self, mock_get_transfer_order):
        mock_get_transfer_order.return_value = {
            1: {
                'displayed_amount': ''
            },
        }
        lender_target = MagicMock()
        lender_target.id = 10
        result = get_repayment_transaction_data(lender_target)
        assert result is None

    @patch('juloserver.followthemoney.services.get_current_group_id')
    def test_get_last_transaction(self, mock_get_current_group_id):
        mock_get_current_group_id.return_value = 2
        result = get_last_transaction(1)
        assert not result['2']

    @patch('juloserver.followthemoney.services.get_current_group_id')
    def test_get_last_transaction_no_group_id(self, mock_get_current_group_id):
        mock_get_current_group_id.return_value = None
        result = get_last_transaction(1)
        assert result == {}

    def test_generate_group_id(self):
        result = generate_group_id(self.lender)
        self.assertEqual(result, 2)

    def test_get_current_group_id(self):
        result = get_current_group_id(self.lender)
        self.assertEqual(result, 1)

    def test_get_repayment(self):
        result = get_repayment(self.loan)
        self.assertEqual(result, 0)

    def test_calculate_net_profit(self):
        result = calculate_net_profit(StatusLookup.PAID_OFF_CODE, 1000, 100, 100)
        self.assertEqual(result, 1000)
        result = calculate_net_profit(StatusLookup.SELL_OFF, 1000, 100, 100)
        self.assertEqual(result, 0)

    def test_check_lender_reversal_step_needed(self):
        result = check_lender_reversal_step_needed(self.lender_reversal_transaction)
        self.assertEqual(result, LenderReversalTransactionConst.LENDER_TO_JTF_STEP)

    def test_deduct_lender_reversal_transaction(self):
        data = dict(id=0)
        result = deduct_lender_reversal_transaction(data)
        self.assertEqual(result, (False, 'lender reversal transaction not found'))


class TestPortalView(TestCase):

    def setUp(self):
        self.axita_partner = PartnerFactory(name='axiata')
        self.application_axiata = ApplicationFactory(
            application_xid=123456789,
            partner=self.axita_partner,
        )
        self.icare_partner = PartnerFactory(name='icare')
        self.application_icare = ApplicationFactory(
            application_xid=12345678910,
            partner=self.icare_partner,
        )
        self.loan_axiata = LoanFactory(
            application=self.application_axiata
        )
        self.loan_icare = LoanFactory(
            application=self.application_icare
        )
        script_dir = settings.BASE_DIR + '/misc_files/parsing_data_test/'
        self.midtrans_file = open(script_dir + 'midtrans_test.csv', 'rb').read()
        self.permata_file = open(script_dir + 'PERMATA.xlsx', 'rb').read()
        self.bri_file = open(script_dir + 'BRI.xlsx', 'rb').read()
        self.icare_file = open(script_dir + 'ICARE.xlsx', 'rb').read()
        self.axiata_file = open(script_dir + 'AXIATA.xlsx', 'rb').read()

    def test_midtrans_parser(self):
        parser_factory = StatementParserFactory()
        midtrans_parser = parser_factory.get_parser('midtrans')
        result = midtrans_parser.parse(self.midtrans_file)
        assert result == []

    def test_midtrans_parser_wrong_format(self):
        parser_factory = StatementParserFactory()
        test_data = self.midtrans_file.replace(b'GO-PAY', b'GO-GO')
        midtrans_parser = parser_factory.get_parser('midtrans')
        error_msg = ''
        try:
            midtrans_parser.parse(test_data)
        except Exception as error:
            error_msg = str(error)

        assert error_msg == 'Incorrect file uploaded'

    def test_permata_parser(self):
        parser_factory = StatementParserFactory()
        midtrans_parser = parser_factory.get_parser('permata')
        result = midtrans_parser.parse(self.permata_file)
        assert result == []

    def test_bri_parser(self):
        parser_factory = StatementParserFactory()
        midtrans_parser = parser_factory.get_parser('bri')
        result = midtrans_parser.parse(self.bri_file)
        assert result == []

    def test_icare_parser(self):
        parser_factory = StatementParserFactory()
        midtrans_parser = parser_factory.get_parser('icare')
        result = midtrans_parser.parse(self.icare_file)
        target_payment = self.loan_icare.payment_set.filter(payment_number=4).last()
        assert result == []

    def test_axiata_parser(self):
        parser_factory = StatementParserFactory()
        midtrans_parser = parser_factory.get_parser('axiata')
        result = midtrans_parser.parse(self.axiata_file)
        target_payment = self.loan_axiata.payment_set.last()
        assert result == []
