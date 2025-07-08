from django import forms

from juloserver.employee_financing.constants import EF_PILOT_UPLOAD_ACTION_CHOICES


class PreApprovalUploadFileForm(forms.Form):
    """form to upload file"""
    file_field = forms.FileField(label="File Upload",
                                 error_messages={'required': 'Please choose the CSV file'})
