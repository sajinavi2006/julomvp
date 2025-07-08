import logging
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from juloserver.apiv2.constants import CreditMatrixType
from juloserver.apiv2.credit_matrix2 import get_salaried
from juloserver.apiv2.models import PdCreditModelResult, PdWebModelResult
from juloserver.apiv2.services import get_customer_category
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.application_flow.services import (
    is_experiment_application,
    is_goldfish,
    JuloOneService,
)
from juloserver.julo.admin2.job_data_constants import JOB_MAPPING
from juloserver.julo.constants import FeatureNameConst, MobileFeatureNameConst
from juloserver.julo.models import (
    CreditScore,
    FeatureSetting,
    HighScoreFullBypass,
    MobileFeatureSetting,
    Application,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import (
    experimentation_automate_offer,
    process_application_status_change,
)
from juloserver.julo.statuses import ApplicationStatusCodes

logger = logging.getLogger(__name__)

def do_high_score_full_bypass(application):
    if application.is_julo_one() or application.is_julo_one_ios():
        logger.info(
            {
                "message": "do_high_score_full_bypass: hsfbp J1",
                "application_id": application.id,
            }
        )
        from juloserver.application_flow.services import JuloOneByPass
        julo_one_bypass_service = JuloOneByPass()
        do_hsfbp = julo_one_bypass_service.do_high_score_full_bypass_for_julo_one(application)
        return do_hsfbp

    logger.info(
        {
            "message": "do_high_score_full_bypass: hsfbp non J1",
            "application_id": application.id,
        }
    )
    new_status_code = ApplicationStatusCodes.APPLICATION_DENIED
    offer_generated = experimentation_automate_offer(application)
    if offer_generated:
        new_status_code = ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER

    process_application_status_change(
        application.id,
        new_status_code,
        change_reason=FeatureNameConst.HIGH_SCORE_FULL_BYPASS)


def feature_high_score_full_bypass(application, ignore_fraud=False):
    from juloserver.partnership.leadgenb2b.onboarding.services import (
        get_high_score_full_bypass_leadgen_partner,
    )
    from juloserver.partnership.services.services import (
        get_high_score_full_bypass_agent_assisted_partner,
    )
    can_ignore_fraud = ignore_fraud and application.can_ignore_fraud()
    if not can_ignore_fraud and not application.eligible_for_hsfbp():
        if not is_experiment_application(application.id, 'ExperimentUwOverhaul'):
            return None

    feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.HIGH_SCORE_FULL_BYPASS,
        is_active=True,
    ).last()

    if not feature:
        return None

    valid_products = ProductLineCodes.mtl() + ProductLineCodes.stl() + ProductLineCodes.julo_one()

    if application.product_line_code not in valid_products:
        return None

    credit_score = CreditScore.objects.filter(
        application=application).last()

    if not credit_score:
        return None

    credit_model_result = PdCreditModelResult.objects.filter(application_id=application.id).last()
    if not credit_model_result:
        credit_model_result = PdWebModelResult.objects.filter(application_id=application.id).last()
        
        if not credit_model_result:
            credit_model_result = PdWebModelResult.objects.filter(application_id=application.id).last()
            
            if not credit_model_result:
                return None

    if not credit_score.model_version:
        credit_score.model_version = credit_model_result.version
        credit_score.save()
        credit_score.refresh_from_db()

    cm_version = credit_score.model_version
    inside_premium_area = credit_score.inside_premium_area
    customer_category = get_customer_category(application)
    is_leadgen_partner = application.is_partnership_leadgen()
    highscore = None
    checking_score = None
    # try to use pgood instead of probability_fpd
    checking_score = (
        getattr(credit_model_result, 'pgood', None) or credit_model_result.probability_fpd
    )
    # Start QOALA PARTNERSHIP - Leadgen Agent Assisted 20-11-2024
    is_qoala_agent_assisted_partner = False
    if application.partner and application.partner.name == PartnerNameConstant.QOALA:
        is_qoala_agent_assisted_partner = True

    if is_qoala_agent_assisted_partner:
        partner_id = str(application.partner_id)
        latest_config = (
            HighScoreFullBypass.objects.filter(
                customer_category=customer_category,
                parameters__agent_assisted_partner_ids__contains=[partner_id],
            )
            .order_by('-cm_version')
            .first()
        )
        if latest_config:
            cm_version = latest_config.cm_version
        highscore = get_high_score_full_bypass_agent_assisted_partner(
            application,
            cm_version,
            inside_premium_area,
            customer_category,
            checking_score,
        )
    # End QOALA PARTNERSHIP - Leadgen Agent Assisted 20-11-2024
    elif is_leadgen_partner:
        partner_id = str(application.partner_id)
        latest_config = (
            HighScoreFullBypass.objects.filter(
                customer_category=customer_category,
                parameters__partner_ids__contains=[partner_id],
            )
            .order_by('-cm_version')
            .first()
        )
        if latest_config:
            cm_version = latest_config.cm_version

        # get the high score for leadgen
        highscore = get_high_score_full_bypass_leadgen_partner(
            application,
            cm_version,
            inside_premium_area,
            customer_category,
            checking_score,
        )
    else:
        latest_config = (
            HighScoreFullBypass.objects.filter(
                customer_category=customer_category,
            )
            .filter(
                Q(parameters__partner_ids__isnull=True) | Q(parameters__partner_ids__exact=[]),
                Q(parameters__agent_assisted_partner_ids__isnull=True)
                | Q(parameters__agent_assisted_partner_ids__exact=[]),
            )
            .order_by('-cm_version')
            .first()
        )
        if latest_config:
            cm_version = latest_config.cm_version

        # get the high score
        highscore = get_high_score_full_bypass(
            application,
            cm_version,
            inside_premium_area,
            customer_category,
            checking_score,
        )

    # redeclare if leadgen partner or agent assisted partner and highscore not found will use j1 config
    if (is_leadgen_partner and not highscore) or (
        is_qoala_agent_assisted_partner and not highscore
    ):
        latest_config = (
            HighScoreFullBypass.objects.filter(
                customer_category=customer_category,
            )
            .filter(
                Q(parameters__partner_ids__isnull=True) | Q(parameters__partner_ids__exact=[]),
                Q(parameters__agent_assisted_partner_ids__isnull=True)
                | Q(parameters__agent_assisted_partner_ids__exact=[]),
            )
            .order_by('-cm_version')
            .first()
        )
        if latest_config:
            cm_version = latest_config.cm_version

        # get the high score
        highscore = get_high_score_full_bypass(
            application,
            cm_version,
            inside_premium_area,
            customer_category,
            checking_score,
        )

    return highscore


def eligible_to_extra_high_loan(application):
    credit_score_type = 'A' # we no longer using 'B' type
    credit_score = CreditScore.objects.filter(
        application=application).last()
    if not credit_score:
        return False
    customer_category = get_customer_category(application)
    if customer_category == CreditMatrixType.WEBAPP:
        return False
    credit_model_result = PdCreditModelResult.objects.filter(
        application_id=application.id,
        credit_score_type=credit_score_type).last()
    hsfbp_criteria = HighScoreFullBypass.objects.filter(
        cm_version=credit_score.model_version,
        is_premium_area=credit_score.inside_premium_area,
        is_salaried=get_salaried(application.job_type),
        customer_category=customer_category,
        threshold__lte=credit_model_result.probability_fpd
    ).order_by('-threshold').first()
    if hsfbp_criteria or (credit_score.score == 'A-' and customer_category == CreditMatrixType.JULO_REPEAT):
        return True
    return False


def check_high_score_full_bypass(application):
    if feature_high_score_full_bypass(application):
        return True
    else:
        return False


def get_high_score_full_bypass(application, cm_version, inside_premium_area, customer_category, checking_score):

    fit_hsfb = None
    bypass = True

    highscores = (
        HighScoreFullBypass.objects.filter(
            cm_version=cm_version,
            is_premium_area=inside_premium_area,
            is_salaried=get_salaried(application.job_type),
            customer_category=customer_category,
            threshold__lte=checking_score,
        )
        .filter(
            Q(parameters__partner_ids__isnull=True) | Q(parameters__partner_ids__exact=[]),
            Q(parameters__agent_assisted_partner_ids__isnull=True)
            | Q(parameters__agent_assisted_partner_ids__exact=[]),
        )
        .order_by('-threshold')
        .last()
    )

    # is_job_desc = False
    # for highscore in highscores:
    #     if highscore.parameters:
    #
    #         bypass = True
    #
    #         province_criteria = highscore.parameters.get('province', [])
    #         job_type_criteria = highscore.parameters.get('job_type', [])
    #         job_industry_criteria = highscore.parameters.get('job_industry', [])
    #         job_description_criteria = highscore.parameters.get('job_description', [])
    #
    #         if province_criteria:
    #
    #             for province in province_criteria:
    #                 if application.address_provinsi not in province:
    #                     bypass = False
    #                 else:
    #                     bypass = True
    #                     break
    #
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
    #
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
    #                                 job = job_description[(len(job_industry)+1):len(job_description)]
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
    #                             if application.job_description in JOB_MAPPING[application.job_industry] \
    #                                     and application.job_description in job_description_criteria:
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
    #     if bypass:
    #         fit_hsfb = highscore

    # return fit_hsfb
    return highscores


def eligible_hsfbp_goldfish(application: Application) -> bool:
    """
    Eligible High Score Full Bypass for Goldfish
    """

    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.GOLDFISH_BYPASS, is_active=True
    ).last()
    if setting is None:
        return False

    customer = application.customer
    customer_last_digit = str(customer.id)[-1:]
    eligible_experiment = int(customer_last_digit) in setting.parameters["customer_ids"]
    if not eligible_experiment:
        return False

    if JuloOneService().is_c_score(application):
        return False

    if not is_goldfish(application):
        return False

    logger.info(
        {
            "message": "Eligible HSFBP goldfish",
            "application": application.id,
        }
    )
    return True
