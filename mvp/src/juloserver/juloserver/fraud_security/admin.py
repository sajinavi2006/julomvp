import csv
import codecs
from django.shortcuts import render, redirect
from django.db import transaction
from django.conf.urls import url
from django.contrib import admin
from django import forms

from rest_framework.exceptions import ValidationError

from juloserver.account.models import Account
from juloserver.antifraud.services.pii_vault import (
    detokenize_pii_antifraud_data,
    construct_query_pii_antifraud_data,
    get_or_create_object_pii,
)
from juloserver.pii_vault.constants import PiiSource
from juloserver.fraud_security.models import (
    FraudBlacklistedCompany,
    FraudBlacklistedPostalCode,
    FraudBlacklistedGeohash5,
    FraudAppealTemporaryBlock,
    FraudBlacklistedNIK,
)
from juloserver.fraud_security.serializers import (
    FraudBlacklistedCompanyAdminSerializer,
    FraudAppealTemporaryBlockAdminSerializer,
)
from juloserver.fraud_security.models import FraudBlacklistedASN
from juloserver.julo.admin import CsvImportForm, JuloModelAdmin


class FraudBlacklistedCompanyAdminForm(forms.ModelForm):
    company_name = forms.CharField(label='Company Name')

    class Meta(object):
        model = FraudBlacklistedCompany
        fields = ('company_name',)

    def clean_company_name(self):
        company_name = self.cleaned_data['company_name']
        if (
            FraudBlacklistedCompany.objects.filter(
                company_name__iexact=company_name,
            ).exclude(id=self.instance.id).exists()
        ):
            raise forms.ValidationError('Company name has been registered.')

        return company_name.strip()


class FraudAppealTemporaryBlockAdminForm(forms.ModelForm):
    account_id = forms.IntegerField(label='Account Id')

    class Meta(object):
        model = FraudAppealTemporaryBlock
        fields = ('account_id',)

    def clean_account_id(self):
        account_id = self.cleaned_data['account_id']
        if (
            FraudAppealTemporaryBlock.objects.filter(
                account_id=account_id,
            )
            .exclude(id=self.instance.id)
            .exists()
        ):
            raise forms.ValidationError('Account Id has been registered.')
        else:
            account = Account.objects.filter(pk=account_id).exists()
            if not account:
                raise forms.ValidationError('Account Id doesnt exist.')

        return account_id


class FraudBlacklistedCompanyAdmin(JuloModelAdmin):
    list_display = ('id', 'company_name', 'cdate', 'udate')
    search_fields = ('company_name',)
    list_display_links = ('id', 'company_name',)
    change_list_template = "custom_admin/upload_with_add_admin_toolbar.html"
    form = FraudBlacklistedCompanyAdminForm

    import_csv_data_table = {
        'property': ('company_name',),
        'data': ('Text',)
    }
    import_csv_serializer = FraudBlacklistedCompanyAdminSerializer

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls


class FraudAppealTemporaryBlockAdmin(JuloModelAdmin):
    list_display = ('id', 'account_id', 'cdate', 'udate')
    search_fields = ('account_id',)
    list_display_links = (
        'id',
        'account_id',
    )
    change_list_template = "custom_admin/upload_with_add_admin_toolbar.html"
    form = FraudAppealTemporaryBlockAdminForm

    import_csv_data_table = {'property': ('account_id',), 'data': ('Numeric',)}
    import_csv_serializer = FraudAppealTemporaryBlockAdminSerializer

    def get_urls(self):
        urls = super().get_urls()
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
                    if 'account_id' in line:
                        account_id = line['account_id']
                        account = Account.objects.filter(pk=account_id).last()
                        if account:
                            FraudAppealTemporaryBlock.objects.get_or_create(account_id=account_id)
                        else:
                            self.message_user(
                                request,
                                "Account Id : " + account_id + " doesnt exist !",
                                level="ERROR",
                            )

            except Exception as error:
                self.message_user(
                    request, "Something went wrong with file: %s" % str(error), level="ERROR"
                )
            else:
                self.message_user(request, "Your csv file has been imported")
            return redirect("..")

        form = CsvImportForm()
        payload = {
            "form": form,
            'data_table': self.import_csv_data_table,
        }
        return render(request, "custom_admin/upload_config_form.html", payload)


class FraudBlacklistedASNAdmin(JuloModelAdmin):
    change_list_template = "custom_admin/upload_with_add_admin_toolbar.html"

    list_display = (
        'id',
        'asn_data',
    )

    def get_urls(self):
        from django.conf.urls import url

        urls = super(FraudBlacklistedASNAdmin, self).get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls

    def import_csv(self, request):
        if request.method == "POST":
            with transaction.atomic():
                try:
                    csv_file = request.FILES["csv_file"]
                    new_count = 0
                    reader = csv.DictReader(codecs.iterdecode(csv_file, 'utf-8'))
                    for line in reader:
                        asn_data = line.get('asn_data')
                        if not asn_data:
                            raise ValidationError(
                                "'asn_data' cannot be empty in any of the rows in the CSV")
                        asn, created = FraudBlacklistedASN.objects.get_or_create(asn_data=asn_data)
                        if created:
                            new_count = new_count + 1
                except Exception as error:
                    self.message_user(
                        request, "Something went wrong with file: %s" % str(error), level="ERROR"
                    )
                else:
                    self.message_user(request, "CSV Imported. {} new rows added".format(new_count))
            return redirect("..")
        form = CsvImportForm()
        payload = {
            'data_table': {
                'property': ['asn_data'],
                'data': ['ASN data to be blacklisted']
            },
            'form': form
        }
        return render(request, "custom_admin/upload_config_form.html", payload)


class FraudBlacklistedPostalCodeAdmin(JuloModelAdmin):
    change_list_template = "custom_admin/upload_with_add_admin_toolbar.html"

    list_display = (
        'id',
        'postal_code',
    )

    def get_urls(self):
        from django.conf.urls import url

        urls = super(FraudBlacklistedPostalCodeAdmin, self).get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls

    def import_csv(self, request):
        if request.method == "POST":
            with transaction.atomic():
                try:
                    csv_file = request.FILES["csv_file"]
                    new_count = 0
                    reader = csv.DictReader(codecs.iterdecode(csv_file, 'utf-8'))
                    for line in reader:
                        postal_code = line.get('postal_code')
                        if not postal_code:
                            raise ValidationError(
                                "'postal_code' cannot be empty in any of the rows in the CSV")
                        block_postal_code_obj, created = (
                            FraudBlacklistedPostalCode.objects.get_or_create(
                                postal_code=postal_code
                            )
                        )
                        if created:
                            new_count = new_count + 1
                except Exception as error:
                    self.message_user(
                        request, "Something went wrong with file: %s" % str(error), level="ERROR"
                    )
                else:
                    self.message_user(request, "CSV Imported. {} new rows added".format(new_count))
            return redirect("..")
        form = CsvImportForm()
        payload = {
            'data_table': {
                'property': ['postal_code'],
                'data': ['postal code data to be blacklisted']
            },
            'form': form
        }
        return render(request, "custom_admin/upload_config_form.html", payload)


class FraudBlacklistedGeohash5Admin(JuloModelAdmin):
    list_display = ('id', 'geohash5')
    change_list_template = "custom_admin/upload_with_add_admin_toolbar.html"

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls

    def import_csv(self, request):
        if request.method == "POST":
            with transaction.atomic():
                try:
                    csv_file = request.FILES["csv_file"]
                    new_count = 0
                    reader = csv.DictReader(codecs.iterdecode(csv_file, 'utf-8'))
                    for line in reader:
                        geohash5 = line.get('geohash5')
                        if not geohash5:
                            raise ValidationError(
                                "'geohash5' cannot be empty in any of the rows in the CSV")
                        goehash5, created = FraudBlacklistedGeohash5.objects.get_or_create(
                            geohash5=geohash5
                        )
                        if created:
                            new_count = new_count + 1
                except Exception as error:
                    self.message_user(
                        request, "Something went wrong with file: %s" % str(error), level="ERROR"
                    )
                else:
                    self.message_user(request, "CSV Imported. {} new rows added".format(new_count))
            return redirect("..")
        form = CsvImportForm()
        payload = {
            'data_table': {
                'property': ['geohash5'],
                'data': ['Geohash 5 data to be blacklisted']
            },
            'form': form
        }
        return render(request, "custom_admin/upload_config_form.html", payload)


class FraudBlacklistedNIKAdmin(JuloModelAdmin):
    change_list_template = "custom_admin/upload_with_add_admin_toolbar.html"
    search_fields = ('nik',)

    list_display = (
        'id',
        'nik_detokenized',
    )

    def nik_detokenized(self, obj):
        # Show nik that sourced from object detokenizated
        detokenized_nik = detokenize_pii_antifraud_data(PiiSource.FRAUD_BLACKLISTED_NIK, [obj])[0]
        return detokenized_nik.nik

    # Label nik_detokenized with the name NIK
    nik_detokenized.short_description = 'NIK'

    def get_search_results(self, request, queryset, search_term):
        """
        override the search process to perform a search based on a modified nik filter
        by including its tokenized value.
        """
        use_distinct = False
        if not search_term:
            return queryset, use_distinct
        filter_pii, filter_without_pii = construct_query_pii_antifraud_data(
            FraudBlacklistedNIK, {'nik': search_term}
        )
        results = FraudBlacklistedNIK.objects.filter(*filter_pii, **filter_without_pii)
        return results, use_distinct

    def get_urls(self):
        from django.conf.urls import url

        urls = super(FraudBlacklistedNIKAdmin, self).get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
        ]
        return my_urls + urls

    def import_csv(self, request):
        if request.method == "POST":
            with transaction.atomic():
                try:
                    csv_file = request.FILES["csv_file"]
                    new_count = 0
                    reader = csv.DictReader(codecs.iterdecode(csv_file, 'utf-8'))
                    for line in reader:
                        nik = line.get('nik')
                        if not nik:
                            raise ValidationError(
                                "'nik' cannot be empty in any of the rows in the CSV")
                        if not nik.isdigit() or len(nik) != 16:
                            raise Exception("'nik' has to be 16 numeric digits ({})".format(nik))
                        nik_obj, created = get_or_create_object_pii(
                            FraudBlacklistedNIK, {'nik': nik}
                        )
                        if created:
                            new_count = new_count + 1
                except Exception as error:
                    self.message_user(
                        request, "Something went wrong with file: %s" % str(error), level="ERROR"
                    )
                else:
                    self.message_user(request, "CSV Imported. {} new rows added".format(new_count))
            return redirect("..")
        form = CsvImportForm()
        payload = {
            'data_table': {
                'property': ['nik'],
                'data': ['NIK data to be blacklisted (max 16 char)']
            },
            'form': form
        }
        return render(request, "custom_admin/upload_config_form.html", payload)


admin.site.register(FraudBlacklistedCompany, FraudBlacklistedCompanyAdmin)
admin.site.register(FraudBlacklistedASN, FraudBlacklistedASNAdmin)
admin.site.register(FraudBlacklistedPostalCode, FraudBlacklistedPostalCodeAdmin)
admin.site.register(FraudBlacklistedGeohash5, FraudBlacklistedGeohash5Admin)
admin.site.register(FraudAppealTemporaryBlock, FraudAppealTemporaryBlockAdmin)
admin.site.register(FraudBlacklistedNIK, FraudBlacklistedNIKAdmin)
