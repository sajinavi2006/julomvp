from builtins import object
from django import forms
from .models import CashbackPromo

class CashbackPromoTemplateForm(forms.ModelForm):
    class Meta(object):
        model = CashbackPromo
        fields = [
            'promo_name',
            'department',
            'pic_email',
        ]

    def clean_pic_email(self):
        pic_email = self.cleaned_data['pic_email']
        if pic_email.split('@')[1] not in ('julo.co.id', 'julofinance.com'):
            raise forms.ValidationError("Email must be @julo.co.id or @julofinance.com")
        return pic_email
