import json

from django.db.models import Q
from django.utils import timezone

from juloserver.application_flow.models import (
    ApplicationPathTag,
    ApplicationPathTagStatus,
)
from juloserver.julo.models import Application, ExperimentSetting
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julolog.julolog import JuloLog

logger = JuloLog(__name__)


class AutoDebitError(Exception):
    pass


class AutoDebit:
    """
    AutoDebit service.
    """

    APPLICATION_TAG = "is_nonfdc_autodebet"
    CREDIT_MATRIX_TYPE = "julo1_entry_level"

    # Please adjust this with the intersection test group
    # based on experiment setting in Shopee whitelist.
    SHOPEE_WHITELIST_CRITERIA_INTERSECTION = "criteria_2"

    STATUS_PENDING = -1
    STATUS_SUCCESS = 1

    def __init__(self, application: Application):
        """
        :param application: Application
        """
        self._configuration = None
        self._credit_matrix = None

        self.application = application
        self.heimdall = None
        self.shopee_whitelist = None
        self.is_premium_area = None

    def _has_active_configuration(self) -> bool:
        """
        Check if the application has active configuration
        :return: bool
        """
        if self.configuration is None:
            return False

        return True

    def _is_fdc_not_found(self) -> bool:
        """
        Check if the application has FDC not found.
        :return: bool
        """
        from juloserver.apiv2.models import PdCreditModelResult

        heimdall = PdCreditModelResult.objects.filter(application_id=self.application.id).last()
        return not heimdall.has_fdc

    def _is_fdc_found(self) -> bool:
        return not self._is_fdc_not_found()

    def _fetch_configuration(self):
        """
        Fetch the configuration from the database.
        :return: None
        """
        from juloserver.julo.constants import ExperimentConst

        today = timezone.localtime(timezone.now()).date()

        self._configuration = (
            ExperimentSetting.objects.filter(
                code=ExperimentConst.AUTODEBET_ACTIVATION_EXPERIMENT, is_active=True
            )
            .filter(
                (Q(start_date__date__lte=today) & Q(end_date__date__gte=today))
                | Q(is_permanent=True)
            )
            .last()
        )

    def _fetch_credit_matrix(self):
        from juloserver.account.services.credit_limit import (
            get_credit_matrix,
            get_salaried,
            get_transaction_type,
        )

        self._fetch_heimdall_score()

        params = {
            "min_threshold__lte": self.heimdall,
            "max_threshold__gte": self.heimdall,
            "credit_matrix_type": self.CREDIT_MATRIX_TYPE,
            "is_salaried": get_salaried(self.application.job_type),
            "is_premium_area": self.is_premium_area,
        }

        cm = get_credit_matrix(params, get_transaction_type())
        self._credit_matrix = cm

    def _fetch_heimdall_score(self):
        from juloserver.apiv2.models import PdCreditModelResult, PdWebModelResult

        if self.heimdall is not None:
            return

        if not self.application.is_web_app() and not self.application.is_partnership_app():
            credit_model = PdCreditModelResult.objects.filter(
                application_id=self.application.id
            ).last()
        else:
            credit_model = PdWebModelResult.objects.filter(
                application_id=self.application.id
            ).last()

        self.heimdall = credit_model.pgood

    def _assign_tag(self, status: int):
        """
        Assign the tag to the application.
        :return: None
        """
        from juloserver.application_flow.tasks import application_tag_tracking_task

        application_tag_tracking_task.delay(
            self.application.id, None, None, None, self.APPLICATION_TAG, status
        )
        logger.info(
            {
                "application_id": self.application.id,
                "message": "queued application tag",
                "tag": self.APPLICATION_TAG,
            }
        )

    def _is_odd(self):
        """
        Check the last digit of application id is odd or not.
        """
        return self.application.id % 2 == 1

    @property
    def configuration(self):
        """
        Get the configuration from the database.
        """
        if self._configuration is None:
            self._fetch_configuration()

        return self._configuration

    def should_continue_in_x105(self) -> bool:
        """
        Check if the autodebit should continue.
        :return: bool
        """

        if not self.application.is_regular_julo_one():
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "nonfdc_autodebet: not regular julo one",
                }
            )
            return False

        # If not 105 should be skipped.
        if self.application.status != ApplicationStatusCodes.FORM_PARTIAL:
            logger.info(
                {"application_id": self.application.id, "message": "nonfdc_autodebet: not in x105"}
            )
            return False

        # Skip the execution if FDC found
        if self._is_fdc_found():
            logger.info(
                {"application_id": self.application.id, "message": "nonfdc_autodebet: fdc found"}
            )
            return False

        # Skip the execution if configuration off
        if not self._has_active_configuration():
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "nonfdc_autodebet: does not have active configuration",
                }
            )
            return False

        if not self._still_has_quota():
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "nonfdc_autodebet: quota is full",
                }
            )
            return False

        if not self._match_configuration():
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "nonfdc_autodebet: not match configuration",
                }
            )
            return False

        return True

    def _still_has_quota(self):
        criteria = self.configuration.criteria

        limit = criteria["limit"]

        action = self.configuration.action.replace("\'", "\"")
        action = json.loads(action)
        count = action['count']

        return int(count) < limit

    def _decrease_quota(self):
        """
        Decrease quota with increasing limit.
        """
        action = self.configuration.action.replace("\'", "\"")
        action = json.loads(action)
        count = action['count']
        count += 1
        self.configuration.action = json.dumps({"count": count})
        self.configuration.save()

    def _is_hsfbp_or_sonic(self):
        hsfbp = ApplicationPathTagStatus.objects.filter(application_tag="is_hsfbp", status=1).last()
        sonic = ApplicationPathTagStatus.objects.filter(application_tag="is_sonic", status=1).last()
        return ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status__in=[hsfbp, sonic]
        ).exists()

    def _match_configuration(self):
        self._fetch_heimdall_score()

        configuration = self.configuration

        parameters = configuration.criteria
        upper_threshold = parameters.get("upper_threshold")
        bottom_threhsold = parameters.get("bottom_threshold")

        return bottom_threhsold <= self.heimdall < upper_threshold

    def decide_to_assign_tag(self):
        """
        Decide to assign tag or not.
        :return: bool
        """
        if not self.should_continue_in_x105():
            logger.info(
                {
                    "application_id": self.application.id,
                    "message": "nonfdc_autodebet: can not continue",
                }
            )
            return False

        self._assign_tag(self.STATUS_PENDING)
        self._decrease_quota()

        return True

    @property
    def credit_matrix(self):
        if not self._credit_matrix:
            self._fetch_credit_matrix()

        return self._credit_matrix

    @property
    def has_pending_tag(self) -> bool:
        """If no fdc autodebit already running, check has tag or not."""

        return len(self.tags(self.STATUS_PENDING)) > 0

    @property
    def has_success_tag(self) -> bool:
        """If no fdc autodebit already running, check has tag or not."""

        return len(self.tags(self.STATUS_SUCCESS)) > 0

    def tags(self, status: int):
        """If no fdc autodebit already running, get the all application tags."""
        statuses = ApplicationPathTagStatus.objects.filter(
            application_tag=self.APPLICATION_TAG, status=status
        )
        return ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status__in=statuses
        )

    def ask_to_activate(self):
        """
        Ask to activate the autodebit, with move it to x153 bucket.
        """
        from juloserver.julo.services import process_application_status_change

        process_application_status_change(
            self.application.id,
            ApplicationStatusCodes.ACTIVATION_AUTODEBET,
            change_reason="Eligible for autodebit activation",
        )

    def _allow_to_activate(self):
        """
        Check if the autodebit can be activated.
        """
        if self.application.status != ApplicationStatusCodes.ACTIVATION_AUTODEBET:
            raise AutoDebitError("Application is not in activation autodebit status")

        if not self.has_pending_tag:
            raise AutoDebitError("Application does not have pending tag")

    def activate(self):
        """
        Activate the autodebit.
        """
        from django.db import transaction

        self._allow_to_activate()

        with transaction.atomic():
            self._approve()
            self._update_tag_as_success()

    def _approve(self):
        """
        Approve the application.
        """
        from juloserver.julo.services import process_application_status_change

        process_application_status_change(
            self.application.id,
            ApplicationStatusCodes.LOC_APPROVED,
            change_reason="Credit limit activated by autodebit",
        )

    def _update_tag_as_success(self):
        """Mark the tag as success."""
        application_path_tag_status = ApplicationPathTagStatus.objects.filter(
            application_tag=self.APPLICATION_TAG,
            status=self.STATUS_PENDING,
        ).last()
        tag = ApplicationPathTag.objects.filter(
            application_id=self.application.id,
            application_path_tag_status=application_path_tag_status,
        ).last()

        if tag is None:
            self._assign_tag(self.STATUS_SUCCESS)
            return

        if tag.application_path_tag_status.status == self.STATUS_PENDING:
            success_status = ApplicationPathTagStatus.objects.filter(
                application_tag=self.APPLICATION_TAG, status=self.STATUS_SUCCESS
            ).last()

            tag.application_path_tag_status = success_status
            tag.save()


def activate(application: Application):
    """
    Activate the autodebit.
    This can be used in the autodebit activation process by
    squad 11 as callback.

    Use it like this:
    ```
    from juloserver.application_flow.services2 import autodebit

    autodebit.activate(application)
    ```

    :param application: Application
    """
    autodebit = AutoDebit(application)
    autodebit.activate()
