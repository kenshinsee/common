#!/usr/bin/env python
# coding=utf-8

import os, json
import requests
from log.logger import Logger


class ScheduleParamsToTable(object):
    """
    :input: schedule_params.json under same folder. Note: this config file name is hardcoded.
    :output: table RSI_CORE_SCHEDULE.
    :usage: python ScheduleParamsToTable.py

    :description:
    This is a temp solution for loading schedule parameters data from json format into schedule rule tables. Since the frontend UI is not yet working.
    It is mainly for job OSMAlerting. But also supports other jobs.
    Refer to above json string for the format template. When the frontend finished, this module will be also retired.
    """
    def __init__(self, meta, params, logger=None, filename="schedule_params.json"):
        """
        :param meta:      common config
        :param params:    used by calling REST API
        :param filename:  only used for local testing
        """
        self.meta = meta
        self.params = params
        self.filename = filename
        self._logger = logger if logger else Logger(log_level="debug", target="console",
                                                    vendor_key=-1, retailer_key=-1, sql_conn=None)

        self.job_url = self.meta["api_schedule_str"]   # http://engv3dstr2.eng.rsicorp.local/common
        self.headers = {#"tokenid": "eyJhbGciOiJIUzI1NiJ9.eyJjb29raWVWYWx1ZSI6IkFRSUM1d00yTFk0U2Zjd1ZidkJILXZOWFhEYS1HQm1ETlVpd240dWtMSzBsNEJjLipBQUpUU1FBQ01ERUFBbE5MQUJNek16azRPVEkyTXpFNU5EZzJNemMwTnpZeUFBSlRNUUFBKiIsInVzZXJJZCI6ImJlbi53dUByc2ljb3JwLmxvY2FsIiwiY29va2llTmFtZSI6InJzaVNzb05leHRHZW4iLCJzdGF0dXMiOiJzdWNjZXNzIiwiaWF0IjoxNTM0ODE1NTAxfQ.Hbv_wcsEqmUBFTy64BTf15nWC94fsFTfmt3LZMq24Ag",
                        "content-type": "application/json"}

        self.find_job_def_url = self.job_url + '/schedule/jobdefinitions'
        self._logger.info("URL to find the job definition is: %s " % self.find_job_def_url)

        # self.body = self.get_data()    # for local testing
        self.body = self.params    # getting data from params directly instead of reading from config file.
        self.group_name = self.body["groupName"]
        self.schedule_name = self.body["scheduleName"]
        self.job_name = str(self.schedule_name).split(":")[-1]  # getting job_name from scheduleName
        self.find_schedule_url = self.job_url + "/schedule/" + str(self.group_name) + "/schedules"
        self.update_schedule_url = self.job_url + "/schedule/schedules"
        self._logger.info("URL to check schedule for given groupname is: %s " % self.find_schedule_url)
        self._logger.info("URL to add/update the schedule is: %s " % self.update_schedule_url)

    def get_data(self):
        with open(self.filename, 'r') as fp:
            json_data = json.load(fp=fp)
        return json_data

    def get_job_def_id(self):
        res = requests.get(url=self.find_job_def_url, headers=self.headers, verify=False)
        if res.text == "invalid token":
            self._logger.warning("WARNING: Please update the tokenid manually. "
                                 "Then rerun this script again!!!")
            exit(1)

        x = [dct["id"] for dct in res.json() if dct["jobDefName"] == self.job_name]
        if not x:
            self._logger.info("There is no job id found for job: %s. You can refer to API: %s"
                              % (self.job_name, self.find_job_def_url))
            exit(1)
        return x[0]

    def check_schedule_id(self):
        req = requests.get(url=self.find_schedule_url, headers=self.headers, verify=False)
        if req.text == "invalid token":
            self._logger.warning("WARNING: Please update the tokenid manually. Then rerun this script again!!!")
            exit(1)
        r = req.json()
        return r

    def load_data(self):
        self.body["jobDefinitionId"] = self.get_job_def_id()
        res = self.check_schedule_id()

        # addSchedule if schedule not exists
        if not res:
            self._logger.info("There is no schedule id for group name: %s. So adding a new schedule." % self.group_name)
            self._logger.info("The parameters are: %s " % self.body)

            res = requests.post(self.update_schedule_url, json=self.body, headers=self.headers, verify=False)
            if res.status_code != 200:
                self._logger.info("Adding schedule failed with body: %s" % self.body)
                self._logger.info(res.text)
                exit(1)

            self._logger.info(res.text)
            self._logger.info("Adding new schedule successfully!!! Please validate table RSI_CORE_SCHEDULE.")

        # updateSchedule if schedule already exists
        else:
            # get the first one. Normally there will be only 1 element. just incase there are more.
            schedule_id = res[0]["id"]
            self._logger.info("Found related schedule_id: %s for group name: %s. "
                              "Updating this schedule_id." % (schedule_id, self.group_name))

            self.body["id"] = schedule_id
            self._logger.info("The parameters are: %s " % self.body)
            res = requests.put(self.update_schedule_url, json=self.body, headers=self.headers, verify=False)
            if res.status_code != 200:
                self._logger.info("Updating schedule failed with body: %s" % self.body)
                self._logger.info(res.text)
                exit(1)

            self._logger.info(res.text)
            self._logger.info("Updating schedule successfully!!! Please validate table RSI_CORE_SCHEDULE.")


if __name__ == "__main__":
    # getting meta
    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    meta = {}
    exec(open(generic_main_file).read())  # fill meta argument

    loader = ScheduleParamsToTable(meta=meta, params={})
    loader.load_data()
