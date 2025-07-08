from __future__ import absolute_import

from builtins import object

from django import forms
from django.contrib import admin
from django.utils.safestring import mark_safe

from .constants import CommonVariables
from .models import CRMBucketColor, CRMBucketStatusColor

DEFAULT_COLOURS = CommonVariables.DEFAULT_COLOURS
COLOURS_CHOICES = [
    ((x['color'], x['color_name']) if x['color_name'] else (x['color'], x['color']))
    for x in DEFAULT_COLOURS
]


class CRMBucketStatusColorInline(admin.TabularInline):
    model = CRMBucketStatusColor
    extra = 0


class CRMBucketColorForm(forms.ModelForm):
    WHITE_TEXT = '#FFFFFF'
    BLACK_TEXT = '#2B2B2B'
    BR_BLUE = '#337AB7'
    choicelist = (
        (None, '----------'),
        (WHITE_TEXT, 'Text-White'),
        (BLACK_TEXT, 'Text-black'),
        (BR_BLUE, 'Text-Blue'),
    )
    content_color = forms.ChoiceField(choices=choicelist, required=False)

    class Meta(object):
        model = CRMBucketColor
        fields = ('color', 'color_name', 'content_color', 'display_text')
        widgets = {'color': forms.TextInput(attrs={'type': 'color'})}


class CRMBucketColorAdmin(admin.ModelAdmin):
    inlines = (CRMBucketStatusColorInline,)
    list_display = [
        'color',
        'color_preview',
        'color_name',
        'display_text',
        'content_color',
        'content_color_preview',
    ]
    form = CRMBucketColorForm

    class Meta(object):
        model = CRMBucketColor

    def get_queryset(self, request):
        qs_ex = CRMBucketColor.objects.exists()
        if not qs_ex:
            buld_qs = [
                CRMBucketColor(
                    color=x['color'], color_name=x['color_name'], content_color=x['content_color']
                )
                for x in DEFAULT_COLOURS
            ]
            CRMBucketColor.objects.bulk_create(buld_qs)
        return CRMBucketColor.objects.all()

    def color_preview(self, obj):
        if obj.color:
            return mark_safe('<input type="color" value=%s disabled />' % (obj.color,))
        return None

    def content_color_preview(self, obj):
        if obj.content_color:
            return mark_safe('<input type="color" value=%s disabled />' % (obj.content_color,))
        return None


class CRMBucketStatusColorAdmin(admin.ModelAdmin):
    '''
    This module supports all status code like 200, 105 etc..
    and some additional status code like cashback_request,
    courtesy_call, cycle_day_requested.
    '''

    list_display = ('status_code', 'color', 'color_preview')
    list_filter = ('color__color_name',)

    class Meta(object):
        model = CRMBucketStatusColor

    def color_preview(self, obj):
        if obj.color:
            return mark_safe('<input type="color" value=%s disabled />' % (obj.color.color,))
        return None


admin.site.register(CRMBucketColor, CRMBucketColorAdmin)
admin.site.register(CRMBucketStatusColor, CRMBucketStatusColorAdmin)
