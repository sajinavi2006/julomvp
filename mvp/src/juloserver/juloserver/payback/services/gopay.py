from __future__ import division

import re
from builtins import object
from past.utils import old_div
import logging
import uuid

from datetime import datetime
from django.db import transaction as db_transaction

from juloserver.autodebet.services.authorization_services import gopay_autodebet_revocation
from juloserver.disbursement.services.gopay import GopayConst
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import MobileFeatureSetting, PaybackTransaction, FeatureSetting
from juloserver.julo.services import process_partial_payment
from juloserver.julo.services2.payment_method import create_or_update_gopay_payment_method
from juloserver.julo.utils import display_rupiah, generate_sha512
from juloserver.julocore.python2.utils import py2round
from juloserver.loan_refinancing.services.loan_related import (
    get_loan_refinancing_request_info,
    check_eligibility_of_loan_refinancing,
    activate_loan_refinancing,
    get_unpaid_payments
)
from juloserver.loan_refinancing.services.refinancing_product_related import (
    get_covid_loan_refinancing_request,
    check_eligibility_of_covid_loan_refinancing,
    CovidLoanRefinancing,
    process_partial_paid_loan_refinancing
)
from juloserver.payback.client import get_gopay_client
from juloserver.payback.constants import (
    Messages,
    GopayAccountStatusMessageConst,
    GopayAccountStatusConst,
    GopayTransactionStatusConst,
    GopayAccountFailedResponseCodeConst,
    GopayAccountErrorConst,
    FeatureSettingNameConst,
)
from juloserver.payback.models import (
    GopayAccountLinkStatus,
    GopayCustomerBalance,
    GopayRepaymentTransaction,
)
from juloserver.payback.services.payback import create_pbt_status_history
from juloserver.payback.services.waiver import (
    process_waiver_after_payment,
    process_waiver_before_payment,
)
from juloserver.payback.status import PaybackTransStatus, PaymentServices
from django.conf import settings
from juloserver.integapiv1.tasks import send_sms_async

logger = logging.getLogger(__name__)


class GopayServices(object):
    def __init__(self):
        self.client = get_gopay_client()

    def init_transaction(self, payment, payment_method, amount):
        loan = payment.loan
        customer = payment_method.customer
        # make request call
        # build customer full name

        net_amount = self.get_amount_with_fee(amount)

        req_data = {
            'loan': loan,
            'customer': customer,
            'payment': payment,
            'amount': amount,
        }

        res_data = self.client.init_transaction(req_data)
        transaction = PaybackTransaction.objects.create(
            transaction_id=res_data['transaction_id'],
            customer=customer,
            payment=payment,
            payment_method=payment_method,
            loan=loan,
            payback_service='gopay',
            amount=net_amount,
            is_processed=False
        )

        logger.info({
            'action': 'init_transaction',
            'request_data': req_data,
            'response_data': res_data,
            'net_amount': net_amount
        })

        return {
            'transaction': transaction,
            'gopay': res_data['server_res']
        }

    def init_account_payment_transaction(self, account_payment, payment_method, amount):

        net_amount = self.get_amount_with_fee(amount)
        customer = payment_method.customer
        req_data = {
            'customer': customer,
            'payment': account_payment,
            'amount': amount,
        }

        res_data = self.client.init_transaction(req_data)
        transaction = PaybackTransaction.objects.create(
            transaction_id=res_data['transaction_id'],
            customer=customer,
            payment_method=payment_method,
            payback_service='gopay',
            amount=net_amount,
            is_processed=False,
            account=account_payment.account
        )

        #Record the gopay repayment transaction detail
        GopayRepaymentTransaction.objects.create(
            transaction_id=res_data['transaction_id'],
            amount=net_amount,
            source='gopay',
        )

        logger.info({
            'action': 'init_transaction',
            'request_data': req_data,
            'response_data': res_data,
            'net_amount': net_amount
        })

        return {
            'transaction': transaction,
            'gopay': res_data['server_res']
        }

    def get_transaction_status(self, transaction_id):
        req_data = {
            'transaction_id': transaction_id
        }

        return self.client.get_status(req_data)

    def gross_to_net_amount(self, gross_amount):
        """calculate net amount from gross amount with fee"""
        net_amount = gross_amount - GopayConst.GOPAY_TRANSFER_FEE
        return net_amount

    def get_amount_with_fee(self, amount):
        """check fee in setting and calculate net amount if any fee"""
        admin_fee_feature = MobileFeatureSetting.objects.filter(
            feature_name='gopay_admin_fee',
            is_active=True).first()

        if admin_fee_feature:
            logger.info({
                "action": "get_amount_with_fee",
                "data": admin_fee_feature.__dict__,
                "amount": amount
            })
            amount = self.gross_to_net_amount(amount)

        return amount

    @staticmethod
    def process_loan(loan, payment, transaction, data):
        note = 'payment with gopay'
        paid_date = datetime.strptime(data['transaction_time'], '%Y-%m-%d %H:%M:%S')
        paid_amount = transaction.amount
        old_status = transaction.status_code
        payment_method = transaction.payment_method

        # loan refinancing process
        loan_refinancing_request = get_loan_refinancing_request_info(loan)
        covid_loan_refinancing_request = get_covid_loan_refinancing_request(loan)

        if loan_refinancing_request and check_eligibility_of_loan_refinancing(
                loan_refinancing_request, paid_date.date()):
            if loan_refinancing_request.new_installment != paid_amount:
                raise JuloException('pembayaran tidak sesuai due amount, paid_amount != due_amount')
            else:
                is_loan_refinancing_active = activate_loan_refinancing(
                    payment, loan_refinancing_request)
                if not is_loan_refinancing_active:
                    raise JuloException('failed to activate loan refinancing',
                                        'gagal aktivasi loan refinancing')
                payment = get_unpaid_payments(loan, order_by='payment_number')[0]
        elif covid_loan_refinancing_request and \
                check_eligibility_of_covid_loan_refinancing(
                    covid_loan_refinancing_request, paid_date.date()):

                covid_lf_factory = CovidLoanRefinancing(
                    payment, covid_loan_refinancing_request)

                is_covid_loan_refinancing_active = covid_lf_factory.activate()

                if not is_covid_loan_refinancing_active:
                    raise JuloException('failed to activate covid loan refinancing',
                                        'gagal aktivasi covid loan refinancing')

                payment = get_unpaid_payments(loan, order_by='payment_number')[0]

                payment.refresh_from_db()

                paid_amount = process_partial_paid_loan_refinancing(
                    covid_loan_refinancing_request,
                    payment,
                    paid_amount
                )

        with db_transaction.atomic():
            # waive process if exist
            process_waiver_before_payment(payment, paid_amount, paid_date.date())

            process_payment = process_partial_payment(
                payment, paid_amount, note, paid_date=paid_date.date(),
                payment_receipt=transaction.transaction_id,
                payment_method=payment_method)
            transaction.status_code = PaybackTransStatus.get_mapped_status(
                payment_service=PaymentServices.GOPAY, inbo_status=data['transaction_status'])
            transaction.status_desc = data['status_message']
            transaction.transaction_date = data['transaction_time']
            transaction.is_processed = True
            transaction.payment = payment
            transaction.save(update_fields=['status_code', 'status_desc',
                                            'transaction_date', 'is_processed', 'payment'])
            create_pbt_status_history(transaction, old_status, transaction.status_code)
            # process waive_late_fee or waive_interest if exist
            process_waiver_after_payment(payment, paid_amount, paid_date.date())

        if process_payment and payment.payment_number == 1:
            send_sms_async.delay(
                application_id=payment.loan.application_id,
                template_code=Messages.PAYMENT_RECEIVED_TEMPLATE_CODE,
                context={'amount': display_rupiah(transaction.amount)}
            )

        return process_payment

    @staticmethod
    def update_transaction_status(transaction, data):
        old_status = transaction.status_code
        transaction.status_desc = data.get('status_message', '')
        transaction.status_code = PaybackTransStatus.get_mapped_status(
            payment_service=PaymentServices.GOPAY,
            inbo_status=data['transaction_status'])
        transaction.save()

        # Create status history
        create_pbt_status_history(transaction, old_status, transaction.status_code)

        return transaction

    @staticmethod
    def get_gopay_onboarding_data():
        feature_settings = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.GOPAY_ONBOARDING_PAGE,
            is_active=True
        )

        if not feature_settings:
            return {}, 'Feature setting not found/not active.'

        return feature_settings.parameters, ''

    def create_pay_account(self, customer):
        gopay_account_link = GopayAccountLinkStatus.objects.filter(account=customer.account).last()

        if gopay_account_link and gopay_account_link.status == 'PENDING':
            return False, GopayAccountStatusMessageConst.status['PENDING']

        phone = customer.application_set.last().mobile_phone_1 or customer.phone

        if not phone:
            logger.error(
                {
                    'action': 'juloserver.payback.services.gopay.create_pay_account',
                    'error': 'Phone number not found'
                }
            )
            return False, 'Phone number not found'

        if phone.startswith('62'):
            mobile_phone = phone[2:]
        else:
            mobile_phone = phone[1:]

        data = {
            'payment_type': 'gopay',
            'gopay_partner': {
                'phone_number': mobile_phone,
                'country_code': '62',
                'redirect_url': 'julo://aktivitaspinjaman'
            }
        }

        res_data = self.client.create_pay_account(data)

        if 'account_status' not in res_data:
            if res_data['channel_response_code'] == GopayAccountFailedResponseCodeConst.USER_NOT_FOUND:
                logger.error(
                    {
                        'action': 'juloserver.payback.services.gopay.create_pay_account',
                        'error': 'Phone number not registered as gopay account',
                        'data': res_data
                    }
                )

                return None, 'Pastikan nomor HP di akun GoPay ' \
                             'kamu sama dengan nomor HP utama kamu di akun JULO, ya!'

            elif res_data['channel_response_code'] == GopayAccountFailedResponseCodeConst.WALLET_IS_BLOCKED:
                logger.error(
                    {
                        'action': 'juloserver.payback.services.gopay.create_pay_account',
                        'error': 'Phone number is blocked by GoPay',
                        'data': res_data
                    }
                )

                return None, 'Silakan hubungi pihak GoPay untuk membuka blokir nomor kamu ' \
                             'agar proses di JULO dapat dilanjutkan, ya! '

        if res_data['account_status'] == 'ENABLED':
            return None, GopayAccountStatusMessageConst.status[res_data['account_status']]

        actions = next((item for item in res_data['actions']
                        if item['name'] == 'activation-link-app'), None)

        if not actions:
            logger.error(
                {
                    'action': 'juloserver.payback.services.gopay.create_pay_account',
                    'error': 'Activation link not provided',
                    'data': res_data
                }
            )
            return None, 'Activation link not provided'

        activation_link = actions['url']

        gopay_account_link = GopayAccountLinkStatus.objects.create(
            pay_account_id=res_data['account_id'],
            status=res_data['account_status'],
            account=customer.account,
            registration_url_id=activation_link.split('id=')[1]
        )
        create_or_update_gopay_payment_method(
            customer=customer,
            gopay_account_link_status=gopay_account_link.status,
            phone=phone,
        )
        return {
            'account_status': res_data['account_status'],
            'web_linking': activation_link
        }, None

    @staticmethod
    def pay_account_link_notification(pay_account_id, signature_key, status_code,
                                      account_status):

        gopay_account_link = GopayAccountLinkStatus.objects.filter(
            pay_account_id=pay_account_id).last()

        if not gopay_account_link:
            logger.error(
                {
                    'action': 'juloserver.payback.services.gopay.pay_account_link_notification',
                    'error': 'GoPay account not found',
                    'data': {'pay_account_id': pay_account_id}
                }
            )
            return None, 'GoPay account not found'

        verify_signature = generate_sha512('{}{}{}{}'.format(
            pay_account_id,
            account_status,
            status_code,
            settings.GOPAY_SERVER_KEY
            )
        )

        if verify_signature != signature_key:
            logger.error(
                {
                    'action': 'juloserver.payback.services.gopay.pay_account_link_notification',
                    'error': 'Signature doesnt match',
                    'data': {'signature_key': signature_key}
                }
            )
            return None, 'Signature doesnt match'

        gopay_account_link.status = account_status
        gopay_account_link.save()
        create_or_update_gopay_payment_method(
            customer=gopay_account_link.account.customer, 
            gopay_account_link_status=gopay_account_link.status
        )
        if account_status == GopayAccountStatusConst.DISABLED:
            gopay_autodebet_revocation(gopay_account_link.account, True)
        return True, None

    def get_pay_account(self, account):
        gopay_account_link = GopayAccountLinkStatus.objects.filter(
            account=account).last()
        if not gopay_account_link:
            return {
                       "account_status": "DISABLED",
                       "message": "Akun GoPay kamu belum terhubung",
                       "balance": 0
                   }, None

        res_data = self.client.get_pay_account(gopay_account_link.pay_account_id)
        gopay_account_status = res_data['account_status']
        gopay_account_link.status = gopay_account_status
        gopay_account_link.save()
        payment_method = create_or_update_gopay_payment_method(
            customer=account.customer, 
            gopay_account_link_status=gopay_account_link.status,
            is_get_payment_method=True
        )

        if not res_data['account_status'] == 'ENABLED':
            return {
                "account_status": gopay_account_status,
                "message": GopayAccountStatusMessageConst.status[gopay_account_status],
                "balance": 0
            }, None

        if not payment_method:
            logger.error(
                {
                    'action': 'juloserver.payback.services.gopay.get_pay_account',
                    'error': 'Payment method not found',
                    'data': {'account_id': account.id }
                }
            )
            return None, 'Payment method not found'

        gopay_wallet = next((item for item in res_data['metadata']['payment_options']
                             if item['name'] == 'GOPAY_WALLET'), None)

        if not gopay_wallet:
            logger.error(
                {
                    'action': 'juloserver.payback.services.gopay.get_pay_account',
                    'error': 'GoPay wallet not provided',
                    'data': res_data
                }
            )
            return None, 'GoPay wallet not provided'

        gopay_balance = int(float(gopay_wallet['balance']['value']))
        gopay_token = gopay_wallet['token']

        GopayCustomerBalance.objects.create(
            gopay_account=gopay_account_link,
            is_active=gopay_wallet['active'],
            balance=gopay_balance,
            account=account
        )
        gopay_account_link.update_safely(token=gopay_token)

        return {
            "account_status": gopay_account_status,
            "message": GopayAccountStatusMessageConst.status[gopay_account_status],
            "balance": gopay_balance,
            "payment_method_id": payment_method.id
        }, None

    @staticmethod
    def is_show_gopay_account_linking(account_id):
        gopay_activation_linking_feature_setting = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.GOPAY_ACTIVATION_LINKING,
            is_active=True
        )

        gopay_whitelist_setting = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.WHITELIST_GOPAY,
            is_active=True
        )

        if gopay_activation_linking_feature_setting:
            if gopay_whitelist_setting:
                if account_id in gopay_whitelist_setting.parameters['account_id']:
                    return True
                return False
            return True
        return False

    def unbind_gopay_account_linking(self, account):
        gopay_account_link = GopayAccountLinkStatus.objects.filter(
            account=account, status='ENABLED').last()

        if not gopay_account_link:
            logger.error(
                {
                    'action': 'juloserver.payback.services.gopay.unbind_gopay_account_linking',
                    'error': GopayAccountErrorConst.ACCOUNT_NOT_REGISTERED,
                    'data': {'account_id': account.id}
                }
            )
            return None, GopayAccountErrorConst.ACCOUNT_NOT_REGISTERED

        res_data = self.client.unbind_pay_account(gopay_account_link.pay_account_id)

        if 'account_status' not in res_data:
            logger.error(
                {
                    'action': 'juloserver.payback.services.gopay.unbind_gopay_account_linking',
                    'error': 'Caller authentication error',
                    'data': res_data
                }
            )
            return None, 'Mohon coba beberapa saat lagi'

        if res_data['account_status'] == 'PENDING':
            return 'Akun Anda sedang dalam proses deaktivasi', None
        elif res_data['account_status'] == 'DISABLED':
            gopay_account_link.update_safely(status=res_data['account_status'])
            create_or_update_gopay_payment_method(
                customer=account.customer,
                gopay_account_link_status=gopay_account_link.status
            )
            gopay_autodebet_revocation(account)
            return GopayAccountErrorConst.DEACTIVATED, None
        else:
            return 'Mohon ulangi kembali proses deaktivasi', None

    def gopay_tokenization_init_account_payment_transaction(self, account_payment, payment_method, amount):
        net_amount = self.get_amount_with_fee(amount)
        customer = payment_method.customer
        gopay_account_link = GopayAccountLinkStatus.objects.filter(
            account=account_payment.account, status=GopayAccountStatusConst.ENABLED).last()

        if not gopay_account_link:
            logger.error(
                {
                    'action': 'juloserver.payback.services.gopay.gopay_tokenization_init_account_payment_transaction',
                    'error': GopayAccountErrorConst.ACCOUNT_NOT_REGISTERED,
                    'data': {'account_id': account_payment.account.id}
                }
            )
            return None, GopayAccountErrorConst.ACCOUNT_NOT_REGISTERED

        fullname = customer.fullname.split()
        application = customer.application_set.last()

        req_data = {
            "payment_type": "gopay",
            "gopay": {
                "account_id": gopay_account_link.pay_account_id,
                "payment_option_token": gopay_account_link.token,
                "callback_url": "julo://aktivitaspinjaman",
                "recurring": False,
            },
            'transaction_details': {
                "gross_amount": amount,
                "order_id": str(uuid.uuid4()),
            },
            'customer_details': {
                'first_name': fullname[0].title(),
                'last_name': fullname[-1].title() if len(fullname) > 1 else '',
                'phone': customer.phone,
                'email': customer.email,
                'billing_address': {
                    'address': '{}, {}, {}, {}, {}'.format(
                        application.address_street_num,
                        application.address_kelurahan,
                        application.address_kecamatan,
                        application.address_kabupaten,
                        application.address_provinsi
                    ),
                    'first_name': fullname[0].title(),
                    'last_name': fullname[-1].title() if len(fullname) > 1 else '',
                    'phone': customer.phone,
                    'postal_code': application.address_kodepos,
                    'country_code': 'IDN'
                },
            }
        }

        res_data = self.client.gopay_tokenization_init_transaction(req_data)

        if res_data['transaction_status'] != GopayTransactionStatusConst.DENY:
            PaybackTransaction.objects.create(
                transaction_id=res_data['order_id'],
                customer=customer,
                payment_method=payment_method,
                payback_service='gopay_tokenization',
                amount=net_amount,
                is_processed=False,
                account=account_payment.account
            )

        #Record the gopay repayment transaction detail
        GopayRepaymentTransaction.objects.create(
            transaction_id=res_data['order_id'],
            status=res_data['transaction_status'],
            amount=net_amount,
            source='gopay_tokenization',
            gopay_account=gopay_account_link,
        )

        logger.info({
            'action': 'Init gopay tokenization transaction',
            'request_data': req_data,
            'response_data': res_data,
            'net_amount': net_amount
        })

        if res_data['transaction_status'] == GopayTransactionStatusConst.SETTLEMENT:
            return {
                "payment_type": res_data['payment_type'],
                "gross_amount": res_data['gross_amount'],
                "gopay": {
                    "transaction_status": res_data['transaction_status'],
                    "status_message": res_data['status_message'],
                    "payment_option_token": gopay_account_link.token,
                }
            }, None

        if res_data['transaction_status'] == GopayTransactionStatusConst.DENY:
            logger.error(
                {
                    'action': 'juloserver.payback.services.gopay.gopay_tokenization_init_account_payment_transaction',
                    'error': res_data['status_message'],
                    'data': res_data
                }
            )
            return None, res_data['status_message']

        actions = next((item for item in res_data['actions']
                        if item['name'] == 'verification-link-app'), None)

        if not actions:
            logger.error(
                {
                    'action': 'juloserver.payback.services.gopay.gopay_tokenization_init_account_payment_transaction',
                    'error': 'Verification link not provided',
                    'data': res_data
                }
            )
            return None, 'Verification link not provided'

        return {
            "payment_type": res_data['payment_type'],
            "gross_amount": res_data['gross_amount'],
            "gopay": {
                "transaction_status": res_data['transaction_status'],
                "status_message": res_data['status_message'],
                "payment_option_token": gopay_account_link.token,
                "web_linking": actions['url']
            }
        }, None


def is_eligible_change_url_gopay(url: str) -> bool:
    gopay_change_url_feature = FeatureSetting.objects.filter(
        feature_name=FeatureSettingNameConst.GOPAY_CHANGE_URL,
        is_active=True,
    ).exists()

    if gopay_change_url_feature and url.find('/payback/v1/') >= 0:
        return True

    return False
