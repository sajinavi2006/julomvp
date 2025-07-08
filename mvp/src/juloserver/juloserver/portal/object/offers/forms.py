from __future__ import unicode_literals

from builtins import object
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _

from django import forms
from django.forms import ModelForm
from django.forms.widgets import TextInput, Textarea
from django.forms.widgets import RadioSelect, Select

from juloserver.julocore.python2.utils import py2round
from juloserver.julo.models import StatusLookup, Offer
from juloserver.julo.models import ProductLookup
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.apiv2.credit_matrix2 import get_score_rate
from juloserver.julo.services import get_credit_score3
from juloserver.apiv2.constants import CreditMatrixType


PERIODE_CHOICES = ((True, _('Hari ini')), (False, _('Bebas')))


class HorizontalRadioRenderer(forms.RadioSelect.renderer):
    def render(self):
        return mark_safe(u'&nbsp;&nbsp;&nbsp;\n'.join([u'%s\n' % w for w in self]))


class OfferSearchForm(forms.Form):

    def __init__(self, *args, **kwargs):
        super(OfferSearchForm, self).__init__(*args, **kwargs)

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

    status_app = forms.ModelChoiceField(required=False,
                    queryset=StatusLookup.objects.filter(status_code__range=[100, 199]).order_by('status_code'),
                    widget = Select(attrs={
                        'class':'form-control',
                        })
                    )

    status_now = forms.ChoiceField(required=False,
                    choices=PERIODE_CHOICES,
                    widget = RadioSelect(renderer=HorizontalRadioRenderer))


class NoteForm(forms.Form):

    notes = forms.CharField(required = True,
        widget  = Textarea(attrs={ 'rows': 5,
                    'class': 'form-control',
                    'required': False,
                    'placeholder':'Masukan catatan pada applikasi ini'}),
    )

    def clean_notes(self):
        if 'notes' in self.cleaned_data:
            # check if they not null each other
            notes = self.cleaned_data['notes']
            if notes:
                return notes
        raise forms.ValidationError("Notes Tidak Boleh Kosong !!!")


class OfferForm(ModelForm):

    class Meta(object):
        model = Offer

        fields = (
            'product',
            'loan_amount_offer',
            'loan_duration_offer',
            'installment_amount_offer',
            'first_installment_amount',
            'first_payment_date'
        )
        widgets = {

            'product':Select(attrs={
                'size':model._meta.get_field('product').max_length,
                'class':'form-control',
                'maxlength':model._meta.get_field('product').max_length,
                'placeholder':'masukan nama bank '}),
            'loan_amount_offer':TextInput(attrs={
                'class':'form-control mask',
                'maxlength':model._meta.get_field('loan_amount_offer').max_length,
                'placeholder':'Loan Amount Offer'
                }),
            'loan_duration_offer':TextInput(attrs={
                'class':'form-control maskNumber',
                'maxlength': 2,
                'placeholder':'Loan Duration Offer'
                }),
            'installment_amount_offer':TextInput(attrs={
                'class':'form-control',
                'readonly': '',
                'maxlength':model._meta.get_field('installment_amount_offer').max_length,
                'placeholder':'Loan Amount Offer'
                }),
            'first_installment_amount':TextInput(attrs={
                'class':'form-control p_installment_amount',
                'id': 'p_installment_amount',
                'maxlength':model._meta.get_field('first_installment_amount').max_length,
                'readonly': '',
                'placeholder':'First Installment Amount Offer'
                }),
            'first_payment_date':TextInput(attrs={
                'class':'form-control odatepicker',
                'id': 'p_installment_date',
                'maxlength':model._meta.get_field('first_payment_date').max_length,
                'placeholder':'First Payment Date Offer'
                }),

        }
        error_messages = {
            'product': {
                'required': _("Nama Product belum dipilih!"),
            },
        }

    def __init__(self, *args, **kwargs):
        super(OfferForm, self).__init__(*args, **kwargs)

        if 'instance' not in kwargs:
            raise Exception

        offer = kwargs['instance']
        product_line = offer.application.product_line
        product_lookup_qs = ProductLookup.objects.filter(
            product_line=product_line)
        application = offer.application

        if product_line.product_line_code in ProductLineCodes.mtl():
            credit_score = get_credit_score3(offer.application)
            rate = product_line.max_interest_rate
            if credit_score:
                customer = application.customer
                credit_matrix_type = CreditMatrixType.WEBAPP if application.is_web_app() else (
                    CreditMatrixType.JULO if not customer.is_repeated else CreditMatrixType.JULO_REPEAT)
                rate = get_score_rate(credit_score, credit_matrix_type,
                    product_line.product_line_code, rate, application.job_type)
                interest_rate = py2round(rate * 12, 2)
                product_lookup_qs = product_lookup_qs.filter(interest_rate = interest_rate)

        self.fields['product'].queryset = product_lookup_qs

    def clean(self):
        # Running parent process for Clean()
        cleaned_data = super(OfferForm, self).clean()

        # Validating
        return cleaned_data

    def save(self, commit=True):
        instance = super(OfferForm, self).save(commit=False)
        if commit:
            instance.save()
        return instance
