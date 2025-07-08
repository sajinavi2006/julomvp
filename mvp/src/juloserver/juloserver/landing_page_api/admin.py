from django import forms
from django.contrib import admin
from django.db import models

from juloserver.landing_page_api.constants import FAQItemType
from juloserver.landing_page_api.models import (
    FAQItem,
    TYPE_CHOICES,
    LandingPageSection,
    LandingPageCareer,
)


class AdminParentListFilter(admin.SimpleListFilter):
    title = 'Parent Section'
    parameter_name = 'parent'

    def lookups(self, request, model_admin):
        parent_faqs = FAQItem.objects.values('id', 'title') \
            .filter(type=FAQItemType.SECTION) \
            .order_by('-udate')
        values_list = []
        for parent_faq in parent_faqs:
            value = (
                parent_faq.get('id'),
                '{} - {}'.format(parent_faq.get('id'), parent_faq.get('title', '-no-title-'))
            )
            values_list.append(value)
        return values_list

    def queryset(self, request, queryset):
        if self.value() is not None:
            value = self.value() if self.value() != '-' else None
            return queryset.filter(parent_id=value)
        return queryset


class FAQItemAdminForm(forms.ModelForm):
    class Meta:
        model = FAQItem
        exclude = []
        widgets = {
            'type': forms.Select(choices=TYPE_CHOICES),
            'title': forms.Textarea(attrs={'rows': 2, 'cols': 80})
        }


class FAQItemAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'type', 'parent', 'order_priority', 'visible', 'cdate', 'udate'
    ]
    list_filter = [
        'type', 'visible', AdminParentListFilter
    ]
    search_fields = [
                        'title', 'parent__title', 'rich_text'
                    ],
    prepopulated_fields = {
        'slug': ('title',),
    }

    form = FAQItemAdminForm

    def formfield_for_foreignkey(self, db_field, request=None, **kwargs):
        if db_field.name == 'parent':
            kwargs["queryset"] = FAQItem.objects.get_queryset().section()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)



class LandingPageSectionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'name', 'udate', 'cdate'
    ]
    list_display_links = [
        'id', 'name'
    ]
    formfield_overrides = {
        models.TextField: {'widget': forms.TextInput}
    }


class LandingPageCareerAdminForm(forms.ModelForm):
    vacancy = forms.CharField(required=False, help_text="ex: 5")
    type = forms.CharField(required=False, help_text="Fill with: Intern, Full-time, Part-time")
    salary = forms.CharField(required=False, help_text='ex: 7.000.000')
    experience = forms.CharField(required=False, help_text='ex: min. 2 years')
    location = forms.CharField(required=False, help_text='ex: JAKARTA, Indonesia')

    class Meta:
        model = LandingPageCareer
        exclude = ['extra_data']
        widgets = {
            'title': forms.TextInput(),
            'category': forms.TextInput(),
            'skills': forms.Textarea(attrs={'rows': 2, 'cols': 80})
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance:
            for field in LandingPageCareer.extra_data_fields:
                self.fields[field].initial = getattr(instance, field)

    def save(self, commit=True):
        for field in LandingPageCareer.extra_data_fields:
            self.instance.set_extra_data_value(field, self.cleaned_data.get(field))
        return super().save(commit)


class LandingPageCareerAdmin(admin.ModelAdmin):
    form = LandingPageCareerAdminForm
    list_display = [
        'id', 'title', 'category', 'is_active', 'published_date', 'udate'
    ]
    list_display_links = [
        'id', 'title'
    ]
    list_filter = [
        'is_active', 'category'
    ]
    search_fields = [
        'title', 'category'
    ]
    fieldsets = (
        (None, {'fields': ('title', 'category', 'published_date', 'is_active')}),
        ('Career Info', {'fields': (('location', 'type'), ('salary', 'experience'), 'vacancy', 'skills')}),
        ('Description', {'fields': ('rich_text', )})
    )


# Register your models here.
admin.site.register(FAQItem, FAQItemAdmin)
admin.site.register(LandingPageSection, LandingPageSectionAdmin)
admin.site.register(LandingPageCareer, LandingPageCareerAdmin)
