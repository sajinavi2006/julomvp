import logging
from django.contrib import admin
from juloserver.julo.admin import JuloModelAdmin
from juloserver.faq.forms import (
    FaqForm,
)
from juloserver.faq.models import (
    Faq,
)


class FaqAdmin(JuloModelAdmin):
    form = FaqForm
    list_display = (
        'id',
        'question',
        'feature_name',
        'answer',
        'order_priority',
    )


admin.site.register(Faq, FaqAdmin)
