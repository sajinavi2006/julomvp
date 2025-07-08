from juloserver.julo.constants import ExperimentConst
from juloserver.julo.models import Application, ExperimentSetting
from juloserver.account.models import ExperimentGroup

from juloserver.application_form.constants import MotherMaidenNameConst
from juloserver.application_flow.services import still_in_experiment, is_version_target
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.application_form.exceptions import JuloMotherNameException

logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


class MotherNameValidation:
    def __init__(self, application_id, app_version=None, mother_maiden_name=None):
        self._is_passed_app_id = False
        self._is_passed_app_version = False

        # criteria from experiment setting
        self.criteria_app_id = []
        self.criteria_app_version = None
        self.criteria_improper_names = []

        self._app_version = app_version
        self._application_id = application_id
        self._mother_maiden_name = mother_maiden_name

        self.experiment_code = ExperimentConst.MOTHER_NAME_VALIDATION
        self.experiment_group = 'experiment'
        self.control_group = 'control'

    @property
    def app_version(self):
        return self._app_version

    @app_version.setter
    def app_version(self, value):
        self._app_version = value

    @property
    def application_id(self):
        return self._application_id

    @application_id.setter
    def application_id(self, value):
        self._application_id = value

    @property
    def mother_maiden_name(self):
        return self._mother_maiden_name

    @mother_maiden_name.setter
    def mother_maiden_name(self, value):
        self._mother_maiden_name = value

    def is_passed_app_id(self):

        application = self.get_obj_application()
        if not application:
            return False

        last_digit_app_id = application.id % 10
        if last_digit_app_id not in self.criteria_app_id:
            return False

        return True

    def is_passed_app_version(self):

        if not self.app_version or not self.criteria_app_version:
            return False

        return is_version_target(
            app_version=self.app_version,
            target_versions=self.criteria_app_version,
        )

    def get_experiment_setting(self):
        experiment_setting = ExperimentSetting.objects.filter(
            code=self.experiment_code,
        ).last()

        return experiment_setting

    def get_obj_application(self):

        application = Application.objects.filter(pk=self.application_id).last()
        return application

    def setup_experiment_setting(self, is_need_criteria_only=False):

        experiment_setting = self.get_experiment_setting()
        if not experiment_setting:
            return False

        criteria = experiment_setting.criteria
        self.criteria_app_id = criteria.get(MotherMaidenNameConst.KEY_APP_ID)
        self.criteria_app_version = criteria.get(MotherMaidenNameConst.KEY_APP_VERSION)
        self.criteria_improper_names = criteria.get(MotherMaidenNameConst.KEY_IMPROPER_NAMES)

        if is_need_criteria_only:
            return True

        self._is_passed_app_version = self.is_passed_app_version()
        self._is_passed_app_id = self.is_passed_app_id()

        return True

    def store_to_experiment_group(self, experiment_group, customer_id):

        experiment_setting = self.get_experiment_setting()
        is_exists = ExperimentGroup.objects.filter(
            application_id=self.application_id, experiment_setting=experiment_setting
        ).exists()
        if not is_exists:
            ExperimentGroup.objects.create(
                application_id=self.application_id,
                customer_id=customer_id,
                experiment_setting=experiment_setting,
                group=experiment_group,
            )

    @sentry.capture_exceptions
    def run(self, is_need_store_as_experiment=True) -> bool:
        """
        This trigger when user create application ID will be check
        - this application ID is eligible for experiment or not?
        - the app_version is available for the feature or not?
        - if yes, will check and run the validation
        """

        try:
            is_active = still_in_experiment(self.experiment_code)
            if not is_active:
                return False

            if not self.setup_experiment_setting(is_need_criteria_only=False):
                logger.info(
                    {
                        'message': '[MotherNameExp] Something problem '
                        'when setup experiment setting',
                        'application_id': self.application_id,
                    }
                )
                return False

            application = self.get_obj_application()
            customer_id = application.customer_id
            if (
                not self._is_passed_app_id
                or not self._is_passed_app_version
                or not application.is_julo_one()
            ):
                logger.info(
                    {
                        'message': '[MotherNameExp] Application ID is not in criteria',
                        'application_id': self.application_id,
                        'criteria_app_id': self.criteria_app_id,
                        'app_version': self.app_version,
                        'criteria_app_version': self.criteria_app_version,
                    }
                )
                if self._is_passed_app_version:
                    if is_need_store_as_experiment:
                        self.store_to_experiment_group(
                            customer_id=customer_id, experiment_group=self.control_group
                        )

                return False

            if is_need_store_as_experiment:
                self.store_to_experiment_group(
                    customer_id=customer_id, experiment_group=self.experiment_group
                )
            return True

        except Exception as error:
            raise JuloMotherNameException(str(error))

    def run_validation(self):
        """
        This function to trigger validation improper names
        if return True, so the application is fine
        and can proceed to submit the form / other process
        """

        experiment_setting = self.get_experiment_setting()
        is_experiment = ExperimentGroup.objects.filter(
            application_id=self.application_id,
            experiment_setting=experiment_setting,
            group=self.experiment_group,
        ).exists()
        if not is_experiment:
            return True

        if not self.mother_maiden_name:
            logger.warning(
                {'message': '[MotherNameExp] value is empty', 'application_id': self.application_id}
            )
            return False

        # Setup / Load experiment setting
        self.setup_experiment_setting(is_need_criteria_only=True)
        for item in self.criteria_improper_names:
            if self.mother_maiden_name.lower() == item.lower():
                logger.error(
                    {
                        'message': '[MotherNameExp] the improper names is detected!',
                        'application_id': self.application_id,
                        'mother_maiden_name_db': self.mother_maiden_name,
                        'improper_names': item,
                    }
                )
                return False

        return True

    def check_and_get_improper_names(self):

        experiment_setting = self.get_experiment_setting()
        if not experiment_setting:
            return None

        # Call and setup to load experiment setting
        if not self.setup_experiment_setting(is_need_criteria_only=True):
            return None

        experiment_app = ExperimentGroup.objects.filter(
            application_id=self.application_id,
            experiment_setting=experiment_setting,
        ).last()
        if experiment_app and experiment_app.group == self.experiment_group:
            return self.criteria_improper_names

        # If application still record on experiment group will check manually by logic
        is_app_experiment = self.run(is_need_store_as_experiment=False)
        if is_app_experiment:
            return self.criteria_improper_names

        return None
