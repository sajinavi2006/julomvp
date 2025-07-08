from builtins import object

from rest_framework.serializers import ModelSerializer

from juloserver.julo.models import Application


class BoostStatusViewSerializer(ModelSerializer):
    class Meta(object):
        model = Application
        fields = [
            'additional_contact_1_name',
            'additional_contact_1_number',
            'additional_contact_2_name',
            'additional_contact_2_number',
            'loan_purpose_description_expanded',
        ]
