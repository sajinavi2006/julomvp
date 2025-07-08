from django import forms

from django.conf.urls import url
from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils.safestring import mark_safe

from juloserver.education.constants import UploadStatusMessage
from juloserver.education.models import School
from juloserver.education.serializers import SchoolUploadSerializer
from juloserver.sdk.services import xls_to_dict


class CsvImportForm(forms.Form):
    xls_file = forms.FileField()


class SchoolForm(forms.ModelForm):
    class Meta:
        model = School
        exclude = ('id',)

    def full_clean(self):
        super(SchoolForm, self).full_clean()
        try:
            self.instance.validate_unique()
        except forms.ValidationError as e:
            self._update_errors(e)


class SchoolAdmin(ModelAdmin):
    ordering = ('-id',)
    search_fields = ('id', 'name', 'city')
    list_display = ('id', 'name', 'city', 'is_active', 'is_verified')
    change_list_template = "custom_admin/upload_add_btn_change_list.html"
    form = SchoolForm

    def get_urls(self):
        urls = super(SchoolAdmin, self).get_urls()
        my_urls = [
            url('add-file/', self.import_csv, name='education_upload_school'),
        ]
        return my_urls + urls

    def import_csv(self, request):
        def _return_form():
            context = self.admin_site.each_context(request)
            context['opts'] = self.model._meta
            context['form'] = CsvImportForm
            context['title'] = "Upload School"
            context['add'] = True
            return TemplateResponse(request, 'custom_admin/full_upload_form.html', context)

        if request.method == "POST":
            if 'xls_file' not in request.FILES:
                level, message = UploadStatusMessage.FILE_NOT_FOUND
                self.message_user(request, message, level=level)
                return _return_form()

            try:
                xls_file = request.FILES["xls_file"]
                school_data = []
                school_success = 0
                school_xls_data = xls_to_dict(xls_file)
                for _, sheet_data in enumerate(school_xls_data):
                    serializer = SchoolUploadSerializer(data=school_xls_data[sheet_data], many=True)
                    if serializer.is_valid(raise_exception=True):
                        for data in serializer.data:
                            data['is_verified'] = True
                            school_data.append(School(**data))
                            school_success += 1

                if school_data:
                    School.objects.bulk_create(school_data, batch_size=100)

            except Exception as error:
                self.message_user(request, "Something went wrong: %s" % str(error), level="ERROR")
            else:
                level, message = UploadStatusMessage.SUCCESS
                if school_success == 0:
                    level, message = UploadStatusMessage.WARNING

                self.message_user(request, mark_safe(message), level=level)
                return HttpResponseRedirect(reverse('admin:education_school_changelist'))

        return _return_form()


admin.site.register(School, SchoolAdmin)
