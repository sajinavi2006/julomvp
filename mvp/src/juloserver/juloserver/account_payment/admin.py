import re

from django.contrib import admin
from django import forms

from juloserver.julo.admin import JuloModelAdmin

from juloserver.account_payment.models import PaymentMethodInstruction


class PaymentMethodInstructionForm(forms.ModelForm):

    class Meta(object):
        model = PaymentMethodInstruction
        fields = ('global_payment_method', 'title', 'content', 'is_active',)

    def clean_content(self):
        return re.sub(r"[\n\t\r]", "", self.cleaned_data['content'])


class PaymentMethodInstructionAdmin(JuloModelAdmin):
    form = PaymentMethodInstructionForm
    list_display = ('id', 'global_payment_method', 'title', 'content', 'is_active')
    list_select_related = (
        'global_payment_method',
    )


admin.site.register(PaymentMethodInstruction, PaymentMethodInstructionAdmin)
