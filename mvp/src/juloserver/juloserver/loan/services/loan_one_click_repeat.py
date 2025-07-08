import operator
import json
from datetime import timedelta
from functools import reduce
from django.db.models import Q, Max
from django.utils import timezone

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Loan, SepulsaTransaction, FeatureSetting
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import LoanStatusCodes, ApplicationStatusCodes
from juloserver.julo.utils import display_rupiah
from juloserver.loan.constants import (
    OneClickRepeatConst,
    OneClickRepeatTransactionMethod,
    LoanFeatureNameConst,
)
from juloserver.account.constants import AccountConstant
from juloserver.julo_starter.services.services import determine_application_for_credit_info
from juloserver.julo.services import get_julo_one_is_proven
from juloserver.customer_module.services.customer_related import julo_starter_proven_bypass
from juloserver.loan.services.loan_related import is_all_product_locked
from juloserver.payment_point.models import XfersEWalletTransaction, AYCEWalletTransaction
from juloserver.payment_point.constants import (
    TransactionMethodCode,
    SepulsaTransactionStatus,
    SepulsaProductType,
    SepulsaProductCategory
)

sentry_client = get_julo_sentry_client()


class OneClickRepeatRedis:
    def __init__(self, customer_id, version):
        self.redis_client = get_redis_client()
        self.customer_id = customer_id
        self.version = version
        self.key = self.get_key()

    def get_redis_data(self):
        return self.redis_client.get(self.key)

    def set_redis_data(self, loan_info):
        self.redis_client.set(
            self.key, json.dumps(loan_info), timedelta(days=OneClickRepeatConst.REDIS_CACHE_TTL_DAY)
        )

    def get_key(self):
        if self.version == "v1":
            return OneClickRepeatConst.REDIS_KEY_CLICK_REPEAT.format(self.customer_id)
        elif self.version == "v2":
            return OneClickRepeatConst.REDIS_KEY_CLICK_REPEAT_V2.format(self.customer_id)
        else:
            return OneClickRepeatConst.REDIS_KEY_CLICK_REPEAT_V3.format(self.customer_id)


def invalidate_one_click_repeat_cache(customer):
    redis_client = get_redis_client()
    key = OneClickRepeatConst.REDIS_KEY_CLICK_REPEAT.format(customer.pk)
    key_v2 = OneClickRepeatConst.REDIS_KEY_CLICK_REPEAT_V2.format(customer.pk)
    key_v3 = OneClickRepeatConst.REDIS_KEY_CLICK_REPEAT_V3.format(customer.pk)
    redis_client.delete_key(key)
    redis_client.delete_key(key_v2)
    redis_client.delete_key(key_v3)


def get_latest_transactions_info(customer, check_exist, version, application=None):
    click_rep_redis = OneClickRepeatRedis(customer.pk, version)
    cached_data = click_rep_redis.get_redis_data()
    if check_exist and cached_data:
        return json.loads(cached_data)

    transaction_method_ids = get_transaction_method_ids(version)

    latest_transactions_info = get_latest_transactions_info_from_db(
        customer, transaction_method_ids, application
    )

    click_rep_redis.set_redis_data(latest_transactions_info)
    return latest_transactions_info


def get_transaction_method_ids(version):
    if version == 'v1':
        return OneClickRepeatTransactionMethod.V1
    elif version == 'v2':
        return OneClickRepeatTransactionMethod.V2
    else:
        return OneClickRepeatTransactionMethod.V3


def get_latest_transactions_info_from_db(customer, transaction_method_ids, application=None):
    fs = FeatureSetting.objects.filter(
        feature_name=LoanFeatureNameConst.ONE_CLICK_REPEAT, is_active=True
    ).last()
    interval_day = fs.parameters.get("interval_day", OneClickRepeatConst.INTERVAL_DAY)

    latest_transactions_info = list(
        reduce(
            lambda transactions, method_id:
                transactions + get_latest_transactions_with_method(
                    customer, method_id, application, interval_day
                ), transaction_method_ids, []
        )
    )
    latest_transactions_info.sort(key=operator.itemgetter('loan_id'), reverse=True)
    return latest_transactions_info[:OneClickRepeatConst.ONE_CLICK_REPEAT_DISPLAYED_LOAN]


def get_latest_transactions_with_method(customer, transaction_method_id,
                                        application=None, interval_day=None):
    if transaction_method_id == TransactionMethodCode.SELF.code:
        return get_tarik_dana_latest_transactions(customer, application, interval_day)

    # only for ewallet
    elif transaction_method_id == TransactionMethodCode.DOMPET_DIGITAL.code:
        return get_dompet_digital_latest_transactions(customer, interval_day)

    return get_latest_sepulsa_transactions(customer, transaction_method_id, interval_day)


def get_tarik_dana_latest_transactions(customer, application=None, interval_day=None):
    if not application:
        application = determine_application_for_credit_info(customer)

    loan_info = []
    suggested_loans = get_tarik_dana_transactions(
        customer=customer,
        application=application,
        limit=OneClickRepeatConst.ONE_CLICK_REPEAT_DISPLAYED_LOAN,
        interval_day=interval_day
    )

    for suggested_loan in suggested_loans:
        try:
            loan_detail = construct_tarik_dana_response_data(suggested_loan)
            loan_info.append(loan_detail)
        except Exception:
            sentry_client.captureException()
            continue
    return loan_info


def get_latest_sepulsa_transactions(customer, transaction_method_id, interval_day=None):
    sepulsa_transactions = get_sepulsa_transactions(
        customer=customer,
        transaction_method_id=transaction_method_id,
        limit=OneClickRepeatConst.ONE_CLICK_REPEAT_DISPLAYED_LOAN,
        interval_day=interval_day
    )
    transaction_info = []
    for transaction in sepulsa_transactions:
        try:
            transaction_detail = construct_utilities_response_data(transaction)
            transaction_info.append(transaction_detail)
        except Exception:
            sentry_client.captureException()
            continue
    return transaction_info


def get_tarik_dana_transactions(customer, application, limit=None, interval_day=None):
    suggested_loans = Loan.objects.select_related(
        'transaction_method', 'bank_account_destination'
    ).filter(
        customer_id=customer.pk,
        bank_account_destination__isnull=False,
        loan_status__gte=LoanStatusCodes.CURRENT,
        transaction_method_id=TransactionMethodCode.SELF.code
    )
    # if is proven => follow up primary bank only
    # else: show all
    is_proven = (
        get_julo_one_is_proven(application.account) or julo_starter_proven_bypass(application)
    )
    if not is_proven:
        suggested_loans = suggested_loans.filter(
            bank_account_destination__name_bank_validation_id=application.name_bank_validation_id
        )

    suggested_loans = (
        suggested_loans.values(
            'bank_account_destination',
            'loan_amount'
        )
        .annotate(latest_id=Max('id'))
        .order_by('-latest_id')
    )
    if interval_day:
        threshold = timezone.localtime(timezone.now()).date() - timedelta(days=interval_day)
        suggested_loans = suggested_loans.filter(cdate__date__gte=threshold)
    if limit:
        suggested_loans = suggested_loans[:limit]

    suggested_loans_ids = [trans['latest_id'] for trans in suggested_loans]
    suggested_loans = Loan.objects.filter(
        id__in=suggested_loans_ids
    )
    return suggested_loans


def get_sepulsa_transactions(customer, transaction_method_id, limit=None, interval_day=None):
    """"
    Get top "limit" sepulsa transactions for methods:
        - DOMPET_DIGITAL (transaction_method_id = 5)
        - PLN (transaction_method_id = 6)
        - BPJS (transaction_method_id = 7)

    """
    filter_conditions = get_filter_conditions(customer, transaction_method_id)
    sepulsa_transactions = (
        SepulsaTransaction.objects
        .filter(filter_conditions)
        .values('product', 'phone_number')
        .annotate(latest_id=Max('id'))
        .order_by('-latest_id')
    )
    if interval_day:
        threshold = timezone.localtime(timezone.now()).date() - timedelta(days=interval_day)
        sepulsa_transactions = sepulsa_transactions.filter(cdate__date__gte=threshold)
    if limit:
        sepulsa_transactions = sepulsa_transactions[:limit]

    sepulsa_transaction_ids = [trans['latest_id'] for trans in sepulsa_transactions]
    sepulsa_transactions = SepulsaTransaction.objects.filter(
        id__in=sepulsa_transaction_ids
    )

    return sepulsa_transactions


def get_filter_conditions(customer, transaction_method_id):
    return Q(
        customer_id=customer.pk,
        **get_general_filter_conditions(),
        **get_specific_filter_conditions(transaction_method_id)
    )


def get_general_filter_conditions():
    """
    Return general criteria for all transactions:
        - Transaction status = "success"
        - Loan is associated with transaction
        - Loan status >= 220 and <= 250
    """
    return dict(
        loan__loan_status__status_code__range=(
            LoanStatusCodes.CURRENT, LoanStatusCodes.PAID_OFF
        ),
        transaction_status=SepulsaTransactionStatus.SUCCESS,
    )


def get_specific_filter_conditions(transaction_method_id):
    """
    Return specific criteria for each type of transaction
    """
    if transaction_method_id == TransactionMethodCode.DOMPET_DIGITAL.code:
        return dict(
            product__type=SepulsaProductType.EWALLET
        )
    elif transaction_method_id == TransactionMethodCode.LISTRIK_PLN.code:
        return dict(
            product__type=SepulsaProductType.ELECTRICITY,
            product__category=SepulsaProductCategory.ELECTRICITY_PREPAID
        )
    elif transaction_method_id == TransactionMethodCode.BPJS_KESEHATAN.code:
        return dict(
            product__type=SepulsaProductType.BPJS
        )
    return dict()


def get_dompet_digital_latest_transactions(customer, interval_day=None):
    # get top 5 sepulsa transactions
    sepulsa_ewallet_transactions = get_sepulsa_transactions(
        customer=customer,
        transaction_method_id=TransactionMethodCode.DOMPET_DIGITAL.code,
        limit=OneClickRepeatConst.ONE_CLICK_REPEAT_DISPLAYED_LOAN,
        interval_day=interval_day
    )

    # get top 5 xfers_ewallet_transactions
    xfers_ewallet_transactions = get_xfers_or_ayc_ewallet_transactions(
        customer=customer,
        vendor_name='xfers',
        limit=OneClickRepeatConst.ONE_CLICK_REPEAT_DISPLAYED_LOAN,
        interval_day=interval_day
    )

    # get top 5 ayc_ewallet_transactions
    ayc_ewallet_transactions = get_xfers_or_ayc_ewallet_transactions(
        customer=customer,
        vendor_name='ayc',
        limit=OneClickRepeatConst.ONE_CLICK_REPEAT_DISPLAYED_LOAN,
        interval_day=interval_day
    )

    # combine and get top 5 latest transactions
    transactions = sorted(
        [*sepulsa_ewallet_transactions, *xfers_ewallet_transactions, *ayc_ewallet_transactions],
        key=lambda trans: trans.cdate,
        reverse=True
    )[:OneClickRepeatConst.ONE_CLICK_REPEAT_DISPLAYED_LOAN]

    transaction_info = []
    for transaction in transactions:
        try:
            transaction_detail = construct_utilities_response_data(transaction)
            transaction_info.append(transaction_detail)
        except Exception:
            sentry_client.captureException()
            continue
    return transaction_info


def construct_tarik_dana_response_data(loan):
    transaction_method = loan.transaction_method
    bank_account_destination = loan.bank_account_destination
    loan_amount = loan.loan_amount

    return {
        'loan_id': loan.id,
        'title': display_rupiah(loan_amount),
        'body': '{} - {}'.format(
            bank_account_destination.bank.bank_name_frontend,
            bank_account_destination.account_number
        ),
        'icon': transaction_method.foreground_icon_url,
        'transaction_method_id': loan.transaction_method_id,
        'product_data': {
            "transaction_method_name": transaction_method.fe_display_name,
            "bank_account_destination_id": loan.bank_account_destination_id,
            "bank_account_number": bank_account_destination.account_number,
            "loan_duration": loan.loan_duration,
            "loan_purpose": loan.loan_purpose,
            "loan_amount": loan_amount
        }
    }


def construct_utilities_response_data(transaction):
    loan = transaction.loan
    transaction_method = loan.transaction_method
    title, body = get_title_body_response_data(transaction_method, transaction)
    product_data = get_product_response_data(loan, transaction)

    return {
        'loan_id': loan.id,
        'title': title,
        'body': body,
        'icon': transaction_method.foreground_icon_url,
        'transaction_method_id': transaction_method.id,
        'product_data': product_data
    }


def get_product_response_data(loan, transaction):
    transaction_method = loan.transaction_method
    product_data = {
        "transaction_method_name": transaction_method.fe_display_name,
        "loan_duration": loan.loan_duration,
        "loan_amount": loan.loan_amount,
        "sepulsa_product_id": transaction.product.sepulsa_id,
        "sepulsa_product_category": transaction.product.category
    }

    if transaction_method.id == TransactionMethodCode.DOMPET_DIGITAL.code:
        product_data = {
            **product_data,
            "phone_number": transaction.phone_number
        }
    else:
        if transaction_method.id == TransactionMethodCode.BPJS_KESEHATAN.code:
            product_data['paid_period'] = transaction.paid_period
        product_data = {
            **product_data,
            "customer_number": transaction.customer_number
        }

    return product_data


def get_title_body_response_data(transaction_method, transaction):
    if transaction_method.id == TransactionMethodCode.DOMPET_DIGITAL.code:
        return transaction.product.product_name, transaction.phone_number
    elif transaction_method.id == TransactionMethodCode.BPJS_KESEHATAN.code:
        return str(transaction.paid_period) + " Bulan", transaction.customer_number
    else:
        return transaction.product.product_name, transaction.customer_number


def is_show_one_click_repeat(application):
    if (
        application.application_status_id not in ApplicationStatusCodes.active_account()
        or not application.is_julo_one_or_starter()
        or application.account.status_id != AccountConstant.STATUS_CODE.active
    ):
        return False

    if is_all_product_locked(application.account):
        return False

    return True


def get_xfers_or_ayc_ewallet_transactions(customer, vendor_name, limit=None, interval_day=None):
    if vendor_name == 'ayc':
        model_transaction = AYCEWalletTransaction
        product_field = 'ayc_product'
    elif vendor_name == 'xfers':
        model_transaction = XfersEWalletTransaction
        product_field = 'xfers_product'

    ewallet_transactions = (
        model_transaction.objects
        .filter(customer=customer, loan__loan_status__gte=LoanStatusCodes.CURRENT)
        .values(product_field, 'phone_number')
        .annotate(latest_id=Max('id'))
        .order_by('-latest_id')
    )
    if interval_day:
        threshold = timezone.localtime(timezone.now()).date() - timedelta(days=interval_day)
        ewallet_transactions = ewallet_transactions.filter(cdate__date__gte=threshold)
    if limit:
        ewallet_transactions = ewallet_transactions[:limit]

    ewallet_transaction_ids = [trans['latest_id'] for trans in ewallet_transactions]
    ewallet_transactions = model_transaction.objects.filter(
        id__in=ewallet_transaction_ids
    )

    return ewallet_transactions
