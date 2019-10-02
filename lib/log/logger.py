import json
import logging
import traceback
from datetime import datetime
from pytz import timezone, utc
from log.db_handler import LogDBHandler


class Logger(object):

    def __init__(self, log_level="INFO", target="console", module_name="DEFAULT", vendor_key=-1, retailer_key=-1,
                 log_file=None, sql_conn=None, log_id="-1_-1"):
        __numeric_level = getattr(logging, log_level.upper(), None)
        __format_str = '{"log_time": "%(asctime)s", "level_name": "%(levelname)s", %(message)s}'
        __date_format = "%Y-%m-%d %H:%M:%S"
        __target = ["console", "file", "table"]
        self.format_dict = {"module_name": module_name, "log_id": log_id,
                            "vendor_key": vendor_key, "retailer_key": retailer_key}

        if not isinstance(__numeric_level, int):
            raise ValueError('Invalid log level: %s' % log_level)
        if not (vendor_key and retailer_key):
            raise ValueError('Vendor key and retailer key must be specified')

        def custom_time(*args):
            utc_dt = utc.localize(datetime.utcnow())
            custom_tz = timezone("US/Eastern")
            converted = utc_dt.astimezone(custom_tz)
            return converted.timetuple()

        logging.basicConfig(level=__numeric_level, format=__format_str, datefmt=__date_format)
        logging.Formatter.converter = custom_time
        self.logger = logging.getLogger(__name__)
        self._fh = None

        for t in target.split("|"):
            if t not in __target:
                raise ValueError('Invalid target: %s' % t)
            if t == "file":
                if not log_file:
                    raise ValueError('log_file is not specified.')
                self._fh = logging.FileHandler(log_file)
                self._fh.setFormatter(logging.Formatter(__format_str, datefmt=__date_format))
                self.logger.addHandler(self._fh)
            if t == "table":
                if not (sql_conn and module_name):
                    raise ValueError('app name and db connection is not specified.')
                dbh = LogDBHandler(module_name, vendor_key, retailer_key, sql_conn)
                self.logger.addHandler(dbh)

    def set_level(self, log_level=10):
        """Set log level, 10 to 50 levelno or levelname refer below
        :param log_level:
            %(levelno)s Numeric logging level for the message (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            %(levelname)s Text logging level for the message ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        :return:
        """
        self.logger.setLevel(log_level)

    def set_keys(self, **kwargs):
        """Set log keys from input
        :param kwargs:
        :return:
        """
        self.format_dict.update(**kwargs)

    def format_log_msg(self, log_msg):
        # Strip may remove all "{}" in begin or end of string
        # if type(log_msg) == dict:
        #     self.format_dict["message"] = json.dumps(log_msg)
        # else:
        #     self.format_dict["message"] = log_msg
        self.format_dict["message"] = str(log_msg)  # message value should be the string type.
        log_msg = json.dumps(self.format_dict).strip("{}")
        return log_msg

    def debug(self, msg, *args, **kwargs):
        msg = self.format_log_msg(msg)
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        msg = self.format_log_msg(msg)
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        msg = self.format_log_msg(msg)
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        msg = self.format_log_msg("{}  --||##  {}".format(traceback.format_exc(), msg))
        self.logger.error(msg, *args, **kwargs)
        raise RuntimeError(msg)

    def critical(self, msg, *args, **kwargs):
        msg = self.format_log_msg(("{}  --||##  {}".format(traceback.format_exc(), msg)))
        self.logger.critical(msg, *args, **kwargs)
        raise RuntimeError(msg)

    def remove_handler(self):
        if self._fh:
            self.logger.removeHandler(self._fh)


if __name__ == "__main__":
    import pyodbc

    conn = pyodbc.connect("DRIVER={SQL Server};SERVER=ENGV2HHDBQA1;DATABASE=OSA;PORT=1433;UID=hong.hu;PWD=test666")

    # logger = Logger(log_level="info", target="console|file", log_file="./test.log")
    logger = Logger(log_level="info", target="console|file|table", vendor_key=10, retailer_key=20,
                    log_file="./test.log", sql_conn=conn)
    logger.set_level(10)
    logger.debug("in debug")
    logger.info("in info")
    logger.info({"module_name": "Test", "a": 'a', 'b': "b", 'vendor_key': 0, "retailer_key": 1, 1: 1})
    logger.warning("in warning")
    # logger.error("in error")
    # logger.critical("in critical")
