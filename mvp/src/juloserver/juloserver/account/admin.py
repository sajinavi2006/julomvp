from django.contrib import admin
from django import forms
from juloserver.account.models import PaymentMethodMapping


class PaymentMethodMappingModelForm(forms.ModelForm):
    class Meta:
        model = PaymentMethodMapping
        fields = ('payment_method_name', 'visible_payment_method_name')

    def clean(self):
        cleaned_data = super().clean()
        payment_method_name = cleaned_data.get('payment_method_name')

        payment_method_mapping = PaymentMethodMapping.objects.filter(
            payment_method_name=payment_method_name
        )

        if self.instance and self.instance.pk:
            payment_method_mapping = payment_method_mapping.exclude(pk=self.instance.pk)

        if payment_method_mapping.exists():
            raise forms.ValidationError('Payment method name already exist.')

        return cleaned_data


class PaymentMethodMappingAdmin(admin.ModelAdmin):
    form = PaymentMethodMappingModelForm
    list_display = ('id', 'payment_method_name', 'visible_payment_method_name')


admin.site.register(PaymentMethodMapping, PaymentMethodMappingAdmin)
