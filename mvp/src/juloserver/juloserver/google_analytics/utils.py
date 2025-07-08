from itertools import islice


def chunks_dictionary(dictionary, size):
    it = iter(dictionary)
    for i in range(0, len(dictionary), size):
        yield {k: dictionary[k] for k in islice(it, size)}
