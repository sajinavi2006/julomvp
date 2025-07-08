# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from juloserver.julo.constants import FeatureNameConst

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunSQL("ALTER USER ops_server SET timezone = 'UTC';")
    ]
