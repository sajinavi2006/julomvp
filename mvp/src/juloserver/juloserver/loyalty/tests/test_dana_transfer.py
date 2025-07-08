from unittest.mock import Mock

from django.conf import settings
from juloserver.julo.utils import encrypt_order_id_sepulsa

from juloserver.julo.models import SepulsaTransaction

from juloserver.julo.services2.sepulsa import SepulsaService
from rest_framework.test import APIClient, APITestCase
from mock import patch

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
    StatusLookupFactory,
    SepulsaTransactionFactory, SepulsaProductFactory,
)
from juloserver.loyalty.constants import (
    PointRedeemReferenceTypeConst,
)
from juloserver.loyalty.models import PointHistory, PointUsageHistory
from juloserver.loyalty.tests.factories import (
    LoyaltyPointFactory,
    PointRedeemFSFactory,
    PointUsageHistoryFactory,
)
from juloserver.payment_point.constants import SepulsaProductType, SepulsaProductCategory
from juloserver.pin.tests.factories import CustomerPinFactory


class TestTransferToDana(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        CustomerPinFactory(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.loyalty_point = LoyaltyPointFactory(customer=self.customer, total_point=110_000)
        self.user.set_password('123456')
        self.user.save()
        self.user.refresh_from_db()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.point_redeem_fs = PointRedeemFSFactory(parameters={
            PointRedeemReferenceTypeConst.DANA_TRANSFER: {
                'is_active': True,
                'julo_fee': 0,
                'minimum_withdrawal': 10_000
            }
        })
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.status = StatusLookupFactory()
        self.status.status_code = 220
        self.status.save()
        self.sepulsa_product = SepulsaProductFactory(
            type=SepulsaProductType.E_WALLET_OPEN_PAYMENT, category=SepulsaProductCategory.DANA,
            is_active=True,
            customer_price_regular=500, partner_price=500
        )

    @patch('juloserver.loyalty.views.views_api_v1.process_transfer_loyalty_point_to_dana')
    def test_dana_service_success_basic(self, mock_process_transfer_loyalty_point_to_dana):
        point_usage_history = PointUsageHistoryFactory()
        sepulsa_transaction = SepulsaTransactionFactory(
            product=self.sepulsa_product,
            customer_price_regular=100_500,
            partner_price=500,
            admin_fee=0,
            transaction_status='pending'
        )
        mock_process_transfer_loyalty_point_to_dana.return_value = (
            sepulsa_transaction, point_usage_history
        )
        data = {
            'pin': 123456,
            'mobile_phone_number': '08987893218',
            'nominal': 100_000
        }
        response = self.client.post('/api/loyalty/v1/dana_transfer', data=data)
        self.assertEqual(response.status_code, 200)


    @patch('juloserver.julo.services2.sepulsa.get_julo_sepulsa_client')
    def test_dana_service_success_details(self, mock_get_julo_sepulsa_client):
        mock_client = Mock()
        mock_client.inquiry_ewallet_open_payment_transaction.return_value = False
        mock_get_julo_sepulsa_client.return_value = mock_client
        mock_get_julo_sepulsa_client.return_value.get_balance_and_check_minimum.return_value = 1_000_000, True
        mock_get_julo_sepulsa_client.return_value.create_transaction.return_value = {
            "customer_id": "081298700001",
            "product": {
                "label": "Ewallet Open Payment",
                "type": "ewallet_open_payment",
                "operator": "DANA"
            },
            "price": 500,
            "transaction_id": "1",
            "response_code": "10",
            "created": 1632322549,
            "data": {
                "admin_charge": 500
            }
        }

        services = SepulsaService()
        services.julo_sepulsa_client = mock_get_julo_sepulsa_client

        data = {
            'pin': 123456,
            'mobile_phone_number': '08987893218',
            'nominal': 100_000
        }
        response = self.client.post('/api/loyalty/v1/dana_transfer', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['errors'],
            ['Pencairan point melalui metode ini untuk sementara tidak dapat dilakukan']
        )
        mock_client.inquiry_ewallet_open_payment_transaction.assert_called_with(
            mobile_phone_number='08987893218',
            product_code=self.sepulsa_product.product_id,
            amount=99_500
        )
        mock_client.inquiry_ewallet_open_payment_transaction.return_value = True
        response = self.client.post('/api/loyalty/v1/dana_transfer', data=data)
        self.assertEqual(response.status_code, 200)

        sepulsa_transaction = SepulsaTransaction.objects.filter(
            product_id=self.sepulsa_product.id
        ).last()
        settings.SEPULSA_FERNET_KEY = (
            'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx='
        )
        order_str = '%s-%s-%s' % (
            sepulsa_transaction.id,
            str(sepulsa_transaction.product.product_id),
            sepulsa_transaction.customer_id)
        order_id = encrypt_order_id_sepulsa(order_str)
        sepulsa_transaction.update_safely(order_str)
        self.assertEqual(response.data['data'], {
            'id': sepulsa_transaction.id,
            'nominal_amount': 100_000,
            'transfer_status': 'pending',
            'transfer_amount': 99_500,
            'admin_fee': 500,
            'point_amount': 100_000,
            "mobile_phone_number": '08987893218',
        })
        ph = PointHistory.objects.get(
            customer_id=self.loyalty_point.customer_id, change_reason='Dana transfer'
        )
        puh = PointUsageHistory.objects.get(point_history_id=ph.id)
        expect_point_usage_history = {
            "reference_type": "dana_transfer",
            "reference_id": puh.reference_id,
            "point_amount": 100_000,
            "exchange_amount": 100_000,
            "exchange_amount_unit": "rupiah",
            "extra_data": {
                "julo_fee": 0,
                "partner_fee": 500
            }
        }
        self.assertEqual(expect_point_usage_history, {
            "reference_type": puh.reference_type,
            "reference_id": puh.reference_id,
            "point_amount": puh.point_amount,
            "exchange_amount": puh.exchange_amount,
            "exchange_amount_unit": puh.exchange_amount_unit,
            "extra_data": puh.extra_data
        })
        self.loyalty_point.refresh_from_db()
        self.assertEqual(self.loyalty_point.total_point, 10_000)

        # callback and make the transaction success
        response = self.client.post(
            '/api/integration/v1/callbacks/sepulsa/transaction', data={
                'response_code': '20', # failed
                'transaction_id': '1',
                'order_id': order_id,
            }, format='json'
        )
        self.assertEqual(response.data['message'], 'Update transaction success.')
        sepulsa_transaction.refresh_from_db()
        self.assertEqual(sepulsa_transaction.transaction_status, 'failed')
        ph = PointHistory.objects.get(
            customer_id=self.loyalty_point.customer_id, change_reason='Refunded dana transfer'
        )
        expected_refunded_point_history = {
            'customer_id': self.customer.id,
            'change_reason': 'Refunded dana transfer',
            'old_point': 10_000,
            'new_point': 110_000,
        }
        self.assertEqual(expected_refunded_point_history, {
            'customer_id': self.customer.id,
            'change_reason': ph.change_reason,
            'old_point': ph.old_point,
            'new_point': ph.new_point,
        })

        response = self.client.post('/api/loyalty/v1/check_dana_transfer', data={
            'transaction_id': sepulsa_transaction.id,
        })
        self.assertEqual(response.status_code, 200)
        expected_response = {
            'id': sepulsa_transaction.id,
            'transfer_status': 'failed',
            'nominal_amount': 100_000,
            'transfer_amount': 99_500,
            'admin_fee': 500,
            'point_amount': 100_000,
            'mobile_phone_number': '08987893218',
        }

        self.assertEqual(response.data['data'], expected_response)

    @patch('juloserver.julo.services2.sepulsa.get_julo_sepulsa_client')
    def test_dana_service_failed_with_minimum_withdrawal(self, mock_get_julo_sepulsa_client):
        mock_get_julo_sepulsa_client.return_value.get_balance_and_check_minimum.return_value = 0, False
        data = {
            'pin': 123456,
            'mobile_phone_number': '08987893218',
            'nominal': 1_000
        }
        response = self.client.post('/api/loyalty/v1/dana_transfer', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['errors'],
            ['Pencairan point melalui metode ini untuk sementara tidak dapat dilakukan']
        )
