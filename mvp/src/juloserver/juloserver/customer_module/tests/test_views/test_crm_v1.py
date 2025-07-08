from datetime import timedelta
from unittest import mock
from unittest.mock import patch
from juloserver.julo.models import (
    ApplicationHistory,
    CustomerRemoval,
    ProductLine,
    StatusLookup,
    Workflow,
)
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from rest_framework.test import APITestCase, APIClient

from django.conf import settings
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationHistoryFactory,
    ApplicationJ1Factory,
    AuthUserFactory,
    CustomerFactory,
    ImageFactory,
    LoanFactory,
    CustomerRemovalFactory,
    ProductLineFactory,
    StatusLookupFactory,
    WorkflowFactory,
)
from juloserver.account.constants import (
    AccountConstant,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AddressFactory,
)
from juloserver.customer_module.constants import (
    DELETION_REQUEST_AUTO_APPROVE_DAY_LIMIT,
    AccountDeletionRequestStatuses,
    AccountDeletionStatusChangeReasons,
    FailedAccountDeletionRequestStatuses,
)
from juloserver.customer_module.tests.factories import (
    AccountDeletionRequestFactory,
    CustomerDataChangeRequestFactory,
)
from juloserver.julo.statuses import ApplicationStatusCodes, JuloOneCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationJ1Factory,
    AuthUserFactory,
    CustomerFactory,
    CustomerRemovalFactory,
    ImageFactory,
    LoanFactory,
    StatusLookupFactory,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles


class TestCustomerRemovalView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.CS_ADMIN)
        self.group.save()
        self.user.groups.add(self.group)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.client.force_login(self.user)

        self.current_datetime = timezone.datetime(2023, 3, 8, 12, 0, 0)
        with patch('django.utils.timezone.now', return_value=self.current_datetime):

            self.user_2 = AuthUserFactory()
            self.customer_2 = CustomerFactory(user=self.user_2)
            self.application_2 = ApplicationFactory(customer=self.customer_2)
            self.customer_removal = CustomerRemovalFactory(
                customer=self.customer_2,
                application=self.application_2,
                user=self.user_2,
                reason="its a test",
                added_by=self.user,
                udate=self.current_datetime,
            )

        self.current_datetime_2 = timezone.datetime(2022, 12, 9, 12, 0, 0)
        with patch('django.utils.timezone.now', return_value=self.current_datetime_2):
            self.user_3 = AuthUserFactory()
            self.customer_3 = CustomerFactory(user=self.user_3)
            self.application_3 = ApplicationFactory(customer=self.customer_3)
            self.customer_removal = CustomerRemovalFactory(
                customer=self.customer_3,
                application=self.application_3,
                user=self.user_3,
                reason="its a test",
                added_by=self.user,
                udate=self.current_datetime_2,
            )

        self.current_datetime_3 = timezone.datetime(2023, 2, 25, 12, 0, 0)
        with patch('django.utils.timezone.now', return_value=self.current_datetime_3):
            self.user_4 = AuthUserFactory()
            self.customer_4 = CustomerFactory(user=self.user_4)
            self.application_4 = ApplicationFactory(customer=self.customer_4)
            self.customer_removal = CustomerRemovalFactory(
                customer=self.customer_4,
                application=self.application_4,
                user=self.user_4,
                reason="its a test",
                added_by=self.user,
                udate=self.current_datetime_3,
            )

    @mock.patch('django.utils.timezone.now')
    def test_customer_removal(self, mock_localtime):

        # test all
        mock_localtime.return_value = timezone.datetime(2023, 3, 9, 12, 0, 0)
        url = '/api/customer-module/v1/customer-removal/'
        response = self.client.get(url)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data']['count'], 3)

        # test last 2 months
        url = '/api/customer-module/v1/customer-removal/?filter_by=2M'
        response = self.client.get(url)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data']['count'], 2)

        # test last 1 months
        url = '/api/customer-module/v1/customer-removal/?filter_by=1M'
        response = self.client.get(url)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data']['count'], 2)

        # test last 10 days
        url = '/api/customer-module/v1/customer-removal/?filter_by=10D'
        response = self.client.get(url)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data']['count'], 1)


class TestSearchCustomer(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.CS_ADMIN)
        self.group.save()
        self.user.groups.add(self.group)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(
            customer=self.customer,
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.J1,
            ),
            workflow=WorkflowFactory(
                name=WorkflowConst.JULO_ONE,
            ),
        )
        self.client.force_login(self.user)

        # active loan data
        self.user_2 = AuthUserFactory()
        self.customer_2 = CustomerFactory(user=self.user_2, id=1000007538)
        self.application_2 = ApplicationFactory(
            customer=self.customer_2,
            id=2000006794,
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.J1,
            ),
            workflow=WorkflowFactory(
                name=WorkflowConst.JULO_ONE,
            ),
        )
        status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer_2, status=status_code)
        self.status_2 = StatusLookupFactory(status_code=237)
        self.loan_2 = LoanFactory(
            customer=self.customer_2,
            application=self.application_2,
            loan_status=self.status_2,
        )
        # no active loan data
        self.user_3 = AuthUserFactory()
        self.customer_3 = CustomerFactory(user=self.user_3, id=1000007539)
        self.application_3 = ApplicationFactory(
            customer=self.customer_3,
            id=2000006795,
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.J1,
            ),
            workflow=WorkflowFactory(
                name=WorkflowConst.JULO_ONE,
            ),
        )
        status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer_3, status=status_code)
        self.status_3 = StatusLookupFactory(status_code=260)
        self.loan_3 = LoanFactory(
            customer=self.customer_3,
            application=self.application_3,
            loan_status=self.status_3,
        )
        self.url = '/api/customer-module/v1/search-customer/'

    # test using application id
    def test_search_using_application_id_active_loan(self):

        data = {"app_or_customer_id": self.application_2.pk}
        response = self.client.post(self.url, data)
        self.assertEquals(response.status_code, 200)
        self.assertTrue(response.json()['data']['active_loan_found'])
        self.assertFalse(response.json()['data']['show_delete_button'])
        self.assertEquals(response.json()['data']['account_status_id'], 420)

    def test_search_using_application_id_no_active_loan(self):

        data = {"app_or_customer_id": self.application_3.pk}
        response = self.client.post(self.url, data)
        self.assertEquals(response.status_code, 200)
        self.assertFalse(response.json()['data']['active_loan_found'])
        self.assertTrue(response.json()['data']['show_delete_button'])
        self.assertEquals(response.json()['data']['account_status_id'], 420)

    # test using Customer id
    def test_search_using_customer_id_active_loan(self):

        data = {"app_or_customer_id": self.customer_2.pk}
        response = self.client.post(self.url, data)
        self.assertEquals(response.status_code, 200)
        self.assertTrue(response.json()['data']['active_loan_found'])
        self.assertFalse(response.json()['data']['show_delete_button'])
        self.assertEquals(response.json()['data']['account_status_id'], 420)

    def test_search_using_customer_id_no_active_loan(self):
        data = {"app_or_customer_id": self.customer_3.pk}
        response = self.client.post(self.url, data)
        self.assertEquals(response.status_code, 200)
        self.assertFalse(response.json()['data']['active_loan_found'])
        self.assertTrue(response.json()['data']['show_delete_button'])
        self.assertEquals(response.json()['data']['account_status_id'], 420)

    def test_account_status(self):
        status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        # active loan
        self.account = AccountFactory(customer=self.customer_2, status=status_code)
        data = {"app_or_customer_id": self.application_2.pk}
        response = self.client.post(self.url, data)
        self.assertEquals(response.status_code, 200)
        self.assertTrue(response.json()['data']['active_loan_found'])
        self.assertFalse(response.json()['data']['show_delete_button'])
        self.assertFalse(response.json()['data']['is_soft_delete'])
        self.assertEquals(response.json()['data']['account_status_id'], 420)

        # No active loan
        self.account = AccountFactory(customer=self.customer_3, status=status_code)
        data = {"app_or_customer_id": self.application_3.pk}
        response = self.client.post(self.url, data)
        self.assertEquals(response.status_code, 200)
        self.assertFalse(response.json()['data']['active_loan_found'])
        self.assertTrue(response.json()['data']['show_delete_button'])
        self.assertFalse(response.json()['data']['is_soft_delete'])
        self.assertEquals(response.json()['data']['account_status_id'], 420)

    def test_account_soft_deletion(self):
        status_code = StatusLookupFactory(status_code=JuloOneCodes.INACTIVE)
        self.account = AccountFactory(customer=self.customer_3, status=status_code)
        data = {"app_or_customer_id": self.application_3.pk}
        response = self.client.post(self.url, data)
        self.assertEquals(response.status_code, 200)
        self.assertFalse(response.json()['data']['active_loan_found'])
        self.assertTrue(response.json()['data']['show_delete_button'])
        self.assertTrue(response.json()['data']['is_soft_delete'])
        self.assertEquals(response.json()['data']['account_status_id'], 410)


class TestDeleteCustomerView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.CS_ADMIN)
        self.group.save()
        self.user.groups.add(self.group)
        self.customer = CustomerFactory(
            user=self.user, nik='8698731301958085', email='abcd@julo.co.id', phone=None
        )
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )
        self.workflow = Workflow.objects.get(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            ktp=None,
            mobile_phone_1=None,
            email=None,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.client.force_login(self.user)

    @patch('juloserver.customer_module.services.crm_v1.generate_new_token')
    def test_no_application(self, mock_generate_new_token):
        user = AuthUserFactory()
        customer = CustomerFactory(
            user=user,
            nik='3173847362810003',
            email='qwerty@julo.co.id',
            phone=None,
        )
        client = APIClient()
        client.force_login(user)

        url = '/api/customer-module/v1/delete-customer/'
        data = {
            "customer_id": customer.pk,
            "reason": "Its a test",
        }
        response = self.client.post(url, data)
        self.assertTrue(response.json()['data']['is_deleted'])

        mock_generate_new_token.assert_called_once_with(user)

        user.refresh_from_db()
        customer.refresh_from_db()

        self.assertFalse(user.is_active)
        self.assertFalse(customer.can_reapply)
        self.assertFalse(customer.is_active)

    def test_no_deletion_supported_application(self):
        user = AuthUserFactory()
        customer = CustomerFactory(
            user=user,
        )
        application = ApplicationFactory(
            customer=customer,
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.GRAB,
            ),
        )

        client = APIClient()
        client.force_login(user)

        url = '/api/customer-module/v1/delete-customer/'
        data = {
            "customer_id": customer.pk,
            "reason": "Its a test",
        }

        old_customer_removal_count = CustomerRemoval.objects.count()
        response = self.client.post(url, data)
        self.assertEqual(
            response.json(),
            {'success': False, 'data': None, 'errors': ['Akun tidak bisa di delete']},
        )

        new_customer_removal_count = CustomerRemoval.objects.count()
        self.assertEqual(old_customer_removal_count, new_customer_removal_count)

        is_customer_removal_exists = CustomerRemoval.objects.filter(user_id=user.id).exists()
        self.assertFalse(is_customer_removal_exists)

        user.refresh_from_db()
        customer.refresh_from_db()
        application.refresh_from_db()

        self.assertTrue(user.is_active)
        self.assertTrue(customer.is_active)
        self.assertTrue(application.is_active)

    @patch('juloserver.customer_module.services.crm_v1.generate_new_token')
    def test_all_applications_are_deleted(self, mock_generate_new_token):
        self.application_two = ApplicationFactory(
            customer=self.customer, workflow=self.workflow, product_line=self.product_line
        )
        url = '/api/customer-module/v1/delete-customer/'
        data = {
            "customer_id": self.customer.pk,
            "reason": "Its a test",
        }
        response = self.client.post(url, data)

        mock_generate_new_token.assert_called_once_with(self.customer.user)

        self.user.refresh_from_db()
        self.customer.refresh_from_db()
        self.application.refresh_from_db()
        self.application_two.refresh_from_db()

        self.assertFalse(self.user.is_active)
        self.assertFalse(self.customer.can_reapply)
        self.assertFalse(self.customer.is_active)
        self.assertTrue(self.application.is_deleted)
        self.assertTrue(self.application_two.is_deleted)
        self.assertEqual(
            self.application.application_status_id, ApplicationStatusCodes.CUSTOMER_DELETED
        )
        self.assertEqual(
            self.application_two.application_status_id, ApplicationStatusCodes.CUSTOMER_DELETED
        )
        self.assertTrue(response.json()['data']['is_deleted'])

    @patch('juloserver.customer_module.services.crm_v1.generate_new_token')
    def test_delete_customer_account_no_pending_loan(self, mock_generate_new_token):
        self.status = StatusLookupFactory(status_code=260)
        self.loan = LoanFactory(
            customer=self.customer,
            application=self.application,
            loan_status=self.status,
        )

        url = '/api/customer-module/v1/delete-customer/'
        data = {
            "customer_id": self.customer.pk,
            "reason": "Its a test",
        }
        response = self.client.post(url, data)
        self.assertTrue(response.json()['data']['is_deleted'])

        mock_generate_new_token.assert_called_once_with(self.customer.user)

    def test_delete_customer_account_pending_loan(self):
        self.status = StatusLookupFactory(status_code=237)
        self.loan = LoanFactory(
            customer=self.customer,
            application=self.application,
            loan_status=self.status,
        )

        url = '/api/customer-module/v1/delete-customer/'
        data = {
            "customer_id": self.customer.pk,
            "reason": "Its a test",
        }
        response = self.client.post(url, data)
        self.assertEquals(
            response.json()['errors'][0]['msg'],
            'Maaf, terjadi kesalahan di sistem. Silakan coba lagi.',
        )

    @patch('juloserver.customer_module.services.crm_v1.generate_new_token')
    def test_delete_customer(self, mock_generate_new_token):
        self.user_2 = AuthUserFactory()
        self.customer_2 = CustomerFactory(
            id=1000015042,
            user=self.user_2,
            nik='8698731301957084',
            email='test@gmail.com',
            phone='086688702319',
        )
        self.application_2 = ApplicationFactory(
            customer=self.customer_2,
            ktp='8698731301957084',
            email='test@gmail.com',
            mobile_phone_1='086688702319',
            workflow=self.workflow,
            product_line=self.product_line,
        )

        self.status = StatusLookupFactory(status_code=260)
        self.loan = LoanFactory(
            customer=self.customer_2,
            application=self.application_2,
            loan_status=self.status,
        )

        url = '/api/customer-module/v1/delete-customer/'
        data = {
            "customer_id": self.customer_2.pk,
            "reason": "Its a test",
        }
        response = self.client.post(url, data)
        mock_generate_new_token.assert_called_once_with(self.user_2)

        self.user_2.refresh_from_db()
        self.customer_2.refresh_from_db()
        self.application_2.refresh_from_db()

        self.assertFalse(self.user_2.is_active)
        self.assertFalse(self.customer_2.can_reapply)
        self.assertFalse(self.customer_2.is_active)
        self.assertTrue(self.application_2.is_deleted)
        self.assertEqual(
            self.application_2.application_status_id, ApplicationStatusCodes.CUSTOMER_DELETED
        )
        self.assertTrue(response.json()['data']['is_deleted'])
        self.assertTrue(response.json()['data']['is_deleted'])
        self.assertEquals('444444' + str(self.customer_2.id), self.customer_2.nik)
        self.assertEquals(
            'deleteduser{}@gmail.com'.format(self.customer_2.id), self.customer_2.email
        )
        self.assertEquals('44' + str(self.customer_2.id), self.customer_2.phone)
        self.assertEquals('444444' + str(self.customer_2.id), self.application_2.ktp)
        self.assertEquals('44' + str(self.customer_2.id), self.application_2.mobile_phone_1)
        self.assertEquals(
            'deleteduser{}@gmail.com'.format(self.customer_2.id), self.application_2.email
        )

    @patch('juloserver.customer_module.services.crm_v1.generate_new_token')
    def test_delete_customer_username_is_nik(self, mock_generate_new_token):
        self.app_status = StatusLookupFactory(status_code=250)

        self.user_3 = AuthUserFactory(username='8698731301957085')
        self.customer_3 = CustomerFactory(
            user=self.user_3, nik=None, email=None, phone='086688702619'
        )
        self.application_3 = ApplicationFactory(
            customer=self.customer_3,
            ktp=None,
            status=self.app_status,
            mobile_phone_1=None,
            email=None,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application_4 = ApplicationFactory(
            customer=self.customer_3,
            ktp='8698731301957085',
            mobile_phone_1=None,
            email=None,
            workflow=self.workflow,
            product_line=self.product_line,
        )

        self.status = StatusLookupFactory(status_code=260)

        self.loan = LoanFactory(
            customer=self.customer_3,
            application=self.application_4,
            loan_status=self.status,
        )

        url = '/api/customer-module/v1/delete-customer/'
        data = {
            "customer_id": self.customer_3.pk,
            "reason": "Its a test",
        }
        response = self.client.post(url, data)
        mock_generate_new_token.assert_called_once_with(self.user_3)

        self.user_3.refresh_from_db()
        self.customer_3.refresh_from_db()
        self.application_3.refresh_from_db()
        self.application_4.refresh_from_db()

        self.assertFalse(self.user_3.is_active)
        self.assertFalse(self.customer_3.can_reapply)
        self.assertFalse(self.customer_3.is_active)
        self.assertTrue(self.application_3.is_deleted)
        self.assertTrue(self.application_4.is_deleted)
        self.assertEqual(
            self.application_3.application_status_id, ApplicationStatusCodes.CUSTOMER_DELETED
        )
        self.assertEqual(
            self.application_4.application_status_id, ApplicationStatusCodes.CUSTOMER_DELETED
        )
        self.assertTrue(response.json()['data']['is_deleted'])
        self.assertTrue(response.json()['data']['is_deleted'])
        self.assertEquals('444444' + str(self.customer_3.id), self.application_4.ktp)
        self.assertEquals('444444' + str(self.customer_3.id), self.user_3.username)

    @patch('juloserver.customer_module.services.crm_v1.generate_new_token')
    def test_delete_customer_account_username_is_not_nik(self, mock_generate_new_token):

        self.app_status = StatusLookupFactory(status_code=250)

        self.user_3 = AuthUserFactory(username='test123')
        self.customer_3 = CustomerFactory(user=self.user_3, nik=None, email=None, phone=None)
        self.application_3 = ApplicationFactory(
            customer=self.customer_3,
            ktp=None,
            status=self.app_status,
            mobile_phone_1=None,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application_4 = ApplicationFactory(
            customer=self.customer_3,
            ktp='8698731301957085',
            mobile_phone_1=None,
            workflow=self.workflow,
            product_line=self.product_line,
        )

        self.status = StatusLookupFactory(status_code=260)

        self.loan = LoanFactory(
            customer=self.customer_3,
            application=self.application_4,
            loan_status=self.status,
        )

        url = '/api/customer-module/v1/delete-customer/'
        data = {
            "customer_id": self.customer_3.pk,
            "reason": "Its a test",
        }
        response = self.client.post(url, data)
        mock_generate_new_token.assert_called_once_with(self.user_3)

        self.user_3.refresh_from_db()
        self.customer_3.refresh_from_db()
        self.application_3.refresh_from_db()
        self.application_4.refresh_from_db()

        self.assertFalse(self.user_3.is_active)
        self.assertFalse(self.customer_3.can_reapply)
        self.assertFalse(self.customer_3.is_active)
        self.assertTrue(self.application_3.is_deleted)
        self.assertTrue(self.application_4.is_deleted)
        self.assertEqual(
            self.application_3.application_status_id, ApplicationStatusCodes.CUSTOMER_DELETED
        )
        self.assertEqual(
            self.application_4.application_status_id, ApplicationStatusCodes.CUSTOMER_DELETED
        )
        self.assertTrue(response.json()['data']['is_deleted'])
        self.assertTrue(response.json()['data']['is_deleted'])
        self.assertEquals('444444' + str(self.customer_3.id), self.application_4.ktp)
        self.assertNotEquals('444444' + str(self.customer_3.id), self.user_3.username)

    def test_deleted_customer_with_account_status_code(self):
        self.status = StatusLookupFactory(status_code=260)
        self.loan = LoanFactory(
            customer=self.customer,
            application=self.application,
            loan_status=self.status,
        )
        self.status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.sold_off)
        self.account = AccountFactory(customer=self.customer, status=self.status_code)
        url = '/api/customer-module/v1/delete-customer/'
        data = {
            "customer_id": self.customer.pk,
            "reason": "Its a test",
            "is_NIK_modified": False,
        }
        response = self.client.post(url, data)
        self.assertEquals(
            response.json()['errors'][0],
            {'title': 'Hapus Akun Gagal', 'msg': 'akun tidak dapat dihapus'},
        )

        self.status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=self.status_code)
        url = '/api/customer-module/v1/delete-customer/'
        data = {
            "customer_id": self.customer.pk,
            "reason": "Its a test",
            "is_NIK_modified": False,
        }
        response = self.client.post(url, data)
        self.assertTrue(response.json()['data']['is_deleted'])

    @patch('juloserver.customer_module.services.crm_v1.generate_new_token')
    def test_delete_customer_have_other_than_j1_jstarter(self, mock_generate_new_token):
        customer = CustomerFactory(
            phone='086688702319',
        )
        grab_application = ApplicationFactory(
            customer=customer,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB),
            workflow=WorkflowFactory(name=WorkflowConst.GRAB),
        )
        j1_application = ApplicationFactory(
            customer=customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        url = '/api/customer-module/v1/delete-customer/'
        data = {
            "customer_id": customer.pk,
            "reason": "Its a test",
        }
        response = self.client.post(url, data)
        self.assertTrue(response.json()['data']['is_deleted'])

        mock_generate_new_token.assert_called_once_with(customer.user)

        customer.refresh_from_db()
        grab_application.refresh_from_db()
        j1_application.refresh_from_db()

        self.assertTrue(customer.is_active)
        self.assertFalse(grab_application.is_deleted)
        self.assertTrue(j1_application.is_deleted)

    def test_soft_delete(self):
        customer = CustomerFactory(
            phone='086688702319',
        )
        j1_application = ApplicationFactory(
            customer=customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        j1_application.application_status_id = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
        j1_application.save()

        url = '/api/customer-module/v1/delete-customer/'
        data = {
            "customer_id": customer.pk,
            "reason": "Its a test",
        }
        response = self.client.post(url, data)
        self.assertTrue(response.json()['data']['is_deleted'])

        customer.refresh_from_db()
        j1_application.refresh_from_db()

        self.assertFalse(customer.is_active)
        self.assertTrue(j1_application.is_deleted)

    def test_multiple_product_line(self):
        customer = CustomerFactory(
            phone='086688702319',
        )
        app = ApplicationFactory(
            customer=customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        app.application_status_id = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
        app.save()

        app2 = ApplicationFactory(
            customer=customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        app2.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        app2.save()

        app3 = ApplicationFactory(
            customer=customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.JTURBO,
            ),
        )
        app3.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        app3.save()

        url = '/api/customer-module/v1/delete-customer/'
        data = {
            "customer_id": customer.pk,
            "reason": "Its a test",
        }
        response = self.client.post(url, data)

        self.assertTrue(response.json()['data']['is_deleted'])

        removals = CustomerRemoval.objects.filter(
            customer=customer,
        )
        self.assertEqual(len(removals), 2)

        j1_removal = removals.filter(product_line=self.product_line).first()
        self.assertIsNotNone(j1_removal)
        self.assertEqual(j1_removal.application_id, app2.id)

        jturbo_removal = removals.filter(product_line_id=ProductLineCodes.JTURBO).first()
        self.assertIsNotNone(jturbo_removal)
        self.assertEqual(jturbo_removal.application_id, app3.id)

    def test_multiple_product_line_soft_delete(self):
        customer = CustomerFactory(
            phone='086688702319',
        )
        app1 = ApplicationFactory(
            customer=customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        app1.application_status_id = ApplicationStatusCodes.APPLICATION_DENIED
        app1.save()

        app2 = ApplicationFactory(
            customer=customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        app2.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        app2.save()

        app3 = ApplicationFactory(
            customer=customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.JTURBO,
            ),
        )
        app3.application_status_id = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
        app3.save()

        url = '/api/customer-module/v1/delete-customer/'
        data = {
            "customer_id": customer.pk,
            "reason": "Its a test",
        }
        response = self.client.post(url, data)

        self.assertTrue(response.json()['data']['is_deleted'])

        removals = CustomerRemoval.objects.filter(
            customer=customer,
        )
        self.assertEqual(len(removals), 2)

        j1_removal = removals.filter(product_line=self.product_line).first()
        self.assertIsNotNone(j1_removal)
        self.assertEqual(j1_removal.application_id, app2.id)

        jturbo_removal = removals.filter(product_line_id=ProductLineCodes.JTURBO).first()
        self.assertIsNotNone(jturbo_removal)
        self.assertEqual(jturbo_removal.application_id, app3.id)

    def test_soft_delete_after_hard_delete(self):
        customer = CustomerFactory(phone='086688702319', nik='3173068495920001', is_active=True)
        nik = customer.nik
        phone = customer.phone
        email = customer.email

        j1_application = ApplicationFactory(
            customer=customer,
            workflow=self.workflow,
            product_line=self.product_line,
            ktp='444444{}'.format(customer.id),
            mobile_phone_1='444444{}'.format(customer.id),
            email='deleteduser{}@gmail.com'.format(customer.id),
        )
        j1_application.application_status_id = ApplicationStatusCodes.CUSTOMER_DELETED
        j1_application.save()

        dana_application = ApplicationFactory(
            customer=customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        dana_application.application_status_id = (
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
        )
        dana_application.save()

        url = '/api/customer-module/v1/delete-customer/'
        data = {
            "customer_id": customer.pk,
            "reason": "Its a test",
        }
        response = self.client.post(url, data)
        self.assertTrue(response.json()['data']['is_deleted'])

        j1_application.refresh_from_db()
        dana_application.refresh_from_db()

        self.assertEqual(j1_application.ktp, nik)
        self.assertEqual(j1_application.mobile_phone_1, phone)
        self.assertEqual(j1_application.email, email)


class TestCustomerDataChangeRequestListView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.CS_ADMIN)
        self.group.save()
        self.user.groups.add(self.group)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.client.force_login(self.user)

    def test_get_list(self):
        CustomerDataChangeRequestFactory.create_batch(10)
        url = '/api/customer-module/v1/customer-data/change-request/'
        response = self.client.get(url)
        self.assertEquals(200, response.status_code, str(response.content))
        self.assertTrue(response.json()['success'], str(response.content))
        self.assertEquals(5, len(response.json()['data']['results']), str(response.content))
        self.assertEquals(10, response.json()['data']['count'], str(response.content))

    def test_get_list_empty(self):
        url = '/api/customer-module/v1/customer-data/change-request/'
        response = self.client.get(url)
        self.assertEquals(404, response.status_code, str(response.content))
        self.assertFalse(response.json()['success'], str(response.content))
        expected_error = [
            {
                'title': "Data tidak ditemukan",
                'msg': "Coba lakukan pencarian kembali",
            }
        ]
        self.assertEquals(expected_error, response.json()['errors'], str(response.content))

    def test_get_filter_search(self):
        CustomerDataChangeRequestFactory.create_batch(10)
        application = ApplicationJ1Factory()
        CustomerDataChangeRequestFactory(application=application, customer=application.customer)
        url = '/api/customer-module/v1/customer-data/change-request/'
        response = self.client.get(url, {'search': application.id})
        self.assertEquals(200, response.status_code, str(response.content))
        self.assertEquals(1, len(response.json()['data']['results']), str(response.content))
        self.assertEquals(1, response.json()['data']['count'], str(response.content))

    def test_get_forbidden_non_admin(self):
        user = AuthUserFactory()
        group = Group(name=JuloUserRoles.CCS_AGENT)
        group.save()
        user.groups.add(group)
        self.client.force_login(user)

        CustomerDataChangeRequestFactory.create_batch(10)
        url = '/api/customer-module/v1/customer-data/change-request/'
        response = self.client.get(url)
        self.assertEquals(401, response.status_code, str(response.content))

    def test_get_filter_application_non_admin(self):
        user = AuthUserFactory()
        group = Group(name=JuloUserRoles.CCS_AGENT)
        group.save()
        user.groups.add(group)
        self.client.force_login(user)
        application = ApplicationJ1Factory()
        CustomerDataChangeRequestFactory(application=application, customer=application.customer)

        CustomerDataChangeRequestFactory.create_batch(10)
        url = '/api/customer-module/v1/customer-data/change-request/'
        response = self.client.get(url, {'application_id': application.id})
        self.assertEquals(200, response.status_code, str(response.content))

        response = self.client.get(url, {'customer_id': application.customer_id})
        self.assertEquals(200, response.status_code, str(response.content))


class TestCustomerDataChangeRequestDetailView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.CS_ADMIN)
        self.group.save()
        self.user.groups.add(self.group)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationJ1Factory(customer=self.customer)
        self.client.force_login(self.user)
        self.default_change_request_data = dict(
            source='app',
            status='submitted',
            approval_note=None,
            address=AddressFactory(
                latitude=1.2,
                longitude=3.4,
                provinsi='DKI Jakarta',
                kabupaten='Jakarta Selatan',
                kecamatan='Kebayoran Baru',
                kelurahan='Gandaria Utara',
                kodepos=12140,
                detail='Jl. Gandaria I No. 1',
            ),
            job_type='karyawan',
            job_industry='perbankan',
            job_description='mengelola uang',
            company_name='PT. Bank Julo',
            company_phone_number='0211234567',
            payday=15,
            monthly_income=10000000,
            monthly_expenses=5000000,
            monthly_housing_cost=2000000,
            total_current_debt=1000000,
            address_transfer_certificate_image=ImageFactory(
                url='address_transfer_certificate_image.jpg',
            ),
            company_proof_image=ImageFactory(
                url='company_proof_image.jpg',
            ),
            paystub_image=ImageFactory(
                url='paystub_image.jpg',
            ),
        )
        self.approved_change_request = CustomerDataChangeRequestFactory(
            application=self.application,
            customer=self.customer,
            **self._construct_request_data(
                status='approved',
            ),
        )
        self.change_request = CustomerDataChangeRequestFactory(
            application=self.application,
            customer=self.customer,
            **self._construct_request_data(
                payday=20,
                job_type='wiraswasta',
                address=AddressFactory(
                    latitude=1.2,
                    longitude=3.4,
                    provinsi='Jawa Barat',
                    kabupaten='Jakarta Selatan',
                    kecamatan='Kebayoran Baru',
                    kelurahan='Gandaria Utara',
                    kodepos=12140,
                    detail='Jl. Gandaria I No. 1',
                ),
                address_transfer_certificate_image=None,
                company_proof_image=None,
                paystub_image=ImageFactory(
                    url='paystub_image_2.jpg',
                ),
                last_education='S1',
            ),
        )

    def _construct_request_data(self, **kwargs):
        data = self.default_change_request_data.copy()
        data.update(kwargs)
        return data

    def test_get_detail(self):
        url = '/api/customer-module/v1/customer-data/change-request/{}/'.format(
            self.change_request.id,
        )
        response = self.client.get(url)
        self.assertEquals(200, response.status_code, str(response.content))
        self.assertTrue(response.json()['success'], str(response.content))
        self.assertIn('original_data', response.json()['data'], str(response.content))
        self.assertIn('previous_data', response.json()['data'], str(response.content))
        self.assertIn('check_data', response.json()['data'], str(response.content))
        self.assertIn('change_fields', response.json()['data'], str(response.content))

        expected_change_fields = [
            'address_provinsi',
            'job_type',
            'payday',
            'paystub_image_url',
            'last_education',
        ]
        self.assertEquals(
            expected_change_fields, response.json()['data']['change_fields'], str(response.content)
        )

        expected_check_data = {
            'address_street_num': 'Jl. Gandaria I No. 1',
            'address_kelurahan': 'Gandaria Utara',
            'address_kecamatan': 'Kebayoran Baru',
            'address_kabupaten': 'Jakarta Selatan',
            'address_provinsi': 'Jawa Barat',
            'address_kodepos': '12140',
            'job_type': 'wiraswasta',
            'job_industry': 'perbankan',
            'job_description': 'mengelola uang',
            'company_name': 'PT. Bank Julo',
            'company_phone_number': '0211234567',
            'payday': 20,
            'payday_change_reason': '',
            'monthly_income': 10000000,
            'monthly_expenses': 5000000,
            'monthly_housing_cost': 2000000,
            'total_current_debt': 1000000,
            'last_education': 'S1',
        }
        check_data = {
            field: value
            for field, value in response.json()['data']['check_data'].items()
            if '_url' not in field
        }
        self.assertEquals(expected_check_data, check_data, str(response.content))

    def test_post_valid(self):
        url = '/api/customer-module/v1/customer-data/change-request/{}/'.format(
            self.change_request.id,
        )
        data = {
            'status': 'approved',
            'approval_note': 'ok',
        }
        response = self.client.post(url, data)
        self.assertEquals(200, response.status_code, str(response.content))
        self.assertTrue(response.json()['success'], str(response.content))

        self.change_request.refresh_from_db()
        self.assertEquals('approved', self.change_request.status)

    def test_post_invalid(self):
        url = '/api/customer-module/v1/customer-data/change-request/{}/'.format(
            self.change_request.id,
        )
        data = {
            'status': 'approved',
        }
        response = self.client.post(url, data)
        self.assertEquals(400, response.status_code, str(response.content))
        self.assertFalse(response.json()['success'], str(response.content))
        self.assertEqual(['Ada data yang salah.'], response.json()['errors'], str(response.content))

        self.change_request.refresh_from_db()
        self.assertEquals('submitted', self.change_request.status)


class TestGetCustomerDeleteUpdatedData(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.CS_ADMIN)
        self.group.save()
        self.user.groups.add(self.group)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.client.force_login(self.user)

    def test_cutomer_id_is_blank(self):
        self.user_1 = AuthUserFactory()
        self.customer_1 = CustomerFactory(
            id=1000014866,
            user=self.user_1,
            phone="086616792879",
            email="test@gmail.com",
            nik='9091600000111122',
        )

        data = {
            "nik": 9091600000111122,
            "email": "test+integration9091679287@julo.co.id",
            "phone": "086616792879",
        }

        url = '/api/customer-module/v1/get-customer-delete-updated-data/'

        response = self.client.post(url, data=data)

        self.assertFalse(response.json()['success'])
        self.assertEqual(response.json()['errors'], ['Silakan periksa input kembali'])

    def test_customer_is_not_valid(self):
        self.user_1 = AuthUserFactory()
        self.customer_1 = CustomerFactory(
            id=1000014866,
            user=self.user_1,
            phone="086616792879",
            email="test@gmail.com",
            nik='9091600000111122',
        )

        data = {
            "nik": 9091600000111122,
            "email": "test+integration9091679287@julo.co.id",
            "phone": "086616792879",
            'customer_id': 1000014866000,
        }
        url = '/api/customer-module/v1/get-customer-delete-updated-data/'

        response = self.client.post(url, data=data)
        err_msg = {'title': "Akun tidak ditemukan", 'msg': "Coba lakukan pencarian kembali"}
        self.assertFalse(response.json()['success'])
        self.assertEqual(response.json()['errors'], [err_msg])

    def test_get_valid_updated_data(self):
        self.user_1 = AuthUserFactory()
        self.customer_1 = CustomerFactory(
            id=1000014866,
            user=self.user_1,
            phone="086616792879",
            email="test@gmail.com",
            nik='9091600000111122',
        )

        data = {
            "nik": 9091600000111122,
            "email": "test@gmail.com",
            "phone": "086616792879",
            'customer_id': 1000014866,
        }
        url = '/api/customer-module/v1/get-customer-delete-updated-data/'

        response = self.client.post(url, data=data)
        split_email = str(self.customer_1.email).split('@')
        edited_email = 'deleteduser{}@{}'.format(self.customer_1.id, split_email[1])

        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data']['nik'], '444444' + str(self.customer_1.id))
        self.assertEqual(response.json()['data']['email'], edited_email)
        self.assertEqual(response.json()['data']['phone'], '44' + str(self.customer_1.id))


class TestAccountDeletetionManual(TestCase):
    def setUp(self):
        group = Group(name="cs_admin")
        group.save()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.user.groups.add(group)

        self.client.force_login(self.user)

    def test_dashboard_manual_cs_admin_get(self):
        url = '/api/customer-module/v1/manual-deletion/'
        response = self.client.get(url)
        redirected_url = (
            settings.CRM_REVAMP_BASE_URL + 'dashboard/cs_admin/manual-deletion/?csrftoken='
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, redirected_url, fetch_redirect_response=False)

    def test_dashboard_manual_cs_admin_post(self):
        url = '/api/customer-module/v1/manual-deletion/'
        data = {"application_id": self.application.pk}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 405)


class TestAccountDeletetionInApp(TestCase):
    def setUp(self):
        group = Group(name="cs_admin")
        group.save()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.user.groups.add(group)

        self.client.force_login(self.user)

    def test_dashboard_cs_admin_get(self):
        url = '/api/customer-module/v1/deletion-request-inapp/'
        response = self.client.get(url)
        redirected_url = (
            settings.CRM_REVAMP_BASE_URL + 'dashboard/cs_admin/deletion-request-inapp/?csrftoken='
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, redirected_url, fetch_redirect_response=False)

    def test_dashboard_cs_admin_post(self):
        url = '/api/customer-module/v1/deletion-request-inapp/'
        data = {"application_id": self.application.pk}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 405)


class TestAccountDeleteMenuInApp(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.CS_ADMIN)
        self.group.save()
        self.user.groups.add(self.group)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.client.force_login(self.user)
        self.url = '/api/customer-module/v1/in-app-deletion-request/'

    def test_account_deletion_requests(self):
        self.request = AccountDeletionRequestFactory()
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['errors'], [])

    def test_account_deletion_requests_post(self):
        self.request = AccountDeletionRequestFactory()
        response = self.client.post(self.url, {})

        self.assertEqual(response.status_code, 405)

    @mock.patch('juloserver.customer_module.views.crm_v1.timezone')
    def test_account_deletion_requests_buttons(self, mock_date):
        mock_date.datetime.return_value = timezone.localtime(timezone.now()).replace(
            year=2023, month=11, day=16
        )

        self.request = AccountDeletionRequestFactory()
        self.request.cdate = timezone.now() - timedelta(days=10)
        self.request.save()
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertTrue(response.json()['data']['results'][0]['show_approve_button'])
        self.assertTrue(response.json()['data']['results'][0]['show_reject_button'])
        self.assertEqual(response.json()['errors'], [])

    def test_account_deletion_request_auto_deletion(self):
        from django.utils.dateparse import parse_datetime

        self.request = AccountDeletionRequestFactory()

        response = self.client.get(self.url)
        self.assertEqual(
            parse_datetime(response.json()['data']['results'][0]['auto_deletion_date']).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            (self.request.cdate + timedelta(days=DELETION_REQUEST_AUTO_APPROVE_DAY_LIMIT)).strftime(
                "%Y-%m-%d 09:00:00"
            ),
        )


class TestAccountDeleteMenuInAppHistory(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.CS_ADMIN)
        self.group.save()
        self.user.groups.add(self.group)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.client.force_login(self.user)
        self.url = '/api/customer-module/v1/in-app-deletion-request-history/'

    def test_account_deletion_requests_approved(self):
        self.request = AccountDeletionRequestFactory(
            request_status=AccountDeletionRequestStatuses.APPROVED
        )
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(
            response.json()['data']['results'][0]['status'], AccountDeletionRequestStatuses.APPROVED
        )
        self.assertEqual(response.json()['errors'], [])

    def test_account_deletion_requests_approved_after_success(self):
        self.request = AccountDeletionRequestFactory(
            request_status=AccountDeletionRequestStatuses.SUCCESS,
            verdict_date=timezone.localtime(timezone.now()),
        )
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(
            response.json()['data']['results'][0]['status'], AccountDeletionRequestStatuses.APPROVED
        )
        self.assertEqual(response.json()['errors'], [])

    def test_account_deletion_requests_auto_approved(self):
        self.request = AccountDeletionRequestFactory(
            request_status=AccountDeletionRequestStatuses.SUCCESS,
        )
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(
            response.json()['data']['results'][0]['status'],
            AccountDeletionRequestStatuses.AUTO_APPROVED,
        )
        self.assertEqual(response.json()['errors'], [])

    def test_account_deletion_requests_post(self):
        self.request = AccountDeletionRequestFactory()
        response = self.client.post(self.url, {})

        self.assertEqual(response.status_code, 405)


class TestUpdateStatusOfAccountDeletionRequest(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.CS_ADMIN)
        self.group.save()
        self.user.groups.add(self.group)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.update_safely(
            application_status_id=ApplicationStatusCodes.LOC_APPROVED,
        )
        self.old_application_status = self.application.application_status_id
        self.application_history = ApplicationHistory.objects.create(
            application=self.application,
            status_old=self.application.application_status_id,
            status_new=ApplicationStatusCodes.CUSTOMER_ON_DELETION,
            change_reason=AccountDeletionStatusChangeReasons.REQUEST_REASON,
        )
        self.application.update_safely(
            application_status_id=ApplicationStatusCodes.CUSTOMER_ON_DELETION,
        )
        self.client.force_login(self.user)
        self.url = '/api/customer-module/v1/in-app-deletion-update-status/'

    def test_no_application_approved(self):
        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        request = AccountDeletionRequestFactory(customer=customer)
        data = {
            "customer_id": customer.id,
            "status": AccountDeletionRequestStatuses.APPROVED,
            "reason": "Test",
        }
        response = self.client.post(self.url, data)
        request.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(request.request_status, AccountDeletionRequestStatuses.APPROVED)
        self.assertEqual(request.verdict_reason, 'Test')
        self.assertIsNotNone(request.verdict_date)

    def test_no_application_rejected(self):
        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        request = AccountDeletionRequestFactory(customer=customer)
        data = {
            "customer_id": customer.id,
            "status": AccountDeletionRequestStatuses.REJECTED,
            "reason": "Test",
        }
        response = self.client.post(self.url, data)
        request.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(request.request_status, AccountDeletionRequestStatuses.REJECTED)
        self.assertEqual(request.verdict_reason, 'Test')
        self.assertIsNotNone(request.verdict_date)

    def test_update_status_in_app_account_deletion_approved(self):
        self.request = AccountDeletionRequestFactory(customer=self.customer)
        data = {
            "customer_id": self.customer.id,
            "status": AccountDeletionRequestStatuses.APPROVED,
            "reason": "Test",
        }
        response = self.client.post(self.url, data)

        self.request.refresh_from_db()
        self.application.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(self.request.request_status, AccountDeletionRequestStatuses.APPROVED)
        self.assertEqual(self.request.verdict_reason, 'Test')
        self.assertIsNotNone(self.request.verdict_date)
        self.assertEqual(
            self.application.application_status_id, ApplicationStatusCodes.CUSTOMER_ON_DELETION
        )

    def test_update_status_in_app_account_deletion_declined(self):
        self.request = AccountDeletionRequestFactory(customer=self.customer)
        data = {
            "customer_id": self.customer.id,
            "status": AccountDeletionRequestStatuses.REJECTED,
            "reason": "Test",
        }
        response = self.client.post(self.url, data)

        self.request.refresh_from_db()

        self.assertEqual(
            self.application.application_status_id, ApplicationStatusCodes.CUSTOMER_ON_DELETION
        )
        self.application.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(self.request.request_status, AccountDeletionRequestStatuses.REJECTED)
        self.assertEqual(self.request.verdict_reason, 'Test')
        self.assertIsNotNone(self.request.verdict_date)
        self.assertEqual(
            self.application.application_status_id,
            self.old_application_status,
        )

    def test_update_status_in_app_account_deletion_invalid_status(self):
        self.request = AccountDeletionRequestFactory(customer=self.customer)
        data = {
            "customer_id": self.customer.id,
            "status": AccountDeletionRequestStatuses.AUTO_APPROVED,
            "reason": "Test",
        }
        response = self.client.post(self.url, data)

        self.request.refresh_from_db()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertEqual(self.request.request_status, AccountDeletionRequestStatuses.PENDING)


class TestIsCustomerDeleteAllowed(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

    @mock.patch('juloserver.customer_module.views.views_api_v1.is_user_delete_allowed')
    def test_not_exists(self, mock_is_user_delete_allowed):
        mock_is_user_delete_allowed.return_value = (
            False,
            FailedAccountDeletionRequestStatuses.NOT_EXISTS,
        )

        url = '/api/customer-module/v1/delete-allowed'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertIsNone(response.json()['data'])
        self.assertEqual(response.json()['errors'][0], 'not_exists:user does not exists')

    @mock.patch('juloserver.customer_module.views.views_api_v1.is_user_delete_allowed')
    def test_active_loans(self, mock_is_user_delete_allowed):
        mock_is_user_delete_allowed.return_value = (
            False,
            FailedAccountDeletionRequestStatuses.ACTIVE_LOANS,
        )

        url = '/api/customer-module/v1/delete-allowed'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertIsNone(response.json()['data'])
        self.assertEqual(
            response.json()['errors'][0], 'active_loan:user have loans on disbursement'
        )

    @mock.patch('juloserver.customer_module.views.views_api_v1.is_user_delete_allowed')
    def test_not_eligible(self, mock_is_user_delete_allowed):
        mock_is_user_delete_allowed.return_value = (
            False,
            FailedAccountDeletionRequestStatuses.ACCOUNT_NOT_ELIGIBLE,
        )

        url = '/api/customer-module/v1/delete-allowed'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertIsNone(response.json()['data'])
        self.assertEqual(
            response.json()['errors'][0], 'not_eligible:user is not eligible to delete account'
        )

    @mock.patch('juloserver.customer_module.views.views_api_v1.is_user_delete_allowed')
    def test_allowed(self, mock_is_user_delete_allowed):
        mock_is_user_delete_allowed.return_value = True, None

        url = '/api/customer-module/v1/delete-allowed'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data'], {'delete_allowed': True})


class TestCustomerDataChangeRequestCustomerInfoView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.CS_ADMIN)
        self.group.save()
        self.user.groups.add(self.group)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationJ1Factory(
            customer=self.customer,
            address_provinsi='Jawa Barat',
            address_kabupaten='Jakarta Selatan',
            address_kecamatan='Kebayoran Baru',
            address_kelurahan='Gandaria Utara',
            address_kodepos='12140',
            address_street_num='Jl. Gandaria I No. 1',
            job_type='wiraswasta',
            job_industry='perbankan',
            job_description='mengelola uang',
            company_name='PT. Bank Julo',
            company_phone_number='0211234567',
            payday=10,
            monthly_income=10000000,
            monthly_expenses=5000000,
            monthly_housing_cost=2000000,
            total_current_debt=1000000,
        )
        self.client.force_login(self.user)

    # def test_get_no_approved_change_request(self):
    #     url = '/api/customer-module/v1/customer-data/change-request/customer-info/{}/'.format(
    #         self.customer.id,
    #     )
    #     response = self.client.get(url)
    #     self.assertEquals(200, response.status_code, str(response.content))
    #     self.assertTrue(response.json()['success'], str(response.content))

    #     expected_data = {
    #         'address_street_num': 'Jl. Gandaria I No. 1',
    #         'address_kelurahan': 'Gandaria Utara',
    #         'address_kecamatan': 'Kebayoran Baru',
    #         'address_kabupaten': 'Jakarta Selatan',
    #         'address_provinsi': 'Jawa Barat',
    #         'address_kodepos': '12140',
    #         'job_type': 'wiraswasta',
    #         'job_industry': 'perbankan',
    #         'job_description': 'mengelola uang',
    #         'company_name': 'PT. Bank Julo',
    #         'company_phone_number': '0211234567',
    #         'payday': 10,
    #         'monthly_income': 10000000,
    #         'monthly_expenses': 5000000,
    #         'monthly_housing_cost': 2000000,
    #         'total_current_debt': 1000000,
    #         'last_education': 'SMA',
    #         'address_transfer_certificate_image_url': None,
    #         'company_proof_image_url': None,
    #         'paystub_image_url': None,
    #         'payday_change_reason': None,
    #         'payday_change_proof_image_url': None
    #     }
    #     self.assertEquals(expected_data, response.json()['data'], str(response.content))

    # def test_get_approved_change_request(self):
    #     CustomerDataChangeRequestFactory(
    #         application=self.application,
    #         customer=self.customer,
    #         status='approved',
    #         payday=20,
    #         monthly_income=1,
    #         monthly_expenses=2,
    #         monthly_housing_cost=3,
    #         total_current_debt=4,
    #         last_education='S1',
    #         job_type='wiraswasta 2',
    #         job_industry='perbankan 2',
    #         job_description='mengelola uang 2',
    #         company_name='PT. Bank Julo 2',
    #         company_phone_number='02112345672',
    #         address=AddressFactory(
    #             latitude=1.2,
    #             longitude=3.4,
    #             provinsi='Jawa Barat',
    #             kabupaten='Jakarta Selatan',
    #             kecamatan='Kebayoran Baru',
    #             kelurahan='Gandaria Utara',
    #             kodepos=12140,
    #             detail='Jl. Gandaria I No. 2',
    #         ),
    #         payday_change_reason=''
    #     )
    #     url = '/api/customer-module/v1/customer-data/change-request/customer-info/{}/'.format(
    #         self.customer.id,
    #     )
    #     response = self.client.get(url)
    #     self.assertEquals(200, response.status_code, str(response.content))
    #     self.assertTrue(response.json()['success'], str(response.content))

    #     expected_data = {
    #         'address_street_num': 'Jl. Gandaria I No. 2',
    #         'address_kelurahan': 'Gandaria Utara',
    #         'address_kecamatan': 'Kebayoran Baru',
    #         'address_kabupaten': 'Jakarta Selatan',
    #         'address_provinsi': 'Jawa Barat',
    #         'address_kodepos': '12140',
    #         'job_type': 'wiraswasta 2',
    #         'job_industry': 'perbankan 2',
    #         'job_description': 'mengelola uang 2',
    #         'company_name': 'PT. Bank Julo 2',
    #         'company_phone_number': '02112345672',
    #         'payday': 20,
    #         'monthly_income': 1,
    #         'monthly_expenses': 2,
    #         'monthly_housing_cost': 3,
    #         'total_current_debt': 4,
    #         'last_education': 'S1',
    #         'address_transfer_certificate_image_url': None,
    #         'company_proof_image_url': None,
    #         'paystub_image_url': None,
    #         'payday_change_reason': ''
    #     }
    #     self.assertEquals(expected_data, response.json()['data'], str(response.content))

    @mock.patch('juloserver.customer_module.views.crm_v1.CustomerDataChangeRequestCRMSerializer')
    def test_post_success(self, mock_serializer_class):
        mock_serializer = mock.MagicMock()
        mock_serializer_class.return_value = mock_serializer
        mock_serializer.is_valid.return_value = True
        url = '/api/customer-module/v1/customer-data/change-request/customer-info/{}/'.format(
            self.customer.id,
        )
        post_data = {"post": "data"}
        response = self.client.post(url, data=post_data)
        self.assertEquals(201, response.status_code, str(response.content))

    @mock.patch('juloserver.customer_module.views.crm_v1.CustomerDataChangeRequestCRMSerializer')
    def test_post_invalid(self, mock_serializer_class):
        mock_serializer = mock.MagicMock()
        mock_serializer_class.return_value = mock_serializer
        mock_serializer.is_valid.return_value = False
        mock_serializer.errors = {'error': 'error message'}
        url = '/api/customer-module/v1/customer-data/change-request/customer-info/{}/'.format(
            self.customer.id,
        )
        post_data = {"post": "data"}
        response = self.client.post(url, data=post_data)
        self.assertEquals(400, response.status_code, str(response.content))
        self.assertEquals(
            {'error': 'error message'},
            response.json()['data'],
            str(response.content),
        )
        self.assertEqual(
            'Ada data yang salah.', response.json()['errors'][0], str(response.content)
        )


class TestRedirectAccountDeletionHistory(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.client.force_login(self.user)

    def test_success_redirect_dashboard_account_deletion_history(self):
        url = '/api/customer-module/v1/account-deletion-histories/'
        response = self.client.get(url)
        redirected_url = (
            settings.CRM_REVAMP_BASE_URL + 'dashboard/account-deletion-histories/?csrftoken='
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, redirected_url, fetch_redirect_response=False)

    def test_fail_redirect_dashboard_account_deletion_history(self):
        url = '/api/customer-module/v1/account-deletion-histories/'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 405)


class TestAccountDeletionHistory(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)

    def test_search_without_query_parameter(self):
        expected_response = {
            "title": "Data tidak ditemukan",
            "msg": "Coba lakukan pencarian kembali",
        }
        response = self.client.get("/api/customer-module/v1/account-deletion-histories/search/?q=")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['errors'][0], expected_response)

    def test_success_search_with_not_found_data(self):
        query = "123456789"
        expected_response = {
            "title": "Data tidak ditemukan",
            "msg": "Coba lakukan pencarian kembali",
        }
        response = self.client.get(
            "/api/customer-module/v1/account-deletion-histories/search/?q=" + query
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['errors'][0], expected_response)

    def test_success_search_with_only_active_customer_data(self):
        self.customer = CustomerFactory(user=self.user, phone="081123123123", is_active=True)
        query = "081123123123"
        response = self.client.get(
            "/api/customer-module/v1/account-deletion-histories/search/?q=" + query
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"])
