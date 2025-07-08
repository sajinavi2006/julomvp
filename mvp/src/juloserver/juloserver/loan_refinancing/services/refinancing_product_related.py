from __future__ import absolute_import
from builtins import str
from builtins import range
from builtins import object
import math
import logging
import shortuuid
import re

from datetime import timedelta, datetime
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from django.db import DatabaseError, transaction
from django.db.models import Sum, Q

from juloserver.julo.models import (FeatureSetting,
                                    PaymentEvent,
                                    Loan,
                                    PaymentHistory)
from juloserver.julo.constants import (
    FeatureNameConst,
    PaymentEventConst
)
from juloserver.julo.services2 import encrypt
from juloserver.urlshortener.services import shorten_url

from ..models import (
    LoanRefinancingRequest,
    LoanRefinancingOffer,
    CollectionOfferExtensionConfiguration,
    WaiverRecommendation,
    LoanRefinancingRequestCampaign,
    WaiverRequest,
    AccountPayment,
)
from ..constants import LoanRefinancingConst, CovidRefinancingConst, Campaign

from .loan_related import (
    get_sum_of_principal_paid_and_late_fee_amount,
    get_unpaid_payments,
    mark_old_payments_as_restructured,
    create_loan_refinancing_payments_based_on_new_tenure,
    create_payment_event_to_waive_late_fee,
    waive_customer_wallet_for_loan_refinancing,
    send_loan_refinancing_success_email,
    construct_tenure_probabilities,
    generate_new_tenure_extension_probabilities,
    create_payment_event_for_R3_as_late_fee,
    store_payments_restructured_to_payment_pre_refinancing,
    update_payments_after_restructured,
    get_r1_loan_refinancing_offer,
    get_r4_loan_refinancing_offer,
)
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.models import Payment
from ..tasks import send_email_covid_refinancing_activated
from juloserver.julo.formulas import round_rupiah
from ..utils import get_after_refinancing_due_date
from .comms_channels import send_loan_refinancing_request_activated_notification

from ...apiv2.models import LoanRefinancingScore, LoanRefinancingScoreJ1
from ...julo.product_lines import ProductLineCodes

logger = logging.getLogger(__name__)


def get_covid_loan_refinancing_request(loan):
    return LoanRefinancingRequest.objects.filter(
        loan=loan
    ).filter(
        status__in=(CovidRefinancingConst.STATUSES.approved,
                    CovidRefinancingConst.STATUSES.offer_selected)
    ).last()


def get_activated_covid_loan_refinancing_request(loan):
    return LoanRefinancingRequest.objects.filter(
        status=CovidRefinancingConst.STATUSES.activated,
        loan=loan
    ).last()


def check_eligibility_of_covid_loan_refinancing(
        loan_refinancing_request, paid_date, paid_amount=0):

    if loan_refinancing_request.product_type in CovidRefinancingConst.reactive_products():
        first_payment_due_date = get_due_date(loan_refinancing_request)

    else:
        first_payment_due_date = get_first_payment_due_date(loan_refinancing_request)

    if loan_refinancing_request.status == CovidRefinancingConst.STATUSES.expired:
        return False

    if paid_date > first_payment_due_date:
        loan_refinancing_request.update_safely(status=CovidRefinancingConst.STATUSES.expired)
        return False

    total_paid_amount = get_prerequisite_amount_has_paid(loan_refinancing_request, first_payment_due_date)
    if not total_paid_amount:
        total_paid_amount = paid_amount
    else:
        total_paid_amount += paid_amount
    if total_paid_amount < (loan_refinancing_request.prerequisite_amount or 0):
        return False

    return True


def get_first_payment_due_date(loan_refinancing_request):
    date_ref = loan_refinancing_request.form_submitted_ts or \
        loan_refinancing_request.request_date or loan_refinancing_request.cdate
    if type(date_ref) == datetime:
        date_ref = timezone.localtime(date_ref).date()
    loan_refinancing_offer = loan_refinancing_request.loanrefinancingoffer_set.filter(
        is_accepted=True).last()
    if loan_refinancing_offer and loan_refinancing_offer.offer_accepted_ts:
        date_ref = timezone.localtime(loan_refinancing_offer.offer_accepted_ts).date()

    first_payment_due_date = date_ref + timedelta(days=loan_refinancing_request.expire_in_days)
    return first_payment_due_date


def get_prerequisite_amount_has_paid(
        loan_refinancing_request, first_payment_due_date, account=None):
    date_approved = timezone.localtime(loan_refinancing_request.cdate)
    loan_refinancing_offer = loan_refinancing_request.loanrefinancingoffer_set.filter(is_accepted=True).last()
    if loan_refinancing_offer:
        date_approved = timezone.localtime(loan_refinancing_offer.offer_accepted_ts)

    if account:
        payments = Payment.objects.values_list('id', flat=True).filter(
            account_payment_id__in=account.accountpayment_set.values_list('id', flat=True)
        )
    else:
        payments = Payment.objects.values_list('id', flat=True).filter(loan=loan_refinancing_request.loan)

    total_paid_amount = PaymentEvent.objects.filter(
        payment__in=payments, event_type__in=PaymentEventConst.PARTIAL_PAYMENT_TYPES, cdate__gte=date_approved,
        event_date__gte=date_approved.date(), event_date__lte=first_payment_due_date
    ).aggregate(total_paid_amount=Sum('event_payment')).get('total_paid_amount')

    total_paid_amount = total_paid_amount if total_paid_amount is not None else 0
    return total_paid_amount


def get_partially_paid_prerequisite_amount(loan, account=None):
    if account:
        covid_loan_refinancing_request = LoanRefinancingRequest.objects.filter(
            account=account).last()
    else:
        covid_loan_refinancing_request = LoanRefinancingRequest.objects.filter(loan=loan).last()

    total_paid_amount = 0
    if covid_loan_refinancing_request:

        if covid_loan_refinancing_request.product_type in CovidRefinancingConst.reactive_products():
            first_payment_due_date = get_due_date(covid_loan_refinancing_request)

        else:
            first_payment_due_date = get_first_payment_due_date(covid_loan_refinancing_request)

        prerequisite_amount_has_paid = get_prerequisite_amount_has_paid(
            covid_loan_refinancing_request, first_payment_due_date, account=account)
        if covid_loan_refinancing_request.product_type not in CovidRefinancingConst.waiver_products() and \
                prerequisite_amount_has_paid < covid_loan_refinancing_request.prerequisite_amount:
            total_paid_amount = prerequisite_amount_has_paid

    return total_paid_amount


def generate_new_principal_and_interest_amount_based_on_covid_month_for_r3(
    tenure_extension, index, current_month, original_monthly_dict, admin_fee=75000
):
    if index in range(tenure_extension):
        new_interest_amount = 0
        new_principal_amount = 0
        new_late_fee = admin_fee
        new_due_amount = new_late_fee
    else:
        new_principal_amount = original_monthly_dict['principal']
        new_interest_amount = original_monthly_dict['interest']
        new_late_fee = 0
        new_due_amount = original_monthly_dict['due']

    return new_due_amount, new_principal_amount, new_interest_amount, new_late_fee


def construct_new_payments_for_r2(
        loan_refinancing_request, unpaid_payments, simulate=False, proactive_loan_duration=0,
        loans=None, number_of_unpaid_payment=0
):
    # Logger variables.
    refinancing_negative_interest = False

    if not loans:
        if loan_refinancing_request.account:
            loans = loan_refinancing_request.account.get_all_active_loan()
        else:
            loans = [loan_refinancing_request.loan]

    if unpaid_payments[0].__class__ is Payment:
        account = unpaid_payments[0].loan.account
        if account:
            cycle_day = account.cycle_day
        else:
            cycle_day = unpaid_payments[0].due_date.day
    elif unpaid_payments[0].__class__ is AccountPayment:
        cycle_day = unpaid_payments[0].account.cycle_day

    refinancing_period_installment = 0
    for loan in loans:
        refinancing_period_installment += int(
            math.floor(float(loan.loan_amount * loan.interest_rate_monthly))
        )

    if not number_of_unpaid_payment:
        number_of_unpaid_payment = unpaid_payments.count()

    refinancing_period_in_months = loan_refinancing_request.loan_duration
    if proactive_loan_duration and not loan_refinancing_request.loan_duration:
        refinancing_period_in_months = proactive_loan_duration

    total_loan_duration = refinancing_period_in_months + number_of_unpaid_payment

    loan_dict = get_sum_of_principal_paid_and_late_fee_amount(
        unpaid_payments, loan_refinancing_request)
    paid_principal_amount = loan_dict['paid_principal__sum']
    paid_interest_amount = loan_dict['paid_interest__sum']

    remaining_interest_amount = loan_dict['installment_interest__sum'] - paid_interest_amount
    remaining_principal_amount = loan_dict['installment_principal__sum'] - paid_principal_amount
    remaining_installment_amount = remaining_principal_amount + remaining_interest_amount

    normal_monthly_interest = int(math.floor(
        float(remaining_interest_amount) / number_of_unpaid_payment))
    normal_monthly_principal = int(math.floor(
        float(remaining_principal_amount) / number_of_unpaid_payment))
    normal_monthly_installment = int(math.floor(normal_monthly_principal + normal_monthly_interest))

    new_payments = []
    due_date = get_due_date(loan_refinancing_request)
    for index in range(total_loan_duration):
        first_unpaid_payment_number = unpaid_payments[0].payment_number or 1
        payment_number = index + first_unpaid_payment_number
        paid_interest, paid_principal, paid_amount = 0, 0, 0
        refinancing_last_payment_number = refinancing_period_in_months + first_unpaid_payment_number

        if payment_number > first_unpaid_payment_number:
            due_date = get_after_refinancing_due_date(due_date + relativedelta(months=1), cycle_day)

        if payment_number < refinancing_last_payment_number:
            due_amount = refinancing_period_installment
            interest_amount = due_amount
            principal_amount = 0
        else:
            if index < (total_loan_duration - 1):
                due_amount = normal_monthly_installment
                principal_amount = normal_monthly_principal
                interest_amount = due_amount - principal_amount

                remaining_installment_amount -= due_amount
                remaining_principal_amount -= principal_amount
                remaining_interest_amount -= interest_amount
            else:
                due_amount = remaining_installment_amount
                principal_amount = remaining_principal_amount
                interest_amount = remaining_interest_amount

        if interest_amount < 0:
            refinancing_negative_interest = True

        new_payments.append(
            dict(
                loan=loans[0],
                payment_number=payment_number,
                due_date=due_date,
                due_amount=due_amount,
                installment_principal=principal_amount,
                installment_interest=interest_amount,
                payment_status_id=PaymentStatusCodes.PAYMENT_NOT_DUE,
                paid_interest=paid_interest,
                paid_principal=paid_principal,
                paid_amount=paid_amount,
                account_payment_id=0,
            )
        )

    if simulate:
        loan_dict = get_sum_of_principal_paid_and_late_fee_amount(
            unpaid_payments, loan_refinancing_request)
        loan_refinancing_request.update_safely(
            prerequisite_amount=refinancing_period_installment,
            status=CovidRefinancingConst.STATUSES.approved,
            total_latefee_discount=loan_dict['late_fee_amount__sum']
        )

    if refinancing_negative_interest:
        logger.info({
            "error_msg":"refinancing_negative_interest",
            "loan_refinancing_request": loan_refinancing_request,
            "unpaid_payments": unpaid_payments,
            "simulate": simulate,
            "proactive_loan_duration": proactive_loan_duration,
            "loans": loans,
            "number_of_unpaid_payment": number_of_unpaid_payment,
            "loan_dict": loan_dict,
            "new_payments": new_payments
        })

    return new_payments


def construct_new_payments_for_r3(
        loan_refinancing_request, unpaid_payments, proactive_loan_duration=0,
        number_of_unpaid_payment=0
):
    # Logger variables.
    refinancing_negative_interest = False

    new_payment_struct = {
        'payments': [],
        'total_latefee_amount': 0
    }

    tenure_extension = loan_refinancing_request.loan_duration
    if proactive_loan_duration and not loan_refinancing_request.loan_duration:
        tenure_extension = proactive_loan_duration

    loan_dict = get_sum_of_principal_paid_and_late_fee_amount(
        unpaid_payments, loan_refinancing_request
    )

    if unpaid_payments[0].__class__ is Payment:
        account = unpaid_payments[0].loan.account
        if account:
            cycle_day = account.cycle_day
        else:
            cycle_day = unpaid_payments[0].due_date.day
    elif unpaid_payments[0].__class__ is AccountPayment:
        cycle_day = unpaid_payments[0].account.cycle_day

    new_payment_struct['total_latefee_amount'] = loan_dict['late_fee_amount__sum']
    # unpaid_payments_due_date_list = list(unpaid_payments.values_list('due_date', flat=True))\
    due_date = unpaid_payments[0].due_date
    total_unpaid_payments = unpaid_payments.count()
    if number_of_unpaid_payment:
        total_unpaid_payments = number_of_unpaid_payment

    paid_principal_amount = loan_dict['paid_principal__sum']
    paid_interest_amount = loan_dict['paid_interest__sum']

    remaining_interest_amount = loan_dict['installment_interest__sum'] - paid_interest_amount
    remaining_principal_amount = loan_dict['installment_principal__sum'] - paid_principal_amount
    remaining_due_amount = remaining_interest_amount + remaining_principal_amount

    original_monthly_interest_amount = int(math.floor(float(
        remaining_interest_amount) / total_unpaid_payments))
    original_monthly_principal_amount = int(math.floor(float(
        remaining_principal_amount) / total_unpaid_payments))
    original_monthly_due_amount = int(math.floor(
        original_monthly_principal_amount + original_monthly_interest_amount))

    monthly_derived_interest_amount = original_monthly_due_amount - \
        original_monthly_principal_amount

    first_unpaid_payment_number = unpaid_payments[0].payment_number or 1
    index = 0
    max_index = total_unpaid_payments + tenure_extension
    last_payment_index = max_index - 1
    admin_fee = 75000
    if loan_refinancing_request.account and number_of_unpaid_payment:
        loans = loan_refinancing_request.account.get_all_active_loan().count()
        admin_fee = int(math.ceil(float(admin_fee / loans)))
    # Admin fee will be categorized as late_fee
    late_fee_amount = admin_fee * tenure_extension
    remaining_due_amount_after_get_admin_fee = remaining_due_amount + late_fee_amount

    for index in range(max_index):
        if index == LoanRefinancingConst.FIRST_LOAN_REFINANCING_INSTALLMENT:
            due_date = get_due_date(loan_refinancing_request)
        else:
            due_date = get_after_refinancing_due_date(due_date + relativedelta(months=1), cycle_day)

        (
            new_due_amount,
            new_principal_amount,
            new_interest_amount,
            new_late_fee,
        ) = generate_new_principal_and_interest_amount_based_on_covid_month_for_r3(
            tenure_extension,
            index,
            due_date.month,
            {
                'due': original_monthly_due_amount,
                'principal': original_monthly_principal_amount,
                'interest': monthly_derived_interest_amount,
            },
            admin_fee=admin_fee,
        )

        if index == last_payment_index:
            if new_due_amount < remaining_due_amount:
                new_principal_amount += remaining_principal_amount - new_principal_amount
                new_interest_amount += remaining_interest_amount - new_interest_amount
                new_late_fee = 0
                adjusted_due_amount = remaining_due_amount - (original_monthly_due_amount
                                                              * total_unpaid_payments)
                new_due_amount = original_monthly_due_amount + adjusted_due_amount

        if new_interest_amount < 0:
            refinancing_negative_interest = True

        new_payment_struct['payments'].append({
            'principal_amount': new_principal_amount,
            'interest_amount': new_interest_amount,
            'due_amount': new_due_amount,
            'due_date': due_date,
            'payment_number': first_unpaid_payment_number,
            'late_fee': new_late_fee,
            'account_payment_id': 0,
        })

        first_unpaid_payment_number += 1
        index += 1
        remaining_due_amount_after_get_admin_fee -= new_due_amount
        remaining_principal_amount -= new_principal_amount
        remaining_interest_amount -= new_interest_amount

    if refinancing_negative_interest:
        if not loans:
            loans = None
        logger.info({
            "error_msg":"refinancing_negative_interest",
            "loan_refinancing_request": loan_refinancing_request,
            "unpaid_payments": unpaid_payments,
            "proactive_loan_duration": proactive_loan_duration,
            "number_of_unpaid_payment": number_of_unpaid_payment,
            "loans": loans,
            "loan_dict": loan_dict,
            "new_payment_struct": new_payment_struct
        })
    return new_payment_struct


class CovidLoanRefinancing(object):
    def __init__(self, payment, loan_refinancing_request):
        self._payment = payment
        self._loan_refinancing_request = loan_refinancing_request
        self._loan_refinancing_product = loan_refinancing_request.product_type

    def activate(self):
        loan_refinancing_method = self._get_loan_refinancing_product_method()
        with transaction.atomic():
            try:
                if self._loan_refinancing_product in CovidRefinancingConst.reactive_products():
                    self._loan_refinancing_request.loan.update_safely(
                        is_restructured=True
                    )

                return loan_refinancing_method()
            except DatabaseError:
                logger.info({
                    'method': 'activate_covid_loan_refinancing',
                    'payment_id': self._payment.id,
                    'error': 'failed do adjustment and split the payments'
                })

                return False

    def _get_loan_refinancing_product_method(self):
        if self._loan_refinancing_product == CovidRefinancingConst.PRODUCTS.r1 or \
                self._loan_refinancing_product == CovidRefinancingConst.PRODUCTS.p1:
            return self._activate_loan_refinancing_r1
        if self._loan_refinancing_product == CovidRefinancingConst.PRODUCTS.r2 or \
                self._loan_refinancing_product == CovidRefinancingConst.PRODUCTS.p2:
            return self._activate_loan_refinancing_r2
        if self._loan_refinancing_product == CovidRefinancingConst.PRODUCTS.r3 or \
                self._loan_refinancing_product == CovidRefinancingConst.PRODUCTS.p3:
            return self._activate_loan_refinancing_r3
        if self._loan_refinancing_product in CovidRefinancingConst.waiver_products():
            return self._activate_loan_refinancing_waiver
        raise ValueError('product is not found')

    def _activate_loan_refinancing_r1(self):
        loan = self._loan_refinancing_request.loan

        with ActivateRefinancingRequest(self._loan_refinancing_request, self._payment) as unpaid_payments:
            chosen_loan_duration = unpaid_payments.count() + self._loan_refinancing_request.loan_duration
            new_payment_struct = construct_tenure_probabilities(
                unpaid_payments, chosen_loan_duration)[chosen_loan_duration]
            new_payment_struct[0]['due_date'] = self._loan_refinancing_request.request_date + \
                timedelta(days=self._loan_refinancing_request.expire_in_days)
            mark_old_payments_as_restructured(unpaid_payments)
            store_payments_restructured_to_payment_pre_refinancing(
                unpaid_payments, self._loan_refinancing_request)
            update_payments_after_restructured(unpaid_payments)
            create_loan_refinancing_payments_based_on_new_tenure(
                new_payment_struct, loan
            )
        return True

    def _activate_loan_refinancing_r2(self):
        with ActivateRefinancingRequest(self._loan_refinancing_request, self._payment) as unpaid_payments:
            new_payments = construct_new_payments_for_r2(
                self._loan_refinancing_request,
                unpaid_payments
            )
            mark_old_payments_as_restructured(unpaid_payments)
            store_payments_restructured_to_payment_pre_refinancing(
                unpaid_payments, self._loan_refinancing_request)
            update_payments_after_restructured(unpaid_payments)
            payment_data = []
            for payment in new_payments:
                payment.pop("account_payment_id")
                payment_data.append(Payment(**payment))
            Payment.objects.bulk_create(payment_data)
        return True

    def _activate_loan_refinancing_r3(self):
        with ActivateRefinancingRequest(self._loan_refinancing_request, self._payment) as unpaid_payments:
            new_payment_struct = construct_new_payments_for_r3(
                self._loan_refinancing_request,
                unpaid_payments
            )
            mark_old_payments_as_restructured(unpaid_payments)
            store_payments_restructured_to_payment_pre_refinancing(
                unpaid_payments, self._loan_refinancing_request)
            update_payments_after_restructured(unpaid_payments)
            create_loan_refinancing_payments_based_on_new_tenure(
                new_payment_struct['payments'],
                self._payment.loan
            )

            create_payment_event_for_R3_as_late_fee(
                self._loan_refinancing_request.loan,
                self._loan_refinancing_request.loan_duration
            )

        return True

    def _activate_loan_refinancing_waiver(self):
        self._loan_refinancing_request.change_status(CovidRefinancingConst.STATUSES.activated)
        self._loan_refinancing_request.offer_activated_ts = timezone.localtime(timezone.now())
        self._loan_refinancing_request.save()

        today_date = timezone.localtime(timezone.now()).date()
        waiver_request = WaiverRequest.objects.filter(
            loan_id=self._loan_refinancing_request.loan_id, is_approved__isnull=True,
            is_automated=False, waiver_validity_date__gte=today_date
        ).order_by('cdate').last()
        if not waiver_request:
            send_loan_refinancing_request_activated_notification(self._loan_refinancing_request)
        return True


class ActivateRefinancingRequest(object):
    def __init__(self, loan_refinancing_request, payment):
        self._loan_refinancing_request = loan_refinancing_request
        self._loan = loan_refinancing_request.loan
        self._payment = payment
        self._ordered_unpaid_payments = get_unpaid_payments(
            self._loan, order_by='payment_number'
        )

    def __enter__(self):
        return self._ordered_unpaid_payments

    def __exit__(self, exc_type, exc_value, traceback):
        from juloserver.minisquad.tasks2.intelix_task import \
            delete_paid_payment_from_intelix_if_exists_async
        from juloserver.minisquad.tasks2.dialer_system_task import delete_paid_payment_from_dialer
        if not exc_value:
            create_payment_event_to_waive_late_fee(self._payment, self._loan_refinancing_request)
            waive_customer_wallet_for_loan_refinancing(self._loan.customer, self._payment)
            send_loan_refinancing_request_activated_notification(self._loan_refinancing_request)
            self._loan_refinancing_request.change_status(CovidRefinancingConst.STATUSES.activated)
            self._loan_refinancing_request.offer_activated_ts = timezone.localtime(timezone.now())
            self._loan_refinancing_request.save()
            delete_paid_payment_from_intelix_if_exists_async.delay(self._payment.id)
            delete_paid_payment_from_dialer.delay(self._payment.id)


def generate_unique_uuid():
    uuid = shortuuid.uuid()
    is_uuid_exists = LoanRefinancingRequest.objects.filter(
        uuid=uuid
    ).exists()

    if not is_uuid_exists:
        return uuid
    else:
        return generate_unique_uuid()


def generate_timestamp(day=0):
    timestamp = timezone.localtime(timezone.now()) + relativedelta(days=day)
    return timestamp


def generate_short_url_for_proactive_webview(uuid):
    encrypttext = encrypt()
    encoded_uuid = encrypttext.encode_string(str(uuid))
    url = CovidRefinancingConst.PROACTIVE_URL + '{}/'.format(encoded_uuid)
    shortened_url = shorten_url(url)

    return shortened_url


def get_refinancing_request_feature_setting_params():
    active_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.COVID_REFINANCING,
        is_active=True).last()
    if active_feature:
        return active_feature.parameters
    return None


def get_due_date(loan_refinancing_request):
    due_date = timezone.localtime(loan_refinancing_request.cdate).date() + \
               timedelta(days=loan_refinancing_request.expire_in_days)
    if loan_refinancing_request.request_date:
        due_date = loan_refinancing_request.request_date + timedelta(days=loan_refinancing_request.expire_in_days)
    return due_date


def get_max_tenure_extension_r1(loan_refinancing_request):
    from ...account_payment.services.account_payment_related import get_unpaid_account_payment
    today = timezone.localtime(timezone.now()).date()
    if loan_refinancing_request.is_julo_one:
        payments_or_account_payments = get_unpaid_account_payment(
            loan_refinancing_request.account.id)
    else:
        payments_or_account_payments = get_unpaid_payments(
            loan_refinancing_request.loan)

    extension_config = CollectionOfferExtensionConfiguration.objects.filter(
        product_type=CovidRefinancingConst.PRODUCTS.r1,
        remaining_payment=len(payments_or_account_payments),
        date_end__gte=today,
        date_start__lte=today,
    ).last()
    if not extension_config:
        logger.info({
            'method': 'get_max_tenure_extension_r1',
            'loan_id': loan_refinancing_request.loan_id,
            'account_id': loan_refinancing_request.account_id,
            'error': 'max tenure extensions not found for remaining payment {}'.format(
                len(payments_or_account_payments))
        })
        return

    return extension_config.max_extension


def proactive_offer_generation(loan_refinancing_req):
    from ...account_payment.services.account_payment_related import get_unpaid_account_payment
    if loan_refinancing_req.account:
        account = loan_refinancing_req.account
        application = account.last_application
        loan_refinancing_score = LoanRefinancingScoreJ1.objects.filter(account=account).last()
        payments = get_unpaid_account_payment(account.id)
    else:
        loan = loan_refinancing_req.loan
        application = loan.application
        loan_refinancing_score = LoanRefinancingScore.objects.filter(loan=loan).last()
        payments = get_unpaid_payments(loan, order_by='payment_number')

    product_line_code = application.product_line_code
    allowed_product_line = ProductLineCodes.mtl() + ProductLineCodes.stl() + \
        ProductLineCodes.pede() + ProductLineCodes.laku6() + ProductLineCodes.j1() + \
        ProductLineCodes.turbo()
    is_can_calculate_r1_until_r6 = True if product_line_code in allowed_product_line \
        else False
    if not loan_refinancing_score or not is_can_calculate_r1_until_r6:
        logger.error({
            'action': 'proactive_offer_generation',
            'loan_request_id': loan_refinancing_req.id,
            'error': 'Loan ID yang anda masukan tidak terdaftar untuk COVID Refinancing, '
                     'harap melakukan pengecekan kembali'
        })
        return False

    ability_score = loan_refinancing_score.ability_score
    willingness_score = loan_refinancing_score.willingness_score
    net_due_amt = payments.aggregate(Sum('due_amount'))['due_amount__sum']
    total_not_yet_due_installment = 0
    for payment in payments:
        if payment.due_late_days < 0:
            total_not_yet_due_installment += 1

    if net_due_amt < 0:
        logger.error({
            'action': 'proactive_offer_generation',
            'loan_request_id': loan_refinancing_req.id,
            'error': 'Invalid due_amount'
        })
        return False

    v1 = ability_score * 0.6
    v2 = float(net_due_amt) / float(
        (loan_refinancing_req.new_income - loan_refinancing_req.new_expense))
    if v2 < 0.9:
        v3 = 3
    elif v2 < 1:
        v3 = 2
    else:
        v3 = 1

    v4 = v3 * 0.2
    v5 = v1 + v4
    new_ability_score = v5 + 1 * 0.2
    if new_ability_score >= 2.5:
        new_quadrant = 'H'
    else:
        new_quadrant = 'L'

    if willingness_score >= 2.5:
        new_quadrant += 'H'
    else:
        new_quadrant += 'L'

    if new_quadrant == 'HH':
        if total_not_yet_due_installment > 2:
            return 'R5,R1,R3'
        return 'R4,R1,R3'
    elif new_quadrant == 'LH':
        return 'R1,R2,R3'
    elif new_quadrant == 'LL':
        return 'R1,R2,R3'
    elif new_quadrant == 'HL':
        if total_not_yet_due_installment > 2:
            return 'R5,R6'
        return 'R4'


def get_waiver_recommendation(loan_id, program, is_covid_risky, bucket):
    loan = Loan.objects.get_or_none(pk=loan_id)
    product = re.sub(r'[0-9]+', '', loan.application.product_line.product_line_type).lower()
    product = 'normal' if product == 'mtl' else product
    waiver_recommendation = WaiverRecommendation.objects.filter(
        program_name=program,
        bucket_name=bucket,
        partner_product=product,
        is_covid_risky=is_covid_risky
    ).last()
    if not waiver_recommendation:
        logger.info({
            'method': 'get_waiver_recommendation',
            'loan_id': loan.id,
            'error': ("waiver recommendation for program {}"
                      "bucket {} product {} is_covid_risky {}").format(
                          program, bucket, product, is_covid_risky)
        })
        return
    return waiver_recommendation


def get_loan_refinancing_request_r4_spcecial_campaign(loan_ids):
    today = timezone.localtime(timezone.now()).date()
    loan_refinancing_request_campaigns = LoanRefinancingRequestCampaign.objects.filter(
        loan_id__in=loan_ids,
        campaign_name=Campaign.R4_SPECIAL_FEB_MAR_20,
        expired_at__gte=today,
        status='Success'
    )
    return list(loan_refinancing_request_campaigns)


def check_loan_refinancing_request_is_r4_spcecial_campaign_by_loan(loan_id):
    is_loan_refinancing_request_campaign = LoanRefinancingRequestCampaign.objects.filter(
        loan_id=loan_id,
        campaign_name=Campaign.R4_SPECIAL_FEB_MAR_20,
        expired_at__gte=datetime.today().date(),
        status='Success'
    ).exists()

    return is_loan_refinancing_request_campaign


def get_payment_event_for_oldest_payment(
    loan_refinancing_request,
    first_payment_due_date,
):
    if loan_refinancing_request.loan:
        payments = Payment.objects.values_list('id', flat=True).filter(
            loan=loan_refinancing_request.loan).exclude(is_restructured=False)
    else:
        loan_ids = loan_refinancing_request.account.get_all_active_loan().values_list(
            'id', flat=True)
        payments = Payment.objects.values_list('id', flat=True).filter(
            loan__in=loan_ids).exclude(is_restructured=True)

    date_approved = timezone.localtime(loan_refinancing_request.cdate)
    loan_refinancing_offer = loan_refinancing_request.loanrefinancingoffer_set.filter(is_accepted=True).last()

    if loan_refinancing_offer:
        date_approved = timezone.localtime(loan_refinancing_offer.offer_accepted_ts)

    return PaymentEvent.objects.filter(
        payment__in=payments,
        event_type__in=["payment"],
        cdate__gte=date_approved,
        event_date__gte=date_approved.date(),
        event_date__lte=first_payment_due_date
    )


def create_payment_event_for_partial_paid_prerequisite_amount(
    loan_refinancing_request,
    first_payment_due_date,
    total_prerequisite_amount,
    payment
):
    from juloserver.julo.services import process_partial_payment
    from juloserver.julo.services2.payment_event import PaymentEventServices
    from payment_status.services import create_reversal_transaction

    payment = Payment.objects.get(pk=payment.id)

    payment_events = get_payment_event_for_oldest_payment(
        loan_refinancing_request,
        first_payment_due_date
    )

    payment_event_service = PaymentEventServices()

    for payment_event in payment_events:
        # reverse payment for old payment
        result, payment_event_void = payment_event_service.process_reversal_event_type_payment(
            payment_event,
            None)

        if result:
            old_payment = payment_event.payment

            if old_payment.paid_amount != 0:
                old_payment.payment_status_id = PaymentStatusCodes.PARTIAL_RESTRUCTURED
                old_payment.save()
            else:
                old_payment.update_status_based_on_due_date()
                old_payment.save()

            create_reversal_transaction(payment_event_void, payment.id)

        note = "Move paid amount: {}, from payment_id : {} to payment_id: {}".format(
            payment_event.event_payment,
            payment_event.payment_id,
            payment.id)

        with transaction.atomic():
            process_partial_payment(
                payment,
                payment_event.event_payment,
                note,
                paid_date=payment_event.event_date,
                payment_receipt=payment_event.payment_receipt,
                payment_method=payment_event.payment_method
            )


def process_partial_paid_loan_refinancing(
    loan_refinancing_request,
    new_payment,
    paid_amount
):

    new_paid_amount = paid_amount
    if loan_refinancing_request.product_type in \
            CovidRefinancingConst.waiver_products():
        partially_paid_prerequisite_amount_for_waiver_product = \
            get_partially_paid_prerequisite_amount(loan_refinancing_request.loan)
        new_paid_amount += partially_paid_prerequisite_amount_for_waiver_product

    first_payment_due_date = get_due_date(loan_refinancing_request)
    partially_paid_prerequisite_amount = get_prerequisite_amount_has_paid(
        loan_refinancing_request,
        first_payment_due_date)

    if partially_paid_prerequisite_amount != 0 and \
        new_paid_amount != loan_refinancing_request.prerequisite_amount\
            and loan_refinancing_request.product_type \
            in CovidRefinancingConst.reactive_products():
        create_payment_event_for_partial_paid_prerequisite_amount(
            loan_refinancing_request,
            first_payment_due_date,
            partially_paid_prerequisite_amount,
            new_payment)

    return new_paid_amount


def generate_content_email_sos_refinancing(fullname_customer, loan_refinancing_req):
    from juloserver.account_payment.services.account_payment_related import \
        get_unpaid_account_payment
    from juloserver.refinancing.services import generate_new_payment_structure

    old_account_payment_list = []
    today = timezone.localtime(timezone.now()).date()
    unpaid_payments = get_unpaid_account_payment(loan_refinancing_req.account.id)
    new_loan_extension = 1 + len(unpaid_payments)
    _, new_account_payment_list = generate_new_payment_structure(
        loan_refinancing_req.account, loan_refinancing_req,
        chosen_loan_duration=new_loan_extension)

    for account_payment in unpaid_payments:
        old_account_payment_list.append({
            'due_date': account_payment.due_date,
            'due_amount': account_payment.due_amount,
        })
    # make account payment list old and new have same index
    old_account_payment_list.append({
        'due_date': '',
        'due_amount': '',
    })

    # first due date based on expiry date
    loan_refinancing_campaign = loan_refinancing_req.loanrefinancingrequestcampaign_set.last()
    new_account_payment_list[0]['due_date'] = loan_refinancing_campaign.expired_at
    context = {
        'fullname_with_title': fullname_customer,
        'old_payments': old_account_payment_list,
        'new_payments': new_account_payment_list,
    }

    return context
