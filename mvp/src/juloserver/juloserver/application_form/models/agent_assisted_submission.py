from django.db import models

from juloserver.julocore.data.models import TimeStampedModel
from juloserver.julo.models import Application


class AgentAssistedWebToken(TimeStampedModel):
    id = models.AutoField(db_column='web_token_id', primary_key=True)

    # cipher text for SHA 256 is 64 char
    session_token = models.CharField(max_length=64, blank=True, null=True, unique=True)
    is_active = models.BooleanField(default=False)
    expire_time = models.DateTimeField(blank=True, null=True)
    application_id = models.BigIntegerField(null=False, blank=False, db_column='application_id')

    class Meta:
        db_table = 'agent_assisted_web_token'
        managed = False

    def is_token_valid_for_application(self, application_xid):
        """
        Checks if the token belong to customer from application_xid
        """
        application_from_xid = Application.objects.filter(application_xid=application_xid).first()
        if not application_from_xid:
            return False

        return str(application_from_xid.id) == str(self.application_id)

    @classmethod
    def get_token_instance(cls, token):
        return cls.objects.filter(session_token=token).first()

    @classmethod
    def get_token_from_application(cls, application_xid):
        application = Application.objects.filter(application_xid=application_xid).first()
        return cls.objects.filter(application_id=application.id).first()
