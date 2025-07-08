from builtins import str
from django.test import TestCase, override_settings
import json
from django.utils import timezone
from rest_framework.test import APIClient
from mock import patch, MagicMock, mock
from datetime import timedelta
from rest_framework import status
from datetime import datetime

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.collection_vendor.models import AgentAssignment
from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.julo.tests.factories import CrmSettingFactory
from juloserver.julo.tests.factories import LoanFactory
from juloserver.julo.tests.factories import ApplicationFactory
from juloserver.julo.tests.factories import PaymentFactory
from juloserver.julo.tests.factories import CustomerFactory

from juloserver.collection_vendor.tests.factories import CollectionVendorFactory, VendorRecordingDetailFactory
from juloserver.collection_vendor.tests.factories import CollectionVendorAssignmentTransferFactory
from juloserver.collection_vendor.tests.factories import CollectionVendorAssigmentTransferTypeFactory
from juloserver.collection_vendor.tests.factories import AgentAssignmentFactory
from juloserver.collection_vendor.tests.factories import SubBucketFactory
from juloserver.collection_vendor.tests.factories import CollectionVendorAssignmentFactory
from juloserver.collection_vendor.tests.factories import CollectionVendorAssignmentExtensionFactory
from juloserver.collection_vendor.tests.factories import UploadVendorReportFactory
from juloserver.collection_vendor.tests.factories import VendorReportErrorInformationFactory
from django.contrib.auth.models import Group


class TestCollectionVendorData(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)

    def test_collection_vendor_data(self):
        res = self.client.get('/collection_vendor/collection_vendor_data')
        assert res.status_code == 200


class TestCollectionVendorForm(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.crm_setting = CrmSettingFactory(user=self.user)
        self.collection_vendor = CollectionVendorFactory(last_updated_by=self.user,
                                                         vendor_name='test_vendor_name')
        self.collection_vendor_1 = CollectionVendorFactory(last_updated_by=self.user,
                                                         vendor_name='test123')

    def test_get_collection_vendor_data(self):
        data = {
            'vendor_id': self.collection_vendor.id
        }
        res = self.client.get('/collection_vendor/collection_vendor_form', data=data)
        assert res.status_code == 200

    def test_collection_vendor_data_edit(self):
        data = {
            'save_type': '',
            'vendor_name': 'test_vendor_name',
            'is_active': '',
            'is_special': 'on',
            'is_general': '',
            'is_final': ''
        }
        res = self.client.post('/collection_vendor/collection_vendor_form', data=data)
        assert res.status_code == 200
        # vendor name exist
        data['vendor_name'] = 'test123'
        res = self.client.post('/collection_vendor/collection_vendor_form', data=data)
        assert res.status_code == 200

    @patch('juloserver.collection_vendor.views.generate_collection_vendor_ratio')
    @patch('juloserver.collection_vendor.views.validate_collection_vendor_name')
    def test_collection_vendor_data_add(self, mock_validate_collection_vendor_name,
                                        mock_generate_collection_vendor_ratio):
        data = {
            'save_type': '',
            'vendor_name': 'test123',
            'is_active': '',
            'is_special': 'on',
            'is_general': '',
            'is_final': ''
        }
        mock_validate_collection_vendor_name.return_value = True
        mock_generate_collection_vendor_ratio.return_value = True
        res = self.client.post('/collection_vendor/collection_vendor_form', data=data)
        assert res.status_code == 200
        # else
        mock_validate_collection_vendor_name.return_value = False
        res = self.client.post('/collection_vendor/collection_vendor_form', data=data)
        assert res.status_code == 200


class TestCollectionVendorDelete(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)

    def test_collection_vendor_data(self):
        data = {
            'collections_vendor_ids': '1,2,3,4,5'
        }
        res = self.client.post('/collection_vendor/collection_vendor_delete', data= data)
        assert res.status_code == 200
        assert res.json()['messages'] == 'Collection Vendor berhasil dihapus'


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestTransferAccountList(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.loan = LoanFactory()
        self.payment = PaymentFactory(loan=self.loan)
        self.coll_vendor_assignment_trf_type = CollectionVendorAssigmentTransferTypeFactory()
        self.coll_vendor_assignment_trf = CollectionVendorAssignmentTransferFactory(
            id=123123123,transfer_type=self.coll_vendor_assignment_trf_type)
        self.coll_vendor = CollectionVendorFactory()
        self.agent_assignment = AgentAssignmentFactory()
        self.sub_bucket = SubBucketFactory(sub_bucket=5)

    @patch('juloserver.collection_vendor.views.get_current_sub_bucket')
    def test_transfer_account_list(self, mock_get_current_sub_bucket):
        self.coll_vendor_assignment_trf.transfer_from_id = 1
        self.coll_vendor_assignment_trf.transfer_from = self.user
        self.coll_vendor_assignment_trf.payment = self.payment
        self.coll_vendor_assignment_trf.save()

        self.agent_assignment.agent = self.user
        self.agent_assignment.collection_vendor_assigment_transfer = self.coll_vendor_assignment_trf
        self.agent_assignment.is_transferred_to_other = True
        self.agent_assignment.assign_time = timezone.now()
        self.agent_assignment.save()

        mock_get_current_sub_bucket.return_value = self.sub_bucket
        res = self.client.get('/collection_vendor/transfer_account_list')
        assert res.status_code == 200
        # sub bucket today is none
        mock_get_current_sub_bucket.return_value = None
        res = self.client.get('/collection_vendor/transfer_account_list')
        assert res.status_code == 200
        # transfer from not user
        self.coll_vendor.vendor = self.user
        self.coll_vendor.collection_vendor_assigment_transfer = self.coll_vendor_assignment_trf
        self.coll_vendor.is_transferred_to_other = True
        self.coll_vendor.assign_time = timezone.now()
        self.coll_vendor.save()

        self.coll_vendor_assignment_trf.transfer_from_id = 1
        self.coll_vendor_assignment_trf.transfer_from = self.coll_vendor
        self.coll_vendor_assignment_trf.save()

        mock_get_current_sub_bucket.return_value = self.sub_bucket
        res = self.client.get('/collection_vendor/transfer_account_list')
        assert res.status_code == 200


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestAddNewTransferAccount(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.application = ApplicationFactory()
        self.loan = LoanFactory()
        self.payment = PaymentFactory()
        self.customer = CustomerFactory()
        self.sub_bucket = SubBucketFactory()
        self.coll_vendor_assignment = CollectionVendorAssignmentFactory()
        self.agent_assignment = AgentAssignmentFactory()
        self.coll_vendor = CollectionVendorFactory()


    @patch('juloserver.collection_vendor.views.format_assigment_transfer_from')
    @patch('juloserver.collection_vendor.views.get_current_sub_bucket')
    def test_get_add_new_transfer_account(self, mock_get_current_sub_bucket,
                                      mock_format_assigment_transfer_from):
        data = {
            'application_xid': self.loan.application.application_xid
        }
        # self.application.customer = self.customer
        # self.application.save()

        self.coll_vendor_assignment.is_active_assignment=False
        self.coll_vendor_assignment.save()

        # self.loan.application = self.application
        # self.loan.application_xid = self.application
        self.loan.loan_status_id = 220
        self.loan.ever_entered_B5 = True
        self.loan.save()

        mock_get_current_sub_bucket.return_value = self.sub_bucket
        res = self.client.get('/collection_vendor/add_new_transfer_account', data=data)
        assert res.status_code == 200
        # CollectionVendorAssignment not none
        # self.loan.application = self.application
        # self.loan.save()

        # self.payment.loan = self.loan
        # self.payment.save()
        payment = self.loan.payment_set.first()

        self.coll_vendor_assignment.is_active_assignment = True
        self.coll_vendor_assignment.payment = payment
        self.coll_vendor_assignment.save()
        mock_format_assigment_transfer_from.return_value = {'test_key': 'test_value'}
        res = self.client.get('/collection_vendor/add_new_transfer_account', data=data)
        assert res.status_code == 200


    @patch('juloserver.collection_vendor.views.get_current_sub_bucket')
    def test_current_sub_bucket_1(self, mock_get_current_sub_bucket):
        data = {
            'transfer_from_id': self.agent_assignment.id,
            'vendor_name': self.coll_vendor.id,
            'transfer_reason': '',
            'payment_id': self.payment.id,
            'save_type': '',
            'transfer_from_labels': 'agent',
        }
        self.agent_assignment.agent = self.user
        self.agent_assignment.save()

        mock_get_current_sub_bucket.return_value = self.sub_bucket
        # transfer from agent
        res = self.client.post('/collection_vendor/add_new_transfer_account', data=data)
        assert res.status_code == 200

    @patch('juloserver.collection_vendor.views.get_current_sub_bucket')
    def test_current_sub_bucket_2_3(self, mock_get_current_sub_bucket):
        data = {
            'transfer_from_id': self.coll_vendor_assignment.id,
            'vendor_name': self.coll_vendor.id,
            'transfer_reason': '',
            'payment_id': self.payment.id,
            'save_type': '',
            'transfer_from_labels': 'vendor',
        }
        self.agent_assignment.agent = self.user
        self.agent_assignment.save()

        self.sub_bucket.sub_bucket = 2
        self.sub_bucket.save()
        mock_get_current_sub_bucket.return_value = self.sub_bucket
        res = self.client.post('/collection_vendor/add_new_transfer_account', data=data)
        assert res.status_code == 200

    @patch('juloserver.collection_vendor.views.get_current_sub_bucket')
    def test_current_sub_bucket_4(self, mock_get_current_sub_bucket):
        data = {
            'transfer_from_id': self.coll_vendor_assignment.id,
            'vendor_name': self.coll_vendor.id,
            'transfer_reason': '',
            'payment_id': self.payment.id,
            'save_type': '',
            'transfer_from_labels': 'vendor',
        }
        self.agent_assignment.agent = self.user
        self.agent_assignment.save()

        self.sub_bucket.sub_bucket = 4
        self.sub_bucket.save()
        mock_get_current_sub_bucket.return_value = self.sub_bucket
        res = self.client.post('/collection_vendor/add_new_transfer_account', data=data)
        assert res.status_code == 200

    @patch('juloserver.collection_vendor.views.get_current_sub_bucket')
    def test_from_vendor_and_other(self, mock_get_current_sub_bucket):
        data = {
            'transfer_from_id': self.agent_assignment.id,
            'vendor_name': self.coll_vendor.id,
            'transfer_reason': '',
            'payment_id': self.payment.id,
            'save_type': '',
            'transfer_from_labels': 'agent',
        }
        self.agent_assignment.agent = self.user
        self.agent_assignment.save()

        mock_get_current_sub_bucket.return_value = self.sub_bucket
        # transfer from vendor
        data['transfer_from_labels'] = 'vendor'
        data['transfer_from_id'] = self.coll_vendor_assignment.id
        res = self.client.post('/collection_vendor/add_new_transfer_account', data=data)
        assert res.status_code == 200
        # transfer from other
        data['transfer_from_labels'] = 'Other'
        res = self.client.post('/collection_vendor/add_new_transfer_account', data=data)
        assert res.status_code == 200


class TestCollectionretainData(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)

    def test_collection_retain_data(self):
        res = self.client.get('/collection_vendor/collection_retain_data')
        assert res.status_code == 200


class TestCollectionretainForm(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)

    def test_collection_retain_form(self):
        res = self.client.get('/collection_vendor/collection_retain_form')
        assert res.status_code == 200


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestGetDataAssignment(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.application = ApplicationFactory(id=123123122,
                                              application_xid=123123123)
        self.loan = LoanFactory(
            id=123123124, application_xid=self.application)
        PaymentFactory(
            loan=self.loan,
            payment_number=0,
            id=123123125,
            account_payment=None,
        )
        self.payment = self.loan.payment_set.order_by('payment_number').first()
        self.coll_vendor_assign = CollectionVendorAssignmentFactory()
        self.sub_bucket = SubBucketFactory()
        self.coll_vendor = CollectionVendorFactory()
        self.vendor_assign_ext = CollectionVendorAssignmentExtensionFactory()

    def test_application_not_found(self):
        res = self.client.get('/collection_vendor/retain_assignment/123')
        assert res.json()['messages'] == 'application atau account tidak ditemukan'
        assert res.status_code == 200

    def test_loan_not_found(self):
        res = self.client.get('/collection_vendor/retain_assignment/123123123')
        assert res.json()['messages'] == 'loan tidak ditemukan'
        assert res.status_code == 200

    @mock.patch('juloserver.julo.models.Loan.get_oldest_unpaid_payment')
    def test_no_active_assignment(self, mocked_oldest_payment):
        self.loan.application = self.application
        self.loan.save()
        self.payment.loan = self.loan
        self.payment.payment_status_id = 310
        self.payment.payment_number = 0
        self.payment.save()
        mocked_oldest_payment.return_value = self.payment
        res = self.client.get('/collection_vendor/retain_assignment/123123123')
        assert res.json()['messages'] == 'Account tidak memiliki vendor assignment yang masih aktif'
        assert res.status_code == 200

    @patch('juloserver.collection_vendor.views.get_current_sub_bucket')
    def test_already_retain(self, mock_get_current_sub_bucket):
        self.loan.application = self.application
        self.loan.loan_status_id = 231
        self.loan.save()

        self.payment.loan = self.loan
        self.payment.payment_status_id = 310
        self.payment.payment_number = 0
        self.payment.save()
        self.vendor_assign_ext.vendor = self.coll_vendor
        self.vendor_assign_ext.sub_bucket_current = self.sub_bucket
        self.vendor_assign_ext.save()

        self.coll_vendor_assign.vendor_assignment_extension = self.vendor_assign_ext
        self.coll_vendor_assign.vendor = self.coll_vendor
        self.coll_vendor_assign.payment = self.payment
        self.coll_vendor_assign.is_active_assignment = True
        self.coll_vendor_assign.save()

        mock_get_current_sub_bucket.return_value = self.sub_bucket
        res = self.client.get('/collection_vendor/retain_assignment/123123123')
        assert res.json()['messages'] == 'Account sudah pernah di-retain sebelumnya oleh ' \
                                         'Vendor ini pada periode Sub Bucket yang sama'
        assert res.status_code == 200

    @patch('juloserver.collection_vendor.views.get_current_sub_bucket')
    def test_over_dpd_720(self, mock_get_current_sub_bucket):
        self.loan.application = self.application
        self.loan.loan_status_id = 231
        self.loan.save()

        today = timezone.localtime(timezone.now()).date()
        self.payment.loan = self.loan
        self.payment.payment_status_id = 310
        self.payment.payment_number = 0
        self.payment.due_date = today - timedelta(days=722)
        self.payment.save()

        self.coll_vendor_assign.vendor = self.coll_vendor
        self.coll_vendor_assign.payment = self.payment
        self.coll_vendor_assign.is_active_assignment = True
        self.coll_vendor_assign.save()

        mock_get_current_sub_bucket.return_value = self.sub_bucket
        res = self.client.get('/collection_vendor/retain_assignment/123123123')
        assert res.json()['messages'] == 'Account ini telah melewati DPD 720 pada saat' \
                                         'Retain Removal Date (1 bulan dari sekarang)'
        assert res.status_code == 200

    @patch('juloserver.collection_vendor.views.get_current_sub_bucket')
    def test_success(self, mock_get_current_sub_bucket):
        self.loan.application = self.application
        self.loan.loan_status_id = 231
        self.loan.save()

        self.payment.loan = self.loan
        self.payment.payment_status_id = 310
        self.payment.payment_number = 0
        self.payment.due_date = None
        self.payment.save()

        self.sub_bucket.bucket = 5
        self.sub_bucket.sub_bucket = None
        self.sub_bucket.save()
        self.sub_bucket.refresh_from_db()

        self.coll_vendor_assign.vendor = self.coll_vendor
        self.coll_vendor_assign.payment = self.payment
        self.coll_vendor_assign.is_active_assignment = True
        self.coll_vendor_assign.sub_bucket_assign_time = self.sub_bucket
        self.coll_vendor_assign.save()

        mock_get_current_sub_bucket.return_value = self.sub_bucket
        res = self.client.get('/collection_vendor/retain_assignment/123123123')
        assert res.json()['status'] == 'success'
        assert res.status_code == 200


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestStoreretainData(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.application = ApplicationFactory(application_xid=123123123)
        self.loan = LoanFactory()
        self.payment = PaymentFactory()
        self.coll_vendor_assign = CollectionVendorAssignmentFactory()
        self.sub_bucket = SubBucketFactory()
        self.coll_vendor = CollectionVendorFactory()
        self.vendor_assign_ext = CollectionVendorAssignmentExtensionFactory()

    def test_payment_not_found(self):
        data = {
            'vendor_id': self.coll_vendor.id,
            'payment_id': 123321,
            'account_payment_id': 0,
            'retain_reason': 'test_retain'
        }

        res = self.client.post('/collection_vendor/store_retain_assignment', data= data)
        assert res.json()['status'] == 'fail'
        assert res.json()['messages'] == 'Payment atau account payment tidak ditemukan'
        assert res.status_code == 200

    @patch('juloserver.collection_vendor.views.get_current_sub_bucket')
    def test_payment_not_assign(self, mock_get_current_sub_bucket):
        data = {
            'vendor_id': self.coll_vendor.id,
            'payment_id': self.payment.id,
            'account_payment_id': 0,
            'retain_reason': 'test_retain'
        }
        mock_get_current_sub_bucket.return_value = self.sub_bucket
        res = self.client.post('/collection_vendor/store_retain_assignment', data= data)
        assert res.json()['status'] == 'fail'
        assert res.json()['messages'] == 'Payment ini belum diassign ke vendor'
        assert res.status_code == 200

    @patch('juloserver.collection_vendor.views.get_current_sub_bucket')
    def test_success(self, mock_get_current_sub_bucket):
        data = {
            'vendor_id': self.coll_vendor.id,
            'payment_id': self.payment.id,
            'account_payment_id': 0,
            'retain_reason': 'test_retain'
        }

        self.sub_bucket.bucket = 5
        self.sub_bucket.sub_bucket = None
        self.sub_bucket.save()
        self.sub_bucket.refresh_from_db()

        self.coll_vendor_assign.payment = self.payment
        self.coll_vendor_assign.is_active_assignment = True
        self.coll_vendor_assign.sub_bucket_assign_time = self.sub_bucket
        self.coll_vendor_assign.save()

        mock_get_current_sub_bucket.return_value = self.sub_bucket
        res = self.client.post('/collection_vendor/store_retain_assignment', data= data)
        assert res.json()['status'] == 'success'
        assert res.json()['messages'] == 'Account vendor berhasil di retain'
        assert res.status_code == 200


class TestVendorCallingResult(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.application = ApplicationFactory()
        self.upload_vendor_report = UploadVendorReportFactory()
        self.vendor_report_error_information = VendorReportErrorInformationFactory(
            application_xid=self.application.application_xid
        )

    def test_download_error_information_vendor_calling_result(self):
        response = self.client.get('/collection_vendor/download_error_information/{}'.format(
            self.upload_vendor_report.id
        ))
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestAgentRemovalB5(TestCase):
    def setUp(self):
        group = Group(name="collection_supervisor")
        group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(group)
        self.client.force_login(self.user)
        self.agent_user = AuthUserFactory()
        self.account = AccountFactory(
            ever_entered_B5=True
        )
        self.j1_customer = CustomerFactory()
        self.j1_application = ApplicationFactory(
            account=self.account, customer=self.j1_customer
        )
        AccountPaymentFactory(
            account=self.account)
        self.account_payment = self.account.accountpayment_set.order_by('due_date').first()
        self.agent_assignment_j1 = AgentAssignmentFactory(
            agent=self.agent_user,
            is_active_assignment=True,
            payment=None, account_payment=self.account_payment,
        )
        self.mtl_customer = CustomerFactory()
        self.mtl_application = ApplicationFactory(
            customer=self.mtl_customer
        )
        self.loan = LoanFactory(application=self.mtl_application)
        self.payment = PaymentFactory(loan=self.loan)
        self.agent_assignment_mtl = AgentAssignmentFactory(
            agent=self.agent_user,
            is_active_assignment=True,
            payment=self.payment, account_payment=None,
        )

    def test_access_agent_removal_page(self):
        url = '/collection_vendor/agent_removal/'
        # without filter
        response = self.client.get(
            url,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # with agent name mode
        data_for_search = dict(
            agent_username=self.agent_user.username,
            input_mode='agent_name_mode'
        )
        response = self.client.post(url, data=data_for_search, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # with account id
        data_for_search = dict(
            loan_or_account_id=self.account.id,
            input_mode='loan_or_account_mode'
        )
        response = self.client.post(url, data=data_for_search, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # with loan id
        data_for_search = dict(
            loan_or_account_id=self.loan.id,
            input_mode='loan_or_account_mode'
        )
        response = self.client.post(url, data=data_for_search, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_transfer_agent_assignment(self):
        url = '/collection_vendor/process_agent_transfer'
        new_agent = AuthUserFactory()
        data = dict(
            agent_assignment_ids=str(self.agent_assignment_mtl.id),
            new_agent_username=new_agent.username
        )
        response = self.client.post(url, data=data)
        response_json = response.json()
        self.assertEqual(response_json['status'], "success")
        self.agent_assignment_mtl.refresh_from_db()
        self.assertEqual(self.agent_assignment_mtl.is_active_assignment, False)
        new_agent_assignment = AgentAssignment.objects.filter(agent=new_agent).last()
        self.assertEqual(new_agent_assignment.is_active_assignment, True)

    def test_remove_agent_assignment(self):
        url = '/collection_vendor/process_agent_removal'
        data = dict(
            agent_assignment_ids=str(self.agent_assignment_j1.id),
        )
        response = self.client.post(url, data=data)
        response_json = response.json()
        self.assertEqual(response_json['status'], "success")
        self.agent_assignment_j1.refresh_from_db()
        self.assertEqual(self.agent_assignment_j1.is_active_assignment, False)


class TestMenuAccessingVendorRecordingFile(TestCase):
    def setUp(self):
        group = Group(name="collection_supervisor")
        group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(group)
        self.client.force_login(self.user)
        self.agent_user = AuthUserFactory()

    def test_access_menu_recording_files_page(self):
        j1_customer = CustomerFactory()
        account = AccountFactory(customer=j1_customer)
        j1_application = ApplicationFactory(
            account=account, customer=j1_customer
        )
        AccountPaymentFactory(account=account)
        account_payment = account.accountpayment_set.order_by('due_date').first()
        mtl_customer = CustomerFactory()
        mtl_application = ApplicationFactory(
            customer=mtl_customer
        )
        loan = LoanFactory(application=mtl_application)
        payment = PaymentFactory(loan=loan)
        today = datetime.now()
        today = today.strftime("%Y-%m-%d")
        start_date = today + " 12:00:00"
        end_date = today + " 12:00:30"
        vendor_recording = VendorRecordingDetailFactory(
            agent=self.agent_user,
            payment=None,
            account_payment=account_payment,
            call_start=datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S'),
            call_end=datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S'),
        )
        url = '/collection_vendor/recording_detail_list/'
        # without filter
        response = self.client.get(
            url,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data_for_search = dict(
            search_call_date_mode='between',
            search_call_date_1=start_date,
            search_call_date_2=end_date,
        )
        response = self.client.post(url, data=data_for_search, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data_for_search.update(
            search_duration_mode='between',
            search_duration_filter_1=5,
            search_duration_filter_2=15,
        )
        response = self.client.post(url, data=data_for_search, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data_for_search.update(
            search_duration_mode='greater',
            search_duration_filter_1=5,
        )
        response = self.client.post(url, data=data_for_search, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data_for_search.update(
            search_duration_mode='less',
            search_duration_filter_1=15,
        )
        response = self.client.post(url, data=data_for_search, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data_for_search_specific = dict(
            global_search_value_call_start='{},{}'.format(
                start_date, end_date
            ),
        )
        response = self.client.post(url, data=data_for_search_specific, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data_for_search_specific_end = dict(
            global_search_value_call_end='{},{}'.format(
                start_date, end_date
            ),
        )
        response = self.client.post(url, data=data_for_search_specific_end, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data_for_search_specific_duration = dict(
            global_search_value_duration='10,15'
        )
        response = self.client.post(url, data=data_for_search_specific_duration, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data_for_search_specific_payment = dict(
            global_search_value_payment_id='{},400012321'.format(
                str(payment.id))
        )
        response = self.client.post(url, data=data_for_search_specific_payment, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data_for_search_specific_account_payment = dict(
            global_search_value_account_payment_id='{},123'.format(
                str(vendor_recording.account_payment.id))
        )
        response = self.client.post(url, data=data_for_search_specific_account_payment, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data_for_search_specific_agent = dict(
            global_search_value_agent='{},unitestzz'.format(vendor_recording.agent.username)
        )
        response = self.client.post(url, data=data_for_search_specific_agent, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data_for_search_specific_bucket = dict(
            global_search_value_bucket='{},JULO_B2'.format(vendor_recording.bucket)
        )
        response = self.client.post(url, data=data_for_search_specific_bucket, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data_for_search_specific_call_to = dict(
            global_search_value_call_to='{},0821312312'.format(vendor_recording.call_to)
        )
        response = self.client.post(url, data=data_for_search_specific_call_to, )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
