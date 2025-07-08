from django.db import models

from juloserver.inapp_survey.const import (
    ANSWER_TYPE_CHOICES,
    SURVEY_TYPE_CHOICES,
    USER_STATUS_CHOICES,
    IN_ANSWER_TYPE_CHOICES,
)
from juloserver.julo.models import TimeStampedModel
from juloserver.julocore.customized_psycopg2.models import (
    BigForeignKey,
)
from juloserver.pii_vault.models import PIIVaultModel


class SurveyTypeConst:
    ACCOUNT_DELETION = 'account_deletion'


class InAppSurveyQuestion(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column="inapp_survey_question_id")
    triggered_by_answers = models.ManyToManyField(
        'InAppSurveyAnswer',
        related_name='answer_trigger_questions',
        through='InAppSurveyTriggeredAnswer',
    )
    question = models.CharField(max_length=120)
    survey_type = models.CharField(max_length=30, choices=SURVEY_TYPE_CHOICES)
    answer_type = models.CharField(
        max_length=30,
        choices=ANSWER_TYPE_CHOICES,
        help_text='Custom Page choices is type for question that need custom '
        'action to be performed.',
    )
    is_first_question = models.BooleanField(default=False)
    is_optional_question = models.BooleanField(default=False)
    survey_usage = models.CharField(
        null=True,
        blank=True,
        max_length=50,
        help_text='This field is mandatory if survey type is autodebet_deactivation_survey',
    )
    should_randomize = models.BooleanField(default=False)
    page = models.CharField(
        null=True,
        blank=True,
        max_length=50,
        help_text='Page field is related to answer_type = custom_page, helping FE to '
        'show which page will be used.',
    )

    class Meta:
        db_table = 'inapp_survey_question'
        index_together = [('survey_type', 'is_first_question')]
        managed = False

    def __str__(self):
        return str(self.id) + " - " + self.question


class InAppSurveyAnswer(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column="inapp_survey_answer_id")
    question = BigForeignKey(
        'InAppSurveyQuestion', models.DO_NOTHING, db_column='question_id', related_name="answers"
    )
    answer = models.CharField(max_length=120)
    answer_type = models.CharField(
        max_length=30,
        choices=IN_ANSWER_TYPE_CHOICES,
        help_text='This type is to flag which action that needs to be performed after'
        ' customer choose this option.',
        null=True,
        blank=True,
    )
    is_bottom_position = models.BooleanField(
        default=False,
        help_text='If answer is randomized, the answer with is_bottom_position = true, will'
        ' always on bottom position.',
    )

    class Meta:
        db_table = 'inapp_survey_answer'
        managed = False

    def __str__(self):
        return str(self.id) + " - " + self.answer


class InAppSurveyAnswerCriteria(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column="inapp_survey_answer_criteria_id")
    answer = BigForeignKey(
        InAppSurveyAnswer, models.DO_NOTHING, db_column='answer_id', related_name="answer_criteria"
    )
    status_code = models.IntegerField()
    status_type = models.CharField(max_length=30, choices=USER_STATUS_CHOICES)

    class Meta:
        db_table = 'inapp_survey_answer_criteria'
        index_together = [('status_type', 'status_code')]
        managed = False


class InAppSurveyUserAnswer(PIIVaultModel):
    from juloserver.julo.models import PIIType

    PII_FIELDS = ['full_name', 'nik', 'email', 'phone']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'cx_pii_vault'

    id = models.AutoField(primary_key=True, db_column="inapp_survey_user_answer_id")
    customer_id = models.BigIntegerField()
    question = models.CharField(max_length=120)
    answer = models.TextField(null=True, blank=True)
    submission_uid = models.CharField(max_length=50)
    full_name = models.TextField(max_length=100, blank=True, null=True)
    nik = models.TextField(max_length=16, blank=True, null=True)
    email = models.TextField(max_length=254, blank=True, null=True)
    phone = models.TextField(max_length=50, blank=True, null=True)
    full_name_tokenized = models.TextField(blank=True, null=True)
    nik_tokenized = models.TextField(blank=True, null=True)
    email_tokenized = models.TextField(blank=True, null=True)
    phone_tokenized = models.TextField(blank=True, null=True)
    survey_type = models.CharField(blank=True, null=True, max_length=100)

    class Meta:
        db_table = 'inapp_survey_user_answer'
        managed = False


class InAppSurveyTriggeredAnswer(TimeStampedModel):
    id = models.AutoField(primary_key=True, db_column="inapp_survey_triggered_answer_id")
    question = BigForeignKey(InAppSurveyQuestion, models.DO_NOTHING, db_column='question_id')
    answer = BigForeignKey(
        InAppSurveyAnswer, models.DO_NOTHING, db_column='answer_id', related_name="trigger_answers"
    )

    class Meta:
        db_table = 'inapp_survey_triggered_answer'
        managed = False
        unique_together = ('question', 'answer')
