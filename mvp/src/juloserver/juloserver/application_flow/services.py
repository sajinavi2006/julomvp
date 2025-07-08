"""services.py"""
import datetime
import itertools
import logging
import urllib
from builtins import object
from math import asin, cos, radians, sin, sqrt, ceil
from typing import Union
import copy

import semver
from django.db import transaction
from django.db.utils import IntegrityError
from django.template.base import Template
from django.template.context import Context
from django.utils import timezone
from django.db.models import Q
from django.conf import settings
from fuzzywuzzy import fuzz
from datetime import timedelta

from juloserver.account_payment.models import AccountPayment
from juloserver.account.models import (
    ExperimentGroup,
    AccountStatusHistory,
    Account,
)
from juloserver.ana_api.models import (
    SdBankAccount,
    SdBankStatementDetail,
    PdApplicationFraudModelResult,
    PdCreditEarlyModelResult,
    DynamicCheck,
    EligibleCheck,
)
from juloserver.apiv2.models import AutoDataCheck, SdDeviceApp, PdCreditModelResult
from juloserver.application_flow.clients import get_here_maps_client
from juloserver.application_flow.models import (
    ApplicationPathTag,
    ApplicationPathTagHistory,
    ApplicationPathTagStatus,
    ApplicationRiskyCheck,
    ApplicationRiskyDecision,
    ApplicationTag,
    EmulatorCheck,
    EmulatorCheckEligibilityLog,
    ReverseGeolocation,
    SuspiciousFraudApps,
    HsfbpIncomeVerification,
)
from juloserver.google_analytics.constants import GAEvent
from juloserver.google_analytics.tasks import send_event_to_ga_task_async
from juloserver.income_check.models import IncomeCheckLog
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import (
    Affordability,
    ExperimentConst,
    FeatureNameConst,
    MobileFeatureNameConst,
    OnboardingIdConst,
    ProductLineCodes,
    WorkflowConst,
)
from juloserver.julo.models import (
    AddressGeolocation,
    AffordabilityHistory,
    Application,
    ApplicationExperiment,
    ApplicationHistory,
    CreditScore,
    CustomerRemoval,
    Device,
    DeviceGeolocation,
    Experiment,
    ExperimentSetting,
    ExperimentTestGroup,
    FeatureSetting,
    Image,
    MobileFeatureSetting,
    ProductLine,
    Workflow,
    SuspiciousDomain,
    ApplicationNote,
)
from juloserver.julo.statuses import ApplicationStatusCodes, JuloOneCodes
from juloserver.julo.utils import display_rupiah, get_oss_public_url
from juloserver.julolog.julolog import JuloLog

from ..antifraud.services.binary_checks import get_application_old_status_code
from ..antifraud.services.call_back import (
    overwrite_application_history_and_call_anti_fraud_call_back,
)
from ..julo.exceptions import JuloException
from .constants import (
    AddressFraudPreventionConstants,
    ApplicationRiskyDecisions,
    ExperimentJuloStarterKeys,
    JuloOne135Related,
    JuloOneChangeReason,
    ApplicationStatusEventType,
    ApplicationStatusAppsflyerEvent,
    PartnerNameConstant,
    CacheKey,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.application_form.constants import IDFyApplicationTagConst
from juloserver.ana_api.models import SdDevicePhoneDetail
from juloserver.application_flow.constants import (
    AgentAssistedSubmissionConst,
    HSFBPIncomeConst,
)
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object

julo_logger = JuloLog(__name__)
logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class JuloOneByPass(object):
    def bypass_julo_one_iti_122_to_124(self, application):
        from juloserver.julo.services import process_application_status_change

        process_application_status_change(
            application.id,
            ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
            JuloOneChangeReason.SONIC_AFFORDABILITY,
        )

    def bypass_julo_one_iti_120_to_121(self, application):
        from juloserver.julo.services import process_application_status_change

        process_application_status_change(
            application.id,
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            JuloOneChangeReason.SONIC_AFFORDABILITY,
        )

    def do_high_score_full_bypass_for_julo_one(self, application):
        from juloserver.face_recognition.services import CheckFaceSimilarity
        from juloserver.julo.services import process_application_status_change
        from juloserver.julo.services2.high_score import feature_high_score_full_bypass
        from juloserver.face_recognition.tasks import face_matching_task
        from juloserver.julo.services2.high_score import eligible_hsfbp_goldfish

        logger.info(
            {
                "message": "do_high_score_full_bypass_for_julo_one",
                "application_id": application.id,
            }
        )
        # get next status from old one base on mapping

        check_face_similarity = CheckFaceSimilarity(application)
        check_face_similarity.check_face_similarity()
        face_matching_task.delay(application.id)
        is_ios = application.is_julo_one_ios()

        eligible_hsfbp = feature_high_score_full_bypass(application)
        eligible_goldfish_hsfbp = eligible_hsfbp_goldfish(application)
        eligible_to_continue = eligible_hsfbp or eligible_goldfish_hsfbp
        if not eligible_to_continue:
            logger.info(
                {
                    "message": "do_high_score_full_bypass_for_julo_one: not eligible",
                    "application_id": application.id,
                }
            )

            if is_ios:
                logger.info(
                    {
                        "message": "do_high_score_full_bypass_for_julo_one: ios not eligible",
                        "application_id": application.id,
                    }
                )
                new_status_code = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
                process_application_status_change(
                    application.id, new_status_code, change_reason='regular flow DV'
                )

            return False

        if (
            (eligible_hsfbp and not eligible_hsfbp.bypass_dv_x121)
            or not application.dukcapil_eligible()
            or eligible_goldfish_hsfbp
        ):
            logger.info(
                {
                    "message": "do_high_score_full_bypass_for_julo_one: eligible set status",
                    "application_id": application.id,
                }
            )
            new_status_code = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        else:

            new_status_code = ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL

            risky_checklist = ApplicationRiskyCheck.objects.filter(application=application).last()
            if (
                    risky_checklist
                    and risky_checklist.decision
                    and risky_checklist.decision.decision_name
                    in ApplicationRiskyDecisions.no_dv_bypass()
            ):
                new_status_code = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
            elif is_experiment_application(application.id, 'ExperimentUwOverhaul'):
                new_status_code = ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL

        logger.info(
            {
                "message": "do_high_score_full_bypass_for_julo_one: set status",
                "to": new_status_code,
                "application_id": application.id,
            }
        )

        ga_event = GAEvent.APPLICATION_BYPASS
        if application.customer.app_instance_id:
            send_event_to_ga_task_async.apply_async(
                kwargs={'customer_id': application.customer.id, 'event': ga_event}
            )
        else:
            logger.info(
                'handle_iti_ready|app_instance_id not found|'
                'application_id={}'.format(application.id)
            )

        if self.is_hsfbp_income_verification(
            application=application, new_status_code=new_status_code
        ):
            self._store_experiment_group(
                application=application,
                group=HSFBPIncomeConst.KEY_EXP_EXPERIMENT,
            )
            remove_session_check_hsfbp(application.id)
            return True

        self._store_experiment_group(
            application=application,
            group=HSFBPIncomeConst.KEY_EXP_CONTROL,
        )
        process_application_status_change(
            application.id, new_status_code, change_reason=FeatureNameConst.HIGH_SCORE_FULL_BYPASS
        )
        return True

    def is_hsfbp_income_verification(self, application, new_status_code):
        """
        Handle experiment HSFBP Income Verification
        Will Calculate expired days for target applications to stay as temporary in x120 status.
        """

        # Strict validation only J1 application x120 to x121 can proceed this function
        if (
            not application.is_julo_one()
            or application.application_status_id != ApplicationStatusCodes.DOCUMENTS_SUBMITTED
            or new_status_code != ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        ):
            logger.info(
                {
                    'message': '[SkipApplication] application is not criteria '
                    'HSFBP Income Verification',
                    'application_id': application.id,
                    'application_status_id': application.application_status_id,
                    'new_status_code': new_status_code,
                }
            )
            return False

        # Check experiment still ongoing?
        is_experiment = still_in_experiment(
            experiment_type=ExperimentConst.HSFBP_INCOME_VERIFICATION
        )
        if not is_experiment:
            return False

        experiment = ExperimentSetting.objects.filter(
            code=ExperimentConst.HSFBP_INCOME_VERIFICATION,
        ).last()

        # Check rule in last digit
        criteria = experiment.criteria
        application_id = application.id
        last_digit_config = criteria.get(HSFBPIncomeConst.KEY_LAST_DIGIT_APP_ID)
        if application_id % 10 not in last_digit_config:
            return False

        if not application.app_version:
            logger.info(
                {'message': '[x120_HSFBP] app_version is empty', 'application_id': application_id}
            )
            return False

        app_version = application.app_version
        app_version_criteria = criteria.get(HSFBPIncomeConst.KEY_ANDROID_APP_VERSION)
        if not semver.match(app_version, app_version_criteria):
            logger.info(
                {
                    'message': '[x120_HSFBP] application is not match with criteria app version',
                    'application_id': application_id,
                    'app_version': app_version,
                    'app_version_criteria': app_version_criteria,
                }
            )
            return False

        # Calculation for duration expired
        time_now = timezone.localtime(timezone.now())
        expiry_days = criteria.get(HSFBPIncomeConst.KEY_EXPIRATION_DAY)
        expiry_date = time_now + timedelta(expiry_days)

        logger.info(
            {
                'message': '[x120_HSFBP] Configuration is active',
                'application_id': application_id,
                'expiry_date': expiry_date,
                'expiry_days': expiry_days,
                'last_digit_config': last_digit_config,
            }
        )

        self._store_hsfbp_income_verification(
            application=application,
            expired_date=expiry_date,
        )

        self._expiry_hsfbp_income_verification(
            application=application,
            expired_date=expiry_date,
        )

        from juloserver.moengage.services.use_cases import (
            update_moengage_for_application_status_change_event,
        )

        update_moengage_for_application_status_change_event.apply_async(
            (ApplicationStatusCodes.DOCUMENTS_SUBMITTED, None, application.id),
            countdown=settings.DELAY_FOR_REALTIME_EVENTS,
        )

        return True

    def check_accept_hsfbp_income_verification(self, application):
        return ApplicationHistory.objects.filter(
            application_id = application.id,
            change_reason = HSFBPIncomeConst.ACCEPTED_REASON,
        ).last()

    def check_expired_hsfbp_tag(self, application):
        return check_has_path_tag(application.id, HSFBPIncomeConst.EXPIRED_TAG)

    def check_decline_hsfbp_tag(self, application):
        path_tag = ApplicationPathTagStatus.objects.filter(
            application_tag=HSFBPIncomeConst.DECLINED_TAG, status=1
        ).last()

        return ApplicationPathTag.objects.filter(
            application_id=application.id, application_path_tag_status=path_tag
        ).last()

    def _store_hsfbp_income_verification(self, application, expired_date):

        if not HsfbpIncomeVerification.objects.filter(application_id=application.id).exists():
            HsfbpIncomeVerification.objects.create(
                application_id=application.id,
                stated_income=application.monthly_income,
                expired_date=expired_date,
            )

    def _store_experiment_group(self, application, group):

        hsfbp_exp_setting = ExperimentSetting.objects.filter(
            code=ExperimentConst.HSFBP_INCOME_VERIFICATION,
        ).last()

        if not hsfbp_exp_setting:
            return False

        experiment_group = ExperimentGroup.objects.filter(
            application=application,
            experiment_setting=hsfbp_exp_setting,
        ).exists()
        if not experiment_group:
            customer = application.customer
            ExperimentGroup.objects.create(
                experiment_setting=hsfbp_exp_setting,
                application=application,
                customer=customer,
                group=group,
            )
        return True

    def _expiry_hsfbp_income_verification(self, application, expired_date):
        from juloserver.application_flow.tasks import expiration_hsfbp_income_verification_task

        expiration_hsfbp_income_verification_task.apply_async(
            (application.id,),
            eta=expired_date,
        )


class JuloOneService(object):
    def check_affordability_julo_one(self, application):
        from juloserver.julo.formulas.experiment import (
            calculation_affordability_based_on_affordability_model,
        )

        if not application.is_julo_one():
            return False

        if not application.eligible_for_sonic():
            return False

        affordability_status = calculation_affordability_based_on_affordability_model(application)

        return affordability_status

    @staticmethod
    def is_high_c_score(application):
        credit_score = CreditScore.objects.filter(application_id=application.id).last()
        if not credit_score:
            julo_logger.warning(
                {"message": "Credit Score not Existed", "application_id": application.id}
            )
            return False

        high_c_score_setting = MobileFeatureSetting.objects.filter(
            feature_name='high_c_setting', is_active=True
        ).first()
        if not high_c_score_setting:
            return False

        if high_c_score_setting and high_c_score_setting.parameters:
            for score_name, status in list(high_c_score_setting.parameters.items()):
                if status['is_active'] and score_name == credit_score.score:
                    return True

        return False

    @staticmethod
    def is_c_score(application):
        credit_score = CreditScore.objects.filter(application_id=application.id).last()
        if not credit_score:
            return False
        return True if credit_score.score in ['C', '--'] else False

    def construct_params_for_affordability(self, application):
        from juloserver.julo.services import get_data_application_checklist_collection

        application_checklist = get_data_application_checklist_collection(application)

        # CA CALCULATION
        sum_undisclosed_expense = 0
        if 'total_current_debt' in application_checklist:
            for expense in application_checklist['total_current_debt']['undisclosed_expenses']:
                sum_undisclosed_expense += expense['amount']

        input_params = {
            'product_line_code': application.product_line.product_line_code,
            'job_start_date': application.job_start,
            'job_end_date': timezone.localtime(application.cdate).date(),
            'job_type': application.job_type,
            'monthly_income': application.monthly_income,
            'monthly_expense': application.monthly_expenses,
            'dependent_count': application.dependent,
            'undisclosed_expense': sum_undisclosed_expense,
            'monthly_housing_cost': application.monthly_housing_cost,
            'application': application,
            'application_id': application.id,
            'application_xid': application.application_xid,
        }

        return input_params

    def get_reason_affordability(self, application):
        reason = None
        if application.is_julo_one():
            if application.status in [
                ApplicationStatusCodes.DOCUMENTS_VERIFIED,
                ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
            ]:
                reason = Affordability.REASON['limit_generation']
            elif application.status == ApplicationStatusCodes.FORM_PARTIAL:
                reason = Affordability.REASON['sonic_preliminary']
        return reason


def assign_julo1_application(application):
    # update workflow and product_line to julo1
    j1_workflow = Workflow.objects.get(name=WorkflowConst.JULO_ONE)
    j1_product_line = ProductLine.objects.get(pk=ProductLineCodes.J1)

    application.workflow = j1_workflow
    application.product_line = j1_product_line
    application.save()


def create_julo1_application(
        customer,
        nik=None,
        app_version=None,
        web_version=None,
        email=None,
        partner=None,
        phone=None,
        onboarding_id=OnboardingIdConst.ONBOARDING_DEFAULT,
):
    j1_workflow = Workflow.objects.get(name=WorkflowConst.JULO_ONE)
    j1_product_line = ProductLine.objects.get(pk=ProductLineCodes.J1)
    application = Application.objects.create(
        customer=customer,
        ktp=nik,
        app_version=app_version,
        web_version=web_version,
        email=email,
        partner=partner,
        workflow=j1_workflow,
        product_line=j1_product_line,
        mobile_phone_1=phone,
        onboarding_id=onboarding_id,
    )

    return application


def create_julo1_application_with_serializer(
    serializer,
    customer,
    device,
    app_version,
    web_version,
    onboarding_id,
    workflow_name=None,
):

    if not workflow_name:
        # update workflow and product_line to julo1
        workflow = Workflow.objects.get(name=WorkflowConst.JULO_ONE)
    else:
        workflow = Workflow.objects.get(name=workflow_name)

    j1_product_line = ProductLine.objects.get(pk=ProductLineCodes.J1)
    application = serializer.save(
        customer=customer,
        device=device,
        app_version=app_version,
        web_version=web_version,
        workflow=workflow,
        product_line=j1_product_line,
        onboarding_id=onboarding_id,
    )

    return application


def is_active_julo1():
    active_julo1_flag = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ACTIVE_JULO1_FLAG, is_active=True
    ).exists()

    return active_julo1_flag


def fetch_application_image_url(customer, image_id):
    application = customer.application_set.regular_not_deletes().last()
    if not application:
        return None
    image = Image.objects.get_or_none(id=image_id, image_source=application.id)
    if image:
        return image.image_url
    return None


def format_pre_long_form_message():
    guidance_message_mobile_feature_setting = MobileFeatureSetting.objects.filter(
        feature_name=MobileFeatureNameConst.PRE_LONG_FORM_GUIDANCE_POP_UP, is_active=True
    ).last()
    if not guidance_message_mobile_feature_setting:
        return dict()

    params = guidance_message_mobile_feature_setting.parameters
    formated_minimum_salary = display_rupiah(int(params.get('minimum_salary')))
    template = Template(params.get('message'))
    formated_message = template.render(
        Context({'formated_minimum_salary': formated_minimum_salary})
    )
    return dict(title=params.get('title'), message=formated_message)


class ApplicationTagTracking(object):
    BY_AGENT = 1
    BY_SYSTEM = 2
    BY_ANY = 0

    def __init__(
        self,
        application: Application,
        old_status_code=None,
        new_status_code=None,
        change_reason=None,
    ):
        self.old_status_code = old_status_code
        self.new_status_code = new_status_code
        self.change_reason = change_reason
        self.application_history = None
        self.application = application
        self.by_who = None
        self._hsfbp = None
        self._c_score = None
        self._sonic = None
        self._in_hsfbp_path = None
        self._income_check = None

    def tracking(self, tag=None, status=None, certain=False):
        active_product_codes = self.get_active_product_code()
        if self.application.product_line_code not in active_product_codes:
            logger.warning(
                {
                    'action': 'application tag tracking',
                    'msg': 'product code is not supported',
                    'data': {
                        'application_id': self.application.id,
                        'product_code': self.application.product_line_code,
                        'active_product_codes': active_product_codes,
                    },
                }
            )
            return
        active_tag = list(self.get_active_tag())
        if certain:
            if tag in active_tag:
                self.adding_application_path_tag(tag, status)
            logger.info(
                {
                    'action': 'application tag tracking',
                    'data': {
                        'application_id': self.application.id,
                        'certain': certain,
                        'tag': tag,
                        'status': status,
                    },
                }
            )
            return
        application_history = ApplicationHistory.objects.filter(
            application=self.application.id,
            status_old=self.old_status_code,
            status_new=self.new_status_code,
        ).last()
        if not application_history:
            raise JuloException('ApplicationHistory not found')

        self.application_history = application_history
        self.by_who = self.is_manual()

        for tag in active_tag:
            method_to_call = getattr(self, tag, None)
            if not method_to_call:
                continue

            status = method_to_call()
            if status is not None:
                self.adding_application_path_tag(tag, status)

    def is_underwriting_overhaul(self):
        valid_condition_list = [
            [0, 100, self.BY_ANY],
        ]
        for condition in valid_condition_list:
            if self.check_condition(condition):
                if is_experiment_application(self.application.id, 'ExperimentUwOverhaul'):
                    return 1
                else:
                    return 0
        return None

    def is_bpjs_scrape(self):
        valid_condition_list = [
            [105, 120, self.BY_ANY],
        ]
        for condition in valid_condition_list:
            if self.check_condition(condition):
                if self.bpjs_successfully_scraped:
                    return 1
                else:
                    return 0
        return None

    def is_bank_scrape(self):
        valid_condition_list = [[105, 120, self.BY_ANY], [120, 121, self.BY_ANY]]
        for condition in valid_condition_list:
            if self.check_condition(condition):
                if not self.bank_successfully_scraped:
                    return 0

        return None

    def is_salary_photo(self):
        valid_condition_list = [
            ([None, 120, self.BY_ANY], 1, 'mandatory'),
            ([None, 121, self.BY_ANY], 1, 'mandatory'),
            ([105, 120, self.BY_ANY], 0, ''),
            ([120, 121, self.BY_ANY], 0, ''),
        ]
        for condition, result, note in valid_condition_list:
            if self.check_condition(condition):
                if note == 'mandatory' and self.has_paystub_image:
                    return result

                if not note and not self.hsfbp and not self.c_score and not self.has_paystub_image:
                    return result

        return None

    def is_bank_statement(self):
        valid_condition_list = [
            ([None, 120, self.BY_ANY], 1, 'mandatory'),
            ([None, 121, self.BY_ANY], 1, 'mandatory'),
            ([105, 120, self.BY_ANY], 0, ''),
            ([120, 121, self.BY_ANY], 0, ''),
        ]
        for condition, result, note in valid_condition_list:
            if self.check_condition(condition):
                if note == 'mandatory' and self.has_bank_statement_image:
                    return result

                if (
                        not note
                        and not self.hsfbp
                        and not self.c_score
                        and not self.has_bank_statement_image
                ):
                    return result

        return None

    def is_dv(self):
        valid_condition_list = [
            ([121, 135, self.BY_AGENT], -1, 'rejection 135'),
            ([121, 135, self.BY_AGENT], -2, 'rejection 135 - job type blacklisted'),
            ([121, 124, self.BY_AGENT], 0, 'sonic checking'),
            ([121, 122, self.BY_AGENT], 1, ''),
            ([121, 131, self.BY_AGENT], 0, ''),
        ]
        for condition, result, note in valid_condition_list:
            if self.check_condition(condition):
                if note == 'rejection 135':
                    if (
                            self.change_reason.lower()
                            in JuloOne135Related.REJECTION_135_DV_CHANGE_REASONS
                    ):
                        return result
                elif note == 'rejection 135 - job type blacklisted':
                    if self.change_reason.lower() == 'job type blacklisted':
                        return result
                elif note == 'sonic checking':
                    if self.sonic:
                        return 4
                    elif not self.sonic and (
                            self.has_paystub_image
                            or self.bank_successfully_scraped
                            or self.bpjs_successfully_scraped
                            or self.has_bank_statement_image
                    ):
                        return 3
                else:
                    return result
        return None

    def is_hsfbp(self):
        valid_condition_list = [
            ([120, 121, self.BY_ANY], 0, 'hsfbp fraud'),
            ([120, 124, self.BY_SYSTEM], 1, 'hsfbp'),
            ([120, 131, self.BY_ANY], 0, 'hsfbp failed'),
        ]
        for condition, result, note in valid_condition_list:
            if self.check_condition(condition):
                if note == 'hsfbp':
                    if self.hsfbp:
                        return result
                elif note == 'hsfbp failed':
                    if self.hsfbp:
                        return result
                elif note == 'hsfbp fraud':
                    if self.hsfbp:
                        return result
        return None

    def is_mandatory_docs(self):
        valid_condition_list = [
            ([105, 106, self.BY_ANY], 0, 'rejected'),
            ([120, 106, self.BY_ANY], 0, 'rejected'),
        ]
        for condition, result, note in valid_condition_list:
            if self.check_condition(condition):
                if note == 'rejected':
                    if not self.hsfbp and not self.c_score:
                        return result
        return None

    def is_sonic(self):
        valid_condition_list = [
            ([120, 121, self.BY_ANY], 1, 'sonic'),
            ([122, 124, self.BY_ANY], 1, 'sonic'),
        ]
        for condition, result, note in valid_condition_list:
            if self.check_condition(condition):
                if note == 'sonic':
                    if self.change_reason == JuloOneChangeReason.SONIC_AFFORDABILITY:
                        return result
                else:
                    return result
        return None

    def is_pve(self):
        valid_condition_list = [
            ([122, 124, self.BY_AGENT], 1, ''),
            ([138, 124, self.BY_AGENT], 1, ''),
            ([138, 139, self.BY_AGENT], 0, ''),
            ([122, 133, self.BY_AGENT], 0, ''),
            ([122, 135, self.BY_AGENT], -1, 'rejection_135'),
            ([122, 135, self.BY_AGENT], 0, ''),
            ([122, 137, self.BY_AGENT], 0, ''),
        ]
        for condition, result, note in valid_condition_list:
            if self.check_condition(condition):
                if note == 'rejection_135':
                    if (
                            self.change_reason.lower()
                            in JuloOne135Related.REJECTION_135_PVE_PVA_CHANGE_REASONS
                    ):
                        return result
                else:
                    return result
        return None

    def is_pva(self):
        valid_condition_list = [
            ([124, 130, self.BY_ANY], 1, 'bypass'),
            ([175, 130, self.BY_ANY], 1, ''),
            ([124, 135, self.BY_ANY], -1, 'rejection_135'),
            ([124, 135, self.BY_ANY], 0, ''),
            ([124, 137, self.BY_ANY], 0, ''),
            ([124, 139, self.BY_ANY], 0, ''),
        ]

        for condition, result, note in valid_condition_list:
            if self.check_condition(condition):
                if note == 'bypass':
                    if not self.in_hsfbp_path and not self.sonic:
                        return result
                elif note == 'rejection_135':
                    if not self.in_hsfbp_path and not self.sonic:
                        if (
                                self.change_reason.lower()
                                in JuloOne135Related.REJECTION_135_PVE_PVA_CHANGE_REASONS
                        ):
                            return result
                else:
                    return result

        return None

    def is_ca(self):
        valid_condition_list = [
            ([130, 141, self.BY_ANY], 1, 'credit'),
            ([130, 142, self.BY_ANY], 0, ''),
        ]

        for condition, result, note in valid_condition_list:
            if self.check_condition(condition):
                if note == 'credit':
                    if self.change_reason == 'Credit limit generated':
                        return result
                else:
                    return result

        return None

    def is_bpjs_bypass(self):
        valid_condition_list = [
            ([105, 130, self.BY_SYSTEM], 1),
        ]
        for condition, result in valid_condition_list:
            if self.check_condition(condition) and self.change_reason == 'bpjs_bypass':
                return result
        return None

    def is_bpjs_entrylevel(self):
        valid_condition_list = [
            ([105, None, self.BY_SYSTEM], 1),
        ]
        for condition, result in valid_condition_list:
            if self.check_condition(condition) and self.change_reason == 'bpjs_entrylevel':
                return result
        return None

    def is_ac(self):
        valid_condition_list = [
            ([141, 150, self.BY_AGENT], 1),
            ([141, 137, self.BY_AGENT], 0),
            ([141, 139, self.BY_AGENT], 0),
        ]
        for condition, result in valid_condition_list:
            if self.check_condition(condition):
                return result
        return None

    def is_doc_resubmission(self):
        valid_condition_list = [([131, 132, self.BY_ANY], 1), ([131, 136, self.BY_AGENT], 0)]
        for condition, result in valid_condition_list:
            if self.check_condition(condition):
                return result
        return None

    def check_status(self, old_status, new_status):
        if old_status is None:
            return self.new_status_code == new_status

        if new_status is None:
            return self.old_status_code == old_status

        old_status_checking = self.old_status_code == old_status
        new_status_checking = self.new_status_code == new_status

        return old_status_checking and new_status_checking

    def is_manual(self):
        return (
            self.BY_AGENT if self.application_history.changed_by_id is not None else self.BY_SYSTEM
        )

    def check_condition(self, data):
        old_status, new_status, by_who = data
        if not self.check_status(old_status, new_status):
            return False
        if by_who != self.BY_ANY:
            if self.by_who != by_who:
                return False
        return True

    @property
    def has_paystub_image(self):
        return Image.objects.filter(image_source=self.application.id, image_type='paystub').exists()

    @property
    def has_bank_statement_image(self):
        return Image.objects.filter(
            image_source=self.application.id, image_type='bank_statement'
        ).exists()

    @property
    def bpjs_successfully_scraped(self):
        application = Application.objects.get(pk=self.application.id)

        from juloserver.bpjs.services import Bpjs

        return Bpjs(application=application).is_scraped

    @property
    def bank_successfully_scraped(self):
        from juloserver.boost.services import check_scrapped_bank

        application = Application.objects.get(pk=self.application.id)
        is_scrapped_bank = check_scrapped_bank(application)
        if not is_scrapped_bank:
            return False

        sd_bank_account = SdBankAccount.objects.filter(application_id=application.id).last()
        if not sd_bank_account:
            return False

        return SdBankStatementDetail.objects.filter(sd_bank_account=sd_bank_account).exists()

    @property
    def hsfbp(self):
        if self._hsfbp is None:
            hsfbp_history = self.application.applicationhistory_set.filter(
                change_reason=FeatureNameConst.HIGH_SCORE_FULL_BYPASS
            ).exists()
            self._hsfbp = hsfbp_history

        return self._hsfbp

    @property
    def in_hsfbp_path(self):
        if self._in_hsfbp_path is None:
            hsfbp_history = self.application.applicationhistory_set.filter(
                status_new=124, status_old=120, changed_by_id__isnull=True
            ).exists()
            self._in_hsfbp_path = self.hsfbp and hsfbp_history

        return self._in_hsfbp_path

    @property
    def c_score(self):
        if self._c_score is None:
            self._c_score = JuloOneService.is_c_score(self.application_history.application)

        return self._c_score

    @property
    def sonic(self):
        if self._sonic is None:
            self._sonic = self.application.applicationhistory_set.filter(
                change_reason=JuloOneChangeReason.SONIC_AFFORDABILITY
            ).exists()

        return self._sonic

    @property
    def income_check(self):
        if self._income_check is None:
            self._income_check = IncomeCheckLog.objects.filter(
                application_id=self.application.id, is_found=True
            ).exists()

        return self._income_check

    def get_active_tag(self):
        return ApplicationTag.objects.filter(is_active=True).values_list(
            'application_tag', flat=True
        )

    def get_active_product_code(self):
        return ProductLineCodes.j1() + ProductLineCodes.julo_starter()

    def get_application_path_tag_status(self, application_tag, status):
        return ApplicationPathTagStatus.objects.get(application_tag=application_tag, status=status)

    def adding_application_path_tag(self, tag, status):
        import traceback

        path_tag_status = self.get_application_path_tag_status(tag, status)
        current_app_tag = ApplicationPathTag.objects.filter(
            application_id=self.application.id,
            application_path_tag_status__application_tag=tag,
        ).last()
        if current_app_tag:
            current_app_tag.application_path_tag_status = path_tag_status
            current_app_tag.save()

            logger.info(
                {
                    "message": "Trace app tag update",
                    "application": self.application.id,
                    "tag": tag,
                    "to_status": status,
                    "stack": traceback.format_stack(),
                }
            )
        else:
            current_app_tag = ApplicationPathTag.objects.create(
                application_id=self.application.id,
                application_path_tag_status=path_tag_status,
            )
        self.adding_application_tag_history(current_app_tag, status)

    def adding_application_tag_history(self, application_tag, tag_status):
        status_code = self.new_status_code
        if not status_code and self.old_status_code is not None:
            status_code = self.old_status_code
        else:
            status_code = self.application.status

        ApplicationPathTagHistory.objects.create(
            application_path_tag_id=application_tag.id,
            application_status_code=status_code,
            tag_status=tag_status,
        )


class AddressFraudPrevention(object):
    def __init__(self, application):
        self.application = application
        self.full_address = None
        self.coordinates = None
        self.geocode_response = None
        self.distance_in_km = None
        self.device_geolocation = None
        self.address_geolocation = None

    def initiate_address_fraud_prevention(self):
        self.get_address_coordinates()
        if not self.coordinates:
            return self.save_and_return_result(suspicious=True)
        inside_limit_radius = self.evaluate_device_and_address_distance()
        if self.coordinates and self.geocode_response and self.distance_in_km:
            self.save_reverse_geolocation()
        return self.save_and_return_result(suspicious=not inside_limit_radius)

    def get_address_coordinates(self):
        self.full_address = ' '.join(
            [
                self.application.address_street_num,
                self.application.address_provinsi,
                self.application.address_kabupaten,
                self.application.address_kecamatan,
                self.application.address_kelurahan,
            ]
        )
        encoded_address = urllib.parse.quote_plus(self.full_address)
        self.get_geocoding_by_address_here_maps(encoded_address)

    def get_geocoding_by_address_here_maps(self, enconded_address):
        here_maps_client = get_here_maps_client()
        (
            self.coordinates,
            self.geocode_response,
        ) = here_maps_client.get_geocoding_response_by_address(enconded_address)

    def save_reverse_geolocation(self):
        ReverseGeolocation.objects.create(
            application=self.application,
            customer_id=self.application.customer_id,
            latitude=self.coordinates.get('lat'),
            longitude=self.coordinates.get('lng'),
            full_address=self.full_address,
            response=self.geocode_response,
            device_geolocation=self.device_geolocation,
            address_geolocation=self.address_geolocation,
            distance_km=self.distance_in_km,
        )

    def evaluate_device_and_address_distance(self):
        device = Device.objects.filter(customer_id=self.application.customer_id).last()
        geolocation = None
        if device:
            self.device_geolocation = geolocation = DeviceGeolocation.objects.filter(
                device=device
            ).last()
        if not geolocation:
            self.address_geolocation = geolocation = AddressGeolocation.objects.filter(
                application=self.application
            ).last()
        if not geolocation:
            return False
        self.distance_in_km = self.calculate_distance(
            geolocation.longitude,
            geolocation.latitude,
            self.coordinates['lng'],
            self.coordinates['lat'],
        )
        if self.distance_in_km < AddressFraudPreventionConstants.DISTANCE_RADIUS_LIMIT_KM:
            return True
        else:
            return False

    def calculate_distance(self, lon1, lat1, lon2, lat2):
        """
        Calculate the great circle distance between two points
        on the earth (specified in decimal degrees)
        """
        # convert decimal degrees to radians
        lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

        # haversine formula
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * asin(sqrt(a))

        radius = 6371  # Radius of earth in kilometers. Use 3956 for miles
        return c * radius

    def save_analysed_result(self, suspicious=False):
        risky_checklist = ApplicationRiskyCheck.objects.filter(application=self.application).last()
        if suspicious:
            if (
                    risky_checklist
                    and risky_checklist.decision
                    and risky_checklist.decision.decision_name
                    in ApplicationRiskyDecisions.no_pve_bypass()
            ):
                decision_name = ApplicationRiskyDecisions.NO_DV_BYPASS_AND_NO_PVE_BYPASS
            else:
                decision_name = ApplicationRiskyDecisions.NO_DV_BYPASS
            decision = ApplicationRiskyDecision.objects.get(decision_name=decision_name)
        else:
            decision = risky_checklist.decision if risky_checklist else None
        if not risky_checklist:
            ApplicationRiskyCheck.objects.create(
                application=self.application, is_address_suspicious=suspicious, decision=decision
            )
        else:
            risky_checklist.is_address_suspicious = suspicious
            risky_checklist.decision = decision
            risky_checklist.save()

    def save_and_return_result(self, suspicious):
        self.save_analysed_result(suspicious)
        return suspicious


def is_suspicious_address(application):
    risky_checklist = ApplicationRiskyCheck.objects.filter(application=application).last()
    if not risky_checklist or risky_checklist.is_address_suspicious is None:
        address_fraud_service = AddressFraudPrevention(application)
        is_fraud = address_fraud_service.initiate_address_fraud_prevention()
        application.refresh_from_db()
        return is_fraud
    return risky_checklist.is_address_suspicious


def suspicious_app_check(application: Application) -> None:
    """
    Check and store if a customer's application contain application that we flagged as suspicious.

    Args:
        application (Application): Application to check for.
    """
    application_risky_check, created = ApplicationRiskyCheck.objects.get_or_create(
        application=application
    )
    if application_risky_check.is_sus_app_detected is not None:
        return

    suspicious_fraud_apps = SuspiciousFraudApps.objects.values_list('package_names', flat=True)
    suspicious_fraud_app_list = list(itertools.chain.from_iterable(suspicious_fraud_apps))

    customer_fraud_applications = SdDeviceApp.objects.filter(
        application_id=application.id, app_package_name__in=suspicious_fraud_app_list
    ).values_list('app_package_name', flat=True)
    if customer_fraud_applications:
        decision_name = ApplicationRiskyDecisions.NO_DV_BYPASS
        if (
                not created
                and application_risky_check.decision
                and application_risky_check.decision.decision_name
                in ApplicationRiskyDecisions.no_pve_bypass()
        ):
            decision_name = ApplicationRiskyDecisions.NO_DV_BYPASS_AND_NO_PVE_BYPASS

        decision = ApplicationRiskyDecision.objects.get(decision_name=decision_name)
        application_risky_check.decision = decision
        application_risky_check.is_sus_app_detected = True
        application_risky_check.sus_app_detected_list = list(customer_fraud_applications)
    else:
        application_risky_check.is_sus_app_detected = False
    application_risky_check.save()


def run_bypass_eligibility_checks(application: Application) -> bool:
    """
    Eligibility check to set decision whether an application is eligible for full bypass.

    Args:
        application (Application): Application object to be checked.

    Returns:
        bool: True if eligible for HSFBP (High Score Full ByPass), False otherwise.
    """
    # Address fraud prevention check
    address_fraud_prevention_feature = MobileFeatureSetting.objects.filter(
        feature_name=MobileFeatureNameConst.ADDRESS_FRAUD_PREVENTION,
        is_active=True,
    ).last()
    if address_fraud_prevention_feature:
        is_suspicious_address(application)

    special_event_fraud_checking(application)
    suspicious_app_check(application)

    return application.eligible_for_hsfbp()


class SpecialEventSettingHelper:
    def __init__(self):
        self._setting = None

    @property
    def setting(self):
        if not self._setting:
            self._setting = FeatureSetting.objects.get_or_none(
                feature_name=FeatureNameConst.SPECIAL_EVENT_BINARY, is_active=True
            )

        return self._setting

    def is_no_bypass(self):
        return self.check_action("No Bypass")

    def is_rejected_105(self):
        return self.check_action("Reject 105")

    def check_action(self, value):
        if self.setting and self.setting.parameters:
            action = self.setting.parameters.get('action')
            if action == value:
                return True

        return False


def special_event_fraud_checking(application):
    is_special_event = AutoDataCheck.objects.filter(
        application_id=application.id, is_okay=False, data_to_check='special_event'
    ).exists()

    decision = ApplicationRiskyDecision.objects.get(
        decision_name=ApplicationRiskyDecisions.NO_DV_BYPASS_AND_NO_PVE_BYPASS
    )

    if hasattr(application, 'applicationriskycheck'):
        application_risky_check = application.applicationriskycheck
    else:
        application_risky_check = ApplicationRiskyCheck.objects.create(application=application)

    application_risky_check.is_special_event = is_special_event
    if is_special_event:
        application_risky_check.decision = decision
    application_risky_check.save()


def bpjs_nik_mismatch_fraud_check(application):
    from juloserver.bpjs.services import Bpjs

    application_risky_check, _ = ApplicationRiskyCheck.objects.get_or_create(
        application=application
    )
    if application_risky_check.is_bpjs_nik_suspicious is not None:
        return

    bpjs = Bpjs(application=application)
    if bpjs.is_identity_match:
        application_risky_check.is_bpjs_nik_suspicious = False
    else:
        if (
                application_risky_check.decision
                and application_risky_check.decision.decision_name
                in ApplicationRiskyDecisions.no_pve_bypass()
        ):
            decision_name = ApplicationRiskyDecisions.NO_DV_BYPASS_AND_NO_PVE_BYPASS
        else:
            decision_name = ApplicationRiskyDecisions.NO_DV_BYPASS
        decision = ApplicationRiskyDecision.objects.get(decision_name=decision_name)
        application_risky_check.is_bpjs_nik_suspicious = True
        application_risky_check.decision = decision
    application_risky_check.save()


def fraud_bank_scrape_and_bpjs_checking(application):
    from juloserver.bpjs.services import Bpjs

    mismatch_name_in_bank_scrape_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FRAUD_MISMATCH_NAME_IN_BANK_THRESHOLD, is_active=True
    ).last()
    if not mismatch_name_in_bank_scrape_feature_setting:
        return 0

    parameter = mismatch_name_in_bank_scrape_feature_setting.parameters
    mismatch_threshold = parameter['mismatch_threshold']
    sd_bank_scrape_data = SdBankAccount.objects.filter(
        application_id=application.id,
    ).last()
    bpjs = Bpjs(application=application)
    bpjs_profile = bpjs.profiles.last()
    if not sd_bank_scrape_data and not bpjs_profile:
        return 3

    application_risky_check_params = dict(
        application=application,
        is_bank_name_suspicious=False,
        is_bpjs_name_suspicious=False,
    )
    if not application.fullname:
        return 3

    long_form_full_name = application.fullname.lower()
    if sd_bank_scrape_data:
        distance_bank_scrape = fuzz.ratio(
            long_form_full_name, sd_bank_scrape_data.customer_name.lower()
        )
        if distance_bank_scrape <= mismatch_threshold:
            application_risky_check_params.update(is_bank_name_suspicious=True)

    if bpjs_profile:
        # todo: adjust real_name with Brick
        distance_bpjs = fuzz.ratio(long_form_full_name, bpjs_profile.real_name.lower())

        if distance_bpjs <= mismatch_threshold:
            application_risky_check_params.update(is_bpjs_name_suspicious=True)

    if (
            application_risky_check_params['is_bank_name_suspicious']
            or application_risky_check_params['is_bank_name_suspicious']
    ):
        application_decision = ApplicationRiskyDecision.objects.filter(
            decision_name=ApplicationRiskyDecisions.NO_DV_BYPASS
        ).last()
        if application_decision:
            application_risky_check_params.update(decision=application_decision)
    with transaction.atomic():
        existing_application_risky = ApplicationRiskyCheck.objects.filter(
            application=application
        ).last()
        if existing_application_risky:
            existing_application_risky.update_safely(**application_risky_check_params)
        else:
            ApplicationRiskyCheck.objects.create(**application_risky_check_params)
        # prevent double check if data already completed
        if sd_bank_scrape_data and bpjs_profile:
            return 0

        return 1


def fraud_message_mismatch_scraping(risky_checklist):
    if not risky_checklist:
        return ''

    mismatch_name_in_bank_scrape_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FRAUD_MISMATCH_NAME_IN_BANK_THRESHOLD, is_active=True
    ).last()
    if not mismatch_name_in_bank_scrape_feature_setting:
        return ''

    if risky_checklist.is_bank_name_suspicious:
        return 'Name mismatch with bank scrape'
    if risky_checklist.is_bpjs_name_suspicious:
        return 'Name mismatch with bpjs scrape'
    return ''


def suspicious_hotspot_app_fraud_check(application):
    from juloserver.julo.services import check_fraud_hotspot_gps

    address_geolocation = AddressGeolocation.objects.filter(application=application).last()
    if not address_geolocation:
        logger.warning(
            'application has no address geolocation|application_id={}'.format(application.id)
        )
        return

    is_fh = check_fraud_hotspot_gps(address_geolocation.latitude, address_geolocation.longitude)
    app_risk_check = capture_suspicious_app_risk_check(application, 'is_fh_detected', is_fh)
    if is_fh:
        today = timezone.localtime(timezone.now()).date()
        fh_reverse_experiment = (
            ExperimentSetting.objects.filter(
                code=ExperimentConst.FRAUD_HOTSPOT_REVERSE_EXPERIMENT, is_active=True
            )
            .filter(
                (Q(start_date__date__lte=today) & Q(end_date__date__gte=today))
                | Q(is_permanent=True)
            )
            .last()
        )
        if fh_reverse_experiment:
            group = 'control'
            criteria_list = fh_reverse_experiment.criteria.get(
                'test_group_last_two_digits_app_id', []
            )
            app_id_last_two_digits = int(str(application.id)[-2:])
            if app_id_last_two_digits in criteria_list:
                group = 'experiment'
            ExperimentGroup.objects.create(
                experiment_setting=fh_reverse_experiment, application=application, group=group
            )
    return app_risk_check


def capture_suspicious_app_risk_check(application, suspicious_type, is_suspicious):
    created = False
    app_risk_check = ApplicationRiskyCheck.objects.filter(application=application).last()
    if not app_risk_check:
        app_risk_check, created = create_or_update_application_risky_check(application)

    decision = app_risk_check.decision
    update_data = {}
    if is_suspicious:
        decision_name = ApplicationRiskyDecisions.NO_DV_BYPASS
        if (
                not created
                and app_risk_check.decision
                and app_risk_check.decision.decision_name in ApplicationRiskyDecisions.no_pve_bypass()
        ):
            decision_name = ApplicationRiskyDecisions.NO_DV_BYPASS_AND_NO_PVE_BYPASS
        decision = ApplicationRiskyDecision.objects.get(decision_name=decision_name)

    if getattr(app_risk_check, suspicious_type) != is_suspicious:
        update_data[suspicious_type] = is_suspicious
    if app_risk_check.decision != decision:
        update_data["decision"] = decision
    if update_data:
        app_risk_check.update_safely(**update_data)

    return app_risk_check


def log_emulator_check_eligbility(data):
    EmulatorCheckEligibilityLog.objects.create(**data)


def verify_emulator_check_eligibility(application):
    from juloserver.apiv2.services import check_binary_result
    from juloserver.julo_starter.services.onboarding_check import check_bpjs_and_dukcapil_for_turbo

    try:
        log_data = {'application_id': application.id, "application_status": application.status}
        is_jstarter = application.is_julo_starter()
        if is_jstarter:
            existing_emulator_check = EmulatorCheck.objects.filter(application=application).exists()
        else:
            existing_emulator_check = EmulatorCheck.objects.filter(
                application=application, error_msg__isnull=True
            ).exists()
        if existing_emulator_check:
            log_data.update({"remarks": "Already checked by emulator", "is_eligible": False})
            log_emulator_check_eligbility(log_data)
            return False

        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.EMULATOR_DETECTION, is_active=True
        ).last()

        if is_jstarter:
            from juloserver.julo_starter.services.submission_process import check_affordability

        if not feature_setting or not feature_setting.parameters.get('active_emulator_detection'):
            log_data.update(
                {
                    "remarks": "Feature Setting not found or parameters not found",
                    "is_eligible": False,
                }
            )
            if is_jstarter:
                with transaction.atomic():
                    # prevent inconsistency data for second-check-status API
                    application = Application.objects.select_for_update().get(id=application.id)
                    detokenized_applications = detokenize_for_model_object(
                        PiiSource.APPLICATION,
                        [
                            {
                                'customer_xid': application.customer.customer_xid,
                                'object': application,
                            }
                        ],
                        force_get_local_data=True,
                    )
                    application = detokenized_applications[0]
                    if check_affordability(application):
                        logger.info(
                            {
                                "application_id": application.id,
                                "action": "initiate bpjs and dukcapil check",
                                "function": "verify_emulator_check_eligibility",
                                "current_status": application.status,
                            }
                        )

                        check_bpjs_and_dukcapil_for_turbo(application)

            log_emulator_check_eligbility(log_data)
            return False
        else:
            if (
                    application
                    and application.status >= ApplicationStatusCodes.FORM_PARTIAL
                    and application.product_line_id == ProductLineCodes.J1
            ):
                passed_checks = check_binary_result(application)
                log_data.update({"passed_binary_checks": passed_checks})
                if (
                        passed_checks
                        and hasattr(application, 'creditscore')
                        and application.creditscore.score not in ['C', '--']
                ):
                    log_data['is_eligible'] = True
                    log_emulator_check_eligbility(log_data)
                    return {'timeout': feature_setting.parameters.get('timeout', 20)}
            elif application and is_jstarter:
                with transaction.atomic():
                    # prevent inconsistency data for second-check-status API
                    application = Application.objects.select_for_update().get(id=application.id)
                    if check_affordability(application):
                        log_data['is_eligible'] = True
                        log_emulator_check_eligbility(log_data)
                        return {'timeout': feature_setting.parameters.get('timeout', 20)}

        log_data['is_eligible'] = False
        log_emulator_check_eligbility(log_data)
        return False
    except Exception:
        get_julo_sentry_client().captureException()
        return False


def still_in_experiment(experiment_type, application=None, experiment=None):
    """
    This function will check experiment with
    start/end with date and time Experiment.
    """

    today = timezone.localtime(timezone.now())

    if not experiment:
        experiment = ExperimentSetting.objects.filter(code=experiment_type).last()

    if experiment:
        start_date = timezone.localtime(experiment.start_date)
        end_date = timezone.localtime(experiment.end_date)

        if experiment.code == 'ExperimentUwOverhaul':
            if allow_min_apk_version(experiment, application):
                if experiment.is_permanent:
                    return True
                elif start_date <= today <= end_date:
                    if experiment.is_active:
                        return True
                else:
                    return False
            return False
        else:
            if experiment.is_permanent:
                return True
            elif start_date <= today <= end_date:
                if experiment.is_active:
                    return True
            else:
                return False

    return False


def list_experiment_application(experiment_code, application_id):
    experiment = Experiment.objects.filter(code=experiment_code).last()

    if experiment:
        experiment_test = ExperimentTestGroup.objects.filter(experiment=experiment).last()
        value = experiment_test.value.split(':', 2)
        total_digit = abs(int(value[1]))
        digits = value[2].split(',')
        last_digit_of_application = str(application_id % (10 ** total_digit))
        if last_digit_of_application in digits:
            ApplicationExperiment.objects.get_or_create(
                application_id=application_id, experiment=experiment
            )
            valid_application = True
        else:
            valid_application = False
    else:
        valid_application = False

    return valid_application


def allow_min_apk_version(experiment, application):
    application_apk_version = application.app_version
    experiment_apk_version = experiment.criteria["min_apk_version"]

    if application_apk_version:
        if semver.match(application_apk_version, ">={}".format(experiment_apk_version)):
            return True

    return False


def store_application_to_experiment_table(
        application, experiment_code, app_version=None, for_reapply=False, customer=None
):
    if (still_in_experiment(experiment_code, application) and application.is_julo_one()) or (
        application.is_web_app()
        or application.is_partnership_webapp()
        or application.is_julo_one_ios()
    ):
        list_experiment_application(experiment_code, application.id)

        if application.onboarding_id == OnboardingIdConst.JULO_STARTER_FORM_ID:
            if not customer:
                customer = application.customer
            determine_by_experiment_julo_starter(
                customer,
                application,
                app_version,
                for_reapply=for_reapply,
            )


def is_experiment_application(application_id, experiment_code):
    if experiment_code == ExperimentConst.JULO_STARTER_EXPERIMENT:
        experiment_setting = ExperimentSetting.objects.filter(
            code=ExperimentConst.JULO_STARTER_EXPERIMENT, is_active=True
        ).last()
        result = ExperimentGroup.objects.filter(
            application_id=application_id, experiment_setting=experiment_setting
        ).last()

        return result

    experiment = Experiment.objects.filter(code=experiment_code).last()
    result = ApplicationExperiment.objects.filter(
        application_id=application_id, experiment=experiment
    ).last()

    return result


def check_sonic_bypass(application):
    sonic_path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_sonic', status=1
    ).last()
    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=sonic_path_tag
    ).last()

    if application_path:
        return True

    return False


def check_hsfbp_bypass(application):
    hsfbp_path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_hsfbp', status=1
    ).last()
    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=hsfbp_path_tag
    ).last()

    if application_path:
        return True

    return False


def check_revive_mtl(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_revive_mtl', status=1
    ).last()
    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).last()

    if application_path:
        return True

    return False


def check_bpjs_bypass(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_bpjs_bypass', status=1
    ).last()
    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).last()

    if application_path:
        return True

    return False


def check_bpjs_entrylevel(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_bpjs_entrylevel', status=1
    ).last()
    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).last()

    if application_path:
        return True

    return False


def check_bpjs_found(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_bpjs_found', status=1
    ).last()
    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).last()

    if application_path:
        return True

    return False


def is_121_via_brick_revival(application: Application):
    from juloserver.bpjs.services.x105_revival import X105Revival

    return application.applicationhistory_set.filter(
        status_new=121,
        change_reason__in=[
            X105Revival.REASON_PASSED_COMPLETE,
            X105Revival.REASON_PASSED_DIFF_COMPANY,
        ],
    ).exists()


def is_offline_activation(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_offline_activation', status=1
    ).last()
    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).last()

    if application_path:
        return True

    return False


def is_entry_level_swapin(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_entry_level_swapin', status=1
    ).last()
    if not path_tag:
        return False

    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).last()

    if application_path:
        return True

    return False

def not_eligible_offline_activation(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_offline_activation', status=1
    ).last()
    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).last()

    if application_path:
        failed_tag = ApplicationPathTagStatus.objects.filter(
            application_tag='is_offline_activation', status=0
        ).last()
        application_path.update_safely(application_path_tag_status=failed_tag)

    return

def is_offline_activation_low_pgood(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_offline_activation_low_pgood', status=1
    ).last()
    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).last()

    if application_path:
        return True

    return False


def check_bad_history(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_bad_history', status=1
    ).last()
    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).last()

    if application_path:
        return True

    return False


def _assign_bad_history_path_tag(application):
    from juloserver.application_flow.tasks import application_tag_tracking_task

    has_tag = check_bad_history(application)

    if has_tag:
        return

    application_tag_tracking_task(application.id, None, None, None, 'is_bad_history', 1)


def is_c_plus_score(application):
    credit_score = CreditScore.objects.filter(application=application).last()

    if credit_score:
        if credit_score.score == 'C+':
            return True

    return False


def is_goldfish(application: Application):
    return EligibleCheck.objects.filter(
        application_id=application.id, check_name="eligible_goldfish", is_okay=True
    ).exists()


def is_eligible_lannister(application: Application):
    return EligibleCheck.objects.filter(
        application_id=application.id, check_name="eligible_lannister", is_okay=True
    ).exists()


def check_is_success_goldfish(application: Union[int, Application]):
    if isinstance(application, int):
        application = Application.objects.get(pk=application)

    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_goldfish', status=1
    ).last()
    return ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).exists()


def check_telco_pass(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_telco_pass', status=1
    ).last()
    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).last()

    if application_path:
        return True

    return False


def check_success_submitted_bank_statement(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_submitted_bank_statement', status=1
    ).last()
    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).last()

    if application_path:
        return True

    return False


def check_good_fdc(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_good_fdc', status=1
    ).last()

    return ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).exists()


def check_waitlist(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_waitlist', status=1
    ).last()

    return ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).exists()


def check_click_pass(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_clik_pass', status=1
    ).last()

    return ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).exists()


def is_click_model(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_clik_model', status=1
    ).last()

    return ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).exists()

def check_has_path_tag(application_id, path_tag, status=1):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag=path_tag,
        status=status
    ).last()

    if not path_tag:
        return False

    return ApplicationPathTag.objects.filter(
        application_id=application_id,
        application_path_tag_status=path_tag
    ).exists()


def check_good_fdc_bypass(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_good_fdc_bypass', status=1
    ).last()
    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).last()

    if application_path:
        return True

    return False


def _update_failed_good_fdc_bypass(application):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_good_fdc_bypass', status=1
    ).last()
    failed_path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_good_fdc_bypass', status=0
    ).last()
    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).last()

    if not application_path:
        return

    application_path.update_safely(application_path_tag_status=failed_path_tag)


def has_good_fdc_el_tag(application):
    path_tags = ApplicationPathTagStatus.objects.filter(
        application_tag='is_good_fdc_el'
    ).values_list('id', flat=True)
    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status__in=path_tags
    )

    return len(application_path) > 0


def check_is_fdc_tag(application, status=1):
    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag='is_fdc', status=status
    ).last()
    application_path = ApplicationPathTag.objects.filter(
        application_id=application.id, application_path_tag_status=path_tag
    ).last()

    if application_path:
        return True

    return False


def check_liveness_detour_workflow_status_path(
        application: Application, status_new: int, status_old: int = None, change_reason: str = None
) -> bool:
    """
    Checks if an application has history of successful liveness manual check when transitioning
        from x134 to x105.

    Args:
        application (Application): Application object to be checked.
        status_new (int): For filtering ApplicationHistory that will be checked.
        status_old (int): For filtering ApplicationHistory that will be checked.
        change_reason (str):

    Returns:
        bool: True if application detected passing liveness check. False otherwise.
    """

    if not status_old:
        application_history = ApplicationHistory.objects.filter(
            application=application, status_new=status_new
        ).last()
        status_old = application_history.status_old if application_history else None
        change_reason = application_history.change_reason if application_history else None

    if (
            status_new == ApplicationStatusCodes.FORM_PARTIAL
            and status_old == ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR
            and change_reason == 'Success manual check liveness'
    ):
        return True

    return False


def process_emulator_detection(emulator_check_data: dict) -> None:
    from juloserver.julo.services import process_application_status_change

    fail_emulator_check_condition = (
            emulator_check_data.get('cts_profile_match') is False
            and emulator_check_data.get('basic_integrity') is False
            and not emulator_check_data.get('error_msg')
    )
    if fail_emulator_check_condition:
        feature_setting = FeatureSetting.objects.filter(
            feature_name='emulator_detection', is_active=True
        ).last()
        if feature_setting.parameters.get('reject_fail_emulator_detection'):
            with transaction.atomic():
                application = (
                    Application.objects.select_for_update()
                    .filter(id=emulator_check_data['application_id'])
                    .last()
                )
                if (
                        application.status
                        in ApplicationStatusCodes.eligible_for_emualtor_check_rejection()
                ):
                    process_application_status_change(
                        emulator_check_data['application_id'],
                        ApplicationStatusCodes.APPLICATION_DENIED,
                        JuloOneChangeReason.EMULATOR_DETECED,
                    )
                else:
                    logger.info(
                        {
                            'action': 'process_emulator_detection',
                            'application_id': str(application.id),
                            'application_status_code': str(application.status),
                            'message': "Application was not moved to 135 after emulator has been "
                                       "detected",
                        }
                    )


def check_application_version(application):
    onboarding = application.onboarding
    if onboarding:
        if onboarding.id in (
                OnboardingIdConst.SHORTFORM_ID,
                OnboardingIdConst.LONGFORM_SHORTENED_ID,
                OnboardingIdConst.LFS_REG_PHONE_ID,
                OnboardingIdConst.JULO_360_EXPERIMENT_ID,
        ):
            sonic_shortform = True
        else:
            sonic_shortform = False
    else:
        sonic_shortform = False

    return sonic_shortform


def create_or_update_application_risky_check(application, data=None):
    created = False
    try:
        data = {} if not data else data
        with transaction.atomic():
            app_risky_check = ApplicationRiskyCheck.objects.create(application=application, **data)
        created = True
    except IntegrityError:
        logger.debug('application_risky_check_duplication_error|data={}'.format(data))

    if not created:
        app_risky_check = ApplicationRiskyCheck.objects.filter(application=application).last()
        if not app_risky_check:
            raise JuloException(
                'application_risky_check_duplication_not_found|' 'data={}'.format(data)
            )
        if data:
            app_risky_check.update_safely(refresh=False, **data)

    return app_risky_check, created


def reject_application_by_google_play_integrity(emulator_check: EmulatorCheck) -> None:
    from juloserver.julo.services import process_application_status_change
    from juloserver.julo_starter.services.submission_process import check_affordability
    from juloserver.julo_starter.services.onboarding_check import check_bpjs_and_dukcapil_for_turbo

    if emulator_check.error_msg != '' and emulator_check.error_msg is not None:
        return

    application_id = emulator_check.application_id
    application = Application.objects.get(id=application_id)
    is_jstarter = application.is_jstarter

    device_recognition_verdict = emulator_check.device_recognition_verdict
    is_emulator = (
            device_recognition_verdict is None
            or device_recognition_verdict == {}
            or device_recognition_verdict == []
            or "MEETS_VIRTUAL_INTEGRITY" in device_recognition_verdict
    )
    if not is_emulator:
        if is_jstarter:
            with transaction.atomic():
                # prevent inconsistency data for second-check-status API
                application = Application.objects.select_for_update().get(id=application_id)
                if check_affordability(application):
                    logger.info(
                        {
                            "application_id": application.id,
                            "action": "initiate bpjs and dukcapil check",
                            "function": "verify_emulator_check_eligibility",
                            "current_status": application.status,
                        }
                    )

                    check_bpjs_and_dukcapil_for_turbo(application)
        return

    feature_setting = FeatureSetting.objects.filter(
        feature_name='emulator_detection', is_active=True
    ).last()
    if not feature_setting or not feature_setting.parameters.get('reject_fail_emulator_detection'):
        if is_jstarter:
            with transaction.atomic():
                # prevent inconsistency data for second-check-status API
                application = Application.objects.select_for_update().get(id=application_id)
                if check_affordability(application):
                    logger.info(
                        {
                            "application_id": application.id,
                            "action": "initiate bpjs and dukcapil check",
                            "function": "verify_emulator_check_eligibility",
                            "current_status": application.status,
                        }
                    )

                    check_bpjs_and_dukcapil_for_turbo(application)
            return

    with transaction.atomic():
        application = (
            Application.objects.select_for_update().filter(id=emulator_check.application_id).last()
        )
        if is_jstarter and application.status == ApplicationStatusCodes.FORM_PARTIAL:
            process_application_status_change(
                emulator_check.application_id,
                ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                JuloOneChangeReason.EMULATOR_DETECED,
            )
            return

        if application.status in ApplicationStatusCodes.eligible_for_emualtor_check_rejection():
            process_application_status_change(
                emulator_check.application_id,
                ApplicationStatusCodes.APPLICATION_DENIED,
                JuloOneChangeReason.EMULATOR_DETECED,
            )
        else:
            logger.info(
                {
                    'action': 'process_emulator_detection',
                    'application_id': str(application.id),
                    'application_status_code': str(application.status),
                    'message': "Application was not moved to 135 after emulator has been detected",
                }
            )


def is_referral_blocked(application) -> bool:
    if application.referral_code:
        referral_code = str(application.referral_code).lower()
        if referral_code in JuloOne135Related.ALL_REJECTED_REFERRAL_CODE:
            return True
    return False


def has_bad_history_customer(application):
    from dateutil.relativedelta import relativedelta

    customer_removal = CustomerRemoval.objects.filter(nik=application.ktp).last()
    within_2years = timezone.localtime(timezone.now()) - relativedelta(years=2)

    if not customer_removal:
        julo_logger.info(
            {
                'action': 'has_bad_history_customer',
                'application': application.id,
                'status': application.status,
                'message': 'not found in customer removal',
            }
        )
        return False

    old_application = customer_removal.application
    if not old_application:
        return False

    account = Account.objects.get_or_none(customer=old_application.customer)
    account_payment = AccountPayment.objects.filter(account=account).last()

    if (
            account_payment
            and account_payment.dpd > 0
            and account_payment.cdate.date() > within_2years.date()
    ):
        julo_logger.info(
            {
                'action': 'has_bad_history_customer',
                'application': application.id,
                'old application': old_application.id,
                'status': application.status,
                'message': 'has DPD',
            }
        )
        return True

    if (
            account
            and account.status_id >= JuloOneCodes.SUSPENDED
            and account.cdate.date() > within_2years.date()
    ):
        julo_logger.info(
            {
                'action': 'has_bad_history_customer',
                'application': application.id,
                'old application': old_application.id,
                'status': application.status,
                'message': 'account status >= x430',
            }
        )
        return True

    has_fraud_application = ApplicationHistory.objects.filter(
        application=old_application, status_new=133
    ).last()
    if has_fraud_application and has_fraud_application.cdate.date() > within_2years.date():
        julo_logger.info(
            {
                'action': 'has_bad_history_customer',
                'application': application.id,
                'old application': old_application.id,
                'status': application.status,
                'message': 'fraud_application_history',
            }
        )
        return True

    account_history_fraud_statuses = [440, 441, 442, 443]
    has_fraud_account = AccountStatusHistory.objects.filter(
        account=account,
        status_new__in=account_history_fraud_statuses,
    ).last()
    if has_fraud_account and has_fraud_account.cdate.date() > within_2years.date():
        julo_logger.info(
            {
                'action': 'has_bad_history_customer',
                'application': application.id,
                'old application': old_application.id,
                'status': application.status,
                'message': 'fraud_account_history',
            }
        )
        return True

    julo_logger.info(
        {
            'action': 'has_bad_history_customer',
            'application': application.id,
            'old application': old_application.id,
            'status': application.status,
            'message': 'found in customer removal but good performance',
        }
    )
    return False


def process_bad_history_customer(application):
    if application.partner:
        return False

    if application.status not in (105, 130):
        return False

    from juloserver.julo.services import process_application_status_change

    is_bad_history_customer = has_bad_history_customer(application)

    if is_bad_history_customer:
        _assign_bad_history_path_tag(application)
        change_reason = JuloOneChangeReason.BAD_HISTORY_CUSTOMER
        julo_logger.info(
            {
                'action': 'is_bad_history_customer',
                'application': application.id,
                'change_reason': change_reason,
            }
        )
        process_application_status_change(
            application.id,
            ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason,
        )
        return True

    return False


@sentry_client.capture_exceptions
def determine_by_experiment_julo_starter(
        customer, application, app_version=None, for_reapply=False
):
    """
    Check for experiment still active or not
    Determine onboarding by experiment Julo Starter
    """

    customer_id = customer.id if customer else None
    onboarding_id = application.onboarding_id if application else None

    # check by rule criteria
    setting = ExperimentSetting.objects.filter(code=ExperimentConst.JULO_STARTER_EXPERIMENT).last()
    in_experiment = still_in_experiment(
        experiment_type=ExperimentConst.JULO_STARTER_EXPERIMENT,
        experiment=setting,
    )

    if for_reapply and not in_experiment:
        return False

    # check experiment still in going or not
    if in_experiment and app_version and customer_id and setting:
        if (
                ExperimentJuloStarterKeys.JULOSTARTER not in setting.criteria
                and ExperimentJuloStarterKeys.TARGET_VERSION not in setting.criteria
        ):
            error_msg = "Criteria experiment is invalid"
            julo_logger.error(
                {
                    "message": error_msg,
                    "in_experiment": in_experiment,
                    "customer": customer_id,
                    "onboarding": onboarding_id,
                    "app_version": app_version,
                }
            )
            raise JuloException(error_msg)

        try:
            if is_version_target(
                    app_version, setting.criteria[ExperimentJuloStarterKeys.TARGET_VERSION]
            ):
                return run_criteria_experiment(customer, application, setting, app_version)

        except Exception as error:
            error_msg = str(error)
            julo_logger.error(
                {
                    "message": error_msg,
                    "in_experiment": in_experiment,
                    "customer": customer_id,
                    "onboarding": onboarding_id,
                    "app_version": app_version,
                }
            )
            raise JuloException(error_msg)

    julo_logger.info(
        {
            "message": "Process without experiment",
            "in_experiment": in_experiment,
            "customer": customer_id,
            "onboarding": onboarding_id,
            "app_version": app_version,
        }
    )

    return application


def has_good_score_mycroft(application):
    mycroft_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.MYCROFT_THRESHOLD_SETTING, is_active=True
    ).last()

    if not mycroft_setting or not application.is_assisted_selfie:
        return True

    mycroft_score_ana = PdApplicationFraudModelResult.objects.filter(
        application_id=application.id
    ).last()
    mycroft_score = None
    if mycroft_score_ana:
        mycroft_score = ceil(mycroft_score_ana.pgood * 100) / 100

    if mycroft_score and application.is_assisted_selfie:
        if mycroft_score > mycroft_setting.parameters['threshold']:
            return True

    return False


def pass_mycroft_threshold(application_id):
    from juloserver.julo.services import process_application_status_change

    application = Application.objects.get_or_none(id=application_id)

    if application.is_assisted_selfie is None:
        application.update_safely(is_assisted_selfie=False)

    is_good_score = has_good_score_mycroft(application)

    if is_good_score:
        return True

    process_application_status_change(
        application.id,
        ApplicationStatusCodes.APPLICATION_DENIED,
        JuloOneChangeReason.ASSISTED_SELFIE,
    )
    return False


def is_version_target(app_version, target_versions):
    """
    Check target experiment by app_version
    """

    import semver

    if target_versions:
        return semver.match(app_version, target_versions)
    return False


def run_criteria_experiment(customer, application, setting, app_version):
    """
    For run and check criteria experiment
    """

    onboarding_experiment = None
    group_name = None
    customer_id = customer.id if customer else None
    last_digit = customer.id % 10

    # Get rule for JuloStarter
    if last_digit in setting.criteria[ExperimentJuloStarterKeys.JULOSTARTER]:
        onboarding_experiment = OnboardingIdConst.JULO_STARTER_FORM_ID
        group_name = ExperimentJuloStarterKeys.GROUP_NON_REGULAR

    elif last_digit in setting.criteria[ExperimentJuloStarterKeys.REGULAR]:
        onboarding_experiment = OnboardingIdConst.LONGFORM_SHORTENED_ID
        group_name = ExperimentJuloStarterKeys.GROUP_REGULAR

    if onboarding_experiment:
        # Save to experiment group
        ExperimentGroup.objects.create(
            experiment_setting=setting, customer=customer, application=application, group=group_name
        )

        julo_logger.info(
            {
                "message": "Experiment JuloStarter is running",
                "customer": customer_id,
                "onboarding": onboarding_experiment,
                "app_version": app_version,
                "setting_criteria": str(setting.criteria) if setting else None,
            }
        )

        # Ger fresh data from db
        application.refresh_from_db()
        application.update_safely(onboarding_id=onboarding_experiment)

    return application


def record_google_play_integrity_api_emulator_check_data(
        application, decoded_response=None, error_message=None, emulator_check=None,
        save_record=True
):
    if error_message:
        stored_data = {"error_msg": error_message}
    else:
        data = decoded_response.get('tokenPayloadExternal')
        if "requestDetails" in data:
            if "timestampMillis" in data['requestDetails']:
                data["requestDetails"]["timestampMillis"] = timezone.localtime(
                    datetime.datetime.fromtimestamp(
                        int(data["requestDetails"]["timestampMillis"]) / 1000,
                    )
                )
            else:
                data["requestDetails"]["timestampMillis"] = None
        else:
            data["requestDetails"] = {}
            data["requestDetails"]["timestampMillis"] = None
            data["requestDetails"]["nonce"] = None

        if "appIntegrity" in data:
            if "certificateSha256Digest" not in data["appIntegrity"]:
                data["appIntegrity"]["certificateSha256Digest"] = []
            if "packageName" not in data["appIntegrity"]:
                data["appIntegrity"]["packageName"] = None
            if "appRecognitionVerdict" not in data["appIntegrity"]:
                data["appIntegrity"]["appRecognitionVerdict"] = None
        else:
            data["appIntegrity"] = {}
            data["appIntegrity"]["certificateSha256Digest"] = []
            data["appIntegrity"]["packageName"] = None
            data["appIntegrity"]["appRecognitionVerdict"] = None

        if "deviceIntegrity" in data:
            if "deviceRecognitionVerdict" not in data["deviceIntegrity"]:
                data["deviceIntegrity"]["deviceRecognitionVerdict"] = None
        else:
            data["deviceIntegrity"] = {}
            data["deviceIntegrity"]["deviceRecognitionVerdict"] = None

        if "accountDetails" in data:
            if "appLicensingVerdict" not in data["accountDetails"]:
                data["accountDetails"]["appLicensingVerdict"] = None
        else:
            data["accountDetails"] = {}
            data["accountDetails"]["appLicensingVerdict"] = None

        certificateSha256Digest = ",".join(data["appIntegrity"]["certificateSha256Digest"])

        device_integrity = data.get("deviceIntegrity", {})
        device_activity_level = device_integrity.get("recentDeviceActivity", {}).get(
            "deviceActivityLevel", ''
        )

        env_details = data.get('environmentDetails', {})
        app_access_risk_verdict = env_details.get('appAccessRiskVerdict', {}).get(
            'appsDetected', []
        )
        play_protect_verdict = env_details.get('playProtectVerdict', '')

        stored_data = {
            "timestamp_ms": data["requestDetails"]["timestampMillis"],
            "nonce": data["requestDetails"]["nonce"],
            "apk_package_name": data["appIntegrity"]["packageName"],
            "apk_certificate_digest_sha_256": f"[{certificateSha256Digest}]",
            "app_recognition_verdict": data["appIntegrity"]["appRecognitionVerdict"],
            "device_recognition_verdict": data["deviceIntegrity"]["deviceRecognitionVerdict"],
            "app_licensing_verdict": data["accountDetails"]["appLicensingVerdict"],
            "app_access_risk_verdict": app_access_risk_verdict,
            "play_protect_verdict": play_protect_verdict,
            "device_activity_level": device_activity_level,
            "original_response": str(decoded_response),
        }
    stored_data["application"] = application
    stored_data["service_provider"] = "GooglePlayIntegrity"
    if error_message:
        if not emulator_check:
            emulator_check = EmulatorCheck.objects.filter(
                application=application,
                error_msg__icontains=error_message,
            ).last()
            if not emulator_check:
                emulator_check = EmulatorCheck.objects.create(**stored_data)

        error_occurrences = emulator_check.error_occurrences
        if not error_occurrences:
            error_occurrences = []
        retry_occurrence_count = len(error_occurrences)
        occurrence = "retry - {} : {}".format(
            str(retry_occurrence_count),
            timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S'),
        )
        error_occurrences.append(occurrence)
        emulator_check.error_occurrences = error_occurrences
        if save_record:
            emulator_check.save()
    else:
        if save_record:
            emulator_check = EmulatorCheck.objects.create(**stored_data)
        else:
            emulator_check = EmulatorCheck(**stored_data)
    return emulator_check


def is_suspicious_domain(email: str) -> bool:
    """
    Check if an email domain has suspicious.

    Args:
        email (str): The email of an application

    Returns:
        bool: True if an email has suspicious domain, False otherwise.
    """

    if not email:
        return False
    try:
        domain = '@' + email.split('@')[1]
        blacklisted_domain = SuspiciousDomain.objects.filter(email_domain=domain)
        if blacklisted_domain.exists():
            return True
        return False
    except Exception:
        return False


def get_tutorial_bottom_sheet_content():
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.TUTORIAL_BOTTOM_SHEET, is_active=True
    )
    if not feature_setting:
        return None

    parameters = feature_setting.parameters
    try:
        image_url = parameters['image_url']
        parameters['image_url'] = get_oss_public_url(settings.OSS_PUBLIC_ASSETS_BUCKET, image_url)
        return parameters
    except Exception:
        sentry_client.captureException()
        return None


def increment_counter(redis_key, default_counter=1, limit_counter=10):
    """
    Increment process to stored data in redis
    """

    redis_client = get_redis_client()

    cache = redis_client.get(redis_key)
    if not cache:
        redis_client.set(redis_key, default_counter)
        logger.info(
            {
                'message': 'init counter as 1',
                'key': redis_key,
            }
        )
        return default_counter

    if int(cache) >= limit_counter:
        redis_client.set(redis_key, default_counter)
        logger.info(
            {
                'message': 'reset increment to 1',
                'key': redis_key,
            }
        )
        return default_counter

    current_counter = redis_client.increment(
        redis_key,
    )

    logger.info(
        {
            'message': 'running increment to {}'.format(current_counter),
            'key': redis_key,
        }
    )
    return current_counter


def registration_method_is_video_call(application):
    vcdv_tag_ids = ApplicationPathTagStatus.get_ids_from_tag(IDFyApplicationTagConst.TAG_NAME)
    return (
        ApplicationPathTag.objects.filter(
            application_id=application.id, application_path_tag_status_id__in=vcdv_tag_ids
        ).exists()
        if vcdv_tag_ids
        else False
    )


def pass_binary_check_scoring(application):
    if application.partner:
        return False

    return EligibleCheck.objects.filter(
        application_id=application.id, check_name="eligible_vendor_check", is_okay=True
    ).exists()


def bypass_binary_check_campaign(application):
    if application.partner:
        return False

    eligible = EligibleCheck.objects.filter(
        application_id=application.id,
        is_okay=True,
        check_name='eligible_offline_booth',
    ).exists()

    return eligible


def eligible_to_offline_activation_flow(application):
    if application.partner:
        if application.partner.name == PartnerNameConstant.QOALASPF:
            return True

    has_path_tag = is_offline_activation(application)
    binary_okay = bypass_binary_check_campaign(application)

    return has_path_tag and binary_okay


def eligible_entry_level(application_id):
    return EligibleCheck.objects.filter(
        application_id=application_id,
        is_okay=True,
        check_name='eligible_entry_level',
    ).exists()


def eligible_entry_level_swapin(application_id):
    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ELIGIBLE_ENTRY_LEVEL_SWAPIN
    ).last()

    is_eligible = EligibleCheck.objects.filter(
        application_id=application_id,
        is_okay=True,
        check_name='eligible_entry_level_swapin',
    ).exists()

    return setting and setting.is_active and is_eligible


def eligible_vendor_check_telco(application_id):
    return EligibleCheck.objects.filter(
        application_id=application_id,
        is_okay=True,
        check_name='eligible_vendor_check_telco',
    ).exists()


def eligible_waitlist(application_id):
    setting = FeatureSetting.objects.filter(feature_name=FeatureNameConst.WAITING_LIST).last()

    is_eligible = EligibleCheck.objects.filter(
        application_id=application_id, is_okay=True,
        check_name='eligible_waitlist',
    ).exists()

    return setting and setting.is_active and is_eligible


def process_eligibility_waitlist(application_id):
    from juloserver.application_flow.tasks import application_tag_tracking_task

    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.WAITING_LIST
    ).last()

    if setting and setting.is_active:
        if setting.parameters.get('FTC achieved') or eligible_waitlist(application_id):
            application_tag_tracking_task(application_id, None, None, None, 'is_waitlist', 1)


def has_application_rejection_history(customer):
    '''
    Check if the customer have history of being rejected based by applications

    Parameters:
        customer [Customer]: customer that will be checked

    Return:
        boolean: True if user has application rejection history
    '''
    if not customer:
        return False

    has_rejected_application = customer.application_set.filter(
        application_status_id__in=ApplicationStatusCodes.rejection_statuses(),
    ).exists()
    if has_rejected_application:
        return True

    expired_application = customer.application_set.filter(
        application_status_id=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
    )
    for exp_app in expired_application:
        if exp_app and JuloOneService().is_c_score(exp_app):
            return True

    return False


ga_event_mapping = {
    (ApplicationStatusCodes.FORM_PARTIAL, 0.9): GAEvent.APPLICATION_X105_PCT90,
    (ApplicationStatusCodes.FORM_PARTIAL, 0.8): GAEvent.APPLICATION_X105_PCT80,
    (ApplicationStatusCodes.FORM_PARTIAL, 0.7): GAEvent.APPLICATION_X105_PCT70,
    (ApplicationStatusCodes.LOC_APPROVED, 0.9): GAEvent.APPLICATION_X190_PCT90,
    (ApplicationStatusCodes.LOC_APPROVED, 0.8): GAEvent.APPLICATION_X190_PCT80,
    (ApplicationStatusCodes.LOC_APPROVED, 0.7): GAEvent.APPLICATION_X190_PCT70,
    (ApplicationStatusCodes.FORM_PARTIAL, 0.8, 0.9): GAEvent.APPLICATION_X105_PCT80_MYCROFT_90,
    (ApplicationStatusCodes.FORM_PARTIAL, 0.9, 0.9): GAEvent.APPLICATION_X105_PCT90_MYCROFT_90,
    (ApplicationStatusCodes.LOC_APPROVED, 0.8, 0.9): GAEvent.APPLICATION_X190_PCT80_MYCROFT_90,
    (ApplicationStatusCodes.LOC_APPROVED, 0.9, 0.9): GAEvent.APPLICATION_X190_PCT90_MYCROFT_90,
}

appsflyer_event_mapping = {
    (
        ApplicationStatusCodes.FORM_PARTIAL,
        0.9,
    ): ApplicationStatusAppsflyerEvent.APPLICATION_X105_PCT90,
    (
        ApplicationStatusCodes.FORM_PARTIAL,
        0.8,
    ): ApplicationStatusAppsflyerEvent.APPLICATION_X105_PCT80,
    (
        ApplicationStatusCodes.FORM_PARTIAL,
        0.7,
    ): ApplicationStatusAppsflyerEvent.APPLICATION_X105_PCT70,
    (
        ApplicationStatusCodes.LOC_APPROVED,
        0.9,
    ): ApplicationStatusAppsflyerEvent.APPLICATION_X190_PCT90,
    (
        ApplicationStatusCodes.LOC_APPROVED,
        0.8,
    ): ApplicationStatusAppsflyerEvent.APPLICATION_X190_PCT80,
    (
        ApplicationStatusCodes.LOC_APPROVED,
        0.7,
    ): ApplicationStatusAppsflyerEvent.APPLICATION_X190_PCT70,
    (
        ApplicationStatusCodes.FORM_PARTIAL,
        0.8,
        0.9,
    ): ApplicationStatusAppsflyerEvent.APPLICATION_X105_PCT80_MYCROFT_90,
    (
        ApplicationStatusCodes.FORM_PARTIAL,
        0.9,
        0.9,
    ): ApplicationStatusAppsflyerEvent.APPLICATION_X105_PCT90_MYCROFT_90,
    (
        ApplicationStatusCodes.LOC_APPROVED,
        0.8,
        0.9,
    ): ApplicationStatusAppsflyerEvent.APPLICATION_X190_PCT80_MYCROFT_90,
    (
        ApplicationStatusCodes.LOC_APPROVED,
        0.9,
        0.9,
    ): ApplicationStatusAppsflyerEvent.APPLICATION_X190_PCT90_MYCROFT_90,
}

event_mapping = {
    ApplicationStatusEventType.APPSFLYER: appsflyer_event_mapping,
    ApplicationStatusEventType.GA: ga_event_mapping,
}


def _send_events(application, appsflyer_data, ga_data):
    from juloserver.julo.services2 import get_appsflyer_service
    from juloserver.julo.workflows2.tasks import appsflyer_update_status_task
    if ga_data:
        send_event_to_ga_task_async.apply_async(kwargs=ga_data)

    if appsflyer_data:
        appsflyer_service = get_appsflyer_service()
        if appsflyer_service.appflyer_id(application):
            appsflyer_update_status_task.delay(application.id, **appsflyer_data)


def get_pgood_key(pgood):
    pgood_key = None
    if pgood >= 0.9:
        pgood_key = 0.9
    elif pgood >= 0.8:
        pgood_key = 0.8
    elif pgood >= 0.7:
        pgood_key = 0.7

    return pgood_key


def send_application_event_by_certain_pgood(application, status_code, event_type):
    """
    Send GA event and Appsflyer event for application with a certain pgood
    """
    from juloserver.julo_starter.services.mocking_services import mock_determine_pgood

    credit_model = PdCreditModelResult.objects.filter(application_id=application.id).last()
    if not credit_model:
        logger.warning(
            'send_application_event_name_by_certain_pgood_PdCreditModelResult_not_found'
            '|application_id={}, event_type={}'.format(application.id, event_type)
        )
        return

    pgood = mock_determine_pgood(application, credit_model.pgood)
    if not pgood:
        logger.warning(
            'send_application_event_name_by_certain_pgood_pgood_not_found'
            '|application_id={}, event_type={}'.format(application.id, event_type)
        )
        return

    pgood_key = get_pgood_key(pgood)

    if pgood_key:
        appsflyer_event_name = None
        ga_event_name = None

        if event_type == ApplicationStatusEventType.APPSFLYER:
            event_name_mapping = event_mapping[event_type]
            appsflyer_event_name = event_name_mapping.get((status_code, pgood_key))
        elif event_type == ApplicationStatusEventType.GA:
            event_name_mapping = event_mapping[event_type]
            ga_event_name = event_name_mapping.get((status_code, pgood_key))
        elif event_type == ApplicationStatusEventType.APPSFLYER_AND_GA:
            appsflyer_event_name_mapping = event_mapping[ApplicationStatusEventType.APPSFLYER]
            appsflyer_event_name = appsflyer_event_name_mapping.get((status_code, pgood_key))
            ga_event_name_mapping = event_mapping[ApplicationStatusEventType.APPSFLYER]
            ga_event_name = ga_event_name_mapping.get((status_code, pgood_key))

        logger.info(
            'start_send_application_event_name_by_certain_pgood|'
            'application={}, pgood={}, status={}, event_type={}, ga_event_name={}, '
            'appsflyer_event_name={}'.format(
                application.id, pgood, status_code, event_type, ga_event_name, appsflyer_event_name
            )
        )

        _send_events(
            application,
            appsflyer_data={'event_name': appsflyer_event_name} if appsflyer_event_name else None,
            ga_data=(
                {'customer_id': application.customer.id, 'event': ga_event_name} if ga_event_name
                else None
            )
        )


def send_application_event_for_x100_device_info(application, event_type):
    """
    Send GA event and Appsflyer event for application at x100 with device info
    """
    devide = SdDevicePhoneDetail.objects.filter(application_id=application.id).last()
    if not devide or not devide.manufacturer:
        logger.warning(
            'send_application_event_for_x100_device_info_device_not_found|'
            'application={}, device={}'.format(application.id, devide)
        )
        return

    if devide.manufacturer.lower() != 'samsung':
        return

    appsflyer_event_name = None
    ga_event_name = None

    if event_type == ApplicationStatusEventType.APPSFLYER_AND_GA:
        appsflyer_event_name = ApplicationStatusAppsflyerEvent.APPLICATION_X100_DEVICE
        ga_event_name = GAEvent.APPLICATION_X100_DEVICE
    elif event_type == ApplicationStatusEventType.APPSFLYER:
        appsflyer_event_name = ApplicationStatusAppsflyerEvent.APPLICATION_X100_DEVICE
    elif event_type == ApplicationStatusEventType.GA:
        ga_event_name = GAEvent.APPLICATION_X100_DEVICE

    logger.info(
        'start_send_application_event_name_for_x100_device_info|'
        'application={}, event_type={}, ga_event_name={}, appsflyer_event_name={}'.format(
            application.id, event_type, ga_event_name, appsflyer_event_name
        )
    )

    _send_events(
        application,
        appsflyer_data={'event_name': appsflyer_event_name} if appsflyer_event_name else None,
        ga_data=(
            {'customer_id': application.customer.id, 'event': ga_event_name} if ga_event_name
            else None
        )
    )


def send_application_event_for_x105_bank_name_info(application, event_type):
    """
    Send GA event and Appsflyer event for application at x105 with bank_name info
    """
    from juloserver.pii_vault.services import detokenize_for_model_object
    from juloserver.pii_vault.constants import PiiSource

    detokenized_applications = detokenize_for_model_object(
        PiiSource.APPLICATION,
        [
            {
                'customer_xid': application.customer.customer_xid,
                'object': application,
            }
        ],
        force_get_local_data=True,
    )
    application = detokenized_applications[0]

    if not application.bank_name:
        logger.warning('send_application_event_for_x105_bank_name_info_bank_name_not_found|'
                       'application={}'.format(application.id))
        return

    if application.bank_name not in ('BANK CENTRAL ASIA, Tbk (BCA)', 'BANK MANDIRI (PERSERO), Tbk'):
        return

    appsflyer_event_name = None
    ga_event_name = None

    if event_type == ApplicationStatusEventType.APPSFLYER_AND_GA:
        appsflyer_event_name = ApplicationStatusAppsflyerEvent.APPLICATION_X105_BANK
        ga_event_name = GAEvent.APPLICATION_X105_BANK
    elif event_type == ApplicationStatusEventType.APPSFLYER:
        appsflyer_event_name = ApplicationStatusAppsflyerEvent.APPLICATION_X105_BANK
    elif event_type == ApplicationStatusEventType.GA:
        ga_event_name = GAEvent.APPLICATION_X105_BANK

    logger.info(
        'start_send_application_event_name_for_x105_bank_name_info|'
        'application={}, event_type={}, ga_event_name={}, appsflyer_event_name={}'.format(
            application.id, event_type, ga_event_name, appsflyer_event_name
        )
    )

    _send_events(
        application,
        appsflyer_data={'event_name': appsflyer_event_name} if appsflyer_event_name else None,
        ga_data=(
            {'customer_id': application.customer.id, 'event': ga_event_name} if ga_event_name
            else None
        )
    )


def process_anti_fraud_binary_check(application_status, application_id, retry: int = 0) -> bool:
    from juloserver.antifraud.services.binary_checks import get_anti_fraud_binary_check_status
    from juloserver.antifraud.constant.binary_checks import StatusEnum

    if retry == 3:
        return StatusEnum.RETRYING

    application_history, application_status, is_need_callback = get_application_old_status_code(
        application_id, application_status
    )

    binary_check_result = get_anti_fraud_binary_check_status(
        status=application_status, application_id=application_id
    )

    retry_binary_check_result = [
        StatusEnum.ERROR,
        StatusEnum.RETRYING,
    ]

    if binary_check_result in retry_binary_check_result:
        return process_anti_fraud_binary_check(application_status, application_id, retry + 1)

    logger.info(
        {
            "action": "process_anti_fraud_binary_check",
            "message": "binary check result is {}".format(binary_check_result),
            "application_id": application_id,
        },
    )

    if is_need_callback and binary_check_result == StatusEnum.MOVE_APPLICATION_TO115:
        # edge case, if the application already in 115 and got x115 response
        # need to call the API call back and update the change reason
        overwrite_application_history_and_call_anti_fraud_call_back(
            application_id, application_history
        )
        return StatusEnum.RETRYING  # return re-triyng to not trigger status change in the caller

    return binary_check_result


def send_application_event_base_on_mycroft(application, status_code, event_type):
    """
    Send GA event and Appsflyer event for application base on mycroft
    """
    from juloserver.julo_starter.services.mocking_services import mock_determine_pgood

    credit_model = PdCreditModelResult.objects.filter(application_id=application.id).last()

    if not credit_model:
        logger.warning(
            'send_application_event_base_on_mycroft_PdCreditModelResult_not_found'
            '|application_id={}, event_type={}'.format(application.id, event_type)
        )
        return

    pgood = mock_determine_pgood(application, credit_model.pgood)
    if not pgood:
        logger.warning(
            'send_application_event_name_by_certain_pgood_pgood_not_found'
            '|application_id={}, event_type={}'.format(application.id, event_type)
        )
        return

    mycroft_score_ana = PdApplicationFraudModelResult.objects.filter(
        application_id=application.id
    ).last()

    if not mycroft_score_ana:
        logger.warning(
            'send_application_event_base_on_mycroft_score_ana_not_found|'
            'application_id={}, event_type={}'.format(application.id, event_type)
        )
        return

    pgood_key = get_pgood_key(pgood)

    mycroft_pgood_key = None
    if mycroft_score_ana.pgood >= 0.9:
        mycroft_pgood_key = 0.9

    if pgood_key and mycroft_pgood_key:
        appsflyer_event_name = None
        ga_event_name = None

        if event_type == ApplicationStatusEventType.APPSFLYER:
            event_name_mapping = event_mapping[event_type]
            appsflyer_event_name = event_name_mapping.get(
                (status_code, pgood_key, mycroft_pgood_key)
            )
        elif event_type == ApplicationStatusEventType.GA:
            event_name_mapping = event_mapping[event_type]
            ga_event_name = event_name_mapping.get((status_code, pgood_key, mycroft_pgood_key))
        elif event_type == ApplicationStatusEventType.APPSFLYER_AND_GA:
            appsflyer_event_name_mapping = event_mapping[ApplicationStatusEventType.APPSFLYER]
            appsflyer_event_name = appsflyer_event_name_mapping.get(
                (status_code, pgood_key, mycroft_pgood_key)
            )
            ga_event_name_mapping = event_mapping[ApplicationStatusEventType.APPSFLYER]
            ga_event_name = ga_event_name_mapping.get((status_code, pgood_key, mycroft_pgood_key))

        logger.info(
            'start_send_application_event_base_on_mycroft|'
            'application={}, pgood={}, pgood_mycroft={}, status={}, event_type={}, '
            'ga_event_name={}, appsflyer_event_name={}'.format(
                application.id,
                pgood,
                mycroft_score_ana.pgood,
                status_code,
                event_type,
                ga_event_name,
                appsflyer_event_name,
            )
        )

        _send_events(
            application,
            appsflyer_data={'event_name': appsflyer_event_name} if appsflyer_event_name else None,
            ga_data=(
                {'customer_id': application.customer.id, 'event': ga_event_name}
                if ga_event_name
                else None
            ),
        )


def is_agent_assisted_submission_flow(application):

    # Check if application have path tag is_agent_assisted_submission
    application_tag_status = ApplicationPathTagStatus.objects.filter(
        application_tag=AgentAssistedSubmissionConst.TAG_NAME,
        status=AgentAssistedSubmissionConst.TAG_STATUS,
    ).last()
    is_exist = ApplicationPathTag.objects.filter(
        application_id=application.id,
        application_path_tag_status=application_tag_status,
    ).exists()

    if is_exist and not application.is_term_accepted and not application.is_verification_agreed:
        return True

    return False


def get_age_group(age):
    age_group = [
        [0, 25, 1],
        [25, 29, 2],
        [30, 34, 3],
        [35, 39, 4],
        [40, None, 5],
    ]
    if age:
        for item in age_group:
            [min_age, max_age, age_group] = item

            if not max_age and age >= min_age:
                return age_group
            elif min_age <= age and age <= max_age:
                return age_group
    return 99


def get_education_group(last_edu):
    last_education = [
        ['SD', 'SD', 1],
        ['SMP', 'SLTP', 2],
        ['SMA', 'SLTA', 3],
        ['Diploma', 'Diploma', 4],
        ['Bachelor', 'S1', 5],
        ['Master', 'S2', 6],
        ['Doctor', 'S3', 7],
    ]
    if last_edu:
        for item in last_education:
            [codes, app_last_edu, edu_group] = item

            if last_edu == app_last_edu:
                return edu_group
    return 99


def get_salary_group(income, data_type="income"):
    income = income if income else 0
    salary_group = [
        [0, 2500000, 1, "A"],
        [2500000, 3500000, 2, "B"],
        [3500000, 4500000, 3, "C"],
        [4500000, 5500000, 4, "D"],
        [5500000, 6500000, 5, "E"],
        [6500000, 7500000, 6, "F"],
        [7500000, 8500000, 7, "G"],
        [8500000, 12500000, 8, "H"],
        [12500000, 20500000, 9, "J"],
        [20500000, None, 10, "K"],
    ]

    for item in salary_group:
        [min_range, max_range, salary_group, affordability] = item

        return_data = salary_group if data_type == "income" else affordability

        if not max_range and income >= min_range:
            return return_data
        elif min_range <= income and income <= max_range:
            return return_data
    return 99


def get_extra_params_dynamic_events(application):
    from dateutil.relativedelta import relativedelta
    from juloserver.apiv2.credit_matrix2 import get_salaried
    from datetime import datetime

    cs = CreditScore.objects.filter(application_id=application.id).last()
    credit_score = cs.score if cs else None

    heimdall_score = PdCreditModelResult.objects.filter(application_id=application.id).last()
    heimdall_pgood = heimdall_score.pgood if heimdall_score else None
    has_fdc = heimdall_score.has_fdc if heimdall_score else None

    mycroft_score = PdApplicationFraudModelResult.objects.filter(
        application_id=application.id
    ).last()
    mycroft_pgood = mycroft_score.pgood if mycroft_score else None

    orion_score = PdCreditEarlyModelResult.objects.filter(application_id=application.id).last()
    orion_pgood = orion_score.pgood if orion_score else None

    job_type = application.job_type
    is_salaried = get_salaried(job_type)
    job_type_group = 1 if is_salaried else 2

    dob = application.dob
    age = relativedelta(datetime.today(), dob).years

    affordability = AffordabilityHistory.objects.filter(application_id=application.id).last()
    affordability_value = affordability.affordability_value if affordability else None

    extra_params = {
        'product_line_code': application.product_line_code,
        'heimdall_pgood': heimdall_pgood,
        'mycroft_pgood': mycroft_pgood,
        'orion_pgood': orion_pgood,
        'credit_score': credit_score,
        'has_fdc': has_fdc,
        'age_group': get_age_group(age),
        'education_group': get_education_group(application.last_education),
        'income_group': get_salary_group(application.monthly_income),
        'affordability_group': get_salary_group(affordability_value, "affordability"),
        'job_type_group': job_type_group,
    }

    logger.info(
        'extra_params_dynamic_events|'
        'application_id={}, extra_params={}'.format(
            application.id,
            extra_params,
        )
    )

    return extra_params


def is_active_clik_model(application_id=None):

    is_active = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CLIK_MODEL, is_active=True
    ).exists()

    logger.info(
        {
            'message': 'Run is_active_clik_model',
            'application_id': application_id,
            'is_active': is_active,
        }
    )

    return is_active


def clik_model_decision(application):
    is_eligible = EligibleCheck.objects.filter(
        application_id=application.id, is_okay=True,
        check_name='eligible_clik',
    ).last()
    has_path_tag = is_click_model(application)

    decision = None
    if has_path_tag and is_eligible:
        decision = is_eligible.parameter['action']

    logger.info(
        {
            'message': 'clik_model_decision',
            'application_id': application.id,
            'has_path_tag': has_path_tag,
            'action': decision,
        }
    )

    return decision


def create_application(
    customer,
    nik=None,
    app_version=None,
    web_version=None,
    email=None,
    partner=None,
    phone=None,
    onboarding_id=OnboardingIdConst.LONGFORM_SHORTENED_ID,
    workflow_name=None,
    product_line_code=None,
):
    workflow = Workflow.objects.get(name=workflow_name)
    product_line_code = ProductLine.objects.get(pk=product_line_code)
    application = Application.objects.create(
        customer=customer,
        ktp=nik,
        app_version=app_version,
        web_version=web_version,
        email=email,
        partner=partner,
        workflow=workflow,
        product_line=product_line_code,
        mobile_phone_1=phone,
        onboarding_id=onboarding_id,
    )

    return application


def process_antifraud_status_decision_x120(application, retry: int = 0):
    from juloserver.julo.services import process_application_status_change
    from juloserver.antifraud.constant.binary_checks import BinaryCheckType
    from juloserver.antifraud.constant.transport import Path
    from juloserver.antifraud.client import get_anti_fraud_http_client
    from juloserver.antifraud.constant.binary_checks import StatusEnum

    anti_fraud_http_client = get_anti_fraud_http_client()

    if retry == 3:
        process_application_status_change(
            application.id,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
            'anti_fraud_api_unavailable',
        )
        return True

    antifraud_api_onboarding_fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.ANTIFRAUD_API_ONBOARDING,
        is_active=True,
    )
    if not antifraud_api_onboarding_fs or not antifraud_api_onboarding_fs.parameters.get(
        'j1_x120', False
    ):
        logger.info(
            {
                "action": "process_anti_fraud_api_j1_x120",
                "message": "feature setting for antifraud is not active",
                "application_id": application.id,
            },
        )
        return False

    params = {
        "status": application.status,
        "type": BinaryCheckType.APPLICATION,
        "application_id": application.id,
    }

    try:
        response = anti_fraud_http_client.get(
            path=Path.ANTI_FRAUD_BINARY_CHECK,
            params=params,
        )
    except Exception as e:
        logger.error(
            {
                "action": "process_anti_fraud_api_j1_x120",
                "error": e,
            }
        )
        sentry_client.captureException()
        return process_antifraud_status_decision_x120(application, retry=retry + 1)

    if response.status_code != 200:
        return process_antifraud_status_decision_x120(application, retry=retry + 1)

    try:
        binary_check_status = StatusEnum(response.json().get("data", {}).get("status", None))
    except Exception as e:
        logger.error(
            {
                "action": "process_anti_fraud_api_j1_x120",
                "error": e,
                "response": response,
            }
        )
        sentry_client.captureException()
        return False

    logger.info(
        {
            "action": "process_anti_fraud_api_j1_x120",
            "application_id": application.id,
            "binary_check_status": binary_check_status,
        }
    )

    if binary_check_status is None or binary_check_status in (
        StatusEnum.ERROR,
        StatusEnum.BYPASSED_HOLDOUT,
        StatusEnum.DO_NOTHING,
    ):
        return False

    if binary_check_status == StatusEnum.MOVE_APPLICATION_TO115:
        process_application_status_change(
            application.id,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
            'Prompted by the Anti Fraud API',
        )
        return True
    else:
        error_message = "Unhandled status: {}".format(binary_check_status)
        logger.error(
            {
                "action": "process_anti_fraud_api_j1_x120",
                "error": error_message,
                "application_id": application.id,
                "binary_check_status": binary_check_status,
            }
        )
        sentry_client.captureException(
            error=Exception(error_message),
            extra={"application_id": application.id, "binary_check_status": binary_check_status},
        )
        return False


def _assign_hsfbp_income_path_tag(application_id):
    from juloserver.application_flow.tasks import application_tag_tracking_task

    application_history = ApplicationHistory.objects.filter(
        application_id=application_id,
        status_old=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        status_new=ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
    ).last()

    if application_history:
        change_reason = application_history.change_reason
        if change_reason == HSFBPIncomeConst.CHANGE_REASON_GOOD_DOCS:
            application_tag_tracking_task(
                application_id,
                None,
                None,
                None,
                HSFBPIncomeConst.GOOD_DOC_TAG,
                1,
            )
        if change_reason == HSFBPIncomeConst.CHANGE_REASON_BAD_DOCS:
            application_tag_tracking_task(
                application_id,
                None,
                None,
                None,
                HSFBPIncomeConst.BAD_DOC_TAG,
                1,
            )


@sentry_client.capture_exceptions
def get_instruction_verification_docs(type_param):

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.INSTRUCTION_VERIFICATION_DOCS,
    ).last()
    if not feature_setting:
        return None

    parameters = feature_setting.parameters.get(type_param)
    try:
        return parameters
    except Exception as error:
        raise JuloException(str(error))


def decline_hsfbp_income_verification(application_id):
    from juloserver.application_flow.tasks import application_tag_tracking_task
    from juloserver.julo.services import process_application_status_change
    from juloserver.application_flow.constants import HSFBPIncomeConst

    application = Application.objects.get(id=application_id)

    bypass = JuloOneByPass()
    accept_hsfbp = bypass.check_accept_hsfbp_income_verification(application)
    expire_hsfbp = bypass.check_expired_hsfbp_tag(application)

    logger.info(
        {
            'message': 'decline_hsfbp_income_verification',
            'application_id': application_id,
            'application_status': application.status,
            'accept_hsfbp': accept_hsfbp,
            'expire_hsfbp': expire_hsfbp,
        }
    )

    if accept_hsfbp or expire_hsfbp:
        return False, "HSFBP offer already accepted or expired"

    if application.status != ApplicationStatusCodes.DOCUMENTS_SUBMITTED:
        return False, "Application status not allowed"

    application_tag_tracking_task(
        application.id,
        None,
        None,
        None,
        HSFBPIncomeConst.DECLINED_TAG,
        1,
    )

    process_application_status_change(
        application.id,
        ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        change_reason=FeatureNameConst.HIGH_SCORE_FULL_BYPASS,
    )

    logger.info(
        {'action': 'decline_hsfbp_income_verification: success', 'application_id': application_id}
    )

    return True, ""


def is_hsfbp_hold_with_status(application, is_ios_device):

    if (
        application.application_status_id
        not in (
            ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        )
        or not application.is_julo_one()
        or is_ios_device
    ):
        return False

    is_hsfbp = HsfbpIncomeVerification.objects.filter(
        application_id=application.id,
    ).exists()

    return is_hsfbp


def get_expiry_hsfbp(application_id):
    hsfbp_income = HsfbpIncomeVerification.objects.filter(
        application_id=application_id,
    ).last()

    if not hsfbp_income:
        return None

    today = timezone.localtime(timezone.now())
    expired_date = timezone.localtime(hsfbp_income.expired_date)
    if today <= expired_date:
        return expired_date.isoformat()

    return None


def build_prefix_session_hsfbp(application_id):
    cache_key_name = CacheKey.HSFBP_SESSION_PREFIX.format(application_id)

    return cache_key_name


def set_session_check_hsfbp(application):

    if not application.is_julo_one() or not application.app_version:
        return False

    # Check experiment still ongoing?
    is_experiment = still_in_experiment(experiment_type=ExperimentConst.HSFBP_INCOME_VERIFICATION)
    if not is_experiment:
        return False

    experiment = ExperimentSetting.objects.filter(
        code=ExperimentConst.HSFBP_INCOME_VERIFICATION,
    ).last()

    try:
        # Check rule in last digit
        criteria = experiment.criteria
        application_id = application.id
        last_digit_config = criteria.get(HSFBPIncomeConst.KEY_LAST_DIGIT_APP_ID)
        if application_id % 10 not in last_digit_config:
            return False

        app_version_criteria = criteria.get('android_app_version')
        app_version = application.app_version
        if not semver.match(app_version, app_version_criteria):
            return False

        application_id = application.id
        redis_client = get_redis_client()
        cache_key_name = build_prefix_session_hsfbp(application_id)

        # set session checking for certain seconds
        redis_client.set(
            cache_key_name,
            application_id,
            HSFBPIncomeConst.REDIS_EXPIRED_IN_SECONDS,
        )

        logger.info(
            {
                'message': '[HSFBP_SessionCheck] Set session in redis',
                'application_id': application_id,
                'redis_key': cache_key_name,
                'expired_in_seconds': HSFBPIncomeConst.REDIS_EXPIRED_IN_SECONDS,
            }
        )
    except Exception as error:

        # Create process to silent error stored to logger
        # Prevent breaking in other process
        logger.error(
            {
                'message': '[HSFBP_SessionCheck] Error: {}'.format(str(error)),
                'application_id': application.id,
            }
        )
        return False

    return True


def is_available_session_check_hsfbp(application_id):

    redis_client = get_redis_client()
    cache_key_name = build_prefix_session_hsfbp(application_id)

    return redis_client.get(cache_key_name)


def remove_session_check_hsfbp(application_id):

    try:
        redis_client = get_redis_client()
        cache_key_name = build_prefix_session_hsfbp(application_id)
        if redis_client.get(cache_key_name):

            redis_client.delete_key(cache_key_name)
            logger.info(
                {
                    'message': '[HSFBP_SessionCheck] Remove session in redis',
                    'application_id': application_id,
                    'redis_key': cache_key_name,
                    'expired_in_seconds': HSFBPIncomeConst.REDIS_EXPIRED_IN_SECONDS,
                }
            )
    except Exception as error:
        logger.error(
            {
                'message': '[HSFBP_SessionCheck] remove session error: {}'.format(str(error)),
                'application_id': application_id,
            }
        )
        return False

    return True


def rule_hsfbp_for_infocards(application, info_cards):
    """
    This function to handle destination / btn_action "appl_docs"
    Will set as None for that btn_action for a while to prevent show mandatory docs popup
    until session check HSFBP is done
    """

    if (
        not application
        or not application.is_julo_one()
        or application.application_status_id != ApplicationStatusCodes.DOCUMENTS_SUBMITTED
    ):
        return info_cards

    is_experiment = still_in_experiment(
        experiment_type=ExperimentConst.HSFBP_INCOME_VERIFICATION,
    )
    if not is_experiment:
        return info_cards

    application_id = application.id
    if not is_available_session_check_hsfbp(application_id=application_id):
        return info_cards

    try:
        temp_info_cards = copy.deepcopy(info_cards)
        for info_card in temp_info_cards:
            if 'button' in info_card:
                for button in info_card['button']:
                    if button.get('destination', None) == 'appl_docs':
                        button['destination'] = None

        logger.info(
            {
                'message': '[HSFB_x120] btn action appl_docs change as temporary',
                'application_id': application_id,
            }
        )

        return temp_info_cards
    except Exception as error:
        logger.error(
            {
                'message': '[HSFBP_x120] error info cards: {}'.format(str(error)),
                'application_id': application_id,
            }
        )
        return info_cards


def check_path_tag(application_id, path_tag_name, status, return_instance=False):

    path_tag = ApplicationPathTagStatus.objects.filter(
        application_tag=path_tag_name,
        status=status,
    ).last()

    application_path = ApplicationPathTag.objects.filter(
        application_id=application_id,
        application_path_tag_status=path_tag,
    )

    if return_instance:
        return application_path.last()

    return application_path.exists()


def check_and_move_status_hsfbp_submit_doc(application, is_ios_device):
    from juloserver.julo.services import process_application_status_change

    today = timezone.localtime(timezone.now()).date()
    application_id = application.id

    is_hsfbp = is_hsfbp_hold_with_status(  # noqa
        application=application,
        is_ios_device=is_ios_device,
    )

    if not is_hsfbp:
        return

    if application.application_status_id < ApplicationStatusCodes.SCRAPED_DATA_VERIFIED:
        process_application_status_change(
            application_id,
            ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            change_reason=HSFBPIncomeConst.CHANGE_REASON_SUBMIT_DOCS,
        )

    #  Case if user already moved to x121 or have path tag no_docs
    if application.application_status_id == ApplicationStatusCodes.SCRAPED_DATA_VERIFIED:
        application_history = ApplicationHistory.objects.filter(
            application_id=application_id,
            status_new=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            status_old=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
        ).last()

        if (
            application_history
            and application_history.cdate.date() == today
            and application_history.change_reason != HSFBPIncomeConst.CHANGE_REASON_SUBMIT_DOCS
        ):
            change_reason = application_history.change_reason
            note_text = 'change_reason updated {0} to {1}'.format(
                change_reason, HSFBPIncomeConst.CHANGE_REASON_SUBMIT_DOCS
            )
            ApplicationNote.objects.create(
                application_id=application_id,
                note_text=note_text,
            )
            application_history.update_safely(
                change_reason=HSFBPIncomeConst.CHANGE_REASON_SUBMIT_DOCS
            )

            # check if have path tag is_hsfbp_no_docs
            hsfbp_no_docs_path_tag = check_path_tag(
                application_id=application_id,
                path_tag_name='is_hsfbp_no_doc',
                status=1,
                return_instance=False,
            )
            if not hsfbp_no_docs_path_tag:
                return

            logger.info(
                {
                    'message': 'Override path tag HSFBP no docs, '
                    'since user already upload document',
                    'application_id': application_id,
                }
            )
            tag_tracer = ApplicationTagTracking(application=application)
            tag_tracer.adding_application_path_tag('is_hsfbp_no_doc', 0)

            # doublecheck is_hsfbp is success
            is_hsfbp_success = check_path_tag(
                application_id=application_id,
                path_tag_name='is_hsfbp',
                status=1,
                return_instance=False,
            )
            if not is_hsfbp_success:
                tag_tracer = ApplicationTagTracking(application=application)
                tag_tracer.adding_application_path_tag('is_hsfbp', 1)
