from django.contrib import (
    admin,
    messages,
)
from django.contrib.postgres.fields import ArrayField
from django.forms import Textarea
from django.http import HttpResponseRedirect

from juloserver.application_flow.models import (
    ApplicationPathTagStatus,
    ApplicationTag,
    DigitalSignatureThreshold,
    MycroftResult,
    MycroftThreshold,
    SuspiciousFraudApps,
    VoiceRecordingThreshold,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


class ApplicationPathTagStatusAdmin(admin.ModelAdmin):
    list_display = ('application_tag', 'status', 'definition')


class ApplicationTagAdmin(admin.ModelAdmin):
    list_display = ('application_tag', 'is_active')


class SuspiciousFraudAppsAdmin(admin.ModelAdmin):
    formfield_overrides = {
        ArrayField: {'widget': Textarea(attrs={'rows': 8, 'cols': 40})},
    }


class MycroftThresholdAdmin(admin.ModelAdmin):
    list_display = ['score', 'logical_operator', 'is_active']

    def delete_model(self, request, obj):
        if MycroftResult.objects.filter(mycroft_threshold=obj).exists():
            messages.error(
                request,
                'Not allowed to delete this threshold as it is already used by some records.',
            )
            return None

        if (
            obj.is_active
            and FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.MYCROFT_SCORE_CHECK, is_active=True
            ).exists()
        ):
            messages.error(
                request,
                'Not allowed to delete this active threshold as Mycroft Check is active. '
                'Please change active threshold or disable Mycroft Check in FeatureSetting.',
            )
            return None

        super().delete_model(request, obj)

    def response_delete(self, request, object_display, object_id):
        error_messages = messages.get_messages(request)
        if error_messages:
            for message in error_messages:
                messages.error(request, message)
            return HttpResponseRedirect(request.path)

        return super().response_delete(request, object_display, object_id)


admin.site.register(ApplicationPathTagStatus, ApplicationPathTagStatusAdmin)
admin.site.register(ApplicationTag, ApplicationTagAdmin)
admin.site.register(DigitalSignatureThreshold)
admin.site.register(VoiceRecordingThreshold)
admin.site.register(SuspiciousFraudApps, SuspiciousFraudAppsAdmin)
admin.site.register(MycroftThreshold, MycroftThresholdAdmin)
