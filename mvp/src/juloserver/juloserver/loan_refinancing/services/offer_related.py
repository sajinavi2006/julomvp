from builtins import str
import logging
import json
import pyotp
import time
from datetime import timedelta
from django.utils import timezone
from babel.dates import format_date

from ..models import (LoanRefinancingRequest,
                      LoanRefinancingMainReason,
                      LoanRefinancingOffer,
                      CollectionOfferEligibility,
                      WebScrapedData,
                      WaiverApproval,
                      WaiverPaymentRequest,
)

from ..constants import CovidRefinancingConst
from ..constants import GeneralWebsiteConst
from juloserver.julo.constants import VendorConst
from juloserver.webapp.constants import CommonVariables

from .loan_related import (get_sum_of_principal_paid_and_late_fee_amount,
                           get_unpaid_payments)

from .refinancing_product_related import (construct_new_payments_for_r2,
                                          construct_new_payments_for_r3)
from juloserver.julo.models import Payment, Loan, OtpRequest, Application, SmsHistory, PaymentPreRefinancing
from juloserver.julo.exceptions import JuloException
from django.conf import settings
from django.db.models import Q
from django.db import transaction
from django.template.loader import render_to_string
from juloserver.julo.models import FeatureSetting
from juloserver.webapp.models import WebScrapedData
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.julo.tasks import send_sms_otp_token
from juloserver.loan_refinancing.tasks import send_sms_notification
from juloserver.julo.utils import display_rupiah

from juloserver.account.models import Account
from dateutil.relativedelta import relativedelta
from juloserver.waiver.models import WaiverRequest
from juloserver.integapiv1.tasks import update_va_bni_transaction
from juloserver.account_payment.models import AccountPayment

logger = logging.getLogger(__name__)

def get_r2_loan_refinancing_offer(loan_refinancing_request, bucket, default_extension=True):
    from juloserver.account_payment.services.account_payment_related import (
        get_unpaid_account_payment
    )
    from juloserver.refinancing.services import generate_new_payment_structure
    tenure_extension = loan_refinancing_request.loan_duration
    if default_extension:
        # temporary update extension based on constant
        tenure_extension = CovidRefinancingConst.BUCKET_BASED_EXTENSION_LIMIT[bucket]
        loan_refinancing_request.loan_duration = tenure_extension
    if loan_refinancing_request.account:
        unpaid_payments = get_unpaid_account_payment(loan_refinancing_request.account_id)
    else:
        unpaid_payments = get_unpaid_payments(loan_refinancing_request.loan, order_by='payment_number')

    if loan_refinancing_request.account and loan_refinancing_request.product_type:
        _, new_payment_structures = generate_new_payment_structure(
            loan_refinancing_request.account, loan_refinancing_request,
            count_unpaid_account_payments=len(unpaid_payments),
        )
    else:
        new_payment_structures = construct_new_payments_for_r2(
            loan_refinancing_request, unpaid_payments)

    loan_dict = get_sum_of_principal_paid_and_late_fee_amount(unpaid_payments, loan_refinancing_request)
    if default_extension:
        # switch back to original value
        loan_refinancing_request.refresh_from_db()

    return dict(
        loan_refinancing_request=loan_refinancing_request,
        product_type="R2",
        prerequisite_amount=new_payment_structures[0]['due_amount'],
        total_latefee_discount=loan_dict['late_fee_amount__sum'],
        loan_duration=tenure_extension,
        validity_in_days=loan_refinancing_request.expire_in_days
    )


def get_r3_loan_refinancing_offer(loan_refinancing_request, bucket, default_extension=True):
    from juloserver.account_payment.services.account_payment_related import (
        get_unpaid_account_payment
    )
    from juloserver.refinancing.services import generate_new_payment_structure
    tenure_extension = loan_refinancing_request.loan_duration
    if default_extension:
        # temporary update extension based on constant
        tenure_extension = CovidRefinancingConst.BUCKET_BASED_EXTENSION_LIMIT[bucket]
        loan_refinancing_request.loan_duration = tenure_extension
    if loan_refinancing_request.account:
        unpaid_payments = get_unpaid_account_payment(loan_refinancing_request.account_id)
    else:
        unpaid_payments = get_unpaid_payments(loan_refinancing_request.loan, order_by='payment_number')

    if loan_refinancing_request.account and loan_refinancing_request.product_type:
        _, new_payment_structures = generate_new_payment_structure(
            loan_refinancing_request.account, loan_refinancing_request,
            count_unpaid_account_payments=len(unpaid_payments),
        )
        loan_dict = get_sum_of_principal_paid_and_late_fee_amount(
            unpaid_payments, loan_refinancing_request)
        total_latefee_discount = loan_dict['late_fee_amount__sum']
    else:
        new_payment_structures = construct_new_payments_for_r3(
            loan_refinancing_request, unpaid_payments)
        total_latefee_discount = new_payment_structures['total_latefee_amount']
    if default_extension:
        # switch back to original value
        loan_refinancing_request.refresh_from_db()

    return dict(
        loan_refinancing_request=loan_refinancing_request,
        product_type="R3",
        prerequisite_amount=new_payment_structures['payments'][0]['due_amount'],
        total_latefee_discount=total_latefee_discount,
        loan_duration=tenure_extension,
        validity_in_days=loan_refinancing_request.expire_in_days
    )


def get_offer_constructor_function(product_type):
    from .loan_related import (get_r1_loan_refinancing_offer,
                               get_r4_default_loan_refinancing_offer,
                               get_r5_default_loan_refinancing_offer,
                               get_r6_default_loan_refinancing_offer)
    offer_function = {
        'R1': get_r1_loan_refinancing_offer,
        'R2': get_r2_loan_refinancing_offer,
        'R3': get_r3_loan_refinancing_offer,
        'R4': get_r4_default_loan_refinancing_offer,
        'R5': get_r5_default_loan_refinancing_offer,
        'R6': get_r6_default_loan_refinancing_offer,
    }
    return offer_function[product_type]


def generated_default_offers(
        loan_refinancing_request, refinancing_products,
        is_proactive_offer=False):
    if not refinancing_products:
        return False

    default_offers = []

    if loan_refinancing_request.account:
        account = loan_refinancing_request.account
        bucket_number = account.bucket_number
    else:
        payment = Payment.objects.filter(
            loan=loan_refinancing_request.loan).not_paid_active().order_by('payment_number').first()
        if not payment:
            raise JuloException("tidak dapat diproses. pinjaman belum aktif")
        bucket_number = payment.bucket_number
    refinancing_product = refinancing_products.split(',')
    refinancing_product = list([_f for _f in refinancing_product if _f])
    loan_refinancing_request.loanrefinancingoffer_set.update(is_latest=False)
    recommendation_order = 1
    for product in refinancing_product:
        offer_dict = get_offer_constructor_function(product)(loan_refinancing_request, bucket_number)
        offer_dict['is_latest'] = True
        offer_dict['recommendation_order'] = recommendation_order
        offer_dict['is_proactive_offer'] = is_proactive_offer
        default_offers.append(LoanRefinancingOffer(**offer_dict))
        recommendation_order = recommendation_order + 1
    LoanRefinancingOffer.objects.bulk_create(default_offers)
    return True


def construct_loan_refinancing_request(data, feature_params, initial=True, is_j1=False):
    from juloserver.refinancing.services import get_monthly_expenses
    account = None
    if is_j1:
        account = Account.objects.get(pk=data['account_id'])
        loan = account.loan_set.last()
        app = account.last_application
        loan_id = None
        account_id = data['account_id']
    else:
        loan = Loan.objects.select_related(
            'application', 'application__customer').get(pk=data['loan_id'])
        app = loan.application
        account_id = None
        loan_id = data['loan_id']

    app_monthly_expenses = get_monthly_expenses(account, app)
    new_net_income = app.monthly_income - app_monthly_expenses
    if data['new_income'] and data['new_expense']:
        new_net_income = int(data['new_income']) - int(data['new_expense'])
    previous_net_income = app.monthly_income - app_monthly_expenses
    new_affordability = float(new_net_income) / float(previous_net_income)
    extension = 0
    product = None
    if not initial:
        product = data['selected_product']
        if 'MTL_%s' % loan.loan_duration not in feature_params['tenure_extension_rule']:
            extension = 3
        else:
            max_extension = feature_params['tenure_extension_rule']['MTL_%s' % loan.loan_duration]
            tenure_extension = int(data['tenure_extension']) if data['tenure_extension'] else 0
            extension = tenure_extension if tenure_extension < max_extension else max_extension
        if product == CovidRefinancingConst.PRODUCTS.r1:
            extension = int(data['tenure_extension'])

    return dict(
        loan_id=loan_id,
        account_id=account_id,
        # store percentage as decimal
        affordability_value=new_affordability,
        product_type=product,
        expire_in_days=feature_params['email_expire_in_days'],
        loan_duration=extension,
        new_income=int(data['new_income'] or 0),
        new_expense=int(data['new_expense'] or 0),
        loan_refinancing_main_reason=LoanRefinancingMainReason.objects.filter(
            reason__icontains=data['new_employment_status'], is_active=True).last(),
    )


def determine_collection_offer_eligibility(mobile_phone, browser_data):
    customer = None
    loan = None
    is_eligible = False
    application = Application.objects.filter(
        (Q(mobile_phone_1=mobile_phone) | Q(mobile_phone_2=mobile_phone))
    ).last()
    if application:
        queryset = Loan.objects.filter(application_id=application.id)
        loan = queryset.last()
        if loan:
            queryset = queryset.filter(
                loan_status__gt=LoanStatusCodes.INACTIVE,
                loan_status__lt=LoanStatusCodes.PAID_OFF,
                application__application_status=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL)
            loan = queryset.last()
            if loan:
                loan_refinancing_request = LoanRefinancingRequest.objects.filter(
                    loan=loan).last()
                if loan_refinancing_request:
                    if loan_refinancing_request.status in GeneralWebsiteConst.STATUSES.eligible:
                        is_eligible = True
                        customer = loan.application.customer
                    reason = GeneralWebsiteConst.REASONS[loan_refinancing_request.status]
                    application = loan.application
                else:
                    reason = "not whitelisted"
            else:
                reason = "not whitelisted"
        else:
            reason = "not whitelisted"
    else:
        reason = "phone number does not exist"
    web_scraped_data = None
    with transaction.atomic():
        if application:
            web_scraped_data = WebScrapedData.objects.create(
                application=application,
                data_trigger_location=browser_data['data_trigger_location'],
                browser_name=browser_data['browser_name'],
                browser_version=browser_data['browser_version'],
                os_name=browser_data['os_name'],
                os_version=browser_data.get('os_version', None),
                os_version_name=browser_data.get('os_version_name', None),
                platform_type=browser_data['platform_type'],
                engine_name=browser_data['engine_name'])

        status = "Eligible" if is_eligible else "Not Eligible"
        CollectionOfferEligibility.objects.create(
            mobile_phone=mobile_phone,
            status="%s - %s" % (status, reason),
            application=application,
            loan=loan,
            web_scraped_data=web_scraped_data)
    return application, customer, is_eligible


def check_collection_offer_eligibility(mobile_phone, browser_data):

    feature_setting = FeatureSetting.objects.get_or_none(
                        feature_name=FeatureNameConst.COLLECTION_OFFER_GENERAL_WEBSITE)
    if not feature_setting or not feature_setting.is_active:
        raise JuloException('Verifikasi kode tidak aktif')

    application, customer, is_eligible = determine_collection_offer_eligibility(mobile_phone, browser_data)

    if not is_eligible:
        raise JuloException('You are not eligible')

    otp_wait_time_seconds = feature_setting.parameters['otp_wait_time_seconds']
    otp_max_request = feature_setting.parameters['otp_max_request']
    otp_resend_time = feature_setting.parameters['otp_resend_time']
    otp_request, need_to_send, change_sms_provider = generate_or_get_active_otp(
        application, customer, mobile_phone, otp_wait_time_seconds, otp_max_request, otp_resend_time)

    if need_to_send:
        context = {'otp_token': otp_request.otp_token}
        text_message = render_to_string('otp_token_sms_template.txt', context=context)
        send_sms_otp_token.delay(mobile_phone, text_message, customer.id, otp_request.id,
                                 change_sms_provider, 'eligibility_check_otp')

    return otp_request.request_id


def generate_or_get_active_otp(application, customer, mobile_phone, otp_wait_time_seconds, otp_max_request, otp_resend_time):
    change_sms_provider = False
    need_to_send = True
    now = timezone.localtime(timezone.now())

    postfixed_request_id = str(customer.id) + str(int(time.time()))
    existing_otp_request = OtpRequest.objects.filter(
        customer=customer, is_used=False, phone_number=mobile_phone).order_by('id').last()

    if not existing_otp_request:
        hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
        otp_token = str(hotp.at(int(postfixed_request_id)))
        otp_request = OtpRequest.objects.create(
            application=application, customer=customer, request_id=postfixed_request_id,
            otp_token=otp_token, phone_number=mobile_phone)
        return otp_request, need_to_send, change_sms_provider

    if not existing_otp_request.sms_history:
        #change_sms_provider = True
        return existing_otp_request, need_to_send, change_sms_provider

    if not existing_otp_request.is_active_by_sms_history(otp_wait_time_seconds):
        hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
        otp_token = str(hotp.at(int(postfixed_request_id)))
        otp_request = OtpRequest.objects.create(
            application=application, customer=customer,
            request_id=postfixed_request_id,
            otp_token=otp_token, phone_number=mobile_phone)
        return otp_request, need_to_send, change_sms_provider

    retry_count = SmsHistory.objects.filter(
        customer=customer, cdate__gte=existing_otp_request.cdate
    ).exclude(status='UNDELIV').exclude(status="failed").count()
    retry_count += 1
    if retry_count > otp_max_request:
        # customer is stuck until OTP expires
        need_to_send = False
        return existing_otp_request, need_to_send, change_sms_provider

    sms_history = existing_otp_request.sms_history
    resend_time = timezone.localtime(sms_history.cdate) + timedelta(seconds=otp_resend_time)
    if now < resend_time:
        # customer just needs to wait
        need_to_send = False
        return existing_otp_request, need_to_send, change_sms_provider

    if not sms_history.comms_provider and not sms_history.comms_provider.provider_name:
        raise JuloException

    # customer wait while we resend the otp
    if sms_history.comms_provider.provider_name.lower() == VendorConst.MONTY:
        return existing_otp_request, need_to_send, change_sms_provider


def validate_collection_offer_otp(otp_token, request_id, otp_wait_time_seconds):

    otp_request = OtpRequest.objects.filter(
        otp_token=otp_token, is_used=False, request_id=request_id).order_by('id').last()
    if not otp_request:
        raise JuloException("OTP not found: %s" % otp_token)
    if str(otp_request.customer_id) not in str(otp_request.request_id):
        raise JuloException("request ID invalid: %s" % request_id)

    hotp = pyotp.HOTP(settings.OTP_SECRET_KEY)
    valid_token = hotp.verify(otp_token, int(otp_request.request_id))
    if not valid_token:
        raise JuloException("OTP invalid: %s" % otp_token)

    if not otp_request.is_active_by_sms_history(otp_wait_time_seconds):
        raise JuloException("OTP expired after: %s seconds" % otp_wait_time_seconds)

    otp_request.update_safely(is_used=True)

    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        loan__application=otp_request.application).last()
    url = loan_refinancing_request.url
    context = {'url': url}
    text_message = render_to_string('webpage_url_sms_template.txt', context=context)
    send_sms_notification.delay(
        otp_request.customer_id, otp_request.phone_number,
        text_message, template_code='eligibility_check_url'
    )
    return url


def reorder_recommendation(loan_refinancing_request):
    refinancing_offers = loan_refinancing_request.loanrefinancingoffer_set\
        .filter(is_latest=True, is_proactive_offer=True)\
        .order_by('recommendation_order', '-cdate')

    for idx, refinancing_offer in enumerate(refinancing_offers):
        recommendation_order = idx + 1
        is_latest = True
        if recommendation_order > 2:
            recommendation_order = None
            is_latest = False
        refinancing_offer.update_safely(
            recommendation_order=recommendation_order, is_latest=is_latest)


def reorder_recommendation_by_status(loan_refinancing_status):
    loan_refinancing_requests = LoanRefinancingRequest.objects.exclude(
        status__in=loan_refinancing_status
    ).filter(loanrefinancingoffer__isnull=False)

    for loan_refinancing_request in loan_refinancing_requests:
        reorder_recommendation(loan_refinancing_request)


def get_proactive_offers(loan_refinancing_request):
    return loan_refinancing_request.loanrefinancingoffer_set.filter(
        is_latest=True,
        recommendation_order__isnull=False)\
        .order_by('recommendation_order')[:2]


def get_status_date(refinancing_request):
    status = refinancing_request.status
    if status == CovidRefinancingConst.STATUSES.activated:
        return format_date(
            refinancing_request.offer_activated_ts.date(), 'dd-MM-yyyy', locale='id_ID')
    if status in (CovidRefinancingConst.STATUSES.offer_selected,
                  CovidRefinancingConst.STATUSES.approved):
        offer = refinancing_request.loanrefinancingoffer_set.filter(
            is_accepted=True, product_type=refinancing_request.product_type).last()
        if offer:
            return format_date(
                offer.offer_accepted_ts.date(), 'dd-MM-yyyy', locale='id_ID')
    if status in (CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email,
                  CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit):
        return format_date(
            refinancing_request.cdate.date(), 'dd-MM-yyyy', locale='id_ID')
    if status == CovidRefinancingConst.STATUSES.offer_generated:
        offer = refinancing_request.loanrefinancingoffer_set.last()
        if offer:
            return format_date(
                offer.cdate.date(), 'dd-MM-yyyy', locale='id_ID')
    return ''


def get_discount_detail(refinancing_request):
    if refinancing_request.product_type:
        offer = refinancing_request.loanrefinancingoffer_set.filter(
            is_accepted=True, product_type=refinancing_request.product_type).last()
        if offer:
            return (
                display_rupiah(offer.total_principal_discount),
                display_rupiah(offer.total_interest_discount),
                display_rupiah(offer.total_latefee_discount)
            )
        else:
            return (display_rupiah(0),
                    display_rupiah(0),
                    display_rupiah(refinancing_request.total_latefee_discount))

    return display_rupiah(0), display_rupiah(0), display_rupiah(0)


def get_existing_accepted_offer(refinancing_request_qs):
    existing_offers_list = []
    refinancing_request_qs = refinancing_request_qs.order_by('-cdate')
    for refinancing_request in refinancing_request_qs:
        request_date = refinancing_request.request_date or refinancing_request.cdate.date()
        principal_discount, interest_discount, latefee_discount = \
            get_discount_detail(refinancing_request)
        requested_expire_date = ''
        expire_date = ''
        if refinancing_request.status != CovidRefinancingConst.STATUSES.activated:
            requested_expire_date = refinancing_request.request_date + timedelta(
                days=refinancing_request.expire_in_days
            )
            requested_expire_date = format_date(requested_expire_date, 'dd-MM-yyyy', locale='id_ID') 
            expire_date = requested_expire_date
            waiver_approval = WaiverApproval.objects.filter(waiver_request__loan_refinancing_request=refinancing_request).last()
            if waiver_approval: 
                expire_date = format_date(waiver_approval.approved_waiver_validity_date, 'dd-MM-yyyy', locale='id_ID') 
                    
        constructed_offer = {
            'product_type': refinancing_request.product_type or '',
            'request_date': format_date(request_date, 'dd-MM-yyyy', locale='id_ID'),
            'status': refinancing_request.status,
            'status_date': get_status_date(refinancing_request),
            'principal_discount': principal_discount,
            'interest_discount': interest_discount,
            'latefee_discount': latefee_discount,
            'extension': refinancing_request.loan_duration or 0,
            'prerequisite_amount': display_rupiah(refinancing_request.prerequisite_amount or 0),
            'requested_expire_date': requested_expire_date,
            'expire_date': expire_date
        }
        existing_offers_list.append(constructed_offer)
    return existing_offers_list


def pass_check_refinancing_max_cap_rule_by_account_id(account_id, product_type):
    latest_refinancing = None
    now = timezone.localtime(timezone.now())

    product_type = product_type.upper()
    max_cap_rule_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.REFINANCING_MAX_CAP_RULE_TRIGGER,
        is_active=True,
    ).last()
    if not max_cap_rule_fs:
        max_cap_rule_fs = {
            'parameters': {
                'R1': True,
                'R2': True,
                'R3': True,
                'R4': True,
                'Stacked': False,
            },
        }

    if hasattr(max_cap_rule_fs, 'parameters'):
        max_cap_rule_params = max_cap_rule_fs.parameters
    else:
        max_cap_rule_params = {
            'R1': True,
            'R2': True,
            'R3': True,
            'R4': True,
            'Stacked': False,
        }

    activated_refinancing = LoanRefinancingRequest.objects.filter(
        account_id=account_id,
        product_type__in=CovidRefinancingConst.reactive_products() + CovidRefinancingConst.waiver_without_r4(),
        status=CovidRefinancingConst.STATUSES.activated,
    ).last()
    if activated_refinancing and max_cap_rule_params.get('Stacked', False):
        if activated_refinancing.product_type in CovidRefinancingConst.reactive_products():
            effected_loan_ids = list(PaymentPreRefinancing.objects.filter(
                loan_refinancing_request=activated_refinancing.id
            ).distinct('loan').values_list('loan_id', flat=True))
            unpaid_loan = Loan.objects.filter(
                loan_status__lt=LoanStatusCodes.PAID_OFF,
                pk__in=effected_loan_ids
            )
            if unpaid_loan:
                return False, 'Sedang ada program refinancing yang berjalan atau aktif'
        if activated_refinancing.product_type in CovidRefinancingConst.waiver_without_r4():
            waiver_request = WaiverRequest.objects.filter(
                loan_refinancing_request=activated_refinancing.id
            ).values_list('id', flat=True).last()
            effected_loan_ids = list(WaiverPaymentRequest.objects.filter(
                waiver_request=waiver_request
            ).distinct('payment__loan').values_list('payment__loan', flat=True))
            unpaid_loan = Loan.objects.filter(
                loan_status__lt=LoanStatusCodes.PAID_OFF,
                pk__in=effected_loan_ids
            )
            if unpaid_loan:
                return False, 'Sedang ada program refinancing yang berjalan atau aktif'

    if product_type == 'R1' and max_cap_rule_params.get('R1', False):
        latest_refinancing = LoanRefinancingRequest.objects.filter(
            account_id=account_id,
            product_type=product_type,
            status=CovidRefinancingConst.STATUSES.activated,
            offer_activated_ts__date__gte=now - relativedelta(years=1)
        ).exists()
        if latest_refinancing:
            return False, 'Hanya bisa digunakan sekali dalam 12 bulan terakhir'

    elif product_type in ['R2', 'R3'] and max_cap_rule_params.get('R2', False) and max_cap_rule_params.get('R3', False):
        latest_refinancing = LoanRefinancingRequest.objects.filter(
            account_id=account_id,
            product_type__in=['R2', 'R3'],
            status=CovidRefinancingConst.STATUSES.activated,
            offer_activated_ts__date__gte=now - relativedelta(years=1)
        )
        if latest_refinancing.count() >= 2:
            return False, 'Kombinasi 2 tawaran refinancing ini hanya berlaku 2 kali dalam 12 bulan terakhir'

    elif product_type == 'R4' and max_cap_rule_params.get('R4', False):
        latest_refinancing = WaiverRequest.objects.filter(
            account=account_id,
            program_name=product_type.lower(),
            loan_refinancing_request__status=CovidRefinancingConst.STATUSES.activated
        )
        if len(latest_refinancing) >= 2:
            return False, 'Hanya dapat digunakan total 2 kali selamanya untuk pelanggan jika diskon pokok yang diberikan < 50%'
        elif len(latest_refinancing) == 1:
            latest_refinancing = latest_refinancing.last()
            if latest_refinancing.unrounded_requested_principal_waiver_percentage >= 0.5:
                return False, 'Hanya dapat digunakan 1 kali selamanya untuk pelanggan dengan diskon pokok yang diberikan >= 50%'

    return True, ''


def is_account_can_offered_refinancing(account):
    today = timezone.localtime(timezone.now()).date()
    dpd_90 = today - relativedelta(days=90)
    loan_active_with_bss_lender =  account.loan_set.filter(
        lender__lender_name__in=CovidRefinancingConst.BLOCKED_BY_LENDER,
        loan_status__status_code__range=(LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_60DPD),
    )
    if loan_active_with_bss_lender:
        return False
    loan_dpd_90_with_bss_lender = account.loan_set.filter(
        lender__lender_name__in=CovidRefinancingConst.BLOCKED_BY_LENDER,
        loan_status__status_code=LoanStatusCodes.LOAN_90DPD
    )
    if loan_dpd_90_with_bss_lender:
        for loan in loan_dpd_90_with_bss_lender:
            payment_dpd_90_with_bss_lender = loan.payment_set.not_paid_active().order_by('due_date').first()
            if payment_dpd_90_with_bss_lender.due_date >= dpd_90:
                return False
    return True


def create_loan_refinancing_request_sos(account_id, expire_days):
    loan_refinancing_request = LoanRefinancingRequest.objects.create(
        **dict(
            account_id=account_id,
            expire_in_days=expire_days,
            product_type='R1',
            loan_duration=0,
            new_income=0,
            new_expense=0,
            affordability_value=1,
            prerequisite_amount=0,
            status=CovidRefinancingConst.STATUSES.approved,
            request_date=timezone.localtime(timezone.now()).date(),
            channel=CovidRefinancingConst.CHANNELS.reactive,
            comms_channel_1=CovidRefinancingConst.COMMS_CHANNELS.email,
        ))
    account_payment = AccountPayment.objects.filter(
        account=loan_refinancing_request.account).not_paid_active().order_by(
        'due_date').first()
    offer_constuctor_func = get_offer_constructor_function('R1')
    selected_offer_dict = offer_constuctor_func(
        loan_refinancing_request, account_payment.bucket_number, default_extension=False)
    LoanRefinancingOffer.objects.create(
        **dict(
            product_type="R1",
            prerequisite_amount=0,
            total_latefee_discount=selected_offer_dict['total_latefee_discount'],
            validity_in_days=expire_days,
            is_latest=True,
            is_accepted=True,
            offer_accepted_ts=timezone.localtime(timezone.now()),
            loan_refinancing_request=loan_refinancing_request,
        ))
    loan_refinancing_request.update_safely(**dict(
        total_latefee_discount=selected_offer_dict['total_latefee_discount']))

    return loan_refinancing_request


def change_exist_refinancing_status_to_expired(account):
    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        account=account, status__in=[
            'Email Sent', 'Form Viewed', 'Offer Generated', 'Offer Selected', 'Approved']
    )
    LoanRefinancingOffer.objects.filter(
        loan_refinancing_request=loan_refinancing_request
    ).update(is_latest=False)
    loan_refinancing_request.update(
        expire_in_days=0,
        status=CovidRefinancingConst.STATUSES.expired,
        udate=timezone.localtime(timezone.now())
    )
    update_va_bni_transaction.delay(
        account.id,
        'loan_refinancing.services.offer_related.change_exist_refinancing_status_to_expired',
    )
