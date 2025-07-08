from django import forms

from juloserver.inapp_survey.const import SURVEY_TYPE_CHOICES
from juloserver.inapp_survey.models import InAppSurveyQuestion


class InAppSurveyQuestionAdminForm(forms.ModelForm):
    question = forms.CharField(
        required=True,
        max_length=120,
    )
    survey_type = forms.TypedChoiceField(
        choices=SURVEY_TYPE_CHOICES,
    )
    is_first_question = forms.BooleanField(
        required=False,
    )

    def clean(self):
        if self.cleaned_data.get('is_first_question'):
            first_question = InAppSurveyQuestion.objects.filter(
                is_first_question=True,
                survey_type=self.cleaned_data.get('survey_type'),
            )
            if self.cleaned_data.get('survey_usage'):
                first_question = first_question.filter(
                    survey_usage=self.cleaned_data.get('survey_usage')
                )

            if self.instance.id:
                first_question = first_question.exclude(id=self.instance.id)

            if first_question.exists():
                raise forms.ValidationError(
                    {
                        'is_first_question': [
                            'First question for survey type {} is already exists'.format(
                                self.cleaned_data.get('survey_type')
                            )
                        ]
                    }
                )

        return super().clean()
