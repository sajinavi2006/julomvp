from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform


from juloserver.streamlined_communication.models import StreamlinedCommunication



from juloserver.streamlined_communication.models import StreamlinedMessage



def add_message_for_notify_va_bl(apps, schema_editor):
    
    

    sms_content, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Hi {{first_name}}, Virtual Account untuk pembayaran Bukalapak BayarNanti "
                            "anda adl (013){{virtual_account}}. Info lebih lanjut (021) 395 099 57.",
            parameter="{first_name,virtual_account}",
        )

    streamlined_communication, _ = StreamlinedCommunication.objects.get_or_create(
        message=sms_content,
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_bukalapak_notify_va_created',
        description="this streamlined comm is to send sms to bl customer that want direct payment to us",
    )


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_message_for_notify_va_bl,
                             migrations.RunPython.noop)
    ]
