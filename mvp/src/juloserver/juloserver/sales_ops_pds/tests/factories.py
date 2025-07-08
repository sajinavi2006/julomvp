from django.utils import timezone
from factory import SubFactory
from factory.django import DjangoModelFactory

from juloserver.sales_ops_pds.models import (
    SalesOpsLineupAIRudderData,
    AIRudderAgentGroupMapping,
    AIRudderDialerTaskGroup,
    AIRudderDialerTaskUpload,
    AIRudderDialerTaskDownload,
)


class SalesOpsLineupAIRudderDataFactory(DjangoModelFactory):
    class Meta:
        model = SalesOpsLineupAIRudderData

    mobile_phone_1 = "+64123456789"
    gender = "Pria"
    fullname = "Prod Only"
    available_limit = 10_000_000
    set_limit = 8_000_000
    application_history_x190_cdate = timezone.localtime(timezone.now())
    latest_loan_fund_transfer_ts = timezone.localtime(timezone.now())
    is_12m_user = "non_12M_user"
    is_high_value_user = "average_value_user"
    r_score = 1
    m_score = 1
    latest_active_dates = timezone.localtime(timezone.now()).date()
    customer_id = 1
    application_id = 1
    account_id = 1
    data_date = timezone.localtime(timezone.now()).date()
    partition_date = timezone.localtime(timezone.now()).date()
    cicilan_per_bulan_sebelumnya = "dummy"
    cicilan_per_bulan_baru = "dummy"
    saving_overall_after_np = "dummy"


class AIRudderAgentGroupMappingFactory(DjangoModelFactory):
    class Meta:
        model = AIRudderAgentGroupMapping

    is_active = True


class AIRudderDialerTaskGroupFactory(DjangoModelFactory):
    class Meta:
        model = AIRudderDialerTaskGroup

    agent_group_mapping = SubFactory(AIRudderAgentGroupMappingFactory)


class AIRudderDialerTaskUploadFactory(DjangoModelFactory):
    class Meta:
        model = AIRudderDialerTaskUpload

    dialer_task_group = SubFactory(AIRudderDialerTaskGroupFactory)


class AIRudderDialerTaskDownloadFactory(DjangoModelFactory):
    class Meta:
        model = AIRudderDialerTaskDownload

    dialer_task_upload = SubFactory(AIRudderDialerTaskUploadFactory)
