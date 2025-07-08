from builtins import object, str

from django import forms
from django.contrib.admin.widgets import AdminFileWidget
from django.contrib.auth.models import User
from django.forms import ModelForm
from django.forms.widgets import (
    PasswordInput,
    RadioSelect,
    Select,
    SelectMultiple,
    Textarea,
    TextInput,
)
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _
from julo_status.models import ReasonStatusAppSelection, StatusAppSelection
from multiupload.fields import MultiMediaField

from juloserver.apiv1.data.loan_purposes import (
    get_loan_purpose_dropdown_by_product_line,
)
from juloserver.application_flow.models import HsfbpIncomeVerification
from juloserver.julo.models import (
    Application,
    AwsFaceRecogLog,
    FaceRecognition,
    Image,
    ProductLine,
    StatusLookup,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import ApplicationStatusCodes
from juloserver.new_crm.services.application_services import filter_app_statuses_crm

YES_NO_CHOICES = ((True, _('Ya')), (False, _('Tidak')))


class HorizontalRadioRenderer(forms.RadioSelect.renderer):
    def render(self):
        return mark_safe(u'&nbsp;&nbsp;&nbsp;\n'.join([u'%s\n' % w for w in self]))


class StatusChangesForm(forms.Form):
    """
        please use ModelChoiceField instead of ChoiceField if using queryset
    """

    status_to = forms.ChoiceField(
        required=True,
        widget=Select(attrs={'class': 'form-control'}),
    )
    reason_str = forms.CharField(widget=forms.HiddenInput(), required=False)
    notes = forms.CharField(
        required=False,
        widget=Textarea(attrs={
            'rows': 6,
            'class': 'form-control',
            'placeholder': 'Insert notes here'
        }),
    )
    notes_only = forms.CharField(
        required=False,
        widget=Textarea(attrs={
            'rows': 6,
            'class': 'form-control',
            'placeholder': 'Insert notes here'
        }),
    )
    
    autodebit_notes = forms.CharField(
        required=False,
        widget=Textarea(attrs={
            'rows': 6,
            'class': 'form-control',
            'placeholder': 'Insert notes here'
        }),
    )

    def __init__(self, status_code, application, *args, **kwargs):
        super(StatusChangesForm, self).__init__(*args, **kwargs)

        if not isinstance(application, Application):
            application = Application.objects.get_or_none(pk=application)

        # get allow status from julo core service
        _, status_choices = filter_app_statuses_crm(
            status_code=status_code,
            application=application,
        )
        # print "status_choices: ", status_choices
        self.fields['status_to'].choices = status_choices

    def clean_status_to(self):
        if 'status_to' in self.cleaned_data:
            status_to_data = self.cleaned_data['status_to']
            if status_to_data:
                return status_to_data

        raise forms.ValidationError("Status Perpindahan belum dipilih!!!")

    def clean_reason_str(self):
        if 'reason_str' in self.cleaned_data:
            reason_data = self.cleaned_data['reason_str']
            if reason_data:
                return reason_data

        raise forms.ValidationError("Alasan Perpindahan belum dipilih!!!")


class HsfbpIncomeVerificationForm(ModelForm):
    class Meta(object):
        model = HsfbpIncomeVerification

        fields = ('verified_income',)
        widgets = {
            'verified_income':TextInput(attrs={
                'size':model._meta.get_field('verified_income').max_length,
                'class':'form-control mask',
                'maxlength':model._meta.get_field('verified_income').max_length,
                'placeholder':'verified_income'}),
        }

    def save(self, commit=True):
        instance = super(HsfbpIncomeVerificationForm, self).save(commit=False)
        if commit:
            instance.save()
        return instance


class NoteForm(forms.Form):

    notes = forms.CharField(
        required=True,
        widget=Textarea(attrs={
            'rows': 15,
            'class': 'form-control',
            'required': True,
            'placeholder': 'Masukan catatan pada aplikasi ini'}),
    )


class ApplicationForm(forms.Form):
    """
        Selected Application field to be edited
        (14, 'address_street_num', True),
        (15, 'address_provinsi', True),
        (16, 'address_kabupaten', True),
        (17, 'address_kecamatan', True),
        (18, 'address_kelurahan', True),
        (19, 'address_kodepos', True),
        (23, 'mobile_phone_1', True),
        (25, 'mobile_phone_2', True),

        (31, 'marital_status', True),
        (32, 'dependent', True),
        (22, 'landlord_mobile_phone', True),


        (35, 'spouse_mobile_phone', True),
        (40, 'kin_mobile_phone', True),
        (41, 'kin_relationship', True),
        (47, 'company_phone_number', True),
        (50, 'monthly_income', True),
        (60, 'other_income_amount', True),
        (62, 'monthly_housing_cost', True),
        (63, 'monthly_expenses', True),
        (64, 'total_current_debt', True),
        (65, 'company_name', True),
    """

    status_to = forms.ChoiceField(
        required=True,
        widget=Select(attrs={'class': 'form-control'}),
    )
    reason_str = forms.CharField(widget=forms.HiddenInput(), required=False)
    notes = forms.CharField(
        required=False,
        widget=Textarea(attrs={
            'rows': 6,
            'class': 'form-control',
            'placeholder': 'Insert notes here'
        }),
    )
    notes_only = forms.CharField(
        required=False,
        widget=Textarea(attrs={
            'rows': 6,
            'class': 'form-control',
            'placeholder': 'Insert notes here'
        }),
    )

    def __init__(self, status_code, *args, **kwargs):
        super(StatusChangesForm, self).__init__(*args, **kwargs)


class ApplicationSelectFieldForm(forms.Form):
    """
        Application Field for selection
    """
    loan_purpose = forms.ChoiceField(
        required=True,
        widget=Select(attrs={'class': 'form-control'}),
    )
    product_line = forms.ChoiceField(
        required=True,
        widget=Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, application, *args, **kwargs):
        super(ApplicationSelectFieldForm, self).__init__(*args, **kwargs)

        if application.product_line_id:
            # get allow status from julo core service
            loan_purpose_choices = []
            product_line_choices = []
            loan_purpose_list = get_loan_purpose_dropdown_by_product_line(application.product_line_id)
            product_line_list = ProductLine.objects.all()
            if loan_purpose_list:
                loan_purpose_choices = [
                    [item,  item] for item in loan_purpose_list['results']
                ]
            if product_line_list:
                product_line_choices = [
                    [item.product_line_code,
                     ' - '.join([str(item.product_line_code), item.product_line_type])
                     ] for item in product_line_list
                ]
            #loan_purpose_choices.insert(0,[None, '-- Pilih --'])
            self.fields['loan_purpose'].choices = loan_purpose_choices
            self.fields['product_line'].choices = product_line_choices
        else:
            self.fields['loan_purpose'].choices = []
            self.fields['product_line'].choices = []



class ApplicationForm(ModelForm):

    class Meta(object):
        model = Application

        fields = (
            #PIN TAB
            # 'loan',
            'loan_purpose_desc',
            'loan_amount_request',
            'loan_duration_request',

            #BIO TAB
            'fullname',
            'email',
            'dob',
            'birth_place',
            'ktp',
            'address_street_num',
            'address_kecamatan',
            'address_kelurahan',
            'address_kabupaten',
            'address_provinsi',
            'address_kodepos',

            'mobile_phone_1',
            'has_whatsapp_1',
            'mobile_phone_2',
            'has_whatsapp_2',
            'dialect',
            'gender',

            # KEL TAB
            'spouse_name',
            'spouse_dob',
            'marital_status',
            'dependent',

            'spouse_mobile_phone',
            'spouse_has_whatsapp',
            'kin_name',
            'kin_dob',
            'kin_gender',
            'kin_mobile_phone',
            'kin_relationship',
            'close_kin_name',
            'close_kin_mobile_phone',
            'close_kin_relationship',

            #PEK TAB
            'company_name',
            'company_phone_number',
            'monthly_income',
            'payday',
            'work_kodepos',
            'job_start',
            'hrd_name',
            'company_address',
            'number_of_employees',
            'position_employees',
            'employment_status',
            'billing_office',
            'mutation',

            #KEU TAB
            'other_income_amount',
            'monthly_housing_cost',
            'monthly_expenses',
            'total_current_debt',
            'vehicle_ownership_1',
            'bank_branch',
            'bank_account_number',
            'name_in_bank',
            'bank_name'
        )
        widgets = {
            # 'loan_purpose':Select(attrs={
            #     'class':'form-control',
            #     'placeholder':'loan_purpose'}),

            'loan_purpose_desc':TextInput(attrs={
                'size':model._meta.get_field('loan_purpose_desc').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('loan_purpose_desc').max_length,
                'placeholder':'loan_purpose_desc'}),
            'loan_amount_request':TextInput(attrs={
                'size':model._meta.get_field('loan_amount_request').max_length,
                'class':'form-control',
                'type':'number',
                'maxlength':model._meta.get_field('loan_amount_request').max_length,
                'placeholder':'loan_amount_request'}),
            'loan_duration_request':TextInput(attrs={
                'size':model._meta.get_field('loan_duration_request').max_length,
                'class':'form-control',
                'type':'number',
                'maxlength':model._meta.get_field('loan_duration_request').max_length,
                'placeholder':'loan_duration_request'}),

            'fullname':TextInput(attrs={
                'size':model._meta.get_field('fullname').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('fullname').max_length,
                'placeholder':'nama lengkap'}),
            'email':TextInput(attrs={
                'size':model._meta.get_field('email').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('email').max_length,
                'placeholder':'nama lengkap'}),
            'dob':TextInput(attrs={
                'size':model._meta.get_field('dob').max_length,
                'class':'form-control mydatepicker',
                'maxlength':model._meta.get_field('dob').max_length,
                'placeholder':'dd-mm-yyyy '}),
            'birth_place':TextInput(attrs={
                'size':model._meta.get_field('birth_place').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('birth_place').max_length,
                'placeholder':'tempat lahir'}),
            'ktp':TextInput(attrs={
                'size':model._meta.get_field('ktp').max_length,
                'class':'form-control',
                'oninput':'javascript: if (this.value.length > this.maxLength) this.value = this.value.slice(0, this.maxLength);',
                'type':'number',
                'maxlength':model._meta.get_field('ktp').max_length,
                'placeholder':'no. ktp'}),
            'address_street_num':TextInput(attrs={
                'size':model._meta.get_field('address_street_num').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('address_street_num').max_length,
                'placeholder':'address_street_num'}),
            'address_kecamatan':TextInput(attrs={
                'size':model._meta.get_field('address_kecamatan').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('address_kecamatan').max_length,
                'placeholder':'address_kecamatan'}),
            'address_kelurahan':TextInput(attrs={
                'size':model._meta.get_field('address_kelurahan').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('address_kelurahan').max_length,
                'placeholder':'address_kelurahan'}),
            'address_kabupaten':TextInput(attrs={
                'size':model._meta.get_field('address_kabupaten').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('address_kabupaten').max_length,
                'placeholder':'address_kabupaten'}),
            'address_provinsi':TextInput(attrs={
                'size':model._meta.get_field('address_provinsi').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('address_provinsi').max_length,
                'placeholder':'address_provinsi'}),
            'address_kodepos':TextInput(attrs={
                'size':model._meta.get_field('address_kodepos').max_length,
                'class':'form-control maskNumber',
                'maxlength':model._meta.get_field('address_kodepos').max_length,
                'placeholder':'address_kodepos'}),
            'mobile_phone_1':TextInput(attrs={
                'size':model._meta.get_field('mobile_phone_1').max_length,
                'class':'form-control',
                'type':'number',
                'maxlength':model._meta.get_field('mobile_phone_1').max_length,
                'placeholder':'mobile_phone_1'}),
            'has_whatsapp_1':RadioSelect(choices=YES_NO_CHOICES,
                renderer=HorizontalRadioRenderer),
            'mobile_phone_2':TextInput(attrs={
                'size':model._meta.get_field('mobile_phone_2').max_length,
                'class':'form-control',
                'type':'number',
                'maxlength':model._meta.get_field('mobile_phone_2').max_length,
                'placeholder':'mobile_phone_2'}),
            'has_whatsapp_2':RadioSelect(choices=YES_NO_CHOICES,
                renderer=HorizontalRadioRenderer),
            'dialect': Select(attrs={
                'class': 'form-control',
                'placeholder': 'dialect'}),

            'spouse_name':TextInput(attrs={
                'size':model._meta.get_field('spouse_name').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('spouse_name').max_length,
                'placeholder':'spouse_name'}),
            'spouse_dob':TextInput(attrs={
                'size':model._meta.get_field('spouse_dob').max_length,
                'class':'form-control mydatepicker',
                'maxlength':model._meta.get_field('spouse_dob').max_length,
                'placeholder':'dd-mm-yyyy '}),
            'marital_status':Select(attrs={
                'class':'form-control',
                'placeholder':'marital_status'}),
            'dependent':TextInput(attrs={
                'size':model._meta.get_field('dependent').max_length,
                'class':'form-control',
                'type':'number',
                'maxlength':model._meta.get_field('dependent').max_length,
                'placeholder':'dependent'}),

            'spouse_mobile_phone':TextInput(attrs={
                'size':model._meta.get_field('spouse_mobile_phone').max_length,
                'class':'form-control',
                'type':'number',
                'maxlength':model._meta.get_field('spouse_mobile_phone').max_length,
                'placeholder':'spouse_mobile_phone'}),
            'spouse_has_whatsapp':RadioSelect(choices=YES_NO_CHOICES,
                renderer=HorizontalRadioRenderer),
            'kin_name':TextInput(attrs={
                'size':model._meta.get_field('kin_name').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('kin_name').max_length,
                'placeholder':'kin_name'}),
            'kin_gender':Select(attrs={
                'class':'form-control',
                'placeholder':'kin_gender'}),
            'gender':Select(attrs={
                'class':'form-control',
                'placeholder':'gender'}),
            'kin_dob':TextInput(attrs={
                'size':model._meta.get_field('kin_dob').max_length,
                'class':'form-control mydatepicker',
                'maxlength':model._meta.get_field('kin_dob').max_length,
                'placeholder':'dd-mm-yyyy '}),
            'kin_mobile_phone':TextInput(attrs={
                'size':model._meta.get_field('kin_mobile_phone').max_length,
                'class':'form-control',
                'type':'number',
                'maxlength':model._meta.get_field('kin_mobile_phone').max_length,
                'placeholder':'kin_mobile_phone'}),
            'kin_relationship':Select(attrs={
                'class':'form-control',
                'placeholder':'kin_relationship'}),
            'close_kin_name': TextInput(attrs={
                'size': model._meta.get_field('close_kin_name').max_length,
                'class': 'form-control',
                'maxlength': model._meta.get_field('close_kin_name').max_length,
                'placeholder': 'close_kin_name'}),
            'close_kin_mobile_phone': TextInput(attrs={
                'size': model._meta.get_field('close_kin_mobile_phone').max_length,
                'class': 'form-control',
                'type': 'number',
                'maxlength': model._meta.get_field('close_kin_mobile_phone').max_length,
                'placeholder': 'close_kin_mobile_phone'}),
            'close_kin_relationship': Select(attrs={
                'class': 'form-control',
                'placeholder': 'close_kin_relationship'}),

            'company_name':TextInput(attrs={
                'size':model._meta.get_field('company_name').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('company_name').max_length,
                'placeholder':'company_name'}),
            'company_phone_number':TextInput(attrs={
                'size':model._meta.get_field('company_phone_number').max_length,
                'class':'form-control',
                'type':'number',
                'maxlength':model._meta.get_field('company_phone_number').max_length,
                'placeholder':'company_phone_number'}),
            'monthly_income':TextInput(attrs={
                'size':model._meta.get_field('monthly_income').max_length,
                'class':'form-control mask',
                'maxlength':model._meta.get_field('monthly_income').max_length,
                'placeholder':'monthly_income'}),
            'payday':TextInput(attrs={
                'size':model._meta.get_field('payday').max_length,
                'class':'form-control',
                'type':'number',
                'maxlength':2,
                'placeholder':'payday'}),
            'work_kodepos':TextInput(attrs={
                'size':model._meta.get_field('work_kodepos').max_length,
                'class':'form-control',
                'type':'number',
                'maxlength':model._meta.get_field('work_kodepos').max_length,
                'placeholder':'work_kodepos'}),
            'job_start':TextInput(attrs={
                'size':model._meta.get_field('job_start').max_length,
                'class':'form-control mydatepicker',
                'maxlength':model._meta.get_field('job_start').max_length,
                'placeholder':'dd-mm-yyyy '}),
            'hrd_name':TextInput(attrs={
                'size':model._meta.get_field('hrd_name').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('hrd_name').max_length,
                'placeholder':'hrd_name'}),
            'company_address':TextInput(attrs={
                'size':model._meta.get_field('company_address').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('company_address').max_length,
                'placeholder':'company_address'}),
            'number_of_employees':TextInput(attrs={
                'size':model._meta.get_field('number_of_employees').max_length,
                'class':'form-control',
                'type':'number',
                'maxlength':model._meta.get_field('number_of_employees').max_length,
                'placeholder':'number_of_employees'}),
            'position_employees':TextInput(attrs={
                'size':model._meta.get_field('position_employees').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('position_employees').max_length,
                'placeholder':'position_employees'}),
            'employment_status':TextInput(attrs={
                'size':model._meta.get_field('employment_status').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('employment_status').max_length,
                'placeholder':'employment_status'}),
            'billing_office':TextInput(attrs={
                'size':model._meta.get_field('billing_office').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('billing_office').max_length,
                'placeholder':'billing_office'}),
            'mutation':TextInput(attrs={
                'size':model._meta.get_field('mutation').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('mutation').max_length,
                'placeholder':'mutation'}),

            'other_income_amount':TextInput(attrs={
                'size':model._meta.get_field('other_income_amount').max_length,
                'class':'form-control mask',
                'maxlength':model._meta.get_field('other_income_amount').max_length,
                'placeholder':'other_income_amount'}),
            'monthly_housing_cost':TextInput(attrs={
                'size':model._meta.get_field('monthly_housing_cost').max_length,
                'class':'form-control mask',
                'maxlength':model._meta.get_field('monthly_housing_cost').max_length,
                'placeholder':'monthly_housing_cost'}),
            'monthly_expenses':TextInput(attrs={
                'size':model._meta.get_field('monthly_expenses').max_length,
                'class':'form-control mask',
                'maxlength':model._meta.get_field('monthly_expenses').max_length,
                'placeholder':'monthly_expenses'}),
            'total_current_debt':TextInput(attrs={
                'size':model._meta.get_field('total_current_debt').max_length,
                'class':'form-control mask',
                'maxlength':model._meta.get_field('total_current_debt').max_length,
                'placeholder':'total_current_debt'}),
            'vehicle_ownership_1':Select(attrs={
                'class':'form-control',
                'placeholder':'vehicle_ownership_1'}),
            'bank_branch':TextInput(attrs={
                'size':model._meta.get_field('bank_branch').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('bank_branch').max_length,
                'placeholder':'bank_branch'}),
            'bank_account_number':TextInput(attrs={
                'size':model._meta.get_field('bank_account_number').max_length,
                'class':'form-control',
                'type':'number',
                'maxlength':model._meta.get_field('bank_account_number').max_length,
                'placeholder':'bank_account_number'}),
            'name_in_bank': TextInput(attrs={
                'size': model._meta.get_field('name_in_bank').max_length,
                'class': 'form-control',
                'maxlength': model._meta.get_field('name_in_bank').max_length,
                'placeholder': 'name_in_bank'}),
            'bank_name':TextInput(attrs={
                'size':model._meta.get_field('bank_name').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('bank_name').max_length,
                'placeholder':'bank_name'}),
        }
        error_messages = {
            # 'julo_bank_name': {
            #     'required': _("Nama Bank belum diisi!"),
            # },
        }



    # def clean(self):
    #     # Running parent process for Clean()
    #     cleaned_data = super(ApplicationForm, self).clean()

    #     # Validating
    #     return cleaned_data

    def save(self, commit=True):
        instance = super(ApplicationForm, self).save(commit=False)
        if commit:
            instance.save()
        return instance


class SecurityForm(forms.Form):

    security_note = forms.CharField(
        required=True,
        widget=Textarea(attrs={
            'rows': 6,
            'class': 'form-control',
            'required': True,
            'placeholder': 'Insert notes here..'}),
    )
