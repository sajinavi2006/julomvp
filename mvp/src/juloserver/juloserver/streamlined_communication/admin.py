import base64
import codecs
import csv
import os
import tempfile
from builtins import object
from datetime import timedelta
from io import BytesIO

import pandas as pd
from django.conf.urls import url
from django.contrib import (
    admin,
    messages,
)
from django.contrib.admin import ModelAdmin
from django import forms
from django.core.urlresolvers import reverse
from django.http import HttpResponse
from django.shortcuts import (
    redirect,
    render,
)
from rest_framework import serializers

from juloserver.email_delivery.constants import EmailStatusMapping
from juloserver.email_delivery.utils import email_status_prioritization
from juloserver.julo.admin import (
    JuloModelAdmin,
    ImportCsvForm,
)
from juloserver.julo.models import EmailHistory
from juloserver.julo.services2 import get_redis_client
from juloserver.streamlined_communication.models import (
    Holiday,
    StreamlinedVoiceMessage,
    PnAction,
    TelcoServiceProvider,
    SmsTspVendorConfig,
    AppDeepLink,
    NeoBannerCard,
    StreamlinedCampaignDepartment,
    StreamlinedCampaignSquad,
)
from juloserver.streamlined_communication.serializers import HolidaySerializer
from juloserver.streamlined_communication.utils import delete_audio_obj


class StreamlinedVoiceMessageForm(forms.ModelForm):
    class Meta(object):
        model = StreamlinedVoiceMessage
        fields = ('title', 'audio_file')


class StreamlinedVoiceMessageAdmin(ModelAdmin):
    form = StreamlinedVoiceMessageForm
    actions = ['custom_delete_selected']
    list_display = (
        'title',
        'audio_file_player',
    )

    def custom_delete_selected(self, request, queryset):
        for obj in queryset:
            delete_audio_obj(obj)
            obj.delete()
        self.message_user(request, ("Successfully deleted %d audio files.") % queryset.count())

    custom_delete_selected.short_description = "Delete selected items"

    def delete_model(self, request, obj):
        delete_audio_obj(obj)
        super(StreamlinedVoiceMessageAdmin, self).delete_model(request, obj)

    def get_actions(self, request):
        actions = super(StreamlinedVoiceMessageAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions


class PnActionAdmin(admin.ModelAdmin):
    list_display = ('id', 'streamlined_communication', 'order', 'title', 'action', 'target')


class HolidayForm(forms.ModelForm):
    class Meta(object):
        model = Holiday
        fields = ('holiday_date', 'is_annual', 'is_religious_holiday')


class HolidayImportForm(forms.Form):
    csv_file = forms.FileField()


class HolidayAdmin(admin.ModelAdmin):
    list_filter = ("is_annual", "is_religious_holiday")

    form = HolidayForm
    list_display = ("id", "holiday_date", "is_annual", "is_religious_holiday")

    change_list_template = "custom_admin/upload_with_add_admin_toolbar.html"

    def import_csv(self, request):
        if request.method == 'POST':
            csv_file = request.FILES['csv_file']
            if not csv_file:
                self.message_user(request, 'Fail to read csv file', level='error')
                return redirect('..')

            csv_data = csv.DictReader(codecs.iterdecode(csv_file, 'utf-8'))
            serializer = HolidaySerializer(csv_data, many=True)
            for row in serializer.data:
                Holiday.objects.update_or_create(
                    holiday_date=row['holiday_date'],
                    defaults={'is_annual': row['is_annual']}
                )

            self.message_user(request, 'Your csv file has been imported.')
            return redirect('..')

        form = HolidayImportForm()
        payload = {
            'data_table': {
                'property': ['holiday_date', 'is_annual'],
                'data': ['datetime (YYYY-MM-DD)', 'boolean (FALSE/TRUE)']
            },
            'form': form
        }
        return render(
            request, 'custom_admin/upload_config_form.html', payload
        )

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls


class TelcoServiceProviderModelForm(forms.ModelForm):
    class Meta:
        model = SmsTspVendorConfig
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        telco_code = cleaned_data.get('telco_code')

        if telco_code:
            for item in telco_code:
                if not item.isdigit():
                    raise forms.ValidationError('Invalid telco code')
        return cleaned_data


class TelcoServiceProviderAdmin(admin.ModelAdmin):
    form = TelcoServiceProviderModelForm
    list_display = ('id', 'provider_name', 'telco_code')

    def has_add_permission(self, request, obj=None):
        return False


class SmsTspVendorConfigModelForm(forms.ModelForm):
    class Meta:
        model = SmsTspVendorConfig
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        primary = cleaned_data.get('primary')
        backup = cleaned_data.get('backup')

        if primary == backup:
            raise forms.ValidationError('Primary and backup SMS vendor must not be same.')
        return cleaned_data


class SmsTspVendorConfigAdmin(admin.ModelAdmin):
    form = SmsTspVendorConfigModelForm
    list_display = ('id', 'tsp', 'primary', 'backup', 'is_otp')


class AppDeepLinkModelForm(forms.ModelForm):
    class Meta:
        model = AppDeepLink
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        label = cleaned_data.get('label')
        deeplink = cleaned_data.get('deeplink')

        if AppDeepLink.objects.filter(label=label).exists():
            raise forms.ValidationError('Label already exist.')

        if AppDeepLink.objects.filter(deeplink=deeplink).exists():
            raise forms.ValidationError('Deeplink already exist.')

        return cleaned_data


class AppDeepLinkAdmin(admin.ModelAdmin):
    form = AppDeepLinkModelForm
    list_display = ('deeplink', 'label')


class NeoBannerCardModelForm(forms.ModelForm):
    BADGE_COLOR_CHOICES_WITH_DEFAULT = [
        ('', 'DEFAULT'),
    ] + NeoBannerCard.BADGE_COLOR_CHOICES

    badge_color = forms.ChoiceField(
        choices=BADGE_COLOR_CHOICES_WITH_DEFAULT,
        widget=forms.RadioSelect,
        required=False,
    )

    class Meta:
        model = NeoBannerCard
        fields = [
            'is_active',
            'product',
            'statuses',
            'template_card',
            'top_image',
            'top_title',
            'top_message',
            'badge_icon',
            'badge_color',
            'button_text',
            'button_action',
            'button_action_type',
            'extended_image',
            'extended_title',
            'extended_button_text',
            'extended_button_action',
            'top_info_icon',
            'top_info_title',
            'top_info_message',
        ]

    def is_valid_image_extension(self, filename):
        valid_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']
        ext = os.path.splitext(filename)[-1].lower()
        return ext in valid_extensions

    def clean(self):
        cleaned_data = super().clean()

        fields_to_check = [
            'product',
            'statuses',
            'template_card',
            'top_image',
            'top_title',
            'top_message',
            'badge_icon',
            'badge_color',
            'button_text',
            'button_action',
            'button_action_type',
            'extended_image',
            'extended_title',
            'extended_message',
            'extended_button_text',
            'extended_button_action',
            'top_info_icon',
            'top_info_title',
            'top_info_message',
        ]

        for field_name in fields_to_check:
            field_value = cleaned_data.get(field_name)
            if field_value == '':
                cleaned_data[field_name] = None

        mandatory_fields_to_check = [
            'product',
            'statuses',
            'template_card',
            'top_image',
            'top_title',
            'top_message',
        ]

        for field_name in mandatory_fields_to_check:
            field_value = cleaned_data.get(field_name)
            if not field_value:
                raise forms.ValidationError(f"'{field_name}' is mandatory for Neo Banner")

        image_fields_to_check = [
            'top_image',
            'badge_icon',
            'extended_image',
            'top_info_icon',
        ]

        for field_name in image_fields_to_check:
            field_value = cleaned_data.get(field_name)
            if field_value and not self.is_valid_image_extension(field_value):
                raise forms.ValidationError(f"Invalid image extension for field '{field_name}'")

        if cleaned_data.get('template_card') == 'B_BUTTON':
            button_fields_to_check = [
                'button_text',
            ]

            for field_name in button_fields_to_check:
                field_value = cleaned_data.get(field_name)
                if not field_value:
                    raise forms.ValidationError(f"'{field_name}' should not be empty for B_BUTTON template")

        return cleaned_data

    def clean_badge_color(self):
        badge_color = self.cleaned_data.get('badge_color')
        return None if badge_color == '' else badge_color


class NeoBannerCardAdmin(admin.ModelAdmin):
    form = NeoBannerCardModelForm
    list_display = (
        'id',
        'is_active',
        'product',
        'statuses',
        'template_card',
        'top_image',
        'top_title',
        'top_message',
        'badge_icon',
        'badge_color',
        'button_text',
        'button_action',
        'button_action_type',
        'extended_image',
        'extended_title',
        'extended_button_text',
        'extended_button_action',
        'top_info_icon',
        'top_info_title',
        'top_info_message',
    )


class EmailHistoryAdminSerializer(serializers.Serializer):
    me_email_id = serializers.CharField(label='ME Email ID', required=True)
    status = serializers.CharField(label='Status', required=True)
    campaign_id = serializers.CharField(label='Campaign ID', required=True)
    template_code = serializers.CharField(label='Template Code', required=True)
    to_email = serializers.CharField(label='To Email', required=True)
    application_id = serializers.CharField(
        label='Application ID', required=False, allow_blank=True, allow_null=True
    )
    customer_id = serializers.CharField(
        label='Customer ID', required=False, allow_blank=True, allow_null=True
    )

    def validate(self, data):
        if not data.get('application_id') and not data.get('customer_id'):
            raise serializers.ValidationError(
                "Either application_id or customer_id must be provided."
            )
        return data


class EmailHistoryAdmin(JuloModelAdmin):
    """
    This is a Django Admin page made for reconcile ME data.
    Some of the functionalities have been suppressed to avoid unwanted interaction.
    """

    change_list_template = 'custom_admin/email_history/status_upload_csv.html'

    import_csv_data_table = {
        'property': (
            'me_email_id',
            'status',
            'campaign_id',
            'template_code',
            'to_email',
            'application_id',
            'customer_id',
        ),
        'data': (
            'Text',
            'Text',
            'Text',
            'Text',
            'Text',
            'Text',
            'Text',
        ),
    }

    def get_queryset(self, request):
        return self.model.objects.none()

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def change_view(self, request, object_id, form_url='', extra_context=None):
        if 'from_csv_upload' not in request.GET:
            self.message_user(
                request, 'Not allowed to edit this data directly.', level=messages.ERROR
            )
            return redirect('admin:julo_emailhistory_changelist')
        return super().change_view(request, object_id, form_url, extra_context)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}

        extra_context['error_csv_exists'] = False
        redis_client = get_redis_client()
        if redis_client.get('emailhistory_error_csv'):
            extra_context['error_csv_exists'] = True
        return super(EmailHistoryAdmin, self).changelist_view(request, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            url('me-status-update/', self.import_csv, name='julo_emailhistory_uploadcsv'),
            url('download-errors/', self.download_errors, name='julo_emailhistory_downloaderrors'),
        ]
        return my_urls + urls

    def import_csv(self, request):
        if request.method == 'POST':
            form = ImportCsvForm(request.POST, request.FILES)
            if form.is_valid():
                file = request.FILES['csv_file']
                if (
                    file.name.endswith('.xls')
                    or file.name.endswith('.xlsx')
                    or file.name.endswith('.csv')
                ):
                    try:
                        data = (
                            pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
                        )
                        success_count, error_count, errors = self.process_upload_data(data)

                        if error_count > 0:
                            try:
                                with tempfile.NamedTemporaryFile(
                                    delete=False, mode='w', newline='', suffix='.csv'
                                ) as temp_file:
                                    errors.to_csv(temp_file, index=False)
                                    temp_file.flush()

                                with open(temp_file.name, 'rb') as temp_file_binary:
                                    error_file = BytesIO(temp_file_binary.read())

                                os.remove(temp_file.name)
                                error_csv_value = base64.b64encode(error_file.getvalue()).decode(
                                    'utf-8'
                                )
                                redis_client = get_redis_client()
                                redis_client.set('emailhistory_error_csv', error_csv_value)
                                self.message_user(
                                    request,
                                    f'Processed with errors. Success: {success_count}, '
                                    f'Failed: {error_count}.',
                                    level=messages.WARNING,
                                )
                            except Exception as e:
                                self.message_user(
                                    request,
                                    f'Error generating error CSV: {str(e)}',
                                    level=messages.ERROR,
                                )
                            return redirect('..')

                        self.message_user(
                            request,
                            f'{success_count} records processed successfully!',
                            level=messages.SUCCESS,
                        )
                    except Exception as e:
                        self.message_user(
                            request, f'Error processing file: {str(e)}', level=messages.ERROR
                        )
                else:
                    self.message_user(request, 'Invalid file format.', level=messages.ERROR)
            return redirect('..')
        else:
            form = ImportCsvForm()
            payload = {'data_table': self.import_csv_data_table, 'form': form}
            return render(request, 'custom_admin/upload_config_form.html', payload)

    def process_upload_data(self, data):
        success_count = 0
        error_count = 0
        errors = []
        for index, row in data.iterrows():
            row_dict = row.to_dict()
            serializer = EmailHistoryAdminSerializer(data=row_dict)
            if not serializer.is_valid():
                row_dict['Error Reason'] = f"Validation errors: {serializer.errors}."
                errors.append(row_dict)
                error_count += 1
                continue

            try:
                if row['customer_id'] != '':
                    email_history = EmailHistory.objects.get(
                        customer_id=row['customer_id'],
                        template_code=row['template_code'],
                        to_email=row['to_email'],
                        campaign_id=row['campaign_id'],
                    )
                else:
                    email_history = EmailHistory.objects.get(
                        application_id=row['application_id'],
                        template_code=row['template_code'],
                        to_email=row['to_email'],
                        campaign_id=row['campaign_id'],
                    )

                moengage_stream_status_map = EmailStatusMapping['MoEngageStream']
                moengage_status = moengage_stream_status_map.get(row['status'], 'unknown')
                current_status = email_history.status
                processed_status = email_status_prioritization(current_status, moengage_status)
                email_history.status = processed_status
                email_history.save()
                success_count += 1
            except EmailHistory.MultipleObjectsReturned:
                row_dict['Error Reason'] = f'Multiple records found in database.'
                error_count += 1
                errors.append(row_dict)
            except EmailHistory.DoesNotExist:
                row_dict['Error Reason'] = f'Record does not exist in the database.'
                error_count += 1
                errors.append(row_dict)
            except Exception as e:
                row_dict['Error Reason'] = f'Unhandled exception. Error details: {str(e)}.'
                error_count += 1
                errors.append(row_dict)

        data_frame_columns = [
            'me_email_id',
            'status',
            'campaign_id',
            'template_code',
            'to_email',
            'application_id',
            'customer_id',
            'Error Reason',
        ]

        error_data = None
        if errors:
            error_data = pd.DataFrame(errors, columns=data_frame_columns)
        return success_count, error_count, error_data

    def download_errors(self, request):
        redis_client = get_redis_client()
        error_csv = redis_client.get('emailhistory_error_csv')
        if error_csv:
            response = HttpResponse(base64.b64decode(error_csv), content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="error_report.csv"'
            redis_client.delete_key('emailhistory_error_csv')
            return response
        else:
            self.message_user(request, 'No error file available.', level=messages.ERROR)
            return redirect('admin:julo_emailhistory_changelist')


class StreamlinedCampaignDepartmentModelForm(forms.ModelForm):
    class Meta:
        model = StreamlinedCampaignDepartment
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        department_code = cleaned_data.get('department_code')
        name = cleaned_data.get('name')

        if StreamlinedCampaignDepartment.objects.filter(name=name).exists():
            raise forms.ValidationError('Department name already exist.')

        if StreamlinedCampaignDepartment.objects.filter(department_code=department_code).exists():
            raise forms.ValidationError('Department code already exist.')

        return cleaned_data


class StreamlinedCampaignDepartmentAdmin(admin.ModelAdmin):
    form = StreamlinedCampaignDepartmentModelForm
    list_display = ('id', 'name', 'department_code')


class StreamlinedCampaignSquadAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')


admin.site.register(StreamlinedVoiceMessage, StreamlinedVoiceMessageAdmin)
admin.site.register(PnAction, PnActionAdmin)
admin.site.register(Holiday, HolidayAdmin)
admin.site.register(TelcoServiceProvider, TelcoServiceProviderAdmin)
admin.site.register(SmsTspVendorConfig, SmsTspVendorConfigAdmin)
admin.site.register(AppDeepLink, AppDeepLinkAdmin)
admin.site.register(NeoBannerCard, NeoBannerCardAdmin)
admin.site.register(EmailHistory, EmailHistoryAdmin)
admin.site.register(StreamlinedCampaignDepartment, StreamlinedCampaignDepartmentAdmin)
admin.site.register(StreamlinedCampaignSquad, StreamlinedCampaignSquadAdmin)
