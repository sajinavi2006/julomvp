import logging
import sys
from django.core.management.base import BaseCommand
from . import load_workflow
from ...models import Workflow, ProductLine
from ...product_lines import ProductLineCodes


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'reload LOC workflow with new schema and set it as default for LOC product line'

    def handle(self, *args, **options):
        workflow = Workflow.objects.get_or_none(name='LineOfCreditWorkflow')
        if workflow:
            workflow.workflowstatuspath_set.all().delete()
            workflow.workflowstatusnode_set.all().delete()
        workflow_name = 'line_of_credit'
        workflow_cmd = load_workflow.Command()
        opts = {'workflow_name': (workflow_name,)}
        workflow_cmd.handle(**opts)

        loc_product = ProductLine.objects.get_or_none(pk=ProductLineCodes.LOC)
        if loc_product:
            loc_product.default_workflow = workflow
            loc_product.save()

