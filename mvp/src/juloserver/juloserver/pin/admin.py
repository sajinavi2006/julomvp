import codecs
import csv

from django import forms
from django.conf.urls import url
from django.contrib import admin
from django.shortcuts import redirect, render

from juloserver.pin.models import BlacklistedFraudster
from juloserver.pin.services import (
    trigger_new_blacklisted_fraudster_move_account_status_to_440)


class CsvImportForm(forms.Form):
    csv_file = forms.FileField()


class BlacklistedFraudsterForm(forms.ModelForm):
    class Meta:
        model = BlacklistedFraudster
        fields = '__all__'

    def clean_android_id(self):
        if self.cleaned_data['android_id'] == "":
            return None
        else:
            return self.cleaned_data['android_id']

    def clean_phone_number(self):
        if self.cleaned_data['phone_number'] == "":
            return None
        else:
            return self.cleaned_data['phone_number']


class BlacklistedFraudsterAdmin(admin.ModelAdmin):
    change_list_template = "custom_admin/upload_with_add_admin_toolbar.html"
    form = BlacklistedFraudsterForm

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        trigger_new_blacklisted_fraudster_move_account_status_to_440(obj)

    def get_urls(self):
        urls = super(BlacklistedFraudsterAdmin, self).get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls

    def import_csv(self, request):
        if request.method == "POST":
            try:
                csv_file = request.FILES["csv_file"]
                reader = csv.DictReader(codecs.iterdecode(csv_file, 'utf-8'))
                for line in reader:
                    if 'android_id' in line:
                        BlacklistedFraudster.objects.get_or_create(
                            android_id=line['android_id'],
                            defaults={'blacklist_reason': line['reason']},
                        )
                    if 'phone_number' in line:
                        phone_number = line['phone_number']
                        if phone_number.startswith('62'):
                            phone_number = phone_number.replace('62', '0', 1)
                        BlacklistedFraudster.objects.get_or_create(
                            phone_number=phone_number, defaults={'blacklist_reason': line['reason']}
                        )
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


admin.site.register(BlacklistedFraudster, BlacklistedFraudsterAdmin)
