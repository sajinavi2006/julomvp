from django.core.management.base import BaseCommand
from ...models import Application
from ...statuses import ApplicationStatusCodes


class Command(BaseCommand):

    help = 'retroactively move application in status 170 to 163'

    def handle(self, *args, **options):
        applications = Application.objects.filter(application_status=ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED)
        for application in applications:
            application.change_status(ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED)
            application.save()
        self.stdout.write(self.style.SUCCESS('Successfully move retroactive application from 170 to 163'))
