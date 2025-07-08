from django import forms

from juloserver.employee_financing.constants import WEB_FORM_TYPE
from juloserver.employee_financing.models import Company
from django.forms.widgets import DateInput


class DateInput(forms.DateInput):
    input_type = 'date'


class ExportResponseWebForm(forms.Form):
    """form to download csv"""
    company_field = forms.ModelChoiceField(queryset=Company.objects.filter(
        is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'}),
        error_messages={'required': 'Company required'})
    action_field = forms.ChoiceField(widget=forms.RadioSelect,
                                     choices=WEB_FORM_TYPE,
                                     label="Web Form Type",
                                     initial=1,
                                     error_messages={'required': 'Need to choose web form type'})
    start_date = forms.DateField(label="Start Date",
                                 widget=DateInput,
                                 error_messages={'required': 'Need to select start date'}
                                 )
    end_date = forms.DateField(label="End Date",
                               widget=DateInput,
                               error_messages={'required': 'Need to select end date'}
                               )
