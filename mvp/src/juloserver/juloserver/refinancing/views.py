import json
import logging

from dashboard.constants import JuloUserRoles
from rest_framework.views import APIView
from datetime import datetime
from babel.dates import format_date
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.http.response import HttpResponseNotAllowed
from django.template import loader, RequestContext
from django.utils import timezone

from juloserver.account.models import Account
from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.services.account_payment_related import (
    get_unpaid_account_payment,
    update_checkout_experience_status_to_cancel
)

from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst

from juloserver.standardized_api_response.utils import (
    general_error_response,
    forbidden_error_response,
    success_response,
)

from juloserver.loan_refinancing.constants import (
    NEW_WAIVER_APPROVER_GROUPS,
    CovidRefinancingConst,
    ApprovalLayerConst,
)
from juloserver.loan_refinancing.models import (
    LoanRefinancingRequest,
    LoanRefinancingOffer,
    LoanRefinancingApproval,
    WaiverRequest,
    WaiverPaymentRequest,
    WaiverPaymentApproval,
)
from juloserver.loan_refinancing.services.loan_related import (
    recalculate_affordability,
    generate_recommended_tenure_extension_r1,
)
from juloserver.loan_refinancing.services.loan_related2 import get_not_allowed_products
from juloserver.loan_refinancing.services.refinancing_product_related import (
    get_refinancing_request_feature_setting_params,
    generate_unique_uuid,
    generate_short_url_for_proactive_webview,
    get_max_tenure_extension_r1,
    get_partially_paid_prerequisite_amount,
)
from juloserver.loan_refinancing.services.comms_channels import (
    send_loan_refinancing_request_approved_notification,
    send_loan_refinancing_request_offer_selected_notification,
)
from juloserver.loan_refinancing.services.offer_related import (
    generated_default_offers,
    construct_loan_refinancing_request,
    reorder_recommendation,
    get_proactive_offers,
    get_offer_constructor_function,
    pass_check_refinancing_max_cap_rule_by_account_id
)
from juloserver.loan_refinancing.utils import (
    convert_payment_format_to_plaform_for_agent,
    generate_status_and_tips_loan_refinancing_status,
)
from juloserver.loan_refinancing.tasks import (
    send_email_refinancing_offer_selected,
    send_sms_covid_refinancing_offer_selected,
    send_pn_covid_refinancing_offer_selected,
    send_slack_notification_for_refinancing_approver,
)

from juloserver.waiver.services.account_related import (
    get_data_for_agent_portal,
    get_account_ids_for_bucket_tree,
    can_account_get_refinancing,
    can_account_get_refinancing_bss,
    generate_approval_refinancing_data,
)

from juloserver.portal.object import julo_login_required

from .serializers import (
    GenerateReactiveJ1RefinancingSerializer,
    SimulationJ1RefinancingOfferSerializer,
    J1RefinancingRequestSerializer,
    J1ProactiveRefinancingSerializer,
    J1RefinancingRequestApprovalSerializer,
)
from juloserver.refinancing.services import (
    j1_validate_proactive_refinancing_data,
    store_j1_proactive_refinancing_data,
    generate_new_payment_structure,
    check_account_id_is_for_cohort_campaign,
    update_requested_status_refinancing_to_expired_for_cohort_campaign,
    process_loan_refinancing_approval,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.pii_vault.constants import PiiSource
from juloserver.minisquad.utils import collection_detokenize_sync_object_model
logger = logging.getLogger(__name__)


@julo_login_required
def collection_offer_j1(request):
    portal_type = request.GET.get('portal_type', 'agent_portal')
    template_name = 'refinancing/agent.html'
    account_id_list = []
    is_approver = False
    get_data_function = get_data_for_agent_portal

    user_groups = request.user.groups.values_list('name', flat=True)
    if any(approver_role in user_groups for approver_role in NEW_WAIVER_APPROVER_GROUPS):
        account_id_list = get_account_ids_for_bucket_tree(user_groups, is_refinancing=True)
        is_approver = True
        if portal_type == 'approver_portal':
            template_name = 'refinancing/approver.html'
            get_data_function = generate_approval_refinancing_data

    template = loader.get_template(template_name)
    data = {
        'ongoing_account_payments': [],
        'account_id': '',
        'show': False,
        'is_covid_risky': '',
        'bucket': '',
        'loan_refinancing_request_count': 0,
        'account_id_list': account_id_list,
        'is_approver': is_approver,
        'reasons': [],
        'predefined_message': '',
    }

    account_id = request.GET.get('account_id')
    is_bss_allow_program, message_bss_refinancing = can_account_get_refinancing_bss(
        account_id, refinancing_type="refinancing"
    )
    allow_refinancing_program, message = can_account_get_refinancing(account_id)
    if not allow_refinancing_program:
        data['predefined_message'] = message
    elif not is_bss_allow_program:
        data['predefined_message'] = message_bss_refinancing
    elif account_id:
        loan_refinancing_result = {}
        for rule in ['R1', 'R2', 'R3']:
            is_available, message = pass_check_refinancing_max_cap_rule_by_account_id(
                account_id,
                rule,
            )
            loan_refinancing_result[rule] = {
                'is_available': is_available,
                'message': message,
            }
        data['loan_refinancing_result'] = loan_refinancing_result

        data = get_data_function(data, account_id)

    context = RequestContext(request, data)
    return HttpResponse(template.render(context))


def ajax_generate_j1_reactive_refinancing_offer(request):
    from juloserver.moengage.tasks import \
        async_update_moengage_for_refinancing_request_status_change

    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse({
            "status": "failed",
            "message": "non authorized user",
        })

    data = request.POST.dict()
    serializer = GenerateReactiveJ1RefinancingSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    data = serializer.data
    loan_refinancing_request_qs = LoanRefinancingRequest.objects.filter(
        account_id=data['account_id'])
    loan_refinancing_request = loan_refinancing_request_qs.last()
    is_auto_populate = False if 'is_auto_populated' not in data else data['is_auto_populated']
    data['multiple_payment_ptp'] = {'is_multiple_ptp_payment': False}
    data['datepicker_start_date'] = '+0d'
    if is_auto_populate:
        return_data = {
            'status': 'success',
            'message': 'offers berhasil di autopopulate',
        }
        data = {'selected_refinancing_offers': ''}
        loan_refinancing_offers = LoanRefinancingOffer.objects.filter(
            loan_refinancing_request=loan_refinancing_request, is_latest=True) \
            .values('loan_duration', 'product_type')
        data['refinancing_offers'] = list(loan_refinancing_offers)

        if loan_refinancing_request.status in (
                CovidRefinancingConst.STATUSES.offer_selected,
                CovidRefinancingConst.STATUSES.approved,
        ):
            selected_refinancing_offers = LoanRefinancingOffer.objects.filter(
                loan_refinancing_request=loan_refinancing_request,
                is_latest=True, is_accepted=True
            ).values('product_type', 'loan_refinancing_request__loan_duration',
                     'loan_refinancing_request__comms_channel_1',
                     'loan_refinancing_request__comms_channel_2',
                     'loan_refinancing_request__comms_channel_3').last()
            data['selected_refinancing_offers'] = json.dumps(selected_refinancing_offers)
            data['multiple_payment_ptp'] = {'is_multiple_ptp_payment': False}
            waiver_request = None
            if selected_refinancing_offers['product_type'] in \
                    CovidRefinancingConst.waiver_products():
                waiver_request = WaiverRequest.objects.filter(
                    loan_refinancing_request=loan_refinancing_request
                ).last()
            if waiver_request:
                data['waiver_validity'] = waiver_request.waiver_validity_date
                data['first_waived_payment'] = waiver_request.first_waived_payment.id
                data['last_waived_payment'] = waiver_request.last_waived_payment.id
                data['requested_late_fee_waiver_percentage'] = \
                    waiver_request.requested_late_fee_waiver_percentage.replace('%', '')
                data['requested_late_fee_waiver_amount'] = \
                    waiver_request.requested_late_fee_waiver_amount
                data['requested_interest_waiver_percentage'] = \
                    waiver_request.requested_interest_waiver_percentage.replace('%', '')
                data['requested_interest_waiver_amount'] = \
                    waiver_request.requested_interest_waiver_amount
                data['requested_principal_waiver_percentage'] = \
                    waiver_request.requested_principal_waiver_percentage.replace('%', '')
                data['requested_late_fee_waiver_amount'] = \
                    waiver_request.requested_principal_waiver_amount
                data['ptp_amount'] = waiver_request.ptp_amount
                data['waived_payment_count'] = waiver_request.waived_payment_count
                waiver_payment_requests = []
                for payment in waiver_request.loan.payment_set.normal().order_by('id'):
                    waiver_payment_request = WaiverPaymentRequest.objects.filter(
                        waiver_request=waiver_request, payment=payment).first()
                    if waiver_payment_request:
                        waiver_payment_request_dict = {
                            'payment_id': waiver_payment_request.payment_id,
                        }
                        waiver_payment_request_dict['outstanding_late_fee_amount'] = \
                            waiver_payment_request.outstanding_late_fee_amount
                        waiver_payment_request_dict['outstanding_interest_amount'] = \
                            waiver_payment_request.outstanding_interest_amount
                        waiver_payment_request_dict['outstanding_principal_amount'] = \
                            waiver_payment_request.outstanding_principal_amount
                        waiver_payment_request_dict['total_outstanding_amount'] = \
                            waiver_payment_request.total_outstanding_amount
                        waiver_payment_request_dict['requested_late_fee_waiver_amount'] = \
                            waiver_payment_request.requested_late_fee_waiver_amount
                        waiver_payment_request_dict['requested_interest_waiver_amount'] = \
                            waiver_payment_request.requested_interest_waiver_amount
                        waiver_payment_request_dict['requested_principal_waiver_amount'] = \
                            waiver_payment_request.requested_principal_waiver_amount
                        waiver_payment_request_dict['total_requested_waiver_amount'] = \
                            waiver_payment_request.total_requested_waiver_amount
                        waiver_payment_request_dict['remaining_late_fee_amount'] = \
                            waiver_payment_request.remaining_late_fee_amount
                        waiver_payment_request_dict['remaining_interest_amount'] = \
                            waiver_payment_request.remaining_interest_amount
                        waiver_payment_request_dict['remaining_principal_amount'] = \
                            waiver_payment_request.remaining_principal_amount
                        waiver_payment_request_dict['total_remaining_amount'] = \
                            waiver_payment_request.total_remaining_amount
                        if waiver_payment_request_dict['total_remaining_amount'] > 0:
                            waiver_payment_request_dict['is_paid_off_after_ptp'] = 'Y'
                        waiver_payment_requests.append(waiver_payment_request_dict)
                    else:
                        waiver_payment_requests.append(None)
                data['waiver_payment_request'] = waiver_payment_requests
                today_date = timezone.localtime(timezone.now()).date()
                date_diff = waiver_request.cdate.date() - today_date
                data['datepicker_start_date'] = '%sd' % date_diff.days
                multiple_payment_ptp = waiver_request.ordered_multiple_payment_ptp()
                multiple_payment_ptp_data = []
                for payment_ptp in multiple_payment_ptp:
                    payment_ptp_data = {}
                    payment_ptp_data['promised_payment_date'] = format_date(
                        payment_ptp.promised_payment_date,
                        'yyyy-MM-dd', locale='id_ID'
                    )
                    payment_ptp_data['sequence'] = payment_ptp.sequence
                    payment_ptp_data['promised_payment_amount'] = \
                        payment_ptp.promised_payment_amount
                    multiple_payment_ptp_data.append(payment_ptp_data)

                data['multiple_payment_ptp'] = {
                    'is_multiple_ptp_payment': waiver_request.is_multiple_ptp_payment,
                    'number_of_multiple_ptp_payment': waiver_request.number_of_multiple_ptp_payment,
                    'multiple_payment_ptp_data': multiple_payment_ptp_data,
                }

                waiver_approval = waiver_request.waiverapproval_set.last()
                if waiver_approval:
                    data['waiver_validity'] = waiver_approval.approved_waiver_validity_date
                    data['first_waived_payment'] = \
                        waiver_approval.waiver_payment_approval.first().id
                    data['last_waived_payment'] = waiver_approval.waiver_payment_approval.last().id
                    data['requested_late_fee_waiver_percentage'] = "{}%".format(
                        waiver_approval.approved_late_fee_waiver_percentage * 100)
                    data['requested_late_fee_waiver_amount'] = \
                        waiver_approval.get_total_approved_waiver_amount(
                            "approved_late_fee_waiver_amount")
                    data['requested_interest_waiver_percentage'] = "{}%".format(
                        waiver_approval.approved_interest_waiver_percentage * 100)
                    data['requested_interest_waiver_amount'] = \
                        waiver_approval.get_total_approved_waiver_amount(
                            "approved_interest_waiver_amount")
                    data['requested_principal_waiver_percentage'] = "{}%".format(
                        waiver_approval.approved_principal_waiver_percentage * 100)
                    data['requested_late_fee_waiver_amount'] = \
                        waiver_approval.get_total_approved_waiver_amount(
                            "approved_principal_waiver_amount")
                    data['ptp_amount'] = waiver_approval.need_to_pay
                    data['waived_payment_count'] = waiver_approval.waiver_payment_approval.count()
                    waiver_payment_approvals = []
                    for payment in waiver_request.loan.payment_set.normal().order_by('id'):
                        waiver_payment_approval = WaiverPaymentApproval.objects.filter(
                            waiver_approval=waiver_approval, payment=payment).first()
                        if waiver_payment_approval:
                            waiver_payment_approval_dict = {
                                'payment_id': waiver_payment_approval.payment_id,
                            }
                            waiver_payment_approval_dict['outstanding_late_fee_amount'] = \
                                waiver_payment_approval.outstanding_late_fee_amount
                            waiver_payment_approval_dict['outstanding_interest_amount'] = \
                                waiver_payment_approval.outstanding_interest_amount
                            waiver_payment_approval_dict['outstanding_principal_amount'] = \
                                waiver_payment_approval.outstanding_principal_amount
                            waiver_payment_approval_dict['total_outstanding_amount'] = \
                                waiver_payment_approval.total_outstanding_amount
                            waiver_payment_approval_dict['requested_late_fee_waiver_amount'] = \
                                waiver_payment_approval.approved_late_fee_waiver_amount
                            waiver_payment_approval_dict['requested_interest_waiver_amount'] = \
                                waiver_payment_approval.approved_interest_waiver_amount
                            waiver_payment_approval_dict['requested_principal_waiver_amount'] = \
                                waiver_payment_approval.approved_principal_waiver_amount
                            waiver_payment_approval_dict['total_requested_waiver_amount'] = \
                                waiver_payment_approval.total_approved_waiver_amount
                            waiver_payment_approval_dict['remaining_late_fee_amount'] = \
                                waiver_payment_approval.remaining_late_fee_amount
                            waiver_payment_approval_dict['remaining_interest_amount'] = \
                                waiver_payment_approval.remaining_interest_amount
                            waiver_payment_approval_dict['remaining_principal_amount'] = \
                                waiver_payment_approval.remaining_principal_amount
                            waiver_payment_approval_dict['total_remaining_amount'] = \
                                waiver_payment_approval.total_remaining_amount
                            if waiver_payment_approval_dict['total_remaining_amount'] > 0:
                                waiver_payment_approval_dict['is_paid_off_after_ptp'] = 'Y'
                            waiver_payment_approvals.append(waiver_payment_approval_dict)
                        else:
                            waiver_payment_approvals.append(None)
                    data['waiver_payment_request'] = waiver_payment_approvals

        recommen_extension = generate_recommended_tenure_extension_r1(
            loan_refinancing_request
        )
        recommended_extension = 0
        if recommen_extension:
            recommended_extension = recommen_extension

        max_extension = get_max_tenure_extension_r1(loan_refinancing_request)
        data['max_tenure_extension'] = max_extension
        data['recommended_extension'] = recommended_extension
        return_data['data'] = data
        return JsonResponse(return_data)

    if loan_refinancing_request and \
        loan_refinancing_request.status == \
            CovidRefinancingConst.STATUSES.approved:
        return JsonResponse({
            'status': 'failed',
            'message': 'Ada program refinancing yang sedang berjalan'
        })

    if loan_refinancing_request and \
        loan_refinancing_request.status in \
            CovidRefinancingConst.NEED_VALIDATE_FOR_MULTIPLE_REQUEST_STATUSES:
        not_allowed_products = get_not_allowed_products(loan_refinancing_request_qs)
        if data['recommendation_offer_products']:
            for product in not_allowed_products:
                data['recommendation_offer_products'] = \
                    data['recommendation_offer_products'].replace(product, '')
        if loan_refinancing_request.status \
                in CovidRefinancingConst.MULTI_OFFER_CHANGE_TO_EXPIRED_STATUSES:
            loan_refinancing_request.update_safely(status=CovidRefinancingConst.STATUSES.expired)
            today_date = timezone.localtime(timezone.now()).date()
            waiver_request = WaiverRequest.objects.filter(
                account=loan_refinancing_request.account, is_approved__isnull=True,
                is_automated=False, waiver_validity_date__gte=today_date
            ).order_by('cdate').last()
            if waiver_request:
                waiver_request.update_safely(
                    is_approved=False,
                    refinancing_status=CovidRefinancingConst.STATUSES.expired
                )

    feature_params = get_refinancing_request_feature_setting_params()
    if not feature_params:
        return JsonResponse({
            'status': 'failed',
            'message': 'Feature setting status tidak aktif'
        })
    loan_refinancing_offers = []
    max_extension = 0
    recommended_extension = 0
    # check account id is cohort campaign
    campaign_request = check_account_id_is_for_cohort_campaign(data['account_id'])
    try:
        with transaction.atomic():
            loan_refinancing_request_dict = construct_loan_refinancing_request(
                data, feature_params, initial=True, is_j1=True)
            loan_refinancing_request_dict['status'] = CovidRefinancingConst.STATUSES.offer_generated
            loan_refinancing_request_dict['request_date'] = timezone.localtime(
                timezone.now()).date()
            loan_refinancing_request_dict['form_submitted_ts'] = timezone.localtime(timezone.now())
            loan_refinancing_request_dict['channel'] = CovidRefinancingConst.CHANNELS.reactive

            old_status = None
            if loan_refinancing_request and loan_refinancing_request.status in \
                    list(CovidRefinancingConst.NEW_PROACTIVE_STATUSES.__dict__.values()):
                old_status = loan_refinancing_request.status
                loan_refinancing_request.update_safely(**loan_refinancing_request_dict)
            else:
                loan_refinancing_request = LoanRefinancingRequest.objects.\
                    create(**loan_refinancing_request_dict)
                async_update_moengage_for_refinancing_request_status_change.apply_async(
                    (loan_refinancing_request.id,),
                    countdown=settings.DELAY_FOR_MOENGAGE_API_CALL
                )
            # to update loan refinancing request from blast csv to expired
            if campaign_request and campaign_request.loan_refinancing_request.\
                    status == CovidRefinancingConst.STATUSES.requested:
                update_requested_status_refinancing_to_expired_for_cohort_campaign(
                    campaign_request, loan_refinancing_request)
            if not loan_refinancing_request.uuid:
                uuid = generate_unique_uuid()
                url = generate_short_url_for_proactive_webview(uuid)
                loan_refinancing_request.update_safely(uuid=uuid, url=url)
            is_offer_generated = generated_default_offers(
                loan_refinancing_request, data['recommendation_offer_products'])
            loan_refinancing_offers = []
            if is_offer_generated:
                loan_refinancing_offers = LoanRefinancingOffer.objects.filter(
                    loan_refinancing_request=loan_refinancing_request, is_latest=True)\
                    .values('loan_duration', 'product_type')
            if old_status in CovidRefinancingConst\
                    .REACTIVE_OFFER_STATUS_AVAILABLE_FOR_GENERATE_OFFER:
                loan_refinancing_request.refresh_from_db()
                check_refinancing_offers = get_proactive_offers(loan_refinancing_request)
                limit = 2
                if check_refinancing_offers.count() != 2:
                    limit = limit - check_refinancing_offers.count()
                    loan_ref_offers = LoanRefinancingOffer.objects.filter(
                        loan_refinancing_request=loan_refinancing_request,
                        is_latest=False, recommendation_order__isnull=False,
                        product_type__in=CovidRefinancingConst.OFFER_GENERATED_AVAILABLE_PRODUCT)\
                        .order_by('id')

                    for loan_ref_offer in loan_ref_offers:
                        if limit == 0:
                            break
                        current_offer = loan_refinancing_request.loanrefinancingoffer_set.filter(
                            loan_refinancing_request=loan_refinancing_request, is_latest=True,
                            product_type=loan_ref_offer.product_type).exists()

                        if not current_offer:
                            loan_ref_offer.update_safely(is_latest=True)
                            limit = limit - 1

                    reorder_recommendation(loan_refinancing_request)
            recommen_extension = generate_recommended_tenure_extension_r1(
                loan_refinancing_request
            )
            if recommen_extension:
                recommended_extension = recommen_extension
            max_extension = get_max_tenure_extension_r1(loan_refinancing_request)

            # update status checkout request when create R1 - R3 (offer generated status)
            update_checkout_experience_status_to_cancel(data['account_id'])

    except Exception as e:
        get_julo_sentry_client().captureException()
        return JsonResponse({
            "status": "failed",
            "message": str(e)
        })
    return JsonResponse({
        'status': 'success',
        'data': {
            'refinancing_offers': list(loan_refinancing_offers),
            'max_tenure_extension': max_extension,
            'recommended_extension': recommended_extension,
            'current_loan_refinancing_request_status':
                generate_status_and_tips_loan_refinancing_status(
                    loan_refinancing_req=loan_refinancing_request,
                    data={})
        },
        'message': 'offers berhasil di generate'
    })


def ajax_simulation_j1_refinancing_calculate_offer(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse({
            "status": "failed",
            "message": "non authorized user",
        })
    data = request.POST.dict()
    ser = SimulationJ1RefinancingOfferSerializer(data=data)
    ser.is_valid(raise_exception=True)
    active_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.COVID_REFINANCING,
        is_active=True).last()
    if not active_feature:
        return general_error_response(
            'Feature setting status tidak aktif',
        )
    account_id = data['account_id']
    selected_offer_recommendation = data['selected_offer_recommendation']
    account = Account.objects.get_or_none(pk=account_id)
    # validation max cap rule
    is_passed, err_msg = pass_check_refinancing_max_cap_rule_by_account_id(
        account_id, selected_offer_recommendation)
    if not is_passed:
        delete_refinancing = LoanRefinancingRequest.objects.filter(
            account_id=account_id,
            status=CovidRefinancingConst.STATUSES.offer_generated
        ).last()
        if delete_refinancing:
            LoanRefinancingOffer.objects.filter(
                loan_refinancing_request=delete_refinancing
            ).delete()
            delete_refinancing.delete()
        return JsonResponse({
            'status': 'max cap rule validation',
            'message': err_msg
        })

    unpaid_payments = get_unpaid_account_payment(account.id)
    loan = account.loan_set.last()
    new_affordability = recalculate_affordability(loan, data, account)
    feature_params = active_feature.parameters
    max_extension = 3 if len(unpaid_payments) >= 6 \
        else feature_params['tenure_extension_rule']['J1_%s' % len(unpaid_payments)]
    if selected_offer_recommendation.upper() != CovidRefinancingConst.PRODUCTS.r1:
        extension = int(data['tenure_extension']) if int(
            data['tenure_extension']) < max_extension else max_extension
    else:
        extension = int(data['tenure_extension'])
    loan_refinancing_request = LoanRefinancingRequest(
        cdate=timezone.localtime(timezone.now()),
        account=account,
        loan_duration=extension,
        affordability_value=new_affordability,
        product_type=data['selected_offer_recommendation'].upper(),
        expire_in_days=feature_params['email_expire_in_days'],
        new_income=int(data["new_income"].replace(',', '')),
        new_expense=int(data["new_expense"].replace(',', '')),
    )
    data_to_return = []
    chosen_loan_duration = None
    count_unpaid_account_payments = 0
    if selected_offer_recommendation == 'r1':
        max_extension = get_max_tenure_extension_r1(loan_refinancing_request)
        new_loan_extension = max_extension + len(unpaid_payments)
        loan_refinancing_request.loan_duration = new_loan_extension
        index = unpaid_payments.count() + extension
        index = index if index < new_loan_extension else new_loan_extension
        loan_refinancing_request.request_date = timezone.localtime(
            loan_refinancing_request.cdate).date()
        chosen_loan_duration = index
    elif selected_offer_recommendation in ('r2', 'r3'):
        count_unpaid_account_payments = len(unpaid_payments)

    _, new_account_payments = generate_new_payment_structure(
        account, loan_refinancing_request,
        chosen_loan_duration=chosen_loan_duration,
        count_unpaid_account_payments=count_unpaid_account_payments)
    if selected_offer_recommendation == 'r3':
        new_account_payments = new_account_payments['payments']
    data_to_return = convert_payment_format_to_plaform_for_agent(
        new_account_payments, is_object=False)

    return JsonResponse({
        'status': 'success',
        'data': data_to_return
    })


def ajax_submit_j1_refinancing_request(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse({
            "status": "failed",
            "message": "non authorized user",
        })

    data = json.loads(request.body)
    serializer = J1RefinancingRequestSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    data = serializer.data
    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        account_id=data['account_id']).last()
    if not loan_refinancing_request:
        return JsonResponse({
            'status': False,
            'message': "loan refinancing request tidak ditemukan"
        })
    account = loan_refinancing_request.account
    app = account.last_application

    app_detokenized = collection_detokenize_sync_object_model(
        PiiSource.APPLICATION,
        app,
        app.customer.customer_xid,
        ['fullname'],
    )

    request_date = datetime.strftime(loan_refinancing_request.cdate, '%d-%m-%Y')
    if loan_refinancing_request.status in (
            CovidRefinancingConst.STATUSES.offer_selected,
            CovidRefinancingConst.STATUSES.approved):
        if get_partially_paid_prerequisite_amount(loan=None, account=account) > 0:
            message = (
                "<b>%s (ID: %s)</b> sudah mengajukan program keringanan <b>%s</b> "
                "pada tanggal <b>%s</b> dan belum melakukan pembayarannya secara penuh."
                % (app_detokenized.fullname, account.id, data['selected_product'], request_date)
            )
            return JsonResponse({'status': False, 'message': message})
        message = (
            "<b>%s (ID: %s)</b> sudah mengajukan program keringanan <b>%s</b> pada tanggal "
            "<b>%s</b> dan sudah melakukan konfirmasi atau sudah memilih detail program "
            "tersebut." % (app_detokenized.fullname, app.id, data['selected_product'], request_date)
        )
        return JsonResponse({'status': False, 'message': message})
    if loan_refinancing_request.status == CovidRefinancingConst.STATUSES.activated:
        message = (
            "<b>%s (ID: %s)</b> sudah mengajukan program keringanan <b>%s</b> pada tanggal "
            "<b>%s</b> dan program telah aktif"
            % (app_detokenized.fullname, app.id, data['selected_product'], request_date)
        )
        return JsonResponse({'status': False, 'message': message})

    feature_params = get_refinancing_request_feature_setting_params()
    if not feature_params:
        return JsonResponse({
            'status': 'failed',
            'message': 'Feature setting status tidak aktif'
        })
    with transaction.atomic():
        loan_refinancing_request_dict = construct_loan_refinancing_request(
            data, feature_params, initial=False, is_j1=True)
        is_accepted = True

        for num, comms_channel in enumerate(data['comms_channels'].split(','), start=1):
            loan_refinancing_request_dict['comms_channel_%s' % num] = comms_channel
        loan_refinancing_request_dict['channel'] = CovidRefinancingConst.CHANNELS.reactive

        loan_refinancing_request.update_safely(**loan_refinancing_request_dict)
        loan_refinancing_request.refresh_from_db()

        existing_offer = LoanRefinancingOffer.objects.filter(
            loan_refinancing_request=loan_refinancing_request,
            product_type=data['selected_product'],
            is_latest=True
        ).last()

        if not existing_offer or existing_offer.loan_duration != int(data['tenure_extension']):
            payment = AccountPayment.objects.filter(
                account=loan_refinancing_request.account
            ).not_paid_active().order_by('due_date').first()
            offer_constuctor_func = get_offer_constructor_function(data['selected_product'])
            selected_offer_dict = offer_constuctor_func(
                loan_refinancing_request, payment.bucket_number, default_extension=False)
            selected_offer_dict['generated_by'] = request.user
            selected_offer_dict.pop('recommendation_order', None)
            if existing_offer and not existing_offer.generated_by:
                existing_offer.update_safely(is_latest=False)

            # override existing offer by creating new one
            existing_offer = LoanRefinancingOffer.objects.create(**selected_offer_dict)

        # update_campaign_request_dict = dict()
        if data['is_customer_confirmed']:
            loan_refinancing_request_dict = dict(
                status=CovidRefinancingConst.STATUSES.offer_selected,
                prerequisite_amount=existing_offer.prerequisite_amount,
                total_latefee_discount=existing_offer.total_latefee_discount,
                source=data['agent_group'],
            )
            if data.get('agent_detail'):
                loan_refinancing_request_dict.update(source_detail=json.loads(data['agent_detail']))

            update_existing_offer_dict = dict(
                selected_by=request.user,
                is_accepted=is_accepted,
                is_latest=True,
                offer_accepted_ts=timezone.localtime(timezone.now())
            )
        else:
            loan_refinancing_request_dict = dict(
                product_type=None,
                loan_duration=0
            )
            update_existing_offer_dict = dict(
                is_latest=True,
            )
        loan_refinancing_request_dict['form_submitted_ts'] = timezone.localtime(timezone.now())

        if not loan_refinancing_request.uuid:
            uuid = generate_unique_uuid()
            loan_refinancing_request_dict['uuid'] = uuid
            loan_refinancing_request_dict['url'] = generate_short_url_for_proactive_webview(uuid)

        loan_refinancing_request.update_safely(**loan_refinancing_request_dict)
        existing_offer.update_safely(**update_existing_offer_dict)

        if data['selected_product'] == CovidRefinancingConst.PRODUCTS.r1:
            proactive_existing_offer = LoanRefinancingOffer.objects.filter(
                loan_refinancing_request=loan_refinancing_request,
                product_type=existing_offer.product_type,
                loan_duration=existing_offer.loan_duration,
                is_proactive_offer=True
            ).last()
            if proactive_existing_offer:
                proactive_existing_offer.update_safely(recommendation_order=0, is_latest=True)
            else:
                existing_offer.refresh_from_db()
                proactive_r1_offer = dict(
                    loan_refinancing_request=loan_refinancing_request,
                    product_type=existing_offer.product_type,
                    loan_duration=existing_offer.loan_duration,
                    prerequisite_amount=existing_offer.prerequisite_amount,
                    total_latefee_discount=existing_offer.total_latefee_discount,
                    validity_in_days=existing_offer.validity_in_days,
                    generated_by_id=existing_offer.generated_by_id,
                    recommendation_order=0,
                    is_proactive_offer=True,
                    is_latest=True,
                )
                LoanRefinancingOffer.objects.create(**proactive_r1_offer)
            reorder_recommendation(loan_refinancing_request)

        approval = LoanRefinancingApproval.objects.create(
            loan_refinancing_request=loan_refinancing_request,
            approval_type=ApprovalLayerConst.TL,
            bucket_name=data['bucket_name'],
            requestor_reason=data['reason'],
            requestor_notes=data['notes'],
            extra_data=data['extra_data'],
            requestor=request.user,
        )
        send_slack_notification_for_refinancing_approver.delay(approval.id)

        if data['is_customer_confirmed'] and loan_refinancing_request.product_type:
            comms_list = loan_refinancing_request.comms_channel_list()
            if loan_refinancing_request.channel == CovidRefinancingConst.CHANNELS.reactive:
                if CovidRefinancingConst.COMMS_CHANNELS.email in comms_list:
                    send_email_refinancing_offer_selected.delay(loan_refinancing_request.id)
                if CovidRefinancingConst.COMMS_CHANNELS.pn in comms_list:
                    send_pn_covid_refinancing_offer_selected.delay(loan_refinancing_request.id)
                if CovidRefinancingConst.COMMS_CHANNELS.sms in comms_list:
                    send_sms_covid_refinancing_offer_selected.delay(loan_refinancing_request.id)

    success_message = (
        "Permohonan Refinancing <b>%s</b> untuk <b>%s (ID: %s)</b> "
        "telah dilanjutkan ke proses berikutnya. JULO akan mengirimkan email/PN/SMS"
        " secara otomatis kepada customer tentang detil program ini. "
        "Mohon ingatkan customer untuk membuka pesan yang JULO kirimkan"
        "." % (data['selected_product'], app_detokenized.fullname, app.id)
    )
    return JsonResponse({'status': True, 'message': success_message})


def ajax_retrigger_j1_comms(request):
    # this ajax retrigger just only can trigger if the status is offer_selected and approved
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse({
            "status": "failed",
            "message": "non authorized user",
        })

    data = request.POST.dict()
    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        account_id=data['account_id']).last()
    if not loan_refinancing_request:
        return JsonResponse({
            'status': 'failed',
            'message': "loan refinancing request not exist"
        })

    today = timezone.localtime(timezone.now()).date()
    if loan_refinancing_request.last_retrigger_comms is not None \
            and today == loan_refinancing_request.last_retrigger_comms:
        return JsonResponse({
            'status': 'failed',
            'message': "hanya bisa retrigger 1x satu hari"
        })

    refinancing_status = loan_refinancing_request.status
    if refinancing_status not in (
            CovidRefinancingConst.STATUSES.offer_selected, CovidRefinancingConst.STATUSES.approved
    ):
        return JsonResponse({
            'status': 'failed',
            'message': "status refinancing ini {}, yang di ijinkan hanya status {} dan {}".format(
                refinancing_status, CovidRefinancingConst.STATUSES.offer_selected,
                CovidRefinancingConst.STATUSES.approved
            )
        })
    comms_channel_1 = data['comms_channel_1'] if data['comms_channel_1'] else None
    comms_channel_2 = data['comms_channel_2'] if data['comms_channel_2'] else None
    comms_channel_3 = data['comms_channel_3'] if data['comms_channel_3'] else None
    with transaction.atomic():
        loan_refinancing_request.update_safely(
            last_retrigger_comms=today,
            comms_channel_1=comms_channel_1,
            comms_channel_2=comms_channel_2,
            comms_channel_3=comms_channel_3,
        )
        loan_refinancing_request.refresh_from_db()
        if refinancing_status == CovidRefinancingConst.STATUSES.offer_selected:
            send_loan_refinancing_request_offer_selected_notification(loan_refinancing_request)
        elif refinancing_status == CovidRefinancingConst.STATUSES.approved:
            send_loan_refinancing_request_approved_notification(loan_refinancing_request)

    return JsonResponse({
        'status': True,
        'message': 'Berhasil trigger ulang notification',
        'comms_channel_1': comms_channel_1,
        'comms_channel_2': comms_channel_2,
        'comms_channel_3': comms_channel_3,
    })


class J1ProactiveRefinancing(APIView):
    serializer_class = J1ProactiveRefinancingSerializer

    def post(self, request):
        if JuloUserRoles.PRODUCT_MANAGER not in request.user.groups.values_list('name', flat=True):
            return forbidden_error_response('User harus mempunyai role sebagai Product Manager',)

        serializer = self.serializer_class(data=request.data)
        active_feature = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.COVID_REFINANCING, is_active=True,
        ).last()

        if not active_feature:
            return general_error_response('Feature setting status tidak aktif',)

        serializer.is_valid(raise_exception=True)
        data_reader = serializer.validated_data['csv_file']
        is_valid_, data = j1_validate_proactive_refinancing_data(data_reader)

        if not is_valid_:
            message = 'sebagian data tidak valid harap perbaiki terlebih dahulu'
            if 'invalid_lenders' in data and len(data['invalid_lenders']) > 0:
                message = (
                    "Terdapat data pinjaman dari channeling lender,",
                    " harap perbaiki terlebih dahulu"
                )
            return general_error_response(message, data=data)

        num_of_rows = store_j1_proactive_refinancing_data(
            data['valid_data'], active_feature.parameters
        )
        return success_response({'number_of_row_processed': num_of_rows})


def ajax_approve_j1_refinancing_request(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "message": "non authorized user",
            }
        )

    data = json.loads(request.body)
    serializer = J1RefinancingRequestApprovalSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    data = serializer.data
    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        id=data['loan_refinancing_request_id'],
        account_id=data['account_id'],
    ).last()
    if not loan_refinancing_request:
        return JsonResponse(
            {
                "status": "failed",
                "message": "loan_refinancing_request not found",
            }
        )
    loan_refinancing_approval = loan_refinancing_request.loanrefinancingapproval_set.filter(
        id=data['loan_refinancing_approval_id'],
        loan_refinancing_request=loan_refinancing_request,
        is_accepted__isnull=True,
    ).last()
    if not loan_refinancing_approval:
        return JsonResponse(
            {
                "status": "failed",
                "message": "loan_refinancing_approval not found",
            }
        )

    required_group, next_approval = loan_refinancing_approval.approver_group_name()
    user_groups = request.user.groups.values_list('name', flat=True)
    if not required_group or required_group not in user_groups:
        return JsonResponse(
            {
                "status": "failed",
                "message": "user is not allowed to this approval",
            }
        )

    try:
        data.update(
            user=request.user,
            loan_refinancing_request=loan_refinancing_request,
            loan_refinancing_approval=loan_refinancing_approval,
        )
        msg = process_loan_refinancing_approval(data, next_approval)
    except Exception as e:
        get_julo_sentry_client().captureException()
        return JsonResponse(
            {
                "status": "failed",
                "message": str(e),
            }
        )

    return JsonResponse(
        {
            'status': 'success',
            'message': msg,
        }
    )
