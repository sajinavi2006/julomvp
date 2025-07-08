from django import forms
from django.core.exceptions import ValidationError
from django.forms.widgets import (
    Select,
    Textarea,
)
from juloserver.balance_consolidation.constants import BalanceConsolidationMessageException
from juloserver.balance_consolidation.models import (
    Fintech,
    BalanceConsolidation
)
from juloserver.balance_consolidation.services import filter_app_statuses_crm
from .utils import (
    check_valid_loan_amount,
    check_valid_loan_date,
)


class BalanceConsolidationVerificationForm(forms.Form):
    status_to = forms.ChoiceField(
        required=False,
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

    def __init__(self, instance, *args, **kwargs):
        super(BalanceConsolidationVerificationForm, self).__init__(*args, **kwargs)
        status_choices = filter_app_statuses_crm(instance.validation_status)
        self.fields['status_to'].choices = status_choices


class BalanceConsolidationForm(forms.ModelForm):
    class Meta(object):
        model = BalanceConsolidation
        fields = (
            'fintech', 'loan_principal_amount', 'loan_outstanding_amount',
            'disbursement_date', 'due_date'
        )

    def __init__(self, *args, **kwargs):
        super(BalanceConsolidationForm, self).__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name in ('disbursement_date', 'due_date'):
                field.widget.attrs['class'] = 'form-control mydatepicker'
            else:
                field.widget.attrs['class'] = 'form-control'
        self.fields['fintech'].choices = Fintech.objects.filter(is_active=True).values_list('id', 'name')

    def clean(self):
        super(BalanceConsolidationForm, self).clean()
        self.check_loan_amount_input()
        self.check_loan_date_input()

    def check_loan_amount_input(self):
        loan_principal_amount = self.cleaned_data['loan_principal_amount']
        loan_outstanding_amount = self.cleaned_data['loan_outstanding_amount']
        if not check_valid_loan_amount(loan_principal_amount, loan_outstanding_amount):
            raise ValidationError(
                BalanceConsolidationMessageException.INVALID_LOAN_AMOUNT
            )

    def check_loan_date_input(self):
        loan_disbursement_date = self.cleaned_data['disbursement_date']
        loan_due_date = self.cleaned_data['due_date']
        if not check_valid_loan_date(loan_disbursement_date, loan_due_date):
            raise ValidationError(
                BalanceConsolidationMessageException.INVALID_LOAN_DATE
            )
