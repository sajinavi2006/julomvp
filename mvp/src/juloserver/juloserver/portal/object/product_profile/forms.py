from __future__ import unicode_literals

from django import forms
from django.forms.widgets import TextInput


class ProductProfileSearchForm(forms.Form):

    def __init__(self, *args, **kwargs):
        super(ProductProfileSearchForm, self).__init__(*args, **kwargs)

    # date with time DateTimeWidget
    datetime_range = forms.CharField(required=False, widget=TextInput(
                                     attrs={'class': 'form-control input-daterange-timepicker',
                                            'name': "daterange"}))

    search_q = forms.CharField(required=False, widget=TextInput(
                               attrs={'class': 'form-control',
                                      'placeholder': 'Pencarian'}))

    sort_q = forms.CharField(required=False)
