import csv
import io
from pathlib import Path
from typing import List

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.core.files.uploadedfile import InMemoryUploadedFile

from juloserver.julo.constants import CSVWhitelistFileValidatorConstant
from juloserver.julo.utils import convert_size_unit


class FileValidator:
    """
    Validate uploaded file from Django admin page, including:
        - File extension
        - File size
    """

    invalid_extension_message = _(
        "File extension %(extension)s is not allowed. "
        "Allowed extensions are: %(allowed_extensions)s."
    )

    invalid_size_message = _(
        "File size %(size)s is too large. "
        "Maximum uploaded file size is %(max_size)s."
    )

    def __init__(self, allowed_extensions: List[str], max_size: int):
        """
        params allowed_extensions:: list of allowed file extensions.
        params max_size:: max file size to be processed (in B).
        """

        self.allowed_extensions = [extension.lower() for extension in allowed_extensions]
        self.max_size = max_size

    def __call__(self, file: InMemoryUploadedFile):
        self.file_validator(file)

    def get_list_of_validation(self):
        return [
            self.file_extension_validation,
            self.file_size_validation,
        ]

    def file_validator(self, file: InMemoryUploadedFile):
        for validation in self.get_list_of_validation():
            validation(file)

    def file_extension_validation(self, file: InMemoryUploadedFile):
        extension = Path(file.name).suffix[1:].lower()
        if extension not in self.allowed_extensions:
            raise ValidationError(
                message=self.invalid_extension_message,
                params={
                    "extension": extension,
                    "allowed_extensions": ", ".join(self.allowed_extensions),
                },
            )

    def file_size_validation(self, file: InMemoryUploadedFile):
        if file.size > self.max_size:
            raise ValidationError(
                message=self.invalid_size_message,
                params={
                    "size": convert_size_unit(file.size, "MB"),
                    "max_size": convert_size_unit(self.max_size, "MB"),
                }
            )


class CustomerWhitelistCSVFileValidator(FileValidator):
    """
    Validate CSV uploaded file from Django admin page, including:
        - File extension (CSV only)
        - File size
        - File format
    """

    invalid_format_message = _(
        "Invalid customer ID at line %(line_id)s."
    )

    def __init__(self, allowed_extensions: List[str], max_size: int, with_header: bool = False):
        super().__init__(allowed_extensions, max_size)
        self.with_header = with_header

    def get_list_of_validation(self):
        lst = super(CustomerWhitelistCSVFileValidator, self).get_list_of_validation()
        lst.append(self.whitelist_csv_file_format_validation)
        return lst

    def whitelist_csv_file_format_validation(self, file: InMemoryUploadedFile):
        """
        Check format of CSV whitelist file:
            - Row contains valid customer ID (length = 10, prefix = '1')
        """
        decoded_file = file.read().decode('utf-8')
        csv_io = io.StringIO(decoded_file)
        csv_reader = csv.reader(csv_io, delimiter=',')

        start = 1
        if self.with_header:
            next(csv_reader, None)
            start += 1

        for line_id, line_data in enumerate(csv_reader, start):
            customer_id = line_data[0]
            if not (
                len(customer_id) == CSVWhitelistFileValidatorConstant.CUSTOMER_ID_LENGTH and
                customer_id.startswith(CSVWhitelistFileValidatorConstant.CUSTOMER_ID_PREFIX)
            ):
                raise ValidationError(
                    message=self.invalid_format_message,
                    params={
                        'line_id': line_id
                    }
                )
        file.seek(0)
