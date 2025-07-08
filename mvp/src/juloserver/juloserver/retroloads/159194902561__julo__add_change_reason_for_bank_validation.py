# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import StatusLookup



from juloserver.julo.models import ChangeReason



def add_change_reason_for_160(apps, schema_editor):
    
    
    status = StatusLookup.objects.filter(status_code=160).last()
    ChangeReason.objects.get_or_create(
        reason="Name Validation Ongoing",
        status=status,
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_change_reason_for_160,
            migrations.RunPython.noop)
    ]
