from django import forms

from juloserver.employee_financing.constants import EF_PILOT_UPLOAD_ACTION_CHOICES


class PilotApplicationUploadFileForm(forms.Form):
    """form to upload file"""
    file_field = forms.FileField(label="File Upload",
                                 error_messages={'required': 'Please choose the CSV file'})
    action_field = forms.ChoiceField(widget=forms.RadioSelect,
                                     choices=EF_PILOT_UPLOAD_ACTION_CHOICES,
                                     label="Action",
                                     initial=1,
                                     error_messages={'required': 'Need to choose action'})
