"""
forms.py
declare Django Form
"""

from django import forms
from datetime import date

class UploadFileForm(forms.Form):
    """form to upload file"""
    file_field = forms.FileField(label="File Upload")
    email_date = forms.DateField(label="Email Date", initial=date.today())


class LenderReversalPaymentForm(forms.Form):

    id = forms.IntegerField(required=True)
