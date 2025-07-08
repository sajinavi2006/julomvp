from __future__ import unicode_literals
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0125_originalpassword'),
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='is_courtesy_call',
            field=models.BooleanField(null=True,default=False),
        ),
    ]
