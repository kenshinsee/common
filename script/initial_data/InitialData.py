#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import json
import sys
import requests
from common.step_status import StepStatus
from agent.master import MasterHandler
from agent.app import App


class InitialData:
    """
    Initial Data
    """
    def __init__(self, context):
        self.context = context.copy()
        self.body = {"vendor_key": context["vendor_key"], "retailer_key": context["retailer_key"],
                     "status": StepStatus.RUNNING.name}
        self._logger = context["logger"]
        self.body["message"] = "Initial Data start"
        self._logger.info(self.body)
        self._lst_hub = []

    def get_url_response(self, url, method="POST", **kwargs):
        """Get response from url
        :return: response
        """
        self._logger.info(url)
        if method.upper() not in ["GET", "POST", "PUT"]:
            method = "GET"
        response = requests.request(method=method, url=url, verify=False, **kwargs)
        self._logger.info(response.json())
        return response

    def _get_hub_ids(self):
        """Get attribute from config table
        :return:
        """
        for vendor_key in self.body["vendor_key"]:
            self.body["vendor_key"] = vendor_key
            properties = requests.get("{}/properties?vendorKey={}&retailerKey={}".format(
                self.context["meta"]["api_config_str"], vendor_key, self.body["retailer_key"])).json()
            if properties:
                if properties[0]["hubId"] not in self._lst_hub:
                    self._lst_hub.append(properties[0]["hubId"])
            else:
                self.body["message"] = ("None properties data found by vendor_key {} and retailer_key {}"
                                        "".format(self.body["vendor_key"], self.body["retailer_key"]))
                self._logger.warning(self.body)
        self.body["vendor_key"] = self.context["vendor_key"]
        if self._lst_hub:
            return self._lst_hub
        else:
            self.body["message"] = self._logger.warning("None data found by vendor_key {} and retailer_key {}"
                                                        "".format(self.body["vendor_key"], self.body["retailer_key"]))
            self._logger.warning(self.body)
            return None

    def get_job_definition_id(self, job_def_name):
        """Get job definition id
        :return: job_definition_id
        """
        response = self.get_url_response(
            url="{}/schedule/jobdefinitions".format(self.context["meta"]["api_schedule_str"]),
            method="GET", headers=self.context["header"]).json()
        for d in response:
            if d["jobDefName"] == job_def_name:
                job_definition_id = d["id"]
                return job_definition_id
        self.body["message"] = self._logger.warning('Not found "{}", please check job definition'.format(job_def_name))
        self._logger.error(self.body)

    def _sync_dim_data(self, lst_hub):
        """Call Sync Dim Data service
        :return:
        """
        job_definition_id = self.get_job_definition_id("OSASyncDimData")
        group_name = "{}:singleton".format(job_definition_id)
        api_schedule = self.get_url_response(
            url="{}/job/{}/scheduleDetails".format(self.context["meta"]["api_job_str"], group_name), method="GET",
            headers=self.context["header"]).json()
        schedule_id = api_schedule[0]["id"]
        #request_json = {"groupName": group_name, "scheduleId": schedule_id, "paras": {"hubIDs": lst_hub}}
        request_json = {"groupName": group_name, "scheduleId": schedule_id}
        response = self.get_url_response(
            url="{}/job/newjobs".format(self.context["meta"]["api_job_str"], group_name), method="POST",
            headers=self.context["header"], json=request_json).json()
        self._logger.debug(response)
        if response["status"] == StepStatus.SUCCESS.name:
            self.body["status"] = StepStatus.SUCCESS.name
            self.body["message"] = "OSASyncDimData {} job request has send".format(group_name)
            self._logger.info(self.body)
        else:
            self.body["status"] = StepStatus.ERROR.name
            self.body["message"] = response
            self._logger.warning(self.body)

    def _process_initial_data(self):
        """Process to initial data
        :return:
        """
        try:
            lst_hub = self._get_hub_ids()
            if lst_hub:
                self._sync_dim_data(lst_hub)
            self.body["message"] = ("Sync dim data done from hubs {}".format(lst_hub))
            self._logger.info(self.body)
        except Exception as msg:
            self._logger.error(msg)
        finally:
            self.body["message"] = "Initial Data end"
            self._logger.info(self.body)

    def process(self):
        self._process_initial_data()


class InitialDataNanny(InitialData):

    def __init__(self, meta, request_body, logger=None):
        logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="initialDataNanny")
        
        meta = meta.copy()
        request_body["log_level"] = request_body.get("log_level", 20)
        logger.set_level(request_body["log_level"])
        logger.set_keys(log_id="{}_{}".format(request_body["retailer_key"], request_body["vendor_key"]))
        request_body["header"] = {"Content-Type": "application/json", "module_name": logger.format_dict["module_name"]}
        
        InitialData.__init__(self, {**request_body, **{"meta": meta}, **{"logger": logger}})
    

class InitialDataHandler(MasterHandler):

    def set_service_properties(self):
        self.service_name = 'initialDataNanny'
        self.set_as_not_notifiable()
        
    
class InitialDataApp(App):
    '''
    This class is just for testing, osa_bundle triggers it somewhere else
    '''
    def __init__(self, meta):
        App.__init__(self, meta=meta, service_bundle_name='InitialData')
    
    
        
if __name__ == '__main__':
    #import configparser
    #from log.logger import Logger
    #with open("{}/../../../config/config.properties".format(sys.argv[0])) as fp:
    #    cp = configparser.ConfigParser()
    #    cp.read_file(fp)
    #    meta = dict(cp.items("DEFAULT"))
    #body = {"body": "Initial Data done", "meta": meta, "retailer_key": 5240, "vendor_key": [300, 15]}
    #log_file = "{}_{}.log".format(sys.argv[0], body['retailer_key'])
    #body["logger"] = Logger(log_level="INFO", target="console|file", module_name="sdd_service", log_file=log_file)
    ## initial_data = InitialDataWrapper(meta=body["meta"])
    ## initial_data.on_action(body)
    #initial_data = InitialData(body)
    #initial_data.process()

    '''REQUEST BODY
    {
      "retailer_key": 6,
      "vendor_key": [300, 342],
      "log_level": 20
    }
    '''
    import os
    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    exec(open(generic_main_file).read())
    
    app = InitialDataApp(meta=meta)   #************* update services.json --> dataCleanupNanny.service_bundle_name to initial_data before running the script
    app.start_service()
