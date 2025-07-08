import ulid
import hashlib

from django.contrib import admin

from juloserver.partnership.models import LivenessConfiguration
from juloserver.partnership.liveness_partnership.constants import LivenessType
from juloserver.partnership.liveness_partnership.forms import LivenessConfigurationAdminForm
from juloserver.partnership.liveness_partnership.utils import generate_api_key


class LivenessConfigurationAdmin(admin.ModelAdmin):
    form = LivenessConfigurationAdminForm
    readonly_fields = ('client_id', 'hashing_client_id', 'api_key')

    def hashing_client_id(self, obj):
        if obj.client_id:
            return hashlib.sha1(str(obj.client_id).encode()).hexdigest()
        return ""

    # Add the computed field to the list_display if you want to show it in the list view
    list_display = (
        'cdate',
        'id',
        'client_id',
        'hashing_client_id',
        'platform',
        'partner_id',
        'provider',
        'is_active',
    )

    def get_fieldsets(self, request, obj=None):
        if not obj:
            # Customize the fieldset for create the data
            return (
                (
                    None,
                    {
                        'fields': (
                            'partner_id',
                            'platform',
                            'is_active',
                            'provider',
                        )
                    },
                ),
            )
        else:
            return (
                (
                    None,
                    {
                        'fields': (
                            'client_id',
                            'hashing_client_id',
                            'api_key',
                            'partner_id',
                            'platform',
                            'detection_types',
                            'whitelisted_domain',
                            'provider',
                            'is_active',
                        )
                    },
                ),
            )

    def save_model(self, request, obj, form, change):
        # Custom logic before saving
        if not change:  # Only for new objects (inserts)
            ulid_value = ulid.new()
            obj.client_id = ulid_value.uuid
            obj.detection_types = {
                LivenessType.PASSIVE: True,
                LivenessType.SMILE: True,
            }
            obj.whitelisted_domain = []
            # Save the model instance first
            super().save_model(request, obj, form, change)

            # start process generate api key
            timestamp = int(obj.cdate.timestamp())
            data = "{}:{}".format(timestamp, obj.client_id)
            api_key = generate_api_key(data)

            # Update the instance with the generated API key
            obj.api_key = api_key
            obj.save()  # Save the updated instance
        else:
            if obj.platform not in ['web', 'ios', 'android']:
                obj.platform = 'web'  # Set a default value if needed

            # Call the original save method to actually save the object
            super().save_model(request, obj, form, change)


admin.site.register(LivenessConfiguration, LivenessConfigurationAdmin)
