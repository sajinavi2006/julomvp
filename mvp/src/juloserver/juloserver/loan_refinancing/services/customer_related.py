from datetime import timedelta

from django.utils import timezone
from django.db.models import (
    IntegerField,
    F,
    ExpressionWrapper,
    Sum
)
from juloserver.julo.models import (
    Payment,
    Loan,
    SkiptraceHistory,
    Partner,
    FeatureSetting,
    Customer,
    Application
)
from juloserver.julo.partners import (
    PartnerConstant
)
from juloserver.julo.statuses import (
    PaymentStatusCodes,
    LoanStatusCodes
)
from juloserver.julo.services2 import encrypt
from ..utils import (
    convert_string_date_to_date_object
)
from ..constants import (
    LoanRefinancingConst,
    CovidRefinancingConst
)
from ..models import (
    LoanRefinancing,
    LoanRefinancingMainReason,
    LoanRefinancingSubReason)


def get_first_criteria_passed_loans(loans):
    """To get loans that have its payments paid minimum once on time

    Arguments:
        loans {list} -- list of active loans

    Returns:
        list -- list of eligible loans
    """
    eligible_loans = Payment.objects.filter(
        loan__in=loans,
        payment_status_id=PaymentStatusCodes.PAID_ON_TIME
    ).distinct('loan').values_list('loan', flat=True)

    return eligible_loans


def get_second_criteria_passed_loans(loans):
    """To get loans who are at 60 DPD for now. Subjected to changes usually

    Arguments:
        loans {list} -- list of loans

    Returns:
        list -- eligible loans that are 60 DPD
    """
    from .loan_related import get_all_loan_refinanced_loans

    today = timezone.localtime(timezone.now()).date()
    loan_refinanced_loans = get_all_loan_refinanced_loans()
    eligible_loans = Payment.objects\
        .annotate(
            dpd=ExpressionWrapper(
                today - F('due_date'),
                output_field=IntegerField()))\
        .filter(
            loan_id__in=loans,
            payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
            dpd__in=LoanRefinancingConst.ELIGIBLE_DPD
        ).exclude(loan__in=loan_refinanced_loans)\
        .order_by('loan', 'id').distinct('loan').values_list('loan', flat=True)

    return eligible_loans


def get_customers_that_passed_st_criteria(applications):
    """To get customers who has high effectiveness value

    Arguments:
        applications {list} -- list of applications

    Returns:
        list -- list of customers
    """

    loan_refinancing_experiment = FeatureSetting.objects.get_or_none(
        is_active=True,
        feature_name=LoanRefinancingConst.LOAN_REFINANCING_FEATURE_SETTING
    )

    if not loan_refinancing_experiment:
        return []

    customer_reliability_threshold = loan_refinancing_experiment\
        .parameters['customer_reliability_threshold']

    targeted_customers = SkiptraceHistory.objects.values('application')\
        .annotate(sum_reliability_score=Sum('call_result__customer_reliability_score'))\
        .filter(
            sum_reliability_score__gte=customer_reliability_threshold,
            application__in=applications)\
        .values_list('loan__customer', flat=True)

    if not targeted_customers:
        return []

    return targeted_customers


def get_eligible_customers():
    """To get eligible customers who passed 3 criterias:
     - At least one payment paid on time
     - The oldest active payment is on dpd 60
     - Have high customer reliability score

    Returns:
        list -- List of customers who are eligible
    """
    exclude_partner_ids = Partner.objects.filter(name__in=PartnerConstant.excluded_for_crm())\
        .values_list('id', flat=True)
    loans = Loan.objects\
        .filter(loan_status_id__gte=LoanStatusCodes.CURRENT,
                loan_status_id__lt=LoanStatusCodes.RENEGOTIATED,
                )\
        .exclude(application__partner__id__in=exclude_partner_ids)\
        .values_list('id', flat=True)

    # One payment is paid on time
    first_criteria_passed_loans = get_first_criteria_passed_loans(loans)

    if not first_criteria_passed_loans:
        return []

    # Oldest payment is on 60 dpd
    second_criteria_passed_loans = get_second_criteria_passed_loans(first_criteria_passed_loans)

    if not second_criteria_passed_loans:
        return []

    applications = Loan.objects.filter(
        pk__in=second_criteria_passed_loans
    ).values_list('application', flat=True)

    eligible_customers = get_customers_that_passed_st_criteria(applications)

    return eligible_customers


def check_if_customer_still_eligible_for_loan_refinancing_registration(email_time):
    today = timezone.localtime(timezone.now()).date()
    difference_in_days = (today - email_time).days

    if difference_in_days > LoanRefinancingConst.LOAN_REFINANCING_EMAIL_EXPIRATION_DAYS:
        return False

    return True


def get_user_data_from_app(application_id):
    application = Application.objects.get_or_none(pk=application_id)

    if not application:
        return False

    customer = application.customer
    customer_dict = {
        'id': customer.id,
        'email': customer.email,
        'ktp': customer.nik,
        'fullname': customer.fullname
    }
    application_dict = {
        'id': application.id
    }

    return {
        'token': customer.user.auth_expiry_token.key,
        'customer': customer_dict,
        'application': application_dict
    }


def process_encrypted_customer_data(encrypted_customer_data):
    encrypter = encrypt()
    decrypted_customer_data = encrypter.decode_string(encrypted_customer_data)

    if not decrypted_customer_data:
        return False, 'customer info is invalid'

    application_id, loan_refinancing_email_time = decrypted_customer_data.split('|')
    loan_refinancing_email_time = convert_string_date_to_date_object(
        loan_refinancing_email_time)

    if not loan_refinancing_email_time:
        return False, 'email time is invalid'

    is_customer_email_expired = \
        check_if_customer_still_eligible_for_loan_refinancing_registration(
            loan_refinancing_email_time)

    if not is_customer_email_expired:
        return False, 'email already expired!'

    user_data = get_user_data_from_app(application_id)

    if not user_data:
        return False, 'application id not found'

    return True, user_data


def get_main_unpaid_reasons():
    return LoanRefinancingMainReason.objects.filter(
        is_active=True
    )


def get_sub_unpaid_reasons(main_reasons):
    return LoanRefinancingSubReason.objects.filter(
        loan_refinancing_main_reason__in=main_reasons
    )


def construct_main_and_sub_reasons(main_reasons, sub_reasons):
    reason_dict = {}

    for main_reason in main_reasons:
        reason_dict[main_reason.reason] = []

    for sub_reason in sub_reasons:
        main_reason = sub_reason.loan_refinancing_main_reason.reason

        if main_reason in reason_dict:
            reason_dict[main_reason].append(sub_reason.reason)

    return reason_dict


def populate_main_and_sub_unpaid_reasons():
    main_reasons = get_main_unpaid_reasons()
    sub_reasons = get_sub_unpaid_reasons(main_reasons)
    reason_dict = construct_main_and_sub_reasons(
        main_reasons,
        sub_reasons
    )

    return reason_dict


def get_refinancing_status_display(loan_refinancing_request):
    status_date_str = loan_refinancing_request.get_status_ts().strftime('%d-%m-%Y')
    if loan_refinancing_request.status == \
            CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email:
        return 'Proactive Email Sent'
    if loan_refinancing_request.status == \
            CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit:
        return 'Proactive Form Viewed'
    if loan_refinancing_request.status == \
            CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer:
        return 'Offer Generated'
    if loan_refinancing_request.status == CovidRefinancingConst.STATUSES.offer_selected:
        return "%s Offer Selected, %s" % (
            loan_refinancing_request.product_type.upper(),
            status_date_str,
        )
    if loan_refinancing_request.status == CovidRefinancingConst.STATUSES.approved:
        return "%s Offer Approved, %s" % (
            loan_refinancing_request.product_type.upper(),
            status_date_str,
        )
    if loan_refinancing_request.status == CovidRefinancingConst.STATUSES.activated:
        return "%s Offer Activated, %s" % (
            loan_refinancing_request.product_type.upper(),
            status_date_str,
        )
    # handle campaign R1-3
    if loan_refinancing_request.status == CovidRefinancingConst.STATUSES.requested:
        return "Offer Requested"
