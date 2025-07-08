import io
from cacheops import cached
from zipfile import ZIP_DEFLATED, ZipFile
from django.http.response import HttpResponse
from juloserver.julo.models import ProductLineCodes
from juloserver.apiv2.constants import DropdownResponseCode
from juloserver.apiv1.dropdown import write_dropdowns_to_buffer


def generate_dropdown_data(product_line_code, request, url, api_version=None):
    if (
        product_line_code not in ProductLineCodes.all()
        and product_line_code not in ProductLineCodes.julo_one()
    ):
        return DropdownResponseCode.PRODUCT_NOT_FOUND, 'Product line code not found'

    in_memory, file_size = generate_dropdown_zip(request, product_line_code, url, api_version)
    if file_size > 22:  # A zip file binary header is 22 bytes
        in_memory.seek(0)
        response = HttpResponse(content=in_memory.read(), content_type="application/zip")
        response["Content-Disposition"] = "attachment; filename=dropdowns.zip"
        response['Content-Length'] = file_size
        return DropdownResponseCode.NEW_DATA, response

    return DropdownResponseCode.UP_TO_DATE, 'Up to date'


def generate_dropdown_zip(request, product_line_code, url, api_version=None):
    """
    Generate file dropdown in memory
    And sent file to response, and set invalidate per-day.

    request.GET example
    addresses=16&banks=5&colleges=1&companies=2&jobs=7&loan_purposes=117&majors=1
    &marketing_sources=2&uker_bri=1&birthplace=1
    """

    @cached(timeout=60 * 60 * 3, extra=url)
    def _generate_dropdown_zip():
        in_memory = io.BytesIO()
        zip_file = ZipFile(in_memory, "a", ZIP_DEFLATED)
        write_dropdowns_to_buffer(zip_file, request.GET, int(product_line_code), api_version)

        # close the file
        zip_file.close()
        file_size = in_memory.tell()
        return in_memory, file_size

    return _generate_dropdown_zip()
