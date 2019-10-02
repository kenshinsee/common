from agent.master import MasterHandler
from log.logger import Logger
import requests


class MobileNotifier(object):
    def __init__(self, meta, params, logger=None):
        self.meta = meta
        self.params = params
        self.logger = logger if logger else Logger(log_level="INFO", target="console", vendor_key=-1, retailer_key=-1)
        self.alert_url = self.meta["api_alerts_str"]
        self.alert_mobile_url = "{url}/mobilemessage".format(url=self.alert_url)
        self.group_name = self.params.get("groupName", "")
        self.cycle_key = ""
        self.sla_time = self.params.get("sla_time", "")

    def process(self):
        """
        Calling API to notify mobile service when AFM is done.
        :return:
        """

        try:
            self.logger.debug("params are: %s" % self.params)
            # Checking the cancel status from previous step.
            _cancel_flag = self.params.get("cancel_flag", False)
            if _cancel_flag:
                return {"cancel_flag": _cancel_flag, "message": self.params.get("message")}

            self._check_params()

            _body = {"sla_time": self.sla_time, "cycle_key": self.cycle_key}
            self.logger.info("Calling API: %s to notify mobile with body: %s" % (self.alert_mobile_url, _body))
            resp = requests.post(url=self.alert_mobile_url, data=_body, verify=False)
            if resp.text == "invalid token":
                self.logger.error("ERROR: invalid tokenid, Please update the tokenid manually. "
                                  "Then rerun this script again!!!")
            if resp.status_code != requests.codes.ok or str(resp.json().get("status")).lower() != "success":
                self.logger.warning("The response result is: %s" % resp.json())
                self.logger.error(
                    "Calling notify API failed! Refer to API: %s with body: %s" % (self.alert_mobile_url, _body))

            self.logger.info("Calling API to notify mobile completes")

            # below params are used to pass to following steps via JobService.
            afm_params = {"sla_time": self.sla_time,
                          "raw_alerts_info": self.params.get("raw_alerts_info", ""),
                          "debug": self.params.get("debug", "")}
            return afm_params

        except Exception as msg:
            self.logger.error(msg)

    def _check_params(self):
        if not self.group_name:
            self.logger.error("There is no groupName from input parameter: %s" % self.params)

        self.cycle_key = self.group_name.split(":")[1]
        if not self.sla_time:  # if no sla_time passed.
            self.logger.info("sla_time has not been passed from previous job, "
                             "Retrieve it via calling availablecycles API.")
            self.sla_time = self._get_sla_time(cycle_key=self.cycle_key)

    def _get_sla_time(self, cycle_key):
        """
        Calling availablecycles API to get sla_time for given cycle_key.
        Better to get the sla_time from preceding job instead of calling API.
        But what if there is no sla_time passed, then we can call this method to get sla_time.
        :param cycle_key:
        :return: sla_time
        """

        _cycle_url = "{0}/availablecycles".format(self.alert_url)
        _headers = {"content-type": "application/json",
                    "cycle_key": cycle_key,
                    "hour_offset": "-6"}
        self.logger.info("Calling availablecycles API(POST): %s with headers: %s" % (_cycle_url, _headers))
        resp = requests.post(url=_cycle_url, headers=_headers, verify=False)
        self.logger.debug("Result of calling availablecycles is: %s" % resp.json())
        if resp.status_code != requests.codes.ok or str(resp.json().get("status")).lower() != "success":
            self.logger.warning("The response result is: %s" % resp.json())
            self.logger.error("Calling API failed with cycle: %s. Refer to API: %s" % (cycle_key, _cycle_url))

        _cycle_data = resp.json()["data"]
        if not _cycle_data or not _cycle_data["payload"]:
            self.logger.warning("The cycle data is: %s" % _cycle_data)
            self.logger.error(
                "There is no data returned with cycle: %s. Refer to API: %s" % (cycle_key, _cycle_url))

        # For given cycle_key, There should only have one element.
        _data = _cycle_data["payload"][0]
        # Getting sla_time
        sla_time = _data.get("sla_time_est")

        return sla_time


class MobileNotifierNanny(MobileNotifier):

    def __init__(self, meta, request_body, logger=None):
        logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="MobileNotifierNanny")
        __debug = request_body.get("debug", 'N')
        __log_level = 'DEBUG' if str(__debug).upper() in ('Y', 'YES', 'TRUE', 'T') else 'INFO'
        logger.set_level(log_level=__log_level)

        MobileNotifier.__init__(self, meta={**meta}, params={**request_body}, logger=logger)


class MobileNotifierHandler(MasterHandler):

    def set_service_properties(self):
        self.service_name = 'MobileNotifierNanny'


if __name__ == "__main__":
    import os
    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + '..' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    meta = {}
    exec(open(generic_main_file).read())  # fill meta argument

    _params = {"jobId": 12345, "stepId": 1, "batchId": 0, "retry": 0,
               "groupName": "6:3",
               "sla_time": "2019-07-02 02:08:00",
               "debug": "Y"
               }
    mn = MobileNotifier(meta=meta, params=_params)
    mn.process()
