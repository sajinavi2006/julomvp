from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms.models import BaseInlineFormSet

from juloserver.inapp_survey.const import MessagesConst
from juloserver.inapp_survey.forms.survey_question import InAppSurveyQuestionAdminForm
from juloserver.inapp_survey.models import (
    InAppSurveyAnswer,
    InAppSurveyAnswerCriteria,
    InAppSurveyQuestion,
    InAppSurveyTriggeredAnswer,
)
from juloserver.inapp_survey.services import delete_answer, delete_question
from juloserver.julo.admin import JuloModelAdmin


class InAppSurveyAdminAnswerCriteriaInline(admin.TabularInline):
    model = InAppSurveyAnswerCriteria


class InAppSurveyAnswerForm(forms.ModelForm):
    class Meta:
        model = InAppSurveyAnswer
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        is_bottom_position = cleaned_data.get('is_bottom_position')
        answer_type = cleaned_data.get('answer_type')

        if is_bottom_position:
            if (
                InAppSurveyAnswer.objects.filter(
                    is_bottom_position=True, question=cleaned_data['question']
                )
                .exclude(pk=self.instance.pk)
                .exists()
            ):
                raise ValidationError(MessagesConst.DUPLICATE_BOTTOM_POSITION)

        if answer_type == 'multi-option':
            if (
                InAppSurveyAnswer.objects.filter(
                    answer_type=cleaned_data['answer_type'], question=cleaned_data['question']
                )
                .exclude(pk=self.instance.pk)
                .exists()
            ):
                raise ValidationError(MessagesConst.DUPLICATE_MULTI_OPTION)

        return cleaned_data


class InAppSurveyAnswerInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        found_bottom = False
        found_multi_option = False

        for form in self.forms:
            if form.cleaned_data and form.cleaned_data.get('is_bottom_position'):
                if found_bottom:
                    raise ValidationError(MessagesConst.DUPLICATE_BOTTOM_POSITION)
                found_bottom = True

            if form.cleaned_data and form.cleaned_data.get('answer_type') == 'multi-option':
                if found_multi_option:
                    raise ValidationError(MessagesConst.DUPLICATE_MULTI_OPTION)
                found_multi_option = True


class InAppSurveyAdminAnswerInline(admin.TabularInline):
    model = InAppSurveyAnswer
    formset = InAppSurveyAnswerInlineFormSet


class InAppSurveyAnswerAdmin(JuloModelAdmin):
    inlines = [InAppSurveyAdminAnswerCriteriaInline]
    list_display = (
        'answer',
        'question',
        'is_bottom_position',
    )
    search_fields = ('answer',)
    form = InAppSurveyAnswerForm

    def get_actions(self, request):
        actions = super().get_actions(request)
        del actions['delete_selected']
        return actions

    def delete_list(self, request, queryset):
        with transaction.atomic():
            for qs in queryset:
                delete_answer(qs)

    delete_list.short_description = "Delete selected survey answers"

    def delete_model(self, request, obj):
        delete_answer(obj)

    actions = [delete_list]


class InAppSurveyTriggeredAnswerInline(admin.TabularInline):
    model = InAppSurveyTriggeredAnswer
    extra = 1

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        answer = formset.form.base_fields['answer']
        answer.widget.can_add_related = False
        answer.widget.can_change_related = False
        answer.widget.can_delete_related = False
        return formset


class InAppSurveyQuestionAdmin(JuloModelAdmin):
    form = InAppSurveyQuestionAdminForm
    inlines = [InAppSurveyAdminAnswerInline, InAppSurveyTriggeredAnswerInline]
    list_display = (
        'question',
        'survey_type',
        'survey_usage',
        'answer_type',
        'is_first_question',
        'is_optional_question',
        'should_randomize',
    )
    search_fields = ('question',)

    def get_actions(self, request):
        actions = super(InAppSurveyQuestionAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    def delete_list(self, request, queryset):
        for qs in queryset:
            delete_question(qs)

    delete_list.short_description = "Delete selected survey questions"

    def delete_model(self, request, obj):
        delete_question(obj)

    actions = [delete_list]


admin.site.register(InAppSurveyQuestion, InAppSurveyQuestionAdmin)
admin.site.register(InAppSurveyAnswer, InAppSurveyAnswerAdmin)
