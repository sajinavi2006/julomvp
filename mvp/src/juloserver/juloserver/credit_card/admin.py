import csv
import os

from django.contrib import admin
from django.conf.urls import url
from django.shortcuts import (
    redirect,
    render,
)
from django import forms
from django.utils.safestring import mark_safe
from django.conf import settings

from juloserver.julo.admin import (
    JuloModelAdmin,
    CsvImportForm,
)
from juloserver.julo.models import Image
from juloserver.julo.utils import upload_file_to_oss

from juloserver.portal.core import functions

from juloserver.credit_card.models import (
    CreditCardMobileContentSetting,
    JuloCardWhitelistUser,
    JuloCardBanner,
)


class CreditCardAdmin(JuloModelAdmin):

    list_display = ('content_name', 'description', 'content', 'is_active')

    def has_delete_permission(self, request, obj=None):
        return False


class JuloCardWhitelistForm(forms.ModelForm):

    class Meta(object):
        model = JuloCardWhitelistUser
        fields = ('application',)


class JuloCardWhitelistUserAdmin(JuloModelAdmin):
    form = JuloCardWhitelistForm
    list_display = (
        "id",
        "application_id",
    )
    readonly_fields = ('application',)

    change_list_template = "custom_admin/upload_btn_change_list.html"

    def get_urls(self):
        urls = super(JuloCardWhitelistUserAdmin, self).get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls

    def import_csv(self, request):
        if request.method == "POST":
            message = "Your csv file has been imported"
            try:
                csv_file = request.FILES["csv_file"]
                reader = csv.DictReader(csv_file.read().decode().splitlines())
                application_ids = [int(row['application_id']) for row in reader]
                application_ids_already_exists = JuloCardWhitelistUser.objects.filter(
                    application_id__in=application_ids
                ).values_list('application_id', flat=True)
                application_ids_filtered = list(
                    filter(
                        lambda application_id: application_id not in application_ids_already_exists,
                        application_ids)
                )
                julo_card_whitelist_user_list = []
                for app_id in application_ids_filtered:
                    julo_card_whitelist_user_list.append(JuloCardWhitelistUser(
                        application_id=int(app_id)
                    ))
                JuloCardWhitelistUser.objects.bulk_create(julo_card_whitelist_user_list,
                                                          batch_size=25)

                if application_ids_already_exists:
                    message = message + ', application ids {} already exists'.format(
                        application_ids_already_exists
                    )
            except Exception as e:
                self.message_user(request, "Something went wrong : %s" % str(e),
                                  level="ERROR")
            else:
                self.message_user(request, message)
            return redirect("..")

        form = CsvImportForm()
        payload = {"form": form}
        return render(
            request, "custom_admin/upload_config_form.html", payload
        )


class JuloCardBannerForm(forms.ModelForm):
    image = forms.ImageField(required=False)
    display_order = forms.IntegerField(required=False)

    class Meta(object):
        model = JuloCardBanner
        exclude = ('image',)


class JuloCardBannerAdmin(JuloModelAdmin):
    form = JuloCardBannerForm
    list_display = (
        'id',
        'name',
        'banner_type',
        'is_active',
        'display_order'
    )
    readonly_fields = ('id', 'preview_image',)
    search_fields = ('name',)
    list_filter = ('banner_type',)
    ordering = ('id', 'display_order',)

    def save_model(self, request, obj, form, change):
        super(JuloCardBannerAdmin, self).save_model(request, obj, form, change)

        if request.FILES and request.FILES['image']:
            banner_image = request.FILES['image']

            _, file_extension = os.path.splitext(banner_image.name)

            remote_path = 'julo_card_banner_{}/image{}'.format(obj.pk, file_extension)

            image = Image()
            image.image_source = obj.pk
            image.image_type = 'julo_card_banner_image'
            image.url = remote_path
            image.save()
            obj.update_safely(image=image)

            file = functions.upload_handle_media(banner_image, "julo_card_banner/image")
            if file:
                upload_file_to_oss(
                    settings.OSS_MEDIA_BUCKET,
                    file['file_name'],
                    remote_path
                )

    def preview_image(self, obj):
        if obj.image:
            return mark_safe('<img src="{url}" width="{width}" />'.format(
                url=obj.image.image_url,
                width=300
            )
            )
        return None


admin.site.register(CreditCardMobileContentSetting, CreditCardAdmin)
admin.site.register(JuloCardWhitelistUser, JuloCardWhitelistUserAdmin)
admin.site.register(JuloCardBanner, JuloCardBannerAdmin)
