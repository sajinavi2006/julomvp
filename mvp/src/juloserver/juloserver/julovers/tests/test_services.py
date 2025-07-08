import csv
import io
from unittest.mock import patch

from django.conf import settings
from django.core.files import File
from django.test.testcases import TestCase

from juloserver.account.constants import AccountConstant, CreditMatrixType, TransactionType
from juloserver.account.models import CurrentCreditMatrix
from juloserver.account.services.credit_limit import calculate_credit_limit
from juloserver.account.tests.factories import AccountFactory
from juloserver.apiv2.tests.test_apiv2_services import StatusLookupFactory
from juloserver.julo.constants import (
    UploadAsyncStateStatus,
    UploadAsyncStateType,
    WorkflowConst,
)
from juloserver.julo.models import (
    UploadAsyncState,
    Application,
    ApplicationHistory,
)
from juloserver.julo.banks import BankManager
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import process_loan_status_change
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CustomerFactory,
    LoanFactory,
    PartnerFactory,
    ProductLineFactory,
    ProductLookupFactory,
    WorkflowFactory,
    AppVersionFactory,
)
from juloserver.julovers.constants import JuloverPageConst
from juloserver.julovers.models import Julovers
from juloserver.julovers.tasks import (
    process_julovers_task,
    sync_julover_to_application,
)
from juloserver.julovers.tests.factories import (
    JuloverPageFactory,
    UploadAsyncStateFactory,
    JuloverFactory,
    JuloversProductLineFactory,
    WorkflowStatusPathFactory,
)
from juloserver.julovers.services.core_services import (
    contruct_params_from_set_limit_for_julover,
    JuloverPageMapping,
)
from juloserver.julovers.exceptions import JuloverPageNotFound
from django.contrib.auth.models import (
    Group,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles

HEADER = [
    'fullname', 'email', 'address', 'birth_place', 'dob', 'mobile_phone_number',
    'gender', 'marital_status', 'job_industry', 'job_description', 'job_type',
    'job_start', 'bank_name', 'bank_account_number', 'name_in_bank', 'resign_date',
    'set_limit', 'real_nik'
]


class TestProcessJuloversTask(TestCase):
    def setUp(self):
        self.application = ApplicationFactory(mobile_phone_1='081977920287')
        self.application_2 = ApplicationFactory(email='william@julofinance.com')
        self.data = [
            HEADER,
            [
                'Yogi Surya Dinata', 'yogi@julo.co.id',
                'BSD, Tangerang Selatan, Banten', 'Bandar Lampung', '30/12/1991', '081977920287',
                'Pria', 'Lajang', 'Product', 'Senior Product Manager', 'Pengawai swasta',
                '05/06/2017', 'BCA', '200838289', 'YOGI ISWANTELLY SURYA DI', '', '20,000,000',
                '1871023012910003'
            ],
            [
                'William Tjeng', 'william@julofinance.com',
                'Cikupa Jalan Bhumimas 1 No.5', 'Jakarta', '18/08/1980', '081280527576',
                'Pria', 'Lajang', 'Product', 'Associate Product Manager', 'Pengawai negeri',
                '23/11/2021', 'BCA', '709932355', 'William', '', '15,000,000',
                '3603180610990003'
            ],
            [
                'Grady Richata', 'grady.richata@julofinance.com',
                'Bandung, road 123', '', '18/08/1980', '08123452889',
                'Pria', 'Lajang', 'Product', 'Group Product Manager', 'Pengawai swasta',
                '15/11/2021', 'BCA', '90248000', 'Grady Richata', '18/08/2022', '10,000,000',
                '3273073001820002'
            ]
        ]
        self.partner = PartnerFactory.mock_julover()

    def test_process_julovers_task_not_found_and_exception(self):
        process_julovers_task(100)
        self.assertEqual(UploadAsyncState.objects.all().count(), 0)

    @patch('juloserver.julovers.services.core_services.upload_file_to_oss')
    @patch.object(BankManager, 'get_by_name_or_none')
    def test_process_julovers_task(self, mock_bank_validate, mock_upload_csv_data_to_oss):
        mock_bank_validate.return_value = 'BANK CENTRAL ASIA, Tbk (BCA)'
        upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.JULOVERS
        )
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(self.data)
        upload = File(output, name='employee_data.csv')
        upload_async_state.file.save(
            upload_async_state.full_upload_name(upload.name), upload
        )
        # no 1 => duplicate phone number
        # no 2 => duplicate email
        # no 3 => success
        process_julovers_task(upload_async_state.id)
        self.assertEqual(Julovers.objects.all().count(), 1)
        upload_async_state = UploadAsyncState.objects.filter(id=upload_async_state.id).first()
        self.assertEqual(upload_async_state.task_status, UploadAsyncStateStatus.PARTIAL_COMPLETED)
        self.assertEqual(upload_async_state.error_detail, "Data invalid please check")

    @patch('juloserver.julovers.services.core_services.upload_file_to_oss')
    @patch.object(BankManager, 'get_by_name_or_none')
    def test_process_julovers_task_invalid_data(self, mock_validate_bank, mock_upload_csv_data_to_oss):
        mock_validate_bank.return_value = 'BANK CENTRAL ASIA, Tbk (BCA)'
        # case invalid date
        self.data.append([
            'Grady Richata', 'grady.richata@julofinance.com',
            'Bandung, road 123', '', 'invalid date', '08123452889',
            'Pria', 'Lajang', 'Product', 'Group Product Manager', 'Pengawai swasta',
            '15/11/2021', 'BCA', '90248000', 'Grady Richata', '', '10,000,000', '1871023012910003'
        ])
        self.data.append([
            'Nam', 'nam@julofinance.com',
            'Bandung, road 123', '', '1/1/2022', '08123452889',
            'Pria', 'Lajang', 'backend', 'Group backend Vietnam', 'Pengawai swasta',
            '15/11/2021', 'BCA', '90248000', 'Nam', '', '10,000,000@@#!', '3273073001820002'
        ])
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(self.data)
        upload = File(output, name='employee_data_2.csv')
        upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.JULOVERS,
        )
        upload_async_state.file.save(
            upload_async_state.full_upload_name(upload.name), upload
        )
        process_julovers_task(upload_async_state.id)
        self.assertEqual(Julovers.objects.all().count(), 1)
        upload_async_state = UploadAsyncState.objects.filter(id=upload_async_state.id).first()
        self.assertEqual(upload_async_state.task_status, UploadAsyncStateStatus.PARTIAL_COMPLETED)


class TestProcessJuloverToApplication(TestCase):
    def setUp(self):
        self.julover = JuloverFactory()
        self.julovers_workflow = WorkflowFactory(
            name=WorkflowConst.JULOVER,
        )
        self.product_line = JuloversProductLineFactory()
        self.work_flow_status_path = WorkflowStatusPathFactory(
            status_previous=0, status_next=105, type='happy', is_active=True,
            workflow=self.julovers_workflow,
        )
        self.app_version = AppVersionFactory(status='latest', app_version='6.1.0')
        self.partner = PartnerFactory.mock_julover()


    def test_process_julover_to_application_at_x100(self):
        sync_julover_to_application(self.julover.id, self.partner.id)
        application = Application.objects.first()
        self.assertIsNotNone(application)
        julover = Julovers.objects.get(id=self.julover.id)
        self.assertTrue(julover.is_sync_application)
        application_history = ApplicationHistory.objects.filter(
            application_id=application.id, status_old=0, status_new=105
        )
        self.assertIsNotNone(application_history)


class TestJuloverServices(TestCase):
    def setUp(self):
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.JULOVER,
            product_line_type='JULOVER',
            min_amount=300000,
            max_amount=20000000,
            min_duration=1,
            max_duration=4,
            min_interest_rate=0,
            max_interest_rate=0,
            payment_frequency='Monthly',
        )
        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line,
        )
        self.credit_matrix = CreditMatrixFactory(
            min_threshold=0,
            max_threshold=1,
            score_tag='A : 0 - 1',
            is_premium_area=True,
            credit_matrix_type=CreditMatrixType.JULOVER,
            is_salaried=True,
            transaction_type=TransactionType.SELF,
            product=self.product_lookup,
        )
        CurrentCreditMatrix.objects.create(
            transaction_type=TransactionType.SELF,
            credit_matrix=self.credit_matrix,
        )
        self.matrix_product_line = CreditMatrixProductLineFactory(
            interest=0,
            min_loan_amount=300000,
            max_loan_amount=20000000,
            max_duration=4,
            min_duration=1,
            product=self.product_line,
        )
        self.partner = PartnerFactory.mock_julover()

    def test_construct_params_from_set_limit(self):
        set_limit = 12000000
        params = contruct_params_from_set_limit_for_julover(set_limit)
        affordability = params['affordability_value']

        rs = calculate_credit_limit(
            credit_matrix_product_line=self.matrix_product_line,
            affordability_value=affordability,
            limit_adjustment_factor=AccountConstant.CREDIT_LIMIT_ADJUSTMENT_FACTOR_GTE_PGOOD_CUTOFF,
        )
        self.assertEqual(set_limit, rs['set_limit'])

    def test_email_content_at_190(self):
        page = JuloverPageFactory.email_at_190()
        app = ApplicationFactory()
        app.fullname = 'peter parker'
        app.mobile_phone_1 = '314159265359'
        JuloverFactory(
            email=app.email,
            set_limit=5000,
        )
        page.content = "{set_limit}{email}{first_name}{reset_link}{mobile_phone_number}"
        page.content += "{full_name}{job_description}{bank_account_number}{dob}"
        page.extra_data = {'title': "You know nothing, Jon Snow..."}
        page.save()
        subject_title, content = JuloverPageMapping.get_julover_page_content(
            title=JuloverPageConst.EMAIL_AT_190,
            application=app,
            reset_pin_key='Rosebud',
        )
        link = settings.RESET_PIN_JULO_ONE_LINK_HOST + 'Rosebud' + '/' + '?julover=true'
        self.assertEqual(subject_title, "You know nothing, Jon Snow...")
        self.assertIn(
            f"Rp 5.000{app.email}Peter{link}314159265359" +
            f"{app.full_name_only}{app.job_description}{app.bank_account_number}{app.dob}",
            content,
        )

    def test_get_julover_page_content(self):
        app = ApplicationFactory()
        with self.assertRaises(JuloverPageNotFound):
            JuloverPageMapping.get_julover_page_content(
                application=app,
                title="Here's Johnny!"
            )


class TestLoanProcess(TestCase):
    def setUp(self) -> None:
        self.partner = PartnerFactory.mock_julover()
        self.customer = CustomerFactory()
        self.product_line = ProductLineFactory.julover()
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            partner=self.partner,
            product_line=self.product_line,
            account=self.account,
        )
        self.start_status = StatusLookupFactory()
        self.start_status.status_code = LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING
        self.start_status.save()
        self.loan = LoanFactory(
            customer=self.customer,
            application=self.application,
            loan_status=self.start_status,
        )
        self.agent = AuthUserFactory()
        self.group = Group.objects.create(name=JuloUserRoles.BO_DATA_VERIFIER)
        self.agent.groups.add(self.group)

    @patch('juloserver.loan.services.loan_related.update_loan_status_and_loan_history')
    def test_process_loan_status_change_at_216(self, mock_update_loan_status):
        process_loan_status_change(
            loan_id=self.loan.id,
            new_status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER,
            change_reason='This is a test Julo deserves, but not one it needs right now',
            user=self.agent,
        )
        mock_update_loan_status.assert_called_once()
