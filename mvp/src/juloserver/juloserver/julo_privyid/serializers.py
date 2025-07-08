from __future__ import unicode_literals

from builtins import object
from rest_framework import serializers
from ..julo.models import Image


class ConfirmOtpSerializer(serializers.Serializer):
    otp_code = serializers.CharField(max_length=6, required=True)


class ReuploadPrivyImageSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Image
        exclude = ('url', 'thumbnail_url')
