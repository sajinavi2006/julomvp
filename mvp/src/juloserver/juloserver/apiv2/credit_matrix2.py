import logging
from builtins import str

from django.db.models import Q

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.constants import ScoreTag
from juloserver.julo.models import CreditMatrix, JobType
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes

logger = logging.getLogger(__name__)
messages = {
    'application_date_of_birth': (
        'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum memenuhi kriteria '
        'umur yang di tentukan.'
    ),
    'form_partial_location': 'Produk pinjaman lain belum tersedia di daerah Anda.',
    'form_partial_income': (
        'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum memenuhi kriteria '
        'pinjaman yang ada. Silakan coba kembali 6 bulan mendatang.'
    ),
    'saving_margin': (
        'Anda belum dapat mengajukan pinjaman untuk saat ini karena belum memenuhi kriteria '
        'pinjaman yang ada. Silakan coba kembali 6 bulan mendatang.'
    ),
    'fraud_form_partial_device': (
        'Anda belum dapat mengajukan pinjaman karena menggunakan HP yang sudah terdaftar. '
        'Silahkan login kembali menggunakan HP pribadi Anda.'
    ),
    'fraud_device': (
        'Anda belum dapat mengajukan pinjaman karena menggunakan HP yang sudah terdaftar. '
        'Silahkan login kembali menggunakan HP pribadi Anda.'
    ),
    'fraud_form_partial_hp_own': (
        'Anda belum dapat mengajukan pinjaman karena menggunakan nomor HP yang sudah terdaftar. '
        'Silahkan coba kembali menggunakan nomor HP pribadi Anda atau login menggunakan akun '
        'yang sudah terdaftar.'
    ),
    'not_meet_criteria': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
    'memenuhi kriteria pinjaman yang ada.',
    'A_minus_score': (
        'Poin kredit Anda sangat bagus. Peluang pengajuan Anda di-ACC besar! Silakan pilih '
        'salah satu produk pinjaman di bawah ini & selesaikan pengajuannya. Tinggal sedikit lagi!'
    ),
    'B_plus_score': (
        'Poin kredit Anda bagus. Peluang pengajuan Anda di-ACC cukup besar! Silakan pilih '
        'salah satu produk pinjaman di bawah ini & selesaikan pengajuannya. Tinggal sedikit lagi!'
    ),
    'B_minus_score': (
        'Peluang pengajuan Anda di-ACC cukup besar! Silakan pilih salah satu produk pinjaman '
        'di bawah ini & selesaikan pengajuannya. Tinggal sedikit lagi!'
    ),
    'grab_default': 'Pilih produk pinjaman Grab & selesaikan pengajuan. Pasti CAIR!',
    'scraped_data_existence': (
        'Terdapat kendala dalam proses registrasi Anda. Mohon verifikasi ulang data Anda dengan'
        ' menekan tombol di bawah ini.'
    ),
    'C_score_and_passed_binary_check': (
        'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum memenuhi kriteria'
        ' pinjaman yang ada. Tetapi Anda tetap dapat mengajukan pinjaman dengan pilihan'
        ' Julo Agunan'
    ),
    # Use this mes if want to disable CTL product
    # 'C_score_and_passed_binary_check': (
    #     'Anda belum dapat mengajukan pinjaman karena belum memenuhi kriteria'
    #     ' pinjaman. Mohon coba kembali dalam 3 bulan.'),
    'special_event': (
        'Mohon Maaf. Dalam situasi sulit ini, JULO belum bisa memenuhi pengajuan pinjaman '
        'untuk sementara waktu. Kami terus memantau perkembangan keadaan untuk dapat segera '
        'melayani Anda saat layanan kembali normal. Terima kasih untuk pengertiannya. '
        'Tetap sehat di rumah.'
    ),
    'loan_purpose_description_black_list': (
        'Mohon Maaf. Dalam situasi sulit ini JULO belum bisa memenuhi '
        'pengajuan pinjaman untuk sementara waktu. Kami terus memantau '
        'perkembangan keadaan untuk dapat segera melayani Anda saat layanan '
        'kembali normal. Terima kasih untuk pengertiannya. Tetap sehat di rumah.'
    ),
    'known_fraud': ('known as fraudster'),
    'fraud_email': ('the email has been used'),
    'fraud_ktp': ('the ktp has been used'),
}

product_lines_default = [ProductLineCodes.CTL1]
# product_lines_default = []

non_grab_checks = {
    'application_date_of_birth': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['application_date_of_birth'],
    },
    'job_not_black_listed': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['not_meet_criteria'],
    },
    'form_partial_location': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['form_partial_location'],
    },
    'scraped_data_existence': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['scraped_data_existence'],
    },
    'form_partial_income': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['form_partial_income'],
    },
    'saving_margin': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['saving_margin'],
    },
    'fraud_form_partial_device': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['fraud_form_partial_device'],
    },
    'fraud_device': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['fraud_device'],
    },
    'fraud_form_partial_hp_own': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['fraud_form_partial_hp_own'],
    },
    'fraud_form_partial_hp_kin': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['not_meet_criteria'],
    },
    'fraud_hp_spouse': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['not_meet_criteria'],
    },
    'email_delinquency_24_months': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['not_meet_criteria'],
    },
    'sms_delinquency_24_months': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['not_meet_criteria'],
    },
    'long_form_binary_checks': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['not_meet_criteria'],
    },
    'loan_purpose_description_black_list': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['loan_purpose_description_black_list'],
    },
    'special_event': {
        'score': '--',
        'product_lines': product_lines_default,
        'message': messages['special_event'],
    },
    'fdc_inquiry_check': {
        'score': '--',
        'product_lines': product_lines_default,
        'message': messages['special_event'],
    },
    'monthly_income': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['not_meet_criteria'],
    },
    'known_fraud': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['known_fraud'],
    },
    'fraud_email': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['fraud_email'],
    },
    'fraud_ktp': {
        'score': 'C',
        'product_lines': product_lines_default,
        'message': messages['fraud_ktp'],
    },
}


def get_salaried(job_type):
    get_job_type = JobType.objects.get_or_none(job_type=job_type)

    if not get_job_type:
        return False

    return get_job_type.is_salaried


def get_credit_matrix(parameters):
    from juloserver.apiv2.services import queryset_custom_matrix_processing

    parameter_dict_custom = dict()

    if 'id' in parameters:
        if parameters['id']:
            credit_matrix = CreditMatrix.objects.get_or_none(pk=parameters['id'])
            if credit_matrix:
                return credit_matrix
        parameters.pop('id', None)

    if 'job_type' in parameters:
        parameters['is_salaried'] = get_salaried(parameters['job_type'])
        parameters.pop('job_type', None)

    if 'score' in parameters:
        if parameters['score'] == 'C' or not parameters.get('score_tag'):
            parameters.pop('score_tag', None)

    if 'job_industry' in parameters:
        parameter_dict_custom['job_industry'] = (
            str(parameters.pop('job_industry')).replace(' ', '').lower()
        )

    if 'repeat_time' in parameters:
        parameter_dict_custom['repeat_time'] = parameters.pop('repeat_time')

    query_set = CreditMatrix.objects.filter(**parameters)
    query_set, is_custom_matrix = queryset_custom_matrix_processing(
        query_set, parameter_dict_custom
    )
    query_set = query_set.extra(select={'version_is_null': 'version IS NULL'})

    if is_custom_matrix:
        return_value = query_set.order_by(
            'version_is_null', '-version', 'priority', '-max_threshold'
        ).first()
    else:
        query_set = query_set.filter(Q(parameter__isnull=True) | Q(parameter=u''))
        return_value = query_set.order_by('version_is_null', '-version', '-max_threshold').first()

    return return_value


def get_good_score(
    probabilty,
    job_type,
    custom_matrix_parameters,
    is_premium_area,
    is_fdc,
    credit_matrix_type="julo"
):
    credit_matrix_parameters = dict(
        min_threshold__lte=probabilty,
        max_threshold__gte=probabilty,
        is_premium_area=is_premium_area,
        credit_matrix_type=credit_matrix_type,
        job_type=job_type,
        is_fdc=is_fdc,
    )
    for key, value in list(custom_matrix_parameters.items()):
        credit_matrix_parameters[key] = value
    credit_matrix = get_credit_matrix(credit_matrix_parameters)

    if credit_matrix:
        return (
            credit_matrix.score,
            credit_matrix.list_product_lines,
            credit_matrix.message,
            credit_matrix.score_tag,
            credit_matrix.version,
            credit_matrix.id,
        )

    logger.error(
        {
            'action_view': 'get_good_score',
            'probabilty': probabilty,
            'errors': "get good score from hard-code",
        }
    )

    credit_matrix_low_score = CreditMatrix.objects.get_current_matrix(
        'C', ScoreTag.C_LOW_CREDIT_SCORE
    )
    matrix_id, version = (
        (credit_matrix_low_score.id, credit_matrix_low_score.version)
        if credit_matrix_low_score
        else (None, None)
    )

    return (
        'C',
        product_lines_default,
        messages['C_score_and_passed_binary_check'],
        ScoreTag.C_LOW_CREDIT_SCORE,
        version,
        matrix_id,
    )


def get_score_product(credit_score, credit_matrix_type, product_line, job_type):
    credit_matrix_parameters = dict(
        is_premium_area=credit_score.inside_premium_area,
        score=credit_score.score,
        credit_matrix_type=credit_matrix_type,
        job_type=job_type,
        score_tag=credit_score.score_tag,
        version=credit_score.credit_matrix_version,
        id=credit_score.credit_matrix_id,
    )
    credit_matrix = get_credit_matrix(credit_matrix_parameters)

    if credit_matrix:
        return credit_matrix.product_lines.filter(product=product_line).first()

    return None


def get_score_rate(credit_score, credit_matrix_type, product_line, rate, job_type):
    score_product = get_score_product(credit_score, credit_matrix_type, product_line, job_type)
    if score_product:
        return score_product.interest
    return rate


credit_score_rules2 = {
    # Partner None which means Julo
    None: {'checks': non_grab_checks, 'bypass_checks': []},
    PartnerConstant.TOKOPEDIA_PARTNER: {'checks': non_grab_checks, 'bypass_checks': []},
    PartnerConstant.DOKU_PARTNER: {'checks': non_grab_checks, 'bypass_checks': []},
    PartnerConstant.GRAB_PARTNER: {
        'checks': {
            'application_date_of_birth': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': messages['grab_default'],
            },
            'job_not_black_listed': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': messages['grab_default'],
            },
            'form_partial_location': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': messages['grab_default'],
            },
            'scraped_data_existence': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': messages['grab_default'],
            },
            'form_partial_income': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': messages['grab_default'],
            },
            'saving_margin': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': messages['grab_default'],
            },
            'fraud_form_partial_device': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': messages['grab_default'],
            },
            'fraud_device': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': messages['grab_default'],
            },
            'fraud_form_partial_hp_own': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': messages['grab_default'],
            },
            'fraud_form_partial_hp_kin': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': messages['grab_default'],
            },
            'fraud_hp_spouse': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': messages['grab_default'],
            },
            'email_delinquency_24_months': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': messages['grab_default'],
            },
            'sms_delinquency_24_months': {
                'score': 'C',
                'product_lines': [ProductLineCodes.GRAB1],
                'message': messages['grab_default'],
            },
        },
        'bypass_checks': ['application_date_of_birth', 'form_partial_location'],
    },
    PartnerConstant.GRAB_FOOD_PARTNER: {
        'checks': non_grab_checks,
        'bypass_checks': [
            'application_date_of_birth',
            'form_partial_location',
            'job_not_black_listed',
        ],
    },
    PartnerConstant.BRI_PARTNER: {'checks': non_grab_checks, 'bypass_checks': []},
    PartnerConstant.ATURDUIT_PARTNER: {'checks': non_grab_checks, 'bypass_checks': []},
    PartnerConstant.LAKU6_PARTNER: {'checks': non_grab_checks, 'bypass_checks': []},
    PartnerConstant.PEDE_PARTNER: {'checks': non_grab_checks, 'bypass_checks': []},
    PartnerConstant.ICARE_PARTNER: {'checks': non_grab_checks, 'bypass_checks': []},
    PartnerConstant.AXIATA_PARTNER: {'checks': non_grab_checks, 'bypass_checks': []},
    PartnerNameConstant.GENERIC: {
        'checks': non_grab_checks,
        'bypass_checks': [
            'long_form_binary_checks',
            'fraud_hp_spouse',
            'fraud_device',
            'fraud_form_partial_device',
            'saving_margin',
            'scraped_data_existence',
        ],
    },
}
