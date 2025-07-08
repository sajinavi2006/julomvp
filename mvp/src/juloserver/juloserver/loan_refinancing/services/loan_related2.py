from builtins import str
import logging
from collections import OrderedDict
from datetime import timedelta

from babel.dates import format_date
from django.utils import timezone
from django.db.models import Case, When, Value, BooleanField, CharField, Q

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.loan_refinancing.utils import (add_rupiah_separator_without_rp,
                                               generate_status_and_tips_loan_refinancing_status)
from ..constants import (CovidRefinancingConst,
                         MultipleRefinancingLimitConst,
                         WAIVER_BUCKET_LIST,
                         WAIVER_B1_CURRENT_APPROVER_GROUP,
                         WAIVER_B2_APPROVER_GROUP,
                         WAIVER_B3_APPROVER_GROUP,
                         WAIVER_B4_APPROVER_GROUP,
                         WAIVER_B5_APPROVER_GROUP,
                         WAIVER_COLL_HEAD_APPROVER_GROUP,
                         WAIVER_OPS_TL_APPROVER_GROUP,
                         WAIVER_FRAUD_APPROVER_GROUP,
                         WAIVER_SPV_APPROVER_GROUP,
                         TOP_LEVEL_WAIVER_APPROVERS, ApprovalLayerConst)
from ..models import (WaiverRequest,
                      LoanRefinancingRequest,
                      LoanRefinancingMainReason)
from juloserver.julo.models import Loan, FeatureSetting, Payment
from juloserver.apiv2.models import LoanRefinancingScore
from juloserver.payback.services.waiver import get_remaining_principal
from juloserver.payback.services.waiver import get_remaining_interest
from juloserver.payback.services.waiver import get_remaining_late_fee
from juloserver.payback.services.waiver import get_partial_payments
from juloserver.pii_vault.constants import PiiSource
from juloserver.minisquad.utils import collection_detokenize_sync_object_model

logger = logging.getLogger(__name__)


def get_not_allowed_products(refinancing_req):
    not_allowed_products = []
    r1_request = refinancing_req.filter(product_type=CovidRefinancingConst.PRODUCTS.r1,
                                        status=CovidRefinancingConst.STATUSES.activated)
    if r1_request.count() >= MultipleRefinancingLimitConst.R1:
        not_allowed_products.append(CovidRefinancingConst.PRODUCTS.r1)
    r2_r3_request = refinancing_req.filter(
        product_type__in=(CovidRefinancingConst.PRODUCTS.r2, CovidRefinancingConst.PRODUCTS.r3),
        status=CovidRefinancingConst.STATUSES.activated
    )
    if r2_r3_request.count() >= MultipleRefinancingLimitConst.R2_R3:
        not_allowed_products.append(CovidRefinancingConst.PRODUCTS.r2)
        not_allowed_products.append(CovidRefinancingConst.PRODUCTS.r3)
    return not_allowed_products


def get_loan_ids_for_bucket_tree(user_groups):
    loan_id_dict = {}
    listed_bucket = []
    approval_layer_states = []
    tl_role_buckets = []
    today = timezone.localtime(timezone.now()).date()

    if WAIVER_B1_CURRENT_APPROVER_GROUP in user_groups:
        tl_role_buckets += ['Current', 1]
    if WAIVER_B2_APPROVER_GROUP in user_groups:
        tl_role_buckets.append(2)
    if WAIVER_B3_APPROVER_GROUP in user_groups:
        tl_role_buckets.append(3)
    if WAIVER_B4_APPROVER_GROUP in user_groups:
        tl_role_buckets.append(4)
    if WAIVER_B5_APPROVER_GROUP in user_groups:
        tl_role_buckets.append(5)

    listed_bucket += tl_role_buckets

    if any(approver_role in user_groups for approver_role in TOP_LEVEL_WAIVER_APPROVERS):
        listed_bucket = WAIVER_BUCKET_LIST
        if WAIVER_SPV_APPROVER_GROUP in user_groups:
            approval_layer_states.append(ApprovalLayerConst.TL)
        if WAIVER_COLL_HEAD_APPROVER_GROUP in user_groups:
            approval_layer_states.append(ApprovalLayerConst.SPV)
        if WAIVER_FRAUD_APPROVER_GROUP in user_groups:
            approval_layer_states.append(ApprovalLayerConst.SPV)
        if WAIVER_OPS_TL_APPROVER_GROUP in user_groups:
            approval_layer_states.append(ApprovalLayerConst.COLLS_HEAD)

    for bucket in WAIVER_BUCKET_LIST:
        if listed_bucket and bucket in listed_bucket:
            loan_ids_qs = WaiverRequest.objects.filter(
                bucket_name=bucket,
                is_automated=False,
                is_approved__isnull=True,
                waiver_validity_date__gte=today)
            if bucket in tl_role_buckets:
                loan_ids_qs = loan_ids_qs.filter(
                    Q(approval_layer_state__in=approval_layer_states) |
                    Q(approval_layer_state__isnull=True))
            else:
                loan_ids_qs = loan_ids_qs.filter(approval_layer_state__in=approval_layer_states)

            loan_ids = loan_ids_qs.distinct().values_list('loan_id', flat=True)
            bucket = 0 if bucket == 'Current' else bucket
            loan_id_dict["bucket_" + str(bucket)] = loan_ids
    return OrderedDict(sorted(loan_id_dict.items()))


def get_data_for_agent_portal(data, loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)
    data['loan_id'] = loan_id
    if loan and not loan.account:
        customer = loan.application.customer
        application_id = loan.application.id
        payments = loan.payment_set.exclude(is_restructured=True).order_by('payment_number')
        total_principal_loan = 0
        total_interest_loan = 0
        total_late_fee_loan = 0
        total_installment_amount_loan = 0
        total_installment_paid_loan = 0
        total_installment_outstanding_loan = 0
        total_not_yet_due_installment = 0
        total_remaining_principal = 0
        total_remaining_interest = 0
        total_remaining_late_fee = 0
        list_ongoing_loan = []
        loan_refinancing_request = LoanRefinancingRequest.objects.filter(loan=loan).last()
        refinancing_reason_reasons = LoanRefinancingMainReason.objects.filter(
            is_active=True, reason__in=CovidRefinancingConst.NEW_REASON
        )
        if refinancing_reason_reasons:
            reasons = refinancing_reason_reasons.values_list('reason', flat=True)

        if loan_refinancing_request:
            if loan_refinancing_request.status in (
                    CovidRefinancingConst.STATUSES.offer_selected,
                    CovidRefinancingConst.STATUSES.approved,
                    CovidRefinancingConst.STATUSES.offer_generated
            ):
                main_reason_id = loan_refinancing_request.loan_refinancing_main_reason_id
                if refinancing_reason_reasons and main_reason_id:
                    main_reason = reasons.filter(id=main_reason_id).last()
                    data['new_employment_status'] = main_reason
                data['new_expense'] = add_rupiah_separator_without_rp(
                    loan_refinancing_request.new_expense
                )
                data['new_income'] = add_rupiah_separator_without_rp(
                    loan_refinancing_request.new_income
                )
                data['refinancing_request_id'] = loan_refinancing_request.id
                data['loan_refinancing_request_count'] = 1
                data['loan_refinancing_request_date'] = format_date(
                    loan_refinancing_request.cdate.date(),
                    'dd-MM-yyyy', locale='id_ID'
                )
                data['is_auto_populated'] = True
                waiver_request = loan_refinancing_request.waiverrequest_set.last()
                if waiver_request:
                    data['is_multiple_ptp_payment'] = waiver_request.is_multiple_ptp_payment
                    data['number_of_multiple_ptp_payment'] = \
                        waiver_request.number_of_multiple_ptp_payment
                    multiple_payment_ptp = waiver_request.ordered_multiple_payment_ptp()
                    for payment_ptp in multiple_payment_ptp:
                        payment_ptp.promised_payment_date = format_date(
                            payment_ptp.promised_payment_date,
                            'yyyy-MM-dd', locale='id_ID'
                        )
                    data['multiple_payment_ptp'] = multiple_payment_ptp

        for payment in payments:
            due_status = 'N' if payment.due_late_days < 0 else 'Y'
            total_installment_amount = payment.installment_principal + \
                payment.installment_interest + payment.late_fee_amount
            if due_status == 'N':
                total_not_yet_due_installment += 1

            if payment.is_paid:
                paid_status = 'Paid'
            elif payment.paid_amount != 0:
                paid_status = 'Partially Paid'
            elif payment.paid_amount == 0:
                paid_status = 'Not Paid'
            remaining_late_fee = get_remaining_late_fee(payment, is_unpaid=False)
            remaining_interest = get_remaining_interest(payment, is_unpaid=False)
            remaining_principal = get_remaining_principal(payment, is_unpaid=False)
            list_ongoing_loan.append(
                dict(
                    payment_number=payment.payment_number,
                    due_date=payment.due_date,
                    paid_date=payment.paid_date,
                    due_status=due_status,
                    installment_principal=payment.installment_principal,
                    remaining_principal=remaining_principal,
                    installment_interest=payment.installment_interest,
                    remaining_interest=remaining_interest,
                    late_fee_amount=payment.late_fee_amount,
                    remaining_late_fee=remaining_late_fee,
                    total_installment=total_installment_amount,
                    paid_amount=payment.paid_amount,
                    outstanding=payment.due_amount,
                    is_restructured=payment.is_restructured,
                    payment_id=payment.id,
                    paid_status=paid_status,
                )
            )
            total_principal_loan += payment.installment_principal
            total_interest_loan += payment.installment_interest
            total_late_fee_loan += payment.late_fee_amount
            total_installment_amount_loan += total_installment_amount
            total_installment_paid_loan += payment.paid_amount
            total_installment_outstanding_loan += payment.due_amount
            total_remaining_principal += remaining_principal
            total_remaining_interest += remaining_interest
            total_remaining_late_fee += remaining_late_fee
        loan_refinancing_score = LoanRefinancingScore.objects.filter(loan=loan_id).last()
        product_line_code = loan.application.product_line_code

        if loan_refinancing_score:
            data['ability_score'] = loan_refinancing_score.ability_score
            data['willingness_score'] = loan_refinancing_score.willingness_score
            data['is_covid_risky'] = loan_refinancing_score.is_covid_risky
            data['bucket'] = loan_refinancing_score.bucket
        # partner other than mtl, stl, pede & laku6
        allowed_product_line = ProductLineCodes.mtl() + ProductLineCodes.stl() + \
            ProductLineCodes.pede() + ProductLineCodes.laku6()
        is_can_calculate_r1_until_r6 = True if product_line_code in allowed_product_line \
            else False
        data['is_can_calculate_r1_until_r6'] = is_can_calculate_r1_until_r6
        active_feature = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.COVID_REFINANCING,
            is_active=True).last()
        if active_feature and is_can_calculate_r1_until_r6:
            feature_params = active_feature.parameters
            max_extension = 3 if loan.loan_duration > 9 \
                or product_line_code in ProductLineCodes.stl() \
                or product_line_code in ProductLineCodes.pedestl() \
                else feature_params['tenure_extension_rule']['MTL_%s' % loan.loan_duration]
            data['max_extension'] = max_extension
        partner_product = ''
        if product_line_code in (ProductLineCodes.mtl() + ProductLineCodes.stl()):
            partner_product = 'normal'
        elif product_line_code in ProductLineCodes.pede():
            partner_product = 'pede'
        elif product_line_code in ProductLineCodes.laku6():
            partner_product = 'laku6'
        elif product_line_code in ProductLineCodes.icare():
            partner_product = 'icare'

        customer_detokenized = collection_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            customer,
            customer.customer_xid,
            ['fullname', 'email'],
        )

        data['partner_product'] = partner_product
        data['customer_name'] = customer_detokenized.fullname
        data['email_address'] = customer_detokenized.email
        data['ongoing_loan_data'] = list_ongoing_loan
        data['total_principal_loan'] = total_principal_loan
        data['total_interest_loan'] = total_interest_loan
        data['total_late_fee_loan'] = total_late_fee_loan
        data['total_installment_amount_loan'] = total_installment_amount_loan
        data['total_installment_paid_loan'] = total_installment_paid_loan
        data['total_installment_outstanding_loan'] = total_installment_outstanding_loan
        data['total_remaining_principal'] = total_remaining_principal
        data['total_remaining_interest'] = total_remaining_interest
        data['total_remaining_late_fee'] = total_remaining_late_fee
        data['show'] = True
        data['total_not_yet_due_installment'] = total_not_yet_due_installment
        data['application_id'] = application_id
        data['reasons'] = reasons
        data['dpd'] = loan.dpd
        data = generate_status_and_tips_loan_refinancing_status(loan_refinancing_request, data)
    elif loan and loan.account:
        data['show'] = False
        data['is_julo_one'] = True
    else:
        data['show'] = False
    return data


def get_data_for_approver_portal(data, loan_id):
    today_date = timezone.localtime(timezone.now()).date()
    waiver_request = WaiverRequest.objects.filter(
        loan_id=loan_id, is_approved__isnull=True,
        is_automated=False, waiver_validity_date__gte=today_date
    ).order_by('cdate').last()

    data['loan_id'] = loan_id
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        return data
    customer = loan.application.customer
    application_id = loan.application.id

    customer_detokenized = collection_detokenize_sync_object_model(
        PiiSource.CUSTOMER,
        customer,
        customer.customer_xid,
        ['fullname', 'email'],
    )

    data.update(
        dict(
            loan_id=loan_id,
            application_id=application_id,
            customer_name=customer_detokenized.fullname,
            email_address=customer_detokenized.email,
            total_principal_loan=0,
            requested_ptp_amount=0,
            total_interest_loan=0,
            total_late_fee_loan=0,
            total_installment_amount_loan=0,
            total_installment_paid_loan=0,
            total_installment_outstanding_loan=0,
            total_remaining_principal=0,
            total_remaining_interest=0,
            total_remaining_late_fee=0,
            remaining_approved_installment=0,
            all_outstanding_late_fee_amount=0,
            all_outstanding_interest_amount=0,
            all_outstanding_principal_amount=0,
            all_total_outstanding_amount=0,
            all_requested_late_fee_waiver_amount=0,
            all_requested_interest_waiver_amount=0,
            all_requested_principal_waiver_amount=0,
            all_total_requested_waiver_amount=0,
            all_remaining_late_fee_amount=0,
            all_remaining_interest_amount=0,
            all_remaining_principal_amount=0,
            all_total_remaining_amount=0,
            total_not_yet_due_installment=0,
            is_apply_waiver=False,
            show=False
        )
    )

    # payment data
    list_ongoing_loan = []
    payments = loan.payment_set.normal().order_by('payment_number')
    key = -1
    for payment in payments:
        key += 1
        due_status = 'N' if payment.due_late_days < 0 else 'Y'
        total_installment_amount = payment.installment_principal + \
            payment.installment_interest + payment.late_fee_amount
        if due_status == 'N':
            data['total_not_yet_due_installment'] += 1
        if payment.is_paid:
            paid_status = 'Paid'
        elif payment.paid_amount != 0:
            paid_status = 'Partially Paid'
        elif payment.paid_amount == 0:
            paid_status = 'Not Paid'
        remaining_late_fee = get_remaining_late_fee(payment, is_unpaid=False)
        remaining_interest = get_remaining_interest(payment, is_unpaid=False)
        remaining_principal = get_remaining_principal(payment, is_unpaid=False)
        list_ongoing_loan.append(
            dict(
                key=key,
                payment_number=payment.payment_number,
                due_date=payment.due_date,
                paid_date=payment.paid_date,
                due_status=due_status,
                installment_principal=payment.installment_principal,
                remaining_principal=remaining_principal,
                installment_interest=payment.installment_interest,
                remaining_interest=remaining_interest,
                late_fee_amount=payment.late_fee_amount,
                remaining_late_fee=remaining_late_fee,
                total_installment=total_installment_amount,
                paid_amount=payment.paid_amount,
                outstanding=payment.due_amount,
                is_restructured=payment.is_restructured,
                payment_id=payment.id,
                paid_status=paid_status,
            )
        )
        data['total_principal_loan'] += payment.installment_principal
        data['total_interest_loan'] += payment.installment_interest
        data['total_late_fee_loan'] += payment.late_fee_amount
        data['total_installment_amount_loan'] += total_installment_amount
        data['total_installment_paid_loan'] += payment.paid_amount
        data['total_installment_outstanding_loan'] += payment.due_amount
        data['total_remaining_principal'] += remaining_principal
        data['total_remaining_interest'] += remaining_interest
        data['total_remaining_late_fee'] += remaining_late_fee

    data['ongoing_loan_data'] = list_ongoing_loan

    if waiver_request:
        loan_refinancing_request = LoanRefinancingRequest.objects.filter(loan=loan).last()
        if loan_refinancing_request:
            main_reason_id = loan_refinancing_request.loan_refinancing_main_reason_id

            main_reason = LoanRefinancingMainReason.objects.values_list(
                'reason', flat=True).filter(id=main_reason_id).last()
            data['new_employment_status'] = main_reason
            data['refinancing_request_id'] = loan_refinancing_request.id
            data['loan_refinancing_request_count'] = 1
            data['loan_refinancing_request_date'] = format_date(
                loan_refinancing_request.cdate.date(),
                'dd-MM-yyyy', locale='id_ID'
            )

        data.update(
            dict(
                show=True,
                waiver_request_id=waiver_request.id,
                program_name=waiver_request.program_name,
                original_program_name=waiver_request.program_name,
                agent_name=waiver_request.agent_name,
                waiver_cdate=waiver_request.cdate.date(),
                agent_notes=waiver_request.agent_notes,
                waived_payment_count=waiver_request.waived_payment_count,
                outstanding_amount=waiver_request.outstanding_amount,
                requested_waiver_amount=waiver_request.requested_waiver_amount,
                waiver_validity_date=waiver_request.waiver_validity_date,
                waived_payment_list=waiver_request.payment_number_list_str
            )
        )

        ptp_paid = get_partial_payments(
            waiver_request.waiverpaymentrequest_set.values_list('payment', flat=True),
            waiver_request.cdate, waiver_request.cdate.date(),
            waiver_request.waiver_validity_date)
        recommended_waiver = waiver_request.waiver_recommendation

        data["notes"] = [
            dict(
                layer="Agent",
                note=waiver_request.agent_notes
            )
        ]
        waiver_approvals = waiver_request.waiverapproval_set.all().order_by('cdate')
        for waiver_approval in waiver_approvals:
            data["notes"].append(
                dict(
                    layer=waiver_approval.approver_type,
                    note=waiver_approval.notes,
                )
            )

        waiver_approval = waiver_request.waiverapproval_set.last()
        if waiver_approval:
            data.update(
                dict(
                    program_name=waiver_approval.approved_program,
                    actual_late_fee_waiver_percent="{}%".format(
                        int(waiver_approval.approved_late_fee_waiver_percentage * 100)),
                    actual_interest_waiver_percent="{}%".format(
                        int(waiver_approval.approved_interest_waiver_percentage * 100)),
                    actual_principal_waiver_percent="{}%".format(
                        int(waiver_approval.approved_principal_waiver_percentage * 100)),
                    requested_waiver_amount=waiver_approval.approved_waiver_amount,
                    waiver_validity_date=waiver_approval.approved_waiver_validity_date,
                    ptp_amount=waiver_approval.need_to_pay,
                    remaining_original_ptp=waiver_approval.need_to_pay - ptp_paid,
                    need_to_pay=waiver_approval.need_to_pay - ptp_paid,
                )
            )

        if ptp_paid > 0:
            data.update(
                dict(
                    program_name="General Paid Waiver",
                    is_apply_waiver=True,
                    actual_late_fee_waiver_percent="100%",
                    actual_interest_waiver_percent="100%",
                    actual_principal_waiver_percent="100%",
                    recommended_late_fee_waiver_percent=1,
                    recommended_interest_waiver_percent=1,
                    recommended_principal_waiver_percent=1,
                )
            )
        else:
            data.update(
                dict(
                    recommended_late_fee_waiver_percent=recommended_waiver.late_fee_waiver_percentage,
                    recommended_interest_waiver_percent=recommended_waiver.interest_waiver_percentage,
                    recommended_principal_waiver_percent=recommended_waiver.principal_waiver_percentage,
                )
            )
            if not waiver_approval:
                data.update(
                    dict(
                        actual_late_fee_waiver_percent=waiver_request.requested_late_fee_waiver_percentage,
                        actual_interest_waiver_percent=waiver_request.requested_interest_waiver_percentage,
                        actual_principal_waiver_percent=waiver_request.requested_principal_waiver_percentage,
                    )
                )


        if not waiver_approval:
            data.update(
                dict(
                    ptp_amount=waiver_request.ptp_amount,
                    remaining_original_ptp=waiver_request.ptp_amount - ptp_paid,
                    need_to_pay=waiver_request.ptp_amount - ptp_paid,
                )
            )

        data.update(
            dict(
                requested_ptp_amount=waiver_request.ptp_amount,
                ptp_paid=ptp_paid,
                remaining_original_installment=waiver_request.remaining_amount_for_waived_payment,
            )
        )

        new_payments = loan.payment_set.normal().filter(
            waiverpaymentrequest__waiver_request_id=waiver_request.id
        ).annotate(
            is_late_fee_waived=Case(
                When(waiverpaymentrequest__waiver_request__program_name='r5', then=Value(True)),
                default=Value(False),
                output_field=BooleanField()),
            is_interest_waived=Case(
                When(waiverpaymentrequest__waiver_request__program_name='r6', then=Value(True)),
                default=Value(False),
                output_field=BooleanField()),
            is_principal_waived=Case(
                When(waiverpaymentrequest__waiver_request__program_name='r4', then=Value(True)),
                default=Value(False),
                output_field=BooleanField()),
            is_paid_off=Case(
                When(Q(waiverpaymentrequest__isnull=False) &
                     Q(waiverpaymentrequest__total_remaining_amount__gt=0),
                     then=Value('N')),
                When(Q(waiverpaymentrequest__isnull=True) & Q(due_amount__gt=0),
                     then=Value('N')),
                default=Value('Y'),
                output_field=CharField())
        ).order_by('payment_number')

        requested_waiver_amount = data['requested_waiver_amount']
        outstanding_amount = 0 if ptp_paid > 0 else data['outstanding_amount']
        payment_requests_data = []
        index = -1
        for payment in payments:
            index = index + 1
            due_status = 'N' if payment.due_late_days < 0 else 'Y'
            paid_off_status = 'N' if payment.due_amount > 0 else 'Y'
            waiver_payment = payment.waiverpaymentrequest_set.filter(
                waiver_request=waiver_request).last()
            if waiver_approval:
                waiver_payment = payment.waiverpaymentapproval_set.filter(
                    waiver_approval=waiver_approval).last()
            remaining_late_fee = get_remaining_late_fee(payment, is_unpaid=False)
            remaining_interest = get_remaining_interest(payment, is_unpaid=False)
            remaining_principal = get_remaining_principal(payment, is_unpaid=False)
            payment_request_data = dict(
                id=payment.id,
                index=index,
                due_status=due_status,
                payment_number=payment.payment_number,
                is_paid_off=paid_off_status,
                is_late_fee_waived=False,
                is_interest_waived=False,
                is_principal_waived=False,
                is_apply_waiver=False,
                real_outstanding_late_fee_amount=remaining_late_fee,
                real_outstanding_interest_amount=remaining_interest,
                real_outstanding_principal_amount=remaining_principal,
                outstanding_late_fee_amount=remaining_late_fee,
                outstanding_interest_amount=remaining_interest,
                outstanding_principal_amount=remaining_principal,
                total_outstanding_amount=payment.due_amount,
                requested_late_fee_waiver_amount=None,
                requested_interest_waiver_amount=None,
                requested_principal_waiver_amount=None,
                total_requested_waiver_amount=None,
                remaining_late_fee_amount=remaining_late_fee,
                remaining_interest_amount=remaining_interest,
                remaining_principal_amount=remaining_principal,
                total_remaining_amount=payment.due_amount,
            )
            new_payment = new_payments.filter(pk=payment.id).last()
            if new_payment:
                payment_request_data.update(
                    dict(
                        is_paid_off=new_payment.is_paid_off,
                        is_late_fee_waived=new_payment.is_late_fee_waived,
                        is_interest_waived=new_payment.is_interest_waived,
                        is_principal_waived=new_payment.is_principal_waived,
                    )
                )
            if waiver_payment and payment.due_amount > 0:
                payment_request_data.update(
                    dict(
                        total_outstanding_amount=waiver_payment.total_outstanding_amount,
                        outstanding_late_fee_amount=waiver_payment.outstanding_late_fee_amount,
                        outstanding_interest_amount=waiver_payment.outstanding_interest_amount,
                        outstanding_principal_amount=waiver_payment.outstanding_principal_amount,
                        requested_late_fee_waiver_amount=waiver_payment.
                        requested_late_fee_waiver_amount,
                        requested_interest_waiver_amount=waiver_payment.
                        requested_interest_waiver_amount,
                        requested_principal_waiver_amount=waiver_payment.
                        requested_principal_waiver_amount,
                        total_requested_waiver_amount=waiver_payment.
                        total_requested_waiver_amount,
                        remaining_late_fee_amount=waiver_payment.remaining_late_fee_amount,
                        remaining_interest_amount=waiver_payment.remaining_interest_amount,
                        remaining_principal_amount=waiver_payment.remaining_principal_amount,
                        total_remaining_amount=waiver_payment.total_remaining_amount
                    )
                )
                if ptp_paid > 0:
                    outstanding_amount += payment.due_amount
                data['remaining_approved_installment'] += waiver_payment.total_remaining_amount

            if new_payment and ptp_paid > 0 and requested_waiver_amount > 0 and payment.due_amount > 0:
                payment_request_data["total_requested_waiver_amount"] = 0
                payment_request_data["is_apply_waiver"] = True
                remainings = dict(
                    principal=remaining_principal,
                    interest=remaining_interest,
                    late_fee=remaining_late_fee
                )

                for waiver_type in ("principal", "interest", "late_fee", ):
                    requested_key = "requested_{}_waiver_amount".format(waiver_type)
                    outstanding_key = "outstanding_{}_amount".format(waiver_type)
                    if requested_waiver_amount >= remainings[waiver_type]:
                        payment_request_data[requested_key] = remainings[waiver_type]
                        payment_request_data["total_requested_waiver_amount"] += remainings[waiver_type]
                        requested_waiver_amount -= remainings[waiver_type]
                    else:
                        payment_request_data[requested_key] = requested_waiver_amount
                        payment_request_data["total_requested_waiver_amount"] += requested_waiver_amount
                        requested_waiver_amount = 0

                    outstanding_principal = remainings[waiver_type] - payment_request_data[requested_key]
                    payment_request_data[outstanding_key] = outstanding_principal
                    payment_request_data["total_outstanding_amount"] = outstanding_principal

            data['all_outstanding_late_fee_amount'] += \
                payment_request_data['outstanding_late_fee_amount']
            data['all_outstanding_interest_amount'] += \
                payment_request_data['outstanding_interest_amount']
            data['all_outstanding_principal_amount'] += \
                payment_request_data['outstanding_principal_amount']
            data['all_total_outstanding_amount'] += \
                payment_request_data['total_outstanding_amount']

            if payment_request_data['requested_late_fee_waiver_amount']:
                data['all_requested_late_fee_waiver_amount'] += \
                    payment_request_data['requested_late_fee_waiver_amount']
            if payment_request_data['requested_interest_waiver_amount']:
                data['all_requested_interest_waiver_amount'] += \
                    payment_request_data['requested_interest_waiver_amount']
            if payment_request_data['requested_principal_waiver_amount']:
                data['all_requested_principal_waiver_amount'] += \
                    payment_request_data['requested_principal_waiver_amount']
            if payment_request_data['total_requested_waiver_amount']:
                data['all_total_requested_waiver_amount'] += \
                    payment_request_data['total_requested_waiver_amount']

            data['all_remaining_late_fee_amount'] += \
                payment_request_data['remaining_late_fee_amount']
            data['all_remaining_interest_amount'] += \
                payment_request_data['remaining_interest_amount']
            data['all_remaining_principal_amount'] += \
                payment_request_data['remaining_principal_amount']
            data['all_total_remaining_amount'] += \
                payment_request_data['total_remaining_amount']

            payment_requests_data.append(payment_request_data)
        data.update(
            dict(
                payment_requests=payment_requests_data,
                outstanding_amount=outstanding_amount,
            )
        )
        if data['requested_waiver_amount'] and ptp_paid > 0:
            data['need_to_pay'] = waiver_request.ptp_amount - ptp_paid
            if outstanding_amount < data['requested_waiver_amount']:
                data['requested_waiver_amount'] = outstanding_amount
    else:
        waiver_request = WaiverRequest.objects.filter(
            loan_id=loan_id, is_approved__isnull=True,
            is_automated=False, waiver_validity_date__lt=today_date,
            first_waived_payment__isnull=False, last_waived_payment__isnull=False
        ).order_by('cdate').last()
        payment_filter = dict(loan_id=loan_id)
        if waiver_request:
            payment_filter.update(
                dict(
                    id__gte=waiver_request.first_waived_payment.id,
                    id__lte=waiver_request.last_waived_payment.id
                )
            )

        waived_payment = Payment.objects.not_paid_active().filter(**payment_filter).first()
        if waived_payment:
            loan_refinancing_score = LoanRefinancingScore.objects.filter(loan=loan_id).last()
            product_line_code = loan.application.product_line_code

            if loan_refinancing_score:
                data.update(
                    dict(
                        bucket=loan_refinancing_score.bucket.lower().replace('bucket ', ''),
                        is_covid_risky=loan_refinancing_score.is_covid_risky,
                        waiver_recommendation_id=None,
                    )
                )

            data['partner_product'] = ''
            if product_line_code in (ProductLineCodes.mtl() + ProductLineCodes.stl()):
                data['partner_product'] = 'normal'
            elif product_line_code in ProductLineCodes.pede():
                data['partner_product'] = 'pede'
            elif product_line_code in ProductLineCodes.laku6():
                data['partner_product'] = 'laku6'
            elif product_line_code in ProductLineCodes.icare():
                data['partner_product'] = 'icare'

            data.update(
                dict(
                    show=True,
                    program_name="General Paid Waiver",
                    outstanding_amount=waived_payment.due_amount,
                    requested_waiver_amount=waived_payment.due_amount,
                    need_to_pay=0,
                    is_apply_waiver=True,
                    actual_late_fee_waiver_percent="100%",
                    actual_interest_waiver_percent="100%",
                    actual_principal_waiver_percent="100%",
                    recommended_late_fee_waiver_percent=1,
                    recommended_interest_waiver_percent=1,
                    recommended_principal_waiver_percent=1,
                    waiver_validity_date=timezone.localtime(timezone.now()).date(),
                    agent_notes="approved",
                    waived_payment_list="Payment %s" % waived_payment.payment_number
                )
            )

            payment_requests_data = []
            index = -1
            for payment in payments:
                index = index + 1
                due_status = 'N' if payment.due_late_days < 0 else 'Y'
                paid_off_status = 'N' if payment.due_amount > 0 else 'Y'
                remaining_late_fee = get_remaining_late_fee(payment, is_unpaid=False)
                remaining_interest = get_remaining_interest(payment, is_unpaid=False)
                remaining_principal = get_remaining_principal(payment, is_unpaid=False)
                payment_request_data = dict(
                    id=payment.id,
                    index=index,
                    due_status=due_status,
                    payment_number=payment.payment_number,
                    is_paid_off=paid_off_status,
                    is_late_fee_waived=False,
                    is_interest_waived=False,
                    is_principal_waived=False,
                    is_apply_waiver=False,
                    real_outstanding_late_fee_amount=remaining_late_fee,
                    real_outstanding_interest_amount=remaining_interest,
                    real_outstanding_principal_amount=remaining_principal,
                    outstanding_late_fee_amount=remaining_late_fee,
                    outstanding_interest_amount=remaining_interest,
                    outstanding_principal_amount=remaining_principal,
                    total_outstanding_amount=payment.due_amount,
                    requested_late_fee_waiver_amount=None,
                    requested_interest_waiver_amount=None,
                    requested_principal_waiver_amount=None,
                    total_requested_waiver_amount=None,
                    remaining_late_fee_amount=remaining_late_fee,
                    remaining_interest_amount=remaining_interest,
                    remaining_principal_amount=remaining_principal,
                    total_remaining_amount=payment.due_amount,
                )
                if payment == waived_payment:
                    payment_request_data.update(
                        dict(
                            is_paid_off='Y',
                            is_apply_waiver=True,
                            total_outstanding_amount=0,
                            outstanding_late_fee_amount=0,
                            outstanding_interest_amount=0,
                            outstanding_principal_amount=0,
                            requested_late_fee_waiver_amount=remaining_late_fee,
                            requested_interest_waiver_amount=remaining_interest,
                            requested_principal_waiver_amount=remaining_principal,
                            total_requested_waiver_amount=waived_payment.due_amount,
                            remaining_late_fee_amount=0,
                            remaining_interest_amount=0,
                            remaining_principal_amount=0,
                            total_remaining_amount=0,
                        )
                    )
                    data['remaining_approved_installment'] += payment.due_amount

                data['all_outstanding_late_fee_amount'] += \
                    payment_request_data['outstanding_late_fee_amount']
                data['all_outstanding_interest_amount'] += \
                    payment_request_data['outstanding_interest_amount']
                data['all_outstanding_principal_amount'] += \
                    payment_request_data['outstanding_principal_amount']
                data['all_total_outstanding_amount'] += \
                    payment_request_data['total_outstanding_amount']

                if payment_request_data['requested_late_fee_waiver_amount']:
                    data['all_requested_late_fee_waiver_amount'] += \
                        payment_request_data['requested_late_fee_waiver_amount']
                if payment_request_data['requested_interest_waiver_amount']:
                    data['all_requested_interest_waiver_amount'] += \
                        payment_request_data['requested_interest_waiver_amount']
                if payment_request_data['requested_principal_waiver_amount']:
                    data['all_requested_principal_waiver_amount'] += \
                        payment_request_data['requested_principal_waiver_amount']
                if payment_request_data['total_requested_waiver_amount']:
                    data['all_total_requested_waiver_amount'] += \
                        payment_request_data['total_requested_waiver_amount']

                data['all_remaining_late_fee_amount'] += \
                    payment_request_data['remaining_late_fee_amount']
                data['all_remaining_interest_amount'] += \
                    payment_request_data['remaining_interest_amount']
                data['all_remaining_principal_amount'] += \
                    payment_request_data['remaining_principal_amount']
                data['all_total_remaining_amount'] += \
                    payment_request_data['total_remaining_amount']

                payment_requests_data.append(payment_request_data)
            data['payment_requests'] = payment_requests_data
    return data


def get_refinanced_r1r2r3_payments(payments, loan):
    loan_ref_req = LoanRefinancingRequest.objects.filter(
        account_id=loan.account_id, status=CovidRefinancingConst.STATUSES.activated,
        product_type__in=CovidRefinancingConst.reactive_products()
    ).last()
    description = '-'
    if not loan_ref_req:
        return [], description

    range1 = loan_ref_req.cdate
    range2 = loan_ref_req.cdate + timedelta(days=loan_ref_req.expire_in_days)
    filter_dict = dict(cdate__range=[range1, range2])
    if loan_ref_req.product_type in (
            CovidRefinancingConst.PRODUCTS.r2,
            CovidRefinancingConst.PRODUCTS.r3):
        description = 'Program Penundaan'
        filter_dict.update(dict(paid_amount=loan_ref_req.prerequisite_amount))
    payments_after_filter = payments.filter(**filter_dict)
    if loan_ref_req.product_type == CovidRefinancingConst.PRODUCTS.r1:
        description = 'Program Restrukturisasi'
        payments_after_filter = payments.filter(
            **filter_dict)[:loan.loan_duration + loan_ref_req.loan_duration]
    return payments_after_filter, description
