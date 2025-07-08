from __future__ import print_function
from django.core.management.base import BaseCommand

from django.conf import settings
from django.db.models import Q

from juloserver.julo.models import Application
from juloserver.julo.models import ApplicationNote
from juloserver.julo.services import ApplicationHistoryUpdated


def manual_change_status(application_id, new_status_code, change_reason, note):
    app = Application.objects.get(pk=application_id)
    old_status_code = app.status
    new_status_code = new_status_code
    is_experiment = False
    with ApplicationHistoryUpdated(
        app, change_reason=change_reason, is_experiment=is_experiment
    ) as updated:
        app.change_status(new_status_code)
        app.save()

    status_change = updated.status_change
    application_note = ApplicationNote.objects.create(
        note_text=note, application_id=app.id, status_change=status_change
    )


class Command(BaseCommand):
    help = 'mass change status applications in 164 to 163'

    def handle(self, *args, **options):
        status_from = 164
        status_to = 163
        note = 'Back to 163 new disbursement flow adjustment'
        change_reason = 'legal agreement resubmitted'

        applications = Application.objects.filter(application_status_id=status_from)
        self.stdout.write(self.style.SUCCESS(
            '========================== change status Begin for %s applications ================' % (
                applications.count())))
        sucess_applications = []
        failed_applications = []

        for application in applications:
            try:
                manual_change_status(application.id, status_to, change_reason, note)
            except Exception as e:
                print(e)
                failed_applications.append(application.id)
                continue
            sucess_applications.append(application.id)

        self.stdout.write(self.style.SUCCESS(
            'Successfully change status from 164 to 163 for %s applications %s' % (
                len(sucess_applications), sucess_applications)))
        self.stdout.write(self.style.ERROR(
            'Failed change status from 164 to 163 for %s applications %s' % (
                len(failed_applications), failed_applications)))
