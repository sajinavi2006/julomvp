import logging
import sys
from django.core.management.base import BaseCommand
from . import load_workflow
from ...models import Workflow, ProductLine
from ...product_lines import ProductLineCodes


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'load LOC workflow and set it as default for LOC product line'

    def handle(self, *args, **options):
        workflow = 'line_of_credit'
        workflow_cmd = load_workflow.Command()
        opts = {'workflow_name': (workflow,)}
        workflow_cmd.handle(**opts)

        workflow = Workflow.objects.get_or_none(name='LineOfCreditWorkflow')
        if workflow:
            loc_product = ProductLine.objects.get_or_none(pk=ProductLineCodes.LOC)
            if loc_product:
                loc_product.default_workflow = workflow
                loc_product.save()

