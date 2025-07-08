from datetime import datetime, date
import os

from rest_framework import status as http_status_codes
from rest_framework import serializers
from django import forms

from juloserver.merchant_financing.constants import MFStandardProductUploadDetails
from juloserver.merchant_financing.web_app.utils import mf_standard_verify_nik
from juloserver.partnership.utils import custom_error_messages_for_required
from juloserver.merchant_financing.utils import validate_max_file_size


class UpdateLoanSerializer(serializers.Serializer):
    distributor_code = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Kode Distributor")
    )

    funder = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Pendana")
    )

    interest_rate = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Bunga Per Bulan")
    )

    provision_rate = serializers.CharField(
        required=True, error_messages=custom_error_messages_for_required("Persentase Provisi")
    )

    def validate_interest_rate(self, value: str) -> str:
        try:
            float(value)
        except ValueError:
            raise serializers.ValidationError("interest rate bukan merupakan sebuah angka")
        return value

    def validate_provision_rate(self, value: str) -> str:
        try:
            float(value)
        except ValueError:
            raise serializers.ValidationError("provision rate bukan merupakan sebuah angka")
        return value


class CreateLoanSerializer(forms.Form):
    ALLOWED_FILE_TYPES = {
        'pdf',
        'jpg',
        'jpeg',
        'png',
        'csv',
        'xls',
        'xlsx',
        'doc',
        'docx',
        'zip',
        'rar',
    }
    # 4 * 1024 * 1024 = 4194304 (4MB)
    MAX_UPLOAD_SIZE = 4194304
    LOAN_TYPES = {'SCF', 'IF'}

    loan_type = forms.CharField()
    loan_amount = forms.IntegerField()
    loan_duration = forms.IntegerField()
    installment_number = forms.IntegerField()
    invoice_number = forms.CharField()
    invoice_file = forms.FileField()
    bilyet_file = forms.FileField(required=False)

    def clean_loan_type(self):
        loan_type = self.cleaned_data['loan_type']
        if loan_type not in self.LOAN_TYPES:
            raise forms.ValidationError("loan_type not SCF or IF")
        return loan_type

    def clean_loan_amount(self):
        loan_amount = self.cleaned_data['loan_amount']
        if loan_amount < 0:
            raise forms.ValidationError("loan_amount must be positive value")
        return loan_amount

    def clean_loan_duration(self):
        loan_duration = self.cleaned_data['loan_duration']
        if loan_duration < 0:
            raise forms.ValidationError("loan_duration must be positive value")
        return loan_duration

    def clean_installment_number(self):
        installment_number = self.cleaned_data['installment_number']
        if installment_number < 0:
            raise forms.ValidationError("installment_number must be positive value")
        return installment_number

    def clean_invoice_file(self):
        invoice_file = self.cleaned_data['invoice_file']
        file_ext = os.path.splitext(invoice_file.name)[1][1:].lower()
        if file_ext in self.ALLOWED_FILE_TYPES:
            if invoice_file._size > self.MAX_UPLOAD_SIZE:
                raise forms.ValidationError("File terlalu besar")
        else:
            raise forms.ValidationError("File type tidak didukung")
        return invoice_file

    def clean_bilyet_file(self):
        bilyet_file = self.cleaned_data['bilyet_file']
        if not bilyet_file:
            return bilyet_file

        file_ext = os.path.splitext(bilyet_file.name)[1][1:].lower()
        if file_ext in self.ALLOWED_FILE_TYPES:
            if bilyet_file._size > self.MAX_UPLOAD_SIZE:
                raise forms.ValidationError("File terlalu besar")
        else:
            raise forms.ValidationError("File type tidak didukung")
        return bilyet_file


class UploadDocumentMfSerializer(forms.Form):
    ALLOWED_DOCUMENT_FILE_TYPES = {
        'pdf',
        'png',
        'img',
        'jpg',
        'jpeg',
        'webp',
    }

    ALLOWED_IMAGE_FILE_TYPES = {
        'png',
        'img',
        'jpg',
        'jpeg',
        'webp',
    }

    invoice = forms.FileField(required=False)
    bilyet = forms.FileField(required=False)
    manual_skrtp = forms.FileField(required=False)
    merchant_photo = forms.FileField(required=False)

    def validate_file(self, file, file_type, allowed_file_types):
        if file:
            file_ext = os.path.splitext(file.name)[1][1:].lower()

            if file_ext in allowed_file_types:
                err = validate_max_file_size(file, 2)
                if err:
                    raise forms.ValidationError(
                        "File terlalu besar, harap upload dokumen di bawah 2MB",
                        http_status_codes.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    )
            else:
                raise forms.ValidationError(
                    "file type is not acceptable", http_status_codes.HTTP_415_UNSUPPORTED_MEDIA_TYPE
                )

            if self.cleaned_data.get('file'):
                raise forms.ValidationError("only accept 1 file per upload")

            self.cleaned_data['file'] = file
            self.cleaned_data['file_type'] = file_type

    def clean_invoice(self):
        file = self.cleaned_data['invoice']
        self.validate_file(file, "invoice", self.ALLOWED_DOCUMENT_FILE_TYPES)
        return file

    def clean_bilyet(self):
        file = self.cleaned_data['bilyet']
        self.validate_file(file, "bilyet", self.ALLOWED_DOCUMENT_FILE_TYPES)
        return file

    def clean_manual_skrtp(self):
        file = self.cleaned_data['manual_skrtp']
        self.validate_file(file, "manual_skrtp", self.ALLOWED_DOCUMENT_FILE_TYPES)
        return file

    def clean_merchant_photo(self):
        file = self.cleaned_data['merchant_photo']
        self.validate_file(file, "merchant_photo", self.ALLOWED_DOCUMENT_FILE_TYPES)
        return file


class MFStandardLoanSubmissionSerializer:
    def __init__(self, data):
        self.LOAN_TYPES = {'SCF', 'IF'}
        self.data = data
        self.errors = ""
        self.validated_data = {}

    def validate(self):
        self.errors = []
        self.validate_nik()
        self.validate_distributor()
        self.validate_funder()
        self.validate_type()
        self.validate_loan_request_date()
        self.validate_interest_rate()
        self.validate_provision_rate()
        self.validate_financing_amount()
        self.validate_financing_tenure()
        self.validate_installment_number()
        self.validate_invoice_number()
        self.validate_invoice_link()
        self.validate_giro_link()
        self.validate_skrtp_link()
        self.validate_merchant_photo_link()
        self.errors = ", ".join(self.errors)
        return self.errors

    def validate_nik(self):
        nik = self.data.get(MFStandardProductUploadDetails.NIK, '').strip()
        if not nik:
            self.errors.append("NIK is required")
        else:
            err = mf_standard_verify_nik(nik)
            if err:
                self.errors.append(err)
            else:
                self.validated_data[MFStandardProductUploadDetails.NIK] = nik

    def validate_distributor(self):
        distributor = self.data.get(MFStandardProductUploadDetails.DISTRIBUTOR)
        if distributor:
            try:
                distributor = int(distributor)
                self.validated_data[MFStandardProductUploadDetails.DISTRIBUTOR] = distributor
            except ValueError:
                self.errors.append("Distributor is not a number")

    def validate_funder(self):
        funder = self.data.get(MFStandardProductUploadDetails.FUNDER, '')
        self.validated_data[MFStandardProductUploadDetails.FUNDER] = funder

    def validate_type(self):
        type = self.data.get(MFStandardProductUploadDetails.TYPE, '').strip().upper()
        if not type:
            self.errors.append("type is required")
        elif type not in self.LOAN_TYPES:
            self.errors.append("type must be SCF or IF")
        else:
            self.validated_data[MFStandardProductUploadDetails.TYPE] = type

    def validate_loan_request_date(self):
        loan_request_date = self.data.get(MFStandardProductUploadDetails.LOAN_REQUEST_DATE)
        if not loan_request_date:
            self.errors.append("Loan request date is required")
        else:
            try:
                parsed_date = datetime.strptime(loan_request_date, '%d/%m/%Y').date()
                current_date = date.today()
                if parsed_date < current_date:
                    self.errors.append("Loan request date cannot be later than upload date")
                self.validated_data[MFStandardProductUploadDetails.LOAN_REQUEST_DATE] = parsed_date
            except ValueError:
                self.errors.append("Date Format is not valid")

    def validate_interest_rate(self):
        interest_rate = self.data.get(MFStandardProductUploadDetails.INTEREST_RATE)
        if not interest_rate:
            self.errors.append("Interest rate is required")
        else:
            try:
                interest_rate = float(interest_rate)
                self.validated_data[MFStandardProductUploadDetails.INTEREST_RATE] = interest_rate
            except ValueError:
                self.errors.append("Interest rate is not a number")

    def validate_provision_rate(self):
        provision_rate = self.data.get(MFStandardProductUploadDetails.PROVISION_RATE)
        if not provision_rate:
            self.errors.append("Provision rate is required")
        else:
            try:
                provision_rate = float(provision_rate)
                self.validated_data[MFStandardProductUploadDetails.PROVISION_RATE] = provision_rate
            except ValueError:
                self.errors.append("Provision rate is not a number")

    def validate_financing_amount(self):
        financing_amount = self.data.get(MFStandardProductUploadDetails.FINANCING_AMOUNT)
        if not financing_amount:
            self.errors.append("Financing amount is required")
        else:
            try:
                financing_amount = float(financing_amount)
                if financing_amount <= 0:
                    self.errors.append("Financing amount must greater than 0")
                self.validated_data[
                    MFStandardProductUploadDetails.FINANCING_AMOUNT
                ] = financing_amount
            except ValueError:
                self.errors.append("Financing amount is not a number")

    def validate_financing_tenure(self):
        financing_tenure = self.data.get(MFStandardProductUploadDetails.FINANCING_TENURE)
        if not financing_tenure:
            self.errors.append("Financing tenure is required")
        else:
            try:
                financing_tenure = int(financing_tenure)
                if financing_tenure <= 0:
                    self.errors.append("Financing tenure must greater than 0")
                self.validated_data[
                    MFStandardProductUploadDetails.FINANCING_TENURE
                ] = financing_tenure
            except ValueError:
                self.errors.append("financing_tenure is not a number")

    def validate_installment_number(self):
        installment_number = self.data.get(MFStandardProductUploadDetails.INSTALLMENT_NUMBER)
        if not installment_number:
            self.errors.append("installment_number is required")
        else:
            try:
                installment_number = int(installment_number)
                if installment_number <= 0:
                    self.errors.append("Installment number must greater than 0")
                self.validated_data[
                    MFStandardProductUploadDetails.INSTALLMENT_NUMBER
                ] = installment_number
            except ValueError:
                self.errors.append("installment_number is not a number")

    def validate_invoice_number(self):
        invoice_number = self.data.get(MFStandardProductUploadDetails.INVOICE_NUMBER)
        if not invoice_number:
            self.errors.append("invoice_number is required")
        else:
            self.validated_data[MFStandardProductUploadDetails.INVOICE_NUMBER] = invoice_number

    def validate_invoice_link(self):
        invoice_link = self.data.get(MFStandardProductUploadDetails.INVOICE_LINK)
        if invoice_link:
            self.validated_data[MFStandardProductUploadDetails.INVOICE_LINK] = invoice_link

    def validate_giro_link(self):
        giro_link = self.data.get(MFStandardProductUploadDetails.GIRO_LINK)
        if giro_link:
            self.validated_data[MFStandardProductUploadDetails.GIRO_LINK] = giro_link

    def validate_skrtp_link(self):
        skrtp_link = self.data.get(MFStandardProductUploadDetails.SKRTP_LINK)
        if skrtp_link:
            self.validated_data[MFStandardProductUploadDetails.SKRTP_LINK] = skrtp_link

    def validate_merchant_photo_link(self):
        merchant_photo_link = self.data.get(MFStandardProductUploadDetails.MERCHANT_PHOTO_LINK)
        if merchant_photo_link:
            self.validated_data[
                MFStandardProductUploadDetails.MERCHANT_PHOTO_LINK
            ] = merchant_photo_link

    def get_validated_data(self):
        """Returns the validated data"""
        if self.errors:
            raise ValueError("Validation errors found: {}".format(self.errors))
        return self.validated_data
