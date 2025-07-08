from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform


def change_stl_mtl_template_codes(apps, schema_editor):
    StreamlinedMessage = apps.get_model("streamlined_communication", "StreamlinedMessage")
    StreamlinedCommunication = apps.get_model("streamlined_communication", "StreamlinedCommunication")


    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='friska_mtl_sms_dpd_-2',
               dpd=-2).update(template_code='mtl_sms_dpd_-2')

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='friska_stl_sms_dpd_-2',
               dpd=-2).update(template_code='stl_sms_dpd_-2')

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='friska_mtl_sms_dpd_0',
               dpd=0).update(template_code='mtl_sms_dpd_0')

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='friska_stl_sms_dpd_0',
               dpd=0).update(template_code='stl_sms_dpd_0')


class Migration(migrations.Migration):
    dependencies = [
        ('streamlined_communication', '0020_add_pn_for_110_old_version'),
    ]

    operations = [
        migrations.RunPython(change_stl_mtl_template_codes,
                             migrations.RunPython.noop)
    ]
