import mock

from django.test.testcases import TestCase

from juloserver.merchant_financing.tasks import upload_axiata_disbursement_and_repayment_data_to_oss
from mock import patch
from juloserver.account.tests.factories import (
    AccountFactory
)
from juloserver.julo.tests.factories import (
    CustomerFactory,
    PartnerFactory,
    AuthUserFactory,
    ApplicationFactory,
    StatusLookupFactory
)
from juloserver.merchant_financing.tasks import (
    upload_axiata_disbursement_and_repayment_data_to_oss,
    process_merchant_financing_disbursement
)
from juloserver.julovers.tests.factories import (
    UploadAsyncStateFactory
)
from juloserver.julo.constants import (
    UploadAsyncStateStatus,
    UploadAsyncStateType
)
from juloserver.merchant_financing.constants import AxiataReportType

from juloserver.julo.models import Document, UploadAsyncState


class TestAxiataDailyReport(TestCase):

    @mock.patch('juloserver.merchant_financing.tasks.upload_file_to_oss')
    @mock.patch('juloserver.merchant_financing.tasks.get_axiata_repayment_data')
    @mock.patch('juloserver.merchant_financing.tasks.get_axiata_disbursement_data')
    def test_upload_report_disbursement_and_repayment(self, mock_get_axiata_disbursement_data,
                                                      mock_get_axiata_repayment_data,
                                                      mock_upload_file_to_oss):
        mock_get_axiata_disbursement_data.return_value = [
            ('2022-01-19 16:17:02.815',
             '103296688',
             'ANI',
             'ADIL MAKMUR',
             '3525135006111111',
             '081390322222',
             'PT Adil Makmur',
             3300000,
             3300000,
             'Disbursed',
             '2022-01-18',
             '2022-01-18 14:51:00',
             '2022-01-18 14:51:00',
             '357813000300555555',
             'JULO',
             '2022-01-18',
             3300000,
             10000,
             500)
        ]
        mock_get_axiata_repayment_data.return_value = [
            ('2022-01-19 16:17:02.815',
             '103296688',
             0,
             1,
             '0',
             '2022-02-01',
             None,
             None,
             -13,
             49500,
             0,
             '081390322222',
             'ANI',
             'ADIL MAKMUR',
             'PT Adil Makmur',
             3300000,
             3349500,
             0,
             'Payment not due',
             'Bank BCA',
             '1099408139999998',
             'JULO')
        ]
        upload_axiata_disbursement_and_repayment_data_to_oss()

        documents = Document.objects.all()
        self.assertIsNotNone(documents.filter(document_type=AxiataReportType.REPAYMENT).last())
        self.assertIsNotNone(documents.filter(document_type=AxiataReportType.DISBURSEMENT).last())


class TestMFDisbursementProcess(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory(username='rabando')
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer,
                                      status=StatusLookupFactory(status_code=420))
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            application_xid=9999999880,
        )
        self.partner = PartnerFactory(
            user=self.user, is_active=True,
            name="Rabando"
        )
        self.upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.MERCHANT_FINANCING_DISBURSEMENT,
            service = 'oss',
            file="test.csv"
        )

    @patch('juloserver.merchant_financing.tasks.logger')
    def test_process_merchant_financing_disbursement_with_no_upload_async_state(self, mock_logger) -> None:
        process_merchant_financing_disbursement(13453, self.partner.id)
        mock_logger.info.assert_called_once_with(
            {
                "action": "process_merchant_financing_disbursement",
                "message": "File not found",
                "upload_async_state_id": 13453,
            }
        )

    @mock.patch('juloserver.merchant_financing.services.disburse_mf_upload')
    def test_process_merchant_financing_disbursement_fail(
            self, mock_disburse_mf_upload
    ) -> None:
        mock_disburse_mf_upload.return_value = False
        process_merchant_financing_disbursement(self.upload_async_state.id, self.partner.id)
        self.assertEqual(1, UploadAsyncState.objects.filter(
            id=self.upload_async_state.id,
            task_status=UploadAsyncStateStatus.PARTIAL_COMPLETED).count())

    @mock.patch('juloserver.merchant_financing.services.disburse_mf_upload')
    def test_process_merchant_financing_disbursement_success(
            self, mock_disburse_mf_upload
    ) -> None:
        mock_disburse_mf_upload.return_value = True
        process_merchant_financing_disbursement(self.upload_async_state.id, self.partner.id)
        self.assertEqual(1, UploadAsyncState.objects.filter(
            id=self.upload_async_state.id,
            task_status=UploadAsyncStateStatus.COMPLETED).count())
