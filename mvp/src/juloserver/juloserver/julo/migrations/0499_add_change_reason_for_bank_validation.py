# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


def add_change_reason_for_160(apps, schema_editor):
    ChangeReason = apps.get_model("julo", "ChangeReason")
    StatusLookup = apps.get_model("julo", "StatusLookup")
    status = StatusLookup.objects.filter(status_code=160).last()
    ChangeReason.objects.get_or_create(
        reason="Name Validation Ongoing",
        status=status,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0498_fixing_statuspath_for_name_bank_validation'),
    ]

    operations = [
        migrations.RunPython(add_change_reason_for_160,
            migrations.RunPython.noop)
    ]
