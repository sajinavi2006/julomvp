from builtins import str

from django.conf.urls import url
from django.contrib import admin
from django.shortcuts import redirect, render

from juloserver.entry_limit.models import EntryLevelLimitConfiguration as EntryLimit
from juloserver.julo.admin import CsvImportForm

from .services import EntryLevelFileUpload


class EntryLevelLimitConfigurationAdmin(admin.ModelAdmin):
    readonly_fields = ('version',)
    list_exclude = ('cdate', 'udate')
    change_list_template = "custom_admin/upload_btn_change_list.html"

    def get_urls(self):
        urls = super(EntryLevelLimitConfigurationAdmin, self).get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls

    @property
    def list_display(self):
        return [f.name for f in EntryLimit._meta.fields if f.name not in self.list_exclude]

    def import_csv(self, request):
        if request.method == "POST":
            csv_file = request.FILES["csv_file"]
            csv_data = csv_file.read().decode().splitlines()
            try:
                EntryLevelFileUpload().process(csv_data)
            except Exception as error:
                self.message_user(
                    request, "Something went wrong with file: %s" % str(error), level="ERROR"
                )
            else:
                self.message_user(request, "Your csv file has been imported")
            return redirect("..")
        form = CsvImportForm()
        payload = {"form": form}
        return render(request, "custom_admin/upload_config_form.html", payload)


admin.site.register(EntryLimit, EntryLevelLimitConfigurationAdmin)
