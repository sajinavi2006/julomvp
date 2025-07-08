from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform


from juloserver.streamlined_communication.models import StreamlinedMessage



def update_sms_content_due_date_25(apps, schema_editor):
    
    bukalapak_sms_pre_due_date_25 = StreamlinedMessage.objects.filter(
        message_content="Yth {{firstname}} Tagihan BayarNanti kamu Rp {{due_amount}} akan jatuh tempo pd {{due_date}}. "
                        "Segera bayar tagihannya agar ttp bs pk BayarNanti- bl.id/BayarNanti"
        )
    if bukalapak_sms_pre_due_date_25:
        bukalapak_sms_pre_due_date_25.update(
            message_content="Yth {{firstname}}, tagihan BayarNanti kamu Rp {{due_amount}} akan jatuh tempo pd {{due_date}}. "
                            "Segera bayar tagihannya agar ttp bs pk BayarNanti- bl.id/BayarNanti"
        )


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_sms_content_due_date_25,
                             migrations.RunPython.noop)
    ]
