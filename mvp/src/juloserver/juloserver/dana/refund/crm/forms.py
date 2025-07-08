from django import forms


class DanaRefundRepaymentSettlementForm(forms.Form):
    """form to upload file"""

    file_field = forms.FileField(
        label="File Upload", error_messages={'required': 'Please choose the CSV file'}
    )
