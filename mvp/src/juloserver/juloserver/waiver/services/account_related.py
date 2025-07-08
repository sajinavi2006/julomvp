from builtins import str
from collections import OrderedDict
from django.utils import timezone
from django.db.models import Case, When, Value, BooleanField, CharField, Q
from babel.dates import format_date
from datetime import timedelta

from juloserver.account.models import Account
from juloserver.account_payment.models import AccountPayment
from juloserver.loan_refinancing.utils import (
    generate_status_and_tips_loan_refinancing_status,
    get_partner_product,
    add_rupiah_separator_without_rp,
)
from juloserver.loan_refinancing.models import (
    LoanRefinancingRequest,
    WaiverRequest,
    LoanRefinancingMainReason,
    LoanRefinancingApproval,
)
from juloserver.loan_refinancing.constants import (
    CovidRefinancingConst,
    WAIVER_BUCKET_LIST,
    WAIVER_B1_CURRENT_APPROVER_GROUP,
    WAIVER_B2_APPROVER_GROUP,
    WAIVER_B3_APPROVER_GROUP,
    WAIVER_B4_APPROVER_GROUP,
    WAIVER_B5_APPROVER_GROUP,
    WAIVER_B6_APPROVER_GROUP,
    WAIVER_COLL_HEAD_APPROVER_GROUP,
    WAIVER_OPS_TL_APPROVER_GROUP,
    WAIVER_SPV_APPROVER_GROUP,
    TOP_LEVEL_WAIVER_APPROVERS,
    WAIVER_FRAUD_APPROVER_GROUP,
    ApprovalLayerConst,
)
from juloserver.channeling_loan.models import ChannelingLoanWriteOff
from juloserver.followthemoney.models import LenderCurrent
from juloserver.channeling_loan.constants import BSSChannelingConst
from juloserver.channeling_loan.constants import ChannelingConst
from juloserver.julo.constants import FeatureBSSRefinancing

from .waiver_related import get_partial_account_payments_by_program

from juloserver.apiv2.models import LoanRefinancingScoreJ1

from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst
from juloserver.minisquad.utils import collection_detokenize_sync_object_model
from juloserver.julo.utils import display_rupiah
from typing import Dict


def can_account_get_refinancing(account_id):
    account = Account.objects.get_or_none(pk=account_id)
    if not account:
        return False, "Invalid Account ID"
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.REFINANCING_RESTRICT_CHANNELING_LOAN, is_active=True
    ).last()
    if not feature_setting:
        return True, ""
    criterion = feature_setting.parameters

    filter = Q()
    for key, values in criterion["data"].items():
        queries = values['query']
        filter = filter | Q(**queries)

    return not account.loan_set.filter(filter).exists(), criterion["message"]


def can_account_get_refinancing_bss(account_id, refinancing_type="waiver"):
    account = Account.objects.get_or_none(pk=account_id)
    if not account:
        return False, "Invalid Account ID"

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureBSSRefinancing.FEATURE_NAME, is_active=True
    ).exists()
    if not feature_setting:
        eligible = refinancing_type == "refinancing"
        return eligible, "BSS Feature setting is off"

    bss_lender = LenderCurrent.objects.filter(lender_name=BSSChannelingConst.LENDER_NAME).last()
    if not bss_lender:
        return True, "Invalid lender"

    loans = account.get_all_active_loan().filter(lender_id=bss_lender.id)
    if not loans.exists():
        return True, "Doesn't have any loan with BSS"
    elif loans.exists() and refinancing_type == "refinancing":
        return False, "Not eligible for refinancing BSS"

    write_off = ChannelingLoanWriteOff.objects.filter(
        channeling_type=ChannelingConst.BSS,
        is_write_off=True,
        loan__in=list(loans),
    )
    if len(write_off) != len(loans):
        return False, "Not eligible for refinancing BSS"

    return True, "Only eligible for R4"


def can_account_get_refinancing_centralized(account_id):
    """
    This function is for validate is account eligible to get waiver and refinancing
    this function also will used to send data to PDS and show it on CRM
    """
    account = Account.objects.get_or_none(pk=account_id)
    if not account:
        return False, "Invalid Account ID"

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.REFINANCING_RESTRICT_CHANNELING_LOAN, is_active=True
    ).last()
    if not feature_setting:
        return True, ""

    criteria = feature_setting.parameters

    filter = Q()
    for key, values in criteria["data"].items():
        queries = values['query']
        filter = filter | Q(**queries)

    if account.loan_set.filter(filter).exists():
        return False, criteria["message"]

    bss_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureBSSRefinancing.FEATURE_NAME, is_active=True
    ).exists()

    if not bss_feature_setting:
        return True, "BSS Feature setting is off"

    channeling_lender_block = LenderCurrent.objects.filter(
        lender_name=BSSChannelingConst.LENDER_NAME
    ).last()
    if not channeling_lender_block:
        return True, "Invalid lender"

    loan_ids = (
        account.get_all_active_loan()
        .filter(lender_id=channeling_lender_block.id)
        .values_list('id', flat=True)
    )
    if loan_ids:
        write_off = ChannelingLoanWriteOff.objects.filter(
            channeling_type=ChannelingConst.BSS,
            is_write_off=True,
            loan_id__in=list(loan_ids),
        )
        if len(write_off) != len(loan_ids):
            return False, "Not eligible for refinancing BSS"

    return True, ''


def can_account_get_refinancing_centralized_crm(account_id, user):
    result, message = can_account_get_refinancing_centralized(account_id)
    if (
        user
        and result
        and not user.groups.filter(
            name__in=[
                "collection_agent_1",
                "collection_agent_2",
                "collection_agent_3",
                "collection_agent_4",
                "collection_agent_5",
                "collection_bucket_1",
                "collection_bucket_2",
                "collection_bucket_3",
                "collection_bucket_4",
                "collection_bucket_5",
                "collection_courtesy_call",
                "collection_supervisor",
                "collection_team_leader",
            ]
        ).exists()
    ):
        result = "no permission"

    return result, message


def get_is_covid_risky(account):
    """
    this function is obsolete
    adding early return no for is covid risky

    """
    return 'no'
    application = account.application_set.last()

    banned_province = CovidRefinancingConst.BANNED_PROVINCE
    banned_city = CovidRefinancingConst.BANNED_CITY
    allowed_job_industry = CovidRefinancingConst.ALLOWED_JOB_INDUSTRY
    banned_job_type = CovidRefinancingConst.BANNED_JOB_TYPE
    banned_job_description = CovidRefinancingConst.BANNED_JOB_DESCRIPTION

    today_date = timezone.localtime(timezone.now()).date()
    application_age = today_date.year - application.dob.year
    if today_date.month == application.dob.month:
        if today_date.day < application.dob.day:
            application_age -= 1
    elif today_date.month < application.dob.month:
        application_age -= 1

    if (
        (application.address_provinsi.lower() in banned_province)
        or (application.address_kabupaten.lower() in banned_city)
        or (application_age >= 55)
        or ((application.job_industry or '').lower() not in allowed_job_industry)
        or (application.job_type.lower() in banned_job_type)
        or (application.job_description.lower() in banned_job_description)
    ):
        return 'yes'
    return 'no'


def get_data_for_agent_portal(data, account_id):
    account = Account.objects.get_or_none(pk=account_id)
    data['account_id'] = account_id
    if account:
        customer = account.customer
        detokenize_attributes = collection_detokenize_sync_object_model(
            'customer', customer, customer.customer_xid, ['email', 'fullname']
        )

        data.update(
            dict(
                show=True,
                partner_product='normal',
                customer_name=detokenize_attributes.fullname,
                email_address=detokenize_attributes.email,
                is_covid_risky=get_is_covid_risky(account),
                bucket=account.bucket_name,
                total_principal_account=0,
                total_interest_account=0,
                total_late_fee_account=0,
                total_installment_amount_account=0,
                total_installment_paid_account=0,
                total_installment_outstanding_account=0,
                total_remaining_principal=0,
                total_remaining_interest=0,
                total_remaining_late_fee=0,
                total_not_yet_due_installment=0,
                total_due_installment=0,
                dpd=account.dpd,
                max_extension=3,
            )
        )

        list_ongoing_account_payments = []
        account_payments = account.accountpayment_set.not_paid_active().order_by('due_date')
        for account_payment in account_payments:
            total_installment_amount = \
                account_payment.principal_amount + \
                account_payment.interest_amount + \
                account_payment.late_fee_amount
            if account_payment.due_status_str == 'N':
                data['total_not_yet_due_installment'] += 1
            else:
                data['total_due_installment'] += 1

            list_ongoing_account_payments.append(
                dict(
                    due_date=account_payment.due_date,
                    paid_date=account_payment.paid_date,
                    due_status=account_payment.due_status_str,
                    principal_amount=account_payment.principal_amount,
                    remaining_principal=account_payment.remaining_principal,
                    interest_amount=account_payment.interest_amount,
                    remaining_interest=account_payment.remaining_interest,
                    late_fee_amount=account_payment.late_fee_amount,
                    remaining_late_fee=account_payment.remaining_late_fee,
                    total_installment=total_installment_amount,
                    paid_amount=account_payment.paid_amount,
                    outstanding=account_payment.due_amount,
                    account_payment_id=account_payment.id,
                    paid_status=account_payment.paid_status_str,
                )
            )
            data['total_principal_account'] += account_payment.principal_amount
            data['total_interest_account'] += account_payment.interest_amount
            data['total_late_fee_account'] += account_payment.late_fee_amount
            data['total_installment_amount_account'] += total_installment_amount
            data['total_installment_paid_account'] += account_payment.paid_amount
            data['total_installment_outstanding_account'] += account_payment.due_amount
            data['total_remaining_principal'] += account_payment.remaining_principal
            data['total_remaining_interest'] += account_payment.remaining_interest
            data['total_remaining_late_fee'] += account_payment.remaining_late_fee
        data['ongoing_account_payments'] = list_ongoing_account_payments

        refinancing_reasons = LoanRefinancingMainReason.objects.filter(
            is_active=True, reason__in=CovidRefinancingConst.NEW_REASON
        )
        if refinancing_reasons:
            data['reasons'] = refinancing_reasons.values_list('reason', flat=True)

        loan_refinancing_request = LoanRefinancingRequest.objects.filter(account=account).last()
        if loan_refinancing_request:
            if loan_refinancing_request.status in (
                    CovidRefinancingConst.STATUSES.offer_selected,
                    CovidRefinancingConst.STATUSES.approved,
                    CovidRefinancingConst.STATUSES.offer_generated
            ):
                main_reason_id = loan_refinancing_request.loan_refinancing_main_reason_id
                if refinancing_reasons and main_reason_id:
                    data['new_employment_status'] = refinancing_reasons.filter(
                        id=main_reason_id).last().reason
                data['new_expense'] = add_rupiah_separator_without_rp(
                    loan_refinancing_request.new_expense)
                data['new_income'] = add_rupiah_separator_without_rp(
                    loan_refinancing_request.new_income)
                data['refinancing_request_id'] = loan_refinancing_request.id
                data['loan_refinancing_request_count'] = 1
                data['loan_refinancing_request_date'] = format_date(
                    loan_refinancing_request.cdate.date(),
                    'dd-MM-yyyy', locale='id_ID'
                )
                data['is_auto_populated'] = True
                waiver_request = loan_refinancing_request.waiverrequest_set.last()
                if waiver_request:
                    data['waiver_validity_date'] = format_date(
                        waiver_request.waiver_validity_date,
                        'yyyy-MM-dd', locale='id_ID'
                    )
                    data['existing_program_name'] = waiver_request.program_name
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

        # need confirmation first
        loan_refinancing_score = LoanRefinancingScoreJ1.objects.filter(account=account).last()
        if loan_refinancing_score:
            data['ability_score'] = loan_refinancing_score.ability_score
            data['willingness_score'] = loan_refinancing_score.willingness_score
            data['is_covid_risky'] = False
            bucket = loan_refinancing_score.bucket
            if bucket.lower() == 'current':
                bucket = "Current"
            else:
                buckets = bucket.split(' ')
                if len(buckets) == 2:
                    bucket = buckets[1]
            data['bucket'] = bucket

        data = generate_status_and_tips_loan_refinancing_status(loan_refinancing_request, data)
    else:
        data['show'] = False
    return data


def get_data_for_approver_portal(data, account_id, user_groups=None):
    today_date = timezone.localtime(timezone.now()).date()
    waiver_request = (
        WaiverRequest.objects.filter(
            account_id=account_id, is_approved__isnull=True,
            is_automated=False, waiver_validity_date__gte=today_date,
        ).exclude(
            loan_refinancing_request__status__in=[
                CovidRefinancingConst.STATUSES.expired, CovidRefinancingConst.STATUSES.activated
            ])
        .order_by('cdate')
        .last()
    )

    account = Account.objects.get(pk=account_id)
    application = account.application_set.last()
    customer = application.customer
    detokenize_attributes = collection_detokenize_sync_object_model(
        'customer', customer, customer.customer_xid, ['email', 'fullname']
    )

    data.update(
        dict(
            account_id=account_id,
            application_id=application.id,
            customer_name=detokenize_attributes.fullname,
            email_address=detokenize_attributes.email,
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
            show=False,
            need_approval=True,
        )
    )

    # account payment data
    list_ongoing_account_payments = []
    account_payments = account.accountpayment_set.normal().order_by('due_date')
    key = -1
    for account_payment in account_payments:
        key += 1
        due_status = account_payment.due_status_str
        total_installment_amount = \
            account_payment.principal_amount + \
            account_payment.interest_amount + account_payment.late_fee_amount
        if due_status == 'N':
            data['total_not_yet_due_installment'] += 1
        list_ongoing_account_payments.append(
            dict(
                key=key,
                due_date=account_payment.due_date,
                paid_date=account_payment.paid_date,
                due_status=due_status,
                principal_amount=account_payment.principal_amount,
                remaining_principal=account_payment.remaining_principal,
                interest_amount=account_payment.interest_amount,
                remaining_interest=account_payment.remaining_interest,
                late_fee_amount=account_payment.late_fee_amount,
                remaining_late_fee=account_payment.remaining_late_fee,
                total_installment=total_installment_amount,
                paid_amount=account_payment.paid_amount,
                outstanding=account_payment.due_amount,
                account_payment_id=account_payment.id,
                paid_status=account_payment.paid_status_str,
            )
        )
        data['total_principal_loan'] += account_payment.principal_amount
        data['total_interest_loan'] += account_payment.interest_amount
        data['total_late_fee_loan'] += account_payment.late_fee_amount
        data['total_installment_amount_loan'] += total_installment_amount
        data['total_installment_paid_loan'] += account_payment.paid_amount
        data['total_installment_outstanding_loan'] += account_payment.due_amount
        data['total_remaining_principal'] += account_payment.remaining_principal
        data['total_remaining_interest'] += account_payment.remaining_interest
        data['total_remaining_late_fee'] += account_payment.remaining_late_fee

    data['ongoing_account_payments'] = list_ongoing_account_payments

    if waiver_request:
        loan_refinancing_request = LoanRefinancingRequest.objects.filter(account=account).last()
        if loan_refinancing_request:
            data['refinancing_request_id'] = loan_refinancing_request.id
            data['loan_refinancing_request_count'] = 1
            data['loan_refinancing_request_date'] = format_date(
                loan_refinancing_request.cdate.date(),
                'dd-MM-yyyy', locale='id_ID')
            data['waiver_validity_date'] = timezone.localtime(timezone.now()).date(
            ) + timedelta(days=loan_refinancing_request.expire_in_days)
            data['source'] = loan_refinancing_request.source
            data['field_collection_agent_name'] = (
                loan_refinancing_request.source_detail or {}
            ).get('agent_name')
        else:
            data['waiver_validity_date'] = waiver_request.waiver_validity_date

        data.update(
            dict(
                show=True,
                waiver_request_id=waiver_request.id,
                program_name=waiver_request.program_name,
                original_program_name=waiver_request.program_name,
                agent_name=waiver_request.agent_name,
                waiver_cdate=waiver_request.cdate.date(),
                agent_notes=waiver_request.agent_notes,
                waived_account_payment_count=waiver_request.waived_account_payment_count,
                outstanding_amount=waiver_request.outstanding_amount,
                requested_waiver_amount=waiver_request.requested_waiver_amount,
                waived_account_payment_list=waiver_request.account_payment_list_str,
            )
        )
        data['unrounded_approved_late_fee_waiver_percentage'] = \
            waiver_request.unrounded_requested_late_fee_waiver_percentage
        data['unrounded_approved_interest_waiver_percentage'] = \
            waiver_request.unrounded_requested_interest_waiver_percentage
        data['unrounded_approved_principal_waiver_percentage'] = \
            waiver_request.unrounded_requested_principal_waiver_percentage

        ptp_paid = get_partial_account_payments_by_program(waiver_request)

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
            data['unrounded_approved_late_fee_waiver_percentage'] = \
                waiver_approval.unrounded_approved_late_fee_waiver_percentage
            data['unrounded_approved_interest_waiver_percentage'] = \
                waiver_approval.unrounded_approved_interest_waiver_percentage
            data['unrounded_approved_principal_waiver_percentage'] = \
                waiver_approval.unrounded_approved_principal_waiver_percentage

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
                    unrounded_approved_late_fee_waiver_percentage=1,
                    unrounded_approved_interest_waiver_percentage=1,
                    unrounded_approved_principal_waiver_percentage=1,
                )
            )
        else:
            data['recommended_late_fee_waiver_percent'] = \
                recommended_waiver.late_fee_waiver_percentage
            data['recommended_interest_waiver_percent'] = \
                recommended_waiver.interest_waiver_percentage
            data['recommended_principal_waiver_percent'] = \
                recommended_waiver.principal_waiver_percentage
            if not waiver_approval:
                data['actual_late_fee_waiver_percent'] = \
                    waiver_request.requested_late_fee_waiver_percentage
                data['actual_interest_waiver_percent'] = \
                    waiver_request.requested_interest_waiver_percentage
                data['actual_principal_waiver_percent'] = \
                    waiver_request.requested_principal_waiver_percentage

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

        new_account_payments = account.accountpayment_set.normal().filter(
            waiveraccountpaymentrequest__waiver_request_id=waiver_request.id
        ).annotate(
            is_late_fee_waived=Case(
                When(
                    waiveraccountpaymentrequest__waiver_request__program_name='r5',
                    then=Value(True)
                ),
                default=Value(False),
                output_field=BooleanField()),
            is_interest_waived=Case(
                When(
                    waiveraccountpaymentrequest__waiver_request__program_name='r6',
                    then=Value(True)
                ),
                default=Value(False),
                output_field=BooleanField()),
            is_principal_waived=Case(
                When(
                    waiveraccountpaymentrequest__waiver_request__program_name='r4',
                    then=Value(True)
                ),
                default=Value(False),
                output_field=BooleanField()),
            is_paid_off=Case(
                When(Q(waiveraccountpaymentrequest__isnull=False)
                     & Q(waiveraccountpaymentrequest__total_remaining_amount__gt=0),
                     then=Value('N')),
                When(Q(waiveraccountpaymentrequest__isnull=True) & Q(due_amount__gt=0),
                     then=Value('N')),
                default=Value('Y'),
                output_field=CharField())
        ).order_by('due_date')

        requested_waiver_amount = data['requested_waiver_amount']
        outstanding_amount = 0 if ptp_paid > 0 else data['outstanding_amount']
        account_payment_requests_data = []
        index = -1
        for account_payment in account_payments:
            index = index + 1
            waiver_account_payment = account_payment.waiveraccountpaymentrequest_set.filter(
                waiver_request=waiver_request).last()
            if waiver_approval:
                waiver_account_payment = account_payment.waiveraccountpaymentapproval_set.filter(
                    waiver_approval=waiver_approval).last()
            account_payment_request_data = dict(
                id=account_payment.id,
                index=index,
                due_status=account_payment.due_status_str,
                due_date=account_payment.due_date,
                is_paid_off=account_payment.paid_off_status_str,
                is_late_fee_waived=False,
                is_interest_waived=False,
                is_principal_waived=False,
                is_apply_waiver=False,
                real_outstanding_late_fee_amount=account_payment.remaining_late_fee,
                real_outstanding_interest_amount=account_payment.remaining_interest,
                real_outstanding_principal_amount=account_payment.remaining_principal,
                outstanding_late_fee_amount=account_payment.remaining_late_fee,
                outstanding_interest_amount=account_payment.remaining_interest,
                outstanding_principal_amount=account_payment.remaining_principal,
                total_outstanding_amount=account_payment.due_amount,
                requested_late_fee_waiver_amount=None,
                requested_interest_waiver_amount=None,
                requested_principal_waiver_amount=None,
                total_requested_waiver_amount=None,
                remaining_late_fee_amount=account_payment.remaining_late_fee,
                remaining_interest_amount=account_payment.remaining_interest,
                remaining_principal_amount=account_payment.remaining_principal,
                total_remaining_amount=account_payment.due_amount,
            )
            new_account_payment = new_account_payments.filter(pk=account_payment.id).last()
            if new_account_payment:
                account_payment_request_data.update(
                    dict(
                        is_paid_off=new_account_payment.is_paid_off,
                        is_late_fee_waived=new_account_payment.is_late_fee_waived,
                        is_interest_waived=new_account_payment.is_interest_waived,
                        is_principal_waived=new_account_payment.is_principal_waived,
                    )
                )
            if waiver_account_payment and account_payment.due_amount > 0:
                account_payment_request_data.update(
                    dict(
                        total_outstanding_amount=waiver_account_payment.
                        total_outstanding_amount,
                        requested_late_fee_waiver_amount=waiver_account_payment.
                        requested_late_fee_waiver_amount,
                        requested_interest_waiver_amount=waiver_account_payment.
                        requested_interest_waiver_amount,
                        requested_principal_waiver_amount=waiver_account_payment.
                        requested_principal_waiver_amount,
                        total_requested_waiver_amount=waiver_account_payment.
                        total_requested_waiver_amount,
                        remaining_late_fee_amount=waiver_account_payment.
                        remaining_late_fee_amount,
                        remaining_interest_amount=waiver_account_payment.
                        remaining_interest_amount,
                        total_remaining_amount=waiver_account_payment.
                        total_remaining_amount
                    )
                )
                account_payment_request_data['outstanding_late_fee_amount'] = \
                    waiver_account_payment.outstanding_late_fee_amount
                account_payment_request_data['outstanding_interest_amount'] = \
                    waiver_account_payment.outstanding_interest_amount
                account_payment_request_data['outstanding_principal_amount'] = \
                    waiver_account_payment.outstanding_principal_amount
                account_payment_request_data['remaining_principal_amount'] = \
                    waiver_account_payment.remaining_principal_amount
                if ptp_paid > 0:
                    outstanding_amount += account_payment.due_amount
                data['remaining_approved_installment'] += \
                    waiver_account_payment.total_remaining_amount

            if new_account_payment and ptp_paid > 0 and requested_waiver_amount > 0 \
                    and account_payment.due_amount > 0:
                account_payment_request_data["total_requested_waiver_amount"] = 0
                account_payment_request_data["is_apply_waiver"] = True
                remainings = dict(
                    principal=account_payment.remaining_principal,
                    interest=account_payment.remaining_interest,
                    late_fee=account_payment.remaining_late_fee
                )

                account_payment_request_data["total_outstanding_amount"] = 0
                for waiver_type in ("late_fee", "interest", "principal",):
                    requested_key = "requested_{}_waiver_amount".format(waiver_type)
                    outstanding_key = "outstanding_{}_amount".format(waiver_type)

                    if requested_waiver_amount >= remainings[waiver_type]:
                        account_payment_request_data[requested_key] = remainings[waiver_type]
                        account_payment_request_data["total_requested_waiver_amount"] += \
                            remainings[waiver_type]
                        requested_waiver_amount -= remainings[waiver_type]
                    elif requested_waiver_amount >= account_payment_request_data[requested_key]:
                        account_payment_request_data["total_requested_waiver_amount"] += \
                            account_payment_request_data[requested_key]
                        requested_waiver_amount -= account_payment_request_data[requested_key]
                    else:
                        account_payment_request_data[requested_key] = requested_waiver_amount
                        account_payment_request_data["total_requested_waiver_amount"] += \
                            requested_waiver_amount
                        requested_waiver_amount = 0

                    outstanding_principal = remainings[waiver_type] - account_payment_request_data[
                        requested_key]
                    account_payment_request_data[outstanding_key] = outstanding_principal
                    account_payment_request_data["total_outstanding_amount"] += \
                        outstanding_principal

            data['all_outstanding_late_fee_amount'] += \
                account_payment_request_data['outstanding_late_fee_amount']
            data['all_outstanding_interest_amount'] += \
                account_payment_request_data['outstanding_interest_amount']
            data['all_outstanding_principal_amount'] += \
                account_payment_request_data['outstanding_principal_amount']
            data['all_total_outstanding_amount'] += \
                account_payment_request_data['total_outstanding_amount']

            if account_payment_request_data['requested_late_fee_waiver_amount']:
                data['all_requested_late_fee_waiver_amount'] += \
                    account_payment_request_data['requested_late_fee_waiver_amount']
            if account_payment_request_data['requested_interest_waiver_amount']:
                data['all_requested_interest_waiver_amount'] += \
                    account_payment_request_data['requested_interest_waiver_amount']
            if account_payment_request_data['requested_principal_waiver_amount']:
                data['all_requested_principal_waiver_amount'] += \
                    account_payment_request_data['requested_principal_waiver_amount']
            if account_payment_request_data['total_requested_waiver_amount']:
                data['all_total_requested_waiver_amount'] += \
                    account_payment_request_data['total_requested_waiver_amount']

            data['all_remaining_late_fee_amount'] += \
                account_payment_request_data['remaining_late_fee_amount']
            data['all_remaining_interest_amount'] += \
                account_payment_request_data['remaining_interest_amount']
            data['all_remaining_principal_amount'] += \
                account_payment_request_data['remaining_principal_amount']
            data['all_total_remaining_amount'] += \
                account_payment_request_data['total_remaining_amount']

            account_payment_requests_data.append(account_payment_request_data)
        data.update(
            dict(
                account_payment_requests=account_payment_requests_data,
                outstanding_amount=outstanding_amount,
            )
        )
        if data['requested_waiver_amount'] and ptp_paid > 0:
            data['need_to_pay'] = waiver_request.ptp_amount - ptp_paid
            if outstanding_amount < data['requested_waiver_amount']:
                data['requested_waiver_amount'] = outstanding_amount
        return data

    waiver_request = WaiverRequest.objects.filter(
        account_id=account_id, is_automated=True
    ).order_by('cdate').last()

    if waiver_request and \
            waiver_request.waiver_validity_date >= today_date \
            and WAIVER_FRAUD_APPROVER_GROUP not in user_groups:
        data['need_approval'] = False
        return data

    waived_account_payment = AccountPayment.objects.not_paid_active().filter(
        account_id=account_id).first()
    if not waived_account_payment:
        return data
    if user_groups:
        if waived_account_payment.paid_amount == 0 \
                and WAIVER_FRAUD_APPROVER_GROUP not in user_groups:
            return data
    else:
        if waived_account_payment.paid_amount == 0:
            return data

    data.update(
        dict(
            bucket=account.bucket_name,
            is_covid_risky=get_is_covid_risky(account),
            waiver_recommendation_id=None,
            show=True,
            program_name="General Paid Waiver",
            outstanding_amount=waived_account_payment.due_amount,
            requested_waiver_amount=waived_account_payment.due_amount,
            need_to_pay=0,
            is_apply_waiver=True,
            actual_late_fee_waiver_percent="100%",
            actual_interest_waiver_percent="100%",
            actual_principal_waiver_percent="100%",
            recommended_late_fee_waiver_percent=1,
            recommended_interest_waiver_percent=1,
            recommended_principal_waiver_percent=1,
            unrounded_approved_late_fee_waiver_percentage=1,
            unrounded_approved_interest_waiver_percentage=1,
            unrounded_approved_principal_waiver_percentage=1,
            waiver_validity_date=timezone.localtime(timezone.now()).date(),
            agent_notes="approved",
            waived_account_payment_list="Tagihan %s" % format_date(
                waived_account_payment.due_date,
                'MMMM yyyy', locale='id_ID'
            ),
            partner_product=get_partner_product(application.product_line_code),
        )
    )

    account_payment_requests_data = []
    index = -1
    for account_payment in account_payments:
        index = index + 1
        account_payment_request_data = dict(
            id=account_payment.id,
            index=index,
            due_status=account_payment.due_status_str,
            due_date=account_payment.due_date,
            is_paid_off=account_payment.paid_off_status_str,
            is_late_fee_waived=False,
            is_interest_waived=False,
            is_principal_waived=False,
            is_apply_waiver=False,
            real_outstanding_late_fee_amount=account_payment.remaining_late_fee,
            real_outstanding_interest_amount=account_payment.remaining_interest,
            real_outstanding_principal_amount=account_payment.remaining_principal,
            outstanding_late_fee_amount=account_payment.remaining_late_fee,
            outstanding_interest_amount=account_payment.remaining_interest,
            outstanding_principal_amount=account_payment.remaining_principal,
            total_outstanding_amount=account_payment.due_amount,
            requested_late_fee_waiver_amount=None,
            requested_interest_waiver_amount=None,
            requested_principal_waiver_amount=None,
            total_requested_waiver_amount=None,
            remaining_late_fee_amount=account_payment.remaining_late_fee,
            remaining_interest_amount=account_payment.remaining_interest,
            remaining_principal_amount=account_payment.remaining_principal,
            total_remaining_amount=account_payment.due_amount,
        )
        if account_payment == waived_account_payment:
            account_payment_request_data.update(
                dict(
                    is_paid_off='Y',
                    is_apply_waiver=True,
                    total_outstanding_amount=0,
                    outstanding_late_fee_amount=0,
                    outstanding_interest_amount=0,
                    outstanding_principal_amount=0,
                    requested_late_fee_waiver_amount=account_payment.remaining_late_fee,
                    requested_interest_waiver_amount=account_payment.remaining_interest,
                    requested_principal_waiver_amount=account_payment.remaining_principal,
                    total_requested_waiver_amount=waived_account_payment.due_amount,
                    remaining_late_fee_amount=0,
                    remaining_interest_amount=0,
                    remaining_principal_amount=0,
                    total_remaining_amount=0,
                )
            )
            data['remaining_approved_installment'] += account_payment.due_amount

        data['all_outstanding_late_fee_amount'] += \
            account_payment_request_data['outstanding_late_fee_amount']
        data['all_outstanding_interest_amount'] += \
            account_payment_request_data['outstanding_interest_amount']
        data['all_outstanding_principal_amount'] += \
            account_payment_request_data['outstanding_principal_amount']
        data['all_total_outstanding_amount'] += \
            account_payment_request_data['total_outstanding_amount']

        if account_payment_request_data['requested_late_fee_waiver_amount']:
            data['all_requested_late_fee_waiver_amount'] += \
                account_payment_request_data['requested_late_fee_waiver_amount']
        if account_payment_request_data['requested_interest_waiver_amount']:
            data['all_requested_interest_waiver_amount'] += \
                account_payment_request_data['requested_interest_waiver_amount']
        if account_payment_request_data['requested_principal_waiver_amount']:
            data['all_requested_principal_waiver_amount'] += \
                account_payment_request_data['requested_principal_waiver_amount']
        if account_payment_request_data['total_requested_waiver_amount']:
            data['all_total_requested_waiver_amount'] += \
                account_payment_request_data['total_requested_waiver_amount']

        data['all_remaining_late_fee_amount'] += \
            account_payment_request_data['remaining_late_fee_amount']
        data['all_remaining_interest_amount'] += \
            account_payment_request_data['remaining_interest_amount']
        data['all_remaining_principal_amount'] += \
            account_payment_request_data['remaining_principal_amount']
        data['all_total_remaining_amount'] += \
            account_payment_request_data['total_remaining_amount']

        account_payment_requests_data.append(account_payment_request_data)
    data['account_payment_requests'] = account_payment_requests_data
    return data


def get_account_ids_for_bucket_tree(user_groups, is_refinancing: bool = False):
    account_id_dict = {}
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
    if WAIVER_B6_APPROVER_GROUP in user_groups:
        tl_role_buckets.append(6)

    listed_bucket += tl_role_buckets

    if any(approver_role in user_groups for approver_role in TOP_LEVEL_WAIVER_APPROVERS):
        listed_bucket = WAIVER_BUCKET_LIST
        if WAIVER_SPV_APPROVER_GROUP in user_groups:
            approval_layer_states.append(ApprovalLayerConst.TL)
        if WAIVER_COLL_HEAD_APPROVER_GROUP in user_groups:
            approval_layer_states.append(ApprovalLayerConst.SPV)
        if WAIVER_OPS_TL_APPROVER_GROUP in user_groups:
            approval_layer_states.append(ApprovalLayerConst.COLLS_HEAD)

    for bucket in WAIVER_BUCKET_LIST:
        # handle waiver approval
        if listed_bucket and bucket in listed_bucket and not is_refinancing:
            account_ids_qs = WaiverRequest.objects.filter(
                bucket_name=bucket,
                is_automated=False,
                is_approved__isnull=True,
                waiver_validity_date__gte=today)
            if bucket in tl_role_buckets:
                account_ids_qs = account_ids_qs.filter(
                    Q(approval_layer_state__in=approval_layer_states)
                    | Q(approval_layer_state__isnull=True))
            else:
                account_ids_qs = account_ids_qs.filter(
                    approval_layer_state__in=approval_layer_states)

            account_ids = account_ids_qs.distinct().values_list('account_id', flat=True)
            bucket = 0 if bucket == 'Current' else bucket
            account_id_dict["bucket_" + str(bucket)] = account_ids

        # handle refinancing approval
        if listed_bucket and bucket in listed_bucket and is_refinancing:
            loan_refinancing_need_approval = LoanRefinancingRequest.objects.filter(
                loanrefinancingapproval__bucket_name=bucket,
                loanrefinancingapproval__is_accepted__isnull=True,
                status=CovidRefinancingConst.STATUSES.offer_selected,
            )
            if bucket in tl_role_buckets:
                loan_refinancing_need_approval = loan_refinancing_need_approval.filter(
                    Q(loanrefinancingapproval__approval_type__in=approval_layer_states)
                    | Q(loanrefinancingapproval__approval_type__isnull=True)
                )
            else:
                loan_refinancing_need_approval = loan_refinancing_need_approval.filter(
                    loanrefinancingapproval__approval_type=approval_layer_states
                )

            account_ids = loan_refinancing_need_approval.distinct().values_list(
                'account_id', flat=True
            )
            bucket = 0 if bucket == 'Current' else bucket
            account_id_dict["bucket_" + str(bucket)] = account_ids

    return OrderedDict(sorted(account_id_dict.items()))


def generate_approval_refinancing_data(data: Dict, account_id: int):
    account = Account.objects.filter(pk=account_id).last()
    refinancing_approval_query = """
        EXISTS (
            SELECT 1
            FROM "loan_refinancing_approval" lra
            WHERE
            lra.loan_refinancing_request_id = loan_refinancing_request.loan_refinancing_request_id
            AND lra.is_accepted ISNULL
        )
    """
    loan_refinancing = (
        LoanRefinancingRequest.objects.filter(
            account=account,
            status=CovidRefinancingConst.STATUSES.offer_selected,
            product_type__in=CovidRefinancingConst.reactive_products(),
        )
        .extra(where=[refinancing_approval_query])
        .last()
    )
    if not loan_refinancing:
        return data

    customer = account.customer
    detokenize_attributes = collection_detokenize_sync_object_model(
        'customer', customer, customer.customer_xid, ['email', 'fullname']
    )
    refinancing_approvals = LoanRefinancingApproval.objects.filter(
        loan_refinancing_request_id=loan_refinancing.id
    )
    first_refinancing_approval = refinancing_approvals.first()
    last_refinancing_approval = refinancing_approvals.last()
    spv_notes = ''
    for refinancing_approval in refinancing_approvals:
        if refinancing_approval.approver_notes:
            spv_notes += '%s (%s): \n %s \n' % (
                refinancing_approval.approver.username,
                refinancing_approval.approval_type,
                refinancing_approval.approver_notes,
            )
    extra_data = last_refinancing_approval.extra_data
    account_payment_ids = extra_data.get('account_payment_ids', [])
    simulated_payments = extra_data.get('simulated_payments', [])
    account_payments_count = 0
    refinancing_account_payments = []
    ongoing_account_payments = []
    data.update(
        dict(
            total_principal_account=0,
            total_interest_account=0,
            total_late_fee_account=0,
            total_installment_amount_account=0,
            total_installment_paid_account=0,
            total_installment_outstanding_account=0,
            total_remaining_principal=0,
            total_remaining_interest=0,
            total_remaining_late_fee=0,
        )
    )
    if account_payment_ids:
        account_payments = AccountPayment.objects.filter(pk__in=account_payment_ids)
        account_payments_count = len(account_payment_ids)
        for account_payment in account_payments.iterator():
            refinancing_account_payments.append(
                format_date(account_payment.due_date, 'MMMM yyyy', locale='id_ID')
            )
            total_installment_amount = (
                account_payment.principal_amount
                + account_payment.interest_amount
                + account_payment.late_fee_amount
            )
            ongoing_account_payments.append(
                dict(
                    due_date=account_payment.due_date,
                    paid_date=account_payment.paid_date,
                    due_status=account_payment.due_status_str,
                    principal_amount=account_payment.principal_amount,
                    remaining_principal=account_payment.remaining_principal,
                    interest_amount=account_payment.interest_amount,
                    remaining_interest=account_payment.remaining_interest,
                    late_fee_amount=account_payment.late_fee_amount,
                    remaining_late_fee=account_payment.remaining_late_fee,
                    total_installment=total_installment_amount,
                    paid_amount=account_payment.paid_amount,
                    outstanding=account_payment.due_amount,
                    account_payment_id=account_payment.id,
                    paid_status=account_payment.paid_status_str,
                )
            )
            data['total_principal_account'] += account_payment.principal_amount
            data['total_interest_account'] += account_payment.interest_amount
            data['total_late_fee_account'] += account_payment.late_fee_amount
            data['total_installment_amount_account'] += total_installment_amount
            data['total_installment_paid_account'] += account_payment.paid_amount
            data['total_installment_outstanding_account'] += account_payment.due_amount
            data['total_remaining_principal'] += account_payment.remaining_principal
            data['total_remaining_interest'] += account_payment.remaining_interest
            data['total_remaining_late_fee'] += account_payment.remaining_late_fee

    total_principal = 0
    total_interest = 0
    total_late_fee = 0
    total_installment_amount = 0
    total_paid_amount = 0
    total_outstanding_amount = 0
    for simulated_payment in simulated_payments:
        total_principal += simulated_payment.get('installment_principal')
        total_interest += simulated_payment.get('installment_interest')
        total_late_fee += simulated_payment.get('installment_late_fee')
        total_installment_amount += simulated_payment.get('total_installment_amount')
        total_outstanding_amount += simulated_payment.get('outstanding')

    data.update(
        show=True,
        program=loan_refinancing.product_type,
        account_id=account.id,
        customer_name=detokenize_attributes.fullname,
        email=detokenize_attributes.email,
        agent_name=first_refinancing_approval.requestor.username,
        refinancing_created=format_date(
            loan_refinancing.cdate.date(), 'dd MMMM yyyy', locale='id_ID'
        ),
        agent_notes='%s (Agent): \n %s'
        % (
            first_refinancing_approval.requestor.username,
            first_refinancing_approval.requestor_notes,
        )
        or '-',
        spv_notes=spv_notes,
        account_payments_count=account_payments_count,
        refinancing_account_payments=refinancing_account_payments,
        refinancing_reason=loan_refinancing.loan_refinancing_main_reason.reason
        if loan_refinancing.loan_refinancing_main_reason
        else '',
        new_income=display_rupiah(loan_refinancing.new_income),
        new_expense=display_rupiah(loan_refinancing.new_expense),
        refinancing_duration=loan_refinancing.loan_duration,
        ongoing_account_payments=ongoing_account_payments,
        simulated_payments=simulated_payments,
        total_principal=total_principal,
        total_interest=total_interest,
        total_late_fee=total_late_fee,
        total_all_installment_amount=total_installment_amount,
        total_paid_amount=total_paid_amount,
        total_outstanding_amount=total_outstanding_amount,
        loan_refinancing_request_id=loan_refinancing.id,
        loan_refinancing_approval_id=last_refinancing_approval.id,
        source=loan_refinancing.source,
        field_collection_agent_name=(loan_refinancing.source_detail or {}).get('agent_name'),
    )
    return data
