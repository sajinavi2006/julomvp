from __future__ import unicode_literals
from django.db import migrations


def load_new_status_lookups_and_add_feature_params(apps, schema_editor):
    new_status_codes = {'Fraud Reported': 440,
                        'Application or Friendly Fraud': 441,
                        'Scam Victim': 442}
    StatusLookup = apps.get_model("julo", "StatusLookup")
    MobileFeatureSetting = apps.get_model("julo", "MobileFeatureSetting")
    to_create = []
    for status, code in new_status_codes.items():
        to_create.append(StatusLookup(status_code=code, status=status))
    StatusLookup.objects.bulk_create(to_create)
    feature = MobileFeatureSetting.objects.get(feature_name='bad_payment_message_setting')
    params = feature.parameters
    for status, code in new_status_codes.items():
        params[str(code)] = {
            "button_action": "aktivitaspinjaman",
            "button_text": "Bayar Sekarang",
            "content": "Pinjaman Anda sudah lewat jatuh tempo.\n Segera bayar tagihan untuk kembali bertransaksi",
            "title": "Halo"
        }
    feature.parameters = params
    feature.save()



class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(load_new_status_lookups_and_add_feature_params, migrations.RunPython.noop)
    ]
