from rest_framework import serializers
from juloserver.apiv2.utils import custom_error_messages_for_required


class RunFdcInquirySerializer(serializers.Serializer):
    nik_spouse = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required('nik_spouse')
    )
    application_xid = serializers.IntegerField(
        required=True, error_messages=custom_error_messages_for_required('application_xid')
    )
