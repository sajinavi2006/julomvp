from __future__ import print_function

import mock
from mock import patch
from juloserver.followthemoney.models import LenderBucket
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory, PartnerFactory, ProductLineFactory, ProductLookupFactory, StatusLookupFactory,
    FeatureSettingFactory,
    WorkflowFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory
)
from juloserver.followthemoney.factories import (
    LenderCurrentFactory,
    LenderBalanceCurrentFactory,
    LenderBucketFactory,
)
from juloserver.dana.constants import DANA_ACCOUNT_LOOKUP_NAME
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.services2.redis_helper import MockRedisHelper


class TestListApplication(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.application = ApplicationFactory(customer=self.customer)
        self.partner = PartnerFactory(user=self.user)
        self.lender = LenderCurrentFactory(user=self.user)
        self.product_line = ProductLineFactory(product_line_code=12345)
        self.product_look_up = ProductLookupFactory(product_line=self.product_line)
        self.loan = LoanFactory(
            application=self.application,
            lender=self.lender,
            product=self.product_look_up
        )
        self.lender_bucket = LenderBucketFactory(
            loan_ids={"approved": [self.loan.pk], "rejected": []},
            lender_bucket_xid="1232321321321"
        )
        self.hide_partner_loan_fs = FeatureSettingFactory(
            feature_name='hide_partner_loan',
            category='followthemoney',
            is_active=False
        )

    def test_list_application(self):
        self.loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL)
        self.loan.save()

        # filter by product_line_code
        response = self.client.get(
            '/api/followthemoney/v1/list_application/'
            '?product_line_code={}'.format(self.product_line.product_line_code)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']), 1)
        response = self.client.get('/api/followthemoney/v1/list_application/?product_line_code=1')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']), 0)

        # disable hide_partner_loan fs
        self.hide_partner_loan_fs.is_active = False
        self.hide_partner_loan_fs.save()
        response = self.client.get('/api/followthemoney/v1/list_application/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']), 1)

        # enable hide_partner_loan fs but hidden_product_line_codes does not contain 12345
        self.hide_partner_loan_fs.is_active = True
        self.hide_partner_loan_fs.parameters = {'hidden_product_line_codes': [999]}
        self.hide_partner_loan_fs.save()
        response = self.client.get('/api/followthemoney/v1/list_application/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']), 1)

        # enable hide_partner_loan fs and hidden_product_line_codes contain 12345
        self.hide_partner_loan_fs.parameters = {
            'hidden_product_line_codes': [999, self.product_line.product_line_code]
        }
        self.hide_partner_loan_fs.save()
        response = self.client.get('/api/followthemoney/v1/list_application/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']), 0)

    @patch('juloserver.followthemoney.services.get_redis_client')
    def test_list_application_past(self, _mock_get_redis_client):
        _mock_get_redis_client.return_value = MockRedisHelper()
        self.loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)
        self.loan.save()

        # filter by product_line_code
        response = self.client.get(
            '/api/followthemoney/v1/list_application_past/'
            '?product_line_code={}'.format(self.product_line.product_line_code)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']), 1)
        self.assertEqual(
            response.data['data'][0]['lender_bucket_xid'], str(self.lender_bucket.lender_bucket_xid)
        )
        response = self.client.get(
            '/api/followthemoney/v1/list_application_past/?product_line_code=1'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']), 0)

        # disable hide_partner_loan fs
        self.hide_partner_loan_fs.is_active = False
        self.hide_partner_loan_fs.save()
        response = self.client.get('/api/followthemoney/v1/list_application_past/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']), 1)

        # enable hide_partner_loan fs but hidden_product_line_codes does not contain 12345
        self.hide_partner_loan_fs.is_active = True
        self.hide_partner_loan_fs.parameters = {'hidden_product_line_codes': [999]}
        self.hide_partner_loan_fs.save()
        response = self.client.get('/api/followthemoney/v1/list_application_past/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']), 1)

        # enable hide_partner_loan fs and hidden_product_line_codes contain 12345
        self.hide_partner_loan_fs.parameters = {
            'hidden_product_line_codes': [999, self.product_line.product_line_code]
        }
        self.hide_partner_loan_fs.save()
        response = self.client.get('/api/followthemoney/v1/list_application_past/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']), 0)


class TestPerformanceSummary(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        ApplicationFactory(customer=self.customer)
        PartnerFactory(user=self.user)
        self.lender = LenderCurrentFactory(user=self.user)
        LenderBalanceCurrentFactory(lender=self.lender, available_balance=100000000)

    @patch('juloserver.followthemoney.views.application_views.get_total_outstanding_for_lender')
    def test_performance_summary(self, mock_get_total_outstanding_for_lender):
        mock_get_total_outstanding_for_lender.return_value = 123
        response = self.client.get('/api/followthemoney/v1/performance_summary/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['total_outstanding'], 123)


class TestDanaLenderBucketCreationFlow(APITestCase):
    def setUp(self) -> None:
        self.url = '/api/followthemoney/v1/create_bucket/'
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='dana')
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.DANA, handler='DanaWorkflowHandler')
        self.account_lookup = AccountLookupFactory(workflow=self.workflow, name=DANA_ACCOUNT_LOOKUP_NAME)
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )
        self.client = APIClient()
        self.client.force_login(self.user)
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.loan = LoanFactory(
            customer=self.customer,
            loan_amount=9000000,
            loan_duration=180,
            account=self.account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL)
        )

    @patch('juloserver.followthemoney.services.get_redis_client')
    @mock.patch('juloserver.followthemoney.views.j1_views.dana_update_loan_status_and_loan_history')
    @mock.patch('juloserver.followthemoney.views.j1_views.dana_disbursement_trigger_task')
    def test_api_view(
        self,
        mock_dana_disbursement_trigger_task,
        mock_dana_update_loan_status_and_loan_history,
        _mock_get_redis_client
    ):
        _mock_get_redis_client.return_value = MockRedisHelper()
        data = {
            "application_ids": {
                "approved": [self.loan.id],
                "rejected": []
            }
        }
        mock_dana_disbursement_trigger_task.return_value = None
        mock_dana_update_loan_status_and_loan_history.return_value = None
        response = self.client.post(self.url, data=data, format='json')

        # make sure update to 212 is properly called
        mock_dana_update_loan_status_and_loan_history.assert_called()
        self.assertEqual(response.status_code, 200)
        assert LenderBucket.objects.count() == 1

        # second request with the same loan_id => not genreate lender bucket
        response = self.client.post(self.url, data=data, format='json')
        assert response.status_code == 200
        # 3rd request with the same loan_id => not genreate lender bucket
        response = self.client.post(self.url, data=data, format='json')
        assert response.status_code == 200

        assert LenderBucket.objects.count() == 1
