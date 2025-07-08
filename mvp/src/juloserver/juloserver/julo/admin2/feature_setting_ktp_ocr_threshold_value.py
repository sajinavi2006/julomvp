from django import forms
from juloserver.julo.models import FeatureSetting


class KTPThresholdValueForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super(KTPThresholdValueForm, self).__init__(*args, **kwargs)

    class Meta:
        model = FeatureSetting
        exclude = ['id']

    def clean(self):
        data = super(KTPThresholdValueForm, self).clean()

        key, error_message = validate_param(data)
        if error_message:
            error_append = None
            if key:
                error_append = 'Key [{0}] is not valid: '.format(key)

            raise forms.ValidationError('{0} {1}'.format(error_append, error_message))

        return data


def validate_param(data):

    parameters = data.get('parameters', None)
    error_message = 'Please input threshold value only range 0-100'

    if not parameters:
        return None, 'Parameters cannot empty'

    if parameters:
        for key in parameters:
            try:
                threshold = parameters[key].get('threshold', None)
                if not isinstance(threshold, int):
                    return key, error_message

                if 0 > threshold or threshold > 100:
                    return key, error_message
            except ValueError as error:
                return None, str(error)

    return None, None
