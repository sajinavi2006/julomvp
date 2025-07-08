import base64
from django.utils import timezone
from babel.dates import format_date
from django.test import TestCase
from unittest.mock import patch
from datetime import datetime
from dateutil.relativedelta import relativedelta
from django.core.files.uploadedfile import SimpleUploadedFile
from mock import ANY

from juloserver.followthemoney.models import LoanAgreementTemplate
from juloserver.julo.exceptions import JuloException
from juloserver.qris.serializers import UploadImageSerializer
from juloserver.julo.models import Image
from juloserver.qris.models import (
    QrisLinkageLenderAgreement,
    QrisPartnerLinkage,
    QrisPartnerLinkageHistory,
    QrisUserState,
    QrisPartnerTransaction,
    QrisTransactionStatus,
)
from juloserver.qris.services.user_related import (
    QrisUploadSignatureService,
    create_signature_image,
    get_master_agreement_html,
    QrisListTransactionService,
    get_qris_skrtp_agreement_html,
)
from juloserver.julo.tests.factories import (
    CustomerFactory,
    PartnerFactory,
    AuthUserFactory,
    ImageFactory,
    ApplicationFactory,
    MasterAgreementTemplateFactory,
    LoanFactory,
    StatusLookupFactory,
    ProductLineFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.followthemoney.factories import LenderCurrentFactory
from juloserver.portal.object.loan_app.constants import ImageUploadType
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo_financing.services.core_services import JFinancingSignatureService
from juloserver.qris.tasks import upload_qris_signature_and_master_agreement_task
from juloserver.followthemoney.constants import (
    LoanAgreementType,
    MasterAgreementTemplateName,
    LenderName,
)
from juloserver.qris.exceptions import QrisLinkageNotFound
from juloserver.qris.constants import QrisLinkageStatus, QrisTransactionStatus
from juloserver.julo.constants import LoanStatusCodes
from juloserver.followthemoney.tasks import generate_julo_one_loan_agreement
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.loan.constants import TransactionMethodCode
from juloserver.julo.constants import ProductLineCodes
from juloserver.qris.tests.factories import QrisPartnerLinkageFactory


class TestQrisUploadSignatureService(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.partner = PartnerFactory(name=PartnerNameConstant.AMAR, user=self.user_auth)
        self.image = ImageFactory(image_type=ImageUploadType.QRIS_SIGNATURE)
        self.signature_image_data = {'data': 'test_image.jpg', 'upload': b'fake_image_content'}

        self.lender = LenderCurrentFactory(
            lender_name=LenderName.BLUEFINC,
        )
        self.lender2 = LenderCurrentFactory(
            lender_name=LenderName.JTP,
        )

    @patch('juloserver.qris.services.user_related.create_signature_image')
    @patch('juloserver.qris.services.user_related.execute_after_transaction_safely')
    def test_process_linkage_and_upload_signature(self, mock_execute, mock_create_signature):
        # Mock the create_signature_image function
        image_id = self.image.id
        mock_create_signature.return_value = image_id

        service = QrisUploadSignatureService(
            customer=self.customer,
            signature_image_data=self.signature_image_data,
            partner=self.partner,
            lender=self.lender,
        )
        service.process_linkage_and_upload_signature()

        # following records should be created
        qris_linkage = QrisPartnerLinkage.objects.get(customer_id=self.customer.id)
        qris_user_state = QrisUserState.objects.get(qris_partner_linkage=qris_linkage)
        qris_linkage_agreement = QrisLinkageLenderAgreement.objects.get(
            qris_partner_linkage=qris_linkage
        )
        # since first time, linkage created
        qris_linkage_history = QrisPartnerLinkageHistory.objects.filter(
            qris_partner_linkage=qris_linkage
        ).last()

        mock_create_signature.assert_called_once_with(
            image_type=ImageUploadType.QRIS_SIGNATURE,
            image_source_id=qris_linkage.id,
            input_data=self.signature_image_data,
        )
        self.assertEqual(qris_linkage.partner_id, self.partner.id)
        self.assertEqual(qris_user_state.qris_partner_linkage_id, qris_linkage.id)
        self.assertEqual(qris_user_state.signature_image_id, image_id)
        self.assertEqual(qris_linkage_agreement.qris_partner_linkage_id, qris_linkage.id)
        self.assertEqual(qris_linkage_agreement.signature_image_id, image_id)
        self.assertEqual(qris_linkage_history.value_new, QrisLinkageStatus.REQUESTED)
        self.assertEqual(qris_linkage_history.value_old, "")

        # Assert that execute_after_transaction_safely was called
        mock_execute.assert_called_once()
        positional_args = mock_execute.call_args[0]
        task_call = positional_args[0]
        self.assertTrue(callable(task_call))

        # Call the task function to ensure it's correctly formed
        with patch(
            'juloserver.qris.services.user_related.upload_qris_signature_and_master_agreement_task'
        ) as mock_task:
            task_call()
            mock_task.delay.assert_called_once_with(
                qris_lender_agreement_id=qris_linkage_agreement.id,
            )

    @patch('juloserver.qris.services.user_related.create_signature_image')
    @patch('juloserver.qris.services.user_related.execute_after_transaction_safely')
    def test_process_linkage_and_upload_signature_non_first_time(
        self, mock_execute, mock_create_signature
    ):
        """
        Test sign with existing linkage
        """
        linkage = QrisPartnerLinkageFactory(
            customer_id=self.customer.id,
            partner_id=self.partner.id,
            status=QrisLinkageStatus.SUCCESS,
        )
        # Mock the create_signature_image function
        image_id = self.image.id
        mock_create_signature.return_value = image_id

        service = QrisUploadSignatureService(
            customer=self.customer,
            signature_image_data=self.signature_image_data,
            partner=self.partner,
            lender=self.lender,
        )
        service.process_linkage_and_upload_signature()

        # following records should be recreated
        qris_linkage = QrisPartnerLinkage.objects.get(customer_id=self.customer.id)
        qris_user_state = QrisUserState.objects.get(qris_partner_linkage=qris_linkage)
        qris_linkage_agreement = QrisLinkageLenderAgreement.objects.get(
            qris_partner_linkage=qris_linkage
        )

        # linkage exists, won't create new history
        newly_created_qris_linkage_history = QrisPartnerLinkageHistory.objects.filter(
            qris_partner_linkage=qris_linkage,
            value_old="",
            value_new=QrisLinkageStatus.REQUESTED,
        ).last()
        self.assertIsNone(newly_created_qris_linkage_history)

        mock_create_signature.assert_called_once_with(
            image_type=ImageUploadType.QRIS_SIGNATURE,
            image_source_id=qris_linkage.id,
            input_data=self.signature_image_data,
        )
        self.assertEqual(qris_linkage.id, linkage.id)
        self.assertEqual(qris_linkage.partner_id, self.partner.id)
        self.assertEqual(qris_user_state.qris_partner_linkage_id, qris_linkage.id)
        self.assertEqual(qris_user_state.signature_image_id, image_id)
        self.assertEqual(qris_linkage_agreement.qris_partner_linkage_id, qris_linkage.id)
        self.assertEqual(qris_linkage_agreement.signature_image_id, image_id)

        # Assert that execute_after_transaction_safely was called
        mock_execute.assert_called_once()
        positional_args = mock_execute.call_args[0]
        task_call = positional_args[0]
        self.assertTrue(callable(task_call))

        # Call the task function to ensure it's correctly formed
        with patch(
            'juloserver.qris.services.user_related.upload_qris_signature_and_master_agreement_task'
        ) as mock_task:
            task_call()
            mock_task.delay.assert_called_once_with(
                qris_lender_agreement_id=qris_linkage_agreement.id,
            )

class TestCreateSignatureImage(TestCase):
    def setUp(self):
        self.fake_image = SimpleUploadedFile(
            name='test_image.png',
            content=base64.b64decode(
                'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAACklEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg=='
            ),
            content_type='image/png',
        )

    def test_create_signature_image(self):
        # Arrange
        image_type = ImageUploadType.QRIS_SIGNATURE
        image_source_id = 123

        # Create input data
        name_image = 'test_image'
        input_data = UploadImageSerializer(
            data={'data': name_image + '.png', 'upload': self.fake_image}
        )
        self.assertTrue(input_data.is_valid())

        # act
        image_id = create_signature_image(image_type, image_source_id, input_data.validated_data)

        # assert
        self.assertIsNotNone(image_id)
        created_image = Image.objects.get(id=image_id)
        self.assertEqual(created_image.image_type, image_type)
        self.assertEqual(created_image.image_source, image_source_id)
        self.assertTrue(name_image in created_image.image.name)

    def tearDown(self):
        self.fake_image.close()


class TestUploadQrisSignatureAndMasterAgreement(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.image = ImageFactory(image_type=ImageUploadType.QRIS_SIGNATURE)
        self.customer = CustomerFactory(user=self.user_auth)
        self.partner = PartnerFactory(name=PartnerNameConstant.AMAR, user=self.user_auth)
        self.linkage = QrisPartnerLinkage.objects.create(
            customer_id=self.customer.id,
            partner_id=self.partner.id,
        )
        self.lender = LenderCurrentFactory(
            lender_name=LenderName.BLUEFINC,
        )
        self.qris_user_state = QrisUserState.objects.create(
            qris_partner_linkage=self.linkage,
            signature_image=self.image,
        )
        self.qris_linkage_lender_agreement = QrisLinkageLenderAgreement.objects.create(
            qris_partner_linkage=self.linkage,
            lender_id=self.lender.id,
            signature_image_id=self.image.id,
        )

    @patch.object(JFinancingSignatureService, 'upload_jfinancing_signature_image')
    @patch('juloserver.qris.tasks.generate_qris_master_agreement_task')
    def test_upload_qris_signature_and_master_agreement(
        self, mock_generate_master_agreement, mock_upload_signature
    ):
        upload_qris_signature_and_master_agreement_task(
            qris_lender_agreement_id=self.qris_linkage_lender_agreement.id,
        )
        mock_generate_master_agreement.delay.assert_called_once_with(
            self.qris_linkage_lender_agreement.id
        )


class TestGetMasterAgreementHtml(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.image = ImageFactory(image_type=ImageUploadType.QRIS_SIGNATURE)
        self.lender = LenderCurrentFactory(lender_name=LenderName.BLUEFINC)
        self.paramteters_body = 'Test'
        self.master_agreement_template = MasterAgreementTemplateFactory(
            product_name=MasterAgreementTemplateName.QRIS_J1,
            is_active=False,
            parameters=self.paramteters_body,
        )

    @patch('juloserver.qris.services.user_related.timezone')
    @patch('juloserver.qris.services.user_related.render_to_string')
    def test_get_master_agreement_html_template(self, mock_render_to_string, mock_timezone):
        # Arrange
        expected_date = timezone.datetime(2024, 1, 1)
        mock_timezone.localtime.return_value = expected_date
        hash_digi_sign = "PPFP-" + str(self.application.application_xid)
        context = {
            "hash_digi_sign": hash_digi_sign,
            "signed_date": format_date(expected_date, 'd MMMM yyyy', locale='id_ID'),
            "application": self.application,
            "dob": format_date(self.application.dob, 'dd-MM-yyyy', locale='id_ID'),
            "lender": self.lender,
            "qris_signature": "",
        }
        # Act
        get_master_agreement_html(
            application=self.application,
            lender=self.lender,
        )

        # Assert
        mock_render_to_string.assert_called_with(
            'loan_agreement/qris_master_agreement.html', context=context
        )

        # existing signature image
        context['qris_signature'] = self.image.thumbnail_url_api
        get_master_agreement_html(self.application, self.lender, self.image)
        mock_render_to_string.assert_called_with(
            'loan_agreement/qris_master_agreement.html', context=context
        )

    @patch('juloserver.qris.services.user_related.render_to_string')
    def test_get_master_agreement_html_with_db_template(self, mock_render_to_string):
        # Arrange
        self.master_agreement_template.is_active = True
        self.master_agreement_template.save()
        # Act
        result = get_master_agreement_html(self.application, lender=self.lender)
        # Assert
        self.assertEqual(result, self.paramteters_body)
        mock_render_to_string.assert_not_called()


class TestQrisListTransactionService(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.partner = PartnerFactory(user=self.user)
        self.service = QrisListTransactionService(self.customer.pk, self.partner.pk)

        # Create test data
        self.linkage = QrisPartnerLinkage.objects.create(
            customer_id=self.customer.pk,
            partner_id=self.partner.pk,
            status=QrisLinkageStatus.SUCCESS,
        )

        self.now = datetime(2024, 11, 4, 16, 0, 0)
        self.transaction_c = QrisPartnerTransaction.objects.create(
            id=1,
            qris_partner_linkage=self.linkage,
            total_amount=30000,
            merchant_name='Merchant C',
            status=QrisTransactionStatus.SUCCESS,
            loan_id=1,
        )
        self.transaction_c.cdate = self.now - relativedelta(months=2)
        self.transaction_c.save()

        self.transaction_b = QrisPartnerTransaction.objects.create(
            id=2,
            qris_partner_linkage=self.linkage,
            total_amount=20000,
            merchant_name='Merchant B',
            status=QrisTransactionStatus.SUCCESS,
            loan_id=2,
        )
        self.transaction_b.cdate = self.now - relativedelta(days=1)
        self.transaction_b.save()

        self.transaction_a = QrisPartnerTransaction.objects.create(
            id=3,
            qris_partner_linkage=self.linkage,
            total_amount=10000,
            merchant_name='Merchant A',
            status=QrisTransactionStatus.SUCCESS,
            loan_id=3,
        )
        self.transaction_a.cdate = self.now
        self.transaction_a.save()

    def test_get_qris_partner_linkage(self):
        result = self.service._get_qris_partner_linkage()
        self.assertEqual(result, self.linkage)

    @patch('juloserver.qris.services.user_related.timezone')
    def test_get_qris_partner_transactions(self, mock_timezone):
        mock_timezone.localtime.return_value = self.now
        result = self.service._get_qris_partner_transactions(self.linkage, limit=2)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['total_amount'], self.transaction_a.total_amount)
        self.assertEqual(result[1]['total_amount'], self.transaction_b.total_amount)
        result = self.service._get_qris_partner_transactions(self.linkage, limit=0)
        self.assertEqual(len(result), 3)

    @patch('juloserver.qris.services.user_related.timezone')
    def test_get_successful_transaction(self, mock_timezone):
        mock_timezone.localtime.return_value = self.now
        result = self.service.get_successful_transaction()

        expected_month_year = self.now.strftime('%m-%Y')
        expected_month_year_c = (self.now - relativedelta(months=2)).strftime('%m-%Y')
        self.assertIn(expected_month_year, result[0]['date'])
        self.assertEqual(len(result[0]['transactions']), 2)
        self.assertIn(expected_month_year_c, result[1]['date'])
        self.assertEqual(len(result[1]['transactions']), 1)

        # Check the first transaction
        self.assertEqual(result[0]['transactions'][0]['merchant_name'], 'Merchant A')
        self.assertEqual(
            result[0]['transactions'][0]['transaction_date'], self.now.strftime('%d-%m-%Y')
        )
        self.assertTrue(result[0]['transactions'][0]['amount'].startswith('Rp'))

        # Check the second transaction
        self.assertEqual(result[0]['transactions'][1]['merchant_name'], 'Merchant B')
        self.assertEqual(
            result[0]['transactions'][1]['transaction_date'],
            (self.now - relativedelta(days=1)).strftime('%d-%m-%Y'),
        )
        self.assertTrue(result[0]['transactions'][1]['amount'].startswith('Rp'))

    def test_get_successful_transaction_no_linkage(self):
        self.linkage.status = QrisLinkageStatus.FAILED
        self.linkage.save()
        with self.assertRaises(QrisLinkageNotFound):
            self.service.get_successful_transaction()

    def test_get_successful_transaction_no_transactions(self):
        QrisPartnerTransaction.objects.all().delete()
        result = self.service.get_successful_transaction()
        self.assertEqual(result, [])


class TestGetQrisSKRTPAgreementHtml(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.partner = PartnerFactory(name=PartnerNameConstant.AMAR, user=self.user_auth)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.image = ImageFactory(image_type=ImageUploadType.QRIS_SIGNATURE)
        self.lender = LenderCurrentFactory(lender_name=LenderName.JTP)
        self.transaction_method = TransactionMethodFactory(
            id=TransactionMethodCode.QRIS_1.code,
            method=TransactionMethodCode.QRIS_1,
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL),
            transaction_method=self.transaction_method,
        )
        self.qris_partner_linkage = QrisPartnerLinkage.objects.create(
            customer_id=self.customer.id,
            partner_id=self.partner.id,
        )
        self.qris_user_state = QrisUserState.objects.create(
            qris_partner_linkage=self.qris_partner_linkage,
            signature_image=self.image,
        )
        self.qris_partner_transaction = QrisPartnerTransaction.objects.create(
            loan_id=self.loan.id,
            qris_partner_linkage_id=self.qris_partner_linkage.id,
        )

    def test_get_qris_skrtp_agreement(self):
        result = get_qris_skrtp_agreement_html(self.loan, self.application)
        self.assertIsNotNone(result)

    @patch('juloserver.qris.services.user_related.render_to_string')
    def test_context_transaction_date_not_yet_disbursed(self, mock_render_to_string):
        creation_time = datetime.strptime("25/11/2023 15:00:00", "%d/%m/%Y %H:%M:%S")

        self.loan.cdate = creation_time
        self.loan.fund_transfer_ts = None
        self.loan.save()

        # remove all templates
        LoanAgreementTemplate.objects.filter(
            agreement_type=LoanAgreementType.QRIS_SKRTP,
        ).delete()

        # call func
        get_qris_skrtp_agreement_html(self.loan, self.application)

        mock_render_to_string.assert_called_once()
        _, kwargs = mock_render_to_string.call_args

        expected_transaction_time = '25 November 2023'

        context = kwargs['context']
        self.assertEqual(context['transaction_date'], expected_transaction_time)

    @patch('juloserver.qris.services.user_related.render_to_string')
    def test_context_transaction_date_disbursed_loan(self, mock_render_to_string):
        disbursed_time = datetime.strptime("28/11/2023 15:00:00", "%d/%m/%Y %H:%M:%S")

        self.loan.loan_status_id = 220
        self.loan.fund_transfer_ts = disbursed_time
        self.loan.save()

        # remove all templates
        LoanAgreementTemplate.objects.filter(
            agreement_type=LoanAgreementType.QRIS_SKRTP,
        ).delete()

        # call func
        get_qris_skrtp_agreement_html(self.loan, self.application)

        mock_render_to_string.assert_called_once()
        _, kwargs = mock_render_to_string.call_args

        expected_transaction_time = '28 November 2023'

        context = kwargs['context']
        self.assertEqual(context['transaction_date'], expected_transaction_time)

    @patch('juloserver.followthemoney.tasks.pdfkit.from_string')
    @patch('juloserver.followthemoney.tasks.generate_qris_skrtp_julo')
    @patch('juloserver.loan.services.agreement_related.get_qris_skrtp_agreement_html')
    def test_generate_skrtp_agreement(
        self, mock_get_qris_skrtp_agreement_html, mock_generate_qris_skrtp_julo, mock_pdfkit
    ):
        generate_julo_one_loan_agreement(self.loan.id)
        mock_get_qris_skrtp_agreement_html.assert_called_once_with(self.loan, self.application)
        mock_generate_qris_skrtp_julo.assert_called()
