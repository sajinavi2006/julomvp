from juloserver.promo.constants import PromoCodeCriteriaConst


def chunker_list(data, chunksize=PromoCodeCriteriaConst.WHITELIST_BATCH_SIZE):
    for i in range(0, len(data), chunksize):
        yield data[i:i+chunksize]
