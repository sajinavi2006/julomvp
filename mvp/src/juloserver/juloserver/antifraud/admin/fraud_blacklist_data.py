import codecs
import csv

from django import forms
from django.db import transaction
from django.shortcuts import redirect, render
from rest_framework import serializers
from django.conf.urls import url

from juloserver.antifraud.models.fraud_blacklist_data import (
    FraudBlacklistData,
)
from juloserver.julo.admin import (
    JuloModelAdmin,
    CsvImportForm,
)


class FraudBlacklistDataAdminForm(forms.ModelForm):
    class Meta:
        model = FraudBlacklistData
        fields = "__all__"


class FraudBlacklistDataAdminSerializer(serializers.ModelSerializer):
    type = serializers.ChoiceField(
        choices=[
            enum.string
            for enum in FraudBlacklistData.Type
            if enum != FraudBlacklistData.Type.UNKNOWN
        ]
    )

    class Meta:
        model = FraudBlacklistData
        fields = "__all__"

    def create(self, validated_data):
        type_str = validated_data.get("type")
        validated_data["type"] = FraudBlacklistData.Type.from_string(type_str).value
        return FraudBlacklistData.objects.create(**validated_data)


class FraudBlacklistDataAdmin(JuloModelAdmin):
    list_display = ("id", "type", "value", "cdate", "udate")
    search_fields = ("value",)
    list_display_links = ("id", "value")
    change_list_template = "custom_admin/upload_with_add_admin_toolbar.html"
    form = FraudBlacklistDataAdminForm

    import_csv_serializer = FraudBlacklistDataAdminSerializer

    def get_data_table(self):
        properties = ["type", "value"]
        enum_values = "\n- ".join(
            [
                enum.string
                for enum in FraudBlacklistData.Type
                if enum != FraudBlacklistData.Type.UNKNOWN
            ]
        )
        data_types = [
            f"string\n\nchoose one of:\n- {enum_values}",
            "string",
        ]
        return {"property": properties, "data": data_types}

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            url("add-file/", self.import_csv),
        ]
        return my_urls + urls

    def import_csv(self, request):
        if request.method == "POST":
            csv_file = request.FILES.get("csv_file")
            if not csv_file:
                self.message_user(request, "Failed to read CSV file.", level="error")
                return redirect("..")

            csv_data = csv.DictReader(codecs.iterdecode(csv_file, "utf-8"))
            try:
                with transaction.atomic():
                    serializer = self.import_csv_serializer(data=list(csv_data), many=True)
                    if serializer.is_valid(raise_exception=True):
                        serializer.save()
            except Exception as e:
                self.message_user(
                    request,
                    f"Failed to import due to an error in one or more rows: {str(e)}",
                    level="error",
                )
                return redirect("..")

            self.message_user(request, "Your CSV file has been successfully imported.")
            return redirect("..")

        if request.method == "GET":
            form = CsvImportForm()
            data_table = self.get_data_table()
            payload = {
                "form": form,
                "data_table": data_table,
            }
            return render(request, "custom_admin/upload_config_form.html", payload)
