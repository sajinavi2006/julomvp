import os

from django import forms
from django.forms.widgets import RadioSelect, Select, TextInput
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.models import Partner
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.merchant_financing.web_app.constants import (
    AXIATA_ALLOWED_DOCUMENT_EXTENSION_FORMAT,
    AXIATA_ALLOWED_IMAGE_EXTENSION_FORMAT,
    MF_WEB_APP_CRM_UPLOAD_DOCUMENT_MAX_SIZE,
    MF_WEB_APP_UPLOAD_ACTION_CHOICES,
)
from juloserver.partnership.constants import DOCUMENT_TYPE, IMAGE_TYPE
from juloserver.julo.models import StatusLookup, ProductLine
from juloserver.partnership.utils import partnership_detokenize_sync_kv_in_bulk
from juloserver.pii_vault.constants import PiiSource


class PartnerFieldMixin:
    """Mixin to handle partner_field initialization"""

    def populate_partner_field(self, partner_query):
        detokenize_partner_list = partnership_detokenize_sync_kv_in_bulk(
            PiiSource.PARTNER, partner_query, ['name']
        )
        partner_names = [
            getattr(detokenize_partner_list.get(partner.id), 'name', '')
            for partner in partner_query
        ]

        self.fields['partner_field'].choices = [("", "--------------")] + [
            (name, name) for name in partner_names
        ]


class MFWebAppMultiImageUploadForm(forms.Form):
    allowed_document_type = DOCUMENT_TYPE.copy()
    allowed_document_type.update(IMAGE_TYPE)
    document_type_choices = [(value, value) for value in allowed_document_type]

    attachment = forms.FileField(
        label="File Upload",
        error_messages={'required': 'Unggahan Dokumen Tidak Boleh kosong'},
        required=True,
    )
    select_widget = Select(attrs={'required': False, 'class': 'form-control'})
    document_type = forms.ChoiceField(
        required=False,
        choices=document_type_choices,
        widget=select_widget,
    )

    def clean_attachment(self):
        attachment = self.cleaned_data.get('attachment')

        file_extension = os.path.splitext(attachment.name)[-1]
        file_name = os.path.splitext(attachment.name)[0]
        self.cleaned_data['extension'] = file_extension
        self.cleaned_data['file_name'] = file_name

        if attachment.size > MF_WEB_APP_CRM_UPLOAD_DOCUMENT_MAX_SIZE:
            raise forms.ValidationError('Maximal ukuran file 4 MB')

        return attachment

    def clean_document_type(self):
        document_type = self.cleaned_data.get('document_type')
        if (
            not document_type
            or (
                document_type not in DOCUMENT_TYPE
                and document_type not in IMAGE_TYPE
            )
        ):
            raise forms.ValidationError('Tipe Dokumen kosong/tidak diizinkan')
        return document_type

    def clean(self):
        cleaned_data = super().clean()
        document_type = cleaned_data.get('document_type')
        extension = cleaned_data.get('extension')

        if document_type in {'ktp', 'selfie', 'kk', 'nib_document', 'company_photo'}:
            if extension not in AXIATA_ALLOWED_IMAGE_EXTENSION_FORMAT:
                list_extension = ', '.join(AXIATA_ALLOWED_IMAGE_EXTENSION_FORMAT)
                msg = 'Ekstensi Dokumen tidak diizinkan, ekstensi harus {}'.format(list_extension)
                raise forms.ValidationError(msg)
        else:
            if (
                extension not in AXIATA_ALLOWED_DOCUMENT_EXTENSION_FORMAT
                and extension not in AXIATA_ALLOWED_IMAGE_EXTENSION_FORMAT
            ):
                list_extension = ', '.join(
                    map(
                        str,
                        AXIATA_ALLOWED_DOCUMENT_EXTENSION_FORMAT
                        | AXIATA_ALLOWED_IMAGE_EXTENSION_FORMAT
                    )
                )

                msg = 'Ekstensi Dokumen tidak diizinkan, ekstensi harus {}'.format(list_extension)
                raise forms.ValidationError(msg)

        return cleaned_data


class MFWebAppUploadFileForm(forms.Form, PartnerFieldMixin):
    """form to upload file"""

    partner_field = forms.ChoiceField(
        choices=[],
        widget=forms.Select(attrs={'class': 'form-control'}),
        error_messages={'required': 'Partner required'},
    )
    file_field = forms.FileField(label="File Upload",
                                 error_messages={'required': 'Please upload CSV file'})
    action_field = forms.ChoiceField(widget=forms.RadioSelect,
                                     choices=MF_WEB_APP_UPLOAD_ACTION_CHOICES,
                                     label="Action",
                                     initial=1,
                                     error_messages={'required': 'Action not selected'})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        partner_query = Partner.objects.filter(name=PartnerNameConstant.AXIATA_WEB).all()
        self.populate_partner_field(partner_query)


class MFWebLoanUploadFileForm(forms.Form, PartnerFieldMixin):
    """form to upload file"""

    partner_field = forms.ChoiceField(
        choices=[],
        widget=forms.Select(attrs={"class": "form-control"}),
        error_messages={'required': 'Partner required'},
    )
    file_field = forms.FileField(
        label="File Upload", error_messages={'required': 'Please upload CSV file'}
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        partner_query = Partner.objects.filter(is_csv_upload_applicable=True).all()
        self.populate_partner_field(partner_query)


class MFWebRepaymentUploadFileForm(forms.Form, PartnerFieldMixin):
    """Form to upload file for repayment"""

    partner_field = forms.ChoiceField(
        choices=[],
        widget=forms.Select(attrs={"class": "form-control"}),
        error_messages={'required': 'Partner required'},
    )

    file_field = forms.FileField(
        label="File Upload", error_messages={'required': 'Please upload CSV file'}
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        partner_query = Partner.objects.filter(is_csv_upload_applicable=True).all()
        self.populate_partner_field(partner_query)


class MFWebDisbursementUploadFileForm(forms.Form, PartnerFieldMixin):
    """Form to upload file for disbursement"""

    partner_field = forms.ChoiceField(
        choices=[],
        widget=forms.Select(attrs={'class': 'form-control'}),
        error_messages={'required': 'Partner required'},
    )
    file_field = forms.FileField(
        label="File Upload", error_messages={'required': 'Please upload CSV file'}
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        partner_query = Partner.objects.filter(is_csv_upload_applicable=True).all()
        self.populate_partner_field(partner_query)


class HorizontalRadioRenderer(forms.RadioSelect.renderer):
    def render(self):
        return mark_safe(u'&nbsp;&nbsp;&nbsp;\n'.join([u'%s\n' % w for w in self]))


class MFWebappLoanListForm(forms.Form):
    PERIODE_CHOICES = ((True, _('Hari ini')), (False, _('Bebas')))
    PRODUCT_LINE_MF_WEBAPP = {
        ProductLineCodes.AXIATA_WEB,
        ProductLineCodes.J1
    }

    def __init__(self, *args, **kwargs):
        super(MFWebappLoanListForm, self).__init__(*args, **kwargs)

    # date with time DateTimeWidget
    datetime_range = forms.CharField(
        required=False,
        widget=TextInput(
            attrs={'class': 'form-control input-daterange-timepicker', 'name': "daterange"}
        ),
    )

    search_q = forms.CharField(
        required=False,
        widget=TextInput(attrs={'class': 'form-control', 'placeholder': 'Pencarian'}),
    )

    sort_q = forms.CharField(required=False)

    status_app = forms.ModelChoiceField(
        required=False,
        queryset=StatusLookup.objects.filter(status_code__range=[200, 300]),
        widget=Select(
            attrs={
                'class': 'form-control',
            }
        ),
    )

    list_product_line = forms.ModelChoiceField(
        required=False,
        queryset=ProductLine.objects.filter(product_line_code__in=PRODUCT_LINE_MF_WEBAPP),
        widget=Select(
            attrs={
                'class': 'form-control',
            }
        ),
    )

    status_now = forms.ChoiceField(
        required=False,
        choices=PERIODE_CHOICES,
        widget=RadioSelect(renderer=HorizontalRadioRenderer),
    )

    specific_column_search = forms.ChoiceField(
        required=False,
        choices=(
            ("", "-------"),
            ("loan_xid", "SPHP Number"),
        ),
        widget=Select(
            attrs={
                'class': 'form-control',
            }
        ),
    )


class MFWebAppCSVLoanUploadForm(forms.Form):
    CONTENT_TYPES = {'application', 'text', 'image'}
    MAX_UPLOAD_SIZE = 2621440

    partner = forms.CharField()
    nik = forms.CharField()
    distributor = forms.IntegerField()
    funder = forms.CharField()
    type = forms.CharField()
    loan_request_date = forms.DateField(input_formats=['%d/%m/%Y'])
    interest_rate = forms.FloatField()
    provision_rate = forms.FloatField()
    financing_amount = forms.IntegerField()
    financing_tenure = forms.IntegerField()
    installment_number = forms.IntegerField()
    invoice_number = forms.CharField()
    buyer_name = forms.CharField()
    buying_amount = forms.FloatField()
    invoice_file = forms.FileField()
    bilyet_file = forms.FileField(required=False)
    invoice_number = forms.CharField()
    buyer_name = forms.CharField(required=False)
    buying_amount = forms.IntegerField(required=False)

    def clean_partner(self):
        partner_name = self.cleaned_data['partner']
        partner = Partner.objects.filter(name=partner_name).last()
        if not partner:
            raise forms.ValidationError("{} tidak ditemukan".format(partner_name))
        return partner

    def clean_invoice_file(self):
        invoice_file = self.cleaned_data['invoice_file']
        content_type = invoice_file.content_type.split('/')[0]
        if content_type in self.CONTENT_TYPES:
            if invoice_file._size > self.MAX_UPLOAD_SIZE:
                raise forms.ValidationError("File terlalu besar")
        else:
            raise forms.ValidationError("File type tidak didukung")
        return invoice_file

    def clean_bilyet_file(self):
        bilyet_file = self.cleaned_data['bilyet_file']
        if not bilyet_file:
            return bilyet_file

        content_type = bilyet_file.content_type.split('/')[0]
        if content_type in self.CONTENT_TYPES:
            if bilyet_file._size > self.MAX_UPLOAD_SIZE:
                raise forms.ValidationError("File terlalu besar")
        else:
            raise forms.ValidationError("File type tidak didukung")
        return bilyet_file

    def clean(self):
        cleaned_data = super().clean()
        type = cleaned_data['type']
        if type == 'IF':
            invoice_number = self.cleaned_data['invoice_number']
            if not invoice_number:
                raise forms.ValidationError("Invoice number tidak boleh kosong")

            buying_amount = self.cleaned_data['buying_amount']
            if not buying_amount:
                raise forms.ValidationError("Buying amount tidak boleh kosong")

        return cleaned_data
