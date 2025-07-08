from __future__ import print_function
from builtins import str
from django.core.management.base import BaseCommand
from juloserver.julo.models import Application, CreditScore


class Command(BaseCommand):
    help = 'retroactively update (assign paymnet method) for existing payment event '

    def handle(self, *args, **options):
        query = Application.objects.filter(app_version__regex=r'^1')
        for app_id, status_code in query.values_list('id', 'application_status'):
            print((app_id, status_code))
            try:
                if status_code in [133, 135]:
                    CreditScore.objects.create(application_id=app_id,
                                               score='C',
                                               message=('Anda belum dapat mengajukan pinjaman tanpa agunan karena belum '
                                                        'memenuhi kriteria pinjaman yang ada.'),
                                               products_str='[]')
                elif status_code in [170, 173, 180, 181]:
                    CreditScore.objects.create(application_id=app_id,
                                               score='B+',
                                               message=('Poin kredit Anda sangat bagus. Peluang pengajuan Anda di-ACC besar! '
                                                        'Silahkan memilih salah satu produk pinjaman di atas & selesaikan '
                                                        'pengajuan. Tinggal sedikit lagi!'),
                                               products_str='[10,20,30]')
                else:
                    CreditScore.objects.create(application_id=app_id,
                                               score='B-',
                                               message=('Poin kredit Anda bagus. Peluang pengajuan Anda di-ACC cukup besar! '
                                                        'Silahkan memilih salah satu produk pinjaman di atas & selesaikan '
                                                        'pengajuan. Tinggal sedikit lagi!'),
                                               products_str='[20,30]')
            except Exception as e:
                self.stdout.write(self.style.ERROR(str(e)))

        self.stdout.write(self.style.SUCCESS('Done'))
