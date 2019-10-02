#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import requests
import json
from common.step_status import StepStatus
from agent.master import MasterHandler
from agent.app import App
from api.capacity_service import Capacity
from api.config_service import Config
from log.logger import Logger
from db.db_operation import DWOperation, SiloOperation, MSOperation


class DataCompleteBlob:
    """
    Check SPD dump completeness status for only retail compass cycles.
    """

    def __init__(self, context):
        self.context = context
        self.meta = self.context["meta"]
        self._logger = self.context["logger"]
        self.body = {"job_id": self.context["jobId"], "step_id": self.context["stepId"], "status": StepStatus.RUNNING.name}
        self._db = MSOperation(meta=self.meta)
        self._dw = DWOperation(meta=self.meta)
        self._common_schema = self.meta["db_conn_vertica_common_schema"]
        self._check_spd_url = "{}/availablecycle/rc/action".format(self.meta["api_alerts_str"])
        self.pacific_job_def_name = "OSAPacificNotification"

    def get_url_response(self, url, method="POST", **kwargs):
        """
        Get response from url
        :return: response
        """
        self._logger.info(url)
        if method.upper() not in ["GET", "POST", "PUT"]:
            method = "GET"

        response = requests.request(method=method, url=url, verify=False, **kwargs)
        if response.status_code != requests.codes.ok:
            self._logger.warning("The response result is: %s" % response)
            self._logger.error("Calling API: %s failed with args: %s." % (url, str(kwargs)))

        self._logger.info(response.json())

        return response

    def _get_available_cycles(self):
        """
        Get all available cycles
        :return: available cycles
        """

        _url = "{}/availablecycles".format(self.meta["api_alerts_str"])
        resp = self.get_url_response(url=_url, headers=self.context["header"])
        if resp.status_code != requests.codes.ok:
            self._logger.warning("The response result is: %s" % resp.text)
            self._logger.error("Calling API failed. Refer to API: %s" % _url)

        response = resp.json()
        available_cycles = response["data"]
        if not available_cycles or not available_cycles.get("payload", []):
            self._logger.error("No available cycles returned at the time being, refer to API: %s" % _url)

        return available_cycles.get("payload", [])

    def _get_available_rc_cycles(self):
        """
        Getting all rc cycles based on all available cycles for only retail compass..
        :return: rc cycles
        """
        _available_rc_cycles = []
        _available_cycles = self._get_available_cycles()
        for cycle in _available_cycles:
            # Checking if all vendor_retailer pairs enabled rc. filter out vendor_retailer which not enable RC.
            _vendor_retailer_pairs = cycle["vendor_retailer_pair"]
            _tmp_rc_cycle = cycle
            _tmp_rc_cycle["vendor_retailer_pair"] = []  # reset list
            _tmp_rc_cycle["rc_id"] = []  # rc_id: [1, 2, 3, ...]

            for _vendor_retailer in _vendor_retailer_pairs:
                rc_id = _vendor_retailer["rc_id"]
                if rc_id is not None:  # Meaning this vendor & retailer enabled rc.
                    _tmp_rc_cycle["vendor_retailer_pair"].append(_vendor_retailer)
                    _tmp_rc_cycle["rc_id"].append(rc_id)
                    _tmp_rc_cycle["retailer_key"] = _vendor_retailer["retailer_key"]  # can be override since retailer_key should always be the same for same cycle_key

            if _tmp_rc_cycle["vendor_retailer_pair"]:
                _available_rc_cycles.append(_tmp_rc_cycle)

        return _available_rc_cycles

    def get_job_definition_id(self, job_def_name):
        """
        Get job definition id for given job definition name. e.g. OSAAlerting,
        :return: job definition id
        """

        _url = "{}/schedule/jobdefinitions".format(self.meta["api_schedule_str"])
        resp = self.get_url_response(url=_url, method="GET", headers=self.context["header"])
        if resp.status_code != requests.codes.ok:
            self._logger.warning("The response result is: %s" % resp.text)
            self._logger.error("Calling API failed. Refer to API: %s" % _url)

        response = resp.json()
        for d in response:
            if d["jobDefName"] == job_def_name:
                job_definition_id = d["id"]
                return job_definition_id

        # return 6   # testing purpose
        raise Exception('Not found "{}", please check job definition'.format(job_def_name))

    def get_schedule_info(self, group_name):
        """
        Get schedule info for given groupName
        :return: schedule info
        """
        _url = "{}/schedule/{}/schedules".format(self.meta["api_schedule_str"], group_name)
        resp = self.get_url_response(url=_url, method="GET", headers=self.context["header"])
        if resp.status_code != requests.codes.ok:
            self._logger.warning("The response result is: %s" % resp.text)
            self._logger.error("Calling API failed with param: %s. Refer to API: %s" % (group_name, _url))

        if resp:
            schedule_info = resp.json()[0]  # get the first one. Normally there will be only 1 element.
        else:
            schedule_info = {}

        return schedule_info

    def _check_spd_dumping_status(self, rc_cycle_key):
        """
        Checking if SPD tables of all vendors have been dumped to BlobStorage for this given cycle
        :param rc_cycle_key:
        :return: cycle_info
        """

        rc_cycle_info = {}
        self._logger.info("Checking if spd data is already dumped to blob storage...")
        resp = self.get_url_response(url=self._check_spd_url, method="GET")
        if resp.status_code != requests.codes.ok or str(resp.json().get("status")).lower() != "success":
            self._logger.error("Calling api: %s failed. Refer to: %s" % (self._check_spd_url, resp.text))

        resp_json = resp.json().get("data")
        if resp_json:
            _cycle_info = list(filter(lambda x: x["cycle_key"] == rc_cycle_key, resp_json))
            if _cycle_info:
                # The cycle_key must be unique. So if matched, then it should be the first element in the list.
                rc_cycle_info = _cycle_info[0]

        return rc_cycle_info

        test_resp = '''
        {
            "status": "success",
            "data": [
                {
                    "cycle_key": 3,
                    "sla_time": "2019-06-10 11:00:00",
                    "rc_action": "RUN",
                    "vendor_keys": [
                        55
                    ],
                    "date_range": [
                        20190515,
                        20190520
                    ]
                },
                {
                    "cycle_key": 84,
                    "sla_time": "2019-06-10 18:00:00",
                    "rc_action": "SKIP",
                    "vendor_keys": [
                        300,
                        500
                    ],
                    "date_range": null
                }
            ],
            "error": null
        }
        '''

    def _request_pacific_notification_api(self, request_body):
        """
        Call job service API to invoke new job.
        This api will create a new job based on given params
        :return:
        """

        _url = "{}/job/newjobs".format(self.meta["api_job_str"])
        _headers = {"Content-Type": "application/json"}
        resp = self.get_url_response(url=_url, method="POST", json=request_body, headers=_headers)
        if resp.status_code != requests.codes.ok:
            self._logger.warning("The response result is: %s" % resp.text)
            self._logger.error("Calling API failed with body: %s. Refer to API: %s" % (request_body, _url))

        response = resp.json()
        if response["status"].upper() == StepStatus.SUCCESS.name:
            self.body["status"] = StepStatus.SUCCESS.name
            self.body["message"] = "data complete blob checking completed, invoke PacificNotification job."
            self._logger.info(self.body)
        else:
            self.body["status"] = StepStatus.ERROR.name
            self.body["message"] = response
            self._logger.warning(self.body)

    def _data_complete_blob(self):
        """
        SPD Data completeness check
        :return:
        """
        try:
            self._logger.info("SPD Data completeness check start")

            _rc_available_cycles = self._get_available_rc_cycles()
            for cycle_info in _rc_available_cycles:
                self._logger.debug("Current cycle is: %s" % cycle_info)
                _cycle_key = cycle_info["cycle_key"]

                # if SPD table is synced to blob storage, then call PacificNotification job.
                _rc_cycle_info = self._check_spd_dumping_status(rc_cycle_key=_cycle_key)
                if not _rc_cycle_info:
                    self._logger.warning("There is no data returned for given cycle_key: %s" % _cycle_key)
                    continue

                if str(_rc_cycle_info["rc_action"]).upper() == 'RUN':
                    # create a schedule for PacificNotification job
                    job_definition_id = self.get_job_definition_id(job_def_name=self.pacific_job_def_name)
                    # Be Noted: PacificNotification schedule is like: jobDefId:singleton
                    _schedule_group_name = "{}:singleton".format(job_definition_id)
                    _schedule_info = self.get_schedule_info(group_name=_schedule_group_name)  # e.g. {"parametersContext": {}, "priority": 1, "id": 22}
                    if not _schedule_info:
                        self._logger.error("There is no job schedule configed for PacificNotificationNanny")

                    # Below paras has to be dict.
                    _group_name = "{}:{}".format(job_definition_id, _cycle_key)
                    _param_context = _schedule_info.get("parametersContext")
                    _paras = json.loads(_param_context if _param_context else "{}")
                    _paras["vendors"] = _rc_cycle_info["vendor_keys"]
                    _paras["dateRange"] = _rc_cycle_info["date_range"]
                    _paras["rcId"] = cycle_info["rc_id"]
                    _paras["retailerKey"] = cycle_info["retailer_key"]
                    _body = {"groupName": _group_name,
                             "paras": _paras,
                             "priority": _schedule_info.get("priority", 0),
                             "scheduleId": _schedule_info["id"]
                             }
                    self._logger.debug("The body is: %s" % _body)
                    self._request_pacific_notification_api(request_body=_body)

                elif str(_rc_cycle_info["rc_action"]).upper() == 'SKIP':
                    self._logger.warning("The rc_action is SKIP for cycle_key: %s" % _cycle_key)

        except Exception as msg:
            self._logger.warning(str(msg))
            raise

    def process(self):
        """
        main process
        :return:
        """

        try:
            self.body["status"] = StepStatus.RUNNING.name
            self.body["message"] = "Checking SPD Data dump Completeness"
            self._logger.info("DataComplete Blob process is getting started...")
            self._data_complete_blob()

        except Exception as msg:
            self.body["message"] = msg
            self.body["status"] = StepStatus.ERROR.name
            self._logger.error(self.body)


class DataCompleteBlobNanny(DataCompleteBlob):

    def __init__(self, meta, request_body, logger=None):
        logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1,
                                              module_name="DataCompleteBlobNanny")
        logger.set_keys(log_id="{}_{}".format(request_body["jobId"], request_body["stepId"]))
        request_body["log_level"] = request_body.get("log_level", 20)
        logger.set_level(request_body["log_level"])
        logger.debug(request_body)

        request_body["header"] = {"Content-Type": "application/json", "hour_offset": "-6",
                                  "module_name": logger.format_dict["module_name"]}
        DataCompleteBlob.__init__(self, {**request_body, **{"meta": meta}, **{"logger": logger}})


class DataCompleteBlobHandler(MasterHandler):

    def set_service_properties(self):
        self.service_name = 'DataCompleteBlobNanny'


class DataCompleteBlobApp(App):
    '''
    This class is just for testing, osa_bundle triggers it somewhere else
    '''

    def __init__(self, meta):
        App.__init__(self, meta=meta, service_bundle_name='DataCompleteBlobNanny')


if __name__ == "__main__":
    '''REQUEST BODY
    Schedule will send POST request to this to get payload from Available Cycles API,
    organize json data to call data complete blob, then post return to API invoke PacificNotification
    POST body like
    {
        "jobId": 1234567890,
        "stepId": 1,
        "batchId": 1,
        "retry": 0,
        "log_level": 10,
        "groupName": 22
    }
    log_level: optional default 20 AS Info, refer logging level
    '''
    import os

    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    exec(open(generic_main_file).read())

    # ************* update services.json --> DataCompleteBlobNanny.service_bundle_name to DataCompleteBlobNanny before running the script
    # app = DataCompleteBlobApp(meta=meta)
    # app.start_service()
    context = {'jobId': 123456789, 'stepId': 1, 'batchId': 0, 'retry': 0,
               'groupName': '6:singleton',
               'log_level': 10,
               }
    inst = DataCompleteBlobNanny(meta=meta, request_body=context)
    inst.process()
