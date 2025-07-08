from __future__ import unicode_literals

from builtins import object
from datetime import datetime, timedelta

from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _

from django import forms
from django.forms.widgets import HiddenInput, TextInput
from django.forms.widgets import DateInput, RadioSelect, Select
from django.forms import ModelForm
from django.conf import settings

from django.contrib.admin.widgets import AdminFileWidget
from django.forms.widgets import Textarea, SelectMultiple
from django.forms.widgets import PasswordInput

# from tinymce.widgets import TinyMCE

from juloserver.julo.models import StatusLookup, Payment
from juloserver.julo.services import get_allowed_payment_statuses
from julo_status.models import StatusAppSelection, ReasonStatusAppSelection


PERIODE_CHOICES = ((True, _('Hari ini')), (False, _('Bebas')))


class HorizontalRadioRenderer(forms.RadioSelect.renderer):
    def render(self):
        return mark_safe(u'&nbsp;&nbsp;&nbsp;\n'.join([u'%s\n' % w for w in self]))


class PaymentSearchForm(forms.Form):
    
    def __init__(self, *args, **kwargs):
        super(PaymentSearchForm, self).__init__(*args, **kwargs)

    #date with time DateTimeWidget
    datetime_range = forms.CharField(required = False,
                    widget = TextInput(attrs={
                        'class': 'form-control input-daterange-timepicker',
                        'name':"daterange"})
                    )

    search_q = forms.CharField(required = False,
                    widget = TextInput(attrs={'class': 'form-control',
                                            'placeholder':'Pencarian'})
                    )

    sort_q = forms.CharField(required = False)
    sort_agent = forms.CharField(required = False)

    status_app = forms.ModelChoiceField(required=False,
                    queryset=StatusLookup.objects.filter(status_code__gte=300), 
                    widget = Select(attrs={
                        'class':'form-control',
                        })
                    )

    status_now = forms.ChoiceField(required=False,
                    choices=PERIODE_CHOICES, 
                    widget = RadioSelect(renderer=HorizontalRadioRenderer))





class StatusChangesForm(forms.Form):
    """
        please use ModelChoiceField instead of ChoiceField if using queryset
    """

    status_to = forms.ModelChoiceField(required = True,
        # choices = [],
        queryset = StatusLookup.objects.all(),
        widget  = Select(attrs={
                # 'required': "",
                'class':'form-control',
                }),
    )
    reason = forms.ModelMultipleChoiceField(required = True,
        queryset = ReasonStatusAppSelection.objects.all(),
        widget  = SelectMultiple(attrs={
                # 'required': "",
                'class':'form-control',
                'style': 'height: 140px;'
                }),
    )
    notes = forms.CharField(required = False,
        widget  = Textarea(attrs={ 'rows': 6,
                    'class': 'form-control',
                    # 'required': "",
                    'placeholder':'Insert notes here'}),
    )
    notes_only = forms.CharField(
        required=False,
        widget=Textarea(attrs={
            'rows': 6,
            'class': 'form-control',
            'placeholder': 'Insert notes here'
        }),
    )
    autodebit_notes = forms.CharField(
        required=False,
        widget=Textarea(attrs={
            'rows': 6,
            'class': 'form-control',
            'placeholder': 'Insert notes here'
        }),
    )

    def __init__(self, status_code, *args, **kwargs):
        super(StatusChangesForm, self).__init__(*args, **kwargs)
        # print "status_code: ", status_code

        #get allow status from julo core service
        status_choices = []
        allowed_statuses = get_allowed_payment_statuses(int(status_code.status_code))
        if allowed_statuses:
            status_choices = [
                [status.code, "%s - %s" % (status.code, status.desc)] for status in allowed_statuses
            ]
        status_choices.insert(0,[None, '-- Pilih --'])
        # print "status_choices: ", status_choices
        self.fields['status_to'].choices = status_choices

    def clean_status_to(self):
        if 'status_to' in self.cleaned_data:
            status_to_data = self.cleaned_data['status_to']
            if status_to_data:
                return status_to_data

        raise forms.ValidationError("Status Perpindahan belum dipilih!!!")

    def clean_reason(self):
        if 'reason' in self.cleaned_data:
            reason_data = self.cleaned_data['reason']
            if reason_data:
                return reason_data

        raise forms.ValidationError("Alasan Perpindahan belum dipilih!!!")


class EventPaymentForm(forms.Form):
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
    cashback_earned = forms.CharField(required = True,
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
        super(EventPaymentForm, self).__init__(*args, **kwargs)


class SendSmsForm(forms.Form):

    message = forms.CharField(
        required=True,
        widget=Textarea(attrs={
            'rows': 10,
            'maxlength': '160',  # max SMS char length
            'class': 'form-control',
            'required': "",
            'placeholder': 'Ketik SMS di sini'}),
        )


class ApplicationPhoneForm(forms.Form):
    """
        please use ModelChoiceField instead of ChoiceField if using queryset
    """
    SMS_CATEGORY = [
        ('', '-- Pilih --'),
        ('crm_sms_ptp', 'PTP/Janji Bayar'),
        ('crm_sms_va', 'Kirim VA'),
        ('crm_sms_relief', 'Penawaran Program'),
        ('crm_sms_payment', 'Pembayaran'),
        ('crm_sms_others', 'Lainnya'),
    ]
    phones = forms.ChoiceField(required = True,
        choices = [],
        widget  = Select(attrs={
                'required': "",
                'class':'form-control',
                'id': 'phone_selects',
                }),
    )
    category = forms.CharField(
        max_length=50
    )
    template_code = forms.ChoiceField(required=True,
                                      choices=SMS_CATEGORY,
                                      widget=Select(attrs={
                                          'required': "",
                                          'class': 'form-control',
                                          'id': 'sms_category_selects',
                                      }),
                                      )

    def __init__(self, app_phone, *args, **kwargs):
        super(ApplicationPhoneForm, self).__init__(*args, **kwargs)
        #get allow status from julo core service
        phone_choices = app_phone
        phone_choices.insert(0,['', '-- Pilih --'])
        self.fields['phones'].choices = phone_choices


class SendEmailForm(forms.Form):
    EMAIL_CATEGORY = [
        ('', '-- Pilih --'),
        ('crm_email_ptp', 'PTP/Janji Bayar'),
        ('crm_email_va', 'Kirim VA'),
        ('crm_email_relief', 'Penawaran Program'),
        ('crm_email_payment', 'Pembayaran'),
        ('crm_email_others', 'Lainnya'),
    ]
    to_email = forms.CharField(
        widget  = TextInput(attrs={
                'required': "",
                'class':'form-control',
                'id': 'to_email',
                }),
    )

    email_subject = forms.CharField(
        widget  = TextInput(attrs={
                'required': "",
                'class':'form-control',
                'id': 'email_subject',
                }),
    )

    email_content = forms.CharField(
        widget=Textarea(attrs={
                'required': "",
                'class':'form-control',
                'id':'email_content',
                }))
    template_code = forms.ChoiceField(required=True,
                                      choices=EMAIL_CATEGORY,
                                      widget=Select(attrs={
                                          'required': "",
                                          'class': 'form-control',
                                          'id': 'email_category_selects',
                                      }),
                                      )
    category = forms.CharField(
        max_length=50)
    pre_header = forms.CharField(
        widget=TextInput(attrs={
            'required': "",
            'class': 'form-control',
            'id': 'email_pre_header',
        }),
    )

    def __init__(self, *args, **kwargs):
        super(SendEmailForm, self).__init__(*args, **kwargs)

class PaymentForm(ModelForm):

    class Meta(object):
        model = Payment

        fields = (
            'ptp_date',
        )
        widgets = {
                    'ptp_date':TextInput(attrs={
                        'size':model._meta.get_field('ptp_date').max_length,
                        'class':'form-control mydatepicker',
                        'maxlength':model._meta.get_field('ptp_date').max_length,
                        'placeholder':'dd-mm-yyyy '}),
        }
        error_messages = {
            # 'julo_bank_name': {
            #     'required': _("Nama Bank belum diisi!"),
            # },
        }

    def save(self, commit=True):
        instance = super(PaymentForm, self).save(commit=False)
        if commit:
            instance.save()
        return instance


class RobocallTemplateForm(forms.Form):
    robocall_template = forms.ChoiceField(required = True,
        choices = [],
        widget  = Select(attrs={
                'required': "",
                'class':'form-control',
                'id': 'robocall_template_select',
                }),
    )

    def __init__(self, robocall_template, *args, **kwargs):
        super(ApplicationPhoneForm, self).__init__(*args, **kwargs)
        #get allow status from julo core service
        robocall_template_choices = robocall_template
        robocall_template_choices.insert(0,['', '-- Pilih --'])
        self.fields['robocall_template'].choices = robocall_template_choices