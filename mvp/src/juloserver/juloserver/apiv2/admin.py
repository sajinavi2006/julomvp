import logging
from builtins import object, str
from urllib.parse import urlparse

from django import forms
from django.conf import settings
from django.contrib import admin
from django.utils.safestring import mark_safe
from future import standard_library

from juloserver.apiv2.models import PublicFile
from juloserver.julo.utils import (
    construct_public_remote_filepath,
    delete_public_file_from_oss,
    get_oss_public_url,
    put_public_file_to_oss,
)

standard_library.install_aliases()


logger = logging.getLogger(__name__)


class PublicFileForm(forms.ModelForm):
    image = forms.ImageField(required=True)
    image_preview = forms.ImageField()

    class Meta(object):
        model = PublicFile
        fields = ('name', 'image', 'file_url')

    def save(self, commit=True):
        image_inst = super(PublicFileForm, self).save(commit=False)
        image = self.cleaned_data['image']
        bucket_name = settings.OSS_PUBLIC_BUCKET
        remote_path = construct_public_remote_filepath(image)
        put_public_file_to_oss(bucket_name, image, remote_path)
        public_url = get_oss_public_url(bucket_name, remote_path)
        image_inst.file_url = public_url
        return image_inst


class PublicFileAdmin(admin.ModelAdmin):
    form = PublicFileForm
    list_display = ('name', 'file_url')
    readonly_fields = ('file_url', 'image_preview')
    search_fields = ('name',)
    actions = ['delete_selected_files']

    def delete_cloud_data(self, obj):
        """
        Delete the given key from the cloud service(oss)
        """
        bucket_name = settings.OSS_PUBLIC_BUCKET
        try:
            if obj.file_url:
                url = urlparse(obj.file_url)
                file_key = url.path
                delete_public_file_from_oss(bucket_name, file_key[1:])
        except Exception as e:
            logger.error(str(e))

    def delete_model(self, request, obj):
        self.delete_cloud_data(obj)
        obj.delete()

    def delete_selected_files(self, request, queryset):
        for obj in queryset:
            self.delete_cloud_data(obj)
            obj.delete()

    def get_actions(self, request):
        actions = super(PublicFileAdmin, self).get_actions(request)
        if 'delete_selected' in actions:
            del actions['delete_selected']
        return actions

    def image_preview(self, obj):
        if obj.file_url:
            image_tag = (
                '<img style="object-fit:contain;" '
                'src="%s" width="250" height="250" />' % obj.file_url
            )
            return mark_safe(image_tag)
        return None

    class Meta(object):
        model = PublicFile


admin.site.register(PublicFile, PublicFileAdmin)
