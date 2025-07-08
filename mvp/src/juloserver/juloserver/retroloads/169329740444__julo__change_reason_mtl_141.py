# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import StatusLookup



from juloserver.julo.models import ChangeReason



def add_change_reason_for_141(apps, schema_editor):
    
    
    status = StatusLookup.objects.filter(status_code=141).last()
    ChangeReason.objects.get_or_create(
        reason="Bank Name Validation for MTL users",
        status=status,
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_change_reason_for_141,
            migrations.RunPython.noop)
    ]
