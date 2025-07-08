import logging
import time

from builtins import str
from datetime import (
    datetime,
    date,
    timedelta,
)
from typing import Any, Dict, Tuple

import pytz
from babel.dates import format_date, format_datetime
from django.forms import model_to_dict

from django.utils import timezone
from dateutil import relativedelta
from django.db.models import Sum, Max
from django.db.models.functions import Coalesce
from django.conf import settings
from django.utils.translation import gettext as _

from juloserver.account.models import AccountStatusHistory
from juloserver.account_payment.models import AccountPayment
from juloserver.ana_api.models import CustomerSegmentationComms

from juloserver.autodebet.constants import (
    AutodebetVendorConst,
    BRIErrorCode,
)
from juloserver.autodebet.models import AutodebetAPILog, AutodebetBRITransaction
from juloserver.cfs.constants import MAP_VERIFY_ACTION_WITH_VERIFY_STATUS, VerifyStatus, \
    MAP_VERIFY_STATUS_WITH_ACTION_SENT_MOENGAGE
from juloserver.channeling_loan.models import ChannelingLoanHistory
from juloserver.entry_limit.services import is_entry_level_type
from juloserver.julo.models import (
    ApplicationHistory,
    Partner,
    PaymentMethod,
    CreditScore,
    Application,
    Payment,
    Loan,
    CommsBlocked,
    PaymentMethodLookup,
    Customer,
    FeatureSetting,
)
from juloserver.julo_financing.services.token_related import get_or_create_customer_token
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.moengage.constants import (
    MoengageAccountStatusEventType,
    MoengageEventType,
    UpdateFields,
)
from juloserver.moengage.services.get_parameters import (
    get_credit_score_type,
    get_application_history_cdate,
)
from juloserver.julo.statuses import (
    PaymentStatusCodes,
    ApplicationStatusCodes,
)
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.julo.utils import (
    convert_to_me_value,
    format_e164_indo_phone_number,
    display_rupiah,
)
from juloserver.julocore.utils import localtime_timezone_offset
from juloserver.payment_point.services.sepulsa import get_payment_point_transaction_from_loan
from juloserver.pin.models import LoginAttempt
from juloserver.portal.object.lender.templatetags.currency import default_separator

from juloserver.moengage.utils import day_on_status
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo_privyid.models import PrivyCustomerData
from juloserver.julo.services2 import encrypt
from juloserver.account_payment.services.pause_reminder import \
    check_account_payment_is_blocked_comms
from juloserver.qris.services.linkage_related import get_linkage
from juloserver.urlshortener.services import shorten_url
from juloserver.autodebet.services.account_services import get_existing_autodebet_account
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.partnership.models import PartnerOrigin
from juloserver.customer_module.services.device_related import get_device_repository
from juloserver.apiv2.constants import PaymentMethodCategoryConst
from juloserver.payback.models import GopayAutodebetTransaction, GopayCustomerBalance
from juloserver.application_flow.services import check_has_path_tag
from juloserver.application_flow.models import HsfbpIncomeVerification
from juloserver.application_flow.constants import BankStatementConstant, HSFBPIncomeConst
from juloserver.graduation.constants import CustomerSuspendType
from juloserver.julo_financing.models import JFinancingVerification
from juloserver.account.models import Account
from juloserver.julo.constants import FeatureNameConst
from juloserver.dana_linking.models import DanaWalletBalanceHistory
from juloserver.julo.services2.payment_method import get_main_payment_method
from juloserver.ovo.models import OvoWalletBalanceHistory, OvoWalletAccount
from juloserver.ovo.constants import OvoWalletAccountStatusConst


logger = logging.getLogger(__name__)


loan_refinancing_request_staus = [
    CovidRefinancingConst.STATUSES.activated,
    CovidRefinancingConst.STATUSES.offer_selected,
    CovidRefinancingConst.STATUSES.offer_generated,
    CovidRefinancingConst.STATUSES.approved,
]


def construct_user_attributes(payment):
    payment.refresh_from_db()
    from juloserver.julo.services import get_payment_url_from_payment

    payment_method = PaymentMethod.objects.filter(
        loan=payment.loan, is_latest_payment_method=True
    ).last()
    if not payment_method:
        payment_method = PaymentMethod.objects.filter(loan=payment.loan, is_primary=True).last()

    va_number = ''
    va_method_name = ''
    if payment_method:
        va_number = payment_method.virtual_account
        va_method_name = payment_method.payment_method_name

    bank_account_number = 'XXXXXXXXXX'
    if payment.loan.application.bank_account_number:
        bank_account_num = payment.loan.application.bank_account_number[-4:]
        bank_account_number = bank_account_number + bank_account_num
    today = timezone.localtime(timezone.now()).date()
    query = Payment.objects.filter(loan=payment.loan, payment_status_id__lte=PaymentStatusCodes.
                                   PAYMENT_180DPD)
    total_amount = query.aggregate(total_due_amount=Sum('due_amount'),
                                   total_late_fee=Sum('late_fee_amount'),
                                   total_cashback_earned=Sum('cashback_earned'))
    loan_level_dpd = 0
    total_late_fee = 0
    total_cashback_earned = 0
    total_due_amount = 0
    if query:
        time_delta = today - query.last().due_date
        loan_level_dpd = time_delta.days
    if total_amount:
        total_late_fee = total_amount['total_late_fee'] \
            if total_amount['total_late_fee'] else 0
        total_cashback_earned = total_amount['total_cashback_earned'] \
            if total_amount['total_cashback_earned'] else 0
        total_due_amount = total_amount['total_due_amount'] \
            if total_amount['total_due_amount'] else 0
    net_due_amount = total_due_amount + total_late_fee - total_cashback_earned
    payment_url = get_payment_url_from_payment(payment)
    customer_id = payment.loan.application.customer.id
    product_line_code = payment.loan.application.product_line.product_line_type \
        if payment.loan.application.product_line else ''
    application_id = payment.loan.application.id
    today = timezone.localtime(timezone.now()).date()
    application_count = Application.objects.filter(customer=customer_id).count()
    credit_score = CreditScore.objects.get_or_none(
        application_id=payment.loan.application)
    score = ''
    if credit_score:
        score = credit_score.score
    due_date = datetime.strftime(timezone.localtime(timezone.now()), "%Y-%m-%dT%H:%M:%S.%fZ")
    if payment.due_date:
        due_date = datetime.strftime(payment.due_date, "%Y-%m-%dT%H:%M:%S.%fZ")
    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        loan=payment.loan).last()
    refinancing_status = False
    if loan_refinancing_request:
        if loan_refinancing_request.status in loan_refinancing_request_staus:
            refinancing_status = True

    firstname, lastname, fullname = '', '', ''
    if payment.loan.application.fullname:
        firstname, lastname = payment.loan.application.split_name
        fullname = payment.loan.application.full_name_only
    query = Payment.objects.filter(loan=payment.loan,
                                   payment_status_id=PaymentStatusCodes.
                                   PAID_LATE)
    late_payment_count = 0
    if query:
        late_payment_count = query.count()
    date_of_birth = datetime.strftime(timezone.localtime(timezone.now()), "%Y-%m-%dT%H:%M:%S.%fZ")
    age = 0
    if payment.loan.application.dob and payment.loan.application.dob.year >= 1900:
        date_of_birth = datetime.strftime(payment.loan.application.dob, "%Y-%m-%dT%H:%M:%S.%fZ")
        age = relativedelta.relativedelta(today, payment.loan.application.dob).years
    mobile_phone_1 = ''
    if payment.loan.application.mobile_phone_1:
        mobile_phone_1 = format_e164_indo_phone_number(
            payment.loan.application.mobile_phone_1).replace('+', '')
    gender = ''
    title = ''
    if payment.loan.application.gender:
        title = payment.loan.application.gender_title
        gender = payment.loan.application.gender
    city = ''
    if payment.loan.application.address_kabupaten:
        city = payment.loan.application.address_kabupaten

    attributes = None
    attributes = {
        "customer_id": customer_id,
        "firstname": firstname,
        "lastname": lastname,
        "fullname": fullname,
        "mobile_phone_1": mobile_phone_1,
        "application_id": application_id,
        "loan_id": payment.loan.id,
        "payment_id": payment.id,
        "email": payment.loan.application.email,
        "gender": gender,
        "age": age,
        "title": title,
        "date_of_birth": date_of_birth,
        "city": city,
        "due_date": due_date,
        "payment_level_dpd": payment.due_late_days,
        "application_status_code": payment.loan.application.status,
        "loan_status_code": payment.loan.loan_status.status_code,
        "payment_status_code": payment.status,
        "due_amount": payment.due_amount,
        "late_payment_count": late_payment_count,
        "loan_level_dpd": loan_level_dpd,
        "total_due_amount": net_due_amount,
        "payment_number": payment.payment_number,
        "cashback_amount": payment.cashback_earned if payment.cashback_earned else 0,
        "bank_name": payment.loan.application.bank_name,
        "bank_account_number": bank_account_number,
        "va_number": va_number,
        "va_method_name": va_method_name,
        "product_type": product_line_code,
        "payment_details_url": payment_url,
        "monthly_income": payment.loan.application.monthly_income
        if payment.loan.application.monthly_income else 0,
        "loan_purpose": payment.loan.application.loan_purpose,
        "is_fdc_risky": False
        if payment.loan.application.is_fdc_risky is None or
           payment.loan.application.is_fdc_risky is False
        else True,
        "job_type": payment.loan.application.job_type,
        "job_industry": payment.loan.application.job_industry,
        "score": score,
        "number_of_application": application_count,
        "refinancing_process": refinancing_status,
        "platforms": [{
            "platform": "ANDROID",
            "active": "true"}]
    }

    customer = Customer.objects.get(id=customer_id)
    payment_methods = populate_customer_payment_methods(customer)
    for k, v in payment_methods.items():
        attributes[k] = v

    user_attributes = {
        "type": "customer",
        "customer_id": customer_id,
        "attributes": attributes
    }

    return user_attributes, attributes, customer_id


def construct_data_for_loan_payment_reminders_event(payment_id):
    from juloserver.julo.services import get_payment_url_from_payment

    event_data = {}
    user_attributes = {}
    loan_id = None
    application_id = None
    payment = Payment.objects.get_or_none(pk=payment_id)
    if payment:
        device_id = ''
        if payment.loan.application_id:
            application = Application.objects.get(pk=payment.loan.application_id)
            if application:
                if application.device:
                    device_id = application.device.gcm_reg_id

        payment_method = PaymentMethod.objects.filter(
            loan=payment.loan, is_latest_payment_method=True
        ).last()
        if not payment_method:
            payment_method = PaymentMethod.objects.filter(loan=payment.loan, is_primary=True).last()
        va_number = ''
        va_method_name = ''
        if payment_method:
            va_number = payment_method.virtual_account
            va_method_name = payment_method.payment_method_name

        bank_account_number = 'XXXXXXXXXX'
        if payment.loan.application.bank_account_number:
            bank_account_num = payment.loan.application.bank_account_number[-4:]
            bank_account_number = bank_account_number + bank_account_num
        today = timezone.localtime(timezone.now()).date()
        query = Payment.objects.filter(
            loan=payment.loan, payment_status_id__lte=PaymentStatusCodes.PAYMENT_180DPD
        )
        total_amount = query.aggregate(
            total_due_amount=Sum('due_amount'),
            total_late_fee=Sum('late_fee_amount'),
            total_cashback_earned=Sum('cashback_earned'),
        )
        loan_level_dpd = 0
        if query:
            time_delta = today - query.last().due_date
            loan_level_dpd = time_delta.days
        total_late_fee = 0
        total_cashback_earned = 0
        total_due_amount = 0
        if total_amount:
            total_late_fee = total_amount['total_late_fee'] if total_amount['total_late_fee'] else 0
            total_cashback_earned = (
                total_amount['total_cashback_earned']
                if total_amount['total_cashback_earned']
                else 0
            )
            total_due_amount = (
                total_amount['total_due_amount'] if total_amount['total_due_amount'] else 0
            )
        net_due_amount = total_due_amount + total_late_fee - total_cashback_earned
        payment_url = get_payment_url_from_payment(payment)
        customer_id = payment.loan.application.customer.id
        product_line_code = (
            payment.loan.application.product_line.product_line_type
            if payment.loan.application.product_line
            else ''
        )
        loan_id = payment.loan.id
        application_id = payment.loan.application.id
        due_date = datetime.strftime(timezone.localtime(timezone.now()), "%Y-%m-%dT%H:%M:%S.%fZ")
        if payment.due_date:
            due_date = datetime.strftime(payment.due_date, "%Y-%m-%dT%H:%M:%S.%fZ")
        event_data = {
            "type": "event",
            "customer_id": customer_id,
            "device_id": device_id,
            "actions": [
                {
                    "action": "Loan_Payment_Reminders",
                    "attributes": {
                        "customer_id": customer_id,
                        "due_date": due_date,
                        "due_amount": payment.due_amount,
                        "total_due_amount": net_due_amount,
                        "loan_id": payment.loan.id,
                        "loan_level_dpd": loan_level_dpd,
                        "loan_status_code": payment.loan.loan_status.status_code,
                        "payment_id": payment.id,
                        "payment_number": payment.payment_number,
                        "product_type": product_line_code,
                        "payment_status_code": payment.status,
                        "bank_name": payment.loan.application.bank_name,
                        "bank_account_number": bank_account_number,
                        "va_number": va_number,
                        "va_method_name": va_method_name,
                        "cashback_amount": payment.cashback_earned,
                        "payment_details_url": payment_url,
                    },
                    "platform": "ANDROID",
                    "current_time": time.time(),
                    "user_timezone_offset": localtime_timezone_offset(),
                }
            ],
        }
        user_attributes, _, _ = construct_user_attributes(payment)
    return user_attributes, event_data, loan_id, application_id


def construct_data_for_payment_reminders_event(payment_id):
    from juloserver.julo.services import get_payment_url_from_payment

    event_data = {}
    user_attributes = {}
    loan_id = None
    application_id = None
    payment = Payment.objects.get_or_none(pk=payment_id)
    if payment:
        device_id = ''
        if payment.loan.application_id:
            application = Application.objects.get(pk=payment.loan.application_id)
            if application:
                if application.device:
                    device_id = application.device.gcm_reg_id

        payment_method = PaymentMethod.objects.filter(
            loan=payment.loan, is_latest_payment_method=True
        ).last()
        if not payment_method:
            payment_method = PaymentMethod.objects.filter(loan=payment.loan, is_primary=True).last()
        va_number = ''
        va_method_name = ''
        if payment_method:
            va_number = payment_method.virtual_account
            va_method_name = payment_method.payment_method_name

        bank_account_number = 'XXXXXXXXXX'
        if payment.loan.application.bank_account_number:
            bank_account_num = payment.loan.application.bank_account_number[-4:]
            bank_account_number = bank_account_number + bank_account_num
        payment_url = get_payment_url_from_payment(payment)
        customer_id = payment.loan.application.customer.id
        product_line_code = payment.loan.application.product_line.product_line_type \
            if payment.loan.application.product_line else ''
        loan_id = payment.loan.id
        application_id = payment.loan.application.id
        due_date = datetime.strftime(timezone.localtime(timezone.now()), "%Y-%m-%dT%H:%M:%S.%fZ")
        if payment.due_date:
            due_date = datetime.strftime(payment.due_date, "%Y-%m-%dT%H:%M:%S.%fZ")
        event_data = {
            "type": "event",
            "customer_id": customer_id,
            "device_id": device_id,
            "actions": [{
                "action": "Payment_Reminders",
                "attributes": {
                    "customer_id": customer_id,
                    "due_date": due_date,
                    "due_amount": payment.due_amount,
                    "payment_level_dpd": payment.due_late_days,
                    "payment_id": payment.id,
                    "loan_id": payment.loan.id,
                    "payment_number": payment.payment_number,
                    "product_type": product_line_code,
                    "payment_status_code": payment.status,
                    "bank_name": payment.loan.application.bank_name,
                    "bank_account_number": bank_account_number,
                    "va_number": va_number,
                    "va_method_name": va_method_name,
                    "cashback_amount": payment.cashback_earned if payment.cashback_earned else 0,
                    "payment_details_url": payment_url
                },
                "platform": "ANDROID",
                "current_time": time.time(),
                "user_timezone_offset": localtime_timezone_offset(),
            }
            ]
        }
        user_attributes, _, _ = construct_user_attributes(payment)
    return user_attributes, event_data, loan_id, application_id


def construct_data_for_payment_received_event(account_trx, event_type):
    application = account_trx.account.last_application
    customer = account_trx.account.customer
    device_id = ''
    if application:
        if application.device:
            device_id = application.device.gcm_reg_id
    payment_event_id_list = list(account_trx.paymentevent_set.all().values_list('id', flat=True))
    payment_id_list = list(account_trx.paymentevent_set.all().values_list('payment_id', flat=True))
    account_payment_id_list = list(
        account_trx.paymentevent_set.all().values_list('payment__account_payment_id', flat=True)
    )
    paid_during_refinancing_list = list(
        account_trx.paymentevent_set.all().values_list(
            'payment__account_payment__paid_during_refinancing', flat=True
        )
    )
    total_due_amount = account_trx.paymentevent_set.aggregate(
        total_due_amount=Sum('payment__account_payment__due_amount')
    )
    paid_during_refinancing_list = [
        False if item is None else item for item in paid_during_refinancing_list
    ]
    if True in paid_during_refinancing_list:
        paid_during_refinancing = True
    else:
        paid_during_refinancing = False
    is_paid_within_dpd_1to10_list = list(
        account_trx.paymentevent_set.all().values_list(
            'payment__account_payment__is_paid_within_dpd_1to10', flat=True
        )
    )
    is_paid_within_dpd_1to10_list = [
        False if item is None else item for item in is_paid_within_dpd_1to10_list
    ]
    if True in is_paid_within_dpd_1to10_list:
        is_paid_within_dpd_1to10 = True
    else:
        is_paid_within_dpd_1to10 = False

    unpaid_account_payment_ids = account_trx.account.get_unpaid_account_payment_ids()
    unpaid_installment_count = len(unpaid_account_payment_ids)
    is_ever_late_payments = account_trx.account.accountpayment_set.normal().exclude(
        status=PaymentStatusCodes.PAID_ON_TIME).exists()

    event_data = {
        "type": "event",
        "customer_id": customer.id,
        "device_id": device_id,
        "actions": [
            {
                "action": event_type,
                "attributes": {
                    "payment_event_id": payment_event_id_list,
                    "payment_id": payment_id_list,
                    "account_payment_id": list(set(account_payment_id_list)),
                    "paid_during_refinancing": paid_during_refinancing,
                    "is_paid_within_dpd_1to10": is_paid_within_dpd_1to10,
                    "event_payment_amount": default_separator(
                        str(account_trx.transaction_amount), '.'
                    ),
                    "event_payment_partial": True
                    if total_due_amount.get('total_due_amount', None)
                    else False,
                    "event_triggered_date": datetime.strftime(
                        timezone.localtime(timezone.now()), "%Y-%m-%d %H:%M:%S"
                    ),
                    "unpaid_installment_count": unpaid_installment_count,
                    "is_ever_late": is_ever_late_payments
                },
                "platform": "ANDROID",
                "current_time": time.time(),
                "user_timezone_offset": localtime_timezone_offset(),
            }
        ],
    }
    return event_data


def construct_data_for_loan_status_reminders_event(payment_id):
    event_data = {}

    payment = Payment.objects.get_or_none(pk=payment_id)
    if payment:
        device_id = ''
        if payment.loan.application_id:
            application = Application.objects.get(pk=payment.loan.application_id)
            if application:
                if application.device:
                    device_id = application.device.gcm_reg_id

        _, attributes, customer_id = construct_user_attributes(payment)
        attributes.pop("firstname")
        attributes.pop("lastname")
        attributes.pop("fullname")
        attributes.pop("mobile_phone_1")
        attributes.pop("application_id")
        attributes.pop("email")
        attributes.pop("title")
        attributes.pop("date_of_birth")
        attributes.pop("due_date")
        attributes.pop("payment_level_dpd")
        attributes.pop("application_status_code")
        attributes.pop("payment_status_code")
        attributes.pop("due_amount")
        attributes.pop("payment_number")
        attributes.pop("cashback_amount")
        attributes.pop("payment_details_url")
        attributes.pop("refinancing_process")
        attributes.pop("platforms")

        event_data = {
            "type": "event",
            "customer_id": customer_id,
            "device_id": device_id,
            "actions": [{
                "action": "Loan_Status_Reminders",
                "attributes": attributes,
                "platform": "ANDROID",
                "current_time": time.time(),
                "user_timezone_offset": localtime_timezone_offset(),
            }
            ]
        }

    return event_data


def construct_data_for_hi_season_reminders_event(payment_id):
    from juloserver.julo.services import get_payment_url_from_payment
    event_data = {}
    user_attributes = {}
    loan_id = None
    application_id = None
    payment = Payment.objects.get_or_none(pk=payment_id)
    if payment:
        device_id = ''
        if payment.loan.application_id:
            application = Application.objects.get(pk=payment.loan.application_id)
            if application:
                if application.device:
                    device_id = application.device.gcm_reg_id

        payment_method = PaymentMethod.objects.filter(
            loan=payment.loan, is_latest_payment_method=True
        ).last()
        if not payment_method:
            payment_method = PaymentMethod.objects.filter(loan=payment.loan, is_primary=True).last()
        va_number = ''
        va_method_name = ''
        if payment_method:
            va_number = payment_method.virtual_account
            va_method_name = payment_method.payment_method_name

        bank_account_number = 'XXXXXXXXXX'
        if payment.loan.application.bank_account_number:
            bank_account_num = payment.loan.application.bank_account_number[-4:]
            bank_account_number = bank_account_number + bank_account_num
        payment_url = get_payment_url_from_payment(payment)
        customer_id = payment.loan.application.customer.id
        product_line_code = payment.loan.application.product_line.product_line_type \
            if payment.loan.application.product_line else ''
        loan_refinancing_request = LoanRefinancingRequest.objects.filter(
            loan=payment.loan).last()
        refinancing_status = False
        if loan_refinancing_request:
            if loan_refinancing_request.status in loan_refinancing_request_staus:
                refinancing_status = True
        is_fdc_risky = payment.loan.application.is_fdc_risky
        loan_id = payment.loan.id
        application_id = payment.loan.application.id
        today = timezone.localtime(timezone.now()).date()
        query = Payment.objects.filter(loan=payment.loan,
                                       payment_status_id__lte=PaymentStatusCodes.
                                       PAYMENT_180DPD)
        loan_level_dpd = 0
        if query:
            time_delta = today - query.last().due_date
            loan_level_dpd = time_delta.days
        due_date = datetime.strftime(timezone.localtime(timezone.now()), "%Y-%m-%dT%H:%M:%S.%fZ")
        if payment.due_date:
            due_date = datetime.strftime(payment.due_date, "%Y-%m-%dT%H:%M:%S.%fZ")
        event_data = {
            "type": "event",
            "customer_id": customer_id,
            "device_id": device_id,
            "actions": [{
                "action": "Hi_Season_Lottery",
                "attributes": {
                    "customer_id": customer_id,
                    "due_date": due_date,
                    "due_amount": payment.due_amount,
                    "payment_level_dpd": payment.due_late_days,
                    "loan_level_dpd": loan_level_dpd,
                    "payment_id": payment.id,
                    "loan_id": payment.loan.id,
                    "is_fdc_risky": False
                    if is_fdc_risky is None or is_fdc_risky is False else True,
                    "loan_status_code": payment.loan.loan_status.status_code,
                    "payment_number": payment.payment_number,
                    "product_type": product_line_code,
                    "payment_status_code": payment.status,
                    "bank_name": payment.loan.application.bank_name,
                    "bank_account_number": bank_account_number,
                    "va_number": va_number,
                    "va_method_name": va_method_name,
                    "cashback_amount": payment.cashback_earned if payment.cashback_earned else 0,
                    "payment_details_url": payment_url,
                    "refinancing_process": refinancing_status
                },
                "platform": "ANDROID",
                "current_time": time.time(),
                "user_timezone_offset": localtime_timezone_offset(),
            }
            ]
        }
        user_attributes, _, _ = construct_user_attributes(payment)
    return user_attributes, event_data, loan_id, application_id


def construct_data_for_loan_status_reminders(loan):
    loan.refresh_from_db()
    device_id = ''
    if loan.application_id:
        application = Application.objects.get(pk=loan.application_id)
        if application:
            if application.device:
                device_id = application.device.gcm_reg_id

    customer_id = loan.application.customer.id
    application_count = Application.objects.filter(customer=customer_id).count()
    loan_id = loan.id
    payment_method = PaymentMethod.objects.filter(
        loan=loan_id, is_latest_payment_method=True
    ).last()
    if not payment_method:
        payment_method = PaymentMethod.objects.filter(loan=loan_id, is_primary=True).last()
    va_number = ''
    va_method_name = ''
    if payment_method:
        va_number = payment_method.virtual_account
        va_method_name = payment_method.payment_method_name
    today = timezone.localtime(timezone.now()).date()
    credit_score = CreditScore.objects.get_or_none(application_id=loan.application)
    score = ''
    if credit_score:
        score = credit_score.score

    bank_account_number = 'XXXXXXXXXX'
    if loan.application.bank_account_number:
        bank_account_number = bank_account_number + loan.application.bank_account_number[-4:]
    query = Payment.objects.filter(loan=loan)
    sub_query = query.filter(payment_status_id__lte=PaymentStatusCodes.
                             PAYMENT_180DPD)
    loan_level_dpd = 0
    if sub_query:
        time_delta = today - sub_query.last().due_date
        loan_level_dpd = time_delta.days
    query = query.filter(loan=loan,
                         payment_status_id=PaymentStatusCodes.
                         PAID_LATE)
    late_payment_count = 0
    if query:
        late_payment_count = query.count()

    firstname, lastname, fullname = '', '', ''
    if loan.application.fullname:
        firstname, lastname = loan.application.split_name
        fullname = loan.application.full_name_only
    product_line_code = loan.application.product_line.product_line_type \
        if loan.application.product_line else ''
    date_of_birth = datetime.strftime(timezone.localtime(timezone.now()), "%Y-%m-%dT%H:%M:%S.%fZ")
    age = 0
    if loan.application.dob and loan.application.dob.year >= 1900:
        date_of_birth = datetime.strftime(loan.application.dob, "%Y-%m-%dT%H:%M:%S.%fZ")
        age = relativedelta.relativedelta(today, loan.application.dob).years
    mobile_phone_1 = ''
    if loan.application.mobile_phone_1:
        mobile_phone_1 = format_e164_indo_phone_number(
            loan.application.mobile_phone_1).replace('+', '')
    title = ''
    if loan.application.gender:
        title = loan.application.gender_title

    user_attributes = {
        "type": "customer",
        "customer_id": customer_id,
        "attributes": {
            "customer_id": customer_id,
            "firstname": firstname,
            "loan_id": loan.id,
            "lastname": lastname,
            "fullname": fullname,
            "mobile_phone_1": mobile_phone_1,
            "application_id": loan.application.id,
            "email": loan.application.email,
            "gender": loan.application.gender,
            "age": age,
            "title": title,
            "date_of_birth": date_of_birth,
            "city": loan.application.address_kabupaten,
            "application_status_code": loan.application.status,
            "bank_name": loan.application.bank_name,
            "product_type": product_line_code,
            "monthly_income": loan.application.monthly_income
            if loan.application.monthly_income else 0,
            "loan_purpose": loan.application.loan_purpose,
            "is_fdc_risky": False
            if loan.application.is_fdc_risky is None or
               loan.application.is_fdc_risky is False
            else True,
            "job_type": loan.application.job_type,
            "job_industry": loan.application.job_industry,
            "score": score,
            "number_of_application": application_count,
            "loan_status_code": loan.loan_status.status_code,
            "total_due_amount": loan.installment_amount,
            "loan_level_dpd": loan_level_dpd,
            "platforms": [{
                "platform": "ANDROID",
                "active": "true"
            }]
        }
    }
    event_data = {
        "type": "event",
        "customer_id": customer_id,
        "device_id": device_id,
        "actions": [{
            "action": "Loan_Status_Reminders",
            "attributes": {
                "customer_id": customer_id,
                "total_due_amount": loan.installment_amount,
                "loan_id": loan_id,
                "loan_level_dpd": loan_level_dpd,
                "late_payment_count": late_payment_count,
                "loan_status_code": loan.loan_status.status_code,
                "product_type": product_line_code,
                "bank_name": loan.application.bank_name,
                "bank_account_number": bank_account_number,
                "va_number": va_number,
                "va_method_name": va_method_name,
                "job_type": loan.application.job_type,
                "job_industry": loan.application.job_industry,
                "is_fdc_risky": False
                if loan.application.is_fdc_risky is None or loan.application.is_fdc_risky is False
                else True,
                "monthly_income": loan.application.monthly_income
                if loan.application.monthly_income else 0,
                "loan_purpose": loan.application.loan_purpose,
                "gender": loan.application.gender,
                "age": age,
                "city": loan.application.address_kabupaten,
                "score": score,
                "number_of_application": application_count

            },
            "platform": "ANDROID",
            "current_time": time.time(),
            "user_timezone_offset": localtime_timezone_offset(),
        }
        ]
    }
    return user_attributes, event_data


def construct_data_for_application_status_reminders(application, new_status_code):
    application.refresh_from_db()
    device_id = ''
    if application.device:
        device_id = application.device.gcm_reg_id

    customer_id = application.customer.id
    application_count = Application.objects.filter(customer=customer_id).count()
    credit_score = CreditScore.objects.get_or_none(application_id=application)
    score = ''
    if credit_score:
        score = credit_score.score
    today = timezone.localtime(timezone.now()).date()

    firstname, lastname, fullname = '', '', ''
    if application.fullname:
        firstname, lastname = application.split_name
        fullname = application.full_name_only
    product_line_code = application.product_line.product_line_type \
        if application.product_line else ''
    bank_account_number = 'XXXXXXXXXX'
    if application.bank_account_number:
        bank_account_num = application.bank_account_number[-4:]
        bank_account_number = bank_account_number + bank_account_num

    date_of_birth = datetime.strftime(timezone.localtime(timezone.now()), "%Y-%m-%dT%H:%M:%S.%fZ")
    age = 0
    if application.dob and application.dob.year >= 1900:
        date_of_birth = datetime.strftime(application.dob, "%Y-%m-%dT%H:%M:%S.%fZ")
        age = relativedelta.relativedelta(today, application.dob).years
    mobile_phone_1 = ''
    if application.mobile_phone_1:
        mobile_phone_1 = format_e164_indo_phone_number(
            application.mobile_phone_1).replace('+', '')
    title = ''
    if application.gender_title:
        title = application.gender_title
    platform = 'ANDROID'
    if application and application.is_julo_one_ios():
        platform = 'iOS'

    user_attributes = {
        "type": "customer",
        "customer_id": customer_id,
        "attributes": {
            "customer_id": customer_id,
            "firstname": firstname,
            "lastname": lastname,
            "fullname": fullname,
            "mobile_phone_1": mobile_phone_1,
            "application_id": application.id,
            "email": application.email,
            "gender": application.gender,
            "bank_name": application.bank_name,
            "product_type": product_line_code,
            "bank_account_number": bank_account_number,
            "monthly_income": application.monthly_income
            if application.monthly_income else 0,
            "loan_purpose": application.loan_purpose,
            "is_fdc_risky": False
            if application.is_fdc_risky is None or
               application.is_fdc_risky is False
            else True,
            "job_type": application.job_type,
            "job_industry": application.job_industry,
            "number_of_application": application_count,
            "platforms": [{
                "platform": platform,
                "active": "true"
            }]
        }
    }

    event_data = {
        "type": "event",
        "customer_id": customer_id,
        "device_id": device_id,
        "actions": [{
            "action": "Application_Status_Reminders",
            "attributes": {
                "application_status_code": new_status_code,
                "application_id": application.id,
                "loan_amount_request": application.loan_amount_request
                if application.loan_amount_request else 0,
                "is_fdc_risky": False
                if application.is_fdc_risky is None or application.is_fdc_risky is False
                else True,
                "monthly_income": application.monthly_income
                if application.monthly_income else 0,
                "loan_purpose": application.loan_purpose,
                "gender": application.gender,
                "age": age,
                "city": application.address_kabupaten,
                "score": score,
                "number_of_application": application_count,
                "bank_account_number": bank_account_number
            },
            "platform": platform,
            "current_time": time.time(),
            "user_timezone_offset": localtime_timezone_offset(),
        }
        ]
    }

    return user_attributes, event_data


# J1 event for loan status change
def construct_data_for_loan_status_change_j1_event(loan, event_name):
    from juloserver.julo.services import get_payment_url_from_payment
    application = Application.objects.filter(account=loan.account).last()
    device_id = ''
    if application.device:
        device_id = application.device.gcm_reg_id
    customer_id = application.customer.id

    event_attributes = dict()
    event_attributes['customer_id'] = customer_id
    event_attributes["event_triggered_date"] = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S")
    if loan.loan_status_id == LoanStatusCodes.CURRENT:
        transaction_method = loan.transaction_method.fe_display_name \
            if loan.transaction_method else ''
        event_attributes['transaction_method'] = transaction_method
        event_attributes['loan_amount'] = loan.loan_amount
    else:
        event_attributes['application_id'] = application.id

    event_attributes['application_product_type'] = application.product_line.product_line_type
    event_attributes['account_id'] = loan.account_id
    event_attributes['loan_id'] = loan.id
    event_attributes['cdate'] = datetime.strftime(loan.udate, "%Y-%m-%dT%H:%M:%S.%fZ")

    if loan.loan_status_id == LoanStatusCodes.INACTIVE:
        event_attributes['day_of_status'] = day_on_status(loan.udate)

    if loan.loan_status_id in [
        LoanStatusCodes.CANCELLED_BY_CUSTOMER,
        LoanStatusCodes.INACTIVE
    ] and application.is_julo_one_product():
        event_attributes['product_type'] = _get_loan_product_type(loan)
        event_attributes['product_name'] = _get_loan_product_name(loan)

    platform = 'ANDROID'
    if application and application.is_julo_one_ios():
        platform = 'iOS'

    event_data = {
        "type": "event",
        "customer_id": customer_id,
        "device_id": device_id,
        "actions": [{
            "action": event_name,
            "attributes": event_attributes,
            "platform": platform,
            "current_time": time.time(),
            "user_timezone_offset": localtime_timezone_offset(),
        }
        ]
    }
    user_attributes = construct_user_attributes_for_j1_customer(application, application.status)
    return user_attributes, event_data


def construct_user_attributes_for_j1_customer(application, new_status_code=None):
    customer_id = application.customer.id
    application_count = Application.objects.filter(customer=customer_id).count()
    credit_score = CreditScore.objects.get_or_none(application_id=application)
    score = ''
    if credit_score:
        score = credit_score.score
    today = timezone.localtime(timezone.now()).date()
    age = relativedelta.relativedelta(today, application.dob).years
    firstname, lastname, fullname = '', '', ''
    if application.fullname:
        firstname, lastname = application.split_name
        fullname = application.full_name_only

    product_line_code = application.product_line.product_line_type \
        if application.product_line else ''
    bank_account_number = 'XXXXXXXXXX'
    if application.bank_account_number:
        bank_account_num = application.bank_account_number[-4:]
        bank_account_number = bank_account_number + bank_account_num

    mobile_phone_1 = ''
    if application.mobile_phone_1:
        mobile_phone_1 = format_e164_indo_phone_number(application.mobile_phone_1).replace('+', '')
    gender = ''
    if application.gender:
        gender = application.gender
    title = ''
    if application.gender_title:
        title = application.gender_title
    dob = ''
    if application.dob and application.dob.year >= 1900:
        dob = datetime.strftime(application.dob, "%Y-%m-%dT%H:%M:%S.%fZ")
    city = ''
    if application.address_kabupaten:
        city = application.address_kabupaten

    partner_name = ''
    if application.partner_id:
        partner_name = application.partner.name
    platform = 'ANDROID'
    if application and application.is_julo_one_ios():
        platform = 'iOS'

    user_attributes = {
        "type": "customer",
        "customer_id": customer_id,
        "attributes": {
            "customer_id": customer_id,
            "firstname": firstname,
            "lastname": lastname,
            "fullname": fullname,
            "mobile_phone_1": mobile_phone_1,
            "application_id": application.id,
            "email": application.email,
            "gender": gender,
            "age": age,
            "title": title,
            "date_of_birth": dob,
            "city": city,
            "application_status_code": new_status_code if new_status_code \
                else application.application_status_id,
            "bank_name": application.bank_name,
            "product_type": product_line_code,
            "bank_account_number": bank_account_number,
            "monthly_income": application.monthly_income
            if application.monthly_income else 0,
            "loan_purpose": application.loan_purpose,
            "is_fdc_risky": False
            if application.is_fdc_risky is None or
               application.is_fdc_risky is False
            else True,
            "job_type": application.job_type,
            "job_industry": application.job_industry,
            "score": score,
            "number_of_application": application_count,
            "is_j1_customer": application.is_julo_one(),
            "partner_name": partner_name,
            "platforms": [{
                "platform": platform,
                "active": "true"
            }]
        }
    }

    return user_attributes


def construct_user_attributes_for_account_payment_events(account_payment):
    account = account_payment.account
    customer = account.customer
    fullname = customer.fullname
    due_amount = 0
    unpaid_account_payments = account.accountpayment_set.not_paid_active()
    if not unpaid_account_payments:
        logger.warning('There are no unpaid account payment|'
                       'customer={}, account_payment={}'.format(customer.id, account_payment.id))
        return {}
    for each in unpaid_account_payments:
        due_amount += each.due_amount
    upcoming_due_amount = account.get_oldest_unpaid_account_payment().due_amount
    oldest_unpaid_date = account.get_oldest_unpaid_account_payment().due_date
    due_date = date.strftime(oldest_unpaid_date, '%d %B %Y')
    due_date_short = date.strftime(oldest_unpaid_date, '%d-%b')
    month_and_year_due_date = date.strftime(oldest_unpaid_date, '%m/%Y')
    month_due_date = date.strftime(oldest_unpaid_date, '%B')
    active_loans = account.loan_set.filter(loan_status__gte=LoanStatusCodes.CURRENT,
                                           loan_status__lt=LoanStatusCodes.PAID_OFF)
    payment_cashback_amount = 0
    for loan in active_loans:
        payment_cashback_amount += (0.01 / loan.loan_duration) * loan.loan_amount
    payment_methods = []
    payment_details = payment_details = customer.paymentmethod_set.filter(is_shown=True).values(
        'payment_method_code', 'payment_method_name', 'virtual_account', 'bank_code').order_by('-id')
    for payment_detail in payment_details:
        payment_methods.append(payment_detail)
    oldest_unpaid_payment = (
        account_payment.payment_set.not_paid_active().order_by('payment_number').first()
    )
    if not oldest_unpaid_payment:
        logger.warning(
            'There are no unpaid payment|'
            'customer={}, account_payment={}'.format(customer.id, account_payment.id)
        )
        return {}
    cashback_multiplier = oldest_unpaid_payment.cashback_multiplier
    primary_payment_method = customer.paymentmethod_set.filter(is_latest_payment_method=True).last()
    if not primary_payment_method:
        primary_payment_method = customer.paymentmethod_set.filter(is_primary=True).last()
    current_date_string = date.strftime(timezone.localtime(timezone.now()).date(), '%d-%b-%Y')
    encrypter = encrypt()
    encoded_account_payment_id = encrypter.encode_string(str(account_payment.id))
    url = settings.PAYMENT_DETAILS + str(encoded_account_payment_id)
    shortened_url = shorten_url(url)
    user_attributes = {
        "type": "customer",
        "customer_id": customer.id,
        "attributes": {
            "customer_id": customer.id,
            "email": customer.email,
            "title_short": "Bpk" if customer.gender == "Pria" else "Ibu",
            "va_method_name": primary_payment_method.payment_method_name if primary_payment_method \
                else None,
            "va_number": primary_payment_method.virtual_account if primary_payment_method \
                else None,
            "current_date_string": current_date_string,
            "due_amount": due_amount,
            "upcoming_due_amount": upcoming_due_amount,
            "dpd": account_payment.dpd,
            "month_and_year_due_date": month_and_year_due_date,
            "month_due_date": month_due_date,
            "due_date_long": due_date,
            "due_date_short": due_date_short,
            "cashback_multiplier": cashback_multiplier,
            "sum_payment_cashback_amount": payment_cashback_amount,
            "payment_details_url": shortened_url,
            "account_payment_id": account_payment.id,
            "account_id": account.id,
            "platforms": [{
                "platform": "ANDROID",
                "active": "true"
            }]
        }
    }
    return user_attributes


def construct_application_status_change_event_data_for_j1_customer(
        event_name,
        application_id,
        event_attributes
):
    application = Application.objects.get(id=application_id)
    device_id = ''
    if application.device:
        device_id = application.device.gcm_reg_id

    customer_id = application.customer.id
    platform = 'ANDROID'
    if application and application.is_julo_one_ios():
        platform = 'iOS'
    event_data = {
        "type": "event",
        "customer_id": customer_id,
        "device_id": device_id,
        "actions": [{
            "action": event_name,
            "attributes": event_attributes,
            "platform": platform,
            "current_time": time.time(),
            "user_timezone_offset": localtime_timezone_offset(),
        }]
    }

    return event_data


def construct_base_data_for_application_status_change(application_id):
    application = Application.objects.get(id=application_id)
    partner_name = ''
    if application.partner_id:
        partner_name = application.partner.name
    event_attributes = {
        "customer_id": application.customer.id,
        "partner_name": partner_name,
        "application_id": application.id,
        "cdate": get_application_history_cdate(application),
        "event_triggered_date": timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "product_type": application.product_line.product_line_type,
    }
    user_attributes = construct_user_attributes_for_j1_customer(application, application.status)
    return user_attributes, event_attributes


def construct_data_for_application_status_change_in_100(application_id):
    user_attributes, event_attributes = construct_base_data_for_application_status_change(
        application_id)
    event_attributes["day_of_status"] = day_on_status(event_attributes['cdate'])
    return user_attributes, event_attributes


def construct_data_for_application_status_change_in_105(application_id):
    application = Application.objects.get(id=application_id)
    user_attributes, event_attributes = construct_base_data_for_application_status_change(
        application_id)
    event_attributes["score_type"] = get_credit_score_type(application)
    event_attributes["day_of_status"] = day_on_status(event_attributes['cdate'])
    return user_attributes, event_attributes


def construct_data_for_application_status_change_in_106(application_id):
    application = Application.objects.get(id=application_id)
    user_attributes, event_attributes = construct_base_data_for_application_status_change(
        application_id)
    event_attributes["no_negative_payment_history"] = application.customer.can_reapply
    status = application.status
    history = ApplicationHistory.objects.filter(
        status_new=status, application_id=application.id
    ).last()
    status_old = history.status_old
    credit_score = CreditScore.objects.get_or_none(application=application)
    is_c_score = credit_score.score in ['C', '--'] if credit_score else False
    if application.customer.can_reapply:
        resubmission_status = 'REAPPLY'
    elif status_old == ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
        resubmission_status = 'RESUBMIT' if not is_c_score else 'CANNOT_RESUBMIT'
    else:
        resubmission_status = 'CANNOT_REAPPLY'
    event_attributes['resubmission_status'] = resubmission_status
    return user_attributes, event_attributes


def contruct_data_for_application_status_changes_in_120(application_id):
    application = Application.objects.get(id=application_id)
    user_attributes, event_attributes = construct_base_data_for_application_status_change(
        application_id)
    midas_eligible = HsfbpIncomeVerification.objects.filter(application_id=application_id).exists()
    event_attributes["midas_eligible"] = midas_eligible
    return user_attributes, event_attributes


def construct_data_for_application_status_change_in_124_or_130(application_id):
    user_attributes, event_attributes = construct_base_data_for_application_status_change(
        application_id)
    return user_attributes, event_attributes


def contruct_data_for_application_status_changes_in_131(application_id):
    from juloserver.julo.formulas import count_expired_date_131
    application = Application.objects.get(id=application_id)
    user_attributes, event_attributes = construct_base_data_for_application_status_change(
        application_id)
    event_attributes["day_of_status"] = day_on_status(application.cdate)
    expired_date = count_expired_date_131(
        timezone.localtime(timezone.now()).date())
    event_attributes['expiry_date'] = expired_date + ' jam  22:30'
    event_attributes['mandatory_docs_deeplink'] = "https://goo.gl/VeRC4O"

    return user_attributes, event_attributes


def contruct_data_for_application_status_changes_in_133(application_id):
    user_attributes, event_attributes = construct_base_data_for_application_status_change(
        application_id)
    return user_attributes, event_attributes


def contruct_data_for_application_status_changes_in_135(application_id):
    application = Application.objects.get(id=application_id)
    user_attributes, event_attributes = construct_base_data_for_application_status_change(
        application_id)
    event_attributes["can_reapply"] = application.customer.can_reapply
    return user_attributes, event_attributes


def contruct_data_for_application_status_changes_in_136(application_id):
    application = Application.objects.get(id=application_id)
    user_attributes, event_attributes = construct_base_data_for_application_status_change(
        application_id
    )
    if application.customer.can_reapply:
        resubmission_status = 'REAPPLY'
    else:
        resubmission_status = 'RESUBMIT'
    event_attributes['resubmission_status'] = resubmission_status
    return user_attributes, event_attributes


def contruct_data_for_application_status_changes_in_138(application_id):
    user_attributes, event_attributes = construct_base_data_for_application_status_change(
        application_id)
    return user_attributes, event_attributes


def contruct_data_for_application_status_changes_in_147(application_id):
    application = Application.objects.get(id=application_id)
    user_attributes, event_attributes = construct_base_data_for_application_status_change(
        application_id)
    event_attributes["day_of_status"] = day_on_status(application.cdate)
    reject_reason = ''
    privy_customer_data = PrivyCustomerData.objects.filter(
        customer_id=application.customer_id).last()
    if privy_customer_data:
        reject_reason = privy_customer_data.privy_customer_status
    event_attributes["reject_reason"] = reject_reason

    return user_attributes, event_attributes


def contruct_data_for_application_status_changes_in_190(application_id):
    application = Application.objects.get(id=application_id)
    user_attributes, event_attributes = construct_base_data_for_application_status_change(
        application_id)
    event_attributes["day_of_status"] = day_on_status(application.cdate)
    is_transacted = False
    if application.account_id:
        loan = Loan.objects.filter(account_id=application.account_id).last()
        if loan:
            if loan.loan_status_id == LoanStatusCodes.CURRENT:
                is_transacted = True

    event_attributes['is_transacted'] = is_transacted
    event_attributes['is_entry_level'] = is_entry_level_type(application)
    event_attributes['referral_code'] = application.referral_code
    event_attributes['midas_good_doc'] = check_has_path_tag(
        application_id, HSFBPIncomeConst.GOOD_DOC_TAG
    )

    return user_attributes, event_attributes


APPLICATION_EVENT_STATUS_CONSTRUCTORS = {
    100: {
        'construct_data': construct_data_for_application_status_change_in_100,
        'event_type': 'BEx100',
        'scheduled': True},
    105: {
        'construct_data': construct_data_for_application_status_change_in_105,
        'event_type': 'BEx105',
        'scheduled': True},
    106: {
        'construct_data': construct_data_for_application_status_change_in_106,
        'event_type': 'BEx106',
        'scheduled': False},
    109: {
        'construct_data': construct_base_data_for_application_status_change,
        'event_type': 'BEx109',
        'scheduled': False},
    115: {
        'construct_data': construct_base_data_for_application_status_change,
        'event_type': 'BEx115',
        'scheduled': False},
    120: {
        'construct_data': contruct_data_for_application_status_changes_in_120,
        'event_type': 'BEx120',
        'scheduled': False},
    121: {
        'construct_data': construct_base_data_for_application_status_change,
        'event_type': 'BEx121',
        'scheduled': False},
    124: {
        'construct_data': construct_data_for_application_status_change_in_124_or_130,
        'event_type': 'BEx124',
        'scheduled': False},
    127: {
        'construct_data': construct_base_data_for_application_status_change,
        'event_type': 'BEx127',
        'scheduled': False,
    },
    130: {
        'construct_data': construct_data_for_application_status_change_in_124_or_130,
        'event_type': 'BEx130',
        'scheduled': False},
    131: {
        'construct_data': contruct_data_for_application_status_changes_in_131,
        'event_type': 'BEx131',
        'scheduled': False,
    },
    132: {
        'construct_data': construct_base_data_for_application_status_change,
        'event_type': 'BEx132',
        'scheduled': False,
    },
    133: {
        'construct_data': contruct_data_for_application_status_changes_in_133,
        'event_type': 'BEx133',
        'scheduled': False},
    135: {
        'construct_data': contruct_data_for_application_status_changes_in_135,
        'event_type': 'BEx135',
        'scheduled': False,
    },
    136: {
        'construct_data': contruct_data_for_application_status_changes_in_136,
        'event_type': 'BEx136',
        'scheduled': False,
    },
    138: {
        'construct_data': contruct_data_for_application_status_changes_in_138,
        'event_type': 'BEx138',
        'scheduled': False
    },
    139: {
        'construct_data': construct_base_data_for_application_status_change,
        'event_type': 'BEx139',
        'scheduled': False,
    },
    147: {
        'construct_data': contruct_data_for_application_status_changes_in_147,
        'event_type': 'BEx147',
        'scheduled': True},
    153: {
        'construct_data': construct_base_data_for_application_status_change,
        'event_type': 'BEx153',
        'scheduled': False,
    },
    155: {
        'construct_data': construct_base_data_for_application_status_change,
        'event_type': 'BEx155',
        'scheduled': False,
    },
    175: {
        'construct_data': construct_base_data_for_application_status_change,
        'event_type': 'BEx175',
        'scheduled': False},
    190: {
        'construct_data': contruct_data_for_application_status_changes_in_190,
        'event_type': 'BEx190',
        'scheduled': True},
    191: {
        'construct_data': construct_base_data_for_application_status_change,
        'event_type': 'BEx191',
        'scheduled': False,
    },
}


def construct_user_attributes_for_submit_bank_statement(
    application, submission_url, is_available_bank_statement
):
    application.refresh_from_db()
    user_attributes = construct_user_attributes_for_j1_customer(application)
    user_attributes["attributes"]["submit_bank_statement_url"] = submission_url
    if is_available_bank_statement == BankStatementConstant.IS_AVAILABLE_BANK_STATEMENT_ALL:
        user_attributes["attributes"]["is_available_bank_statement"] = True
        user_attributes["attributes"]["is_available_bank_statement_email"] = True
    elif is_available_bank_statement == BankStatementConstant.IS_AVAILABLE_BANK_STATEMENT_EMAIL:
        user_attributes["attributes"]["is_available_bank_statement"] = False
        user_attributes["attributes"]["is_available_bank_statement_email"] = True
    else:
        user_attributes["attributes"]["is_available_bank_statement"] = False
        user_attributes["attributes"]["is_available_bank_statement_email"] = False
    return user_attributes


def construct_user_attributes_customer_level(
    customer: Customer, update_field: str = None, daily_update: bool = False
):
    from juloserver.cashback.services import get_expired_date_and_cashback
    from juloserver.promo.services import get_used_promo_code_for_loan

    customer.refresh_from_db()
    payment_method = get_main_payment_method(customer)
    attributes = dict()
    account = customer.account
    application = None
    loan = None

    if account:
        application = account.last_application

    if not application:
        application = customer.application_set.last()

    if account and not loan:
        loan = account.loan_set.last()

    if not update_field or update_field == 'va_number':
        va_number = ''
        if payment_method:
            va_number = payment_method.virtual_account

        attributes['va_number'] = va_number

    if not update_field or update_field == 'va_method_name':
        va_method_name = ''
        if payment_method:
            va_method_name = payment_method.payment_method_name

        attributes['va_method_name'] = va_method_name

    if not update_field or update_field == 'first_name':
        first_name = ''
        lastname = ''
        if customer.fullname:
            fullname = customer.fullname
            _, lastname = customer.split_name
            first_name = fullname.split()[0].title().replace(" ", "")

        attributes['first_name'] = first_name
        attributes['lastname'] = lastname

    if not update_field or update_field == 'bank_name':
        bank_name = ''
        if application and application.bank_name:
            bank_name = application.bank_name

        attributes['bank_name'] = bank_name

    if not update_field or update_field == 'bank_account_number':
        bank_account_number = 'XXXXXXXXXX'
        if application and application.bank_account_number:
            bank_account_num = application.bank_account_number[-4:]
            bank_account_number = bank_account_number + bank_account_num

        attributes['bank_account_number'] = bank_account_number

    if not update_field or update_field == 'gender':
        gender = ''
        title_short = ''
        title_long = ''
        if customer.gender:
            gender = customer.gender
            if gender == "Pria":
                title_long = "Bapak"
                title_short = "Bpk"
            elif gender == "Wanita":
                title_long = "Ibu"
                title_short = title_long
            else:
                title_long = "Bapak/Ibu"
                title_short = "Bpk/Ibu"

        attributes['gender'] = gender
        attributes['title_short'] = title_short
        attributes['title_long'] = title_long

    if not update_field or update_field == 'email':
        email = ''
        if customer.email:
            email = customer.email

        attributes['email'] = email

    if not update_field or update_field == 'ever_entered_250':
        ever_entered_250 = False
        ever_entered_250 = customer.ever_entered_250
        attributes['ever_entered_250'] = ever_entered_250

    if not update_field or update_field == 'can_reapply':
        can_reapply = False
        can_reapply = customer.can_reapply
        attributes['can_reapply'] = can_reapply

    if daily_update or update_field == 'self_referral_code':
        if customer.self_referral_code:
            attributes['self_referral_code'] = customer.self_referral_code

    if update_field == UpdateFields.CASHBACK:
        expired_date, total_expired_amount = get_expired_date_and_cashback(
            customer_id=customer.id,
        )
        if expired_date is not None:
            expired_date = str(expired_date)
        attributes['next_cashback_expiry_date'] = expired_date
        attributes['next_cashback_expiry_total_amount'] = total_expired_amount

    if loan:
        if loan.loan_status_id == LoanStatusCodes.CURRENT or update_field == 'promo_code':
            promo_code_usage = get_used_promo_code_for_loan(loan)
            if promo_code_usage:
                attributes['promo_code'] = promo_code_usage.promo_code.promo_code

    return attributes


def construct_wallet_balance_attributes_account_level(index: str, account: Account) -> dict:
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MOENGAGE_EWALLET_BALANCE, is_active=True
    ).last()
    if not fs:
        return dict()

    gopay_fs = fs.parameters.get("gopay", {})
    dana_fs = fs.parameters.get("dana", {})
    ovo_fs = fs.parameters.get("ovo", {})

    gopay_key_attribute = index + gopay_fs.get(
        'moengage_attribute', 'latest_gopay_wallet_is_below_15k_or_20%'
    )
    dana_key_attribute = index + dana_fs.get(
        'moengage_attribute', 'latest_dana_wallet_is_below_15k_or_20%'
    )
    ovo_key_attribute = index + ovo_fs.get(
        'moengage_attribute', 'latest_ovo_wallet_is_below_15k_or_20%'
    )
    gopay_balance_key_attribute = index + '_gopay_wallet_available_balance'
    dana_balance_key_attribute = index + '_dana_wallet_available_balance'
    ovo_balance_key_attribute = index + '_ovo_wallet_available_balance'
    gopay_last_balance_change_date_key_attribute = index + '_gopay_last_balance_change_date'
    dana_last_balance_change_date_key_attribute = index + '_dana_last_balance_change_date'
    ovo_last_balance_change_date_key_attribute = index + '_ovo_last_balance_change_date'
    attributes = dict(
        {
            gopay_key_attribute: False,
            dana_key_attribute: False,
            ovo_key_attribute: False,
            gopay_balance_key_attribute: 0,
            dana_balance_key_attribute: 0,
            ovo_balance_key_attribute: 0,
            gopay_last_balance_change_date_key_attribute: None,
            dana_last_balance_change_date_key_attribute: None,
            ovo_last_balance_change_date_key_attribute: None,
        }
    )

    start_dt = timezone.localtime(timezone.now()).date() - timedelta(days=90)
    end_dt = timezone.localtime(timezone.now())

    # gopay balance
    gopay_customer_balance = GopayCustomerBalance.objects.filter(
        account=account,
        cdate__range=(start_dt, end_dt),
    ).order_by('cdate')
    if gopay_customer_balance.exists():
        max_gopay_customer_balance = gopay_customer_balance.aggregate(
            max_balance=Max(Coalesce("balance", 0), default=0)
        )
        last_gopay_record = gopay_customer_balance.annotate(
            balance_coalesced=Coalesce('balance', 0)
        ).last()
        last_gopay_customer_balance = (
            last_gopay_record.balance_coalesced if last_gopay_record else 0
        )
        attributes[gopay_balance_key_attribute] = last_gopay_customer_balance
        attributes[gopay_last_balance_change_date_key_attribute] = last_gopay_record.cdate.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        percentage_gopay_customer_balance = (
            gopay_fs.get('treshold_percentage', 0)
            / 100
            * max_gopay_customer_balance.get('max_balance', 0)
        )
        if (
            last_gopay_customer_balance < gopay_fs.get('treshold_balance', 0)
            or last_gopay_customer_balance < percentage_gopay_customer_balance
        ):
            attributes[gopay_key_attribute] = True

    # dana balance
    dana_customer_balance = DanaWalletBalanceHistory.objects.filter(
        dana_wallet_account__account=account,
        cdate__range=(start_dt, end_dt),
    ).order_by('cdate')
    if dana_customer_balance.exists():
        max_dana_customer_balance = dana_customer_balance.aggregate(
            max_balance=Max(Coalesce("balance", 0), default=0)
        )
        last_dana_record = dana_customer_balance.annotate(
            balance_coalesced=Coalesce('balance', 0)
        ).last()
        last_dana_customer_balance = last_dana_record.balance_coalesced if last_dana_record else 0
        attributes[dana_balance_key_attribute] = last_dana_customer_balance
        attributes[dana_last_balance_change_date_key_attribute] = last_dana_record.cdate.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        percentage_dana_customer_balance = (
            dana_fs.get('treshold_percentage', 0)
            / 100
            * max_dana_customer_balance.get('max_balance', 0)
        )

        if (
            last_dana_customer_balance < dana_fs.get('treshold_balance', 0)
            or last_dana_customer_balance < percentage_dana_customer_balance
        ):
            attributes[dana_key_attribute] = True

    # ovo balance
    current_ovo_wallet = OvoWalletAccount.objects.filter(account_id=account.id, status=OvoWalletAccountStatusConst.ENABLED).last()
    if current_ovo_wallet:
        ovo_customer_balance = OvoWalletBalanceHistory.objects.filter(
            ovo_wallet_account=current_ovo_wallet,
            cdate__range=(start_dt, end_dt),
        ).order_by('cdate')
    if current_ovo_wallet and ovo_customer_balance.exists():
        max_ovo_customer_balance = ovo_customer_balance.aggregate(
            max_balance=Max(Coalesce("balance", 0), default=0)
        )
        last_ovo_record = ovo_customer_balance.annotate(
            balance_coalesced=Coalesce('balance', 0)
        ).last()
        last_ovo_customer_balance = last_ovo_record.balance_coalesced if last_ovo_record else 0
        attributes[ovo_balance_key_attribute] = last_ovo_customer_balance
        attributes[ovo_last_balance_change_date_key_attribute] = last_ovo_record.cdate.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        percentage_ovo_customer_balance = (
            ovo_fs.get('treshold_percentage', 0)
            / 100
            * max_ovo_customer_balance.get('max_balance', 0)
        )
        if (
            last_ovo_customer_balance < ovo_fs.get('treshold_balance', 0)
            or last_ovo_customer_balance < percentage_ovo_customer_balance
        ):
            attributes[ovo_key_attribute] = True

    return attributes


def construct_user_attributes_account_level(
    customer: Customer, update_field: str = None, daily_update: bool = False
):
    from juloserver.moengage.utils import (
        get_total_due_amount,
        total_of_cashback_amount,
        get_due_date_account_payment,
        format_money_to_rupiah,
    )
    from juloserver.portal.core.templatetags.unit import (
        format_rupiahs,
    )
    from juloserver.account_payment.services.earning_cashback import (
        get_paramters_cashback_new_scheme,
    )

    attributes = dict()
    accounts = customer.account_set.all().order_by('id')
    if not accounts:
        return attributes

    _, cashback_percentage_mapping = get_paramters_cashback_new_scheme()
    for account in accounts:
        index = get_index_using_account_mapping(account)

        oldest_unpaid_account_payment = account.get_oldest_unpaid_account_payment()
        oldest_account_payment = account.accountpayment_set.all().order_by('due_date').last()
        upcoming_due_amount = 0
        due_date_short = ''
        due_date_long = ''
        month_and_year_due_date = ''
        dpd = ''
        due_amount = ''
        shortened_url = ''
        sum_payment_cashback_amount = 0
        cashback_multiplier = ''
        payment_id = ''
        payment_status_code = ''
        total_due_amount = 0

        # if there is an account, add a user's property -- value: account_id, type: string
        attributes[index + '_account_id_string'] = str(account.id)
        attributes[index + '_account_status_code'] = account.status_id

        # Assign cashback attributes
        cashback_counter = account.cashback_counter_for_customer
        attributes[index + '_cashback_counter'] = cashback_counter
        attributes[index + '_cashback_percentage'] = cashback_percentage_mapping.get(
            str(cashback_counter)
        )

        if not oldest_account_payment:
            return attributes
        comms_block = CommsBlocked.objects.filter(account=account).last()
        autodebet_account = get_existing_autodebet_account(account)
        # handle paid off account
        if not oldest_unpaid_account_payment:
            is_comms_blocked = check_account_payment_is_blocked_comms(oldest_account_payment)
            due_date_short, due_date_long, month_due_date, \
            month_and_year_due_date, due_date = get_due_date_account_payment(
                oldest_account_payment)
            dpd = oldest_account_payment.dpd

            attributes[index + '_due_amount'] = oldest_account_payment.due_amount
            attributes[index + '_payment_status_code'] = oldest_account_payment.status_id
            attributes[index + '_payment_id'] = oldest_account_payment.id
            attributes[index + '_upcoming_due_amount'] = upcoming_due_amount
            attributes[index + '_upcoming_formated_due_amount'] = format_rupiahs(upcoming_due_amount, 'no_currency')
            attributes[index + '_formated_due_amount'] = format_rupiahs(due_amount, 'no_currency')
            attributes[index + '_payment_details_url'] = shortened_url
            attributes[index + '_sum_payment_cashback_amount'] = sum_payment_cashback_amount
            attributes[index + '_cashback_due_date_slash'] = format_date(due_date - timedelta(days=2), 'dd/MM/yyyy')
            attributes[index + '_due_date_slash'] = format_date(due_date, 'dd/MM/yyyy')
            attributes[index + '_year_due_date'] = format_date(due_date, 'yyyy')
            attributes[index + '_due_date_short'] = due_date_short
            attributes[index + '_due_date_long'] = due_date_long
            attributes[index + '_month_due_date'] = month_due_date
            attributes[index + '_month_and_year_due_date'] = month_and_year_due_date
            attributes[index + '_dpd'] = dpd
            attributes[index + '_cashback_multiplier'] = cashback_multiplier
            attributes[index + '_total_due_amount'] = oldest_account_payment.due_amount
            attributes[index + '_is_email_blocked'] = comms_block.is_email_blocked \
                if is_comms_blocked else False
            attributes[index + '_is_sms_blocked'] = comms_block.is_sms_blocked \
                if is_comms_blocked else False
            attributes[index + '_is_pn_blocked'] = comms_block.is_pn_blocked \
                if is_comms_blocked else False
            if daily_update:
                account_limit = account.get_account_limit
                attributes[index + '_available_limit'] = (
                    account_limit.available_limit if account_limit else 0
                )
                attributes[index + '_available_limit_text'] = (
                    format_money_to_rupiah(account_limit.available_limit) if account_limit else 0
                )
            attributes[index + '_is_use_autodebet'] = (
                False if not autodebet_account else autodebet_account.is_use_autodebet
            )

            return attributes

        # handle loan refinancing j1
        account_property = account.accountproperty_set.last()
        attributes[index + '_refinancing_ongoing'] = account_property.refinancing_ongoing
        encrypter = encrypt()
        encoded_account_payment_id = encrypter.encode_string(str(
            oldest_unpaid_account_payment.id))
        url = settings.PAYMENT_DETAILS + str(encoded_account_payment_id)
        shortened_url = shorten_url(url)
        due_date_short, due_date_long, month_due_date, month_and_year_due_date, _ = \
            get_due_date_account_payment(oldest_unpaid_account_payment)
        dpd = oldest_unpaid_account_payment.dpd
        total_due_amount = get_total_due_amount(account)
        due_amount = oldest_unpaid_account_payment.due_amount
        sum_payment_cashback_amount = total_of_cashback_amount(account)
        payment_status_code = oldest_account_payment.status_id
        payment_id = oldest_unpaid_account_payment.id
        cashback_multiplier = oldest_unpaid_account_payment.cashback_multiplier
        attributes[index + '_account_id'] = account.id
        due_date = oldest_unpaid_account_payment.due_date
        upcoming_account_payment = account.accountpayment_set.filter(
            due_date__gt=due_date).order_by('cdate').first()

        if upcoming_account_payment:
            upcoming_due_amount = upcoming_account_payment.due_amount

        if not update_field or update_field == 'due_amount':
            is_comms_blocked = check_account_payment_is_blocked_comms(oldest_unpaid_account_payment)
            attributes[index + '_payment_status_code'] = payment_status_code
            attributes[index + '_payment_id'] = payment_id
            attributes[index + '_payment_details_url'] = shortened_url
            attributes[index + '_sum_payment_cashback_amount'] = sum_payment_cashback_amount
            attributes[index + '_cashback_due_date_slash'] = format_date(due_date - timedelta(days=2), 'dd/MM/yyyy')
            attributes[index + '_due_date_slash'] = format_date(due_date, 'dd/MM/yyyy')
            attributes[index + '_year_due_date'] = format_date(due_date, 'yyyy')
            attributes[index + '_due_date_short'] = due_date_short
            attributes[index + '_due_date_long'] = due_date_long
            attributes[index + '_month_due_date'] = month_due_date
            attributes[index + '_month_and_year_due_date'] = month_and_year_due_date
            attributes[index + '_dpd'] = dpd
            attributes[index + '_upcoming_due_amount'] = upcoming_due_amount
            attributes[index + '_upcoming_formated_due_amount'] = format_rupiahs(upcoming_due_amount, 'no_currency')
            attributes[index + '_formated_due_amount'] = format_rupiahs(due_amount, 'no_currency')
            attributes[index + '_due_amount'] = due_amount
            attributes[index + '_cashback_multiplier'] = cashback_multiplier
            attributes[index + '_total_due_amount'] = total_due_amount
            attributes[index + '_is_email_blocked'] = comms_block.is_email_blocked \
                if is_comms_blocked else False
            attributes[index + '_is_sms_blocked'] = comms_block.is_sms_blocked \
                if is_comms_blocked else False
            attributes[index + '_is_pn_blocked'] = comms_block.is_pn_blocked \
                if is_comms_blocked else False
            attributes[index + '_is_use_autodebet'] = False if not autodebet_account \
                else autodebet_account.is_use_autodebet

        if daily_update:
            account_limit = account.get_account_limit
            attributes[index + '_available_limit'] = (
                account_limit.available_limit if account_limit else 0
            )
            attributes[index + '_available_limit_text'] = (
                format_money_to_rupiah(account_limit.available_limit) if account_limit else 0
            )

        latest_payment = (
            account.accountpayment_set.paid_or_partially_paid().order_by('paid_date').last()
        )
        if latest_payment and daily_update:
            attributes[index + '_latest_amount_payment'] = latest_payment.paid_amount
            attributes[index + '_latest_date_time_of_payment'] = format_datetime(
                timezone.localtime(latest_payment.udate), "yyyy-MM-dd HH:mm:ss"
            )
            attributes[
                index + '_latest_method_of_payment'
            ] = account.get_last_used_payment_method_name

        if daily_update:
            wallet_balance_attributes = construct_wallet_balance_attributes_account_level(
                index,
                account,
            )
            attributes.update(wallet_balance_attributes)

    return attributes


def construct_data_for_account_payment_comms_block(customer, account_payment):
    from juloserver.moengage.utils import (
        get_total_due_amount,
        total_of_cashback_amount,
        get_due_date_account_payment,
    )
    from juloserver.portal.core.templatetags.unit import (
        format_rupiahs,
    )
    attributes = dict()
    accounts = customer.account_set.all().order_by('id')
    index = None
    i = 0
    for account in accounts:
        i += 1
        if account.id == account_payment.account.id:
            index = 'account' + str(i)
            break
    if not index:
        logger.warning('construct_data_for_account_payment_comms_block account not found')
        return attributes
    upcoming_due_amount = 0
    encrypter = encrypt()
    encoded_account_payment_id = encrypter.encode_string(str(account_payment.id))
    url = settings.PAYMENT_DETAILS + str(encoded_account_payment_id)
    shortened_url = shorten_url(url)
    due_date_short, due_date_long, month_due_date, month_and_year_due_date, _ = \
        get_due_date_account_payment(account_payment)
    dpd = account_payment.dpd
    total_due_amount = get_total_due_amount(account_payment.account)
    due_amount = account_payment.due_amount
    sum_payment_cashback_amount = total_of_cashback_amount(account_payment.account)
    payment_status_code = account_payment.status_id
    payment_id = account_payment.id
    cashback_multiplier = account_payment.cashback_multiplier
    attributes[index + '_account_id'] = account_payment.account.id
    due_date = account_payment.due_date
    upcoming_account_payment = account_payment.account.accountpayment_set.filter(
        due_date__gt=due_date).order_by('cdate').first()
    if upcoming_account_payment:
        upcoming_due_amount = upcoming_account_payment.due_amount

    attributes[index + '_payment_status_code'] = payment_status_code
    attributes[index + '_payment_id'] = account_payment.id
    attributes[index + '_payment_details_url'] = shortened_url
    attributes[index + '_sum_payment_cashback_amount'] = sum_payment_cashback_amount
    attributes[index + '_cashback_due_date_slash'] = format_date(due_date - timedelta(days=2), 'dd/MM/yyyy')
    attributes[index + '_due_date_slash'] = format_date(due_date, 'dd/MM/yyyy')
    attributes[index + '_year_due_date'] = format_date(due_date, 'yyyy')
    attributes[index + '_due_date_short'] = due_date_short
    attributes[index + '_due_date_long'] = due_date_long
    attributes[index + '_month_due_date'] = month_due_date
    attributes[index + '_month_and_year_due_date'] = month_and_year_due_date
    attributes[index + '_dpd'] = dpd
    attributes[index + '_upcoming_due_amount'] = upcoming_due_amount
    attributes[index + '_upcoming_formated_due_amount'] = format_rupiahs(upcoming_due_amount, 'no_currency')
    attributes[index + '_formated_due_amount'] = format_rupiahs(due_amount, 'no_currency')
    attributes[index + '_due_amount'] = due_amount
    attributes[index + '_cashback_multiplier'] = cashback_multiplier
    attributes[index + '_total_due_amount'] = total_due_amount
    comms_block = CommsBlocked.objects.filter(account=account_payment.account).last()
    is_comms_blocked = check_account_payment_is_blocked_comms(account_payment)
    attributes[index + '_is_email_blocked'] = comms_block.is_email_blocked \
        if is_comms_blocked else False
    attributes[index + '_is_sms_blocked'] = comms_block.is_sms_blocked \
        if is_comms_blocked else False
    attributes[index + '_is_pn_blocked'] = comms_block.is_pn_blocked \
        if is_comms_blocked else False

    return attributes


def construct_user_attributes_account_level_available_limit_change(customer, account, limit_val):
    from juloserver.moengage.utils import format_money_to_rupiah

    application = customer.application_set.last()

    platform = 'ANDROID'
    if application and application.is_julo_one_ios():
        platform = 'iOS'

    attributes = {
        "platforms": [{
            "platform": platform,
            "active": "true"}]
    }
    user_attributes = {
        "type": "customer",
        "customer_id": customer.id,
        "attributes": attributes
    }
    account_level_attributes = dict()
    accounts = customer.account_set.all().order_by('id')
    if not accounts:
        return user_attributes
    i = 1
    index = None
    for acc in accounts:
        if acc.id == account.id:
            index = 'account' + str(i)
            break
        i += 1
    if not index:
        raise ValueError('account %s not belong to the customer %s' % (account.id, customer.id))
    account_level_attributes[index + '_available_limit'] = limit_val
    account_level_attributes[index + '_available_limit_text'] = format_money_to_rupiah(limit_val)
    attributes.update(account_level_attributes)

    return user_attributes


def construct_user_attributes_customer_level_referral_change(customer, update_field):
    application = customer.application_set.last()
    platform = 'ANDROID'
    if application and application.is_julo_one_ios():
        platform = 'iOS'
    attributes = {
        "platforms": [{
            "platform": platform,
            "active": "true"}]
    }
    user_attributes = {
        "type": "customer",
        "customer_id": customer.id,
        "attributes": attributes
    }
    customer_level_attributes = construct_user_attributes_customer_level(customer, update_field)
    attributes.update(customer_level_attributes)

    return user_attributes


def construct_user_attributes_for_realtime_basis(
    customer: Customer,
    update_field: str = None,
    daily_update: bool = False,
    is_religious_holiday: bool = False,
) -> dict:
    """
    Central function that constructs a set of user attributes at different levels based on
    processing needs in MoEngage system.

    Args:
        customer (Customer): A customer class object.
        update_field (str):
        daily_update (bool):

    Returns:
        user_attributes (dict): Returns a dictionary containing all sorts of user attributes.
    """
    customer_level_attributes = construct_user_attributes_customer_level(
        customer, update_field, daily_update=daily_update
    )
    account_level_attributes = construct_user_attributes_account_level(
        customer, update_field, daily_update=daily_update
    )
    application_level_attributes = construct_user_attributes_application_level(
        customer, update_field
    )
    payment_level_attributes = construct_user_attributes_payment_level(customer, update_field)

    attributes = dict()
    application = customer.application_set.last()

    platform = 'ANDROID'
    if application and application.is_julo_one_ios():
        platform = 'iOS'
    platforms = {
        "platforms": [{
            "platform": platform,
            "active": "true"}]
    }
    attributes.update(customer_level_attributes)
    attributes.update(account_level_attributes)
    attributes.update(application_level_attributes)
    attributes.update(payment_level_attributes)
    attributes.update(platforms)

    if daily_update:
        is_today_religious_holiday = {'is_religious_holiday': is_religious_holiday}
        attributes.update(is_today_religious_holiday)

    user_attributes = {"type": "customer", "customer_id": customer.id, "attributes": attributes}

    return user_attributes


def construct_user_attributes_customer_level_cashback_expiry(customer, update_field):
    attributes = {
        "platforms": [{
            "platform": "ANDROID",
            "active": "true"}]
    }
    user_attributes = {
        "type": "customer",
        "customer_id": customer.id,
        "attributes": attributes
    }
    customer_level_attributes = construct_user_attributes_customer_level(customer, update_field)
    attributes.update(customer_level_attributes)

    return user_attributes

def construct_user_attributes_for_comms_blocked(customer, account_payment):
    account_level_attributes = construct_data_for_account_payment_comms_block(
        customer, account_payment)
    attributes = {
        "platforms": [{
            "platform": "ANDROID",
            "active": "true"}]
    }
    attributes.update(account_level_attributes)

    user_attributes = {
        "type": "customer",
        "customer_id": customer.id,
        "attributes": attributes
    }

    return user_attributes


def construct_base_data_for_account_payment_status_change(account_payment, cdate):
    event_attributes = {
        "customer_id": account_payment.account.customer.id,
        "cdate": cdate.strftime("%Y-%m-%d %H:%M:%S"),
        "account_payment_id": account_payment.id,
        "account_id": account_payment.account.id,
        "event_triggered_date": timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S"),
    }
    user_attributes = construct_user_attributes_for_account_payment_events(account_payment)
    return user_attributes, event_attributes


def construct_user_attributes_application_level(
        customer: Customer, update_field: str = None
) -> dict:
    attributes = dict()
    application = Application.objects.filter(
        customer=customer
    ).last()

    if not application:
        return attributes
    product_line_code = application.product_line.product_line_type if \
        application.product_line else ''
    is_fdc_risky = False if application.is_fdc_risky is None or application.is_fdc_risky is False \
        else True
    monthly_income = application.monthly_income if application.monthly_income else 0
    loan_purpose = application.loan_purpose if application.loan_purpose else ''
    customer_id = application.customer_id
    application_count = 1

    if customer_id:
        application_count = Application.objects.filter(customer=customer_id).count()
    credit_score = CreditScore.objects.get_or_none(
        application=application)
    score = ''
    if credit_score:
        score = credit_score.score

    is_j1_customer = False

    if application.is_julo_one():
        is_j1_customer = True
    mobile_phone_1 = ''

    if application.mobile_phone_1:
        mobile_phone_1 = format_e164_indo_phone_number(application.mobile_phone_1).replace('+', '')

    date_of_birth = datetime.strftime(timezone.localtime(timezone.now()), "%Y-%m-%dT%H:%M:%S.%fZ")
    age = 0
    today = timezone.localtime(timezone.now()).date()
    if application.dob and application.dob.year >= 1900:
        date_of_birth = datetime.strftime(application.dob, "%Y-%m-%dT%H:%M:%S.%fZ")
        age = relativedelta.relativedelta(today, application.dob).years

    city = ''
    if application.address_kabupaten:
        city = application.address_kabupaten

    job_type = ''
    if application.job_type:
        job_type = application.job_type

    application_status_code = ''
    if application.status:
        application_status_code = application.status

    job_industry = ''
    if application.job_industry:
        job_industry = application.job_industry

    partner_name = ''
    if application.partner_id:
        partner_name = application.partner.name

    attributes['application_id'] = application.id
    if not update_field or update_field == 'application_status_code':
        attributes['application_status_code'] = application_status_code
    if not update_field or update_field == 'product_type':
        attributes['product_type'] = product_line_code
    if not update_field or update_field == 'is_fdc_risky':
        attributes['is_fdc_risky'] = is_fdc_risky
    if not update_field or update_field == 'monthly_income':
        attributes['monthly_income'] = monthly_income
    if not update_field or update_field == 'loan_purpose':
        attributes['loan_purpose'] = loan_purpose
    attributes['application_count'] = application_count
    if not update_field or update_field == 'job_type':
        attributes['job_type'] = job_type
    if not update_field or update_field == 'job_industry':
        attributes['job_industry'] = job_industry
    attributes['score'] = score
    attributes['is_j1_customer'] = is_j1_customer
    if not update_field or update_field == 'mobile_phone_1':
        attributes['mobile_phone_1'] = mobile_phone_1
        attributes['mobile'] = mobile_phone_1
    if not update_field or update_field == 'dob':
        attributes['age'] = age
        attributes['date_of_birth'] = date_of_birth
    if not update_field or update_field == 'city':
        attributes['city'] = city
    if not update_field or update_field == 'address_provinsi':
        attributes['address_provinsi'] = ''
        if application.address_provinsi:
            attributes['address_provinsi'] = application.address_provinsi
    if not update_field or update_field == 'partner_name':
        attributes['partner_name'] = partner_name
    if not update_field or update_field == 'is_deleted':
        if application.is_deleted:
            attributes.update({'is_deleted': True, 'moe_unsubscribe': True})
        else:
            attributes['is_deleted'] = False
    if not update_field or update_field == 'app_version':
        attributes['app_version'] = application.app_version

    if application.application_status_id == ApplicationStatusCodes.LOC_APPROVED:
        attributes['is_entry_level'] = is_entry_level_type(application)
    elif (
        application.application_status_id
        == ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
    ):
        latest_x131_application_history = ApplicationHistory.objects.filter(
            application=application,
            status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        ).last()
        attributes['x131_change_reason'] = latest_x131_application_history.change_reason

    return attributes


def construct_user_attributes_payment_level(customer, update_field=None):
    attributes = dict()
    loan = Loan.objects.filter(customer=customer).last()
    if not loan:
        return attributes

    oldest_payment = loan.payment_set.all().order_by('due_date').last()
    payment = loan.get_oldest_unpaid_payment()
    if not payment and not oldest_payment:
        return attributes

    payment_id = ''
    payment_level_dpd = ''
    payment_status_code = ''
    due_amount = ''
    payment_number = ''
    cashback_amount = ''
    loan_id = ''
    loan_status_code = ''
    loan_level_dpd = ''
    payment_number = ''
    cashback_amount = ''

    # for handle loan paid off
    if not payment and oldest_payment:
        if oldest_payment.id:
            payment_id = oldest_payment.id

        if oldest_payment.get_dpd:
            payment_level_dpd = oldest_payment.get_dpd

        if oldest_payment.status:
            payment_status_code = oldest_payment.status

        if oldest_payment.due_amount:
            due_amount = oldest_payment.due_amount

        if oldest_payment.payment_number:
            payment_number = oldest_payment.payment_number

        if oldest_payment.cashback_earned:
            cashback_amount = oldest_payment.cashback_earned

        attributes['payment_id'] = payment_id
        attributes['payment_level_dpd'] = payment_level_dpd
        attributes['payment_status_code'] = payment_status_code
        attributes['due_amount'] = due_amount
        attributes['payment_number'] = payment_number
        attributes['cashback_amount'] = cashback_amount

        return attributes

    today = timezone.localtime(timezone.now()).date()
    query = Payment.objects.filter(loan=loan, payment_status_id__lte=PaymentStatusCodes.
                                   PAYMENT_180DPD)
    total_amount = query.aggregate(total_due_amount=Sum('due_amount'),
                                   total_late_fee=Sum('late_fee_amount'),
                                   total_cashback_earned=Sum('cashback_earned'))
    loan_level_dpd = 0
    total_late_fee = 0
    total_cashback_earned = 0
    total_due_amount = 0

    if query.exists():
        time_delta = today - query.last().due_date
        loan_level_dpd = time_delta.days
    if total_amount:
        total_late_fee = total_amount['total_late_fee'] \
            if total_amount['total_late_fee'] else 0
        total_cashback_earned = total_amount['total_cashback_earned'] \
            if total_amount['total_cashback_earned'] else 0
        total_due_amount = total_amount['total_due_amount'] \
            if total_amount['total_due_amount'] else 0
    net_due_amount = total_due_amount + total_late_fee - total_cashback_earned

    query = Payment.objects.filter(loan=loan,
                                   payment_status_id=PaymentStatusCodes.PAYMENT_180DPD)
    late_payment_count = 0
    if query.exists():
        late_payment_count = query.count()

    if loan.application_id:
        loan_refinancing_request = LoanRefinancingRequest.objects.filter(
            account_id__isnull=True,
            loan=loan).last()
    elif not loan.application_id:
        loan_refinancing_request = LoanRefinancingRequest.objects.filter(
            account_id__isnull=False,
            account=customer.account).last()

    refinancing_status = False
    if loan_refinancing_request:
        if loan_refinancing_request.status in loan_refinancing_request_staus:
            refinancing_status = True

    if payment and payment.id:
        payment_id = payment.id
    if payment and payment.loan_id:
        loan_id = payment.loan_id

    attributes['payment_id'] = payment_id
    attributes['loan_id'] = loan_id

    if loan.loan_status.status_code:
        loan_status_code = loan.loan_status.status_code

    if payment and payment.get_dpd:
        payment_level_dpd = payment.get_dpd

    if payment and payment.status:
        payment_status_code = payment.status

    if payment and payment.due_amount:
        due_amount = payment.due_amount

    if payment and payment.payment_number:
        payment_number = payment.payment_number

    if payment and payment.cashback_earned:
        cashback_amount = payment.cashback_earned

    if not update_field or update_field == 'loan_status_code':
        attributes['loan_status_code'] = loan.loan_status.status_code
        attributes['loan_level_dpd'] = loan_level_dpd

    if not update_field or update_field == 'payment_status':
        attributes['loan_status_code'] = loan_status_code
        attributes['loan_level_dpd'] = loan_level_dpd
        attributes['payment_level_dpd'] = payment_level_dpd
        attributes['payment_status_code'] = payment_status_code
        attributes['due_amount'] = due_amount
        attributes['total_due_amount'] = net_due_amount
        attributes['payment_number'] = payment_number
        attributes['cashback_amount'] = cashback_amount
        attributes['late_payment_count'] = late_payment_count

    if not update_field or update_field == 'payment_due_amount':
        attributes['due_amount'] = due_amount
        attributes['total_due_amount'] = net_due_amount

    if not update_field or update_field == "cashback_amount":
        attributes['cashback_amount'] = cashback_amount

    attributes['refinancing_status'] = refinancing_status
    return attributes


def construct_user_attributes_for_realtime_basis_wl_url(customer, wl_url=None, mtl=False):
    wl_url = wl_url.replace("https://", "")
    application = customer.application_set.last()
    platform = 'ANDROID'
    if application and application.is_julo_one_ios():
        platform = 'iOS'
    platforms = {
        "platforms": [{
            "platform": platform,
            "active": "true"}]
    }

    attributes = dict()
    if mtl:
        attributes['nonj1_wl_url'] = wl_url
    else:
        attributes['wl_url'] = wl_url
    attributes.update(platforms)

    user_attributes = {
        "type": "customer",
        "customer_id": customer.id,
        "attributes": attributes
    }

    return user_attributes


def get_index_using_account_mapping(account):
    account_lookup = account.account_lookup
    if not account_lookup:
        return ''
    else:
        return 'account' + account_lookup.moengage_mapping_number

def populate_customer_payment_methods(customer):
    payment_methods = (
        customer.paymentmethod_set.filter(is_shown=True)
        .order_by(
            '-is_primary',
            'sequence',
        )
        .values(
            'payment_method_code',
            'payment_method_name',
            'virtual_account',
            'bank_code',
            'is_primary',
        )
    )

    va_keys, e_wallet_keys, another_method_keys = [], [], []
    va_values, e_wallet_values, another_method_values = [], [], []

    for payment_method in payment_methods:
        payment_method_name = payment_method["payment_method_name"]
        payment_method_value = payment_method["virtual_account"]

        if payment_method_name in PaymentMethodCategoryConst.PAYMENT_METHOD_VA \
            and not payment_method["is_primary"]:
            va_keys.append(payment_method_name)
            va_values.append(payment_method_value)
        elif payment_method_name in PaymentMethodCategoryConst.PAYMENT_METHOD_E_WALLET:
            e_wallet_keys.append(payment_method_name)
            e_wallet_values.append(payment_method_value)
        elif payment_method_name in PaymentMethodCategoryConst.PAYMENT_METHOD_ANOTHER_METHOD:
            another_method_keys.append(payment_method_name)
            another_method_values.append(payment_method_value)

    return {
        "va_keys": va_keys,
        "va_values": va_values,
        "e_wallet_keys": e_wallet_keys,
        "e_wallet_values": e_wallet_values,
        "another_method_keys": another_method_keys,
        "another_method_values": another_method_values,
    }


def populate_customer_primary_payment_method(customer):
    va_method_name, va_number = "", ""

    primary_payment_method = PaymentMethod.objects.filter(
        customer=customer, is_latest_payment_method=True
    ).last()
    if not primary_payment_method:
        primary_payment_method = PaymentMethod.objects.filter(
            customer=customer, is_primary=True
        ).last()
    if primary_payment_method:
        va_method_name = primary_payment_method.payment_method_name
        va_number = primary_payment_method.virtual_account

    return {
        "va_method_name": va_method_name,
        "va_number": va_number,
    }


def construct_update_user_attributes_for_j1(customer, update_data=None):
    application = customer.application_set.filter(
        product_line__product_line_type="J1"
    ).order_by('cdate').last()

    platform = 'ANDROID'
    if application and application.is_julo_one_ios():
        platform = 'iOS'

    platforms = {
        "platforms": [{
            "platform": platform,
            "active": "true",
        }]
    }

    attributes = dict()

    if update_data:
        if 'partner_name' in update_data:
            if application.partner_id:
                partner_name = application.partner.name
                attributes['partner_name'] = partner_name
        if 'payment_methods' in update_data:
            payment_methods = populate_customer_payment_methods(customer)
            for k, v in payment_methods.items():
                attributes[k] = v
        if 'primary_va' in update_data:
            primary_payment_method = populate_customer_primary_payment_method(customer)
            for k, v in primary_payment_method.items():
                attributes[k] = v

    attributes.update(platforms)

    user_attributes = {
        "type": "customer",
        "customer_id": customer.id,
        "attributes": attributes
    }

    return user_attributes


def construct_data_for_referral_event(customer, event_type, cashback_earned):
    from juloserver.moengage.constants import MoengageEventType

    account = customer.account

    cdate_at_130 = ''
    device_id = ''
    loan_id = ''
    account_id = ''
    event_attributes = {}
    application = None
    product_line_code = ''

    if account:
        loan = account.loan_set.first()
        if loan:
            loan_id = loan.id
        account_id = account.id
        application = account.application_set.last()

    if application:
        cdate_at_130 = get_application_history_cdate(application, 130)
        product_line_code = (
            application.product_line.product_line_type
            if application.product_line else ''
        )
        if application.device:
            device_id = application.device.gcm_reg_id

    event_attributes['loan_id'] = loan_id
    event_attributes['account_id'] = account_id
    event_attributes['self_referral_code'] = customer.self_referral_code
    event_attributes['cdate_at_130'] = cdate_at_130
    event_attributes['product_type'] = product_line_code
    if event_type in (
            MoengageEventType.BEx190_NOT_YET_REFER,
            MoengageEventType.BEx190_NOT_YET_REFER_JULOVER,
            MoengageEventType.BEx220_GET_REFERRER
    ):
        event_attributes.update({
            'customer_referred_id': customer.id,
            'referred_cashback_earned': cashback_earned
        })
    elif event_type in MoengageEventType.BEX220_GET_REFEREE:
        event_attributes.update({
            'customer_referee_id': customer.id,
            'referee_cashback_earned': cashback_earned
        })

    event_data = {
        "type": "event",
        "customer_id": customer.id,
        "device_id": device_id,
        "actions": [{
            "action": event_type,
            "attributes": event_attributes,
            "platform": "ANDROID",
            "current_time": time.time(),
            "user_timezone_offset": localtime_timezone_offset(),
        }]
    }
    return event_data


def construct_event_attributes_for_promo_code_usage(loan, event_name):
    from juloserver.promo.services import get_used_promo_code_for_loan
    application = Application.objects.filter(account=loan.account).last()
    device_id = application.device.gcm_reg_id if application.device else ''
    customer_id = application.customer.id

    event_attributes = dict()
    event_attributes['customer_id'] = customer_id
    event_attributes["event_triggered_date"] = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S")
    promo_code_usage = get_used_promo_code_for_loan(loan)
    event_attributes['promo_code'] = promo_code_usage.promo_code.promo_code if promo_code_usage else ''
    event_attributes['loan_id'] = loan.id
    event_attributes['loan_amount'] = loan.loan_amount
    event_attributes['cdate'] = datetime.strftime(loan.udate, "%Y-%m-%dT%H:%M:%S.%fZ")

    event_data = {
        "type": "event",
        "customer_id": customer_id,
        "device_id": device_id,
        "actions": [{
            "action": event_name,
            "attributes": event_attributes,
            "platform": "ANDROID",
            "current_time": time.time(),
            "user_timezone_offset": localtime_timezone_offset(),
        }
        ]
    }
    return event_data


def construct_user_attributes_with_linking_status(account, partner_origin_id, partner_loan_request_id):
    customer_id = account.customer.id
    partner_origin = PartnerOrigin.objects.filter(id=partner_origin_id).last()
    attributes = dict()
    platforms = {
        "platforms": [{
            "platform": "ANDROID",
            "active": "true"}]
    }
    attributes['account_status_code'] = account.status_id
    attributes['partner_origin_name'] = partner_origin.partner_origin_name
    attributes['is_linked'] = partner_origin.is_linked
    attributes['partner_id'] = partner_origin.partner.id
    attributes['partner_loan_request_id'] = partner_loan_request_id
    attributes.update(platforms)

    user_attributes = {
        "type": "customer",
        "customer_id": customer_id,
        "attributes": attributes
    }
    return user_attributes


def construct_data_for_autodebit_failed_deduction(account_payment_id, customer, vendor, event_type):
    if vendor == AutodebetVendorConst.BCA:
        autodebit_log = AutodebetAPILog.objects.filter(
            account_payment_id=account_payment_id, http_status_code=400
        ).last()
        if not autodebit_log:
            return
        error_message = autodebit_log.error_message
    elif vendor == AutodebetVendorConst.BRI:
        autodebit_log = AutodebetBRITransaction.objects.filter(
            status='FAILED', account_payment_id=account_payment_id
        ).last()
        if not autodebit_log:
            return
        error_message = autodebit_log.description
    elif vendor == AutodebetVendorConst.GOPAY:
        autodebit_log = GopayAutodebetTransaction.objects.filter(
            customer=customer, status_code=202
        ).last()
        if not autodebit_log:
            return
        error_message = autodebit_log.status_desc
    elif vendor == AutodebetVendorConst.MANDIRI:
        autodebit_log = AutodebetAPILog.objects.filter(
            account_payment_id=account_payment_id,
            request_type='[POST] /WEBHOOK/AUTODEBET/MANDIRI/V1/PURCHASE_NOTIFICATION',
            error_message__isnull=False
        ).last()
        if not autodebit_log:
            return
        error_message = autodebit_log.error_message
    else:
        return

    application = customer.application_set.last()
    device_id = ''
    if application:
        if application.device:
            device_id = application.device.gcm_reg_id

    event_data = {
        "type": "event",
        "customer_id": customer.id,
        "device_id": device_id,
        "actions": [
            {
                "action": event_type,
                "attributes": {
                    "cdate": datetime.strftime(
                        timezone.localtime(autodebit_log.cdate), "%Y-%m-%d %H:%M:%S"
                    ),
                    "vendor": vendor,
                    "error_message": error_message,
                    "account_payment_id": account_payment_id,
                },
                "platform": "ANDROID",
                "current_time": timezone.localtime(datetime.now()).timestamp(),
                "user_timezone_offset": localtime_timezone_offset(),
            }
        ],
    }

    return event_data


def construct_event_attributes_for_fraud_ato_device_change(fraud_flag, loan):
    event_time = timezone.localtime(fraud_flag.cdate)
    event_attribute = {
        "loan_id": loan.id,
        "loan_amount": loan.loan_amount,
        "product_type": _get_loan_product_type(loan),
        "product_name": _get_loan_product_name(loan),
        "event_triggered_date": event_time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    device_repo = get_device_repository()
    event_data = {
        "type": "event",
        "customer_id": loan.customer_id,
        "device_id": device_repo.get_active_fcm_id(loan.customer_id),
        "actions": [{
            "action": MoengageEventType.FRAUD_ATO_DEVICE_CHANGE,
            "attributes": event_attribute,
            "platform": "ANDROID",
            "current_time": event_time.timestamp(),
            "user_timezone_offset": event_time.utcoffset().seconds
        }]
    }
    return event_data


def _get_loan_product_type(loan):
    return loan.transaction_method.fe_display_name if loan.transaction_method else ''


def _get_loan_product_name(loan):
    if loan.transaction_method_id in TransactionMethodCode.payment_point():
        payment_point_transaction = get_payment_point_transaction_from_loan(loan=loan)
        return payment_point_transaction.product.product_name

    if loan.transaction_method_id in TransactionMethodCode.cash():
        return _get_loan_product_type(loan)

    if loan.transaction_method_id == TransactionMethodCode.E_COMMERCE.code:
        return loan.bank_account_destination.description


def construct_data_for_julo_card_status_change_event(credit_card_application_history, event_name):
    credit_card_application = credit_card_application_history.credit_card_application
    account = credit_card_application.account
    device_repo = get_device_repository()
    customer_id = account.customer_id
    card_number = credit_card_application.creditcard_set.values_list(
        'card_number', flat=True
    ).last()
    event_datetime = timezone.localtime(credit_card_application_history.cdate)

    event_attributes = {
        "event_triggered_date": event_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        "credit_card_application_id": credit_card_application.id,
        "card_number": card_number,
    }

    event_data = {
        "type": "event",
        "customer_id": customer_id,
        "device_id": device_repo.get_active_fcm_id(customer_id),
        "actions": [{
            "action": event_name,
            "attributes": event_attributes,
            "platform": "ANDROID",
            "current_time": event_datetime.timestamp(),
            "user_timezone_offset": event_datetime.utcoffset().seconds
        }
        ]
    }
    return event_data


def construct_data_for_rpc_sales_ops(application, event_type, agent_assignment, r_score,
                                     promotion_code, minimum_transaction):
    device_id = ''
    if application and application.device:
        device_id = application.device.gcm_reg_id
    event_time = timezone.localtime(agent_assignment.cdate)
    customer_id = application.customer_id
    # add completed_date = completed_date + 6 days is logic define by OPS
    completed_date_plus6 = agent_assignment.completed_date + timedelta(days=6)
    completed_date_plus6 = datetime.strftime(
        timezone.localtime(completed_date_plus6), "%Y-%m-%d %H:%M:%S"
    )
    event_attributes = {
        "r_score": r_score,
        "promo_code_salesops": promotion_code,
        "completed_date_plus6": completed_date_plus6,
        "minimum_transaction": minimum_transaction,
    }

    event_data = construct_data_moengage_event_data(
        customer_id, device_id, event_type, event_attributes, event_time
    )

    return event_data


def construct_data_for_rpc_sales_ops_pds(application, event_type, agent_assignment,
                                         promotion_code, minimum_transaction):
    device_id = ''
    if application and application.device:
        device_id = application.device.gcm_reg_id
    event_time = timezone.localtime(agent_assignment.cdate)
    customer_id = application.customer_id
    completed_date = datetime.strftime(
        timezone.localtime(agent_assignment.completed_date), "%Y-%m-%d %H:%M:%S"
    )
    event_attributes = {
        "promo_code": promotion_code,
        "completed_date": completed_date,
        "minimum_transaction": minimum_transaction,
    }

    event_data = construct_data_moengage_event_data(
        customer_id, device_id, event_type, event_attributes, event_time
    )

    return event_data


def construct_data_for_account_status_change(account_status_history):
    """
    Construct the user attribute and the event attribute that should be sent to ME for
    account status change.

    Args:
        account_status_history (AccountStatusHistory): The object of Account Status History

    Returns:
        (dict, dict): The tuple of a single user_attribute and a single event_attribute.
        event_attribute might be None if there is no event found in MoengageAccountStatusEventType
    """
    account = account_status_history.account
    account_prefix = get_index_using_account_mapping(account)
    user_attributes = {
        "type": "customer",
        "customer_id": account.customer_id,
        "attributes": {
            "customer_id": account.customer_id,
            "account_status_code": account.status_id,
            f"{account_prefix}_account_id_string": str(account.id),
            f"{account_prefix}_account_status_code": account.status_id,
        }
    }

    event_type = 'STATUS_' + str(account_status_history.status_new_id)
    event_name = getattr(MoengageAccountStatusEventType, event_type, '')
    if not event_name:
        return user_attributes, None

    event_attributes = {
        "account_id": account.id,
        "account_lookup_name": account.account_lookup.name,
        "old_status_code": account_status_history.status_old_id,
        "old_status_name": (
            account_status_history.status_old.status
            if account_status_history.status_old_id
            else None
        ),
        "new_status_code": account_status_history.status_new_id,
        "new_status_name": account_status_history.status_new.status,
        "reason": account_status_history.change_reason,
    }

    event_data = {
        "type": "event",
        "customer_id": account.customer_id,
        "actions": [{
            "action": event_name,
            "attributes": event_attributes,
            "platform": "ANDROID",
            "current_time": account_status_history.cdate.timestamp(),
            "user_timezone_offset": localtime_timezone_offset(),
        }]
    }

    return user_attributes, event_data


def construct_data_moengage_user_attributes(customer_id, **kwargs):
    customer = Customer.objects.filter(id=customer_id).last()
    application = customer.application_set.last()
    platform = 'ANDROID'
    if application and application.is_julo_one_ios():
        platform = 'iOS'
    return {
        "type": "customer",
        "customer_id": customer_id,
        "attributes": {
            "customer_id": customer_id,
            "platforms": [{"platform": platform, "active": "true"}],
            **kwargs
        },
    }


def construct_data_moengage_event_data(
    customer_id, device_id, event_type, event_attributes, event_time
):
    customer = Customer.objects.filter(id=customer_id).last()
    application = customer.application_set.last()
    platform = 'ANDROID'
    if application and application.is_julo_one_ios():
        platform = 'iOS'
    return {
        "type": "event",
        "customer_id": customer_id,
        "device_id": device_id,
        "actions": [
            {
                "action": event_type,
                "attributes": event_attributes,
                "platform": platform,
                "current_time": event_time.timestamp(),
                "user_timezone_offset": event_time.utcoffset().seconds,
            }
        ],
    }


def construct_moengage_event_data(
    event_type: str, customer_id: int, event_attributes: Dict[str, Any]
):
    """
    Common use case for 'construct_data_moengage_event_data()'
    """
    customer = Customer.objects.get_or_none(id=customer_id)
    if not customer:
        raise ValueError('customer_id={} is not found'.format(customer_id))

    application = customer.account.get_active_application()

    return construct_data_moengage_event_data(
        customer_id=customer_id,
        device_id=application.device.gcm_reg_id if application.device else '',
        event_type=event_type,
        event_attributes=event_attributes,
        event_time=timezone.localtime(timezone.now()),
    )


def construct_data_for_balance_consolidation_verification(
    application, status_new, change_reason, event_time, agent_id, event_type
):
    device_id = ''
    if application and application.device:
        device_id = application.device.gcm_reg_id
    event_time = timezone.localtime(event_time)
    customer_id = application.customer_id

    user_attributes = construct_data_moengage_user_attributes(customer_id)
    event_attributes = {
        "balance_cons_validation_status": status_new,
        "change_reason": change_reason,
        "balance_cons_agent_id": agent_id,
    }

    event_data = construct_data_moengage_event_data(
        customer_id, device_id, event_type, event_attributes, event_time
    )

    return user_attributes, event_data


def construct_data_for_balance_consolidation_submit_form_id(application_id, event_type):
    from juloserver.balance_consolidation.services import BalanceConsolidationToken

    token_obj = BalanceConsolidationToken()

    application = Application.objects.get(id=application_id)
    device_id = ''

    if application and application.device:
        device_id = application.device.gcm_reg_id
    customer_id = application.customer_id

    event_time, expiry_time, encrypted_str = token_obj.generate_token_balance_cons_submit(
        customer_id
    )
    user_attributes = construct_data_moengage_user_attributes(
        customer_id, balance_cons_encrypted_key=encrypted_str
    )
    event_attributes = {
        "key_event_time": event_time.strftime('%Y-%m-%d, %H:%M:%S %z'),
        "key_expiry_time": expiry_time.strftime('%Y-%m-%d, %H:%M:%S %z'),
    }

    event_data = construct_data_moengage_event_data(
        customer_id, device_id, event_type, event_attributes, event_time
    )

    return user_attributes, event_data


def construct_data_for_cfs_mission_verification_change(
    application,
    assignment_verification,
    event_type
):
    device_id = ''
    if application and application.device:
        device_id = application.device.gcm_reg_id
    event_time = timezone.localtime(assignment_verification.cdate)
    customer_id = application.customer_id
    cfs_action = assignment_verification.cfs_action_assignment.action

    user_attributes = construct_data_moengage_user_attributes(customer_id)
    event_attributes = {
        "status": MAP_VERIFY_STATUS_WITH_ACTION_SENT_MOENGAGE[assignment_verification.verify_status],
        "cfs_action_code": cfs_action.action_code,
        "cfs_action_title": cfs_action.title,
        "cfs_action_id": cfs_action.id,
    }

    event_data = construct_data_moengage_event_data(
        customer_id, device_id, event_type, event_attributes, event_time
    )

    return user_attributes, event_data


def construct_data_for_jstarter_limit_approved(application, event_type, js_workflow):
    device_id = ''
    if application and application.device:
        device_id = application.device.gcm_reg_id
    event_time = timezone.localtime(timezone.now())
    customer_id = application.customer_id
    user_attributes = construct_data_moengage_user_attributes(customer_id)
    event_attributes = {
        "js_workflow": js_workflow,
    }
    event_data = construct_data_moengage_event_data(
        customer_id, device_id, event_type, event_attributes, event_time
    )
    return user_attributes, event_data


def construct_data_for_early_limit_release(application, limit_release_amount, event_type, status):
    device_id = ''
    if application and application.device:
        device_id = application.device.gcm_reg_id
    event_time = timezone.localtime(timezone.now())
    customer_id = application.customer_id

    user_attributes = construct_data_moengage_user_attributes(customer_id)
    event_attributes = {
        "status": status,
        "limit_release_amount": display_rupiah(limit_release_amount),
    }

    event_data = construct_data_moengage_event_data(
        customer_id, device_id, event_type, event_attributes, event_time
    )

    return user_attributes, event_data


def construct_data_for_typo_calls_unsuccessful(application, event_type, workflow_name):
    device_id = ''
    if application and application.device:
        device_id = application.device.gcm_reg_id
    event_time = timezone.localtime(timezone.now())
    customer_id = application.customer_id
    user_attributes = construct_data_moengage_user_attributes(customer_id)
    event_attributes = {
        "workflow_name": workflow_name,
    }
    event_data = construct_data_moengage_event_data(
        customer_id, device_id, event_type, event_attributes, event_time
    )
    return user_attributes, event_data


def construct_data_for_change_lender(event_type, loan, customer_id):
    application = Application.objects.filter(customer_id=customer_id).last()

    transaction_method = loan.transaction_method.fe_display_name if loan.transaction_method else ''

    channeling_loan_history = ChannelingLoanHistory.objects.filter(loan=loan).last()
    # new lender already set to loan in update_loan_lender, get old lender from channeling history
    current_lender = channeling_loan_history.old_lender

    user_attributes = construct_data_moengage_user_attributes(
        customer_id, fullname_with_title=application.fullname_with_title
    )
    event_data = construct_data_moengage_event_data(
        customer_id=customer_id,
        device_id=application.device.gcm_reg_id if application.device else '',
        event_type=event_type,
        event_attributes={
            'customer_id': customer_id,
            'event_triggered_date': timezone.localtime(timezone.now()).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            'transaction_method': transaction_method,
            'loan_amount': loan.loan_amount,
            'account_id': loan.account_id,
            'loan_id': loan.id,
            'cdate': datetime.strftime(loan.udate, "%Y-%m-%dT%H:%M:%S.%fZ"),
            'current_lender_id': current_lender.id,
            'current_lender_display_name': current_lender.lender_display_name,
            'new_lender_id': loan.lender_id,  # new lender already set to loan in update_loan_lender
            'new_lender_display_name': loan.lender.lender_display_name,
            'transfer_date': timezone.localtime(channeling_loan_history.cdate).strftime(
                "%b %d, %Y, %I:%M %p"
            ),
        },
        event_time=timezone.localtime(timezone.now()),
    )

    return user_attributes, event_data


def construct_data_for_idfy_verification_success(application, event_type):
    device_id = ''
    if application and application.device:
        device_id = application.device.gcm_reg_id
    event_time = timezone.localtime(timezone.now())
    customer_id = application.customer_id
    user_attributes = construct_data_moengage_user_attributes(customer_id)
    event_attributes = {}
    event_data = construct_data_moengage_event_data(
        customer_id, device_id, event_type, event_attributes, event_time
    )
    return user_attributes, event_data


def construct_data_for_idfy_completed_data(application, event_type):
    device_id = ''
    if application and application.device:
        device_id = application.device.gcm_reg_id
    event_time = timezone.localtime(timezone.now())
    customer_id = application.customer_id
    user_attributes = construct_data_moengage_user_attributes(customer_id)
    event_attributes = {}
    event_data = construct_data_moengage_event_data(
        customer_id, device_id, event_type, event_attributes, event_time
    )
    return user_attributes, event_data


def construct_data_for_autodebet_payment_method_disabled(
        customer, vendor, event_type, start_date_time, end_date_time):
    application = Application.objects.filter(customer_id=customer.id).last()
    device_id = ''
    if application:
        if application.device:
            device_id = application.device.gcm_reg_id
    event_data = {
        "type": "event",
        "customer_id": customer.id,
        "device_id": device_id,
        "actions": [{
            "action": event_type,
            "attributes": {
                "vendor": vendor,
                "disable_start_date_time": start_date_time,
                "disable_end_date_time": end_date_time
            },
            "platform": "ANDROID",
            "current_time": time.time(),
            "user_timezone_offset": localtime_timezone_offset(),
        }
        ]
    }
    return event_data


def construct_data_for_customer_reminder_vkyc(application, event_type):
    device_id = ''
    if application and application.device:
        device_id = application.device.gcm_reg_id
    event_time = timezone.localtime(timezone.now())
    customer_id = application.customer_id
    user_attributes = construct_data_moengage_user_attributes(customer_id)
    event_attributes = {}
    event_data = construct_data_moengage_event_data(
        customer_id, device_id, event_type, event_attributes, event_time
    )
    return user_attributes, event_data


def construct_data_to_send_churn_users_to_moengage(churn_user):
    churn_customer_id = churn_user.customer_id
    customer = Customer.objects.filter(id=churn_customer_id ).last()
    device_id = ''
    attributes = {'customer_id': churn_customer_id,
                   'predict_date': churn_user.predict_date.strftime('%Y-%m-%d'),
                   'pchurn': churn_user.pchurn,
                   'experiment_group': churn_user.experiment_group,
                   'model_version': churn_user.model_version,
                    }
    user_attributes = {
        "type": "customer",
        "customer_id": churn_customer_id,
        "attributes": attributes
    }
    if customer:
        application = customer.account.get_active_application()
        if application and application.device:
                device_id = application.device.gcm_reg_id
    event_data = {
        "type": "event",
        "customer_id": churn_customer_id,
        "device_id": device_id,
        "actions": [{
            "action": MoengageEventType.IS_CHURN_EXPERIMENT,
            "attributes": user_attributes,
            "platform": "ANDROID",
            "current_time": time.time(),
            "user_timezone_offset": localtime_timezone_offset(),
        }]
    }

    return user_attributes, event_data


def construct_user_attributes_for_graduation_downgrade(
    customer, account, new_set_limit, old_set_limit, event_type, graduation_flow=None,
        graduation_date=None
):
    device_id = ''
    application = account.get_active_application()
    if application and application.device:
        device_id = application.device.gcm_reg_id

    event_time = timezone.localtime(timezone.now())

    attributes = {
        "old_set_limit": convert_to_me_value(old_set_limit),
        "new_set_limit": convert_to_me_value(new_set_limit),
    }
    if event_type == MoengageEventType.GRADUATION:
        attributes['additional_limit'] = convert_to_me_value(new_set_limit - old_set_limit)
        attributes['graduated_date'] = graduation_date.astimezone(pytz.utc).isoformat()
    else:
        attributes['downgrade_limit'] = convert_to_me_value(old_set_limit - new_set_limit)

    if graduation_flow:
        attributes['graduation_flow'] = graduation_flow

    user_attributes = construct_data_moengage_user_attributes(customer.id, **attributes)
    event_data = {
        "type": "event",
        "customer_id": customer.id,
        "device_id": device_id,
        "actions": [
            {
                "action": event_type,
                "attributes": attributes,
                "platform": "ANDROID",
                "current_time": event_time.timestamp(),
                "user_timezone_offset": event_time.utcoffset().seconds,
            }
        ],
    }

    return user_attributes, event_data


def construct_data_for_activated_autodebet(customer, event_type, payday, vendor, next_due=None):
    application = Application.objects.filter(customer_id=customer.id).last()
    device_id = ''
    if application:
        if application.device:
            device_id = application.device.gcm_reg_id

    due_date = None
    if next_due:
        next_due = AccountPayment.objects.get(pk=next_due).due_date
        due_date = "{} {}".format(next_due.day, next_due.strftime("%B %Y"))

    event_data = {
        "type": "event",
        "customer_id": customer.id,
        "device_id": device_id,
        "actions": [
            {
                "action": event_type,
                "attributes": {
                    "payday": payday,
                    "vendor": vendor,
                    "due_date": due_date,
                },
                "platform": "ANDROID",
                "current_time": time.time(),
                "user_timezone_offset": localtime_timezone_offset(),
            }
        ],
    }
    return event_data


def construct_data_for_cashback_freeze_unfreeze(
    customer, account, referral_type, status, cashback_earned
):
    user_attributes = construct_data_moengage_user_attributes(customer.id)

    application = account.get_active_application()
    device_id = ''
    if application and application.device:
        device_id = application.device.gcm_reg_id

    event_time = timezone.localtime(timezone.now())
    attributes = {
        'status': status,
        'referral_type': referral_type,
        'cashback_earned': convert_to_me_value(cashback_earned),
    }
    event_data = {
        "type": "event",
        "customer_id": customer.id,
        "device_id": device_id,
        "actions": [
            {
                "action": MoengageEventType.REFERRAL_CASHBACK,
                "attributes": attributes,
                "platform": "ANDROID",
                "current_time": event_time.timestamp(),
                "user_timezone_offset": event_time.utcoffset().seconds,
            }
        ],
    }

    return user_attributes, event_data


def construct_data_for_active_julo_care(event_type, loan, customer_id):
    application = Application.objects.filter(customer_id=customer_id).last()
    user_attributes = construct_data_moengage_user_attributes(
        customer_id, fullname_with_title=application.fullname_with_title
    )
    event_data = construct_data_moengage_event_data(
        customer_id=customer_id,
        device_id=application.device.gcm_reg_id if application.device else '',
        event_type=event_type,
        event_attributes={
            'customer_id': customer_id,
            'event_triggered_date': timezone.localtime(timezone.now()).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            'account_id': loan.account_id,
            'loan_id': loan.id,
            'cdate': datetime.strftime(loan.udate, "%Y-%m-%dT%H:%M:%S.%fZ"),
        },
        event_time=timezone.localtime(timezone.now()),
    )

    return user_attributes, event_data


def construct_user_attributes_for_customer_suspended_unsuspended(
    customer, account, event_type, is_suspended, reason
):
    device_id = ''

    if account:
        application = account.get_active_application()
    else:
        application = customer.last_application

    if application and application.device:
        device_id = application.device.gcm_reg_id

    suspend_type = (
        CustomerSuspendType.SUSPENDED if is_suspended else CustomerSuspendType.UNSUSPENDED
    )
    event_time = timezone.localtime(timezone.now())
    user_attributes = construct_data_moengage_user_attributes(
        customer.id,
        is_suspended=is_suspended
    )

    attributes = {
        "customer_id": customer.id,
        "type": suspend_type,
        "reason": reason,
    }

    event_data = {
        "type": "event",
        "customer_id": customer.id,
        "device_id": device_id,
        "actions": [
            {
                "action": event_type,
                "attributes": attributes,
                "platform": "ANDROID",
                "current_time": event_time.timestamp(),
                "user_timezone_offset": event_time.utcoffset().seconds,
            }
        ],
    }

    return user_attributes, event_data


def construct_user_attributes_for_active_platforms_rule(event_type, customer_id, is_eligible):
    customer = Customer.objects.get_or_none(id=customer_id)
    if not customer:
        raise ValueError('customer_id={} is not found'.format(customer_id))

    application = customer.account.get_active_application()

    user_attributes = construct_data_moengage_user_attributes(customer_id)

    event_data = construct_data_moengage_event_data(
        customer_id=customer_id,
        device_id=application.device.gcm_reg_id if application.device else '',
        event_type=event_type,
        event_attributes={
            'is_eligible': is_eligible,
        },
        event_time=timezone.localtime(timezone.now()),
    )

    return user_attributes, event_data


def construct_data_for_emergency_consent_received(application, event_type, consent_value):
    device_id = ''
    if application and application.device:
        device_id = application.device.gcm_reg_id
    event_time = timezone.localtime(timezone.now())
    customer_id = application.customer_id
    user_attributes = construct_data_moengage_user_attributes(customer_id)
    event_attributes = {
        'consent_value': consent_value,
    }
    event_data = construct_data_moengage_event_data(
        customer_id, device_id, event_type, event_attributes, event_time
    )
    return user_attributes, event_data


def construct_customer_segment_data(segment: CustomerSegmentationComms) -> Dict[str, Any]:
    """
    Construct customer segmentation data for moengage
    """
    d = model_to_dict(segment)

    # remove non-used fields
    d.pop('id')
    d.update(**d.pop('extra_params'))

    customer_id = d.pop('customer_id')
    user_attributes = construct_data_moengage_user_attributes(
        customer_id=customer_id,
        **d,
    )
    return user_attributes


def construct_user_attributes_for_goldfish(application: Application, value: bool):
    user_attributes = construct_user_attributes_for_j1_customer(application)
    user_attributes["attributes"]["is_goldfish"] = value
    return user_attributes


def construct_event_data_for_gtl(event_type, customer_id, event_attributes):
    customer = Customer.objects.get_or_none(id=customer_id)
    if not customer:
        raise ValueError('customer_id={} is not found'.format(customer_id))

    application = customer.account.get_active_application()

    return construct_data_moengage_event_data(
        customer_id=customer_id,
        device_id=application.device.gcm_reg_id if application.device else '',
        event_type=event_type,
        event_attributes=event_attributes,
        event_time=timezone.localtime(timezone.now()),
    )


def construct_data_for_autodebet_bri_expiration_handler(account_payment_id, customer, event_type):
    autodebit_log = AutodebetBRITransaction.objects.filter(
        status='FAILED',
        description__icontains=BRIErrorCode.INVALID_PAYMENT_METHOD_ERROR,
        account_payment_id=account_payment_id,
    ).last()

    if not autodebit_log:
        return

    error_message = autodebit_log.description
    application = customer.application_set.last()
    device_id = ''
    if application:
        if application.device:
            device_id = application.device.gcm_reg_id

    event_data = {
        "type": "event",
        "customer_id": customer.id,
        "device_id": device_id,
        "actions": [
            {
                "action": event_type,
                "attributes": {
                    "cdate": datetime.strftime(
                        timezone.localtime(autodebit_log.cdate), "%Y-%m-%d %H:%M:%S"
                    ),
                    "vendor": AutodebetVendorConst.BRI,
                    "error_message": error_message,
                    "account_payment_id": account_payment_id,
                },
                "platform": "ANDROID",
                "current_time": timezone.localtime(datetime.now()).timestamp(),
                "user_timezone_offset": localtime_timezone_offset(),
            }
        ],
    }

    return event_data


def construct_event_data_loyalty_mission_to_moengage(customer, mission_progress_dict):
    mission_progress_id = mission_progress_dict['mission_progress_id']
    status = mission_progress_dict['status']
    device_id = ''

    application = customer.account.get_active_application()
    if application and application.device:
        device_id = application.device.gcm_reg_id

    event_attributes = {
        'customer_id': customer.id,
        'mission_progress_id': mission_progress_id,
        'status': status,
    }

    event_data = {
        "type": "event",
        "customer_id": customer.id,
        "device_id": device_id,
        "actions": [{
            "action": MoengageEventType.LOYALTY_MISSION,
            "attributes": event_attributes,
            "platform": "ANDROID",
            "current_time": time.time(),
            "user_timezone_offset": localtime_timezone_offset(),
        }]
    }

    return event_data


def construct_user_attributes_loyalty_total_point_to_moengage(customer_id, total_point):
    attributes = {
        "total_point": total_point,
        "platforms": [{
            "platform": "ANDROID",
            "active": "true"}]
    }
    user_attributes = {
        "type": "customer",
        "customer_id": customer_id,
        "attributes": attributes
    }

    return user_attributes


def construct_julo_financing_event_data(customer_id, event_type):

    token, token_data = get_or_create_customer_token(customer_id)

    user_attributes = construct_data_moengage_user_attributes(
        customer_id=customer_id,
        jfinancing_encrypted_key=token,
    )
    event_data = construct_moengage_event_data(
        event_type=event_type,
        customer_id=customer_id,
        event_attributes={
            "key_event_time": token_data.event_time_datetime.strftime('%Y-%m-%d, %H:%M:%S %z'),
            "key_expiry_time": token_data.expiry_time_datetime.strftime('%Y-%m-%d, %H:%M:%S %z'),
            "jfinancing_encrypted_key": token,
        },
    )

    return user_attributes, event_data


def construct_data_for_customer_agent_assisted(application, event_type):
    from juloserver.application_form.utils import get_url_form_for_tnc

    device_id = ''
    if application and application.device:
        device_id = application.device.gcm_reg_id
    event_time = timezone.localtime(timezone.now())
    customer_id = application.customer_id
    application_xid = application.application_xid
    user_attributes = construct_data_moengage_user_attributes(
        customer_id=customer_id,
        sales_ops_tnc_url=get_url_form_for_tnc(
            application_id=application.id,
            application_xid=application_xid,
        ),
        application_xid=application_xid,
    )
    event_attributes = {}
    event_data = construct_data_moengage_event_data(
        customer_id, device_id, event_type, event_attributes, event_time
    )
    return user_attributes, event_data


def construct_data_julo_financing_verification(
    application: Application, verification: JFinancingVerification, event_type: str
) -> Tuple[dict, dict]:
    device_id = ''
    if application and application.device:
        device_id = application.device.gcm_reg_id
    event_time = timezone.localtime(timezone.now())
    customer_id = application.customer_id

    user_attributes = construct_data_moengage_user_attributes(customer_id)
    if event_type in [
        MoengageEventType.JFINANCING_COMPLETED,
        MoengageEventType.JFINANCING_TRANSACTION,
    ]:
        event_attributes = {
            "j_financing_product_name": verification.j_financing_checkout.j_financing_product.name,
        }

    # JFINANCING_DELIVERY
    else:
        event_attributes = {
            "courier_name": verification.j_financing_checkout.courier_name,
            "tracking_id": verification.j_financing_checkout.courier_tracking_id,
        }

    event_data = construct_data_moengage_event_data(
        customer_id, device_id, event_type, event_attributes, event_time
    )

    return user_attributes, event_data


def construct_data_for_balcon_punishment(
        application, event_type, limit_deducted, fintech_id, fintech_name
):
    device_id = ''
    if application and application.device:
        device_id = application.device.gcm_reg_id

    event_time = timezone.localtime(timezone.now())
    customer_id = application.customer_id

    event_attributes = {
        "limit_deducted": limit_deducted,
        "fintech_id": fintech_id,
        "fintech_name": fintech_name
    }

    event_data = construct_data_moengage_event_data(
        customer_id, device_id, event_type, event_attributes, event_time
    )
    return event_data


def construct_data_for_cashback_delay_disbursement(event_type, loan, customer_id):
    application = Application.objects.filter(customer_id=customer_id).last()
    user_attributes = construct_data_moengage_user_attributes(
        customer_id, fullname_with_title=application.fullname_with_title
    )
    event_data = construct_data_moengage_event_data(
        customer_id=customer_id,
        device_id=application.device.gcm_reg_id if application.device else '',
        event_type=event_type,
        event_attributes={
            'customer_id': customer_id,
            'event_triggered_date': timezone.localtime(timezone.now()).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            'account_id': loan.account_id,
            'loan_id': loan.id,
            'cdate': datetime.strftime(loan.udate, "%Y-%m-%dT%H:%M:%S.%fZ"),
        },
        event_time=timezone.localtime(timezone.now()),
    )

    return user_attributes, event_data


def construct_data_for_activated_oneklik(customer, event_type, cdate):
    application = Application.objects.filter(customer_id=customer.id).last()
    device_id = ''
    if application:
        if application.device:
            device_id = application.device.gcm_reg_id

    event_data = {
        "type": "event",
        "customer_id": customer.id,
        "device_id": device_id,
        "attributes": {},
        "actions": [
            {
                "action": event_type,
                "attributes": {"customersID": customer.id, "cdate": cdate},
                "platform": "ANDROID",
                "current_time": time.time(),
                "user_timezone_offset": localtime_timezone_offset(),
            }
        ],
    }
    return event_data


def construct_qris_linkage_status_change_event_data(
    customer_id: int, partner_id: int, event_type: str
):
    """
    Send linkage status change event data
    Data changes based on qris partners
    Event attributes examples:
    {
        "status": "requested/failed/success"
        "linkage_partner": "amar",
        "reject_reasons: ["message A", "message B", "message C"],
    }
    """
    from juloserver.qris.services.notification_related import (
        get_partner_extra_moengage_data_to_send,
    )

    linkage = get_linkage(
        customer_id=customer_id,
        partner_id=partner_id,
    )

    partner = Partner.objects.get(pk=partner_id)

    user_attributes = construct_data_moengage_user_attributes(
        customer_id=customer_id,
    )

    # construct event attributes
    event_attributes = {
        "status": linkage.status,
        "linkage_partner": partner.name,
    }

    # update extra moengage data based on partners
    # update rejected_reasons, etc
    extra_data = get_partner_extra_moengage_data_to_send(linkage, partner)
    event_attributes.update(**extra_data)

    # constract event data
    event_data = construct_moengage_event_data(
        event_type=event_type,
        customer_id=customer_id,
        event_attributes=event_attributes,
    )

    return user_attributes, event_data
