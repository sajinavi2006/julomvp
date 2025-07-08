from juloserver.apiv1.dropdown.jobs import JobDropDown
from juloserver.julo.models import ProductProfile


def get_job_list(jobs_data):
    job_industry_list = []
    job_description_list = []

    for index, data in enumerate(jobs_data):
        job_industry, job_description = data.split(',')
        if job_industry not in job_industry_list:
            job_industry_list.append(job_industry)
        if job_description not in job_description_list:
            job_description_list.append(job_description)

    return (job_industry_list, job_description_list)


JOB_INDUSTRY_CHOICES, JOB_DESCRIPTION_CHOICES = get_job_list(JobDropDown.DATA)

JOB_FUNCTION_CHOICES = [
    'Marketing',
    'HRD',
    'Keuangan',
    'Keamanan'
]

JOB_TYPE_CHOICES = [
    'Pegawai swasta',
    'Pegawai negeri',
    'Pengusaha',
    'Freelance',
    'Pekerja rumah tangga',
    'Lainnya',
    'Staf rumah tangga',
    'Ibu rumah tangga',
    'Mahasiswa',
    'Tidak bekerja',
]

CREDIT_SCORE_CHOICES = [
    'A-',
    'B+',
    'B-',
    'C'
]

CREDIT_SCORE_CHOICES_EXCLUDE_C = [
    'A-',
    'B+',
    'B-'
]

MTL_STL_PRODUCT = [
    'MTL1',
    'MTL2',
    'STL1',
    'STL2'
]

JULO_GRAB_PRODUCT = [
    'MTL1',
    'MTL2',
    'STL1',
    'STL2',
    'J1',
    'GRAB1',
    'GRAB2',
    'GRAB',
    'J-STARTER',
]

PAYMENT_FREQUENCY_CHOICES = [freq[0] for freq in ProductProfile.PAYMENT_FREQ_CHOICES]

FIELDS_MAP = {
    'code': str,
    'name': str,
    'payment_frequency': str,
    'min_amount': int,
    'max_amount': int,
    'min_duration': int,
    'max_duration': int,
    'min_interest_rate': float,
    'max_interest_rate': float,
    'interest_rate_increment': float,
    'min_origination_fee': float,
    'max_origination_fee': float,
    'origination_fee_increment': float,
    'late_fee': float,
    'min_late_fee': float,
    'max_late_fee': float,
    'cashback_initial': float,
    'min_cashback_initial': float,
    'max_cashback_initial': float,
    'cashback_payment': float,
    'min_cashback_payment': float,
    'max_cashback_payment': float,
    'min_age': int,
    'max_age': int,
    'min_income': int,
    'max_income': int,
    'debt_income_ratio': float,
    'location': list,
    'job_type': list,
    'job_industry': list,
    'job_description': list,
    'credit_score': list,
    'is_initial': bool,
    'is_active': bool,
    'is_product_exclusive': bool
}


def get_choices_list(type):
    choices = []
    lists = None
    if type == "job_type":
        lists = JOB_TYPE_CHOICES

    elif type == "job_industry":
        lists = JOB_INDUSTRY_CHOICES

    elif type == "credit_score":
        lists = CREDIT_SCORE_CHOICES

    elif type == "product_list":
        return ProductProfile.objects.filter(
            name__in=JULO_GRAB_PRODUCT
        ).values_list('id', 'name')

    for data in lists:
        choices.append([data, data])

    return choices


class ProductProfileCode():
    EMPLOYEE_FINANCING = '500'
