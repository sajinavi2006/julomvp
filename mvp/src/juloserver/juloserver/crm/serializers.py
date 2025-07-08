from __future__ import unicode_literals

from builtins import object
from rest_framework import serializers

from juloserver.julo.models import Application
from juloserver.julo.models import ApplicationNote
from app_status.models import CannedResponse


class ApplicationNoteSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = ApplicationNote
        fields = ('__all__')


class ApplicationSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Application
        fields = ('__all__')


class CannedResponseSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = CannedResponse
        fields = ('__all__')
