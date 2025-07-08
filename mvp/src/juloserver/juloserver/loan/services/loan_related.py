from __future__ import division

from builtins import str
import json
from typing import Dict, Tuple, Optional

from django.forms import model_to_dict

from juloserver.fraud_security.constants import DeviceConst
from juloserver.julo.product_lines import ProductLineCodes
import semver
from builtins import range
from past.utils import old_div
from requests.exceptions import Timeout
import logging
import math
from dateutil.relativedelta import relativedelta
from datetime import timedelta, date, datetime

from django.db.models import Q, F, Min
from django.utils import timezone
from django.db import transaction

from juloserver.ana_api.models import (
    ZeroInterestExclude,
    FDCPlatformCheckBypass,
)
from juloserver.apiv2.models import PdClcsPrimeResult
from juloserver.cfs.constants import TierId

from juloserver.julocore.common_services.redis_service import query_redis_ids_whitelist
from juloserver.julocore.context_manager import db_transactions_atomic
from juloserver.julocore.constants import DbConnectionAlias, RedisWhiteList
from juloserver.fdc.constants import FDCLoanStatus
from juloserver.grab.clients.paths import GrabPaths
from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.julo.utils import execute_after_transaction_safely, replace_day
from juloserver.loan.services.adjusted_loan_matrix import (
    validate_max_fee_rule_by_loan_requested,
    get_adjusted_monthly_interest_rate_case_exceed,
    get_adjusted_total_interest_rate,
    get_loan_amount_and_provision_non_tarik_dana_delay_disbursement,
)
from juloserver.cfs.services.core_services import check_lock_by_customer_tier, is_graduate_of
from juloserver.loan.services.loan_prize_chance import (
    handle_loan_prize_chance_on_loan_status_change,
)
from juloserver.moengage.constants import MoengageEventType
from juloserver.moengage.services.use_cases import (
    send_transaction_status_event_to_moengage,
    send_user_attributes_to_moengage_for_active_platforms_rule,
    send_gtl_event_to_moengage,
)
from juloserver.loan.exceptions import CreditMatrixNotFound, LoanDbrException
from juloserver.promo.services import (
    check_and_apply_application_promo_code,
    check_and_apply_promo_code_benefit,
    return_promo_code_usage_count,
    process_interest_discount_benefit,
)
from juloserver.qris.services.feature_settings import QrisWhitelistSetting
from juloserver.standardized_api_response.utils import general_error_response
from juloserver.streamlined_communication.models import InAppNotificationHistory
from juloserver.account.services.account_related import (
    is_new_loan_part_of_bucket5,
    is_account_hardtoreach,
    update_cycle_day_history,
    is_account_exceed_dpd_threshold,
)
from juloserver.account.services.credit_limit import update_available_limit
from juloserver.julo.formulas import (
    round_rupiah,
    determine_first_due_dates_by_payday,
    calculate_first_due_date_ldde_old_flow,
    calculate_first_due_date_ldde_v2_flow,
)
from juloserver.julo.models import (
    CreditMatrix,
    CreditMatrixProductLine,
    CreditScore,
    Customer,
    Loan,
    StatusLookup,
    Payment,
    LoanHistory,
    PaymentMethod,
    MobileFeatureSetting,
    FeatureSetting,
    LoanStatusChange,
    ExperimentSetting,
    Workflow,
    WorkflowStatusPath,
    Application,
    FDCActiveLoanChecking,
    FDCInquiry,
    FDCRejectLoanTracking,
    FDCInquiryLoan,
)
from juloserver.referral.services import (
    process_referral_code_v2,
    get_referral_benefit_logic_fs,
    update_referrer_counting,
)
from juloserver.julo.services import (
    update_is_proven_julo_one,
    get_julo_one_is_proven,
    check_fraud_hotspot_gps,
    capture_device_geolocation,
)
from juloserver.julo.statuses import (
    JuloOneCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
    ApplicationStatusCodes,
)
from juloserver.julo.exceptions import (
    JuloException,
    JuloInvalidStatusChange,
)

from juloserver.account.constants import (
    TransactionType,
    AccountConstant,
    LDDEReasonConst,
    AccountLockReason,
)
from juloserver.account.models import (
    Account,
    CreditLimitGeneration,
    AccountCycleDayHistory,
    AccountGTL,
    AccountGTLHistory,
    AccountLimit
)
from juloserver.account.services.credit_limit import (
    get_credit_matrix,
    get_credit_matrix_parameters_from_account_property,
)
from juloserver.loan.constants import (
    LoanJuloOneConstant,
    TransactionRiskyDecisionName,
    FDCUpdateTypes,
    DBRConst,
    LoanFeatureNameConst,
    CustomerSegmentsZeroInterest,
    CampaignConst,
    JuloCareStatusConst,
    LoanStatusChangeReason,
    GTLOutsideConstant,
    ErrorCode,
    LoanFailGTLReason,
    IS_NAME_IN_BANK_MISMATCH_TAG,
    DEFAULT_LOCK_PRODUCT_BOTTOM_SHEET_INFO
)
from juloserver.followthemoney.constants import LenderTransactionTypeConst
from juloserver.followthemoney.models import LenderCurrent, LenderTransactionMapping
from juloserver.followthemoney.services import deposit_internal_lender_balance
from juloserver.payment_point.models import TransactionMethod
from juloserver.julocore.python2.utils import py2round
from juloserver.julo.constants import (
    BYPASS_CREDIT_SCORES_FROM_OTHER_PLATFORMS,
    FeatureNameConst,
    ExperimentConst,
    WorkflowConst,
    RedisLockKeyName,
)
from juloserver.entry_limit.services import check_lock_by_entry_level_limit
from juloserver.customer_module.services.bank_account_related import is_ecommerce_bank_account
from juloserver.julo.services2.fraud_check import get_client_ip_from_request, check_suspicious_ip
from juloserver.loan.models import (
    TransactionRiskyCheck,
    TransactionRiskyDecision,
    LoanAdjustedRate,
    LoanJuloCare,
    LoanZeroInterest,
    LoanFailGTL,
    Platform,
    LoanPlatform,
    LoanTransactionDetail,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.loan.utils import sort_transaction_method_limit_params
from juloserver.grab.clients.clients import GrabClient, send_grab_api_timeout_alert_slack
from juloserver.fdc.models import InitialFDCInquiryLoanData
from juloserver.fdc.services import (
    store_initial_fdc_inquiry_loan_data,
    get_or_non_fdc_inquiry_not_out_date,
    get_info_active_loan_from_platforms,
)
from juloserver.grab.tasks import trigger_push_notification_grab
from juloserver.account.services.account_related import (
    get_account_property_by_account,
    get_data_from_ana_calculate_cycle_day,
)
from juloserver.grab.tasks import trigger_grab_loan_sync_api_async_task
from juloserver.integapiv1.tasks import update_va_bni_transaction
from juloserver.loan.services.loan_tax import (
    insert_loan_tax,
    calculate_tax_amount,
    insert_loan_digisign_fee,
    insert_loan_registration_fees,
)
from juloserver.loan.services.dbr_ratio import LoanDbrSetting
from juloserver.loan.services.loan_event import send_loan_status_changed_to_ga_appsflyer_event
from juloserver.application_flow.services import check_is_success_goldfish
from juloserver.julo.context_managers import redis_lock_for_update
from juloserver.dana.models import DanaCustomerData, DanaApplicationReference
from juloserver.loyalty.tasks import execute_loyalty_transaction_mission_task
from juloserver.application_flow.models import ApplicationPathTag
from juloserver.channeling_loan.constants import FeatureNameConst as ChannelingFeatureNameConst
from juloserver.antifraud.services.fraud_block import is_fraud_blocked
from juloserver.antifraud.models.fraud_block import FraudBlock
from juloserver.loan.services.delayed_disbursement_related import (
    insert_delay_disbursement_fee,
    DelayedDisbursementStatus,
)
from juloserver.loan.services.delayed_disbursement_related import (
    process_delayed_disbursement_cashback,
)
from juloserver.digisign.services.common_services import (
    insert_registration_fees,
    update_registration_fees_status
)
from juloserver.fdc.services import get_fdc_status
from juloserver.loan.data import LoanTransactionDetailData
from juloserver.loan.services.feature_settings import AutoAdjustDueDateSetting
from juloserver.julo.constants import MINIMUM_DAY_DIFF_LDDE_v2_FLOW
from juloserver.promo.constants import PromoCodeBenefitConst


logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def get_transaction_type(
    is_self_bank_account, ppob_transaction=None, bank_account_destination=None
):
    if ppob_transaction:
        return TransactionType.PPOB
    if is_self_bank_account:
        return TransactionType.SELF
    if is_ecommerce_bank_account(bank_account_destination):
        return TransactionType.ECOMMERCE
    return TransactionType.OTHER


def get_loan_duration(
    loan_amount_request, max_duration, min_duration, set_limit, customer=None, application=None
):
    def length_experiment_duration() -> int:
        if customer is None:
            return 0

        current_time = timezone.localtime(timezone.now())
        experiment = ExperimentSetting.objects.filter(
            code=ExperimentConst.LOAN_DURATION_DETERMINATION,
            start_date__lte=current_time,
            end_date__gte=current_time,
            is_active=True,
        ).last()

        if experiment is None:
            return 0

        # the criteria will be like this
        # {"customer_id": ['#last:2:1,2,3,4', '#last:3:1,2,3,3,4']}
        criteria = experiment.criteria
        chosen_length = 0
        for value in criteria["customer_id"]:
            value_split = value.split(':')
            if value_split[0] != '#last':
                continue

            length = int(value_split[1])
            end_digits = value_split[2].split(',')
            last_digit = str(customer.id)[-1:]
            if last_digit in end_digits and (
                (chosen_length == 0 and length > 0) or (length < chosen_length)
            ):
                chosen_length = length

        return chosen_length

    original_max_duration = max_duration
    original_min_duration = min_duration

    max_limit_pre_matrix = 0

    if application:
        credit_limit = CreditLimitGeneration.objects.filter(application=application).last()
        if credit_limit:
            credit_limit_log_json = json.loads(credit_limit.log)
            max_limit_pre_matrix = int(credit_limit_log_json.get("max_limit (pre-matrix)", 0))

        if max_limit_pre_matrix > set_limit:
            set_limit = max_limit_pre_matrix

        if set_limit > LoanJuloOneConstant.MAX_LOAN_DURATION_AMOUNT:
            set_limit = LoanJuloOneConstant.MAX_LOAN_DURATION_AMOUNT

    old_div_limit = old_div(float(loan_amount_request), float(set_limit))
    loan_min_duration = int(
        py2round((old_div_limit * (max_duration - min_duration)) + min_duration)
    )
    loan_min_duration = loan_min_duration if loan_min_duration <= max_duration else max_duration
    loan_max_duration = calculate_max_duration_from_additional_month_param(
        customer=customer,
        cm_max_duration=max_duration,
        min_duration=loan_min_duration,
    )

    # Calculate max duration from feature setting
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LOAN_MAX_ALLOWED_DURATION, is_active=True
    ).last()

    if feature_setting:
        sorted_params = sorted(feature_setting.parameters, key=lambda i: i['min_amount'])
        for params in sorted_params:
            index = sorted_params.index(params)
            is_valid = params['min_amount'] < loan_amount_request <= params['max_amount']
            if index == 0:
                is_valid = params['min_amount'] <= loan_amount_request <= params['max_amount']
            if is_valid and loan_max_duration > params['duration']:
                loan_max_duration = params['duration']
                if loan_min_duration > loan_max_duration:
                    loan_max_duration = loan_min_duration
                break

    parameters = get_feature_settings_parameters()
    number_of_tenure_options = parameters.get(
        'number_of_loan_tenures', LoanJuloOneConstant.NUMBER_TENURE
    )

    if (loan_max_duration - loan_min_duration) >= number_of_tenure_options:
        loan_max_duration = loan_min_duration + (number_of_tenure_options - 1)

    loan_durations = []
    for duration in range(int(loan_min_duration), int(loan_max_duration) + 1):
        loan_durations.append(duration)

    length_experiment = length_experiment_duration()
    if customer is not None and length_experiment != 0:
        if len(loan_durations) <= length_experiment:
            return loan_durations
        else:
            return loan_durations[:length_experiment]

    logger.info(
        {
            "action": "juloserver.loan.services.loan_related.get_loan_duration",
            "input_max_duration": original_max_duration,
            "input_min_duration": original_min_duration,
            "result_max_duration": max_duration,
            "result_min_duration": min_duration,
            "customer_id": customer.id if customer else '',
        }
    )

    return loan_durations


def calculate_max_duration_from_additional_month_param(
    customer: Customer, cm_max_duration: int, min_duration: int
) -> int:
    """
    https://juloprojects.atlassian.net/browse/LOL-2737
    To make sure:
        -diff between max & min doesn't exceed additional month value
        -make sure max duration < credit-matrix-max duration
    Params:
        cm_max_duration: max duration from credit matrix
        min_duration: calculated from formula
    """
    additional_month = get_loan_additional_month(customer)
    max_duration = min_duration + additional_month

    # can't be more than that of Credit matrix
    max_duration = min(cm_max_duration, max_duration)

    return max_duration


def get_loan_additional_month(customer: Customer) -> int:
    """
    Get additional month from FS
    """
    DEFAULT_ADDITIONAL_MONTH = 5

    fs = FeatureSettingHelper(
        feature_name=LoanFeatureNameConst.LOAN_TENURE_ADDITIONAL_MONTH,
    )

    if fs.is_active:
        fs_additional_month = fs.params['additional_month']

        # Check if whitelist is active
        if fs.params['whitelist']['is_active']:
            # Return additional month if customer is in whitelist
            if customer and customer.id in fs.params['whitelist']['customer_ids']:
                return fs_additional_month
        else:
            # Return additional month if whitelist is not active
            return fs_additional_month

    return DEFAULT_ADDITIONAL_MONTH


def get_feature_settings_parameters():
    feature_settings = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.NUMBER_TENURE_OPTION, is_active=True
    ).last()
    if not feature_settings:
        return dict()

    return feature_settings.parameters


def calculate_installment_amount(loan_amount_request, duration, interest_fee):
    principal = old_div(loan_amount_request, duration)
    interest = interest_fee * loan_amount_request
    installment_amount = principal + interest
    # special case to handle interest 0% caused by max_fee rule
    if interest_fee == 0.0 or duration == 1:
        return int(installment_amount)

    installment_amount = round_rupiah(installment_amount)
    return int(installment_amount)


def get_credit_matrix_and_credit_matrix_product_line_v2(
    application: Application, is_self_bank_account=True, payment_point=None, transaction_type=None
) -> Tuple[CreditMatrix, CreditMatrixProductLine]:
    """
    Get both credit matrix (CM) & CM product line
    """
    if not transaction_type:
        transaction_type = get_transaction_type(is_self_bank_account, payment_point)

    # get params to filter CM with
    credit_matrix_params = get_loan_credit_matrix_params(
        app=application,
    )
    if not credit_matrix_params:
        return None, None

    # get 'parameter' field for filtering
    field_param = get_credit_matrix_field_param(app=application)

    credit_matrix = get_credit_matrix(
        parameters=credit_matrix_params,
        transaction_type=transaction_type,
        parameter=field_param,
    )

    if not credit_matrix:
        raise CreditMatrixNotFound

    # CM product line
    credit_matrix_product_line = CreditMatrixProductLine.objects.filter(
        credit_matrix=credit_matrix, product=application.product_line
    ).last()

    # logging
    logger.info(
        {
            "action": "get_credit_matrix_and_credit_matrix_product_line_v2",
            "customer_id": application.customer_id,
            "application_id": application.id,
            "field_param": field_param,
            "credit_matrix_params": credit_matrix_params,
            "credit_matrix_id": credit_matrix.id if credit_matrix else "",
            "credit_matrix_product_line_id": (
                credit_matrix_product_line.id if credit_matrix_product_line else ""
            ),
            "payment_point": payment_point,
            "transaction_type": transaction_type,
            "is_self_bank_account": is_self_bank_account,
        }
    )

    return credit_matrix, credit_matrix_product_line


def get_credit_matrix_and_credit_matrix_product_line_v1(
    application: Application, is_self_bank_account=True, payment_point=None, transaction_type=None
):
    """
    Get both credit matrix (CM) & CM product line
    (old, without dynamic special parameters filtering)
    """
    if not transaction_type:
        transaction_type = get_transaction_type(is_self_bank_account, payment_point)

    credit_matrix_params = get_loan_credit_matrix_params(app=application)
    if not credit_matrix_params:
        return None, None

    parameter = None
    revive_semi_good_score = get_revive_semi_good_customer_score(application)
    if revive_semi_good_score:
        credit_matrix_params['score'] = revive_semi_good_score
        parameter = Q(parameter='feature:is_semi_good')

    if check_is_success_goldfish(application):
        parameter = Q(parameter='feature:is_goldfish')

    credit_matrix = get_credit_matrix(credit_matrix_params, transaction_type, parameter)

    credit_matrix_product_line = CreditMatrixProductLine.objects.filter(
        credit_matrix=credit_matrix, product=application.product_line
    ).last()

    # logging
    logger.info(
        {
            "action": "get_credit_matrix_and_credit_matrix_product_line_v1",
            "customer_id": application.customer_id,
            "application_id": application.id,
            "revive_semi_good_score": revive_semi_good_score,
            "parameter": parameter,
            "credit_matrix_params": credit_matrix_params,
            "credit_matrix_id": credit_matrix.id if credit_matrix else "",
            "credit_matrix_product_line_id": (
                credit_matrix_product_line.id if credit_matrix_product_line else ""
            ),
            "payment_point": payment_point,
            "transaction_type": transaction_type,
            "is_self_bank_account": is_self_bank_account,
        }
    )

    return credit_matrix, credit_matrix_product_line


def get_credit_matrix_and_credit_matrix_product_line(
    application: Application,
    is_self_bank_account: bool = True,
    payment_point: bool = None,
    transaction_type: str = None,
) -> Tuple[CreditMatrix, CreditMatrixProductLine]:
    """
    Get both credit matrix (CM) & CM product line
    Params:
        - is_self_bank_account: ONLY when no `transaction_type`
        - payment_point: ONLY when no `transaction_type`
        - transaction_type: name of loan transaction method
    """
    fs = FeatureSettingHelper(
        feature_name=LoanFeatureNameConst.NEW_CREDIT_MATRIX_PRODUCT_LINE_RETRIEVAL_LOGIC,
    )

    if fs.is_active:
        return get_credit_matrix_and_credit_matrix_product_line_v2(
            application, is_self_bank_account, payment_point, transaction_type
        )

    return get_credit_matrix_and_credit_matrix_product_line_v1(
        application, is_self_bank_account, payment_point, transaction_type
    )


def get_loan_credit_matrix_params(app: Application) -> Dict:
    """
    For loan services:
    Get paramters to filter with when querying credit matrix
    """
    params = {}

    account = app.account
    account_property = get_account_property_by_account(account)

    if not account_property:
        return {}

    # acount property
    from_account_property = get_credit_matrix_parameters_from_account_property(
        application=app,
        account_property=account_property,
    )

    if from_account_property:
        params.update(**from_account_property)

    # get fdc
    is_fdc = get_fdc_status(app=app)
    params.update(is_fdc=is_fdc)

    return params


def get_credit_matrix_field_param(app: Application) -> Q:
    """
    Get filter for field 'parameter' when querying credit matrix
    """
    field_param_filter = None

    # get field 'parameter' from CLGeneration.credit_matrix table for J1
    field_param = (
        CreditLimitGeneration.objects.filter(
            application=app,
        )
        .exclude(credit_matrix__parameter__exact='')
        .values_list('credit_matrix__parameter', flat=True).last()
    )
    if field_param:
        field_param_filter = Q(parameter=field_param)

    return field_param_filter


def generate_loan_payment_julo_one(
    application,
    loan_requested,
    loan_purpose,
    credit_matrix,
    bank_account_destination=None,
    draft_loan=False,
    promo_code_data=None,
):
    logger.info(
        {
            "action": "generate_loan_payment_julo_one",
            "message": "before generating loan payment",
            "customer_id": application.customer_id,
            "loan_requested": loan_requested,
            "loan_purpose": loan_purpose,
            "credit_matrix_id": credit_matrix.id,
            "bank_account_destination": bank_account_destination,
            "draft_loan": draft_loan,
        }
    )

    from juloserver.integapiv1.services import get_bni_payment_method

    with transaction.atomic():
        today_date = timezone.localtime(timezone.now()).date()
        first_payment_date = get_first_payment_date_by_application(application)
        original_provision_rate = loan_requested['provision_fee']
        transaction_method_id = loan_requested.get('transaction_method_id')
        is_consolidation = loan_requested.get('is_consolidation', False)
        dd_premium = 0
        promo_benefit_data = {}

        kwargs = {}
        if loan_requested.get('is_buku_warung'):
            kwargs = {
                'is_buku_warung': loan_requested.get('is_buku_warung'),
                'duration_in_days': loan_requested.get('duration_in_days'),
            }
        kwargs['transaction_method_id'] = transaction_method_id

        # DD
        kwargs['dd_premium'] = loan_requested.get("delayed_disbursement_premium", 0)
        kwargs['disbursement_amount'] = loan_requested.get("original_loan_amount_requested", 0)

        (
            is_max_fee_exceeded,
            total_fee,
            max_fee,
            monthly_interest_rate,
            insurance_premium_rate,
            provision_fee,
            dd_premium_rate,
        ) = validate_max_fee_rule_by_loan_requested(first_payment_date, loan_requested, kwargs)
        adjusted_monthly_interest_rate = loan_requested['interest_rate_monthly']
        digisign_fee = loan_requested.get('digisign_fee', 0)
        registration_fees_dict = loan_requested.get('registration_fees_dict', {})
        total_registration_fee = sum([fee for fee in registration_fees_dict.values()])
        if is_max_fee_exceeded:
            (adjusted_total_interest_rate, _, _,) = get_adjusted_total_interest_rate(
                max_fee=max_fee,
                provision_fee=provision_fee,
                insurance_premium_rate=insurance_premium_rate,
            )

            # DD
            dd_premium = loan_requested.get("delayed_disbursement_premium", 0)
            if dd_premium:
                adjusted_total_interest_rate = py2round(
                    monthly_interest_rate * float(loan_requested.get("loan_duration_request")), 7
                )

            loan_requested['provision_fee'] = provision_fee
            if (
                loan_requested['is_loan_amount_adjusted']
                and not loan_requested['is_withdraw_funds']
                and loan_requested['provision_fee'] != original_provision_rate
            ):
                readjusted_loan_amount = get_loan_amount_by_transaction_type(
                    loan_requested['original_loan_amount_requested'],
                    loan_requested['provision_fee'],
                    loan_requested['is_withdraw_funds'],
                )
                loan_requested['loan_amount'] = readjusted_loan_amount

            first_month_delta_days = (first_payment_date - today_date).days
            loan_duration = loan_requested['loan_duration_request']

            (
                first_month_interest_rate,
                adjusted_monthly_interest_rate,
            ) = get_adjusted_monthly_interest_rate_case_exceed(
                adjusted_total_interest_rate=adjusted_total_interest_rate,
                first_month_delta_days=first_month_delta_days,
                loan_duration=loan_duration,
            )

            is_zero_interest = loan_requested.get('disbursement_amount_zt', False)
            loan_amount = loan_requested['loan_amount']
            insurance_premium = loan_amount * (insurance_premium_rate or 0)
            dd_premium = loan_amount * (dd_premium_rate or 0)
            # Apply promo for provision fee
            provision_fee_amount = loan_amount * (loan_requested['provision_fee'] or 0)
            if promo_code_data and\
                promo_code_data.get('type') in [PromoCodeBenefitConst.FIXED_PROVISION_DISCOUNT,
                                                PromoCodeBenefitConst.PERCENT_PROVISION_DISCOUNT]:
                apply_benefit_service_handler = promo_code_data.get('handler')
                discount_amount, provision_fee_amount = apply_benefit_service_handler(
                    loan_amount=loan_requested['loan_amount'],
                    provision_rate=loan_requested['provision_fee'],
                )

                # benefit data for loan_transaction_detail table
                promo_benefit_data['type'] = promo_code_data.get('type')
                promo_benefit_data['discount_amount'] = discount_amount
                promo_benefit_data['provision_fee_amount'] = provision_fee_amount

            provision_amount = (
                provision_fee_amount
                + insurance_premium
                + dd_premium
                + digisign_fee
                + total_registration_fee
            )

            # DD
            if dd_premium_rate and transaction_method_id != TransactionMethodCode.SELF.code:
                dd_premium = loan_requested.get("delayed_disbursement_premium", 0)
                (
                    loan_requested['loan_amount'],
                    provision_amount,
                ) = get_loan_amount_and_provision_non_tarik_dana_delay_disbursement(
                    loan_requested['original_loan_amount_requested'],
                    loan_requested['provision_fee'],
                    dd_premium,
                    # other provisions component here
                    insurance_premium,
                    digisign_fee,
                    total_registration_fee,
                )

            tax = (
                calculate_tax_amount(
                    provision_amount,
                    loan_requested.get('product_line_code', None),
                    application.id,
                )
                if not is_consolidation
                else 0
            )

            # with Tarik Dana, tax and digisign_fee are included in disbursement amount
            if transaction_method_id != TransactionMethodCode.SELF.code:
                loan_requested['loan_amount'] += tax
                loan_requested['loan_amount'] += digisign_fee
                loan_requested['loan_amount'] += total_registration_fee
            # first month
            (
                principal_first,
                interest_first,
                installment_first,
            ) = compute_first_payment_installment_julo_one(
                loan_amount=loan_requested['loan_amount'],
                loan_duration=loan_duration,
                monthly_interest_rate=adjusted_monthly_interest_rate,
                start_date=today_date,
                end_date=first_payment_date,
                is_zero_interest=is_zero_interest,
            )
            # rest of months
            principal_rest, interest_rest, installment_rest = compute_payment_installment_julo_one(
                loan_amount=loan_requested['loan_amount'],
                loan_duration_months=loan_duration,
                monthly_interest_rate=adjusted_monthly_interest_rate,
            )

        else:
            loan_amount = loan_requested['loan_amount']
            insurance_premium = loan_amount * (insurance_premium_rate or 0)
            dd_premium = loan_amount * (dd_premium_rate or 0)
            # Apply promo for provision fee
            provision_fee_amount = loan_amount * (loan_requested['provision_fee'] or 0)
            if promo_code_data and\
                promo_code_data.get('type') in [PromoCodeBenefitConst.FIXED_PROVISION_DISCOUNT,
                                                PromoCodeBenefitConst.PERCENT_PROVISION_DISCOUNT]:
                apply_benefit_service_handler = promo_code_data.get('handler')
                discount_amount, provision_fee_amount = apply_benefit_service_handler(
                    loan_amount=loan_requested['loan_amount'],
                    provision_rate=loan_requested['provision_fee'],
                )

                # benefit data for loan_transaction_detail table
                promo_benefit_data['type'] = promo_code_data.get('type')
                promo_benefit_data['discount_amount'] = discount_amount
                promo_benefit_data['provision_fee_amount'] = provision_fee_amount

            provision_amount = (
                provision_fee_amount
                + insurance_premium
                + dd_premium
                + digisign_fee
                + total_registration_fee
            )

            # DD
            if dd_premium_rate and transaction_method_id != TransactionMethodCode.SELF.code:
                dd_premium = loan_requested.get("delayed_disbursement_premium", 0)
                (
                    loan_requested['loan_amount'],
                    provision_amount,
                ) = get_loan_amount_and_provision_non_tarik_dana_delay_disbursement(
                    loan_requested['original_loan_amount_requested'],
                    loan_requested['provision_fee'],
                    dd_premium,
                    # other provisions component here
                    insurance_premium,
                    digisign_fee,
                    total_registration_fee,
                )

            tax = (
                calculate_tax_amount(
                    provision_amount,
                    loan_requested.get('product_line_code', None),
                    application.id,
                )
                if not is_consolidation
                else 0
            )

            # with Tarik Dana, tax and digisign_fee are included in disbursement amount
            if transaction_method_id != TransactionMethodCode.SELF.code:
                loan_requested['loan_amount'] += tax
                loan_requested['loan_amount'] += digisign_fee
                loan_requested['loan_amount'] += total_registration_fee

            principal_rest, interest_rest, installment_rest = compute_payment_installment_julo_one(
                loan_requested['loan_amount'],
                loan_requested['loan_duration_request'],
                loan_requested['interest_rate_monthly'],
            )

            (
                principal_first,
                interest_first,
                installment_first,
            ) = compute_first_payment_installment_julo_one(
                loan_requested['loan_amount'],
                loan_requested['loan_duration_request'],
                loan_requested['interest_rate_monthly'],
                today_date,
                first_payment_date,
                loan_requested.get('disbursement_amount_zt'),
            )

        installment_amount = (
            installment_rest if loan_requested['loan_duration_request'] > 1 else installment_first
        )

        # move here inside transaction
        is_dbr_exceeded = False
        if transaction_method_id != TransactionMethodCode.QRIS_1.code:
            loan_dbr = LoanDbrSetting(application, True)
            dbr_err = loan_dbr.popup_banner.get(DBRConst.CONTENT_KEY)
            is_dbr_exceeded = loan_dbr.is_dbr_exceeded(
                duration=loan_requested['loan_duration_request'],
                payment_amount=installment_amount,
                first_payment_date=first_payment_date,
                first_payment_amount=installment_first,
            )
        if is_dbr_exceeded:
            logger.error(
                {
                    'action': 'juloserver.loan.services.loan_related.\
                        generate_loan_payment_julo_one',
                    'error': dbr_err,
                    'application': application.id,
                    'loan_amount': loan_requested.get('loan_amount'),
                    'loan_duration': loan_requested.get('loan_duration_request'),
                    'payment_amount': installment_amount,
                    'first_payment_amount': installment_first,
                    'first_payment_date': first_payment_date,
                }
            )
            raise LoanDbrException(
                loan_amount=loan_requested['loan_amount'],
                loan_duration=loan_requested['loan_duration_request'],
                transaction_method_id=transaction_method_id,
                error_msg=dbr_err,
            )

        initial_status = LoanStatusCodes.DRAFT if draft_loan else LoanStatusCodes.INACTIVE

        loan = Loan.objects.create(
            customer=application.customer,
            loan_status=StatusLookup.objects.get(status_code=initial_status),
            product=loan_requested['product'],
            loan_amount=loan_requested['loan_amount'],
            loan_duration=loan_requested['loan_duration_request'],
            first_installment_amount=installment_first,
            installment_amount=installment_amount,
            bank_account_destination=bank_account_destination,
            account=application.account,
            loan_purpose=loan_purpose,
            credit_matrix=credit_matrix,
            transaction_method_id=transaction_method_id,
        )
        if is_max_fee_exceeded:
            loan.loanadjustedrate = LoanAdjustedRate.objects.create(
                loan=loan,
                adjusted_first_month_interest_rate=first_month_interest_rate,
                adjusted_monthly_interest_rate=adjusted_monthly_interest_rate,
                adjusted_provision_rate=loan_requested['provision_fee'],
                max_fee=max_fee,
                simple_fee=total_fee,
            )

        # this below field application_id2 need to filled only for analytic purposes
        loan.application_id2 = application.id
        loan.cycle_day = application.account.cycle_day

        if tax:
            insert_loan_tax(loan, tax)

        if digisign_fee:
            insert_loan_digisign_fee(loan, digisign_fee)

        if total_registration_fee:
            insert_loan_registration_fees(loan, registration_fees_dict)
            insert_registration_fees(
                loan.customer_id,
                registration_fees_dict,
                extra_data={'loan_id': loan.id}
            )

        # if loan is zero interest => get disbursement_amount from zero interest
        if loan_requested.get('disbursement_amount_zt'):
            # Case: Other method: disbursement_amount == loan_amount_request
            if loan_requested['is_withdraw_funds']:
                total_fee = loan_requested['loan_amount'] * loan_requested['provision_fee']
                loan.loan_disbursement_amount = round_rupiah(
                    loan_requested['loan_amount'] - round_rupiah(total_fee)
                )
            else:
                loan.loan_disbursement_amount = loan_requested['original_loan_amount_requested']
        else:
            if loan_requested.get('insurance_premium') and insurance_premium_rate:
                LoanJuloCare.objects.create(
                    loan=loan,
                    status=JuloCareStatusConst.PENDING,
                    insurance_premium=loan_requested['loan_amount'] * insurance_premium_rate,
                    insurance_premium_rate=insurance_premium_rate,
                    original_insurance_premium=loan_requested['insurance_premium'],
                    device_brand=loan_requested['device_brand'],
                    device_model=loan_requested['device_model'],
                    os_version=loan_requested['os_version'],
                )
                loan.refresh_from_db()
            loan.set_disbursement_amount(promo_code_data=promo_code_data)

        # set delay disbursement
        if dd_premium_rate and dd_premium:
            insert_delay_disbursement_fee(
                loan=loan,
                delay_disbursement_premium_fee=dd_premium,
                delay_disbursement_premium_rate=dd_premium_rate,
                status=DelayedDisbursementStatus.DELAY_DISBURSEMENT_STATUS_PENDING,
                cashback=loan_requested['dd_cashback'],
                threshold_time=loan_requested['dd_threshold_duration'],
            )

        loan.set_sphp_expiration_date()
        loan.sphp_sent_ts = timezone.localtime(timezone.now())
        # set payment method for Loan
        customer_has_vas = PaymentMethod.objects.active_payment_method(application.customer)
        if customer_has_vas:
            primary_payment_method = customer_has_vas.filter(is_primary=True).last()
            if primary_payment_method:
                loan.julo_bank_name = primary_payment_method.payment_method_name
                loan.julo_bank_account_number = primary_payment_method.virtual_account
        if is_new_loan_part_of_bucket5(application.account):
            loan.ever_entered_B5 = True
        loan.save()
        payment_status = StatusLookup.objects.get(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        principal_deviation = loan.loan_amount - (
            principal_first + ((loan.loan_duration - 1) * principal_rest)
        )

        # PAYMENT GENERATION
        logger.info(
            {
                'action': 'generate_loan_payment_julo_one',
                'message': "before generating payments",
                'application': application.id,
                'loan_id': loan.id,
                'principal_first': principal_first,
                'interest_first': interest_first,
                'installment_first': installment_first,
                'principal_rest': principal_rest,
                'interest_rest': principal_rest,
                'installment_rest': principal_rest,
                'principal_deviation': principal_deviation,
            }
        )

        for payment_number in range(loan.loan_duration):
            if payment_number == 0:
                due_date = first_payment_date
                principal, interest, installment = (
                    principal_first,
                    interest_first,
                    installment_first,
                )
            else:
                due_date = first_payment_date + relativedelta(
                    months=payment_number, day=application.account.cycle_day
                )
                principal, interest, installment = principal_rest, interest_rest, installment_rest
                if (payment_number + 1) == loan.loan_duration:
                    # special case to handle interest 0% caused by max_fee rule
                    if principal == installment and interest == 0:
                        principal += principal_deviation
                        installment = principal
                    else:
                        principal += principal_deviation
                        interest -= principal_deviation

            payment = Payment.objects.create(
                loan=loan,
                payment_status=payment_status,
                payment_number=payment_number + 1,
                due_date=due_date,
                due_amount=installment,
                installment_principal=principal,
                installment_interest=interest if interest > 0 else 0,
            )
            _, is_bni_payment_method_exist = get_bni_payment_method(application.account)
            if is_bni_payment_method_exist:
                update_va_bni_transaction.delay(
                    application.account.id,
                    'loan.services.loan_related.generate_loan_payment_julo_one',
                )

            logger.info(
                {
                    'action': 'generate_loan_payment_julo_one',
                    'message': "done generating a payment",
                    'application': application.id,
                    "customer_id": application.customer_id,
                    'loan_id': loan.id,
                    'payment_number': payment_number,
                    'payment_object': model_to_dict(payment),
                    'due_date': due_date,
                    'status': 'payment_created',
                    'principal': principal,
                    'interest': interest,
                    'due_amount': installment,
                }
            )

        # Store loan detail
        # Store loan detail
        promo_applied = None
        if promo_code_data:
            promo_applied = {
                "promo_code_id": promo_code_data['promo_code'].id,
                "promo_code": promo_code_data['promo_code'].code,
                "benefit_data": promo_benefit_data
            }
        transaction_detail_data = LoanTransactionDetailData(
            loan=loan,
            admin_fee=provision_amount,
            provision_fee_rate=loan_requested['provision_fee'] or 0,
            dd_premium=dd_premium,
            insurance_premium=insurance_premium,
            digisign_fee=digisign_fee,
            total_registration_fee=total_registration_fee,
            tax_fee=tax,
            monthly_interest_rate=adjusted_monthly_interest_rate,
            tax_on_fields=[
                "provision_fee",
                "dd_premium",
                "insurance_premium",
                "digisign_fee",
                "total_registration_fee",
            ],
            promo_applied=promo_applied
        )
        create_loan_transaction_detail(transaction_detail_data)

        logger.info(
            {
                "action": "generate_loan_payment_julo_one",
                "message": "after generating loan payment",
                "customer_id": application.customer_id,
                "loan_id": loan.id,
                "loan_disbursement_amount": loan.loan_disbursement_amount,
                "loan_requested": loan_requested,
                "loan_purpose": loan_purpose,
                "credit_matrix_id": credit_matrix.id,
                "bank_account_destination": bank_account_destination,
                "draft_loan": draft_loan,
                "provision_amount": provision_amount,
                "dd_premium": dd_premium,
                "insurance_premium": insurance_premium,
                "digisign_fee": digisign_fee,
                "total_registration_fee": total_registration_fee,
                "tax_fee": tax,
            }
        )

        return loan


def capture_platform_for_loan_creation(loan, platform_name):
    if not platform_name:
        return

    platform = Platform.objects.filter(name=platform_name).first()
    if not platform:
        logger.error('platform_name_not_found|loan={}, name={}'.format(loan.id, platform_name))
        return

    loan_platform = LoanPlatform.objects.create(
        loan=loan,
        platform=platform,
    )

    return loan_platform


def generate_rentee_loan_payment_julo_one(
    application,
    loan_requested,
    loan_purpose,
    credit_matrix,
    bank_account_destination=None,
    draft_loan=False,
):
    with transaction.atomic():
        today_date = timezone.localtime(timezone.now()).date()
        first_payment_date = get_first_payment_date_by_application(application)

        principal_rest, interest_rest, installment_rest = compute_payment_installment_julo_one(
            loan_requested['installed_loan_amount'],
            loan_requested['loan_duration_request'],
            loan_requested['interest_rate_monthly'],
        )

        (
            principal_first,
            interest_first,
            installment_first,
        ) = compute_first_payment_installment_julo_one(
            loan_requested['installed_loan_amount'],
            loan_requested['loan_duration_request'],
            loan_requested['interest_rate_monthly'],
            today_date,
            first_payment_date,
        )
        installment_amount = (
            installment_rest if loan_requested['loan_duration_request'] > 1 else installment_first
        )

        initial_status = LoanStatusCodes.DRAFT if draft_loan else LoanStatusCodes.INACTIVE

        loan = Loan.objects.create(
            customer=application.customer,
            loan_status=StatusLookup.objects.get(status_code=initial_status),
            product=loan_requested['product'],
            loan_amount=loan_requested['loan_amount'],
            loan_duration=loan_requested['loan_duration_request'],
            first_installment_amount=installment_first,
            installment_amount=installment_amount,
            bank_account_destination=bank_account_destination,
            account=application.account,
            loan_purpose=loan_purpose,
            credit_matrix=credit_matrix,
        )
        # this below field application_id2 need to filled only for analytic purposes
        loan.application_id2 = application.id

        loan.cycle_day = application.account.cycle_day
        loan.set_disbursement_amount()
        loan.set_sphp_expiration_date()
        loan.sphp_sent_ts = timezone.localtime(timezone.now())
        # set payment method for Loan
        customer_has_vas = PaymentMethod.objects.active_payment_method(application.customer)
        if customer_has_vas:
            primary_payment_method = customer_has_vas.filter(is_primary=True).last()
            if primary_payment_method:
                loan.julo_bank_name = primary_payment_method.payment_method_name
                loan.julo_bank_account_number = primary_payment_method.virtual_account
        if is_new_loan_part_of_bucket5(application.account):
            loan.ever_entered_B5 = True
        loan.save()
        payment_status = StatusLookup.objects.get(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        principal_deviation = loan_requested['installed_loan_amount'] - (
            principal_first + ((loan.loan_duration - 1) * principal_rest)
        )

        for payment_number in range(loan.loan_duration):
            if payment_number == 0:
                due_date = first_payment_date
                principal, interest, installment = (
                    principal_first,
                    interest_first,
                    installment_first,
                )
            else:
                due_date = first_payment_date + relativedelta(
                    months=payment_number, day=application.account.cycle_day
                )
                principal, interest, installment = principal_rest, interest_rest, installment_rest
                if (payment_number + 1) == loan.loan_duration:
                    principal += principal_deviation
                    interest -= principal_deviation

            payment = Payment.objects.create(
                loan=loan,
                payment_status=payment_status,
                payment_number=payment_number + 1,
                due_date=due_date,
                due_amount=installment,
                installment_principal=principal,
                installment_interest=interest,
            )
            last_due_date = due_date

            logger.info(
                {
                    'action': 'generate_payment_julo_one',
                    'application': application.id,
                    'loan': loan,
                    'payment_number': payment_number,
                    'payment_amount': payment.due_amount,
                    'due_date': due_date,
                    'payment_status': payment.payment_status.status,
                    'status': 'payment_created',
                }
            )

        # generate 13th payment for rentee
        payment_number = loan.loan_duration + 1
        residual_loan_amount = loan_requested['residual_loan_amount']
        last_due_date = first_payment_date + relativedelta(
            months=loan.loan_duration, day=application.account.cycle_day
        )
        payment = Payment.objects.create(
            loan=loan,
            payment_status=payment_status,
            payment_number=payment_number,
            due_date=last_due_date,
            due_amount=residual_loan_amount,
            installment_principal=residual_loan_amount,
            installment_interest=0,
        )

        return loan


def compute_payment_installment_julo_one(loan_amount, loan_duration_months, monthly_interest_rate):
    """
    Computes installment and interest for payments after first installment
    """
    principal = int(math.floor(float(loan_amount) / float(loan_duration_months)))
    interest = int(math.floor(float(loan_amount) * monthly_interest_rate))

    unrounded_installment = installment_amount = principal + interest
    rounded_installment = round_rupiah(unrounded_installment)

    # special case to handle interest 0% caused by max_fee rule
    if monthly_interest_rate == 0.0 or loan_duration_months == 1:
        return principal, interest, unrounded_installment

    # rounding when:
    # > one month tenure
    # not 0% interest
    # rounding doesn't result in negative interest
    if rounded_installment > principal:
        installment_amount = rounded_installment

    derived_interest = installment_amount - principal

    return principal, derived_interest, installment_amount


def get_loan_amount_by_transaction_type(loan_amount, origination_fee_percentage, is_withdraw_funds):
    decrease_amount = loan_amount
    if not is_withdraw_funds:
        decrease_amount = int(py2round(old_div(loan_amount, (1 - origination_fee_percentage))))
    return decrease_amount


def compute_first_payment_installment_julo_one(
    loan_amount,
    loan_duration,
    monthly_interest_rate,
    start_date,
    end_date,
    is_zero_interest=False,
):
    days_in_month = 30.0
    delta_days = (end_date - start_date).days
    basic_interest = float(loan_amount) * monthly_interest_rate
    adjusted_interest = int(math.floor((float(delta_days) / days_in_month) * basic_interest))

    principal = int(math.floor(float(loan_amount) / float(loan_duration)))

    # default, not rounding
    unrounded_installment = principal + adjusted_interest
    rounded_installment = round_rupiah(unrounded_installment)  # round to previous thousand

    installment_amount = unrounded_installment

    # rounding when:
    # > one month tenure
    # not 0% interest
    # rounding doesn't result in negative interest
    if (loan_duration > 1 and not is_zero_interest) and (rounded_installment > principal):
        installment_amount = rounded_installment

    interest = installment_amount - principal

    return principal, interest, installment_amount


def update_loan_status_and_loan_history(
    loan_id, new_status_code, change_by_id=None, change_reason="system triggered", force=False
):
    from juloserver.account.tasks.account_task import process_account_reactivation
    from juloserver.refinancing.tasks import update_account_for_paid_off_after_refinanced
    from juloserver.loan.services.lender_related import return_lender_balance_amount
    from juloserver.ecommerce.services import update_iprice_transaction_by_loan
    from juloserver.julo.product_lines import ProductLineCodes
    from juloserver.balance_consolidation.services import ConsolidationVerificationStatusService
    from juloserver.julo.tasks import send_pn_invalidate_caching_loans_android
    from juloserver.channeling_loan.tasks import (
        cancel_loan_prefund_flow_task,
        notify_channeling_loan_cancel_task,
    )
    from juloserver.julo_financing.services.crm_services import (
        update_jfinancing_verification_with_failed_loan,
    )

    status_code = StatusLookup.objects.get_or_none(status_code=new_status_code)
    if not status_code:
        raise JuloException("Status Not Found in status Lookup")

    with db_transactions_atomic(DbConnectionAlias.utilization()):
        loan = Loan.objects.select_for_update().get(id=loan_id)
        if not loan:
            raise JuloException("Loan Not Found")
        old_status_code = loan.status
        if old_status_code == new_status_code:
            raise JuloException(
                "Can't change Loan Status from %s to %s" % (old_status_code, new_status_code)
            )

        """
            Validation for Status Change on loan,
            by checking to WorkflowStatuspath for the old_status and new_status,
            for 'force' status will not shown on CRM.
            only for J1 and JTurbo Product Line
        """
        loan_status_path_check = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.LOAN_STATUS_PATH_CHECK, is_active=True
        ).last()

        loan_product_line = None
        path_check_products = {ProductLineCodes.J1, ProductLineCodes.TURBO}
        if loan.product:
            loan_product_line = loan.product.product_line.product_line_code

        if (
            old_status_code <= LoanStatusCodes.CURRENT
            and new_status_code <= LoanStatusCodes.CURRENT
            and loan_product_line in path_check_products
        ):
            """
            only check path upto 220 (LoanStatusCodes.CURRENT),
            since after 220, path are flexible and may be changed a lot
            """
            workflow = Workflow.objects.get(name=WorkflowConst.LEGACY)
            query_filter = {
                "workflow": workflow,
                "status_previous": old_status_code,
                "status_next": new_status_code,
                "is_active": True,
            }
            exclude = {}
            if not force:
                exclude = {"type": "force"}

            status_path = (
                WorkflowStatusPath.objects.filter(**query_filter).exclude(**exclude).exists()
            )
            if not status_path:
                logger.error(
                    {
                        "reason": "Workflow not specified for status change",
                        "loan_id": loan.id,
                        "old_status_code": old_status_code,
                        "new_status_code": new_status_code,
                    }
                )
                sentry_client.captureMessage(
                    {
                        'error': 'Workflow not specified for status change',
                        'task': 'update_loan_status_and_loan_history',
                        'loan_id': loan.id,
                        'old_status_code': old_status_code,
                        'new_status_code': new_status_code,
                    }
                )
                if loan_status_path_check:
                    raise JuloInvalidStatusChange(
                        "No path from status {} to {}".format(old_status_code, new_status_code)
                    )

        loan.loan_status = status_code
        loan.save()
        loan_history_data = {
            'loan': loan,
            'status_old': old_status_code,
            'status_new': new_status_code,
            'change_reason': change_reason,
            'change_by_id': change_by_id,
        }
        LoanHistory.objects.create(**loan_history_data)
        is_axiata_loan = False
        account = loan.account
        if loan.application and loan.application.product_line_code in ProductLineCodes.axiata():
            application = loan.application
            is_axiata_loan = True
        else:
            application = loan.get_application
        loan.refresh_from_db()
        not_draft_loan = (
            old_status_code >= LoanStatusCodes.INACTIVE
            or new_status_code == LoanStatusCodes.INACTIVE
        )
        if not_draft_loan or (
            application.is_merchant_flow()
            and new_status_code == LoanStatusCodes.CANCELLED_BY_CUSTOMER
        ):
            if not is_axiata_loan:
                update_available_limit(loan)

        if not is_axiata_loan:
            update_is_proven_julo_one(loan)

        if (
            new_status_code in (LoanStatusCodes.CURRENT, LoanStatusCodes.PAID_OFF)
            and old_status_code >= LoanStatusCodes.CURRENT
            and not loan.is_restructured
        ):
            execute_after_transaction_safely(
                lambda account_id=loan.account_id: process_account_reactivation.delay(account_id)
            )

        if new_status_code == LoanStatusCodes.PAID_OFF:
            if loan.is_restructured:
                update_account_for_paid_off_after_refinanced.delay(account.id)

            from juloserver.loan.tasks.loan_related import adjust_is_maybe_gtl_inside

            execute_after_transaction_safely(lambda: adjust_is_maybe_gtl_inside.delay(loan_id))

        if application.is_grab():
            trigger_push_notification_grab.apply_async(kwargs={'loan_id': loan.id})

        if new_status_code == LoanStatusCodes.CURRENT:
            if loan.loanhistory_set.filter(status_new=LoanStatusCodes.CURRENT).count() == 1:
                if loan.is_balance_consolidation:
                    consolidation_services = ConsolidationVerificationStatusService(
                        loan.balanceconsolidationverification, account
                    )
                    consolidation_services.update_status_disbursed()
                    consolidation_services.update_post_graduation()
                    waive_interest_in_loan_balance_consolidation(loan)
                else:
                    check_promo_code_julo_one(loan)

                referral_fs = get_referral_benefit_logic_fs()
                process_referral_code_v2(application, loan, referral_fs)
                update_referrer_counting(application)
                execute_after_transaction_safely(
                    lambda: send_pn_invalidate_caching_loans_android.delay(
                        loan.customer_id, loan.loan_xid, loan.loan_amount
                    )
                )

                if loan.is_j1_or_jturbo_loan():
                    execute_after_transaction_safely(
                        lambda: execute_loyalty_transaction_mission_task.delay(loan.id)
                    )

                # Marketing Promo Loan Price Chance Logic (see `loan_prize_chance.py`)
                handle_loan_prize_chance_on_loan_status_change(loan)

                # delayed disbursement cashback trigger
                process_delayed_disbursement_cashback(loan)

                # update digisign registration fee status to charged
                update_registration_fees_status(loan.customer_id, loan.id, disbursed=True)

        # re-count promo code if loan is applied promo code fail
        # update digisign registration fee status to cancelled
        if (
            old_status_code not in LoanStatusCodes.fail_status()
            and new_status_code in LoanStatusCodes.fail_status()
        ):
            return_promo_code_usage_count(loan)
            update_registration_fees_status(loan.customer_id, loan.id, disbursed=False)

        if application.is_grab():
            if new_status_code in {
                LoanStatusCodes.GRAB_AUTH_FAILED,
                LoanStatusCodes.SPHP_EXPIRED,
                LoanStatusCodes.CANCELLED_BY_CUSTOMER,
                LoanStatusCodes.TRANSACTION_FAILED,
            }:
                try:
                    GrabClient.submit_cancel_loan(
                        loan_id, application_id=application.id, customer_id=application.customer.id
                    )
                except Timeout as e:
                    default_url = GrabPaths.CANCEL_LOAN
                    if e.response:
                        send_grab_api_timeout_alert_slack.delay(
                            response=e.response,
                            uri_path=e.request.url if e.request else default_url,
                            application_id=application.id,
                            customer_id=application.customer.id,
                        )
                    else:
                        send_grab_api_timeout_alert_slack.delay(
                            uri_path=e.request.url if e.request else default_url,
                            application_id=application.id,
                            customer_id=application.customer.id,
                            err_message=str(e) if e else None,
                        )
            if new_status_code in set(
                LoanStatusCodes.grab_current_until_180_dpd()
                + (
                    LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                    LoanStatusCodes.FUND_DISBURSAL_FAILED,
                    LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
                    LoanStatusCodes.PAID_OFF,
                    LoanStatusCodes.HALT,
                )
            ):
                trigger_grab_loan_sync_api_async_task.apply_async(
                    (loan_id,),
                )

        # iPrice ecommerce handler
        update_iprice_transaction_by_loan(loan, new_status_code, change_reason)
        if (
            new_status_code == LoanStatusCodes.CANCELLED_BY_CUSTOMER
            and old_status_code
            in (LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING, LoanStatusCodes.CURRENT)
            or new_status_code == LoanStatusCodes.TRANSACTION_FAILED
        ):
            if change_reason not in (
                'CPA detected before first transact',
                LoanStatusChangeReason.SWIFT_LIMIT_DRAINER,
                LoanStatusChangeReason.TELCO_MAID_LOCATION,
                LoanStatusChangeReason.INVALID_NAME_BANK_VALIDATION,
                LoanStatusChangeReason.RUN_OUT_OF_LENDER_BALANCE,
                LoanStatusChangeReason.FRAUD_LOAN_BLOCK,
            ):
                return_lender_balance_amount(loan)
            if new_status_code == LoanStatusCodes.TRANSACTION_FAILED:
                LoanStatusChange.objects.create(
                    loan=loan,
                    status_old=old_status_code,
                    status_new=new_status_code,
                    change_reason=change_reason,
                )

        cancel_status_list = (
            LoanStatusCodes.FUND_DISBURSAL_ONGOING,
            LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
            LoanStatusCodes.FUND_DISBURSAL_FAILED,
        )
        if (
            new_status_code == LoanStatusCodes.CANCELLED_BY_CUSTOMER
            and old_status_code in cancel_status_list
        ):
            if not loan.disbursement_id:
                return

            ltm = LenderTransactionMapping.objects.filter(
                disbursement_id=loan.disbursement_id,
                lender_transaction__isnull=False,
            )
            if not ltm:
                return

            lender = loan.lender
            if lender and lender.lender_name in LenderCurrent.escrow_lender_list():
                deposit_internal_lender_balance(
                    lender, loan.loan_disbursement_amount, LenderTransactionTypeConst.DEPOSIT
                )

        send_loan_status_changed_to_ga_appsflyer_event(
            application, loan, old_status_code, new_status_code
        )

        # Julo Financing
        if (
            loan.is_jfinancing_product
            and new_status_code in LoanStatusCodes.J1_failed_loan_status()
        ):
            update_jfinancing_verification_with_failed_loan(loan.pk)

        # send transaction status to moengage for notification
        notify_transaction_status_to_user(loan=loan, app=application)

        if new_status_code in LoanStatusCodes.fail_status():
            # cancel channeling loan prefund flow, validation inside tasks
            cancel_loan_prefund_flow_task.delay(loan_id)

        if (
            old_status_code >= LoanStatusCodes.CURRENT
            and new_status_code in LoanStatusCodes.fail_from_active_status()
        ):
            execute_after_transaction_safely(
                lambda: notify_channeling_loan_cancel_task.delay(loan_id)
            )


def notify_transaction_status_to_user(loan: Loan, app: Application) -> None:
    """
    Notify user of their transaction status for J1, starter, julover
    """
    # refresh in case running manually
    loan.refresh_from_db()
    app.refresh_from_db()

    # get fs
    fs = FeatureSettingHelper(LoanFeatureNameConst.TRANSACTION_RESULT_NOTIFICATION)
    if not fs.is_active or not fs.params:
        return

    # only for some products
    if not any([app.is_julo_one_or_starter(), app.is_julover()]):
        return

    # check for old version
    minimum_ver = fs.params['minimum_app_version']
    if loan.account.is_app_version_outdated(minimum_version=minimum_ver):
        return

    # check for allowed methods
    allowed_methods = fs.params['allowed_methods']
    if loan.transaction_method_id not in allowed_methods:
        return

    # only for some statuses
    if loan.loan_status_id not in LoanStatusCodes.transaction_notification_status():
        return

    execute_after_transaction_safely(
        lambda: send_transaction_status_event_to_moengage.delay(
            customer_id=loan.customer.id,
            loan_xid=loan.loan_xid,
            loan_status_code=loan.loan_status_id,
        )
    )


def is_julo_one_product_locked(account, product, method_code, application_direct=None):
    is_locked, _ = is_julo_one_product_locked_and_reason(
        account, product, method_code, application_direct
    )
    return is_locked


def is_julo_one_product_locked_and_reason(account, product, method_code, application_direct=None,
                                          device_ios_user=None):
    if check_lock_by_gtl_inside(account, method_code):
        return True, AccountLockReason.GTL_INSIDE

    if check_lock_by_gtl_outside(account, method_code):
        return True, AccountLockReason.GTL_OUTSIDE

    if not is_eligible_application_status(account, application_direct):
        return True, AccountLockReason.INVALID_APPLICATION_STATUS

    if is_name_in_bank_mismatch(account, application_direct, method_code):
        return True, AccountLockReason.NAME_IN_BANK_MISMATCH

    is_locked = _is_julo_one_product_locked_by_setting(account, product, device_ios_user)
    if is_locked:
        return True, AccountLockReason.PRODUCT_SETTING

    lock_by_entry_level_limit = check_lock_by_entry_level_limit(
        account, method_code, application_direct
    )
    if lock_by_entry_level_limit:
        return True, AccountLockReason.ENTRY_LEVEL_LIMIT

    lock_by_customer_tier = check_lock_by_customer_tier(account, method_code, application_direct)
    if lock_by_customer_tier:
        return True, AccountLockReason.CUSTOMER_TIER

    if is_fraud_blocked(
        account,
        [
            FraudBlock.Source.LOAN_FRAUD_BLOCK,
        ],
    ):
        return True, AccountLockReason.FRAUD_BLOCK

    if is_qris_1_blocked(account, method_code):
        return True, AccountLockReason.QRIS_NOT_WHITELISTED

    return False, None


def is_qris_1_blocked(account, method_code):
    if method_code == TransactionMethodCode.QRIS_1.code:
        fs = QrisWhitelistSetting()
        if fs.is_active:
            customer_id = account.customer_id

            # check if whitelisted from redis
            if fs.redis_customer_whitelist_active:
                is_redis_success, is_whitelisted = query_redis_ids_whitelist(
                    id=customer_id,
                    key=RedisWhiteList.Key.SET_QRIS_WHITELISTED_CUSTOMER_IDS,
                )

                if is_redis_success:
                    is_blocked = not is_whitelisted
                    return is_blocked

            # redis has issue or fs off, continue with django settings
            customer_ids = fs.customer_ids
            experiment_tail = fs.allowed_last_digits

            if (customer_id not in customer_ids) and (customer_id % 10) not in experiment_tail:
                return True
    return False


def is_all_product_locked(account):
    is_locked, _ = is_all_product_locked_and_reason(account)
    return is_locked


def is_all_product_locked_and_reason(account):
    from juloserver.balance_consolidation.services import get_or_none_balance_consolidation
    from juloserver.graduation.services import is_customer_suspend

    is_locked = True
    is_fraud_product_lock = is_fraud_blocked(account, [FraudBlock.Source.LOAN_FRAUD_BLOCK])
    if is_fraud_product_lock:
        return is_locked, AccountLockReason.FRAUD_BLOCK

    if not account:
        return is_locked, AccountLockReason.INVALID_ACCOUNT_STATUS

    # Pop up Exceed DPD Threshold
    is_exceed, reason_lock = is_account_exceed_dpd_90(account)
    if is_exceed:
        return is_locked, reason_lock

    if account.status_id not in AccountConstant.UNLOCK_STATUS:
        return is_locked, AccountLockReason.INVALID_ACCOUNT_STATUS

    customer_id = account.customer_id
    if get_or_none_balance_consolidation(customer_id):
        return is_locked, AccountLockReason.BALANCE_CONSOLIDATION

    is_suspend, lock_reason = is_customer_suspend(customer_id)
    if is_suspend:
        return is_locked, lock_reason

    return False, None


def is_product_locked(account, method_code, application_direct=None, device_ios_user=None):
    is_locked, _ = is_product_locked_and_reason(
        account, method_code, application_direct=application_direct, device_ios_user=device_ios_user
    )
    return is_locked


def is_product_locked_and_reason(account, method_code, application_direct=None,
                                 device_ios_user=None):
    is_locked, locked_reason = is_all_product_locked_and_reason(account)
    if is_locked:
        return is_locked, locked_reason

    return is_product_lock_by_method(account, method_code, application_direct, device_ios_user)


def is_product_lock_by_method(account, method_code, application_direct=None, device_ios_user=None):
    if method_code == TransactionMethodCode.SELF.code:
        is_locked, locked_reason = is_julo_one_product_locked_and_reason(
            account, LoanJuloOneConstant.TARIK_DANA, method_code, application_direct,
            device_ios_user
        )
    elif method_code == TransactionMethodCode.OTHER.code:
        # split code for optimize only v2 CreditInfo.
        app = application_direct or account.get_active_application()
        tier_pro = False
        if app:
            tier_pro = is_graduate_of(app, TierId.PRO)

        if tier_pro:
            is_locked, locked_reason = is_julo_one_product_locked_and_reason(
                account, LoanJuloOneConstant.KIRIM_DANA, method_code, application_direct,
                device_ios_user
            )
        else:
            is_proven = get_julo_one_is_proven(account)
            if is_proven:
                is_locked, locked_reason = is_julo_one_product_locked_and_reason(
                    account, LoanJuloOneConstant.KIRIM_DANA, method_code, application_direct,
                    device_ios_user
                )
            else:
                is_locked = True
                locked_reason = AccountLockReason.NOT_PROVEN_ACCOUNT

    elif method_code == TransactionMethodCode.E_COMMERCE.code:
        is_locked, locked_reason = is_julo_one_product_locked_and_reason(
            account, LoanJuloOneConstant.ECOMMERCE_PRODUCT, method_code, application_direct,
            device_ios_user
        )
    elif method_code == TransactionMethodCode.QRIS.code:
        is_locked, locked_reason = is_julo_one_product_locked_and_reason(
            account, LoanJuloOneConstant.QRIS, method_code, application_direct, device_ios_user
        )
    elif method_code == TransactionMethodCode.CREDIT_CARD.code:
        is_locked, locked_reason = is_julo_one_product_locked_and_reason(
            account, LoanJuloOneConstant.CREDIT_CARD, method_code, application_direct,
            device_ios_user
        )
    elif method_code == TransactionMethodCode.TRAIN_TICKET.code:
        is_locked, locked_reason = is_julo_one_product_locked_and_reason(
            account, LoanJuloOneConstant.TRAIN_TICKET, method_code, application_direct,
            device_ios_user
        )
    elif method_code == TransactionMethodCode.PDAM.code:
        is_locked, locked_reason = is_julo_one_product_locked_and_reason(
            account, LoanJuloOneConstant.PDAM, method_code, application_direct, device_ios_user
        )
    elif method_code == TransactionMethodCode.EDUCATION.code:
        is_locked, locked_reason = is_julo_one_product_locked_and_reason(
            account, LoanJuloOneConstant.EDUCATION, method_code, application_direct, device_ios_user
        )
    elif method_code == TransactionMethodCode.BALANCE_CONSOLIDATION.code:
        is_locked, locked_reason = is_julo_one_product_locked_and_reason(
            account, LoanJuloOneConstant.BALANCE_CONSOLIDATION, method_code, application_direct,
            device_ios_user
        )
    elif method_code == TransactionMethodCode.HEALTHCARE.code:
        is_locked, locked_reason = is_julo_one_product_locked_and_reason(
            account, LoanJuloOneConstant.HEALTHCARE, method_code, application_direct,
            device_ios_user
        )
    elif method_code == TransactionMethodCode.INTERNET_BILL.code:
        is_locked, locked_reason = is_julo_one_product_locked_and_reason(
            account, LoanJuloOneConstant.INTERNET_BILL, method_code, application_direct,
            device_ios_user
        )
    elif method_code == TransactionMethodCode.DOMPET_DIGITAL.code:
        is_locked, locked_reason = is_julo_one_product_locked_and_reason(
            account, LoanJuloOneConstant.DOMPET_DIGITAL, method_code, application_direct,
            device_ios_user
        )
    elif method_code == TransactionMethodCode.JFINANCING.code:
        is_locked, locked_reason = is_julo_one_product_locked_and_reason(
            account, LoanJuloOneConstant.JFINANCING, method_code, application_direct,
            device_ios_user
        )
    elif method_code == TransactionMethodCode.PFM.code:
        is_locked, locked_reason = is_julo_one_product_locked_and_reason(
            account, LoanJuloOneConstant.PFM, method_code, application_direct,
            device_ios_user
        )
    elif method_code == TransactionMethodCode.QRIS_1.code:
        is_locked, locked_reason = is_julo_one_product_locked_and_reason(
            account, LoanJuloOneConstant.QRIS_1, method_code, application_direct,
            device_ios_user
        )
    # PPOB
    else:
        is_locked, locked_reason = is_julo_one_product_locked_and_reason(
            account, LoanJuloOneConstant.PPOB_PRODUCT, method_code, application_direct,
            device_ios_user
        )

    return is_locked, locked_reason


def _is_julo_one_product_locked_by_setting(account, product, device_ios_user=None):
    if not account:
        return False

    if not account.app_version:
        return False

    lock_product_feature = MobileFeatureSetting.objects.get_or_none(
        feature_name=LoanJuloOneConstant.PRODUCT_LOCK_FEATURE_SETTING, is_active=True
    )

    if not lock_product_feature:
        return False

    parameters = lock_product_feature.parameters
    if not parameters:
        return False

    locking_rule = parameters.get(product)
    if not locking_rule:
        return False

    if not locking_rule.get('locked') or not locking_rule['locked']:
        return False

    is_locked = True
    if device_ios_user:
        # Check iOS version lock
        if locking_rule.get('ios_app_version'):
            is_locked = semver.match(
                device_ios_user['app_version'], "<%s" % locking_rule['ios_app_version']
            )
    else:
        # Check Android version lock
        if locking_rule.get('app_version'):
            is_locked = semver.match(account.app_version, "<%s" % locking_rule['app_version'])

    return is_locked


def get_first_payment_date_by_application(application):
    if application.is_julover():
        from juloserver.julovers.services.core_services import get_first_payment_date

        return get_first_payment_date()

    auto_adjust_changes = {}
    today_date = timezone.localtime(timezone.now()).date()
    experiment_flag = False
    account = Account.objects.get(id=application.account_id)
    if application.is_julo_one_or_starter() and not account.is_payday_changed:
        unpaid_account_payment = account.accountpayment_set.filter(
            status_id__lt=PaymentStatusCodes.PAID_ON_TIME
        ).exists()
        if not unpaid_account_payment or account.is_ldde:
            experiment_flag = True

    logger.info(
        {
            'action': 'get_first_payment_date_by_application',
            'offer_date': today_date,
            'experiment_flag': experiment_flag,
            'customer_id': application.customer_id,
            'payday': application.payday,
        }
    )

    if application.status != ApplicationStatusCodes.LOC_APPROVED:
        # skip LDDE check, LDDE only on application status 190
        experiment_flag = False

    if not experiment_flag:
        first_payment_date = calculate_first_due_date_ldde_old_flow(
            application.payday, account.cycle_day, today_date
        )
    else:
        # LDDE flow
        old_cycle_day = account.cycle_day
        reason = LDDEReasonConst.LDDE_V1
        ana_cycle_day_data = {}
        payday = application.payday
        # check if using v2
        ldde_v2_history, is_ldde_v2, unpaid_loan = check_ldde_v2(application, account)

        if is_ldde_v2:
            # Use LDDE V2
            is_update_ldde_v2 = is_update_ldde_v2_after_months(ldde_v2_history, today_date)
            # if is_update_ldde_v2 = true and paid off all loans => get new cycle_day
            if is_update_ldde_v2 and not unpaid_loan:
                ana_cycle_day_data = get_data_from_ana_calculate_cycle_day(application.id)
            else:
                ana_cycle_day_data['cycle_day_selection'] = old_cycle_day

        if ana_cycle_day_data:
            # LDDE V2,
            # no need to calculate, just get the cycle_date directly from ana
            reason = LDDEReasonConst.LDDE_V2
            ana_cycle_date = ana_cycle_day_data.get('cycle_day_selection')
            first_payment_date = calculate_first_due_date_ldde_v2_flow(
                ana_cycle_date, ana_cycle_date, today_date
            )
            account.update_safely(cycle_day=ana_cycle_date)
        else:
            # LDDE V1
            # check case with Feb every year when the day can be 28 or 29
            first_payment_date = determine_first_due_dates_by_payday(
                application.payday,
                today_date,
                application.product_line_code,
                customer_id=application.customer_id,
                experiment_flag=True,
            )
            if payday in [30, 29]:
                account.update_safely(cycle_day=payday + 1)
            else:
                if first_payment_date.day == payday:
                    account.update_safely(cycle_day=first_payment_date.day + 1)
                elif account.cycle_day != first_payment_date.day:
                    account.update_safely(cycle_day=first_payment_date.day)

        if not account.is_ldde:
            account.update_safely(is_ldde=True)

        fs = AutoAdjustDueDateSetting()
        if fs.is_active:
            whitelist_config = fs.get_whitelist()
            mapping_config = fs.get_auto_adjust_due_date_mapping()
            if (
                application.is_julo_one_or_starter()
                and not account.is_payday_changed
                and is_eligible_auto_adjust_due_date(account.customer_id, whitelist_config)
            ):
                new_cycle_day, first_payment_date = get_auto_adjust_due_date(
                    account=account, mapping_config=mapping_config
                )
                if new_cycle_day:
                    auto_adjust_changes.update({
                        "ldde": {
                            "old_cycle_day": old_cycle_day, "new_cycle_day": account.cycle_day
                        },
                        "auto_adjust": {
                            "old_cycle_day": account.cycle_day, "new_cycle_day": new_cycle_day
                        }
                    })
                    account.update_safely(cycle_day=new_cycle_day)

        with redis_lock_for_update(RedisLockKeyName.UPDATE_ACCOUNT_CYCLE_DAY_HISTORY, account.pk):
            update_cycle_day_history(
                account, reason, old_cycle_day, ana_cycle_day_data,
                application.pk, auto_adjust_changes
            )

    application.refresh_from_db()
    return first_payment_date


def is_update_ldde_v2_after_months(ldde_v2_history: AccountCycleDayHistory, today_date: date):
    ldde_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LDDE_V2_SETTING
    ).first()

    if not ldde_v2_history or not ldde_feature_setting:
        return True

    return ldde_v2_history.cdate.date() < today_date - relativedelta(
        months=ldde_feature_setting.parameters['update_ldde_v2_after_months']
    )


def check_ldde_v2(application, account):
    is_ldde_v2_fs = get_ldde_v2_status(application.id)

    # check if current flow is using the v2, if not exist meaning is using v1
    current_ldde_v2_history = AccountCycleDayHistory.objects.filter(
        account_id=account.pk,
        latest_flag=True,
        reason=LDDEReasonConst.LDDE_V2,
    ).last()

    unpaid_loan = (
        Loan.objects.filter(
            account_id=account.id,
        )
        .filter(
            Q(loan_status__gte=LoanStatusCodes.CURRENT, loan_status__lt=LoanStatusCodes.PAID_OFF)
            | Q(loan_status_id__in=LoanStatusCodes.in_progress_status())
        )
        .exists()
    )

    if current_ldde_v2_history:
        # if last history is v2, will use v2 regardless the FS
        return current_ldde_v2_history, True, unpaid_loan

    if is_ldde_v2_fs and unpaid_loan:
        """
        fs ldd2 v2 active, but there was pending loan,
        so cannot change directly, Feature setting is ignored
        for this case will continue using v1
        """
        is_ldde_v2_fs = False

    return current_ldde_v2_history, is_ldde_v2_fs, unpaid_loan


def get_ldde_v2_status(application_id):
    ldde_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LDDE_V2_SETTING, is_active=True
    ).last()
    last_digit_application_id = application_id % 10
    if ldde_feature_setting:
        ldde_v2_application_id_list = ldde_feature_setting.parameters.get('ldde_version', {}).get(
            'v2_last_digit_of_application_id', {}
        )
        if last_digit_application_id in ldde_v2_application_id_list:
            return True

    return False


def refiltering_cash_loan_duration(available_duration, application):
    # filter out duration less than 60 days due to google restriction for cash loan
    if 2 not in available_duration:
        return available_duration

    today_date = timezone.localtime(timezone.now()).date()
    first_payment_date = get_first_payment_date_by_application(application)
    second_payment_date = first_payment_date + relativedelta(months=1)
    days_delta = second_payment_date - today_date

    if days_delta.days < LoanJuloOneConstant.CASH_MIN_DURATION_DAYS:
        available_duration.remove(2)
        # if 2 is the only duration available, replace it by 3
        if not available_duration:
            available_duration.append(3)

    return available_duration


def check_promo_code_julo_one(loan):
    check_and_apply_promo_code_benefit(loan)

    check_and_apply_application_promo_code(loan)


def determine_transaction_method_by_transaction_type(transaction_type):
    if transaction_type == TransactionType.SELF:
        return TransactionMethod.objects.get(pk=1)
    elif transaction_type == TransactionType.ECOMMERCE:
        return TransactionMethod.objects.get(pk=8)
    else:
        return TransactionMethod.objects.get(pk=2)


def suspicious_ip_loan_fraud_check(loan, request, is_suspicious_ip=None):
    if not is_suspicious_ip:
        ip_address = get_client_ip_from_request(request)
        if not ip_address:
            logger.warning('can not find ip address|loan={}'.format(loan.id))
            return

        try:
            is_suspicious_ip = check_suspicious_ip(ip_address)
        except Exception:
            sentry_client.captureException()
            return

    loan_risk_check = capture_suspicious_transaction_risk_check(
        loan, 'is_vpn_detected', is_suspicious_ip
    )

    return loan_risk_check


def suspicious_hotspot_loan_fraud_check(loan, data):
    from juloserver.pin.services import validate_device, get_device_model_name

    device_model_name = get_device_model_name(data.get('manufacturer'), data.get('model'))
    device, suspicious_login = validate_device(
        gcm_reg_id=data.get('gcm_reg_id'),
        customer=loan.customer,
        imei=data.get('imei'),
        android_id=data.get('android_id'),
        device_model_name=device_model_name,
        julo_device_id=data.get(DeviceConst.JULO_DEVICE_ID),
    )
    device_geolocation = capture_device_geolocation(
        device, data.get('latitude'), data.get('longitude'), 'transaction'
    )

    is_fh = check_fraud_hotspot_gps(device_geolocation.latitude, device_geolocation.longitude)
    loan_risk_check = capture_suspicious_transaction_risk_check(loan, 'is_fh_detected', is_fh)

    return loan_risk_check


def capture_suspicious_transaction_risk_check(loan, suspicious_type, is_suspicious):
    decision = None
    if is_suspicious:
        decision_name = TransactionRiskyDecisionName.OTP_NEEDED
        decision = TransactionRiskyDecision.objects.get(decision_name=decision_name)

    loan_risk_check, created = TransactionRiskyCheck.objects.get_or_create(loan=loan)
    if (
        getattr(loan_risk_check, suspicious_type) == is_suspicious
        and loan_risk_check.decision == decision
    ):
        return

    loan_risk_check.update_safely(**{suspicious_type: is_suspicious, "decision": decision})

    return loan_risk_check


def get_ecommerce_limit_transaction():
    limit_transaction = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MINIMUM_AMOUNT_TRANSACTION_LIMIT, is_active=True
    ).last()
    if not limit_transaction:
        return LoanJuloOneConstant.MIN_lOAN_TRANSFER_AMOUNT
    return limit_transaction.parameters['limit_transaction']


def validate_time_frame(account_loans, method_params, error_messages, minimum_loan_status: int):
    now = timezone.localtime(timezone.now())
    loan_histories = LoanHistory.objects.filter(
        status_new=minimum_loan_status, loan__in=account_loans
    )

    for key, value in method_params.items():
        if 'hr' in key:
            timespan = int(key.strip('hr'))
            timeframe = now - relativedelta(hours=timespan)
        elif 'min' in key:
            timespan = int(key.strip('min'))
            timeframe = now - relativedelta(minutes=timespan)
        transaction_history_count = loan_histories.filter(cdate__gte=timeframe).count()
        if transaction_history_count >= value:
            error_message = error_messages.get(key, None)
            if not error_message:
                error_message = error_messages.get('other')
            return False, error_message
    return True, None


def fetch_method_params_for_method_limiting(parameters, customer, transaction_method):
    current_device = customer.device_set.last()
    if current_device and current_device.is_new_customer_device:
        new_params = parameters.get('new_devices', {}).get(transaction_method)
        if new_params:
            return new_params

    return parameters.get(transaction_method)


def transaction_method_limit_check(
    account,
    transaction_method: TransactionMethod,
    minimum_loan_status=LoanStatusCodes.LENDER_APPROVAL,
):
    """
    Check if there are more loans than threshold based on transaction method
    """
    feature = FeatureSetting.objects.filter(
        is_active=True, feature_name=LoanFeatureNameConst.TRANSACTION_METHOD_LIMIT
    ).last()

    error = None
    if not feature:
        return True, error
    method_params = fetch_method_params_for_method_limiting(
        feature.parameters, account.customer, transaction_method.method
    )
    if not method_params or method_params['is_active'] is False:
        return True, error
    sorted_method_params = sort_transaction_method_limit_params(method_params)
    account_loans = account.loan_set.filter(
        transaction_method=transaction_method,
        loan_status_id__gte=minimum_loan_status,
    )
    error_messages = feature.parameters.get('errors')
    valid_transaction, error = validate_time_frame(
        account_loans,
        sorted_method_params,
        error_messages,
        minimum_loan_status=minimum_loan_status,
    )
    return valid_transaction, error


def transaction_fdc_risky_check(loan):
    fdc_risky_check_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FDC_RISKY_CHECK, is_active=True
    ).exists()
    if not fdc_risky_check_feature:
        return

    loan_risk_check, _ = TransactionRiskyCheck.objects.get_or_create(loan=loan)
    if loan_risk_check.is_fdc_risky is not None:
        return loan_risk_check.is_fdc_risky
    is_fdc_risky = False
    application = loan.get_application
    latest_fdc_inquiry = FDCInquiry.objects.filter(application_id=application.id).last()
    latest_fdc_inquiry_loans = latest_fdc_inquiry.fdcinquiryloan_set.all()

    # Check Delequency
    if is_fdc_risky is False:
        delinquent_loans = (
            latest_fdc_inquiry_loans.filter(dpd_terakhir__gt=5).exclude(is_julo_loan=True).exists()
        )
        if delinquent_loans:
            is_fdc_risky = True

    # Check increasing ongoing loans
    if is_fdc_risky is False:
        initial_fdc_inquiry = FDCInquiry.objects.filter(application_id=application.id).order_by(
            'cdate').first()
        if initial_fdc_inquiry:
            initial_fdc_loan_data = InitialFDCInquiryLoanData.objects.filter(
                fdc_inquiry=initial_fdc_inquiry
            ).last()
            if initial_fdc_loan_data:
                initial_fdc_loan_count = initial_fdc_loan_data.initial_outstanding_loan_count_x100
            else:
                initial_fdc_loan_count, _ = store_initial_fdc_inquiry_loan_data(initial_fdc_inquiry)
            latest_fdc_loan_count = (
                latest_fdc_inquiry_loans.filter(status_pinjaman='Outstanding')
                .exclude(is_julo_loan=True)
                .count()
            )
            if latest_fdc_loan_count > initial_fdc_loan_count:
                is_fdc_risky = True

    to_update = {'is_fdc_risky': is_fdc_risky}
    if is_fdc_risky:
        decision = TransactionRiskyDecision.objects.get(
            decision_name=TransactionRiskyDecisionName.OTP_NEEDED
        )
        to_update['decision'] = decision
    loan_risk_check.update_safely(**to_update)
    return is_fdc_risky


def transaction_web_location_blocked_check(loan, latitude, longitude):
    loan_risk_check, _ = TransactionRiskyCheck.objects.get_or_create(loan=loan)

    if latitude is not None or longitude is not None:
        return

    loan_risk_check.update_safely(
        is_web_location_blocked=True,
        decision=TransactionRiskyDecision.objects.get(
            decision_name=TransactionRiskyDecisionName.OTP_NEEDED
        ),
    )


def transaction_hardtoreach_check(loan, account_id):
    loan_risk_check, _ = TransactionRiskyCheck.objects.get_or_create(loan=loan)

    if not is_account_hardtoreach(account_id):
        return

    loan_risk_check.update_safely(is_hardtoreach=is_account_hardtoreach(account_id))


def get_range_loan_amount(
    account_limit, credit_matrix, credit_matrix_product_line, self_bank_account, transaction_type
):
    origination_fee = credit_matrix.product.origination_fee_pct
    cm_max_loan_amount = credit_matrix_product_line.max_loan_amount
    available_limit = account_limit.available_limit

    max_loan_amount = (
        cm_max_loan_amount if cm_max_loan_amount <= available_limit else available_limit
    )
    if not self_bank_account:
        max_loan_amount = max_loan_amount - int(py2round(max_loan_amount * origination_fee))
    min_amount_threshold = LoanJuloOneConstant.MIN_LOAN_AMOUNT_THRESHOLD
    if transaction_type == TransactionType.ECOMMERCE:
        min_amount_threshold = get_ecommerce_limit_transaction()
    min_loan_amount = (
        min_amount_threshold if min_amount_threshold < available_limit else available_limit
    )

    return min_loan_amount, max_loan_amount


def trigger_reward_cashback_for_campaign_190(
    promo_loan_amount,
    promo_cashback_amount,
    money_change_reason,
    time_ago,  # type timedelta/relativedelta
    campaign_code,
):
    # only for Julo1 customers
    # . Find all users who have clicked the nofification with template code in previous N hours
    # . Check if their current loan has passed a certain amount
    # . If yes, give them the cashback

    now = timezone.localtime(timezone.now())

    customer_ids = (
        InAppNotificationHistory.objects.filter(
            status="clicked",
            template_code__contains=campaign_code,
            cdate__gte=(now - time_ago),
        )
        .distinct("customer_id")
        .values_list("customer_id", flat=True)
    )

    loans = (
        Loan.objects.select_related("customer")
        .filter(
            customer_id__in=list(map(int, customer_ids)),
            loan_amount__gt=promo_loan_amount,
            cdate__date=now.date(),
        )
        .all_active_julo_one()
        .exclude(customer__wallet_history__change_reason=money_change_reason)
        .order_by("customer_id")
        .distinct("customer_id")
    )

    for loan in loans:
        loan.customer.change_wallet_balance(
            change_accruing=promo_cashback_amount,
            change_available=promo_cashback_amount,
            reason=money_change_reason,
            loan=loan,
        )


def calculate_loan_amount(
    application,
    loan_amount_requested,
    transaction_type,
    is_self_bank_account=False,
    is_payment_point=False,
):
    """
    Calculate Adjusted Loan Amount and return the CreditMatrix also.
    """
    credit_matrix, credit_matrix_product_line = get_credit_matrix_and_credit_matrix_product_line(
        application,
        is_self_bank_account=is_self_bank_account,
        payment_point=is_payment_point,
        transaction_type=transaction_type,
    )

    origination_fee_pct = credit_matrix.product.origination_fee_pct
    adjusted_loan_amount = get_loan_amount_by_transaction_type(
        loan_amount_requested, origination_fee_pct, is_self_bank_account
    )
    return adjusted_loan_amount, credit_matrix, credit_matrix_product_line


def get_loan_credit_card_inactive(account):
    today_ts = timezone.localtime(timezone.now())
    return Loan.objects.filter(
        account=account,
        loan_status_id=LoanStatusCodes.INACTIVE,
        transaction_method_id=TransactionMethodCode.CREDIT_CARD.code,
        cdate__gte=today_ts - timedelta(minutes=5),
    ).last()


def readjusted_loan_amount_by_max_fee_rule(loan, loan_duration):
    application = loan.get_application
    is_withdraw_funds = True
    if loan.transaction_method_id != TransactionMethodCode.SELF.code:
        is_withdraw_funds = False
    credit_matrix, credit_matrix_product_line = get_credit_matrix_and_credit_matrix_product_line(
        application,
        is_withdraw_funds,
    )
    original_loan_amount = loan.loan_amount if is_withdraw_funds else loan.loan_disbursement_amount
    first_payment_date = get_first_payment_date_by_application(application)
    original_provision_rate = credit_matrix.product.origination_fee_pct
    loan_requested = dict(
        is_loan_amount_adjusted=True,
        original_loan_amount_requested=original_loan_amount,
        loan_amount=loan.loan_amount,
        loan_duration_request=loan_duration,
        interest_rate_monthly=credit_matrix.product.monthly_interest_rate,
        product=credit_matrix.product,
        provision_fee=original_provision_rate,
        is_withdraw_funds=is_withdraw_funds,
    )
    (
        is_max_fee_exceeded,
        total_fee,
        max_fee,
        monthly_interest_rate,
        _,
        _,
        _,
    ) = validate_max_fee_rule_by_loan_requested(first_payment_date, loan_requested, {})
    is_loan_amount_adjusted = True
    if is_max_fee_exceeded:
        if (
            is_loan_amount_adjusted
            and not is_withdraw_funds
            and loan_requested['provision_fee'] != original_provision_rate
        ):
            readjusted_loan_amount = get_loan_amount_by_transaction_type(
                loan_requested['original_loan_amount_requested'],
                loan_requested['provision_fee'],
                is_withdraw_funds,
            )
            loan_requested['loan_amount'] = readjusted_loan_amount

    return loan_requested['loan_amount']


def generate_new_payments(loan_duration, loan):
    application = loan.get_application
    is_withdraw_funds = True
    if loan.transaction_method_id != TransactionMethodCode.SELF.code:
        is_withdraw_funds = False
    credit_matrix, credit_matrix_product_line = get_credit_matrix_and_credit_matrix_product_line(
        application,
        is_withdraw_funds,
    )
    original_loan_amount = loan.loan_amount if is_withdraw_funds else loan.loan_disbursement_amount
    apply_loan_date = timezone.localtime(loan.cdate).date()
    first_payment_date = get_first_payment_date_by_application(application)
    original_provision_rate = credit_matrix.product.origination_fee_pct
    loan_requested = dict(
        is_loan_amount_adjusted=True,
        original_loan_amount_requested=original_loan_amount,
        loan_amount=loan.loan_amount,
        loan_duration_request=loan_duration,
        interest_rate_monthly=credit_matrix.product.monthly_interest_rate,
        product=credit_matrix.product,
        provision_fee=original_provision_rate,
        is_withdraw_funds=is_withdraw_funds,
    )
    (
        is_max_fee_exceeded,
        total_fee,
        max_fee,
        monthly_interest_rate,
        _,
        _,
        _,
    ) = validate_max_fee_rule_by_loan_requested(first_payment_date, loan_requested, {})
    is_loan_amount_adjusted = True
    if is_max_fee_exceeded:
        if (
            is_loan_amount_adjusted
            and not is_withdraw_funds
            and loan_requested['provision_fee'] != original_provision_rate
        ):
            readjusted_loan_amount = get_loan_amount_by_transaction_type(
                loan_requested['original_loan_amount_requested'],
                loan_requested['provision_fee'],
                is_withdraw_funds,
            )
            loan_requested['loan_amount'] = readjusted_loan_amount

        principal_rest, interest_rest, installment_rest = compute_payment_installment_julo_one(
            loan_requested['loan_amount'],
            loan_requested['loan_duration_request'],
            monthly_interest_rate,
        )
        principal_first = principal_rest
        interest_first = interest_rest
        installment_first = installment_rest
    else:
        principal_rest, interest_rest, installment_rest = compute_payment_installment_julo_one(
            loan_requested['loan_amount'],
            loan_requested['loan_duration_request'],
            loan_requested['interest_rate_monthly'],
        )

        (
            principal_first,
            interest_first,
            installment_first,
        ) = compute_first_payment_installment_julo_one(
            loan_requested['loan_amount'],
            loan_requested['loan_duration_request'],
            loan_requested['interest_rate_monthly'],
            apply_loan_date,
            first_payment_date,
        )
    principal_deviation = loan.loan_amount - (
        principal_first + ((loan_duration - 1) * principal_rest)
    )
    payments = []
    payment_status = StatusLookup.objects.get(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
    for payment_number in range(loan_duration):
        if payment_number == 0:
            due_date = first_payment_date
            principal, interest, installment = principal_first, interest_first, installment_first
        else:
            due_date = first_payment_date + relativedelta(
                months=payment_number, day=application.account.cycle_day
            )
            principal, interest, installment = principal_rest, interest_rest, installment_rest
            if (payment_number + 1) == loan.loan_duration:
                # special case to handle interest 0% caused by max_fee rule
                if principal == installment and interest == 0:
                    principal += principal_deviation
                    installment = principal
                else:
                    principal += principal_deviation
                    interest -= principal_deviation

        payments.append(
            Payment(
                loan=loan,
                payment_status=payment_status,
                payment_number=payment_number + 1,
                due_date=due_date,
                due_amount=installment,
                installment_principal=principal,
                installment_interest=interest,
            )
        )
    return payments


@transaction.atomic
def update_loan(loan, loan_duration):
    from juloserver.credit_card.tasks.transaction_tasks import upload_sphp_loan_credit_card_to_oss
    from juloserver.credit_card.services.transaction_related import (
        assign_loan_credit_card_to_lender,
    )

    if loan.loan_duration == loan_duration:
        assign_loan_credit_card_to_lender(loan.id)
        return
    old_payments = Payment.objects.select_for_update().filter(loan=loan)
    for payment in old_payments:
        payment.update_safely(
            due_amount=0, installment_principal=0, installment_interest=0, is_restructured=True
        )
    payments = generate_new_payments(loan_duration, loan)
    loan_amount = readjusted_loan_amount_by_max_fee_rule(loan, loan_duration)
    Payment.objects.bulk_create(payments)
    first_payment = loan.payment_set.filter(payment_number=1).only('id', 'due_amount').last()
    last_payment = loan.payment_set.only('id', 'due_amount').last()
    today_ts = timezone.localtime(timezone.now())
    loan.update_safely(
        loan_amount=loan_amount,
        loan_duration=loan_duration,
        sphp_accepted_ts=today_ts,
        sphp_sent_ts=today_ts,
        first_installment_amount=first_payment.due_amount,
        installment_amount=last_payment.due_amount,
    )
    assign_loan_credit_card_to_lender(loan.id)
    upload_sphp_loan_credit_card_to_oss.delay(loan.id)


def waive_interest_in_loan_balance_consolidation(loan):
    duration = loan.loan_duration
    discount_percentage = 100.0
    note_details = 'Zero interest amount for loan balance consolidation'

    total_benefit, payment_events = process_interest_discount_benefit(
        loan=loan,
        duration=duration,
        discount_percentage=discount_percentage,
        max_amount_per_payment=0,
        promo_code=None,
        note_details=note_details,
    )

    payment_event_ids = [pe.id for pe in payment_events]
    balcon_verification = loan.balanceconsolidationverification
    balcon_verification.extra_data["payment_event_ids"] = payment_event_ids
    balcon_verification.save()

    return total_benefit


def get_range_loan_duration_and_amount_apply_zero_interest(transaction_method_code, customer_id):
    """
    Get range loan duration and range loan amount which apply zero interest
    :param transaction_method_code: 1, 2, .... we can get it from TransactionMethodCode
    :param customer_id:
    :return: Tuple(
        is_apply_zero_interest: bool,
        min_duration: int,
        max_duration: int,
        min_loan_amount: int,
        max_loan_amount: int
    )
    """
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ZERO_INTEREST_HIGHER_PROVISION,
        is_active=True,
    ).last()
    if not feature_setting:
        return False, None, None, None, None

    is_apply_zero_interest = True
    parameters = feature_setting.parameters
    condition = parameters['condition']
    whitelist_config = parameters['whitelist']
    if (
        str(transaction_method_code) not in condition['list_transaction_method_code']
        or (
            whitelist_config['is_active']
            and customer_id not in whitelist_config['list_customer_id']
        )
        or (
            not whitelist_config['is_active']
            and parameters['is_experiment_for_last_digit_customer_id_is_even']
            and customer_id % 2 != 0
        )
    ):
        is_apply_zero_interest = False

    if not is_apply_zero_interest:
        return False, None, None, None, None

    return (
        True,
        condition['min_duration'],
        condition['max_duration'],
        condition['min_loan_amount'],
        condition['max_loan_amount'],
    )


def is_eligible_apply_zero_interest(
    transaction_method_code, customer_id, loan_duration, loan_amount, is_zero_interest_request=True
):
    """
    Check if satisfy all conditions to apply zero interest higher provision
    :param transaction_method_code:  1, 2, .... we can get it from TransactionMethodCode
    :param customer_id:
    :param loan_duration:
    :param loan_amount:
    :return: True if satisfy all conditions, False otherwise
    """
    if not is_zero_interest_request:
        return False

    (
        is_apply_zero_interest,
        min_duration,
        max_duration,
        min_loan_amount,
        max_loan_amount,
    ) = get_range_loan_duration_and_amount_apply_zero_interest(transaction_method_code, customer_id)
    if (
        not is_apply_zero_interest
        or not (min_duration <= loan_duration <= max_duration)
        or not (min_loan_amount <= loan_amount <= max_loan_amount)
    ):
        return False

    return True


def adjust_loan_with_zero_interest(
    monthly_interest_rate,
    loan_duration,
    provision_rate,
    application,
    loan_amount_request,
    is_self_bank_account,
    available_limit,
):
    today_date = timezone.localtime(timezone.now()).date()
    first_payment_date = get_first_payment_date_by_application(application)

    # calculate total interest rate
    days_in_month = 30.0
    delta_days = (first_payment_date - today_date).days
    first_interest_rate = delta_days * (monthly_interest_rate / days_in_month)
    total_interest = py2round(
        first_interest_rate + (monthly_interest_rate * (loan_duration - 1)), 3
    )

    # recalculate loan_amount when plus total interest to provision_rate
    provision_rate = py2round(provision_rate + total_interest, 3)
    adjust_loan_amount = get_loan_amount_by_transaction_type(
        loan_amount_request, provision_rate, is_self_bank_account
    )

    if adjust_loan_amount <= available_limit:
        monthly_interest_rate = 0
        # Other method: disbursement_amount == loan_amount_request
        if is_self_bank_account:
            provision_fee = round_rupiah(adjust_loan_amount * provision_rate)
            disbursement_amount = round_rupiah(adjust_loan_amount - provision_fee)
        else:
            disbursement_amount = loan_amount_request

        return adjust_loan_amount, provision_rate, disbursement_amount, monthly_interest_rate

    return None, None, None, None


def is_show_toggle_zero_interest(customer_id, transaction_method_id):
    """
    Having 2 customer segments: FTC, Repeat
        - is FTC, or not FTC and Repeat => False
        - is Repeat => if transaction_id is cash => True else False
    Return: False(not show), True(show)
    """
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ZERO_INTEREST_HIGHER_PROVISION,
        is_active=True,
    ).last()
    if not feature_setting:
        return False

    customer_segments = feature_setting.parameters['customer_segments']
    is_eligible, segment_name = is_customer_segments_zero_interest(customer_segments, customer_id)

    if is_eligible and segment_name == CustomerSegmentsZeroInterest.REPEAT:
        return transaction_method_id in TransactionMethodCode.cash()

    return False


def is_customer_segments_zero_interest(customer_segments, customer_id):
    is_customer_segment = False
    segment = None
    account = Account.objects.filter(customer_id=customer_id).last()

    if ZeroInterestExclude.objects.filter(customer_id=customer_id).exists():
        return is_customer_segment, segment

    if account and account.status_id == JuloOneCodes.ACTIVE:
        loans = Loan.objects.filter(
            account=account, loan_status__gte=LoanStatusCodes.CURRENT
        ).exists()
        if customer_segments['is_ftc'] and not loans:
            is_customer_segment = True
            segment = CustomerSegmentsZeroInterest.FTC
        elif customer_segments['is_repeat'] and loans:
            is_customer_segment = True
            segment = CustomerSegmentsZeroInterest.REPEAT

    return is_customer_segment, segment


def is_customer_can_do_zero_interest(customer, transaction_method_code):
    result = {
        'campaign_name': '',
        'alert_image': '',
        'alert_description': '',
        'max_default_amount': 0,
        'show_alert': False,
        'show_pop_up': False,
        'toggle_title': '',
        'toggle_description': '',
        'toggle_link_text': '',
        'toggle_click_link': '',
    }
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ZERO_INTEREST_HIGHER_PROVISION,
        is_active=True,
    ).last()

    if not feature_setting:
        return False, result

    is_apply_zero_interest = get_range_loan_duration_and_amount_apply_zero_interest(
        transaction_method_code, customer.id
    )
    if not is_apply_zero_interest[0]:
        return False, result

    parameters = feature_setting.parameters
    customer_segments = parameters['customer_segments']
    is_customer_segment, _ = is_customer_segments_zero_interest(customer_segments, customer.id)
    if not is_customer_segment:
        return False, result

    condition = parameters['condition']
    campaign_content = parameters['campaign_content']

    for res in result:
        result[res] = campaign_content.get(res)
    result['campaign_name'] = CampaignConst.ZERO_INTEREST
    result['max_default_amount'] = condition.get('max_loan_amount')

    return True, result


def get_revive_semi_good_customer_score(application):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.REVIVE_SEMI_GOOD_CUSTOMER,
        is_active=True,
    ).last()
    if not feature_setting:
        return None
    parameters = feature_setting.parameters
    application_exists = application.applicationhistory_set.filter(
        change_reason__in=parameters.get('change_reason', [])
    ).exists()
    if not application_exists:
        return None
    return parameters.get('score', 'C+')


def is_loan_is_zero_interest(loan):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ZERO_INTEREST_HIGHER_PROVISION,
        is_active=True,
    ).last()
    if not feature_setting:
        return

    return LoanZeroInterest.objects.filter(loan=loan).exists()


def is_product_locked_for_balance_consolidation(account, method_code, application_direct=None):
    is_locked, _ = is_product_locked_for_balance_consolidation_and_reason(
        account, method_code, application_direct
    )
    return is_locked


def is_product_locked_for_balance_consolidation_and_reason(
    account, method_code, application_direct=None
):
    from juloserver.graduation.services import is_customer_suspend

    is_locked = True
    if not account:
        return is_locked, AccountLockReason.INVALID_ACCOUNT_STATUS

    is_exceed, reason_lock = is_account_exceed_dpd_90(account)
    if is_exceed:
        return is_locked, reason_lock

    if account.status_id not in AccountConstant.UNLOCK_STATUS:
        return is_locked, AccountLockReason.INVALID_ACCOUNT_STATUS

    customer_id = account.customer_id
    is_suspend, reason_lock = is_customer_suspend(customer_id)
    if is_suspend:
        return is_locked, reason_lock

    return False, None


def get_parameters_fs_check_other_active_platforms_using_fdc(
    feature_name=FeatureNameConst.CHECK_OTHER_ACTIVE_PLATFORMS_USING_FDC
):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=feature_name,
        is_active=True,
    ).last()
    return feature_setting.parameters if feature_setting else None


def is_apply_check_other_active_platforms_using_fdc(
    application_id, parameters=None, application=None, transaction_method_id=None
):
    """
    Parameter Application Object is used by partnership to check partner
    check whether application_id is applied check active loans using fdc or not
    :param application_id:
    :param parameters: parameters of feature setting, if not pass in, will get from db
    :return: boolean
    """
    if parameters is None:
        parameters = get_parameters_fs_check_other_active_platforms_using_fdc()

    if not parameters:
        return False

    # when enable whitelist, only application_id in whitelist will be applied
    if parameters['whitelist']['is_active']:
        if application_id in parameters['whitelist']['list_application_id']:
            return True
        else:
            return False

    # bypass transaction method
    transaction_methods_bypass = parameters.get('transaction_methods_bypass')
    if (
        transaction_method_id
        and transaction_methods_bypass
        and transaction_methods_bypass['is_active']
    ):
        whitelist = transaction_methods_bypass['whitelist']
        if whitelist and transaction_method_id in whitelist:
            return False

    # when enable bypass, only application_id NOT in bypass list will be applied
    if parameters['bypass']['is_active']:
        if FDCPlatformCheckBypass.objects.filter(application_id=application_id).exists():
            return False

        if application_id in parameters['bypass']['list_application_id']:
            return False

    c_score_bypass = parameters.get('c_score_bypass', {})
    if c_score_bypass.get('is_active', False):
        if not application:
            application = Application.objects.filter(id=application_id).first()

        application_id = application.id
        dana_application_reference_exists = DanaApplicationReference.objects.filter(
            application_id=application_id
        ).exists()

        if (
            application
            and application.partner
            and (
                application.partner.is_csv_upload_applicable
                or not dana_application_reference_exists
            )
            and application.product_line.product_line_code != ProductLineCodes.J1
        ):
            return True
        else:
            application = Application.objects.get(pk=application_id)
            if dana_application_reference_exists:
                scores = c_score_bypass.get('scores', BYPASS_CREDIT_SCORES_FROM_OTHER_PLATFORMS)
                credit_score = CreditScore.objects.get(application_id=application_id)
                if credit_score.score in scores + ["B"]:
                    return False
                else:
                    return True

            pgood = c_score_bypass.get('pgood_gte', 0)
            account_property = get_account_property_by_account(application.account)
            bypass_fdc_checking = account_property and account_property.pgood >= pgood
            if bypass_fdc_checking:
                return False

    # if the above conditions are not met, always apply check active loans using fdc
    return True


def is_eligible_other_active_platforms(
    application_id,
    fdc_data_outdated_threshold_days,
    number_of_allowed_platforms,
):
    application = Application.objects.get_or_none(id=application_id)
    if not application:
        raise JuloException('Application id = {} not found.'.format(application_id))

    customer_id = application.customer_id

    fdc_active_loan_checking, is_created = FDCActiveLoanChecking.objects.get_or_create(
        customer_id=customer_id
    )
    if not is_created:
        fdc_active_loan_checking.last_access_date = timezone.localtime(timezone.now()).date()
        fdc_active_loan_checking.save()

    if fdc_active_loan_checking.product_line_id != application.product_line_id:
        fdc_active_loan_checking.product_line_id = application.product_line_id
        fdc_active_loan_checking.save()

    customer_ids = get_all_customer_ids_from_ana_and_j1(application)
    if Loan.objects.filter(
        customer_id__in=customer_ids,
        loan_status_id__gte=LoanStatusCodes.CURRENT,
        loan_status_id__lt=LoanStatusCodes.PAID_OFF,
    ).exists():
        # when already had active loans, return True to allow to create another loan
        return True

    fdc_inquiry = get_or_non_fdc_inquiry_not_out_date(
        application_id=application_id, day_diff=fdc_data_outdated_threshold_days
    )
    if not fdc_inquiry:
        # return True to continue the loan to x210, cronjob will update the status before go to x211
        return True

    _, count_other_platforms, _ = get_info_active_loan_from_platforms(fdc_inquiry_id=fdc_inquiry.id)

    fdc_active_loan_checking.number_of_other_platforms = count_other_platforms
    fdc_active_loan_checking.save()

    if count_other_platforms < number_of_allowed_platforms:
        return True

    with redis_lock_for_update(RedisLockKeyName.CREATE_FDC_REJECTED_LOAN_TRACKING, customer_id):
        create_tracking_record_when_customer_get_rejected(
            customer_id, fdc_inquiry.pk, count_other_platforms
        )

    return False


def check_eligible_and_out_date_other_platforms(
    customer_id,
    application_id,
    fdc_data_outdated_threshold_days,
    number_of_allowed_platforms,
):
    _, _ = FDCActiveLoanChecking.objects.get_or_create(customer_id=customer_id)
    application = Application.objects.get(pk=application_id)
    customer_ids = get_all_customer_ids_from_ana_and_j1(application)

    is_out_date = False
    if (
        Loan.objects.filter(customer_id__in=customer_ids)
        .filter(
            Q(
                loan_status_id__gte=LoanStatusCodes.CURRENT,
                loan_status_id__lt=LoanStatusCodes.PAID_OFF,
            )
            | Q(loan_status_id=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        )
        .exists()
    ):
        # continue creating loan when users has active loans
        return True, is_out_date

    fdc_inquiry = get_or_non_fdc_inquiry_not_out_date(
        application_id=application_id, day_diff=fdc_data_outdated_threshold_days
    )
    if not fdc_inquiry:
        is_out_date = True
        return True, is_out_date

    _, count_other_platforms, _ = get_info_active_loan_from_platforms(fdc_inquiry_id=fdc_inquiry.id)

    if not is_out_date and count_other_platforms >= number_of_allowed_platforms:
        create_tracking_record_when_customer_get_rejected(
            customer_id, fdc_inquiry.pk, count_other_platforms
        )

    return count_other_platforms < number_of_allowed_platforms, is_out_date


def handle_reject_loan_for_active_loan_from_platform(loan_id, customer_id):
    update_loan_status_and_loan_history(
        loan_id=loan_id,
        new_status_code=LoanStatusCodes.LENDER_REJECT,
        change_reason="Ineligible active loans from platforms",
    )
    send_user_attributes_to_moengage_for_active_platforms_rule.delay(
        customer_id=customer_id, is_eligible=False
    )


def create_fdc_inquiry_and_execute_check_active_loans(customer, params):
    from juloserver.loan.tasks.lender_related import (
        fdc_inquiry_other_active_loans_from_platforms_task,
    )

    fdc_inquiry = FDCInquiry.objects.create(
        nik=customer.nik, customer_id=customer.pk, application_id=params['application_id']
    )
    fdc_inquiry_data = {'id': fdc_inquiry.pk, 'nik': customer.nik}
    params['fdc_inquiry_id'] = fdc_inquiry.pk

    fdc_inquiry_other_active_loans_from_platforms_task.delay(
        fdc_inquiry_data, customer.pk, FDCUpdateTypes.AFTER_LOAN_STATUS_x211, params
    )


def handle_loan_status_after_fdc_inquiry_success(customer_id: int, params: dict):
    from juloserver.loan.tasks.lender_related import loan_lender_approval_process_task

    loan_id = params['loan_id']
    application_id = params['application_id']
    threshold_days = params['fdc_data_outdated_threshold_days']
    number_platforms = params['number_of_allowed_platforms']

    is_eligible, _ = check_eligible_and_out_date_other_platforms(
        customer_id, application_id, threshold_days, number_platforms
    )

    if is_eligible:
        loan_lender_approval_process_task.delay(loan_id)
    else:
        handle_reject_loan_for_active_loan_from_platform(loan_id, customer_id)


def handle_loan_status_after_fdc_inquiry_failed_completely(customer_id: int, params: dict):
    from juloserver.loan.tasks.lender_related import loan_lender_approval_process_task

    loan_id = params['loan_id']
    application_id = params['application_id']
    number_platforms = params['number_of_allowed_platforms']

    is_eligible, _ = check_eligible_and_out_date_other_platforms(
        customer_id, application_id, None, number_platforms
    )

    if is_eligible:
        loan_lender_approval_process_task.delay(loan_id)
    else:
        handle_reject_loan_for_active_loan_from_platform(loan_id, customer_id)


def update_fdc_active_loan_checking(customer_id, params):
    nearest_due_date, count_other_platforms, _ = get_info_active_loan_from_platforms(
        fdc_inquiry_id=params['fdc_inquiry_id']
    )
    fdc_active_loan_checking = FDCActiveLoanChecking.objects.filter(customer_id=customer_id).first()
    fdc_active_loan_checking.update_safely(
        last_updated_time=timezone.now(),
        nearest_due_date=nearest_due_date,
        number_of_other_platforms=count_other_platforms,
    )

    return fdc_active_loan_checking


def move_grab_app_to_190(application):
    # do the same thing like Grab150Handler, it will move 180 to 190
    from juloserver.grab.workflows import GrabWorkflowAction

    workflow = GrabWorkflowAction(
        application=application,
        new_status_code=application.application_status,
        old_status_code=application.application_status,
        change_reason='',
        note=''
    )
    workflow.register_or_update_customer_to_privy()


def grab_handle_daily_checker(customer_id):
    # only last app 180 will procceed
    application = Application.objects.filter(
        customer_id=customer_id,
        application_status=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
        workflow__name=WorkflowConst.GRAB
    ).last()
    if application:
        move_grab_app_to_190(application)


def handle_update_after_fdc_inquiry_success(type: str, customer_id: int, params: dict):
    fdc_active_loan_checking = update_fdc_active_loan_checking(customer_id, params)

    if type == FDCUpdateTypes.AFTER_LOAN_STATUS_x211:
        handle_loan_status_after_fdc_inquiry_success(customer_id, params)
    elif type == FDCUpdateTypes.DAILY_CHECKER:
        number_of_other_platforms = fdc_active_loan_checking.number_of_other_platforms
        if number_of_other_platforms < params['number_of_allowed_platforms']:
            send_user_attributes_to_moengage_for_active_platforms_rule.delay(
                customer_id=customer_id, is_eligible=True
            )
    elif type == FDCUpdateTypes.GRAB_DAILY_CHECKER:
        number_of_other_platforms = fdc_active_loan_checking.number_of_other_platforms
        if number_of_other_platforms < params['number_of_allowed_platforms']:
            grab_handle_daily_checker(customer_id)
    elif type == FDCUpdateTypes.GRAB_STUCK_150:
        # just keep it as it
        # let scheduler for 150 handle it
        pass


def handle_update_after_fdc_inquiry_failed_completely(type: str, customer_id: int, params: dict):
    if type == FDCUpdateTypes.AFTER_LOAN_STATUS_x211:
        handle_loan_status_after_fdc_inquiry_failed_completely(customer_id, params)


def get_fdc_loan_active_checking_for_daily_checker(
    params: dict, current_time: datetime, applied_product_lines: list = None
):
    config = params['daily_checker_config']
    number_allowed_platforms = params['number_of_allowed_platforms']
    nearest_due_date_diff = config['nearest_due_date_from_days']

    customer_ids = FDCActiveLoanChecking.objects.filter(
        Q(
            number_of_other_platforms__gte=number_allowed_platforms,
            last_updated_time__lte=current_time - relativedelta(days=config['retry_per_days']),
            nearest_due_date__lte=current_time.date() + relativedelta(days=nearest_due_date_diff),
        )
        | Q(number_of_other_platforms__isnull=True)
    )

    if applied_product_lines:
        customer_ids = customer_ids.filter(product_line_id__in=applied_product_lines)

    return customer_ids.values_list('customer_id', flat=True)


def get_parameters_fs_check_gtl():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CHECK_GTL,
        is_active=True,
    ).last()
    return feature_setting.parameters if feature_setting else None


def is_apply_gtl_inside(transaction_method_code, application, parameters=None):
    """
    only apply for J1 & Jturbo
    check whether application_id is applied check GTL or not
    :param transaction_method_code: used to check list_transaction_method_code
    :param application: used to check whitelist
    :param parameters: parameters of feature setting, if not pass in, will get from db
    :return: boolean
    """
    if not application.is_julo_one_or_starter():
        return False

    if parameters is None:
        parameters = get_parameters_fs_check_gtl()

    if not parameters:
        return False

    if transaction_method_code not in parameters['list_transaction_method_code']:
        return False

    # when enable whitelist, only application_id in whitelist will be applied
    if parameters['whitelist']['is_active']:
        if application.id in parameters['whitelist']['list_application_id']:
            return True
        else:
            return False

    # if the above conditions are not met, always apply check active loans using fdc
    return True


def is_eligible_gtl_inside(
    account_limit,
    loan_amount_request,
    threshold_set_limit_percent,
    threshold_loan_within_hours,
):
    account_id = account_limit.account_id
    account_gtl = AccountGTL.objects.get_or_none(account_id=account_id)
    if account_gtl and account_gtl.is_gtl_inside:
        logger.info(
            {
                'action': 'is_eligible_gtl_inside',
                'account_id': account_id,
                'status': 'ineligible gtl inside because already blocked before',
            }
        )
        return False

    now = timezone.localtime(timezone.now())
    earliest_threshold_time = now - timedelta(hours=threshold_loan_within_hours)
    if (
        # check limit utilization at 90+% after taking new loan
        loan_amount_request + account_limit.used_limit
        >= account_limit.set_limit * threshold_set_limit_percent / 100
    ):
        # check is there any paid off loans within 12 hours
        loan_ids = LoanHistory.objects.filter(
            loan__account_id=account_id,
            status_new=LoanStatusCodes.PAID_OFF,
            cdate__gte=earliest_threshold_time,
        ).values_list('loan_id', flat=True)

        # check is there any dpd+1 loans within 12 hours:
        # - get all payments of all paid off loans within 12 hours
        # - order by payment_number desc
        # - check is there any last payment with status dpd+1
        # (loop through all payments but only check last payment of each loan)
        payments = (
            Payment.objects.filter(loan_id__in=loan_ids)
            .order_by('-payment_number')
            .only('loan_id', 'payment_status_id')
        )

        is_exist_paid_dpd_plus_one = False
        checked_last_payment_loan_ids = []
        for payment in payments:
            if payment.loan_id not in checked_last_payment_loan_ids:
                checked_last_payment_loan_ids.append(payment.loan_id)
                if payment.payment_status_id in PaymentStatusCodes.paid_dpd_plus_one():
                    is_exist_paid_dpd_plus_one = True
                    break

        if not is_exist_paid_dpd_plus_one:
            return True

        logger.info(
            {
                'action': 'is_eligible_gtl_inside',
                'account_id': account_id,
                'status': 'ineligible gtl inside because does not satisfy GTL rule',
            }
        )
        return False

    return True


def check_lock_by_gtl_inside(account, method_code):
    gtl_fs_parameters = get_parameters_fs_check_gtl()
    return (
        gtl_fs_parameters
        and method_code in gtl_fs_parameters['list_transaction_method_code']
        and AccountGTL.objects.filter(account_id=account.id, is_gtl_inside=True).exists()
    )


def create_loan_rejected_by_gtl(account_id, transaction_method_id, loan_amount_request, reason):
    LoanFailGTL.objects.create(
        account_id=account_id,
        transaction_method_id=transaction_method_id,
        loan_amount_request=loan_amount_request,
        reason=reason,
    )


def create_or_update_is_maybe_gtl_inside(account_id: int, new_value: bool):
    account_gtl = AccountGTL.objects.get_or_none(account_id=account_id)
    if account_gtl:
        if account_gtl.is_maybe_gtl_inside != new_value:
            AccountGTLHistory.objects.create(
                account_gtl=account_gtl,
                field_name='is_maybe_gtl_inside',
                value_old=account_gtl.is_maybe_gtl_inside,
                value_new=new_value,
            )
            account_gtl.is_maybe_gtl_inside = new_value
            account_gtl.save()
            logger.info(
                {
                    'action': 'create_or_update_is_maybe_gtl_inside',
                    'message': 'update is_maybe_gtl_inside from existing account gtl record',
                    'account_id': account_id,
                    'new_value': new_value,
                }
            )
    else:
        AccountGTL.objects.create(account_id=account_id, is_maybe_gtl_inside=new_value)
        logger.info(
            {
                'action': 'create_or_update_is_maybe_gtl_inside',
                'message': 'create new account gtl record',
                'account_id': account_id,
                'new_value': new_value,
            }
        )


def create_or_update_is_maybe_gtl_inside_and_send_to_moengage(
    customer_id, account_id, new_value_is_maybe_gtl_inside
):
    with transaction.atomic():
        create_or_update_is_maybe_gtl_inside(
            account_id=account_id,
            new_value=new_value_is_maybe_gtl_inside,
        )
        execute_after_transaction_safely(
            lambda: send_gtl_event_to_moengage.delay(
                customer_id=customer_id,
                event_type=MoengageEventType.MAYBE_GTL_INSIDE,
                event_attributes={'is_maybe_gtl_inside': new_value_is_maybe_gtl_inside},
            )
        )


def process_block_by_gtl_inside(account_id):
    """
    If exist AccountGTL, change flag. If not exist, create new record to block due to GTL inside.
    """
    account_gtl = AccountGTL.objects.get_or_none(account_id=account_id)

    # create new record for this account to block
    if not account_gtl:
        AccountGTL.objects.create(account_id=account_id, is_gtl_inside=True)
        return

    # re-block again after unblocking
    AccountGTLHistory.objects.create(
        account_gtl=account_gtl,
        field_name='is_gtl_inside',
        value_old=False,
        value_new=True,
    )
    account_gtl.is_gtl_inside = True
    account_gtl.save()


def process_check_gtl_inside(
    transaction_method_id, loan_amount, application, customer_id, account_limit
):
    params = get_parameters_fs_check_gtl()
    if not params or not is_apply_gtl_inside(transaction_method_id, application, params):
        return None

    account_id = account_limit.account_id
    if is_eligible_gtl_inside(
        account_limit=account_limit,
        loan_amount_request=loan_amount,
        threshold_set_limit_percent=params['threshold_set_limit_percent'],
        threshold_loan_within_hours=params['threshold_loan_within_hours'],
    ):
        # update is_maybe_gtl_inside to False in case maybe flag=True (paid off but late),
        # but doesn't satisfy taking loan of 90% of set limit or within 12hour
        if AccountGTL.objects.filter(
            account_id=account_id,
            is_maybe_gtl_inside=True,
        ).exists():
            create_or_update_is_maybe_gtl_inside_and_send_to_moengage(
                customer_id=customer_id,
                account_id=account_id,
                new_value_is_maybe_gtl_inside=False,
            )
        return None

    with transaction.atomic():
        # for calculate the financial impact
        create_loan_rejected_by_gtl(
            account_id=account_id,
            transaction_method_id=transaction_method_id,
            loan_amount_request=loan_amount,
            reason=LoanFailGTLReason.INSIDE,
        )
        process_block_by_gtl_inside(account_id)
        create_or_update_is_maybe_gtl_inside_and_send_to_moengage(
            customer_id=customer_id,
            account_id=account_id,
            new_value_is_maybe_gtl_inside=False,
        )
        execute_after_transaction_safely(
            lambda: send_gtl_event_to_moengage.delay(
                customer_id=customer_id,
                event_type=MoengageEventType.GTL_INSIDE,
                event_attributes={'is_gtl_inside': True},
            )
        )

    params['ineligible_popup']['error_code'] = ErrorCode.INELIGIBLE_GTL_INSIDE
    return general_error_response(
        # 400 with errors[0] contains message to handle backward compatibility
        message=params['ineligible_message_for_old_application'],
        data={
            # show popup in new application version
            'error_popup': params['ineligible_popup'],
        },
    )


def create_tracking_record_when_customer_get_rejected(
    customer_id, fdc_inquiry_id, number_other_platforms
):
    # record one record per one day
    rejected_date = timezone.localtime(timezone.now()).date()
    _, _ = FDCRejectLoanTracking.objects.get_or_create(
        customer_id=customer_id,
        rejected_date=rejected_date,
        fdc_inquiry_id=fdc_inquiry_id,
        defaults={'number_of_other_platforms': number_other_platforms},
    )


def get_params_fs_gtl_cross_platform() -> Dict:
    fs = FeatureSettingHelper(
        FeatureNameConst.GTL_CROSS_PLATFORM,
    )

    if fs.is_active:
        return fs.params

    return None


def is_b_score_satisfy_gtl_outside(customer_id, threshold_lte_b_score):
    pd_clcs_prime_result = (
        PdClcsPrimeResult.objects.filter(customer_id=customer_id).order_by('partition_date').last()
    )
    if not pd_clcs_prime_result or pd_clcs_prime_result.b_score is None:
        return False

    if pd_clcs_prime_result.b_score <= threshold_lte_b_score:
        return True

    return False


def is_repeat_user_gtl_outside(customer_id):
    min_paid_date_payment = Payment.objects.filter(loan__customer_id=customer_id).aggregate(
        Min('paid_date')
    )['paid_date__min']
    today = timezone.localtime(timezone.now()).date()
    if not min_paid_date_payment or min_paid_date_payment > today:
        return False
    return True


def calculate_date_diff_m_and_m_minus_1_gtl_outside(last_due_date):
    today = timezone.localtime(timezone.now()).date()

    if today >= last_due_date:
        predicted_due_date_m = last_due_date
    else:
        predicted_due_date_m = replace_day(original_date=today, new_day=last_due_date.day)

    predicted_due_date_m_minus_1 = predicted_due_date_m - relativedelta(months=1)

    date_diff_m = (today - predicted_due_date_m).days
    date_diff_m_minus_1 = (today - predicted_due_date_m_minus_1).days
    return date_diff_m, date_diff_m_minus_1


def is_fdc_loan_satisfy_gtl_outside(application_id, threshold_gt_last_dpd_fdc):
    """
    calculate date diff between today and predicted due date in current month & previous month.
    if date diff is 4-5 days, need to check DPD history of fdc_id (loan id in other platforms).
    if there is a history of fdc_id with last_dpd > 0, block by GTL outside
    """
    # the query below contains all histories of loans
    fdc_inquiry_loans = (
        FDCInquiryLoan.objects.filter(
            fdc_inquiry__application_id=application_id,
            fdc_inquiry__inquiry_status='success',
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
        )
        .exclude(is_julo_loan=True)
        .exclude(id_penyelenggara=GTLOutsideConstant.EXCLUDE_ORGANIZER_AFDC150)
        .annotate(last_due_date=F('tgl_jatuh_tempo_pinjaman'), last_dpd=F('dpd_terakhir'))
        .values('last_due_date', 'last_dpd', 'fdc_id')
    )

    # bypass when users FDC inquiry loan do not have outstanding
    if not fdc_inquiry_loans:
        return False

    set_fdc_id_has_dpd_history = set()
    for fdc_inquiry_loan in fdc_inquiry_loans:
        fdc_id = fdc_inquiry_loan['fdc_id']
        if fdc_inquiry_loan['last_dpd'] > threshold_gt_last_dpd_fdc:
            set_fdc_id_has_dpd_history.add(fdc_id)

    for fdc_inquiry_loan in fdc_inquiry_loans:
        fdc_id = fdc_inquiry_loan['fdc_id']
        date_diff_m, date_diff_m_minus_1 = calculate_date_diff_m_and_m_minus_1_gtl_outside(
            last_due_date=fdc_inquiry_loan['last_due_date']
        )

        if (
            date_diff_m in GTLOutsideConstant.ACCEPTABLE_DATE_DIFFS
            or date_diff_m_minus_1 in GTLOutsideConstant.ACCEPTABLE_DATE_DIFFS
        ) and fdc_id in set_fdc_id_has_dpd_history:
            return True

    return False


def process_block_by_gtl_outside(account_id, is_experiment, block_time_in_hours):
    """
    If exist AccountGTL, change flag. If not exist, create new record to block due to GTL outside.
    last_gtl_outside_blocked is used to unblock after block_time_in_hours.
    """
    new_last_gtl_outside_blocked = timezone.localtime(timezone.now()) + timedelta(
        hours=block_time_in_hours
    )

    account_gtl = AccountGTL.objects.get_or_none(account_id=account_id)

    # create new record for this account to block
    if not account_gtl:
        AccountGTL.objects.create(
            account_id=account_id,
            # is_experiment = False
            # -> block by GTL outside: is_gtl_outside=True, is_gtl_outside_bypass=False
            # is_experiment = True
            # -> bypass block by GTL outside: is_gtl_outside=False, is_gtl_outside_bypass=True
            is_gtl_outside=not is_experiment,
            is_gtl_outside_bypass=is_experiment,
            last_gtl_outside_blocked=new_last_gtl_outside_blocked if not is_experiment else None,
        )
        return

    # re-block again after unblocking

    account_gtl_histories = []
    if is_experiment and not account_gtl.is_gtl_outside_bypass:
        account_gtl_histories.append(
            AccountGTLHistory(
                account_gtl=account_gtl,
                field_name='is_gtl_outside_bypass',
                value_old=False,
                value_new=True,
            )
        )
        account_gtl.is_gtl_outside_bypass = True

    if not is_experiment:
        if account_gtl.is_gtl_outside_bypass:
            account_gtl_histories.append(
                AccountGTLHistory(
                    account_gtl=account_gtl,
                    field_name='is_gtl_outside_bypass',
                    value_old=True,
                    value_new=False,
                )
            )
            account_gtl.is_gtl_outside_bypass = False

        account_gtl_histories.append(
            AccountGTLHistory(
                account_gtl=account_gtl,
                field_name='is_gtl_outside',
                value_old=False,
                value_new=True,
            )
        )
        account_gtl.is_gtl_outside = True

        account_gtl_histories.append(
            AccountGTLHistory(
                account_gtl=account_gtl,
                field_name='last_gtl_outside_blocked',
                # stored with UTC in database, but value old & new are text field
                # so convert to local tz to easy compare
                value_old=account_gtl.last_gtl_outside_blocked.astimezone(
                    timezone.get_current_timezone()
                ) if account_gtl.last_gtl_outside_blocked else None,
                value_new=new_last_gtl_outside_blocked,
            )
        )
        account_gtl.last_gtl_outside_blocked = new_last_gtl_outside_blocked

    account_gtl.save()
    AccountGTLHistory.objects.bulk_create(account_gtl_histories)


def is_eligible_gtl_outside(
    application_id: int,
    customer_id: int,
    account_limit: AccountLimit,
    loan_amount_request: int,
    threshold_gte_available_limit_percent=GTLOutsideConstant.DEFAULT_THRESHOLD_GTE_LIMIT_PERCENT,
    threshold_lte_b_score=GTLOutsideConstant.DEFAULT_THRESHOLD_LTE_B_SCORE,
    threshold_gt_last_dpd_fdc=GTLOutsideConstant.DEFAULT_THRESHOLD_GT_LAST_DPD_FDC,
) -> bool:
    """
    check whether block by GTL outside.
    is_experiment, block_time_in_hours & threshold params are taken from FS config
    :param application_id: used to check FDC inquiry
    :param customer_id: used to check B score & repeat user
    :param account_limit: used to get account_id to get AccountGTL & check limit utilization
    :param loan_amount_request: used to check limit utilization
    :param is_experiment: bypass GTL outside (for testing)
    :param block_time_in_hours: only block for a period of time, have cron job to unblock after that
    :param threshold_gte_available_limit_percent: check loan amount request with available limit
    :param threshold_lte_b_score: check B score
    :param threshold_gt_last_dpd_fdc: check DPD history of FDC loan
    :return: True -> not blocked by GTL outside, False -> blocked by GTL outside
    """
    account_id = account_limit.account_id

    def log_and_return(is_eligible, message) -> bool:
        logger.info(
            {
                'action': 'is_eligible_gtl_outside',
                'application_id': application_id,
                'customer_id': customer_id,
                'account_id': account_id,
                'is_block_by_gtl_outside': not is_eligible,
                'message': message,
            }
        )
        return is_eligible

    # CHECK ALREADY LOCKED BEFORE
    account_gtl = AccountGTL.objects.get_or_none(account_id=account_id)
    if account_gtl and account_gtl.is_gtl_outside:
        if account_gtl.is_gtl_outside_bypass:
            return log_and_return(
                True, 'eligible because blocked before but bypassed due to experiment'
            )
        else:
            return log_and_return(False, 'ineligible because blocked before')

    # CHECK CREDIT UTILIZATION: only apply for loan amount request more than 90% of available limit
    if (
        loan_amount_request
        <= account_limit.available_limit * threshold_gte_available_limit_percent / 100
    ):
        return log_and_return(True, 'bypass because loan amount request is not enough')

    # CHECK B SCORE: bypass when B Score > 0.75
    if not is_b_score_satisfy_gtl_outside(customer_id, threshold_lte_b_score):
        return log_and_return(True, 'bypass because b score is greater than threshold')

    # CHECK REPEAT USER: bypass if not repeat user
    if not is_repeat_user_gtl_outside(customer_id):
        return log_and_return(True, 'bypass because user is not repeat user')

    # CHECK FDC OUTSTANDING LOANS:
    if not is_fdc_loan_satisfy_gtl_outside(application_id, threshold_gt_last_dpd_fdc):
        return log_and_return(True, 'bypass because pass FDC inquiry loan rule')

    return log_and_return(False, 'ineligible because does not satisfy GTL outside rule')


def check_lock_by_gtl_outside(account, method_code):
    """
    check which transaction method is locked in homepage for GTL outside
    """
    params = get_params_fs_gtl_cross_platform()
    return (
        params
        and method_code in params['block_trx_method_ids']
        and AccountGTL.objects.filter(
            account_id=account.id, is_gtl_outside=True, is_gtl_outside_bypass=False
        ).exists()
    )


def is_experiment_gtl_outside(experiment_last_digits, application_id):
    return experiment_last_digits and application_id % 10 in experiment_last_digits


def is_apply_gtl_outside(transaction_method_code, application, fs_parameters):
    """
    check whether application_id is applied check GTL or not:
    only apply for J1 & Jturbo and depends on FS config
    """
    if not application.is_julo_one_or_starter():
        return False

    if not fs_parameters:
        return False

    if transaction_method_code not in fs_parameters['block_trx_method_ids']:
        return False

    return True


def fill_dynamic_param_in_error_message_gtl_outside(block_time_in_hours, message):
    waiting_days = block_time_in_hours // 24
    return message.replace(GTLOutsideConstant.DYNAMIC_PARAM_IN_ERROR_MESSAGE, str(waiting_days))


def process_check_gtl_outside(
    transaction_method_id, loan_amount, application, customer_id, account_limit
):
    params = get_params_fs_gtl_cross_platform()
    if not params or not is_apply_gtl_outside(
        transaction_method_code=transaction_method_id, application=application, fs_parameters=params
    ):
        return None

    application_id = application.id
    account_id = account_limit.account_id
    block_time_in_hours = params['block_time_in_hours']

    if is_eligible_gtl_outside(
        application_id=application_id,
        customer_id=customer_id,
        account_limit=account_limit,
        loan_amount_request=loan_amount,
        threshold_gte_available_limit_percent=params['threshold_gte_available_limit_percent'],
        threshold_lte_b_score=params['threshold_lte_b_score'],
        threshold_gt_last_dpd_fdc=params['threshold_gt_last_dpd_fdc'],
    ):
        return None

    is_experiment = is_experiment_gtl_outside(
        experiment_last_digits=params['exclude_app_id_last_digit'],
        application_id=application_id,
    )

    with transaction.atomic():
        # for calculate the financial impact
        create_loan_rejected_by_gtl(
            account_id=account_id,
            transaction_method_id=transaction_method_id,
            loan_amount_request=loan_amount,
            reason=LoanFailGTLReason.OUTSIDE,
        )

        process_block_by_gtl_outside(
            account_id=account_id,
            is_experiment=is_experiment,
            block_time_in_hours=block_time_in_hours,
        )

        if not is_experiment:
            execute_after_transaction_safely(
                lambda: send_gtl_event_to_moengage.delay(
                    customer_id=customer_id,
                    event_type=MoengageEventType.GTL_OUTSIDE,
                    event_attributes={'is_gtl_outside': True},
                )
            )

    # do not show the error popup when do experiment
    if is_experiment:
        return None

    # replace waiting days in the error message based on feature setting

    ineligible_message_for_old_application = fill_dynamic_param_in_error_message_gtl_outside(
        block_time_in_hours=block_time_in_hours,
        message=params['ineligible_message_for_old_application'],
    )
    params['ineligible_popup']['content'] = fill_dynamic_param_in_error_message_gtl_outside(
        block_time_in_hours=block_time_in_hours,
        message=params['ineligible_popup']['content'],
    )
    params['ineligible_popup']['error_code'] = ErrorCode.INELIGIBLE_GTL_OUTSIDE

    return general_error_response(
        # 400 with errors[0] contains message to handle backward compatibility
        message=ineligible_message_for_old_application,
        data={
            # show popup in new application version
            'error_popup': params['ineligible_popup'],
        },
    )


def process_check_gtl(transaction_method_id, loan_amount, application, customer_id, account_limit):
    """
    check GTL inside first. If they pass inside, then check the outside
    """
    gtl_inside_error_response = process_check_gtl_inside(
        transaction_method_id=transaction_method_id,
        loan_amount=loan_amount,
        application=application,
        customer_id=customer_id,
        account_limit=account_limit,
    )
    if gtl_inside_error_response:
        return gtl_inside_error_response

    gtl_outside_error_response = process_check_gtl_outside(
        transaction_method_id=transaction_method_id,
        loan_amount=loan_amount,
        application=application,
        customer_id=customer_id,
        account_limit=account_limit,
    )
    if gtl_outside_error_response:
        return gtl_outside_error_response


def get_all_customer_ids_from_ana_and_j1(application: Application) -> list:
    """
    Get all customer_ids from ana when a user has J1 and vice versa
    if current application is J1 => using application.ktp
    else dana_customer_data.ktp
    """
    customer_ids = []
    if hasattr(application, "dana_customer_data"):
        dana_customer_data = application.dana_customer_data
        customer_ids = list(
            Application.objects.filter(ktp=dana_customer_data.nik)
            .exclude(customer_id=application.customer_id)
            .values_list("customer_id", flat=True)
        )
    else:
        # This to get Dana customer_id if current application is J1
        customer_ids = list(
            DanaCustomerData.objects.filter(nik=application.ktp)
            .exclude(customer_id=application.customer_id)
            .values_list("customer_id", flat=True)
        )
    return customer_ids + [application.customer_id]


def is_eligible_application_status(account: Account, application_direct: Application):
    application = application_direct or account.get_active_application()
    if not application or (
        application.status < ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        and application.is_julo_starter()
    ):
        return False
    return True


def get_loan_from_xid(loan_xid: int) -> Loan:
    return Loan.objects.filter(
        loan_xid=loan_xid,
    ).last()


def get_allowed_transaction_methods_from_name_bank_mismatch_fs() -> dict:
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FAILED_BANK_NAME_VALIDATION_DURING_UNDERWRITING,
        is_active=True,
    ).first()
    return fs.parameters['allowed_transaction_methods'] if fs else None


def is_name_in_bank_mismatch(
    account: Account, application_direct: Application, method_code: int
) -> bool:
    """
    If the application has IS_NAME_IN_BANK_MISMATCH_TAG => check allowed_transaction_method in fs
    """
    locked = True
    not_locked = False

    allowed_transaction_methods = get_allowed_transaction_methods_from_name_bank_mismatch_fs()
    if allowed_transaction_methods is None or str(method_code) in allowed_transaction_methods:
        return not_locked

    current_application = application_direct or account.get_active_application()
    if not current_application:
        return locked

    # if name bank mismatch exists and method_code not in allowed_transaction_methods => locked
    name_bank_mismatch_exists = ApplicationPathTag.objects.filter(
        application_id=current_application.pk,
        application_path_tag_status__application_tag=IS_NAME_IN_BANK_MISMATCH_TAG,
        application_path_tag_status__status=1,
    ).exists()
    if name_bank_mismatch_exists:
        return locked

    return not_locked


def get_lock_info_in_app_bottom_sheet(
        reason_locked: str, product_lock_fs: FeatureSetting
) -> dict:
    parameters = product_lock_fs.parameters if product_lock_fs else {}
    lock_info = parameters.get(reason_locked, {})
    return {
        "body": lock_info.get("body", DEFAULT_LOCK_PRODUCT_BOTTOM_SHEET_INFO["body"]),
        "title": lock_info.get("title", DEFAULT_LOCK_PRODUCT_BOTTOM_SHEET_INFO["title"]),
        "button": lock_info.get("button", DEFAULT_LOCK_PRODUCT_BOTTOM_SHEET_INFO["button"]),
    }


def is_account_exceed_dpd_90(account):
    from juloserver.julo.product_lines import ProductLineCodes

    lock_reason = AccountLockReason.INVALID_ACCOUNT_STATUS_A
    if is_account_exceed_dpd_threshold(account) and not account.get_oldest_unpaid_account_payment():
        application = account.last_application
        if application and application.product_line_id in ProductLineCodes.julo_product():
            return True, lock_reason

    return False, lock_reason


def get_loan_write_off_feature_setting():
    fs = FeatureSetting.objects.filter(
        feature_name=ChannelingFeatureNameConst.LOAN_WRITE_OFF,
        is_active=True,
    ).first()

    return fs.parameters if fs else {}


def create_loan_transaction_detail(transaction_detail_data: LoanTransactionDetailData):
    LoanTransactionDetail.objects.create(
        loan_id=transaction_detail_data.loan.id,
        detail={
            "admin_fee": transaction_detail_data.admin_fee,
            "provision_fee_rate": transaction_detail_data.provision_fee_rate,
            "dd_premium": transaction_detail_data.dd_premium,
            "insurance_premium": transaction_detail_data.insurance_premium,
            "digisign_fee": transaction_detail_data.digisign_fee,
            "total_registration_fee": transaction_detail_data.total_registration_fee,
            "tax_fee": transaction_detail_data.tax_fee,
            "monthly_interest_rate": transaction_detail_data.monthly_interest_rate,
            "tax_on_fields": transaction_detail_data.tax_on_fields,
            "promo_applied": transaction_detail_data.promo_applied,
        }
    )


def is_eligible_auto_adjust_due_date(customer_id: int, whitelist_config: dict) -> bool:
    if not whitelist_config["is_active"]:
        return True

    last_customer_digit = int(str(customer_id)[-2:])
    from_digit = int(whitelist_config["last_customer_digit"]["from"])
    to_digit = int(whitelist_config["last_customer_digit"]["to"])

    return (
        customer_id in whitelist_config["customer_ids"]
        or from_digit <= last_customer_digit <= to_digit
    )


def get_auto_adjust_due_date(account: Account, mapping_config: dict) -> Tuple[Optional[int], date]:
    curr_cycle_day = account.cycle_day
    new_cycle_day = mapping_config.get(str(curr_cycle_day))
    offer_date = timezone.localtime(timezone.now()).date()

    if new_cycle_day:
        first_payment_date = offer_date + relativedelta(day=new_cycle_day)
    else:
        first_payment_date = offer_date + relativedelta(day=curr_cycle_day)

    first_payment_date = shift_due_date_forward(
        due_date=first_payment_date,
        offer_date=offer_date,
        min_days=MINIMUM_DAY_DIFF_LDDE_v2_FLOW
    )
    return new_cycle_day, first_payment_date


def shift_due_date_forward(due_date: date, offer_date: date, min_days: int) -> date:
    cycle_day = due_date.day
    new_due_date = offer_date + relativedelta(day=cycle_day)
    while (new_due_date - offer_date).days < min_days:
        new_due_date += relativedelta(months=1, day=cycle_day)

    return new_due_date


def get_loan_transaction_detail(loan_id: int) -> dict:
    obj = LoanTransactionDetail.objects.filter(loan_id=loan_id).last()
    if obj:
        detail = obj.detail
        detail['loan_id'] = loan_id
        return detail

    return {}
