import csv
import os

from rest_framework import serializers
from django import forms


class CollectionVendorAssignmentExtensionSerializer(serializers.Serializer):
    vendor_id = serializers.IntegerField(required=True)
    payment_id = serializers.IntegerField(required=False)
    account_payment_id = serializers.IntegerField(required=False)
    retain_reason = serializers.CharField(required=True)


class CollectionVendorManualTransferSerializer(serializers.Serializer):
    transfer_from_id = serializers.CharField(required=False)
    vendor_name = serializers.IntegerField(required=False)
    payment_id = serializers.IntegerField(required=False, default=0)
    account_payment_id = serializers.IntegerField(required=False, default=0)
    transfer_reason = serializers.CharField(required=False, allow_blank=True)
    save_type = serializers.CharField(required=False, allow_blank=True)
    is_julo_one = serializers.BooleanField(required=True)
    transfer_from_labels = serializers.CharField(required=False)


class VendorBulkTransferSerializer(forms.Form):
    reason = serializers.CharField()
    uploaded_file = forms.FileField()

    def clean_uploaded_file(self):
        uploaded_file = self.cleaned_data['uploaded_file']
        if not uploaded_file:
            raise forms.ValidationError('Please select a CSV file')
        file_name, file_extension = os.path.splitext(uploaded_file.name)
        if file_extension.lower() != '.csv':
            raise forms.ValidationError('Only CSV files are allowed')
        file_read = uploaded_file.read()
        decoded_file = file_read.decode().splitlines()
        data_reader = csv.DictReader(decoded_file)
        if 'application_xid' not in data_reader.fieldnames:
            raise forms.ValidationError(
                'The uploaded file has no application_xid field on header')
        if 'vendor_id' not in data_reader.fieldnames:
            raise forms.ValidationError(
                'The uploaded file has no vendor_id field on header')

        rows = list(data_reader)
        if len(rows) == 0:
            raise forms.ValidationError(
                'The uploaded file has no data or contains only the header row.')
        return file_read.decode('utf-8')
