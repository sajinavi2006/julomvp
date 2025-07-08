import json

from cuser.middleware import CuserMiddleware
from django.db.models import signals
from django.dispatch import receiver
from django.db.models.expressions import CombinedExpression

from juloserver.sales_ops.models import (
    SalesOpsLineup,
    SalesOpsLineupHistory,
)
from juloserver.sales_ops.utils import convert_dict_to_json_serializable


@receiver(signals.post_save, sender=SalesOpsLineup)
def store_sales_ops_lineup_history(sender, instance, created, **kwargs):
    """
    Store the changes to the SalesOpsLineupHistory
    """
    excluded_fields = ['cdate', 'udate']
    tracker = instance.tracker
    old_values = tracker.changed()
    old_values = {key: value for key, value in old_values.items() if key not in excluded_fields}

    new_values = {
        field_name: (
            getattr(instance, field_name)
            if not isinstance(getattr(instance, field_name), CombinedExpression)
            else str(getattr(instance, field_name))
        )
        for field_name in old_values
    }

    if new_values != old_values:
        # this is a workaround until we can use JSONField(encoder=DjangoJSONEncoder)
        new_values = convert_dict_to_json_serializable(new_values)
        old_values = convert_dict_to_json_serializable(old_values)
        auth_user = CuserMiddleware.get_user()
        auth_user_id = getattr(auth_user, "id", None)
        SalesOpsLineupHistory.objects.create(
            lineup_id=instance.id,
            old_values=old_values,
            new_values=new_values,
            changed_by_id=auth_user_id
        )
