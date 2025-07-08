import logging
import sys
from django.core.management.base import BaseCommand
from . import load_workflow, update_status_lookups, load_status_change_reasons, load_loan_purpose
from ...models import Workflow, ProductLine
from ...product_lines import ProductLineCodes


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'load/reload grab food workflow and set it as default for grab food product line'

    def handle(self, *args, **options):
        workflow = Workflow.objects.get_or_none(name='GrabFoodWorkflow')
        if workflow:
            workflow.workflowstatuspath_set.all().delete()
            workflow.workflowstatusnode_set.all().delete()
        workflow_name = 'grab_food'
        workflow_cmd = load_workflow.Command()
        opts = {'workflow_name': (workflow_name,)}
        workflow_cmd.handle(**opts)

        grab_food_products = ProductLine.objects.filter(pk__in=ProductLineCodes.grabfood())
        if grab_food_products:
            for product in grab_food_products:
                product.default_workflow = workflow
                product.save()

        update_status_lookups.Command().handle()
        load_status_change_reasons.Command().handle()
        load_loan_purpose.Command().handle()

