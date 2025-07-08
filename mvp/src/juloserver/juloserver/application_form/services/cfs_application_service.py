import logging

from juloserver.account.models import CreditLimitGeneration
from juloserver.application_flow.services import JuloOneService
from juloserver.julo.constants import Affordability
from juloserver.julo.formulas.underwriting import compute_and_get_affordable_payment
from juloserver.julo.models import (
    AffordabilityHistory,
    ApplicationFieldChange,
)


logger = logging.getLogger(__name__)


def update_application_monthly_income(application, agent, new_monthly_income):
    old_monthly_income = application.monthly_income
    if new_monthly_income <= old_monthly_income:
        return False

    application.update_safely(monthly_income=new_monthly_income)
    ApplicationFieldChange.objects.create(
        application=application,
        field_name='monthly_income',
        old_value=old_monthly_income,
        new_value=new_monthly_income,
        agent=agent,
    )
    return True


def update_affordability(application, new_monthly_income):
    # Calc new affordability
    julo_one_service = JuloOneService()
    input_params = julo_one_service.construct_params_for_affordability(application)
    input_params['monthly_income'] = new_monthly_income

    log_params = {**input_params}
    log_params.pop('application')
    job_start_date, job_end_date = log_params['job_start_date'], log_params['job_end_date']
    logger.info({
        'action': 'update_affordability_compute_and_get_affordable_payment_before',
        'params': {
            **log_params,
            'job_start_date': job_start_date and job_start_date.strftime('%d-%m-%Y'),
            'job_end_date': job_end_date and job_end_date.strftime('%d-%m-%Y'),
        }
    })

    new_affordable_results = compute_and_get_affordable_payment(**input_params)
    new_max_affordable = new_affordable_results['max_affordable_simple']
    new_max_affordable_dti = new_affordable_results['max_affordable_dti']
    new_affordability_value = new_affordable_results['affordable_payment']

    credit_limit_generation = (
        CreditLimitGeneration.objects.select_related('affordability_history')
        .filter(application=application)
        .last()
    )

    old_affordability_history = (
        credit_limit_generation.affordability_history
        if credit_limit_generation
        else None
    )

    if (
        old_affordability_history
        and old_affordability_history.affordability_value >= new_affordability_value
    ):
        return None

    affordability_type = (
        Affordability.MONTHLY_INCOME_DTI
        if new_max_affordable > new_max_affordable_dti
        else Affordability.MONTHLY_INCOME_NEW_AFFORDABILITY
    )

    new_affordability_history = AffordabilityHistory(
        application_id=application.id,
        application_status=application.application_status,
        affordability_value=new_affordable_results['affordable_payment'],
        affordability_type=affordability_type,
        reason=Affordability.REASON['auto_update_affordability'],
    )
    new_affordability_history.save()

    logger.info({
        'action': 'update_affordability_compute_and_get_affordable_payment_after',
        'params': {
            'application_id': application.id,
            **new_affordable_results
        }
    })

    return new_affordability_history
