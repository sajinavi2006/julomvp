from datetime import datetime, timedelta
from django.utils import timezone

from django.core.management.base import BaseCommand

from ...models import Experiment
from ...models import ExperimentAction
from ...models import ExperimentTestGroup
from ...statuses import ApplicationStatusCodes
from juloserver.julo.constants import CreditExperiments

class Command(BaseCommand):

    help = "Create experiment for provide B- credit score for previousley proved customers"

    def handle(self, *args, **options):

        code = CreditExperiments.RABMINUS165
        experiment = Experiment.objects.filter(code=code).first()

        if not experiment:
            experiment = Experiment.objects.create(
                code=code,
                name="Users who have already completed a loan and are eligible for B- when "
                        "they apply for new loan and got C even then get low credit assign them B-",
                status_old=0,
                status_new=0,
                date_start=timezone.localtime(timezone.now()).date(),
                date_end=timezone.localtime(timezone.now() + timedelta(days=21)).date(),
                description="Details can be found here: https://juloprojects.atlassian.net/browse/JEF-165",
                is_active=True,
                created_by="Titus")
            self.stdout.write(
                self.style.SUCCESS("Successfully created experiment %s" % experiment))
        else:
            self.stdout.write(
                self.style.SUCCESS("Experiment %s already exists %s" % (code, experiment,)))

        experiment_group = ExperimentTestGroup.objects.filter(
            experiment=experiment, type="credit_score_b_minus").first()
        if not experiment_group:
            ExperimentTestGroup.objects.create(
                experiment=experiment, type="credit_score_b_minus", value="#rng:0.74,0.86")

            self.stdout.write(
                self.style.SUCCESS(
                    "Successfully created test groups for experiment %s" % experiment))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Test groups already exists for %s" % experiment))

        experiment_action = ExperimentAction.objects.filter(
            experiment=experiment, type="CHANGE_CREDIT").first()
        if not experiment_action:
            ExperimentAction.objects.create(
                experiment=experiment, type="CHANGE_CREDIT",
                value="0.87")

            self.stdout.write(
                self.style.SUCCESS(
                    "Successfully created actions for experiment %s" % experiment))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Test Action already exists for %s" % experiment))