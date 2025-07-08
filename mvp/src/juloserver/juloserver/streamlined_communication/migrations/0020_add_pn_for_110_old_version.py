# coding=utf-8
from django.db import migrations

from juloserver.julo.models import StatusLookup
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import PaymentStatusCodes, ApplicationStatusCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform


def add_upgrade_app_pn_for_110_handler(apps, schema_editor):
    StreamlinedMessage = apps.get_model("streamlined_communication", "StreamlinedMessage")
    StreamlinedCommunication = apps.get_model("streamlined_communication", "StreamlinedCommunication")


    # pn to reinstall new version of app
    message_streamlined_110_pn_for_old_version, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Anda terdeteksi menggunakan versi aplikasi yang sudah tidak disupport oleh julo. Silahkan update applikasi anda terlebih dahulu untuk melakukan pengajuan"
        )
    streamlined_comm_110_pn_for_old_version = StreamlinedCommunication.objects.get_or_create(
        message=message_streamlined_110_pn_for_old_version,
        status="Send Pn when application status 110 for installing new version of app",
        communication_platform=CommunicationPlatform.PN,
        criteria={},
        status_code_id=ApplicationStatusCodes.FORM_SUBMITTED,
        template_code='inform_old_version_reinstall',
        description="called in function inform_old_version_reinstall for review Legal Agreement dont have fullname"
    )


class Migration(migrations.Migration):
    dependencies = [
        ('streamlined_communication', '0019_update_streamlined_sms_va_for_bl'),
    ]

    operations = [
        migrations.RunPython(add_upgrade_app_pn_for_110_handler,
                             migrations.RunPython.noop)
    ]
