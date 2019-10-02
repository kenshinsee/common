from enum import Enum, unique

@unique
class JobStatus(Enum):
    QUEUE = 0
    PENDING = 1
    DISPATCHED = 2
    RUNNING = 3
    COMPLETED = 4
    INVALID = 5
    ERROR = 6
    STOP = 7
