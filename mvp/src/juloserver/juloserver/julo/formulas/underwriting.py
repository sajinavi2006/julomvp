import logging
from builtins import str
from unittest import result

from django.utils import timezone

from juloserver.application_flow.services import JuloOneService
from juloserver.julo.constants import Affordability, ExperimentConst
from juloserver.julo.formulas.covid19 import compute_affordability_covid19_adjusted
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.apiv2.models import PdIncomeModelResult

from ..exceptions import JuloException
from ..models import AffordabilityHistory, Application, ExperimentSetting
from ..product_lines import ProductLineCodes

logger = logging.getLogger(__name__)


class UnderwritingCalculationError(JuloException):
    pass


def compute_affordable_payment(**params):

    logger.info(params)

    application_id = params['application_id']
    results = compute_and_get_affordable_payment(**params)

    if 'application' in params:
        app_obj = params['application']
    else:
        app_obj = Application.objects.get_or_none(pk=application_id)

    julo_one_service = JuloOneService()
    reason = julo_one_service.get_reason_affordability(app_obj)

    AffordabilityHistory.objects.create(
        application_id=app_obj.id,
        application_status=app_obj.application_status,
        affordability_value=results['affordable_payment'],
        affordability_type=results['affordability_type'],
        reason=reason,
    )

    logger.info({**results,})

    return results


################################################################################


def compute_work_tenure_adjustment(
        application_xid, product_line_code, job_start_date, job_end_date=None, ):

    # calculation_affordability_group_b
    # Remove dependent expense variable and work tenure adjustment in affordability calculation
    # All application_id with last id (6,7,8,9)
    setting = ExperimentSetting.objects.get_or_none(code=ExperimentConst.AFFORDABILITY_130_CALCULATION_TENURE,
                                                    is_active=True)

    if not job_end_date:
        job_end_date = timezone.localtime(timezone.now()).date()

    if not job_start_date:
        job_start_date = timezone.localtime(timezone.now()).date()

    work_tenure_month = float((job_end_date - job_start_date).days) / 30

    half_year_tenure = 6
    full_year_tenure = 12
    if setting:
        adjustment = setting.start_date <= timezone.now() <= setting.end_date
        if adjustment:
            application_xid_str = str(application_xid)
            last_application_xid = int(application_xid_str[-2])
            if last_application_xid in setting.criteria['b_group_second_last_app_xid']:
                return {"work_tenure": 1.0,
                        "affordability_type": Affordability.AFFORDABILITY_TYPE_1_TENURE}
            elif last_application_xid in setting.criteria['c_group_second_last_app_xid']:
                if work_tenure_month <= half_year_tenure:
                    return {"work_tenure": 0.9,
                            "affordability_type": Affordability.AFFORDABILITY_TYPE_2_TENURE}
                if work_tenure_month >= half_year_tenure:
                    return {"work_tenure": 1.0,
                            "affordability_type": Affordability.AFFORDABILITY_TYPE_2_TENURE}

    if product_line_code in ProductLineCodes.stl():
        return {"work_tenure": 1.0,
                "affordability_type": Affordability.AFFORDABILITY_TYPE}

    if work_tenure_month <= half_year_tenure:
        return {"work_tenure": 0.8,
                "affordability_type": Affordability.AFFORDABILITY_TYPE}
    if work_tenure_month <= full_year_tenure:
        return {"work_tenure": 0.9,
                "affordability_type": Affordability.AFFORDABILITY_TYPE}
    # tenure longer than a year
    return {"work_tenure": 1.0,
            "affordability_type": Affordability.AFFORDABILITY_TYPE}


def compute_job_adjustment(job_type):
    job_type_adjustment_mappings = [
        {
            'types': ['Pegawai negeri', 'Pegawai swasta'],
            'adjustment': 1.0
        },
        {
            'types': ['Pengusaha', 'Pekerja rumah tangga'],
            'adjustment': 0.9
        },
        {
            'types': [
                'Freelance', 'Lainnya', 'Tidak bekerja', 'Ibu rumah tangga', 'Staf rumah tangga', 'Mahasiswa'],
            'adjustment': 0.8
        },
    ]
    job_adjustment = None
    for mapping in job_type_adjustment_mappings:
        if job_type in mapping['types']:
            job_adjustment = mapping['adjustment']

    if not job_adjustment:
        raise UnderwritingCalculationError("job_type=%s unknown" % job_type)

    return job_adjustment


def compute_total_adjusted_income(
        monthly_income, work_tenure_adjustment, job_adjustment):
    total_income_adjust = float(monthly_income) * work_tenure_adjustment * job_adjustment
    return total_income_adjust


################################################################################


def compute_dependents_expense(application_xid, product_line_code, dependent_count):

    if product_line_code in ProductLineCodes.stl():
        return 0

    # calculation_affordability_group_b
    # Remove only dependent expense variable in affordability calculation
    # All application_id with last id (0, 1, 2, 3, 4)
    # calculation_affordability_group_c
    # Remove dependent expense variable and work tenure adjustment in affordability calculation
    # All application_id with last id (5, 6, 7, 8, 9)
    setting = ExperimentSetting.objects.get_or_none(code=ExperimentConst.AFFORDABILITY_130_CALCULATION_TENURE,
                                                    is_active=True)
    if setting:
        adjustment = setting.start_date <= timezone.now() <= setting.end_date
        group_application_xid = setting.criteria['b_group_second_last_app_xid'] + setting.criteria[
            'c_group_second_last_app_xid']
        if adjustment:
            application_xid_str = str(application_xid)
            last_application_xid = int(application_xid_str[-2])
            if last_application_xid in group_application_xid:
                return 0

    buffer_per_dependent = 150000
    if not dependent_count:
        dependent_count = 0
    return (dependent_count + 1) * buffer_per_dependent


def compute_total_adjusted_expense(
        monthly_expense, monthly_housing_cost, undisclosed_expense, dependent_expense):
    if not monthly_expense:
        monthly_expense = 0
    if not monthly_housing_cost:
        monthly_housing_cost = 0
    if not undisclosed_expense:
        undisclosed_expense = 0
    if not dependent_expense:
        dependent_expense = 0

    return sum([
        monthly_expense,
        monthly_housing_cost,
        undisclosed_expense,
        dependent_expense
    ])


################################################################################


def compute_max_afford_simple(total_adj_income, total_adj_expense):
    max_affordable = total_adj_income - total_adj_expense
    return max_affordable


def calculate_dti_multiplier(product_line_code):
    # DTI = Debt to Income Ratio
    if product_line_code in \
            ProductLineCodes.mtl() + ProductLineCodes.pedemtl() + ProductLineCodes.julo_one():
        return 0.3
    if product_line_code in ProductLineCodes.merchant_financing():
        # Joey'said from growth team, DTI for merchant financing is 0
        return 0
    if product_line_code in ProductLineCodes.stl() + ProductLineCodes.pedestl():
        return 0.4
    if product_line_code in ProductLineCodes.bri():
        return 0.3
    if product_line_code in ProductLineCodes.grab():
        return 0.4
    if product_line_code in ProductLineCodes.loc():
        return 0.4
    if product_line_code in ProductLineCodes.grabfood():
        return 0.4
    if product_line_code in ProductLineCodes.employee_financing():
        return 0
    raise UnderwritingCalculationError(
        "Unexpected product_line_code=%s" % product_line_code)


def compute_max_affordable_dti(product_line_code, total_adjusted_income):
    max_allowable_dti = calculate_dti_multiplier(product_line_code)
    max_affordable_dti = total_adjusted_income * max_allowable_dti
    return max_affordable_dti


################################################################################


def compute_and_get_affordable_payment(**params):
    # Compute total adjusted income
    product_line_code = params['product_line_code']
    job_start_date = params['job_start_date']
    job_end_date = params['job_end_date']

    application_xid = params['application_xid']
    work_tenure_adjustment = compute_work_tenure_adjustment(
        application_xid, product_line_code, job_start_date, job_end_date=job_end_date)
    affordability_type = work_tenure_adjustment["affordability_type"]

    job_type = params['job_type']
    job_adjustment = compute_job_adjustment(job_type)

    monthly_income = params['monthly_income']
    total_adjusted_income = compute_total_adjusted_income(
        monthly_income, work_tenure_adjustment["work_tenure"], job_adjustment)

    # Compute total adjusted expense
    dependent_count = params['dependent_count']
    dependent_expense = compute_dependents_expense(application_xid, product_line_code, dependent_count)

    monthly_expense = params['monthly_expense']
    monthly_housing_cost = params['monthly_housing_cost']
    undisclosed_expense = params['undisclosed_expense']
    total_adjusted_expense = compute_total_adjusted_expense(
        monthly_expense, monthly_housing_cost, undisclosed_expense, dependent_expense)

    # Compute affordable payment
    max_affordable_simple = compute_max_afford_simple(
        total_adjusted_income, total_adjusted_expense)
    max_affordable_dti = compute_max_affordable_dti(
        product_line_code, total_adjusted_income)
    affordable_payment = min([max_affordable_simple, max_affordable_dti])

    affordable_payment = compute_affordability_covid19_adjusted(affordable_payment)

    return {
        'work_tenure_adjustment': work_tenure_adjustment["work_tenure"],
        'job_adjustment': job_adjustment,
        'total_adjusted_income': total_adjusted_income,
        'monthly_income': monthly_income,
        'dependent_expense': dependent_expense,
        'total_adjusted_expense': total_adjusted_expense,
        'max_affordable_simple': max_affordable_simple,
        'max_affordable_dti': max_affordable_dti,
        'affordable_payment': affordable_payment,
        'other_income_adjustment': 0.00,
        'affordability_type': affordability_type,
    }
