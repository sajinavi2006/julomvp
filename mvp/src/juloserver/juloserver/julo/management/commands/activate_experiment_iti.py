from builtins import str
from datetime import datetime

from django.core.management.base import BaseCommand

from ...models import Experiment
from ...models import ExperimentAction
from ...models import ExperimentTestGroup
from ...statuses import ApplicationStatusCodes


class Command(BaseCommand):

    help = "Create experiment based on rules here: https://trello.com/c/FZ3Kb3Ul/2466-138-experiment"

    def handle(self, *args, **options):

        code = "PVXITI"
        experiment = Experiment.objects.create(
            code=code+"XSTL",
            name="Income Trust Index Experiment STL",
            status_old=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            status_new=ApplicationStatusCodes.DOCUMENTS_VERIFIED,
            date_start=datetime(2018, 5, 21),
            date_end=datetime(2018, 6, 20),
            description="Details can be found here: https://trello.com/c/FZ3Kb3Ul/2466-138-experiment",
            is_active=True,
            created_by="Hans")
        self.stdout.write(
            self.style.SUCCESS("Successfully created experiment %s" % experiment))

        ExperimentTestGroup.objects.create(
            experiment=experiment, type="product", value="stl1,stl2")
        ExperimentTestGroup.objects.create(
            experiment=experiment, type="application_id", value="#nth:-1:1,2,3,4,5,6")
        ExperimentTestGroup.objects.create(
            experiment=experiment, type="income_trust_index", value="0.95~")

        self.stdout.write(
            self.style.SUCCESS(
                "Successfully created test groups for experiment %s" % experiment))

        ExperimentAction.objects.create(
            experiment=experiment, type="CHANGE_STATUS",
            value=str(ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL))
        ExperimentAction.objects.create(
            experiment=experiment, type="ADD_NOTE", value=code)

        self.stdout.write(
            self.style.SUCCESS(
                "Successfully created actions for experiment %s" % experiment))

        experiment2 = Experiment.objects.create(
            code=code+"XMTL",
            name="Income Trust Index Experiment MTL",
            status_old=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            status_new=ApplicationStatusCodes.DOCUMENTS_VERIFIED,
            date_start=datetime(2018, 5, 21),
            date_end=datetime(2018, 6, 20),
            description="Details can be found here: https://trello.com/c/FZ3Kb3Ul/2466-138-experiment",
            is_active=True,
            created_by="Hans")
        self.stdout.write(
            self.style.SUCCESS("Successfully created experiment2 %s" % experiment2))

        ExperimentTestGroup.objects.create(
            experiment=experiment2, type="product", value="mtl1,mtl2")
        ExperimentTestGroup.objects.create(
            experiment=experiment2, type="application_id", value="#nth:-1:1,2,3,4")
        ExperimentTestGroup.objects.create(
            experiment=experiment2, type="income_trust_index", value="0.95~")

        self.stdout.write(
            self.style.SUCCESS(
                "Successfully created test groups for experiment2 %s" % experiment2))

        ExperimentAction.objects.create(
            experiment=experiment2, type="CHANGE_STATUS",
            value=str(ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL))
        ExperimentAction.objects.create(
            experiment=experiment2, type="ADD_NOTE", value=code)

        self.stdout.write(
            self.style.SUCCESS(
                "Successfully created actions for experiment2 %s" % experiment2))
