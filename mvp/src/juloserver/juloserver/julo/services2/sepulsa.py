from builtins import object
import logging
import json
from datetime import datetime
from django.utils import timezone
from django.forms.models import model_to_dict

from ..clients import get_julo_sepulsa_client
from ..clients.sepulsa import SepulsaResponseCodes
from ..exceptions import JuloException
from ..models import SepulsaProduct
from ..models import SepulsaTransaction
from ..models import SepulsaTransactionHistory
from ..utils import fulfil_optional_response_sepulsa
from juloserver.julo.clients.constants import SepulsaProductType
from juloserver.payment_point.models import TrainTransaction

logger = logging.getLogger(__name__)


class SepulsaService(object):

    def __init__(self):
        self.julo_sepulsa_client = get_julo_sepulsa_client()

    def is_balance_enough_for_transaction(self, price):
        from juloserver.julo.tasks import warn_sepulsa_balance_low_once_daily_async
        julo_sepulsa_client = self.julo_sepulsa_client
        balance, is_below_minimum = julo_sepulsa_client.get_balance_and_check_minimum()
        if is_below_minimum:
            warn_sepulsa_balance_low_once_daily_async.delay(balance)
        return balance > price

    def create_transaction_sepulsa(self, customer, product, phone_number=None, account_name=None,
                                   customer_number=None, transaction_status=None, loan=None,
                                   retry_times=None, partner_price=None, customer_price=None,
                                   customer_price_regular=None, category=None, customer_amount=None,
                                   partner_amount=None, admin_fee=None, service_fee=None,
                                   collection_fee=None, paid_period=None):
        sepulsa_transaction = SepulsaTransaction.objects.create(
            product=product,
            customer=customer,
            phone_number=phone_number,
            customer_number=customer_number,
            account_name=account_name,
            is_order_created=False,
            transaction_status=transaction_status,
            loan=loan,
            retry_times=retry_times,
            partner_price=partner_price,
            customer_price=customer_price,
            customer_price_regular=customer_price_regular,
            paid_period=paid_period,
            category=category,
            customer_amount=customer_amount,
            partner_amount=partner_amount,
            admin_fee=admin_fee,
            service_fee=service_fee,
            collection_fee=collection_fee
        )
        return sepulsa_transaction

    def update_sepulsa_transaction_with_history_accordingly(self, sepulsa_transaction, transaction_type, payload):
        payload = fulfil_optional_response_sepulsa(payload)
        before_sepulsa_transaction = model_to_dict(sepulsa_transaction)
        if payload['response_code'] in SepulsaResponseCodes.FAILED or not payload['response_code']:
            sepulsa_transaction.transaction_status = 'failed'
        elif payload['response_code'] in SepulsaResponseCodes.SUCCESS:
            sepulsa_transaction.transaction_status = 'success'
            sepulsa_transaction.transaction_success_date = datetime.today()
        elif payload['response_code'] in SepulsaResponseCodes.PENDING:
            sepulsa_transaction.transaction_status = 'pending'
        else:
            raise JuloException('Sepulsa response code not found (%s)' % (payload))
        sepulsa_transaction.is_order_created = True
        sepulsa_transaction.transaction_code = payload['transaction_id']
        sepulsa_transaction.response_code = payload['response_code']
        sepulsa_transaction.serial_number = payload['serial_number']
        sepulsa_transaction.transaction_token = payload['token']
        if sepulsa_transaction.product.type == SepulsaProductType.E_WALLET_OPEN_PAYMENT:
            if transaction_type == 'create_transaction':
                sepulsa_transaction.partner_price = payload.get("data", {}).get("admin_charge")
        sepulsa_transaction.save()
        sepulsa_transaction_history = SepulsaTransactionHistory.objects.create(
            sepulsa_transaction=sepulsa_transaction,
            before_transaction_status=before_sepulsa_transaction['transaction_status'],
            before_transaction_success_date=before_sepulsa_transaction['transaction_success_date'],
            before_response_code=before_sepulsa_transaction['response_code'],
            after_transaction_status=sepulsa_transaction.transaction_status,
            after_transaction_success_date=sepulsa_transaction.transaction_success_date,
            after_response_code=sepulsa_transaction.response_code,
            transaction_type=transaction_type,
            request_payload=json.dumps(payload)
        )
        logger.info({
            'action': 'process_save_sepulsa_transaction_history',
            'sepulsa_transaction': sepulsa_transaction,
            'sepulsa_transaction_history': sepulsa_transaction_history,
        })
        return sepulsa_transaction

    def get_account_electricity_info(self, meter_number, product_id):
        product = SepulsaProduct.objects.filter(pk=int(product_id)).last()
        if not product:
            raise JuloException('Sepulsa product not found, with id (%s)' % (product_id))
        hour = timezone.localtime(timezone.now()).hour
        if hour in SepulsaResponseCodes.PLN_HOURS_SERVER_OFF:
            raise JuloException(
                'Saat ini Anda tidak dapat melakukan pembelian produk dari PLN. Silakan kembali setelah pukul 01:00 WIB.'
            )
        julo_sepulsa_client = self.julo_sepulsa_client
        response = julo_sepulsa_client.get_account_electricity(meter_number, product.product_id)
        return response

    def get_sepulsa_product(self, manual_types=None):
        default_types = [
            SepulsaProductType.MOBILE,
            SepulsaProductType.ELECTRICITY,
            SepulsaProductType.BPJS_KESEHATAN,
            SepulsaProductType.E_WALLET,
            SepulsaProductType.MOBILE_POSTPAID,
            SepulsaProductType.ELECTRICITY_POSTPAID,
            SepulsaProductType.TRAIN_TICKET,
        ]
        types = manual_types or default_types

        data_products = []
        for type in types:
            response = self.julo_sepulsa_client.get_product_list(type)
            if not response:
                continue
            for sepulsa_product in response['list']:
                data_products.append(sepulsa_product)
        return data_products

    def mapping_train_transaction(self, sepulsa_transaction):
        train_transaction = TrainTransaction.objects.filter(
            customer=sepulsa_transaction.customer,
            sepulsa_transaction__isnull=True,
        ).last()
        if train_transaction:
            train_transaction.update_safely(sepulsa_transaction=sepulsa_transaction)
            sepulsa_transaction.update_safely(phone_number=train_transaction.account_mobile_phone)
