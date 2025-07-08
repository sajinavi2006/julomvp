import logging

from datetime import datetime

from django.utils import timezone

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import FeatureSetting, Partner, PartnerProperty
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.partners import PartnerConstant

from juloserver.qris.exceptions import (
    PhoneRegisteredDokuApiError,
    RegisteredDokuApiError,
    DokuApiError,
)
from juloserver.qris.models import (
    DokuQrisTopUp,
    DokuQrisTransactionPayment,
    DokuQrisVoidTopUp,
    DokuQrisTransactionScan,
)
from juloserver.qris.client_wrapper import DokuClientWrapper
from juloserver.qris.constants import DokuAccountStatus, DokuResponseCode, QrisTransactionStatus
from juloserver.qris.utils import get_timestamp

logger = logging.getLogger(__name__)


class QrisService:
    def __init__(self, account):
        self.doku_client_wrapper = DokuClientWrapper()
        self.account = account
        self._doku_id = None

    def register_doku_account(self):
        status = True
        doku_id = None

        # check on partner property table
        partner_property, account_status = self.check_doku_account_register()
        if account_status == DokuAccountStatus.DONE:
            return status

        # register new account
        application = self.account.application_set.last()
        customer_name = application.fullname
        customer_email = application.email
        customer_phone = application.mobile_phone_prefix_62
        try:
            doku_id = self.doku_client_wrapper.register_customer(
                customer_name, customer_email, customer_phone
            )
        except (PhoneRegisteredDokuApiError, RegisteredDokuApiError) as error:
            logger.warning(
                {
                    'action': 'register_doku_account',
                    'msg': str(error),
                    'data': {'application_id': application.id},
                }
            )
        else:
            # store doku_id
            partner_property.partner_reference_id = doku_id
            partner_property.save()
            return status

        self.doku_client_wrapper.request_linking_account(customer_phone)
        status = False

        return status

    def linking_account_confirm(self, otp):
        # send confirm linking account
        partner_property, status = self.check_doku_account_register()
        if status == DokuAccountStatus.DONE:
            return True

        application = self.account.application_set.last()
        doku_id = self.doku_client_wrapper.confirm_linking_account(
            application.mobile_phone_prefix_62, otp
        )

        # mark success linking
        partner_property.partner_reference_id = doku_id
        partner_property.save()
        return True
        # return status

    def inquiry_qris(self, qr_code):
        # call api to get qr code data
        result = None

        try:
            response = self.doku_client_wrapper.inquiry_qris(self.doku_id, qr_code)
        except DokuApiError as error:
            self.store_invalid_qr_transaction_scanning(qr_code, error.args[0], error.args[1])
            return result
        # store qr_code to DB
        qr_object = self.store_qr_transaction_scanning(response, qr_code)
        result = {
            "qr_id": qr_object.id,
            "merchant_name": response["merchantName"],
            "merchant_city": response["merchantCity"],
            "is_blacklisted_transaction": self.qris_merchant_blacklist_check(qr_object),
        }
        if response.get("amount"):
            result.update({"amount": response["amount"]})

        return result

    def payment_qris(self, qr_payment, retry=False):
        qr_scan = qr_payment.doku_qris_transaction_scan
        amount = qr_payment.amount

        if retry:
            if qr_payment.response_code == DokuResponseCode.SUCCESS:
                raise JuloException('This qris transaction can not retry')
            qr_payment = self.update_qris_payment_for_retry(qr_payment)

        if not self.top_up_process(amount, qr_payment):
            self.update_qr_payment_failed(qr_payment)
            return False

        if not self.payment_process(qr_payment, qr_scan):
            self.update_qr_payment_failed(qr_payment)
            self.void_top_up_process(qr_payment)
            return False

        self.update_qr_payment_success(qr_payment)
        return True

    def payment_process(self, qr_payment, qr_scan):
        try:
            response = self.doku_client_wrapper.payment_qris(
                self.doku_id,
                qr_scan.qr_code,
                qr_payment.invoice,
                qr_payment.amount,
                transaction_id_qris=qr_scan.transaction_id,
            )

        except DokuApiError as error:
            self.update_doku_payment_qris_error(qr_payment, error.args[0], error.args[1])
            return False
        except Exception:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            response = None

        if not response:
            try:
                response = self.doku_client_wrapper.status_payment(qr_payment.invoice)
            except Exception:
                sentry_client = get_julo_sentry_client()
                sentry_client.captureException()
                return False

        if not self.update_doku_payment_qris(qr_payment, response):
            return False

        return True

    def top_up_process(self, amount, qr_payment):
        qr_topup = self.init_doku_qris_top_up(qr_payment, amount, self.doku_id)
        try:
            response = self.doku_client_wrapper.top_up(
                self.doku_id, qr_topup.amount, qr_topup.transaction_id
            )
        except DokuApiError as error:
            self.update_doku_qris_top_up_error(qr_topup, error.args[0], error.args[1])
            return False
        except Exception:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            response = None

        if not response:
            try:
                response = self.doku_client_wrapper.status_top_up(qr_topup.transaction_id)
            except Exception:
                sentry_client = get_julo_sentry_client()
                sentry_client.captureException()
                return False

        if not self.update_doku_qris_top_up(qr_topup, response):
            return False

        return True

    def void_top_up_process(self, qr_payment):
        qr_topup = qr_payment.qris_topup.last()
        qr_void_topup = self.init_qr_void_top_up(qr_topup)
        try:
            response = self.doku_client_wrapper.void_top_up(qr_void_topup.transaction_id)
        except DokuApiError as error:
            self.update_doku_qris_void_top_up_error(qr_void_topup, error.args[0], error.args[1])
            return False
        except Exception:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            return False

        self.update_doku_qris_void_topup(qr_void_topup, response)
        return True

    def check_doku_account_register(self):
        doku_partner = Partner.objects.get(name=PartnerConstant.DOKU_PARTNER)
        property_account, _created = PartnerProperty.objects.get_or_create(
            account=self.account, partner=doku_partner
        )
        if not property_account.partner_reference_id:
            return property_account, DokuAccountStatus.UNREGISTERED

        return property_account, DokuAccountStatus.DONE

    def check_doku_account_status(self):
        _partner_property, account_status = self.check_doku_account_register()
        if account_status == DokuAccountStatus.DONE:
            return True

        return False

    def update_qr_payment_success(self, qr_payment):
        qr_payment.transaction_status = QrisTransactionStatus.SUCCESS
        qr_payment.save()

    def update_qr_payment_failed(self, qr_payment):
        qr_payment.transaction_status = QrisTransactionStatus.FAILED
        qr_payment.save()

    def update_qr_payment_cancel(self, qr_payment):
        qr_payment.transaction_status = QrisTransactionStatus.CANCEL
        qr_payment.save()

    def store_qr_transaction_scanning(self, response, qr_code):
        acquirer = response["listAcquirer"][0]
        return DokuQrisTransactionScan.objects.create(
            qr_code=qr_code,
            customer=self.account.customer,
            acquirer_id=acquirer.get("acquirerId"),
            card_id=acquirer.get("cardId"),
            primary_account_number=acquirer.get("primaryAccountNumber"),
            merchant_criteria=acquirer.get("merchantCriteria"),
            acquirer_name=acquirer.get("acquirerName"),
            terminal_id=acquirer.get("terminalId"),
            additional_data_national=response["additionalDataNational"],
            transaction_id=response.get("transactionId"),
            merchant_category_code=response["merchantCategoryCode"],
            merchant_city=response["merchantCity"],
            post_entry_mode=response["postEntryMode"],
            merchant_country_code=response["merchantCountryCode"],
            merchant_name=response["merchantName"],
            to_account_type=response["toAccountType"],
            from_account_type=response["fromAccountType"],
            amount=response.get("amount"),
            response_code=response["responseCode"],
            response_message=response["responseMessage"],
        )

    def init_qr_void_top_up(self, qr_topup):
        return DokuQrisVoidTopUp.objects.create(
            doku_qris_top_up=qr_topup, transaction_id=qr_topup.transaction_id
        )

    def update_doku_qris_void_top_up_error(self, qr_void_topup, message, error_code):
        qr_void_topup.response_message = message
        qr_void_topup.response_code = error_code
        qr_void_topup.save()

    def init_doku_qris_transaction_payment(self, qr_scan_id, amount, loan):
        if not amount:
            raise JuloException('Amount can not be NULL')

        qr_scan = self.get_qris_scan_by_id(qr_scan_id)

        if qr_scan.amount and amount != qr_scan.amount:
            raise JuloException('Amount is not valid')

        qr_payment = DokuQrisTransactionPayment.objects.create(
            doku_qris_transaction_scan=qr_scan,
            amount=amount,
            loan=loan,
            acquirer_name=qr_scan.acquirer_name,
            from_account_type=qr_scan.from_account_type,
            merchant_name=qr_scan.merchant_name,
        )
        qr_payment.invoice = self.get_qr_payment_invoice(qr_payment)
        qr_payment.save()

        return qr_payment

    def get_qr_payment_invoice(self, qr_payment):
        return "JULO-%s-%s" % (qr_payment.pk, get_timestamp())

    def update_qris_payment_for_retry(self, qr_payment):
        qr_payment.retry_times += 1
        qr_payment.invoice = self.get_qr_payment_invoice(qr_payment)
        qr_payment.save()

        return qr_payment

    def init_doku_qris_top_up(self, qr_payment, amount, doku_id):
        qr_topup = DokuQrisTopUp.objects.create(
            doku_qris_transaction_payment=qr_payment,
            amount=amount,
            doku_id=doku_id,
        )
        qr_topup.transaction_id = "JULO-%s-%s" % (qr_payment.pk, get_timestamp())
        qr_topup.save()

        return qr_topup

    def update_doku_qris_top_up(self, qr_topup, response):
        qr_topup.tracking_id = response["trackingId"]
        qr_topup.result = response["result"]
        qr_topup.date_time = timezone.localtime(
            datetime.strptime(response["dateTime"], '%Y%m%d%H%M%S')
        )
        qr_topup.client_id = response["clientId"]
        qr_topup.response_code = response["responseCode"]
        qr_topup.response_message = response["responseMessage"]
        qr_topup.save()

        return response["result"].upper() == "SUCCESS"

    def update_doku_qris_void_topup(self, qr_void_topup, response):
        qr_void_topup.tracking_id = response["trackingId"]
        qr_void_topup.date_time = timezone.localtime(
            datetime.strptime(response["dateTime"], '%Y%m%d%H%M%S')
        )
        qr_void_topup.amount = response["amount"]
        qr_void_topup.response_code = response["responseCode"]
        qr_void_topup.response_message = response["responseMessage"]
        qr_void_topup.save()

    def update_doku_qris_top_up_error(self, qr_topup, message, error_code):
        qr_topup.response_message = message
        qr_topup.response_code = error_code
        qr_topup.save()

    def get_qris_scan_by_id(self, qr_id):
        return DokuQrisTransactionScan.objects.get(pk=qr_id, response_code=DokuResponseCode.SUCCESS)

    @property
    def doku_id(self):
        if not self._doku_id:
            partner_property = self.account.partnerproperty_set.filter(
                partner__name=PartnerConstant.DOKU_PARTNER
            ).last()
            self._doku_id = partner_property.partner_reference_id
        return self._doku_id

    def update_doku_payment_qris_error(self, qr_payment, message, error_code):
        qr_payment.response_message = message
        qr_payment.response_code = error_code
        qr_payment.save()

    def update_doku_payment_qris(self, qr_payment, response):
        qr_payment.reference_number = response.get("referenceNumber")
        qr_payment.conveniences_fee = response.get("conveniencesFee")
        qr_payment.nns_code = response.get("nnsCode")
        qr_payment.approval_code = response.get("approvalCode")
        qr_payment.invoice_acquirer = response.get("invoiceAcquirer")
        qr_payment.response_code = response["responseCode"]
        qr_payment.response_message = response["responseMessage"]
        qr_payment.save()

        return response.get("result", "SUCCESS").upper() == "SUCCESS"

    def store_invalid_qr_transaction_scanning(self, qr_code, message, error_code):
        DokuQrisTransactionScan.objects.create(
            qr_code=qr_code,
            customer=self.account.customer,
            response_code=error_code,
            response_message=message,
        )

    def qris_merchant_blacklist_check(self, qr_object):
        feature = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.QRIS_MERCHANT_BLACKLIST, is_active=True
        ).last()
        if feature:
            params = feature.parameters
            category_codes = [
                str(code).lower().replace(' ', '')
                for code in params.get('merchant_category_codes', [])
            ]
            cities = [city.lower().replace(' ', '') for city in params.get('merchant_cities', [])]
            names = [name.lower().replace(' ', '') for name in params.get('merchant_names', [])]
            if (
                qr_object.merchant_category_code.lower().replace(' ', '') in category_codes
                or qr_object.merchant_city.lower().replace(' ', '') in cities
                or qr_object.merchant_name.lower().replace(' ', '') in names
            ):
                return True
        return False


def get_qris_transaction_status(loan):
    result = {}
    qr_payment = DokuQrisTransactionPayment.objects.get(loan=loan)
    if not qr_payment:
        return result

    result = {
        "status": qr_payment.transaction_status,
        "merchantName": qr_payment.merchant_name,
        "nominal": qr_payment.amount,
        "date": timezone.localtime(qr_payment.udate).isoformat(timespec='milliseconds'),
        "invoice": qr_payment.invoice,
    }
    return result
