from builtins import str
import logging

from juloserver.disbursement.models import Disbursement, PaymentGatewayCustomerDataLoan
from juloserver.grab.models import PaymentGatewayCustomerData
from juloserver.payment_point.tasks.notification_related import send_train_ticket_email_task

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from django.db.models import Q, Sum, F
from django.db.models.query import QuerySet
from django.db import transaction
from dateutil.relativedelta import relativedelta

from juloserver.ecommerce import juloshop_service
from juloserver.ecommerce.juloshop_service import get_juloshop_transaction_by_loan
from juloserver.grab.tasks import trigger_submit_grab_disbursal_creation
from juloserver.loan.exceptions import LenderException

from juloserver.payment_point.clients import get_julo_sepulsa_loan_client
from juloserver.payment_point.services.sepulsa import SepulsaLoanService

from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.loan.tasks.sphp import send_sphp_email_task
from datetime import timedelta, datetime

from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.julo.exceptions import JuloException
from juloserver.julo.services import (
    update_lender_disbursement_counter,
    record_disbursement_transaction,
    process_sepulsa_transaction_failed,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.statuses import (
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.models import (
    StatusLookup,
    LenderProductCriteria,
    FeatureSetting,
    Loan,
    SepulsaTransaction,
    PartnerProperty,
)
from juloserver.followthemoney.services import (
    update_lender_balance_current_for_disbursement,
    update_committed_amount_for_lender_balance,
    update_committed_amount_for_lender_balance_payment_point,
    update_committed_amount_for_lender_balance_qris,
    get_bypass_lender_matchmaking,
    RedisCacheLoanBucketXidPast,
)
from juloserver.followthemoney.models import (
    LenderCurrent,
    LenderBalanceCurrent,
    LenderTransactionMapping,
    LenderBucket,
)
from juloserver.followthemoney.tasks import (
    generate_summary_lender_loan_agreement,
    assign_lenderbucket_xid_to_lendersignature,
    send_warning_message_low_balance_amount,
    auto_expired_loan_tasks,
)

from juloserver.disbursement.constants import (
    DisbursementVendors,
    DisbursementStatus,
    AyoconnectConst,
    AyoconnectErrorReason,
    XfersDisbursementStep,
    AyoconnectFailoverXfersConst,
    AyoconnectErrorCodes,
    AyoconnectBeneficiaryStatus,
)
from juloserver.disbursement.services import (
    trigger_disburse,
    create_disbursement_new_flow_history,
    AyoconnectDisbursementProcess,
)
from juloserver.disbursement.services.daily_disbursement_limit import (
    store_daily_disbursement_score_limit_amount,
)

from juloserver.merchant_financing.models import BulkDisbursementSchedule

from juloserver.qris.services.legacy_service import QrisService

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.clients import get_julo_pn_client
from juloserver.julo.clients.sepulsa import SepulsaResponseCodes

from juloserver.account.models import AccountTransaction, Account
from juloserver.account_payment.models import AccountPayment

from juloserver.payment_point.models import SpendTransaction, Vendor
from juloserver.payment_point.constants import (
    TransactionMethodCode,
    SepulsaProductCategory,
)

from juloserver.loan.constants import DisbursementAutoRetryConstant, LoanStatusChangeReason
from juloserver.followthemoney.constants import (
    LenderTransactionTypeConst,
    SnapshotType,
    LenderNameByPartner,
    LenderName,
)
from juloserver.followthemoney.models import LenderTransactionType, LenderTransaction
from juloserver.followthemoney.tasks import calculate_available_balance
from juloserver.customer_module.services.bank_account_related import is_ecommerce_bank_account
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.partnership.models import (
    PartnerLoanRequest,
    PartnershipTransaction,
    PartnershipConfig,
)
from juloserver.partnership.constants import PartnershipChangeReason
from juloserver.partnership.tasks import (
    email_notification_for_partner_loan,
    partnership_mfsp_send_email_disbursement_notification_task,
)

from juloserver.channeling_loan.tasks import (
    send_loan_for_channeling_task,
    send_loan_prefund_flow_task,
    record_channeling_tenure_cap_after_220_task,
)
from juloserver.channeling_loan.services.lender_services import channeling_lender_auto_matchmaking
from juloserver.channeling_loan.services.lender_services import (
    force_assigned_lender,
    is_force_assign_lender_active,
)
from juloserver.employee_financing.tasks.email_task import (
    email_notification_for_employee_financing_loan,
)
from juloserver.promo.models import PromoCode
from juloserver.promo.services import (
    check_promo_code_and_get_message,
    create_promo_code_usage,
)
from juloserver.partnership.services.services import check_partnership_type_is_paylater
from juloserver.application_flow.constants import PartnerNameConstant

from juloserver.credit_card.tasks.notification_tasks import (
    send_pn_obtained_first_transaction_cashback,
)
from juloserver.education.tasks import send_education_email_invoice_task
from juloserver.healthcare.tasks import send_healthcare_email_invoice_task
from juloserver.minisquad.tasks import store_cashback_new_scheme_by_account_ids

from juloserver.loan.tasks.julo_care_task_related import generate_julo_care_policy_task

logger = logging.getLogger(__name__)


def julo_one_lender_auto_matchmaking(loan, lender_ids=None):
    def general_response(lender_):
        if lender_:
            if lender_ids and lender_.id in set(lender_ids):
                return lender_
            update_lender_disbursement_counter(lender_)
        return lender_

    def get_default_lender():
        default_lender_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DEFAULT_LENDER_MATCHMAKING,
            category="followthemoney",
            is_active=True,
        ).first()

        if default_lender_setting and default_lender_setting.parameters['lender_name']:
            default_lender_balance = LenderBalanceCurrent.objects.get_or_none(
                lender__lender_name=default_lender_setting.parameters['lender_name'],
            )
            if not default_lender_balance:
                return None

            if default_lender_balance.available_balance < loan.loan_amount:
                logger.info(
                    {
                        'task': (
                            'juloserver.loan.services.'
                            'lender_related.julo_one_lender_auto_matchmaking'
                        ),
                        'loan_id': loan.id,
                        'message': 'Default lender has insufficient balance',
                    }
                )

            # assign default lender in any case (even its insufficient but will be stuck at x211)
            return default_lender_balance.lender

        return None

    if loan.is_j1_or_jturbo_loan():
        # Force to specific lender, if tenor met
        # Will pass the round robin
        if is_force_assign_lender_active(loan):
            return general_response(force_assigned_lender(loan))
        lender = channeling_lender_auto_matchmaking(loan.id, loan.loan_amount, lender_ids)
        if lender:
            return general_response(lender)

    if loan.application and loan.application.product_line_code in ProductLineCodes.axiata():
        application = loan.application
    else:
        application = loan.get_application

    lender, is_bypass = get_bypass_lender_matchmaking(loan, application=application)
    if is_bypass:
        return general_response(lender)

    if loan.account and loan.account.is_grab_account():
        matched_lender = (
            LenderCurrent.objects.filter(
                lender_name__in=LenderNameByPartner.GRAB,
                lender_status='active',
            )
            .order_by('lenderdisbursecounter__rounded_count', 'lenderdisbursecounter__cdate')
            .first()
        )
        return general_response(matched_lender)

    manual_disbursement_partners = BulkDisbursementSchedule.objects.filter(
        is_manual_disbursement=True, is_active=True
    ).values_list('partner__name', flat=True)
    if manual_disbursement_partners:
        if (
            loan.account
            and PartnerLoanRequest.objects.filter(
                loan=loan, partner__name__in=manual_disbursement_partners
            ).exists()
        ):
            assigned_lender = LenderCurrent.objects.get_or_none(lender_name='jtp')
            return general_response(assigned_lender)

    today_date = timezone.localtime(timezone.now())
    customer = loan.customer
    customer_age = 0
    if customer.dob:
        customer_age = today_date.year - customer.dob.year
        if today_date.month == customer.dob.month:
            if today_date.day < customer.dob.day:
                customer_age -= 1
        elif today_date.month < customer.dob.month:
            customer_age -= 1

    lender_exclusive_by_product = PartnerConstant.lender_exclusive_by_product()

    try:
        credit_score = [application.creditscore.score]
    except ObjectDoesNotExist:
        credit_score = []

    loan_purpose = [application.loan_purpose]
    company_name = application.company_name
    job_type = [application.job_type]
    job_industry = [application.job_industry]
    product_profile_id = application.product_line.product_profile_id

    if application.is_merchant_flow():
        loan_purpose = loan_purpose if None not in loan_purpose else ['']
        company_name = company_name or ''
        job_type = job_type if None not in job_type else ['']
        job_industry = job_industry if None not in job_industry else ['']

    if not lender_ids:
        lender_ids = []

    lender_ids_from_lender_balance = (
        LenderBalanceCurrent.objects.filter(lender__lender_status="active")
        .exclude(lender__lender_name__in=lender_exclusive_by_product)
        .exclude(lender__id__in=lender_ids)
        .exclude(lender__is_pre_fund_channeling_flow=True)
        .values_list("lender_id", flat=True)
    )

    if not lender_ids_from_lender_balance:
        return None

    matched_lender_products = LenderProductCriteria.objects.filter(
        # lender product criteria filter
        Q(lender_id__in=lender_ids_from_lender_balance)
        & Q(product_profile_list__contains=[product_profile_id])
        & Q(min_duration__lte=loan.loan_duration)
        & Q(max_duration__gte=loan.loan_duration)
        & (  # lender customer filter
            Q(lender__lendercustomercriteria__credit_score__isnull=True)
            | Q(lender__lendercustomercriteria__credit_score=[])
            | Q(lender__lendercustomercriteria__credit_score__contains=credit_score)
        )
        & (
            Q(lender__lendercustomercriteria__company_name__isnull=True)
            | Q(lender__lendercustomercriteria__company_name=[])
            | Q(lender__lendercustomercriteria__company_name__icontains=company_name)
        )
        & (
            Q(lender__lendercustomercriteria__loan_purpose__isnull=True)
            | Q(lender__lendercustomercriteria__loan_purpose=[])
            | Q(lender__lendercustomercriteria__loan_purpose__contains=loan_purpose)
        )
        & (
            Q(lender__lendercustomercriteria__min_age__isnull=True)
            | Q(lender__lendercustomercriteria__min_age__lte=customer_age)
        )
        & (
            Q(lender__lendercustomercriteria__max_age__isnull=True)
            | Q(lender__lendercustomercriteria__max_age__gte=customer_age)
        )
        & (
            Q(lender__lendercustomercriteria__job_type__isnull=True)
            | Q(lender__lendercustomercriteria__job_type=[])
            | Q(lender__lendercustomercriteria__job_type__contains=job_type)
        )
        & (
            Q(lender__lendercustomercriteria__job_industry__isnull=True)
            | Q(lender__lendercustomercriteria__job_industry=[])
            | Q(lender__lendercustomercriteria__job_industry__contains=job_industry)
        )
    ).order_by(
        "lender__lenderdisbursecounter__rounded_count", "lender__lenderdisbursecounter__cdate"
    )

    assigned_lender = None
    for matched_lender_product in matched_lender_products:
        # need available_balance is not enough, next lender automatically selected
        assigned_lender = matched_lender_product.lender
        lender_balance = LenderBalanceCurrent.objects.get_or_none(
            lender=assigned_lender, available_balance__gte=loan.loan_amount
        )

        if lender_balance:
            # lender found, so no need to match another lender
            break

        assigned_lender = None
        logger.info(
            {
                'task': (
                    'juloserver.loan.services.lender_related.julo_one_lender_auto_matchmaking'
                ),
                'loan_id': loan.id,
                'original_lender': matched_lender_product.lender,
                'message': 'lender balance insufficient',
            }
        )

    if not assigned_lender:
        assigned_lender = get_default_lender()

    return general_response(assigned_lender)


def julo_one_get_fama_buyback_lender(loan):
    action = "juloserver.loan.services.lender_related.julo_one_get_fama_buyback_lender"

    lender_balances = LenderBalanceCurrent.objects.filter(
        lender__lender_status="active",
        lender__lender_name__in=(LenderName.BLUEFINC, LenderName.LEGEND_CAPITAL),
        available_balance__gte=loan.loan_amount,
    ).select_related("lender")

    if not lender_balances:
        logger.info(
            {
                "action": action,
                "message": "No lender available",
                "loan_id": loan.id,
                "current_lender": loan.lender.lender_name,
            }
        )

        return None

    return lender_balances.last().lender


def julo_one_disbursement_process(loan, grab=False, new_payment_gateway=False):
    from juloserver.merchant_financing.services import move_to_bulk_queue
    from juloserver.grab.services.loan_related import check_grab_auth_success

    application = None
    bank_account_destination = None
    if loan.account:
        application = loan.get_application
    if not application or not application.is_merchant_flow():
        bank_account_destination = loan.bank_account_destination
        if not bank_account_destination:
            raise JuloException(
                {
                    'action': 'julo_one_disbursement_process',
                    'message': 'bank account destination not found for this loan!!',
                    'loan_id': loan.id,
                }
            )
        name_bank_validation_id = bank_account_destination.name_bank_validation_id
    else:
        distributor = application.merchant.distributor
        name_bank_validation_id = distributor.name_bank_validation_id

    if application and application.is_grab():
        is_auth_called = check_grab_auth_success(loan.id)
        if not is_auth_called:
            update_loan_status_and_loan_history(
                loan_id=loan.id,
                new_status_code=LoanStatusCodes.LENDER_REJECT,
                change_reason="Auth Redundency Check 3 - Failure",
            )
            raise JuloException(
                {
                    'action': 'julo_one_disbursement_process',
                    'message': 'Attempting Disbursal before Auth call!!',
                    'loan_id': loan.id,
                }
            )

    data_to_disburse = {
        'disbursement_id': loan.disbursement_id,
        'name_bank_validation_id': name_bank_validation_id,
        'amount': loan.loan_disbursement_amount,
        'external_id': loan.loan_xid,
        'type': 'loan',
        'original_amount': loan.loan_amount,
    }
    partner = None
    distributor = None
    if (application and application.is_merchant_flow()) or (
        bank_account_destination
        and bank_account_destination.bank_account_category.category
        == BankAccountCategoryConst.PARTNER
    ):
        if loan.product.product_line.product_line_code == ProductLineCodes.MF:
            partner = loan.account.last_application.partner
            distributor = loan.account.last_application.merchant.distributor
        else:
            partner_loan_request = PartnerLoanRequest.objects.filter(loan=loan).last()
            if partner_loan_request:
                partner = partner_loan_request.partner

    bulk_disbursement_active = BulkDisbursementSchedule.objects.filter(
        product_line_code=loan.product.product_line,
        partner=partner,
        distributor=distributor,
        is_active=True,
    ).exists()

    if bulk_disbursement_active:
        if application and application.is_merchant_flow():
            distributor = loan.account.last_application.merchant.distributor
            data_to_disburse['bank_name'] = distributor.bank_name
            data_to_disburse['bank_account_number'] = distributor.bank_account_number
        else:
            data_to_disburse['bank_name'] = bank_account_destination.bank.bank_name
            data_to_disburse['bank_account_number'] = bank_account_destination.account_number
        move_to_bulk_queue(loan, data_to_disburse, partner, distributor)
        return

    # This for merchant financing if bulk_disbursement is not active do xfers process
    if application and application.is_merchant_flow():
        distributor = loan.account.last_application.merchant.distributor
        data_to_disburse['disbursement_id'] = None
        data_to_disburse['bank_name'] = distributor.bank_name
        data_to_disburse['bank_account_number'] = distributor.bank_account_number

    process_disburse(data_to_disburse, loan, grab, new_payment_gateway)


def process_disburse(data_to_disburse, loan, grab=False, new_payment_gateway=False):
    disbursement = trigger_disburse(data_to_disburse, new_payment_gateway=new_payment_gateway)
    disbursement_id = disbursement.get_id()
    loan.disbursement_id = disbursement_id
    loan.save(update_fields=['disbursement_id'])
    loan.refresh_from_db()

    # exclude J1 AYC for update to 212
    if not (
        disbursement.disbursement.method == DisbursementVendors.AYOCONNECT
        and loan.product.product_line_id in [ProductLineCodes.J1, ProductLineCodes.JTURBO]
        and loan.loan_status_id == LoanStatusCodes.FUND_DISBURSAL_ONGOING
    ):
        if loan.product.product_line_id != ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT:
            update_loan_status_and_loan_history(
                loan.id,
                new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                change_reason="Loan approved by lender",
            )

    # follow the money block
    ltm = LenderTransactionMapping.objects.filter(
        disbursement_id=disbursement.disbursement.id, lender_transaction_id__isnull=True
    )

    if not ltm:
        try:
            with transaction.atomic():
                update_committed_amount_for_lender_balance(disbursement.disbursement, loan.id)
        except JuloException:
            julo_one_loan_disbursement_failed(loan)
            # change status for disbursement to failed when insufficient balance
            disbursement_obj = disbursement.disbursement
            disbursement_obj.disburse_status = DisbursementStatus.FAILED
            disbursement_obj.reason = "Insufficient {} Balance".format(loan.lender)
            disbursement_obj.save(update_fields=['disburse_status', 'reason'])
            # create history of disbursement
            create_disbursement_new_flow_history(disbursement_obj)
            return True
    # end of follow the money block

    # handle for 13 Feb 2021, due to Xfers service off all day long
    if disbursement.disbursement.method == DisbursementVendors.XFERS:
        xfers_manual_disbursement = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.XFERS_MANUAL_DISBURSEMENT, is_active=True
        )
        is_vospay_partner = False
        partner_property = (
            PartnerProperty.objects.filter(account=loan.account).select_related('partner').last()
        )
        if partner_property:
            partnership_config = PartnershipConfig.objects.filter(
                partner=partner_property.partner
            ).last()
            if (
                partnership_config
                and not partnership_config.order_validation
                and partner_property.partner.name == PartnerNameConstant.VOSPAY
            ):
                if PartnerLoanRequest.objects.filter(loan=loan).exists():
                    is_vospay_partner = check_partnership_type_is_paylater(partner_property.partner)

        change_reason = (
            'Manual disbursement due to vospay partner'
            if is_vospay_partner
            else 'Manual disbursement due to Xfers turn off'
        )
        if xfers_manual_disbursement or is_vospay_partner:
            update_loan_status_and_loan_history(
                loan.id,
                new_status_code=LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
                change_reason=change_reason,
            )
            return

    disbursement.disburse()
    disbursement_data = disbursement.get_data()
    # check disbursement status
    if disbursement.is_success():
        # process partner transaction record
        if loan.partner and loan.partner.is_active_lender:
            record_disbursement_transaction(loan)
        julo_one_loan_disbursement_success(loan)
        if disbursement.disbursement.method == DisbursementVendors.BCA:
            try:
                update_lender_balance_current_for_disbursement(loan.id)
            except JuloException:
                sentry_client = get_julo_sentry_client()
                sentry_client.capture_exceptions()

    elif disbursement.is_failed():
        if isinstance(disbursement, AyoconnectDisbursementProcess):
            logger.info(
                {
                    "action": "process_disburse",
                    "data": data_to_disburse,
                    "is_ayoconnect_process": True,
                }
            )
            if disbursement_data.get("reason") not in (
                AyoconnectErrorReason.ERROR_BENEFICIARY_BLOCKED,
                AyoconnectErrorReason.SYSTEM_UNDER_MAINTENANCE,
            ):
                ayoconnect_loan_disbursement_failed(loan)
        else:
            julo_one_loan_disbursement_failed(loan)


def grab_disbursement_process(loan):
    bank_account_destination = loan.bank_account_destination
    if not bank_account_destination:
        raise JuloException(
            {
                'action': 'grab_disbursement_process',
                'message': 'bank account destination not found for this loan!!',
                'loan_id': loan.id,
            }
        )

    data_to_disburse = {
        'disbursement_id': loan.disbursement_id,
        'name_bank_validation_id': bank_account_destination.name_bank_validation_id,
        'amount': loan.loan_disbursement_amount,
        'external_id': loan.loan_xid,
        'type': 'loan',
        'original_amount': loan.loan_amount,
    }
    disbursement = trigger_disburse(data_to_disburse, application=loan.account.last_application)
    disbursement_id = disbursement.get_id()
    loan.disbursement_id = disbursement_id
    loan.save(update_fields=['disbursement_id'])
    loan.refresh_from_db()

    update_loan_status_and_loan_history(
        loan.id,
        new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        change_reason="Loan approved by lender",
    )

    # follow the money block
    ltm = LenderTransactionMapping.objects.filter(
        disbursement_id=disbursement.disbursement.id, lender_transaction_id__isnull=True
    )

    if not ltm:
        try:
            with transaction.atomic():
                update_committed_amount_for_lender_balance(disbursement.disbursement, loan.id)
        except JuloException:
            julo_one_loan_disbursement_failed(loan)
            # change status for disbursement to failed when insufficient balance
            disbursement_obj = disbursement.disbursement
            disbursement_obj.disburse_status = DisbursementStatus.FAILED
            disbursement_obj.reason = "Insufficient {} Balance".format(loan.lender)
            disbursement_obj.save(update_fields=['disburse_status', 'reason'])
            # create history of disbursement
            create_disbursement_new_flow_history(disbursement_obj)
            return True
    # end of follow the money block

    # handle for 13 Feb 2021, due to Xfers service off all day long
    if disbursement.disbursement.method == DisbursementVendors.XFERS:
        xfers_manual_disbursement = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.XFERS_MANUAL_DISBURSEMENT, is_active=True
        )
        if xfers_manual_disbursement:
            update_loan_status_and_loan_history(
                loan.id,
                new_status_code=LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
                change_reason="Manual disbursement due to Xfers turn off",
            )
            return

    disbursement.disburse()
    # check disbursement status
    if disbursement.is_success():
        # process partner transaction record
        if loan.partner and loan.partner.is_active_lender:
            record_disbursement_transaction(loan)
        julo_one_loan_disbursement_success(loan)
        if disbursement.disbursement.method == DisbursementVendors.BCA:
            try:
                update_lender_balance_current_for_disbursement(loan.id)
            except JuloException:
                sentry_client = get_julo_sentry_client()
                sentry_client.capture_exceptions()

    elif disbursement.is_failed():
        julo_one_loan_disbursement_failed(loan)


def update_payment_due_date_by_account_payment(account_payment):
    payments = account_payment.payment_set.not_paid_active().exclude(
        due_date=account_payment.due_date
    )

    for payment in payments:
        payment.due_date = account_payment.due_date
        payment.update_status_based_on_due_date()
        payment.save()


@transaction.atomic()
def julo_one_loan_disbursement_success(loan):
    loan.refresh_from_db()
    loan.set_fund_transfer_time()
    loan.save()

    update_loan_status_and_loan_history(
        loan.id,
        new_status_code=LoanStatusCodes.CURRENT,
        change_reason=LoanStatusChangeReason.ACTIVATED,
    )
    send_warning_message_low_balance_amount.delay(loan.lender.lender_name)
    generate_account_payment_for_payments(loan)

    if loan.product.product_line_id in ProductLineCodes.allow_for_agreement():
        # this obsolete ticket : https://juloprojects.atlassian.net/browse/LC5-395
        # store_daily_disbursement_limit_amount(loan)
        store_daily_disbursement_score_limit_amount(loan)
    application = loan.get_application
    if application.is_grab():
        trigger_submit_grab_disbursal_creation.delay(loan.id)

    if application.is_julo_one_product():
        execute_after_transaction_safely(lambda: send_loan_for_channeling_task.delay(loan.id))
        execute_after_transaction_safely(lambda: send_loan_prefund_flow_task.delay(loan.id))
        execute_after_transaction_safely(
            lambda: record_channeling_tenure_cap_after_220_task.delay(loan.id)
        )
        execute_after_transaction_safely(
            lambda: store_cashback_new_scheme_by_account_ids.delay([loan.account_id])
        )

    if application.is_julo_one_product() or application.is_julo_starter():
        execute_after_transaction_safely(
            lambda: send_sphp_email_task.apply_async((loan.id,), countdown=60)
        )

        if loan.is_education_product:
            execute_after_transaction_safely(
                lambda: send_education_email_invoice_task.delay(loan.id)
            )
        if loan.is_healthcare_product:
            execute_after_transaction_safely(
                lambda: send_healthcare_email_invoice_task.delay(loan.id)
            )

        # Please fix this for generate pdf and send email train ticket
        sepulsa_transaction = loan.sepulsatransaction_set.last()
        if sepulsa_transaction and (
            sepulsa_transaction.category == SepulsaProductCategory.TRAIN_TICKET
        ):
            execute_after_transaction_safely(lambda: send_train_ticket_email_task.delay(loan.id))

        execute_after_transaction_safely(lambda: generate_julo_care_policy_task.delay(loan.id))

    elif application.product_line_code == ProductLineCodes.EMPLOYEE_FINANCING:
        email_notification_for_employee_financing_loan.delay(loan.id)

    elif loan.is_mf_std_loan():
        execute_after_transaction_safely(
            lambda: partnership_mfsp_send_email_disbursement_notification_task.delay(loan.id)
        )

    elif (
        application.partner
        and application.partner.is_csv_upload_applicable
        and application.product_line_code != ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
    ):
        if application.product_line_code in {ProductLineCodes.BUKUWARUNG, ProductLineCodes.KARGO}:
            email_notification_for_partner_loan.delay(
                loan.id, application.product_line_code, application.email
            )
        else:
            email_notification_for_partner_loan.delay(loan.id, application.product_line_code)


@transaction.atomic()
def ayoconnect_loan_disbursement_success(loan):
    """
    shadowing function due to standarize naming
    """
    julo_one_loan_disbursement_success(loan)


def julo_one_loan_disbursement_failed(loan, force_failed=False, payment_gateway_failed=False):
    from juloserver.loan.tasks.lender_related import (
        loan_disbursement_retry_task,
        loan_payment_point_disbursement_retry_task,
    )

    if payment_gateway_failed:
        if loan.is_grab_loan():
            mark_loan_as_manual_disbursed(loan)
            return

        mark_loan_transaction_failed(loan)
        return

    if (
        is_ecommerce_bank_account(loan.bank_account_destination)
        or loan.is_qris_product
        or (loan.is_ecommerce_product and juloshop_service.get_juloshop_transaction_by_loan(loan))
    ):
        mark_loan_transaction_failed(loan)
        return

    sepulsa_transaction = SepulsaTransaction.objects.filter(loan=loan).last()
    feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DISBURSEMENT_AUTO_RETRY,
        category="disbursement",
        is_active=True,
    ).first()

    if force_failed or not feature:
        if sepulsa_transaction:
            mark_loan_transaction_failed(loan)
            prevent_double_calculate_account_payment_for_loan(loan)
            pn_client = get_julo_pn_client()
            pn_client.infrom_cashback_sepulsa_transaction(
                sepulsa_transaction.customer, sepulsa_transaction.transaction_status, False
            )
            return

        if loan.is_xfers_ewallet_transaction:
            logger.info(
                {
                    'task': 'julo_one_loan_disbursement_failed_xfer_ewallet',
                    'loan_id': loan.id,
                    'status': 'failed',
                }
            )
            mark_loan_transaction_failed(loan)
            return

        logger.info(
            {
                'task': 'send_back_to_170_for_disbursement_auto_retry_task',
                'loan_id': loan.id,
                'status': 'feature inactive',
            }
        )
        update_loan_status_and_loan_history(
            loan.id,
            new_status_code=LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
            change_reason="Manual disbursement",
        )

        return

    # For Leadgen Webview
    partnership_transaction = PartnershipTransaction.objects.filter(loan=loan).exists()
    if partnership_transaction:
        update_loan_status_and_loan_history(
            loan.id,
            new_status_code=LoanStatusCodes.DISBURSEMENT_FAILED_ON_PARTNER_SIDE,
            change_reason=PartnershipChangeReason.DISBURSEMENT_FAILED_ON_PARTNER_SIDE,
        )
        return

    loan.refresh_from_db()
    update_loan_status_and_loan_history(
        loan.id,
        new_status_code=LoanStatusCodes.FUND_DISBURSAL_FAILED,
        change_reason="Disbursement failed",
    )

    if sepulsa_transaction and sepulsa_transaction.is_not_auto_retry_product:
        mark_loan_transaction_failed(loan)
        prevent_double_calculate_account_payment_for_loan(loan)
        return

    prevent_double_calculate_account_payment_for_loan(loan)

    if not sepulsa_transaction:
        params = feature.parameters
        later = timezone.localtime(timezone.now()) + timedelta(hours=params['waiting_hours'])
        loan_disbursement_retry_task.apply_async((loan.id, params['max_retries']), eta=later)
    elif sepulsa_transaction:
        later = timezone.localtime(timezone.now()) + timedelta(
            minutes=DisbursementAutoRetryConstant.PPOB_WAITING_MINUTES
        )
        loan_payment_point_disbursement_retry_task.apply_async(
            (loan.id, DisbursementAutoRetryConstant.PPOB_MAX_RETRIES), eta=later
        )


def ayoconnect_loan_disbursement_failed(loan, force_failed=False):
    """
    This function is called when the disbursement fails for Ayoconnect
    """
    from juloserver.loan.tasks.lender_related import loan_disbursement_retry_task

    delay_in_hours = AyoconnectConst.DEFAULT_RETRY_DELAY_IN_HOUR
    delay_in_mins = AyoconnectConst.DEFAULT_RETRY_DELAY_IN_MIN
    max_retries = AyoconnectConst.MAX_FAILED_RETRIES
    is_j1_or_jturbo_loan = loan.is_j1_or_jturbo_loan()

    logger.info(
        {
            "task": "ayoconnect_loan_disbursement_failed",
            "message": "starting task",
        }
    )
    if not loan.account.is_grab_account() and not is_j1_or_jturbo_loan:
        logger.info(
            {
                "task": "ayoconnect_loan_disbursement_failed",
                "status": "Failed Due to Non grab or none J1 or none Jturbo loan",
            }
        )
        return

    # for GRAB, we use dynamic feature setting
    if not is_j1_or_jturbo_loan:
        grab_disbursement_retry_feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.GRAB_DISBURSEMENT_RETRY, is_active=True
        ).last()
        if grab_disbursement_retry_feature_setting:
            parameter = grab_disbursement_retry_feature_setting.parameters
            delay_in_mins = parameter.get('delay_in_min', delay_in_mins)
            max_retries = parameter.get('max_retry_times', max_retries)

    disbursement_auto_retry_fs = None
    if is_j1_or_jturbo_loan:
        disbursement_auto_retry_fs = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DISBURSEMENT_AUTO_RETRY,
            is_active=True,
        ).last()
        if disbursement_auto_retry_fs:
            params = disbursement_auto_retry_fs.parameters
            retry_config = params.get("ayc_configuration", {}).get("retry_config", {})
            delay_in_hours = retry_config.get(
                'delay_in_hours', AyoconnectConst.DEFAULT_RETRY_DELAY_IN_HOUR
            )
            max_retries = retry_config.get('max_retries', AyoconnectConst.MAX_FAILED_RETRIES)

    if force_failed or (is_j1_or_jturbo_loan and not disbursement_auto_retry_fs):
        logger.info(
            {
                'task': 'ayoconnect_loan_disbursement_failed',
                'loan_id': loan.id,
                'status': 'feature inactive',
            }
        )
        update_loan_status_and_loan_history(
            loan.id,
            new_status_code=LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
            change_reason="Manual disbursement / Max retry reached",
        )

        return

    loan.refresh_from_db()
    update_loan_status_and_loan_history(
        loan.id,
        new_status_code=LoanStatusCodes.FUND_DISBURSAL_FAILED,
        change_reason="Disbursement failed",
    )

    prevent_double_calculate_account_payment_for_loan(loan)

    logger.info(
        {
            "task": "ayoconnect_loan_disbursement_failed",
            "message": "end task",
            "max_retries": max_retries,
            "delay_in_hours": delay_in_hours,
            "delay_in_mins": delay_in_mins,
        }
    )
    if is_j1_or_jturbo_loan:
        later = timezone.localtime(timezone.now()) + timedelta(hours=delay_in_hours)
    else:
        later = timezone.localtime(timezone.now()) + timedelta(minutes=delay_in_mins)
    loan_disbursement_retry_task.apply_async((loan.id, max_retries), eta=later)


def julo_one_generate_lender_agreement_document(lender_id):
    lender = LenderCurrent.objects.get_or_none(pk=lender_id)
    if not lender:
        raise LenderException(
            {
                'action': 'julo_one_generate_lla_document',
                'message': 'Lender ID not found!!',
                'lender_id': lender_id,
            }
        )

    loans = Loan.objects.filter(
        loan_status__gte=LoanStatusCodes.CURRENT, lender=lender, lendersignature__isnull=True
    ).values_list("id", flat=True)

    if not loans:
        raise LenderException(
            {
                'action': 'julo_one_generate_lla_document',
                'message': 'Loan not found!!',
                'lender_id': lender_id,
            }
        )

    # total disbursement amount and total loan amount
    fields = ("loan_disbursement_amount", "loan_amount")
    total = {"loan_disbursement_amount": 0, "loan_amount": 0}

    for field in fields:
        subtotal = Loan.objects.filter(id__in=loans).aggregate(Sum('%s' % (field)))

        if not subtotal['%s__sum' % (field)]:
            subtotal['%s__sum' % (field)] = 0

        total[field] = subtotal['%s__sum' % (field)]

    lender_bucket = LenderBucket.objects.create(
        partner=lender.user.partner,
        total_approved=len(loans),
        total_rejected=0,
        total_disbursement=total['loan_disbursement_amount'],
        total_loan_amount=total['loan_amount'],
        loan_ids={"approved": list(loans), "rejected": []},
        is_disbursed=True,
        is_active=True,
        action_time=timezone.localtime(timezone.now()),
        action_name='Disbursed',
    )

    # generate summary lla
    assign_lenderbucket_xid_to_lendersignature(loans, lender_bucket.lender_bucket_xid, is_loan=True)
    generate_summary_lender_loan_agreement.delay(lender_bucket.id)


def payment_point_disbursement_process(sepulsa_transaction):
    loan = sepulsa_transaction.loan
    trigger_disbursement_step_1 = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DISBURSEMENT_STEP_1_NON_CASH, is_active=True
    ).last()
    disbursement = None
    if trigger_disbursement_step_1:
        application = loan.get_application
        data_to_disburse = {
            'disbursement_id': loan.disbursement_id,
            'name_bank_validation_id': application.name_bank_validation_id,
            'amount': loan.loan_disbursement_amount,
            'external_id': loan.loan_xid,
            'type': 'loan',
            'original_amount': loan.loan_amount,
        }
        disbursement = trigger_disburse(data_to_disburse)
        disbursement_id = disbursement.get_id()
        loan.disbursement_id = disbursement_id
        loan.save(update_fields=['disbursement_id'])
        loan.refresh_from_db()

    update_loan_status_and_loan_history(
        loan.id,
        new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        change_reason="Loan approved by lender",
    )

    ltm = LenderTransactionMapping.objects.filter(
        sepulsa_transaction=sepulsa_transaction, lender_transaction_id__isnull=True
    )

    if not ltm:
        try:
            with transaction.atomic():
                update_committed_amount_for_lender_balance_payment_point(sepulsa_transaction)
                ltm_current = LenderTransactionMapping.objects.filter(
                    sepulsa_transaction=sepulsa_transaction, lender_transaction_id__isnull=False
                )
                update_lender_balance_current_for_disbursement(
                    loan.id,
                    lender_transaction_id=ltm_current.values_list('lender_transaction', flat=True),
                )
        except JuloException as je:
            if disbursement:
                disbursement_obj = disbursement.disbursement
                disbursement_obj.disburse_status = DisbursementStatus.FAILED
                disbursement_obj.reason = "Insufficient {} Balance".format(loan.lender)
                disbursement_obj.save(update_fields=['disburse_status', 'reason'])
                # create history of disbursement
                create_disbursement_new_flow_history(disbursement_obj)
            logger.info(
                {
                    'method': 'payment_point_disbursement_process',
                    'loan_id': loan.id,
                    'msg': 'update_committed_amount_for_lender_balance_payment_point failed',
                    'error_msg': str(je),
                }
            )
            return True
    # end of follow the money block
    sepulsa_service = SepulsaLoanService()
    response = {}
    try:
        is_enough = sepulsa_service.is_balance_enough_for_transaction(loan.loan_amount)
        if not is_enough:
            raise JuloException(
                "not enough sepulsa balance for transaction loan {}".format(loan.id)
            )
        sepulsa_client = get_julo_sepulsa_loan_client()
        response = sepulsa_client.create_transaction(sepulsa_transaction)
        sepulsa_transaction = sepulsa_service.update_sepulsa_transaction_with_history_accordingly(
            sepulsa_transaction, 'create_transaction', response
        )
    except JuloException as je:
        logger.info(
            {
                'method': 'payment_point_disbursement_process',
                'loan_id': loan.id,
                'sepulsa_transaction_id': sepulsa_transaction.id,
                'msg': 'create_transaction_sepulsa_failed',
                'error_msg': str(je),
            }
        )

    if disbursement:
        disbursement.disburse()
        disbursement.get_data()
    response_code = response.get('response_code')
    # check disbursement status
    if response_code and response_code in SepulsaResponseCodes.SUCCESS:
        # process partner transaction record
        if loan.partner and loan.partner.is_active_lender:
            record_disbursement_transaction(loan)
        julo_one_loan_disbursement_success(loan)
        pn_client = get_julo_pn_client()
        pn_client.infrom_cashback_sepulsa_transaction(
            sepulsa_transaction.customer, sepulsa_transaction.transaction_status, False
        )
    elif not response_code or response_code in SepulsaResponseCodes.FAILED:
        process_sepulsa_transaction_failed(sepulsa_transaction)
        julo_one_loan_disbursement_failed(loan)
    # the pending status will go to the cron job that is check_transaction_sepulsa_loan()


def return_lender_balance_amount(loan):
    from juloserver.qris.services.transaction_related import is_qris_loan_from_partner

    with transaction.atomic():
        if not loan.lender:
            return

        if loan.is_qris_1_product and is_qris_loan_from_partner(
            loan, partner_name=PartnerNameConstant.AMAR
        ):
            return

        disbursment_id = loan.disbursement_id
        lender_mapping_filter_params = {
            'disbursement_id': disbursment_id,
        }
        if loan.is_payment_point_product():
            # if payment point, use sepulsa transaction on lender mapping
            sepulsa_transaction = SepulsaTransaction.objects.filter(loan=loan).last()
            if sepulsa_transaction:
                disbursment_id = sepulsa_transaction.id
                lender_mapping_filter_params = {
                    'sepulsa_transaction_id': disbursment_id,
                }

        juloshop_transaction = get_juloshop_transaction_by_loan(loan)
        if loan.is_ecommerce_product and juloshop_transaction:
            disbursment_id = juloshop_transaction.id
            lender_mapping_filter_params = {'juloshop_transaction': juloshop_transaction}

        if not disbursment_id:
            raise JuloException("Disbursement id is null")

        lender_transaction_mapping = LenderTransactionMapping.objects.filter(
            **lender_mapping_filter_params,
        ).exists()
        if not lender_transaction_mapping:
            return
        lender_balance_current = (
            LenderBalanceCurrent.objects.select_for_update().filter(lender=loan.lender).last()
        )
        if lender_balance_current:
            repayment_transaction_type = LenderTransactionType.objects.get_or_none(
                transaction_type=LenderTransactionTypeConst.REPAYMENT
            )

            # create transaction for repayment
            LenderTransaction.objects.create(
                lender=loan.lender,
                lender_balance_current=lender_balance_current,
                transaction_type=repayment_transaction_type,
                transaction_amount=loan.loan_amount,
            )

            updated_data_dict = {
                'repayment_amount': loan.loan_amount,
            }

            calculate_available_balance.delay(
                lender_balance_current.id, SnapshotType.TRANSACTION, **updated_data_dict
            )


def mark_loan_transaction_failed(loan):
    update_loan_status_and_loan_history(
        loan.id,
        new_status_code=LoanStatusCodes.TRANSACTION_FAILED,
        change_reason="Disbursement failed",
    )


def mark_loan_as_manual_disbursed(loan):
    update_loan_status_and_loan_history(
        loan.id,
        new_status_code=LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
        change_reason="PG Service disbursement failed",
    )


def qris_disbursement_process(loan):
    qris_service = QrisService(loan.account)
    qris_transaction = loan.qris_transaction

    update_loan_status_and_loan_history(
        loan.id,
        new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        change_reason="Loan approved by lender",
    )

    ltm = LenderTransactionMapping.objects.filter(
        qris_transaction=qris_transaction, lender_transaction_id__isnull=True
    )

    if not ltm:
        try:
            with transaction.atomic():
                update_committed_amount_for_lender_balance_qris(qris_transaction)
                update_lender_balance_current_for_disbursement(loan.id)
        except JuloException as e:
            logger.info(
                {
                    'method': 'qris_disbursement_process',
                    'loan_id': loan.id,
                    'msg': 'update_committed_amount_for_lender_balance_qris_failed',
                    'error_msg': str(e),
                }
            )
            return True
    if qris_service.payment_qris(qris_transaction):
        julo_one_loan_disbursement_success(loan)
    else:
        julo_one_loan_disbursement_failed(loan)


def prevent_double_calculate_account_payment_for_loan(loan):
    from juloserver.account_payment.services.account_payment_related import void_ppob_transaction

    loan.refresh_from_db()
    unexpected_path = loan.loanhistory_set.order_by('cdate').last()
    unexpected_new_statuses = [
        LoanStatusCodes.FUND_DISBURSAL_FAILED,
        LoanStatusCodes.TRANSACTION_FAILED,
        LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
    ]
    if (
        unexpected_path.status_old == LoanStatusCodes.CURRENT
        and unexpected_path.status_new in unexpected_new_statuses
    ):
        void_ppob_transaction(loan)
    return


def is_grab_lender_balance_sufficient(loan):
    lender = loan.lender
    if not lender:
        return False, "Lender not found"

    lender_balance = lender.lenderbalancecurrent
    if not lender_balance:
        return False, "Lender balance current not exist"

    if lender_balance.available_balance < loan.loan_amount:
        return False, "Insufficient balance"

    return True, None


def credit_card_disbursement_process(loan):
    application = loan.get_application
    data_to_disburse = {
        'disbursement_id': loan.disbursement_id,
        'name_bank_validation_id': application.name_bank_validation_id,
        'amount': loan.loan_disbursement_amount,
        'external_id': loan.loan_xid,
        'type': 'loan',
        'original_amount': loan.loan_amount,
    }
    disbursement = trigger_disburse(data_to_disburse)
    disbursement_id = disbursement.get_id()
    loan.disbursement_id = disbursement_id
    loan.save(update_fields=['disbursement_id'])
    loan.refresh_from_db()

    update_loan_status_and_loan_history(
        loan.id,
        new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        change_reason="Loan approved by lender",
    )

    # follow the money block
    ltm = LenderTransactionMapping.objects.filter(
        disbursement_id=disbursement.disbursement.id, lender_transaction_id__isnull=True
    )

    if not ltm:
        try:
            with transaction.atomic():
                update_committed_amount_for_lender_balance(disbursement.disbursement, loan.id)
        except JuloException:
            julo_one_loan_disbursement_failed(loan)
            # change status for disbursement to failed when insufficient balance
            disbursement_obj = disbursement.disbursement
            disbursement_obj.disburse_status = DisbursementStatus.FAILED
            disbursement_obj.reason = "Insufficient {} Balance".format(loan.lender)
            disbursement_obj.save(update_fields=['disburse_status', 'reason'])
            # create history of disbursement
            create_disbursement_new_flow_history(disbursement_obj)
            return True
    # end of follow the money block

    disbursement.disburse()
    disbursement.get_data()

    promo_code = PromoCode.objects.filter(
        promo_name='JULOCARDCASHBACK', promo_code='JULOCARDCASHBACK', is_active=True
    ).last()
    if promo_code:
        loan_credit_card = Loan.objects.filter(
            account=loan.account,
            cdate__lt=loan.cdate,
            transaction_method_id=TransactionMethodCode.CREDIT_CARD.code,
            loan_status_id__gte=LoanStatusCodes.CURRENT,
        ).exists()
        if not loan_credit_card:
            is_valid, _ = check_promo_code_and_get_message(
                promo_code=promo_code,
                loan=loan,
            )
            if is_valid:
                create_promo_code_usage(
                    loan=loan,
                    promo_code=promo_code,
                )
                send_pn_obtained_first_transaction_cashback.delay(loan.customer_id)

    julo_one_loan_disbursement_success(loan)


def julo_one_generate_auto_lender_agreement_document(loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)

    if not loan:
        logger.info(
            {
                'action': 'julo_one_auto_generate_lla_document',
                'message': 'Loan not found!!',
                'loan_id': loan_id,
            }
        )
        return

    lender = loan.lender
    if not lender:
        logger.info(
            {
                'action': 'julo_one_auto_generate_lla_document',
                'message': 'Lender not found!!',
                'loan_id': loan_id,
            }
        )
        return

    existing_lender_bucket = LenderBucket.objects.filter(
        total_approved=1,
        total_disbursement=loan.loan_disbursement_amount,
        total_loan_amount=loan.loan_amount,
        loan_ids__approved__contains=[loan_id],
    )
    if existing_lender_bucket:
        logger.info(
            {
                'action': 'julo_one_auto_generate_lla_document',
                'message': 'Lender bucket already created!!',
                'loan_id': loan_id,
                'lender_bucket_id': existing_lender_bucket.values_list('id', flat=True),
            }
        )
        return

    is_disbursed = False
    if loan.status >= LoanStatusCodes.CURRENT:
        is_disbursed = True

    action_time = timezone.localtime(timezone.now())
    use_fund_transfer = False

    # Handle axiata loan to define transaction time based on
    if loan.is_axiata_loan():
        if loan.fund_transfer_ts:
            action_time = loan.fund_transfer_ts
        else:
            action_time = loan.cdate

        use_fund_transfer = True

    lender_bucket = LenderBucket.objects.create(
        partner=lender.user.partner,
        total_approved=1,
        total_rejected=0,
        total_disbursement=loan.loan_disbursement_amount,
        total_loan_amount=loan.loan_amount,
        loan_ids={"approved": [loan_id], "rejected": []},
        is_disbursed=is_disbursed,
        is_active=False,
        action_time=action_time,
        action_name='Disbursed',
    )

    # generate summary lla
    assign_lenderbucket_xid_to_lendersignature(
        [loan_id], lender_bucket.lender_bucket_xid, is_loan=True
    )
    generate_summary_lender_loan_agreement.delay(lender_bucket.id, use_fund_transfer)

    # cache lender bucket xid for getting application past in lender dashboard
    redis_cache = RedisCacheLoanBucketXidPast()
    redis_cache.set(loan_id, lender_bucket.lender_bucket_xid)


def get_whitelist_manual_approval_feature():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.WHITELIST_MANUAL_APPROVAL,
        is_active=True,
    ).last()


def is_application_whitelist_manual_approval_feature(application_id):
    feature_setting = get_whitelist_manual_approval_feature()
    if feature_setting:
        return application_id in feature_setting.parameters
    return False


# must use transaction.atomic
def generate_account_payment_for_payments(loan):
    account = Account.objects.select_for_update().get(pk=loan.account_id)
    payments = loan.payment_set.normal().not_paid_active().order_by('payment_number')
    status_code = StatusLookup.objects.get_or_none(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
    for payment in payments:
        if (
            account.is_grab_account()
            or loan.product.product_line_id in ProductLineCodes.axiata()
            or loan.product.product_line_id in ProductLineCodes.manual_process()
        ):
            account_payment = (
                AccountPayment.objects.select_for_update()
                .filter(
                    account=loan.account,
                    due_date__day=payment.due_date.day,
                    due_date__month=payment.due_date.month,
                    due_date__year=payment.due_date.year,
                )
                .last()
            )
        else:
            account_payment = (
                AccountPayment.objects.select_for_update()
                .filter(
                    account=loan.account,
                    due_date=payment.due_date,
                    is_restructured=False,
                )
                .last()
            )

        if not account_payment:
            account_payment = AccountPayment.objects.create(
                account=loan.account,
                late_fee_amount=0,
                due_date=payment.due_date,
                status=status_code,
            )
        else:
            status = account_payment.status.status_code
            if status >= PaymentStatusCodes.PAID_ON_TIME:
                history_data = {
                    'status_old': account_payment.status,
                    'change_reason': 'New payment added',
                }
                account_payment.change_status(PaymentStatusCodes.PAYMENT_NOT_DUE)
                account_payment.save(update_fields=['status'])
                account_payment.create_account_payment_status_history(history_data)

        account_payment.due_amount += payment.due_amount
        account_payment.principal_amount += payment.installment_principal
        account_payment.interest_amount += payment.installment_interest

        # interest discount promocode has waive interest feature .
        # So save the paid value also in account payment.
        if payment.paid_interest:
            account_payment.paid_interest += payment.paid_interest
            account_payment.paid_amount += payment.paid_amount

        account_payment.due_date = payment.due_date
        account_payment.save(
            update_fields=[
                'due_amount',
                'principal_amount',
                'interest_amount',
                'due_date',
                'paid_amount',
                'paid_interest',
            ]
        )
        update_payment_due_date_by_account_payment(account_payment)
        payment.update_safely(account_payment=account_payment)

    transaction_amount = loan.loan_amount * -1
    transaction_type = 'disbursement'
    spend_transaction = None

    if loan.is_qris_product:
        transaction_type = 'qris'
        vendor = Vendor.objects.filter(vendor_name='doku').last()
        qris_transaction = loan.qris_transaction
        spend_transaction = SpendTransaction.objects.create(
            spend_product=qris_transaction, vendor=vendor
        )
    else:
        sepulsa_transaction = SepulsaTransaction.objects.filter(loan=loan).last()
        if sepulsa_transaction:
            transaction_type = 'ppob'
            vendor = Vendor.objects.filter(vendor_name='sepulsa').last()
            spend_transaction = SpendTransaction.objects.create(
                spend_product=sepulsa_transaction, vendor=vendor
            )
    AccountTransaction.objects.create(
        account=loan.account,
        payback_transaction=None,
        disbursement_id=loan.disbursement_id,
        transaction_date=loan.fund_transfer_ts,
        transaction_amount=transaction_amount,
        transaction_type=transaction_type,
        towards_principal=transaction_amount,
        towards_interest=0,
        towards_latefee=0,
        spend_transaction=spend_transaction,
    )


def reassign_lender_or_expire_loan_x211_in_first_time(loan_query_set: QuerySet, time_now: datetime):
    loans = loan_query_set.filter(
        cdate__lte=time_now - F('expired_in'),
        loanlenderhistory__isnull=True,
    ).values('pk', 'lender_id')

    for loan in loans:
        auto_expired_loan_tasks.delay(loan['pk'], loan['lender_id'])

    logger.info(
        {"action": "reasign_lender_or_expire_loan_x211_in_first_time", "list_loan_ids": loans}
    )


def reassign_lender_or_expire_loan_x211_in_next_retry(loan_query_set: QuerySet, time_now: datetime):
    loans = loan_query_set.prefetch_related('loanlenderhistory_set').filter(
        loanlenderhistory__isnull=False
    )

    for loan in loans:
        last_lender_history = loan.loanlenderhistory_set.last()
        expired_time = last_lender_history.cdate + relativedelta(
            hours=loan.expired_in.hour, minutes=loan.expired_in.minute
        )

        if time_now > expired_time:
            auto_expired_loan_tasks.delay(loan.pk, loan.lender_id)

    logger.info(
        {"action": "reasign_lender_or_expire_loan_x211_in_next_retry", "list_loan_ids": loans}
    )


def handle_ayoconnect_beneficiary_errors_on_disbursement(
    loan: Loan, disbursement_reason: str
) -> None:
    """
    when disbursement API or disbursement callback got some beneficiary errors
    -> change beneficiary status to unknown to re-create beneficiary on next retry
    """
    pg_customer_data_loan = PaymentGatewayCustomerDataLoan.objects.filter(
        loan_id=loan.id,
        disbursement__method=DisbursementVendors.AYOCONNECT,
    ).last()
    if pg_customer_data_loan and disbursement_reason in AyoconnectErrorCodes.J1_RECREATE_BEN_IDS:
        PaymentGatewayCustomerData.objects.filter(
            beneficiary_id=pg_customer_data_loan.beneficiary_id,
            customer_id=loan.customer_id,
        ).update(status=AyoconnectBeneficiaryStatus.UNKNOWN_DUE_TO_UNSUCCESSFUL_CALLBACK)


def is_disbursement_stuck_less_than_threshold(disbursement_created_at: datetime) -> bool:
    """
    if the loan is stuck for less than threshold, we will failover to xfers
    """
    now = timezone.localtime(timezone.now())
    return disbursement_created_at >= now - timedelta(
        days=AyoconnectFailoverXfersConst.STUCK_DAYS_BEFORE_FAILING_OVER
    )


def switch_disbursement_to_xfers(disbursement: Disbursement, lender_name: str, reason: str) -> None:
    """
    update method and other related attributes to Xfers to continue the re-disburse with Xfers
    """
    create_disbursement_new_flow_history(disbursement, reason)

    disbursement.retry_times = 0
    disbursement.disburse_status = DisbursementStatus.INITIATED
    disbursement.method = DisbursementVendors.XFERS
    disbursement.reason = None
    disbursement.disburse_id = None
    disbursement.reference_id = None
    disbursement.step = XfersDisbursementStep.FIRST_STEP
    if lender_name in LenderCurrent.escrow_lender_list():
        disbursement.step = XfersDisbursementStep.SECOND_STEP
    disbursement.save(
        update_fields=[
            'retry_times',
            'disburse_status',
            'method',
            'reason',
            'disburse_id',
            'reference_id',
            'step',
        ]
    )

    disbursement.create_history('update method', ['method'])


def get_ayc_disbursement_feature_setting():
    fs = FeatureSetting.objects.filter(feature_name=FeatureNameConst.DISBURSEMENT_AUTO_RETRY).last()
    return fs.parameters.get('ayc_configuration', {}) if fs else dict()
