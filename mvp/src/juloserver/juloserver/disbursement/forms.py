from __future__ import unicode_literals

import csv
import io

from django.utils.translation import ugettext_lazy as _

from django import forms

from juloserver.disbursement.constants import (
    DailyDisbursementLimitWhitelistConst
)


class DailyDisbursementLimitWhitelistForm(forms.Form):
    file_field = forms.FileField(
        widget=forms.FileInput(
            attrs={
                'class': 'form-control',
            }
        ),
        label="File Upload",
        required=False,
        error_messages={'required': 'Please choose the CSV file'},
    )
    url_field = forms.URLField(
        widget=forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'URL file'}),
        label="URL path",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        file = cleaned_data.get('file_field')
        url = cleaned_data.get('url_field')

        if file and url:
            msg = 'Should choose file or URL'
            self.add_error('file_field', msg)
            self.add_error('url_field', msg)
        elif not file and not url:
            msg = 'Should filled file or URL'
            self.add_error('file_field', msg)
            self.add_error('url_field', msg)
        elif file:
            self.check_upload_file_extension(file)
            self.check_upload_file_size(file)
            self.check_upload_file_format(file)

    def check_upload_file_extension(self, file):
        if file.content_type not in DailyDisbursementLimitWhitelistConst.FILE_UPLOAD_EXTENSIONS:
            self.add_error('file_field', 'File extension should be .csv / .xls / .xlsx')

    def check_upload_file_size(self, file):
        if file.size > DailyDisbursementLimitWhitelistConst.MAX_FILE_UPLOAD_SIZE:
            self.add_error(
                'file_field',
                'File size should be <= {file_size} MB. Use URL field instead.'.format(
                    file_size=DailyDisbursementLimitWhitelistConst.MAX_FILE_UPLOAD_SIZE_IN_MB
                )
            )

    def check_upload_file_format(self, file):
        decoded_file = file.read().decode('utf-8')
        csv_io = io.StringIO(decoded_file)
        csv_reader = csv.reader(csv_io, delimiter=',')

        headers = next(csv_reader, None)
        if headers != DailyDisbursementLimitWhitelistConst.FILE_HEADERS:
            self.add_error(
                'file_field', 'File headers should be `customer_id`, `source`'
            )
            return

        for line_id, line_data in enumerate(csv_reader, start=2):
            customer_id, source = line_data[0], line_data[1]
            if not (len(customer_id) == 10 and customer_id.startswith("1")):
                self.add_error(
                    'file_field', 'Invalid `customer_id` at line {line_id}.'.format(
                        line_id=line_id
                    )
                )
                return
            if not source:
                self.add_error(
                    'file_field', 'Invalid `source` at line {line_id}.'.format(
                        line_id=line_id
                    )
                )
                self.add_error(
                    'file_field', '`source` should not be empty'
                )
                return
        file.seek(0)
