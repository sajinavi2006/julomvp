import json
import logging
import re
from builtins import map, str
from datetime import date, datetime, timedelta

import geopy.geocoders
import requests
from cacheops import invalidate_obj
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q, Sum, Case, CharField, Value, When
from django.db.utils import IntegrityError
from django.utils import timezone
from future import standard_library
from geopy.exc import GeopyError
from json_logic import jsonLogic
from rest_framework.status import HTTP_200_OK

from juloserver.account.constants import AccountConstant
from juloserver.ana_api.utils import check_app_cs_v20b
from juloserver.ana_api.models import EligibleCheck
from juloserver.apiv1.serializers import DeviceGeolocationSerializer
from juloserver.apiv1.services import construct_card
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.application_flow.services import (
    SpecialEventSettingHelper,
)
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.models import NameBankValidation
from juloserver.julo.clients.constants import BlacklistCheckStatus
from juloserver.julo.constants import (
    ExperimentConst,
    FalseRejectMiniConst,
    FeatureNameConst,
    FraudModelExperimentConst,
    ScoreTag,
    MobileFeatureNameConst,
)
from juloserver.julo.models import (
    Application,
    ApplicationHistory,
    ApplicationNote,
    ApplicationWorkflowSwitchHistory,
    AppVersion,
    CreditMatrix,
    CreditScore,
    CreditScoreExperiment,
    CustomerAppAction,
    CustomerFieldChange,
    DeviceAppAction,
    Experiment,
    ExperimentAction,
    ExperimentSetting,
    FacebookData,
    FacebookDataHistory,
    FDCInquiry,
    FDCInquiryCheck,
    FDCInquiryLoan,
    FeatureSetting,
    FraudModelExperiment,
    ITIConfiguration,
    Loan,
    MobileFeatureSetting,
    OtpRequest,
    ProductLine,
    ProductProfile,
    ReferralSystem,
    Workflow,
    Customer,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes, ProductLineManager
from juloserver.julo.services2 import (
    get_advance_ai_service,
    get_appsflyer_service,
    get_bypass_iti_experiment_service,
)
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julo.utils import (
    get_float_or_none,
    post_anaserver,
)
from juloserver.julocore.python2.utils import py2round
from juloserver.otp.constants import FeatureSettingName, SessionTokenAction
from juloserver.streamlined_communication.constant import CommunicationPlatform
from juloserver.streamlined_communication.services import process_streamlined_comm

from ..application_flow.services2.shopee_scoring import ShopeeWhitelist
from juloserver.application_flow.services2 import AutoDebit
from .constants import CreditMatrixType, CreditMatrixV19, FDCFieldsName
from .credit_matrix import credit_score_rules
from .credit_matrix2 import (
    credit_score_rules2,
    get_credit_matrix,
    get_good_score,
    get_salaried,
    get_score_product,
)
from .credit_matrix2 import messages as cm2_messages
from .models import (
    AutoDataCheck,
    EtlJob,
    PdCreditModelResult,
    PdFraudModelResult,
    PdWebModelResult,
)
from juloserver.account.constants import FeatureNameConst as AccountFeatureNameConst
from juloserver.customer_module.services.customer_related import (
    is_device_reset_phone_number_rate_limited,
)
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object


standard_library.install_aliases()

logger = logging.getLogger(__name__)


def determine_product_line_v2(customer, product_line_code, loan_duration_request):
    stl_max_duration = ProductLineManager.get_or_none(ProductLineCodes.STL1).max_duration
    paid_loan_exists = customer.loan_set.filter(loan_status=LoanStatusCodes.PAID_OFF)
    if not paid_loan_exists:
        if product_line_code is not None and product_line_code in ProductLineCodes.ctl():
            product_line = ProductLineCodes.CTL1
        elif product_line_code is not None and product_line_code in ProductLineCodes.bri():
            product_line = ProductLineCodes.BRI1
        elif product_line_code is not None and product_line_code in ProductLineCodes.grab():
            product_line = ProductLineCodes.GRAB
        elif product_line_code is not None and product_line_code in ProductLineCodes.loc():
            product_line = ProductLineCodes.LOC
        elif product_line_code is not None and product_line_code in ProductLineCodes.grabfood():
            product_line = ProductLineCodes.GRABF1
        else:
            if int(loan_duration_request) == stl_max_duration:
                product_line = ProductLineCodes.STL1
            else:
                product_line = ProductLineCodes.MTL1
    else:
        if product_line_code is not None and product_line_code in ProductLineCodes.ctl():
            product_line = ProductLineCodes.CTL2
        elif product_line_code is not None and product_line_code in ProductLineCodes.bri():
            product_line = ProductLineCodes.BRI2
        elif product_line_code is not None and product_line_code in ProductLineCodes.grab():
            product_line = ProductLineCodes.GRAB2
        elif product_line_code is not None and product_line_code in ProductLineCodes.loc():
            product_line = ProductLineCodes.LOC
        elif product_line_code is not None and product_line_code in ProductLineCodes.grabfood():
            product_line = ProductLineCodes.GRABF2
        else:
            if int(loan_duration_request) == stl_max_duration:
                product_line = ProductLineCodes.STL2
            else:
                product_line = ProductLineCodes.MTL2
    logger.info(
        {
            'any_paid_off_loan': paid_loan_exists,
            'customer_id': customer.id,
            'loan_duration_request': loan_duration_request,
            'product_line': product_line,
        }
    )
    return product_line


def ready_to_score(application_id):
    """
    Check if data to calculate credit score for application is present
    """
    query = EtlJob.objects.filter(application_id=application_id, status='done')
    data_types = query.values_list('data_type', flat=True)
    if 'dsd' not in data_types:
        return False
    if 'gmail' not in data_types:
        return False
    app_status_query = Application.objects.values_list('application_status_id', flat=True)
    app_status = app_status_query.get(id=application_id)
    if app_status < 105 or app_status == 106:
        return False
    return True


def get_credit_score1(application_id):
    """
    Get credit score from DB or calculate it in anaserver and save to db.
    Returns None if data for the score is not yet available
    """
    credit_score = CreditScore.objects.get_or_none(application_id=application_id)
    if credit_score:
        return credit_score

    if ready_to_score(application_id):
        headers = {'Authorization': 'Token %s' % settings.ANASERVER_TOKEN}
        url = '/api/decision/v1/credit-score/{}/'.format(application_id)
        result = requests.get(settings.ANASERVER_BASE_URL + url, headers=headers)

        if result.status_code != HTTP_200_OK:
            logger.error(
                {
                    'credit-score': 'anaserver returned error',
                    'http-status': result.status_code,
                    'text': result.text,
                }
            )
            return None

        score_result = result.json()
        data = {
            'score': score_result['credit-score'],
            'products': [ProductLineCodes.CTL1],
            'message': '',
        }

        application = Application.objects.get_or_none(pk=application_id)

        if score_result['binary-rules']:
            data['score'] = 'C'
            data['message'] = score_result['binary-rules'][0]['error_message']
            if application.partner and application.partner.is_grab:
                grab_bypass_check = ['application_date_of_birth']
                if score_result['binary-rules'][0]['failed_check'] in grab_bypass_check:
                    data['products'] = [ProductLineCodes.GRAB]
                    data[
                        'message'
                    ] = 'Pilih produk pinjaman Grab & selesaikan pengajuan. Pasti CAIR!'

        else:
            if score_result['credit-score'] == "B+":
                data['message'] = (
                    'Poin kredit Anda sangat bagus. Peluang pengajuan Anda di-ACC besar! '
                    'Silahkan memilih salah satu produk pinjaman di atas & selesaikan '
                    'pengajuan. Tinggal sedikit lagi!'
                )
            if score_result['credit-score'] == "B-":
                data['message'] = (
                    'Poin kredit Anda bagus. Peluang pengajuan Anda di-ACC cukup besar! '
                    'Silahkan memilih salah satu produk pinjaman di atas & selesaikan '
                    'pengajuan. Tinggal sedikit lagi!'
                )

            if application.mantri:
                data['products'] = [ProductLineCodes.BRI1]

            elif application.partner and application.partner.is_grab:
                data['products'] = [ProductLineCodes.GRAB]
                data['message'] = 'Pilih produk pinjaman Grab & selesaikan pengajuan. Pasti CAIR!'

            else:
                if score_result['credit-score'] == "B+":
                    data['products'] = [
                        ProductLineCodes.MTL1,
                        ProductLineCodes.STL1,
                        ProductLineCodes.CTL1,
                    ]
                if score_result['credit-score'] == "B-":
                    data['products'] = [ProductLineCodes.STL1, ProductLineCodes.CTL1]

        try:
            return CreditScore.objects.create(
                application_id=application_id,
                score=data['score'],
                message=data['message'],
                products_str=json.dumps(data['products']),
            )
        except IntegrityError:
            return CreditScore.objects.get(application_id=application_id)


def get_credit_score2(application_id):
    credit_score = CreditScore.objects.get_or_none(application_id=application_id)
    if credit_score:
        return credit_score

    credit_model_result = PdCreditModelResult.objects.filter(application_id=application_id).last()
    if not credit_model_result:
        return None

    application = Application.objects.get(id=application_id)
    rules = credit_score_rules[application.partner_name]
    bypass_checks = rules['bypass_checks']

    if is_customer_has_good_payment_histories(application.customer):
        bypass_check_for_good_customer = ['fraud_form_partial_device', 'fraud_device']
        bypass_checks = set(bypass_checks + bypass_check_for_good_customer)
    failed_checks = AutoDataCheck.objects.filter(application_id=application_id, is_okay=False)
    failed_checks = failed_checks.exclude(data_to_check__in=bypass_checks)
    failed_checks = failed_checks.values_list('data_to_check', flat=True)
    check_order = [
        'fraud_form_partial_device',
        'fraud_device',
        'fraud_form_partial_hp_own',
        'fraud_form_partial_hp_kin',
        'fraud_hp_spouse',
        'job_not_black_listed',
        'application_date_of_birth',
        'form_partial_income',
        'saving_margin',
        'form_partial_location',
        'scraped_data_existence',
        'email_delinquency_24_months',
        'sms_delinquency_24_months',
    ]

    check_rules = rules['checks']
    first_failed_check = None
    score_tag = None
    for check in check_order:
        if check in failed_checks:
            first_failed_check = check
            break

    if first_failed_check:
        rule_to_apply = check_rules[first_failed_check]
        score_tag = ScoreTag.C_FAILED_BINARY
    else:
        score_rules = rules['scores']
        for score in score_rules:
            if (
                score['probability_min']
                <= credit_model_result.probability_fpd
                < score['probability_max']
            ):
                rule_to_apply = score
                break
        if rule_to_apply['score'] == 'C':
            score_tag = ScoreTag.C_LOW_CREDIT_SCORE

    if rule_to_apply['score'] in ['A-', 'B+'] and 2000000 <= application.monthly_income < 3000000:
        rule_to_apply = dict((d["score"], dict(d)) for (index, d) in enumerate(score_rules))['B-']

    partner_exclusive = [
        PartnerConstant.GRAB_PARTNER,
        PartnerConstant.BRI_PARTNER,
        PartnerConstant.GRAB_FOOD_PARTNER,
    ]
    application_score = rule_to_apply['score']

    product_list = get_product_selections(application, application_score)

    if application.partner:
        if application.partner.name in partner_exclusive:
            product_list = rule_to_apply['product_lines']

    # add LOC product to product_list if score is 'A-'
    if ProductLineCodes.LOC not in product_list and application_score in ['A-']:
        product_list.append(ProductLineCodes.LOC)

    # get inside premium area
    inside_premium_area = AutoDataCheck.objects.filter(
        application_id=application_id, data_to_check='inside_premium_area'
    ).last()
    if inside_premium_area is None:
        inside_premium_area = True
    else:
        inside_premium_area = inside_premium_area.is_okay

    try:
        appsflyer_service = get_appsflyer_service()
        appsflyer_service.info_eligible_product(application, product_list)
        return CreditScore.objects.create(
            application_id=application_id,
            score=application_score,
            products_str=json.dumps(product_list),
            message=rule_to_apply['message'],
            inside_premium_area=inside_premium_area,
            score_tag=score_tag,
        )
    except IntegrityError:
        return CreditScore.objects.get(application_id=application_id)


def get_experimental_probability_fpd(experiment, default=0):
    action_status = experiment.experimentaction_set.filter(
        type=ExperimentAction.TYPELIST['CHANGE_CREDIT']
    ).first()
    if action_status and get_float_or_none(action_status.value):
        return get_float_or_none(action_status.value)
    else:
        return default


def get_eta_time_for_c_score_delay(application, now=None):
    if not now:
        now = timezone.localtime(timezone.now())
    app_history_105 = ApplicationHistory.objects.filter(
        application=application, status_new=ApplicationStatusCodes.FORM_PARTIAL
    ).last()
    if not app_history_105:
        return now

    c_score_delay_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DELAY_C_SCORING,
        is_active=True,
    ).last()

    first_at_105 = timezone.localtime(app_history_105.cdate)
    if not c_score_delay_feature:
        return now
    delay_in_hour = int(c_score_delay_feature.parameters['hours'].split(':')[0])
    delay_in_minutes = int(c_score_delay_feature.parameters['hours'].split(':')[1])
    if c_score_delay_feature.parameters['exact_time']:
        return (first_at_105 + timedelta(days=1)).replace(
            hour=delay_in_hour, minute=delay_in_minutes
        )
    return first_at_105 + timedelta(hours=delay_in_hour, minutes=delay_in_minutes)


def is_c_score_in_delay_period(application):
    if not hasattr(application, 'creditscore'):
        return False
    if application.creditscore.score.upper() != 'C':
        return False
    end_of_delay = get_eta_time_for_c_score_delay(application)
    return timezone.localtime(timezone.now()) < end_of_delay


def is_email_whitelisted_to_force_high_score(email):
    if not email:
        return False
    feature_high_score = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FORCE_HIGH_SCORE, is_active=True
    ).last()
    if not feature_high_score:
        return False
    return email in feature_high_score.parameters


def get_credit_score3(application, minimum_false_rejection=False, skip_delay_checking=False):
    from juloserver.account.services.credit_limit import get_credit_matrix_type
    from juloserver.account.services.credit_matrix import get_good_score_j1
    from juloserver.julo.services import (
        experimentation_false_reject_min_exp,
        is_credit_experiment,
    )
    from juloserver.application_flow.tasks import application_tag_tracking_task

    if not isinstance(application, Application):
        application = Application.objects.get(pk=application)

    def get_credit_model_result(application):
        credit_score_type = 'B' if check_app_cs_v20b(application) else 'A'
        credit_model_result = PdCreditModelResult.objects.filter(
            application_id=application.id, credit_score_type=credit_score_type
        ).last()

        # get model for web app
        if application.is_julo_one():
            credit_matrix_type = get_credit_matrix_type(application, is_proven=False)

            if credit_model_result:
                if credit_model_result.product == 'non-repeat-fdc':
                    application_tag_tracking_task(
                        application.id, None, None, None, 'is_good_fdc_el', 1
                    )

                has_fdc = credit_model_result.has_fdc
                application_tag_tracking_task(application.id, None, None, None, 'is_fdc', has_fdc)
        else:
            if not application.customer.is_repeated:
                credit_matrix_type = CreditMatrixType.JULO
            else:
                credit_matrix_type = CreditMatrixType.JULO_REPEAT

        if not credit_model_result:
            credit_model_webapp = PdWebModelResult.objects.filter(
                application_id=application.id
            ).last()

            if credit_model_webapp:
                credit_model_result = credit_model_webapp

                leadgen_partners = dict()
                feature_setting = FeatureSetting.objects.filter(
                    is_active=True,
                    feature_name=FeatureNameConst.LEAD_GEN_PARTNER_CREDIT_SCORE_GENERATION,
                ).last()
                if feature_setting:
                    leadgen_partners = feature_setting.parameters['partners']

                if (
                    not application.is_partnership_app()
                    and application.partner_name not in leadgen_partners
                ):
                    credit_matrix_type = CreditMatrixType.WEBAPP

        return credit_matrix_type, credit_model_result

    # detokenize in here for application
    detokenized_application = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [{'object': application, "customer_id": application.customer_id}],
        force_get_local_data=True,
    )
    application = detokenized_application[0]

    credit_score = CreditScore.objects.get_or_none(application_id=application.id)
    credit_matrix_id = None

    if credit_score:
        logger.info(
            {
                "message": "get_credit_score3: found credit score",
                "score": credit_score.id,
                "application_id": application.id,
            }
        )
        if not credit_score.model_version:
            _, credit_model_result = get_credit_model_result(application)
            if credit_model_result:
                credit_score.model_version = credit_model_result.version
                credit_score.save()
                credit_score.refresh_from_db()

        if credit_score.score == 'C':
            if minimum_false_rejection:
                experimentation_false_reject_min_exp(application)
            if is_c_score_in_delay_period(application) and not skip_delay_checking:
                return None
        return credit_score

    credit_matrix_type, credit_model_result = get_credit_model_result(application)
    
    # Shadow Score CLIK non FDC
    non_fdc_criteria = ['repeat-fdc', 'non-repeat-fdc']
    is_fdc = credit_model_result and credit_model_result.has_fdc
    if not application.partner:
        if (
            application.is_julo_one_product()
            and credit_model_result
            and credit_model_result.product not in non_fdc_criteria
        ):
            from juloserver.application_flow.services2.clik import CLIKClient

            clik = CLIKClient(application)
            clik.process_shadow_score()

    eligible_good_fdc = EligibleCheck.objects.filter(
        check_name='eligible_good_fdc',
        application_id=application.id,
    ).last()
    is_good_fdc = False
    is_good_fdc_bypass = False

    if eligible_good_fdc and eligible_good_fdc.is_okay:
        is_good_fdc = eligible_good_fdc.is_okay
        is_good_fdc_bypass = eligible_good_fdc.is_okay

    have_experiment = {'is_experiment': False, 'experiment': None}
    partner_name = application.partner_name
    feature_setting = FeatureSetting.objects.filter(
        is_active=True, feature_name=FeatureNameConst.LEAD_GEN_PARTNER_CREDIT_SCORE_GENERATION
    ).last()
    if feature_setting:
        leadgen_partners = feature_setting.parameters['partners']
        if partner_name in leadgen_partners:
            partner_name = PartnerNameConstant.GENERIC
    if application.is_partnership_app():
        partner_name = None
    rules = credit_score_rules2[partner_name]
    bypass_checks = rules['bypass_checks']

    # experiment  remove own_phone binary check
    today = timezone.now().date()
    experiment = Experiment.objects.filter(
        is_active=True,
        date_start__lte=today,
        date_end__gte=today,
        code=ExperimentConst.IS_OWN_PHONE_EXPERIMENT,
    ).last()
    if experiment:
        bypass_checks += ['own_phone']

    if is_customer_has_good_payment_histories(application.customer):
        bypass_check_for_good_customer = ['fraud_form_partial_device', 'fraud_device']
        bypass_checks = set(bypass_checks + bypass_check_for_good_customer)
    failed_checks = AutoDataCheck.objects.filter(application_id=application.id, is_okay=False)
    failed_checks = failed_checks.exclude(data_to_check__in=bypass_checks)
    failed_checks = failed_checks.values_list('data_to_check', flat=True)
    failed_checks, fdc_inquiry_check = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
        credit_model_result, list(failed_checks), application
    )
    check_order = CreditMatrixV19.BINARY_CHECK_SHORT + CreditMatrixV19.BINARY_CHECK_LONG
    check_rules = rules['checks']
    first_failed_check = None
    score_tag = None
    credit_matrix_version = None

    skip_special_event = SpecialEventSettingHelper().is_no_bypass()

    checking_fraud_email_and_ktp(application, failed_checks)

    for check in check_order:
        if check in failed_checks:
            if check != 'special_event' or not skip_special_event:
                first_failed_check = check
                break
    # feature to force credit score to A-
    is_premium_area = is_inside_premium_area(application.id)
    if is_premium_area is None:
        return None
    # force to A- event binary check failed
    if is_email_whitelisted_to_force_high_score(application.email):
        probability_fpd = 0.98
        repeat_time = (
            Loan.objects.get_queryset().paid_off().filter(customer=application.customer).count()
        )
        custom_matrix_parameters = {'repeat_time': repeat_time}
        if application.job_industry:
            custom_matrix_parameters['job_industry'] = application.job_industry
        if application.is_julo_one():
            (
                score,
                product_list,
                message,
                score_tag,
                credit_matrix_version,
                credit_matrix_id,
            ) = get_good_score_j1(
                probability_fpd,
                application.job_type,
                is_premium_area,
                is_fdc,
                credit_matrix_type,
            )

        else:
            (
                score,
                product_list,
                message,
                score_tag,
                credit_matrix_version,
                credit_matrix_id,
            ) = get_good_score(
                probability_fpd,
                application.job_type,
                custom_matrix_parameters,
                is_premium_area,
                is_fdc,
                credit_matrix_type,
            )
        ApplicationNote.objects.create(
            application_id=application.id,
            note_text='Bypass Using Force High Credit Score Feature',
        )
    elif first_failed_check and credit_model_result:
        if first_failed_check in CreditMatrixV19.BINARY_CHECK_LONG:
            if first_failed_check == 'monthly_income':
                rule_to_apply = check_rules[first_failed_check]
            else:
                rule_to_apply = check_rules['long_form_binary_checks']
        else:
            rule_to_apply = check_rules[first_failed_check]

        message = rule_to_apply['message']
        product_list = rule_to_apply['product_lines']
        score = rule_to_apply['score']
        score_tag = ScoreTag.C_FAILED_BINARY
        credit_matrix_version = CreditMatrix.objects.get_current_version(score, score_tag)
    else:
        if not credit_model_result:
            return None

        # check experiment or not
        have_experiment = is_credit_experiment(
            application=application, probability_fpd=credit_model_result.probability_fpd
        )
        if have_experiment['is_experiment']:
            probability_fpd = get_experimental_probability_fpd(
                have_experiment['experiment'], default=credit_model_result.probability_fpd
            )
        else:
            # try to use pgood value instead of probability_fpd
            probability_fpd = (
                getattr(credit_model_result, 'pgood', None) or credit_model_result.probability_fpd
            )

        repeat_time = (
            Loan.objects.get_queryset().paid_off().filter(customer=application.customer).count()
        )
        custom_matrix_parameters = {'repeat_time': repeat_time}
        if application.job_industry:
            custom_matrix_parameters['job_industry'] = application.job_industry
        if application.is_julo_one():

            (
                score,
                product_list,
                message,
                score_tag,
                credit_matrix_version,
                credit_matrix_id,
            ) = get_good_score_j1(
                probability_fpd,
                application.job_type,
                is_premium_area,
                is_fdc,
                credit_matrix_type,
            )

        else:
            (
                score,
                product_list,
                message,
                score_tag,
                credit_matrix_version,
                credit_matrix_id,
            ) = get_good_score(
                probability_fpd,
                application.job_type,
                custom_matrix_parameters,
                is_premium_area,
                is_fdc,
                credit_matrix_type,
            )

    # Good FDC Bypass interception
    good_fdc_not_allowed_binary = ['application_date_of_birth', 'blacklist_customer_check']
    if is_good_fdc_bypass:
        for check in good_fdc_not_allowed_binary:
            if check in failed_checks:
                is_good_fdc_bypass = False
                break

    # try to use pgood value instead of probability_fpd
    probability_fpd = (
        getattr(credit_model_result, 'pgood', None) or credit_model_result.probability_fpd
    )

    from juloserver.application_flow.services import (
        is_offline_activation,
        not_eligible_offline_activation,
    )

    experiment_setting = ExperimentSetting.objects.get_or_none(
        code=ExperimentConst.OFFLINE_ACTIVATION_REFERRAL_CODE
    )

    # additional check for offline users
    if is_offline_activation(application):
        from dateutil import relativedelta

        age_threshold = experiment_setting.criteria.get('age')
        income_threshold = experiment_setting.criteria.get('income')
        salaried_setting = experiment_setting.criteria.get('salaried')

        job_type = application.job_type
        is_salaried = get_salaried(job_type)

        today = date.today().year
        dob = application.dob.year
        age = today - dob

        check_age = age >= age_threshold
        check_income = application.monthly_income > income_threshold
        check_salaried = is_salaried if salaried_setting else True

        if not (check_salaried and check_age and check_income):
            not_eligible_offline_activation(application)
            logger.info(
                {
                    "message": "get_credit_score3: not_eligible_offline_activation",
                    "application_id": application.id,
                    "age": age,
                    "is_salaried": is_salaried,
                    "income": application.monthly_income,
                }
            )

    logger.info(
        {
            "message": "get_credit_score3: score info",
            "score": score,
            "application_id": application.id,
        }
    )

    # add LOC product to product_list if score is 'A-'
    if score == 'A-':
        product_list.append(ProductLineCodes.LOC)

    score, score_tag = override_score_for_failed_dynamic_check(application, score, score_tag)

    # clik model swap in
    from juloserver.application_flow.services import clik_model_decision
    clik_decision = clik_model_decision(application)
    score = 'C' if clik_decision == 'swapout' else score

    if score in ['C', '--']:

        if is_good_fdc_bypass:
            application_tag_tracking_task(application.id, None, None, None, 'is_good_fdc_bypass', 1)

        credit_matrix = get_credit_matrix_c_score_interception(
            application,
            score=score,
            product_list=product_list,
            message=message,
            score_tag=score_tag,
            version=credit_matrix_version,
            credit_matrix_id=credit_matrix_id,
            is_premium_area=is_premium_area,
            probability_fpd=probability_fpd,
            job_type=application.job_type,
            credit_matrix_type=credit_matrix_type,
            is_good_fdc_bypass=is_good_fdc_bypass,
            fdc_inquiry_check=fdc_inquiry_check,
            clik_decision=clik_decision,
            is_fdc=is_fdc,
        )

        score = credit_matrix.score
        score_tag = credit_matrix.score_tag
        message = credit_matrix.message
        credit_matrix_version = credit_matrix.version
        credit_matrix_id = credit_matrix.id
        product_list = credit_matrix.list_product_lines

        credit_score = store_credit_score_to_db(
            application,
            product_list,
            score,
            message,
            score_tag,
            credit_model_result,
            credit_matrix_version,
            credit_matrix_id,
            fdc_inquiry_check=fdc_inquiry_check,
        )

        # false reject minimization Experiment
        if minimum_false_rejection:
            experimentation_false_reject_min_exp(application)

        if is_c_score_in_delay_period(application) and not skip_delay_checking:
            return None

        return credit_score
    else:
        logger.info(
            {
                "message": "get_credit_score3: get non-C score",
                "score": score,
                "application_id": application.id,
            }
        )
        if application:
            advance_ai_service = get_advance_ai_service()
            blacklist_status = BlacklistCheckStatus.PASS
            blacklist_feature = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.BLACKLIST_CHECK, category="experiment", is_active=True
            ).last()

            if blacklist_feature:
                blacklist_status = advance_ai_service.run_blacklist_check(application)

            date_now = timezone.localtime(timezone.now()).date()
            fraud_model_exp_active = Experiment.objects.filter(
                is_active=True,
                code=ExperimentConst.FRAUD_MODEL_105,
                date_start__lte=date_now,
                date_end__gte=date_now,
            ).last()

            fraud_model_feature = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.FRAUD_MODEL_EXPERIMENT,
                category="experiment",
                is_active=True,
            ).last()

            pf_fraud = PdFraudModelResult.objects.filter(application_id=application.id).last()
            fraud_model_check = False
            if pf_fraud and fraud_model_feature:
                low_probability_fpd = fraud_model_feature.parameters.get('low_probability_fpd')
                high_probability_fpd = fraud_model_feature.parameters.get('high_probability_fpd')
                if (
                    pf_fraud.probability_fpd
                    and pf_fraud.probability_fpd >= low_probability_fpd
                    and pf_fraud.probability_fpd <= high_probability_fpd
                ):
                    fraud_model_check = True

            advance_ai_blacklist = False
            if blacklist_status != BlacklistCheckStatus.PASS:
                advance_ai_blacklist = True

            probability_fpd = 0
            if pf_fraud and pf_fraud.probability_fpd:
                probability_fpd = pf_fraud.probability_fpd
            fraud_model_exp = FraudModelExperiment.objects.create(
                application=application,
                fraud_model_check=not fraud_model_check,
                advance_ai_blacklist=not advance_ai_blacklist,
                fraud_model_value=probability_fpd,
                customer=application.customer,
            )

            if (advance_ai_blacklist or fraud_model_check) and fraud_model_exp_active:
                fraud_model_exp.is_fraud_experiment_period = True
                fraud_model_exp.save()

            if (advance_ai_blacklist or fraud_model_check) and not fraud_model_exp_active:
                score = 'C'
                message = cm2_messages['C_score_and_passed_binary_check']
                product_list = [ProductLineCodes.CTL1]
                score_tag = ScoreTag.C_FAILED_BLACK_LIST
                credit_matrix_version = CreditMatrix.objects.get_current_version(score, score_tag)

            score, score_tag = override_score_for_failed_dynamic_check(
                application, score, score_tag
            )

            if score == 'C':
                if is_good_fdc_bypass:
                    application_tag_tracking_task(
                        application.id, None, None, None, 'is_good_fdc_bypass', 1
                    )
            else:
                if is_good_fdc:
                    application_tag_tracking_task(
                        application.id, None, None, None, 'is_good_fdc', 1
                    )

            # If the application has a C score up to this point, then revive it by recalculating
            # the Credit Matrix using a set of revival logic.
            credit_matrix = get_credit_matrix_c_score_interception(
                application,
                score=score,
                product_list=product_list,
                message=message,
                score_tag=score_tag,
                version=credit_matrix_version,
                credit_matrix_id=credit_matrix_id,
                is_premium_area=is_premium_area,
                probability_fpd=probability_fpd,
                job_type=application.job_type,
                credit_matrix_type=credit_matrix_type,
                is_good_fdc_bypass=is_good_fdc_bypass,
                fdc_inquiry_check=fdc_inquiry_check,
                clik_decision=clik_decision,
                is_fdc=is_fdc,
            )

            score = credit_matrix.score
            score_tag = credit_matrix.score_tag
            message = credit_matrix.message
            credit_matrix_version = credit_matrix.version
            credit_matrix_id = credit_matrix.id
            product_list = credit_matrix.list_product_lines

            return store_credit_score_to_db(
                application,
                product_list,
                score,
                message,
                score_tag,
                credit_model_result,
                credit_matrix_version,
                credit_matrix_id,
                experimental=have_experiment['experiment'],
                fdc_inquiry_check=fdc_inquiry_check,
            )


def store_credit_score_to_db(
    application,
    product_list,
    score,
    message,
    score_tag,
    credit_model_result,
    credit_matrix_version,
    credit_matrix_id=None,
    experimental=False,
    fdc_inquiry_check=None,
):
    # get inside premium area
    inside_premium_area = is_inside_premium_area(application.id)
    if credit_matrix_id:
        credit_matrix = CreditMatrix.objects.get_or_none(id=credit_matrix_id)
        inside_premium_area = (
            inside_premium_area if not credit_matrix else credit_matrix.is_premium_area
        )

    try:
        appsflyer_service = get_appsflyer_service()
        appsflyer_service.info_eligible_product(application, product_list)

        model_version = None
        if credit_model_result:
            model_version = credit_model_result.version

        credit_score = CreditScore.objects.create(
            application_id=application.id,
            score=score,
            products_str=json.dumps(product_list),
            message=message,
            inside_premium_area=inside_premium_area,
            score_tag=score_tag,
            credit_matrix_version=credit_matrix_version,
            model_version=model_version,
            fdc_inquiry_check=fdc_inquiry_check,
            credit_matrix_id=credit_matrix_id,
        )

        if experimental:
            CreditScoreExperiment.objects.create(credit_score=credit_score, experiment=experimental)
        if fdc_inquiry_check is not None:
            url = '/api/amp/v1/update-auto-data-check/'
            post_anaserver(
                url, json={'application_id': application.id, 'is_okay': fdc_inquiry_check}
            )

        return credit_score
    except IntegrityError:
        return CreditScore.objects.get(application_id=application.id)


def override_score_for_failed_dynamic_check(application, score, score_tag):
    if application.is_regular_julo_one() or application.is_julo_one_ios():
        if score is not None:
            if is_email_whitelisted_to_force_high_score(application.email):
                return score, score_tag
            not_pass_dynamic_check = AutoDataCheck.objects.filter(
                application_id=application.id,
                data_to_check='dynamic_check',
                is_okay=False,
                latest=True,
            )
            if not_pass_dynamic_check and score != 'C':
                score = 'C'
                score_tag = 'c_failed_dynamic_check'

    return score, score_tag


def get_credit_matrix_c_score_interception(application: Application, **kwargs) -> CreditMatrix:
    """
    Recalculate the credit matrix to match revival condition such as Good FDC Bypass, Click,
    auto debit, Shopee whitelist, and Tokoscore.
    """

    from juloserver.application_flow.services import (
        check_good_fdc_bypass,
        _update_failed_good_fdc_bypass,
        eligible_to_offline_activation_flow,
        eligible_waitlist,
        eligible_entry_level_swapin,
    )
    from juloserver.tokopedia.constants import TokoScoreConst
    from juloserver.tokopedia.services.common_service import (
        is_passed_tokoscore,
        fetch_credit_matrix_and_move_application,
    )
    from juloserver.application_flow.services import pass_binary_check_scoring

    logger.info(
        {
            "message": "get_credit_matrix_c_score_interception",
            "application_id": application.id,
            "kwargs": kwargs,
        }
    )

    original = CreditMatrix()
    original.id = kwargs["credit_matrix_id"]
    original.score = kwargs["score"]
    original.message = kwargs["message"]
    original.score_tag = kwargs["score_tag"]
    original.version = kwargs["version"]
    is_fdc = kwargs.get('is_fdc', None)
    fdc_inquiry_check = kwargs.get('fdc_inquiry_check', None)

    low_pgood_threshold = 0.51

    if application.status != ApplicationStatusCodes.FORM_PARTIAL:
        return original
        
    # Good FDC Bypass - begin #
    is_good_fdc_bypass = kwargs["is_good_fdc_bypass"]
    allowed_tag_good_fdc = ["c_failed_binary", "c_low_credit_score", "c_failed_dynamic_check"]

    # Check if has C score
    if kwargs["score"] != 'C':
        if is_good_fdc_bypass:
            _update_failed_good_fdc_bypass(application)
            logger.info(
                {
                    "message": "get_credit_matrix_c_score_interception: "
                    "_update_failed_good_fdc_bypass",
                    "application_id": application.id,
                    "is_good_fdc_bypass": is_good_fdc_bypass,
                }
            )
        return original

    from juloserver.cfs.services.core_services import get_pgood
    from juloserver.account.services.credit_limit import (
        get_credit_matrix,
        get_transaction_type,
    )
    from juloserver.application_flow.tasks import application_tag_tracking_task

    probability_fpd = get_pgood(application.id)
    is_premium_area = kwargs["is_premium_area"]
    job_type = application.job_type
    is_salaried = get_salaried(job_type)
    params = {
        "min_threshold__lte": probability_fpd,
        "max_threshold__gte": probability_fpd,
        "credit_matrix_type": "julo1",
        "is_salaried": is_salaried,
        "is_premium_area": is_premium_area,
        "is_fdc": is_fdc,
    }

    # clik model swap in
    if kwargs["clik_decision"] == 'swapin':
        cm_parameter = 'feature:is_clik_model'
        cm = get_credit_matrix(
            params,
            get_transaction_type(),
            parameter=Q(parameter=cm_parameter),
        )
        logger.info(
            {
                "message": "get_credit_matrix_c_score_interception: clik model swap in",
                "application_id": application.id,
                "params": params,
                "credit_matrix": cm,
            }
        )
        return cm

    # waitlist swap in
    if eligible_waitlist(application.id) and not application.partner:
        cm = get_credit_matrix(
            params,
            get_transaction_type(),
        )

        logger.info(
            {
                "message": "get_credit_matrix_c_score_interception: get_credit_matrix waitlist",
                "application_id": application.id,
                "params": params,
                "credit_matrix": cm,
            }
        )

        return cm

    # Offline Activation not going to swap in
    if eligible_to_offline_activation_flow(application):
        failed_dynamic_check = kwargs["score_tag"] == "c_failed_dynamic_check"

        cm_parameter = 'feature:good_fdc_bypass'

        if not failed_dynamic_check:
            cm = get_credit_matrix(
                params,
                get_transaction_type(),
                parameter=Q(parameter=cm_parameter),
            )
            application_tag_tracking_task(
                application.id, None, None, None, 'is_offline_activation_low_pgood', 1
            )
        else:
            cm = get_credit_matrix(
                params,
                get_transaction_type(),
            )
        return cm

    # Good Referral

    is_good_referral_check = EligibleCheck.objects.filter(
        check_name='eligible_good_referral',
        application_id=application.id,
    ).last()

    is_good_referral = None if not is_good_referral_check else is_good_referral_check.is_okay

    logger.info(
        {
            "message": "get_credit_score3: is_good_referral info",
            "is_good_referral.is_okay": is_good_referral,
            "application_id": application.id,
        }
    )

    if is_good_referral and probability_fpd >= low_pgood_threshold:
        from juloserver.fraud_security.tasks import check_high_risk_asn

        application_tag_tracking_task(application.id, None, None, None, 'is_good_referral', 1)

        cm = get_credit_matrix(
            params,
            get_transaction_type(),
        )

        logger.info(
            {
                "message": "get_credit_matrix_c_score_interception: get_credit_matrix good ref",
                "application_id": application.id,
                "params": params,
                "credit_matrix": cm,
            }
        )

        check_high_risk_asn(application.id)

        return cm

    if eligible_entry_level_swapin(application.id):
        params = {
            "min_threshold__lte": probability_fpd,
            "max_threshold__gte": probability_fpd,
            "credit_matrix_type": "julo1_entry_level",
            "is_salaried": is_salaried,
            "is_premium_area": is_premium_area,
            "is_fdc": is_fdc,
        }

        cm = get_credit_matrix(
            params,
            get_transaction_type(),
        )

        logger.info(
            {
                "message": "get_credit_matrix_c_score_interception: eligible_entry_level_swapin",
                "application_id": application.id,
                "params": params,
                "credit_matrix": cm,
            }
        )
        application_tag_tracking_task(application.id, None, None, None, 'is_entry_level_swapin', 1)        
        return cm

    if not pass_binary_check_scoring(application):
        return original

    # Good FDC Bypass CM
    if check_good_fdc_bypass(application) and kwargs["score_tag"] in allowed_tag_good_fdc:
        cm_parameter = 'feature:good_fdc_bypass'
        cm = get_credit_matrix(
            params,
            get_transaction_type(),
            parameter=Q(parameter=cm_parameter),
        )

        logger.info(
            {
                "message": "get_credit_matrix_c_score_interception: get_credit_matrix",
                "application_id": application.id,
                "params": params,
                "credit_matrix": cm,
            }
        )

        return cm
    # Good FDC Bypass - end #

    # CLIK - begin #
    from juloserver.application_flow.services2.clik import CLIKClient
    from juloserver.cfs.services.core_services import get_pgood

    clik = CLIKClient(application)
    eligibile_swap_in = clik.process_swap_in()

    if eligibile_swap_in:
        cm = get_credit_matrix(
            params,
            get_transaction_type(),
        )

        logger.info(
            {
                "message": "get_credit_matrix_c_score_interception: get_credit_matrix CLIK",
                "application_id": application.id,
                "params": params,
                "credit_matrix": cm,
            }
        )

        return cm
    # CLIK - end #

    # Telco - begin #
    from juloserver.application_flow.services2.telco_scoring import TelcoScore

    telco = TelcoScore(application=application)
    eligible_swap_in = telco.run_in_105()

    if eligible_swap_in:
        cm = get_credit_matrix(
            params,
            get_transaction_type(),
        )

        logger.info(
            {
                "message": "get_credit_matrix_c_score_interception: get_credit_matrix Telco",
                "application_id": application.id,
                "params": params,
                "credit_matrix": cm,
            }
        )

        return cm
    # Telco - end #

    # The exceptional C score #
    if kwargs["score_tag"] not in ("c_low_credit_score", "c_failed_dynamic_check"):
        return original

    # Here we try to intercept Shopee Whitelist.
    # There are some intersection logic between shopee and autodebit.
    shopee_whitelist = ShopeeWhitelist(application, stay=True)
    shopee_whitelist.is_premium_area = kwargs["is_premium_area"]
    if shopee_whitelist.run():
        return shopee_whitelist.credit_matrix

    # Tokoscore - begin #
    is_passed_tokoscore = is_passed_tokoscore(application, is_available_fdc_check=fdc_inquiry_check)
    if is_passed_tokoscore == TokoScoreConst.KEY_PASSED:
        return fetch_credit_matrix_and_move_application(
            application=application,
            key_for_passed=is_passed_tokoscore,
            origin_credit_matrix=original,
            move_status=False,
        )

    autodebit = AutoDebit(application)
    autodebit.is_premium_area = kwargs["is_premium_area"]

    from juloserver.bpjs.services.bpjs_direct import generate_bpjs_scoring, is_bpjs_found_by_nik

    mfs = MobileFeatureSetting.objects.filter(feature_name="bpjs_direct", is_active=True).last()
    result = 'bpjs_direct_check_not_found'
    if mfs:
        result = generate_bpjs_scoring(application, True)

    if result == 'bpjs_direct_check_not_found':
        is_assigned = autodebit.decide_to_assign_tag()
        if is_assigned:
            return autodebit.credit_matrix
    elif result == 'bpjs_direct_nik_found' and is_bpjs_found_by_nik(application):
        return autodebit.credit_matrix

    return original


def is_customer_has_good_payment_histories(customer):
    apps = customer.application_set.filter(loan__loan_status=LoanStatusCodes.PAID_OFF)
    result = False
    for app in apps:
        payments = app.loan.payment_set.all()
        all_statuses = list([x.payment_status.status_code for x in payments])
        result = not any(status == PaymentStatusCodes.PAID_LATE for status in all_statuses)
    return result


def is_customer_paid_on_time(customer, application_id):
    app = customer.application_set.filter(
        id=application_id, loan__loan_status=LoanStatusCodes.PAID_OFF
    ).first()
    result = False
    if app:
        payments = app.loan.payment_set.all()
        all_statuses = [pay.payment_status.status_code for pay in payments]
        result = all(status == PaymentStatusCodes.PAID_ON_TIME for status in all_statuses)
    return result


def get_customer_app_actions(customer, app_version=None):
    upgrade_action = CustomerAppAction.objects.filter(
        customer=customer, action__in=['force_upgrade', 'warning_upgrade'], is_completed=False
    )

    latest_version = AppVersion.objects.get(status='latest')
    if latest_version.app_version == app_version:
        upgrade_action.update(is_completed=True)

    customer_app_actions = CustomerAppAction.objects.filter(customer=customer, is_completed=False)

    def sort_actions(element):
        action_order = [
            'sell_off',
            'force_upgrade',
            'force_logout',
            'rescrape',
            'warning_upgrade',
            'autodebet_bca_reactivation',
            'autodebet_bri_reactivation',
            'autodebet_gopay_reactivation',
            'autodebet_bni_reactivation',
            'autodebet_mandiri_reactivation',
            'autodebet_dana_reactivation',
            'autodebet_ovo_reactivation',
        ]
        return action_order.index(element)

    actions = [action.action for action in customer_app_actions]
    actions.sort(key=sort_actions)

    if app_version:
        version_entry = AppVersion.objects.get(app_version=app_version)
        if version_entry.status == 'not_supported':
            if 'force_upgrade' not in actions:
                actions.append('force_upgrade')
                actions.sort(key=sort_actions)
        elif version_entry.status == 'deprecated':
            if 'warning_upgrade' not in actions:
                actions.append('warning_upgrade')
                actions.sort(key=sort_actions)
        # selloff j1
        sell_off_action = CustomerAppAction.objects.filter(
            customer=customer, action='sell_off', is_completed=False
        )
        j1_selloff_config = FeatureSetting.objects.get_or_none(
            is_active=True, feature_name=AccountFeatureNameConst.ACCOUNT_SELLOFF_CONFIG
        )
        if (
            sell_off_action
            and j1_selloff_config
            and j1_selloff_config.parameters.get('is_force_upgrade_active', False)
        ):
            selloff_param = j1_selloff_config.parameters
            selloff_apps_minimum_version = AppVersion.objects.filter(
                app_version=selloff_param['force_upgrade_apps_threshold']
            ).last()
            if selloff_apps_minimum_version and version_entry.id >= selloff_apps_minimum_version.id:
                sell_off_action.update(is_completed=True)
            elif (
                selloff_apps_minimum_version
                and version_entry.id < selloff_apps_minimum_version.id
                and 'force_upgrade' not in actions
            ):
                actions.append('force_upgrade')
                actions.sort(key=sort_actions)

    return ({'actions': actions}) if actions else ({'actions': None})


def get_device_app_actions(device, app_version=None):
    upgrade_action = DeviceAppAction.objects.filter(
        device__android_id=device.android_id,
        action__in=['force_upgrade', 'warning_upgrade'],
        is_completed=False,
    )

    latest_version = AppVersion.objects.get(status='latest')
    if latest_version.app_version == app_version:
        upgrade_action.update(is_completed=True)

    device_app_actions = DeviceAppAction.objects.filter(
        device__android_id=device.android_id, is_completed=False
    ).distinct('action')

    def sort_actions(element):
        action_order = ['sell_off', 'force_upgrade', 'force_logout', 'rescrape', 'warning_upgrade']
        return action_order.index(element)

    actions = [action.action for action in device_app_actions]
    actions.sort(key=sort_actions)

    if app_version:
        version_entry = AppVersion.objects.get(app_version=app_version)
        if version_entry.status == 'not_supported':
            if 'force_upgrade' not in actions:
                actions.append('force_upgrade')
                actions.sort(key=sort_actions)
        elif version_entry.status == 'deprecated':
            if 'warning_upgrade' not in actions:
                actions.append('warning_upgrade')
                actions.sort(key=sort_actions)

    return ({'actions': actions}) if actions else ({'actions': None})


def generate_address_from_geolocation(address_geolocation):
    latitude = address_geolocation.latitude
    longitude = address_geolocation.longitude
    geocoder = geopy.geocoders.GoogleV3(api_key=settings.GOOGLE_MAPS_API_KEY)
    try:
        location = geocoder.geocode('%s, %s' % (latitude, longitude))
    except GeopyError as gu:
        logger.error({'status': str(gu), 'service': 'google_maps', 'error_type': str(type(gu))})
        return
    except Exception as e:
        logger.error({'status': str(e), 'error_type': str(type(e))})
        return
    if not location:
        logger.error({'status': "Location not found", 'lat, lon': (latitude, longitude)})
        return

    address_components = location.raw['address_components']
    if is_indonesia(address_components):
        for component in address_components:
            if 'administrative_area_level_4' in component['types']:
                address_geolocation.kelurahan = component['long_name']
            if 'administrative_area_level_3' in component['types']:
                address_geolocation.kecamatan = component['long_name']
            if 'administrative_area_level_2' in component['types']:
                address_geolocation.kabupaten = component['long_name']
            if 'administrative_area_level_1' in component['types']:
                address_geolocation.provinsi = component['long_name']
            if 'postal_code' in component['types']:
                address_geolocation.kodepos = get_postalcode(component['long_name'])

    address_geolocation.save()
    invalidate_obj(address_geolocation)


def get_product_selections(application, application_score):
    # run matching product selection here
    today_date = date.today()
    application_age = today_date.year - application.dob.year
    if today_date.month == application.dob.month:
        if today_date.day < application.dob.day:
            application_age -= 1
    elif today_date.month < application.dob.month:
        application_age -= 1

    income_amount = application.monthly_income
    # loan_amount_request = application.loan_amount_request
    # loan_duration_request = application.loan_duration_request
    job_type = application.job_type
    job_industry = application.job_industry
    job_description = application.job_description

    product_profile_list = ProductProfile.objects.filter(
        Q(is_active=True)
        & Q(is_initial=True)
        & Q(is_product_exclusive=False)
        & (
            Q(productcustomercriteria__credit_score__isnull=True)
            | Q(productcustomercriteria__credit_score=[])
            | Q(productcustomercriteria__credit_score__contains=[application_score])
        )
        & (
            Q(productcustomercriteria__min_age__isnull=True)
            | Q(productcustomercriteria__min_age__lte=application_age)
        )
        & (
            Q(productcustomercriteria__max_age__isnull=True)
            | Q(productcustomercriteria__max_age__gte=application_age)
        )
        & (
            Q(productcustomercriteria__min_income__isnull=True)
            | Q(productcustomercriteria__min_income__lte=income_amount)
        )
        & (
            Q(productcustomercriteria__max_income__isnull=True)
            | Q(productcustomercriteria__max_income__gte=income_amount)
        )
        & (
            Q(productcustomercriteria__job_type__isnull=True)
            | Q(productcustomercriteria__job_type=[])
            | Q(productcustomercriteria__job_type__contains=[job_type])
        )
        & (
            Q(productcustomercriteria__job_industry__isnull=True)
            | Q(productcustomercriteria__job_industry=[])
            | Q(productcustomercriteria__job_industry__contains=[job_industry])
        )
        & (
            Q(productcustomercriteria__job_description__isnull=True)
            | Q(productcustomercriteria__job_description=[])
            | Q(productcustomercriteria__job_description__contains=[job_description])
        )
    )

    product_list = [product.productline.product_line_code for product in product_profile_list]

    return product_list


def get_last_application(customer):
    application = (
        customer.application_set.filter(
            application_status__status_code__gte=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        )
        .order_by('cdate')
        .last()
    )
    return application


def check_fraud_model_exp(application):
    show = False
    fraud_experiment = FraudModelExperiment.objects.filter(
        application_id=application.id, is_fraud_experiment_period=True
    ).last()
    if fraud_experiment:
        show = True
    return show


def false_reject_min_exp(application):
    show = False
    application_experiment = application.applicationexperiment_set.filter(
        experiment__code=ExperimentConst.FALSE_REJECT_MINIMIZATION
    )
    if application_experiment:
        show = True
    return show


def check_eligible_mtl_extenstion(application):
    show = False
    job_type = ['Pegawai negeri', 'Pegawai swasta', 'Pekerja rumah tangga', 'Staf rumah tangga']
    if (
        application
        and application.creditscore.score_tag
        not in [ScoreTag.C_FAILED_BLACK_LIST, ScoreTag.C_FAILED_BINARY]
        and application.job_type in job_type
        and application.product_line
        and application.product_line.product_line_code in ProductLineCodes.mtl()
    ):
        show = True

    return show


def get_product_lines(customer, application, is_web_app=None):
    queryset = ProductLine.objects.select_related('product_profile').all()
    loan = Loan.objects.filter(customer=customer).paid_off().first()

    cm_product_lines = []
    cm_product_lines_id = []
    credit_score = get_credit_score3(application) if application else None
    inside_premium_area = credit_score.inside_premium_area if credit_score else True
    credit_matrix_type = (
        CreditMatrixType.WEBAPP
        if is_web_app
        else (CreditMatrixType.JULO if not customer.is_repeated else CreditMatrixType.JULO_REPEAT)
    )
    credit_matrix_database = None

    def override_outside_premium_area_amount(product_line):
        if not inside_premium_area:
            if product_line.non_premium_area_min_amount:
                product_line.min_amount = product_line.non_premium_area_min_amount
            if product_line.non_premium_area_max_amount:
                product_line.max_amount = product_line.non_premium_area_max_amount
        return product_line

    if credit_score:
        repeat_time = (
            Loan.objects.get_queryset().paid_off().filter(customer=application.customer).count()
        )
        credit_matrix_parameters = dict(
            score=credit_score.score,
            is_premium_area=inside_premium_area,
            credit_matrix_type=credit_matrix_type,
            job_type=application.job_type,
            score_tag=credit_score.score_tag,
            repeat_time=repeat_time,
            id=credit_score.credit_matrix_id,
        )
        if application.job_industry:
            credit_matrix_parameters['job_industry'] = application.job_industry
        credit_matrix_database = get_credit_matrix(credit_matrix_parameters)

        if credit_matrix_database:
            cm_product_lines_id = credit_matrix_database.list_product_lines
            cm_product_lines_temp = ProductLine.objects.filter(
                product_line_code__in=cm_product_lines_id
            )
            cm_product_lines_temp = (
                cm_product_lines_temp.repeat_lines()
                if loan
                else cm_product_lines_temp.first_time_lines()
            )
            for product_line in cm_product_lines_temp:
                override_outside_premium_area_amount(product_line)

                score_product = get_score_product(
                    credit_score, credit_matrix_type, product_line, application.job_type
                )
                if score_product:
                    if product_line.product_line_code in ProductLineCodes.stl():
                        product_line.min_amount = score_product.min_loan_amount
                        product_line.max_amount = score_product.max_loan_amount

                    if product_line.product_line_code in ProductLineCodes.mtl():
                        product_line.min_duration = score_product.min_duration
                        product_line.max_duration = score_product.max_duration
                        product_line.max_amount = score_product.max_loan_amount
                        product_line.min_amount = score_product.min_loan_amount
                        product_line.min_interest_rate = score_product.interest
                        product_line.max_interest_rate = score_product.interest
                    product = score_product.get_product_lookup(product_line.max_interest_rate)
                    if product:
                        product_line.origination_fee_rate = product.origination_fee_pct

                # fix android issue, max value will rounded down on android side
                product_line.max_amount = int(py2round(product_line.max_amount, -6))

                cm_product_lines.append(product_line)

    product_line_list = queryset.repeat_lines() if loan else queryset.first_time_lines()
    return cm_product_lines + list(
        map(
            override_outside_premium_area_amount,
            [pl for pl in product_line_list if pl.product_line_code not in cm_product_lines_id],
        )
    )


def create_facebook_data_history(facebookData):
    return FacebookDataHistory.objects.create(
        application=facebookData.application,
        facebook_id=facebookData.facebook_id,
        fullname=facebookData.fullname,
        email=facebookData.email,
        dob=facebookData.dob,
        gender=facebookData.gender,
        friend_count=facebookData.friend_count,
        open_date=facebookData.open_date,
    )


def add_facebook_data(application, request_data):
    facebookdata = FacebookData.objects.create(
        application=application,
        facebook_id=request_data.get('facebook_id'),
        fullname=request_data.get('fullname'),
        email=request_data.get('email'),
        dob=request_data.get('dob'),
        gender=request_data.get('gender'),
        friend_count=request_data.get('friend_count'),
        open_date=request_data.get('open_date'),
    )
    return facebookdata


def update_facebook_data(application, request_data):
    create_facebook_data_history(application.facebook_data)
    FacebookData.objects.filter(application=application).update(
        facebook_id=request_data.get('facebook_id'),
        fullname=request_data.get('fullname'),
        email=request_data.get('email'),
        dob=request_data.get('dob'),
        gender=request_data.get('gender'),
        friend_count=request_data.get('friend_count'),
        open_date=request_data.get('open_date'),
    )
    return FacebookData.objects.get(application=application)


def check_application(application_id):
    from rest_framework.exceptions import ValidationError

    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        error = ValidationError(
            {
                "success": False,
                "content": {},
                "error_message": "application with id %s not found" % application_id,
            }
        )
        error.status_code = 400
        raise error
    return application


def switch_to_product_default_workflow(application):
    product = application.product_line
    old_workflow = application.workflow
    if not old_workflow:
        return
    if product.default_workflow:
        product_workflow = product.default_workflow
    else:
        product_workflow = Workflow.objects.get(name='CashLoanWorkflow')
    with transaction.atomic():
        application.workflow = product_workflow
        application.save()
        ApplicationWorkflowSwitchHistory.objects.create(
            application_id=application.id,
            workflow_old=old_workflow.name,
            workflow_new=product_workflow.name,
        )


def get_latest_app_version():
    obj = AppVersion.objects.filter(status='latest').last()
    return obj.app_version


def check_payslip_mandatory(application_id):
    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        return None

    experiment_service = get_bypass_iti_experiment_service()
    affordable = experiment_service.iti_low_checking(application)

    return (
        affordable is False
        and check_iti_repeat(application_id)
        and get_salaried(application.job_type)
        and application.product_line_code in [ProductLineCodes.MTL1, ProductLineCodes.STL1]
    )


def get_latest_iti_configuration(customer_category):
    return (
        ITIConfiguration.objects.filter(
            is_active=True,
            customer_category=customer_category,
        )
        .filter(
            Q(parameters__partner_ids__isnull=True) | Q(parameters__partner_ids__exact=[]),
            Q(parameters__agent_assisted_partner_ids__isnull=True)
            | Q(parameters__agent_assisted_partner_ids__exact=[]),
        )
        .order_by('-iti_version')
        .values('iti_version')
        .first()
    )


def check_iti_repeat(application_id):
    from juloserver.partnership.leadgenb2b.onboarding.services import (
        get_latest_iti_configuration_leadgen_partner,
        get_high_score_iti_bypass_leadgen_partner,
    )
    from juloserver.partnership.services.services import (
        get_latest_iti_configuration_agent_assisted_partner,
        get_high_score_iti_bypass_agent_assisted_partner,
    )

    """check iti repeat"""
    criteria = {}

    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        return criteria

    credit_score_type = 'B' if check_app_cs_v20b(application) else 'A'
    credit_model_result = PdCreditModelResult.objects.filter(
        application_id=application.id, credit_score_type=credit_score_type
    ).last()

    credit_model_result = (
        credit_model_result or PdWebModelResult.objects.filter(application_id=application.id).last()
    )

    credit_score = CreditScore.objects.filter(application=application).last()

    if not credit_score:
        return criteria

    customer_category = get_customer_category(application)
    inside_premium_area = credit_score.inside_premium_area
    is_salaried = get_salaried(application.job_type)
    # change versioning from PdIncomeTrustModelResult to latest ITIConfiguration
    is_leadgen_partner = application.is_partnership_leadgen()
    latest_iti_config = None
    # Start QOALA PARTNERSHIP - Leadgen Agent Assisted 22-11-2024
    is_qoala_agent_assisted_partner = False
    if application.partner and application.partner.name == PartnerNameConstant.QOALA:
        is_qoala_agent_assisted_partner = True

    if is_qoala_agent_assisted_partner:
        latest_iti_config = get_latest_iti_configuration_agent_assisted_partner(
            customer_category, application.partner_id
        )
    # End QOALA PARTNERSHIP - Leadgen Agent Assisted 22-11-2024
    elif is_leadgen_partner:
        latest_iti_config = get_latest_iti_configuration_leadgen_partner(
            customer_category, application.partner_id
        )

    # by default will use j1 config and for case
    # leadgen Agent Assisted if not found will use j1 config
    if latest_iti_config is None:
        latest_iti_config = get_latest_iti_configuration(customer_category)

    if not latest_iti_config:
        return

    # try to use pgood instead of probability_fpd
    checking_score = (
        getattr(credit_model_result, 'pgood', None) or credit_model_result.probability_fpd
    )

    # Start QOALA PARTNERSHIP - Leadgen Agent Assisted 22-11-2024
    if is_qoala_agent_assisted_partner:
        iti_bypass_flag = get_high_score_iti_bypass_agent_assisted_partner(
            application,
            latest_iti_config['iti_version'],
            inside_premium_area,
            customer_category,
            is_salaried,
            checking_score,
        )
    # End QOALA PARTNERSHIP - Leadgen Agent Assisted 22-11-2024
    elif is_leadgen_partner:
        iti_bypass_flag = get_high_score_iti_bypass_leadgen_partner(
            application,
            latest_iti_config['iti_version'],
            inside_premium_area,
            customer_category,
            is_salaried,
            checking_score,
        )
    else:
        iti_bypass_flag = get_high_score_iti_bypass(
            application,
            latest_iti_config['iti_version'],
            inside_premium_area,
            customer_category,
            is_salaried,
            checking_score,
        )

    # redeclare if leadgen partner and iti not found will use j1 config
    if (is_leadgen_partner and not iti_bypass_flag) or (
        is_qoala_agent_assisted_partner and not iti_bypass_flag
    ):
        latest_iti_config = get_latest_iti_configuration(customer_category)
        iti_bypass_flag = get_high_score_iti_bypass(
            application,
            latest_iti_config['iti_version'],
            inside_premium_area,
            customer_category,
            is_salaried,
            checking_score,
        )

    return iti_bypass_flag


def get_high_score_iti_bypass(
    application, iti_version, inside_premium_area, customer_category, is_salaried, checking_score
):
    # fit_hssb = False
    # bypass = True
    iticonfigs = (
        ITIConfiguration.objects.filter(
            is_active=True,
            is_premium_area=inside_premium_area,
            is_salaried=is_salaried,
            customer_category=customer_category,
            iti_version=iti_version,
            min_threshold__lte=checking_score,
            max_threshold__gt=checking_score,
            min_income__lte=application.monthly_income,
            max_income__gt=application.monthly_income,
        )
        .filter(
            Q(parameters__partner_ids__isnull=True) | Q(parameters__partner_ids__exact=[]),
            Q(parameters__agent_assisted_partner_ids__isnull=True)
            | Q(parameters__agent_assisted_partner_ids__exact=[]),
        )
        .last()
    )
    # is_job_desc = False
    # for iticonfig in iticonfigs:
    #     if iticonfig.parameters:
    #
    #         province_criteria = iticonfig.parameters.get('province', [])
    #         job_type_criteria = iticonfig.parameters.get('job_type', [])
    #         job_industry_criteria = iticonfig.parameters.get('job_industry', [])
    #         job_description_criteria = iticonfig.parameters.get('job_description', [])
    #
    #         if province_criteria:
    #             for province in province_criteria:
    #                 if application.address_provinsi not in province:
    #                     bypass = False
    #                 else:
    #                     bypass = True
    #                     break
    #         if not bypass:
    #             break
    #
    #         if job_type_criteria:
    #             for job_type in job_type_criteria:
    #                 if application.job_type not in job_type:
    #                     bypass = False
    #                 else:
    #                     bypass = True
    #                     break
    #         if not bypass:
    #             break
    #
    #         if application.job_description not in JOB_MAPPING[application.job_industry]:
    #             bypass = False
    #             break
    #
    #         if job_industry_criteria:
    #
    #             for job_industry in job_industry_criteria:
    #                 enter_first_proces = True
    #
    #                 if job_industry.find(application.job_industry) == -1:
    #                     bypass = False
    #                 else:
    #
    #                     for job_description in job_description_criteria:
    #                         if job_description:
    #                             if job_description == job_industry + ':All':
    #                                 if application.job_description in JOB_MAPPING[job_industry]:
    #                                     is_job_desc = True
    #                                     bypass = True
    #                                     break
    #                                 else:
    #                                     bypass = False
    #                             elif job_industry == job_description[0:len(job_industry)]:
    #                                 job = job_description[(len(job_industry) + 1)
    #                                 :len(job_description)]
    #                                 if job == application.job_description:
    #                                     is_job_desc = True
    #                                     bypass = True
    #                                     break
    #                                 else:
    #                                     bypass = False
    #                             else:
    #                                 if job_description.find(application.job_description) == -1:
    #                                     bypass = False
    #                                 else:
    #                                     is_job_desc = True
    #                                     bypass = True
    #                                     break
    #                     if is_job_desc:
    #                         break
    #             else:
    #                 if is_job_desc and enter_first_proces:
    #                     break
    #                 if job_description_criteria:
    #                     for job_description in job_description_criteria:
    #                         if job_description.find(application.job_description) == -1:
    #                             bypass = False
    #                         else:
    #                             if application.job_description
    #                             in JOB_MAPPING[application.job_industry] \
    #                                     and application.job_description
    #                                     in job_description_criteria:
    #                                 bypass = True
    #                                 break
    #         else:
    #             if job_description_criteria:
    #                 for job_description in job_description_criteria:
    #                     if job_description.find(application.job_description) == -1:
    #                         bypass = False
    #                     else:
    #                         bypass = True
    #                         break
    #
    #     if bypass:
    #         fit_hssb = True
    #
    # return fit_hssb
    return iticonfigs


def get_customer_category(application):
    """return customer type like julo, julo_repeat, webapp"""
    if application.is_julo_one():
        customer_category = CreditMatrixType.JULO_ONE
    elif application.is_julo_one_ios():
        customer_category = CreditMatrixType.JULO_ONE_IOS
    else:
        customer_category = CreditMatrixType.JULO

    if application.customer.is_repeated:
        customer_category = CreditMatrixType.JULO_REPEAT

    return customer_category


def can_reapply_validation(customer):
    can_reapply = customer.can_reapply
    can_show_status = True
    last_status_can_reapply = True
    is_ever_status_190 = False
    last_application = customer.application_set.last()
    if last_application:
        can_show_status = last_application.can_show_status
        last_status_can_reapply = last_application.status in ApplicationStatusCodes.can_reapply()
        is_ever_status_190 = ApplicationHistory.objects.filter(
            application=last_application, status_new=ApplicationStatusCodes.LOC_APPROVED
        ).exists()

    return can_reapply and can_show_status and last_status_can_reapply and not is_ever_status_190


def get_referral_home_content(customer, application, app_version):
    result = {}
    is_show = False
    release_date = '14/10/19'
    app_history_date, last_payment_date, check_loan_date, check_cdate = False, False, False, False
    today = timezone.now()
    release_date = datetime.strptime(release_date, '%d/%m/%y')

    account = customer.account
    if not account or account.status_id != AccountConstant.STATUS_CODE.active:
        return is_show, result

    referral_system = ReferralSystem.objects.filter(name='PromoReferral', is_active=True).first()
    if not referral_system:
        return is_show, result

    current_app_version = AppVersion.objects.filter(app_version=app_version).first()
    if (not current_app_version) or (current_app_version.cdate.date() < release_date.date()):
        return is_show, result

    app_history = application.applicationhistory_set.filter(status_new=180).first()
    if app_history:
        app_history_date = app_history.cdate.date() >= release_date.date()
        check_cdate = today < app_history.cdate + timedelta(days=8)

    status = application.status
    try:
        loan = application.loan
        last_payment = loan.payment_set.order_by('payment_number').last()
        if last_payment and loan.status == LoanStatusCodes.PAID_OFF:
            last_payment_date = last_payment.paid_date >= release_date.date()
            check_loan_date = today < last_payment.paid_date + timedelta(days=8)
    except Exception as e:
        logger.warning(
            {
                'method': 'get_referral_home_content',
                'exception': e,
            }
        )
        loan = None

    if (
        (status == ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL)
        and (app_history_date)
        and (check_cdate)
    ) or ((customer.can_reapply) and (last_payment_date) and (check_loan_date)):
        result = {
            "header": "Program Referral",
            "body": (
                'Bagikan kode referral Anda: {} Caranya: Ajak Teman Mengajukan Pinjaman JULO, '
                'Anda akan mendapatkan Cashback Rp 40.000 untuk setiap pinjaman Anda '
                'yang disetujui oleh JULO. Info selengkapnya '
                '<a href=http://www.julofinance.com/android/goto/referral>Klik disini</a>'
            ).format(customer.self_referral_code),
            "bottomimage": None,
            "buttonurl": "http://www.julofinance.com/android/goto/referral",
            "topimage": None,
            "position": 2,
            "buttontext": "Ajak Teman",
            "headerimageurl": "null",
            "buttonstyle": None,
        }
        is_show = True

    return is_show, result


def create_bank_validation_card(application=None, from_status=None):
    data = {}
    template_name = 'ian_150_name_bank_validation'
    filter_ = dict(
        communication_platform=CommunicationPlatform.IAN,
        status_code=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
    )
    if application:
        loan = application.loan
        name_bank_validation = NameBankValidation.objects.get_or_none(
            pk=loan.name_bank_validation_id
        )
        if name_bank_validation and name_bank_validation.reason:
            bank_account_invalid_reason = "Failed to add bank account"
            if bank_account_invalid_reason in name_bank_validation.reason:
                data['INVALID_REASON'] = NameBankValidationStatus.BANK_ACCOUNT_INVALID
            elif name_bank_validation.reason in ["NAME_INVALID", "Name invalid"]:
                data['INVALID_REASON'] = NameBankValidationStatus.NAME_INVALID
            # default value for temporary solution
            else:
                data['INVALID_REASON'] = NameBankValidationStatus.NAME_INVALID

    header_txt = 'Informasi Pengajuan'
    btn_txt = 'Perbaiki Informasi Rekening Bank'

    deep_link = "http://www.julofinance.com/android/goto/bank_account_verification"
    if from_status == 'from_175':
        deep_link = None
        btn_txt = None
        template_name = 'ian_175_name_bank_validation'
        filter_['status_code'] = ApplicationStatusCodes.NAME_VALIDATE_FAILED

    filter_['template_code'] = template_name
    msg = process_streamlined_comm(filter_)
    card = construct_card(msg, header_txt, '', deep_link, None, btn_txt, data=data)
    return card


def update_response_false_rejection(application, response):
    application_experiment = application.applicationexperiment_set.filter(
        experiment__code=ExperimentConst.FALSE_REJECT_MINIMIZATION
    )
    if application_experiment:
        for product in response['product_lines']:
            if product['product_line_code'] == ProductLineCodes.MTL1:
                if response.get('products'):
                    response['products'] = response['products'] + [ProductLineCodes.MTL1]
                if response.get('message'):
                    response['message'] = FalseRejectMiniConst.MOBMESSAGE
                response['score'] = FalseRejectMiniConst.SCORE
                response['mtl_experiment_enable'] = True
                product['min_amount'] = FalseRejectMiniConst.MIN_AMOUNT
                product['max_amount'] = FalseRejectMiniConst.MAX_AMOUNT
                product['min_duration'] = FalseRejectMiniConst.MIN_DURATION
                product['max_duration'] = FalseRejectMiniConst.MAX_DURATION
                product['min_interest_rate'] = FalseRejectMiniConst.INTEREST_RATE_MONTHLY
                product['max_interest_rate'] = FalseRejectMiniConst.INTEREST_RATE_MONTHLY
    return response


def update_response_fraud_experiment(response):
    for product in response['product_lines']:
        if (
            product['product_line_code'] == ProductLineCodes.MTL1
            or product['product_line_code'] == ProductLineCodes.MTL2
        ):
            if response.get('products'):
                response['products'] = [ProductLineCodes.MTL1]
                if product['product_line_code'] == ProductLineCodes.MTL2:
                    response['products'] = [ProductLineCodes.MTL2]
            if response.get('message'):
                response['message'] = FraudModelExperimentConst.MOBMESSAGE
            response['score'] = FraudModelExperimentConst.SCORE
            response['mtl_experiment_enable'] = True
            product['min_amount'] = FraudModelExperimentConst.MIN_AMOUNT
            product['max_amount'] = FraudModelExperimentConst.MAX_AMOUNT
            product['min_duration'] = FraudModelExperimentConst.MIN_DURATION
            product['max_duration'] = FraudModelExperimentConst.MAX_DURATION
            product['min_interest_rate'] = FraudModelExperimentConst.INTEREST_RATE_MONTHLY
            product['max_interest_rate'] = FraudModelExperimentConst.INTEREST_RATE_MONTHLY
    return response


def remove_fdc_binary_check_that_is_not_in_fdc_threshold(
    credit_model_result, binary_checks, application
):
    def remove_fdc_binary_check(binary_checks):
        if FeatureNameConst.FDC_INQUIRY_CHECK in binary_checks:
            binary_checks.remove(FeatureNameConst.FDC_INQUIRY_CHECK)

        return binary_checks, True

    def validate_fdc_binary_check(binary_checks):
        if FeatureNameConst.FDC_INQUIRY_CHECK in binary_checks:
            return binary_checks, False
        else:
            return binary_checks, True

    fdc_inquiry_check_feature_setting = FeatureSetting.objects.filter(
        is_active=True, feature_name=FeatureNameConst.FDC_INQUIRY_CHECK
    ).last()

    if not fdc_inquiry_check_feature_setting:
        return binary_checks, None

    if hasattr(credit_model_result, 'pgood'):
        pgood_or_probability_fpd = credit_model_result.pgood
    elif hasattr(credit_model_result, 'probability_fpd'):
        pgood_or_probability_fpd = credit_model_result.probability_fpd
    else:
        return binary_checks, None

    fdc_inquiry = FDCInquiry.objects.filter(
        application_id=application.id,
        inquiry_status='success',
        inquiry_date__isnull=False,
        inquiry_reason='1 - Applying loan via Platform',
    ).last()
    if not fdc_inquiry:
        return binary_checks, None

    # check threshold
    fdc_inquiry_check = FDCInquiryCheck.objects.filter(is_active=True).filter(
        min_threshold__lte=pgood_or_probability_fpd, max_threshold__gt=pgood_or_probability_fpd
    )
    if not fdc_inquiry_check:
        return remove_fdc_binary_check(binary_checks)

    total_credit, total_bad_credit = calculate_total_credit(fdc_inquiry, application.id)
    criteria_value = 0
    if total_credit:
        criteria_value = float(total_bad_credit) / total_credit

    logger.info(
        {
            'message': 'fdc_total_credit',
            'application_id': application.id,
            'total_credit': total_credit,
            'total_bad_credit': total_bad_credit,
            'criteria_value': criteria_value,
        }
    )

    exists_fdc_inquiry_check = fdc_inquiry_check.filter(min_macet_pct__lt=criteria_value).exists()

    if exists_fdc_inquiry_check:
        return validate_fdc_binary_check(binary_checks)

    # check paid_pct
    today = timezone.localtime(timezone.now()).date()
    get_loans = FDCInquiryLoan.objects.filter(
        fdc_inquiry=fdc_inquiry,
        tgl_pelaporan_data__gte=fdc_inquiry.inquiry_date - relativedelta(days=1),
        tgl_jatuh_tempo_pinjaman__lt=today,
    )

    if not get_loans:
        return remove_fdc_binary_check(binary_checks)

    get_loans = get_loans.aggregate(
        outstanding_amount=Sum('nilai_pendanaan') - Sum('sisa_pinjaman_berjalan'),
        total_amount=Sum('nilai_pendanaan'),
    )

    paid_pct, outstanding_amount, total_amount = 0, 0, 0
    if get_loans['outstanding_amount']:
        outstanding_amount = get_loans['outstanding_amount']

    if get_loans['total_amount']:
        total_amount = get_loans['total_amount']

    if total_amount > 0:
        paid_pct = float(outstanding_amount) / float(total_amount)

    exists_fdc_inquiry_check = fdc_inquiry_check.filter(max_paid_pct__gt=paid_pct).exists()

    if exists_fdc_inquiry_check:
        return validate_fdc_binary_check(binary_checks)

    return remove_fdc_binary_check(binary_checks)


def store_device_geolocation(customer, latitude, longitude):
    """store location to device_gelocation table"""
    device = customer.device_set.last()
    if not device:
        return
    serializer = DeviceGeolocationSerializer(
        data={'device': device.id, 'latitude': latitude, 'longitude': longitude}
    )
    if serializer.is_valid():
        serializer.save()
    else:
        logger.error(
            {
                'action': 'store_device_geolocation',
                'error': serializer.errors,
                'data': serializer.data,
            }
        )


def evaluate_custom_logic(parameter_var, data):
    regex = re.compile('[<>!=]')
    parameter_split = parameter_var.split()
    rules = {}
    outer_operator = None
    if len(parameter_split) >= 1:

        for individual_params in parameter_split:
            if individual_params in ['and', 'or']:
                outer_operator = individual_params
                rules = {outer_operator: [rules]}
                continue
            [key, value] = individual_params.split(':')
            if regex.search(value) is None:
                operator = '=='
            else:
                operator = ''.join(regex.findall(value))
            value = value.lower()
            alphanumeric = [character for character in value if character.isalnum()]
            alphanumeric = "".join(alphanumeric)
            if alphanumeric.isnumeric():
                alphanumeric = float(alphanumeric)
            rule = {operator: [{'var': key}, alphanumeric]}
            if outer_operator:
                rules[outer_operator].append(rule)
            else:
                rules = rule

        return jsonLogic(rules, data)


def queryset_custom_matrix_processing(query_set, parameter_dict_custom):
    is_complex_matrix = False
    complex_matrix_id_list = []
    query_set_parameter = query_set.filter(parameter__isnull=False)
    for credit_matrix in query_set_parameter:
        if evaluate_custom_logic(credit_matrix.parameter, parameter_dict_custom):
            is_complex_matrix = True
            complex_matrix_id_list.append(credit_matrix.id)

    if is_complex_matrix:
        query_set = query_set.filter(pk__in=complex_matrix_id_list)

    return query_set, is_complex_matrix


def is_inside_premium_area(application_id):
    application = Application.objects.get_or_none(id=application_id)
    if not application:
        return
    query = AutoDataCheck.objects.filter(
        application_id=application_id, data_to_check='inside_premium_area'
    ).last()
    if not query:
        return None

    return query.is_okay


def get_j1_last_application(customer):
    application = (
        customer.application_set.filter(product_line__product_line_type="J1")
        .order_by('cdate')
        .last()
    )
    return application


def get_postalcode(postal_code):
    postal_code = postal_code[:5]
    return postal_code


def is_indonesia(address_component):
    for component in address_component:
        if 'country' in component['types']:
            if component['long_name'] != 'Indonesia':
                return False
    return True


def checking_fraud_email_and_ktp(application, failed_checks):
    if 'fraud_email' in failed_checks:
        existing_customer_app_action = CustomerAppAction.objects.filter(
            customer_id=application.customer.id, action='force_logout', is_completed=False
        )
        if not existing_customer_app_action:
            CustomerAppAction.objects.create(
                customer_id=application.customer.id, action='force_logout', is_completed=False
            )

    if 'fraud_email' in failed_checks or 'fraud_ktp' in failed_checks:
        with transaction.atomic():
            customer = (
                Customer.objects.select_for_update().filter(pk=application.customer_id).last()
            )
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
            update_fields = []
            customer_field_changes = []
            if customer.email is not None:
                customer_email_change = CustomerFieldChange(
                    customer=customer,
                    application=application,
                    field_name='email',
                    old_value=customer.email,
                    new_value=None,
                )
                customer.email = None
                update_fields.append('email')
                customer_field_changes.append(customer_email_change)
            if customer.nik is not None:
                customer_nik_change = CustomerFieldChange(
                    customer=customer,
                    application=application,
                    field_name='nik',
                    old_value=customer.nik,
                    new_value=None,
                )
                customer.nik = None
                update_fields.append('nik')
                customer_field_changes.append(customer_nik_change)

            if update_fields:
                customer.save(update_fields=update_fields)
            if customer_field_changes:
                CustomerFieldChange.objects.bulk_create(customer_field_changes)


def get_credit_model_result(application):
    from juloserver.account.services.credit_limit import get_credit_matrix_type

    credit_score_type = 'B' if check_app_cs_v20b(application) else 'A'
    credit_model_result = PdCreditModelResult.objects.filter(
        application_id=application.id, credit_score_type=credit_score_type
    ).last()

    # get model for web app
    if application.is_julo_one():
        credit_matrix_type = get_credit_matrix_type(application, is_proven=False)
    else:
        if not application.customer.is_repeated:
            credit_matrix_type = CreditMatrixType.JULO
        else:
            credit_matrix_type = CreditMatrixType.JULO_REPEAT

    if not credit_model_result:
        credit_model_webapp = PdWebModelResult.objects.filter(application_id=application.id).last()

        if credit_model_webapp:
            credit_model_result = credit_model_webapp

            leadgen_partners = dict()
            feature_setting = FeatureSetting.objects.filter(
                is_active=True,
                feature_name=FeatureNameConst.LEAD_GEN_PARTNER_CREDIT_SCORE_GENERATION,
            ).last()
            if feature_setting:
                leadgen_partners = feature_setting.parameters['partners']

            if (
                not application.is_partnership_app()
                and application.partner_name not in leadgen_partners
            ):
                credit_matrix_type = CreditMatrixType.WEBAPP

    return credit_matrix_type, credit_model_result


def check_binary_result(application):
    credit_matrix_type, credit_model_result = get_credit_model_result(application)

    partner_name = application.partner_name
    feature_setting = FeatureSetting.objects.filter(
        is_active=True, feature_name=FeatureNameConst.LEAD_GEN_PARTNER_CREDIT_SCORE_GENERATION
    ).last()
    if feature_setting:
        leadgen_partners = feature_setting.parameters['partners']
        if partner_name in leadgen_partners:
            partner_name = PartnerNameConstant.GENERIC
    if application.is_partnership_app():
        partner_name = None
    rules = credit_score_rules2[partner_name]
    bypass_checks = rules['bypass_checks']

    # experiment  remove own_phone binary check
    today = timezone.now().date()
    experiment = Experiment.objects.filter(
        is_active=True,
        date_start__lte=today,
        date_end__gte=today,
        code=ExperimentConst.IS_OWN_PHONE_EXPERIMENT,
    ).last()
    if experiment:
        bypass_checks += ['own_phone']

    if is_customer_has_good_payment_histories(application.customer):
        bypass_check_for_good_customer = ['fraud_form_partial_device', 'fraud_device']
        bypass_checks = set(bypass_checks + bypass_check_for_good_customer)
    failed_checks = AutoDataCheck.objects.filter(application_id=application.id, is_okay=False)
    failed_checks = failed_checks.exclude(data_to_check__in=bypass_checks)
    failed_checks = failed_checks.values_list('data_to_check', flat=True)
    failed_checks, fdc_inquiry_check = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
        credit_model_result, list(failed_checks), application
    )
    check_order = CreditMatrixV19.BINARY_CHECK_SHORT + CreditMatrixV19.BINARY_CHECK_LONG
    skip_special_event = SpecialEventSettingHelper().is_no_bypass()
    checking_fraud_email_and_ktp(application, failed_checks)

    for check in check_order:
        if check in failed_checks:
            if check != 'special_event' or not skip_special_event:
                return False

    return True


def get_countdown_suspicious_domain_from_feature_settings(feature_name, default=21600):
    try:
        settings = FeatureSetting.objects.filter(is_active=True, feature_name=feature_name).last()
        return int(settings.parameters.get('delay_time', default))
    except Exception:
        return default


def is_otp_validated(application, phone_number) -> bool:
    if not MobileFeatureSetting.objects.filter(
        feature_name=FeatureSettingName.NORMAL, is_active=True
    ).exists():
        return True

    if not isinstance(application, Application):
        application = Application.objects.get(id=application)

    if not application or not phone_number:
        return False
    otp_request = OtpRequest.objects.filter(
        phone_number=phone_number,
        is_used=True,
        action_type__in=(SessionTokenAction.VERIFY_PHONE_NUMBER, SessionTokenAction.PHONE_REGISTER),
    ).last()

    if not otp_request:
        return False

    if (
        otp_request.action_type == SessionTokenAction.VERIFY_PHONE_NUMBER
        and otp_request.customer_id != application.customer.id
    ):
        return False
    return True


def rescore_application(application, cm_parameter=None):
    from juloserver.application_flow.services import JuloOneService
    from juloserver.account.services.credit_limit import (
        get_credit_matrix,
        get_transaction_type,
    )

    if JuloOneService.is_c_score(application):
        cs = CreditScore.objects.filter(application_id=application.id).last()
        fdc_inquiry_check = cs.fdc_inquiry_check
        cs.delete()

        credit_matrix_type, credit_model_result = get_credit_model_result(application)
        probability_fpd = (
            getattr(credit_model_result, 'pgood', None) or credit_model_result.probability_fpd
        )
        is_premium_area = is_inside_premium_area(application.id)
        job_type = application.job_type
        is_salaried = get_salaried(job_type)

        params = {
            "min_threshold__lte": probability_fpd,
            "max_threshold__gte": probability_fpd,
            "is_salaried": is_salaried,
            "is_premium_area": is_premium_area,
            'credit_matrix_type': credit_matrix_type,
        }
        if cm_parameter:
            credit_matrix = get_credit_matrix(
                params,
                get_transaction_type(),
                parameter=Q(parameter=cm_parameter),
            )
        else:
            credit_matrix = get_credit_matrix(params, get_transaction_type())

        if credit_matrix:
            score = credit_matrix.score
            score_tag = credit_matrix.score_tag
            message = credit_matrix.message
            credit_matrix_version = credit_matrix.version
            credit_matrix_id = credit_matrix.id
            product_list = credit_matrix.list_product_lines

            store_credit_score_to_db(
                application,
                product_list,
                score,
                message,
                score_tag,
                credit_model_result,
                credit_matrix_version,
                credit_matrix_id,
                fdc_inquiry_check=fdc_inquiry_check,
            )
            return True
        else:
            logger.info(
                {
                    "message": "Failed rescore: Credit Matrix not found",
                    "application_id": application.id,
                    "feature": cm_parameter,
                }
            )
    return False


def modify_change_phone_number_related_response(
    datas,
    android_id: str,
    app_version_code: int,
):
    try:
        feature_setting = MobileFeatureSetting.objects.get(
            feature_name=MobileFeatureNameConst.RESET_PHONE_NUMBER,
            is_active=True,
        )
    except MobileFeatureSetting.DoesNotExist:

        modified_response = []

        for data in datas:

            if data['question'] == 'Tanpa Akses ke Nomor Lama NEW':
                continue

            modified_response.append(data)

        return modified_response

    reset_phone_number_avc = feature_setting.parameters.get('supported_app_version_code')

    is_rate_limited_per_device = is_device_reset_phone_number_rate_limited(
        android_id,
        feature_setting,
    )

    modified_response = []

    for data in datas:

        if data['question'] == 'Tanpa Akses ke Nomor Lama NEW' and (
            app_version_code < reset_phone_number_avc
        ):
            continue

        if (
            data['question'] == 'Tanpa Akses ke Nomor Lama'
            and app_version_code >= reset_phone_number_avc
        ):
            continue

        if data['question'] == 'Tanpa Akses ke Nomor Lama NEW':
            data['question'] = 'Tanpa Akses ke Nomor Lama'
            data['is_action_enabled'] = not is_rate_limited_per_device

        modified_response.append(data)

    return modified_response


def get_query_fdc_inquiry_loan(fdc_inquiry):

    fdc_inquiry_id = fdc_inquiry.id if fdc_inquiry else None
    logger.info(
        {
            'message': '[Start] execute get_query_fdc_inquiry_loan',
            'application_id': fdc_inquiry_id,
        }
    )

    # check kualitas pinjaman count
    loans_data = FDCInquiryLoan.objects.filter(
        fdc_inquiry=fdc_inquiry,
        tgl_pelaporan_data__gte=fdc_inquiry.inquiry_date - relativedelta(years=1),
    ).annotate(
        kualitas_pinjaman_convert=Case(
            When(
                dpd_terakhir__lte=FDCFieldsName.LANCAR_CONF['days'],
                then=Value(FDCFieldsName.LANCAR_CONF['name']),
            ),
            When(
                dpd_terakhir__range=FDCFieldsName.DALAM_PERHATIAN_KHUSUS_CONF['days'],
                then=Value(FDCFieldsName.DALAM_PERHATIAN_KHUSUS_CONF['name']),
            ),
            When(
                dpd_terakhir__range=FDCFieldsName.KURANG_LANCAR_CONF['days'],
                then=Value(FDCFieldsName.KURANG_LANCAR_CONF['name']),
            ),
            When(
                dpd_terakhir__range=FDCFieldsName.DIRAGUKAN_CONF['days'],
                then=Value(FDCFieldsName.DIRAGUKAN_CONF['name']),
            ),
            When(
                dpd_terakhir__gte=FDCFieldsName.MACET_CONF['days'],
                then=Value(FDCFieldsName.MACET_CONF['name']),
            ),
            default=Value('uncategorized'),
            output_field=CharField(),
        )
    )
    loans_data = loans_data.values('kualitas_pinjaman_convert').annotate(
        total=Count('kualitas_pinjaman_convert')
    )

    logger.info(
        {
            'message': '[End] execute get_query_fdc_inquiry_loan',
            'application_id': fdc_inquiry_id,
        }
    )

    return loans_data


def calculate_total_credit(fdc_inquiry, application_id):

    logger.info(
        {
            'message': '[Start] execute calculate_total_credit',
            'application_id': application_id,
        }
    )

    keys = [
        FDCFieldsName.LANCAR_CONF['name'],
        FDCFieldsName.DALAM_PERHATIAN_KHUSUS_CONF['name'],
        FDCFieldsName.KURANG_LANCAR_CONF['name'],
        FDCFieldsName.DIRAGUKAN_CONF['name'],
        FDCFieldsName.MACET_CONF['name'],
    ]

    total_credit = 0
    total_bad_credit = 0
    field_name = 'kualitas_pinjaman_convert'
    loans_data = get_query_fdc_inquiry_loan(fdc_inquiry)

    for item_loan in loans_data:
        for key in keys:
            if item_loan[field_name] == key:
                total_credit = total_credit + item_loan['total']

            if item_loan[field_name] == FDCFieldsName.MACET_CONF['name']:
                total_bad_credit = item_loan['total']

    logger.info(
        {
            'message': '[End] execute calculate_total_credit',
            'application_id': application_id,
            'total_credit': total_credit,
            'total_bad_credit': total_bad_credit,
        }
    )

    return total_credit, total_bad_credit
