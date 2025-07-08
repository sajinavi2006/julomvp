from django import forms
from django.forms.widgets import (
    Select,
    Textarea,
)
from juloserver.julo_financing.services.crm_services import get_verification_status_changes


class JFinancingVerificationFilterForm(forms.Form):
    FILTER_FIELD_CHOICES = [
        ('j_financing_checkout__customer_id', 'Customer ID'),
        ('j_financing_checkout__customer__fullname', 'Full Name'),
        ('j_financing_checkout__customer__email', 'Email'),
    ]

    filter_field = forms.ChoiceField(required=False, choices=FILTER_FIELD_CHOICES)
    filter_keyword = forms.CharField(required=False)

    def reset_filter(self):
        self.fields.get('filter_field').clean(None)
        self.fields.get('filter_keyword').clean(None)


class JFinancingVerificationForm(forms.Form):
    status_to = forms.ChoiceField(
        required=False,
        widget=Select(attrs={'class': 'form-control'}),
    )
    notes = forms.CharField(
        required=False,
        widget=Textarea(
            attrs={'rows': 6, 'class': 'form-control', 'placeholder': 'Insert notes here'}
        ),
    )
    notes_only = forms.CharField(
        required=False,
        widget=Textarea(
            attrs={'rows': 6, 'class': 'form-control', 'placeholder': 'Insert notes here'}
        ),
    )

    def __init__(self, instance, *args, **kwargs):
        super(JFinancingVerificationForm, self).__init__(*args, **kwargs)
        status_choices = get_verification_status_changes(instance.validation_status)
        self.fields['status_to'].choices = status_choices
