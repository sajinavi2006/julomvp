from django.contrib.admin.widgets import AdminFileWidget
from django.contrib.auth.models import User

from django import forms
from django.forms import ModelForm
from django.forms.widgets import Textarea, TextInput
from django.forms.widgets import Select, PasswordInput

from juloserver.julo.models import Application, StatusLookup


class StatusSelectionsForm(forms.Form):

    status_to_all = forms.ModelMultipleChoiceField(
        queryset = StatusLookup.objects.all().order_by('status_code'),
        widget  = forms.SelectMultiple(),
    )

    def __init__(self, ignore_status, *args, **kwargs):
        super(StatusSelectionsForm, self).__init__(*args, **kwargs)
        self.fields['status_to_all'].queryset = StatusLookup.objects.all().exclude(
            status_code__in=ignore_status).order_by('status_code')

    def clean_status_to_all(self):
        if 'status_to_all' in self.cleaned_data:
            # check if they not null each other
            status_to_data = self.cleaned_data['status_to_all']
            if len(status_to_data)>0:
                return status_to_data

        raise forms.ValidationError("Upload Dokumen Tidak Boleh Kosong !!!")


class ReasonSelectionsForm(forms.Form):
    row_max = 15    
    reason_all = forms.CharField(
        widget  = Textarea(attrs={ 'rows': row_max,
                    'class': 'form-control',
                    'required': "",
                    'placeholder':'Masukan alasan pada status aplikasi ini'}),
    )
    def __init__(self, reason_init, *args, **kwargs):
        super(ReasonSelectionsForm, self).__init__(*args, **kwargs)
        if len(reason_init)>0:
            reason_text = '\r\n'.join(reason_init)
            self.fields['reason_all'].initial = reason_text

    def clean_reason_all(self):
        if 'reason_all' in self.cleaned_data:
            # check if they not null each other
            reason_all_data = self.cleaned_data['reason_all']
            if not reason_all_data:
                raise forms.ValidationError("Upload Dokumen Tidak Boleh Kosong !!!")
        return reason_all_data

        