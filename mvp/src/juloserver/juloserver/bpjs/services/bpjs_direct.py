import logging
import re
import json
import jwt
from django.conf import settings
from typing import Dict

from juloserver.julo.models import (
    Application,
    ApplicationHistory,
    FeatureSetting,
    MobileFeatureSetting,
)
from juloserver.julo.constants import (
    FeatureNameConst,
    MycroftThresholdConst,
)
from juloserver.application_flow.models import ApplicationRiskyCheck
from juloserver.ana_api.models import PdApplicationFraudModelResult
from juloserver.bpjs.models import BpjsAPILog
from juloserver.bpjs.constants import BpjsDirectConstants
from juloserver.bpjs import get_bpjs_direct_client
from babel.dates import format_date
from juloserver.cfs.services.core_services import get_pgood
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes

from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object

logger = logging.getLogger(__name__)

sentry = get_julo_sentry_client()


class BPJSSystemErrorException(Exception):
    pass


def encode_jwt_token(payload: Dict) -> str:
    headers = {"typ": "JWT", "alg": "HS256", "pwd": settings.BPJS_DIRECT_PASSWORD}
    encode_jwt = jwt.encode(payload, settings.BPJS_DIRECT_SECRET_KEY, "HS256", headers).decode(
        'utf-8'
    )

    return encode_jwt


def generate_token_jwt(req_id, api):
    payload = {"username": settings.BPJS_DIRECT_USERNAME, "reqId": req_id, "api": api}

    return encode_jwt_token(payload)


def get_range_salary(income):
    income = income if income else 0

    for item in BpjsDirectConstants.BPJS_DIRECT_RANGE_SALARY:
        [min_range, max_range, range_salary] = item

        if not max_range and income >= min_range:
            return range_salary
        elif min_range <= income and income <= max_range:
            return range_salary
    return ""


def get_median_salary(application, is_turbo=False):
    bpjs_log = BpjsAPILog.objects.filter(
        application_id=application.id, service_provider='bpjs_direct'
    ).last()

    if is_turbo:
        customer = application.customer
        bpjs_log = BpjsAPILog.objects.filter(
            customer_id=customer.id, service_provider='bpjs_direct'
        ).last()

    income = application.monthly_income

    if bpjs_log and bpjs_log.response:
        if int(bpjs_log.http_status_code) == 200:
            substring = re.compile('(?<!\\\\)\'')
            bpjs_response = json.loads(substring.sub('\"', bpjs_log.response))

            if bpjs_response['ret'] == '0':
                bpjs_salary = bpjs_response['score']['upahRange']
                income_range_salary = get_range_salary(income)

                if (
                    income_range_salary != bpjs_salary
                    or (bpjs_salary == income_range_salary == '>20.5JT')
                ):
                    for item in BpjsDirectConstants.BPJS_DIRECT_RANGE_SALARY:
                        [min_range, max_range, range_salary] = item

                        if not max_range and bpjs_salary == range_salary:
                            return min_range
                        elif bpjs_salary == range_salary:
                            return (max_range + min_range) / 2

    return None


def _store_raw_response(customer_id, response):
    from juloserver.application_flow.models import BpjsAlertLog

    if response is None:
        return

    BpjsAlertLog.objects.create(
        customer_id=customer_id,
        provider='direct',
        log=response,
    )


def retrieve_and_store_bpjs_direct(application, salary=None):
    if not application:
        logger.error(
            {
                'action_view': 'BPJS Direct - retrieve_and_store_bpjs_direct',
                'data': {},
                'errors': 'Application ID is null',
            }
        )
        return

    if not isinstance(application, Application):
        application = Application.objects.get(pk=application)

    if not application:
        logger.error(
            {
                'action_view': 'BPJS Direct - retrieve_and_store_bpjs_direct',
                'data': {},
                'errors': 'Application not exist',
            }
        )
        return

    detokenized_application = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [{'customer_xid': application.customer.customer_xid, 'object': application}],
        force_get_local_data=True,
    )
    application = detokenized_application[0]

    req_id = settings.BPJS_DIRECT_PREFIX + str(application.application_xid)
    token = generate_token_jwt(req_id, "ClrTKByFieldScore")
    dob = format_date(application.customer.dob, 'dd-MM-yyyy')
    salary = salary if salary else application.monthly_income
    range_salary = get_range_salary(salary)

    bpjs_data = {
        'data': {
            'namaLengkap': application.fullname,
            'nomorIdentitas': application.ktp,
            'jenisKelamin': application.gender_initial,
            'tglLahir': dob,
            'paket': 'JHT,JKK,JKM,JPN',
            'blthUpah': application.last_month_salary,
            'upahRange': range_salary,
            'handphone': application.mobile_phone_1,
            'namaPerusahaan': application.company_name,
        }
    }

    bpjs_mock_feature = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.BPJS_MOCK_RESPONSE_SET,
        is_active=True,
    )
    bpjs_client = get_bpjs_direct_client()
    if (
        settings.ENVIRONMENT != 'prod'
        and bpjs_mock_feature
        and 'j-starter' in bpjs_mock_feature.parameters['product']
    ):
        response = bpjs_client.mock_retrieve_bpjs_direct_data(
            token, req_id, bpjs_data, application.id, application.customer.id
        )
    else:
        response = bpjs_client.retrieve_bpjs_direct_data(
            token, req_id, bpjs_data, application.id, application.customer.id
        )

    if not response:
        logger.error(
            {
                'action_view': 'BPJS Direct - retrieve_and_store_bpjs_direct',
                'data': {},
                'errors': 'Response BPJS Direct not valid',
            }
        )
        return

    return response


def eligible_hit_bpjs(application):
    from juloserver.ana_api.models import EligibleCheck
    from django.db.models import Q

    eligible_bpjs_direct = EligibleCheck.objects.filter(
        application_id=application.id,
        check_name="eligible_bpjs_direct",
        is_okay=True,
    ).last()

    histories = ApplicationHistory.objects.filter(application_id=application.id)
    is_revived = histories.filter(
        Q(change_reason__contains='revived') | Q(change_reason__contains='Revived')
    ).last()

    logger.info(
        {
            'action': 'BPJS Direct - eligible_hit_bpjs',
            'data': {
                'application_id': application.id,
                'eligible_bpjs_direct': eligible_bpjs_direct,
                'is_revived': is_revived,
            },
        }
    )

    return eligible_bpjs_direct and not is_revived


@sentry.capture_exceptions
def generate_bpjs_scoring(application, check_by_nik=False):
    pgood = get_pgood(application.id)
    if not eligible_hit_bpjs(application):
        result = 'bpjs_direct_check_not_pass'
        if pgood < BpjsDirectConstants.BPJS_EL_TRESHOLD:
            result = 'bpjs_direct_check_not_found'
        logger.info(
            {
                'action': 'BPJS Direct - not eligible hit generate_bpjs_scoring',
                'data': {
                    'application_id': application.id,
                    'result': result,
                    'pgood': pgood,
                },
            }
        )
        return result

    try:
        bpjs_log = BpjsAPILog.objects.filter(
            application_id=application.id, service_provider='bpjs_direct'
        ).last()
        response = bpjs_log
        result = 'bpjs_direct_check_not_pass'

        if not bpjs_log:
            response = retrieve_and_store_bpjs_direct(application)
            bpjs_log = BpjsAPILog.objects.filter(
                application_id=application.id, service_provider='bpjs_direct'
            ).last()

        if not response:
            raise BPJSSystemErrorException('No Response')
        else:
            if bpjs_log and bpjs_log.response:
                if int(bpjs_log.http_status_code) != 200:
                    raise BPJSSystemErrorException('BPJS Response HTTP Status Code Unsuccessful')
                else:
                    substring = re.compile('(?<!\\\\)\'')
                    bpjs_response = json.loads(substring.sub('\"', bpjs_log.response))
                    if 'ret' not in bpjs_response:
                        raise BPJSSystemErrorException('BPJS Response Unrecognized')
                    elif (
                        bpjs_response['ret'] == '-2'
                        and bpjs_response['msg'].lower() == 'data tidak ditemukan'
                    ):
                        result = 'bpjs_direct_check_not_found'
                    elif bpjs_response['ret'] == '0':
                        bpjs_nik = bpjs_response['score']['nomorIdentitas']
                        bpjs_salary = bpjs_response['score']['upahRange']
                        bpjs_company = bpjs_response['score']['namaPerusahaan']

                        range_salary = get_range_salary(application.monthly_income)

                        if (
                            bpjs_salary == 'SESUAI'
                            or bpjs_salary == range_salary
                            or bpjs_company == 'SESUAI'
                        ) and not check_by_nik:
                            result = 'bpjs_direct_check_pass'
                        elif bpjs_nik == 'SESUAI' and check_by_nik:
                            result = 'bpjs_direct_nik_found'
                        else:
                            result = 'bpjs_direct_check_not_pass'
                    else:
                        raise BPJSSystemErrorException('BPJS Response Unrecognized')
    except Exception as e:
        result = 'bpjs_direct_check_not_pass'
        _store_raw_response(application.customer_id, str(e))
        logger.info(
            {
                'action': 'BPJS Direct - generate_bpjs_scoring',
                'data': {'application_id': application.id, 'message': str(e)},
            }
        )
    return result


def bypass_bpjs_scoring(application, is_waitlist=False):
    from juloserver.application_flow.tasks import application_tag_tracking_task
    from juloserver.application_flow.services import check_is_fdc_tag

    result = generate_bpjs_scoring(application)
    pgood = get_pgood(application.id)
    last_digit_id = int(str(application.id)[-1:])
    risky_checklist = ApplicationRiskyCheck.objects.filter(application=application).last()
    dv_bypass = True if risky_checklist.decision is None else False
    has_fdc_tag = check_is_fdc_tag(application)

    if result == 'bpjs_direct_check_not_found' and pgood < BpjsDirectConstants.BPJS_EL_TRESHOLD:
        if last_digit_id != 0 and has_fdc_tag:
            application_tag_tracking_task(
                application.id, application.status, None, 'bpjs_entrylevel', 'is_bpjs_entrylevel', 1
            )
        else:
            application_tag_tracking_task(application.id, None, None, None, 'is_bpjs_entrylevel', 0)
    elif result == 'bpjs_direct_check_pass':
        bpjs_risky_setting = FeatureSetting.objects.get(
            feature_name=FeatureNameConst.BPJS_RISKY_BYPASS)
        if bpjs_risky_setting.is_active and not dv_bypass and not is_waitlist:
            last_digit_allowed = bpjs_risky_setting.parameters.get('application_id')
            if last_digit_id in last_digit_allowed:
                process_application_status_change(
                    application.id,
                    ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                    change_reason=FeatureNameConst.HIGH_SCORE_FULL_BYPASS)
                application_tag_tracking_task(
                    application.id, None, None, None, 'is_hsfbp', 1
                )
                return True

        bpjs_super_bypass_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.BPJS_SUPER_BYPASS
        ).last()
        if (
            bpjs_super_bypass_setting
            and bpjs_super_bypass_setting.is_active
            and dv_bypass
            and not is_waitlist
        ):
            last_digit_allowed = bpjs_super_bypass_setting.parameters.get('application_id')
            if last_digit_id in last_digit_allowed:
                process_application_status_change(
                    application.id, ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL, 'bpjs_bypass'
                )
                application_tag_tracking_task(
                    application.id,
                    application.status,
                    ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
                    'bpjs_bypass',
                    'is_bpjs_bypass',
                    1,
                )
                return True
    else:
        application_tag_tracking_task(application.id, None, None, None, 'is_bpjs_entrylevel', 0)

    return False


def is_bpjs_found_by_nik(application):
    from juloserver.application_flow.tasks import application_tag_tracking_task

    mfs = MobileFeatureSetting.objects.filter(feature_name="bpjs_direct", is_active=True).last()

    if not mfs:
        return False

    from juloserver.apiv2.models import PdCreditModelResult, PdWebModelResult

    heimdall = PdCreditModelResult.objects.filter(application_id=application.id).last()

    if not heimdall:
        heimdall = PdWebModelResult.objects.filter(application_id=application.id).last()

    has_fdc = heimdall.has_fdc if heimdall else False
    if has_fdc:
        return False

    pgood = get_pgood(application.id)

    if (
        pgood >= BpjsDirectConstants.BPJS_NO_FDC_EL_LOWER_TRESHOLD
        and pgood < BpjsDirectConstants.BPJS_NO_FDC_EL_UPPER_TRESHOLD
    ):
        mycroft_score_ana = PdApplicationFraudModelResult.objects.filter(
            application_id=application.id
        ).last()
        if (
            mycroft_score_ana
            and mycroft_score_ana.pgood >= MycroftThresholdConst.NO_FDC_BPJS_EL_MYCROFT
        ):
            application_tag_tracking_task(
                application.id,
                application.status,
                None,
                'bpjs_found',
                'is_bpjs_found',
                1,
            )

            return True

    return False


def bypass_bpjs_waitlist(application):
    from juloserver.application_flow.services import check_bpjs_found

    is_bpjs_found = check_bpjs_found(application)
    if is_bpjs_found:
        logger.info(
            {
                'action': 'process_bpjs_waitlist',
                'message': 'application bpjs no fdc eligible el',
                'application': application.id,
            }
        )
        process_application_status_change(
            application.id,
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            'eligible no_fdc entrylevel',
        )
        return True

    bpjs_bypass = bypass_bpjs_scoring(application)
    if bpjs_bypass:
        logger.info(
            {
                'message': 'application have bpjs_bypass',
                'bpjs_bypass': bpjs_bypass,
                'application': application.id,
            }
        )
        return True

    return False
