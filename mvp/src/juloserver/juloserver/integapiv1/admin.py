from django.contrib import admin
from django import forms
from django.conf import settings

from juloserver.julo.admin import JuloModelAdmin

from juloserver.integapiv1.models import (
    EscrowPaymentGateway,
    EscrowPaymentMethodLookup,
    EscrowPaymentMethod,
)


class EscrowPaymentGatewayAdmin(JuloModelAdmin):
    list_display = ('id', 'owner', 'description')


class EscrowPaymentMethodLookupAdmin(JuloModelAdmin):
    list_display = ('id', 'payment_method_code', 'payment_method_name')


class EscrowPaymentMethodForm(forms.ModelForm):

    class Meta(object):
        model = EscrowPaymentMethod
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        virtual_account = self.cleaned_data.get("virtual_account")
        if self.instance:
            virtual_account = self.instance.virtual_account
        if not virtual_account:
            escrow_payment_method_lookup = self.cleaned_data.get("escrow_payment_method_lookup")
            escrow_payment_gateway = self.cleaned_data.get("escrow_payment_gateway")
            suffix = '{}{}'.format(escrow_payment_method_lookup.id, escrow_payment_gateway.id)
            virtual_account = '{}{}'.format(escrow_payment_method_lookup.payment_method_code,
                                            suffix.zfill(11))
            is_virtual_account_exists = EscrowPaymentMethod.objects.filter(
                virtual_account=virtual_account
            ).exists()
            if is_virtual_account_exists:
                raise forms.ValidationError('virtual account already exists')
            cleaned_data["virtual_account"] = virtual_account

        return cleaned_data

    def save(self, commit=True):
        instance = super(EscrowPaymentMethodForm, self).save(commit=False)
        if not instance.virtual_account:
            instance.virtual_account = self.cleaned_data.get('virtual_account')
        if commit:
            instance.save()

        return instance


class EscrowPaymentMethodAdmin(JuloModelAdmin):
    form = EscrowPaymentMethodForm
    list_display = ('id', 'escrow_payment_gateway', 'escrow_payment_method_lookup',
                    'virtual_account')
    readonly_fields = ('virtual_account',)

    def get_form(self, request, obj=None, *args, **kwargs):
        kwargs['form'] = EscrowPaymentMethodForm
        form = super(EscrowPaymentMethodAdmin, self).get_form(request, *args, **kwargs)
        form_partner_escrow_payment_gateway = form.base_fields['escrow_payment_gateway']
        form_partner_escrow_payment_gateway.widget.can_add_related = False
        form_partner_escrow_payment_gateway.widget.can_change_related = False
        form_partner_escrow_payment_gateway.widget.can_delete_related = False
        form_partner_escrow_payment_method_lookup = form.base_fields['escrow_payment_method_lookup']
        form_partner_escrow_payment_method_lookup.widget.can_add_related = False
        form_partner_escrow_payment_method_lookup.widget.can_change_related = False
        form_partner_escrow_payment_method_lookup.widget.can_delete_related = False
        return form


admin.site.register(EscrowPaymentGateway, EscrowPaymentGatewayAdmin)
admin.site.register(EscrowPaymentMethodLookup, EscrowPaymentMethodLookupAdmin)
admin.site.register(EscrowPaymentMethod, EscrowPaymentMethodAdmin)
