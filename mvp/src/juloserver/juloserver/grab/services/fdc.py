from juloserver.julo.models import FDCInquiry
from django.utils import timezone
from dateutil.relativedelta import relativedelta


def get_fdc_inquiry_data(application_id: int, day_diff: int):
    """
    :params application_id
    :params day_diff: it's from fs. used to check data is out of date or not.
    """
    fdc_inquiry = FDCInquiry.objects.filter(
        application_id=application_id, inquiry_status='success'
    ).last()

    result = {
        "fdc_inquiry": fdc_inquiry,
        "is_out_date": False,
        "is_pending": False
    }

    if day_diff:
        day_after_day_diff = timezone.now().date() - relativedelta(days=day_diff)
        if fdc_inquiry:
            if fdc_inquiry.udate.date() < day_after_day_diff:
                result.update({
                    "fdc_inquiry": None,
                    "is_out_date": True
                })
        else:
            # get last fdc, no mater what the inquiry status
            # if pending, just inform it
            fdc_inquiry = FDCInquiry.objects.filter(application_id=application_id).last()
            if fdc_inquiry:
                result.update({"is_pending": fdc_inquiry.inquiry_status == 'pending'})

    return result


def get_fdc_data_without_expired_rules(parameters, application_id):
    fdc_inquiry_dict = get_fdc_inquiry_data(
        application_id=application_id,
        day_diff=parameters['fdc_data_outdated_threshold_days']
    )

    fdc_inquiry = fdc_inquiry_dict.get("fdc_inquiry")

    if not fdc_inquiry:
        fdc_inquiry_dict = get_fdc_inquiry_data(
            application_id=application_id,
            day_diff=0
        )
        fdc_inquiry = fdc_inquiry_dict.get('fdc_inquiry')

    return fdc_inquiry
