from __future__ import unicode_literals
from builtins import str
from builtins import object
import hashlib
import logging
import math
from babel.numbers import format_currency
from dateutil.relativedelta import relativedelta
from gcm.gcm import GCMAuthenticationException

from django.conf import settings
from django.contrib.auth import hashers
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models.functions import Coalesce
from django.db.models.aggregates import Sum
from django.forms.models import model_to_dict
from django.template.loader import get_template
from django.template.loader import render_to_string
from django.utils import timezone

from .models import LineOfCredit
from .models import LineOfCreditTransaction
from .models import LineOfCreditStatement
from .models import LineOfCreditNotification
from .models import LineOfCreditNote

from juloserver.julo.clients import get_julo_sepulsa_client
from juloserver.julo.clients import get_julo_pn_client
from juloserver.julo.clients import get_julo_sms_client
from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import Application
from juloserver.julo.models import PaymentMethod
from juloserver.julo.models import SepulsaTransaction
from juloserver.julo.models import SepulsaProduct
from juloserver.julo.models import PaymentMethodLookup
from juloserver.julo.services import create_payment_method_loc
from juloserver.julo.services import process_sepulsa_transaction_failed
from juloserver.julo.services2.sepulsa import SepulsaService
from juloserver.julo.utils import display_rupiah
from juloserver.julo.utils import have_pn_device

from .constants import LocConst
from .constants import LocCollConst
from .constants import LocErrorTemplate
from .constants import LocNotifConst
from .constants import LocTransConst
from .constants import LocResponseMessageTemplate
from .exceptions import LocException
from .utils import calculate_next_statement_date
from .utils import add_token_sepulsa_transaction
from .utils import generate_pin_email_key
from .utils import pin_format_validation

from juloserver.payment_point.constants import SepulsaProductCategory, SepulsaProductType


julo_sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


class LineOfCreditService(object):
    @staticmethod
    def create(customer_id):
        return LineOfCredit.objects.create(
            customer_id=customer_id,
            limit=LocConst.DEFAULT_LIMIT,
            available=LocConst.DEFAULT_LIMIT,
            service_fee_rate=LocConst.SERVICE_FEE_RATE,
            late_fee_rate=LocConst.LATE_FEE_RATE,
            interest_rate=LocConst.INTEREST_RATE,
            status=LocConst.STATUS_INACTIVE)

    @staticmethod
    def set_active(loc_id, payday):
        """
        Calculates statement day
        Assigns Virtual Account
        """
        with transaction.atomic():
            loc = LineOfCredit.objects.get(id=loc_id)
            # create payment methods loc
            create_payment_method_loc(loc)

            # re-setting all config
            loc.limit = LocConst.DEFAULT_LIMIT
            loc.available = LocConst.DEFAULT_LIMIT
            loc.service_fee_rate = LocConst.SERVICE_FEE_RATE
            loc.late_fee_rate = LocConst.LATE_FEE_RATE
            loc.interest_rate = LocConst.INTEREST_RATE

            # calculate statement_day base on pay_day
            statement_day = LocConst.DEFAULT_STATEMENT_DAY
            if LocConst.MIN_STATEMENT_DAY <= payday <= LocConst.MAX_STATEMENT_DAY:
                statement_day = payday

            # calculate next settlement date
            next_statement_date = calculate_next_statement_date(statement_day)

            # set statement config
            loc.statement_day = statement_day
            loc.next_statement_date = next_statement_date

            loc.status = LocConst.STATUS_ACTIVE
            loc.active_date = timezone.now()
            loc.save()

    @staticmethod
    def set_freeze(loc_id, reason):
        loc = LineOfCredit.objects.get(id=loc_id)
        loc.status = LocConst.STATUS_FREEZE
        loc.freeze_reason = str(reason)
        loc.freeze_date = timezone.now()
        loc.save()

    @staticmethod
    def get_by_id(loc_id):
        return LineOfCredit.objects.filter(id=loc_id).last()

    @staticmethod
    def get_activity(loc):
        if isinstance(loc, int):
            loc = LineOfCredit.objects.get(id=loc)
        loc_data = {'available': loc.available,
                    'limit': loc.limit,
                    'status': loc.status}

        pay_pend_q = LineOfCreditTransaction.objects.filter(
            line_of_credit_id=loc.id, loc_statement__isnull=True,
            type=LocTransConst.TYPE_PAYMENT, status=LocTransConst.STATUS_SUCCESS)

        last_transaction = LineOfCreditTransaction.objects.filter(
            line_of_credit_id=loc.id, loc_statement__isnull=True).exclude(
            type=LocTransConst.TYPE_PAYMENT).last()
        if last_transaction:
            last_transaction_dict = model_to_dict(last_transaction)
            last_transaction_data = \
                LineOfCreditTransactionService.get_sepulsa_transaction_description_detail(
                    last_transaction_dict
                )
            last_transaction_data['cdate'] = last_transaction.cdate
        else:
            last_transaction_data = None

        # get 4 last statement summaries
        statement_summaries = LineOfCreditStatement.objects.values(
            'cdate', 'id', 'billing_amount',
            'payment_due_date', 'minimum_payment').filter(
            line_of_credit_id=loc.id).order_by('-cdate')[:4]

        # get virtual accounts
        virtual_accounts = LineOfCreditService().get_virtual_accounts(loc.id)

        # pin_is_set
        pin_is_set = False
        if loc.pin != '0':
            pin_is_set = True

        data = {'line_of_credit': loc_data,
                'payment_pending_sum': pay_pend_q.aggregate(sum=Coalesce(Sum('amount'), 0))['sum'],
                'last_transaction_data': last_transaction_data,
                'statement_summaries': statement_summaries,
                'virtual_accounts': virtual_accounts,
                'pin_is_set': pin_is_set,
                'next_statement_date': loc.next_statement_date
                }
        return data

    def get_loc_status_by_customer(self, customer):
        loc_status = {}
        loc_status['status'] = LocConst.STATUS_INACTIVE
        loc_status['limit'] = LocConst.DEFAULT_LIMIT
        loc_status['can_apply'] = True

        loc = LineOfCredit.objects.filter(customer=customer).first()
        if loc:
            loc_status['status'] = loc.status
            loc_status['limit'] = loc.limit
            loc_status['can_apply'] = False

        return loc_status

    def decrease_balance(self, loc, amount):
        loc.available -= amount
        loc.save()

    def increase_balance(self, loc, amount):
        loc.available += amount
        loc.save()

    def update_next_statement_date(self, loc):
        last_statement = LineOfCreditStatementService.get_last_statement(loc.id)
        last_statement_date = None
        if last_statement:
            last_statement_date = last_statement.cdate
        next_statement_date = calculate_next_statement_date(loc.statement_day, last_statement_date)
        loc.next_statement_date = next_statement_date
        loc.save()

    @staticmethod
    def get_virtual_accounts(loc_id):

        va_fields = ['payment_method_name', 'bank_code', 'virtual_account']
        virtual_accounts = PaymentMethod.objects.values(*va_fields).filter(
            line_of_credit_id=loc_id, is_shown=True)

        for va in virtual_accounts:
            va['bank_name'] = va.pop('payment_method_name')
            va['bank_code'] = va.pop('bank_code')
            va['bank_virtual_name'] = None

            pm_lookup = PaymentMethodLookup.objects.filter(
                name=va['bank_name']).first()
            if pm_lookup:
                va['bank_virtual_name'] = pm_lookup.bank_virtual_name
                va['image_background_url'] = pm_lookup.image_background_url
                va['image_logo_url'] = pm_lookup.image_logo_url

        return virtual_accounts

    @staticmethod
    def update_pin(loc, data):
        if loc.pin != '0':
            if 'old_pin' not in data:
                raise LocException(LocErrorTemplate.LOC_PIN_UPDATE_NOT_OLD_PIN['message'],
                                   LocErrorTemplate.LOC_PIN_UPDATE_NOT_OLD_PIN['code'])
            if not LineOfCreditService.check_pin(loc, data['old_pin']):
                raise LocException(LocErrorTemplate.LOC_PIN_INVALID['message'],
                                   LocErrorTemplate.LOC_PIN_INVALID['code'])

        if not pin_format_validation(data['new_pin']):
            raise LocException(LocErrorTemplate.LOC_PIN_FORMAT_INVALID['message'],
                               LocErrorTemplate.LOC_PIN_FORMAT_INVALID['code'])

        salt = hashlib.sha1(str(loc.id)).hexdigest()
        chiper_pin = hashers.make_password(data['new_pin'], salt, 'pbkdf2_sha256')
        loc.pin = chiper_pin
        loc.save()

    @staticmethod
    def check_pin(loc, pin):
        return hashers.check_password(pin, loc.pin)

    @staticmethod
    def reset_pin_request(loc, email):
        new_key_needed = False
        if loc.reset_pin_key is None:
            new_key_needed = True
        else:
            if loc.has_resetpin_expired():
                new_key_needed = True

        if new_key_needed:
            reset_pin_key = generate_pin_email_key(loc.id, email)
            loc.reset_pin_key = reset_pin_key
            reset_pin_exp_date = timezone.now() + relativedelta(hours=1)
            loc.reset_pin_exp_date = reset_pin_exp_date
            loc.save()
            logger.info({
                'status': 'just_generated_reset_pin',
                'email': email,
                'loc_id': loc.id,
                'reset_pin_key': reset_pin_key,
                'reset_pin_exp_date': reset_pin_exp_date
            })
        else:
            reset_pin_key = loc.reset_pin_key
            logger.info({
                'status': 'reset_pin_key_already_generated',
                'email': email,
                'reset_pin_key': reset_pin_key
            })

        reset_pin_page_link = (
            settings.RESET_PIN_LINK_HOST + reset_pin_key + '/'
        )

        logger.info({
            'status': 'reset_pin_page_link_created',
            'action': 'sending_email',
            'email': email,
            'reset_pin_page_link': reset_pin_page_link
        })
        time_now = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')
        subject = "JULO: Reset Pin (%s) - %s" % (email, time_now)
        template = get_template('email_reset_pin.html')
        username = email.split("@")
        variable = {"link": reset_pin_page_link, "name": username[0]}
        html_content = template.render(variable)

        try:
            get_julo_email_client().send_email(
                subject,
                html_content,
                email,
                settings.EMAIL_FROM)
        except Exception:
            raise LocException(LocErrorTemplate.GENERAL_ERROR['message'],
                               LocErrorTemplate.GENERAL_ERROR['code'])

    @staticmethod
    def reset_pin_confirm(reset_pin_key, pin1, pin2):
        loc = LineOfCredit.objects.get_or_none(reset_pin_key=reset_pin_key)
        if not loc:
            raise LocException(LocErrorTemplate.RESET_KEY_INVALID['message'],
                               LocErrorTemplate.RESET_KEY_INVALID['code'])

        if loc.has_resetpin_expired():
            loc.reset_pin_key = None
            loc.reset_pin_exp_date = None
            loc.save()
            raise LocException(LocErrorTemplate.RESET_KEY_EXPIRED['message'],
                               LocErrorTemplate.RESET_KEY_EXPIRED['code'])

        if pin1 is None or pin2 is None:
            raise LocException(LocErrorTemplate.PIN_EMPTY['message'],
                               LocErrorTemplate.PIN_EMPTY['code'])

        if not pin_format_validation(pin1):
            raise LocException(LocErrorTemplate.LOC_PIN_FORMAT_INVALID['message'],
                               LocErrorTemplate.LOC_PIN_FORMAT_INVALID['code'])

        if pin1 != pin2:
            raise LocException(LocErrorTemplate.PIN_MISMATCH['message'],
                               LocErrorTemplate.PIN_MISMATCH['code'])

        loc.reset_pin_key = None
        loc.reset_pin_exp_date = None
        with transaction.atomic():
            salt = hashlib.sha1(str(loc.id)).hexdigest()
            loc.pin = hashers.make_password(pin1, salt, 'pbkdf2_sha256')
            loc.save()

            application = loc.application_set.last()
            if have_pn_device(application.device):
                gcm_reg_id = application.device.gcm_reg_id
                message = LocConst.RESET_PIN_MESSAGE

                try:
                    pn_client = get_julo_pn_client()
                    pn_client.inform_loc_reset_pin_finish(gcm_reg_id, message)
                except GCMAuthenticationException as e:
                    sentry_client = julo_sentry_client
                    sentry_client.captureException()
                    return

    @staticmethod
    def get_pin_status(loc):
        is_reset_pin_active = False
        remaining_time = 0
        if loc.reset_pin_key is not None and not loc.has_resetpin_expired():
            is_reset_pin_active = True
            remaining_time = (loc.reset_pin_exp_date - timezone.now()).total_seconds() * 1000

        return {
            'is_reset_pin_active': is_reset_pin_active,
            'remaining_time': int(remaining_time)
        }


class LineOfCreditProductService(object):

    @staticmethod
    def generate_loc_product(sepulsa_product):
        sepulsa_product_dict = {}
        sepulsa_product_dict['product_id'] = sepulsa_product.id
        sepulsa_product_dict['type'] = sepulsa_product.type
        sepulsa_product_dict['category'] = sepulsa_product.category
        sepulsa_product_dict['product_name'] = sepulsa_product.product_name
        sepulsa_product_dict['product_desc'] = sepulsa_product.product_desc
        sepulsa_product_dict['product_label'] = sepulsa_product.product_label
        sepulsa_product_dict['product_nominal'] = sepulsa_product.product_nominal
        sepulsa_product_dict['product_price'] = sepulsa_product.customer_price
        sepulsa_product_dict['service_fee_amount'] = LocConst.SERVICE_FEE_RATE * sepulsa_product.customer_price
        sepulsa_product_dict['total_customer_price'] = sepulsa_product_dict['product_price'] + sepulsa_product_dict['service_fee_amount']
        return sepulsa_product_dict

    @staticmethod
    def get_by_type_and_category(type, category, operator_id, limit):
        """
        Get list sepulsa product by type and category
        """
        list_sepulsa_products = []
        for sepulsa_product in SepulsaProduct.objects.filter(
                type=type, category=category, operator_id=operator_id,
                is_active=True).order_by('product_nominal'):
            sepulsa_product_dict = LineOfCreditProductService.generate_loc_product(sepulsa_product)
            if sepulsa_product_dict['total_customer_price'] <= limit:
                list_sepulsa_products.append(sepulsa_product_dict)
        return list_sepulsa_products

    @staticmethod
    def get_by_id(product_id):
        """
        Get list sepulsa product by id
        """
        sepulsa_product = SepulsaProduct.objects.filter(pk=product_id, is_active=True).last()
        if not sepulsa_product:
            return None
        sepulsa_product_dict = LineOfCreditProductService.generate_loc_product(sepulsa_product)
        return sepulsa_product_dict


class LineOfCreditPurchaseService(object):
    @staticmethod
    def add_purchase(loc, product_id, phone_number, total_customer_price, account_name, meter_number):
        """
        Check and decrease LineOfCredit.available, return false if not enough credit
        Creates Sepulsa transaction
        """
        loc_product_service = LineOfCreditProductService()
        loc_product = loc_product_service.get_by_id(product_id)
        if not loc_product:
            raise LocException(LocResponseMessageTemplate.GENERAL_ERROR)
        if loc.status != LocConst.STATUS_ACTIVE:
            raise LocException(LocResponseMessageTemplate.GENERAL_ERROR)
        if total_customer_price != loc_product['total_customer_price']:
            raise LocException(LocResponseMessageTemplate.GENERAL_ERROR)
        if loc_product['total_customer_price'] > loc.available:
            raise LocException(LocResponseMessageTemplate.BALANCE_INSUFFICIENT)

        order_status = SepulsaTransaction.objects.filter(is_order_created=False,
                                                         line_of_credit_transaction__line_of_credit_id=loc.id).last()

        if order_status:
            raise LocException(LocResponseMessageTemplate.DOUBLE_TRANSACTION)

        # create transaction sepulsa
        sepulsa_service = SepulsaService()
        sepulsa_product = SepulsaProduct.objects.filter(pk=product_id).last()
        sepulsa_transaction = sepulsa_service.create_transaction_sepulsa(loc.customer, sepulsa_product, phone_number, account_name, meter_number)

        # check julo balance sepulsa
        is_enough = sepulsa_service.is_balance_enough_for_transaction(loc_product['total_customer_price'])
        if not is_enough:
            raise LocException(LocResponseMessageTemplate.GENERAL_ERROR)

        try:
            with transaction.atomic():
                # send transaction to sepulsa
                julo_sepulsa_client = get_julo_sepulsa_client()
                response = julo_sepulsa_client.create_transaction(sepulsa_transaction)
                sepulsa_transaction = sepulsa_service.update_sepulsa_transaction_with_history_accordingly(
                                                sepulsa_transaction,
                                                'create_transaction',
                                                response)
                LineOfCreditPurchaseService.action_loc_sepulsa_transaction(loc, 'create_transaction', sepulsa_transaction)
                return True
        except Exception as e:
            julo_sentry_client.captureException()
            process_sepulsa_transaction_failed(sepulsa_transaction)
            raise LocException(LocResponseMessageTemplate.GENERAL_ERROR)

    @staticmethod
    def action_loc_sepulsa_transaction(loc, transaction_type, sepulsa_transaction):
        loc_service = LineOfCreditService()
        if transaction_type == 'create_transaction':
            if sepulsa_transaction.transaction_status != 'failed':
                customer_price = sepulsa_transaction.product.customer_price
                service_fee_amount = customer_price * LocConst.SERVICE_FEE_RATE
                price_amount = customer_price + service_fee_amount
                description = LineOfCreditPurchaseService.get_description_sepulsa_transaction(sepulsa_transaction)
                loc_transaction = LineOfCreditTransactionService.create_transaction(loc, price_amount, description)
                loc_service.decrease_balance(loc, loc_transaction.amount)
                sepulsa_transaction.line_of_credit_transaction = loc_transaction
                sepulsa_transaction.save()
        elif transaction_type in ['update_transaction_via_callback', 'update_transaction_via_task']:
            loc_transaction = sepulsa_transaction.line_of_credit_transaction
            if sepulsa_transaction.transaction_status == 'failed':
                LineOfCreditTransactionService.update_transaction_failed(loc_transaction)
                loc_service.increase_balance(loc, loc_transaction.amount)
            elif sepulsa_transaction.transaction_status == 'success':
                LineOfCreditTransactionService.update_transaction_success(loc_transaction)
        if sepulsa_transaction.transaction_status != 'pending':
            pn_client = get_julo_pn_client()
            pn_client.infrom_loc_sepulsa_transaction(sepulsa_transaction)

    @staticmethod
    def get_description_sepulsa_transaction(sepulsa_transaction):
        product = sepulsa_transaction.product
        number = '-'
        if product.type == SepulsaProductType.MOBILE:
            number = sepulsa_transaction.phone_number
        elif product.type == SepulsaProductType.ELECTRICITY:
            number = sepulsa_transaction.customer_number

        description = '%s/%s/%s.' % (product.title_product(), number, product.product_name)
        return description


class LineOfCreditTransactionService(object):
    @staticmethod
    def create_transaction(loc, amount, description):
        """
        Create line of credit transaction by sepulsa transaction
        """
        trans_data = {'line_of_credit_id': loc.id,
                      'type': LocTransConst.TYPE_PURCHASE,
                      'channel': LocTransConst.CHANNEL_SEPULSA,
                      'status': LocTransConst.STATUS_IN_PROCESS,
                      'amount': amount,
                      'description': description,
                      }
        with transaction.atomic():
            loc_transaction = LineOfCreditTransaction.objects.create(**trans_data)
            return loc_transaction

    @staticmethod
    def update_transaction_success(loc_transaction):
        """
        Update status transaction success
        """
        loc_transaction.status = LocTransConst.STATUS_SUCCESS
        loc_transaction.save()

    @staticmethod
    def update_transaction_failed(loc_transaction):
        """
        Update status transaction failed
        """
        loc_transaction.status = LocTransConst.STATUS_FAILED
        loc_transaction.save()

    @staticmethod
    def add_payment(loc_id, amount, channel, transaction_date, description=None):
        """
        Increases LineOfCredit.available
        Cancels notification if minimum payment paid
        """
        loc = LineOfCredit.objects.get(id=loc_id)
        trans_data = {'line_of_credit_id': loc.id,
                      'type': LocTransConst.TYPE_PAYMENT,
                      'channel': channel,
                      'status': LocTransConst.STATUS_SUCCESS,
                      'amount': amount,
                      'transaction_date': transaction_date,
                      'description': description,
                      }
        with transaction.atomic():
            LineOfCreditTransaction.objects.create(**trans_data)
            loc = LineOfCredit.objects.select_for_update().get(id=loc_id)
            loc.available += amount
            loc.save()
            statement = loc.lineofcreditstatement_set.last()
            if statement is not None:
                total_paid_amount = sum([x.amount for x in LineOfCreditTransactionService.get_payment_pending_list(loc_id)])
                if total_paid_amount >= statement.minimum_payment:
                    LineOfCreditNotificationService().cancel_notification(statement.id)
                    LineOfCreditStatementService().set_is_min_paid(loc.id)

            return True

    @staticmethod
    def add_late_fee(loc_id, amount):
        """
        Decreases LineOfCredit.available
        """
        loc = LineOfCredit.objects.get(id=loc_id)
        trans_data = {'line_of_credit_id': loc.id,
                      'type': LocTransConst.TYPE_LATE_FEE,
                      'channel': LocTransConst.CHANNEL_JULO,
                      'status': LocTransConst.STATUS_SUCCESS,
                      'amount': amount,
                      'description': 'Biaya keterlambatan',
                      }
        with transaction.atomic():
            transaction_late_fee = LineOfCreditTransaction.objects.create(**trans_data)
            loc = LineOfCredit.objects.select_for_update().get(id=loc_id)
            loc.available -= amount
            loc.save()
        return transaction_late_fee

    @staticmethod
    def add_interest(loc_id, amount):
        """
        Decreases LineOfCredit.available
        """
        loc = LineOfCredit.objects.get(id=loc_id)
        trans_data = {'line_of_credit_id': loc.id,
                      'type': LocTransConst.TYPE_INTEREST,
                      'channel': LocTransConst.CHANNEL_JULO,
                      'status': LocTransConst.STATUS_SUCCESS,
                      'amount': amount,
                      'description': 'Bunga',
                      }
        with transaction.atomic():
            transaction_interest = LineOfCreditTransaction.objects.create(**trans_data)
            loc = LineOfCredit.objects.select_for_update().get(id=loc_id)
            loc.available -= amount
            loc.save()
        return transaction_interest

    @staticmethod
    def get_purchase_pending_list(loc_id):
        query = LineOfCreditTransaction.objects.filter(line_of_credit_id=loc_id)
        query = query.filter(loc_statement__isnull=True)
        query = query.filter(type=LocTransConst.TYPE_PURCHASE)
        return list(query)

    @staticmethod
    def get_payment_pending_list(loc_id):
        query = LineOfCreditTransaction.objects.filter(line_of_credit_id=loc_id)
        query = query.filter(loc_statement__isnull=True)
        query = query.filter(type=LocTransConst.TYPE_PAYMENT)
        return list(query)

    @staticmethod
    def get_pending_list(loc_id):
        query = LineOfCreditTransaction.objects.filter(line_of_credit_id=loc_id)
        query = query.filter(loc_statement__isnull=True).exclude(
            type=LocTransConst.TYPE_PAYMENT).order_by('-cdate')
        transactions = query.values('cdate', 'amount', 'description', 'status', 'id')
        for transaction in transactions:
            transaction = LineOfCreditTransactionService.get_sepulsa_transaction_description_detail(transaction)
        return transactions

    @staticmethod
    def get_sepulsa_transaction_description_detail(loc_transaction):
        sepulsa_transaction = SepulsaTransaction.objects.filter(
            line_of_credit_transaction_id=int(loc_transaction['id'])).last()
        if not sepulsa_transaction:
            return loc_transaction
        product = sepulsa_transaction.product
        loc_transaction['description_object'] = {
            'product_name': product.product_name,
            'phone_number': sepulsa_transaction.phone_number,
            'meter_number': sepulsa_transaction.customer_number,
            'account_name': sepulsa_transaction.account_name,
            'serial_number': sepulsa_transaction.serial_number,
            'nominal': product.product_nominal,
            'total_amount': loc_transaction['amount'],
            'type': product.type,
            'category': product.category,
        }
        if 'PLN' in loc_transaction['description'] and sepulsa_transaction.serial_number:
            loc_transaction['description'] = add_token_sepulsa_transaction(
                                                                loc_transaction['description'],
                                                                sepulsa_transaction)
        return loc_transaction

    @staticmethod
    def add_to_statement(loc_id, loc_statement_id, statement_date):
        """
        Sets loc_transaction.loc_statement_id foreign keys before statement_date
        """
        transactions = LineOfCreditTransactionService.get_statement_transactions(loc_id, statement_date)
        for transaction in transactions:
            transaction.loc_statement_id = loc_statement_id
            transaction.save()

    @staticmethod
    def get_statement_transactions(loc_id, statement_date):
        query = LineOfCreditTransaction.objects.filter(line_of_credit_id=loc_id)
        statuses = [LocTransConst.STATUS_SUCCESS, LocTransConst.STATUS_FAILED]
        query = query.filter(status__in=statuses)
        query = query.filter(cdate__lte=statement_date)
        query = query.filter(loc_statement__isnull=True)
        return query


class LineOfCreditStatementService(object):
    @staticmethod
    def create(loc_id, statement_date):
        """
        Sets last billing
        Populates payment
        Populates transaction
        Calculates late fee
        Calculates interest
        Calculates billing
        Creates statement code
        Creates notification
        """
        loc = LineOfCredit.objects.get(id=loc_id)
        loc_service = LineOfCreditService()
        statement_data = {}
        late_fee = 0
        interest = 0
        payment_overpaid = 0
        transaction_late_fee = None
        transaction_interest = None
        transaction_service = LineOfCreditTransactionService()
        transaction_q = transaction_service.get_statement_transactions(loc_id,
                                                                       statement_date)
        transaction_q = transaction_q.filter(status=LocTransConst.STATUS_SUCCESS)
        payment_q = transaction_q.filter(type=LocTransConst.TYPE_PAYMENT)
        purchase_q = transaction_q.filter(type=LocTransConst.TYPE_PURCHASE)
        payment_amount = payment_q.aggregate(sum=Coalesce(Sum('amount'), 0))['sum']
        purchase_amount = purchase_q.aggregate(sum=Coalesce(Sum('amount'), 0))['sum']

        with transaction.atomic():
            if loc.lineofcreditstatement_set.exists():
                prev_statement = loc.lineofcreditstatement_set.last()
                last_billing_amount = prev_statement.billing_amount
                last_minimum_payment = prev_statement.minimum_payment
                last_payment_due_date = prev_statement.payment_due_date
                last_payment_overpaid = prev_statement.payment_overpaid
                statement_data['last_billing_amount'] = prev_statement.billing_amount
                statement_data['last_minimum_payment'] = prev_statement.minimum_payment
                statement_data['last_payment_due_date'] = prev_statement.payment_due_date
                statement_data['last_payment_overpaid'] = prev_statement.payment_overpaid
                if not prev_statement.is_min_paid:
                    loc_service.set_freeze(loc.id, LocConst.DEFAULT_FREEZE_REASON)
            else:
                last_billing_amount = 0
                last_minimum_payment = 0
                last_payment_due_date = None
                last_payment_overpaid = 0

            total_payment_amount = last_payment_overpaid + payment_amount
            if last_payment_due_date:
                paid_on_time_q = payment_q.filter(
                    transaction_date__date__lte=last_payment_due_date.date())
                paid_on_time_amount = paid_on_time_q.aggregate(
                    sum=Coalesce(Sum('amount'), 0))['sum']
                paid_on_time_amount += last_payment_overpaid
                if paid_on_time_amount < last_minimum_payment:
                    late_fee = last_billing_amount * loc.late_fee_rate
                    transaction_late_fee = transaction_service.add_late_fee(loc_id, late_fee)

                interest_amount = last_billing_amount - total_payment_amount
                if interest_amount > 0:
                    interest = math.floor(interest_amount * loc.interest_rate)
                    transaction_interest = transaction_service.add_interest(loc_id, interest)

            billing_amount = last_billing_amount - total_payment_amount + late_fee + interest + purchase_amount
            if billing_amount <= 0:
                payment_overpaid = abs(billing_amount)
                billing_amount = 0
                statement_data['is_min_paid'] = True

            statement_data['line_of_credit_id'] = loc_id
            statement_data['payment_amount'] = payment_amount
            statement_data['late_fee_rate'] = loc.late_fee_rate
            statement_data['late_fee_amount'] = late_fee
            statement_data['interest_rate'] = loc.interest_rate
            statement_data['interest_amount'] = interest
            statement_data['purchase_amount'] = purchase_amount
            statement_data['billing_amount'] = billing_amount
            statement_data['minimum_payment'] = billing_amount
            statement_data['payment_overpaid'] = payment_overpaid
            statement_data['payment_due_date'] = statement_date + relativedelta(days=LocConst.PAYMENT_GRACE_PERIOD)
            statement_data['statement_code'] = "JULO/LOC/{}-{}".format(
                statement_date.date().strftime("%Y/%m/%d"), loc.id)
            statement = LineOfCreditStatement.objects.create(**statement_data)

            transaction_service.add_to_statement(loc_id, statement.id, statement_date)
            if transaction_late_fee:
                transaction_late_fee.loc_statement_id = statement.id
                transaction_late_fee.save()
            if transaction_interest:
                transaction_interest.loc_statement_id = statement.id
                transaction_interest.save()

            # update next_statement_date
            loc_service.update_next_statement_date(loc)

            notif_service = LineOfCreditNotificationService()
            notif_service.create(statement.id, statement.payment_due_date, statement_date)

    @staticmethod
    def get_last_statement(loc_id):
        query = LineOfCreditStatement.objects.filter(line_of_credit_id=loc_id)
        return query.last()

    @staticmethod
    def get_list_transaction_by_statement(statement_id):
        transaction_list = LineOfCreditTransaction.objects.filter(loc_statement=statement_id)
        return transaction_list

    def get_statement_by_id(self, statement_id):
        try:
            statement = LineOfCreditStatement.objects.get(pk=statement_id)
        except ObjectDoesNotExist:
            return None

        transaction_list = self.get_list_transaction_by_statement(statement_id)

        statement_data = {
            'cdate': statement.cdate,
            'last_billing_amount': statement.last_billing_amount,
            'last_minimum_payment': statement.last_minimum_payment,
            'last_payment_overpaid': statement.last_payment_overpaid,
            'last_payment_due_date': statement.last_payment_due_date,
            'payment_amount': statement.payment_amount,
            'late_fee_amount': statement.late_fee_amount,
            'interest_amount': statement.interest_amount,
            'purchase_amount': statement.purchase_amount,
            'billing_amount': statement.billing_amount,
            'minimum_payment': statement.minimum_payment,
            'payment_overpaid': statement.payment_overpaid,
            'payment_due_date': statement.payment_due_date,
            'statement_code': statement.statement_code
        }

        transaction_list_data = transaction_list.values('id',
                                                        'cdate',
                                                        'amount',
                                                        'description',
                                                        'status')
        for transaction in transaction_list_data:
            transaction = \
                LineOfCreditTransactionService.get_sepulsa_transaction_description_detail(
                    transaction
                )

        data = {
            'statement': statement_data,
            'transactions': list(transaction_list_data)
        }
        return data

    @staticmethod
    def set_is_min_paid(loc_id):
        loc = LineOfCreditService().get_by_id(loc_id)
        statements = LineOfCreditStatement.objects.filter(line_of_credit=loc)
        with transaction.atomic():
            for statement in statements:
                statement.is_min_paid = True
                statement.save()

    @staticmethod
    def get_statement_list(loc_id):
        query = LineOfCreditStatement.objects.filter(line_of_credit=loc_id)
        return query


class LineOfCreditNotificationService(object):
    """
    Statement notice:
        - PN (->)
    Payment reminder:
        - Email (->, T-1)
        - SMS (T-2, T-0)
        - PN (T-2, T-0)
    """
    @staticmethod
    def create(loc_statement_id, due_date, statement_date):
        notifications = []
        for type_, channels in list(LocNotifConst.NOTIFICATION_MATRIX.items()):
            if type_ == LocNotifConst.TYPE_STATEMENT_NOTICE:
                T_date = statement_date
            if type_ == LocNotifConst.TYPE_PAYMENT_REMINDER:
                T_date = due_date

            for channel, deltas in list(channels.items()):
                for delta in deltas:
                    notification = LineOfCreditNotification(
                        loc_statement_id=loc_statement_id,
                        channel=channel,
                        type=type_,
                        send_date=T_date + delta)
                    notifications.append(notification)
        LineOfCreditNotification.objects.bulk_create(notifications)

    @staticmethod
    def execute():
        today = timezone.now()
        notif_to_send = LineOfCreditNotification.objects.filter(is_sent=False,
                                                                is_cancel=False,
                                                                send_date__lte=today)
        for loc_notif in notif_to_send:
            LineOfCreditNotificationService.send_notification(loc_notif)

    @staticmethod
    def cancel_notification(loc_statement_id):
        query = LineOfCreditNotification.objects.filter(loc_statement_id=loc_statement_id)
        query.update(is_cancel=True)

    @staticmethod
    def send_notification(loc_notif):
        template = '%s_%s' % (loc_notif.channel, loc_notif.type)
        if loc_notif.channel == LocNotifConst.CHANNEL_SMS:
            LineOfCreditNotificationService.send_sms_notification(template,
                                                                  loc_notif)
        if loc_notif.channel == LocNotifConst.CHANNEL_PN:
            LineOfCreditNotificationService.send_pn_notification(template,
                                                                 loc_notif)

        if loc_notif.channel == LocNotifConst.CHANNEL_EMAIL:
            if loc_notif.type == LocNotifConst.TYPE_STATEMENT_NOTICE:
                LineOfCreditNotificationService.send_email_notification(template,
                                                                        loc_notif)

    @staticmethod
    def send_sms_notification(template, loc_notif):
        loc_statement = loc_notif.loc_statement
        context = {
            'due_date': loc_statement.payment_due_date,
            'minimum_payment': format_currency(loc_statement.minimum_payment, 'IDR')
        }

        message = render_to_string(template + '.txt', context=context)

        application = loc_statement.line_of_credit.application_set.last()
        mobile_phone = application.mobile_phone_1

        try:
            sms_client = get_julo_sms_client()
            message, response = sms_client.sms_loc_notification(mobile_phone,
                                                                message)
        except Exception:
            sentry_client = julo_sentry_client
            sentry_client.captureException()
            return

        if response['status'] != '0':
            logger.warn({
                'send_status': response['status'],
                'loc_notification_id': loc_notif.id,
                'loc_statement_id': loc_statement.id,
                'message_id': response.get('message-id'),
                'sms_client_method_name': 'sms_loc_notification',
                'error_text': response.get('error-text'),
            })
            return

        loc_notif.is_sent = True
        loc_notif.save()

    @staticmethod
    def send_pn_notification(template, loc_notif):
        loc_statement = loc_notif.loc_statement
        context = {
            'due_date': loc_statement.payment_due_date,
            'minimum_payment': format_currency(loc_statement.minimum_payment, 'IDR')
        }

        application = loc_statement.line_of_credit.application_set.last()
        if have_pn_device(application.device):
            gcm_reg_id = application.device.gcm_reg_id

            message = render_to_string(template + '.txt', context=context)

            try:
                pn_client = get_julo_pn_client()
                pn_client.inform_loc_notification(gcm_reg_id, message)
            except GCMAuthenticationException:
                sentry_client = julo_sentry_client
                sentry_client.captureException()
                return

            loc_notif.is_sent = True
            loc_notif.save()

    @staticmethod
    def send_email_notification(template, loc_notif):
        loc_statement = loc_notif.loc_statement
        application = loc_statement.line_of_credit.application_set.last()
        due_date = loc_statement.payment_due_date.date().__format__('%d %B %Y')
        last_billing_amount = 0
        if loc_statement.last_billing_amount:
            last_billing_amount = loc_statement.last_billing_amount

        context = {
            'fullname': application.fullname,
            'statement_code': loc_statement.statement_code,
            'last_billing_amount': display_rupiah(last_billing_amount),
            'purchase_amount': display_rupiah(loc_statement.purchase_amount),
            'payment_amount': display_rupiah(loc_statement.payment_amount),
            'billing_amount': display_rupiah(loc_statement.billing_amount),
            'payment_due_date': due_date,
            'minimum_payment': display_rupiah(loc_statement.minimum_payment)
        }

        email_to = application.email
        message = render_to_string(template + '.html', context=context)

        try:
            email_client = get_julo_email_client()
            status, headers, subject, content = email_client.email_loc_notification(
                                                email_to, message)
        except Exception:
            sentry_client = julo_sentry_client
            sentry_client.captureException()
            return

        if status == 202:
            loc_notif.is_sent = True
            loc_notif.save()
        else:
            logger.warn({
                'status': status,
                'action': 'email_loc_notification',
                'loc_notification_id': loc_notif.id,
                'loc_statement_id': loc_statement.id
            })


class LineOfCreditNoteService(object):
    @staticmethod
    def create(note_text, loc, loc_statement=None):
        if loc_statement:
            return LineOfCreditNote.objects.create(line_of_credit=loc,
                                                   loc_statement=loc_statement,
                                                   note_text=note_text)
        return LineOfCreditNote.objects.create(line_of_credit=loc,
                                               note_text=note_text)

    @staticmethod
    def get_list_by_loc_id(loc_id):
        loc = LineOfCreditService().get_by_id(loc_id)
        loc_note_list = LineOfCreditNote.objects.filter(line_of_credit=loc).order_by('-cdate')
        data = []

        for note in loc_note_list:
            loc_note = {}
            loc_note['statement_code'] = None
            if note.loc_statement is not None:
                loc_note['statement_code'] = note.loc_statement.statement_code
            loc_note['agent_name'] = note.added_by.first_name
            loc_note['cdate'] = note.cdate.strftime('%d %b %Y %H:%m:%S')
            loc_note['note_text'] = note.note_text
            data.append(loc_note)

        return data



class LocCollectionService(object):
    """
    Deprecated
    """
    def get_query_by_bucket(self, bucket):
        db_object = LineOfCreditStatement.objects

        if bucket == 'all':
            queryset = Application.objects.exclude(line_of_credit=None).extra(
                select={'line_of_credit_id': 'line_of_credit_id',
                        'application_id': 'application_id'}).values(
                        'line_of_credit_id', 'application_id')
            return queryset

        q_method = getattr(LocCollConst, bucket)
        q_by_method = getattr(db_object, q_method)
        queryset = q_by_method()
        return queryset

    def get_loc_coll_list_by_bucket(self, bucket):
        loc_list = self.get_query_by_bucket(bucket)
        loc_col_list = []
        for loc_data in loc_list:
            loc_col_data = {}
            # setup ids
            application_id = int(loc_data['application_id'])

            # get objects
            application = Application.objects.get_or_none(id=application_id)
            customer = application.customer
            loc = application.line_of_credit
            if loc.id != int(loc_data['line_of_credit_id']):
                raise JuloException('missmatch application and loc!!')

            last_statement = LineOfCreditStatementService.get_last_statement(loc.id)
            if not last_statement:
                continue

            last_statement_id = last_statement.id
            last_statement_code = last_statement.statement_code

            # prepare data dict
            loc_col_data['customer_id'] = customer.id
            loc_col_data['application_id'] = application.id
            loc_col_data['email'] = application.email
            loc_col_data['fullname'] = application.fullname
            loc_col_data['loc_id'] = loc.id
            loc_col_data['status'] = loc.status
            loc_col_data['last_statement_id'] = last_statement_id
            loc_col_data['last_statement_code'] = last_statement_code
            loc_col_list.append(loc_col_data)

        return loc_col_list

    def get_bucket_count(self, bucket):
        count = len(self.get_query_by_bucket(bucket))
        return count

    def get_statement_summaries(self, loc_id):
        # get 4 last statement summaries
        statement_summaries = list(LineOfCreditStatement.objects.values()).filter(
            line_of_credit_id=loc_id).order_by('-cdate')[:4]

        return statement_summaries

    @staticmethod
    def change_loc_status(loc_id, status, freeze_reason):
        loc = LineOfCreditService().get_by_id(loc_id)
        loc.status = status
        if loc.status == LocConst.STATUS_FREEZE:
            loc.freeze_reason = freeze_reason

        loc.save()
