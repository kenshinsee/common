from enum import Enum, unique


@unique
class DataCompleteStatus(Enum):
    Init = 0
    Green = 1
    Yellow = 2
    Red = 3


@unique
class CycleFeatures(Enum):
    RSA = 1
    RC = 2
    BOTH = 3
