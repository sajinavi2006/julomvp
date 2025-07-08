from django.utils import timezone


def get_first_day_in_month():
    return timezone.localtime(timezone.now()).date().replace(day=1)
