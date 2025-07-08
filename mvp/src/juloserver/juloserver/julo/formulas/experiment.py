import logging
from typing import Tuple

from ..constants import BypassITIExperimentConst, ExperimentConst
from ..models import ExperimentSetting, Application, AffordabilityHistory
from juloserver.apiv2.models import PdIncomeTrustModelResult, PdAffordabilityModelResult, PdIncomeModelResult
from juloserver.julo.models import MarginOfError
from juloserver.julo.formulas.covid19 import compute_affordability_covid19_adjusted
from juloserver.application_flow.services import JuloOneService

logger = logging.getLogger(__name__)

RATE_DTI = BypassITIExperimentConst.RATE_DTI
RATE_TIER1_MAE = BypassITIExperimentConst.RATE_TIER1_MAE
RATE_TIER2_MAE = BypassITIExperimentConst.RATE_TIER2_MAE
RATE_TIER3_MAE = BypassITIExperimentConst.RATE_TIER3_MAE
RATE_TIER4_MAE = BypassITIExperimentConst.RATE_TIER4_MAE
RATE_TIER5_MAE = BypassITIExperimentConst.RATE_TIER5_MAE
TIER1_MAE_WEIGHT = BypassITIExperimentConst.TIER1_MAE_WEIGHT
TIER2_MAE_WEIGHT = BypassITIExperimentConst.TIER2_MAE_WEIGHT
TIER3_MAE_WEIGHT = BypassITIExperimentConst.TIER3_MAE_WEIGHT
TIER4_MAE_WEIGHT = BypassITIExperimentConst.TIER4_MAE_WEIGHT
TIER5_MAE_WEIGHT = BypassITIExperimentConst.TIER5_MAE_WEIGHT

MIN_EXPENSE_AMOUNT = BypassITIExperimentConst.MIN_EXPENSE_AMOUNT
MAX_LOAN_DURATION_OFFER = BypassITIExperimentConst.MAX_LOAN_DURATION_OFFER

ITI_LOW_THRESHOLD = ExperimentConst.ITI_LOW_THRESHOLD


def calculation_affordability(application_id: int, monthly_income: int, monthly_housing_cost: int,
                              monthly_expenses: int, total_current_debt: int, iti_low: bool = False
                              ) -> Tuple[float, float]:
    """
    Calculate customer's affordability based on factors provided in the parameter.

    Args:
        application_id (int): Application.id.
        monthly_income (int): Application.monthly_income.
        monthly_housing_cost (int): Application.monthly_housing_cost.
        monthly_expenses (int): Application.monthly_expenses.
        total_current_debt (int): Application.total_current_debt.
        iti_low (bool):

    Returns:
        (float): Returns affordability calculation.
        (float): Returns income margin of error based on ana calculation.
    """
    affordability = 0
    income_modified = calculate_mae_modified_income(application_id, monthly_income, iti_low)
    if not income_modified:
        return affordability, monthly_income

    expense_modified = calculate_modified_expense(monthly_housing_cost, monthly_expenses, total_current_debt)
    savings_margin = income_modified - expense_modified
    affordability = min(RATE_DTI * income_modified, savings_margin)

    affordability = compute_affordability_covid19_adjusted(affordability)

    affordability_type = 'ITI Affordability' if not iti_low else 'Low threshold ITI Affordability'
    app_obj = Application.objects.get_or_none(pk=application_id)
    julo_one_service = JuloOneService()
    reason = julo_one_service.get_reason_affordability(app_obj)
    AffordabilityHistory.objects.create(
        application_id=app_obj.id,
        application_status=app_obj.application_status,
        affordability_value=affordability,
        affordability_type=affordability_type,
        reason=reason
    )

    logger.info({
        'action': "calculation_affordability",
        'application_id': application_id,
        'monthly_income': monthly_income,
        'income_modified': income_modified,
        'expense_modified': expense_modified,
        'savings_margin': savings_margin,
        'affordability': affordability
    })

    return affordability, income_modified


def calculate_modified_income(application_id, monthly_income):
    # itiv5 applied
    income_modified = 0
    iti_result = PdIncomeTrustModelResult.objects.filter(application_id=application_id).last()
    if iti_result:
        adjusted_income = iti_result.predicted_income
        if adjusted_income < monthly_income :
            income_modified = adjusted_income
        else:
            income_modified = monthly_income
    return income_modified

def calculate_mae_modified_income(application_id, monthly_income, iti_low=False):
    # itiv8 applied
    income_modified = 0
    iti_result = PdIncomeTrustModelResult.objects.filter(application_id=application_id).last()
    if iti_result:
        adjusted_income = iti_result.value
        margin_of_error = MarginOfError.objects.filter(
            min_threshold__lte=monthly_income,
            max_threshold__gt=monthly_income,
        ).order_by('-max_threshold').first()

        MAE = margin_of_error.mae

        if iti_low:
            experiment_iti_low = ExperimentSetting.objects.get_or_none(
                code=ITI_LOW_THRESHOLD,
                is_active=True)

            MAE = iti_result.mae * experiment_iti_low.criteria['n_mae']

        income_modified = adjusted_income - MAE
    return min(monthly_income, income_modified)

def calculate_modified_expense(monthly_housing_cost, monthly_expenses, total_current_debt):
    expense_modified = MIN_EXPENSE_AMOUNT
    expense = monthly_housing_cost + monthly_expenses + total_current_debt
    expense_modified = max(expense_modified, expense)
    return expense_modified

def get_amount_and_duration_by_affordability_stl(affordability, loan_amount_request):
    loan_duration_offer = 1
    loan_amount_offer = None
    if affordability >= 550000 and loan_amount_request == 500000:
        loan_amount_offer = 500000
    elif affordability >= 1100000 and loan_amount_request == 1000000:
        loan_amount_offer = 1000000
    elif 990000 <= affordability < 1100000 and loan_amount_request == 1000000:
        loan_amount_offer = 900000
    elif 880000 <= affordability < 990000 and loan_amount_request == 1000000:
        loan_amount_offer = 800000
    elif 770000 <= affordability < 880000 and loan_amount_request == 1000000:
        loan_amount_offer = 700000
    elif 660000 <= affordability < 770000 and loan_amount_request == 1000000:
        loan_amount_offer = 600000
    elif 550000 <= affordability < 660000 and loan_amount_request == 1000000:
        loan_amount_offer = 500000
    return loan_amount_offer, loan_duration_offer

def get_amount_and_duration_by_affordability_mtl(affordability, loan_amount_request):
    loan_duration_offer = MAX_LOAN_DURATION_OFFER
    loan_amount_offer = None
    if 540000 <= affordability < 580000:
        loan_amount_offer = 1500000
    elif 580000 <= affordability < 725000 and loan_amount_request <= 2000000:
        loan_amount_offer = loan_amount_request
    elif 580000 <= affordability < 725000 and loan_amount_request > 2000000:
        loan_amount_offer = 2000000
    elif 725000 <= affordability < 870000 and loan_amount_request <= 2500000:
        loan_amount_offer = loan_amount_request
    elif 725000 <= affordability < 870000 and loan_amount_request > 2500000:
        loan_amount_offer = 2500000
    elif 870000 <= affordability < 1015000 and loan_amount_request <= 3000000:
        loan_amount_offer = loan_amount_request
    elif 870000 <= affordability < 1015000 and loan_amount_request > 3000000:
        loan_amount_offer = 3000000
    elif 1015000 <= affordability < 1160000 and loan_amount_request <= 3500000:
        loan_amount_offer = loan_amount_request
    elif 1015000 <= affordability < 1160000 and loan_amount_request > 3500000:
        loan_amount_offer = 3500000
    elif 1160000 <= affordability < 1305000 and loan_amount_request <= 4000000:
        loan_amount_offer = loan_amount_request
    elif 1160000 <= affordability < 1305000 and loan_amount_request > 4000000:
        loan_amount_offer = 4000000
    elif 1305000 <= affordability < 1450000 and loan_amount_request <= 4500000:
        loan_amount_offer = loan_amount_request
    elif 1305000 <= affordability < 1450000 and loan_amount_request > 4500000:
        loan_amount_offer = 4500000
    elif 1450000 <= affordability < 1595000 and loan_amount_request <= 5000000:
        loan_amount_offer = loan_amount_request
    elif 1450000 <= affordability < 1595000 and loan_amount_request > 5000000:
        loan_amount_offer = 5000000
    elif 1595000 <= affordability < 1740000 and loan_amount_request <= 5500000:
        loan_amount_offer = loan_amount_request
    elif 1595000 <= affordability < 1740000 and loan_amount_request > 5500000:
        loan_amount_offer = 5500000
    elif affordability >= 1740000 and loan_amount_request <= 6000000:
        loan_amount_offer = loan_amount_request
    elif affordability >= 1740000 and loan_amount_request > 6000000:
        loan_amount_offer = 6000000
    return loan_amount_offer, loan_duration_offer


def calculation_affordability_based_on_affordability_model(application,
                                                           is_with_affordability_value=False):
    pd_affordability_model_result = PdAffordabilityModelResult.objects.filter(application=application).last()
    if not pd_affordability_model_result:
        if is_with_affordability_value:
            return False, 0

        return False

    from juloserver.julo.formulas.underwriting import compute_affordable_payment

    julo_one_service = JuloOneService()
    input_params = julo_one_service.construct_params_for_affordability(application)
    affordability_result = compute_affordable_payment(**input_params)
    affordability_value = affordability_result['affordable_payment']

    if affordability_value < 300000:
        if is_with_affordability_value:
            return False, 0

        return False

    iqr_lower_bound = pd_affordability_model_result.iqr_lower_bound
    iqr_upper_bound = pd_affordability_model_result.iqr_upper_bound

    pd_income_model_result = PdIncomeModelResult.objects.filter(application_id=application.id).last()

    if pd_income_model_result.is_active:
        affordability_type = pd_income_model_result.model_version
        lookup_affordability = predicted_affordability = pd_income_model_result.income_value_adjusted
        affordability_history = AffordabilityHistory.objects.filter(application=application)
        affordability_history.update(
            affordability_value=lookup_affordability,
            affordability_type=affordability_type,
        )
    else:
        affordability_type = affordability_result['affordability_type']
        lookup_affordability = predicted_affordability = affordability_value

    logger.info({
        'action': "calculation_affordability_based_on_affordability_model",
        'application_id': application.id,
        'model_version': affordability_type,
        'lookup_affordability': lookup_affordability,
        'predicted_affordability': predicted_affordability,
        'iqr_lower_bound': iqr_lower_bound,
        'iqr_upper_bound': iqr_upper_bound,
    })

    if iqr_lower_bound <= predicted_affordability <= iqr_upper_bound and predicted_affordability > 0:
        if is_with_affordability_value:
            return True, lookup_affordability
        return True
    else:
        if is_with_affordability_value:
            return False, 0
        return False