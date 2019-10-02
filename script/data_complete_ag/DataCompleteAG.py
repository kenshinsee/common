#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import json
import requests
import sys
from common.step_status import StepStatus
from agent.master import MasterHandler
from agent.app import App
from log.logger import Logger


class DataCompleteAG:
    """
    Check alert generation completeness status for all cycles.
    """

    def __init__(self, context):
        self.context = context
        self.alerts_url = self.context["meta"]["api_alerts_str"]
        self.schedule_url = self.context["meta"]["api_schedule_str"]
        self.job_url = self.context["meta"]["api_job_str"]
        self._logger = self.context["logger"]
        self.body = {"job_id": self.context["jobId"], "step_id": self.context["stepId"],
                     "status": StepStatus.RUNNING.name}

    def get_url_response(self, url, method="POST", **kwargs):
        """
        Getting response from url
        :return: response
        """
        self._logger.info(url)
        if method.upper() not in ["GET", "POST", "PUT"]:
            method = "GET"
        response = requests.request(method=method, url=url, verify=False, **kwargs)
        if response.status_code != requests.codes.ok:
            self._logger.warning("The response result is: %s" % response.text)
            self._logger.error("Calling API failed. Refer to API: %s" % url)

        self._logger.debug("The response is: %s " % response.text)

        return response

    def get_job_definition_id(self, job_def_name):
        """
        Getting job definition id
        :return: job definition id
        """
        _url = "{}/schedule/jobdefinitions".format(self.schedule_url)
        response = self.get_url_response(url=_url, method="GET", headers=self.context["header"]).json()
        for d in response:
            if d["jobDefName"] == job_def_name:
                job_definition_id = d["id"]
                return job_definition_id
        raise Exception('Not found "{}", please check job definition'.format(job_def_name))

    def _get_available_cycle(self):
        """
        Getting available cycle
        :return: payload of available cycle
        """

        _url = "{}/availablecycles".format(self.alerts_url)
        response = self.get_url_response(url=_url, headers=self.context["header"]).json()
        available_cycle = response["data"]
        if not available_cycle or not available_cycle.get("payload", []):
            self._logger.error("No available cycles returned at the time being, refer to API: %s" % _url)

        return available_cycle.get("payload", [])

    def get_schedule(self, group_name):
        """
        Getting schedule
        :return: schedule
        """

        _url = "{}/schedule/{}/schedules".format(self.schedule_url, group_name)
        response = self.get_url_response(url=_url, method="GET", headers=self.context["header"]).json()
        if response:
            schedule_id = response[0]["id"]
        else:
            schedule_id = ""

        return schedule_id

    def _get_data_complete(self, request_body):
        """
        Getting alert generation completeness status
        :return: response from API retailerAFM
        """

        self.body["status"] = StepStatus.RUNNING.name
        self.body["message"] = "Checking Data Complete AG {}".format(request_body)
        self._logger.info("Checking Data Complete AG {}".format(request_body))

        _url = "{}/retailerAFM/status".format(self.alerts_url)
        response = self.get_url_response(url=_url, json=request_body, headers=self.context["header"]).json()
        self._logger.info("The AFM status info is: %s" % str(response))

        return response

    def _get_alert_gen_status(self, sla_time, cycle_key):
        """

        :return:
        """
        self._logger.info("The alert gen status info is not passed. Getting it via API.")
        _headers = {"content-type": "application/json", "sla_time": sla_time}
        _alerts_url = "{url}/{cycle_key}/alertgen/status".format(url=self.alerts_url, cycle_key=cycle_key)
        self._logger.info("Calling alertgen status API(GET): %s with headers: %s" % (_alerts_url, _headers))
        _resp = requests.get(url=_alerts_url, headers=_headers, verify=False)
        if _resp.status_code != requests.codes.ok or str(_resp.json().get("status")).lower() != "success":
            self._logger.warning("The response result is: %s" % _resp.text)
            self._logger.error("The given cycle: %s is no available." % cycle_key)

        self._logger.debug("Result of calling AlertGen status API is: %s" % _resp.json())

        _alert_gen_info = _resp.json()["data"]

        return _alert_gen_info

    def _request_afm(self, request_body):
        """
        Call newjobs to invoke AFM
        request_body format:
        {
          "groupName": "6:20",
          "paras": {}
          "priority": 0,
          "scheduleId": 51
        }
        :return:
        """

        # _url = "{}/retailerAFM/newJobs".format(self.alerts_url)
        _url = "{}/job/newjobs".format(self.job_url)
        self._logger.info("Calling API:%s to create AFM new job with request body: %s." % (_url, request_body))
        response = self.get_url_response(url=_url, json=request_body, headers=self.context["header"]).json()
        self._logger.info("Calling newJobs info is: %s" % str(response))

        if response["status"].upper() == StepStatus.SUCCESS.name:
            self.body["status"] = StepStatus.SUCCESS.name
            self.body["message"] = "Alter generation data complete, request has send to AFM"
            self._logger.info(self.body)
        else:
            self.body["status"] = StepStatus.ERROR.name
            self.body["message"] = response
            self._logger.warning(self.body)

    def _process_data_complete(self):
        """
        Process data
        :return:
        """

        try:
            self._logger.info("Data complete AG check start")
            job_definition_id = self.get_job_definition_id("OSARetailerAFM")

            for cycle in self._get_available_cycle():
                _group_name = "{}:{}".format(job_definition_id, cycle["cycle_key"])
                _schedule_id = self.get_schedule(_group_name)

                if _schedule_id:
                    _body = {"afm_definition_id": job_definition_id,
                             "cycle_key": cycle["cycle_key"],
                             "sla_time": cycle["sla_time_est"],
                             "schedule_id": _schedule_id
                             }
                    # Check if AFM job can be run now.
                    response = self._get_data_complete({"data": [_body]})
                    if response.get("data", []):
                        # pass cycle info and alertgen status info to AFMService.
                        _alert_gen_status = self._get_alert_gen_status(sla_time=cycle["sla_time_est"], cycle_key=cycle["cycle_key"])
                        if not _alert_gen_status or not _alert_gen_status["payload"]:
                            self._logger.warning("The alertgen might not be ready at the time being "
                                                 "for given sla_time: %s and cycle: %s"
                                                 % (cycle["sla_time_est"], cycle["cycle_key"]))
                            continue

                        _paras = {
                            "alertgen_status_info": _alert_gen_status,
                            "cycle_info": {"sla_time_est": cycle["sla_time_est"]}
                        }

                        _afm_body = {
                            "groupName": _group_name,
                            "scheduleId": _schedule_id,
                            "priority": 0,
                            "paras": _paras
                        }
                        self._request_afm(request_body=_afm_body)  # invoke retailerAFM job.

            self._logger.info("Data complete AG check done")

        except Exception as msg:
            self.body["message"] = msg
            self.body["status"] = StepStatus.ERROR.name
            self._logger.error(self.body)
            raise

    def process(self):
        self._process_data_complete()

        
class DataCompleteAGNanny(DataCompleteAG):

    def __init__(self, meta, request_body, logger=None):
        logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="dataCompleteAGNanny")
        logger.set_keys(log_id="{}_{}".format(request_body["jobId"], request_body["stepId"]))
        logger.debug(request_body)
        request_body["header"] = {"Content-Type": "application/json", "hour_offset": "-6", "module_name": logger.format_dict["module_name"]}
        request_body["log_level"] = request_body.get("log_level", 20)
        logger.set_level(request_body["log_level"])

        DataCompleteAG.__init__(self, {**request_body, **{"meta": meta}, **{"logger": logger}})
        
        
class DataCompleteAGHandler(MasterHandler):

    def set_service_properties(self):
        self.service_name = 'dataCompleteAGNanny'
        
    
class DataCompleteAGApp(App):
    '''
    This class is just for testing, osa_bundle triggers it somewhere else
    '''
    def __init__(self, meta):
        App.__init__(self, meta=meta, service_bundle_name='dataCompleteAGNanny')
    
    
if __name__ == "__main__":
    #import configparser
    #from log.logger import Logger
    #
    #with open("{}/../../../config/config.properties".format(sys.argv[0])) as fp:
    #    cp = configparser.ConfigParser()
    #    cp.read_file(fp)
    #    meta = dict(cp.items("DEFAULT"))
    #body = {"jobId": 1234567890, "stepId": 1, "body": "Data complete AG done", "meta": meta}
    #log_file = "{}_{}.log".format(sys.argv[0], body["jobId"])
    #body["meta"]["logger"] = Logger(log_level="INFO", target="console|file", module_name="dc_ag_service",
    #                                log_file=log_file)
    #dc = DCWrapperAG(meta=body["meta"])
    #dc.on_action(body)
    ## d = DataCompleteAG(body)
    ## d.process()

    '''REQUEST BODY
    Schedule will send POST request to this to get payload from Available Cycles API,
    organize json data to call retailerAFM, then post return to API invokeRetailerAFM
    POST body like
    {
        "jobId": 1234567890,
        "stepId": 1,
        "batchId": 1,
        "retry": 0,
        "log_level": 20,
        "gropName": 22
    }
    log_level: optional default 20 AS Info, refer logging level
    '''
    import os
    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    exec(open(generic_main_file).read())
    
    # app = DataCompleteAGApp(meta=meta)   #************* update services.json --> dataCompleteAGNanny.service_bundle_name to dataCompleteAGNanny before running the script
    # app.start_service()

    logger = Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="dataCompleteAGNanny")
    _body = {
        "jobId": 1234567890,
        "stepId": 1,
        "batchId": 1,
        "retry": 0,
        "log_level": 10,
        "groupName": "6:20"
    }

    afm = DataCompleteAGNanny(meta=meta, request_body=_body)
    afm.process()
