from redis_completion.engine import RedisEngine
from django_redis import get_redis_connection


class RedisEnginePy3(RedisEngine):
    def get_client(self):
        return get_redis_connection('redis')

    def search(self, phrase, limit=None, filters=None, mappers=None, boosts=None, autoboost=False):
        cleaned = self.clean_phrase(phrase)
        if not cleaned:
            return []

        if autoboost:
            boosts = boosts or {}
            stored = self.client.hgetall(self.boost_key)
            for obj_id in stored:
                if obj_id not in boosts:
                    boosts[obj_id] = float(stored[obj_id])

        if len(cleaned) == 1 and not boosts:
            new_key = self.search_key(cleaned[0])
        else:
            new_key = self.get_cache_key(cleaned, boosts)
            if not self.client.exists(new_key):
                # zinterstore also takes {k1: wt1, k2: wt2}
                # python3 compatible, old logic:
                # map(self.search_key, cleaned)
                self.client.zinterstore(new_key, list(map(self.search_key, cleaned)))
                self.client.expire(new_key, self.cache_timeout)

        if boosts:
            pipe = self.client.pipeline()
            for raw_id, score in self.client.zrange(new_key, 0, -1, withscores=True):
                orig_score = score
                for part in self.ksplit(raw_id):
                    if part and part in boosts:
                        score *= 1 / boosts[part]
                if orig_score != score:
                    # python3 compatible old logic:
                    # pipe.zadd(new_key, raw_id, score)
                    pipe.zadd(new_key, score, raw_id)
            pipe.execute()

        id_list = self.client.zrange(new_key, 0, -1)
        return self._process_ids(id_list, limit, filters, mappers)

    def store(self, obj_id, title=None, data=None, obj_type=None, check_exist=True):
        if title is None:
            title = obj_id
        if data is None:
            data = title

        title_score = self.score_key(self.create_key(title))

        combined_id = self.kcombine(obj_id, obj_type or '')

        if check_exist and self.exists(obj_id, obj_type):
            stored_title = self.client.hget(self.title_key, combined_id)

            # if the stored title is the same, we can simply update the data key
            # since everything else will have stayed the same
            if stored_title == title:
                self.client.hset(self.data_key, combined_id, data)
                return
            else:
                self.remove(obj_id, obj_type)

        pipe = self.client.pipeline()
        pipe.hset(self.data_key, combined_id, data)
        pipe.hset(self.title_key, combined_id, title)

        for i, word in enumerate(self.clean_phrase(title)):
            word_score = self.score_key(word) + (27**20)
            key_score = (word_score * (i + 1)) + (title_score)
            for partial_key in self.autocomplete_keys(word):
                # python3 compatible old logic:
                # pipe.zadd(self.search_key(partial_key), combined_id, key_score)
                pipe.zadd(self.search_key(partial_key), key_score, combined_id)

        pipe.execute()
