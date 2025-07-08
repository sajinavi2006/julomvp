import tempfile
import os
import logging

from django.contrib import messages
from django.shortcuts import render
from django.utils import timezone

from juloserver.portal.object import (
    julo_login_required,
    julo_login_required_multigroup,
)
from juloserver.disbursement.forms import (
    DailyDisbursementLimitWhitelistForm,
)
from juloserver.disbursement.constants import (
    DailyDisbursementLimitWhitelistConst,
)
from juloserver.disbursement.tasks import (
    process_daily_disbursement_limit_whitelist_task,
)
from juloserver.julo.models import Document
from juloserver.julo.tasks import upload_document

logger = logging.getLogger(__name__)


@julo_login_required
@julo_login_required_multigroup(['product_manager'])
def daily_disbursement_limit_whitelist_view(request):
    def _render(request, upload_form=None):
        if not upload_form:
            upload_form = DailyDisbursementLimitWhitelistForm()
        return render(
            request,
            '../../disbursement/templates/daily_disbursement_limit_whitelist.html',
            {'form': upload_form}
        )

    if request.method == 'GET':
        return _render(request)

    upload_form = DailyDisbursementLimitWhitelistForm(request.POST, request.FILES)
    current_user = request.user
    username = current_user.username
    if upload_form.is_valid():
        timestamp = timezone.localtime(timezone.now()).strftime("%Y%m%d%H%M")
        reason = 'Daily Disbursement Limit uploading by {} timestamp: {}'.format(
            username, timestamp
        )
        upload_file = request.FILES.get("file_field")
        upload_form.cleaned_data.pop('file_field')
        if upload_file:
            filename = '{}_{}_{}'.format(username, timestamp, upload_file.name)
            file_path = os.path.join(tempfile.gettempdir(), filename)
            with open(file_path, 'wb') as f:
                f.write(upload_file.read())

            document = Document.objects.create(
                document_source=current_user.id,
                document_type=DailyDisbursementLimitWhitelistConst.DOCUMENT_TYPE,
                filename=filename,
            )
            upload_document(
                document_id=document.id,
                local_path=file_path,
                is_daily_disbursement_limit_whitelist=True
            )
            process_daily_disbursement_limit_whitelist_task.delay(
                user_id=current_user.id,
                document_id=document.id,
                form_data=upload_form.cleaned_data
            )
        else:
            process_daily_disbursement_limit_whitelist_task.delay(
                user_id=current_user.id,
                document_id=None,
                form_data=upload_form.cleaned_data,
            )
        upload_form = DailyDisbursementLimitWhitelistForm()
        messages.success(request, 'Success: {}'.format(reason))
    else:
        messages.error(request, "Failed : Please check again your input")

    return _render(request, upload_form)
