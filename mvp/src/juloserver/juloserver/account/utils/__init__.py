from past.utils import old_div

from juloserver.julocore.python2.utils import py2round


def round_down_nearest(number, nearest_number):
    """
    Return number round down to nearest in nearest_number
    """
    if number > nearest_number:
        return int(py2round(old_div(number, nearest_number)) * nearest_number)
    return number


def get_first_12_digits(string):
    digits = ''.join(filter(str.isdigit, string))
    return digits[:12]
