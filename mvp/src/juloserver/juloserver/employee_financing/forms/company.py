from django import forms
from juloserver.employee_financing.models import Company
from juloserver.julo.models import Partner
from django.forms.widgets import (TextInput, NumberInput, EmailInput)

from juloserver.apiv2.utils import custom_error_messages_for_required


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = "__all__"
        widgets = {
            'name': TextInput(),
            'email': EmailInput(),
            'phone_number': NumberInput(),
            'company_size': NumberInput(),
            'payday': NumberInput(),
        }

    def __init__(self, *args, **kwargs):
        super(CompanyForm, self).__init__(*args, **kwargs)
        self.fields['partner'].queryset = Partner.objects.filter(is_active=True)
        for field in self.fields:
            self.fields[field].error_messages = custom_error_messages_for_required(
                self.fields[field].label)

    def clean(self):
        cleaned_data = super(CompanyForm, self).clean()
        phone_number = cleaned_data.get('phone_number')
        if phone_number and int(phone_number) < 1:
            msg = 'Harus lebih besar atau sama dengan 1'
            self._errors['phone_number'] = self.error_class([msg])
            del cleaned_data['phone_number']
        return cleaned_data
