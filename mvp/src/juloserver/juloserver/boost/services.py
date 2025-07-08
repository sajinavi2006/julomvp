from juloserver.apiv2.credit_matrix2 import messages
from juloserver.application_flow.services import JuloOneService
from juloserver.julo.exceptions import ApplicationNotFound
from juloserver.julo.models import (
    Application,
    CreditScore,
    Image,
    MobileFeatureSetting,
    Skiptrace,
)
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.sdk.serializers import ImageSerializer

from . import get_scapper_client
from .constants import BoostBankConst, BoostBPJSConst
from juloserver.julolog.julolog import JuloLog
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.pii_vault.constants import PiiSource

logger = JuloLog(__name__)


def get_boost_status(application_id, workflow_name=None):

    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        raise ApplicationNotFound()

    detokenized_application = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [{'customer_xid': application.customer.customer_xid, 'object': application}],
        force_get_local_data=True,
    )
    application = detokenized_application[0]

    boost_status = dict()
    boost_status["additional_contact_1_number"] = application.additional_contact_1_number
    boost_status["additional_contact_2_number"] = application.additional_contact_2_number
    boost_status["additional_contact_1_name"] = application.additional_contact_1_name
    boost_status["additional_contact_2_name"] = application.additional_contact_2_name
    boost_status["loan_purpose_desc"] = application.loan_purpose_desc
    boost_status[
        "loan_purpose_description_expanded"
    ] = application.loan_purpose_description_expanded

    boost_settings = get_boost_mobile_feature_settings()
    if not boost_settings:
        return
    bank_settings = boost_settings.parameters['bank']
    if bank_settings['is_active']:
        julo_scraper_client = get_scapper_client()
        bank_statuses = julo_scraper_client.get_bank_scraping_status(application_id)
        mapped_bank_statuses = show_bank_status(bank_statuses, workflow_name)
        boost_status.update(mapped_bank_statuses)

    bpjs_status = show_bpjs_status(application=application, workflow_name=workflow_name)
    boost_status.update(bpjs_status)

    return boost_status


def check_scrapped_bank(application):
    """
    check at least a bank scrape data is done
    """
    return False

    # julo_scraper_client = get_scapper_client()
    # bank_statuses = julo_scraper_client.get_bank_scraping_status(application.id)
    # boost_settings = get_boost_mobile_feature_settings()
    # if not boost_settings:
    #     return False
    # bank_settings = boost_settings.parameters['bank']
    # if not bank_settings['is_active']:
    #     return False
    # valid_banks = []
    # for bank_name, bank_feature_status in list(bank_settings.items()):
    #     if bank_name == 'is_active':
    #         continue
    #     if bank_feature_status['is_active']:
    #         valid_banks.append(bank_name)
    #
    # for bank, status in list(bank_statuses.items()):
    #     if bank not in valid_banks:
    #         continue
    #     if status == 'load_success':
    #         return True
    #
    # return False


def get_boost_status_at_homepage(application_id, workflow_name=None, app_version_header=None):
    from juloserver.julo.services2.high_score import feature_high_score_full_bypass

    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        raise ApplicationNotFound()
    boost_status = {
        "credit_score": {"score": None, "is_high_c_score": False},
        "bank_status": {"enable": False, "status": []},
        "bpjs_status": {"enable": False, "status": ""},
        "salary_status": {"enable": False, "image": {}},
        "bank_statement_status": {"enable": False, "image": {}},
    }
    boost_status['credit_score']['is_high_c_score'] = JuloOneService.is_high_c_score(application)
    credit_score = CreditScore.objects.filter(application_id=application.id).last()
    boost_status['credit_score']['score'] = credit_score.score

    boost_settings = get_boost_mobile_feature_settings()
    if boost_settings:
        bank_settings = boost_settings.parameters['bank']
        if bank_settings['is_active']:
            boost_status['bank_status']['enable'] = True
            julo_scraper_client = get_scapper_client()
            bank_statuses = julo_scraper_client.get_bank_scraping_status(application_id)
            mapped_bank_statuses = show_bank_status(bank_statuses, workflow_name)
            boost_status['bank_status']['status'] = mapped_bank_statuses['bank_status']

    bpjs_status = show_bpjs_status(
        application=application, workflow_name=workflow_name, app_version_header=app_version_header
    )
    if bpjs_status:
        boost_status['bpjs_status']['enable'] = True
        boost_status['bpjs_status']['status'] = bpjs_status['bpjs_status']

    is_image_enable = False
    medium_score_condition = (
        not feature_high_score_full_bypass(application)
        and not JuloOneService.is_high_c_score(application)
        and not JuloOneService.is_c_score(application)
    )
    if medium_score_condition:
        is_image_enable = True

    if is_image_enable:
        boost_status['salary_status']['enable'] = True
        boost_status['bank_statement_status']['enable'] = True

    salary_image = Image.objects.filter(image_source=application_id, image_type='paystub').last()
    if salary_image:
        boost_status['salary_status']['image'] = ImageSerializer(salary_image).data

    bank_statement_image = Image.objects.filter(
        image_source=application_id, image_type='bank_statement'
    ).last()
    if bank_statement_image:
        boost_status['bank_statement_status']['image'] = ImageSerializer(bank_statement_image).data

    return boost_status


def save_boost_forms(application_id, data):

    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        raise ApplicationNotFound()
    for key, value in list(data.items()):
        if key == 'additional_contact_1_number' and value:
            application.update_safely(additional_contact_1_number=data[key])
            skiptrace, create_flag = Skiptrace.objects.get_or_create(
                application=application,
                customer=application.customer,
                contact_source='additional_contact_1_number',
            )
            skiptrace.update_safely(
                contact_name=data['additional_contact_1_name'],
                phone_number=format_e164_indo_phone_number(data[key]),
                effectiveness=0,
                is_guarantor=False,
            )
        if key == 'additional_contact_2_number' and value:
            application.update_safely(additional_contact_2_number=data[key])
            skiptrace, create_flag = Skiptrace.objects.get_or_create(
                application=application,
                customer=application.customer,
                contact_source='additional_contact_2_number',
            )
            skiptrace.update_safely(
                contact_name=data['additional_contact_2_name'],
                phone_number=format_e164_indo_phone_number(data[key]),
                effectiveness=0,
                is_guarantor=False,
            )
        if key == 'additional_contact_1_name' and value:
            application.update_safely(additional_contact_1_name=data[key])
        if key == 'additional_contact_2_name' and value:
            application.update_safely(additional_contact_2_name=data[key])
        if key == 'loan_purpose_description_expanded' and value:
            application.update_safely(loan_purpose_description_expanded=data[key])
    return_data = dict()
    return_data["additional_contact_1_number"] = application.additional_contact_1_number
    return_data["additional_contact_2_number"] = application.additional_contact_2_number
    return_data["additional_contact_1_name"] = application.additional_contact_1_name
    return_data["additional_contact_2_name"] = application.additional_contact_2_name
    return_data["loan_purpose_description_expanded"] = application.loan_purpose_description_expanded

    julo_scraper_client = get_scapper_client()
    bank_statuses = julo_scraper_client.get_bank_scraping_status(application_id)
    mapped_bank_statuses = show_bank_status(bank_statuses)
    return_data.update(mapped_bank_statuses)

    bpjs_status = show_bpjs_status(application=application)
    return_data.update(bpjs_status)
    return return_data


def add_boost_button_and_message(response, application_id, credit_score):

    applicable_scores = ['A-', 'B+', 'B-']
    if credit_score not in applicable_scores:
        response['show_booster'] = False
        response['boost_message'] = response['message']
        return response

    all_boosts_completed = are_all_boosts_completed(application_id)
    response['show_booster'] = not all_boosts_completed
    if all_boosts_completed:
        response['boost_message'] = (
            "Karena Anda telah menyelesaikan semua pertanyaan, "
            "pengajuan pinjaman Anda akan diproses lebih cepat! "
            "Silahkan lanjutkan ke pemilihan produk."
        )
    else:
        response['boost_message'] = (
            "Beberapa informasi masih belum terisi. Silahkan isi semua "
            "bagian yang belum terisi untuk proses aplikasi yang lebih "
            "cepat atau lanjutkan ke pemilihan produk."
        )
    try:
        if response['message'] in [
            messages['fraud_form_partial_device'],
            messages['fraud_device'],
            messages['fraud_form_partial_hp_own'],
        ]:
            response['boost_message'] = response['message']
    except KeyError:
        pass
    return response


def are_all_boosts_completed(application_id):

    boost_status = get_boost_status(application_id)

    if (
        (boost_status['additional_contact_2_number'] and boost_status['additional_contact_2_name'])
        or (
            boost_status['additional_contact_1_number']
            and boost_status['additional_contact_1_name']
        )
    ) and boost_status['loan_purpose_description_expanded']:
        form_flag = True
    else:
        form_flag = False

    bank_flag = False
    boost_settings = get_boost_mobile_feature_settings()
    if not boost_settings:
        return
    bank_settings = boost_settings.parameters['bank']
    if bank_settings['is_active']:
        bank_statuses = boost_status['bank_status']
        for bank_status in bank_statuses:
            if bank_status['status'] is BoostBankConst.VERIFIED:
                bank_flag = True
                break
    else:
        bank_flag = True

    bpjs_flag = False
    bpjs_settings = boost_settings.parameters['bpjs']
    if bpjs_settings['is_active']:
        bpjs_flag = boost_status['bpjs_status'] is BoostBankConst.VERIFIED
    else:
        bpjs_flag = True
    boost_complete_flag = all([bank_flag, form_flag, bpjs_flag])

    return boost_complete_flag


def show_bank_status(bank_status, workflow_name=None):
    bank_list = []
    boost_settings = get_boost_mobile_feature_settings()
    if not boost_settings:
        return {}
    bank_settings = boost_settings.parameters['bank']
    if not bank_settings['is_active']:
        return {}
    valid_banks = []
    for bank_name, bank_feature_status in list(bank_settings.items()):
        if bank_name == 'is_active':
            continue
        if bank_feature_status['is_active']:
            valid_banks.append(bank_name)
    for bank, status in list(bank_status.items()):
        if bank not in valid_banks:
            continue
        bank_data = {'bank_name': bank}
        if workflow_name == 'julo_one':
            if status in ['auth_success', 'scrape_success', 'initiated']:
                bank_data["status"] = BoostBankConst.NOT_VERIFIED
            elif status in ['auth_failed', 'scrape_failed', 'load_failed']:
                bank_data["status"] = BoostBankConst.NOT_VERIFIED
            elif status == 'load_success':
                bank_data["status"] = BoostBankConst.VERIFIED
            else:
                bank_data["status"] = BoostBankConst.NOT_VERIFIED

        else:
            if status in [
                'load_success',
                'scrape_success',
                'auth_success',
                'scrape_failed',
                'load_failed',
            ]:
                bank_data["status"] = BoostBankConst.VERIFIED
            else:
                bank_data["status"] = BoostBankConst.NOT_VERIFIED
        bank_list.append(bank_data)
    return {"bank_status": bank_list}


def show_bpjs_status(bpjs_task=None, workflow_name=None, application=None, app_version_header=None):
    from juloserver.bpjs.services import Bpjs
    from juloserver.bpjs.services.providers.bpjs_interface import BpjsInterface

    boost_settings = get_boost_mobile_feature_settings()
    if not boost_settings:
        return {}

    # Check that bpjs is active or not. We will differentiate between old provider
    # Tongdun and new provider Brick. Old provider will only get the legacy setting
    # is_active, and new provider get from brick.is_active.
    bpjs_settings = boost_settings.parameters['bpjs']
    is_bpjs_enabled = _is_bpjs_enabled(bpjs_settings, application, app_version_header)
    if not is_bpjs_enabled:
        return {}

    if not application:
        if not bpjs_task:
            return {"bpjs_status": BoostBPJSConst.NOT_VERIFIED}
        application = bpjs_task.application

    bpjs_status = Bpjs(application).status
    if workflow_name == 'julo_one':
        if bpjs_status == BpjsInterface.STATUS_ONGOING:
            status = BoostBPJSConst.ONGOING
        elif bpjs_status == BpjsInterface.STATUS_VERIFIED:
            status = BoostBPJSConst.VERIFIED
        else:
            status = BoostBPJSConst.NOT_VERIFIED
    else:
        if bpjs_status == BpjsInterface.STATUS_VERIFIED:
            status = BoostBPJSConst.VERIFIED
        else:
            status = BoostBPJSConst.NOT_VERIFIED

    logger.info(
        {
            'message': 'BPJS Status Check',
            'application_id': application.id if application else None,
            'bpjs_status': status,
        }
    )

    return {"bpjs_status": status}


def _is_bpjs_enabled(setting, application: Application, app_version_header=None) -> bool:
    import semver

    # Since bpjs also used in the partnership, we set this with old setting.
    # The partnership will not use the app version since it is in web.
    if application is None or (application is not None and not application.app_version):
        return setting["is_active"]

    is_brick_version_eligible = (
        semver.match(app_version_header, '>=7.2.0') if app_version_header else False
    )
    if is_brick_version_eligible and "brick" in setting:
        return setting["brick"]["is_active"]

    return setting["is_active"]


def get_boost_mobile_feature_settings():
    boost_settings = MobileFeatureSetting.objects.filter(
        feature_name='boost', is_active=True
    ).last()
    return boost_settings


def get_bank_and_bpjs_status():
    bank_enable = bpjs_enable = False
    boost_settings = get_boost_mobile_feature_settings()
    if boost_settings:
        if boost_settings.parameters['bpjs']['is_active']:
            bpjs_enable = True
        if boost_settings.parameters['bank']['is_active']:
            bank_enable = True

    return bank_enable, bpjs_enable
