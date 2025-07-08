from django.core.files.storage import FileSystemStorage
from django.contrib import messages
from juloserver.sdk.services import xls_to_dict
from ..serializers import CashbackPromoSerializer
from django.core.urlresolvers import reverse
import tempfile
from juloserver.julo.models import Document
from django.shortcuts import redirect

def save_cashback_promo_file(cashback_promo_saved, excel_file, request):
    extension = excel_file.name.split('.')[-1]
    if extension not in ['xls', 'xlsx', 'csv']:
        messages.error(request, 'Please upload correct file excel.')
        return redirect(reverse('cashback_promo_admin:cashback_promo_add'))

    filename = 'cashback_promo_{}.xlsx'.format(cashback_promo_saved.id)
    Document.objects.create(document_source=cashback_promo_saved.id,
                            document_type='cashback_promo',
                            filename=filename)
    fs = FileSystemStorage(location=tempfile.gettempdir())
    fs.save(filename, excel_file)
    delimiter = ','
    excel_data = xls_to_dict(excel_file, delimiter)
    number_of_customer = 0
    total_money = 0
    for idx_sheet, sheet in enumerate(excel_data):
        number_of_customer = len(excel_data[sheet])
        for idx_rpw, row in enumerate(excel_data[sheet]):
            serializer = CashbackPromoSerializer(data=row)
            if serializer.is_valid():
                data = serializer.data
                total_money += data['cashback']
            else:
                messages.error(request, 'Template or some of the data is invalid please fix it first.')
                return redirect(reverse('cashback_promo_admin:cashback_promo_add'))
    return number_of_customer, total_money
