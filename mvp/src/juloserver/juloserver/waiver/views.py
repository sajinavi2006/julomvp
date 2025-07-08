from builtins import str
from builtins import range
import json

from juloserver.portal.object import (
    julo_login_required,
    julo_login_required_multigroup,
)
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.template import loader, RequestContext
from django.http import JsonResponse, HttpResponse
from django.http.response import HttpResponseNotAllowed
from django.forms.models import model_to_dict
from rest_framework.serializers import ValidationError

from babel.dates import format_date
from datetime import datetime, timedelta

from juloserver.account_payment.services.payment_flow import get_and_update_latest_loan_status
from .services.account_related import (
    get_data_for_agent_portal,
    get_data_for_approver_portal,
    get_account_ids_for_bucket_tree,
    can_account_get_refinancing,
    can_account_get_refinancing_bss,
)
from .services.offer_related import generated_j1_default_offers
from .services.waiver_related import (
    get_j1_waiver_recommendation,
    get_partial_account_payments_by_program,
    j1_paid_waiver,
    force_expired_j1_waiver_temp,
    manual_expire_refinancing_program,
    generate_and_calculate_waiver_request_reactive,
    generate_and_calculate_waiver_approval_reactive,
)
from .serializers import (
    GenerateJ1WaiverRefinancingSerializer,
    J1WaiverRequestSerializer,
    J1WaiverApprovalSerializer,
)
from .models import (
    WaiverAccountPaymentRequest,
    WaiverAccountPaymentApproval,
    MultiplePaymentPTP,
)
from .tasks import send_slack_notification_for_j1_waiver_approver

from juloserver.refinancing.services import J1LoanRefinancing

from juloserver.loan_refinancing.constants import (
    CovidRefinancingConst,
    NEW_WAIVER_APPROVER_GROUPS,
    WaiverApprovalDecisions,
    WAIVER_FRAUD_APPROVER_GROUP,
)
from juloserver.loan_refinancing.services.refinancing_product_related import (
    get_refinancing_request_feature_setting_params,
    generate_short_url_for_proactive_webview,
    generate_unique_uuid,
)
from juloserver.loan_refinancing.services.offer_related import (
    get_proactive_offers,
    get_existing_accepted_offer,
    reorder_recommendation,
    pass_check_refinancing_max_cap_rule_by_account_id
)
from juloserver.loan_refinancing.services.comms_channels import (
    send_loan_refinancing_request_approved_notification,
)
from juloserver.loan_refinancing.tasks import (
    send_email_refinancing_offer_selected,
    send_sms_covid_refinancing_offer_selected,
    send_pn_covid_refinancing_offer_selected,
)
from juloserver.loan_refinancing.models import (
    LoanRefinancingRequest,
    LoanRefinancingOffer,
    WaiverRequest,
    WaiverPaymentRequest,
    WaiverApproval,
    WaiverPaymentApproval,
    WaiverRecommendation,
)
from juloserver.loan_refinancing.utils import (
    generate_status_and_tips_loan_refinancing_status,
    get_waiver_is_need_approvals,
)
from juloserver.account.models import (
    Account,
    AccountTransaction,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.models import (
    FeatureSetting,
    Application,
    Customer,
)
from juloserver.julo.constants import FeatureNameConst, PaymentEventConst
from juloserver.payback.models import (
    WaiverTemp,
    WaiverPaymentTemp,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.account_payment.services.account_payment_related import (
    update_checkout_experience_status_to_cancel,
)
from juloserver.refinancing.services import (
    check_account_id_is_for_cohort_campaign,
    update_requested_status_refinancing_to_expired_for_cohort_campaign,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.minisquad.utils import collection_detokenize_sync_object_model
from juloserver.minisquad.services import get_similar_field_collection_agents


class MaxCapRuleException(Exception):
    pass


@julo_login_required
def collection_offer_j1(request):
    portal_type = request.GET.get('portal_type', 'agent_portal')
    template_name = 'waiver/collection_offer_j1_agent.html'
    account_id_list = []
    is_approver = False
    get_data_function = get_data_for_agent_portal

    user_groups = request.user.groups.values_list('name', flat=True)
    if any(approver_role in user_groups for approver_role in NEW_WAIVER_APPROVER_GROUPS):
        account_id_list = get_account_ids_for_bucket_tree(user_groups)
        is_approver = True

        if portal_type == 'approver_portal':
            template_name = 'waiver/collection_offer_j1_approver.html'
            get_data_function = get_data_for_approver_portal

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
        'is_show_r4_only': False,
    }

    account_id = request.GET.get('account_id')
    allow_refinancing_program, message_refinancing = can_account_get_refinancing(account_id)
    data['allow_bss_r4_program'], message_bss_refinancing = can_account_get_refinancing_bss(
        account_id
    )
    data['is_show_r4_only'] = (
        data.get('allow_bss_r4_program') and message_bss_refinancing == "Only eligible for R4"
    )
    if not allow_refinancing_program:
        data['predefined_message'] = message_refinancing
    elif (
        not data['allow_bss_r4_program']
        and message_bss_refinancing == 'Not eligible for refinancing BSS'
    ):
        data['predefined_message'] = message_bss_refinancing
    elif account_id and portal_type == 'approver_portal':
        data = get_data_function(data, account_id, user_groups)
    elif account_id and portal_type != 'approver_portal':
        data = get_data_function(data, account_id)

    if account_id:
        loan_refinancing_result = {}
        rules = ['R4', 'R5', 'R6']
        if data['is_show_r4_only']:
            rules = ['R4']
        for rule in rules:
            is_available, message = pass_check_refinancing_max_cap_rule_by_account_id(
                account_id, rule)
            loan_refinancing_result[rule] = {
                'is_available': is_available,
                'message': message,
            }
        data['loan_refinancing_result'] = loan_refinancing_result

    if account_id and portal_type == 'approver_portal':
        reason_dict = {
            'products': ['Fraud', 'Pass Away'],
            'reasons': [
                'Desk Collection Internal',
                'Field Collection Internal',
                'Desk Collection Vendor',
                'Field Collection Vendor',
                'Special Campaign OPS',
                'Special Campaign COLL'
            ]
        }
        reason_feature = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.WAIVER_APPROVAL_REASON,
            is_active=True,
        ).last()
        if reason_feature:
            reason_dict = reason_feature.parameters or reason_dict
        if data.get('program_name', ''):
            if data.get('program_name').lower() == 'general paid waiver':
                if data.get('original_program_name', ''):
                    product = [data.get('original_program_name').upper()]
                else:
                    product = ['R4', 'R5', 'R6']
            else:
                product = [data.get('program_name').upper()]
            reason_dict['products'] = product + reason_dict.get('products')
        data['approval_reason'] = reason_dict
    context = RequestContext(request, data)
    return HttpResponse(template.render(context))


def ajax_get_j1_exisiting_offers(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "message": "non authorized user",
            }
        )
    data = request.POST.dict()
    refinancing_req_qs = LoanRefinancingRequest.objects.filter(account_id=data['account_id'])
    existing_offers_list = get_existing_accepted_offer(refinancing_req_qs)

    return JsonResponse(
        {'status': 'success', 'response': {'existing_offers': existing_offers_list}}
    )


def ajax_generate_j1_waiver_refinancing_offer(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "message": "non authorized user",
            }
        )

    feature_params = get_refinancing_request_feature_setting_params()
    if not feature_params:
        return JsonResponse({'status': 'failed', 'message': 'Feature setting status tidak aktif'})

    data = request.POST.dict()
    serializer = GenerateJ1WaiverRefinancingSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    data = serializer.data

    loan_refinancing_request_qs = LoanRefinancingRequest.objects.filter(
        account_id=data['account_id']
    )
    loan_refinancing_request = loan_refinancing_request_qs.last()
    is_auto_populate = False if 'is_auto_populated' not in data else data['is_auto_populated']
    if is_auto_populate:
        return_data = {
            'status': 'success',
            'message': 'offers berhasil di autopopulate',
        }
        loan_refinancing_offers = LoanRefinancingOffer.objects.filter(
            loan_refinancing_request=loan_refinancing_request, is_latest=True
        ).values('loan_duration', 'product_type')
        data['refinancing_offers'] = list(loan_refinancing_offers)

        if loan_refinancing_request.status in (
            CovidRefinancingConst.STATUSES.offer_selected,
            CovidRefinancingConst.STATUSES.approved,
        ):
            selected_refinancing_offers = (
                LoanRefinancingOffer.objects.filter(
                    loan_refinancing_request=loan_refinancing_request,
                    is_latest=True,
                    is_accepted=True,
                )
                .values(
                    'product_type',
                    'loan_refinancing_request__loan_duration',
                    'loan_refinancing_request__comms_channel_1',
                    'loan_refinancing_request__comms_channel_2',
                    'loan_refinancing_request__comms_channel_3',
                )
                .last()
            )
            data['selected_refinancing_offers'] = json.dumps(selected_refinancing_offers)
            waiver_request = None
            if (
                selected_refinancing_offers['product_type']
                in CovidRefinancingConst.waiver_products()
            ):
                waiver_request = WaiverRequest.objects.filter(
                    loan_refinancing_request=loan_refinancing_request
                ).last()
            if waiver_request:
                data['waiver_validity'] = waiver_request.waiver_validity_date
                data[
                    'first_waived_account_payment'
                ] = waiver_request.first_waived_account_payment.id
                data['last_waived_account_payment'] = waiver_request.last_waived_account_payment.id
                data[
                    'unrounded_requested_late_fee_waiver_percentage'
                ] = waiver_request.unrounded_requested_late_fee_waiver_percentage
                data[
                    'requested_late_fee_waiver_percentage'
                ] = waiver_request.requested_late_fee_waiver_percentage.replace('%', '')
                data[
                    'requested_late_fee_waiver_amount'
                ] = waiver_request.requested_late_fee_waiver_amount
                data[
                    'unrounded_requested_interest_waiver_percentage'
                ] = waiver_request.unrounded_requested_interest_waiver_percentage
                data[
                    'requested_interest_waiver_percentage'
                ] = waiver_request.requested_interest_waiver_percentage.replace('%', '')
                data[
                    'requested_interest_waiver_amount'
                ] = waiver_request.requested_interest_waiver_amount
                data[
                    'unrounded_requested_principal_waiver_percentage'
                ] = waiver_request.unrounded_requested_principal_waiver_percentage
                data[
                    'requested_principal_waiver_percentage'
                ] = waiver_request.requested_principal_waiver_percentage.replace('%', '')
                data[
                    'requested_late_fee_waiver_amount'
                ] = waiver_request.requested_principal_waiver_amount
                data['ptp_amount'] = waiver_request.ptp_amount
                data['waived_account_payment_count'] = waiver_request.waived_account_payment_count
                waiver_acount_payment_requests = []
                account = waiver_request.account
                account_payments = account.accountpayment_set.not_paid_active().order_by('due_date')
                for account_payment in account_payments:
                    waiver_account_payment_request = WaiverAccountPaymentRequest.objects.filter(
                        waiver_request=waiver_request, account_payment=account_payment
                    ).first()
                    if waiver_account_payment_request:
                        new_dict = dict()
                        new_dict[
                            'outstanding_late_fee_amount'
                        ] = waiver_account_payment_request.outstanding_late_fee_amount
                        new_dict[
                            'outstanding_interest_amount'
                        ] = waiver_account_payment_request.outstanding_interest_amount
                        new_dict[
                            'outstanding_principal_amount'
                        ] = waiver_account_payment_request.outstanding_principal_amount
                        new_dict[
                            'total_outstanding_amount'
                        ] = waiver_account_payment_request.total_outstanding_amount
                        new_dict[
                            'requested_late_fee_waiver_amount'
                        ] = waiver_account_payment_request.requested_late_fee_waiver_amount
                        new_dict[
                            'requested_interest_waiver_amount'
                        ] = waiver_account_payment_request.requested_interest_waiver_amount
                        new_dict[
                            'requested_principal_waiver_amount'
                        ] = waiver_account_payment_request.requested_principal_waiver_amount
                        new_dict[
                            'total_requested_waiver_amount'
                        ] = waiver_account_payment_request.total_requested_waiver_amount
                        new_dict[
                            'remaining_late_fee_amount'
                        ] = waiver_account_payment_request.remaining_late_fee_amount
                        new_dict[
                            'remaining_interest_amount'
                        ] = waiver_account_payment_request.remaining_interest_amount
                        new_dict[
                            'remaining_principal_amount'
                        ] = waiver_account_payment_request.remaining_principal_amount
                        new_dict[
                            'total_remaining_amount'
                        ] = waiver_account_payment_request.total_remaining_amount
                        new_dict[
                            'account_payment_id'
                        ] = waiver_account_payment_request.account_payment_id
                        if new_dict['total_remaining_amount'] > 0:
                            new_dict['is_paid_off_after_ptp'] = 'Y'
                        waiver_acount_payment_requests.append(new_dict)
                    else:
                        waiver_acount_payment_requests.append(None)
                data['waiver_payment_request'] = waiver_acount_payment_requests

                waiver_approval = waiver_request.waiverapproval_set.last()
                if waiver_approval:
                    data['waiver_validity'] = waiver_approval.approved_waiver_validity_date
                    data[
                        'first_waived_account_payment'
                    ] = waiver_approval.waiver_account_payment_approval.first().id
                    data[
                        'last_waived_account_payment'
                    ] = waiver_approval.waiver_account_payment_approval.last().id
                    data[
                        'unrounded_requested_late_fee_waiver_percentage'
                    ] = waiver_approval.unrounded_approved_late_fee_waiver_percentage
                    data['requested_late_fee_waiver_percentage'] = "{}%".format(
                        waiver_approval.approved_late_fee_waiver_percentage * 100
                    )
                    data[
                        'requested_late_fee_waiver_amount'
                    ] = waiver_approval.get_total_approved_waiver_amount(
                        "approved_late_fee_waiver_amount"
                    )
                    data[
                        'unrounded_requested_interest_waiver_percentage'
                    ] = waiver_approval.unrounded_approved_interest_waiver_percentage
                    data['requested_interest_waiver_percentage'] = "{}%".format(
                        waiver_approval.approved_interest_waiver_percentage * 100
                    )
                    data[
                        'requested_interest_waiver_amount'
                    ] = waiver_approval.get_total_approved_waiver_amount(
                        "approved_interest_waiver_amount"
                    )
                    data[
                        'unrounded_requested_principal_waiver_percentage'
                    ] = waiver_approval.unrounded_approved_principal_waiver_percentage
                    data['requested_principal_waiver_percentage'] = "{}%".format(
                        waiver_approval.approved_principal_waiver_percentage * 100
                    )
                    data[
                        'requested_late_fee_waiver_amount'
                    ] = waiver_approval.get_total_approved_waiver_amount(
                        "approved_principal_waiver_amount"
                    )
                    data['ptp_amount'] = waiver_approval.need_to_pay
                    data[
                        'waived_account_payment_count'
                    ] = waiver_approval.waiver_account_payment_approval.count()
                    waiver_account_payment_approvals = []
                    account_payments = account.accountpayment_set.normal().order_by('id')
                    for account_payment in account_payments:
                        waiver_acc_pay_approval = WaiverAccountPaymentApproval.objects.filter(
                            waiver_approval=waiver_approval, account_payment=account_payment
                        ).first()
                        if waiver_acc_pay_approval:
                            new_dict = dict()
                            new_dict[
                                'outstanding_late_fee_amount'
                            ] = waiver_acc_pay_approval.outstanding_late_fee_amount
                            new_dict[
                                'outstanding_interest_amount'
                            ] = waiver_acc_pay_approval.outstanding_interest_amount
                            new_dict[
                                'outstanding_principal_amount'
                            ] = waiver_acc_pay_approval.outstanding_principal_amount
                            new_dict[
                                'total_outstanding_amount'
                            ] = waiver_acc_pay_approval.total_outstanding_amount
                            new_dict[
                                'requested_late_fee_waiver_amount'
                            ] = waiver_acc_pay_approval.approved_late_fee_waiver_amount
                            new_dict[
                                'requested_interest_waiver_amount'
                            ] = waiver_acc_pay_approval.approved_interest_waiver_amount
                            new_dict[
                                'requested_principal_waiver_amount'
                            ] = waiver_acc_pay_approval.approved_principal_waiver_amount
                            new_dict[
                                'total_requested_waiver_amount'
                            ] = waiver_acc_pay_approval.total_approved_waiver_amount
                            new_dict[
                                'remaining_late_fee_amount'
                            ] = waiver_acc_pay_approval.remaining_late_fee_amount
                            new_dict[
                                'remaining_interest_amount'
                            ] = waiver_acc_pay_approval.remaining_interest_amount
                            new_dict[
                                'remaining_principal_amount'
                            ] = waiver_acc_pay_approval.remaining_principal_amount
                            new_dict[
                                'total_remaining_amount'
                            ] = waiver_acc_pay_approval.total_remaining_amount
                            new_dict[
                                'account_payment_id'
                            ] = waiver_acc_pay_approval.account_payment_id
                            if new_dict['total_remaining_amount'] > 0:
                                new_dict['is_paid_off_after_ptp'] = 'Y'
                            waiver_account_payment_approvals.append(new_dict)
                        else:
                            waiver_account_payment_approvals.append(None)
                    data['waiver_account_payment_request'] = waiver_account_payment_approvals

        return_data['data'] = data
        return JsonResponse(return_data)

    if (
        loan_refinancing_request
        and loan_refinancing_request.status == CovidRefinancingConst.STATUSES.approved
        and loan_refinancing_request.product_type in CovidRefinancingConst.reactive_products()
    ):
        return JsonResponse(
            {'status': 'failed', 'message': 'Ada program refinancing yang sedang berjalan'}
        )

    # set expired
    if (
        loan_refinancing_request
        and loan_refinancing_request.status
        in CovidRefinancingConst.NEED_VALIDATE_FOR_MULTIPLE_REQUEST_STATUSES
    ):

        if (
            loan_refinancing_request.status
            in CovidRefinancingConst.MULTI_OFFER_CHANGE_TO_EXPIRED_STATUSES
        ):
            loan_refinancing_request.update_safely(status=CovidRefinancingConst.STATUSES.expired)
            today_date = timezone.localtime(timezone.now()).date()
            waiver_request = (
                WaiverRequest.objects.filter(
                    account=loan_refinancing_request.account,
                    is_approved__isnull=True,
                    is_automated=False,
                    waiver_validity_date__gte=today_date,
                )
                .order_by('cdate')
                .last()
            )
            if waiver_request:
                waiver_request.update_safely(
                    is_approved=False, refinancing_status=CovidRefinancingConst.STATUSES.expired
                )

    loan_refinancing_offers = []
    campaign_request = check_account_id_is_for_cohort_campaign(data['account_id'])
    try:
        with transaction.atomic():
            loan_refinancing_request_dict = dict(
                account_id=data['account_id'],
                product_type=data['selected_product'],
                expire_in_days=feature_params['email_expire_in_days'],
                status=CovidRefinancingConst.STATUSES.offer_generated,
                request_date=timezone.localtime(timezone.now()).date(),
                form_submitted_ts=timezone.localtime(timezone.now()),
                channel=CovidRefinancingConst.CHANNELS.reactive,
            )

            old_status = None
            if loan_refinancing_request and loan_refinancing_request.status in list(
                CovidRefinancingConst.NEW_PROACTIVE_STATUSES.__dict__.values()
            ):
                old_status = loan_refinancing_request.status
                loan_refinancing_request.update_safely(**loan_refinancing_request_dict)
            else:
                loan_refinancing_request = LoanRefinancingRequest.objects.create(
                    **loan_refinancing_request_dict
                )
            if not loan_refinancing_request.uuid:
                uuid = generate_unique_uuid()
                url = generate_short_url_for_proactive_webview(uuid)
                loan_refinancing_request.update_safely(uuid=uuid, url=url)

            is_offer_generated = generated_j1_default_offers(
                loan_refinancing_request, data['selected_product'])
            # validation max cap rule
            is_passed, err_msg = pass_check_refinancing_max_cap_rule_by_account_id(
                data['account_id'], data['selected_product'])
            if not is_passed:
                raise MaxCapRuleException(err_msg)

            loan_refinancing_offers = []
            if is_offer_generated:
                loan_refinancing_offers = LoanRefinancingOffer.objects.filter(
                    loan_refinancing_request=loan_refinancing_request, is_latest=True
                ).values('loan_duration', 'product_type')
            if (
                old_status
                in CovidRefinancingConst.REACTIVE_OFFER_STATUS_AVAILABLE_FOR_GENERATE_OFFER
            ):
                loan_refinancing_request.refresh_from_db()
                check_refinancing_offers = get_proactive_offers(loan_refinancing_request)
                limit = 2
                if check_refinancing_offers.count() != 2:
                    limit = limit - check_refinancing_offers.count()
                    loan_ref_offers = LoanRefinancingOffer.objects.filter(
                        loan_refinancing_request=loan_refinancing_request,
                        is_latest=False,
                        recommendation_order__isnull=False,
                        product_type__in=CovidRefinancingConst.OFFER_GENERATED_AVAILABLE_PRODUCT,
                    ).order_by('id')

                    for loan_ref_offer in loan_ref_offers:
                        current_offer = loan_refinancing_request.loanrefinancingoffer_set.filter(
                            loan_refinancing_request=loan_refinancing_request,
                            is_latest=True,
                            product_type=loan_ref_offer.product_type,
                        ).exists()

                        if not current_offer:
                            loan_ref_offer.update_safely(is_latest=True)
                            limit = limit - 1

                    reorder_recommendation(loan_refinancing_request)

            # to update loan refinancing request from blast csv to expired
            if (
                campaign_request
                and campaign_request.loan_refinancing_request.status
                == CovidRefinancingConst.STATUSES.requested
            ):
                is_unsuitable_offer = True
                if data['selected_product'] == 'R6':
                    is_unsuitable_offer = False
                update_requested_status_refinancing_to_expired_for_cohort_campaign(
                    campaign_request,
                    loan_refinancing_request,
                    is_unsuitable_offer=is_unsuitable_offer,
                )

            # update status checkout request when create R4 -R6 (offer generated status)
            update_checkout_experience_status_to_cancel(data['account_id'])

    except MaxCapRuleException as e:
        return JsonResponse({
            'status': 'max cap rule validation',
            'message': str(e)
        })

    except Exception as e:
        get_julo_sentry_client().captureException()
        return JsonResponse({
            "status": "failed",
            "message": str(e)
        })

    return JsonResponse(
        {
            'status': 'success',
            'data': {
                'refinancing_offers': list(loan_refinancing_offers),
                'current_loan_refinancing_request_status': generate_status_and_tips_loan_refinancing_status(  # noqa
                    loan_refinancing_req=loan_refinancing_request, data={}
                ),
            },
            'message': 'offers berhasil di generate',
        }
    )


def ajax_j1_waiver_recommendation(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = json.loads(request.body)
    waiver_recommendation = get_j1_waiver_recommendation(
        data['account_id'],
        data['selected_offer_recommendation'],
        data['is_covid_risky'],
        data['bucket'],
        data.get('account_payment_ids') or [],
    )
    if not waiver_recommendation:
        return JsonResponse(
            {
                'status': 'failed',
                'message': 'waiver recommendation tidak ditemukan',
            }
        )

    actual_waiver = model_to_dict(waiver_recommendation)
    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        account=data['account_id'],
        status__in=(
            CovidRefinancingConst.STATUSES.offer_selected,
            CovidRefinancingConst.STATUSES.approved,
        ),
    ).last()
    if loan_refinancing_request:
        today_date = timezone.localtime(timezone.now()).date()
        waiver_request_filter = dict(
            account_id=data['account_id'], is_automated=False, waiver_validity_date__gte=today_date
        )

        if loan_refinancing_request.status == CovidRefinancingConst.STATUSES.offer_selected:
            waiver_request_filter['is_approved__isnull'] = True
        else:
            waiver_request_filter['is_approved'] = True

        waiver_request = (
            WaiverRequest.objects.filter(**waiver_request_filter).order_by('cdate').last()
        )

        if waiver_request:
            actual_waiver = dict()
            percentage = waiver_request.requested_principal_waiver_percentage.replace('%', '')
            actual_waiver['principal_waiver_percentage'] = float(percentage) / float(100)
            percentage = waiver_request.requested_interest_waiver_percentage.replace('%', '')
            actual_waiver['interest_waiver_percentage'] = float(percentage) / float(100)
            percentage = waiver_request.requested_late_fee_waiver_percentage.replace('%', '')
            actual_waiver['late_fee_waiver_percentage'] = float(percentage) / float(100)

    else:
        if data['selected_offer_recommendation'] == "R6":
            actual_waiver['late_fee_waiver_percentage'] = "1.00"

        elif data['selected_offer_recommendation'] == "R4":
            actual_waiver['interest_waiver_percentage'] = "1.00"
            actual_waiver['late_fee_waiver_percentage'] = "1.00"

    return JsonResponse(
        {
            'status': 'success',
            'message': 'berhasil mendapatkan waiver recommendation',
            'waiver_recommendation': model_to_dict(waiver_recommendation),
            'actual_waiver': actual_waiver,
        }
    )


def ajax_j1_covid_refinancing_submit_waiver_request(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "message": "non authorized user",
            }
        )
    data = request.POST.dict()
    serializer = J1WaiverRequestSerializer(data=data)
    if not serializer.is_valid():
        message = serializer.errors
        return JsonResponse(
            {
                "status": "failed",
                "message": str(message),
            }
        )

    data = serializer.data
    create_waiver = True
    account = Account.objects.get_or_none(pk=data['account_id'])
    application = account.application_set.last()
    fullname = collection_detokenize_sync_object_model(
        'application', application, application.customer.customer_xid, ['fullname']
    ).fullname
    message = (
        "Permohonan Waiver untuk <strong>%s (ID: %s)</strong> "
        "telah dilanjutkan ke proses berikutnya. JULO akan mengirimkan email/PN/SMS "
        "secara otomatis kepada customer tentang detil program ini. Mohon ingatkan "
        "customer untuk membuka pesan yang JULO kirimkan."
    ) % (fullname, application.id)

    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        account=data['account_id']
    ).last()
    if loan_refinancing_request:
        created_date = format_date(
            loan_refinancing_request.cdate.date(), 'dd-MM-yyyy', locale='id_ID'
        )
        select_or_approve = CovidRefinancingConst.REACTIVE_OFFER_STATUS_SELECTED_OR_APPROVED
        if loan_refinancing_request.status in select_or_approve:
            create_waiver = False
            date_reference = loan_refinancing_request.form_submitted_ts
            expiration_date = date_reference + timedelta(
                days=loan_refinancing_request.expire_in_days
            )

            all_payments_in_waive_period = (
                AccountTransaction.objects.filter(
                    transaction_type__in=PaymentEventConst.PARTIAL_PAYMENT_TYPES,
                    cdate__gte=date_reference,
                    transaction_date__gte=date_reference,
                    transaction_date__lte=expiration_date,
                    account=account,
                )
                .aggregate(total=Sum('transaction_amount'))
                .get('total')
                or 0
            )

            if all_payments_in_waive_period:
                message = (
                    "<strong>{} (ID: {})</strong> sudah mengajukan program "
                    "keringanan <strong>{}</strong> pada tanggal <strong>{}</strong> "
                    "dan belum melakukan pembayarannya secara penuh."
                ).format(
                    fullname,
                    application.id,
                    loan_refinancing_request.product_type.upper(),
                    created_date,
                )
            else:
                message = (
                    "<strong>{} (ID: {})</strong> sudah mengajukan program keringanan "
                    "<strong>{}</strong> pada tanggal <strong>{}</strong> dan sudah "
                    "melakukan konfirmasi atau sudah memilih detail program "
                    "tersebut."
                ).format(
                    fullname,
                    application.id,
                    loan_refinancing_request.product_type.upper(),
                    created_date,
                )

        elif loan_refinancing_request.status == CovidRefinancingConst.STATUSES.activated:
            create_waiver = False
            message = (
                "<strong>%s (ID: %s)</strong> sudah mengajukan program keringanan "
                "<strong>%s</strong> pada tanggal <strong>%s</strong> dan program "
                "telah aktif."
            ) % (
                fullname,
                application.id,
                loan_refinancing_request.product_type.upper(),
                created_date,
            )

    if not create_waiver:
        return JsonResponse(
            {
                "status": "failed",
                "message": message,
            }
        )

    oldest_account_payment = (
        AccountPayment.objects.oldest_account_payment()
        .filter(account_id=data['account_id'])
        .first()
    )

    (
        is_need_approval_tl,
        is_need_approval_supervisor,
        is_need_approval_colls_head,
        is_need_approval_ops_head,
    ) = get_waiver_is_need_approvals(data, oldest_account_payment.dpd)

    if not (
        is_need_approval_tl
        or is_need_approval_supervisor
        or is_need_approval_colls_head
        or is_need_approval_ops_head
    ):
        data['is_automated'] = True

    active_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.COVID_REFINANCING, is_active=True
    ).last()

    if not active_feature:
        return JsonResponse({'status': 'failed', 'message': 'Feature setting status tidak aktif'})

    loan_refinancing_request = LoanRefinancingRequest.objects.filter(account=account).last()
    waiver_request = None
    waiver_temp = None
    campaign_request = check_account_id_is_for_cohort_campaign(account.id)
    with transaction.atomic():
        today = timezone.localtime(timezone.now())
        validity_date = datetime.strptime(data['waiver_validity_date'], '%Y-%m-%d')
        validity_in_days = abs((today.date() - validity_date.date()).days)
        update_campaign_request_dict = dict()

        if data['is_customer_confirmed']:
            waiver_recommendation = WaiverRecommendation.objects.filter(
                pk=int(data['waiver_recommendation_id'])
            ).last()
            data['selected_account_payments_waived'] = json.loads(
                data['selected_account_payments_waived']
            )
            waiver_request = WaiverRequest.objects.create(
                account=account,
                agent_name=request.user.username,
                bucket_name=data['bucket_name'],
                program_name=data['selected_program_name'],
                is_covid_risky=data['is_covid_risky'],
                outstanding_amount=data['outstanding_amount'],
                unpaid_principal=data['unpaid_principal'],
                unpaid_interest=data['unpaid_interest'],
                unpaid_late_fee=data['unpaid_late_fee'],
                waiver_validity_date=data['waiver_validity_date'],
                ptp_amount=data['ptp_amount'],
                loan_refinancing_request=loan_refinancing_request,
                is_need_approval_tl=is_need_approval_tl,
                is_need_approval_supervisor=is_need_approval_supervisor,
                is_need_approval_colls_head=is_need_approval_colls_head,
                is_need_approval_ops_head=is_need_approval_ops_head,
                waived_account_payment_count=data['waived_account_payment_count'],
                is_automated=data['is_automated'],
                requested_late_fee_waiver_percentage=data["requested_late_fee_waiver_percentage"]
                + "%",
                requested_interest_waiver_percentage=data["requested_interest_waiver_percentage"]
                + "%",
                requested_principal_waiver_percentage=data["requested_principal_waiver_percentage"]
                + "%",
                requested_late_fee_waiver_amount=int(data["requested_late_fee_waiver_amount"]),
                requested_interest_waiver_amount=int(data["requested_interest_waiver_amount"]),
                requested_principal_waiver_amount=int(data["requested_principal_waiver_amount"]),
                waiver_recommendation=waiver_recommendation,
                agent_notes=data["agent_notes"],
                first_waived_account_payment_id=int(data["first_waived_account_payment"]),
                last_waived_account_payment_id=int(data["last_waived_account_payment"]),
                requested_waiver_amount=int(data["requested_waiver_amount"]),
                remaining_amount_for_waived_payment=int(
                    data["remaining_amount_for_waived_payment"]
                ),
                waiver_type="unpaid",
                is_j1=True,
                unrounded_requested_interest_waiver_percentage=data[
                    "unrounded_requested_interest_waiver_percentage"
                ],
                unrounded_requested_late_fee_waiver_percentage=data[
                    "unrounded_requested_late_fee_waiver_percentage"
                ],
                unrounded_requested_principal_waiver_percentage=data[
                    "unrounded_requested_principal_waiver_percentage"],
            )
            (
                waiver_payment_request_data,
                waiver_account_payment_request_data,
            ) = generate_and_calculate_waiver_request_reactive(
                data, waiver_request, data['selected_account_payments_waived']['waiver']
            )
            if waiver_payment_request_data:
                WaiverPaymentRequest.objects.bulk_create(waiver_payment_request_data)
            if waiver_account_payment_request_data:
                WaiverAccountPaymentRequest.objects.bulk_create(waiver_account_payment_request_data)

            loan_refinancing_req_dict = dict(
                prerequisite_amount=data['ptp_amount'],
                total_latefee_discount=data['requested_late_fee_waiver_amount'],
                expire_in_days=validity_in_days,
                product_type=data['selected_program_name'].upper(),
                status=CovidRefinancingConst.STATUSES.offer_selected,
                loan_duration=0,
                source=data['agent_group'],
            )
            if data.get('agent_detail'):
                loan_refinancing_req_dict.update(source_detail=json.loads(data['agent_detail']))

            update_existing_offer_dict = dict(
                selected_by=request.user,
                is_accepted=True,
                offer_accepted_ts=today,
            )

            if 'multiple_payment_ptp' in data:
                data['multiple_payment_ptp'] = json.loads(data['multiple_payment_ptp'])
                if data['multiple_payment_ptp']:
                    multiple_payment_ptp_data = []
                    waiver_request.multiple_payment_ptp.all().delete()
                    for idx in range(len(data['multiple_payment_ptp'])):
                        data['multiple_payment_ptp'][idx].update(
                            dict(
                                waiver_request=waiver_request,
                                remaining_amount=data['multiple_payment_ptp'][idx][
                                    "promised_payment_amount"
                                ],
                            )
                        )
                        multiple_payment_ptp_data.append(
                            MultiplePaymentPTP(**data['multiple_payment_ptp'][idx])
                        )

                    if multiple_payment_ptp_data:
                        MultiplePaymentPTP.objects.bulk_create(multiple_payment_ptp_data)

            if data['is_automated']:
                force_expired_j1_waiver_temp(account)
                waiver_temp = WaiverTemp.objects.create(
                    account=account,
                    late_fee_waiver_amt=data['requested_late_fee_waiver_amount'],
                    interest_waiver_amt=data['requested_interest_waiver_amount'],
                    principal_waiver_amt=data['requested_principal_waiver_amount'],
                    need_to_pay=data['ptp_amount'],
                    waiver_date=today.date(),
                    late_fee_waiver_note="",
                    interest_waiver_note="",
                    principal_waiver_note="",
                    valid_until=validity_date,
                    waiver_request=waiver_request,
                    is_automated=True,
                )
                waiver_payment_temp_data = []
                for idx in range(len(data['selected_account_payments_waived']['waiver'])):
                    account_payment_waived = data['selected_account_payments_waived']['waiver'][idx]
                    waiver_payment_temp_data.append(
                        WaiverPaymentTemp(
                            waiver_temp=waiver_temp,
                            account_payment_id=int(account_payment_waived['account_payment_id']),
                            late_fee_waiver_amount=account_payment_waived['late_fee'],
                            interest_waiver_amount=account_payment_waived['interest'],
                            principal_waiver_amount=account_payment_waived['principal'],
                        )
                    )
                WaiverPaymentTemp.objects.bulk_create(waiver_payment_temp_data)
                loan_refinancing_req_dict['status'] = CovidRefinancingConst.STATUSES.approved

            if (
                campaign_request
                and campaign_request.loan_refinancing_request == loan_refinancing_request
            ):
                update_campaign_request_dict = dict(
                    offer=loan_refinancing_request.product_type,
                )

        else:
            waiver_request = True
            message = "Loan Refinancing Request berhasil diubah"
            update_existing_offer_dict = dict()
            loan_refinancing_req_dict = dict()

        loan_refinancing_req_dict['form_submitted_ts'] = today
        loan_refinancing_req_dict['channel'] = CovidRefinancingConst.CHANNELS.reactive
        loan_refinancing_req_dict['is_multiple_ptp_payment'] = data["is_multiple_ptp_payment"]

        for num, comms_channel in enumerate(data['comms_channels'].split(','), start=1):
            loan_refinancing_req_dict['comms_channel_%s' % num] = comms_channel

        if not loan_refinancing_request.uuid:
            uuid = generate_unique_uuid()
            loan_refinancing_req_dict['uuid'] = uuid
            loan_refinancing_req_dict['url'] = generate_short_url_for_proactive_webview(uuid)

        loan_refinancing_request.update_safely(**loan_refinancing_req_dict)

        loan_refinancing_offer_dict = dict(
            loan_refinancing_request=loan_refinancing_request,
            product_type=data['selected_program_name'].upper(),
            latefee_discount_percentage=data['requested_late_fee_waiver_percentage'] + '%',
            interest_discount_percentage=data['requested_interest_waiver_percentage'] + '%',
            principal_discount_percentage=data['requested_principal_waiver_percentage'] + '%',
            is_latest=True,
        )
        existing_offer = LoanRefinancingOffer.objects.filter(**loan_refinancing_offer_dict).last()
        if not existing_offer:
            latest_offer = LoanRefinancingOffer.objects.filter(
                loan_refinancing_request=loan_refinancing_request,
                product_type=data['selected_program_name'].upper(),
                generated_by__isnull=True,
                is_latest=True,
                is_proactive_offer=False,
            ).last()
            if latest_offer:
                latest_offer.update_safely(is_latest=False)

            existing_offer = LoanRefinancingOffer.objects.create(
                loan_refinancing_request=loan_refinancing_request,
                product_type=data['selected_program_name'].upper(),
                prerequisite_amount=data['ptp_amount'],
                total_latefee_discount=data['requested_late_fee_waiver_amount'],
                total_interest_discount=data['requested_interest_waiver_amount'],
                total_principal_discount=data['requested_principal_waiver_amount'],
                validity_in_days=validity_in_days,
                latefee_discount_percentage=data['requested_principal_waiver_percentage'] + '%',
                interest_discount_percentage=data['requested_interest_waiver_percentage'] + '%',
                principal_discount_percentage=data['requested_principal_waiver_percentage'] + '%',
                generated_by=request.user,
            )

        update_existing_offer_dict['validity_in_days'] = validity_in_days
        update_existing_offer_dict['is_latest'] = True

        existing_offer.update_safely(**update_existing_offer_dict)

        r4_product = CovidRefinancingConst.PRODUCTS.r4
        if data['selected_program_name'].upper() == r4_product:
            proactive_existing_offer = LoanRefinancingOffer.objects.filter(
                loan_refinancing_request=loan_refinancing_request,
                product_type=data['selected_program_name'].upper(),
                latefee_discount_percentage=data['requested_principal_waiver_percentage'] + '%',
                interest_discount_percentage=data['requested_interest_waiver_percentage'] + '%',
                principal_discount_percentage=data['requested_principal_waiver_percentage'] + '%',
                is_proactive_offer=True,
            ).last()
            if proactive_existing_offer:
                proactive_existing_offer.update_safely(recommendation_order=0, is_latest=False)
            else:
                existing_offer.refresh_from_db()
                previous_offer_dict = dict(
                    loan_refinancing_request=loan_refinancing_request,
                    product_type=existing_offer.product_type,
                    prerequisite_amount=existing_offer.prerequisite_amount,
                    total_latefee_discount=existing_offer.total_latefee_discount,
                    total_interest_discount=existing_offer.total_interest_discount,
                    total_principal_discount=existing_offer.total_principal_discount,
                    validity_in_days=existing_offer.validity_in_days,
                    latefee_discount_percentage=existing_offer.latefee_discount_percentage,
                    interest_discount_percentage=existing_offer.interest_discount_percentage,
                    principal_discount_percentage=existing_offer.principal_discount_percentage,
                    generated_by=existing_offer.generated_by,
                    recommendation_order=0,
                    is_proactive_offer=True,
                    is_latest=False,
                )
                LoanRefinancingOffer.objects.create(**previous_offer_dict)
            reorder_recommendation(loan_refinancing_request)

    loan_refinancing_request.refresh_from_db()
    if (
        loan_refinancing_request.status == CovidRefinancingConst.STATUSES.approved
        and loan_refinancing_request.product_type
    ):
        send_loan_refinancing_request_approved_notification(loan_refinancing_request)

    # will update offer column on loan_refinancing_request_campaign
    if campaign_request:
        campaign_request.update_safely(**update_campaign_request_dict)

    if (
        data['is_customer_confirmed']
        and data['selected_program_name'].upper() in CovidRefinancingConst.waiver_products()
        and loan_refinancing_request.status == CovidRefinancingConst.STATUSES.offer_selected
    ):
        if loan_refinancing_request.channel in {
            CovidRefinancingConst.CHANNELS.proactive,
            CovidRefinancingConst.CHANNELS.reactive
        }:
            send_email_refinancing_offer_selected.delay(loan_refinancing_request.id)
        if loan_refinancing_request.channel == CovidRefinancingConst.CHANNELS.proactive:
            send_pn_covid_refinancing_offer_selected.delay(loan_refinancing_request.id)
            send_sms_covid_refinancing_offer_selected.delay(loan_refinancing_request.id)

    return JsonResponse(
        {
            'status': 'success' if waiver_request else 'failed',
            'message': message if waiver_request else 'Mohon maaf. Silakan coba lagi',
        }
    )


def submit_j1_waiver_approval(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse(
            {
                "status": "failed",
                "message": "non authorized user",
            },
            status=400,
        )

    user_groups = request.user.groups.values_list('name', flat=True)
    if not any(approver_role in user_groups for approver_role in NEW_WAIVER_APPROVER_GROUPS):
        return JsonResponse(
            {
                "status": "failed",
                "message": "User anda tidak termasuk dalam role Waiver Approver",
            },
            status=400,
        )
    data = json.loads(request.body)
    waiver_approval_serializer = J1WaiverApprovalSerializer(data=data)
    if WAIVER_FRAUD_APPROVER_GROUP not in user_groups:
        try:
            with transaction.atomic():
                waiver_approval_serializer.is_valid(raise_exception=True)
                waiver_approval_valid = waiver_approval_serializer.validated_data
                waiver_approval_valid.pop('account_id')
                waiver_account_payment_approvals_data = waiver_approval_valid.pop(
                    'waiver_account_payment_approvals'
                )
                if 'waiver_request' in waiver_approval_valid:
                    waiver_request_data = waiver_approval_valid.pop('waiver_request')
                if 'waiver_account_payment_requests' in waiver_approval_valid:
                    waiver_account_payment_requests_data = waiver_approval_valid.pop(
                        'waiver_account_payment_requests'
                    )

                waiver_request_id = waiver_approval_valid.pop('waiver_request_id')
                if not waiver_request_id:
                    if not waiver_request_data:
                        raise ValidationError({'message': 'Waiver request data wajib diisi'})

                    waiver_request_serializer = J1WaiverRequestSerializer(data=waiver_request_data)
                    waiver_request_serializer.is_valid(raise_exception=True)
                    waiver_request_valid = waiver_request_serializer.validated_data

                    oldest_account_payment = (
                        AccountPayment.objects.oldest_account_payment()
                        .filter(account_id=waiver_request_data['account_id'])
                        .first()
                    )

                    (
                        is_need_approval_tl,
                        is_need_approval_supervisor,
                        is_need_approval_colls_head,
                        is_need_approval_ops_head,
                    ) = get_waiver_is_need_approvals(
                        waiver_request_data, oldest_account_payment.dpd
                    )

                    waiver_request_valid['is_need_approval_tl'] = is_need_approval_tl
                    waiver_request_valid[
                        'is_need_approval_supervisor'
                    ] = is_need_approval_supervisor
                    waiver_request_valid[
                        'is_need_approval_colls_head'
                    ] = is_need_approval_colls_head
                    waiver_request_valid['is_need_approval_ops_head'] = is_need_approval_ops_head
                    waiver_request_valid['program_name'] = waiver_request_valid.pop(
                        'selected_program_name'
                    )
                    waiver_request_valid['waiver_recommendation_id'] = waiver_request_valid.pop(
                        'waiver_recommendation_id'
                    )
                    waiver_request_valid['first_waived_account_payment_id'] = int(
                        waiver_request_valid.pop("first_waived_account_payment")
                    )
                    waiver_request_valid['last_waived_account_payment_id'] = int(
                        waiver_request_valid.pop("last_waived_account_payment")
                    )

                    waiver_request_valid.pop('calculated_unpaid_waiver_percentage')
                    waiver_request_valid.pop('recommended_unpaid_waiver_percentage')

                    waiver_request_valid['agent_name'] = request.user.username

                    waiver_recommendation_id = waiver_request_valid['waiver_recommendation_id']
                    waiver_recommendation = WaiverRecommendation.objects.get_or_none(
                        pk=waiver_recommendation_id
                    )
                    if not waiver_recommendation:
                        waiver_request_valid['waiver_recommendation_id'] = None

                    waiver_request_obj = WaiverRequest.objects.create(**waiver_request_valid)
                    (
                        waiver_payment_request_data,
                        waiver_account_payment_request_data,
                    ) = generate_and_calculate_waiver_request_reactive(
                        waiver_request_valid,
                        waiver_request_obj,
                        waiver_account_payment_requests_data,
                        is_from_agent=False,
                    )
                    if waiver_payment_request_data:
                        WaiverPaymentRequest.objects.bulk_create(waiver_payment_request_data)
                    if waiver_account_payment_request_data:
                        WaiverAccountPaymentRequest.objects.bulk_create(waiver_payment_request_data)
                else:
                    waiver_request_obj = WaiverRequest.objects.get_or_none(pk=waiver_request_id)
                    if not waiver_request_obj:
                        raise ValidationError(
                            {
                                'message': 'Waiver request tidak ditemukan',
                                'waiver_request_id': waiver_request_id,
                            }
                        )
                    if waiver_request_obj.is_approved:
                        raise ValidationError(
                            {
                                'message': 'Waiver request status Approved',
                                'waiver_request_id': waiver_request_id,
                            }
                        )
                approver_type = waiver_request_obj.update_approval_layer_state(user_groups)
                waiver_approval_valid['waiver_request'] = waiver_request_obj
                waiver_approval_valid['approver_type'] = approver_type
                waiver_approval_valid['decision_ts'] = timezone.localtime(timezone.now())
                waiver_approval_valid['approved_by'] = request.user
                waiver_approval_obj = WaiverApproval.objects.create(**waiver_approval_valid)
                is_approved = waiver_request_obj.is_last_approval_layer(waiver_approval_obj)

                (
                    calculated_waiver_payment_approvals,
                    calculated_waiver_account_payment_approvals,
                ) = generate_and_calculate_waiver_approval_reactive(
                    waiver_approval_obj,
                    waiver_account_payment_approvals_data,
                    data['ptp_amount'],
                    is_ptp_paid=data['paid_ptp_amount'] > 0,
                )
                if calculated_waiver_payment_approvals:
                    WaiverPaymentApproval.objects.bulk_create(calculated_waiver_payment_approvals)
                if calculated_waiver_account_payment_approvals:
                    WaiverAccountPaymentApproval.objects.bulk_create(
                        calculated_waiver_account_payment_approvals
                    )

                if is_approved:
                    waiver_account_payment_approval = (
                        waiver_approval_obj.waiveraccountpaymentapproval_set.aggregate(
                            late_fee=Sum('approved_late_fee_waiver_amount'),
                            interest=Sum('approved_interest_waiver_amount'),
                            principal=Sum('approved_principal_waiver_amount'),
                        )
                    )
                    if not waiver_approval_obj.is_gpw:
                        force_expired_j1_waiver_temp(waiver_request_obj.account)
                        today = timezone.localtime(timezone.now())
                        waiver_temp = WaiverTemp.objects.create(
                            account=waiver_request_obj.account,
                            late_fee_waiver_amt=waiver_account_payment_approval["late_fee"],
                            interest_waiver_amt=waiver_account_payment_approval["interest"],
                            principal_waiver_amt=waiver_account_payment_approval["principal"],
                            need_to_pay=waiver_approval_obj.need_to_pay,
                            waiver_date=today.date(),
                            late_fee_waiver_note="Waiver Approved by %s" % request.user.username,
                            interest_waiver_note="Waiver Approved by %s" % request.user.username,
                            principal_waiver_note="Waiver Approved by %s" % request.user.username,
                            valid_until=waiver_approval_obj.approved_waiver_validity_date,
                            waiver_request=waiver_request_obj,
                            last_approved_by=request.user,
                        )
                        waiver_temp.waiver_payment_temp.all().delete()
                        waiver_payment_temp_data = []
                        for (
                            waiver_account_payment_approval
                        ) in waiver_account_payment_approvals_data:
                            waiver_payment_temp_data.append(
                                WaiverPaymentTemp(
                                    waiver_temp=waiver_temp,
                                    account_payment_id=waiver_account_payment_approval[
                                        'account_payment_id'
                                    ],
                                    late_fee_waiver_amount=waiver_account_payment_approval[
                                        'approved_late_fee_waiver_amount'
                                    ],
                                    interest_waiver_amount=waiver_account_payment_approval[
                                        'approved_interest_waiver_amount'
                                    ],
                                    principal_waiver_amount=waiver_account_payment_approval[
                                        'approved_principal_waiver_amount'
                                    ],
                                )
                            )
                        WaiverPaymentTemp.objects.bulk_create(waiver_payment_temp_data)
                        waiver_request_obj.update_safely(
                            waiver_type="unpaid",
                            refinancing_status=waiver_approval_valid['decision'],
                        )

                    else:
                        waiver_request_obj.update_safely(
                            waiver_type="paid", refinancing_status=waiver_approval_valid['decision']
                        )
                        loan_statuses_list = []
                        for (
                            waiver_account_payment_approval
                        ) in waiver_account_payment_approvals_data:
                            waived_payment = AccountPayment.objects.get(
                                pk=waiver_account_payment_approval['account_payment_id']
                            )

                            for waiver_type in (
                                "late_fee",
                                "interest",
                                "principal",
                            ):
                                key = 'approved_%s_waiver_amount' % waiver_type
                                if waiver_account_payment_approval[key] > 0:
                                    j1_paid_waiver(
                                        waiver_type,
                                        waived_payment,
                                        waiver_account_payment_approval[key],
                                        "Waiver Approved by %s" % request.user.username,
                                        loan_statuses_list,
                                        waiver_request=waiver_request_obj,
                                    )
                        get_and_update_latest_loan_status(loan_statuses_list)

                    is_gpw = waiver_approval_obj.is_gpw
                    lf_discount = waiver_approval_obj.total_account_payment_approved_late_fee_waiver
                    loan_ref_request = waiver_request_obj.loan_refinancing_request
                    if loan_ref_request:
                        partial_paid = get_partial_account_payments_by_program(loan_ref_request)
                        prerequisite_amount = (
                            0 if is_gpw else waiver_approval_obj.need_to_pay - partial_paid
                        )
                        loan_ref_request.update_safely(
                            prerequisite_amount=prerequisite_amount,
                            total_latefee_discount=lf_discount,
                            is_gpw=is_gpw,
                        )
                        if prerequisite_amount > 0:
                            loan_ref_request.update_safely(
                                status=CovidRefinancingConst.STATUSES.approved
                            )
                            send_loan_refinancing_request_approved_notification(loan_ref_request)
                        else:
                            if loan_ref_request.status != CovidRefinancingConst.STATUSES.activated:
                                if len(waiver_account_payment_approvals_data):
                                    account_payment = AccountPayment.objects.get(
                                        pk=waiver_account_payment_approvals_data
                                        [0]['account_payment_id'])
                                else:
                                    account_payment = loan_ref_request.account.\
                                        accountpayment_set.normal().last()
                                J1LoanRefinancing(account_payment, loan_ref_request).activate()
                    else:
                        if is_gpw:
                            LoanRefinancingRequest.objects.create(
                                **dict(
                                    account=waiver_request_obj.account,
                                    expire_in_days=0,
                                    product_type=waiver_approval_obj.approved_reason_type,
                                    loan_duration=0,
                                    new_income=0,
                                    new_expense=0,
                                    prerequisite_amount=0,
                                    total_latefee_discount=lf_discount,
                                    status=CovidRefinancingConst.STATUSES.activated,
                                    request_date=timezone.localtime(timezone.now()).date(),
                                    form_submitted_ts=timezone.localtime(timezone.now()),
                                    offer_activated_ts=timezone.localtime(timezone.now()),
                                    channel=CovidRefinancingConst.CHANNELS.reactive,
                                    is_gpw=is_gpw,
                                )
                            )

                elif waiver_approval_obj.decision == WaiverApprovalDecisions.REJECTED:
                    loan_ref_request = waiver_request_obj.loan_refinancing_request
                    if loan_ref_request:
                        loan_ref_request.update_safely(
                            status=CovidRefinancingConst.STATUSES.rejected
                        )

                else:
                    send_slack_notification_for_j1_waiver_approver.delay(
                        waiver_request_obj.account_id
                    )

        except ValidationError as e:
            get_julo_sentry_client().captureException()
            return JsonResponse({
                'status': 'failed',
                'message': 'Gagal memproses approval harap cek kembali',
                'detail': e.__dict__,
            }, status=400)
        else:
            return JsonResponse(
                {
                    'status': 'success',
                    'message': 'Berhasil memproses approval',
                    'detail': '',
                }
            )
    else:
        try:
            with transaction.atomic():
                waiver_approval_serializer.is_valid(raise_exception=True)
                waiver_approval_valid = waiver_approval_serializer.validated_data
                waiver_account_payment_approvals_data = waiver_approval_valid.pop(
                    'waiver_account_payment_approvals'
                )
                waiver_request_approval_list = []
                for waiver_account_payment_approval in waiver_account_payment_approvals_data:
                    for waiver_type in ("interest", "principal", "late_fee"):
                        waiver_request_approval = {}
                        key = 'approved_{}_waiver_amount'.format(waiver_type)
                        if waiver_account_payment_approval[key] > 0:
                            waiver_request_approval.update(
                                {
                                    'account_payment_id': waiver_account_payment_approval[
                                        'account_payment_id'
                                    ]
                                }
                            )
                            waiver_request_approval.update({'waiver_type': waiver_type})
                            waiver_request_approval.update(
                                {'waiver_amount': waiver_account_payment_approval[key]}
                            )
                            waiver_request_approval_list.append(waiver_request_approval)
                loan_statuses_list = []
                for waiver_request_approval_data in waiver_request_approval_list:
                    waived_payments = AccountPayment.objects.get(
                        pk=waiver_request_approval_data['account_payment_id']
                    )
                    j1_paid_waiver(
                        waiver_request_approval_data['waiver_type'],
                        waived_payments,
                        waiver_request_approval_data['waiver_amount'],
                        "Waiver Approved by %s" % request.user.username,
                        loan_statuses_list,
                    )
                get_and_update_latest_loan_status(loan_statuses_list)

        except ValidationError as e:
            get_julo_sentry_client().captureException()
            return JsonResponse({
                'status': 'failed',
                'message': 'Gagal memproses approval harap cek kembali',
                'detail': e.__dict__,
            }, status=400)
        else:
            return JsonResponse(
                {
                    'status': 'success',
                    'message': 'Berhasil memproses approval',
                    'detail': '',
                }
            )


@julo_login_required
@julo_login_required_multigroup(
    [
        'collection_supervisor',
        'ops_team_leader',
        'collection_team_leader',
        'collection_area_coordinator',
    ]
)
def manual_waiver_expiry_page(request):
    template_name = 'waiver/waiver_expiry.html'
    data = {
        'error_messages': '',
        'loan_refinancing_request_id': 0,
        'search_id_value': '',
        'input_mode': 'application_xid',
    }
    if request.POST:
        search_id_value = request.POST.get('search_id_value')
        input_mode = request.POST.get('input_mode')
        account = None
        loan = None
        if input_mode == 'application_xid':
            application = Application.objects.filter(application_xid=search_id_value).last()
            if application:
                account = application.account
                if not account and hasattr(application, 'loan'):
                    loan = application.loan
        elif input_mode == 'customer_id':
            customer = Customer.objects.filter(id=search_id_value).last()
            if customer:
                account = customer.account
                if not account:
                    loan = customer.loan_set.filter(loan_status__gte=LoanStatusCodes.CURRENT).last()
        elif input_mode == 'account_id':
            account = Account.objects.get_or_none(id=search_id_value)

        if account or loan:
            all_refinancing_product = (
                CovidRefinancingConst.waiver_products() + CovidRefinancingConst.reactive_products()
            )
            active_loan_refinancing_request = LoanRefinancingRequest.objects.filter(
                product_type__in=all_refinancing_product, account=account, loan=loan
            ).last()
            if active_loan_refinancing_request and active_loan_refinancing_request.status not in (
                CovidRefinancingConst.STATUSES.expired,
                CovidRefinancingConst.STATUSES.inactive,
            ):
                if (
                    active_loan_refinancing_request.status
                    == CovidRefinancingConst.STATUSES.activated
                ):
                    data[
                        'error_messages'
                    ] = "Customer memiliki program {} yang " "sedang berjalanan".format(
                        active_loan_refinancing_request.product_type
                    )
                else:
                    data['loan_refinancing_request_id'] = active_loan_refinancing_request.id
            else:
                data['error_messages'] = (
                    "Customer tidak memiliki program refinancing " "yang sedang berjalan saat ini"
                )
        else:
            data['error_messages'] = "ID tidak valid"
        data['search_id_value'] = search_id_value
        data['input_mode'] = input_mode

    template = loader.get_template(template_name)
    context = RequestContext(request, data)
    return HttpResponse(template.render(context))


def submit_manual_waiver_expiry(request):
    loan_refinancing_request_id = request.POST.get('loan_refinancing_request_id')
    loan_refinancing_request = (
        LoanRefinancingRequest.objects.filter(id=loan_refinancing_request_id)
        .exclude(status__in=CovidRefinancingConst.EXCLUDED_WAIVER_STATUS_FROM_EXPIRED)
        .last()
    )
    if not loan_refinancing_request:
        return JsonResponse({'status': 'failed', 'messages': 'Loan Refinancing not found'})
    if not manual_expire_refinancing_program(loan_refinancing_request):
        return JsonResponse(
            {'status': 'failed', 'messages': 'Gagal mengubah loan refinancing menjadi expired'}
        )

    return JsonResponse({
        'status': 'success',
        'messages': "berhasil mengubah status loan refinancing id {} ke "
                    "expired".format(loan_refinancing_request_id)
    })


@julo_login_required
def fc_agents_list(request):
    # Temporary Mock
    data = json.loads(request.body)
    if not data.get('fullname'):
        return JsonResponse({"status": 'failed', "message": "Can't search empty string"})

    agents = get_similar_field_collection_agents(data['fullname'])
    if not agents:
        return JsonResponse({"status": 'failed', "message": 'No agents found'})

    return JsonResponse(
        {
            "status": 'success',
            "data": {
                "agents": agents,
            },
        }
    )
