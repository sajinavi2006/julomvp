from django import forms


class GrabPromoCodeUploadFileForm(forms.Form):
    file_field = forms.FileField(label="File Upload")


class GrabFDCStuckApplicationUploadFileForm(forms.Form):
    file_field = forms.FileField(label="File Upload")
