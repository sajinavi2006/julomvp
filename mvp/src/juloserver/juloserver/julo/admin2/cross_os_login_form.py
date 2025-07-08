from django import forms
from juloserver.julo.models import FeatureSetting


class CrossOSLoginForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(CrossOSLoginForm, self).__init__(*args, **kwargs)

    class Meta:
        model = FeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters': '<br><b>Description:</b><br>'
            '1. If the setting is <b>NOT active</b>, the users will NOT be able to cross OS at all <br>'
            '2. If the setting is <b>active</b>, the users will be able to cross OS at the specified status code and onwards <br>'
            '3. "status_code": x190 means users can only login cross OS at status x190 and onwards (there is no status after x190, really)<br>'
            '&nbsp;&nbsp;&nbsp; i.e. they will not be able to cross OS at x100, x105, x120, x131, etc. <br>'
            '4. "status_code": x105 means users can only login cross OS at status x105 and onwards <br>'
            '&nbsp;&nbsp;&nbsp; i.e. they will not be able to cross OS at x100 <br>'
            '5. <b>(Hardcorde implemented)</b> allow <b>x105 C</b> to be able to cross OS <br>'
            '6. For the example format parameters:<br>'
            '{"status_code": "x190", "expiry_status_code": [106, 135, 136, 185, 186, 133]}'
        }

    def clean(self):
        data = super(CrossOSLoginForm, self).clean()

        parameters = data.get('parameters')
        error_message = validate_param(parameters)
        if error_message:
            raise forms.ValidationError(error_message)

        return data


def validate_param(parameters):

    status_code = parameters.get('status_code', None)
    if not status_code:
        return 'Parameters status_code cannot empty'

    if not isinstance(status_code, str):
        return 'Parameters status_code must be string, please check in Description "Example parameters".'

    return None
