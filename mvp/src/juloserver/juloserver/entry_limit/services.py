import csv
from builtins import map, object

from django.db import transaction
from django.db.models import Q

from juloserver.account.services.account_related import get_account_property_by_account
from juloserver.account.services.credit_limit import (
    get_credit_matrix_type,
    get_credit_model_result,
    get_salaried,
    is_inside_premium_area,
)
from juloserver.application_flow.models import ApplicationPathTag, ShopeeScoring
from juloserver.customer_module.models import AccountDeletionRequest
from juloserver.julo.models import Application, ApplicationNote, CreditScore
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.application_flow.services import JuloOneService
from juloserver.julo.utils import verify_nik

from .constants import CreditLimitGenerationReason, JobsConst
from .models import EntryLevelLimitConfiguration, EntryLevelLimitHistory
from .serializers import EntryLevelLimitConfigurationSerializer
from juloserver.streamlined_communication.services import customer_have_upgrade_case
from juloserver.application_flow.services import has_good_score_mycroft
from juloserver.julo.exceptions import InvalidPhoneNumberError
from juloserver.julolog.julolog import JuloLog
from juloserver.application_flow.constants import JuloOneChangeReason
from juloserver.julo.models import ApplicationHistory
from juloserver.partnership.models import PartnershipApplicationFlag
from juloserver.partnership.constants import PartnershipPreCheckFlag
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.application_flow.services import eligible_entry_level
from juloserver.account.constants import CreditMatrixType


logger = JuloLog(__name__)


class EntryLevelLimitProcess(object):
    def __init__(self, application_id, application=None):
        self.application_id = application_id
        if application is None:
            self._application = Application.objects.select_related('customer').get(
                pk=self.application_id
            )
        else:
            self._application = application

    @property
    def application(self):
        if not self._application:
            application = Application.objects.get(pk=self.application_id)

            # detokenized before run other function
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
            self._application = application

        return self._application

    def start(self, status, custom_parameters=None, force_got_config_id=None):
        if (
            self.is_click_pass()
            or self.is_telco_pass()
            or self.has_account_deletion_request()
            or self._should_cancel_entry_limit()
            or self._check_is_spouse_registered()
        ):
            return False

        history_exists = EntryLevelLimitHistory.objects.filter(
            application_id=self.application_id,
        ).exists()
        entry_level = self.check_entry_level_limit_config(
            status=status,
            custom_parameters=custom_parameters,
            force_got_config_id=force_got_config_id,
        )

        if entry_level:
            if not self.check_nik_validation_fraud():
                return True

            if not history_exists:
                EntryLevelLimitHistory.objects.create(
                    application_id=self.application_id,
                    entry_level_config=entry_level,
                    entry_level_limit=entry_level.entry_level_limit,
                    action=entry_level.action,
                )

            process_application_status_change(
                self.application,
                entry_level.action[-3:],
                entry_level.change_reason,
            )

            ApplicationNote.objects.create(
                note_text="Got EL with id "
                + str(entry_level.id)
                + " with custom_parameters : "
                + str(custom_parameters)
                + " with force_got_config_id : "
                + str(force_got_config_id),
                application_id=self.application_id,
                application_history_id=None,
            )

            logger.info(
                {
                    "action": "This application got EL",
                    "application_id": self.application.id,
                    "message": "Change status for entry level",
                    "EL config id": str(entry_level.id),
                    "custom_parameters": str(custom_parameters),
                    "force_got_config_id": str(force_got_config_id),
                    "status": status,
                }
            )
            return True

        return False

    def run_entry_level_limit_eligible(self):
        entry_level_limit_history = self.get_entry_level_history()

        if entry_level_limit_history:
            entry_level = entry_level_limit_history.entry_level_config
        else:
            entry_level = self.check_entry_level_limit_config()
            if entry_level:
                EntryLevelLimitHistory.objects.create(
                    application_id=self.application_id,
                    entry_level_config=entry_level,
                    entry_level_limit=entry_level.entry_level_limit,
                    action=entry_level.action,
                )

        return entry_level

    def check_entry_level_limit_config(
        self, status=None, custom_parameters=None, force_got_config_id=None
    ):
        application = self.application
        if customer_have_upgrade_case(
            application.customer, application
        ) or not has_good_score_mycroft(self.application):
            return None

        if force_got_config_id:
            forced_config = EntryLevelLimitConfiguration.objects.get_or_none(pk=force_got_config_id)
            if forced_config:
                return forced_config
        application_tags = ApplicationPathTag.objects.filter(
            application_id=application.id
        ).values_list(
            "application_path_tag_status__application_tag",
            "application_path_tag_status__status",
        )
        tags = ["%s:%s" % (tag, status) for tag, status in application_tags]

        has_credit_score = self.has_credit_score()
        is_high_c_score = JuloOneService.is_high_c_score(application)
        is_c_score = JuloOneService.is_c_score(application)

        if not has_credit_score or is_high_c_score or is_c_score:
            return None

        credit_model_result = get_credit_model_result(application)
        pgood = 0
        if credit_model_result and credit_model_result.pgood:
            pgood = credit_model_result.pgood
        elif credit_model_result and credit_model_result.probability_fpd:
            pgood = credit_model_result.probability_fpd
        customer_category = get_credit_matrix_type(application)
        product_line = application.product_line_code
        is_salaried = get_salaried(application.job_type)
        is_premium_area = is_inside_premium_area(application)

        if eligible_entry_level(application.id):
            customer_category = CreditMatrixType.JULO1

        agent_assisted_app_flag = None
        if application.partner:
            # partnership agent assisted flow
            partnership_application_id = application.id
            agent_assisted_app_flag = (
                PartnershipApplicationFlag.objects.filter(application_id=partnership_application_id)
                .values_list('name', flat=True)
                .last()
            )

        if agent_assisted_app_flag:
            if agent_assisted_app_flag != PartnershipPreCheckFlag.APPROVED:
                return None

        config_parameters = {
            "customer_category": customer_category,
            "product_line_code": product_line,
            "is_premium_area": is_premium_area,
            "is_salaried": is_salaried,
            "min_threshold__lte": pgood,
        }

        # modify parameters if custom_parameters is exists
        if custom_parameters:
            config_parameters = self._modify_filter_based_on_custom_parameters(
                config_parameters, custom_parameters
            )

        # find EL config that match with parameter
        entry_level_data = EntryLevelLimitConfiguration.objects.latest_version().filter(
            **config_parameters
        )

        if status:
            entry_level_data = entry_level_data.filter(action__startswith=status)
        else:
            entry_level_data = entry_level_data.filter(Q(action="") | Q(action__isnull=True))

        entry_level = None

        for entry in entry_level_data:
            entry_tags = entry.application_tags.split("&")
            check_tags = [tag for tag in entry_tags if tag not in tags]
            max_threshold = entry.max_threshold
            check_max_threshold = (
                max_threshold >= pgood if max_threshold == 1 else max_threshold > pgood
            )
            if not check_tags and check_max_threshold:
                entry_level = entry
                break

        return entry_level

    def has_credit_score(self):
        return CreditScore.objects.filter(application_id=self.application.id).last()

    def is_click_pass(self):
        from juloserver.application_flow.services import check_click_pass

        return check_click_pass(self.application)

    def is_telco_pass(self):
        from juloserver.application_flow.services import check_telco_pass

        return check_telco_pass(self.application)

    def has_account_deletion_request(self):
        return AccountDeletionRequest.objects.filter(customer=self.application.customer).exists()

    def check_nik_validation_fraud(self):
        valid_nik = verify_nik(self.application.ktp)
        if not valid_nik:
            new_status_code = ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD
            change_reason = 'Invalid NIK and not Dukcapil Eligible'
            process_application_status_change(
                self.application.id, new_status_code, change_reason=change_reason
            )
            return False
        return True

    def can_bypass_141(self):
        if (
            self.is_click_pass()
            or self.is_telco_pass()
            or self.has_account_deletion_request()
            or not self.check_nik_validation_fraud()
            or self._check_is_spouse_registered()
            or self._check_offer_declined_history()
            or self._check_name_validate_failed_history()
            or customer_have_upgrade_case(self.application.customer, self.application)
            or not has_good_score_mycroft(self.application)
        ):
            return False

        entry_limit_history = self.get_entry_level_history()
        return entry_limit_history and entry_limit_history.entry_level_config.bypass_ac

    def get_entry_level_history(self):
        return EntryLevelLimitHistory.objects.filter(application_id=self.application.id).last()

    def can_bypass_124(self):
        if (
            self.is_click_pass()
            or self.is_telco_pass()
            or self.has_account_deletion_request()
            or not self.check_nik_validation_fraud()
            or self._check_is_spouse_registered()
            or self._check_offer_declined_history()
            or self._check_name_validate_failed_history()
            or customer_have_upgrade_case(self.application.customer, self.application)
            or not has_good_score_mycroft(self.application)
        ):
            return False

        entry_level = self.run_entry_level_limit_eligible()
        return entry_level and entry_level.bypass_pva

    def _should_cancel_entry_limit(self):
        logger.info(
            {"application_id": self.application.id, "message": "Check should cancel entry limit"}
        )
        from juloserver.application_flow.services2 import AutoDebit

        # Block entry level if customer have 142 or 175 in their application history
        # to avoid circular application status code
        if self._check_offer_declined_history() or self._check_name_validate_failed_history():
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "Check should cancel entry limit: _check_offer_declined_history",
                }
            )
            return True

        if self._skip_136_ktp_or_selfie():
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "Check should cancel entry limit: _skip_136_ktp_or_selfie",
                }
            )
            return True

        # Check if ever in shopee scoring
        ever_fail_shopee = ShopeeScoring.objects.filter(
            application=self.application, is_passed=False
        ).exists()
        if ever_fail_shopee:
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "Check should cancel entry limit: ever_fail_shopee",
                }
            )
            return True

        # ever fail shopee by check application history
        ever_fail_shopee_by_app_history = ApplicationHistory.objects.filter(
            application=self.application,
            status_old=130,
            status_new=135,
            change_reason=JuloOneChangeReason.SHOPEE_SCORE_NOT_PASS,
        ).exists()
        if ever_fail_shopee_by_app_history:
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "Check should cancel entry limit: ever_fail_shopee_by_app_history",
                }
            )
            return True

        # Check for non-fdc autodebet eligibility
        autodebit = AutoDebit(self.application)
        if autodebit.has_pending_tag:
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "Check should cancel entry limit: autodebit",
                }
            )
            return True

        return False

    def _check_offer_declined_history(self):
        offer_declined_history = self.application.applicationhistory_set.filter(
            status_new=ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER
        )
        if offer_declined_history:
            return True
        return

    def _check_name_validate_failed_history(self):
        if self.application.applicationhistory_set.filter(
            status_new=ApplicationStatusCodes.NAME_VALIDATE_FAILED
        ):
            return True

    def _check_is_spouse_registered(self):
        from juloserver.julo.utils import format_valid_e164_indo_phone_number

        is_spouse = False
        mobile_phone = self.application.mobile_phone_1
        is_jobless = False

        if self.application.job_type in JobsConst.JOBLESS_CATEGORIES:
            is_jobless = True

        if mobile_phone and is_jobless:
            try:
                mobile_phone_clean = format_valid_e164_indo_phone_number(mobile_phone).replace(
                    '+62', ''
                )

                is_spouse = Application.objects.filter(
                    spouse_mobile_phone__in=[
                        mobile_phone_clean,
                        "0{}".format(mobile_phone_clean),
                        "62{}".format(mobile_phone_clean),
                        "+62{}".format(mobile_phone_clean),
                    ]
                ).exists()
            except InvalidPhoneNumberError as e:
                logger.warning(
                    {
                        "action": "_check_is_spouse_registered",
                        "error": str(e),
                        "data": {
                            "application": self.application.id,
                            "mobile_phone_1": mobile_phone,
                        },
                    }
                )
                return True

        return is_spouse

    def _skip_136_ktp_or_selfie(self) -> bool:
        # Check the previous application history has status to 131 or 132
        # that has reason 'ktp needed' or 'selfie needed'. If it true than entry
        # level limit should not be triggered when move from 136.

        if self.application.status != ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED:
            return False

        last_resubmission_request = self.application.applicationhistory_set.filter(
            status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
        ).last()
        if last_resubmission_request is None:
            return False

        if last_resubmission_request.change_reason.lower() in ["ktp needed", "selfie needed"]:
            return True

        return False

    def _modify_filter_based_on_custom_parameters(
        self, current_parameters: dict, new_parameters: dict
    ) -> dict:
        """
        Modify current filter (custom_parameters) with new filter(new_parameters).
        Ex current_parameters :
        {"custom_category":"julo1", "product_line":1,"is_premium_area":True, "is_salaried" : True,
        "min_threshold__lte":0.75}
        Ex new_parameters :
        {"min_threshold__lte":100}
        Then it will return
        {"custom_category":"julo1", "product_line":1,"is_premium_area":True, "is_salaried" : True,
        "min_threshold__lte":100}

        Args:
            current_parameters (dict): Current filter to find EL config
            new_parameters (dict): Value used to replace current_parameters
        Returns:
            dict
        """
        try:
            logger.info(
                {
                    "function": "_modify_filter_based_on_custom_parameters",
                    "state": "start",
                    "current_parameters": str(current_parameters),
                    "new_parameters": str(new_parameters),
                }
            )
            # if new_parameters is not exists
            if not new_parameters:
                return current_parameters

            # make a copy and create modified parameters
            modified_parameters = current_parameters.copy()
            modified_parameters.update(new_parameters)

            # make sure modified parameters have correct parameters
            is_correct_parameters = set(modified_parameters.keys()) == set(
                (
                    "customer_category",
                    "product_line",
                    "is_premium_area",
                    "is_salaried",
                    "min_threshold__lte",
                )
            )
            if is_correct_parameters:
                return modified_parameters
            else:
                return current_parameters
        except Exception as e:
            logger.info(
                {
                    "function": "_modify_filter_based_on_custom_parameters",
                    "state": "error",
                    "error": str(e),
                    "current_parameters": str(current_parameters),
                    "new_parameters": str(new_parameters),
                }
            )
            return current_parameters


class EntryLevelFileUpload:
    def process(self, csv_data):
        reader = csv.DictReader(csv_data)
        with transaction.atomic():
            next_version = 1
            current_version = EntryLevelLimitConfiguration.objects.latest_version().first()
            if current_version:
                next_version = current_version.version + 1
            for dct in map(dict, reader):
                dct["version"] = next_version
                serializer = EntryLevelLimitConfigurationSerializer(data=dct)
                serializer.is_valid(raise_exception=True)
                serializer.save()


def is_entry_level_type(application):
    account = application.account
    if account:
        account_property = get_account_property_by_account(account)
        if account_property:
            return account_property.is_entry_level

    # old logic, in case no account property
    last_limit_generation = application.creditlimitgeneration_set.last()
    if last_limit_generation:
        if last_limit_generation.reason == CreditLimitGenerationReason.ENTRY_LEVEL_LIMIT:
            return True

    # Some credit matrix does not have correct credit matrix type.
    # Because when credit matrix is fetched, the account property and credit
    # limit generation not exists yet.
    has_entry_level_history = EntryLevelLimitHistory.objects.filter(
        application_id=application.id
    ).exists()
    if has_entry_level_history:
        return True

    return False


def check_lock_by_entry_level_limit(account, product, application_direct=None):

    application = application_direct or account.application_set.last()
    if application and is_entry_level_type(application):
        entry_limit_history = EntryLevelLimitHistory.objects.filter(
            application_id=application.id
        ).last()
        if (
            entry_limit_history
            and product not in entry_limit_history.entry_level_config.enabled_trx_method
        ):
            return True

    return False
