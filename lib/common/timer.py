import time
import datetime
from log.logger import Logger

class Timer:

    def __call__(self, func):
        def _func(*args, **kwargs):
            start_ts = datetime.datetime.now()
            msg = func(*args, **kwargs)
            end_ts = datetime.datetime.now()
            time_elapsed = end_ts - start_ts
            print('[%s] Time elapsed: %s'%(func, time_elapsed))
            return msg
        return _func
