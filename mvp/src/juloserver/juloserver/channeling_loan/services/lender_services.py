from __future__ import division

import logging

from django.utils import timezone

from juloserver.channeling_loan.services.bss_services import is_holdout_users_from_bss_channeling
from juloserver.channeling_loan.services.general_services import (
    loan_risk_acceptance_criteria_check,
    get_channeling_loan_configuration,
    get_general_channeling_ineligible_conditions,
    filter_field_channeling,
    get_bypass_daily_limit_threshold_config,
    get_channeling_eligibility_status,
)
from juloserver.julo.clients import get_julo_sentry_client

from juloserver.followthemoney.models import (
    LenderCurrent,
    LenderBalanceCurrent,
)
from juloserver.channeling_loan.tasks import send_loan_for_channeling_task

from juloserver.julo.models import Loan, FeatureSetting, StatusLookup
from juloserver.channeling_loan.constants import ChannelingConst, FeatureNameConst
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan.services.loan_related import (
    compute_first_payment_installment_julo_one,
    compute_payment_installment_julo_one,
    calculate_loan_amount,
    get_first_payment_date_by_application,
)
from juloserver.payment_point.models import TransactionMethod

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def channeling_lender_auto_matchmaking(loan_id, loan_amount, lender_ids=[]):
    lenders = (
        LenderCurrent.objects.filter(lender_status='active', is_pre_fund_channeling_flow=True)
        .order_by('lenderdisbursecounter__rounded_count', 'lenderdisbursecounter__cdate')
    )
    if lender_ids:
        lenders = lenders.exclude(id__in=lender_ids)
    assigned_lender = None
    for lender in lenders:
        # need available_balance is not enough, next lender automatically selected
        assigned_lender = lender
        lender_balance = LenderBalanceCurrent.objects.get_or_none(
            lender=lender, available_balance__gte=loan_amount
        )

        if lender_balance:
            if send_loan_for_channeling_task(
                loan_id, lender_list=[lender.lender_name], is_prefund=True
            ):
                break

        assigned_lender = None
        logger.info(
            {
                'task': (
                    'juloserver.channeling_loan.services.general_services'
                    '.channeling_lender_auto_matchmaking'
                ),
                'loan_id': loan_id,
                'original_lender': lender.id,
                'message': 'lender balance insufficient',
            }
        )

    return assigned_lender


def force_assigned_lender(loan: Loan):
    logger.info(
        {
            "action": "force_assigned_lender",
            "message": "start checking is balance available & status active FAMA",
            "loan_id": loan.id,
        }
    )
    lender_balance_fama = LenderBalanceCurrent.objects.filter(
        lender__lender_name=ChannelingConst.LENDER_FAMA,
        available_balance__gte=loan.loan_amount,
        lender__lender_status='active',
    ).last()
    if lender_balance_fama:
        if send_loan_for_channeling_task(
            loan.id, lender_list=[lender_balance_fama.lender.lender_name], is_prefund=True
        ):
            logger.info(
                {
                    "action": "force_assigned_lender",
                    "message": "Assigned lender to FAMA",
                    "loan_id": loan.id,
                }
            )
            return lender_balance_fama.lender
    logger.info(
        {
            "action": "force_assigned_lender",
            "message": "not eligible FAMA, will assign to JTP",
            "loan_id": loan.id,
        }
    )
    return LenderCurrent.objects.get_or_none(lender_name=ChannelingConst.LENDER_JTP)


def is_force_assign_lender_active(loan: Loan):
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FORCE_CHANNELING,
        is_active=True,
    ).last()
    if fs and loan.loan_duration in fs.parameters["FAMA"]:
        return True
    return False


def check_channeling_eligibility_bypass_daily_limit(application, loan_data):
    """
    Args:
        application:
        loan_data: {
          "account_id": 230709,
          "bank_account_number": "99320909806969",
          "android_id": "77b345910f6ed496",
          "bank_account_destination_id": 107269,
          "bpjs_times": 0,
          "device_brand": "Genymobile",
          "device_model": "Redmi Note 7",
          "loan_duration": 4,
          "gcm_reg_id": "DEFAULT_GCM_ID",
          "is_julo_care": True,
          "self_bank_account": True,
          "is_suspicious_ip": False,
          "is_tax": True,
          "is_web_location_blocked": True,
          "is_zero_interest": False,
          "loan_amount_request": 1000000,
          "manufacturer": "Xiaomi",
          "model": "Redmi Note 7",
          "os_version": 29,
          "is_payment_point": False,
          "pin": "159357",
          "loan_purpose": "Modal usaha",
          "transaction_type_code": 1
        }
    Returns:
    """
    action = 'services.lender_services.check_channeling_eligibility_bypass_daily_limit'

    logger.info(
        {
            'action': action,
            'application_id': application.id,
            'message': 'start check channeling eligibility bypass daily limit',
        }
    )

    bypass_daily_limit_threshold_config = get_bypass_daily_limit_threshold_config()
    if not bypass_daily_limit_threshold_config:
        logger.info(
            {
                'action': action,
                'application_id': application.id,
                'loan_data': loan_data,
                'message': "is_bypass_daily_limit_threshold_config inactive",
            }
        )
        return None

    lenders = LenderCurrent.objects.filter(
        lender_status='active', is_pre_fund_channeling_flow=True
    ).order_by('lenderdisbursecounter__rounded_count', 'lenderdisbursecounter__cdate')

    loan_amount = loan_data['loan_amount_request']
    loan_duration = loan_data['loan_duration']
    today_date = timezone.localtime(timezone.now()).date()
    transaction_method_id = loan_data.get('transaction_type_code', None)
    first_payment_date = get_first_payment_date_by_application(application)
    is_payment_point = loan_data.get('is_payment_point', False)

    transaction_type = None

    if transaction_method_id:
        transaction_method = TransactionMethod.objects.filter(id=transaction_method_id).last()
        if transaction_method:
            transaction_type = transaction_method.method

    adjusted_loan_amount, credit_matrix, credit_matrix_product_line = calculate_loan_amount(
        application=application,
        loan_amount_requested=loan_amount,
        transaction_type=transaction_type,
        is_payment_point=is_payment_point,
        is_self_bank_account=loan_data['self_bank_account'],
    )

    # first month
    (
        principal_first,
        interest_first,
        installment_first,
    ) = compute_first_payment_installment_julo_one(
        loan_amount=loan_amount,
        loan_duration=loan_duration,
        monthly_interest_rate=credit_matrix.product.monthly_interest_rate,
        start_date=today_date,
        end_date=first_payment_date,
        is_zero_interest=loan_data.get('is_zero_interest', False),
    )
    # rest of months
    principal_rest, interest_rest, installment_rest = compute_payment_installment_julo_one(
        loan_amount=loan_amount,
        loan_duration_months=loan_duration,
        monthly_interest_rate=credit_matrix.product.monthly_interest_rate,
    )

    installment_amount = installment_rest if loan_duration > 1 else installment_first

    loan = Loan(
        loan_status=StatusLookup.objects.get(status_code=LoanStatusCodes.DRAFT),
        customer=application.customer,
        application_id2=application.id,
        account_id=loan_data['account_id'],
        product=credit_matrix.product,
        loan_amount=loan_amount,
        loan_duration=loan_duration,
        installment_amount=installment_amount,
        transaction_method_id=transaction_method_id,
    )

    assigned_lender = None

    channeling_loan_configs = get_channeling_loan_configuration()

    for lender in lenders:
        assigned_lender = lender
        lender_balance = LenderBalanceCurrent.objects.get_or_none(
            lender=lender, available_balance__gte=loan_amount
        )

        if lender_balance:
            channeling_type = bypass_daily_limit_threshold_config.parameters.get(lender.lender_name)

            if not channeling_type:
                assigned_lender = None
                continue

            is_valid_for_channeling_loan = check_pre_send_loan_for_channeling(
                loan, application, channeling_type, channeling_loan_configs[channeling_type]
            )

            if is_valid_for_channeling_loan:
                break
            else:
                logger.info(
                    {
                        'action': action,
                        'application_id': application.id,
                        'channeling_type': channeling_type,
                        'message': 'not pass criteria for channeling loan',
                    }
                )
                assigned_lender = None
                continue
        else:
            assigned_lender = None
            logger.info(
                {
                    'action': action,
                    'application_id': application.id,
                    'message': '{} lender balance insufficient'.format(lender.lender_name),
                }
            )

    logger.info(
        {
            'action': action,
            'application_id': application.id,
            'assigned_lender': assigned_lender,
            'message': 'finish check channeling eligibility bypass daily limit',
        }
    )

    return assigned_lender


def check_pre_send_loan_for_channeling(loan, application, channeling_type, channeling_loan_config):
    action = (
        'juloserver.channeling_loan.services.lender_services.check_pre_send_loan_for_channeling'
    )

    logger.info(
        {
            'action': action,
            'application_id': application.id,
            'channeling_type': channeling_type,
            'message': 'start check pre send loan for channeling',
        }
    )

    ineligible_conditions = get_general_channeling_ineligible_conditions(loan)
    for condition, is_met in ineligible_conditions.items():
        if is_met():
            message = condition.message
            logger.info(
                {
                    'action': action,
                    'application_id': application.id,
                    'message': message,
                }
            )
            return False

    if is_holdout_users_from_bss_channeling(application.id):
        message = "Exclude holdout users from bss channeling"
        logger.info(
            {
                'action': action,
                'application_id': application.id,
                'message': message,
            }
        )
        return False

    channeling_eligibility_status = get_channeling_eligibility_status(
        loan, channeling_type, channeling_loan_config
    )
    if not channeling_eligibility_status:
        message = "application not eligible"
        logger.info(
            {
                'action': action,
                'application_id': application.id,
                'channeling_type': channeling_type,
                'message': message,
            }
        )
        return False

    error = filter_field_channeling(application, channeling_type)
    if error:
        logger.info(
            {
                'action': action,
                'application_id': application.id,
                'channeling_type': channeling_type,
                'message': error,
            }
        )
        return False

    criteria_check_result, reason = loan_risk_acceptance_criteria_check(
        loan, channeling_type, channeling_loan_config
    )
    if not criteria_check_result:
        logger.info(
            {
                'action': action,
                'application_id': application.id,
                'channeling_type': channeling_type,
                'message': 'not pass loan rac',
                'reason': reason,
                'version': channeling_loan_config['force_update']['VERSION'],
            }
        )
        return False

    if channeling_type == ChannelingConst.SMF and application.creditscore.score not in ['A-', 'B+']:
        logger.info(
            {
                'action': action,
                'application_id': application.id,
                'channeling_type': channeling_type,
                'credit_score': application.creditscore.score,
                'message': 'not pass credit score criteria',
            }
        )
        return False

    logger.info(
        {
            'action': action,
            'application_id': application.id,
            'channeling_type': channeling_type,
            'message': 'success check pre send loan for channeling',
        }
    )

    return True
