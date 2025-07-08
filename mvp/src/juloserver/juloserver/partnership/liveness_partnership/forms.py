from django import forms

from juloserver.julo.models import Partner


class LivenessConfigurationAdminForm(forms.ModelForm):
    partner_id = forms.ModelChoiceField(
        required=True,
        queryset=Partner.objects.all(),
        initial=0,
        label="Partner",
        help_text="Select the partner for this configuration",
    )
    platform = forms.ChoiceField(
        choices=[
            ('web', 'Web'),
            ('ios', 'iOS'),
            ('android', 'Android'),
            ('desktop', 'Desktop'),
        ],
        required=True,
        label="Platform",
        help_text="Select the platform: web, iOS, or Android, Desktop",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Update the choices dynamically
        current_instance = kwargs.get('instance', None)
        if current_instance and current_instance.partner_id:
            # If editing, show only the current partner and other partners
            self.fields['partner_id'].choices = [
                (partner.id, partner.name) for partner in Partner.objects.all()
            ]
            self.fields['partner_id'].initial = current_instance.partner_id
        else:
            # If creating, show all partners
            self.fields['partner_id'].choices = [
                (partner.id, partner.name) for partner in Partner.objects.all()
            ]

    def clean_partner_id(self):
        # Ensure partner_id is converted to integer
        partner = self.cleaned_data.get('partner_id')
        return partner.id
