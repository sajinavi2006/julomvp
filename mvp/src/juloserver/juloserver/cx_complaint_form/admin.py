import logging
import os
from urllib.parse import urlparse

from django import forms
from django.conf import settings
from django.contrib import admin
from django.db import transaction
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.text import slugify
from django.core.exceptions import ValidationError

from juloserver.cx_complaint_form.const import ACTION_TYPE_CHOICES
from juloserver.cx_complaint_form.helpers import create_slug
from juloserver.cx_complaint_form.models import ComplaintSubTopic, ComplaintTopic, SuggestedAnswer
from ckeditor.widgets import CKEditorWidget
from juloserver.inapp_survey.models import InAppSurveyAnswer
from juloserver.julo.admin import JuloModelAdmin
from juloserver.julo.utils import (
    delete_public_file_from_oss,
    get_oss_presigned_url,
    put_public_file_to_oss,
)

logger = logging.getLogger(__name__)


class ComplaintTopicForm(forms.ModelForm):
    topic_name = forms.CharField(required=True, max_length=120)
    icon = forms.ImageField(required=False)
    is_shown = forms.BooleanField(required=False)

    class Meta(object):
        model = ComplaintTopic
        fields = ('topic_name', 'icon', 'image_url')

    def save(self, commit=True):
        obj = super(ComplaintTopicForm, self).save(commit=False)
        icon = self.cleaned_data['icon']
        if obj.image_url is None and icon is None:
            raise forms.ValidationError("Icon must be required")

        if icon:
            bucket_name = settings.OSS_MEDIA_BUCKET
            _, file_extension = os.path.splitext(icon.name)
            topic_name = self.cleaned_data['topic_name']
            now_timestamp = str(int(timezone.localtime(timezone.now()).timestamp()))
            dest = (
                "complaint-form/topics/"
                + create_slug(topic_name, ComplaintTopic)
                + "-"
                + now_timestamp
                + file_extension
            )
            put_public_file_to_oss(bucket_name, icon, dest)
            obj.image_url = dest
        return obj


class ComplaintTopicAdmin(JuloModelAdmin):
    form = ComplaintTopicForm
    list_display = (
        'topic_name',
        'total_subtopics',
        'is_shown',
    )
    readonly_fields = ('image_url', 'image')
    search_fields = ('topic_name',)

    @transaction.atomic(using='juloplatform_db')
    def delete_model(self, request, obj):
        try:
            subtopics = obj.subtopics.all()
            subtopics.delete()
            if obj.image_url:
                url = urlparse(obj.image_url)
                path_file = url.path
                delete_public_file_from_oss(settings.OSS_MEDIA_BUCKET, path_file)
        except Exception as e:
            logger.error(str(e))

    def image(self, obj):
        if obj.image_url:
            full_url = get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, obj.image_url)
            full_url = full_url.split('?')[0]
            image_tag = (
                '<img style="object-fit:contain;" '
                'src="%s" width="250" height="250" />' % full_url
            )
            return mark_safe(image_tag)
        return None

    def image_list(self, obj):
        if obj.image_url:
            full_url = get_oss_presigned_url(settings.OSS_MEDIA_BUCKET, obj.image_url)
            full_url = full_url.split('?')[0]
            return mark_safe(f'<a href="{full_url}">{obj.image_url}</a>')
        return None

    def total_subtopics(self, obj):
        return obj.subtopics.count()

    class Meta(object):
        model = ComplaintTopic


class ComplaintSubTopicForm(forms.ModelForm):
    topic = forms.ModelChoiceField(ComplaintTopic.objects.all())
    title = forms.CharField(max_length=100)
    survey_usage = forms.CharField(max_length=100, required=False)
    is_require_attachment = forms.BooleanField(required=False)
    total_required_attachment = forms.IntegerField(required=False)
    action_type = forms.ChoiceField(choices=ACTION_TYPE_CHOICES)
    action_value = forms.CharField(required=False)
    web_required_upload_info_banner = forms.CharField(
        max_length=254, widget=forms.Textarea, required=False
    )
    confirmation_dialog_title = forms.CharField(required=False)
    confirmation_dialog_banner_image = forms.ImageField(required=False)
    confirmation_dialog_content = forms.CharField(
        max_length=1000, widget=forms.Textarea, required=False
    )
    confirmation_dialog_info_text = forms.CharField(
        max_length=1000, widget=forms.Textarea, required=False
    )
    confirmation_dialog_button_text = forms.CharField(max_length=100, required=False)

    class Meta(object):
        model = ComplaintSubTopic
        fields = (
            'topic',
            'title',
            'survey_usage',
            'is_require_attachment',
            'total_required_attachment',
            'action_type',
            'action_value',
            'web_required_upload_info_banner',
            'confirmation_dialog_title',
            'confirmation_dialog_banner_image',
            'confirmation_dialog_content',
            'confirmation_dialog_info_text',
            'confirmation_dialog_button_text',
        )

    def clean(self):
        cleaned_data = super().clean()
        image = cleaned_data.get('confirmation_dialog_banner_image')
        content = cleaned_data.get('confirmation_dialog_content')
        title = cleaned_data.get('confirmation_dialog_title')
        button_text = cleaned_data.get('confirmation_dialog_button_text')
        is_require_attachment = cleaned_data.get('is_require_attachment')
        total_required_attachment = cleaned_data.get('total_required_attachment')
        web_required_upload_info_banner = cleaned_data.get('web_required_upload_info_banner')

        if content:
            if not image and not self.instance.confirmation_dialog_banner:
                self.add_error(
                    'confirmation_dialog_banner_image',
                    "Dialog banner wajib ada jika confirmation dialog data ada.",
                )
            if not title:
                self.add_error(
                    'confirmation_dialog_title',
                    "Dialog title wajib ada jika confirmation dialog data ada.",
                )
            if not button_text:
                self.add_error(
                    'confirmation_dialog_button_text',
                    "Dialog button text wajib ada jika confirmation dialog data ada.",
                )

        if image:
            if not content:
                self.add_error(
                    'confirmation_dialog_content',
                    "Dialog content ada jika confirmation dialog data ada.",
                )
            if not title:
                self.add_error(
                    'confirmation_dialog_title',
                    "Dialog title wajib ada jika confirmation dialog data ada.",
                )
            if not button_text:
                self.add_error(
                    'confirmation_dialog_button_text',
                    "Dialog button text wajib ada jika confirmation dialog data ada.",
                )

        if title:
            if not content:
                self.add_error(
                    'confirmation_dialog_content',
                    "Dialog content ada jika confirmation dialog data ada.",
                )
            if not image and not self.instance.confirmation_dialog_banner:
                self.add_error(
                    'confirmation_dialog_banner_image',
                    "Dialog banner wajib ada jika confirmation dialog data ada.",
                )
            if not button_text:
                self.add_error(
                    'confirmation_dialog_button_text',
                    "Dialog button text wajib ada jika confirmation dialog data ada.",
                )

        if button_text:
            if not content:
                self.add_error(
                    'confirmation_dialog_content',
                    "Dialog content ada jika confirmation dialog data ada.",
                )
            if not image and not self.instance.confirmation_dialog_banner:
                self.add_error(
                    'confirmation_dialog_banner_image',
                    "Dialog banner wajib ada jika confirmation dialog data ada.",
                )
            if not title:
                self.add_error(
                    'confirmation_dialog_title',
                    "Dialog title wajib ada jika confirmation dialog data ada.",
                )

        if is_require_attachment and not total_required_attachment:
            self.add_error(
                'total_required_attachment', 'Total dokumen yang harus diupload wajib diisi.'
            )
        if total_required_attachment > 0 and not web_required_upload_info_banner:
            self.add_error(
                'web_required_upload_info_banner', 'Info wajib upload dokumen harus diisi.'
            )

    def save(self, commit=True):
        obj = super(ComplaintSubTopicForm, self).save(commit=False)
        if self.cleaned_data['confirmation_dialog_banner_image']:
            confirmation_dialog_banner_image = self.cleaned_data['confirmation_dialog_banner_image']
            bucket_name = settings.OSS_MEDIA_BUCKET
            _, file_extension = os.path.splitext(confirmation_dialog_banner_image.name)
            dest = "complaint-form/banners/" + slugify(obj.title) + file_extension
            put_public_file_to_oss(bucket_name, confirmation_dialog_banner_image, dest)
            obj.confirmation_dialog_banner = dest
        return obj


class ComplaintSubTopicAdmin(JuloModelAdmin):
    form = ComplaintSubTopicForm
    list_display = (
        'title',
        'topic',
        'survey_usage',
        'is_require_attachment',
        'total_required_attachment',
        'action_type',
    )
    search_fields = ('title',)
    readonly_fields = ('confirmation_dialog_banner', 'confirmation_dialog_banner_preview')

    def confirmation_dialog_banner_preview(self, obj):
        if obj.confirmation_dialog_banner:
            full_url = get_oss_presigned_url(
                settings.OSS_MEDIA_BUCKET, obj.confirmation_dialog_banner
            )
            full_url = full_url.split('?')[0]
            image_tag = (
                '<img style="object-fit:contain;" '
                'src="%s" width="250" height="250" />' % full_url
            )
            return mark_safe(image_tag)
        return None


class SuggestedAnswerForm(forms.ModelForm):
    survey_answer_ids = forms.MultipleChoiceField(
        widget=forms.SelectMultiple(attrs={'class': 'survey-answer-ids-control'}),
        required=True,
        label="Survey Answer Mapping IDs",
    )

    suggested_answer = forms.CharField(
        widget=CKEditorWidget(config_name='cx_suggested_answers'), required=True
    )

    class Meta:
        model = SuggestedAnswer
        fields = ('survey_answer_ids', 'suggested_answer')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        complaint_titles = {
            item["survey_usage"]: item["title"]
            for item in ComplaintSubTopic.objects.values("survey_usage", "title")
        }

        answers = (
            InAppSurveyAnswer.objects.select_related("question")
            .filter(
                question__survey_usage__isnull=False,
                question__survey_usage__gt="",
                question__survey_type="complaint-form",
                question__survey_usage__in=complaint_titles.keys(),
            )
            .order_by("question__survey_usage")
        )

        MAX_LENGTH = 100

        def truncate_string(s, max_length):
            return (s[:max_length] + "...") if len(s) > max_length else s

        # Populate survey_answer_ids choices with formatted survey answers
        self.fields['survey_answer_ids'].choices = [
            (
                str(answer.pk),
                truncate_string(
                    "{} - {} - {}".format(
                        answer.pk,
                        complaint_titles.get(answer.question.survey_usage, "N/A"),
                        answer.answer,
                    ),
                    MAX_LENGTH,
                ),
            )
            for answer in answers
        ]

        # Set initial values if the form is editing an existing instance
        if self.instance and self.instance.pk:
            initial_ids = self.instance.survey_answer_ids.split(',')
            self.initial['survey_answer_ids'] = initial_ids

    def _validate_clean_ids(self, survey_answer_ids):
        """Validate and clean the IDs format"""
        self.cleaned_ids = sorted(set(id_.strip() for id_ in survey_answer_ids if id_.strip()))

        if not self.cleaned_ids:
            raise ValidationError("Survey answer IDs cannot be empty.")

        invalid_formats = [answer_id for answer_id in self.cleaned_ids if not answer_id.isdigit()]
        if invalid_formats:
            raise ValidationError("Invalid ID format: {}".format(", ".join(invalid_formats)))

    def _validate_existence(self):
        """Validate that all IDs exist in the choices"""
        valid_ids = {str(id_) for id_, _ in self.fields['survey_answer_ids'].choices}
        invalid_ids = set(self.cleaned_ids) - valid_ids

        if invalid_ids:
            raise ValidationError("Invalid survey answer IDs: {}".format(", ".join(invalid_ids)))

    def _validate_subtopics(self):
        """Validate all answers belong to the same subtopic"""
        # Get first answer's survey_usage
        survey_usage = (
            InAppSurveyAnswer.objects.filter(id=self.cleaned_ids[0])
            .values_list('question__survey_usage', flat=True)
            .first()
        )

        if not survey_usage:
            raise ValidationError("Answer ID {} not found.".format(self.cleaned_ids[0]))

        # Get subtopic info
        subtopic = (
            ComplaintSubTopic.objects.filter(survey_usage=survey_usage)
            .values('id', 'topic_id')
            .first()
        )

        if not subtopic:
            raise ValidationError(
                "Survey usage '{}' has no associated subtopic.".format(survey_usage)
            )

        # Check other answers have same survey_usage
        if len(self.cleaned_ids) > 1:
            other_usages = set(
                InAppSurveyAnswer.objects.filter(id__in=self.cleaned_ids[1:]).values_list(
                    'question__survey_usage', flat=True
                )
            )

            if len(other_usages) != 1 or survey_usage not in other_usages:
                raise ValidationError("All answers must belong to the same subtopic.")

        return {
            'id': subtopic['id'],
            'topic_id': subtopic['topic_id'],
            'survey_usage': survey_usage,
        }

    # Validate survey_answer_ids field
    @transaction.atomic
    def clean_survey_answer_ids(self):
        survey_answer_ids = self.cleaned_data['survey_answer_ids']

        # Run all validations
        self._validate_clean_ids(survey_answer_ids)
        self._validate_existence()
        subtopic_info = self._validate_subtopics()

        # Store subtopic info for use in save method
        self._validated_subtopic_info = subtopic_info

        return self.cleaned_ids

    def clean_suggested_answer(self):
        return self.cleaned_data['suggested_answer'].strip()

    # Save method to ensure proper survey_answer_ids formatting
    @transaction.atomic
    def save(self, commit=True):
        instance = super().save(commit=False)
        survey_answer_ids_list = self.cleaned_data['survey_answer_ids']

        instance.survey_answer_ids = ",".join(survey_answer_ids_list)

        # Assign subtopic and topic from validation
        if hasattr(self, '_validated_subtopic_info') and self._validated_subtopic_info:
            instance.subtopic_id = self._validated_subtopic_info['id']
            instance.topic_id = self._validated_subtopic_info['topic_id']

        if commit:
            instance.save()
        return instance


class SuggestedAnswerAdmin(JuloModelAdmin):
    form = SuggestedAnswerForm

    def truncated_suggested_answer(self, obj):
        max_length = 300
        return (
            (obj.suggested_answer[:max_length] + ".....")
            if len(obj.suggested_answer) > max_length
            else obj.suggested_answer
        )

    truncated_suggested_answer.short_description = "Suggested Answer"

    def get_actions(self, request):
        return {}

    def display_subtopic_title(self, obj):
        return obj.subtopic.title if obj.subtopic else "N/A"

    display_subtopic_title.short_description = "Subtopic Title"

    def display_survey_answers(self, obj):
        return obj.survey_answer_ids

    display_survey_answers.short_description = "Survey Answer Mapping IDs"

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['show_delete'] = False
        return super().changeform_view(request, object_id, form_url, extra_context)

    list_display = (
        'topic',
        'display_subtopic_title',
        'display_survey_answers',
        'truncated_suggested_answer',
    )
    search_fields = [
        'subtopic__title',
        'topic__topic_name',
        'survey_answer_ids',
        'suggested_answer',
    ]
    change_form_template = "suggestedanswer/custom_admin/suggested_answer.html"


admin.site.register(SuggestedAnswer, SuggestedAnswerAdmin)
admin.site.register(ComplaintTopic, ComplaintTopicAdmin)
admin.site.register(ComplaintSubTopic, ComplaintSubTopicAdmin)
