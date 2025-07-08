from django import forms
from juloserver.partnership.models import PartnershipUser
from juloserver.julo.models import Partner
from django.contrib.auth.models import User


class PartnershipUserAdminForm(forms.ModelForm):
    user = forms.CharField(
        required=True
    )
    partner = forms.ModelChoiceField(required=True,
                                     queryset=Partner.objects.all(),
                                     initial=0

    )

    def __init__(self, *args, **kwargs):
        self.instance = kwargs.get('instance', None)
        super().__init__(*args, **kwargs)
        try:
            self.initial['user'] = self.instance.user.username
        except:
            pass

    def clean(self):
        cleaned_data = super().clean()
        instance = self.instance
        user = username = self.cleaned_data.get("user")
        partner = self.cleaned_data.get("partner")
        user = User.objects.filter(username=user).last()
        existing_user_partner = None
        if user:
            if instance.id:
                user_partner = PartnershipUser.objects.get(id=instance.id)
                if user_partner:
                    existing_user_partner = PartnershipUser.objects.filter(
                        user=user,
                        partner=partner
                    ).exclude(id=user_partner.id).exists()
            else:
                existing_user_partner = PartnershipUser.objects.filter(
                    user=user, partner=partner
                ).exists()

            if existing_user_partner:
                raise forms.ValidationError(
                    {'user': ['This partner already assigned for this user', ]}
                )
        else:
            if username:
                raise forms.ValidationError(
                    {'user': ['This username not exists', ]}
                )
        cleaned_data['user'] = user
        return cleaned_data
