from __future__ import absolute_import
from __future__ import unicode_literals

from builtins import object
import logging

from django.db import models

# from django.conf import settings

from django.contrib.auth.models import User

from juloserver.julocore.data.models import JuloModelManager, GetInstanceMixin, TimeStampedModel
from juloserver.julo.models import Application


logger = logging.getLogger(__name__)


class ApplicationLockedManager(GetInstanceMixin, models.Manager):
    pass


class ApplicationLocked(models.Model):
    """
    models for Application was Locked for agents until change status take in
    """
    id = models.AutoField(db_column='application_locked_id', primary_key=True)

    user_lock = models.ForeignKey(
        User, models.DO_NOTHING, db_column='user_lock_id', related_name="app_user_lock")
    user_unlock = models.ForeignKey(
        User, models.DO_NOTHING, null=True, blank=True,
        db_column='user_unlock_id', related_name="app_user_unlock")

    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id')

    status_code_locked = models.IntegerField(null=True, blank=True)
    status_code_unlocked = models.IntegerField(null=True, blank=True)

    locked = models.BooleanField(default=True, db_index=True)
    status_obsolete = models.BooleanField(default=False)

    ts_locked = models.DateTimeField(auto_now_add=True, editable=False)
    ts_unlocked = models.DateTimeField(
        auto_now=True, null=True, blank=True, editable=False)

    objects = ApplicationLockedManager()

    class Meta(object):
        db_table = 'application_locked'
        verbose_name_plural = "Application Locked"

    def __unicode__(self):
        return "%s - %s" % (self.user_lock, self.application)

    def __str__(self):
        return '[%s:%s]' % (self.user_lock, self.application)

    @classmethod
    def create(cls, user, application, status_code_locked, locked=None):
        if(locked):
            app_locked = cls(user_lock=user,
                             application=application,
                             status_code_locked=status_code_locked,
                             locked=locked)
        else:
            app_locked = cls(user_lock=user,
                             application=application,
                             status_code_locked=status_code_locked)

        return app_locked.save()


class ApplicationLockedMaster(models.Model):
    """
    models for Only One Application at that time for user to lock
    """
    id = models.AutoField(db_column='app_locked_master_id', primary_key=True)

    user_lock = models.ForeignKey(
        User, models.DO_NOTHING, db_column='user_lock_id', related_name="app_user_lock_master")
    application = models.OneToOneField(
        Application, models.DO_NOTHING, db_column='application_id')

    ts_locked = models.DateTimeField(auto_now_add=True, editable=False)

    objects = ApplicationLockedManager()

    class Meta(object):
        db_table = 'application_locked_master'
        verbose_name_plural = "Application Lock Master"

    def __unicode__(self):
        return "%s - %s" % (self.user_lock, self.application)

    def __str__(self):
        return '[%s:%s]' % (self.user_lock, self.application)

    @classmethod
    def create(cls, user, application, locked):
        ret_create = None
        try:
            app_locked = cls(user_lock=user,
                             application=application)
            app_locked.save()
            ret_create = 1

        except Exception as e:
            err_msg = """
                Application locked master was locked again for agent : %s with err: %s
            """
            err_msg = err_msg % (user, e)
            logger.info({
                'app_id': application.id,
                'user': user,
                'error': err_msg
            })
        return ret_create


class CannedResponseManager(GetInstanceMixin, JuloModelManager):
    pass


class CannedResponse(TimeStampedModel):
    """
    models for CannedResponse email template
    """
    id = models.AutoField(db_column='canned_response_id', primary_key=True)

    name = models.CharField(max_length=100)
    subject = models.TextField()
    content = models.TextField()

    objects = CannedResponseManager()

    class Meta(object):
        db_table = 'canned_response'
