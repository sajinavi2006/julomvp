import logging
import sys
import importlib

from itertools import chain
from django.core.management.base import BaseCommand
from django.db import transaction
from ...models import Workflow, WorkflowStatusNode, WorkflowStatusPath

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'Load workflow schema to DB'

    def add_arguments(self, parser):
        parser.add_argument('--workflow_name', nargs='+', help='workflow schema filename without extension')

    def handle(self, *args, **options):
        verbosity = int(options['verbosity']) if 'verbosity' in options else 0
        argument = options['workflow_name'][0]
        schema_module = importlib.import_module('juloserver.julo.workflows2.schemas.%s' % argument)
        classname = argument + "_schema"
        classobj = eval("schema_module." + ''.join(x.capitalize() or '_' for x in classname.split('_')))
        workflow_name = classobj.NAME
        workflow_desc = classobj.DESC
        workflow_handler = classobj.HANDLER

        happy_paths = classobj.happy_paths
        detour_paths = classobj.detour_paths
        graveyard_paths = classobj.graveyard_paths
        status_paths = chain(happy_paths, detour_paths, graveyard_paths)
        status_nodes = classobj.status_nodes
        if verbosity > 0:
            self.stdout.write(self.style.SUCCESS("======================================"))
            self.stdout.write(self.style.SUCCESS("load workflow begin"))
            self.stdout.write(self.style.SUCCESS("======================================"))
        workflow_exist = Workflow.objects.get_or_none(name=workflow_name)

        with transaction.atomic():
            if not workflow_exist:
                workflow = Workflow.objects.create(name=workflow_name, desc=workflow_desc, handler=workflow_handler)
                if verbosity > 0:
                    self.stdout.write(self.style.SUCCESS("%s workflow created" % workflow_name))
                    self.stdout.write(self.style.SUCCESS("------------------------------------"))
            else:
                workflow = workflow_exist
                if verbosity > 0:
                    self.stdout.write(self.style.SUCCESS("%s workflow updating status and node" % workflow_name))
                    self.stdout.write(self.style.SUCCESS("------------------------------------"))
            for status in status_paths:
                origin = status['origin_status']
                destinations = status['allowed_paths']
                for destination in destinations:
                    if verbosity > 0:
                        self.stdout.write(self.style.SUCCESS("%s --> %s checking" % (origin, destination['end_status'])))
                    path_exist = WorkflowStatusPath.objects.get_or_none(status_previous=origin,
                                                                        status_next=destination['end_status'],
                                                                        workflow=workflow)
                    if not path_exist:
                        WorkflowStatusPath.objects.create(
                            status_previous=origin, status_next=destination['end_status'],
                            customer_accessible=destination['customer_accessible'],
                            agent_accessible=destination['agent_accessible'], workflow=workflow,
                            type=destination['type'])
                        if verbosity > 0:
                            self.stdout.write(
                                self.style.SUCCESS("%s --> %s status path created" % (origin, destination['end_status'])))
                            self.stdout.write(self.style.SUCCESS("------------------------------------"))
                    else:
                        if verbosity > 0:
                            self.stdout.write(
                                self.style.WARNING(
                                    "%s --> %s status path skiped (already exist)" % (origin, destination['end_status'])))
                            self.stdout.write(self.style.WARNING("------------------------------------"))
            if status_nodes:
                for node in status_nodes:
                    node_exist = WorkflowStatusNode.objects.get_or_none(status_node=node['destination_status'],
                                                                        workflow=workflow)
                    if not node_exist:
                        WorkflowStatusNode.objects.create(status_node=node['destination_status'],
                                                          handler=node['handler'], workflow=workflow)
                        if verbosity > 0:
                            self.stdout.write(self.style.SUCCESS(
                                "%s status node with %s handler created" % (node['destination_status'], node['handler'])))
                            self.stdout.write(self.style.SUCCESS("------------------------------------"))
                    else:
                        if verbosity > 0:
                            self.stdout.write(
                                self.style.WARNING("%s status node skiped (already exist)" % node['destination_status']))
                            self.stdout.write(self.style.WARNING("------------------------------------"))
            else:
                if verbosity > 0:
                    self.stdout.write(self.style.WARNING("no status nodes handler defined for %s" % workflow_name))
        if verbosity > 0:
            self.stdout.write(self.style.SUCCESS("all Process done"))
