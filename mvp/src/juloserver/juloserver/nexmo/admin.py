from django.contrib import admin
from django.template.loader import render_to_string
from django.utils.html import format_html

from juloserver.nexmo.models import RobocallCallingNumberChanger
from django.forms import TextInput


class CustomTextInput(TextInput):
    def render(self, name, value, attrs=None):
        widget_html = super().render(name, value, attrs=attrs)
        button_and_modal = render_to_string('custom_admin/nexmo_dial_widget.html')
        return format_html('{}{}', widget_html, button_and_modal)


class RobocallCallingNumberChangerAdmin(admin.ModelAdmin):
    change_form_template = "custom_admin/nexmo_dial_logic.html"
    list_display = ('id', 'start_date', 'end_date', 'new_calling_number')

    def formfield_for_dbfield(self, db_field, **kwargs):
        if db_field.name == 'test_to_call_number':
            kwargs['widget'] = CustomTextInput(attrs={'class': 'custom-class'})
        return super().formfield_for_dbfield(db_field, **kwargs)

    def save_model(self, request, obj, form, change):
        obj.save()


admin.site.register(RobocallCallingNumberChanger, RobocallCallingNumberChangerAdmin)
