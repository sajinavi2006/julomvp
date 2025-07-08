from builtins import str

from django.core.management.base import BaseCommand
from django.db.models import Q
from juloserver.julo.models import Application, ApplicationUpgrade


class Command(BaseCommand):
    help = 'retroload ApplicationUpgrade per 100k row'

    def handle(self, *args, **options):
        batch_size = 100

        extension_ids = ApplicationUpgrade.objects.values_list('application_id', flat=True)
        applications = Application.objects.exclude(pk__in=extension_ids)[:100000]

        self.stdout.write(self.style.SUCCESS('Start retroload ApplicationUpgrade!'))
        application_extension = []

        for application in applications:
            has_extension = ApplicationUpgrade.objects.get_or_none(application_id=application.id)
            if not has_extension:
                self.stdout.write(self.style.SUCCESS(application.id))
                extension = ApplicationUpgrade(
                    application_id=application.id,
                    application_id_first_approval=application.id,
                    is_upgrade=0,
                )
                application_extension.append(extension)
            
        ApplicationUpgrade.objects.bulk_create(application_extension, batch_size=batch_size)
        self.stdout.write(self.style.SUCCESS('Success retroload ApplicationUpgrade!'))
