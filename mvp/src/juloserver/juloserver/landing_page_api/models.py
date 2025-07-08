from ckeditor.fields import RichTextField
from django.contrib.postgres.fields import JSONField, ArrayField
from django.db import models
from juloserver.julo.models import GetInstanceMixin, TimeStampedModel
from juloserver.julocore.data.models import CustomQuerySet, JuloModelManager
from juloserver.landing_page_api.constants import FAQItemType, CareerExtraDataConst

TYPE_CHOICES = (
    (FAQItemType.SECTION, FAQItemType.SECTION.title()),
    (FAQItemType.QUESTION, FAQItemType.QUESTION.title())
)


class FAQItemQuerySet(CustomQuerySet):
    def visible(self):
        return self.filter(visible=True)

    def section(self):
        return self.filter(type=FAQItemType.SECTION)


class FAQItemManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return FAQItemQuerySet(self.model)

    def find_visible(self):
        query_set = self.get_queryset()
        return query_set.visible()


class FAQItem(TimeStampedModel):
    id = models.AutoField(db_column='faq_item_id', primary_key=True)
    type = models.TextField(choices=TYPE_CHOICES, default=FAQItemType.QUESTION, db_index=True)
    parent = models.ForeignKey('self', null=True, blank=True)
    title = models.TextField()
    slug = models.SlugField(max_length=50, db_index=True)
    rich_text = RichTextField(blank=True, null=True)
    order_priority = models.IntegerField(default=0, db_index=True)
    visible = models.BooleanField(default=True, db_index=True)
    objects = FAQItemManager()

    class Meta(object):
        ordering = ('order_priority', 'cdate', 'visible',)
        db_table = 'landing_page_faq_item'

    def __str__(self):
        return "{} - {} - {}".format(self.id, self.type, self.title)


class LandingPageCareerQuerySet(CustomQuerySet):
    def active(self):
        return self.filter(is_active=True)


class LandingPageCareer(TimeStampedModel):
    id = models.AutoField(db_column='landing_page_career_id', primary_key=True)
    title = models.TextField()
    category = models.TextField(blank=True)
    rich_text = RichTextField(blank=True, null=True)
    skills = ArrayField(models.TextField(), blank=True, null=True)
    extra_data = JSONField(blank=True, null=True)
    published_date = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(blank=True, default=False, db_index=True)

    objects = LandingPageCareerQuerySet.as_manager()

    extra_data_fields = [
        CareerExtraDataConst.FIELD_TYPE,
        CareerExtraDataConst.FIELD_VACANCY,
        CareerExtraDataConst.FIELD_SALARY,
        CareerExtraDataConst.FIELD_EXPERIENCE,
        CareerExtraDataConst.FIELD_LOCATION,
    ]

    class Meta:
        db_table = 'landing_page_career'
        ordering = ('published_date',)

    def get_extra_data_value(self, key, default_value=None):
        if self.extra_data:
            return self.extra_data.get(key, default_value)
        return default_value

    def set_extra_data_value(self, key, value):
        if not self.extra_data:
            self.extra_data = {}
        self.extra_data[key] = value

    def __getattr__(self, item):
        if item in self.extra_data_fields:
            value = self.get_extra_data_value(item)
            return value
        raise AttributeError


class LandingPageSection(TimeStampedModel):
    id = models.AutoField(db_column='landing_page_section_id', primary_key=True)
    name = models.TextField(db_index=True)
    rich_text = RichTextField(blank=True, null=True)

    class Meta:
        db_table = 'landing_page_section'
