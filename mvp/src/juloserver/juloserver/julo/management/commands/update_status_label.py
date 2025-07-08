import logging
import sys

from django.core.management.base import BaseCommand

from ...models import StatusLookup, StatusLabel



logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))

def get_name_and_colour_by_status(status):

    if status == 106:
        name = "Kadaluarsa"
    elif status <= 110:
        name = "Tahap Pengajuan"
    elif status == 134:
        name = "Tahap Review"
    elif status in [133, 135, 137]:
        name = "Ditolak"
    elif status in [111, 139, 143, 171, 174]:
        name = "Kadaluarsa"
    elif status < 180:
        name = "Tahap Review"
    elif status in [210,220]:
        name = "Lancar"
    elif 230 <= status <= 237:
        name = "Terlambat"
    elif status == 250:
        name = "Lunas"
    elif status == 250:
        name = "Lunas"
    else:
        name = ""

    if (status <= 110) or (status == 134):
        colour = "#757575"
    elif status in [133, 135, 137]:
        colour = "#e0661b"
    elif status < 180:
        colour = "#757575"
    elif status in [210,220]:
        colour = "#4bab00"
    elif 230 <= status <= 237:
        colour = "#e0661b"
    elif status == 250:
        colour = "#4bab00"
    else:
        colour = "0"

    return name, colour


class Command(BaseCommand):
    help = 'Update status label table'

    def handle(self, *args, **options):
        statuses =  StatusLookup.objects.all()
        for status in statuses:

            status_label = StatusLabel.objects.filter(
                status=status.status_code).first()
            name, colour = get_name_and_colour_by_status(status.status_code)
            if status_label is not None:
                logger.info({
                    'julo_status_code': status.status_code,
                    'status': 'already_exists',
                    'action': 'updating_data'
                })
                status_label.label_name = name
                status_label.label_colour=colour
                status_label.save()
            else:
                status_label = StatusLabel(
                    status=status.status_code, label_name=name, label_colour=colour)
                status_label.save()
