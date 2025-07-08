from django import forms
from juloserver.julo.models import FeatureSetting


class ConfigFlowToLimitJstarterForm(forms.ModelForm):
    enable_for = forms.ChoiceField(
        widget=forms.RadioSelect(attrs={'class': 'action-control'}),
        required=True)

    def __init__(self, *args, **kwargs):
        super(ConfigFlowToLimitJstarterForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        option_flows = [
            ('full_dv', 'Full DV'),
            ('partial_limit', 'Partial Limit'),
        ]

        if instance:
            self.fields['enable_for'].choices = option_flows
            if instance.parameters:
                param = instance.parameters
                self.fields['enable_for'].initial = 'full_dv' if param['full_dv'] == 'enabled' else 'partial_limit'

    class Meta:
        model = FeatureSetting
        exclude = ['id', 'parameters']

    def clean(self):
        data = super(ConfigFlowToLimitJstarterForm, self).clean()
        enable_for = data.get('enable_for')
        is_active = data.get('is_active')

        if enable_for is None:
            raise forms.ValidationError(
                "Please check one flow for enable."
            )

        if not is_active:
            raise forms.ValidationError(
                "This configuration need to always active. Please check is_active."
            )

        return data


def binding_param(value):
    default_param = {
        'full_dv': 'disabled',
        'partial_limit': 'disabled'
    }

    if value == 'full_dv':
        default_param['full_dv'] = 'enabled'
    elif value == 'partial_limit':
        default_param['partial_limit'] = 'enabled'

    return default_param


def save_model_config_jstarter(obj, form):
    data = form.data
    enable_for = data.get('enable_for')

    # prepare data field for update
    obj.is_active = data.get('is_active')
    obj.category = data.get('category')
    obj.description = data.get('description')
    obj.parameters = binding_param(enable_for)
