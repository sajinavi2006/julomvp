from itertools import chain
from django.db.models import Value, CharField
from juloserver.julo.models import ApplicationNote


def get_serialized_status_notes_history(application):
    status_history = application.applicationhistory_set.annotate(
        type_data=Value('Status Change', output_field=CharField()))
    notes_history = ApplicationNote.objects.filter(application_id=application.id).annotate(
        type_data=Value('Notes', output_field=CharField()))
    chained_values = chain(
        status_history.values(
            'changed_by__first_name',
            'cdate',
            'change_reason',
            'status_old',
            'status_new',
            'type_data'
        ),
        notes_history.values('added_by__first_name', 'cdate', 'note_text', 'type_data'))

    return sorted(chained_values, key=lambda instance: instance['cdate'], reverse=True)


def get_serialized_sms_email_history(application):
    email_history = application.emailhistory_set.filter(template_code='custom').annotate(
        type_data=Value('Email', output_field=CharField()))
    sms_history = application.smshistory_set.annotate(
        type_data=Value('Sms', output_field=CharField()))
    chained_values = chain(list(email_history.values()), list(sms_history.values()))

    return sorted(chained_values, key=lambda instance: instance['cdate'], reverse=True)


def get_serialized_skiptrace_history(application):
    skiptrace_history = application.skiptracehistory_set.order_by('-cdate').values(
        'call_result_id', 'call_result__name', 'skiptrace__phone_number',
        'skiptrace__contact_source', 'application_id', 'loan_id', 'payment_id',
        'start_ts', 'end_ts', 'cdate', 'agent_name')

    return skiptrace_history


def get_serialized_app_update_history(application):
    app_field_changes = application.applicationfieldchange_set.annotate(
        type_data=Value('App Detail Change', output_field=CharField()))

    return sorted(
        app_field_changes.values(
            'agent__first_name', 'cdate', 'field_name',
            'old_value', 'new_value', 'type_data'
        ), key=lambda instance: instance['cdate'], reverse=True)
