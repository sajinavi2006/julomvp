from django.db import models

# Create your models here.
from juloserver.julocore.data.models import TimeStampedModel
from juloserver.julo.models import (
    PTP,
    Image,
)
from django.contrib.auth.models import User, AbstractUser


class FieldAssignment(TimeStampedModel):
    id = models.AutoField(db_column='field_assignment_id', primary_key=True)
    agent = models.ForeignKey(
        User,
        on_delete=models.CASCADE, db_column='agent_id', blank=True, null=True,
        related_name='new_field_assignment_relation')
    account = models.ForeignKey(
        'account.Account',
        models.DO_NOTHING,
        db_column='account_id',
        blank=True,
        null=True
    )
    expiry_date = models.DateField(blank=True, null=True)
    assign_date = models.DateField(blank=True, null=True)
    result = models.TextField(blank=True, null=True)
    visit_location = models.TextField(blank=True, null=True)
    visit_description = models.TextField(blank=True, null=True)

    ptp = models.ForeignKey(
        PTP,
        on_delete=models.CASCADE, db_column='ptp_id', blank=True, null=True,
        related_name='new_ptp_field_assignment_relation'
    )

    class Meta(object):
        db_table = 'field_assignment'

    @property
    def visit_proof_image_url(self):
        image = Image.objects.filter(
            image_source=self.id,
            image_type='visit_proof_field_collection').last()
        if image:
            return image.collection_image_url()

        return None


class FieldAttendance(TimeStampedModel):
    id = models.AutoField(
        db_column='field_attendance_id', primary_key=True)
    agent = models.ForeignKey(
        User,
        on_delete=models.CASCADE, db_column='agent_id',
        related_name='new_field_attendance_relation')
    loc_latitude = models.FloatField(blank=True, null=True)
    loc_longitude = models.FloatField(blank=True, null=True)
    loc_geoloc = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'field_attendance'
