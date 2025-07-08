from builtins import str

from dashboard.models import CRMSetting
from django import forms

from .functions import create_or_update_defaultrole


class DefaultRoleForm(forms.Form):

    role_default = forms.CharField(
        max_length=CRMSetting._meta.get_field('role_default').max_length,
        widget=forms.Select(
            attrs={
                'class': 'form-control',
                'required': "",
            }
        ),
        label='Pilih Default Role',
    )

    def __init__(self, user_instance, *args, **kwargs):
        super(DefaultRoleForm, self).__init__(*args, **kwargs)
        self.user = user_instance
        qs = self.user.groups.all()
        self.fields['role_default'] = forms.ChoiceField(choices=[(str(o), str(o)) for o in qs])

    def clean_role_default(self):
        if 'role_default' in self.cleaned_data:
            # check if they not null each other
            role_default = self.cleaned_data['role_default']
            if role_default:
                return role_default
            else:
                raise forms.ValidationError("Role Default harus dipilih !!!")
        raise role_default

    def save(self, commit=True):
        if commit:
            return create_or_update_defaultrole(self.user, self.cleaned_data['role_default'])
        return None
