"""
activity_dialer.py
declare Django Form
"""

from django import forms


class UploadDialerActivityForm(forms.Form):
    """form to upload file"""
    file_field = forms.FileField(label="File Upload")