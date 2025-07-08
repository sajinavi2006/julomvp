from django import forms


class FraudHighRiskAsnTowerCheckForm(forms.ModelForm):
    class Meta(object):
        fields = ('__all__')

    def clean(self):
        cleaned_data = super().clean()

        parameters = cleaned_data.get('parameters')
        if 'mycroft_threshold_min' not in parameters or 'mycroft_threshold_max' not in parameters:
            raise forms.ValidationError(
                'Parameters field must have mycroft_threshold_min and mycroft_threshold_max key.'
                'E.g: {"mycroft_threshold_min": 0.1, "mycroft_threshold_max": 0.9}'
            )

        threshold_x = parameters['mycroft_threshold_min']
        threshold_y = parameters['mycroft_threshold_max']
        if (not isinstance(threshold_x, (int, float)) or
            not isinstance(threshold_y, (int, float))):
            raise forms.ValidationError(
                'Parameters field dictionary \'mycroft_threshold_min\' and \'mycroft_threshold_max'
                '\' must be a float or int value.'
                'E.g: {"mycroft_threshold_min": 0.1, "mycroft_threshold_max": 0.9}'
            )

        if threshold_x >= threshold_y:
            raise forms.ValidationError(
                'mycroft_threshold_min value must be less than mycroft_threshold_max.'
            )

        if not (0 <= threshold_x <= 1) or not (0 <= threshold_y <= 1):
            raise forms.ValidationError(
                'mycroft_threshold_min and mycroft_threshold_max value must be 0 - 1 (inclusive).'
            )

        return cleaned_data
