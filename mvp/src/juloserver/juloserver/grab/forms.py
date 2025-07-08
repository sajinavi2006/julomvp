from builtins import object
from django import forms
from juloserver.julo.models import Application
from .constants import GRAB_APPLICATION_FIELDS, GRAB_PERSONAL_IDENTITY_FIELDS


class GrabApplicationForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super(GrabApplicationForm, self).__init__(*args, **kwargs)

        for field in self.Meta.required:
            self.fields[field].required = True

    class Meta(object):
        model = Application
        fields = GRAB_APPLICATION_FIELDS
        required = GRAB_APPLICATION_FIELDS


class GrabPersonalIdentityForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super(GrabPersonalIdentityForm, self).__init__(*args, **kwargs)

        for field in self.Meta.required:
            self.fields[field].required = True

    class Meta(object):
        model = Application
        fields = GRAB_PERSONAL_IDENTITY_FIELDS
        required = GRAB_PERSONAL_IDENTITY_FIELDS
