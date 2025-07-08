import json
import logging
import re

from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.bpjs.constants import BpjsDirectConstants
from juloserver.bpjs.models import SdBpjsProfileScrape, SdBpjsCompanyScrape, BpjsAPILog
from juloserver.fraud_portal.models.models import BPJSBrickInfo, DukcapilInfo, BPJSDirectInfo
from juloserver.julo.models import (
    Application,
)
from juloserver.personal_data_verification.models import DukcapilResponse
from juloserver.pii_vault.constants import PiiSource

logger = logging.getLogger(__name__)


def get_bpjs_and_ducakpil_info_of_applications(application_ids: list) -> dict:
    bpjs_brick_list = []
    bpjs_direct_info_list = []
    ducakpil_list = []

    for application_id in application_ids:
        application = Application.objects.get(id=application_id)

        dukcapil = get_dukcapil_info(application)
        ducakpil_list.append(dukcapil)

        bpjs_direct_info = get_bpjs_direct_info(application)
        bpjs_direct_info_list.append(bpjs_direct_info)

        bpjs_brick_info = get_bpjs_brick_info(application)
        bpjs_brick_list.append(bpjs_brick_info)

    return {
        "bpjs_brick_info_list": bpjs_brick_list,
        "bpjs_direct_info_list": bpjs_direct_info_list,
        "ducakpil_list": ducakpil_list,
    }


def get_dukcapil_info(application: Application) -> dict:
    dukcakpil_info = DukcapilResponse.objects.filter(application=application).last()
    if dukcakpil_info:

        return DukcapilInfo(
            application_id=application.id,
            name=dukcakpil_info.name,
            birthdate=dukcakpil_info.birthdate,
            birthplace=dukcakpil_info.birthplace,
            gender=dukcakpil_info.gender,
            marital_status=dukcakpil_info.marital_status,
            address_kabupaten=dukcakpil_info.address_kabupaten,
            address_kecamatan=dukcakpil_info.address_kecamatan,
            address_kelurahan=dukcakpil_info.address_kelurahan,
            address_provinsi=dukcakpil_info.address_provinsi,
            address_street=dukcakpil_info.address_street,
            job_type=dukcakpil_info.job_type,
        ).to_dict()

    return DukcapilInfo(application_id=application.id).to_dict()


def get_bpjs_brick_info(application: Application) -> dict:
    try:
        bpjs_profile = SdBpjsProfileScrape.objects.filter(application_id=application.id).last()
        if not bpjs_profile:

            return BPJSBrickInfo(application_id=application.id).to_dict()
        detokenized_bpjs_profile = detokenize_pii_antifraud_data(
            PiiSource.SD_BPJS_PROFILE, [bpjs_profile]
        )[0]

        bpjs_company = SdBpjsCompanyScrape.objects.filter(profile=bpjs_profile).last()

        if not bpjs_company:

            return BPJSBrickInfo(
                application_id=application.id,
                real_name=detokenized_bpjs_profile.real_name,
                identity_number=detokenized_bpjs_profile.identity_number,
                birthday=bpjs_profile.birthday,
                gender=bpjs_profile.gender,
                address=bpjs_profile.address,
                phone=detokenized_bpjs_profile.phone,
                total_balance=bpjs_profile.total_balance,
                bpjs_type=bpjs_profile.type,
                bpjs_cards=bpjs_profile.bpjs_cards,
            ).to_dict()

        return BPJSBrickInfo(
            application_id=application.id,
            real_name=detokenized_bpjs_profile.real_name,
            identity_number=detokenized_bpjs_profile.identity_number,
            birthday=bpjs_profile.birthday,
            gender=bpjs_profile.gender,
            address=bpjs_profile.address,
            phone=detokenized_bpjs_profile.phone,
            total_balance=bpjs_profile.total_balance,
            bpjs_type=bpjs_profile.type,
            bpjs_cards=bpjs_profile.bpjs_cards,
            company_name=bpjs_company.company,
            last_payment_date=bpjs_company.last_payment_date,
            employment_status=bpjs_company.employment_status,
            employment_month_duration=bpjs_company.employment_month_duration,
            current_salary=bpjs_company.current_salary,
        ).to_dict()
    except Exception as e:
        logger.error({'action': 'get_bpjs_brick_info', 'error': e})

        return BPJSBrickInfo(application_id=application.id).to_dict()


def get_bpjs_direct_info(application: Application) -> dict:
    try:
        bpjs_direct_log = BpjsAPILog.objects.filter(
            application_id=application.id,
            service_provider=BpjsDirectConstants.SERVICE_NAME,
            http_status_code=200,
        ).last()

        if not bpjs_direct_log:

            return BPJSDirectInfo(application_id=application.id).to_dict()

        bpjs_direct_response = get_bpjs_direct_response(bpjs_direct_log)
        if 'ret' not in bpjs_direct_response or bpjs_direct_response['ret'] != '0':

            return BPJSDirectInfo(application_id=application.id).to_dict()

        bpjs_direct_score = bpjs_direct_response['score']

        return BPJSDirectInfo(
            application_id=application.id,
            namaLengkap=bpjs_direct_score['namaLengkap'],
            nomorIdentitas=bpjs_direct_score['nomorIdentitas'],
            tglLahir=bpjs_direct_score['tglLahir'],
            jenisKelamin=bpjs_direct_score['jenisKelamin'],
            handphone=bpjs_direct_score['handphone'],
            email=bpjs_direct_score['email'],
            namaPerusahaan=bpjs_direct_score['namaPerusahaan'],
            paket=bpjs_direct_score['paket'],
            upahRange=bpjs_direct_score['upahRange'],
            blthUpah=bpjs_direct_score['blthUpah'],
        ).to_dict()

    except Exception as e:
        logger.error({'action': 'get_bpjs_direct_info', 'error': e})

        return BPJSDirectInfo(application_id=application.id).to_dict()


def get_bpjs_direct_response(bpjs_direct_log: BpjsAPILog) -> dict:
    substring = re.compile('(?<!\\\\)\'')
    bpjs_direct_response = json.loads(substring.sub('\"', bpjs_direct_log.response))

    return bpjs_direct_response
