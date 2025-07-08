from django import forms
from juloserver.dana.constants import DanaMaritalStatusConst, DanaProductType


class DanaUpdateLoanTransferFundForm(forms.Form):
    product_type = forms.ChoiceField(
        choices=[
            (DanaProductType.CICIL, 'Dana Cicil'),
            (DanaProductType.CASH_LOAN, 'Dana Cash Loan'),
        ],
        widget=forms.Select(attrs={'class': 'form-control'}),
        error_messages={'required': 'Please choose the Product'},
    )
    file_field = forms.FileField(
        label="File Upload", error_messages={'required': 'Please choose the CSV file'}
    )


class DanaSettlementFileUpload(forms.Form):
    def __init__(self, *args, **kwargs):
        show_product = kwargs.get('show_product')
        if kwargs.get('show_product'):
            kwargs.pop('show_product')

        super().__init__(*args, **kwargs)
        if not show_product:
            self.fields.pop('product_type')

    product_type = forms.ChoiceField(
        choices=[
            (DanaProductType.CICIL, 'Dana Cicil'),
            (DanaProductType.CASH_LOAN, 'Dana Cash Loan'),
        ],
        widget=forms.Select(attrs={'class': 'form-control'}),
        error_messages={'required': 'Please choose the Product'},
    )
    file_field = forms.FileField(
        label="File Upload", error_messages={'required': 'Please choose the CSV file'}
    )


class DanaDepositDeductionUpload(forms.Form):
    file_field = forms.FileField(label="File Upload")


class DanaUpdateMaritalStatus(forms.Form):
    NOT_SELECTED_VALUE = 'not_selected_value'
    CHOICES = [
        (NOT_SELECTED_VALUE, '--- Select Marital Status ---'),
        (DanaMaritalStatusConst.CERAI, DanaMaritalStatusConst.CERAI),
        (DanaMaritalStatusConst.JANDA_DUDA, DanaMaritalStatusConst.JANDA_DUDA),
        (DanaMaritalStatusConst.MENIKAH, DanaMaritalStatusConst.MENIKAH),
        (DanaMaritalStatusConst.LAJANG, DanaMaritalStatusConst.LAJANG),
    ]

    marital_status = forms.ChoiceField(
        choices=CHOICES,
        widget=forms.Select(attrs={'class': 'btn btn-primary'}),
        required=True,
    )

    def clean_marital_status(self):
        value = self.cleaned_data.get('marital_status')
        if value == self.NOT_SELECTED_VALUE:
            raise forms.ValidationError("Marital status must be selected")
        return value
