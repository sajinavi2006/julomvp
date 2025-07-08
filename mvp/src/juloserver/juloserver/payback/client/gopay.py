from builtins import str
from builtins import object
import base64
import uuid
import requests
import json
import logging

from juloserver.payback.exceptions import GopayError
from juloserver.payback.models import GopayAccountLinkStatus
from juloserver.payback.constants import GopayAccountStatusConst

from juloserver.autodebet.models import AutodebetAPILog
from juloserver.autodebet.constants import VendorConst


logger = logging.getLogger(__name__)

class GopayClient(object):
    def __init__(self, server_key, base_url, base_snap_url):
        self.server_key = server_key
        self.auth_string = base64.b64encode((self.server_key + ':').encode()).decode()
        self.base_url = base_url
        self.base_snap_url = base_snap_url

    def build_api_header(self):
        return {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': 'Basic %s' % (self.auth_string,)
        }

    def init_transaction(self, req_data):
        url = '{}/snap/v1/transactions'.format(self.base_snap_url)
        customer = req_data['customer']
        payment = req_data['payment']

        fullname = ""
        email = ""
        phone = ""
        if customer:
            if customer.fullname:
                fullname = customer.fullname
            if customer.email:
                email = customer.email
            if customer.phone:
                phone = customer.phone

        req_data = {
            'transaction_details': {
                'order_id': str(uuid.uuid4()),
                'gross_amount': req_data['amount']
            },
            'item_details': [{
                'id': 'PT' + str(payment.id),
                'name': 'Julo Loan',
                'price': req_data['amount'],
                'quantity': 1,
            }],
            'customer_details': {
                'first_name': fullname,
                'email': email,
                'phone': phone
            },
            'enabled_payments': ['gopay']
        }

        response = requests.post(url, headers=self.build_api_header(), json=req_data)
        if response.status_code != 201:
            raise GopayError(response.json())

        # order_id is used as transaction_id
        return {
            'transaction_id': req_data['transaction_details']['order_id'],
            'amount': req_data['transaction_details']['gross_amount'],
            'server_res': response.json()
        }

    def get_status(self, req_data):
        url = '{}/v2/{}/status'.format(self.base_url, req_data['transaction_id'])
        response = requests.get(url, headers=self.build_api_header())

        if response.status_code != 200:
            raise GopayError(response.json())

        return response.json()

    def create_pay_account(self, req_data):
        url = '{}/v2/pay/account'.format(self.base_url)
        response = requests.post(url, headers=self.build_api_header(), json=req_data)

        if response.status_code != 200:
            raise GopayError(response.json())

        return response.json()

    def get_pay_account(self, pay_account_id, store_log_autodebet=False):
        url = '{}/v2/pay/account/{}'.format(self.base_url, pay_account_id)
        response = requests.get(url, headers=self.build_api_header())

        if response.status_code != 200:
            raise GopayError(response.json())

        if store_log_autodebet:
            self._record_api_log(pay_account_id, response, 'GET {}'.format(url))

        return response.json()

    def unbind_pay_account(self, pay_account_id):
        url = '{}/v2/pay/account/{}/unbind'.format(self.base_url, pay_account_id)
        response = requests.post(url, headers=self.build_api_header())

        if response.status_code != 200:
            raise GopayError(response.json())

        return response.json()

    def gopay_tokenization_init_transaction(self, req_data):
        url = '{}/v2/charge'.format(self.base_url)
        response = requests.post(url, headers=self.build_api_header(), json=req_data)

        if response.status_code != 200:
            raise GopayError(response.json())

        return response.json()

    def create_subscription_gopay_autodebet(self, pay_account_id, account_payment, req_data):
        # importing here due to circular import
        from juloserver.autodebet.tasks import (
            send_slack_notify_autodebet_gopay_failed_subscription_and_deduction
        )
        url = '{}/v1/subscriptions'.format(self.base_url)
        response = requests.post(url, headers=self.build_api_header(), json=req_data)

        self._record_api_log(
            pay_account_id,
            response,
            'POST {}'.format(url),
            req_data,
            account_payment
        )

        if response.status_code != 200:
            error_message = response.json()['status_message']
            if 'validation_messages' in response.json():
                error_message = response.json()['status_message'] + \
                    response.json()['validation_messages'][0]
            send_slack_notify_autodebet_gopay_failed_subscription_and_deduction.delay(
                account_payment.account.id,
                account_payment.id,
                error_message
            )
            raise GopayError(response.json())

        return response.json()

    def get_subscription_gopay_autodebet(self, subscription_id, pay_account_id):
        url = '{}/v1/subscriptions/{}'.format(self.base_url, subscription_id)
        response = requests.get(url, headers=self.build_api_header())

        if response.status_code != 200:
            raise GopayError(response.json())

        self._record_api_log(pay_account_id, response, 'GET {}'.format(url))

        return response.json()

    def update_subscription_gopay_autodebet(self, gopay_autodebet_transaction, req_data):
        # importing here due to circular import
        from juloserver.autodebet.tasks import (
            send_slack_notify_autodebet_gopay_failed_subscription_and_deduction
        )
        url = '{}/v1/subscriptions/{}'.format(
            self.base_url, gopay_autodebet_transaction.subscription_id)
        response = requests.patch(url, headers=self.build_api_header(), json=req_data)

        self._record_api_log(
            gopay_autodebet_transaction.gopay_account.pay_account_id,
            response,
            'PATCH {}'.format(url),
            req_data,
            gopay_autodebet_transaction.account_payment
        )

        if response.status_code != 200:
            send_slack_notify_autodebet_gopay_failed_subscription_and_deduction.delay(
                gopay_autodebet_transaction.account_payment.account.id,
                gopay_autodebet_transaction.account_payment.id,
                response.json()['status_message'],
                gopay_autodebet_transaction.subscription_id
            )
            raise GopayError(response.json())

        return response.json()

    def _record_api_log(self, pay_account_id, response, request_type, request=None, account_payment=None):
        gopay_account_link = GopayAccountLinkStatus.objects.filter(
            pay_account_id=pay_account_id).last()
        AutodebetAPILog.objects.create(
            vendor=VendorConst.GOPAY,
            http_status_code=response.status_code,
            request_type=request_type,
            response=json.dumps(response.json()) if response else None,
            account_id=gopay_account_link.account.id,
            request=json.dumps(request) if request else None,
            account_payment_id=account_payment.id if account_payment else None,
        )

    def disable_subscription_gopay_autodebet(self, gopay_autodebet_transaction):
        # importing here due to circular import
        from juloserver.autodebet.tasks import (
            send_slack_notify_autodebet_gopay_failed_subscription_and_deduction
        )

        gopay_link_status = gopay_autodebet_transaction.gopay_account
        if gopay_link_status.status == GopayAccountStatusConst.DISABLED:
            logger.info(
                {
                    "action": "juloserver.payback.client.GopayClient.disable_subscription_gopay_autodebet",
                    "message": "Skipping disable subscription Adgopay due to Gopay Account Link already DISABLED",
                    "gopay_autodebet_transaction_id": gopay_autodebet_transaction.id,
                }
            )
            return

        url = '{}/v1/subscriptions/{}/disable'.format(
            self.base_url, gopay_autodebet_transaction.subscription_id)
        response = requests.post(url, headers=self.build_api_header())

        self._record_api_log(
            gopay_autodebet_transaction.gopay_account.pay_account_id,
            response,
            'POST {}'.format(url),
            account_payment=gopay_autodebet_transaction.account_payment
        )

        if response.status_code != 200:
            try:
                error_message = response.json()['status_message']
            except ValueError as e:
                error_message = f"failed to get response (error parsing JSON: {e})"
            send_slack_notify_autodebet_gopay_failed_subscription_and_deduction.delay(
                gopay_autodebet_transaction.account_payment.account.id,
                gopay_autodebet_transaction.account_payment.id,
                error_message,
                gopay_autodebet_transaction.subscription_id
            )
            raise GopayError(response.json())

        return response.json()
