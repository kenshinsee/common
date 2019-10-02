#!/usr/bin/env python
# coding=utf-8

import os, json
import requests
from optparse import OptionParser

parse = OptionParser()
parse.add_option("--retailer_key", action="store", dest="retailer_key")
parse.add_option("--vendor_key", action="store", dest="vendor_key")
parse.add_option("--meta", action="store", dest="meta")
(options, args) = parse.parse_args()

meta = json.loads(options.meta)

# scorecard parameters template
schedule_params = {
    "creater": "ben.wu@rsicorp.local",
    "groupName": "7:740:5240",
    "jobDefinitionId": 7,
    "priority": 0,
    "scheduleExpression": "0 0 2 * * ?",
    "scheduleName": "7:740:5240:OSAScorecard",
    "scheduleType": "TIME"
}


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
    def __init__(self, meta, vendor_key, retailer_key, job_name='OSAScorecard'):
        self.meta = meta
        self.vendor_key = vendor_key
        self.retailer_key = retailer_key
        self.job_name = job_name

        self.headers = {"content-type": "application/json"
                        # ,"tokenid": "eyJhbGciOiJIUzI1NiJ9.eyJjb29raWVWYWx1ZSI6IkFRSUM1d00yTFk0U2Zjd1ZidkJILXZOWFhEYS1HQm1ETlVpd240dWtMSzBsNEJjLipBQUpUU1FBQ01ERUFBbE5MQUJNek16azRPVEkyTXpFNU5EZzJNemMwTnpZeUFBSlRNUUFBKiIsInVzZXJJZCI6ImJlbi53dUByc2ljb3JwLmxvY2FsIiwiY29va2llTmFtZSI6InJzaVNzb05leHRHZW4iLCJzdGF0dXMiOiJzdWNjZXNzIiwiaWF0IjoxNTM0ODE1NTAxfQ.Hbv_wcsEqmUBFTy64BTf15nWC94fsFTfmt3LZMq24Ag"
                        }

        self.job_url = self.meta["api_schedule_str"]   # http://engv3dstr2.eng.rsicorp.local/common
        self.find_job_def_url = self.job_url + '/schedule/jobdefinitions'
        print("URL to find the job definition is: %s " % self.find_job_def_url)

        self.body = self.get_schedule_params()
        self.group_name = self.body["groupName"]
        self.find_schedule_url = self.job_url + "/schedule/" + str(self.group_name) + "/schedules"
        self.update_schedule_url = self.job_url + "/schedule/schedules"
        print("URL to check schedule for given groupname is: %s " % self.find_schedule_url)
        print("URL to add/update the schedule is: %s " % self.update_schedule_url)

    def get_schedule_params(self):
        _job_def_id = self.get_job_def_id()
        _group_name = '{0}:{1}:{2}'.format(_job_def_id, self.vendor_key, self.retailer_key)
        _schedule_name = '{0}:{1}'.format(_group_name, self.job_name)
        schedule_params["groupName"] = _group_name
        schedule_params["jobDefinitionId"] = _job_def_id
        schedule_params["scheduleName"] = _schedule_name
        expr = schedule_params["scheduleExpression"].split(' ')
        # spread the schedules between 02:00:00 to 02:19:59
        expr[0] = str(int(self.vendor_key)%60)
        expr[1] = str(int(self.retailer_key)%20)
        schedule_params["scheduleExpression"] = ' '.join(expr)
        # schedule_params["parametersContext"] = ""
        print("The parameters for scorecard schedule are: %s " % schedule_params)
        return schedule_params

    def get_job_def_id(self):
        res = requests.get(url=self.find_job_def_url, headers=self.headers, verify=False)
        if res.text == "invalid token":
            print("WARNING: Please update the tokenid manually. Then rerun this script again!!!")
            exit(1)
        x = [dct["id"] for dct in res.json() if dct["jobDefName"] == self.job_name]
        # print(x, type(x))
        if not x:
            print("There is no job id found for job: %s. You can refer to API: %s" % (self.job_name, self.find_job_def_url))
            exit(1)
        return x[0]

    def check_schedule_id(self):
        req = requests.get(url=self.find_schedule_url, headers=self.headers, verify=False)
        if req.text == "invalid token":
            print("WARNING: Please update the tokenid manually. Then rerun this script again!!!")
            exit(1)
        r = req.json()
        return r

    def load_data(self):
        res = self.check_schedule_id()
        # print(res, type(res))

        # addSchedule if schedule not exists
        if not res:
            print("There is no schedule id for group name: %s. So adding a new schedule." % self.group_name)
            res = requests.post(self.update_schedule_url, json=self.body, headers=self.headers, verify=False)
            if res.status_code != 200:
                print("Adding schedule failed with body: %s" % self.body)
                print(res.text)
                exit(1)
            print(res.text)
            print("Adding new schedule successfully!!! Please validate table RSI_CORE_SCHEDULE.")

        # updateSchedule if schedule already exists
        else:
            schedule_id = res[0]["id"]  # get the first one. Normally there will be only 1 element. just incase there are more.
            print("Found related schedule_id: %s for group name: %s. Updating this schedule_id." % (schedule_id, self.group_name))

            self.body["id"] = schedule_id
            # print(self.body)
            res = requests.put(self.update_schedule_url, json=self.body, headers=self.headers, verify=False)
            if res.status_code != 200:
                print("Updating schedule failed with body: %s" % self.body)
                print(res.text)
                exit(1)
            print(res.text)
            print("Updating schedule successfully!!! Please validate table RSI_CORE_SCHEDULE.")


if __name__ == "__main__":
    # getting meta
    # SEP = os.path.sep
    # cwd = os.path.dirname(os.path.realpath(__file__))
    # generic_main_file = cwd + SEP + '..' + SEP + '..' + SEP + '..' + SEP + 'script' + SEP + 'main.py'
    # CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    # meta = {}
    # exec(open(generic_main_file).read())  # fill meta argument
    # loader = ScheduleParamsToTable(meta=meta, vendor_key=740, retailer_key=5240, job_name='OSAScorecard')

    loader = ScheduleParamsToTable(meta=meta, vendor_key=options.vendor_key, retailer_key=options.retailer_key, job_name='OSAScorecard')
    loader.load_data()
