import io
from unittest.mock import patch
import uuid

from django.test import TestCase
from mock import ANY

from juloserver.account.constants import AccountConstant
from juloserver.followthemoney.factories import LenderCurrentFactory
from juloserver.julo.constants import CloudStorage, WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julocore.constants import RedisWhiteList
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.qris.exceptions import AmarStatusChangeCallbackInvalid
from juloserver.qris.tasks import (
    bulk_process_callback_transaction_status_from_amar_task,
    generate_qris_master_agreement_task,
    retrieve_and_set_qris_redis_whitelist_csv,
)
from juloserver.qris.models import (
    QrisLinkageLenderAgreement,
    QrisPartnerTransactionHistory,
    QrisUserState,
    QrisPartnerLinkage,
)
from juloserver.julo.models import Document, RedisWhiteListUploadHistory
from juloserver.followthemoney.constants import LenderName, LoanAgreementType
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
    ImageFactory,
    LoanFactory,
    PartnerFactory,
    ProductLineFactory,
    RedisWhiteListUploadHistoryFactory,
    StatusLookupFactory,
    WorkflowFactory,
)
from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.qris.constants import AmarCallbackConst, QrisLinkageStatus, QrisTransactionStatus
from juloserver.qris.tasks import (
    process_callback_register_from_amar_task,
    process_callback_transaction_status_from_amar_task,
)
from juloserver.qris.tests.factories import QrisPartnerLinkageFactory, QrisPartnerTransactionFactory


class TestGenerateQrisMasterAgreementTask(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(account=self.account)
        self.signature_image = ImageFactory()
        self.signature_image_2 = ImageFactory()
        self.partner = PartnerFactory()
        self.qris_partner_linkage = QrisPartnerLinkage.objects.create(
            customer_id=self.customer.pk, partner_id=self.partner.pk
        )
        self.qris_user_state = QrisUserState.objects.create(
            qris_partner_linkage=self.qris_partner_linkage, signature_image=self.signature_image
        )

        self.lender = LenderCurrentFactory(
            lender_name=LenderName.BLUEFINC,
        )
        self.lender_2 = LenderCurrentFactory(
            lender_name=LenderName.JTP,
        )
        self.qris_linkage_lender_agreement = QrisLinkageLenderAgreement.objects.create(
            qris_partner_linkage=self.qris_partner_linkage,
            lender_id=self.lender.id,
            signature_image_id=self.signature_image.id,
        )
        self.qris_linkage_lender_agreement_2 = QrisLinkageLenderAgreement.objects.create(
            qris_partner_linkage=self.qris_partner_linkage,
            lender_id=self.lender_2.id,
            signature_image_id=self.signature_image_2.id,
        )

    @patch('juloserver.qris.services.user_related.get_master_agreement_html')
    @patch('juloserver.qris.tasks.pdfkit.from_string')
    @patch('juloserver.qris.tasks.upload_document')
    @patch('juloserver.account.models.Account.get_active_application')
    def test_generate_qris_master_agreement_task_success(
        self, mock_get_active_application, mock_upload_document, mock_pdfkit, mock_get_html
    ):
        # Arrange
        mock_get_html.return_value = "<html>Test Agreement</html>"
        mock_pdfkit.return_value = None  # Mocking PDF creation
        mock_upload_document.return_value = None
        mock_get_active_application.return_value = self.application
        # Act
        generate_qris_master_agreement_task(self.qris_linkage_lender_agreement.id)

        # Assert
        self.qris_user_state.refresh_from_db()
        self.qris_linkage_lender_agreement.refresh_from_db()

        # Check if master agreement was created
        self.assertIsNotNone(self.qris_user_state.master_agreement_id)  # first time so it's created
        self.assertIsNotNone(self.qris_linkage_lender_agreement.master_agreement_id)

        first_master_agreement_id = self.qris_user_state.master_agreement_id

        # Verify Document creation
        document = Document.objects.get(id=self.qris_linkage_lender_agreement.master_agreement_id)
        self.assertEqual(document.document_source, self.qris_user_state.id)
        self.assertEqual(document.document_type, LoanAgreementType.MASTER_AGREEMENT)
        self.assertIn(
            f'qris_master_agreement_{self.customer.id}_{self.lender.lender_name}_',
            document.filename,
        )

        # Verify function calls
        mock_get_html.assert_called_once_with(
            self.application,
            lender=self.lender,
            signature_image=self.signature_image,
        )
        mock_pdfkit.assert_called_once()
        expected_file = '/tmp/{}'.format(document.filename)
        mock_upload_document.assert_called_once_with(document.id, expected_file, is_qris=True)

        # second time with different lender
        # should throw no error
        generate_qris_master_agreement_task(self.qris_linkage_lender_agreement_2.id)

        # refresh
        self.qris_linkage_lender_agreement_2.refresh_from_db()

        # user_state.master_agreeement_id is not updated for non 1st-time
        self.assertEqual(first_master_agreement_id, self.qris_user_state.master_agreement_id)
        self.assertIsNotNone(self.qris_linkage_lender_agreement_2.master_agreement_id)
        self.assertNotEqual(
            first_master_agreement_id,
            self.qris_linkage_lender_agreement_2.master_agreement_id,
        )

    @patch('juloserver.account.models.Account.get_active_application')
    @patch('juloserver.qris.tasks.logger')
    def test_generate_qris_master_agreement_task_already_generated(
        self, mock_logger, mock_get_active_application
    ):
        mock_get_active_application.return_value = self.application
        # Arrange
        doc = Document.objects.create(
            document_source=self.qris_user_state.id,
            document_type=LoanAgreementType.MASTER_AGREEMENT,
            filename='existing_agreement.pdf',
        )
        self.qris_user_state.master_agreement_id = doc.id
        self.qris_user_state.save()

        self.qris_linkage_lender_agreement.master_agreement_id = doc.id
        self.qris_linkage_lender_agreement.save()

        # Act
        generate_qris_master_agreement_task(self.qris_linkage_lender_agreement.id)

        # Assert
        mock_logger.warning.assert_called_once_with(
            {
                'action': 'generate_qris_master_agreement_task',
                "qris_linkage_lender_agreement_id": self.qris_linkage_lender_agreement.id,
                'message': "Master agreement has already been generated",
            }
        )

    @patch('juloserver.account.models.Account.get_active_application')
    @patch('juloserver.qris.services.user_related.get_master_agreement_html')
    @patch('juloserver.qris.tasks.logger')
    def test_generate_qris_master_agreement_task_exception(
        self, mock_logger, mock_get_html, mock_get_active_application
    ):
        # Arrange
        mock_get_html.side_effect = Exception("Test exception")
        mock_get_active_application.return_value = self.application
        # Act
        with self.assertRaises(Exception) as e:
            generate_qris_master_agreement_task(self.qris_linkage_lender_agreement.id)
            self.assertIn("Test exception", str(e))

        # Assert
        mock_logger.exception.assert_called_once_with(
            {
                'action': 'generate_qris_master_agreement_task',
                "qris_linkage_lender_agreement_id": self.qris_linkage_lender_agreement.id,
                'error': "Test exception",
            }
        )


class TestAmarProcessCallbackRegisterTask(TestCase):
    def setUp(self):
        self.partner_user = AuthUserFactory()
        self.partner = PartnerFactory(
            user=self.partner_user,
            name=PartnerNameConstant.AMAR,
        )

        self.customer = CustomerFactory()
        self.linkage = QrisPartnerLinkageFactory(
            status=QrisLinkageStatus.REQUESTED,
            customer_id=self.customer.id,
            partner_id=self.partner.id,
            partner_callback_payload={"any": "any"},
        )

    def test_happy_case_requested(self):
        # any data in payload can do
        payload = {
            "partnerCustomerId": "2a196a04bf5f45a18187136a6d1706ff",
            "status": "accepted",
            "accountNumber": "1503566938",
            "type": "new",
            "source_type": "partner_apps",
            "client_id": "ebf-amarbank",
            "reject_reason": "",
        }

        # requested -> success

        process_callback_register_from_amar_task(
            amar_status=AmarCallbackConst.AccountRegister.ACCEPTED_STATUS,
            to_partner_user_xid=self.linkage.to_partner_user_xid.hex,
            payload=payload,
        )

        self.linkage.refresh_from_db()
        self.assertEqual(
            self.linkage.status,
            QrisLinkageStatus.SUCCESS,
        )

        self.assertEqual(
            self.linkage.partner_callback_payload,
            payload,
        )

        status_history = self.linkage.histories.filter(field='status').last()
        self.assertIsNotNone(status_history)

        payload_history = self.linkage.histories.filter(field='partner_callback_payload').last()
        self.assertIsNotNone(payload_history)

        #  requested -> failed
        self.linkage.status = QrisLinkageStatus.REQUESTED
        self.linkage.save()

        process_callback_register_from_amar_task(
            amar_status=AmarCallbackConst.AccountRegister.REJECTED_STATUS,
            to_partner_user_xid=self.linkage.to_partner_user_xid.hex,
            payload=payload,
        )

        self.linkage.refresh_from_db()
        self.assertEqual(
            self.linkage.status,
            QrisLinkageStatus.FAILED,
        )

        self.assertEqual(
            self.linkage.partner_callback_payload,
            payload,
        )

        status_history = self.linkage.histories.filter(field='status').last()
        self.assertIsNotNone(status_history)

        payload_history = self.linkage.histories.filter(field='partner_callback_payload').last()
        self.assertIsNotNone(payload_history)

    def test_from_success_status(self):
        #  success -> failed, nothing happens

        payload = {
            "partnerCustomerId": "2a196a04bf5f45a18187136a6d1706ff",
            "status": "rejected",
            "accountNumber": "",
            "type": "new",
            "source_type": "partner_apps",
            "client_id": "ebf-amarbank",
            "reject_reason": "selfieHoldingIdCard,editedSelfie,selfieCapturedByOther,zeroLiveness",
        }
        self.linkage.status = QrisLinkageStatus.SUCCESS
        self.linkage.save()

        process_callback_register_from_amar_task(
            amar_status=AmarCallbackConst.AccountRegister.REJECTED_STATUS,
            to_partner_user_xid=self.linkage.to_partner_user_xid.hex,
            payload=payload,
        )

        self.linkage.refresh_from_db()
        self.assertEqual(
            self.linkage.status,
            QrisLinkageStatus.SUCCESS,
        )

        status_history = self.linkage.histories.filter(field='status').last()
        self.assertIsNone(status_history)

        payload_history = self.linkage.histories.filter(field='partner_callback_payload').last()
        self.assertIsNone(payload_history)

    def test_from_failed_status(self):
        #  failed -> success

        payload = {
            "partnerCustomerId": "2a196a04bf5f45a18187136a6d1706ff",
            "status": "accepted",
            "accountNumber": "1503566938",
            "type": "new",
            "source_type": "partner_apps",
            "client_id": "ebf-amarbank",
            "reject_reason": "",
        }
        self.linkage.status = QrisLinkageStatus.FAILED
        self.linkage.save()

        process_callback_register_from_amar_task(
            amar_status=AmarCallbackConst.AccountRegister.ACCEPTED_STATUS,
            to_partner_user_xid=self.linkage.to_partner_user_xid.hex,
            payload=payload,
        )

        self.linkage.refresh_from_db()
        self.assertEqual(
            self.linkage.status,
            QrisLinkageStatus.SUCCESS,
        )

        self.assertEqual(
            self.linkage.partner_callback_payload,
            payload,
        )

        status_history = self.linkage.histories.filter(
            field='status',
            value_old=QrisLinkageStatus.FAILED,
            value_new=QrisLinkageStatus.SUCCESS,
        ).last()
        self.assertIsNotNone(status_history)

        payload_history = self.linkage.histories.filter(field='partner_callback_payload').last()
        self.assertIsNotNone(payload_history)


class TestAmarProcessCallbackLoanTask(TestCase):
    def setUp(self):
        self.partner_user = AuthUserFactory()
        self.partner = PartnerFactory(
            user=self.partner_user,
            name=PartnerNameConstant.AMAR,
        )

        self.customer = CustomerFactory()
        self.linkage = QrisPartnerLinkageFactory(
            status=QrisLinkageStatus.SUCCESS,
            customer_id=self.customer.id,
            partner_id=self.partner.id,
            partner_callback_payload={"any": "any"},
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
        )
        self.qris_transaction_method = TransactionMethodFactory.qris_1()
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
            transaction_method_id=self.qris_transaction_method.id,
        )
        self.transaction = QrisPartnerTransactionFactory(
            loan_id=self.loan.id,
            status=QrisTransactionStatus.PENDING,
            qris_partner_linkage=self.linkage,
            from_partner_transaction_xid=uuid.uuid4().hex,
        )

    @patch("juloserver.qris.tasks.julo_one_loan_disbursement_success")
    def test_happy_path_success(self, mock_julo_one_disbursement):
        payload = {
            "serviceId": "EB_QRIS_STATUS",
            "amarbankAccount": "1513001959",
            "partnerCustomerID": self.linkage.to_partner_user_xid.hex,
            "timestamp": "2020-07-10 15:00:00.000",
            "statusCode": AmarCallbackConst.LoanDisbursement.SUCESS_STATUS,
            "data": {
                "merchantName": "Toko satu",
                "merchantCity": "JAKARTA PUSAT",
                "merchantPan": "9360081702401979531",
                "transactionID": self.transaction.from_partner_transaction_xid,
                "customerPan": "9360053115011111111",
                "amount": 10000,
            },
        }
        process_callback_transaction_status_from_amar_task(
            payload=payload,
        )

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, QrisTransactionStatus.SUCCESS)

        # assert history
        status_history_exists = QrisPartnerTransactionHistory.objects.filter(
            qris_partner_transaction=self.transaction,
            field='status',
            value_old=QrisTransactionStatus.PENDING,
            value_new=QrisTransactionStatus.SUCCESS,
        ).exists()

        self.assertEqual(status_history_exists, True)

        payload_history_exists = QrisPartnerTransactionHistory.objects.filter(
            qris_partner_transaction=self.transaction,
            field='partner_callback_payload',
            value_old=None,
            value_new=payload,
        ).exists()

        self.assertEqual(payload_history_exists, True)

        mock_julo_one_disbursement.assert_called_once_with(
            loan=self.loan,
        )

    def test_happy_path_failed(self):
        payload = {
            "serviceId": "EB_QRIS_STATUS",
            "amarbankAccount": "1513001959",
            "partnerCustomerID": self.linkage.to_partner_user_xid.hex,
            "timestamp": "2020-07-10 15:00:00.000",
            "statusCode": AmarCallbackConst.LoanDisbursement.FAIL_STATUS,
            "data": {
                "merchantName": "Toko satu",
                "merchantCity": "JAKARTA PUSAT",
                "merchantPan": "9360081702401979531",
                "transactionID": self.transaction.from_partner_transaction_xid,
                "customerPan": "9360053115011111111",
                "amount": 10000,
            },
        }
        process_callback_transaction_status_from_amar_task(
            payload=payload,
        )

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, QrisTransactionStatus.FAILED)

        # assert history
        status_history_exists = QrisPartnerTransactionHistory.objects.filter(
            qris_partner_transaction=self.transaction,
            field='status',
            value_old=QrisTransactionStatus.PENDING,
            value_new=QrisTransactionStatus.FAILED,
        ).exists()

        self.assertEqual(status_history_exists, True)

        payload_history_exists = QrisPartnerTransactionHistory.objects.filter(
            qris_partner_transaction=self.transaction,
            field='partner_callback_payload',
            value_old=None,
            value_new=payload,
        ).exists()

        self.assertEqual(payload_history_exists, True)

        self.loan.refresh_from_db()
        self.assertEqual(self.loan.status, LoanStatusCodes.TRANSACTION_FAILED)

    def test_case_invalid_path(self):
        payload = {
            "serviceId": "EB_QRIS_STATUS",
            "amarbankAccount": "1513001959",
            "partnerCustomerID": self.linkage.to_partner_user_xid.hex,
            "timestamp": "2020-07-10 15:00:00.000",
            "statusCode": "00",  # success
            "data": {
                "merchantName": "Toko satu",
                "merchantCity": "JAKARTA PUSAT",
                "merchantPan": "9360081702401979531",
                "transactionID": self.transaction.from_partner_transaction_xid,
                "customerPan": "9360053115011111111",
                "amount": 10000,
            },
        }

        # already failed, do nothing
        self.transaction.status = QrisTransactionStatus.FAILED
        self.transaction.save()

        with self.assertRaises(AmarStatusChangeCallbackInvalid):
            process_callback_transaction_status_from_amar_task(
                payload=payload,
            )

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, QrisTransactionStatus.FAILED)

        # assert history
        status_history_exists = QrisPartnerTransactionHistory.objects.filter(
            qris_partner_transaction=self.transaction,
            field='status',
            value_old=QrisTransactionStatus.FAILED,
            value_new=QrisTransactionStatus.SUCCESS,
        ).exists()

        self.assertEqual(status_history_exists, False)

        payload_history_exists = QrisPartnerTransactionHistory.objects.filter(
            qris_partner_transaction=self.transaction,
            field='partner_callback_payload',
            value_old=None,
            value_new=payload,
        ).exists()

        self.assertEqual(payload_history_exists, False)

        # already success, do nothing
        self.transaction.status = QrisTransactionStatus.SUCCESS
        self.transaction.save()

        with self.assertRaises(AmarStatusChangeCallbackInvalid):
            process_callback_transaction_status_from_amar_task(
                payload=payload,
            )

        # assert history
        status_history_exists = QrisPartnerTransactionHistory.objects.filter(
            qris_partner_transaction=self.transaction,
            field='status',
            value_old=QrisTransactionStatus.SUCCESS,
            value_new=QrisTransactionStatus.SUCCESS,
        ).exists()

        self.assertEqual(status_history_exists, False)

        payload_history_exists = QrisPartnerTransactionHistory.objects.filter(
            qris_partner_transaction=self.transaction,
            field='partner_callback_payload',
            value_old=None,
            value_new=payload,
        ).exists()

        self.assertEqual(payload_history_exists, False)

    def test_case_ok_amar_pending_status(self):
        # already pending
        payload = {
            "serviceId": "EB_QRIS_STATUS",
            "amarbankAccount": "1513001959",
            "partnerCustomerID": self.linkage.to_partner_user_xid.hex,
            "timestamp": "2020-07-10 15:00:00.000",
            "statusCode": AmarCallbackConst.LoanDisbursement.PENDING_STATUS,
            "data": {
                "merchantName": "Toko satu",
                "merchantCity": "JAKARTA PUSAT",
                "merchantPan": "9360081702401979531",
                "transactionID": self.transaction.from_partner_transaction_xid,
                "customerPan": "9360053115011111111",
                "amount": 10000,
            },
        }
        process_callback_transaction_status_from_amar_task(
            payload=payload,
        )

        payload_history_exists = QrisPartnerTransactionHistory.objects.filter(
            qris_partner_transaction=self.transaction,
            field='partner_callback_payload',
            value_old=None,
            value_new=payload,
        ).exists()

        self.assertEqual(payload_history_exists, True)

        # still same loan status & transaction
        self.loan.refresh_from_db()
        self.transaction.refresh_from_db()
        self.assertEqual(self.loan.status, LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        self.assertEqual(self.transaction.status, QrisTransactionStatus.PENDING)

    def test_case_success_then_pending_status(self):
        # do nothing if status already success
        self.transaction.status = QrisTransactionStatus.SUCCESS
        self.transaction.save()

        payload = {
            "serviceId": "EB_QRIS_STATUS",
            "amarbankAccount": "1513001959",
            "partnerCustomerID": self.linkage.to_partner_user_xid.hex,
            "timestamp": "2020-07-10 15:00:00.000",
            "statusCode": AmarCallbackConst.LoanDisbursement.PENDING_STATUS,
            "data": {
                "merchantName": "Toko satu",
                "merchantCity": "JAKARTA PUSAT",
                "merchantPan": "9360081702401979531",
                "transactionID": self.transaction.from_partner_transaction_xid,
                "customerPan": "9360053115011111111",
                "amount": 10000,
            },
        }

        process_callback_transaction_status_from_amar_task(
            payload=payload,
        )

        payload_history_exists = QrisPartnerTransactionHistory.objects.filter(
            qris_partner_transaction=self.transaction,
            field='partner_callback_payload',
            value_new=payload,
        ).exists()

        self.assertEqual(payload_history_exists, False)
        self.assertEqual(self.transaction.status, QrisTransactionStatus.SUCCESS)


class TestBulkUpdateAmarQrisTransactionStatus(TestCase):
    def setUp(self):
        self.partner_user = AuthUserFactory()
        self.partner = PartnerFactory(
            user=self.partner_user,
            name=PartnerNameConstant.AMAR,
        )

        self.customer = CustomerFactory()
        self.linkage = QrisPartnerLinkageFactory(
            status=QrisLinkageStatus.SUCCESS,
            customer_id=self.customer.id,
            partner_id=self.partner.id,
            partner_callback_payload={"any": "any"},
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
        )
        self.qris_transaction_method = TransactionMethodFactory.qris_1()
        self.loan_1 = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
            transaction_method_id=self.qris_transaction_method.id,
        )
        self.loan_2 = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
            transaction_method_id=self.qris_transaction_method.id,
        )
        self.transaction_1 = QrisPartnerTransactionFactory(
            loan_id=self.loan_1.id,
            status=QrisTransactionStatus.PENDING,
            qris_partner_linkage=self.linkage,
            from_partner_transaction_xid=uuid.uuid4().hex,
        )

        self.transaction_2 = QrisPartnerTransactionFactory(
            loan_id=self.loan_2.id,
            status=QrisTransactionStatus.PENDING,
            qris_partner_linkage=self.linkage,
            from_partner_transaction_xid=uuid.uuid4().hex,
        )

    @patch("juloserver.qris.tasks.julo_one_loan_disbursement_success")
    def test_bulk_process_callback_transaction_status_from_amar_task(
        self, mock_julo_one_disbursement
    ):
        loan_status_map = {self.loan_1.id: "success", self.loan_2.id: "failed"}

        bulk_process_callback_transaction_status_from_amar_task(
            loan_status_map=loan_status_map,
        )
        self.loan_1.refresh_from_db()
        self.loan_2.refresh_from_db()

        status_history_1_exists = QrisPartnerTransactionHistory.objects.filter(
            qris_partner_transaction=self.transaction_1,
            field='status',
            value_old='pending',
            value_new='success',
            change_reason='manually run via script',
        ).exists()

        self.assertEqual(status_history_1_exists, True)
        mock_julo_one_disbursement.assert_called_once_with(
            loan=self.loan_1,
        )

        status_history_2_exists = QrisPartnerTransactionHistory.objects.filter(
            qris_partner_transaction=self.transaction_2,
            field='status',
            value_old='pending',
            value_new='failed',
            change_reason='manually run via script',
        ).exists()

        self.assertEqual(status_history_2_exists, True)
        self.assertEqual(self.loan_2.status, LoanStatusCodes.TRANSACTION_FAILED)


class TestRedisQrisWhitelistTask(TestCase):
    def setUp(self):
        self.admin_user = AuthUserFactory()
        self.customer_1 = CustomerFactory()
        self.customer_2 = CustomerFactory()

        self.past_success_history_1 = RedisWhiteListUploadHistoryFactory(
            whitelist_name=RedisWhiteList.Name.QRIS_CUSTOMER_IDS_WHITELIST,
            cloud_storage=CloudStorage.OSS,
            status=RedisWhiteList.Status.WHITELIST_SUCCESS,
            is_latest_success=True,
        )

        self.past_success_history_2 = RedisWhiteListUploadHistoryFactory(
            whitelist_name=RedisWhiteList.Name.QRIS_CUSTOMER_IDS_WHITELIST,
            cloud_storage=CloudStorage.GCS,
            status=RedisWhiteList.Status.WHITELIST_SUCCESS,
            is_latest_success=True,
        )

    @patch("juloserver.qris.tasks.set_redis_ids_whitelist")
    @patch("juloserver.qris.tasks.get_file_from_oss")
    def test_retrieve_and_set_qris_redis_whitelist_csv(self, mock_get_file_oss, mock_set_redis):
        history = RedisWhiteListUploadHistoryFactory(
            whitelist_name=RedisWhiteList.Name.QRIS_CUSTOMER_IDS_WHITELIST,
            cloud_storage=CloudStorage.OSS,
            status=RedisWhiteList.Status.UPLOAD_SUCCESS,
        )
        csv_content = f"customer_id\n{self.customer_1.id}\n{self.customer_2.id}"
        csv_content_bytes = csv_content.encode()
        csv_stream = io.BytesIO(csv_content_bytes)

        mock_get_file_oss.return_value = csv_stream
        expected_redis_return_value = 2
        mock_set_redis.return_value = expected_redis_return_value

        retrieve_and_set_qris_redis_whitelist_csv()

        history.refresh_from_db()

        mock_set_redis.assert_called_once_with(
            ids=ANY,
            key=RedisWhiteList.Key.SET_QRIS_WHITELISTED_CUSTOMER_IDS,
            temp_key=RedisWhiteList.Key.TEMP_SET_QRIS_WHITELISTED_CUSTOMER_IDS,
        )

        self.assertEqual(history.status, RedisWhiteList.Status.WHITELIST_SUCCESS)
        self.assertEqual(history.len_ids, expected_redis_return_value)
        self.assertEqual(history.is_latest_success, True)

        # only one latest success
        success_count = RedisWhiteListUploadHistory.objects.filter(
            whitelist_name=RedisWhiteList.Name.QRIS_CUSTOMER_IDS_WHITELIST,
            is_latest_success=True,
        ).count()

        self.assertEqual(success_count, 1)
