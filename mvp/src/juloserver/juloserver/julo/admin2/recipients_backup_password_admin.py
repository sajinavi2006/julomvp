import json

from django import forms


class RecipientsBackupPasswordForm(forms.ModelForm):
    class Meta(object):
        fields = ('__all__')

    def clean(self):
        cleaned_data = super().clean()

        parameters = cleaned_data.get('parameters')
        if 'collection' not in parameters or 'operation' not in parameters:
            raise forms.ValidationError(
                'Parameters field must have collection and operation key.'
                'E.g: {"collection": [], "operation": []}'
            )
        if type(parameters['collection']) != list or type(parameters['operation']) != list:
            raise forms.ValidationError(
                'Parameters field dictionary \'collection\' and \'operation\' must be a list.'
                'E.g: {"collection": ["the-email@gmail.com"], "operation": []}'
            )

        return cleaned_data
