from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform
from juloserver.streamlined_communication.models import StreamlinedCommunication
from juloserver.streamlined_communication.models import StreamlinedMessage


def add_streamlined_communication_for_new_login(apps, schema_editor):
    sms_message, created = StreamlinedMessage.objects.get_or_create(
        message_content="Apakah Anda telah melakukan login ke perangkat baru {{short_first_new_device_login_name}}? Jika tidak segera hubungi cs@julo.co.id.",
        parameter="{short_first_new_device_login_name}"
    )
    streamlined_communication_sms, created = StreamlinedCommunication.objects.get_or_create(
        message=sms_message,
        communication_platform=CommunicationPlatform.SMS,
        template_code='new_device_alert_sms'
        )

    old_customer_sms_message, created = StreamlinedMessage.objects.get_or_create(
        message_content="Apakah Anda telah melakukan login ke perangkat baru? Jika tidak segera hubungi cs@julo.co.id.")
    old_customer_streamlined_communication_sms, created = StreamlinedCommunication.objects.get_or_create(
        message=old_customer_sms_message,
        communication_platform=CommunicationPlatform.SMS,
        template_code='new_device_alert_sms_old_customer'
        )

class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_streamlined_communication_for_new_login,
                             migrations.RunPython.noop)
    ]
