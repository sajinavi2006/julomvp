import re
import json
from typing import Union

from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from juloserver.julo.models import (
    Application,
    Customer,
    OnboardingEligibilityChecking,
    FeatureSetting,
    FDCInquiry,
    FDCInquiryLoan,
    ApplicationRiskyCheck,
)
from juloserver.julolog.julolog import JuloLog
from juloserver.application_form.constants import JuloStarterFormResponseMessage
from juloserver.bpjs.models import BpjsAPILog
from juloserver.julo.utils import verify_nik

from juloserver.fdc.services import (
    get_and_save_fdc_data,
    mock_get_and_save_fdc_data,
)

from juloserver.bpjs import get_bpjs_direct_client
from juloserver.bpjs.services.bpjs_direct import (
    generate_token_jwt,
    get_range_salary,
    BPJSSystemErrorException,
    _store_raw_response,
)
from juloserver.julo.constants import FeatureNameConst, OnboardingIdConst
from juloserver.julo_starter.constants import (
    SphinxThresholdNoBpjsConst,
    JuloStarterDukcapilCheck,
    NotificationSetJStarter,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.fdc.constants import FDCStatus
from juloserver.bpjs.constants import BpjsDirectConstants
from juloserver.personal_data_verification.constants import (
    DukcapilDirectError,
    MIN_NO_OF_VERIFICATION_FIELDS_TO_PASS,
)
from juloserver.personal_data_verification.services import is_pass_dukcapil_verification
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object

logger = JuloLog(__name__)

sentry = get_julo_sentry_client()


def check_process_eligible(customer_id, onboarding_id=None):
    """
    BPJS check moved to after emulator check
    """
    on_check = OnboardingEligibilityChecking.objects.filter(customer_id=customer_id).last()

    process_checking = 'no_data'
    is_eligible = 'no_data'

    if on_check:
        if onboarding_id == OnboardingIdConst.JULO_360_TURBO_ID:
            is_eligible = 'passed'
            process_checking = 'finished'
        else:
            process_checking = 'on_process'
            is_eligible = 'on_process'

            if on_check.fdc_check is not None:
                process_checking = 'finished'
                is_eligible = 'not_passed'

                if on_check.fdc_check == 3:
                    process_checking = 'finished'
                    is_eligible = 'offer_regular'
                elif on_check.fdc_check == 1:
                    is_eligible = 'passed'
                    process_checking = 'finished'

    data = {
        'process_eligibility_checking': process_checking,
        'is_eligible': is_eligible,
    }

    logger.info(
        {
            "function": "check_process_eligible()",
            "customer_id": customer_id,
            "data": data,
            "on_check.fdc_check": 'no on_check' if on_check is None else on_check.fdc_check,
        }
    )

    return data


def eligibility_checking(
    customer: Union[Customer, int],
    is_fdc_eligible=True,
    is_send_pn=True,
    application_id=None,
    process_change_application_status=False,
    onboarding_id=None,
):
    from juloserver.julo_starter.tasks.eligibility_tasks import run_eligibility_check

    customer_id = None
    if not isinstance(customer, Customer):
        customer_id = customer
        customer = Customer.objects.get_or_none(id=customer)

    if not customer:
        logger.warning(
            {
                "message": JuloStarterFormResponseMessage.CUSTOMER_NOT_FOUND,
                "customer_id": customer_id if customer_id else customer,
            }
        )
        return False

    # Detokenize because it used nik
    detokenized_customers = detokenize_for_model_object(
        PiiSource.CUSTOMER,
        [
            {
                'object': customer,
            }
        ],
        force_get_local_data=True,
    )
    customer = detokenized_customers[0]

    if is_fdc_eligible and not verify_nik(customer.nik):
        logger.warning(
            {
                "message": "NIK not Valid",
                "customer_id": customer.id,
            }
        )
        return False

    fdc_inquiry_data = {}
    if is_fdc_eligible:
        create_data = dict(nik=customer.nik, customer_id=customer.id)
        if application_id:
            create_data['application_id'] = application_id
        fdc_inquiry = FDCInquiry.objects.create(**create_data)
        fdc_inquiry_data = {'id': fdc_inquiry.id, 'nik': customer.nik}

    run_eligibility_check.delay(
        fdc_inquiry_data,
        1,
        is_fdc_eligible=is_fdc_eligible,
        customer_id=customer.id,
        application_id=application_id,
        is_send_pn=is_send_pn,
        process_change_application_status=process_change_application_status,
        onboarding_id=onboarding_id,
    )

    return True


def retrieve_and_store_bpjs_direct(customer: Union[Customer, int]):
    julo_starter_config = FeatureSetting.objects.get_or_none(
        feature_name="julo_starter_config", is_active=True
    )

    if julo_starter_config and julo_starter_config.parameters['salary']:
        salary = julo_starter_config.parameters['salary']
    else:
        logger.warning(
            {
                "message": "FeatureSetting julo_starter_config not found",
                "customer_id": customer.id,
            }
        )
        # default
        salary = 2500000

    if not customer:
        logger.error(
            {
                'action_view': 'J-Starter BPJS Direct - retrieve_and_store_bpjs_direct',
                'data': {},
                'errors': 'Customer ID is null',
            }
        )
        return

    if not isinstance(customer, Customer):
        customer = Customer.objects.get(pk=customer)

    if not customer:
        logger.error(
            {
                'action_view': 'J-Starter BPJS Direct - retrieve_and_store_bpjs_direct',
                'data': {},
                'errors': 'Customer not exist',
            }
        )
        return

    # Detokenize because it used nik
    detokenized_customers = detokenize_for_model_object(
        PiiSource.CUSTOMER,
        [
            {
                'object': customer,
            }
        ],
        force_get_local_data=True,
    )
    customer = detokenized_customers[0]

    req_id = settings.BPJS_DIRECT_PREFIX + str(customer.customer_xid)
    token = generate_token_jwt(req_id, "ClrTKByFieldScore")
    range_salary = get_range_salary(salary)

    bpjs_data = {
        'data': {
            'namaLengkap': '',
            'nomorIdentitas': customer.nik,
            'jenisKelamin': '',
            'tglLahir': '',
            'paket': 'JHT,JKK,JKM,JPN',
            'blthUpah': customer.last_month_salary,
            'upahRange': range_salary,
            'handphone': '',
            'namaPerusahaan': '',
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
            token, req_id, bpjs_data, None, customer.id
        )
    else:
        response = bpjs_client.retrieve_bpjs_direct_data(
            token, req_id, bpjs_data, None, customer.id
        )

    if not response:
        logger.error(
            {
                'action_view': 'J-Starter BPJS Direct - retrieve_and_store_bpjs_direct',
                'data': {},
                'errors': 'Response BPJS Direct not valid',
            }
        )
        return

    return response


def process_eligibility_check(
    fdc_inquiry_data,
    reason,
    retry,
    is_fdc_eligible=True,
    customer_id=None,
    application_id=None,
    onboarding_id=None,
):
    """
    From card: https://juloprojects.atlassian.net/browse/RUS1-2849
    BPJS checking is separated to function check_bpjs_for_turbo
    """

    if not is_fdc_eligible:
        logger.info('process_eligibility_check_bypass_fdc_check|customer={}'.format(customer_id))
        onboarding_checking = OnboardingEligibilityChecking.objects.filter(
            customer_id=customer_id
        ).last()
        if not onboarding_checking:
            onboarding_checking = OnboardingEligibilityChecking.objects.create(
                customer_id=customer_id
            )

        return onboarding_checking

    # No need to detokenize fdc inquiry here,
    # because it only uses the id, customer_id, and status.
    # Do more detokenization if used PII attribute!
    fdc_inquiry = FDCInquiry.objects.get(id=fdc_inquiry_data['id'])

    onboarding_checking = OnboardingEligibilityChecking.objects.filter(
        customer_id=fdc_inquiry.customer_id
    ).last()
    if onboarding_id == OnboardingIdConst.JULO_360_TURBO_ID:
        if onboarding_checking:
            if application_id:
                onboarding_checking.update_safely(application_id=application_id)
        else:
            onboarding_checking = OnboardingEligibilityChecking.objects.create(
                customer_id=fdc_inquiry.customer_id, application_id=application_id
            )

    fdc_mock_feature = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.FDC_MOCK_RESPONSE_SET,
        is_active=True,
    )

    if (
        settings.ENVIRONMENT != 'prod'
        and fdc_mock_feature
        and 'j-starter' in fdc_mock_feature.parameters['product']
    ):
        mock_get_and_save_fdc_data(fdc_inquiry_data)
    else:
        logger.info(
            {
                "function": "process_eligibility_check",
                "action": "call get_and_save_fdc_data",
                "fdc_inquiry_data": fdc_inquiry_data,
                "reason": reason,
                "retry": retry,
            }
        )
        get_and_save_fdc_data(fdc_inquiry_data, reason, retry)

    fdc_check = 3

    # No need to detokenize customer here,
    # because it only uses id and can_reapply.
    # Do more detokenization if used PII attribute!
    customer = Customer.objects.get(id=customer_id)

    reset_can_reapply = is_need_reset_can_reapply(customer)

    if fdc_inquiry.status and FDCStatus.FOUND != fdc_inquiry.status.lower() and reset_can_reapply:
        customer.can_reapply = False
        customer.save()

    # No need to detokenize fdc inquiry loan here,because it only uses the kualitas_pinjaman,
    # tgl_jatuh_tempo_pinjaman, and sisa_pinjaman_berjalan.
    # Do more detokenization if used PII attribute!
    fdc_inquiry_loans = FDCInquiryLoan.objects.filter(fdc_inquiry=fdc_inquiry)

    if fdc_inquiry_loans:
        fdc_check = 1
        today = timezone.localtime(timezone.now()).date()
        bad_loan_qualities = [
            'Tidak Lancar (30 sd 90 hari)',
            'Tidak Lancar ( 30 sd 90 hari )',
            'Kurang Lancar',
            'Diragukan',
            'Tidak Lancar',
            'Macet (>90)',
            'Macet ( >90 )',
            'Macet',
        ]
        for loan_data in fdc_inquiry_loans:
            if loan_data.kualitas_pinjaman in bad_loan_qualities or (
                loan_data.tgl_jatuh_tempo_pinjaman <= today and loan_data.sisa_pinjaman_berjalan > 0
            ):
                fdc_check = 2
                if reset_can_reapply:
                    reapply_date = timezone.now() + timedelta(days=31)
                    customer.can_reapply = False
                    customer.can_reapply_date = reapply_date
                    customer.save()
                break

    # WARNING: override section
    is_target_whitelist = is_email_for_whitelists(customer)
    if is_target_whitelist:
        logger.info(
            {
                'message': '[FDC_CHECK] override result for email whitelist',
                'new_fdc_check': 1,
                'old_fdc_check': fdc_check,
                'customer': customer.id if customer else None,
            }
        )
        fdc_check = 1

    if onboarding_checking:
        updated_data = dict(fdc_inquiry_id=fdc_inquiry.id, fdc_check=fdc_check)
        onboarding_checking.update_safely(**updated_data)
    else:
        onboarding_checking = OnboardingEligibilityChecking.objects.create(
            customer_id=fdc_inquiry.customer_id, fdc_inquiry_id=fdc_inquiry.id, fdc_check=fdc_check
        )
    return onboarding_checking


def check_bpjs_for_turbo(application: Application):
    """
    This function was originally from process_eligibility_check
    To moved after emulator check and dukcapil check

    No need to detokenize application here, because is only uses for relationships.
    Do more detokenization if used PII attribute!
    """

    def fail_bpjs_check(cust, can_reapply_reset):
        if can_reapply_reset:
            cust.can_reapply = False
            cust.save()
        return 3

    # No need to detokenize customer here, because is only uses id, can_reapply.
    # Do more detokenization if used PII attribute!
    customer = application.customer

    onboarding_checking = OnboardingEligibilityChecking.objects.filter(
        customer_id=customer.id
    ).last()
    if not onboarding_checking:
        logger.warning(
            {
                'action': 'check_bpjs_for_turbo',
                'message': 'OnboardingEligibilityChecking with that customer_id is not found',
                'customer_id': customer.id,
            }
        )
        onboarding_checking = OnboardingEligibilityChecking.objects.create(customer_id=customer.id)

    reset_can_reapply = is_need_reset_can_reapply(customer)

    bpjs_log = None
    bpjs_check = 2

    try:
        response = retrieve_and_store_bpjs_direct(customer)
        if not response:
            raise BPJSSystemErrorException('No Response')

        bpjs_log = BpjsAPILog.objects.filter(
            customer_id=customer.id, service_provider=BpjsDirectConstants.SERVICE_NAME
        ).last()

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
                    bpjs_check = fail_bpjs_check(customer, reset_can_reapply)
                elif bpjs_response['ret'] == '0':
                    bpjs_salary = bpjs_response['score']['upahRange']
                    if bpjs_salary == 'SESUAI' or bpjs_salary == '0-2.5JT':
                        bpjs_check = 2
                        if reset_can_reapply:
                            reapply_date = timezone.now() + timedelta(days=31)
                            customer.can_reapply = False
                            customer.can_reapply_date = reapply_date
                            customer.save()
                    else:
                        bpjs_check = 1
                else:
                    raise BPJSSystemErrorException('BPJS Response Unrecognized')
    except Exception as e:
        bpjs_check = fail_bpjs_check(customer, reset_can_reapply)
        _store_raw_response(customer.id, str(e))
        logger.info(
            {
                'action': 'BPJS Turbo - retrieve_and_store_bpjs_direct',
                'data': {'customer_id': customer.id, 'message': str(e)},
            }
        )
    # WARNING: override section
    is_target_whitelist = is_email_for_whitelists(customer)
    if is_target_whitelist:
        logger.info(
            {
                'message': '[BPJS_CHECK] override result for email whitelist',
                'new_bpjs_check': 1,
                'old_bpjs_check': bpjs_check,
                'customer': customer.id if customer else None,
            }
        )
        bpjs_check = 1

    onboarding_checking.update_safely(
        bpjs_api_log=bpjs_log,
        bpjs_check=bpjs_check,
    )

    return bpjs_check


def check_dukcapil_for_turbo(application: Application):
    """
    This function was originally from workflow actions
    To moved after emulator check

    No need to detokenize application here, because is only check the relationship.
    Do more detokenization if used PII attribute!
    """

    # WARNING: override section

    # No need to detokenize customer here, because it used in function as object.
    # Do more detokenization if used PII attribute!
    customer = application.customer

    is_target_whitelist = is_email_for_whitelists(customer)

    is_pass_dukcapil_verification(application)
    dukcapil_response = application.dukcapilresponse_set.last()
    results = []
    empty_quota = None
    if dukcapil_response is not None:
        if (
            dukcapil_response.errors == '05'
            or dukcapil_response.errors == DukcapilDirectError.EMPTY_QUOTA
        ):
            empty_quota = DukcapilDirectError.EMPTY_QUOTA
        results.append(dukcapil_response.name)
        results.append(dukcapil_response.birthdate)
    pass_criteria = MIN_NO_OF_VERIFICATION_FIELDS_TO_PASS
    dukcapil_check = JuloStarterDukcapilCheck.NOT_PASSED

    feature = FeatureSetting.objects.filter(feature_name='dukcapil_verification').last()
    if feature:
        pass_criteria = feature.parameters.get(
            'minimum_checks_to_pass', MIN_NO_OF_VERIFICATION_FIELDS_TO_PASS
        )
    if not results or None in results:
        if empty_quota == DukcapilDirectError.EMPTY_QUOTA:
            dukcapil_check = JuloStarterDukcapilCheck.BYPASS
        else:
            from juloserver.julo_starter.services.services import process_offer_to_j1

            # No need to detokenize application here,
            # because it only uses `status` and passed to another function.
            # Do more detokenization if used PII attribute!
            app = Application.objects.filter(id=application.id).last()

            if app.status != ApplicationStatusCodes.APPLICATION_DENIED and not is_target_whitelist:
                logger.info(
                    {
                        'action': 'failed dukcapil check julo starter offer j1',
                        'application_id': application.id,
                    }
                )
                process_offer_to_j1(application, 'dukcapil_failed')

    elif sum(results) < pass_criteria:
        dukcapil_check = JuloStarterDukcapilCheck.BYPASS

        flag_application = ApplicationRiskyCheck.objects.filter(application=application).last()

        if flag_application:
            flag_application.update_safely(is_dukcapil_not_match=True)

    else:
        dukcapil_check = JuloStarterDukcapilCheck.PASSED

    # No need to detokenize customer here, because it only use the id.
    # Do more detokenization if used PII attribute!
    customer = application.customer

    onboarding_eligibility_checking = OnboardingEligibilityChecking.objects.filter(
        customer_id=customer.id
    ).last()
    if onboarding_eligibility_checking.application is None:
        onboarding_eligibility_checking.update_safely(
            application=application,
            dukcapil_check=dukcapil_check,
            dukcapil_response=dukcapil_response,
        )
    elif onboarding_eligibility_checking.application.id == application.id:
        onboarding_eligibility_checking.update_safely(
            dukcapil_check=dukcapil_check, dukcapil_response=dukcapil_response
        )
    else:
        OnboardingEligibilityChecking.objects.create(
            customer=onboarding_eligibility_checking.customer,
            fdc_check=onboarding_eligibility_checking.fdc_check,
            bpjs_check=onboarding_eligibility_checking.bpjs_check,
            application=application,
            dukcapil_check=dukcapil_check,
            dukcapil_response=dukcapil_response,
        )

    # WARNING: override section
    if is_target_whitelist:
        logger.info(
            {
                'message': '[DUKCAPIL_CHECK] bypass',
                'application': application.id,
            }
        )
        return True

    logger.info(
        {
            'message': '[DUKCAPIL_CHECK] no bypass',
            'application': application.id,
        }
    )

    return dukcapil_check != JuloStarterDukcapilCheck.NOT_PASSED


def check_julo_turbo_rejected_period(customer: Customer):

    # No need to detokenize customer here,
    # because it only uses id and can_reapply.
    # Do more detokenization if used PII attribute!

    rejected_onboarding = False
    onboarding_check = check_process_eligible(customer.id)
    if onboarding_check and onboarding_check.get('is_eligible') in ['not_passed']:
        rejected_onboarding = True
    return rejected_onboarding and not customer.can_reapply


def get_config_sphinx_no_bpjs(return_instance=False):
    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SPHINX_NO_BPJS_THRESHOLD,
        is_active=True,
    ).last()

    if not setting:
        return False

    if return_instance:
        return setting

    return True


def get_threshold_attributes_no_bpjs(high_threshold=True, setting=None, return_holdout=False):
    if not setting:
        logger.warning(
            {
                'message': 'configuration {} is not active'.format(
                    FeatureNameConst.SPHINX_NO_BPJS_THRESHOLD
                ),
            }
        )
        return None, None

    # parameter feature setting
    param = setting.parameters

    if return_holdout:
        return int(param[SphinxThresholdNoBpjsConst.HOLDOUT])

    if high_threshold:
        # high score
        hs_threshold = float(param[SphinxThresholdNoBpjsConst.HIGH_SCORE_THRESHOLD])
        hs_operator = param[SphinxThresholdNoBpjsConst.HIGH_SCORE_OPERATOR]

        return hs_threshold, hs_operator

    # medium score
    ms_threshold = float(param[SphinxThresholdNoBpjsConst.MEDIUM_SCORE_THRESHOLD])
    ms_operator = param[SphinxThresholdNoBpjsConst.MEDIUM_SCORE_OPERATOR]

    return ms_threshold, ms_operator


def is_email_for_whitelists(customer: Customer):
    """
    For function whitelist by pass check in Jturbo by email
    on the Customer table
    """

    if not customer:
        logger.warning({'message': 'white list email process not have customer data'})
        return False

    # get email list
    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.JTURBO_BYPASS, is_active=True
    ).last()

    if not setting:
        logger.info(
            {
                'message': 'whitelist email configuration is not active',
                'feature_name': FeatureNameConst.JTURBO_BYPASS,
                'customer': customer.id if customer else None,
            }
        )
        return False

    if not setting.parameters:
        logger.info(
            {
                'message': 'whitelist email is empty in parameters setting',
                'feature_name': FeatureNameConst.JTURBO_BYPASS,
                'customer': customer.id if customer else None,
            }
        )
        return False

    email_whitelist = setting.parameters

    # We need to detokenize customer because it use PII attribute `email`
    detokenized_customers = detokenize_for_model_object(
        PiiSource.CUSTOMER,
        [
            {
                'object': customer,
            }
        ],
        force_get_local_data=True,
    )
    customer = detokenized_customers[0]
    if customer and customer.email.lower() in [
        email_target.lower() for email_target in email_whitelist
    ]:
        logger.info(
            {
                'message': '[WHITELIST_PROCESS] checking for email whitelist JTurbo',
                'result': True,
                'customer': customer.id,
            }
        )
        return True

    logger.info(
        {
            'message': '[WHITELIST_PROCESS] checking for email whitelist JTurbo',
            'result': False,
            'customer': customer.id,
        }
    )
    return False


def is_need_reset_can_reapply(customer: Customer):

    # No need to detokenize customer & application here,
    # because is only check the relationship.
    # Do more detokenization if used PII attribute!
    application = Application.objects.filter(customer=customer).last()

    if application and application.is_julo_one():
        logger.info(
            {
                'message': 'is_need_reset_can_reapply',
                'result': False,
                'application': application.id,
            }
        )
        return False

    logger.info(
        {
            'message': 'is_need_reset_can_reapply',
            'result': True,
            'customer': customer.id,
        }
    )
    return True


def check_bpjs_and_dukcapil_for_turbo(application: Application):
    if not application:
        return False

    # No need to detokenize application here,
    # because it passed to another function and use id, `application_status_id`.
    # Do more detokenization if used PII attribute!

    check_dukcapil_for_turbo(application)
    application.refresh_from_db()
    if application.application_status_id != ApplicationStatusCodes.FORM_PARTIAL:
        return

    bpjs_check = check_bpjs_for_turbo(application)

    if bpjs_check == 2:
        from juloserver.julo_starter.tasks.app_tasks import trigger_push_notif_check_scoring

        logger.info(
            {
                "application_id": application.id,
                "action": "move to 135 bpjs_check failed",
                "function": "check_bpjs_and_dukcapil_for_turbo",
                "condition": "bad bpjs_check",
                "current_status": application.status,
            }
        )

        process_application_status_change(
            application.id,
            ApplicationStatusCodes.APPLICATION_DENIED,
            'bad_bpjs_check',
        )

        template_code_for_notif = NotificationSetJStarter.KEY_MESSAGE_REJECTED
        trigger_push_notif_check_scoring.delay(application.id, template_code_for_notif)

    elif bpjs_check == 1:
        logger.info(
            {
                "application_id": application.id,
                "action": "move to 108 with reason sphinx_threshold_passed",
                "function": "check_bpjs_and_dukcapil_for_turbo",
                "condition": "good bpjs_check",
                "current_status": application.status,
            }
        )

        process_application_status_change(
            application.id,
            ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK,
            'sphinx_threshold_passed',
        )

    elif bpjs_check == 3:
        from juloserver.julo_starter.services.services import (
            determine_eligibility_by_pgood,
        )

        setting = get_config_sphinx_no_bpjs(return_instance=True)
        logger.info(
            {
                'message': 'execute determine_eligibility_by_pgood',
                'function': 'check_bpjs_and_dukcapil_for_turbo',
                'application': application.id,
            }
        )
        determine_eligibility_by_pgood(application, setting)
    return


def process_application_eligibility_check_for_jturbo_j360(application_id, on_check):
    from juloserver.julo_starter.services.services import process_offer_to_j1
    from juloserver.julo_starter.workflow import JuloStarterWorkflowAction

    # No need to detokenize application here,
    # because it only uses `id` and status; and passed it to another function.
    # Do more detokenization if used PII attribute!
    application = Application.objects.get(id=application_id)

    logger.info(
        'process_application_eligibility_check_for_jturbo_j360'
        '|application={}, on_check={}'.format(application_id, on_check)
    )
    if on_check and on_check.fdc_check is not None:
        if on_check.fdc_check == 3:
            process_offer_to_j1(application, 'j360_jturbo_offer_regular_fdc_check')
        elif on_check.fdc_check == 1:
            # user is egligible, can continue to the next step
            # do the logic to continue the 105 post handler logic
            jturbo_action = JuloStarterWorkflowAction(application, None, None, None, None)
            jturbo_action.trigger_anaserver_status105()
        else:
            process_application_status_change(
                application.id,
                ApplicationStatusCodes.APPLICATION_DENIED,
                'bad_fdc_check',
            )
            logger.info(
                {
                    "application_id": application.id,
                    "action": "move to 135 fdc_check failed",
                    "function": "check_fdc_for_turbo_j360",
                    "condition": "bad fdc check",
                    "current_status": application.status,
                }
            )
