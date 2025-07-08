from ckeditor.fields import RichTextField
from django.db import models

from juloserver.cx_complaint_form.const import ACTION_TYPE_CHOICES
from juloserver.cx_complaint_form.helpers import create_slug
from juloserver.julo.models import TimeStampedModel
from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from juloserver.pii_vault.models import PIIVaultModel


class ComplaintTopic(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column="complaint_topic_id")
    topic_name = models.CharField(max_length=30)
    image_url = models.TextField()
    slug = models.CharField(max_length=50, null=True, blank=True)
    is_shown = models.BooleanField(default=True)

    __original_name = None

    class Meta:
        db_table = 'complaint_topic'
        managed = False

    def __str__(self):
        return str(self.id) + " - " + self.topic_name

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__original_name = self.topic_name

    def save(self, *args, **kwargs):
        if not self.pk or self.topic_name != self.__original_name:
            self.slug = create_slug(self.topic_name, ComplaintTopic)

        return super().save(*args, **kwargs)


class ComplaintSubTopic(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column="complaint_subtopic_id")
    topic = BigForeignKey(
        ComplaintTopic,
        models.DO_NOTHING,
        db_column='topic_id',
        db_constraint=False,
        related_name="subtopics",
    )
    title = models.CharField(max_length=100)
    survey_usage = models.CharField(max_length=100, null=True, blank=True)
    is_require_attachment = models.BooleanField(default=False)
    total_required_attachment = models.IntegerField(default=0)
    web_required_upload_info_banner = models.CharField(max_length=255, null=True, blank=True)
    action_type = models.CharField(max_length=30, choices=ACTION_TYPE_CHOICES)
    action_value = models.TextField(null=True, blank=True)
    confirmation_dialog_title = models.TextField(null=True, blank=True)
    confirmation_dialog_banner = models.TextField(null=True, blank=True)
    confirmation_dialog_content = models.TextField(null=True, blank=True)
    confirmation_dialog_info_text = models.TextField(null=True, blank=True)
    confirmation_dialog_button_text = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'complaint_subtopic'
        managed = False


class ComplaintSubmissionLog(PIIVaultModel):
    from juloserver.julo.models import PIIType

    PII_FIELDS = ['full_name', 'nik', 'email', 'phone']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'cx_pii_vault'

    id = models.AutoField(primary_key=True, db_column="complaint_submission_log_id")
    customer_id = models.BigIntegerField()
    subtopic = BigForeignKey(
        ComplaintSubTopic, models.DO_NOTHING, db_column='subtopic_id', db_constraint=False
    )
    submission_action_type = models.CharField(max_length=30, choices=ACTION_TYPE_CHOICES)
    submission_action_value = models.TextField()
    survey_submission_uid = models.TextField()
    full_name = models.TextField(max_length=100, blank=True, null=True)
    nik = models.TextField(max_length=16, blank=True, null=True)
    email = models.TextField(max_length=254, blank=True, null=True)
    phone = models.TextField(max_length=50, blank=True, null=True)
    full_name_tokenized = models.TextField(blank=True, null=True)
    nik_tokenized = models.TextField(blank=True, null=True)
    email_tokenized = models.TextField(blank=True, null=True)
    phone_tokenized = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'complaint_submission_log'
        managed = False


class SuggestedAnswer(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column="suggested_answer_id")
    topic = BigForeignKey(
        ComplaintTopic, models.DO_NOTHING, db_column="topic_id", related_name="suggested_answers"
    )
    subtopic = BigForeignKey(
        ComplaintSubTopic,
        models.DO_NOTHING,
        db_column="subtopic_id",
        related_name="suggested_answers",
    )
    survey_answer_ids = models.CharField(max_length=100)
    suggested_answer = RichTextField(config_name='cx_suggested_answers')

    class Meta:
        db_table = 'suggested_answers'
        managed = False


class SuggestedAnswerUserLog(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column="log_id")
    suggested_answer = BigForeignKey(
        SuggestedAnswer,
        models.DO_NOTHING,
        db_column="suggested_answer_id",
        related_name="suggested_answer_user_logs",
    )
    subtopic = BigForeignKey(
        ComplaintSubTopic,
        models.DO_NOTHING,
        db_column="subtopic_id",
        related_name="sibtopic_suggested_answer_logs",
    )
    survey_answer_ids = models.CharField(max_length=100)
    customer_id = models.BigIntegerField(null=True, blank=True)
    ip_address = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        db_table = 'suggested_answers_user_log'
        managed = False


class SuggestedAnswerFeedback(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column="feedback_id")
    suggested_answer = BigForeignKey(
        SuggestedAnswer,
        models.DO_NOTHING,
        db_column="suggested_answer_id",
        related_name="suggested_answer_feedbacks",
    )
    subtopic = BigForeignKey(
        ComplaintSubTopic,
        models.DO_NOTHING,
        db_column="subtopic_id",
        related_name="sibtopic_suggested_answer_feedbacks",
    )
    survey_answer_ids = models.CharField(max_length=100)
    customer_id = models.BigIntegerField(null=True, blank=True)
    ip_address = models.CharField(max_length=100, null=True, blank=True)
    is_helpful = models.BooleanField(default=True)

    class Meta:
        db_table = 'suggested_answer_feedback'
        managed = False
