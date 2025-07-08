from django import forms
from django.forms import ModelForm

from django.forms.widgets import Textarea, TextInput
# from django.forms.widgets import RadioSelect, PasswordInput, Select

from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _


class PartialPaymentForm(forms.Form):
    """
        please use ModelChoiceField instead of ChoiceField if using queryset
    """

    partial_payment = forms.CharField(required = True,
        max_length=15,
        widget  = TextInput(attrs={
                'required': "",
                'class':"form-control mask",
                }),
    )
    paid_date = forms.CharField(required = True,
        widget = TextInput(attrs={
                'required': "",
                'class': "form-control mydatepicker",
                'placeholder': "dd-mm-yyyy"
                })
    )
    notes = forms.CharField(required = True,
        widget  = Textarea(attrs={ 'rows': 10,
                    'class': 'form-control',
                    'required': "",
                    'placeholder':'Masukan catatan pada payment ini'}),
    )

    def __init__(self, *args, **kwargs):
        super(PartialPaymentForm, self).__init__(*args, **kwargs)

