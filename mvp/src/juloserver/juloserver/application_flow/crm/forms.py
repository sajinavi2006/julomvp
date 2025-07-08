from django import forms


class WaitlistUploadForm(forms.Form):
    file_field = forms.FileField(
        label="File Upload", error_messages={'required': 'Please choose the CSV file'}
    )
