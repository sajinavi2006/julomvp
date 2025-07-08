from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform


from juloserver.streamlined_communication.models import StreamlinedCommunication



from juloserver.streamlined_communication.models import StreamlinedMessage



def change_stl_mtl_template_codes(apps, schema_editor):
    
    


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
    ]

    operations = [
        migrations.RunPython(change_stl_mtl_template_codes,
                             migrations.RunPython.noop)
    ]
