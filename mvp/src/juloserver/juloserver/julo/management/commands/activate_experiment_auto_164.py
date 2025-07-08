from builtins import str
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

from ...models import Experiment
from ...models import ExperimentAction
from ...models import ExperimentTestGroup
from ...statuses import ApplicationStatusCodes


class Command(BaseCommand):

    help = "Create experiment for Automatic state change from 163 to 164"

    def handle(self, *args, **options):

        code = "AUTO163TO164"
        experiment = Experiment.objects.filter(code=code).first()
        if not experiment:
            experiment = Experiment.objects.create(
                code=code,
                name="Automatic state change from 163 to 164",
                status_old=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
                status_new=ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
                date_start=datetime.now(),
                date_end=datetime.now() + timedelta(days=28),
                description="Details can be found here: https://juloprojects.atlassian.net/browse/JEF-123",
                is_active=True,
                created_by="Titus")
            self.stdout.write(
                self.style.SUCCESS("Successfully created experiment %s" % experiment))
        else:
            self.stdout.write(
                self.style.SUCCESS("Experiment %s already exists %s" % (code, experiment,)))

        experiment_group = ExperimentTestGroup.objects.filter(
            experiment=experiment, type="application_id", value="#nth:-2:1,2,3,4,5,6,7,8").first()
        if not experiment_group:
            ExperimentTestGroup.objects.create(
                experiment=experiment, type="application_id", value="#nth:-2:1,2,3,4,5,6,7,8")

            self.stdout.write(
                self.style.SUCCESS(
                    "Successfully created test groups for experiment %s" % experiment))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Test groups already exists for %s" % experiment))

        experiment_action = ExperimentAction.objects.filter(
            experiment=experiment, type="CHANGE_STATUS",
            value=str(ApplicationStatusCodes.NAME_VALIDATE_ONGOING)).first()
        if not experiment_action:
            ExperimentAction.objects.create(
                experiment=experiment, type="CHANGE_STATUS",
                value=str(ApplicationStatusCodes.NAME_VALIDATE_ONGOING))

            self.stdout.write(
                self.style.SUCCESS(
                    "Successfully created actions for experiment %s" % experiment))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Test Action already exists for %s" % experiment))
