from __future__ import division, unicode_literals

from past.utils import old_div


def py2round(f, ndigit=0):
    """
    Re-implement for round function with the same behavior on both python2 and python3
    """
    if not isinstance(ndigit, int):
        raise TypeError('%s object cannot be interpreted as an integer' % type(ndigit))
    f = f * (10.0 ** (ndigit))
    if round(f + 1) - round(f) != 1:
        f = f + old_div(abs(f), f) * 0.5
    f = round(f)
    return old_div(f, (10.0 ** (ndigit)))
