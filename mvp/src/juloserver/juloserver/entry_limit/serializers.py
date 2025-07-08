from __future__ import unicode_literals

import logging
from builtins import object

from rest_framework import serializers

from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import WorkflowStatusPath
from juloserver.julo.product_lines import ProductLineCodes

from .models import EntryLevelLimitConfiguration

logger = logging.getLogger(__name__)


class EntryLevelLimitConfigurationSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = EntryLevelLimitConfiguration
        fields = '__all__'

    def validate(self, data):
        """
        Check that the start is before the stop.
        """
        action = data['action']
        status_previous = action[:3]
        status_next = action[-3:]
        product_line_code = data['product_line_code']

        if product_line_code not in ProductLineCodes.j1():
            raise serializers.ValidationError({"product_line": ["Only support J1 for now"]})
        if action:
            path_existed = WorkflowStatusPath.objects.filter(
                status_previous=status_previous,
                status_next=status_next,
                workflow__name=WorkflowConst.JULO_ONE,
            ).exists()
            if not path_existed:
                raise serializers.ValidationError(
                    {"action": "This status path doesn't exist, %s" % action}
                )

        return data

    def to_internal_value(self, data):
        data['enabled_trx_method'] = data['enabled_trx_method'].split(',')
        return super().to_internal_value(data)
