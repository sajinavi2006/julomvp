import logging
import sys
from django.core.management.base import BaseCommand
from . import load_workflow
from . import update_status_lookups


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'run all management command which needed by dynamic workflows'

    def handle(self, *args, **options):
        workflows = ('legacy', 'submitting_form', 'cash_loan', 'partner_workflow', 'julo_one')
        for workflow in workflows:
            workflow_cmd = load_workflow.Command()
            opts = {'workflow_name': (workflow,)}
            opts.update(options)
            workflow_cmd.handle(**opts)

        status_lookup_cmd = update_status_lookups.Command()
        status_lookup_cmd.handle(options)
