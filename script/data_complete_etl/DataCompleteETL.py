#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import base64
import copy
import sys
import json
import datetime
import requests
import traceback

from api.config_service import Config
from db.db_operation import DWOperation, SiloOperation, MSOperation, HubOperation
from api.job_service import JobService
from api.capacity_service import Capacity
from common.job_status import JobStatus
from common.step_status import StepStatus
from common.data_complete_status import DataCompleteStatus as ETLDataCompleteStatus
from common.data_complete_status import CycleFeatures
from log.logger import Logger


class DataCompleteETL:
    """
    Working on the pre-check to see if any new transfer set coming in. Or need to run by force.
    Then we should call "DataCompleteETLVR" to trigger OSACoreProcess/OSMAlerting job(depending on features: rsa or rc).
    """

    def __init__(self, meta, request_body, logger):
        self._meta = meta
        self._body = request_body
        self._capacity = Capacity(meta=self._meta)
        self._db = MSOperation(meta=self._meta)
        self._logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="dataCompleteETLNanny")
        self.lst_warning = []   # collection all warnings.
        self.lst_errors = {}   # collection all exceptions but continue the job.
        self.job_schedules = {'rsa': 'OSMAlerting', 'rc': 'OSACoreProcess'}
        self.num_weeks = self._body.get("numberWeeks", 5)  # this is only for min_period_key
        self.default_min_period_key = int((datetime.datetime.now() - datetime.timedelta(weeks=self.num_weeks)).strftime('%Y%m%d'))

    def process(self):
        self.lst_warning = []
        dct_to_check = {}  # e.g. {'retailer1_vendor1': {cycle_info}, 'retailer2_vendor2': {cycle_info},...}
        dct_changed = {}
        try:
            parameter_json = self._body.get("parameter_json", {})
            if "availableCycles" in parameter_json:
                api_available_cycles = parameter_json["availableCycles"]
                self._body.pop("parameter_json")  # not required further.
            else:
                _url = "{}/availablecycles".format(self._meta["api_alerts_str"])
                api_available_cycles = self.get_url_response(url=_url, headers=self._body["header"]).json()
                if not api_available_cycles["data"] or not api_available_cycles["data"].get("payload", []):
                    self._logger.error("No available cycles returned at the time being, refer to API: %s" % _url)

            self._logger.info("All available cycles are: %s" % api_available_cycles)
            payload = api_available_cycles["data"].get("payload", [])
            if not payload:
                self._logger.warning("Not available cycles found")
            else:
                for cycle in payload:
                    try:
                        _dct_to_check = self._get_to_check_retailer_vendor(cycle, parameter_json)
                        # Checking if same vendor_retailer in multi cycles.
                        # if so, issue a warning and only trigger latest one.
                        _rv_current = set(_dct_to_check.keys())  # retailer_vendor in current cycle
                        _rv_previous = set(dct_to_check.keys())  # retailer_vendor from previous cycle
                        _intersected = _rv_current.intersection(_rv_previous)
                        if _intersected:  # if intersected, means same retailer_vendor in multi cycles.
                            for rv in _intersected:
                                self._logger.warning("The vendor_retailer: %s in multi cycles. "
                                                     "Here JobService will only trigger it with groupName: %s"
                                                     % (rv, _dct_to_check[rv]['group_name']))
                        dct_to_check.update(_dct_to_check)

                    except Exception as msg:
                        message = "{} --||## {}".format(msg, traceback.format_exc())
                        self._logger.warning(message)
                        self.lst_warning.append(message)
                        self.lst_errors.setdefault("cycle_error", []).append(str(msg))
                        continue

                if dct_to_check:
                    dct_hub_retailer_vendor = self._get_hub_retailer_vendor()  # e.g. {'retailer1_vendor1': 'hubid', 'retailer2_vendor2': 'hubid',...}
                    dct_changed = self._get_changed_retailer_vendor(dct_hub_retailer_vendor, dct_to_check)
                else:
                    message = "Not retailer vendor found in available cycles, refer to payload in available cycles."
                    self._logger.warning(message)
                    self.lst_warning.append(message)

                self._logger.info("dct_changed is: %s" % str(dct_changed))
                if dct_changed:
                    for dw_server_name, _body in dct_changed.items():
                        self._logger.debug("Calling ETLVR job with json body: %s" % str(_body))
                        # _etl_vr_url = "{}/dataCompleteETLVR/process".format(self._meta["api_osa_bundle_str"])
                        # self.get_url_response(url=_etl_vr_url, headers=self._body["header"], json=_etl_vr_body)
                        _server_name = str.split(dw_server_name, '.')[0]
                        self._request_etlvr_job(request_body=_body, name=_server_name)

                        # _etl_vr_body = {**self._body, **_body}
                        # inst1 = DataCompleteETLVR(context=_etl_vr_body)  # testing purpose
                        # inst1.process()
                else:
                    message = "Not changed retailer vendor found"
                    self._logger.warning(message)
                    self.lst_warning.append(message)

            if not self.lst_warning:
                self.lst_warning.append("NO warning")

            # if any errors ignored, then return them to job service.
            if self.lst_errors:
                return "Job succeeded with warnings: " + json.dumps(self.lst_errors)  # return str instead of dict.

        except Exception as msg:
            self._logger.warning(traceback.format_exc())
            raise msg

        finally:
            if hasattr(self, "_db"):
                self._db.close_connection()
            if hasattr(self, "_db_hub"):
                self._db_hub.close_connection()

    def get_schedule_info(self, group_name):
        """
        Get schedule info for given groupName
        :return: schedule info
        """
        _url = "{}/schedule/{}/schedules".format(self._meta["api_schedule_str"], group_name)
        resp = self.get_url_response(url=_url, method="GET", headers=self._body["header"])
        if resp.status_code != requests.codes.ok:
            self._logger.warning("The response result is: %s" % resp.text)
            self._logger.error("Calling API failed with param: %s. Refer to API: %s" % (group_name, _url))

        if resp:
            schedule_info = resp.json()[0]  # get the first one. Normally there will be only 1 element.
        else:
            schedule_info = {}

        return schedule_info

    def _request_etlvr_job(self, request_body, name):
        _job_name = 'OSADataCompletenessVR'

        # create a schedule for OSADataCompletenessVR job
        job_definition_id = self.get_job_definition_id(job_def_name=_job_name)
        # Be Noted: _job_name schedule is like: jobDefId:singleton
        _schedule_group_name = "{}:singleton".format(job_definition_id)
        _schedule_info = self.get_schedule_info(group_name=_schedule_group_name)  # e.g. {"parametersContext": {}, "priority": 1, "id": 22}
        if not _schedule_info:
            self._logger.error("There is no job schedule configed for OSADataCompletenessVR")

        _group_name = '{}:{}'.format(job_definition_id, name)
        _body = {"groupName": _group_name,
                 "paras": request_body,
                 "priority": _schedule_info.get("priority", 0),
                 "scheduleId": _schedule_info["id"]
                 }
        _url = "{}/job/newjobs".format(self._meta["api_job_str"])
        _headers = {"Content-Type": "application/json"}
        resp = self.get_url_response(url=_url, method="POST", json=_body, headers=_headers)
        if resp.status_code != requests.codes.ok:
            self._logger.warning("The response result is: %s" % resp.text)
            self.lst_errors.setdefault("trigger_error", []).append(str(resp.text))

    def get_url_response(self, url, method="POST", **kwargs):
        """
        Get response from url
        :return: response
        """
        self._logger.info("Calling url: %s " % url)
        if method.upper() not in ["GET", "POST", "PUT"]:
            method = "GET"
        response = requests.request(method=method, url=url, verify=False, **kwargs)
        if response.status_code != requests.codes.ok:
            self._logger.warning("The response result is: %s" % response.text)
            self._logger.error("Calling API failed. Refer to API: %s" % url)

        self._logger.debug("The response is: %s " % response.text)

        return response

    def _get_to_check_retailer_vendor(self, cycle, parameter_json):
        """
        Getting retailer vendor info based on data returned from availablecycles API
        :return: Dict to check with format. e.g. {'retailer1_vendor1': {cycle_info},'retailer2_vendor2': {cycle_info},...}
        """
        dct_to_check = {}
        now_est = datetime.datetime.now()  # current time
        sla_time_est = datetime.datetime.strptime(cycle["sla_time_est"], "%Y-%m-%d %H:%M:%S")  # sla_time

        for retailer_vendor in cycle["vendor_retailer_pair"]:

            if retailer_vendor["data_complete_action"].upper() != 'CANCEL':
                # Getting job definition id based on features.
                _features = retailer_vendor.get("features")  # e.g. ['rsa', 'rc']
                if CycleFeatures.RSA.name.lower() in _features:  # if rsa enabled, then call OSMAlerting
                    job_definition_id = self.get_job_definition_id(self.job_schedules[CycleFeatures.RSA.name.lower()])
                elif CycleFeatures.RC.name.lower() in _features:  # if rc enabled, call OSACoreProcess
                    job_definition_id = self.get_job_definition_id(self.job_schedules[CycleFeatures.RC.name.lower()])
                else:
                    self._logger.warning("There is no rc or rsa in feature, please check: %s." % retailer_vendor)
                    continue

                _group_name = "{}:{}:{}:{}".format(job_definition_id, cycle["cycle_key"], retailer_vendor["vendor_key"], retailer_vendor["retailer_key"])

                # Getting schedule parameterContext of job from service for given groupName.
                if "schedule" in parameter_json:
                    api_schedule = parameter_json["schedule"][_group_name]
                    api_schedule[0]["parametersContext"] = json.dumps(api_schedule[0]["parametersContext"])  # convert dict to str
                else:
                    _schedule_url = "{}/job/{}/scheduleDetails".format(self._meta["api_job_str"], _group_name)
                    api_schedule = self.get_url_response(url=_schedule_url, method="GET", headers=self._body["header"]).json()

                self._logger.info("Getting job schedule detail for groupName: %s" % _group_name)
                if api_schedule:
                    _tmp_cycle = {
                        # "meet_cut_off_time": _meet_cut_off_time,
                        "check_extra_days": retailer_vendor.get("check_extra_days", []) or [],
                        "period_key": cycle["period_key"],
                        "cycle_key": cycle["cycle_key"],
                        "sla_time_est": cycle["sla_time_est"],
                        "group_name": _group_name,
                        "vendor_key": retailer_vendor["vendor_key"],
                        "retailer_key": retailer_vendor["retailer_key"],
                        "retailer_schema": self._capacity.get_retailer_schema_name(retailer_key=retailer_vendor["retailer_key"]),
                        "data_complete_action": retailer_vendor.get("data_complete_action", "").upper(),
                        "previous_data_complete_status": retailer_vendor.get("previous_data_complete_status", "").upper(),
                        "core_job_id": retailer_vendor.get("job_id", None),
                        "rc_id": retailer_vendor.get("rc_id", None),
                        "features": _features,
                        "data_complete_log": retailer_vendor.get("data_complete_log"),
                        "schedule_id": api_schedule[0]["id"]
                    }

                    parameters_context = api_schedule[0].get("parametersContext", "{}")
                    parameter = json.loads(parameters_context if parameters_context else "{}")
                    if parameter:
                        _data_complete_params = json.loads(base64.standard_b64decode(
                            parameter["JobSteps"][0]["DefaultSetting"]["paraDataCompleteETL"]).decode("utf-8"))
                        _tmp_cycle["parameter"] = _data_complete_params

                        # OSA-3968 : The 2 hours is configurable now.
                        # be noted: the sla_time_est is est time, please be aware when testing from local time zone
                        _time_interval_to_go = _data_complete_params.get("time_interval_to_go", 2)
                        if now_est >= sla_time_est - datetime.timedelta(hours=_time_interval_to_go):
                            _meet_cut_off_time = True
                        else:
                            _meet_cut_off_time = False
                        self._logger.info("Now in EST: {}, SLA in EST: {}, "
                                          "Meet cut off time: {} for vendor_retailer: {}"
                                          .format(now_est, sla_time_est, _meet_cut_off_time, retailer_vendor))

                        # _tmp_cycle["time_interval_to_go"] = _time_interval_to_go
                        _tmp_cycle["meet_cut_off_time"] = _meet_cut_off_time

                        if _tmp_cycle["core_job_id"]:
                            # Getting job status for given job_id if job existing
                            _url = "{}/job/jobs/{}".format(self._meta["api_job_str"], _tmp_cycle["core_job_id"])
                            response = self.get_url_response(url=_url, method="GET", headers=self._body["header"]).json()
                        else:
                            response = {"data": {"status": "None"}}

                        self._logger.debug("The response is: %s" % response)
                        if response["data"]:
                            # Filter out those jobs which are in running status.
                            if (response["data"]["status"] not in [JobStatus.QUEUE.name, JobStatus.PENDING.name,
                                                                   JobStatus.DISPATCHED.name, JobStatus.RUNNING.name]):
                                dct_to_check["{retailer_key}_{vendor_key}".format(**retailer_vendor)] = copy.deepcopy(
                                    _tmp_cycle)
                                self._logger.debug("The dct_to_check is: %s" % dct_to_check)
                            else:
                                _tmp_cycle["message"] = "OSA core job {} is running, skip".format(_tmp_cycle["core_job_id"])
                                self._logger.warning(_tmp_cycle)
                                self.lst_warning.append(_tmp_cycle["message"])
                        else:
                            _tmp_cycle["message"] = "Not found job {} status from jobs".format(_tmp_cycle["core_job_id"])
                            self._logger.warning(_tmp_cycle)
                            self.lst_warning.append(_tmp_cycle["message"])

                    else:
                        _tmp_cycle["message"] = "Not found parameter data from schedule"
                        self._logger.warning(_tmp_cycle)
                        self.lst_warning.append(_tmp_cycle["message"])

                else:
                    _message = "Not found schedules detail info for groupName: {}".format(_group_name)
                    self._logger.warning(_message)
                    self.lst_warning.append(_message)

            else:
                self._logger.warning("The data_complete_action is cancel for retailer_vendor: %s" % retailer_vendor)

        return dct_to_check

    def get_job_definition_id(self, job_def_name):
        """
        Get job definition id
        :return: job_definition_id
        """
        _job_def_url = "{}/schedule/jobdefinitions".format(self._meta["api_schedule_str"])
        resp = self.get_url_response(url=_job_def_url, method="GET", headers=self._body["header"])
        if resp.status_code != requests.codes.ok:
            self._logger.warning("The response result is: %s" % resp.text)
            self._logger.error("Calling API failed. Refer to API: %s" % _job_def_url)

        response = resp.json()
        for job in response:
            if job["jobDefName"] == job_def_name:
                job_definition_id = job["id"]
                return job_definition_id

        raise Exception('Not found "{}", please check job definition'.format(job_def_name))

    def _get_hub_retailer_vendor(self):
        """
        Getting all available HUBs from NXG and all associated silos.
        :return: dict with format like: {'retailer1_vendor1': 'hub_id', 'retailer2_vendor2': 'hub_id', ...}
        """

        # TODO: if the same vendor_retailer has multi hubs? then how to handle this?
        dct = {}
        hubs = self.get_url_response(url="{}/hubs".format(self._meta["api_config_str"]),
                                     method="GET", headers=self._body["header"]).json()

        for hub in hubs:
            silos = self.get_url_response(url="{}/{}/silos".format(self._meta["api_config_str"], hub),
                                          method="GET", headers=self._body["header"]).json()
            for silo in silos:
                if silo["silo_type"].upper() not in ("MR", "ALERT", "CAT", "WMCAT"):
                    for retailer_vendor in silo["vendor_retailer_mappings"]:
                        dct["{retailer_key}_{vendor_key}".format(**retailer_vendor)] = hub

        if dct:
            return dct
        else:
            self._logger.error("None hub retailer vendor data found")

    def _get_changed_retailer_vendor(self, all_retailer_vendor, retailer_vendor_to_check):
        """
        Getting changed retailer_vendor(silo) list info

        :param all_retailer_vendor:
        :param retailer_vendor_to_check:
        :return: dct_changed. e.g. {'server_name': {<info>} }
        """

        dct = {None: []}  # e.g. {'hub_id1': ['retailer_vendor1', 'retailer_vendor2', ...], 'hub_id2': [], ...}
        lst_changed = []  # e.g. [("5240_300", 20190101), ("5240_664", 20190101), ...]
        for hub in set(all_retailer_vendor.values()):
            dct[hub] = []

        # check if need to skip to run
        for retailer_vendor, value_info in retailer_vendor_to_check.items():
            try:
                self._logger.info("Checking if need to skip to run for retailer_vendor: %s" % retailer_vendor)
                dct[all_retailer_vendor.get(retailer_vendor, None)].append(retailer_vendor)  # if given retailer_vendor is not existing in HUB, then ignore it.
                # if meet any of following cases, then go trigger core job, no need to check transfer set further.
                if (
                        value_info["data_complete_action"] == "SKIP"
                        or (value_info["data_complete_action"] == "RUN" and value_info["core_job_id"] is not None)
                        or (value_info["meet_cut_off_time"] and value_info["previous_data_complete_status"] == "YELLOW")
                        or (value_info["meet_cut_off_time"] and value_info["check_extra_days"])
                ):
                    if retailer_vendor not in dct[None]:
                        lst_changed.append(retailer_vendor)
                        _previous_data_complete_log = value_info["data_complete_log"]
                        # There will not be checking transfer_ts if meets above conditions. Then
                        # 1, we should fill out transfer_ts and min_period_key with previous value.
                        if _previous_data_complete_log and json.loads(_previous_data_complete_log).get("curr_transfer_ts"):
                            data_complete_log_json = json.loads(_previous_data_complete_log)
                            retailer_vendor_to_check[retailer_vendor]["prev_transfer_ts"] = data_complete_log_json.get(
                                "prev_transfer_ts")
                            retailer_vendor_to_check[retailer_vendor]["curr_transfer_ts"] = data_complete_log_json.get(
                                "curr_transfer_ts")
                            retailer_vendor_to_check[retailer_vendor]["min_period_key"] = min(
                                data_complete_log_json.get("min_period_key"), self.default_min_period_key)
                            retailer_vendor_to_check[retailer_vendor]["sla_time"] = retailer_vendor_to_check.get(
                                "sla_time_est")
                        # 2, give default value if there is no previous value found(might be the first-run).
                        else:
                            retailer_vendor_to_check[retailer_vendor]["prev_transfer_ts"] = '2000-01-01 00:00:00.000'
                            retailer_vendor_to_check[retailer_vendor]["curr_transfer_ts"] = '2000-01-01 00:00:00.000'
                            retailer_vendor_to_check[retailer_vendor]["min_period_key"] = 20000101
                            retailer_vendor_to_check[retailer_vendor]["sla_time"] = retailer_vendor_to_check.get(
                                "sla_time_est")

            except Exception as msg:
                self._logger.warning(msg)
                self.lst_errors.setdefault("skip_check_error", []).append(str(msg))
                continue

        self._logger.warning("None matched retailer vendors is: {}".format(dct.pop(None)))
        self._logger.info("The lst_changed for skipped customers is : %s" % str(lst_changed))

        # Checking other vendor&retailers except those skipped.
        for hub, retailer_vendors in dct.items():
            try:
                if hub and retailer_vendors:
                    # if do NOT meet above 3 cases, then checking if new transfer_set generated.
                    retailer_vendor_required = list(set(retailer_vendors) - set(lst_changed))
                    if retailer_vendor_required:
                        # _lst_with_changed_transfer = self._get_changed_transfer(hub, retailer_vendor_required)
                        _lst_with_changed_transfer = self._get_changed_transfer_new(hub, retailer_vendor_required,
                                                                                    retailer_vendor_to_check)
                        lst_changed.extend(_lst_with_changed_transfer)

            except Exception as msg:
                message = "{} --||## {}".format(msg, traceback.format_exc())
                self._logger.warning(message)
                self.lst_warning.append(message)
                self.lst_errors.setdefault("ts_check_error", []).append(str(msg))
                continue

        self._logger.info("The lst_changed for all customers is : %s" % str(lst_changed))
        dct_changed = {}
        for _retailer_vendor in set(lst_changed):
            try:
                # _min_period_key = retailer_vendor_to_check[_retailer_vendor].get("min_period_key")  # getting min period_key
                _retailer = _retailer_vendor.split("_")[0]
                _vendor = _retailer_vendor.split("_")[1]
                _prop_url = "{}/properties?vendorKey={}&retailerKey={}".format(self._meta["api_config_str"], _vendor, _retailer)
                properties = self.get_url_response(url=_prop_url, method="GET", headers=self._body["header"]).json()

                dw_server_name = properties[0]["configs"]["dw.server.name"]
                # put all retailer&vendors with the same dw server into one group.
                _retailer_vendor_info = retailer_vendor_to_check[_retailer_vendor]
                # remove data_complete_log from dict, since This param is not required for succeeding job.
                _retailer_vendor_info.pop("data_complete_log") if "data_complete_log" in _retailer_vendor_info else _retailer_vendor_info
                if dw_server_name not in dct_changed:
                    dct_changed[dw_server_name] = {"dw_server_name": dw_server_name,
                                                   "changed_retailer_vendor": [_retailer_vendor],
                                                   _retailer_vendor: _retailer_vendor_info
                                                   }
                else:
                    dct_changed[dw_server_name]["changed_retailer_vendor"].append(_retailer_vendor)
                    dct_changed[dw_server_name][_retailer_vendor] = _retailer_vendor_info

            except Exception as msg:
                message = "{} --||## {}".format(msg, traceback.format_exc())
                self._logger.warning(message)
                self.lst_warning.append(message)
                self.lst_errors.setdefault("property_error", []).append(str(msg))
                continue

        return dct_changed

    def _get_changed_transfer_new(self, hub, retailer_vendors, retailer_vendor_to_check):
        """

        :param hub:
        :param retailer_vendors:
        :param retailer_vendor_to_check:
        :return: lst_changed
        """

        dct = {}
        lst_changed = []  # e.g. ['retailer_vendor1', 'retailer_vendor2', ...]
        dct_previous = {}  # e.g. {'retailer_vendor1': transfer_ts1, 'retailer_vendor2': transfer_ts2, ...}
        if hasattr(self, "_db_hub"):
            self._db_hub.close_connection()
        self._db_hub = HubOperation(hub_id=hub, meta=self._meta)

        # Getting the transfer_ts from last run via the data_complete_log column.
        for retailer_vendor in retailer_vendors:
            value_info = retailer_vendor_to_check[retailer_vendor]
            _curr_sla_time = value_info.get("sla_time_est")
            _previous_data_complete_log = value_info.get("data_complete_log")
            if _previous_data_complete_log and (retailer_vendor in retailer_vendors)\
                    and json.loads(_previous_data_complete_log).get("curr_transfer_ts"):
                data_complete_log_json = json.loads(_previous_data_complete_log)
                # the same vendor_retailer for given sla_time could run multi-time to check new transfer set.
                # if the sla_time from data_complete_log is not equal to the current sla_time.
                # meaning this could be first-run for the given sla_time to check transfer set.
                if _curr_sla_time != data_complete_log_json.get("sla_time_est"):
                    dct_previous[retailer_vendor] = data_complete_log_json.get("curr_transfer_ts")
                    retailer_vendor_to_check[retailer_vendor]["prev_transfer_ts"] = data_complete_log_json.get("curr_transfer_ts")
                    retailer_vendor_to_check[retailer_vendor]["curr_transfer_ts"] = data_complete_log_json.get("curr_transfer_ts")
                    retailer_vendor_to_check[retailer_vendor]["min_period_key"] = self.default_min_period_key  # default value when first run for given sla_time
                else:  # meaning this is not the first-run for the current given sla_time.
                    dct_previous[retailer_vendor] = data_complete_log_json.get("curr_transfer_ts")
                    retailer_vendor_to_check[retailer_vendor]["prev_transfer_ts"] = data_complete_log_json.get("prev_transfer_ts")
                    retailer_vendor_to_check[retailer_vendor]["curr_transfer_ts"] = data_complete_log_json.get("curr_transfer_ts")
                    retailer_vendor_to_check[retailer_vendor]["min_period_key"] = min(int(data_complete_log_json.get("min_period_key")), self.default_min_period_key)
            else:  # if no data_complete_log or no transfer_ts in data_complete_log, then fill out default value.
                retailer_vendor_to_check[retailer_vendor]["prev_transfer_ts"] = '2000-01-01 00:00:00.000'
                retailer_vendor_to_check[retailer_vendor]["curr_transfer_ts"] = '2000-01-01 00:00:00.000'
                retailer_vendor_to_check[retailer_vendor]["min_period_key"] = 20000101

        # for row in self._db.query("SELECT RV, LATEST_DATE FROM {} WHERE UPDATE_TIME IS NOT NULL".format(temp_table)):
        #     dct_previous[row.RV] = row.LATEST_DATE
        self._logger.info("Previous date of vendor and retailer {}".format(dct_previous))

        # Gen sub_query from OSA db as this sub_query will be used below on HUB silo. it is cross db.
        # noted: if update_time is null then here it will be converted to 'None' in Python. same for other columns.
        sub_query_sql = " UNION ALL ".join("SELECT '{0}' as RV, '{1}' as LATEST_DATE "
                                           .format(str(rv), str(ts))
                                           for rv, ts in dct_previous.items())
        self._logger.info("The query of previous transfer_ts is: %s" % sub_query_sql)

        if sub_query_sql:
            # if this is not the first time for the given vendor&retailer
            # then apply the timestamp filter to get incremental data.
            sql = ("SELECT CONCAT(TD.retailer_key,'_',TD.vendor_key) RV, "
                   "       CONVERT(VARCHAR, MAX(TFD.TRANSFER_DAILY_START), 120) LATEST_DATE, "
                   "       MIN(tfd.period_key) MIN_PERIOD_KEY "
                   "FROM ETL.RSI_TRANSFER_DETAIL TD WITH(NOLOCK) "
                   "JOIN ETL.RSI_TRANSFER_FACT_DAILY TFD WITH(NOLOCK) "
                   "ON TFD.TRANSFER_DETAIL_KEY=TD.TRANSFER_DETAIL_KEY "
                   "LEFT JOIN ({}) tmp "
                   "ON tmp.rv = CONCAT(TD.retailer_key,'_',TD.vendor_key) "
                   "WHERE TD.REFERENCE_TYPE='FACT' AND (TD.DIM_NAME IS NULL OR TD.DIM_NAME NOT IN "
                   "    ('DC','DCPD','DCFCST','DCPOFACT','FDBK-ARIA','PROMO-DIM','STOREPOFACT','MRBFW-STORE')) "
                   "AND CONCAT(TD.retailer_key,'_',TD.vendor_key) IN ('{}') AND TFD.TRANSFER_DAILY_STATUS = 'COMPLETE' "
                   "AND TFD.TRANSFER_DAILY_START > coalesce(tmp.LATEST_DATE, CAST(CAST('19000101' AS DATETIME) AS VARCHAR)) "
                   "GROUP BY CONCAT(TD.retailer_key,'_', TD.vendor_key) "
                   "".format(sub_query_sql, "','".join(retailer_vendors)))
        else:
            # if not getting trans_ts, meaning this is the first time, then getting all transfer data.
            sql = ("SELECT CONCAT(TD.retailer_key,'_',TD.vendor_key) RV, "
                   "       CONVERT(VARCHAR, MAX(TFD.TRANSFER_DAILY_START), 120) LATEST_DATE, "
                   "       MIN(tfd.period_key) MIN_PERIOD_KEY "
                   "FROM ETL.RSI_TRANSFER_DETAIL TD WITH(NOLOCK) "
                   "JOIN ETL.RSI_TRANSFER_FACT_DAILY TFD WITH(NOLOCK) "
                   "ON TFD.TRANSFER_DETAIL_KEY=TD.TRANSFER_DETAIL_KEY "
                   "WHERE TD.REFERENCE_TYPE='FACT' AND (TD.DIM_NAME IS NULL OR TD.DIM_NAME NOT IN "
                   "    ('DC','DCPD','DCFCST','DCPOFACT','FDBK-ARIA','PROMO-DIM','STOREPOFACT','MRBFW-STORE')) "
                   "AND CONCAT(TD.retailer_key,'_',TD.vendor_key) IN ('{}') AND TFD.TRANSFER_DAILY_STATUS = 'COMPLETE' "
                   "GROUP BY CONCAT(TD.retailer_key,'_', TD.vendor_key) "
                   "".format("','".join(retailer_vendors)))
        self._logger.info(sql)
        for row in self._db_hub.query(sql):
            dct[row.RV] = (row.LATEST_DATE, row.MIN_PERIOD_KEY)

        self._logger.info("Latest date of retailer and vendor is: {}".format(dct))

        for RV, t in dct.items():  # update the min_period_key & curr_trans_ts if new transfer found.
            if RV in dct_previous:   # got previous transfer_ts
                # checking if transfer_ts changed since last check. if so, update dict, else keep previous values.
                if self._db.query_scalar("SELECT DATEDIFF(SECOND, '{}', '{}')".format(dct_previous[RV], t[0])) != 0:
                    # lst_changed.append((RV, t[1]))
                    lst_changed.append(RV)
                    retailer_vendor_to_check[RV]["curr_transfer_ts"] = t[0]
                    # Always getting the minimal period_key from every time run.This is for the same day of given cycle_retailer_vendor.
                    retailer_vendor_to_check[RV]["min_period_key"] = min(t[1], retailer_vendor_to_check[RV]["min_period_key"])

            else:  # no previous transfer_ts
                lst_changed.append(RV)
                retailer_vendor_to_check[RV]["curr_transfer_ts"] = t[0]
                retailer_vendor_to_check[RV]["min_period_key"] = min(t[1], retailer_vendor_to_check[RV]["min_period_key"])

        return lst_changed


class DataCompleteETLVR:
    """
    Check SVR ETL completeness status for all vendor/retailer pairs within input.
    If checking result meet the condition, skip validation if data matched in table ETL_DATA_COMPLETE
    """

    def __init__(self, context):
        self.context = context
        self.meta = self.context["meta"]
        _logger = Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="DataCompleteETLVRNanny")
        self._logger = self.context.get("logger", _logger)
        self._job_service = JobService(meta=self.meta)
        self._db = MSOperation(meta=self.meta)
        self.body = {"job_id": self.context["jobId"], "step_id": self.context["stepId"], "status": StepStatus.RUNNING.name}
        self._logger.info("Data complete ETL check start: %s" % self.body)
        self.lst_errors = {}

    def process(self):
        self._process_data_complete_etl()

        # if any errors ignored, then return them to job service.
        if self.lst_errors:
            return "Job succeeded with warnings: " + json.dumps(self.lst_errors)  # return str instead of dict.

        if hasattr(self, "_dw_source"):
            self._dw_source.close_connection()
        if hasattr(self, "_db"):
            self._db.close_connection()

    def _process_data_complete_etl(self):
        """
        Process data
        :return:
        """

        self._get_silo_dw_connection()  # all vendor&retailer are in the same Vertica cluster.
        for retailer_vendor in self.context["changed_retailer_vendor"]:
            try:
                self._job_service.cancel_job_status(jobid=self.context["jobId"], stepid=self.context["stepId"])
                self._logger.info("Start to process retailer_vendor: %s" % retailer_vendor)
                self._body = self.body.copy()
                self._body.update(self.context[retailer_vendor])
                self._check_on = self._body["parameter"]["checkOn"]
                self._etl_status = ETLDataCompleteStatus.Init
                self._etl_parameter = {}
                config = Config(vendor_key=self._body["vendor_key"], retailer_key=self._body["retailer_key"],
                                meta=self.meta)
                self._schema = config.get_property("dw.schema.name", "None")
                self._request_core_paras = {"vendor_key": self._body["vendor_key"],
                                            "retailer_key": self._body["retailer_key"],
                                            "hubid": config.get_property("hub.db.name", "None"),
                                            "siloid": config.get_property("deploy.silo.id", "None"),
                                            "min_period_key": self._body.get("min_period_key"),
                                            "rc_id": self._body.get("rc_id"),
                                            "features": self._body.get("features")
                                            }

                self._logger.info("The data_complete_action is: %s for retailer_vendor: %s" %
                                   (self._body["data_complete_action"], retailer_vendor))
                if self._body["data_complete_action"] == "RUN":
                    period_keys = ([self._body["period_key"]] + self._body["check_extra_days"]
                                   if self._body["meet_cut_off_time"] else [self._body["period_key"]])
                    period_keys.sort(reverse=True)
                    self._logger.info("To be processed period_keys {} ...".format(period_keys))

                    for period_key in period_keys:
                        self._logger.info("Processing period_key: {} ...".format(period_key))
                        _flag = self._process_data_complete_etl_by_day(period_key)
                        self._logger.info("The data complete checking flag is: {}".format(_flag))
                        if _flag:
                            self._request_core_paras["end"] = period_key
                            self.request_core()
                            self._update_alert_cycle(period_key)
                            break

                        if period_key == min(period_keys):
                            # no period_key matches yellow/green threshold, update status
                            self._update_alert_cycle(period_key)

                elif self._body["data_complete_action"] == "SKIP":
                    self._request_core_paras["end"] = self._body["period_key"]
                    self.request_core()
                    self._update_alert_cycle(self._body["period_key"])
                    
                self._body["message"] = "Data complete ETL group name {} check done".format(self._body["group_name"])
                self._logger.info("Data complete ETL group name {} check done".format(self._body["group_name"]))

            except Exception as msg:
                self._logger.warning(traceback.format_exc())
                self._body["status"] = StepStatus.ERROR.name
                self._body["message"] = msg
                self.lst_errors.setdefault("main_errors", []).append(str(msg))
                continue

    def _get_silo_dw_connection(self):
        """
        Get Silo DW connection
        :return:
        """
        if hasattr(self, "_dw_source"):
            self._dw_source.close_connection()
        self._dw_source = SiloOperation(retailer_key=self.context["changed_retailer_vendor"][0].split("_")[0],
                                        vendor_key=self.context["changed_retailer_vendor"][0].split("_")[1],
                                        meta=self.meta)

    def _process_data_complete_etl_by_day(self, period_key):
        self._get_data_rate(period_key)
        return self._check_data_rate(period_key)

    def _get_data_rate(self, period_key):
        """
        Get avg value of the week days same day of week for the pre weeks, then calculate rate as current / avg
        The rate will save to their own part
        :return: Dict Rate
        """
        self._etl_parameter[period_key] = copy.deepcopy(self._body["parameter"])
        self._etl_status = ETLDataCompleteStatus.Init  # reset before processing the current period_key
        if ("pos" in self._check_on or "onHand" in self._check_on or "itemCount" in self._check_on
                or "storeCount" in self._check_on):
            self._logger.info("{} start to _check_rate_pos_on_hand for {} ...".format(self._body["group_name"], period_key))
            self._check_rate_pos_on_hand(period_key)

        if "pog" in self._check_on:
            self._logger.info("{} start to _check_rate_pog for {} ...".format(self._body["group_name"], period_key))
            self._check_rate_pog(period_key)

        if "receipt" in self._check_on:
            self._logger.info("{} start to _check_rate_receipt for {} ...".format(self._body["group_name"], period_key))
            self._check_rate_receipt(period_key)

        if "feedback" in self._check_on:
            self._logger.info(
                "{} start to _check_rate_feedback for {} ...".format(self._body["group_name"], period_key))
            self._check_rate_feedback(period_key)

    def _check_rate_pos_on_hand(self, period_key):
        """
        Checking rate of pos and on hand
        :return:
        """
        lst_period_key = self._get_pre_same_day(period_key)
        sql = ('WITH T AS ( '
               '    SELECT /*+ LABEL(GX_IRIS_DATA_COMPLETE_ETL)*/ '
               '        PERIOD_KEY, SUM("Total Units") POS, SUM("On Hand") ON_HAND, '
               '        COUNT(DISTINCT ITEM_KEY) ITEM_COUNT, COUNT(DISTINCT STORE_KEY) STORE_COUNT '
               '    FROM {schema}.ANL_STORE_SALES WHERE PERIOD_KEY IN ({period_keys}, {period_key}) '
               '    GROUP BY PERIOD_KEY) '
               'SELECT CASE WHEN P.POS = 0 OR P.POS IS NULL OR A.POS IS NULL THEN 0 ELSE A.POS / P.POS END POS_RATE, '
               '       CASE WHEN O.ON_HAND = 0 OR O.ON_HAND IS NULL OR A.ON_HAND IS NULL THEN 0 '
               '            ELSE A.ON_HAND / O.ON_HAND END ON_HAND_RATE, '
               '       CASE WHEN I.ITEM_COUNT = 0 OR I.ITEM_COUNT IS NULL OR A.ITEM_COUNT IS NULL THEN 0 '
               '            ELSE A.ITEM_COUNT / I.ITEM_COUNT END ITEM_COUNT_RATE, '
               '       CASE WHEN S.STORE_COUNT = 0 OR S.STORE_COUNT IS NULL OR A.STORE_COUNT IS NULL THEN 0 '
               '            ELSE A.STORE_COUNT / S.STORE_COUNT END STORE_COUNT_RATE '
               'FROM (SELECT * FROM T WHERE PERIOD_KEY = {period_key}) A, '
               '     (SELECT AVG(T.POS) AS POS FROM T '
               '      WHERE PERIOD_KEY in ({period_keys_pos})) P, '
               '     (SELECT AVG(T.ON_HAND) AS ON_HAND FROM T '
               '      WHERE PERIOD_KEY in ({period_keys_on_hand})) O, '
               '     (SELECT AVG(T.ITEM_COUNT) AS ITEM_COUNT FROM T '
               '      WHERE PERIOD_KEY in ({period_keys_item})) I, '
               '     (SELECT AVG(T.STORE_COUNT) AS STORE_COUNT FROM T '
               '      WHERE PERIOD_KEY in ({period_keys_store})) S '
               ''.format(schema=self._schema, period_keys=','.join(lst_period_key), period_key=period_key,
                         period_keys_pos=",".join(lst_period_key[0:self._body["parameter"]["pos"]["preWeek"]]),
                         period_keys_on_hand=",".join(lst_period_key[0:self._body["parameter"]["onHand"]["preWeek"]]),
                         period_keys_item=",".join(lst_period_key[0:self._body["parameter"]["itemCount"]["preWeek"]]),
                         period_keys_store=",".join(lst_period_key[0:self._body["parameter"]["storeCount"]["preWeek"]])
                         ))
        self._logger.info("The SQL for Checking rate of pos and on hand is: %s" % sql)
        row = self._dw_source.query(sql).fetchone()

        if "pos" in self._check_on:
            self._logger.info("Checking pos")
            if not row:
                self._logger.warning("None result with pos_on_hand sql {}.".format(sql))
                self._etl_parameter[period_key]["pos"]["currentStatus"] = '{} - No data returned'.format(
                    ETLDataCompleteStatus.Red.name)
                self._etl_parameter[period_key]["pos"]["currentValue"] = -1
                self._set_compare_etl_status(ETLDataCompleteStatus.Red)
            else:
                self._etl_parameter[period_key]["pos"]["currentValue"] = row.POS_RATE
                pos_green = self._etl_parameter[period_key]["pos"]["green"][0]
                if float(pos_green[0]) < row.POS_RATE <= float(pos_green[1]):
                    self._etl_parameter[period_key]["pos"]["currentStatus"] = ETLDataCompleteStatus.Green.name
                    self._etl_parameter[period_key]["pos"]["completeTime"] = datetime.datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S")
                    self._set_compare_etl_status(ETLDataCompleteStatus.Green)
                else:
                    pos_yellow = self._etl_parameter[period_key]["pos"]["yellow"]
                    if (float(pos_yellow[0][0]) < row.POS_RATE <= float(pos_yellow[0][1]) or
                            float(pos_yellow[1][0]) < row.POS_RATE <= float(pos_yellow[1][1])):
                        self._etl_parameter[period_key]["pos"]["currentStatus"] = ETLDataCompleteStatus.Yellow.name
                        self._set_compare_etl_status(ETLDataCompleteStatus.Yellow)
                    elif "itemCount" in self._check_on and "storeCount" in self._check_on:
                        item_count_yellow = self._etl_parameter[period_key]["itemCount"]["yellow"]
                        store_count_yellow = self._etl_parameter[period_key]["storeCount"]["yellow"]
                        self._etl_parameter[period_key]["itemCount"]["currentValue"] = row.ITEM_COUNT_RATE
                        self._etl_parameter[period_key]["storeCount"]["currentValue"] = row.STORE_COUNT_RATE
                        if ((item_count_yellow[0] < row.ITEM_COUNT_RATE <= item_count_yellow[1]) and
                                (store_count_yellow[0] < row.STORE_COUNT_RATE <= store_count_yellow[1])):
                            self._etl_parameter[period_key]["itemCount"][
                                "currentStatus"] = ETLDataCompleteStatus.Yellow.name
                            self._etl_parameter[period_key]["storeCount"][
                                "currentStatus"] = ETLDataCompleteStatus.Yellow.name
                            self._set_compare_etl_status(ETLDataCompleteStatus.Yellow)
                        else:
                            self._etl_parameter[period_key]["itemCount"][
                                "currentStatus"] = ETLDataCompleteStatus.Red.name
                            self._etl_parameter[period_key]["storeCount"][
                                "currentStatus"] = ETLDataCompleteStatus.Red.name
                            self._set_compare_etl_status(ETLDataCompleteStatus.Red)
                    else:
                        self._etl_parameter[period_key]["pos"]["currentStatus"] = ETLDataCompleteStatus.Red.name
                        self._set_compare_etl_status(ETLDataCompleteStatus.Red)

                self._logger.info("{} - {} pos status {}".format(self._body["group_name"], period_key,
                                                                 self._etl_status.name))
                self._logger.debug(self._etl_parameter[period_key])

        if "onHand" in self._check_on:
            self._logger.info("Checking onHand")
            if not row:
                self._logger.warning("None result with pos_on_hand sql {}.".format(sql))
                self._etl_parameter[period_key]["onHand"]["currentStatus"] = '{} - No data returned'.format(
                    ETLDataCompleteStatus.Red.name)
                self._etl_parameter[period_key]["onHand"]["currentValue"] = -1
                self._set_compare_etl_status(ETLDataCompleteStatus.Red)
            else:
                self._etl_parameter[period_key]["onHand"]["currentValue"] = row.ON_HAND_RATE
                on_hand_green = self._etl_parameter[period_key]["onHand"]["green"][0]
                if float(on_hand_green[0]) < row.ON_HAND_RATE <= float(on_hand_green[1]):
                    self._etl_parameter[period_key]["onHand"]["currentStatus"] = ETLDataCompleteStatus.Green.name
                    self._etl_parameter[period_key]["onHand"]["completeTime"] = datetime.datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S")
                    self._set_compare_etl_status(ETLDataCompleteStatus.Green)
                else:
                    on_hand_yellow = self._etl_parameter[period_key]["onHand"]["yellow"]
                    if (float(on_hand_yellow[0][0]) < row.ON_HAND_RATE <= float(on_hand_yellow[0][1]) or
                            float(on_hand_yellow[1][0]) < row.ON_HAND_RATE <= float(on_hand_yellow[1][1])):
                        self._etl_parameter[period_key]["onHand"]["currentStatus"] = ETLDataCompleteStatus.Yellow.name
                        self._set_compare_etl_status(ETLDataCompleteStatus.Yellow)
                    else:
                        self._etl_parameter[period_key]["onHand"]["currentStatus"] = ETLDataCompleteStatus.Red.name
                        self._set_compare_etl_status(ETLDataCompleteStatus.Red)

                self._logger.info("{} - {} onHand status {}".format(self._body["group_name"], period_key,
                                                                    self._etl_status.name))
                self._logger.debug(self._etl_parameter[period_key])

    def _get_pre_same_day(self, period_key):
        """
        Get same day of week for the max pre pre_week weeks
        :return: period keys list
        """
        max_pre_week = max(
            [self._body["parameter"]["pos"]["preWeek"], self._body["parameter"]["onHand"]["preWeek"],
             self._body["parameter"]["itemCount"]["preWeek"], self._body["parameter"]["storeCount"]["preWeek"]])
        lst_period_key = []
        sql = ("SELECT /*+ LABEL(GX_IRIS_DATA_COMPLETE_ETL)*/ TO_CHAR(T.TS, 'YYYYMMDD') PERIOD_KEY "
               "FROM (SELECT TS FROM ( "
               "          SELECT TO_TIMESTAMP('{period_key}', 'YYYYMMDD') - {pre_week} * 7 AS TM "
               "          UNION ALL "
               "          SELECT TO_TIMESTAMP('{period_key}', 'YYYYMMDD') - 7 AS TM "
               "          ) AS SE "
               "      TIMESERIES TS AS '1 DAY' OVER (ORDER BY TM)) T "
               "WHERE EXTRACT('DOW' FROM TS::DATE) = EXTRACT('DOW' FROM TO_DATE('{period_key}', 'YYYYMMDD')) "
               "ORDER BY PERIOD_KEY DESC".format(period_key=period_key, pre_week=max_pre_week))
        self._logger.info("The SQL for getting same day of week for the max pre pre_week weeks is :%s" % sql)

        for row in self._dw_source.query(sql):
            lst_period_key.append("{}".format(row.PERIOD_KEY))

        self._logger.info('Same day of week: %s' % lst_period_key)
        return lst_period_key

    def _set_compare_etl_status(self, status):
        """
        Update etl status when input value of status greater than current
        :return:
        """
        if self._etl_status.value < status.value:
            self._etl_status = status

    def _check_rate_pog(self, period_key):
        """
        Check rate of pog
        :return:
        """
        sql = ("WITH T AS ("
               "    SELECT /*+ LABEL(GX_IRIS_DATA_COMPLETE_ETL)*/ PERIOD_KEY, SUM(POG_IND) POG "
               "    FROM {schema}.ANL_STORE_SALES WHERE PERIOD_KEY >= "
               "            TO_CHAR(TO_DATE('{period_key}', 'YYYYMMDD') - {days}, 'YYYYMMDD')::INT "
               "    GROUP BY PERIOD_KEY) "
               "SELECT CASE WHEN B.POG = 0 OR B.POG IS NULL OR A.POG IS NULL THEN 0 ELSE A.POG / B.POG END AS POG_RATE "
               "FROM (SELECT * FROM T WHERE PERIOD_KEY = {period_key}) A, "
               "     (SELECT AVG(T.POG) AS POG FROM T WHERE T.PERIOD_KEY != {period_key}) B "
               "".format(schema=self._schema, period_key=period_key,
                         days=self._etl_parameter[period_key]["maxPogExtrapolateDays"]))
        self._logger.info("The SQL for checking rate of pog is: %s" % sql)

        row = self._dw_source.query(sql).fetchone()
        if not row:
            self._logger.warning("None result with pog sql {}.".format(sql))
            self._etl_parameter[period_key]["pog"]["currentStatus"] = '{} - No data returned'.format(
                ETLDataCompleteStatus.Red.name)
            self._etl_parameter[period_key]["pog"]["currentValue"] = -1
            self._set_compare_etl_status(ETLDataCompleteStatus.Red)
        else:
            self._logger.info("Checking pog")
            self._etl_parameter[period_key]["pog"]["currentValue"] = row.POG_RATE
            pog_green = self._etl_parameter[period_key]["pog"]["green"][0]
            if float(pog_green[0]) < row.POG_RATE <= float(pog_green[1]):
                self._etl_parameter[period_key]["pog"]["currentStatus"] = ETLDataCompleteStatus.Green.name
                self._etl_parameter[period_key]["pog"]["completeTime"] = datetime.datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S")
                self._set_compare_etl_status(ETLDataCompleteStatus.Green)
            else:
                pog_yellow = self._etl_parameter[period_key]["pog"]["yellow"]
                if (float(pog_yellow[0][0]) < row.POG_RATE <= float(pog_yellow[0][1]) or
                        float(pog_yellow[1][0]) < row.POG_RATE <= float(pog_yellow[1][1])):
                    self._etl_parameter[period_key]["pog"]["currentStatus"] = ETLDataCompleteStatus.Yellow.name
                    self._set_compare_etl_status(ETLDataCompleteStatus.Yellow)
                else:
                    self._etl_parameter[period_key]["pog"]["currentStatus"] = ETLDataCompleteStatus.Red.name
                    self._set_compare_etl_status(ETLDataCompleteStatus.Red)

            self._logger.info("{} - {} pog status {}".format(self._body["group_name"], period_key,
                                                             self._etl_status.name))
            self._logger.debug(self._etl_parameter[period_key])

    def _check_rate_receipt(self, period_key):
        """
        Checking rate of receipt
        :return:
        """
        sql = ("SELECT /*+ LABEL(GX_IRIS_DATA_COMPLETE_ETL)*/ "
               "    COUNT(CASE WHEN PERIOD_KEY > TO_CHAR(TO_DATE('{period_key}', 'YYYYMMDD') - {interval_green}, "
               "    'YYYYMMDD')::INT THEN \"STORE RECEIPTS\" ELSE NULL END) AS RECEIPT_GREEN, "
               "    COUNT(CASE WHEN PERIOD_KEY > TO_CHAR(TO_DATE('{period_key}', 'YYYYMMDD') - {interval_yellow}, "
               "    'YYYYMMDD')::INT THEN \"STORE RECEIPTS\" ELSE NULL END) AS RECEIPT_YELLOW "
               "FROM {schema}.ANL_STORE_SALES "
               "WHERE \"STORE RECEIPTS\" > 0 AND PERIOD_KEY > "
               "        TO_CHAR(TO_DATE('{period_key}', 'YYYYMMDD') - {interval_yellow}, 'YYYYMMDD')::INT "
               "".format(schema=self._schema, period_key=period_key,
                         interval_green=self._etl_parameter[period_key]["receipt"]["green"],
                         interval_yellow=self._etl_parameter[period_key]["receipt"]["yellow"]))
        self._logger.info("The SQL for Checking rate of receipt is: %s" % sql)

        row = self._dw_source.query(sql).fetchone()
        self._logger.info("Checking receipt")
        if not row:
            self._logger.warning("None result with receipt sql {}.".format(sql))
            self._etl_parameter[period_key]["receipt"]["currentStatus"] = '{} - No data returned'.format(
                ETLDataCompleteStatus.Red.name)
            self._etl_parameter[period_key]["receipt"]["currentValue"] = -1
            self._set_compare_etl_status(ETLDataCompleteStatus.Red)
        else:
            if row.RECEIPT_GREEN > 0:
                self._etl_parameter[period_key]["receipt"]["currentValue"] = row.RECEIPT_GREEN
                self._etl_parameter[period_key]["receipt"]["currentStatus"] = ETLDataCompleteStatus.Green.name
                self._etl_parameter[period_key]["receipt"]["completeTime"] = datetime.datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S")
                self._set_compare_etl_status(ETLDataCompleteStatus.Green)
            elif row.RECEIPT_YELLOW > 0:
                self._etl_parameter[period_key]["receipt"]["currentValue"] = row.RECEIPT_YELLOW
                self._etl_parameter[period_key]["receipt"]["currentStatus"] = ETLDataCompleteStatus.Yellow.name
                self._set_compare_etl_status(ETLDataCompleteStatus.Yellow)
            else:
                self._etl_parameter[period_key]["receipt"]["currentValue"] = 0
                self._etl_parameter[period_key]["receipt"]["currentStatus"] = ETLDataCompleteStatus.Red.name
                self._set_compare_etl_status(ETLDataCompleteStatus.Red)

        self._logger.info("{} - {} receipt status {}".format(self._body["group_name"], period_key,
                                                             self._etl_status.name))
        self._logger.debug(self._etl_parameter[period_key])

    def _check_rate_feedback(self, period_key):
        """
        Checking rate of feedback
        :return:
        """
        sql = ("SELECT /*+ LABEL(GX_IRIS_DATA_COMPLETE_ETL)*/ "
               "    COUNT(CASE WHEN A.PERIOD_KEY > TO_CHAR(TO_DATE('{period_key}', 'YYYYMMDD') - {interval_green}, "
               "    'YYYYMMDD')::INT THEN 1 ELSE NULL END) AS FEEDBACK_GREEN, "
               "    COUNT(CASE WHEN A.PERIOD_KEY > TO_CHAR(TO_DATE('{period_key}', 'YYYYMMDD') - {interval_yellow}, "
               "    'YYYYMMDD')::INT THEN 1 ELSE NULL END) AS FEEDBACK_YELLOW "
               "FROM {retailer_schema}.FACT_PROCESSED_ALERT A "
               "JOIN {retailer_schema}.FACT_FEEDBACK F ON F.ALERT_ID = A.ALERT_ID "
               "WHERE A.ISSUANCEID = 0 "
               "AND   A.PERIOD_KEY > TO_CHAR(TO_DATE('{period_key}', 'YYYYMMDD') - {interval_yellow}, 'YYYYMMDD')::INT "
               "".format(period_key=period_key, retailer_schema=self._body["retailer_schema"],
                         interval_green=self._etl_parameter[period_key]["feedback"]["green"],
                         interval_yellow=self._etl_parameter[period_key]["feedback"]["yellow"]))
        self._logger.info("The SQL for Checking rate of feedback is: %s" % sql)

        _dw = DWOperation(meta=self.meta)
        row = _dw.query(sql).fetchone()
        _dw.close_connection()
        self._logger.info("Checking feedback")
        if not row:
            self._logger.warning("None result with feedback sql {}.".format(sql))
            self._etl_parameter[period_key]["feedback"]["currentStatus"] = '{} - No data returned'.format(
                ETLDataCompleteStatus.Red.name)
            self._etl_parameter[period_key]["feedback"]["currentValue"] = -1
            self._set_compare_etl_status(ETLDataCompleteStatus.Red)
        else:
            if row.FEEDBACK_GREEN > 0:
                self._etl_parameter[period_key]["feedback"]["currentValue"] = row.FEEDBACK_GREEN
                self._etl_parameter[period_key]["feedback"]["currentStatus"] = ETLDataCompleteStatus.Green.name
                self._etl_parameter[period_key]["feedback"]["completeTime"] = datetime.datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S")
                self._set_compare_etl_status(ETLDataCompleteStatus.Green)
            elif row.FEEDBACK_YELLOW > 0:
                self._etl_parameter[period_key]["feedback"]["currentValue"] = row.FEEDBACK_YELLOW
                self._etl_parameter[period_key]["feedback"]["currentStatus"] = ETLDataCompleteStatus.Yellow.name
                self._set_compare_etl_status(ETLDataCompleteStatus.Yellow)
            else:
                self._etl_parameter[period_key]["feedback"]["currentValue"] = 0
                self._etl_parameter[period_key]["feedback"]["currentStatus"] = ETLDataCompleteStatus.Red.name
                self._set_compare_etl_status(ETLDataCompleteStatus.Red)

        self._logger.info("{} - {} feedback status {}".format(self._body["group_name"], period_key,
                                                              self._etl_status.name))
        self._logger.debug(self._etl_parameter[period_key])

    def _check_data_rate(self, period_key):
        """
        Check ETL completeness status
        If [Last Available Date Data] is enabled, check the last $n days
        ($n is a parameter, as Yuting said, by default we could set it as 3)
        :return: True for done, else False
        """
        self._body["message"] = "ETL data complete status is {}".format(self._etl_status.name)
        self._logger.info("ETL data complete status is {}".format(self._etl_status.name))

        if self._etl_status == ETLDataCompleteStatus.Green:
            result = True
        elif self._body["meet_cut_off_time"] and self._etl_status == ETLDataCompleteStatus.Yellow:
            result = True
        else:
            result = False

        if self._etl_status == ETLDataCompleteStatus.Init:
            self._etl_parameter[period_key]["currentStatus"] = ETLDataCompleteStatus.Red.name
        else:
            self._etl_parameter[period_key]["currentStatus"] = self._etl_status.name

        self._body["message"] = "{} ETL data complete status for {} is {}".format(
            self._body["group_name"], period_key, self._etl_parameter[period_key]["currentStatus"])
        self._logger.debug(self._body)

        return result

    def request_core(self):
        """
        Sent POST request to create core processing job.
        :return:
        """

        if not self.check_osa_core_job_running():  # if no job is running, then create a new job for given groupName.
            request_json = {"groupName": self._body["group_name"],
                            "paras": self._request_core_paras,
                            "scheduleId": self._body["schedule_id"]
                            }

            _new_job_url = '{}/job/newjobs'.format(self.meta["api_job_str"])
            self._logger.info("Create new job with params: %s" % str(request_json))
            _resp = requests.post(url=_new_job_url, json=request_json, headers=self.context["header"])
            if _resp.status_code != requests.codes.ok:
                self._logger.warning("The response result is: %s" % _resp.text)
                self._logger.error("Calling API: %s creating new job failed with body: %s."
                                   % (_new_job_url, str(request_json)))

            response = _resp.json()
            self._logger.debug(response)

            self._body["status"] = response["status"]
            if response["status"] == StepStatus.SUCCESS.name:
                self._body["core_job_id"] = response["data"]["id"]
                self._body["message"] = "Request has send to OSA core"
                self._logger.info("Request has send to OSA core, core_job_id=%s" % response["data"]["id"])
            else:
                self._body["message"] = response
                self._logger.warning('Invoked OSA core failed, response: %s' % response)

    def check_osa_core_job_running(self):
        """
        Checking if OSA core job is running...
        :return: True or False
        """
        result = False

        if self._body["core_job_id"]:
            # Getting job status info
            response = requests.get(url="{}/job/jobs/{}".format(self.meta["api_job_str"], self._body["core_job_id"]),
                                    headers=self.context["header"]).json()
        else:
            response = {"data": {"status": "None"}}

        if response["data"]:
            # if job is in one of below 4 status, then it will be treated as in RUNNING status
            if (response["data"]["status"] in
                    [JobStatus.QUEUE.name, JobStatus.PENDING.name, JobStatus.DISPATCHED.name, JobStatus.RUNNING.name]):
                result = True
                self._body["message"] = "OSA core job {} is running, skip".format(self._body["core_job_id"])
                self._logger.warning("OSA core job {} is running, skip".format(self._body["core_job_id"]))
        else:
            self._body["message"] = "Not found job {} status from jobs".format(self._body["core_job_id"])
            self._logger.warning("Not found job {} status from jobs".format(self._body["core_job_id"]))

        return result

    def _update_alert_cycle(self, period_key):
        """
        Update ETL data completeness parameter and status for one cycle, period, vendor and retailer level
        :return: ETL data complete row or None
        """

        job_executed = True if self._body["status"] == StepStatus.SUCCESS.name else False
        request_json = {
            "payload": [
                {
                    "id": {
                            "vendor_key": self._body["vendor_key"],
                            "retailer_key": self._body["retailer_key"],
                            "sla_time": self._body["sla_time_est"]
                    },
                    "attributes": {
                            "cycle_key": self._body["cycle_key"],
                            "period_key": period_key,
                            "job_executed": job_executed,
                            "job_id": self._body["core_job_id"]
                    }
                }
            ]
        }

        if self._body["data_complete_action"] == "RUN":
            request_json["payload"][0]["attributes"]["data_complete_status"] = self._etl_parameter[period_key][
                "currentStatus"]
            self._etl_parameter["curr_transfer_ts"] = self._body.get("curr_transfer_ts")  # adding curr_transfer_ts into data_complete_log
            self._etl_parameter["prev_transfer_ts"] = self._body.get("prev_transfer_ts")  # adding prev_transfer_ts into data_complete_log
            self._etl_parameter["sla_time_est"] = self._body.get("sla_time_est")  # adding sla_time_est into data_complete_log
            self._etl_parameter["min_period_key"] = self._body.get("min_period_key")  # adding min_period_key into data_complete_log
            request_json["payload"][0]["attributes"]["data_complete_log"] = json.dumps(self._etl_parameter)

        self._logger.info("Calling API to update alert_cycle_status with params: %s" % str(request_json))
        response = requests.put(url='{}/availablecycle/status'.format(self.meta["api_alerts_str"]),
                                json=request_json, headers=self.context["header"], verify=False).json()
        self._logger.debug(response)

        if response["status"].upper() == StepStatus.SUCCESS.name:
            self._body["message"] = "ETL data completeness update alert cycle done"
            self._logger.info("ETL data completeness update alert cycle done")
        else:
            self._body["message"] = response["error"]
            self._logger.error('Update availablecycle/status failed, error response: %s'%response)


if __name__ == "__main__":
    import configparser
    from log.logger import Logger

    with open("{}/../../../config/config.properties".format(sys.argv[0])) as fp:
        cp = configparser.ConfigParser()
        cp.read_file(fp)
        meta = dict(cp.items("DEFAULT"))

    body = {
        "jobId": 205789, "stepId": 1, "body": "Data complete ETL done", "meta": meta, "log_level": 10,
        "header": {"Content-Type": "application/json", "hour_offset": "-6", "module_name": "dc_etl_service"},
        # "header": {"Content-Type": "application/json", "hour_offset": "-6", "cycle_key": "69", "module_name": "dc_etl_service"},
        "parameter_json": {
            "availableCycles": {
                "status": "success",
                "data": {"payload":[{"cycle_key": 2, "time_zone": "US/Eastern", "period_key": 20180911, "period_key_est": 20180910,
                                     "sla_time": "2018-09-11 10:00:00", "sla_time_est": "2018-09-10 10:00:00", "afm_action": "RUN",
                                     "vendor_retailer_pair": [
                                         {"vendor_key": 300, "retailer_key": 5240, "check_extra_days": None, "data_complete_action": "RUN", "previous_data_complete_status": "RED", "job_id": None, 'features': ['rsa', 'rc'], 'rc_id': 12, 'data_complete_log': '{ "transfer_ts": ""}'},
                                         # {"vendor_key":300,"retailer_key":5240,"check_extra_days":None,"data_complete_action":"SKIP","previous_data_complete_status":"RED","job_id":123456},
                                         {"vendor_key": 664, "retailer_key": 5240, "check_extra_days": [20180906, 20180909], "data_complete_action": "RUN", "previous_data_complete_status": "RED", "job_id":None, 'features': ['rsa'], 'rc_id': None, 'data_complete_log': '{ "transfer_ts": "2019-06-01 02:00:34"}'}
                                     ]}],
                         "error": None}
                },
            "schedule": {
                "1:2:300:5240": [{"id": 3, "parametersContext": {"JobSteps":[{"StepName": "OSADataCompleteness", "StepID": "2", "DefaultSetting": {"paraDataCompleteETL": "eyJjaGVja09uIjpbInBvcyIsIm9uSGFuZCIsInBvZyJdLCJtYXhQb2dFeHRyYXBvbGF0ZURheXMiOjE0LCJwb3MiOnsiZ3JlZW4iOltbMC44LDEuMl1dLCJ5ZWxsb3ciOltbMC4zLDAuOF0sWzEuMiwxLjddXSwicHJlV2VlayI6MTN9LCJpdGVtQ291bnQiOnsieWVsbG93IjpbWzAuOCwxLjJdXSwicHJlV2VlayI6MTN9LCJzdG9yZUNvdW50Ijp7InllbGxvdyI6W1swLjgsMS4yXV0sInByZVdlZWsiOjEzfSwib25IYW5kIjp7ImdyZWVuIjpbWzAuOCwxLjJdXSwieWVsbG93IjpbWzAuMywwLjhdLFsxLjIsMS43XV0sInByZVdlZWsiOjR9LCJwb2ciOnsiZ3JlZW4iOltbMC44LDEuMl1dLCJ5ZWxsb3ciOltbMC4zLDAuOF0sWzEuMiwxLjddXX0sInJlY2VpcHQiOnsiZ3JlZW4iOjUsInllbGxvdyI6OX0sImZlZWRiYWNrIjp7ImdyZWVuIjo1LCJ5ZWxsb3ciOjl9fQ=="}}]}}],
                "1:2:664:5240": [{"id": 3, "parametersContext": {"JobSteps":[{"StepName": "OSADataCompleteness", "StepID": "2", "DefaultSetting": {"paraDataCompleteETL": "eyJjaGVja09uIjpbInBvcyIsIm9uSGFuZCIsInBvZyJdLCJtYXhQb2dFeHRyYXBvbGF0ZURheXMiOjE0LCJwb3MiOnsiZ3JlZW4iOltbMC44LDEuMl1dLCJ5ZWxsb3ciOltbMC4zLDAuOF0sWzEuMiwxLjddXSwicHJlV2VlayI6MTN9LCJpdGVtQ291bnQiOnsieWVsbG93IjpbWzAuOCwxLjJdXSwicHJlV2VlayI6MTN9LCJzdG9yZUNvdW50Ijp7InllbGxvdyI6W1swLjgsMS4yXV0sInByZVdlZWsiOjEzfSwib25IYW5kIjp7ImdyZWVuIjpbWzAuOCwxLjJdXSwieWVsbG93IjpbWzAuMywwLjhdLFsxLjIsMS43XV0sInByZVdlZWsiOjR9LCJwb2ciOnsiZ3JlZW4iOltbMC44LDEuMl1dLCJ5ZWxsb3ciOltbMC4zLDAuOF0sWzEuMiwxLjddXX0sInJlY2VpcHQiOnsiZ3JlZW4iOjUsInllbGxvdyI6OX0sImZlZWRiYWNrIjp7ImdyZWVuIjo1LCJ5ZWxsb3ciOjl9fQ=="}}]}}]
            }
        }
    }
    body.pop("parameter_json")

    log_file = "{}_{}.log".format(sys.argv[0], body["body"])
    logger = Logger(log_level="DEBUG", target="console|file", module_name="dc_etl_service", log_file=log_file)
    logger.set_keys(log_id="{}_{}".format(body["jobId"], body["stepId"]))
    # dc = DataCompleteETL(meta={**body["meta"], **{"logger": logger}})
    # dc.on_action(body)
    # d = DataCompleteETL({**body, **{"logger": logger}})
    d = DataCompleteETL(meta=meta, request_body=body, logger=logger)
    d.process()
