# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import print_function

from dateutil.relativedelta import relativedelta

from django.db import migrations
from django.utils import timezone

from juloserver.julo.models import SkiptraceHistory
from juloserver.julo.statuses import ApplicationStatusCodes


from juloserver.julo.models import SkiptraceHistory



def retroactively_load_old_status_skiptrace_history(apps, schema_editor):
    

    today = timezone.now().date()
    last_3_month = today - relativedelta(months=3)

    skiptrace_histories = SkiptraceHistory.objects.filter(old_application_status=None,
                                                          cdate__date__gte=last_3_month)

    for skiptrace_history in skiptrace_histories:
        application = skiptrace_history.application
        application_history = application.applicationhistory_set.filter(
            status_new=skiptrace_history.application_status).last()
        old_application_status = None
        if application_history:
            old_application_status = application_history.status_old

        if old_application_status:
            skiptrace_history.old_application_status = old_application_status
            skiptrace_history.save()

            print('successfully retroload old_status {} to skiptrace_history {}'.format(
                skiptrace_history.old_application_status, skiptrace_history.id))


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(retroactively_load_old_status_skiptrace_history,
                             migrations.RunPython.noop)
    ]