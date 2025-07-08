from django import forms
from juloserver.employee_financing.models import Company
from juloserver.employee_financing.constants import SEND_FORM_URL_TO_EMAIL_ACTION_CHOICES


class SendFormURLToEmailForm(forms.Form):
    company = forms.ModelChoiceField(
        queryset=Company.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'}),
        error_messages={'required': 'Partner required'}
    )
    file_field = forms.FileField(
        label="File Upload", error_messages={'required': 'Please choose the CSV file'}
    )
    action_field = forms.ChoiceField(
        widget=forms.RadioSelect, choices=SEND_FORM_URL_TO_EMAIL_ACTION_CHOICES,
        label="Action", initial=1,
        error_messages={'required': 'Need to choose action'}
    )
