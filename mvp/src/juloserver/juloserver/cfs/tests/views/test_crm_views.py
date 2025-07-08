from unittest.mock import patch, MagicMock

from django.test import TestCase
from rest_framework.reverse import reverse

from juloserver.account.tests.factories import AccountFactory
from juloserver.cfs.tests.factories import (
    CfsTierFactory,
    CfsActionFactory,
    CfsActionAssignmentFactory,
    CfsAssignmentVerificationFactory,
    AgentFactory,
)
from juloserver.julo.constants import WorkflowConst, ApplicationStatusCodes
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    ApplicationFactory,
    ProductLineFactory,
    WorkflowFactory,
    StatusLookupFactory,
    CustomerFactory,
    ApplicationJ1Factory,
)

PACKAGE_NAME = 'juloserver.cfs.views.crm_views'


class TestAssignmentVerificationDataListView(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.agent = AgentFactory(user=self.user)
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationJ1Factory(account=self.account, customer=self.customer)
        self.cfs_action = CfsActionFactory()
        self.client.force_login(self.user)

    @patch('juloserver.utilities.paginator.connection')
    def test_timeout(self, mock_connection):
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.__enter__.return_value = mock_cursor

        with patch(
            'juloserver.cfs.constants.AssignmentVerificationDataListViewConstants.TIMEOUT', 300
        ):
            url = reverse('crm_cfs:list')
            self.client.get(url)

            mock_cursor.execute.assert_called_once_with(
                'SET LOCAL statement_timeout TO %s;', [300]
            )

    def test_total_rows(self):
        assignment = CfsActionAssignmentFactory(customer=self.customer, action=self.cfs_action)
        CfsAssignmentVerificationFactory.create_batch(
            51,
            cfs_action_assignment=assignment,
            account=self.account,
        )

        url = reverse('crm_cfs:list')
        response = self.client.get(url)

        self.assertContains(response, 'Halaman 1 dari 2 - Total 51.')

    def test_total_rows_when_application_deleted(self):
        customer = CustomerFactory()
        account = AccountFactory(customer=customer)
        application = ApplicationFactory(account=account, customer=customer, is_deleted=True)
        assignment = CfsActionAssignmentFactory(customer=customer, action=self.cfs_action)
        CfsAssignmentVerificationFactory.create_batch(
            20,
            cfs_action_assignment=assignment,
            account=account,
        )

        url = reverse('crm_cfs:list')
        response = self.client.get(url)

        self.assertContains(response, 'Kosong - Tidak ada Data')

    def test_sort_state_is_saved(self):
        assignment = CfsActionAssignmentFactory(customer=self.customer, action=self.cfs_action)
        CfsAssignmentVerificationFactory.create_batch(
            2,
            cfs_action_assignment=assignment,
            account=self.account,
        )

        url = reverse('crm_cfs:list')
        first_response = self.client.get(url, data={'sort_q': '-cdate'})
        second_response = self.client.get(url)

        self.assertContains(first_response, '<input id="id_sort_q" name="sort_q" type="hidden" value="-cdate" />')
        self.assertContains(second_response, '<input id="id_sort_q" name="sort_q" type="hidden" value="-cdate" />')


class TestAjaxAppStatusTab(TestCase):
    def setUp(self):
        self.application = ApplicationFactory(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE)
        )
        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=190)
        )
        self.auth_user = AuthUserFactory()
        self.agent = AgentFactory(user=self.auth_user)
        self.cfs_tier = CfsTierFactory(
            id=1,
            name='Tier Name',
            point=0,
            cashback_multiplier=1.2,
            referral_bonus=1000,
        )
        self.client.force_login(self.auth_user)

    def test_method_not_allowed(self):
        url = reverse('crm_cfs:ajax_app_status_tab', kwargs={
            'application_pk': self.application.pk
        })
        response = self.client.post(url)

        self.assertEqual(405, response.status_code)

    @patch(f'{PACKAGE_NAME}.get_cfs_tier_info')
    def test_render_cfs_complete(self, mock_get_cfs_tier_info):
        self.cfs_tier.update_safely(
            qris=True, ppob=True, ecommerce=True, tarik_dana=True, dompet_digital=True,
            transfer_dana=True, pencairan_cashback=True
        )
        mock_get_cfs_tier_info.return_value = 500, self.cfs_tier

        url = reverse('crm_cfs:ajax_app_status_tab', kwargs={
            'application_pk': self.application.pk
        })
        response = self.client.get(url)

        self.assertEqual(200, response.status_code)
        self.assertContains(response, '500')
        self.assertContains(response, 'Tier Name')
        self.assertContains(response, '1.2x')
        self.assertContains(response, 'Rp 1.000')
        self.assertContains(response, 'QRIS')
        self.assertContains(response, 'PPOB')
        self.assertContains(response, 'E-Commerce')
        self.assertContains(response, 'Tarik Dana')
        self.assertContains(response, 'Transfer Dana')
        self.assertContains(response, 'Dompet Digital')
        self.assertContains(response, 'Pencairan Cashback')

    def test_cfs_not_eligible(self):
        self.application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB),
            workflow=WorkflowFactory(name=WorkflowConst.GRAB)
        )

        url = reverse('crm_cfs:ajax_app_status_tab', kwargs={
            'application_pk': self.application.pk
        })
        response = self.client.get(url)

        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'Not eligible for CFS')
        self.assertNotContains(response, 'Tier')
        self.assertNotContains(response, 'JScore')

    @patch(f'{PACKAGE_NAME}.get_cfs_tier_info')
    def test_cfs_no_benefit(self, mock_get_cfs_tier_info):
        self.cfs_tier.update_safely(
            qris=False, ppob=False, ecommerce=False, tarik_dana=False, dompet_digital=False,
            transfer_dana=False, pencairan_cashback=False
        )
        mock_get_cfs_tier_info.return_value = 500, self.cfs_tier

        url = reverse('crm_cfs:ajax_app_status_tab', kwargs={
            'application_pk': self.application.pk
        })
        response = self.client.get(url)

        self.assertEqual(200, response.status_code)
        self.assertNotContains(response, 'QRIS')
        self.assertNotContains(response, 'PPOB')
        self.assertNotContains(response, 'E-Commerce')
        self.assertNotContains(response, 'Tarik Dana')
        self.assertNotContains(response, 'Transfer Dana')
        self.assertNotContains(response, 'Dompet Digital')
        self.assertNotContains(response, 'Pencairan Cashback')


class TestAssignmentVerificationCheckLockStatus(TestCase):
    def setUp(self):
        self.auth_user = AuthUserFactory()
        self.agent = AgentFactory(user=self.auth_user, user_extension='test_user')
        self.client.force_login(self.auth_user)

    def test_with_no_lock(self):
        assignment_verification = CfsAssignmentVerificationFactory()
        url = reverse('crm_cfs:assignment_verification.check_lock_status',
                      args=[assignment_verification.pk])

        response = self.client.get(url)

        self.assertEqual(200, response.status_code)

        json_data = response.json()
        self.assertFalse(json_data['data']['is_locked'], json_data)
        self.assertFalse(json_data['data']['is_locked_by_me'], json_data)
        self.assertIsNone(json_data['data']['locked_by_info'], json_data)

    def test_with_lock(self):
        other_agent = AgentFactory(user_extension='other-user')
        assignment_verification = CfsAssignmentVerificationFactory(locked_by=other_agent)
        url = reverse('crm_cfs:assignment_verification.check_lock_status',
                      args=[assignment_verification.pk])

        response = self.client.get(url)

        self.assertEqual(200, response.status_code)

        json_data = response.json()
        self.assertTrue(json_data['data']['is_locked'], json_data)
        self.assertFalse(json_data['data']['is_locked_by_me'], json_data)
        self.assertEqual('other-user', json_data['data']['locked_by_info'], json_data)

    def test_with_self_lock(self):
        assignment_verification = CfsAssignmentVerificationFactory(locked_by=self.agent)
        url = reverse('crm_cfs:assignment_verification.check_lock_status',
                      args=[assignment_verification.pk])

        response = self.client.get(url)

        self.assertEqual(200, response.status_code)

        json_data = response.json()
        self.assertTrue(json_data['data']['is_locked'], json_data)
        self.assertTrue(json_data['data']['is_locked_by_me'], json_data)
        self.assertEqual('test_user', json_data['data']['locked_by_info'], json_data)


class TestAssignmentVerificationLock(TestCase):
    def setUp(self):
        self.auth_user = AuthUserFactory()
        self.agent = AgentFactory(user=self.auth_user, user_extension='test_user')
        self.client.force_login(self.auth_user)

    def test_success_lock(self):
        assignment_verification = CfsAssignmentVerificationFactory(locked_by=None)

        url = reverse('crm_cfs:assignment_verification.lock', [assignment_verification.pk])
        response = self.client.post(url)

        self.assertEqual(201, response.status_code)

    def test_fail_lock_already_locked(self):
        assignment_verification = CfsAssignmentVerificationFactory(locked_by=self.agent)

        url = reverse('crm_cfs:assignment_verification.lock', [assignment_verification.pk])
        response = self.client.post(url)

        self.assertEqual(423, response.status_code)

    def test_not_found(self):
        url = reverse('crm_cfs:assignment_verification.lock', [0])
        response = self.client.post(url)

        self.assertEqual(404, response.status_code)


class TestAssignmentVerificationUnlock(TestCase):
    def setUp(self):
        self.auth_user = AuthUserFactory()
        self.agent = AgentFactory(user=self.auth_user, user_extension='test_user')
        self.client.force_login(self.auth_user)

    def test_unlock_self(self):
        assignment_verification = CfsAssignmentVerificationFactory(locked_by=self.agent)

        url = reverse('crm_cfs:assignment_verification.unlock', [assignment_verification.pk])
        response = self.client.post(url)
        assignment_verification.refresh_from_db()

        self.assertEqual(200, response.status_code)
        self.assertIsNone(assignment_verification.locked_by)

    def test_unlock_other(self):
        other_agent = AgentFactory(user_extension='other-user')
        assignment_verification = CfsAssignmentVerificationFactory(locked_by=other_agent)

        url = reverse('crm_cfs:assignment_verification.unlock', [assignment_verification.pk])
        response = self.client.post(url)
        assignment_verification.refresh_from_db()

        self.assertEqual(200, response.status_code)
        self.assertIsNone(assignment_verification.locked_by)

    def test_not_found(self):
        url = reverse('crm_cfs:assignment_verification.unlock', [0])
        response = self.client.post(url)

        self.assertEqual(200, response.status_code)
