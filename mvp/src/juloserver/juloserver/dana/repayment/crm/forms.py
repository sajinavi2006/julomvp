from django import forms
from juloserver.dana.constants import (
    DanaProductType,
)


class DanaRepaymentSettlementForm(forms.Form):
    """form to upload file"""

    dana_product_choices = [
        (DanaProductType.CICIL, 'Dana Cicil'),
        (DanaProductType.CASH_LOAN, 'Dana Cash Loan'),
    ]

    product_field = forms.ChoiceField(
        label="Product",
        required=False,
        choices=dana_product_choices,
        error_messages={'required': 'Please choose the Product'},
    )

    file_field = forms.FileField(
        label="File Upload", error_messages={'required': 'Please choose the CSV file'}
    )
