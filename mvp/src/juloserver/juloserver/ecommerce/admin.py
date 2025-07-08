import re

from builtins import object
from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django import forms
from .models import (
    EcommerceConfiguration,
    EcommerceBankConfiguration,
)


class EcommerceConfigurationForm(forms.ModelForm):
    class Meta(object):
        model = EcommerceConfiguration
        fields = '__all__'


class EcommerceConfigurationAdmin(ModelAdmin):
    form = EcommerceConfigurationForm
    list_display = (
        'id',
        'ecommerce_name',
        'color_scheme',
        'order_number'
    )
    actions_on_bottom = True
    save_on_top = True


class EcommerceBankConfigurationForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(EcommerceBankConfigurationForm, self).__init__(*args, **kwargs)
        self.fields['prefix'].help_text = (
            'Prefix can be multiple, '
            'please separate it using comma(,) '
            'and prefix should be number'
        )

    class Meta(object):
        model = EcommerceBankConfiguration
        fields = ('ecommerce_configuration', 'bank', 'prefix', 'is_active')

    def clean(self):
        existing_bank_config = EcommerceBankConfiguration.objects.filter(
            ecommerce_configuration=self.cleaned_data['ecommerce_configuration'],
            bank=self.cleaned_data['bank']
        ).exclude(pk=self.instance.pk).last()
        if existing_bank_config:
            ecommerce_name = "Ecommerce"
            ecommerce_configuration = existing_bank_config.ecommerce_configuration
            if ecommerce_configuration:
                ecommerce_name = ecommerce_configuration.ecommerce_name

            bank = existing_bank_config.bank
            bank_name = bank.bank_name_frontend if bank else 'Bank'

            raise forms.ValidationError(
                "{} already have {} for prefix with ID {}".format(
                    ecommerce_name,
                    bank_name,
                    existing_bank_config.id
                )
            )

        prefixes = self.cleaned_data['prefix']
        for prefix in prefixes:
            if not re.match("^\\d+$", prefix):
                raise forms.ValidationError("Wrong format for {} prefix".format(prefix))

            existing_bank_config = EcommerceBankConfiguration.objects.filter(
                prefix__overlap=[prefix]
            ).exclude(id=self.instance.pk).exists()
            if existing_bank_config:
                ecommerce_name = "Ecommerce"
                ecommerce_configuration = existing_bank_config.ecommerce_configuration
                if ecommerce_configuration:
                    ecommerce_name = ecommerce_configuration.ecommerce_name

                bank = existing_bank_config.bank
                bank_name = bank.bank_name_frontend if bank else 'Bank'

                raise forms.ValidationError(
                    "Prefix {} already registered on {} for {}".format(
                        prefix,
                        bank_name,
                        ecommerce_name
                    )
                )


class EcommerceBankConfigurationAdmin(ModelAdmin):
    form = EcommerceBankConfigurationForm
    list_display = (
        'id',
        'ecommerce_configuration',
        'bank',
        'prefix',
        'is_active',
    )
    actions_on_bottom = True
    save_on_top = True


admin.site.register(EcommerceConfiguration, EcommerceConfigurationAdmin)
admin.site.register(EcommerceBankConfiguration, EcommerceBankConfigurationAdmin)
