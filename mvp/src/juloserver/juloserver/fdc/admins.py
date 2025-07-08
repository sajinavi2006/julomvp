import re

from django import forms

from juloserver.julo.models import FeatureSetting


class FdcTimeoutSettingForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        fields = "__all__"

    def clean_parameters(self):
        parameters = self.cleaned_data['parameters']
        regex = r'^([01]\d|20|21|22|23)-([01]\d|20|21|22|23)$'
        if parameters:
            if not isinstance(parameters, dict):
                raise forms.ValidationError('Setting has to be json format')
            sorted_keys = sorted(parameters.keys())
            pre_second_val = None

            for idx, key in enumerate(sorted_keys):

                matching_key = re.match(regex, key)
                if not matching_key:
                    raise forms.ValidationError("Invalid key, %s ex: xx-xx" % key)

                first_val = int(matching_key.group(1))
                second_val = int(matching_key.group(2))
                if idx == 0 and first_val != 0:
                    raise forms.ValidationError("Invalid the first key, %s != 0" % first_val)

                if pre_second_val and first_val != pre_second_val + 1:
                    raise forms.ValidationError(
                        "Invalid the next key, %s != %s + 1" % (first_val, pre_second_val)
                    )

                if not isinstance(parameters[key], int):
                    raise forms.ValidationError("Invalid the value, %s" % parameters)

                if idx == len(sorted_keys) - 1 and second_val != 23:
                    raise forms.ValidationError("Invalid the last key, %s != 23" % second_val)

                pre_second_val = second_val

        return parameters
