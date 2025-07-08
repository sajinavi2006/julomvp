from enum import Enum


class RateLimitMessages(Enum):
    Default = "Coba lagi dalam beberapa saat dan pastikan kamu cukup 1 kali lakukan permintaan, ya!"


class RateLimitAlgorithm(Enum):
    FixedWindow = 0
    SlidingWindow = 1


class RateLimitParameter(Enum):
    Path = 1
    HTTPMethod = 2
    IP = 3
    AuthenticatedUser = 4

    @classmethod
    def get_default(self):
        return [
            self.Path,
            self.HTTPMethod,
            self.IP,
        ]


class RateLimitCount:
    DefaultPerMinute = 20


class RateLimitTimeUnit(Enum):
    Seconds = 0
    Minutes = 1
    Hours = 2
    Days = 3

    @classmethod
    def get_ttl(self, time_unit):
        if time_unit is self.Seconds:
            return 1
        elif time_unit is self.Minutes:
            return 60
        elif time_unit is self.Hours:
            return 3600
        elif time_unit is self.Days:
            return 86400
        return 0
