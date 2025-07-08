from django import forms
import re

from juloserver.julo.models import Partner
from django.contrib.auth.models import User
from juloserver.julo.utils import check_email

class MerchantPartnerAdminForm(forms.ModelForm):
    name = forms.CharField(
        required=True
    )
    email = forms.CharField(
        required=True
    )


    class Meta:
        model = Partner
        fields = ("name", "email", "is_active")

    def __init__(self, *args, **kwargs):
        self.instance = kwargs.get('instance', None)
        super(MerchantPartnerAdminForm, self).__init__(*args, **kwargs)
        dict_error_messages = {
            'required': 'This field is required.',
            'invalid': ""
        }
        self.fields['name'].error_messages.update(dict_error_messages)
        self.fields['email'].error_messages.update(dict_error_messages)

    def clean(self):
        cleaned_data = super().clean()
        instance = self.instance
        name = self.cleaned_data.get("name")
        email = self.cleaned_data.get("email")
        if name is None or email is None:
            raise forms.ValidationError('')

        if name and not re.match(r'^[A-Za-z0-9_]*$', name):
            raise forms.ValidationError(
                {'name': ['Username tidak valid', ]}
            )
        existing_name = None
        existing_email = None
        if instance.id is not None:
            partner = Partner.objects.get(id=instance.id)
            if partner:
                existing_name = User.objects.filter(username=name).exclude(id=partner.user.id).first()
                existing_email = Partner.objects.filter(email=email).\
                    exclude(id=partner.id)
        else:
            existing_name = User.objects.filter(username=name).first()
            existing_email = Partner.objects.filter(email=email)

        if existing_name:
            raise forms.ValidationError(
                {'name': ['Username Anda sudah terdaftar', ]}
            )

        if existing_email:
            raise forms.ValidationError(
                {'email': ['Email Anda sudah terdaftar', ]}
            )

        email = email.strip().lower()
        if not check_email(email):
            raise forms.ValidationError(
                {'email': ['Email tidak valid', ]}
            )

        return cleaned_data
