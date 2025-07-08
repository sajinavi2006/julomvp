from django.forms import (
    ModelForm,
    ValidationError,
)

from juloserver.julo.models import FeatureSetting


class MonnaiFraudScoreForm(ModelForm):
    class Meta(object):
        model = FeatureSetting
        fields = ('__all__')

    def clean(self):
        cleaned_data = super().clean()
        parameters = cleaned_data.get('parameters', {})
        test_group = parameters.get('test_group', [])
        control_group = parameters.get('control_group', [])
        combined_group = test_group + control_group

        encountered_numbers = set()
        for range_str in combined_group:
            start, end = range_str.split('-')
            if not (0 <= int(start) <= 99 and 0 <= int(end) <= 99):
                raise ValidationError(f'Invalid range: {range_str}')
            if len(start) != 2 or len(end) != 2:
                raise ValidationError(f'Invalid range: {range_str}')

            for num in range(int(start), int(end) + 1):
                if num in encountered_numbers:
                    raise ValidationError(f'Duplicate number found in range: {range_str}')
                encountered_numbers.add(num)

        if len(encountered_numbers) != 100:
            raise ValidationError('The combination of test_group and control_group must cover all '
                                  'numbers from 00 to 99.')

        return cleaned_data

