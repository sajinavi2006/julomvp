from future import standard_library
standard_library.install_aliases()
import urllib.request, urllib.error, urllib.parse
import base64


def get_excel_for_cashback_promo_email(document_url, filename):
    excel_data = urllib.request.urlopen(document_url).read()
    file_ext = filename.split('.')
    if file_ext == 'csv':
        file_type = 'text/csv'
    elif file_ext == 'xls':
        file_type = 'application/vnd.ms-excel'
    else:
        file_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    encoded = base64.b64encode(excel_data.encode()).decode()
    return encoded, file_type
