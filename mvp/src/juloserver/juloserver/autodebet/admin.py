from django.contrib import admin
from juloserver.julo.admin import JuloModelAdmin

from juloserver.autodebet.models import (
    AutodebetDeactivationSurveyQuestion,
    AutodebetDeactivationSurveyAnswer,
)


class AutodebetDeactivationSurveyQuestionAdmin(JuloModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AutodebetSurveyAnswerAdmin(JuloModelAdmin):
    ordering = ['order', 'answer']
    list_display = ('answer', 'question', 'order')
    search_fields = ('answer',)


admin.site.register(AutodebetDeactivationSurveyQuestion, AutodebetDeactivationSurveyQuestionAdmin)
admin.site.register(AutodebetDeactivationSurveyAnswer, AutodebetSurveyAnswerAdmin)
