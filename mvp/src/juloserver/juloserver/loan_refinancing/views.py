from __future__ import absolute_import

from builtins import str
from builtins import range
import json
import logging

from babel.dates import format_date
from dateutil.relativedelta import relativedelta
from django.http.response import HttpResponseNotAllowed
from django.template import loader, RequestContext
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from django.shortcuts import redirect
from django.core.urlresolvers import reverse
from django.http import JsonResponse, HttpResponse
from datetime import datetime, timedelta
from django.shortcuts import render
from django.db import transaction
from django.db.models import Sum, F
from django.forms.models import model_to_dict
from .models import (
    LoanRefinancingRequest,
    LoanRefinancingOffer,
    LoanRefinancingMainReason,
    WaiverRequest,
    WaiverRecommendation,
    WaiverPaymentRequest,
    WaiverApproval, WaiverPaymentApproval)
from .services.customer_related import (
    process_encrypted_customer_data,
    populate_main_and_sub_unpaid_reasons
)
from .services.loan_related import (
    generate_new_tenure_offers,
    get_loan_from_application_id,
    get_current_payment_structures,
    create_refinancing_request,
    validate_covid_refinancing_data,
    store_covid_refinancing_data, get_unpaid_payments, construct_tenure_probabilities,
    get_loan_refinancing_request_by_uuid,
    get_r1_payment_structure,
    is_proactive_link_expired,
    recalculate_affordability,
    generate_recommended_tenure_extension_r1,
    get_r2_payment_structure, get_r3_payment_structure
)
from juloserver.julocore.python2.utils import py2round
from .services.loan_related2 import (get_not_allowed_products,
                                     get_loan_ids_for_bucket_tree,
                                     get_data_for_agent_portal,
                                     get_data_for_approver_portal)

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    success_response,
    not_found_response,
    general_error_response,
    forbidden_error_response
)

from juloserver.julo.models import FeatureSetting, Loan, PaymentMethod, Payment, PaymentEvent
from juloserver.payback.models import (WaiverTemp,
                                       WaiverPaymentTemp)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.exceptions import JuloException
from rest_framework.serializers import ValidationError

from .serializers import (
    LoanRefinancingOfferSerializer,
    CovidWaiverRequestSerializer,
    CovidRefinancingSerializer, CovidRefinancingOfferSimulationSerializer,
    RefinancingFormSubmitSerializer, RefinancingFormOfferSerializer,
    LoanRefinancingRequestSerializer, GenerateReactiveRefinancingSerializer,
    LoanRefinancingSelectedOfferSerializer,
    SubmitPhoneSerializer, OtpValidationSerializer,
    WaiverApprovalSerializer, WaiverPaymentApprovalSerializer,
    WaiverPaymentRequestSerializer, WaiverRequestSerializer)
from .services.notification_related import generate_image_for_refinancing_countdown
from .tasks import (send_email_refinancing_offer_selected,
                    send_sms_covid_refinancing_offer_selected,
                    send_pn_covid_refinancing_offer_selected,
                    send_slack_notification_for_waiver_approver,
                    )
from dashboard.constants import JuloUserRoles
from juloserver.portal.object import julo_login_required
from .services.refinancing_product_related import (
    construct_new_payments_for_r3,
    construct_new_payments_for_r2,
    get_refinancing_request_feature_setting_params,
    get_partially_paid_prerequisite_amount,
    generate_unique_uuid,
    generate_short_url_for_proactive_webview,
    get_max_tenure_extension_r1,
    proactive_offer_generation,
    get_waiver_recommendation
)
from .services.offer_related import (
    generated_default_offers,
    construct_loan_refinancing_request,
    get_offer_constructor_function,
    check_collection_offer_eligibility,
    validate_collection_offer_otp,
    reorder_recommendation,
    get_proactive_offers,
    get_existing_accepted_offer
)
from .utils import (
    convert_payment_format_to_plaform_for_agent,
    generate_status_and_tips_loan_refinancing_status,
    get_partner_product,
    get_waiver_is_need_approvals
)
from .constants import CovidRefinancingConst, NEW_WAIVER_APPROVER_GROUPS, WaiverApprovalDecisions
from ..account_payment.models import AccountPayment
from ..account_payment.services.account_payment_related import get_unpaid_account_payment
from ..apiv2.models import LoanRefinancingScore, LoanRefinancingScoreJ1
from ..julo.utils import display_rupiah
from .services.comms_channels import (
    send_loan_refinancing_request_approved_notification,
    send_loan_refinancing_request_offer_selected_notification,
    send_loan_refinancing_request_activated_notification)
from juloserver.minisquad.utils import collection_detokenize_sync_object_model
from ..payback.services.waiver import (
    get_remaining_interest,
    get_remaining_principal,
    get_remaining_late_fee,
    waive_late_fee_paid,
    waive_interest_paid,
    waive_principal_paid,
    get_partial_payments
)
from django.conf import settings
from juloserver.waiver.models import MultiplePaymentPTP
from juloserver.waiver.services.account_related import can_account_get_refinancing
from rest_framework.authtoken.models import Token
from juloserver.refinancing.services import (
    j1_automate_refinancing_offer,
    generate_new_payment_structure,
)
from juloserver.pii_vault.constants import (
    PiiSource,
    PiiVaultDataType,
)
from juloserver.minisquad.utils import collection_detokenize_sync_object_model

logger = logging.getLogger(__name__)


class RefinancingEligibility(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, encrypted_customer_data):
        is_data_processed, data = process_encrypted_customer_data(encrypted_customer_data)

        if not is_data_processed:
            return not_found_response(data)

        return success_response(data)


class RefinancingReason(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, encrypted_customer_data):
        is_data_processed, data = process_encrypted_customer_data(encrypted_customer_data)

        if not is_data_processed:
            return not_found_response(data)

        reason_dict = populate_main_and_sub_unpaid_reasons()

        return success_response(reason_dict)


class RefinancingOffer(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = LoanRefinancingOfferSerializer

    def post(self, request):
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        data = request.data
        application_id = data['application_id']
        loan = get_loan_from_application_id(application_id)
        is_refinancing_created, err_msg = create_refinancing_request(loan, data)

        user = self.request.user

        if user.id != loan.customer.user_id:
            return forbidden_error_response(
                data={'user_id': user.id},
                message=['User not allowed'])

        if not is_refinancing_created:
            return not_found_response(err_msg)

        return success_response()

    def get(self, request, encrypted_customer_data):
        is_data_processed, data = process_encrypted_customer_data(encrypted_customer_data)

        if not is_data_processed:
            return not_found_response(data)

        application_id = data['application']['id']
        loan = get_loan_from_application_id(application_id)

        if not loan:
            return not_found_response('Loan not found')

        user = self.request.user

        if user.id != loan.customer.user_id:
            return forbidden_error_response(
                data={'user_id': user.id},
                message=['User not allowed'])

        current_payments = get_current_payment_structures(loan)
        new_tenure_probabilities = generate_new_tenure_offers(loan)

        result = {
            'current_payment_structures': current_payments,
            'new_tenure_offers': new_tenure_probabilities
        }

        return success_response(result)


class CovidRefinancing(APIView):
    serializer_class = CovidRefinancingSerializer

    def post(self, request):
        if JuloUserRoles.PRODUCT_MANAGER not in request.user.groups.values_list('name', flat=True):
            return forbidden_error_response(
                'User harus mempunyai role sebagai Product Manager',
            )
        serializer = self.serializer_class(data=request.data)
        active_feature = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.COVID_REFINANCING,
            is_active=True).last()

        if not active_feature:
            return general_error_response(
                'Feature setting status tidak aktif',
            )
        serializer.is_valid(raise_exception=True)
        data_reader = serializer.validated_data['csv_file']
        is_valid_, data = validate_covid_refinancing_data(data_reader)

        if not is_valid_:
            return general_error_response(
                'sebagian data tidak valid harap perbaiki terlebih dahulu',
                data=data
            )

        num_of_rows = store_covid_refinancing_data(data['valid_data'], active_feature.parameters)
        return success_response({'number_of_row_processed': num_of_rows})


@julo_login_required
def covid_refinancing_web_portal_for_agent(request):
    portal_type = request.GET.get('portal_type', 'agent_portal')
    template_name = 'covid_loan_refinancing/refinancing_web_portal_agent.html'
    loan_id_list = []
    is_approver = False
    get_data_function = get_data_for_agent_portal

    user_groups = request.user.groups.values_list('name', flat=True)
    if any(approver_role in user_groups for approver_role in NEW_WAIVER_APPROVER_GROUPS):
        loan_id_list = get_loan_ids_for_bucket_tree(user_groups)
        is_approver = True
        if portal_type == 'approver_portal':
            template_name = 'covid_loan_refinancing/refinancing_web_portal_approver.html'
            get_data_function = get_data_for_approver_portal

    template = loader.get_template(template_name)
    data = {
        'ongoing_loan_data': [],
        'loan_id': '',
        'show': False,
        'ability_score': '',
        'willingness_score': '',
        'is_covid_risky': '',
        'max_extension': '',
        'bucket': '',
        'loan_refinancing_request_count': 0,
        'reasons': [],
        'loan_id_list': loan_id_list,
        'is_approver': is_approver,
        'is_julo_one': False
    }
    loan_id = request.GET.get('loan_id')
    if loan_id:
        data = get_data_function(data, loan_id)

    context = RequestContext(request, data)
    return HttpResponse(template.render(context))


def ajax_covid_refinancing_calculate_offer_simulation(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse({
            "status": "failed",
            "message": "non authorized user",
        })
    data = request.POST.dict()
    ser = CovidRefinancingOfferSimulationSerializer(data=data)
    ser.is_valid(raise_exception=True)
    active_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.COVID_REFINANCING,
        is_active=True).last()
    if not active_feature:
        return general_error_response(
            'Feature setting status tidak aktif',
        )
    loan_id = data['loan_id']
    selected_offer_recommendation = data['selected_offer_recommendation']
    loan = Loan.objects.get_or_none(pk=loan_id)
    new_affordability = recalculate_affordability(loan, data)
    feature_params = active_feature.parameters
    max_extension = 3 if loan.loan_duration > 9 \
        else feature_params['tenure_extension_rule']['MTL_%s' % loan.loan_duration]
    if selected_offer_recommendation.upper() != CovidRefinancingConst.PRODUCTS.r1:
        extension = int(data['tenure_extension']) if int(
            data['tenure_extension']) < max_extension else max_extension
    else:
        extension = int(data['tenure_extension'])
    loan_refinancing_request = LoanRefinancingRequest(
        cdate=timezone.localtime(timezone.now()),
        loan=loan,
        loan_duration= extension,
        affordability_value= new_affordability,
        product_type= data['selected_offer_recommendation'],
        expire_in_days= feature_params['email_expire_in_days'],
        new_income=int(data["new_income"].replace(',','')),
        new_expense=int(data["new_expense"].replace(',', '')),
    )
    # loan_refinancing_request.save()
    unpaid_payments = get_unpaid_payments(loan, order_by='payment_number')
    data_to_return = []
    if selected_offer_recommendation == 'r1':
        max_extension = get_max_tenure_extension_r1(loan_refinancing_request)
        new_loan_extension = max_extension + len(unpaid_payments)
        loan_refinancing_request.loan_duration = new_loan_extension
        index = unpaid_payments.count() + extension
        index = index if index < new_loan_extension else new_loan_extension
        new_payments = construct_tenure_probabilities(unpaid_payments=unpaid_payments,
                                                      max_tenure_extension=new_loan_extension,
                                                      loan_refinancing_request=loan_refinancing_request)[index]
        new_payments[0]['due_date'] = \
            timezone.localtime(loan_refinancing_request.cdate).date() + \
            timedelta(days=loan_refinancing_request.expire_in_days)

        data_to_return = convert_payment_format_to_plaform_for_agent(new_payments, is_object=False)
    elif selected_offer_recommendation == 'r2':
        new_payments = construct_new_payments_for_r2(loan_refinancing_request=loan_refinancing_request,
                                                     unpaid_payments=unpaid_payments)
        data_to_return = convert_payment_format_to_plaform_for_agent(new_payments, is_object=False)
    elif selected_offer_recommendation == 'r3':
        new_payments = construct_new_payments_for_r3(loan_refinancing_request=loan_refinancing_request,
                                                     unpaid_payments=unpaid_payments)
        data_to_return = convert_payment_format_to_plaform_for_agent(new_payments['payments'], is_object=False)
    return JsonResponse({
        'status': 'success',
        'data': data_to_return
    })


def covid_approval(request, encrypted_uuid):
    loan_refinancing_req = get_loan_refinancing_request_by_uuid(encrypted_uuid)
    if not loan_refinancing_req:
        return render(request, 'covid_refinancing_proactive.html', {'not_found': True})

    if loan_refinancing_req.status == CovidRefinancingConst.STATUSES.activated:
        return render(request, 'covid_refinancing_proactive.html', {'not_found': True})

    if is_proactive_link_expired(loan_refinancing_req):
        if loan_refinancing_req.status == CovidRefinancingConst.STATUSES.approved:
            loan_refinancing_req.update_safely(status=CovidRefinancingConst.STATUSES.inactive)

        if loan_refinancing_req.status in list(CovidRefinancingConst.NEW_PROACTIVE_STATUSES.__dict__.values()):
            loan_refinancing_req.update_safely(status=CovidRefinancingConst.STATUSES.inactive)
        return render(request, 'covid_refinancing_proactive.html', {'not_found': True})

    if loan_refinancing_req.account_id:
        allow_refinancing_program, _ = can_account_get_refinancing(loan_refinancing_req.account_id)
        if not allow_refinancing_program:
            return render(request, 'covid_refinancing_proactive.html', {'not_found': True})

    product = loan_refinancing_req.product_type
    is_julo_one = True if loan_refinancing_req.account else False
    loan = loan_refinancing_req.loan
    payment_method_filter = {'is_primary': True}
    if is_julo_one:
        application = loan_refinancing_req.account.application_set.last()
        loan = loan_refinancing_req.account.loan_set.last()
        payment_method_filter['customer'] = application.customer
    else:
        payment_method_filter['loan'] = loan
        application = loan.application

    customer = application.customer
    payment_method = PaymentMethod.objects.filter(**payment_method_filter).last()

    customer_detokenized = collection_detokenize_sync_object_model(
        PiiSource.CUSTOMER,
        customer,
        customer.customer_xid,
        ['email'],
    )
    application_detokenized = collection_detokenize_sync_object_model(
        PiiSource.APPLICATION,
        application,
        customer.customer_xid,
        ['fullname'],
    )
    payment_method_detokenized = collection_detokenize_sync_object_model(
        PiiSource.PAYMENT_METHOD,
        payment_method,
        None,
        ['virtual_account'],
        PiiVaultDataType.KEY_VALUE,
    )

    if loan_refinancing_req.status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email:
        loan_refinancing_req.update_safely(
            status=CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit,
            form_viewed_ts=timezone.localtime(timezone.now())
        )
        loan_refinancing_req.refresh_from_db()
    if loan_refinancing_req.status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit:
        main_reasons = LoanRefinancingMainReason.objects.filter(
            is_active=True, reason__in=CovidRefinancingConst.NEW_REASON)
        context = dict(
            fullname_with_title=application.fullname_with_title,
            url=CovidRefinancingConst.URL + 'refinancing_form_submit/{}/'.format(encrypted_uuid),
            main_reasons=main_reasons,
            email=customer_detokenized.email,
            fullname=application_detokenized.fullname,
        )
        return render(request, 'covid_refinancing/covid_proactive_form.html', context)

    if loan_refinancing_req.status == CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer:
        loan_refinancing_offers = get_proactive_offers(loan_refinancing_req)
        if len(loan_refinancing_offers) < 1:
            return render(request, 'covid_refinancing/404.html')

        recommendation_offer = []
        if is_julo_one:
            payments = AccountPayment.objects.filter(
                account=loan_refinancing_req.account).not_paid_active().order_by('due_date')
        else:
            payments = Payment.objects.filter(
                loan=loan_refinancing_req.loan).not_paid_active().order_by('payment_number')

        all_outstanding_amount = 0
        total_due_outstanding_amount = 0
        for payment in payments:
            all_outstanding_amount = all_outstanding_amount + int(payment.due_amount)
            dpd = payment.due_late_days if not is_julo_one else payment.dpd
            if dpd > 0:
                total_due_outstanding_amount = total_due_outstanding_amount + int(payment.due_amount)

        for idx, loan_refinancing_offer in enumerate(loan_refinancing_offers):
            if loan_refinancing_offer.product_type == CovidRefinancingConst.PRODUCTS.r1:
                # hide the offer if the recommended loan duration is 0
                if not loan_refinancing_offer.loan_duration:
                    continue

                new_payment_structures, _, real_loan_duration = get_r1_payment_structure(
                    loan_refinancing_req, loan_refinancing_offer.loan_duration)
                new_payment_structures[real_loan_duration][0]['due_date'] = timezone.localtime(
                    loan_refinancing_offer.cdate).date() + timedelta(
                        days=loan_refinancing_req.expire_in_days)
                real_duration_structure = new_payment_structures[real_loan_duration]

                total_payments = 0
                for payment in real_duration_structure:
                    total_payments = total_payments + int(payment['due_amount'])

                first_payment_number = 1
                if real_duration_structure:
                    first_payment_number = real_duration_structure[0]['payment_number']

                offer_dict = dict(
                    payments=new_payment_structures[real_loan_duration],
                    total_payments=display_rupiah(total_payments),
                    loan_investment=display_rupiah(loan.installment_amount),
                    prerequisite_amount=display_rupiah(loan_refinancing_offer.prerequisite_amount),
                    first_payment_number=first_payment_number,
                    index=idx + 1,
                    product=loan_refinancing_offer.product_type,
                    id=loan_refinancing_offer.id,
                    product_name="Peringanan Angsuran",
                    category="refinancing"
                )
            elif loan_refinancing_offer.product_type in (
                    CovidRefinancingConst.PRODUCTS.r2,
                    CovidRefinancingConst.PRODUCTS.r3
            ):
                # can easy remove if r3 is decided to show on proactive
                if loan_refinancing_offer.product_type == CovidRefinancingConst.PRODUCTS.r3:
                    continue

                new_payment_structures = []
                if loan_refinancing_offer.product_type == CovidRefinancingConst.PRODUCTS.r2:
                    new_payment_structures = get_r2_payment_structure(
                        loan_refinancing_req,
                        loan_duration_extension=loan_refinancing_offer.loan_duration
                    )
                    product_name = 'Perpanjangan Angsuran dengan Biaya bunga'
                else:
                    new_payment_structures = get_r3_payment_structure(
                        loan_refinancing_req,
                        loan_duration_extension=loan_refinancing_offer.loan_duration
                    )['payments']
                    product_name = 'Perpanjangan Angsuran dengan Biaya Admin'

                total_payments = 0
                for payment in new_payment_structures:
                    total_payments = total_payments + int(payment['due_amount'])

                first_payment_number = 1
                if new_payment_structures:
                    first_payment_number = new_payment_structures[0]['payment_number']

                offer_dict = dict(
                    payments=new_payment_structures,
                    total_payments=display_rupiah(total_payments),
                    loan_investment=display_rupiah(loan.installment_amount),
                    prerequisite_amount=display_rupiah(loan_refinancing_offer.prerequisite_amount),
                    first_payment_number=first_payment_number,
                    index=idx + 1,
                    product=loan_refinancing_offer.product_type,
                    id=loan_refinancing_offer.id,
                    product_name=product_name,
                    category="refinancing"
                )

            else:
                product_name = 'Pembayaran pinjaman dengan diskon denda'
                wording_product = 'Sisa Angsuran yang sudah jatuh tempo'
                total_payments = display_rupiah(total_due_outstanding_amount)
                if loan_refinancing_offer.product_type == CovidRefinancingConst.PRODUCTS.r4:
                    product_name = 'Pelunasan dengan Diskon'
                    wording_product = 'Sisa Hutang'
                    total_payments = display_rupiah(all_outstanding_amount)
                elif loan_refinancing_offer.product_type == CovidRefinancingConst.PRODUCTS.r6:
                    product_name = 'Pembayaran pinjaman dengan diskon bunga dan denda'

                offer_dict = dict(
                    prerequisite_amount=display_rupiah(loan_refinancing_offer.prerequisite_amount),
                    total_payments=total_payments,
                    index=idx + 1,
                    product=loan_refinancing_offer.product_type,
                    id=loan_refinancing_offer.id,
                    product_name=product_name,
                    wording_product=wording_product,
                    category="waiver"
                )

            recommendation_offer.append(offer_dict)

        context = dict(
            fullname_with_title=application.fullname_with_title,
            fullname=application_detokenized.fullname,
            email=customer_detokenized.email,
            url=CovidRefinancingConst.URL + 'automate_refinancing_offer/{}/'.format(encrypted_uuid),
            all_outstanding_amount=all_outstanding_amount,
            recommendation_offers=recommendation_offer,
        )
        return render(request, 'covid_refinancing/covid_proactive_offer.html', context)

    if loan_refinancing_req.status in CovidRefinancingConst.PROACTIVE_CONFIRMATION_EMAIL_STATUSES:
        payments = None
        if is_julo_one:
            unpaid_payments = get_unpaid_account_payment(loan_refinancing_req.account.id)
        else:
            unpaid_payments = get_unpaid_payments(loan_refinancing_req.loan, order_by='payment_number')

        account = loan_refinancing_req.account
        if product == CovidRefinancingConst.PRODUCTS.r1:
            if is_julo_one:
                max_extension = get_max_tenure_extension_r1(loan_refinancing_req)
                new_loan_extension = max_extension + len(unpaid_payments)
                index = unpaid_payments.count() + loan_refinancing_req.loan_duration
                index = index if index < new_loan_extension else new_loan_extension
                _, payments = generate_new_payment_structure(
                    account, loan_refinancing_req,
                    chosen_loan_duration=index)
            else:
                new_payment_structures, _, real_loan_duration = get_r1_payment_structure(
                    loan_refinancing_req, loan_refinancing_req.loan_duration)
                payments = new_payment_structures[real_loan_duration]
                payments[0]['due_date'] = timezone.localtime(
                    loan_refinancing_req.form_submitted_ts).date() + timedelta(
                    days=loan_refinancing_req.expire_in_days)

            payments[0]['due_amount'] = loan_refinancing_req.last_prerequisite_amount

        elif product == CovidRefinancingConst.PRODUCTS.r2:
            if is_julo_one:
                _, payments = generate_new_payment_structure(
                    account, loan_refinancing_req,
                    count_unpaid_account_payments=len(unpaid_payments),
                )
            else:
                payments = construct_new_payments_for_r2(loan_refinancing_req, unpaid_payments)
            payments[0]['due_amount'] = loan_refinancing_req.last_prerequisite_amount

        elif product == CovidRefinancingConst.PRODUCTS.r3:
            if is_julo_one:
                _, new_payments = generate_new_payment_structure(
                    account, loan_refinancing_req,
                    count_unpaid_account_payments=len(unpaid_payments),
                )
            else:
                new_payments = construct_new_payments_for_r3(
                    loan_refinancing_req, unpaid_payments)

            payments = new_payments['payments']
            payments[0]['due_amount'] = loan_refinancing_req.last_prerequisite_amount

        total_payments = 0
        first_payment_number = 1
        old_payment_amount = 0
        is_r4_flag = True
        if product in CovidRefinancingConst.reactive_products():
            product_category = "reactive"
            if is_julo_one:
                old_monthly_installment_amount = 0
                for loan in loan_refinancing_req.account.get_all_active_loan():
                    old_monthly_installment_amount += loan.installment_amount
            else:
                payment = Payment.objects.filter(
                    loan=loan_refinancing_req.loan).not_paid_active().order_by('payment_number').first()
                old_monthly_installment_amount = loan_refinancing_req.loan.installment_amount
                first_payment_number = payment.payment_number
            for payment in payments:
                total_payments = total_payments + int(payment['due_amount'])

        else:
            product_category = "waiver"
            if is_julo_one:
                old_monthly_installment_amount = AccountPayment.objects.filter(
                    account=loan_refinancing_req.account).not_paid_active().aggregate(
                    Sum('due_amount')
                )['due_amount__sum'] or 0
            else:
                old_monthly_installment_amount = Payment.objects.filter(
                    loan=loan_refinancing_req.loan).not_paid_active().aggregate(
                        Sum('due_amount')
                    )['due_amount__sum'] or 0
            if product in [CovidRefinancingConst.PRODUCTS.r5, CovidRefinancingConst.PRODUCTS.r6]:
                is_r4_flag = False
                waiver_request_filter = dict(
                    program_name=loan_refinancing_req.product_type.lower()
                )
                if is_julo_one:
                    waiver_request_filter['account'] = loan_refinancing_req.account
                else:
                    waiver_request_filter['loan'] = loan_refinancing_req.loan
                old_payment_amount = WaiverRequest.objects.filter(**waiver_request_filter).\
                    latest('cdate').outstanding_amount

        date_ref = timezone.localtime(loan_refinancing_req.cdate).date()
        if loan_refinancing_req.form_submitted_ts:
            date_ref = timezone.localtime(loan_refinancing_req.form_submitted_ts).date()

        context = dict(
            product_type=loan_refinancing_req.product_type.upper(),
            prerequisite_amount=loan_refinancing_req.last_prerequisite_amount,
            first_due_date=date_ref + timedelta(days=loan_refinancing_req.expire_in_days),
            payments=payments,
            va_number=payment_method_detokenized.virtual_account,
            bank_code=payment_method.bank_code,
            email=customer_detokenized.email,
            bank_name=payment_method.payment_method_name,
            fullname_with_title=application.fullname_with_title,
            fullname=application_detokenized.fullname,
            old_monthly_installment_amount=old_monthly_installment_amount,
            total_payments=total_payments,
            first_payment_number=first_payment_number,
            old_payment_amount=old_payment_amount,
            url=CovidRefinancingConst.URL + 'refinancing_offer_approve/{}/'.format(encrypted_uuid),
            is_r4_flag=is_r4_flag,
        )
        waiver_request = WaiverRequest.objects.filter(
            account=loan_refinancing_req.account).last()
        if waiver_request:
            context['waiver_validity_date'] = waiver_request.waiver_validity_date
        refinancing_status = loan_refinancing_req.status.replace(" ", "_").lower()
        return render(
            request, 'covid_refinancing/covid_%s_%s.html' % (refinancing_status, product_category), context)


def refinancing_form_submit(request, encrypted_uuid):
    url = reverse('loan_refinancing:covid_approval', kwargs={'encrypted_uuid': encrypted_uuid})
    loan_refinancing_req = get_loan_refinancing_request_by_uuid(encrypted_uuid)
    if not loan_refinancing_req:
        return redirect(url)

    serializer = RefinancingFormSubmitSerializer(data=request.POST.dict())
    if not serializer.is_valid(raise_exception=True):
        return redirect(url)

    if loan_refinancing_req.loan:
        unpaid_payments = get_unpaid_payments(loan_refinancing_req.loan, order_by='payment_number')
    else:
        unpaid_payments = get_unpaid_account_payment(loan_refinancing_req.account.id)
    if not unpaid_payments:
        return render(request, 'covid_refinancing/404.html')

    # change affordability
    serializer_data = serializer.data
    new_affordability = recalculate_affordability(
        loan_refinancing_req.loan, serializer_data, loan_refinancing_req.account)
    with transaction.atomic():
        main_reason = LoanRefinancingMainReason.objects.get(pk=int(serializer_data["main_reason"]))
        loan_refinancing_req.update_safely(
            new_income=int(serializer_data["new_income"].replace(',', '')),
            new_expense=int(serializer_data["new_expense"].replace(',', '')),
            # mobile_phone_1=serializer_data["mobile_phone_1"],
            # mobile_phone_2=serializer_data["mobile_phone_2"],
            form_submitted_ts=timezone.localtime(timezone.now()),
            loan_refinancing_main_reason=main_reason,
            status=CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer,
            affordability_value=new_affordability,
            channel=CovidRefinancingConst.CHANNELS.proactive
        )
        # calculate and generate offer
        recommended_product = proactive_offer_generation(loan_refinancing_req)
        if not recommended_product:
            return render(request, 'covid_refinancing_proactive.html', {'not_found': True})

        generated_default_offers(loan_refinancing_req, recommended_product, is_proactive_offer=True)

    return redirect(url)


def ajax_covid_refinancing_submit_waiver_request(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse({
            "status": "failed",
            "message": "non authorized user",
        })
    data = request.POST.dict()
    serializer = CovidWaiverRequestSerializer(data=data)
    if not serializer.is_valid():
        message = serializer.errors
        return JsonResponse({"status": "failed",
                            "message": str(message),
                            })

    data = serializer.data

    create_waiver = True
    loan = Loan.objects.get_or_none(pk=data['loan_id'])
    application = loan.application
    fullname = collection_detokenize_sync_object_model(
        'application', application, application.customer.customer_xid, ['fullname']
    ).fullname
    message = (
        "Permohonan Waiver untuk <strong>%s (ID: %s)</strong> telah dilanjutkan ke proses berikutnya. JULO akan mengirimkan email/PN/SMS secara otomatis kepada customer tentang detil program ini. Mohon ingatkan customer untuk membuka pesan yang JULO kirimkan."
        % (fullname, application.id)
    )

    loan_refinancing_request = LoanRefinancingRequest.objects.filter(loan=data['loan_id']).last()
    if loan_refinancing_request:
        created_date = format_date(loan_refinancing_request.cdate.date(), 'dd-MM-yyyy', locale='id_ID')
        if loan_refinancing_request.status in CovidRefinancingConst.REACTIVE_OFFER_STATUS_SELECTED_OR_APPROVED:
            create_waiver = False
            date_reference = loan_refinancing_request.form_submitted_ts
            expiration_date = date_reference + timedelta(days=loan_refinancing_request.expire_in_days)

            payment = Payment.objects.filter(loan=loan_refinancing_request.loan).not_paid_active().first()
            all_payments_in_waive_period = PaymentEvent.objects.filter(
                event_type="payment",
                cdate__gte=date_reference,
                event_date__gte=date_reference,
                event_date__lte=expiration_date,
                payment=payment
            ).aggregate(
                total=Sum('event_payment')
            )

            if all_payments_in_waive_period['total']:
                message = "<strong>%s (ID: %s)</strong> sudah mengajukan program keringanan <strong>%s</strong> pada tanggal <strong>%s</strong> dan belum melakukan pembayarannya secara penuh." % (application.fullname, application.id, loan_refinancing_request.product_type.upper(), created_date)
            else:
                message = "<strong>%s (ID: %s)</strong> sudah mengajukan program keringanan <strong>%s</strong> pada tanggal <strong>%s</strong> dan sudah melakukan konfirmasi atau sudah memilih detail program tersebut." % (application.fullname, application.id, loan_refinancing_request.product_type.upper(), created_date)

        elif loan_refinancing_request.status == CovidRefinancingConst.STATUSES.activated:
            create_waiver = False
            message = "<strong>%s (ID: %s)</strong> sudah mengajukan program keringanan <strong>%s</strong> pada tanggal <strong>%s</strong> dan program telah aktif." % (application.fullname, application.id, loan_refinancing_request.product_type.upper(), created_date)

    if not create_waiver:
        return JsonResponse({
            "status": "failed",
            "message": message,
        })

    is_need_approval_tl, \
        is_need_approval_supervisor, \
        is_need_approval_colls_head, \
        is_need_approval_ops_head = get_waiver_is_need_approvals(data)

    if not (
        is_need_approval_tl
        or is_need_approval_supervisor
        or is_need_approval_colls_head
        or is_need_approval_ops_head
    ):
        data['is_automated'] = True

    active_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.COVID_REFINANCING,
        is_active=True).last()

    if not active_feature:
        return JsonResponse({
            'status': 'failed',
            'message': 'Feature setting status tidak aktif'
        })
    loan_refinancing_request = LoanRefinancingRequest.objects.filter(loan=loan).last()
    waiver_request = None
    waiver_temp = None
    with transaction.atomic():
        today = timezone.localtime(timezone.now())
        validity_date = datetime.strptime(data['waiver_validity_date'], '%Y-%m-%d')
        validity_in_days = abs((today.date() - validity_date.date()).days)

        if data['is_customer_confirmed']:
            waiver_recommendation = WaiverRecommendation.objects.filter(
                pk=int(data['waiver_recommendation_id'])
            ).last()
            data['selected_payments_waived'] = json.loads(data['selected_payments_waived'])
            total_selected_payment = len(data['selected_payments_waived']['waiver'])
            last_selected_payment = data['selected_payments_waived']['waiver'][total_selected_payment - 1]
            waiver_request = WaiverRequest.objects.create(
                loan=loan, agent_name=request.user.username, bucket_name=data['bucket_name'],
                program_name=data['selected_program_name'], is_covid_risky=data['is_covid_risky'],
                outstanding_amount=data['outstanding_amount'],
                unpaid_principal=data['unpaid_principal'], unpaid_interest=data['unpaid_interest'],
                unpaid_late_fee=data['unpaid_late_fee'],
                waiver_validity_date=data['waiver_validity_date'], reason=data['reason'],
                ptp_amount=data['ptp_amount'],
                loan_refinancing_request=loan_refinancing_request,
                is_need_approval_tl=is_need_approval_tl,
                is_need_approval_supervisor=is_need_approval_supervisor,
                is_need_approval_colls_head=is_need_approval_colls_head,
                is_need_approval_ops_head=is_need_approval_ops_head,
                waived_payment_count=data['waived_payment_count'],
                is_automated=data['is_automated'],
                requested_late_fee_waiver_percentage=data[
                    "requested_late_fee_waiver_percentage"] + "%",
                requested_interest_waiver_percentage=data[
                    "requested_interest_waiver_percentage"] + "%",
                requested_principal_waiver_percentage=data[
                    "requested_principal_waiver_percentage"] + "%",
                requested_late_fee_waiver_amount=int(
                    data["requested_late_fee_waiver_amount"]
                ),
                requested_interest_waiver_amount=int(
                    data["requested_interest_waiver_amount"]
                ),
                requested_principal_waiver_amount=int(
                    data["requested_principal_waiver_amount"]
                ),
                waiver_recommendation=waiver_recommendation,
                agent_notes=data["agent_notes"],
                first_waived_payment_id=int(data["first_waived_payment"]),
                last_waived_payment_id=int(data["last_waived_payment"]),
                requested_waiver_amount=int(data["requested_waiver_amount"]),
                remaining_amount_for_waived_payment=int(data["remaining_amount_for_waived_payment"]),
                last_payment_number=int(last_selected_payment["payment_number"]),
                waiver_type="unpaid",
                is_multiple_ptp_payment=data["is_multiple_ptp_payment"],
                number_of_multiple_ptp_payment=data["number_of_multiple_ptp_payment"],
            )

            waiver_payment_request_data = []
            waiver_request.waiver_payment_request.all().delete()
            for idx in range(len(data['selected_payments_waived']['waiver'])):
                waiver_payment_request_data.append(
                    WaiverPaymentRequest(
                        waiver_request=waiver_request,
                        payment_id=int(
                            data['selected_payments_waived']['waiver'][idx]['payment_id']),
                        outstanding_late_fee_amount=data[
                            'selected_payments_waived']['outstanding'][idx]['late_fee'],
                        outstanding_interest_amount=data[
                            'selected_payments_waived']['outstanding'][idx]['interest'],
                        outstanding_principal_amount=data[
                            'selected_payments_waived']['outstanding'][idx]['principal'],
                        total_outstanding_amount=data[
                            'selected_payments_waived']['outstanding'][idx]['need_to_pay'],
                        requested_late_fee_waiver_amount=data[
                            'selected_payments_waived']['waiver'][idx]['late_fee'],
                        requested_interest_waiver_amount=data[
                            'selected_payments_waived']['waiver'][idx]['interest'],
                        requested_principal_waiver_amount=data[
                            'selected_payments_waived']['waiver'][idx]['principal'],
                        total_requested_waiver_amount=data[
                            'selected_payments_waived']['waiver'][idx]['total_waiver'],
                        remaining_late_fee_amount=data[
                            'selected_payments_waived']['remaining'][idx]['late_fee'],
                        remaining_interest_amount=data[
                            'selected_payments_waived']['remaining'][idx]['interest'],
                        remaining_principal_amount=data[
                            'selected_payments_waived']['remaining'][idx]['principal'],
                        total_remaining_amount=data[
                            'selected_payments_waived']['remaining'][idx]['remaining_installment'],
                    )
                )

            if waiver_payment_request_data:
                WaiverPaymentRequest.objects.bulk_create(waiver_payment_request_data)

            loan_refinancing_req_dict = dict(
                prerequisite_amount=data['ptp_amount'],
                total_latefee_discount=data['requested_late_fee_waiver_amount'],
                expire_in_days=validity_in_days,
                product_type=data['selected_program_name'].upper(),
                status=CovidRefinancingConst.STATUSES.offer_selected,
                loan_duration=0
            )

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
                                remaining_amount=\
                                    data['multiple_payment_ptp'][idx]["promised_payment_amount"],
                            )
                        )
                        multiple_payment_ptp_data.append(
                            MultiplePaymentPTP(**data['multiple_payment_ptp'][idx])
                        )

                    if multiple_payment_ptp_data:
                        MultiplePaymentPTP.objects.bulk_create(multiple_payment_ptp_data)

            if data['is_automated']:
                waiver_temp = WaiverTemp.objects.create(
                    loan=loan,
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
                for idx in range(len(data['selected_payments_waived']['waiver'])):
                    waiver_payment_temp_data.append(
                        WaiverPaymentTemp(
                            waiver_temp=waiver_temp,
                            payment_id=int(
                                data['selected_payments_waived']['waiver'][idx]['payment_id']),
                            late_fee_waiver_amount=data[
                                'selected_payments_waived']['waiver'][idx]['late_fee'],
                            interest_waiver_amount=data[
                                'selected_payments_waived']['waiver'][idx]['interest'],
                            principal_waiver_amount=data[
                                'selected_payments_waived']['waiver'][idx]['principal'],

                        )
                    )
                WaiverPaymentTemp.objects.bulk_create(waiver_payment_temp_data)
                loan_refinancing_req_dict['status'] = CovidRefinancingConst.STATUSES.approved

        else:
            waiver_request = True
            message = "Loan Refinancing Request berhasil diubah"
            update_existing_offer_dict = dict()
            loan_refinancing_req_dict = dict()

        loan_refinancing_req_dict['new_income'] = int(data["new_income"].replace(',', ''))
        loan_refinancing_req_dict['new_expense'] = int(data["new_expense"].replace(',', ''))
        loan_refinancing_req_dict['form_submitted_ts'] = today
        loan_refinancing_req_dict['affordability_value'] = recalculate_affordability(loan, data)
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
            is_latest=True
        )
        existing_offer = LoanRefinancingOffer.objects.filter(**loan_refinancing_offer_dict).last()
        if not existing_offer:
            latest_offer = LoanRefinancingOffer.objects.filter(
                loan_refinancing_request=loan_refinancing_request,
                product_type=data['selected_program_name'].upper(),
                generated_by__isnull=True,
                is_latest=True,
                is_proactive_offer=False)\
                .last()
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
                generated_by=request.user
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
                is_proactive_offer=True
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

    if loan_refinancing_request.status == CovidRefinancingConst.STATUSES.approved and \
            loan_refinancing_request.product_type:
        send_loan_refinancing_request_approved_notification(loan_refinancing_request)

    is_r4_product = data['selected_program_name'].upper() == r4_product
    if data['is_customer_confirmed'] and data['is_automated'] and waiver_temp and is_r4_product:
        loan_refinancing_request.refresh_from_db()
        if loan_refinancing_request.status == CovidRefinancingConst.STATUSES.offer_selected:
            send_email_refinancing_offer_selected.delay(loan_refinancing_request.id)
            send_pn_covid_refinancing_offer_selected.delay(loan_refinancing_request.id)
            send_sms = True
            comms_list = loan_refinancing_request.comms_channel_list()
            if loan_refinancing_request.channel == CovidRefinancingConst.CHANNELS.reactive and \
                    CovidRefinancingConst.COMMS_CHANNELS.sms not in comms_list:
                send_sms = False

            if send_sms:
                send_sms_covid_refinancing_offer_selected.delay(loan_refinancing_request.id)

    return JsonResponse({
        'status': 'success' if waiver_request else 'failed',
        'message': message if waiver_request else 'Mohon maaf. Silakan coba lagi'
    })


def automate_refinancing_offer(request, encrypted_uuid):
    url = reverse('loan_refinancing:covid_approval', kwargs={'encrypted_uuid': encrypted_uuid})
    loan_refinancing_req = get_loan_refinancing_request_by_uuid(encrypted_uuid)
    if not loan_refinancing_req:
        return redirect(url)

    serializer = RefinancingFormOfferSerializer(data=request.POST.dict())
    if not serializer.is_valid():
        return redirect(url)

    if loan_refinancing_req.account:
        j1_automate_refinancing_offer(serializer.data, loan_refinancing_req)
        return redirect(url)

    today = timezone.localtime(timezone.now())
    serializer_data = serializer.data
    offer_id = int(serializer_data["product_id_1"])
    if "product_id_2" in serializer_data and int(serializer_data["product_id_2"]) != 0:
        offer_id = int(serializer_data["product_id_2"])
    loan_refinancing_offer = LoanRefinancingOffer.objects.get(pk=offer_id)
    loan_refinancing_offer.update_safely(
        is_accepted=True,
        offer_accepted_ts=today,
        selected_by=loan_refinancing_req.loan.customer.user,
    )

    other_offer = LoanRefinancingOffer.objects.filter(
        loan_refinancing_request=loan_refinancing_req,
        product_type=loan_refinancing_offer.product_type,
        prerequisite_amount=loan_refinancing_offer.prerequisite_amount,
        loan_duration=loan_refinancing_offer.loan_duration,
        generated_by=loan_refinancing_offer.generated_by,
        latefee_discount_percentage=loan_refinancing_offer.latefee_discount_percentage,
        interest_discount_percentage=loan_refinancing_offer.interest_discount_percentage,
        principal_discount_percentage=loan_refinancing_offer.principal_discount_percentage
    ).exclude(id=offer_id).last()

    target_channel = CovidRefinancingConst.CHANNELS.proactive
    if other_offer and not other_offer.is_proactive_offer:
        target_channel = CovidRefinancingConst.CHANNELS.reactive

    loan_refinancing_req.update_safely(
        status=CovidRefinancingConst.STATUSES.offer_selected,
        product_type=loan_refinancing_offer.product_type,
        prerequisite_amount=loan_refinancing_offer.prerequisite_amount,
        total_latefee_discount=loan_refinancing_offer.total_latefee_discount,
        loan_duration=loan_refinancing_offer.loan_duration,
        channel=target_channel
    )
    if serializer_data["product_type"] in CovidRefinancingConst.waiver_products():
        loan = loan_refinancing_req.loan
        application = loan.application
        loan_refinancing_score = LoanRefinancingScore.objects.filter(loan=loan).last()
        unpaid_payments = get_unpaid_payments(loan, order_by='payment_number')
        payment = unpaid_payments.first()
        last_payment = unpaid_payments.last()
        max_payment_number = last_payment.payment_number
        unpaid_payment_count = len(unpaid_payments)
        bucket_name = 'Bucket {}'.format(payment.bucket_number)
        if serializer_data["product_type"] in CovidRefinancingConst.waiver_without_r4():
            overdue_payment = Payment.objects.filter(
                loan=loan_refinancing_req.loan).overdue().filter(is_restructured=False) \
                .order_by('-payment_number').first()
            if overdue_payment:
                max_payment_number = overdue_payment.payment_number
            else:
                max_payment_number = payment.payment_number
            unpaid_payments = Payment.objects.filter(pk__gte=payment.id, pk__lte=last_payment.id)

        remaining_interest = get_remaining_interest(
            payment, True, max_payment_number=max_payment_number)
        remaining_principal = get_remaining_principal(
            payment, True, max_payment_number=max_payment_number)
        remaining_late_fee = get_remaining_late_fee(
            payment, True, max_payment_number=max_payment_number)

        total_discount = loan_refinancing_offer.total_latefee_discount + \
            loan_refinancing_offer.total_interest_discount + \
            loan_refinancing_offer.total_principal_discount
        outstanding_amount = loan_refinancing_offer.prerequisite_amount + total_discount
        if serializer_data["product_type"] in (
                CovidRefinancingConst.PRODUCTS.r5, CovidRefinancingConst.PRODUCTS.r6):
            remaining_principal = 0
            if serializer_data["product_type"] == CovidRefinancingConst.PRODUCTS.r5:
                remaining_interest = 0

        waiver_validity_date = today + relativedelta(days=loan_refinancing_offer.validity_in_days)
        product_line_code = application.product_line_code
        requested_late_fee_percentage = loan_refinancing_offer.latefee_discount_percentage
        requested_interest_percentage = loan_refinancing_offer.interest_discount_percentage
        requested_principal_percentage = loan_refinancing_offer.principal_discount_percentage
        waiver_request_dict = dict(
            loan=loan_refinancing_req.loan,
            last_waived_payment=last_payment,
            agent_name=None,
            bucket_name=bucket_name,
            program_name=serializer_data["product_type"].lower(),
            is_covid_risky=loan_refinancing_score.is_covid_risky_boolean,
            outstanding_amount=outstanding_amount,
            unpaid_principal=remaining_principal,
            unpaid_interest=remaining_interest,
            unpaid_late_fee=remaining_late_fee,
            requested_late_fee_waiver_percentage=requested_late_fee_percentage,
            requested_late_fee_waiver_amount=loan_refinancing_offer.total_latefee_discount,
            requested_interest_waiver_percentage=requested_interest_percentage,
            requested_interest_waiver_amount=loan_refinancing_offer.total_interest_discount,
            requested_principal_waiver_percentage=requested_principal_percentage,
            requested_principal_waiver_amount=loan_refinancing_offer.total_principal_discount,
            waiver_validity_date=waiver_validity_date,
            reason=loan_refinancing_req.loan_refinancing_main_reason.reason,
            ptp_amount=loan_refinancing_offer.prerequisite_amount,
            is_need_approval_tl=False,
            is_need_approval_supervisor=False,
            is_need_approval_colls_head=False,
            is_need_approval_ops_head=False,
            is_automated=True,
            partner_product=get_partner_product(product_line_code)
        )

        waiver_request = WaiverRequest.objects.create(**waiver_request_dict)
        waiver_payment_request_data = []
        for payment in unpaid_payments:
            late_fee = py2round(
                (float(requested_late_fee_percentage.replace('%', '')) / float(100)) * float(
                    payment.late_fee_amount))
            interest = py2round(
                (float(requested_interest_percentage.replace('%', '')) / float(100)) * float(
                    payment.installment_interest))
            principal = py2round(
                (float(requested_principal_percentage.replace('%', '')) / float(100)) * float(
                    payment.installment_principal))
            total = late_fee + interest + principal
            waiver_payment_dict = dict(
                waiver_request=waiver_request,
                payment=payment,
                outstanding_late_fee_amount=0,
                outstanding_interest_amount=0,
                outstanding_principal_amount=0,
                total_outstanding_amount=0,
                requested_late_fee_waiver_amount=late_fee,
                requested_interest_waiver_amount=interest,
                requested_principal_waiver_amount=principal,
                total_requested_waiver_amount=total,
                remaining_late_fee_amount=0,
                remaining_interest_amount=0,
                remaining_principal_amount=0,
                total_remaining_amount=0,
                is_paid_off_after_ptp=True,
            )
            waiver_payment_request_data.append(WaiverPaymentRequest(**waiver_payment_dict))
        WaiverPaymentRequest.objects.bulk_create(waiver_payment_request_data)

        waiver_temp = WaiverTemp.objects.create(
            loan=loan_refinancing_req.loan, account=loan_refinancing_req.account,
            late_fee_waiver_amt=loan_refinancing_offer.total_latefee_discount,
            interest_waiver_amt=loan_refinancing_offer.total_interest_discount,
            principal_waiver_amt=loan_refinancing_offer.total_principal_discount,
            need_to_pay=loan_refinancing_offer.prerequisite_amount,
            waiver_date=today.date(),
            late_fee_waiver_note="Loan Refinancing Proactive",
            interest_waiver_note="Loan Refinancing Proactive",
            principal_waiver_note="Loan Refinancing Proactive",
            valid_until=today + timedelta(days=loan_refinancing_offer.validity_in_days),
            waiver_request=waiver_request,
        )
        waiver_payment_temp_data = []
        for payment in unpaid_payments:
            waiver_payment_temp_data.append(
                WaiverPaymentTemp(
                    waiver_temp=waiver_temp,
                    payment=payment,
                    late_fee_waiver_amount=py2round(
                        (float(requested_late_fee_percentage.replace('%', '')) / float(100)) * float(
                            payment.late_fee_amount)),
                    interest_waiver_amount=py2round(
                        (float(requested_interest_percentage.replace('%', '')) / float(100)) * float(
                            payment.installment_interest)),
                    principal_waiver_amount=py2round(
                        (float(requested_principal_percentage.replace('%', '')) / float(100)) * float(
                            payment.installment_principal)),
                )
            )
        WaiverPaymentTemp.objects.bulk_create(waiver_payment_temp_data)

    return redirect(url)


def ajax_get_covid_new_employment_statuses(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    reasons = LoanRefinancingMainReason.objects.filter(
        is_active=True, reason__in=CovidRefinancingConst.NEW_REASON
    ).values_list('reason', flat=True)

    return JsonResponse(
        list(reasons), safe=False
    )


def ajax_get_exisiting_offers(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse({
            "status": "failed",
            "message": "non authorized user",
        })
    data = request.POST.dict()
    if 'account_id' in data:
        refinancing_req_qs = LoanRefinancingRequest.objects.filter(account_id=data['account_id'])
    else:
        refinancing_req_qs = LoanRefinancingRequest.objects.filter(loan_id=data['loan_id'])
    existing_offers_list = get_existing_accepted_offer(refinancing_req_qs)

    return JsonResponse({
        'status': 'success',
        'response': {'existing_offers': existing_offers_list}
    })


def ajax_check_refinancing_request_status(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse({
            "status": "failed",
            "message": "non authorized user",
        })
    data = request.POST.dict()
    if "account_id" in data:
        refinancing_req_qs = LoanRefinancingRequest.objects.filter(account_id=data['account_id'])
    else:
        refinancing_req_qs = LoanRefinancingRequest.objects.filter(loan_id=data['loan_id'])
    details = {
        'repeated_request': 0,
        'loan_refinancing_request_available_count': 0,
        'loan_refinancing_generated_count': 0,
        'not_allowed_products': get_not_allowed_products(refinancing_req_qs),
        'multiple_payment_ptp': {'is_multiple_ptp_payment': False},
    }
    if refinancing_req_qs:
        last_refinancing_id = refinancing_req_qs.last().id
        last_refinancing_req_qs = refinancing_req_qs.filter(
            id=last_refinancing_id).values('id', 'cdate', 'product_type')
        loan_refinancing_request_available = last_refinancing_req_qs.filter(
            status__in=CovidRefinancingConst.REACTIVE_OFFER_STATUS_AVAILABLE_FOR_GENERATE_OFFER
        ).last()
        loan_refinancing_request_generated = last_refinancing_req_qs.filter(
            status=CovidRefinancingConst.STATUSES.offer_generated).last()
        loan_refinancing_request_for_repeat = last_refinancing_req_qs.filter(
            status__in=CovidRefinancingConst.NEED_VALIDATE_FOR_MULTIPLE_REQUEST_STATUSES
        ).exists()

        if loan_refinancing_request_for_repeat:
            details['existing_offers'] = get_existing_accepted_offer(refinancing_req_qs)
            details['repeated_request'] = 1

        if loan_refinancing_request_available:
            details['available_refinancing_request_id'] = loan_refinancing_request_available['id']
            details['available_cdate'] = format_date(
                loan_refinancing_request_available['cdate'].date(),
                'dd-MM-yyyy', locale='id_ID')
            details['available_product_type'] =\
                loan_refinancing_request_available['product_type'].upper() \
                if loan_refinancing_request_available['product_type'] else ''
            details['loan_refinancing_request_available_count'] = 1

        if loan_refinancing_request_generated:
            details['generated_refinancing_request_id'] = loan_refinancing_request_generated['id']
            details['generated_cdate'] = format_date(
                loan_refinancing_request_generated['cdate'].date(),
                'dd-MM-yyyy', locale='id_ID')
            details['generated_product_type'] = \
                loan_refinancing_request_generated['product_type'].upper() \
                if loan_refinancing_request_generated['product_type'] else ''
            details['loan_refinancing_generated_count'] = 1

        details['loan_refinancing_request_count'] = refinancing_req_qs.count()
    else:
        details['loan_refinancing_request_count'] = 0

    return JsonResponse({
        'status': 'success',
        'response': details
    })


def refinancing_offer_approve(request, encrypted_uuid):
    url = reverse('loan_refinancing:covid_approval', kwargs={'encrypted_uuid': encrypted_uuid})
    loan_refinancing_req = get_loan_refinancing_request_by_uuid(encrypted_uuid)
    if not loan_refinancing_req:
        return redirect(url)

    serializer = LoanRefinancingSelectedOfferSerializer(data=request.POST.dict())
    if not serializer.is_valid(raise_exception=True):
        return redirect(url)

    if loan_refinancing_req.status != CovidRefinancingConst.STATUSES.offer_selected:
        return redirect(url)

    loan_refinancing_req.update_safely(status=CovidRefinancingConst.STATUSES.approved)
    send_loan_refinancing_request_approved_notification(loan_refinancing_req)

    return redirect(url)


def ajax_generate_reactive_refinancing_offer(request):
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
    serializer = GenerateReactiveRefinancingSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    data = serializer.data
    loan_refinancing_request_qs = LoanRefinancingRequest.objects.filter(loan_id=data['loan_id'])
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
                        waiver_payment_request_dict = dict(
                            outstanding_late_fee_amount=waiver_payment_request.outstanding_late_fee_amount,
                            outstanding_interest_amount=waiver_payment_request.outstanding_interest_amount,
                            outstanding_principal_amount=waiver_payment_request.outstanding_principal_amount,
                            total_outstanding_amount=waiver_payment_request.total_outstanding_amount,
                            requested_late_fee_waiver_amount=waiver_payment_request.requested_late_fee_waiver_amount,
                            requested_interest_waiver_amount=waiver_payment_request.requested_interest_waiver_amount,
                            requested_principal_waiver_amount=waiver_payment_request.requested_principal_waiver_amount,
                            total_requested_waiver_amount=waiver_payment_request.total_requested_waiver_amount,
                            remaining_late_fee_amount=waiver_payment_request.remaining_late_fee_amount,
                            remaining_interest_amount=waiver_payment_request.remaining_interest_amount,
                            remaining_principal_amount=waiver_payment_request.remaining_principal_amount,
                            total_remaining_amount=waiver_payment_request.total_remaining_amount,
                            payment_id=waiver_payment_request.payment_id,
                        )
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
                    data['first_waived_payment'] = waiver_approval.waiver_payment_approval.first().id
                    data['last_waived_payment'] = waiver_approval.waiver_payment_approval.last().id
                    data['requested_late_fee_waiver_percentage'] = "{}%".format(
                        waiver_approval.approved_late_fee_waiver_percentage * 100)
                    data['requested_late_fee_waiver_amount'] = \
                        waiver_approval.get_total_approved_waiver_amount("approved_late_fee_waiver_amount")
                    data['requested_interest_waiver_percentage'] = "{}%".format(
                        waiver_approval.approved_interest_waiver_percentage * 100)
                    data['requested_interest_waiver_amount'] = \
                        waiver_approval.get_total_approved_waiver_amount("approved_interest_waiver_amount")
                    data['requested_principal_waiver_percentage'] = "{}%".format(
                        waiver_approval.approved_principal_waiver_percentage * 100)
                    data['requested_late_fee_waiver_amount'] = \
                        waiver_approval.get_total_approved_waiver_amount("approved_principal_waiver_amount")
                    data['ptp_amount'] = waiver_approval.need_to_pay
                    data['waived_payment_count'] = waiver_approval.waiver_payment_approval.count()
                    waiver_payment_approvals = []
                    for payment in waiver_request.loan.payment_set.normal().order_by('id'):
                        waiver_payment_approval = WaiverPaymentApproval.objects.filter(
                            waiver_approval=waiver_approval, payment=payment).first()
                        if waiver_payment_approval:
                            waiver_payment_approval_dict = dict(
                                outstanding_late_fee_amount=waiver_payment_approval.outstanding_late_fee_amount,
                                outstanding_interest_amount=waiver_payment_approval.outstanding_interest_amount,
                                outstanding_principal_amount=waiver_payment_approval.outstanding_principal_amount,
                                total_outstanding_amount=waiver_payment_approval.total_outstanding_amount,
                                requested_late_fee_waiver_amount=waiver_payment_approval.approved_late_fee_waiver_amount,
                                requested_interest_waiver_amount=waiver_payment_approval.approved_interest_waiver_amount,
                                requested_principal_waiver_amount=waiver_payment_approval.approved_principal_waiver_amount,
                                total_requested_waiver_amount=waiver_payment_approval.total_approved_waiver_amount,
                                remaining_late_fee_amount=waiver_payment_approval.remaining_late_fee_amount,
                                remaining_interest_amount=waiver_payment_approval.remaining_interest_amount,
                                remaining_principal_amount=waiver_payment_approval.remaining_principal_amount,
                                total_remaining_amount=waiver_payment_approval.total_remaining_amount,
                                payment_id=waiver_payment_approval.payment_id,
                            )
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
                loan=loan_refinancing_request.loan, is_approved__isnull=True,
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
    try:
        with transaction.atomic():
            loan_refinancing_request_dict = construct_loan_refinancing_request(
                data, feature_params, initial=True)
            loan_refinancing_request_dict['status'] = CovidRefinancingConst.STATUSES.offer_generated
            loan_refinancing_request_dict['request_date'] = timezone.localtime(timezone.now()).date()
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

    except Exception as e:
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


def ajax_covid_refinancing_submit_refinancing_request(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse({
            "status": "failed",
            "message": "non authorized user",
        })

    data = request.POST.dict()
    serializer = LoanRefinancingRequestSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    data = serializer.data
    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        loan_id=data['loan_id']).last()
    if not loan_refinancing_request:

        return JsonResponse({
            'status': False,
            'message': "loan refinancing request tidak ditemukan"
        })
    loan = loan_refinancing_request.loan
    app = loan.application
    application_detokenized = collection_detokenize_sync_object_model(
        PiiSource.APPLICATION,
        app,
        app.customer.customer_xid,
        ['fullname'],
    )
    request_date = datetime.strftime(loan_refinancing_request.cdate, '%d-%m-%Y')
    if loan_refinancing_request.status in (
            CovidRefinancingConst.STATUSES.offer_selected,
            CovidRefinancingConst.STATUSES.approved):
        if get_partially_paid_prerequisite_amount(loan) > 0:
            message = (
                "<b>%s (ID: %s)</b> sudah mengajukan program keringanan <b>%s</b> pada tanggal <b>%s</b> "
                "dan belum melakukan pembayarannya secara penuh."
                % (application_detokenized.fullname, app.id, data['selected_product'], request_date)
            )
            return JsonResponse({'status': False, 'message': message})
        message = (
            "<b>%s (ID: %s)</b> sudah mengajukan program keringanan <b>%s</b> pada tanggal "
            "<b>%s</b> dan sudah melakukan konfirmasi atau sudah memilih detail program tersebut"
            "." % (application_detokenized.fullname, app.id, data['selected_product'], request_date)
        )
        return JsonResponse({'status': False, 'message': message})
    if loan_refinancing_request.status == CovidRefinancingConst.STATUSES.activated:
        message = (
            "<b>%s (ID: %s)</b> sudah mengajukan program keringanan <b>%s</b> pada tanggal "
            "<b>%s</b> dan program telah aktif"
            % (application_detokenized.fullname, app.id, data['selected_product'], request_date)
        )
        return JsonResponse({'status': False, 'message': message})

    feature_params = get_refinancing_request_feature_setting_params()
    if not feature_params:
        return JsonResponse({
            'status': 'failed',
            'message': 'Feature setting status tidak aktif'
        })

    with transaction.atomic():
        loan_refinancing_request_dict = construct_loan_refinancing_request(data, feature_params, initial=False)
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
            payment = Payment.objects.filter(
                loan=loan_refinancing_request.loan).not_paid_active().order_by('payment_number').first()
            offer_constuctor_func = get_offer_constructor_function(data['selected_product'])
            selected_offer_dict = offer_constuctor_func(
                loan_refinancing_request, payment.bucket_number, default_extension=False)
            selected_offer_dict['generated_by'] = request.user
            selected_offer_dict.pop('recommendation_order', None)
            if existing_offer and not existing_offer.generated_by:
                existing_offer.update_safely(is_latest=False)

            # override existing offer by creating new one
            existing_offer = LoanRefinancingOffer.objects.create(**selected_offer_dict)

        if data['is_customer_confirmed']:
            loan_refinancing_request_dict = dict(
                status=CovidRefinancingConst.STATUSES.offer_selected,
                prerequisite_amount=existing_offer.prerequisite_amount,
                total_latefee_discount=existing_offer.total_latefee_discount
            )
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

        if data['is_customer_confirmed'] and loan_refinancing_request.product_type:
            send_email_refinancing_offer_selected.delay(loan_refinancing_request.id)
            send_pn_covid_refinancing_offer_selected.delay(loan_refinancing_request.id)
            send_sms = True
            comms_list = loan_refinancing_request.comms_channel_list()
            if loan_refinancing_request.channel == CovidRefinancingConst.CHANNELS.reactive and \
                    CovidRefinancingConst.COMMS_CHANNELS.sms not in comms_list:
                send_sms = False

            if send_sms:
                send_sms_covid_refinancing_offer_selected.delay(loan_refinancing_request.id)

    success_message = (
        "Permohonan Refinancing <b>%s</b> untuk <b>%s (ID: %s)</b> "
        "telah dilanjutkan ke proses berikutnya. JULO akan mengirimkan email/PN/SMS"
        " secara otomatis kepada customer tentang detil program ini. "
        "Mohon ingatkan customer untuk membuka pesan yang JULO kirimkan"
        "." % (data['selected_product'], application_detokenized.fullname, app.id)
    )
    return JsonResponse({'status': True, 'message': success_message})


class GeneralWebsiteAPIView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = (AllowAny,)


class EligibilityCheckView(GeneralWebsiteAPIView):
    serializer_class = SubmitPhoneSerializer

    def post(self, request):
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        mobile_phone = request.data['mobile_phone']
        browser_data = request.data['browser_data']
        try:
            request_id = check_collection_offer_eligibility(mobile_phone, browser_data)
        except JuloException as je:
            return general_error_response("error message: %s" % je)
        return success_response({'request_id': request_id})


class OtpConfirmationView(GeneralWebsiteAPIView):
    serializer_class = OtpValidationSerializer

    def post(self, request):
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        otp_token = request.data['otp_token']
        request_id = request.data['request_id']
        feature_setting = FeatureSetting.objects.get_or_none(
                    feature_name=FeatureNameConst.COLLECTION_OFFER_GENERAL_WEBSITE)
        otp_wait_time_seconds = feature_setting.parameters['otp_wait_time_seconds']
        try:
            url = validate_collection_offer_otp(otp_token, request_id, otp_wait_time_seconds)
        except JuloException as je:
            return general_error_response("error message: %s" % je)
        return success_response({'url': url})


def ajax_retrigger_comms(request):
    # this ajax retrigger just only can trigger if the status is offer_selected and approved
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse({
            "status": "failed",
            "message": "non authorized user",
        })

    data = request.POST.dict()
    loan_refinancing_request = LoanRefinancingRequest.objects.filter(loan=data['loan_id']).last()
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


def ajax_covid_refinancing_waiver_recommendation(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = json.loads(request.body)
    waiver_recommendation = get_waiver_recommendation(
        data['loan_id'],
        data['selected_offer_recommendation'],
        data['is_covid_risky'],
        data['bucket']
    )
    if not waiver_recommendation:
        return JsonResponse({
            'status': 'failed',
            'message': 'waiver recommendation tidak ditemukan',
        })

    actual_waiver = model_to_dict(waiver_recommendation)
    loan_refinancing_request = LoanRefinancingRequest.objects.filter(
        loan=data['loan_id'],
        status__in=(
            CovidRefinancingConst.STATUSES.offer_selected,
            CovidRefinancingConst.STATUSES.approved,
        )
    ).last()
    if loan_refinancing_request:
        today_date = timezone.localtime(timezone.now()).date()
        waiver_request_filter = dict(
            loan_id=data['loan_id'],
            is_automated=False,
            waiver_validity_date__gte=today_date
        )

        if loan_refinancing_request.status == CovidRefinancingConst.STATUSES.offer_selected:
            waiver_request_filter['is_approved__isnull'] = True
        else:
            waiver_request_filter['is_approved'] = True

        waiver_request = WaiverRequest.objects.filter(**waiver_request_filter)\
            .order_by('cdate').last()

        if waiver_request:
            actual_waiver = dict(
                principal_waiver_percentage=float(waiver_request.\
                    requested_principal_waiver_percentage.replace('%', '')) / float(100),
                interest_waiver_percentage=float(waiver_request.\
                    requested_interest_waiver_percentage.replace('%', '')) / float(100),
                late_fee_waiver_percentage=float(waiver_request.\
                    requested_late_fee_waiver_percentage.replace('%', '')) / float(100),
            )

    else:
        if data['selected_offer_recommendation'] == "R6":
            actual_waiver['late_fee_waiver_percentage'] = "1.00"

        elif data['selected_offer_recommendation'] == "R4":
            actual_waiver['interest_waiver_percentage'] = "1.00"
            actual_waiver['late_fee_waiver_percentage'] = "1.00"

    return JsonResponse({
        'status': 'success',
        'message': 'berhasil mendapatkan waiver recommendation',
        'waiver_recommendation': model_to_dict(waiver_recommendation),
        'actual_waiver': actual_waiver,
    })


def submit_waiver_approval(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse({
            "status": "failed",
            "message": "non authorized user",
        }, status=400)

    user_groups = request.user.groups.values_list('name', flat=True)
    if not any(approver_role in user_groups for approver_role in NEW_WAIVER_APPROVER_GROUPS):
        return JsonResponse({
            "status": "failed",
            "message": "User anda tidak termasuk dalam role Waiver Approver",
        }, status=400)

    data = json.loads(request.body)
    waiver_approval_serializer = WaiverApprovalSerializer(data=data)

    try:
        with transaction.atomic():
            waiver_approval_serializer.is_valid(raise_exception=True)
            waiver_approval_valid = waiver_approval_serializer.validated_data
            waiver_approval_valid.pop('loan_id')
            waiver_payment_approvals_data = waiver_approval_valid.pop('waiver_payment_approvals')
            if 'waiver_request' in waiver_approval_valid:
                waiver_request_data = waiver_approval_valid.pop('waiver_request')
            if 'waiver_payment_requests' in waiver_approval_valid:
                waiver_payment_requests_data = waiver_approval_valid.pop('waiver_payment_requests')

            waiver_request_id = waiver_approval_valid.pop('waiver_request_id')
            if not waiver_request_id:
                if not waiver_request_data:
                    raise ValidationError({'message': 'Waiver request data wajib diisi'})

                waiver_request_serializer = WaiverRequestSerializer(data=waiver_request_data)
                waiver_request_serializer.is_valid(raise_exception=True)
                waiver_request_valid = waiver_request_serializer.validated_data

                is_need_approval_tl, \
                    is_need_approval_supervisor, \
                    is_need_approval_colls_head, \
                    is_need_approval_ops_head = get_waiver_is_need_approvals(waiver_request_data)

                waiver_request_valid['is_need_approval_tl'] = is_need_approval_tl
                waiver_request_valid['is_need_approval_supervisor'] = is_need_approval_supervisor
                waiver_request_valid['is_need_approval_colls_head'] = is_need_approval_colls_head
                waiver_request_valid['is_need_approval_ops_head'] = is_need_approval_ops_head
                waiver_request_valid['program_name'] = \
                    waiver_request_valid.pop('selected_program_name')
                waiver_request_valid['waiver_recommendation_id'] = \
                    waiver_request_valid.pop('waiver_recommendation_id')
                waiver_request_valid['first_waived_payment_id'] = \
                    int(waiver_request_valid.pop("first_waived_payment"))
                waiver_request_valid['last_waived_payment_id'] = \
                    int(waiver_request_valid.pop("last_waived_payment"))

                waiver_request_valid.pop('calculated_unpaid_waiver_percentage')
                waiver_request_valid.pop('recommended_unpaid_waiver_percentage')

                waiver_recommendation_id = waiver_request_valid['waiver_recommendation_id']
                waiver_recommendation = WaiverRecommendation.objects.get_or_none(
                    pk=waiver_recommendation_id)
                if not waiver_recommendation:
                    waiver_request_valid['waiver_recommendation_id'] = None

                waiver_request_obj = WaiverRequest.objects.create(**waiver_request_valid)

                for waiver_payment_request in waiver_payment_requests_data:
                    waiver_payment_request_serializer = WaiverPaymentRequestSerializer(
                        data=waiver_payment_request)
                    waiver_payment_request_serializer.is_valid(raise_exception=True)
                    waiver_payment_request_valid = waiver_payment_request_serializer.validated_data

                    waiver_payment_request_valid['waiver_request'] = waiver_request_obj
                    WaiverPaymentRequest.objects.create(**waiver_payment_request_valid)
            else:
                waiver_request_obj = WaiverRequest.objects.get_or_none(pk=waiver_request_id)
                if not waiver_request_obj:
                    raise ValidationError({'message': 'Waiver request tidak ditemukan',
                                           'waiver_request_id': waiver_request_id
                                           })
                if waiver_request_obj.is_approved:
                    raise ValidationError({'message': 'Waiver request status Approved',
                                           'waiver_request_id': waiver_request_id
                                           })
            approver_type = waiver_request_obj.update_approval_layer_state(user_groups)
            waiver_approval_valid['waiver_request'] = waiver_request_obj
            waiver_approval_valid['approver_type'] = approver_type
            waiver_approval_valid['decision_ts'] = timezone.localtime(timezone.now())
            waiver_approval_valid['approved_by'] = request.user
            waiver_approval_obj = WaiverApproval.objects.create(**waiver_approval_valid)
            is_approved = waiver_request_obj.is_last_approval_layer(waiver_approval_obj)

            for waiver_payment_approval in waiver_payment_approvals_data:
                waiver_payment_approval_serializer = WaiverPaymentApprovalSerializer(
                    data=waiver_payment_approval)
                waiver_payment_approval_serializer.is_valid(raise_exception=True)
                waiver_payment_approval_valid = waiver_payment_approval_serializer.validated_data
                waiver_payment_approval_valid['waiver_approval'] = waiver_approval_obj
                WaiverPaymentApproval.objects.create(**waiver_payment_approval_valid)

            if is_approved:
                waiver_payment_approval = waiver_approval_obj.waiverpaymentapproval_set.aggregate(
                    late_fee=Sum('approved_late_fee_waiver_amount'),
                    interest=Sum('approved_interest_waiver_amount'),
                    principal=Sum('approved_principal_waiver_amount'))

                if waiver_approval_obj.approved_program != "General Paid Waiver":
                    today = timezone.localtime(timezone.now())
                    waiver_temp = WaiverTemp.objects.create(
                        loan=waiver_request_obj.loan,
                        late_fee_waiver_amt=waiver_payment_approval["late_fee"],
                        interest_waiver_amt=waiver_payment_approval["interest"],
                        principal_waiver_amt=waiver_payment_approval["principal"],
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
                    for waiver_payment_approval in waiver_payment_approvals_data:
                        waiver_payment_temp_data.append(
                            WaiverPaymentTemp(
                                waiver_temp=waiver_temp,
                                payment_id=waiver_payment_approval['payment_id'],
                                late_fee_waiver_amount=waiver_payment_approval[
                                    'approved_late_fee_waiver_amount'],
                                interest_waiver_amount=waiver_payment_approval[
                                    'approved_interest_waiver_amount'],
                                principal_waiver_amount=waiver_payment_approval[
                                    'approved_principal_waiver_amount'],
                            )
                        )
                    WaiverPaymentTemp.objects.bulk_create(waiver_payment_temp_data)
                    waiver_request_obj.update_safely(
                        waiver_type="unpaid",
                        refinancing_status=waiver_approval_valid['decision'])

                    unpaid_multiple_payment_ptp = waiver_request_obj.unpaid_multiple_payment_ptp()
                    if waiver_request_obj.ptp_amount != waiver_temp.need_to_pay and \
                            unpaid_multiple_payment_ptp:
                        excess = waiver_request_obj.ptp_amount - waiver_temp.need_to_pay
                        less_than_ptp_amount = True
                        if excess < 0:
                            excess = -excess
                            less_than_ptp_amount = False

                        for multiple_ptp_payment in unpaid_multiple_payment_ptp:
                            if excess <= 0:
                                continue

                            remaining_amount = multiple_ptp_payment.remaining_amount
                            if not less_than_ptp_amount:
                                multiple_ptp_payment.remaining_amount += excess
                                multiple_ptp_payment.promised_payment_amount += excess
                                excess = 0
                            elif (excess - remaining_amount) < 0:
                                multiple_ptp_payment.remaining_amount -= excess
                                multiple_ptp_payment.promised_payment_amount -= excess
                                excess = 0
                            else:
                                multiple_ptp_payment.promised_payment_amount -= remaining_amount
                                multiple_ptp_payment.remaining_amount -= remaining_amount
                                multiple_ptp_payment.is_fully_paid = True
                                excess -= remaining_amount

                            multiple_ptp_payment.save()
                else:
                    waiver_request_obj.update_safely(
                        waiver_type="paid",
                        refinancing_status=waiver_approval_valid['decision'])
                    for waiver_payment_approval in waiver_payment_approvals_data:
                        waived_payment = Payment.objects.get(
                            pk=waiver_payment_approval['payment_id'])

                        waive_function = dict(
                            principal=waive_principal_paid,
                            interest=waive_interest_paid,
                            late_fee=waive_late_fee_paid
                        )

                        for waiver_type in ("principal", "interest", "late_fee",):
                            key = 'approved_%s_waiver_amount' % waiver_type
                            if waiver_payment_approval[key] > 0:
                                waive_function[waiver_type](
                                    waived_payment,
                                    waiver_payment_approval[key],
                                    "Waiver Approved by %s" % request.user.username
                                )

                loan_ref_request = waiver_request_obj.loan_refinancing_request
                if loan_ref_request:
                    partial_paid = get_partial_payments(
                        waiver_request_obj.waiverpaymentrequest_set.values_list('payment', flat=True),
                        waiver_request_obj.cdate, waiver_request_obj.cdate.date(),
                        waiver_request_obj.waiver_validity_date)
                    if partial_paid < waiver_request_obj.ptp_amount:
                        total_latefee_discount = waiver_approval_obj.total_approved_late_fee_waiver
                        loan_ref_request.update_safely(
                            total_latefee_discount=total_latefee_discount,
                            prerequisite_amount=waiver_approval_obj.need_to_pay - partial_paid,
                            status=CovidRefinancingConst.STATUSES.approved,
                        )
                        send_loan_refinancing_request_approved_notification(loan_ref_request)
                    else:
                        send_loan_refinancing_request_activated_notification(loan_ref_request)

            elif waiver_approval_obj.decision == WaiverApprovalDecisions.REJECTED:
                loan_ref_request = waiver_request_obj.loan_refinancing_request
                if loan_ref_request:
                    loan_ref_request.update_safely(status=CovidRefinancingConst.STATUSES.rejected)

            else:
                send_slack_notification_for_waiver_approver.delay(waiver_request_obj.loan_id)

    except ValidationError as e:
        return JsonResponse({
            'status': 'failed',
            'message': 'Gagal memproses approval harap cek kembali',
            'detail': e.__dict__,
        }, status=400)
    else:
        return JsonResponse({
            'status': 'success',
            'message': 'Berhasil memproses approval',
            'detail': '',
        })


def countdown_time_image(request, encrypted_uuid):
    loan_refinancing_request = get_loan_refinancing_request_by_uuid(encrypted_uuid)
    if not loan_refinancing_request:
        with open(
                "static/images/loan_refinancing/expired_time_count_down.gif", "rb"
        ) as f:
            return HttpResponse(f.read(), content_type="image/gif")

    gif_image = generate_image_for_refinancing_countdown(loan_refinancing_request)
    response = HttpResponse(gif_image.read(), content_type="image/gif")
    response['Pragma-Directive'] = 'no-cache'
    response['Cache-Directive'] = 'no-cache'
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response
