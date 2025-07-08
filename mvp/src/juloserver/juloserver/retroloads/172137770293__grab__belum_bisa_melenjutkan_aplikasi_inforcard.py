from __future__ import unicode_literals

from django.db import migrations
from juloserver.grab.script import generate_belum_bisa_melanjukan_aplikasi_info_card


def retroload_card_belum_bisa_melanjutkan_aplikasi(_apps, _schema_editor):
    generate_belum_bisa_melanjukan_aplikasi_info_card()


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(
            retroload_card_belum_bisa_melanjutkan_aplikasi, migrations.RunPython.noop
        )
    ]
