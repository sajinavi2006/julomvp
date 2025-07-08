import csv
import io
import logging

from django.contrib import admin
from django.conf.urls import url
from django.shortcuts import (
    redirect,
    render,
)
from django import forms

from juloserver.julo.admin import (
    JuloModelAdmin,
    CsvImportForm,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo_savings.models import (
    JuloSavingsWhitelistApplication,
    JuloSavingsMobileContentSetting,
)

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class JuloSavingsWhitelistForm(forms.ModelForm):
    class Meta(object):
        model = JuloSavingsWhitelistApplication
        fields = ('application',)


class JuloSavingsWhitelistAdmin(JuloModelAdmin):
    form = JuloSavingsWhitelistForm
    list_display = (
        "id",
        "application_id",
    )
    readonly_fields = ('application',)

    change_list_template = "custom_admin/upload_btn_change_list.html"

    def get_urls(self):
        urls = super(JuloSavingsWhitelistAdmin, self).get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls

    def import_csv(self, request):
        if request.method == "POST":
            message = "Your csv file has been imported"
            try:
                csv_file = request.FILES["csv_file"]
                # reader = csv.DictReader(csv_file.read().decode().splitlines())

                file = csv_file.read().decode('utf-8')
                # Parse as CSV object
                reader = csv.DictReader(io.StringIO(file))
                application_ids = [int(row['application_id']) for row in reader]
                application_ids_already_exists = JuloSavingsWhitelistApplication.objects.filter(
                    application_id__in=application_ids
                ).values_list('application_id', flat=True)
                application_ids_filtered = list(
                    filter(
                        lambda application_id: application_id not in application_ids_already_exists,
                        application_ids,
                    )
                )
                julo_savings_whitelist_user_list = []
                for app_id in application_ids_filtered:
                    julo_savings_whitelist_user_list.append(
                        JuloSavingsWhitelistApplication(application_id=int(app_id))
                    )
                JuloSavingsWhitelistApplication.objects.bulk_create(
                    julo_savings_whitelist_user_list, batch_size=25
                )

                if application_ids_already_exists:
                    message = message + ', application ids {} already exists'.format(
                        application_ids_already_exists
                    )
            except Exception as e:
                logger.exception(e)
                sentry_client.captureException()
                self.message_user(request, "Something went wrong : %s" % str(e), level="ERROR")

            else:
                self.message_user(request, message)
            redirect_url = '/xgdfat82892ddn/julo_savings/julosavingswhitelistapplication/add-file/'
            return redirect(redirect_url)

        form = CsvImportForm()
        payload = {"form": form}
        return render(request, "custom_admin/upload_config_form.html", payload)


admin.site.register(JuloSavingsWhitelistApplication, JuloSavingsWhitelistAdmin)


class JuloSavingsAdmin(JuloModelAdmin):

    list_display = ('content_name', 'description', 'content', 'parameters', 'is_active')


admin.site.register(JuloSavingsMobileContentSetting, JuloSavingsAdmin)
