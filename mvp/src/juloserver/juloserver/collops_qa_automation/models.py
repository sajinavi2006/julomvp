from django.db import models

from juloserver.collops_qa_automation.constant import QAAirudderAPIPhase
from juloserver.julocore.data.models import TimeStampedModel

# Create your models here.
from juloserver.minisquad.models import VendorRecordingDetail


class AirudderRecordingUpload(TimeStampedModel):
    id = models.AutoField(
        db_column='airruder_recording_upload_id', primary_key=True)
    vendor_recording_detail = models.ForeignKey(
        VendorRecordingDetail, models.DO_NOTHING,
        db_column='vendor_recording_detail_id', blank=True, null=True)
    task_id = models.TextField(blank=True, null=True)
    phase = models.TextField(default=QAAirudderAPIPhase.INITIATED)
    status = models.TextField(blank=True, null=True)
    code = models.IntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'airudder_recording_upload'


class RecordingReport(TimeStampedModel):
    id = models.AutoField(
        db_column='recording_report_id', primary_key=True)
    airudder_recording_upload = models.ForeignKey(
        AirudderRecordingUpload, models.DO_NOTHING,
        db_column='airruder_recording_upload_id')
    length = models.IntegerField()
    total_words = models.IntegerField()
    l_channel_sentence = models.TextField()
    l_channel_negative_checkpoint = models.TextField()
    l_channel_negative_score = models.TextField()
    l_channel_negative_score_amount = models.IntegerField(
        blank=True, null=True
    )
    l_channel_sop_checkpoint = models.TextField()
    l_channel_sop_score = models.TextField()
    l_channel_sop_score_amount = models.IntegerField(
        blank=True, null=True
    )
    r_channel_sentence = models.TextField()
    r_channel_negative_checkpoint = models.TextField()
    r_channel_negative_score = models.TextField()
    r_channel_negative_score_amount = models.IntegerField(
        blank=True, null=True
    )
    r_channel_sop_checkpoint = models.TextField()
    r_channel_sop_score = models.TextField()
    r_channel_sop_score_amount = models.IntegerField(
        blank=True, null=True
    )

    class Meta(object):
        db_table = 'recording_report'

    def save(self, *args, **kwargs):
        if self.l_channel_negative_score:
            self.l_channel_negative_score_amount = self.l_channel_negative_score.split('/')[0]
        if self.l_channel_sop_score:
            self.l_channel_sop_score_amount = self.l_channel_sop_score.split('/')[0]
        if self.r_channel_negative_score:
            self.r_channel_negative_score_amount = self.r_channel_negative_score.split('/')[0]
        if self.r_channel_sop_score:
            self.r_channel_sop_score_amount = self.r_channel_sop_score.split('/')[0]

        super(RecordingReport, self).save(*args, **kwargs)
