from __future__ import absolute_import
from builtins import object
from django.contrib import admin
from django import forms

from .models import DisbursementTrafficControl

from juloserver.julo.admin import JuloModelAdmin
from juloserver.utilities.services import validate_rule_code

from juloserver.utilities.constants import CommonVariables

value_help_texts = """
    Condition supports the following conditions %s<br/>
    Example Conditions:<br/>
        1: #nthgte:-1:6<br/>
            Get the last value(-1) of value from model key
            and do grater than or equal to with 6<br/>
        2: #nth:-2:0,1,2,3,4,5,6<br/>
            Get the last value(-2) of value from model key
            and check the value in 0,1,2,3,4,5,6 or not<br/>
        3: #eq:500<br/>
            Compare model key value with 500<br/><br/>
    For #nth:-2:1,2,3 <br/>
    nth means nth portion(-2) of the given `key`s value in database and
    check the result with the content in 1,2,3<br/>
    #nth - n'th  position<br/>
    #lte  = less than or equal to<br/>
    #nthgt - n'th position grater than<br/>
    #nthlte - n'th position less than or equal to<br/>
    #eq - equals to value from for the key<br/>
    #gt - grater than value from for the key<br/>
    """ % (", ".join(CommonVariables.CONDITION),)


class DisbursementTrafficControlForm(forms.ModelForm):
    condition = forms.CharField(help_text=value_help_texts, required=True)
    success_value = forms.ChoiceField(
        choices=CommonVariables.DISBURSEMENT_RULE_VALUES,
        label="Success Value", widget=forms.Select(), required=True,)
    rule_type = forms.ChoiceField(
        choices=CommonVariables.TRAFFIC_RULES,
        label="Rule Type", widget=forms.Select(), required=True,)
    key = forms.ChoiceField(
        choices=CommonVariables.TRAFFIC_RULES_KEYS,
        label="Key", widget=forms.Select(), required=True,)

    def clean_condition(self, commit=True):
        code = self.cleaned_data['condition']
        if not validate_rule_code(code):
            raise forms.ValidationError("Provide a valid rule code")
        return self.cleaned_data['condition']


class DisbursementTrafficControlAdmin(JuloModelAdmin):
    form = DisbursementTrafficControlForm
    list_display = (
        'rule_type', 
        'key', 
        'condition', 
        'success_value', 
        'description'
    )
    list_filter = ['rule_type']


admin.site.register(DisbursementTrafficControl, DisbursementTrafficControlAdmin)
from django.contrib.postgres.forms import SimpleArrayField
from .models import SlackEWATag, SlackEWAStatusEmotion, SlackEWABucket, \
    SlackUser
from juloserver.julo.models import StatusLookup

from juloserver.julo.admin import JuloModelAdmin
from juloserver.utilities.services import get_result_from_condition_string, \
    validate_condition_str
from juloserver.monitors.notifications import get_slack_client
from juloserver.utilities.constants import CommonVariables


class SlackEWAStatusEmotionForm(forms.ModelForm):
    condition = forms.CharField(
        required=True, label='Condition',
        widget=forms.TextInput(attrs={
            'size': 35,
            'placeholder': 'count >= 200'
        }),
        help_text='count >= 200, count > 200 and '
                  'count < 500  etc.., only one condiont'
                  ' is alloud. alloud conditons: > < >= '
                  '<= ==. alloud key: count and numbers'
    )

    class Meta(object):
        model = SlackEWAStatusEmotion
        fields = ['condition', 'emoji']

    def clean_condition(self):
        valid_condition = validate_condition_str(
            self.cleaned_data['condition'], '100')
        if valid_condition is None:
            raise forms.ValidationError('Provide valid condition')
        return self.cleaned_data['condition']


class SlackEWAStatusEmotionInline(admin.TabularInline):
    extra = 0
    model = SlackEWAStatusEmotion
    form = SlackEWAStatusEmotionForm


class SlackEWAStatusEmotionAdmin(JuloModelAdmin):
    model = SlackEWAStatusEmotion
    autocomplete_fields = ['emoji']


class SlackEWATagForm(forms.ModelForm):
    condition = forms.CharField(
        required=True, label='Condition',
        widget=forms.TextInput(attrs={
            'size': 35,
            'placeholder': 'count >= 200'
        }),
        help_text='count >= 200, count > 200 and '
                  'count < 500  etc.., only one condiont'
                  ' is alloud. alloud conditons: > < >= '
                  '<= ==. alloud key: count and numbers'
    )

    def __init__(self, *args, **kwargs):
        super(SlackEWATagForm, self).__init__(*args, **kwargs)
        self.fields['slack_user'].required = True

    class Meta(object):
        model = SlackEWATag
        fields = ['condition', 'slack_user']

    def clean_condition(self):
        valid_condition = validate_condition_str(
            self.cleaned_data["condition"], "100"
        )
        if valid_condition is None:
            raise forms.ValidationError('Provide valid condition')
        return self.cleaned_data['condition']


class SlackEWATagAdmin(JuloModelAdmin):
    model = SlackEWATag


class SlackEWATagAdminInline(admin.TabularInline):
    extra = 0
    model = SlackEWATag
    form = SlackEWATagForm
    filter_horizontal = ('slack_user', )


class SlackEWABucketAdmin(JuloModelAdmin):
    inlines = [SlackEWAStatusEmotionInline, SlackEWATagAdminInline]
    model = SlackEWABucket


class SlackUserForm(forms.ModelForm):
    slack_id = forms.CharField(
        required=True, label='Slack User Id',
        help_text='Provide Slack User Id (eg: U5ND8XXXX)')

    def clean_slack_id(self):
        slack_client = get_slack_client()
        slack_id = self.cleaned_data['slack_id']
        res = slack_client.api_call("users.info", user=slack_id)
        if res['ok'] is not True:
            raise forms.ValidationError('Unable to identify this slack Id')
        return slack_id


class SlackUserAdmin(JuloModelAdmin):
    model = SlackUser
    form = SlackUserForm


admin.site.register(SlackEWABucket, SlackEWABucketAdmin)
admin.site.register(SlackUser, SlackUserAdmin)
