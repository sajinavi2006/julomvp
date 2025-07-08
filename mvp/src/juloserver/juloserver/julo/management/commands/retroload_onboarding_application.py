from builtins import str

from django.core.management.base import BaseCommand
from django_bulk_update.helper import bulk_update
from django.db.models import Q
from juloserver.julo.models import Application, Workflow
from juloserver.julo.constants import WorkflowConst


class Command(BaseCommand):
    help = 'retroload onboarding on application table'

    def add_arguments(self, parser):
        parser.add_argument('-r', '--Remove', action='store_true', help='retroload onboarding_id to null')
        parser.add_argument('-a', '--All', action='store_true', help='retroload all')
        parser.add_argument('-n', '--Null', action='store_true', help='retroload null onboarding_id')

    def handle(self, *args, **options):
        remove_data = options['Remove']
        all_data = options['All']
        null_data = options['Null']
        batch_size = 100
        workflow = Workflow.objects.get(name=WorkflowConst.JULO_ONE)

        if remove_data:
            applications = Application.objects.all()
            for application in applications:
                application.onboarding_id = None
            bulk_update(applications, update_fields=['onboarding_id'], batch_size=batch_size)
            self.stdout.write(self.style.SUCCESS('Success retroload null onboarding!'))
        else:
            # short form
            if null_data:
                applications = Application.objects.filter(app_version__gte='7.0.0',\
                                onboarding_id__isnull=True,
                                workflow_id=workflow.id)\
                                .exclude(app_version='7.4.2', app_version__contains='-v')
                self.stdout.write(self.style.SUCCESS('Start retroload shortform null onboarding!'))
            else:
                applications = Application.objects.filter(app_version__gte='7.0.0',\
                                workflow_id=workflow.id)\
                                .exclude(app_version='7.4.2', app_version__contains='-v')
                self.stdout.write(self.style.SUCCESS('Start retroload all shortform onboarding!'))

            for application in applications:
                application.onboarding_id = 2
            bulk_update(applications, update_fields=['onboarding_id'], batch_size=batch_size)
            self.stdout.write(self.style.SUCCESS('Success retroload shortform onboarding!'))
            
            # long form
            if null_data:
                applications = Application.objects.filter(Q(app_version__lt='7.0.0') |\
                                Q(app_version='7.4.2') | Q(app_version__contains='-v'),\
                                onboarding_id__isnull=True, workflow_id=workflow.id)
                self.stdout.write(self.style.SUCCESS('Start retroload longform null onboarding!'))
            else:
                applications = Application.objects.filter(Q(app_version__lt='7.0.0') |\
                                Q(app_version='7.4.2') | Q(app_version__contains='-v'),\
                                workflow_id=workflow.id)
                self.stdout.write(self.style.SUCCESS('Start retroload all longform onboarding!'))

            for application in applications:
                application.onboarding_id = 1
            bulk_update(applications, update_fields=['onboarding_id'], batch_size=batch_size)
            self.stdout.write(self.style.SUCCESS('Success retroload longform onboarding!'))
