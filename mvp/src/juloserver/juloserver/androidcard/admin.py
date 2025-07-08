import os

from django import forms
from django.conf import settings
from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.utils.safestring import mark_safe

from juloserver.julo.utils import upload_file_to_oss
from juloserver.julo.models import Image
from juloserver.portal.core import functions

from .models import OtherLoan
from .models import AndroidCard


class AndroidCardAdmin(ModelAdmin):
    list_display = (
        'id',
        'title',
        'message',
        'button_text',
        'action_type',
        'is_active',
        'start_date',
        'end_date',
        'is_permanent',
        'display_order'
    )
    search_fields = ('title',)
    list_filter = ('action_type',)


class OtherLoanExtendForm(forms.ModelForm):
    image = forms.ImageField(required=False)
    url = forms.CharField()
    short_description = forms.CharField()

    def __init__(self, *args, **kwargs):
        super(OtherLoanExtendForm, self).__init__(*args, **kwargs)


class OtherLoanAdmin(ModelAdmin):
    list_display = (
        'id',
        'name',
        'short_description',
        'url',
        'is_active',
    )
    readonly_fields = ('preview_image',)
    search_fields = ('name',)

    def get_form(self, request, obj=None, *args, **kwargs):
        kwargs['form'] = OtherLoanExtendForm
        return super(OtherLoanAdmin, self).get_form(request, *args, **kwargs)

    def save_model(self, request, obj, form, change):
        super(OtherLoanAdmin, self).save_model(request, obj, form, change)

        if request.FILES and request.FILES['image']:
            other_loan_image = request.FILES['image']
            _, file_extension = os.path.splitext(other_loan_image.name)

            remote_path = 'other_loan_{}/image{}'.format(obj.pk, file_extension)

            image = Image()
            image.image_source = obj.pk
            image.image_type = 'other_loan_image'
            image.url = remote_path
            image.save()

            file = functions.upload_handle_media(other_loan_image, "other_loan/image")
            if file:
                upload_file_to_oss(
                    settings.OSS_MEDIA_BUCKET,
                    file['file_name'],
                    remote_path
                )

    def preview_image(self, obj):
        return mark_safe('<img src="{url}" width="{width}" />'.format(
            url=obj.image_url,
            width=300)
        )


admin.site.register(AndroidCard, AndroidCardAdmin)
admin.site.register(OtherLoan, OtherLoanAdmin)
