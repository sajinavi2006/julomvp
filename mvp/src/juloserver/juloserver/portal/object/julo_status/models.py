from __future__ import unicode_literals

from builtins import object
from django.db import models

from cuser.fields import CurrentUserField

# # Create your models here.
from juloserver.julocore.data.models import TimeStampedModel
from juloserver.julo.models import Loan, Application, Payment
from juloserver.julo.models import StatusLookup


class StatusAppSelection(TimeStampedModel):

    status_from = models.ForeignKey(StatusLookup,
        null=False, blank=False, related_name='statusapp_from')
    status_to = models.ForeignKey(StatusLookup,
        null=False, blank=False, related_name='statusapp_to')

    changed_by = CurrentUserField(related_name="user_statusapp")

    class Meta(object):
        verbose_name_plural = "Status Application Selections"

    def __str__(self):
        return "%s - %s" % (self.status_to.status_code,
            self.status_to.status)

    @property
    def from_to(self):
        return "FROM:%s TO:%s" % (self.status_from, self.status_to)

    def save(self, *args, **kwargs):
        # Calling Parent save() function
        super(StatusAppSelection, self).save(*args, **kwargs)


class ReasonStatusAppSelection(TimeStampedModel):

    status_to = models.ForeignKey(StatusLookup,
        null=False, blank=False, related_name='reason_status_to')
    reason = models.CharField(max_length=150, null=False, blank=False)

    changed_by = CurrentUserField(related_name="user_reason")

    class Meta(object):
        ordering = ['cdate']
        verbose_name_plural = "Reason Status Application Selections"

    @property
    def reason_to(self):
        return "status:%s alasan:%s" % (self.status_to, self.reason)

    def __str__(self):
        return "%s" % (self.reason)

    def save(self, *args, **kwargs):
        # Calling Parent save() function
        super(ReasonStatusAppSelection, self).save(*args, **kwargs)