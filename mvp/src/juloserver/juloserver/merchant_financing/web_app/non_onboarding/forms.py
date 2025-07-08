from django import forms


class MFStandardUploadFileForm(forms.Form):
    """form to upload file"""

    file = forms.FileField(
        label="File Upload", error_messages={'required': 'Please choose the CSV file'}
    )
