from __future__ import unicode_literals

from builtins import object
from datetime import datetime, timedelta

from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _

from django import forms
from django.forms import ModelForm
from django.forms.widgets import HiddenInput, TextInput
from django.forms.widgets import DateInput, RadioSelect, Select
from django.forms import ModelForm
from django.conf import settings

from django.contrib.admin.widgets import AdminFileWidget
from django.forms.widgets import Textarea, SelectMultiple

from juloserver.julo.models import StatusLookup, Loan, Partner
from juloserver.julo.services import get_allowed_payment_statuses
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from .services import get_allowed_loan_statuses

PERIODE_CHOICES = ((True, _('Hari ini')), (False, _('Bebas')))

class HorizontalRadioRenderer(forms.RadioSelect.renderer):
    def render(self):
        return mark_safe(u'&nbsp;&nbsp;&nbsp;\n'.join([u'%s\n' % w for w in self]))


class LoanSearchForm(forms.Form):

    def __init__(self, *args, **kwargs):
        super(LoanSearchForm, self).__init__(*args, **kwargs)

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

    status_app = forms.ModelChoiceField(required=False,
                    queryset=StatusLookup.objects.filter(status_code__range=[200, 300]),
                    widget = Select(attrs={
                        'class':'form-control',
                        })
                    )

    list_partner = forms.ModelChoiceField(required=False,
                    queryset=Partner.objects.all(),
                    widget = Select(attrs={
                        'class':'form-control',
                        })
                    )

    status_now = forms.ChoiceField(required=False,
                    choices=PERIODE_CHOICES,
                    widget=RadioSelect(renderer=HorizontalRadioRenderer))

    specific_column_search = forms.ChoiceField(required=False,
                                   choices=(
                                       ("", "-------"),
                                       ("loan_xid", "SPHP Number"),
                                   ),
                                   widget=Select(attrs={'class':'form-control',}))


class LoanReassignmentForm(forms.Form):
    agent_types = forms.ChoiceField(required=False,
                                    choices=[('', 'Select Agent/Vendor'),
                                             ('agent', 'Agent'),
                                             ('vendor', 'Vendor')],
                                    widget=Select(attrs={
                                        'class': 'form-control'
                                    }))

    buckets = forms.ChoiceField(required=False,
                                choices=[('', 'Select Bucket'),
                                         (JuloUserRoles.COLLECTION_BUCKET_5, 'Bucket 5')],
                                widget=Select(attrs={
                                    'class': 'form-control',
                                }))

    agents = forms.ChoiceField(required=False,
                               choices=[('', 'List of Agent/Vendor')],
                               widget=Select(attrs={
                                    'class': 'form-control',
                               }))


class SquadReassignmentForm(forms.Form):
    bucket_list = forms.ChoiceField(required=False,
                                choices=[('', 'Select Bucket'),
                                         (JuloUserRoles.COLLECTION_BUCKET_2, 'Bucket 2'),
                                         (JuloUserRoles.COLLECTION_BUCKET_3, 'Bucket 3'),
                                         (JuloUserRoles.COLLECTION_BUCKET_4, 'Bucket 4')],
                                widget=Select(attrs={
                                    'class': 'form-control',
                                }))
    squad_list = forms.ChoiceField(required=False,
                               choices=[('', 'List of Squad')],
                               widget=Select(attrs={
                                    'class': 'form-control',
                               }))
    agent_list = forms.ChoiceField(required=False,
                               choices=[('', 'List of Agent')],
                               widget=Select(attrs={
                                    'class': 'form-control',
                               }))

class NoteForm(forms.Form):

    notes = forms.CharField(required = True,
        widget  = Textarea(attrs={ 'rows': 5,
                    'class': 'form-control',
                    'required': False,
                    'placeholder':'Masukan catatan pada loan ini'}),
    )

    def clean_notes(self):
        if 'notes' in self.cleaned_data:
            # check if they not null each other
            notes = self.cleaned_data['notes']
            if notes:
                return notes
        raise forms.ValidationError("Notes Tidak Boleh Kosong !!!")


class LoanForm(ModelForm):

    class Meta(object):
        model = Loan

        fields = (
            # 'loan_amount',
            # 'loan_duration',
            # 'installment_amount',
            # 'cashback_earned_total',
            # 'fund_transfer_ts',
            'julo_bank_name',
            'julo_bank_branch',
            # 'julo_bank_account_number',
        )
        # exclude = ('cdate', 'udate' )
        widgets = {
            # 'loan_duration':TextInput(attrs={
            #     'size':model._meta.get_field('loan_duration').max_length,
            #     'class':'form-control mask',
            #     'maxlength':model._meta.get_field('loan_duration').max_length,
            #     'placeholder':''}),
            # 'loan_amount':TextInput(attrs={
            #     'size':model._meta.get_field('loan_amount').max_length,
            #     'class':'form-control mask',
            #     'maxlength':model._meta.get_field('loan_amount').max_length,
            #     'placeholder':''}),
            # 'installment_amount':TextInput(attrs={
            #     'size':model._meta.get_field('installment_amount').max_length,
            #     'class':'form-control mask',
            #     'maxlength':model._meta.get_field('installment_amount').max_length,
            #     'placeholder':''}),
            # 'cashback_earned_total':TextInput(attrs={
            #     'size':model._meta.get_field('cashback_earned_total').max_length,
            #     'class':'form-control mask',
            #     'maxlength':model._meta.get_field('cashback_earned_total').max_length,
            #     'placeholder':''}),
            # 'fund_transfer_ts':TextInput(attrs={
            #     'size':model._meta.get_field('fund_transfer_ts').max_length,
            #     'class':'form-control mydatepicker',
            #     'maxlength':model._meta.get_field('fund_transfer_ts').max_length,
            #     'placeholder':'dd-mm-yyyy '}),
            'julo_bank_name':TextInput(attrs={
                'size':model._meta.get_field('julo_bank_name').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('julo_bank_name').max_length,
                'placeholder':'masukan nama bank '}),
            'julo_bank_branch':TextInput(attrs={
                'class':'form-control',
                'maxlength':model._meta.get_field('julo_bank_branch').max_length,
                'placeholder':'cabang bank'
                }),
            # 'julo_bank_account_number':TextInput(attrs={
            #     'class':'form-control',
            #     'maxlength':model._meta.get_field('julo_bank_account_number').max_length,
            #     'placeholder':'account number'
            #     }),

        }
        error_messages = {
            'julo_bank_name': {
                'required': _("Nama Bank belum diisi!"),
            },
        }


    def clean(self):
        # Running parent process for Clean()
        cleaned_data = super(LoanForm, self).clean()

        # Validating
        return cleaned_data

    def save(self, commit=True):
        instance = super(LoanForm, self).save(commit=False)
        if commit:
            instance.save()
        return instance


class LoanCycleDayForm(ModelForm):

    class Meta(object):
        model = Loan

        fields = (
            'cycle_day_requested',
        )
        # exclude = ('cdate', 'udate' )
        widgets = {
            'cycle_day_requested':TextInput(attrs={
                'size':model._meta.get_field('cycle_day_requested').max_length,
                'class':'form-control maskNumber',
                'maxlength': 2,
                'placeholder':'eg: 1 to 12 '}),
        }
        error_messages = {
            'cycle_day_requested': {
                'required': _("cycle day requested tidak boleh kosong!"),
            },
        }

    def clean(self):
        # Running parent process for Clean()
        cleaned_data = super(LoanCycleDayForm, self).clean()

        # Validating
        return cleaned_data

    def save(self, commit=True):
        instance = super(LoanCycleDayForm, self).save(commit=False)
        if commit:
            instance.save()
        return instance

class NewPaymentInstallmentForm(forms.Form):

    id_first_payment_installment = forms.CharField(
        widget  = TextInput(attrs={
                'required':  _("new installment tidak boleh kosong!"),
                'class':'form-control odatepicker',
                'id': 'id_first_payment_installment',
                'readonly': 'readonly'
                }),
    )


    def __init__(self, *args, **kwargs):
        super(NewPaymentInstallmentForm, self).__init__(*args, **kwargs)


class StatusChangesForm(forms.Form):
    """
        please use ModelChoiceField instead of ChoiceField if using queryset
    """

    status_to = forms.ChoiceField(
        required=True,
        widget=Select(attrs={'class': 'form-control'}),
    )
    reason = forms.CharField(widget=forms.HiddenInput(), required=False)
    notes = forms.CharField(
        required=False,
        widget=Textarea(attrs={
            'rows': 6,
            'class': 'form-control',
            'placeholder': 'Insert notes here'
        }),
    )
    notes_only = forms.CharField(
        required=False,
        widget=Textarea(attrs={
            'rows': 6,
            'class': 'form-control',
            'placeholder': 'Insert notes here'
        }),
    )

    def __init__(self, status_code, loan_id, *args, **kwargs):
        super(StatusChangesForm, self).__init__(*args, **kwargs)

        # get allow status from julo core service
        status_choices = []
        allowed_statuses = get_allowed_loan_statuses(
            int(status_code.status_code), loan_id)

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