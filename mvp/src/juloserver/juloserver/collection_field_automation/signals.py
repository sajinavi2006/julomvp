from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from juloserver.collection_field_automation.models import FieldAttendance
from juloserver.portal.object.dashboard.constants import JuloUserRoles


@receiver(user_logged_in)
def post_agent_field_login(sender, user, request, **kwargs):
    if not user.groups.filter(
            name=JuloUserRoles.COLLECTION_FIELD_AGENT).exists():
        return

    FieldAttendance.objects.create(
        agent=user,
    )

