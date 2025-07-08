from django.core.management.base import BaseCommand

from django.conf import settings
from django.db.models import Q

from juloserver.julo.models import ApplicationHistory

class Command(BaseCommand):
    help = 'retrofix application history lender approval old: 164 new: 165'

    def handle(self, *args, **options):
        old_lender_approval = 164
        new_lender_approval = 165
        application_histories = ApplicationHistory.objects.filter(
            Q(status_old=old_lender_approval) | Q(status_new=old_lender_approval))

        for application_history in application_histories:
            if application_history.status_old == old_lender_approval:
                application_history.status_old = new_lender_approval
                application_history.save()
            elif application_history.status_new == old_lender_approval:
                application_history.status_new = new_lender_approval
                application_history.save()

        self.stdout.write(self.style.SUCCESS(
            'Successfully Retrofix application history lender approval'))
