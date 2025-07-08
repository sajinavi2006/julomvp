from __future__ import division
from builtins import str
from builtins import range
import math
import logging
import calendar

from datetime import datetime

from datetime import timedelta
from dateutil.relativedelta import relativedelta
from babel.dates import format_date
import shortuuid

from django.db.models import (
    Sum,
    F,
    Q
)
from django.template.loader import render_to_string
from django.db import DatabaseError, transaction
from django.utils import timezone


from juloserver.julo.models import (
    Loan,
    Payment,
    PaymentEvent,
    PaymentMethod,
)
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.portal.core.templatetags.unit import format_rupiahs
from juloserver.julo.formulas import round_rupiah
from juloserver.julo.services2 import encrypt

from ..models import (
    LoanRefinancing,
    LoanRefinancingMainReason,
    LoanRefinancingSubReason,
    LoanRefinancingRequest,
    LoanRefinancingOffer,
    WaiverRequest,
    CollectionOfferExtensionConfiguration,
    AccountPayment,
)

from ..constants import (
    LoanRefinancingConst,
    LoanRefinancingStatus
)
from ..tasks.notification_tasks import (
    send_loan_refinancing_request_email,
    send_loan_refinancing_success_email
)
from ..tasks.general_tasks import upload_addendum_pdf_to_oss
from ..constants import CovidRefinancingConst
from juloserver.julo.models import FeatureSetting, PaymentPreRefinancing
from juloserver.julo.constants import FeatureNameConst
from ..utils import get_after_refinancing_due_date, get_partner_product

from juloserver.julocore.python2.utils import py2round

from juloserver.payback.services.waiver import get_remaining_late_fee
from juloserver.payback.services.waiver import get_remaining_interest
from juloserver.payback.services.waiver import get_remaining_principal
from juloserver.payback.constants import WaiverConst
from juloserver.payback.models import WaiverTemp
from ...apiv2.models import LoanRefinancingScore, LoanRefinancingScoreJ1
from django.conf import settings
from juloserver.integapiv1.tasks import update_va_bni_transaction


logger = logging.getLogger(__name__)


def get_loan_from_application_id(application_id):
    loan = Loan.objects.get_or_none(application_id=application_id)

    if not loan:
        return False

    return loan


def get_current_payment_structures(loan):
    payments = Payment.objects.filter(
        loan=loan
    ).annotate(remaining_principal=F('installment_principal') - F('paid_principal'))\
        .values('payment_number',
                'due_date', 'paid_date',
                'late_fee_amount', 'due_amount', 'paid_amount',
                'paid_principal',
                'installment_principal', 'remaining_principal').order_by('payment_number')

    return payments


def generate_new_tenure_offers(loan):
    max_tenure_extension = generate_new_tenure_extension_probabilities(loan.loan_duration)

    if not max_tenure_extension:
        return {}

    ordered_unpaid_payments = get_unpaid_payments(loan, order_by='payment_number')
    tenure_probabilities_dict = \
        construct_tenure_probabilities(
            ordered_unpaid_payments, max_tenure_extension)

    return tenure_probabilities_dict


def get_sum_of_principal_paid_and_late_fee_amount(unpaid_payments, loan_refinancing_request=None):
    if unpaid_payments.__class__.__name__ == 'AccountPaymentQuerySet':
        total = unpaid_payments.aggregate(
            Sum('paid_principal'),
            Sum('paid_interest'),
            Sum('late_fee_amount'),
            installment_principal__sum=Sum('principal_amount'),
            installment_interest__sum=Sum('interest_amount'),
        )

    else:
        total = unpaid_payments.aggregate(
            Sum('paid_principal'),
            Sum('paid_interest'),
            Sum('late_fee_amount'),
            installment_principal__sum=Sum('installment_principal'),
            installment_interest__sum=Sum('installment_interest'),
        )
    if loan_refinancing_request and loan_refinancing_request.id:
        status_list = (
            CovidRefinancingConst.STATUSES.approved,
            CovidRefinancingConst.STATUSES.offer_selected,
        )
        if loan_refinancing_request.status in status_list and not loan_refinancing_request.account:
            total["paid_principal__sum"] = loan_refinancing_request.initial_paid_principal
            total["paid_interest__sum"] = loan_refinancing_request.initial_paid_interest
        else:
            store_sum_of_paid_principal_and_paid_interest(loan_refinancing_request, total)
    return total


def store_sum_of_paid_principal_and_paid_interest(loan_refinancing_request, total):
    loan_refinancing_request.update_safely(
        initial_paid_principal=total["paid_principal__sum"],
        initial_paid_interest=total["paid_interest__sum"]
    )


def get_unpaid_payment_due_date_probabilities(unpaid_payments, max_tenure_extension):
    due_dates = list(unpaid_payments.values_list('due_date', flat=True))

    while len(due_dates) < max_tenure_extension:
        # adding new due_date taken from oldest due_date from payment + 1 month
        due_dates.append(due_dates[-1] + relativedelta(months=1))

    return due_dates


def construct_tenure_probabilities(
        unpaid_payments, max_tenure_extension, loan_refinancing_request=None):
    # Logger variables.
    refinancing_negative_interest = False
    refinancing_negative_interest_on_adjustment = False

    tenure_dict = {}
    today = timezone.localtime(timezone.now()).date()
    loan_dict = get_sum_of_principal_paid_and_late_fee_amount(
        unpaid_payments, loan_refinancing_request)
    minimum_tenure = unpaid_payments.count()

    if unpaid_payments[0].__class__ is Payment:
        account = unpaid_payments[0].loan.account
        if account:
            cycle_day = account.cycle_day
        else:
            cycle_day = unpaid_payments[0].due_date.day
    elif unpaid_payments[0].__class__ is AccountPayment:
        cycle_day = unpaid_payments[0].account.cycle_day

    paid_principal_amount = loan_dict['paid_principal__sum']
    paid_interest_amount = loan_dict['paid_interest__sum']
    remaining_interest_amount = loan_dict['installment_interest__sum'] - paid_interest_amount
    remaining_principal_amount = loan_dict['installment_principal__sum'] - paid_principal_amount
    tenure_dict['late_fee_amount'] = loan_dict['late_fee_amount__sum']

    for tenure in range(minimum_tenure, max_tenure_extension + 1):
        first_unpaid_payment_number = unpaid_payments[0].payment_number or 1
        tenure_dict[tenure] = []
        monthly_principal_amount = \
            math.floor(float(remaining_principal_amount // tenure))

        monthly_interest_amount = \
            math.floor(float(remaining_interest_amount // tenure))

        new_due_amount = math.floor(monthly_principal_amount + monthly_interest_amount)
        derived_interest_amount = new_due_amount - monthly_principal_amount

        # To trigger logger if condition is meet.
        if derived_interest_amount < 0:
            refinancing_negative_interest = True

        for i in range(0, tenure):
            if i == LoanRefinancingConst.FIRST_LOAN_REFINANCING_INSTALLMENT:
                due_date = today + \
                    timedelta(days=LoanRefinancingConst.LOAN_REFINANCING_FIRST_DUE_DATE_ADDITION)
            else:
                due_date = get_after_refinancing_due_date(
                    today + relativedelta(months=i), cycle_day, due_date_before=due_date
                )

            tenure_dict[tenure].append({
                'principal_amount': monthly_principal_amount,
                'interest_amount': derived_interest_amount,
                'due_amount': new_due_amount,
                'due_date': due_date,
                'payment_number': first_unpaid_payment_number,
                'account_payment_id': 0,
            })

            first_unpaid_payment_number += 1

        # this part to check if new principal and interest amount is less than the original
        # principal/ interest amount because of the math floor rounding down
        adjusted_principal_amount = remaining_principal_amount - \
            (tenure * monthly_principal_amount)

        adjusted_interest_amount = remaining_interest_amount - \
            (tenure * derived_interest_amount)

        tenure_dict[tenure][-1]['principal_amount'] = monthly_principal_amount + \
            adjusted_principal_amount

        tenure_dict[tenure][-1]['interest_amount'] = derived_interest_amount + \
            adjusted_interest_amount

        tenure_dict[tenure][-1]['due_amount'] = tenure_dict[tenure][-1]['principal_amount'] + \
            tenure_dict[tenure][-1]['interest_amount']

        if tenure_dict[tenure][-1]['interest_amount'] < 0:
            refinancing_negative_interest_on_adjustment = True

    if refinancing_negative_interest or refinancing_negative_interest_on_adjustment:
        logger.info({
            "error_msg":"refinancing_negative_interest",
            "refinancing_negative_interest": refinancing_negative_interest,
            "unpaid_payments": unpaid_payments,
            "max_tenure_extension": max_tenure_extension,
            "loan_refinancing_request": loan_refinancing_request,
            "loan_dict": loan_dict,
            "tenure_dict": tenure_dict
        })

    return tenure_dict


def get_unpaid_payments(loan, order_by=None):
    qs = loan.payment_set.filter(
        payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME
    ).exclude(is_restructured=True)
    return qs.order_by(order_by) if order_by else qs


def generate_new_tenure_extension_probabilities(loan_duration):
    active_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.COVID_REFINANCING,
        is_active=True
    ).last()
    tenure_extension_rule = active_feature.parameters['tenure_extension_rule']

    if loan_duration not in [int(key_.split('_')[-1]) for key_ in list(tenure_extension_rule.keys())]:
        return loan_duration + 3

    return loan_duration + tenure_extension_rule['MTL_%s' % loan_duration]


def generate_recommended_tenure_extension_r1(loan_refinancing_request):
    from juloserver.account_payment.services.account_payment_related import (
        get_unpaid_account_payment
    )
    today = timezone.localtime(timezone.now()).date()
    loan = None
    account = None
    if loan_refinancing_request.account:
        payments = get_unpaid_account_payment(loan_refinancing_request.account_id)
        account = loan_refinancing_request.account
    else:
        loan = loan_refinancing_request.loan
        payments = get_unpaid_payments(loan, order_by='payment_number')
    if not payments:
        return
    total_ = payments.aggregate(
        due_amount=Sum('due_amount'),
        late_fee_amount=Sum('late_fee_amount')
    )
    new_affordability = loan_refinancing_request.new_income - loan_refinancing_request.new_expense
    remaining_payment_amount = total_['due_amount'] - total_['late_fee_amount']
    remaining_duration = len(payments)
    recommended_extensions = 0
    tenure_extension_config = CollectionOfferExtensionConfiguration.objects.filter(
        date_end__gte=today,
        date_start__lte=today,
        remaining_payment=remaining_duration,
        product_type=CovidRefinancingConst.PRODUCTS.r1,
    ).last()
    if not tenure_extension_config:
        logger.info({
            'method': 'generate_recommended_tenure_extension_r1',
            'loan_id': loan.id if loan else None,
            'account_id': account.id if account else None,
            'error': 'tenure extensions not found'
        })
        return
    failed_get_recommended_extensions = True
    while recommended_extensions <= tenure_extension_config.max_extension:
        new_installment = remaining_payment_amount // (remaining_duration + recommended_extensions)
        if new_installment <= new_affordability:
            failed_get_recommended_extensions = False
            recommended_extensions = 1 if recommended_extensions == 0 else recommended_extensions
            break
        recommended_extensions += 1

    if failed_get_recommended_extensions:
        logger.info({
            'method': 'generate_recommended_tenure_extension_r1',
            'loan_id': loan.id if loan else None,
            'account_id': account.id if account else None,
            'error': 'recommended tenure extensions not found'
        })
        return

    return recommended_extensions


def insert_refinancing_request_to_db(refinancing_request_dict):
    LoanRefinancing.objects.create(**refinancing_request_dict)

    return True, None


def get_main_reason_obj(reason):
    return LoanRefinancingMainReason.objects.filter(reason=reason).last()


def get_sub_reason_obj(reason):
    return LoanRefinancingSubReason.objects.filter(reason=reason).last()


def construct_refinancing_request_dict(data):
    today = timezone.localtime(timezone.now()).date()
    main_reason = get_main_reason_obj(data['main_reason'])
    sub_reason = get_sub_reason_obj(data['sub_reason'])
    try:
        refinancing_request_dict = {
            'loan': data['loan'],
            'original_tenure': data['loan_duration'],
            'tenure_extension': data['tenure_extension'],
            'new_installment': data['due_amount'],
            'refinancing_request_date': today,
            'status': LoanRefinancingStatus.REQUEST,
            'total_latefee_discount': data['late_fee_amount'],
            'loan_level_dpd': data['dpd'],
            'loan_refinancing_main_reason': main_reason,
            'loan_refinancing_sub_reason': sub_reason,
            'additional_reason': data['additional_reason']
        }
    except KeyError:
        return False

    return refinancing_request_dict


def create_refinancing_request(loan, chosen_refinancing_options):
    loan_refinancing_request = get_loan_refinancing_request_info(loan)

    if loan_refinancing_request:
        return False, 'already request for loan refinancing'

    today = timezone.localtime(timezone.now()).date()
    oldest_payment_due_date = get_unpaid_payments(loan, order_by='payment_number')[0].due_date
    dpd = (today - oldest_payment_due_date).days
    chosen_refinancing_options.update(
        {
            'loan': loan,
            'loan_duration': loan.loan_duration,
            'dpd': dpd
        }
    )

    refinancing_request_dict = \
        construct_refinancing_request_dict(chosen_refinancing_options)

    if not refinancing_request_dict:
        return False, 'missing some data to create loan refinancing request'

    try:
        insert_refinancing_request_to_db(refinancing_request_dict)
        send_loan_refinancing_request_email.delay(loan.id)

        return True, ''
    except DatabaseError:
        return False, 'please try again, if error still persist, contact our customer support'


def get_loan_refinancing_request_info(loan):
    loan_refinancing_request = LoanRefinancing.objects.filter(
        status=LoanRefinancingStatus.REQUEST,
        loan=loan
    ).last()

    if loan_refinancing_request:
        return loan_refinancing_request
    else:
        return False


def get_loan_refinancing_obj(loan):
        return LoanRefinancing.objects.filter(
            loan=loan
        ).last()


def get_loan_refinancing_active_obj(loan):
    loan_refinancing_obj = LoanRefinancing.objects.filter(
        status=LoanRefinancingStatus.ACTIVE,
        loan=loan
    ).last()

    return loan_refinancing_obj


def create_loan_refinancing_payments_based_on_new_tenure(
        new_installments, loan, account_payment=None):
    for new_installment in new_installments:
        account_payment_id = None
        if account_payment:
            account_payment_id = account_payment.id
        if 'account_payment_id' in new_installment:
            account_payment_id = new_installment['account_payment_id']
        if account_payment_id == 0:
            account_payment_id = None
        if new_installment['interest_amount'] < 0:
            logger.info("installment_interest have negative value", {
                "new_installments": new_installments,
                "loan": loan,
                "account_payment": account_payment
            })
        Payment.objects.create(
            loan=loan,
            payment_number=new_installment['payment_number'],
            due_date=new_installment['due_date'],
            due_amount=new_installment['due_amount'],
            late_fee_amount=new_installment['late_fee'] if 'late_fee' in new_installment else 0,
            installment_principal=new_installment['principal_amount'],
            installment_interest=new_installment['interest_amount'],
            payment_status_id=PaymentStatusCodes.PAYMENT_NOT_DUE,
            account_payment_id=account_payment_id,
        )


def create_payment_event_to_waive_late_fee(
        payment, loan_refinancing_request):
    today = timezone.localtime(timezone.now()).date()

    waive_late_fee_payment_event = PaymentEvent(
        payment=payment,
        event_due_amount=payment.due_amount,
        event_payment=loan_refinancing_request.total_latefee_discount,
        event_date=today,
        event_type=LoanRefinancingConst.LOAN_REFINANCING_WAIVE_LATE_FEE_TYPE
    )
    waive_late_fee_payment_event.save()


def mark_old_payments_as_restructured(unpaid_payments):
    for unpaid_payment in unpaid_payments:
        updated_data = {
            'is_restructured': True
        }

        if unpaid_payment.paid_amount > 0:
            updated_data['payment_status_id'] = \
                PaymentStatusCodes.PARTIAL_RESTRUCTURED

        unpaid_payment.update_safely(**updated_data)


def check_eligibility_of_loan_refinancing(loan_refinancing_request, paid_date):

    first_payment_due_date = loan_refinancing_request.refinancing_request_date + \
        timedelta(days=LoanRefinancingConst.LOAN_REFINANCING_FIRST_PAYMENT_DPD)

    if loan_refinancing_request.status == CovidRefinancingConst.STATUSES.expired:
        return False

    if paid_date > first_payment_due_date:
        return False

    return True


def waive_customer_wallet_for_loan_refinancing(customer, payment):
    wallet_balance = customer.wallet_balance_available
    today = timezone.localtime(timezone.now()).date()

    if wallet_balance > 0:
        customer.change_wallet_balance(
            change_accruing=-wallet_balance,
            change_available=-wallet_balance,
            reason=LoanRefinancingConst.REFINANCING_CUSTOMER_WALLET_DEDUCTION,
            payment=payment)

        PaymentEvent.objects.create(
            payment=payment,
            event_payment=wallet_balance,
            event_due_amount=payment.due_amount,
            event_date=today,
            event_type='customer_wallet')


def activate_loan_refinancing(payment, loan_refinancing_request):
    loan = payment.loan
    customer = loan.customer
    ordered_unpaid_payments = get_unpaid_payments(
        loan, order_by='payment_number')
    tenure_extension = loan_refinancing_request.tenure_extension
    tenure_dict = construct_tenure_probabilities(
        ordered_unpaid_payments, tenure_extension)
    chosen_tenure = tenure_dict[tenure_extension]
    agreed_first_payment_date = loan_refinancing_request.refinancing_request_date + \
        timedelta(days=5)
    # need to replace the first payment due date because the due_date should be + 5 from refinancing
    # request date
    chosen_tenure[LoanRefinancingConst.FIRST_LOAN_REFINANCING_INSTALLMENT]['due_date'] = \
        agreed_first_payment_date

    try:
        with transaction.atomic():
            mark_old_payments_as_restructured(ordered_unpaid_payments)
            create_loan_refinancing_payments_based_on_new_tenure(chosen_tenure, loan)
            create_payment_event_to_waive_late_fee(
                payment, loan_refinancing_request
            )

            waive_customer_wallet_for_loan_refinancing(customer, payment)
            send_loan_refinancing_success_email.delay(loan.id)
            upload_addendum_pdf_to_oss.delay(loan.id)
    except DatabaseError as e:
        logger.info({
            'method': 'activate_loan_refinancing',
            'payment_id': payment.id,
            'error': 'failed do adjustment and split the payments'
        })

        raise e

        return False

    return True


def get_all_loan_refinanced_loans():
    return LoanRefinancing.objects.all().values_list('loan', flat=True)


def get_all_restructured_payments(loan):
    return Payment.objects.filter(
        loan=loan,
        is_restructured=False
    ).order_by('payment_number')


def get_addendum_template(application):
    customer = application.customer
    loan = application.loan
    payment_method = PaymentMethod.objects.filter(loan=loan, is_primary=True).last()
    loan_refinancing_request = get_loan_refinancing_obj(loan)
    today = timezone.localtime(timezone.now()).date()
    template = 'loan_refinancing_addendum.html'
    payments = get_all_restructured_payments(loan)[1:]
    old_payments_dict = loan.payment_set.filter(
        payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
        is_restructured=True)\
        .aggregate(Sum('due_amount'))
    payments = payments.annotate(
        real_due_amount=F('installment_principal') + F('installment_interest'))
    payments_dict = payments.aggregate(Sum('real_due_amount'))
    total_old_due_amount = old_payments_dict['due_amount__sum']
    total_new_due_amount = payments_dict['real_due_amount__sum']
    context = {
        'today_date': format_date(
            today, format='long', locale='id_ID'),
        'day_of_week': today.day,
        'month': today.month,
        'year': today.year,
        'formatted_date': '{}-{}-{}'.format(today.day, today.month, today.year),
        'address': "{} {} {} {} {} {}".format(
            application.address_street_num,
            application.address_kelurahan,
            application.address_kecamatan,
            application.address_kabupaten,
            application.address_provinsi,
            application.address_kodepos),
        'fullname': customer.fullname,
        'dob': customer.dob,
        'application_id': application.id,
        'disbursement_date': format_date(
            loan.fund_transfer_ts, format='long', locale='id_ID'),
        'bank_name': payment_method.payment_method_name,
        'bank_code': payment_method.bank_code,
        'virtual_account': payment_method.virtual_account,
        'sphp_number': application.application_xid,
        'total_old_due_amount': format_rupiahs(total_old_due_amount, 'no'),
        'new_total_due_amount': format_rupiahs(total_new_due_amount, 'no'),
        'new_tenure': loan_refinancing_request.tenure_extension,
        'due_date': (payments[1].due_date).day,
        'payments': payments
    }

    body = render_to_string(template, context)

    return body


def validate_covid_refinancing_data(data_reader):
    valid_data = []
    invalid_loans = []
    invalid_products = []
    data_incomplete = []
    loan_refinancing_request_exist = []
    for data in data_reader:
        if proactive_validation(data):
            if not Loan.objects.filter(pk=data['loan_id'],
                                       application__customer__email=data['email_address'])\
                    .exists():
                invalid_loans.append(data)
            elif LoanRefinancingRequest.objects.filter(loan_id=data['loan_id'])\
                    .exclude(product_type__in=CovidRefinancingConst.proactive_products())\
                    .exclude(
                status__in=list(CovidRefinancingConst.NEW_PROACTIVE_STATUSES.__dict__.values()) +
                        [CovidRefinancingConst.STATUSES.expired]).exists():
                loan_refinancing_request_exist.append(data)
            else:
                valid_data.append(data)
        elif data['covid_product'] \
                and data['covid_product'] not in\
                        list(CovidRefinancingConst.PRODUCTS.__dict__.values()):
            invalid_products.append(data)
        elif not data['new_affordability'] and (not data['new_income'] or not data['new_expense']):
            data_incomplete.append(data)
        elif not Loan.objects.filter(
                pk=data['loan_id'], application__customer__email=data['email_address']).exists():
            invalid_loans.append(data)
        elif LoanRefinancingRequest.objects.filter(loan_id=data['loan_id'])\
                .exclude(product_type__in=CovidRefinancingConst.proactive_products())\
                .exclude(
            status__in=list(CovidRefinancingConst.NEW_PROACTIVE_STATUSES.__dict__.values()))\
                .exists():
            loan_refinancing_request_exist.append(data)
        else:
            valid_data.append(data)
    is_valid_ = not any((invalid_loans, invalid_products, data_incomplete, loan_refinancing_request_exist))
    return is_valid_, {'invalid_loans': invalid_loans,
                    'invalid_products': invalid_products,
                    'data_incomplete': data_incomplete,
                    'loan_refinancing_request_exist': loan_refinancing_request_exist,
                    'valid_data': valid_data}


def proactive_validation(data):
    email_address = data['email_address']
    loan_id = data['loan_id']
    covid_product = data['covid_product']
    tenure_extension = data['tenure_extension']
    new_income = data['new_income']
    new_expense = data['new_expense']
    new_employment_status = data['new_employment_status']
    new_affordability = data['new_affordability']

    if (email_address and loan_id) and not covid_product and not tenure_extension \
        and not new_income and not new_expense and not new_employment_status and not new_affordability:
        return True

    return False


def store_covid_refinancing_data(valid_data, feature_params):
    from ..tasks import send_email_covid_refinancing_approved, send_email_covid_refinancing_opt
    from juloserver.moengage.tasks import \
        async_update_moengage_for_refinancing_request_status_change
    from ..services.refinancing_product_related import (
        generate_unique_uuid,
        generate_short_url_for_proactive_webview,
        generate_timestamp
    )

    row_count = 0
    for data in valid_data:
        loan = Loan.objects.select_related(
            'application', 'application__customer').get(pk=data['loan_id'])
        if not data['new_affordability']:
            app = loan.application
            new_net_income = app.monthly_income - app.monthly_expenses
            if data['new_income'] and data['new_expense']:
                new_net_income = int(data['new_income']) - int(data['new_expense'])
            previous_net_income = app.monthly_income - app.monthly_expenses
            new_affordability = float(new_net_income) / float(previous_net_income)
        else:
            new_affordability = float(data['new_affordability']) / float(100)

        extension = 0

        if 'MTL_%s' % loan.loan_duration not in feature_params['tenure_extension_rule']:
            extension = 3
        else:
            max_extension = feature_params['tenure_extension_rule']['MTL_%s' % loan.loan_duration]
            tenure_extension = int(data['tenure_extension']) if data['tenure_extension'] else 0
            extension = tenure_extension if tenure_extension < max_extension else max_extension
        loan_refinancing_req = LoanRefinancingRequest.objects.filter(loan=loan)\
            .exclude(status=CovidRefinancingConst.STATUSES.expired).last()
        loan_refinancing_main_reason = data['new_employment_status'] if \
            data['new_employment_status'].lower() not in LoanRefinancingConst.MAPPING_LOAN_REFINANCING_MAIN_REASON \
            else LoanRefinancingConst.MAPPING_LOAN_REFINANCING_MAIN_REASON[data['new_employment_status'].lower()]
        data_loan_refinancing_req = dict(
            loan_id=data['loan_id'],
            # store percentage as decimal
            affordability_value=new_affordability,
            product_type=data['covid_product'],
            expire_in_days=feature_params['email_expire_in_days'],
            loan_duration=extension,
            new_income=int(data['new_income'] or 0),
            new_expense=int(data['new_expense'] or 0),
            request_date=generate_timestamp().date(),
            form_submitted_ts=None,
            loan_refinancing_main_reason=LoanRefinancingMainReason.objects.filter(
                reason__icontains=loan_refinancing_main_reason, is_active=True).last(),
        )
        row_count += 1
        if not data['covid_product']:
            data_loan_refinancing_req['status'] = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email
            data_loan_refinancing_req['uuid'] = generate_unique_uuid()
            data_loan_refinancing_req['url'] = generate_short_url_for_proactive_webview(
                data_loan_refinancing_req['uuid']
            )

        if loan_refinancing_req:
            loan_refinancing_req.update_safely(**data_loan_refinancing_req)
        else:
            loan_refinancing_req = LoanRefinancingRequest.objects.create(
                **data_loan_refinancing_req)
            async_update_moengage_for_refinancing_request_status_change.apply_async(
                (loan_refinancing_req.id,),
                countdown=settings.DELAY_FOR_MOENGAGE_API_CALL)

        if loan_refinancing_req.product_type:
            send_email_covid_refinancing_approved.delay(loan_refinancing_req.id)
        elif loan_refinancing_req.status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES\
                                                                 .proposed_email:
            loan_refinancing_req.update_safely(channel=CovidRefinancingConst.CHANNELS.proactive)
            send_email_covid_refinancing_opt.delay(loan_refinancing_req.id)

    return row_count


def get_paid_payments(loan, order_by=None):
    qs = loan.payment_set.filter(
        payment_status_id__in=[PaymentStatusCodes.PAID_ON_TIME, PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
                               PaymentStatusCodes.PAID_LATE],
    ).exclude(is_restructured=True)
    return qs.order_by(order_by) if order_by else qs


def create_payment_event_for_R3_as_late_fee(loan_id, tenure_extension):
    today = timezone.localtime(timezone.now()).date()
    payments = Payment.objects.filter(
        loan_id=loan_id,
        payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME
    ).exclude(is_restructured=True).order_by('payment_number')[:tenure_extension]

    for payment in payments:
        late_fee = payment.late_fee_amount
        PaymentEvent.objects.create(
            payment=payment,
            event_payment=-late_fee,
            event_due_amount=payment.due_amount,
            event_date=today,
            event_type=LoanRefinancingConst.LOAN_REFINANCING_ADMIN_FEE_TYPE,
            payment_receipt=None,
            payment_method=None
        )


def get_unpaid_payments_after_restructure(loan, order_by=None):
    qs = loan.payment_set.filter(
        Q(payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME) |
        Q(payment_status_id=PaymentStatusCodes.PARTIAL_RESTRUCTURED)
    ).exclude(is_restructured=True)
    return qs.order_by(order_by) if order_by else qs


def get_unpaid_account_payments_after_restructure(account, order_by=None):
    qs = account.accountpayment_set.filter(
        Q(status_id__lt=PaymentStatusCodes.PAID_ON_TIME) |
        Q(status_id=PaymentStatusCodes.PARTIAL_RESTRUCTURED)
    ).exclude(is_restructured=True)
    return qs.order_by(order_by) if order_by else qs


def get_loan_refinancing_request_by_uuid(encrypted_uuid):
    encrypter = encrypt()
    uuid = encrypter.decode_string(encrypted_uuid)

    return LoanRefinancingRequest.objects.filter(
        uuid=uuid,
        status__in=CovidRefinancingConst.web_view_statuses()
    ).last()


def get_r4_loan_refinancing_offer(loan_refinancing_request, payment, bucket):
    last_payment = Payment.objects.filter(
        loan=payment.loan).not_paid_active().order_by('payment_number').last()
    r4_bucket_data = CovidRefinancingConst.BUCKET_BASED_R4_PARAMS[bucket]
    remaining_late_fee = get_remaining_late_fee(last_payment, True, max_payment_number=last_payment.payment_number)
    remaining_interest = get_remaining_interest(last_payment, True, max_payment_number=last_payment.payment_number)
    remaining_principal = get_remaining_principal(last_payment, True, max_payment_number=last_payment.payment_number)
    total_unpaid = remaining_late_fee + remaining_interest + remaining_principal

    total_latefee_discount = py2round(float(r4_bucket_data['late_fee_waiver']) * remaining_late_fee)
    total_interest_discount = py2round(float(r4_bucket_data['interest_waiver']) * remaining_interest)
    total_principal_discount = py2round(float(r4_bucket_data['principal_waiver']) * remaining_principal)
    total_discount = total_latefee_discount + total_interest_discount + total_principal_discount

    return dict(
        loan_refinancing_request=loan_refinancing_request,
        recommendation_order=1,
        product_type="R4",
        prerequisite_amount=total_unpaid - total_discount,
        total_latefee_discount=total_latefee_discount,
        total_interest_discount=total_interest_discount,
        total_principal_discount=total_principal_discount,
        validity_in_days=r4_bucket_data['validity_in_days'],
        interest_discount_percentage=str(r4_bucket_data['interest_waiver']*100)+'%',
        principal_discount_percentage=str(r4_bucket_data['principal_waiver']*100)+'%',
        latefee_discount_percentage=str(r4_bucket_data['late_fee_waiver']* 100) + '%',
        is_latest=True,
        is_proactive_offer=True
    )


def get_r1_loan_refinancing_offer(
        loan_refinancing_request, bucket, default_extension=True, is_proactive_offer=False):
    from ..services.refinancing_product_related import get_max_tenure_extension_r1
    extention_loan_duration = loan_refinancing_request.loan_duration
    max_extension = None
    if not extention_loan_duration:
        max_extension = generate_recommended_tenure_extension_r1(loan_refinancing_request)
    extention_loan_duration = max_extension if max_extension else extention_loan_duration
    total_latefee_discount, prerequisite_amount, _ = get_r1_payment_structure(
        loan_refinancing_request, extention_loan_duration,
        is_for_loan_refinancing_offer=True
    )

    return dict(
        loan_refinancing_request=loan_refinancing_request,
        recommendation_order=2,
        product_type="R1",
        prerequisite_amount=prerequisite_amount,
        total_latefee_discount=total_latefee_discount,
        loan_duration=extention_loan_duration,
        validity_in_days=loan_refinancing_request.expire_in_days,
        is_latest=True,
        is_proactive_offer=is_proactive_offer
    )


def get_r1_payment_structure(
        loan_refinancing_request, tenure_extension,
        is_for_loan_refinancing_offer=False
):
    from ..services.refinancing_product_related import get_max_tenure_extension_r1
    from juloserver.account_payment.services.account_payment_related import (
        get_unpaid_account_payment
    )
    from juloserver.refinancing.services import generate_new_payment_structure

    is_julo_one = True if loan_refinancing_request.account else False
    max_tenure_extension = get_max_tenure_extension_r1(loan_refinancing_request)
    if is_julo_one:
        ordered_unpaid_payments = get_unpaid_account_payment(loan_refinancing_request.account_id)
        max_tenure_extension = max_tenure_extension + len(ordered_unpaid_payments)
    else:
        loan = loan_refinancing_request.loan
        ordered_unpaid_payments = get_unpaid_payments(loan, order_by='payment_number')
        max_tenure_extension = max_tenure_extension + loan.loan_duration
    loan_duration = ordered_unpaid_payments.count() + tenure_extension

    if loan_duration > max_tenure_extension:
        real_loan_duration = max_tenure_extension
    else:
        real_loan_duration = loan_duration

    first_installment = LoanRefinancingConst.FIRST_LOAN_REFINANCING_INSTALLMENT
    if is_julo_one and loan_refinancing_request.product_type:
        _, new_payment_structures, late_fee_discount = generate_new_payment_structure(
            loan_refinancing_request.account,
            loan_refinancing_request,
            chosen_loan_duration=real_loan_duration,
            is_with_latefee_discount=True
        )
        prerequisite_amount = new_payment_structures[first_installment]['due_amount']
    else:
        new_payment_structures = construct_tenure_probabilities(
            ordered_unpaid_payments, max_tenure_extension, loan_refinancing_request)
        late_fee_discount = new_payment_structures['late_fee_amount']
        prerequisite_amount = new_payment_structures[
            real_loan_duration][first_installment]['due_amount']

    if is_for_loan_refinancing_offer:
        return late_fee_discount, prerequisite_amount, real_loan_duration

    return (new_payment_structures,
            new_payment_structures[real_loan_duration][first_installment]['due_amount'],
            real_loan_duration)


def is_proactive_link_expired(loan_refinancing_req):
    date_reference = None
    proactive_initial_status = [CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email,
                                CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit]

    almost_done_status = [CovidRefinancingConst.STATUSES.approved,
                          CovidRefinancingConst.STATUSES.offer_selected]

    if loan_refinancing_req.status in proactive_initial_status:
        date_reference = loan_refinancing_req.request_date
    elif loan_refinancing_req.status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer:
        if loan_refinancing_req.form_submitted_ts:
            date_reference = loan_refinancing_req.form_submitted_ts.date()
    elif loan_refinancing_req.status in almost_done_status:
        loan_refinancing_offer = LoanRefinancingOffer.objects.filter(
            loan_refinancing_request=loan_refinancing_req,
            is_accepted=True
        ).last()
        if loan_refinancing_offer:
            date_reference = loan_refinancing_offer.offer_accepted_ts.date()

    if date_reference:
        if loan_refinancing_req.status in almost_done_status:
            expire_in_days = loan_refinancing_req.expire_in_days
        else:
            expire_in_days = CovidRefinancingConst.PROACTIVE_STATUS_EXPIRATION_IN_DAYS.get(
                loan_refinancing_req.status)
        if expire_in_days is not None:
            expiration_date = date_reference + timedelta(days=expire_in_days)
            return (timezone.localtime(timezone.now())).date() > expiration_date
    return False


def store_payments_restructured_to_payment_pre_refinancing(unpaid_payments,
                                                           loan_refinancing_request):
    payments_restructured = []

    for payment in unpaid_payments:

        payment_data = dict(
            payment_id=payment.id,
            loan_id=payment.loan.id,
            payment_status_id=payment.payment_status_id,
            due_date=payment.due_date,
            ptp_date=payment.ptp_date,
            payment_number=payment.payment_number,
            ptp_robocall_template_id=payment.ptp_robocall_template_id,
            is_ptp_robocall_active=payment.is_ptp_robocall_active,
            due_amount=payment.due_amount,
            installment_principal=payment.installment_principal,
            installment_interest=payment.installment_interest,
            paid_amount=payment.paid_amount,
            redeemed_cashback=payment.redeemed_cashback,
            cashback_earned=payment.cashback_earned,
            late_fee_amount=payment.late_fee_amount,
            late_fee_applied=payment.late_fee_applied,
            discretionary_adjustment=payment.discretionary_adjustment,
            is_robocall_active=payment.is_robocall_active,
            is_success_robocall=payment.is_success_robocall,
            is_collection_called=payment.is_collection_called,
            uncalled_date=payment.uncalled_date,
            reminder_call_date=payment.reminder_call_date,
            is_reminder_called=payment.is_reminder_called,
            is_whatsapp=payment.is_whatsapp,
            is_whatsapp_blasted=payment.is_whatsapp_blasted,
            paid_interest=payment.paid_interest,
            paid_principal=payment.paid_principal,
            paid_late_fee=payment.paid_late_fee,
            ptp_amount=payment.ptp_amount,
            change_due_date_interest=payment.change_due_date_interest,
            is_restructured=payment.is_restructured,
            loan_refinancing_request=loan_refinancing_request
        )

        payments_restructured.append(PaymentPreRefinancing(**payment_data))

    PaymentPreRefinancing.objects.bulk_create(payments_restructured)


def update_payments_after_restructured(payments_restructured):

    for payment in payments_restructured:

        if payment.paid_amount > 0:
            new_calculation = update_calculation_for_payment_partial_restructured(payment)
            new_installment_principal = new_calculation['principal']
            new_installment_interest = new_calculation['interest']
            new_late_fee_amount = new_calculation['late_fee']

        else:
            new_installment_principal = 0
            new_installment_interest = 0
            new_late_fee_amount = 0

        payment.update_safely(
            late_fee_applied=0,
            due_amount=0,
            installment_principal=new_installment_principal,
            paid_principal=new_installment_principal,
            installment_interest=new_installment_interest,
            paid_interest=new_installment_interest,
            late_fee_amount=new_late_fee_amount,
            paid_late_fee=new_late_fee_amount
        )


def update_calculation_for_payment_partial_restructured(payment):
    payment_dict = {}
    # rule base on this card : https://juloprojects.atlassian.net/browse/ENH-286

    payment_dict['principal'] = payment.paid_principal
    payment_dict['interest'] = payment.paid_interest
    payment_dict['late_fee'] = payment.paid_late_fee

    return payment_dict


def regenerate_loan_refinancing_offer(loan):
    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        loan=loan,
        status=CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer
    ).last()
    if not loan_refinancing_request:
        return

    offers_r1 = loan_refinancing_request.loanrefinancingoffer_set.filter(
        product_type=CovidRefinancingConst.PRODUCTS.r1).last()
    offers_r4 = loan_refinancing_request.loanrefinancingoffer_set.filter(
        product_type=CovidRefinancingConst.PRODUCTS.r4).last()

    if offers_r1 or offers_r4:
        unpaid_payments = Payment.objects.filter(
            loan=loan_refinancing_request.loan).not_paid_active().order_by('payment_number')

        if not unpaid_payments:
            return

        for payment in unpaid_payments:
            if payment.status not in PaymentStatusCodes.paid_status_codes():
                if offers_r1:
                    offers_r1.update_safely(**(get_r1_loan_refinancing_offer(
                        loan_refinancing_request, payment.bucket_number, is_proactive_offer=True)))
                if offers_r4:
                    offers_r4.update_safely(**(get_r4_loan_refinancing_offer(
                        loan_refinancing_request, payment, payment.bucket_number)))

                return


def get_payments_refinancing_pending_by_date_approved(date_approved, return_only_payment_id=False):
    payments_refinancing_pending = []

    loan_ids = LoanRefinancingRequest.objects.values_list('loan', flat=True).filter(
        status=CovidRefinancingConst.STATUSES.approved,
        udate__date=date_approved
    )
    for loan_id in loan_ids:
        first_payment_refinancing = Payment.objects.not_paid_active().filter(
            loan_id=loan_id
        ).order_by('payment_number').first()
        if first_payment_refinancing:
            if return_only_payment_id:
                first_payment_refinancing = first_payment_refinancing.id
            payments_refinancing_pending.append(first_payment_refinancing)

    return payments_refinancing_pending


def get_payments_refinancing_pending_by_dpd(dpd_exclude):
    loans_pending_refinancing = LoanRefinancingRequest.objects.values_list('loan', flat=True).filter(
        status=CovidRefinancingConst.STATUSES.approved,
    )
    payments_exclude = Payment.objects.values_list('id', flat=True).filter(
        loan_id__in=loans_pending_refinancing,
        due_date__in=dpd_exclude
    )
    return payments_exclude


def get_refinancing_request_expired_possibility():
    """get refinancing request in some status"""
    expired_possibility_status = [
        CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email,
        CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit,
        CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer,
        CovidRefinancingConst.STATUSES.approved,
        CovidRefinancingConst.STATUSES.offer_selected
    ]

    refinancing_data = LoanRefinancingRequest.objects.filter(status__in=expired_possibility_status)
    refinancing_data = refinancing_data.values_list('pk', flat=True)
    return refinancing_data


def expire_loan_refinancing_request(loan_refinancing_request):
    """update loan refinancing request status"""
    expired_status = CovidRefinancingConst.STATUSES.expired
    LoanRefinancingRequest.objects.filter(pk=loan_refinancing_request.id,
                                          status=loan_refinancing_request.status)\
        .update(status=expired_status)
    if loan_refinancing_request.account:
        update_va_bni_transaction.delay(
            loan_refinancing_request.account.id,
            'loan_refinancing.loan_related.expire_loan_refinancing_request',
        )
    return True


def get_loan_refinancing_request_by_id(refinancing_request_id):
    """get loan refinancing by id"""
    return LoanRefinancingRequest.objects.filter(pk=refinancing_request_id).last()


def recalculate_affordability(loan, data, account=None):
    from juloserver.refinancing.services import get_monthly_expenses
    if account:
        application = account.last_application
    else:
        application = loan.application
    monthly_expenses = get_monthly_expenses(account, application)
    new_income = int(data["new_income"].replace(',', ''))
    new_expense = int(data["new_expense"].replace(',', ''))
    previous_net_income = application.monthly_income - monthly_expenses
    new_net_income = new_income - new_expense
    return float(new_net_income) / float(previous_net_income)


def generate_waiver_default_offer(loan_refinancing_request, bucket, product_type):
    if loan_refinancing_request.account:
        return generate_waiver_default_offer_for_j1(loan_refinancing_request, bucket, product_type)

    payments = Payment.objects.filter(
        loan=loan_refinancing_request.loan).not_paid_active().order_by('payment_number')
    payment = payments.first()
    last_payment_number = payments.last().payment_number
    waiver_request = WaiverRequest.objects.filter(
        loan=loan_refinancing_request.loan,
        program_name=product_type.lower()
    ).last()
    if waiver_request:
        last_payment_number = waiver_request.last_payment_number
    if product_type in CovidRefinancingConst.waiver_without_r4():
        overdue_payment = Payment.objects.filter(
            loan=loan_refinancing_request.loan).overdue().filter(is_restructured=False)\
            .order_by('-payment_number').first()
        if overdue_payment:
            last_payment_number = overdue_payment.payment_number
        else:
            last_payment_number = payment.payment_number

    remaining_late_fee = get_remaining_late_fee(payment, True, max_payment_number=last_payment_number)
    remaining_interest = get_remaining_interest(payment, True, max_payment_number=last_payment_number)
    remaining_principal = get_remaining_principal(payment, True, max_payment_number=last_payment_number)
    total_unpaid = remaining_late_fee + remaining_interest + remaining_principal

    product_line_code = loan_refinancing_request.loan.application.product_line_code
    product_line_name = get_partner_product(product_line_code)

    loan_refinancing_score = LoanRefinancingScore.objects.filter(
        loan=loan_refinancing_request.loan,
    ).last()
    principal_recommended_waiver_percent = 0
    interest_recommended_waiver_percent = 0
    is_covid_risky = loan_refinancing_score.is_covid_risky if type(loan_refinancing_score.is_covid_risky) is not bool \
        else 'yes' if loan_refinancing_score.is_covid_risky is True else 'no'
    if product_type == CovidRefinancingConst.PRODUCTS.r4:
        principal_recommended_waiver_percent = CovidRefinancingConst.RECO_TABLE[
            '{}_{}_{}_{}_{}'.format(
                product_type, bucket, 'principal_waiver',
                is_covid_risky, product_line_name
            )
        ]

    if product_type in (CovidRefinancingConst.PRODUCTS.r4, CovidRefinancingConst.PRODUCTS.r6):
        interest_recommended_waiver_percent = CovidRefinancingConst.RECO_TABLE[
            '{}_{}_{}_{}_{}'.format(
                product_type, bucket, 'interest_fee_waiver',
                is_covid_risky, product_line_name
            )
        ]

    late_fee_recommended_waiver_percent = CovidRefinancingConst.RECO_TABLE[
        '{}_{}_{}_{}_{}'.format(
            product_type, bucket, 'late_fee_waiver',
            is_covid_risky, product_line_name
        )
    ]

    validity_in_days = CovidRefinancingConst.BUCKET_BASED_DEFAULT_PARAMS[product_type][bucket]['validity_in_days']
    total_latefee_discount = py2round(float(late_fee_recommended_waiver_percent) * remaining_late_fee // 100)
    total_interest_discount = py2round(float(interest_recommended_waiver_percent) * remaining_interest // 100)
    total_principal_discount = py2round(float(principal_recommended_waiver_percent) * remaining_principal // 100)
    total_discount = total_latefee_discount + total_interest_discount + total_principal_discount

    return dict(
        loan_refinancing_request=loan_refinancing_request,
        product_type=product_type,
        prerequisite_amount=total_unpaid - total_discount,
        total_latefee_discount=total_latefee_discount,
        total_interest_discount=total_interest_discount,
        total_principal_discount=total_principal_discount,
        validity_in_days=validity_in_days,
        interest_discount_percentage=str(interest_recommended_waiver_percent) + '%',
        principal_discount_percentage=str(principal_recommended_waiver_percent) + '%',
        latefee_discount_percentage=str(late_fee_recommended_waiver_percent) + '%',
    )


def generate_waiver_default_offer_for_j1(loan_refinancing_request, bucket, product_type):
    from juloserver.account_payment.services.account_payment_related import \
        get_unpaid_account_payment
    from juloserver.account_payment.models import AccountPayment
    account = loan_refinancing_request.account
    account_payments = get_unpaid_account_payment(account.id)
    account_payment = account_payments.first()
    last_account_payment = account_payments.last()
    waiver_request = loan_refinancing_request.waiverrequest_set.last()
    if waiver_request:
        last_account_payment = waiver_request.last_waived_account_payment
    if product_type in CovidRefinancingConst.waiver_without_r4():
        overdue_account_payment = AccountPayment.objects.filter(account=account)\
            .overdue().filter(is_restructured=False).order_by('-due_date').first()
        last_account_payment = overdue_account_payment if overdue_account_payment else account_payment
        account_payments = AccountPayment.objects.filter(
            pk__gte=account_payment.id, pk__lte=last_account_payment.id
        )

    remaining_late_fee = account_payments.aggregate(
        total_late_fee=Sum(F('late_fee_amount')-F('paid_late_fee')))['total_late_fee'] or 0
    remaining_interest = account_payments.aggregate(
        total_interest=Sum(F('interest_amount')-F('paid_interest')))['total_interest'] or 0
    remaining_principal = account_payments.aggregate(
        total_principal=Sum(F('principal_amount')-F('paid_principal')))['total_principal'] or 0
    total_unpaid = remaining_late_fee + remaining_interest + remaining_principal

    product_line_code = account.last_application.product_line_code
    product_line_name = get_partner_product(product_line_code)

    loan_refinancing_score = LoanRefinancingScoreJ1.objects.filter(account=account,).last()
    principal_recommended_waiver_percent = 0
    interest_recommended_waiver_percent = 0
    is_covid_risky = loan_refinancing_score.is_covid_risky if type(loan_refinancing_score.is_covid_risky) is not bool \
        else 'yes' if loan_refinancing_score.is_covid_risky is True else 'no'
    if product_type == CovidRefinancingConst.PRODUCTS.r4:
        principal_recommended_waiver_percent = CovidRefinancingConst.RECO_TABLE[
            '{}_{}_{}_{}_{}'.format(
                product_type, bucket, 'principal_waiver',
                is_covid_risky, product_line_name
            )
        ]

    if product_type in (CovidRefinancingConst.PRODUCTS.r4, CovidRefinancingConst.PRODUCTS.r6):
        interest_recommended_waiver_percent = CovidRefinancingConst.RECO_TABLE[
            '{}_{}_{}_{}_{}'.format(
                product_type, bucket, 'interest_fee_waiver',
                is_covid_risky, product_line_name
            )
        ]

    late_fee_recommended_waiver_percent = CovidRefinancingConst.RECO_TABLE[
        '{}_{}_{}_{}_{}'.format(
            product_type, bucket, 'late_fee_waiver',
            is_covid_risky, product_line_name
        )
    ]

    validity_in_days = CovidRefinancingConst.BUCKET_BASED_DEFAULT_PARAMS[product_type][bucket]['validity_in_days']
    total_latefee_discount = py2round(float(late_fee_recommended_waiver_percent) * remaining_late_fee // 100)
    total_interest_discount = py2round(float(interest_recommended_waiver_percent) * remaining_interest // 100)
    total_principal_discount = py2round(float(principal_recommended_waiver_percent) * remaining_principal // 100)
    total_discount = total_latefee_discount + total_interest_discount + total_principal_discount

    return dict(
        loan_refinancing_request=loan_refinancing_request,
        product_type=product_type,
        prerequisite_amount=total_unpaid - total_discount,
        total_latefee_discount=total_latefee_discount,
        total_interest_discount=total_interest_discount,
        total_principal_discount=total_principal_discount,
        validity_in_days=validity_in_days,
        interest_discount_percentage=str(interest_recommended_waiver_percent) + '%',
        principal_discount_percentage=str(principal_recommended_waiver_percent) + '%',
        latefee_discount_percentage=str(late_fee_recommended_waiver_percent) + '%',
    )


def get_r4_default_loan_refinancing_offer(loan_refinancing_request, bucket):
    return generate_waiver_default_offer(loan_refinancing_request, bucket, "R4")


def get_r5_default_loan_refinancing_offer(loan_refinancing_request, bucket):
    return generate_waiver_default_offer(loan_refinancing_request, bucket, "R5")


def get_r6_default_loan_refinancing_offer(loan_refinancing_request, bucket):
    return generate_waiver_default_offer(loan_refinancing_request, bucket, "R6")


def loan_refinancing_request_update_waiver(payment):
    from ..tasks import (send_email_refinancing_offer_selected,
                         send_sms_covid_refinancing_offer_selected,
                         send_pn_covid_refinancing_offer_selected)
    from .comms_channels import send_loan_refinancing_request_approved_notification

    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        loan=payment.loan, status=CovidRefinancingConst.STATUSES.offer_selected
    ).last()

    if loan_refinancing_request:
        loan_refinancing_offer = LoanRefinancingOffer.objects.filter(
            loan_refinancing_request=loan_refinancing_request,
            product_type__in=CovidRefinancingConst.waiver_products(),
            is_accepted=True,
            is_latest=True
        ).last()
        if loan_refinancing_offer:
            waiver_temp = WaiverTemp.objects.filter(
                loan=payment.loan, status=WaiverConst.ACTIVE_STATUS).last()

            if waiver_temp:
                update_offer = False
                pass_latefee = int(waiver_temp.late_fee_waiver_amt) > 0
                pass_interest = int(waiver_temp.interest_waiver_amt) > 0
                pass_principal = int(waiver_temp.principal_waiver_amt) > 0

                if loan_refinancing_request.product_type == CovidRefinancingConst.PRODUCTS.r4 and \
                    pass_latefee and pass_interest and pass_principal:
                    send_email_refinancing_offer_selected.delay(loan_refinancing_request.id)
                    send_pn_covid_refinancing_offer_selected.delay(loan_refinancing_request.id)
                    send_sms = True
                    comms_list = loan_refinancing_request.comms_channel_list()
                    if loan_refinancing_request.channel == CovidRefinancingConst.CHANNELS.reactive \
                            and CovidRefinancingConst.COMMS_CHANNELS.sms not in comms_list:
                        send_sms = False

                    if send_sms:
                        send_sms_covid_refinancing_offer_selected.delay(loan_refinancing_request.id)

                    update_offer = True

                elif loan_refinancing_request.product_type == CovidRefinancingConst.PRODUCTS.r5 and \
                    pass_latefee:
                    loan_refinancing_request.update_safely(status=CovidRefinancingConst.STATUSES.approved)
                    send_loan_refinancing_request_approved_notification(loan_refinancing_request)
                    update_offer = True

                elif loan_refinancing_request.product_type == CovidRefinancingConst.PRODUCTS.r6 and \
                    pass_latefee and pass_interest:
                    loan_refinancing_request.update_safely(status=CovidRefinancingConst.STATUSES.approved)
                    send_loan_refinancing_request_approved_notification(loan_refinancing_request)
                    update_offer = True

                if update_offer:
                    loan_refinancing_offer.update_safely(
                        total_latefee_discount=int(waiver_temp.late_fee_waiver_amt),
                        total_interest_discount=int(waiver_temp.interest_waiver_amt),
                        total_principal_discount=int(waiver_temp.principal_waiver_amt),
                        prerequisite_amount=int(waiver_temp.need_to_pay)
                    )
                    loan_refinancing_request.update_safely(
                        total_latefee_discount=int(waiver_temp.late_fee_waiver_amt),
                        prerequisite_amount=int(waiver_temp.need_to_pay)
                    )


def get_r2_payment_structure(loan_refinancing_request, loan_duration_extension):
    from ..services.refinancing_product_related import construct_new_payments_for_r2
    from juloserver.account_payment.services.account_payment_related import \
        get_unpaid_account_payment
    if loan_refinancing_request.account:
        ordered_unpaid_payments = get_unpaid_account_payment(loan_refinancing_request.account.id)
    else:
        ordered_unpaid_payments = get_unpaid_payments(
            loan_refinancing_request.loan, order_by='payment_number')
    new_payment_structures = construct_new_payments_for_r2(
        loan_refinancing_request=loan_refinancing_request,
        unpaid_payments=ordered_unpaid_payments,
        proactive_loan_duration=loan_duration_extension
    )
    return new_payment_structures


def get_r3_payment_structure(loan_refinancing_request, loan_duration_extension):
    from ..services.refinancing_product_related import construct_new_payments_for_r3
    from juloserver.account_payment.services.account_payment_related import \
        get_unpaid_account_payment
    if loan_refinancing_request.account:
        ordered_unpaid_payments = get_unpaid_account_payment(loan_refinancing_request.account.id)
    else:
        ordered_unpaid_payments = get_unpaid_payments(
            loan_refinancing_request.loan, order_by='payment_number')
    new_payment_structures = construct_new_payments_for_r3(
        loan_refinancing_request=loan_refinancing_request,
        unpaid_payments=ordered_unpaid_payments,
        proactive_loan_duration=loan_duration_extension
    )
    return new_payment_structures


def is_cashback_blocked_by_collection_repayment_reason(account_id):
    # if return True value, will block cashback autodeduction
    return LoanRefinancingRequest.objects.filter(
        status__in=CovidRefinancingConst.BLOCKING_CASHBACK_AUTODEDUCTION,
        account=account_id
    ).exists()


def is_point_blocked_by_collection_repayment_reason(account_id):
    return LoanRefinancingRequest.objects.filter(
        status__in=CovidRefinancingConst.BLOCKING_POINT_AUTODEDUCTION,
        account=account_id
    ).exists()
