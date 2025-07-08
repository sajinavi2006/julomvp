
from juloserver.cashback.constants import BULK_SIZE_DEFAULT


def chunker_iterables(iterables, size=BULK_SIZE_DEFAULT):
    res = []
    for iterable in iterables:
        for el in iterable:
            res.append(el)
            if len(res) == size:
                yield res
                res = []
    if res:
        yield res


def chunker(seq, size=BULK_SIZE_DEFAULT):
    res = []
    for el in seq:
        res.append(el)
        if len(res) == size:
            yield res
            res = []
    if res:
        yield res
