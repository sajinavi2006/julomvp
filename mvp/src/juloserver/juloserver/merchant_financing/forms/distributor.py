from django import forms
from django.forms import TextInput

from juloserver.merchant_financing.services import BankAccount

from juloserver.julo.models import (
    Partner, Bank,
)

from juloserver.partnership.models import Distributor
from juloserver.partnership.constants import ErrorMessageConst

from juloserver.disbursement.constants import NameBankValidationStatus


class DistributorForm(forms.ModelForm):
    bank_name = forms.ChoiceField(
        required=True,
    )

    class Meta:
        model = Distributor
        fields = "__all__"
        widgets = {
            'name': TextInput(),
            'bank_name': TextInput(),
            'bank_account_name': TextInput(),
            'bank_account_number': TextInput(),
            'phone_number': TextInput(),
            'type_of_business': TextInput(),
            'npwp': TextInput(),
            'nib': TextInput(),
            'external_distributor_id': TextInput(),
        }

    def __init__(self, *args, **kwargs):
        super(DistributorForm, self).__init__(*args, **kwargs)
        self.fields['partner'].queryset = Partner.objects.filter(is_active=True)
        banks = tuple(
            Bank.objects.only('bank_name').filter(is_active=True).values_list(
                'bank_name', 'bank_name'
            )
        )
        self.fields['bank_name'].choices = banks
        if self.instance.id:
            self.fields['bank_name'].initial = (self.instance.bank_name, self.instance.bank_name)
            self.fields['name_bank_validation'].initial = self.instance.name_bank_validation

    def clean(self):
        cleaned_data = super().clean()
        bank_name = self.cleaned_data.get("bank_name")
        bank_account_number = self.cleaned_data.get("bank_account_number")
        bank_account_name = self.cleaned_data.get("bank_account_name")
        phone_number = self.cleaned_data.get("phone_number")

        bank_account_data = [bank_account_number, bank_account_name, bank_account_number]
        if None not in bank_account_data:
            if not self.instance or \
                    (bank_name != self.instance.bank_name or
                     bank_account_name != self.instance.bank_account_name or
                     bank_account_number != self.instance.bank_account_number):
                bank = Bank.objects.filter(bank_name=bank_name).last()
                bank_account = BankAccount()
                response = bank_account.inquiry_bank_account(
                    bank_code=bank.xfers_bank_code, bank_account_number=bank_account_number,
                    phone_number=phone_number, name_in_bank=bank_account_name
                )
                if response['status'] != NameBankValidationStatus.SUCCESS:
                    raise forms.ValidationError(
                        {'bank_account_name': ["There was an error in xfers, please try again and "
                                               "check the data",
                                               response['error_message']]}
                    )
                elif response['validated_name'].lower() != bank_account_name.lower():
                    raise forms.ValidationError(
                        {'bank_account_name': ['Data not valid', ]}
                    )
                self.cleaned_data['name_bank_validation'] = response.get('name_bank_validation')

        return cleaned_data
