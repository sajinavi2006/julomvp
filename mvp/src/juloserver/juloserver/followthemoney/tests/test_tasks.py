from django.contrib.auth.hashers import make_password
from mock import patch, MagicMock
import time

from django.test import TestCase
from juloserver.julo.tests.factories import AuthUserFactory, PartnerFactory, ApplicationFactory, CustomerFactory, \
    ProductLineFactory, OfferFactory, StatusLookupFactory, LoanFactory, ProductLookupFactory, PaymentFactory, \
    DocumentFactory, BankFactory
from juloserver.followthemoney.tasks import *
from juloserver.julo.tests.factories import FeatureSettingFactory

from ..constants import LoanAgreementType
from ..factories import LenderCurrentFactory, LenderBucketFactory, LoanAgreementTemplateFactory, \
    ApplicationHistoryFactory, LenderBalanceCurrentFactory
from ...julo.models import Workflow
from ..models import LenderSignature, LenderApproval, LenderDisbursementMethod


class TestFollowTheMoneyTasks(TestCase):
    def setUp(self):
        self.user = AuthUserFactory(username='test2')
        self.lender = LenderCurrentFactory(user=self.user, lender_name='test')
        self.partner = PartnerFactory()
        self.customer = CustomerFactory(user=self.user)
        self.product_line = ProductLineFactory(product_line_code=1000)
        self.loan_status = StatusLookupFactory(status_code=ApplicationStatusCodes.BULK_DISBURSAL_ONGOING)
        self.application = ApplicationFactory(customer=self.customer, partner=self.partner,
                                              product_line=self.product_line, application_xid=123456789,
                                              application_status=self.loan_status, fullname='Test1')
        self.lender_bucket = LenderBucketFactory(partner=self.partner,
                                                 application_ids={"approved": [self.application.id],
                                                                  "rejected": ['2000000146']}, lender_bucket_xid=1234)
        self.product_look_up = ProductLookupFactory(product_line=self.product_line)
        self.offer = OfferFactory(application=self.application, product=self.product_look_up)
        self.loan = LoanFactory(customer=self.customer, application=self.application, offer=self.offer,
                                loan_status=self.loan_status,
                                product=self.product_look_up, lender=self.lender, partner=self.partner)
        self.loan_egreement = LoanAgreementTemplateFactory(lender=self.lender, is_active=True,
                                                           agreement_type=LoanAgreementType.SUMMARY)
        self.application_history = ApplicationHistoryFactory(application=self.application, status_new=178)
        self.payment = PaymentFactory(loan=self.loan, payment_status=self.loan_status)
        self.document = DocumentFactory(document_type="summary_lender_sphp", document_source=self.lender_bucket.id)
        self.lender_signature = LenderSignature.objects.create(loan=self.loan, lender_bucket_xid=self.lender_bucket.lender_bucket_xid)
        LenderApproval.objects.create(partner=self.partner, start_date=datetime.now(), end_date=datetime.now(),
                                      is_endless=True, is_auto=True)
        LenderDisbursementMethod.objects.create(partner=self.partner, product_lines='mtl')
        LenderBalanceCurrentFactory(lender=self.lender)
        LenderBalanceHistory.objects.create(lender=self.lender, snapshot_type=SnapshotType.RECONCILE)
        BankFactory(bank_name='test', swift_bank_code='TEST123')

    @patch('juloserver.julo.clients.email.JuloEmailClient.send_email')
    def test_send_email_set_password(self, mock_get_julo_email_client):
        mock_get_julo_email_client.return_value = 'success', '', {'X-Message-Id': '1'}
        result = send_email_set_password(self.lender.id, reset_password=True)
        assert result is None

    def test_auto_reject_bucket(self):
        result = auto_reject_bucket(self.lender_bucket.id)
        assert result is None

    def test_generate_lender_loan_agreement(self):
        result = generate_lender_loan_agreement(100)
        assert result is None
        result = generate_lender_loan_agreement(self.application.id)
        assert result is None
        self.document.document_source = self.application.id
        self.document.document_type = 'lender_sphp'
        self.document.save()
        result = generate_lender_loan_agreement(self.application.id)
        assert result is None

    def test_partner_bulk_disbursement(self):
        self.application.application_status = self.loan_status
        self.application.save()
        result = partner_bulk_disbursement()
        assert result is None

    def test_generate_summary_lender_loan_agreement(self):
        result = generate_summary_lender_loan_agreement(0)
        assert result is None
        result = generate_summary_lender_loan_agreement(self.lender_bucket.id)
        assert result is None
        self.document.document_type = 'sphp_julo'
        self.document.save()
        result = generate_summary_lender_loan_agreement(self.lender_bucket.id)
        assert result is None

    def test_generate_sphp(self):
        result = generate_sphp(0)
        assert result is None
        result = generate_sphp(self.application.id)
        assert result is None

    @patch('juloserver.followthemoney.tasks.generate_julo_one_loan_agreement')
    def test_generate_julo_one_loan_agreement(self, mock_logger):
        self.document.document_type = 'sphp_julo'
        self.document.save()
        now = time.time()
        result = generate_julo_one_loan_agreement(self.application.id)
        time_limit = 2
        elapsed = time.time() - now
        self.assertIsNone(result)
        if elapsed > time_limit:
            mock_logger.info.assert_called_with({
                'action_view': 'generate_julo_one_loan_agreement',
                'data': {'loan_id': self.application.id},
                'message': "PDF rendering takes {} seconds, which is more than the {} seconds limit.".format(elapsed, time_limit)
            })

    @patch('juloserver.followthemoney.tasks.process_application_status_change')
    def test_approved_application_process_disbursement(self, mock_process_application_status_change):
        approved_application_process_disbursement(self.application.id, self.partner.id)
        assert mock_process_application_status_change.called

    @patch('juloserver.followthemoney.tasks.process_application_status_change')
    def test_bulk_approved_application_process_disbursement(self, mock_process_application_status_change):
        result = bulk_approved_application_process_disbursement(self.lender_bucket, 'digital')
        assert mock_process_application_status_change.called
        assert result is None

    @patch('juloserver.followthemoney.tasks.process_application_status_change')
    def test_reset_all_lender_bucket(self, mock_process_application_status_change):
        self.application.application_status = StatusLookupFactory(status_code=ApplicationStatusCodes.LENDER_APPROVAL)
        self.application.save()
        result = reset_all_lender_bucket(self.partner.id)
        assert mock_process_application_status_change.called

    def test_exclude_write_off_loans_from_current_lender_balance(self):
        result = exclude_write_off_loans_from_current_lender_balance()
        assert result is None

    @patch('juloserver.followthemoney.tasks.task_reconcile_perlender')
    def test_reconcile_lender_balance(self, mock_task_reconcile_perlender):
        result = reconcile_lender_balance()
        assert result is None

    @patch('juloserver.followthemoney.tasks.count_reconcile_transaction')
    def test_task_reconcile_perlender(self, mock_count_reconcile_transaction):
        mock_count_reconcile_transaction.return_value = 0
        result = task_reconcile_perlender(self.lender.id)
        assert mock_count_reconcile_transaction.called
        assert result is None

    def test_assign_lenderbucket_xid_to_lendersignature(self):
        application = ApplicationFactory(customer=self.customer, partner=self.partner,
                                              product_line=self.product_line, application_xid=12345678,
                                              application_status=self.loan_status)
        loan = LoanFactory(customer=self.customer, application=application, offer=self.offer,
                                loan_status=self.loan_status,
                                product=self.product_look_up, lender=self.lender, partner=self.partner)
        result = assign_lenderbucket_xid_to_lendersignature([application.id], self.lender_bucket.lender_bucket_xid)
        assert result is None

    def test_auto_expired_application_tasks(self):
        self.application.application_status = StatusLookupFactory(status_code=ApplicationStatusCodes.LENDER_APPROVAL)
        self.application.save()
        result = auto_expired_application_tasks(self.application.id, self.lender.id)
        assert result is None



    # @patch('juloserver.followthemoney.tasks.get_transaction_detail')
    @patch('juloserver.followthemoney.tasks.get_julo_repayment_bca_client')
    @patch('juloserver.followthemoney.tasks.get_repayment_transaction_data')
    def test_repayment_daily_transfer(self, mock_get_repayment_transaction_data, mock_get_julo_repayment_bca_client):
        self.lender.lender_name = 'jtp'
        self.lender.save()
        mock_get_repayment_transaction_data.return_value = None
        result = repayment_daily_transfer()
        assert mock_get_repayment_transaction_data.called
        assert result is None
        value_dict = {'amount': 10000, 'bank_name': 'test', 'cust_account_number': '1234567',
                      'cust_name_in_bank': 'TEST', 'additional_info': ''}
        mock_get_repayment_transaction_data.return_value = value_dict
        # result = repayment_daily_transfer()
        # mock_get_julo_repayment_bca_client.called

    @patch('juloserver.followthemoney.services.deduct_lender_reversal_transaction')
    @patch('juloserver.followthemoney.services.get_available_balance')
    def test_scheduled_retry_for_reversal_payment_insufficient_balance(self, mock_get_available_balance,
                                                                       mock_deduct_lender_reversal_transaction):
        mock_get_available_balance.return_value = 1000.0
        mock_deduct_lender_reversal_transaction.return_value = True, ''
        result = scheduled_retry_for_reversal_payment_insufficient_balance()
        assert result is None

    @patch('juloserver.followthemoney.tasks.send_message_normal_format')
    @patch('juloserver.followthemoney.tasks.get_julo_xendit_client')
    def test_send_slack_notification_xendit_remaining_balance_task(
            self, xendit_client_mock,
            slack_channel_mock,
        ):
        parameters={
            "users": [
                "INVALIDXXXX"
            ],
            "balance_threshold": 10000000
        }

        self.featuresetting = FeatureSettingFactory(
            feature_name=FeatureNameConst.NOTIFICATION_MINIMUM_XENDIT_BALANCE,
            parameters=parameters,
        )
        xendit_client_mock.return_value.get_balance.return_value = {'balance': 100000}
        send_slack_notification_xendit_remaining_balance()
        xendit_client_mock.return_value.get_balance.return_value = {'balance': 15000000}
        send_slack_notification_xendit_remaining_balance()
        assert '#partner_balance' == slack_channel_mock.mock_calls[0][2]['channel']
        assert len(slack_channel_mock.mock_calls[0][1][0]) > 0
