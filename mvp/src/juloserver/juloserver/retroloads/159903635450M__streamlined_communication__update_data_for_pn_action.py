from __future__ import unicode_literals
from django.db import migrations
from juloserver.streamlined_communication.constant import CommunicationPlatform


from juloserver.streamlined_communication.models import PnAction



from juloserver.streamlined_communication.models import StreamlinedCommunication



def update_pn_action(apps, schema_editor):
    
    

    streamlined_communications = StreamlinedCommunication.objects.filter(
        communication_platform=CommunicationPlatform.PN,
        type='Payment Reminder',
        template_code='MTL_T0'
    )

    for streamlined_communication in streamlined_communications:
        PnAction.objects.get_or_create(
            streamlined_communication=streamlined_communication,
            order=1,
            title="Hubungi Kami",
            action="email",
            target="collections@julo.co.id")


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_pn_action,
                             migrations.RunPython.noop)
    ]
