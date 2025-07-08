import logging
from django.utils import timezone

from juloserver.apiv2.models import (
    PdCreditModelResult,
    PdFraudModelResult,
    AutoDataCheck,
)
from juloserver.julo.models import (
    Application,
    ApplicationNote,
    CreditMatrix,
    CreditScore,
    Experiment,
    FeatureSetting,
    Loan,
)
from juloserver.julo.services2 import get_advance_ai_service
from juloserver.apiv2.services import (
    is_c_score_in_delay_period,
    is_customer_has_good_payment_histories,
    remove_fdc_binary_check_that_is_not_in_fdc_threshold,
    checking_fraud_email_and_ktp,
    is_inside_premium_area,
    is_email_whitelisted_to_force_high_score,
    get_experimental_probability_fpd,
    override_score_for_failed_dynamic_check,
    store_credit_score_to_db,
)
from juloserver.julo.constants import (
    FeatureNameConst,
    ExperimentConst,
    ScoreTag,
)
from juloserver.apiv2.constants import CreditMatrixV19
from juloserver.ana_api.utils import check_app_cs_v20b
from juloserver.apiv2.credit_matrix2 import (
    credit_score_rules2,
    get_good_score,
)
from juloserver.application_flow.services import SpecialEventSettingHelper
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.clients.constants import BlacklistCheckStatus
from juloserver.apiv2.credit_matrix2 import messages as cm2_messages

logger = logging.getLogger(__name__)


def get_credit_score_ios(application, minimum_false_rejection=False, skip_delay_checking=False):
    from juloserver.account.services.credit_limit import get_credit_matrix_type
    from juloserver.account.services.credit_matrix import get_good_score_j1
    from juloserver.julo.models import FraudModelExperiment
    from juloserver.julo.services import (
        experimentation_false_reject_min_exp,
        is_credit_experiment,
    )

    if not isinstance(application, Application):
        application = Application.objects.get(pk=application)

    def get_credit_model_result(application):
        credit_score_type = 'B' if check_app_cs_v20b(application) else 'A'
        credit_model_result = PdCreditModelResult.objects.filter(
            application_id=application.id, credit_score_type=credit_score_type
        ).last()
        credit_matrix_type = get_credit_matrix_type(application)

        return credit_matrix_type, credit_model_result

    credit_score = CreditScore.objects.get_or_none(application_id=application.id)
    credit_matrix_id = None

    if credit_score:
        logger.info(
            {
                "message": "get_credit_score_ios: found credit score",
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
    is_fdc = credit_model_result and credit_model_result.has_fdc

    have_experiment = {'is_experiment': False, 'experiment': None}
    partner_name = application.partner_name
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
        if application.is_julo_one() or application.is_julo_one_ios():
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
        if application.is_julo_one() or application.is_julo_one_ios():

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

    # try to use pgood value instead of probability_fpd
    probability_fpd = (
        getattr(credit_model_result, 'pgood', None) or credit_model_result.probability_fpd
    )

    logger.info(
        {
            "message": "get_credit_score_ios: score info",
            "score": score,
            "application_id": application.id,
        }
    )

    # add LOC product to product_list if score is 'A-'
    if score == 'A-':
        product_list.append(ProductLineCodes.LOC)

    score, score_tag = override_score_for_failed_dynamic_check(application, score, score_tag)

    if score in ['C', '--']:
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
                "message": "get_credit_score_ios: get non-C score",
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
