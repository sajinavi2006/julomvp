from django import forms
from juloserver.julo.models import FeatureSetting
from juloserver.registration_flow.constants import ConfigUserJstarterConst


class ConfigSpecificUserForJstarter(forms.ModelForm):
    operation = forms.ChoiceField(
        widget=forms.RadioSelect(attrs={'class': 'action-control'}),
        required=True, label='Operations')
    value_data = forms.CharField(
        widget=forms.TextInput(attrs={'size': 40}),
        required=True, label='Value')

    def __init__(self, *args, **kwargs):
        super(ConfigSpecificUserForJstarter, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        option_flows = [
            ('contain', 'Contains'),
            ('equal', 'Equal'),
        ]

        if instance:
            self.fields['operation'].choices = option_flows
            if instance.parameters:
                param = instance.parameters
                self.fields['operation'].initial = 'equal' if param['operation'] == 'equal' else 'contain'
                self.fields['value_data'].initial = param['value']

    class Meta:
        model = FeatureSetting
        exclude = ['id', 'parameters']

    def clean(self):
        data = super(ConfigSpecificUserForJstarter, self).clean()
        operation = data.get('operation')
        value_data = data.get('value_data')

        if not operation:
            raise forms.ValidationError(
                "Please check one operation for enable."
            )

        if not value_data:
            raise forms.ValidationError(
                "Please check form required."
            )

        return data


def binding_param(operation, value_data):
    default_param = {
        ConfigUserJstarterConst.OPERATION_KEY: ConfigUserJstarterConst.EQUAL_KEY,
        ConfigUserJstarterConst.VALUE_KEY: "",
    }

    if operation not in (
        ConfigUserJstarterConst.EQUAL_KEY,
        ConfigUserJstarterConst.CONTAIN_KEY,
    ):
        # return default param
        return default_param

    # set the parameters
    default_param['operation'] = operation
    default_param['value'] = value_data

    return default_param


def save_model_config_specific_jstarter(obj, form):
    data = form.data

    # prepare data field for update
    obj.parameters = binding_param(
        data.get('operation'),
        data.get('value_data')
    )
