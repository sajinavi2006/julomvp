from __future__ import unicode_literals

from datetime import datetime, timedelta

from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _

from django import forms
from django.forms.widgets import HiddenInput, TextInput
from django.forms.widgets import DateInput, RadioSelect, Select
from django.forms import ModelForm
from django.conf import settings
from django.db.models import Q

from juloserver.julo.models import StatusLookup
from juloserver.julo.statuses import JuloOneCodes


PERIODE_CHOICES = ((True, _('Hari ini')), (False, _('Bebas')))


class HorizontalRadioRenderer(forms.RadioSelect.renderer):
    def render(self):
        return mark_safe(u'&nbsp;&nbsp;&nbsp;\n'.join([u'%s\n' % w for w in self]))


class ApplicationSearchForm(forms.Form):

    def __init__(self, *args, **kwargs):
        super(ApplicationSearchForm, self).__init__(*args, **kwargs)

    #date with time DateTimeWidget
    datetime_range = forms.CharField(required = False,
                    widget = TextInput(attrs={
                        'class': 'form-control input-daterange-timepicker',
                        'name':"daterange"})
                    )
    filter_category = forms.ModelChoiceField(required=False,
                                        queryset=StatusLookup.objects.filter(status_code__lte=190).order_by(
                                            'status_code'),
                                        widget=Select(attrs={
                                            'class': 'form-control',
                                        })
                                        )
    search_q = forms.CharField(required = False,
                    widget = TextInput(attrs={'class': 'form-control',
                                            'placeholder':'Pencarian'})
                    )

    sort_q = forms.CharField(required = False)

    status_app = forms.ModelChoiceField(
        required=False,
        queryset=StatusLookup.objects.filter(
            Q(status_code__lte=190)
            | Q(status_code__in=JuloOneCodes.fraud_check())
            | Q(status_code__in=(433,))
        ).order_by('status_code'),
        widget=Select(
            attrs={
                'class': 'form-control',
            }
        ),
    )

    status_now = forms.ChoiceField(required=False,
                    choices=PERIODE_CHOICES,
                    widget = RadioSelect(renderer=HorizontalRadioRenderer))


class OESearchForm(forms.Form):

    def __init__(self, *args, **kwargs):
        super(OESearchForm, self).__init__(*args, **kwargs)

    search_q = forms.CharField(required = False,
                    widget = TextInput(attrs={'class': 'form-control',
                                            'placeholder':'Pencarian'})
                    )

    sort_q = forms.CharField(required = False)
