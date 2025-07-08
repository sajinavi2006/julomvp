from rest_framework import serializers

from juloserver.julo.models import Partner


class PartnerSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = Partner
        fields = ('id', 'name', 'company_name')
