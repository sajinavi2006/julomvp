import logging

from django import forms
from django.conf import settings
from django.contrib.postgres.fields import JSONField
from django.contrib import admin
from django.utils.html import format_html
from rest_framework import serializers

from juloserver.payment_point.models import TransactionMethod
from juloserver.julo.admin import JuloModelAdmin, PrettyJSONWidget
from juloserver.julo.utils import get_oss_presigned_url
from juloserver.julo.validators import CustomerWhitelistCSVFileValidator
from juloserver.limit_validity_timer.constants import WhitelistCSVFileValidatorConsts
from juloserver.limit_validity_timer.models import LimitValidityTimer
from juloserver.limit_validity_timer.serializers import LimitValidityTimerContentSerializer
from juloserver.limit_validity_timer.services import (
    delete_limit_validity_campaign_on_redis,
    upload_csv_to_oss,
)
from juloserver.limit_validity_timer.tasks import trigger_upload_limit_validity_timer_campaign

logger = logging.getLogger(__name__)


class LimitValidityForm(forms.ModelForm):
    csv_customers_file = forms.FileField(
        widget=forms.FileInput(
            attrs={
                'class': 'form-control',
                'accept': '.csv',
            }
        ),
        label="File Upload",
        required=False,
        error_messages={'required': 'Please choose the CSV file'},
        validators=[
            CustomerWhitelistCSVFileValidator(
                allowed_extensions=WhitelistCSVFileValidatorConsts.ALLOWED_EXTENSIONS,
                max_size=WhitelistCSVFileValidatorConsts.MAX_FILE_SIZE,
                with_header=False
            )
        ]
    )
    transaction_method = forms.ModelChoiceField(
        required=False,
        queryset=TransactionMethod.objects.all(),
    )
    deeplink_url = forms.CharField(
        required=False,
        label="Deeplink/URL"
    )

    def __init__(self, *args, **kwargs):
        super(LimitValidityForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if not instance:
            self.fields['content'].initial = {
                "title": "", "body": "", "button": ""
            }

    class Meta:
        model = LimitValidityTimer
        exclude = ('csv_customers_file',)

    serializer_class = LimitValidityTimerContentSerializer

    def clean_content(self):
        content = self.cleaned_data['content']
        try:
            self.serializer_class(data=content).is_valid(raise_exception=True)
        except serializers.ValidationError as e:
            raise forms.ValidationError(e)
        return content

    def clean(self):
        cleaned_data = super().clean()
        deeplink_url = cleaned_data.get('deeplink_url')
        transaction_method = cleaned_data.get('transaction_method')
        if transaction_method and not deeplink_url:
            cleaned_data['deeplink_url'] = None
        elif deeplink_url and not transaction_method:
            cleaned_data['transaction_method'] = None
        else:
            raise forms.ValidationError({
                "transaction_method": "Require only 1 input from deeplink_url or transaction_method",
                "deeplink_url": "Require only 1 input from deeplink_url or transaction_method"
            })

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.transaction_method = self.cleaned_data.get('transaction_method')
        instance.deeplink_url = self.cleaned_data.get('deeplink_url')

        if commit:
            instance.save()

        return instance


class LimitValidityTimerAdmin(JuloModelAdmin):
    form = LimitValidityForm

    list_filter = ('campaign_name', 'start_date', 'end_date')
    search_fields = ('campaign_name', 'start_date', 'end_date')
    list_display = (
        'id',
        'campaign_name',
        'start_date',
        'end_date',
        'is_active',
        'minimum_available_limit',
        'transaction_method',
        'deeplink_url',
    )
    formfield_overrides = {
        JSONField: {'widget': PrettyJSONWidget}
    }
    readonly_fields = ('download_campaign_url',)
    exclude = ('id', 'upload_url')

    def save_model(self, request, obj, form, change):
        csv_required = obj.id is None
        super().save_model(request, obj, form, change)
        csv_in_mem = request.FILES.get('csv_customers_file')
        if csv_required or (not csv_required and csv_in_mem):
            upload_csv_to_oss(obj, csv_in_mem)
            trigger_upload_limit_validity_timer_campaign.delay(obj.id)

    def delete_model(self, request, obj):
        delete_limit_validity_campaign_on_redis(obj.id)
        obj.delete()

    @staticmethod
    def download_campaign_url(obj):
        if not obj.pk or not obj.upload_url:
            return

        download_url = get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, obj.upload_url)
        return format_html(
            '<a href="{0}" target="_blank">{1}</a>',download_url, download_url,
        )


admin.site.register(LimitValidityTimer, LimitValidityTimerAdmin)
