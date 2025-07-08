from django import forms
from django.db import transaction
from django.contrib.auth.models import Group, User
from django.contrib.auth.hashers import make_password

from juloserver.customer_module.models import (
    BankAccountDestination,
    BankAccountCategory
)
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.api_token.authentication import make_never_expiry_token
from juloserver.julo.models import (
    Bank,
    Customer,
    SepulsaProduct
)
from juloserver.merchant_financing.services import BankAccount
from juloserver.disbursement.constants import NameBankValidationStatus


class PartnerExtendForm(forms.ModelForm):
    partner_bank_name = forms.ChoiceField(
        required=True,
    )
    logo = forms.ImageField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['logo'].required = False
        banks = tuple(
            Bank.objects.only('bank_name').filter(is_active=True).values_list(
                'bank_name', 'bank_name'
            )
        )
        self.fields['partner_bank_name'].choices = banks
        if self.instance.id:
            self.fields['partner_bank_name'].initial = (self.instance.partner_bank_name, self.instance.partner_bank_name)
            self.fields['name_bank_validation'].initial = self.instance.name_bank_validation

    def clean(self):
        cleaned_data = super().clean()
        partner_bank_name = self.cleaned_data.get("partner_bank_name")
        partner_bank_account_number = self.cleaned_data.get("partner_bank_account_number")
        partner_bank_account_name = self.cleaned_data.get("partner_bank_account_name")
        email = self.cleaned_data.get('email')
        phone_number = self.cleaned_data.get("phone")
        if phone_number:
            phone_number = phone_number.as_e164.replace('+62', '0')
        partner_bank_account_data = {
            partner_bank_account_number,
            partner_bank_account_name,
            email
        }
        self.cleaned_data['recipients_email_address_for_bulk_disbursement'] = self.cleaned_data. \
            get('recipients_email_address_for_bulk_disbursement').replace(" ", "")
        self.cleaned_data['recipients_email_address_for_190_application'] = self.cleaned_data. \
            get('recipients_email_address_for_190_application').replace(" ", "")
        self.cleaned_data['cc_email_address_for_bulk_disbursement'] = self.cleaned_data. \
            get('cc_email_address_for_bulk_disbursement').replace(" ", "")
        self.cleaned_data['cc_email_address_for_190_application'] = self.cleaned_data. \
            get('cc_email_address_for_190_application').replace(" ", "")
        product_line = self.cleaned_data.get("product_line")
        if cleaned_data.get('is_csv_upload_applicable'):
            if product_line is None:
                raise forms.ValidationError(
                    "If is_csv_upload_applicable is True, "
                    "then product_line should be selected"
                )

        is_disbursement_to_partner_bank_account = cleaned_data.get('is_disbursement_to_partner_bank_account')
        is_disbursement_to_distributor_bank_account = cleaned_data.get(
            'is_disbursement_to_distributor_bank_account')
        if is_disbursement_to_partner_bank_account:
            if None in partner_bank_account_data or '' in partner_bank_account_data \
                    or is_disbursement_to_distributor_bank_account:
                raise forms.ValidationError(
                    "If is_disbursement_to_partner_bank is True, "
                    "then partner_bank_account_number, partner_bank_account_name "
                    "and email should be filled and is_disbursement_to_distributor_bank_account "
                    "should be false"
                )
            else:
                if not self.instance or (
                        partner_bank_name != self.instance.partner_bank_name
                        or partner_bank_account_number != self.instance.partner_bank_account_number
                        or partner_bank_account_name != self.instance.partner_bank_account_name
                ):
                    with transaction.atomic():
                        bank = Bank.objects.filter(bank_name=partner_bank_name).first()
                        bank_account = BankAccount()
                        response = bank_account.inquiry_bank_account(
                            bank_code=bank.xfers_bank_code,
                            bank_account_number=partner_bank_account_number,
                            phone_number=phone_number,
                            name_in_bank=partner_bank_account_name
                        )
                        if response['status'] != NameBankValidationStatus.SUCCESS:
                            raise forms.ValidationError(
                                {"There was an error in xfers, please try again and "
                                 "check the data",
                                 response['error_message']}
                            )
                        elif response['validated_name'].lower() != partner_bank_account_name.lower():
                            raise forms.ValidationError(
                                {'partner_bank_account_name': ['Data not valid', ]}
                            )
                        self.cleaned_data['name_bank_validation'] = response.get('name_bank_validation')
                        name_bank_validation = response.get('name_bank_validation')

                        partner_name = self.cleaned_data.get('name').replace(' ', '_')
                        partner_email = email
                        if not self.instance.user:
                            group = Group.objects.get(name="julo_partners")
                            password = make_password('partner')
                            user = User.objects.create(
                                username=partner_name,
                                email=partner_email,
                                password=password
                            )

                            user.groups.add(group)
                            make_never_expiry_token(user)
                            self.cleaned_data['user'] = user

                            customer = Customer.objects.create(user=user, email=partner_email)
                        else:
                            customer = Customer.objects.filter(user=self.instance.user).first()
                            if not customer:
                                customer = Customer.objects.create(
                                    user=self.instance.user,
                                    email=partner_email
                                )

                        partner_bank_account_category = BankAccountCategory.objects.filter(
                            category=BankAccountCategoryConst.PARTNER
                        ).last()
                        BankAccountDestination.objects.create(
                            bank_account_category=partner_bank_account_category,
                            customer=customer,
                            bank=bank,
                            account_number=partner_bank_account_number,
                            name_bank_validation=name_bank_validation,
                            description='{} bank account'.format(partner_name)
                        )

        if is_disbursement_to_distributor_bank_account:
            if None in partner_bank_account_data or '' in partner_bank_account_data \
                    or is_disbursement_to_partner_bank_account:
                raise forms.ValidationError(
                    "If is_disbursement_to_distributor_bank_account is True, "
                    "then partner_bank_account_number, partner_bank_account_name "
                    "and email should be filled and is_disbursement_to_partner_bank_account "
                    "should be false"
                )
            else:
                if not self.instance or (
                        partner_bank_name != self.instance.partner_bank_name
                        or partner_bank_account_number != self.instance.partner_bank_account_number
                        or partner_bank_account_name != self.instance.partner_bank_account_name
                ):
                    with transaction.atomic():
                        bank = Bank.objects.filter(bank_name=partner_bank_name).first()
                        bank_account = BankAccount()
                        response = bank_account.inquiry_bank_account(
                            bank_code=bank.xfers_bank_code,
                            bank_account_number=partner_bank_account_number,
                            phone_number=phone_number,
                            name_in_bank=partner_bank_account_name
                        )
                        if response['status'] != NameBankValidationStatus.SUCCESS:
                            raise forms.ValidationError(
                                {"There was an error in xfers, please try again and "
                                 "check the data",
                                 response['error_message']}
                            )
                        elif response['validated_name'].lower() != partner_bank_account_name.lower():
                            raise forms.ValidationError(
                                {'partner_bank_account_name': ['Data not valid', ]}
                            )
                        self.cleaned_data['name_bank_validation'] = response.get('name_bank_validation')
                        name_bank_validation = response.get('name_bank_validation')

                        partner_name = self.cleaned_data.get('name').replace(' ', '_')
                        partner_email = email
                        if not self.instance.user:
                            group = Group.objects.get(name="julo_partners")
                            password = make_password('partner')
                            user = User.objects.create(
                                username=partner_name,
                                email=partner_email,
                                password=password
                            )

                            user.groups.add(group)
                            make_never_expiry_token(user)
                            self.cleaned_data['user'] = user

                            customer = Customer.objects.create(user=user, email=partner_email)
                        else:
                            customer = Customer.objects.filter(user=self.instance.user).first()
                            if not customer:
                                customer = Customer.objects.create(
                                    user=self.instance.user,
                                    email=partner_email
                                )

                        partner_bank_account_category = BankAccountCategory.objects.filter(
                            category=BankAccountCategoryConst.PARTNER
                        ).last()
                        BankAccountDestination.objects.create(
                            bank_account_category=partner_bank_account_category,
                            customer=customer,
                            bank=bank,
                            account_number=partner_bank_account_number,
                            name_bank_validation=name_bank_validation,
                            description='{} bank account'.format(partner_name)
                        )

        return cleaned_data


class SepulsaProductForm(forms.ModelForm):
    class Meta:
        model = SepulsaProduct
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super(SepulsaProductForm, self).__init__(*args, **kwargs)
        self.fields['operator'].required = False
