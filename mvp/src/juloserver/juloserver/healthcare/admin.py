from django import forms

from django.conf.urls import url
from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils.safestring import mark_safe

from juloserver.healthcare.constants import UploadStatusMessage
from juloserver.healthcare.models import HealthcarePlatform
from juloserver.healthcare.serializers import HealthcarePlatformUploadSerializer
from juloserver.sdk.services import xls_to_dict


class CsvImportForm(forms.Form):
    xls_file = forms.FileField()


class HealthcarePlatformForm(forms.ModelForm):
    class Meta:
        model = HealthcarePlatform
        exclude = ('id',)

    def full_clean(self):
        super(HealthcarePlatformForm, self).full_clean()
        try:
            self.instance.validate_unique()
        except forms.ValidationError as e:
            self._update_errors(e)


class HealthcarePlatformAdmin(ModelAdmin):
    ordering = ('-id',)
    search_fields = ('id', 'name', 'city')
    list_display = ('id', 'name', 'city', 'is_active', 'is_verified')
    change_list_template = "custom_admin/upload_add_btn_change_list.html"
    form = HealthcarePlatformForm

    def get_urls(self):
        urls = super(HealthcarePlatformAdmin, self).get_urls()
        my_urls = [
            url('add-file/', self.import_csv, name='healthcare_platform_upload'),
        ]
        return my_urls + urls

    def import_csv(self, request):
        def _return_form():
            context = self.admin_site.each_context(request)
            context['opts'] = self.model._meta
            context['form'] = CsvImportForm
            context['title'] = "Upload HealthcarePlatform"
            context['add'] = True
            return TemplateResponse(request, 'custom_admin/full_upload_form.html', context)

        if request.method == "POST":
            if 'xls_file' not in request.FILES:
                level, message = UploadStatusMessage.FILE_NOT_FOUND
                self.message_user(request, message, level=level)
                return _return_form()

            try:
                xls_file = request.FILES["xls_file"]
                HealthcarePlatform_data = []
                HealthcarePlatform_success = 0
                HealthcarePlatform_xls_data = xls_to_dict(xls_file)
                for _, sheet_data in enumerate(HealthcarePlatform_xls_data):
                    serializer = HealthcarePlatformUploadSerializer(
                        data=HealthcarePlatform_xls_data[sheet_data], many=True
                    )
                    if serializer.is_valid(raise_exception=True):
                        for data in serializer.data:
                            data['is_verified'] = True
                            HealthcarePlatform_data.append(HealthcarePlatform(**data))
                            HealthcarePlatform_success += 1

                if HealthcarePlatform_data:
                    HealthcarePlatform.objects.bulk_create(HealthcarePlatform_data, batch_size=100)

            except Exception as error:
                self.message_user(request, "Something went wrong: %s" % str(error), level="ERROR")
            else:
                level, message = UploadStatusMessage.SUCCESS
                if HealthcarePlatform_success == 0:
                    level, message = UploadStatusMessage.WARNING

                self.message_user(request, mark_safe(message), level=level)
                return HttpResponseRedirect(
                    reverse('admin:healthcare_healthcareplatform_changelist')
                )

        return _return_form()


admin.site.register(HealthcarePlatform, HealthcarePlatformAdmin)
