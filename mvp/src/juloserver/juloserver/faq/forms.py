from django import forms
from juloserver.faq.models import Faq


class FaqForm(forms.ModelForm):
    class Meta:
        model = Faq
        fields = '__all__'
