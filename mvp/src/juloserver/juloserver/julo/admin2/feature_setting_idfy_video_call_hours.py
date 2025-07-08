from django import forms
from django.db import models
from django.forms import Textarea
from juloserver.julo.models import FeatureSetting


class IDFyVideoCallHoursForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(IDFyVideoCallHoursForm, self).__init__(*args, **kwargs)

    class Meta:
        model = FeatureSetting
        exclude = ['id']
        help_texts = {
            'parameters': '<br><b>Description:</b><br>'
            '1. Format for value hour and minute is <b> 24 hours </b><br>'
            '2. scheduler_messages (optional)        : This will be executed if <code>today == set_date</code> with rule based on open and close in that value <br>'
            '3. If we want to set "Tidak beroperasi" : Only to set with zero (0) in hour and minute for both open and close<br>'
            '<b>1. Example parameter for scheduler messages:</b><br>'
            """
                <pre style="color:#999;padding-left:6%;">
                <code style="font-size:10px;">
                .....
                "scheduler_messages": [
                    {
                        "open": {
                            "hour": 8,
                            "minute": 0
                        },
                        "close": {
                            "hour": 20,
                            "minute": 0
                        },
                        "set_date": "2024-09-02"
                    }
                ]
                ....
                </code>
                </pre>
                """
            '<b class="help" style="padding-left:11%;">2. Example parameter for scheduler messages with case message "Tidak beroperasi":</b><br>'
            """
                <pre style="color:#999;padding-left:6%;">
                <code style="font-size:10px;">
                .....
                "scheduler_messages": [
                    {
                        "open": {
                            "hour": 0,
                            "minute": 0
                        },
                        "close": {
                            "hour": 0,
                            "minute": 0
                        },
                        "set_date": "2024-09-02"
                    }
                ]
                ....
                </code>
                </pre>
                """
            '',
        }

    def clean(self):
        data = super(IDFyVideoCallHoursForm, self).clean()

        return data
