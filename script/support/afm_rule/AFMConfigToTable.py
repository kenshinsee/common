#!/usr/bin/env python
# coding=utf-8

import json, os
from log.logger import Logger
from optparse import OptionParser
from db.db_operation import MSOperation
from api.capacity_service import Capacity
from agent.master import MasterHandler
import job_schedule.ScheduleParamsToTable as scheduler
import requests


class AFMConfigToTable(object):
    """
    :input: afm_config.json under same folder. Note: this config file name is hardcoded.
    :output: below 4 tables.
    AFM_RULE_SET
    AFM_RULES
    AFM_RETAILER_RULE
    AFM_SVR_RULE
    :usage: python AFMConfigToTable.py

    :description:
    This is a temp solution for loading AFM configuration data from json format into AFM rule tables. Since the frontend UI is not yet working.
    Refer to above json string for the format template.
    When the frontend finished, this module will be also retired.
    There are only 4 tables involved here. See output tables list.
    """
    def __init__(self, meta, params, logger=None, filename="afm_config.json"):
        """
        :param meta:      common config
        :param params:    used by calling REST API
        :param filename:  only used for local testing
        """
        self.meta = meta
        self.params = params
        self.filename = filename
        self._cap = Capacity(meta=self.meta)
        self.app_conn = MSOperation(meta=self.meta)
        self._logger = logger if logger else Logger(log_level="debug", target="console",
                                                    vendor_key=-1, retailer_key=-1, sql_conn=None)
        self.scd_url = "{0}/scd/process".format(self.meta["api_osa_bundle_str"])

    def get_data(self):
        # json_data = json.loads(afm_config_data)
        with open(self.filename, 'r') as fp:
            json_data = json.load(fp=fp)
        return json_data

    def insert_data(self):
        # _json_config_data = self.get_data()  # for local testing
        _json_config_data = self.params        # getting data from params directly instead of reading from config file.
        _rule_type = _json_config_data["ruleType"].upper()
        _cycle_key = _json_config_data["cycleKey"]
        _vendor_key = _json_config_data["vendorKey"]
        _retailer_key = _json_config_data["retailerKey"]
        _owner = _json_config_data["owner"]
        _rule_set_name = None

        try:
            if _rule_type not in ("RETAILER", "SVR"):
                self._logger.warning("ruleType should be only either RETAILER or SVR! "
                                     "Please check config file: afm_config.json.")
                exit(1)

            if _rule_type == "RETAILER":
                _rule_set_name = _owner + '_' + self._cap.get_retailer_name_by_key(retailer_key=_retailer_key)
            elif _rule_type == "SVR":
                _rule_set_name = _owner + '_' + self._cap.get_retailer_name_by_key(retailer_key=_retailer_key) + '_' + self._cap.get_vendor_name_by_key(vendor_key=_vendor_key)

            rule_set_data = {"RULE_SET_NAME": _rule_set_name,
                             "ENGINE_PROVIDER_NAME": "AFM",
                             "DATA_PROVIDER_NAME": "AHOLD",
                             "OWNER": _owner,
                             "ITEM_SCOPE": _json_config_data["itemScope"],
                             "STORE_SCOPE": _json_config_data["storeScope"],
                             "TYPES_LIST": _json_config_data["typeList"],
                             "ENABLED": "T",
                             "CREATED_BY": _json_config_data["createdBy"],
                             "UPDATED_BY": _json_config_data["createdBy"]
                             }
            self._logger.info(rule_set_data)

            _rule_set_sql = """
            INSERT INTO AFM_RULE_SET
            (
             [RULE_SET_NAME], [ENGINE_PROVIDER_NAME], [DATA_PROVIDER_NAME],
             [OWNER], [ITEM_SCOPE], [STORE_SCOPE], [TYPES_LIST], [ENABLED],
             [CREATED_BY], [CREATED_DATE], [UPDATED_BY], [UPDATED_DATE]
            ) OUTPUT inserted.RULE_SET_ID
            VALUES(
             '{RULE_SET_NAME}', '{ENGINE_PROVIDER_NAME}', '{DATA_PROVIDER_NAME}',
             '{OWNER}', '{ITEM_SCOPE}', '{STORE_SCOPE}', '{TYPES_LIST}', '{ENABLED}',
             '{CREATED_BY}', GETDATE(), '{UPDATED_BY}', GETDATE()
            )
            """.format(**rule_set_data)
            self._logger.info("SQL for AFM_RULE_SET table is: %s" % _rule_set_sql)
            _rule_set_id = self.app_conn.query_scalar(_rule_set_sql)

            self._logger.info("Generated rule set id is: %s" % _rule_set_id)

            rules_data = _json_config_data["rules"]
            for rule in rules_data:
                rule_data = {
                    "RULE_ID": rule["ruleId"],
                    "RULE_SET_ID": _rule_set_id,
                    "SUB_LEVEL_METRICS": rule["subLevelMetrics"],
                    "PARAMETER1": rule["parameter1"],
                    "PARAMETER2": rule["parameter2"],
                    "PARAMETER3": rule["parameter3"],
                    "ENABLED": "T",
                    "CREATED_BY": _json_config_data["createdBy"],
                    "CREATED_DATE": "",
                    "UPDATED_BY": _json_config_data["createdBy"],
                    "UPDATED_DATE": ""
                     }
                self._logger.debug(rule_data)

                _rules_sql = """
                INSERT INTO AFM_RULES
                ( [RULE_ID], [RULE_SET_ID], [SUB_LEVEL_METRICS], [PARAMETER1], [PARAMETER2], [PARAMETER3],
                  [ENABLED], [CREATED_BY], [CREATED_DATE], [UPDATED_BY], [UPDATED_DATE]
                )
                VALUES (
                  {RULE_ID}, {RULE_SET_ID}, '{SUB_LEVEL_METRICS}', '{PARAMETER1}', '{PARAMETER2}', '{PARAMETER3}',
                  '{ENABLED}', '{CREATED_BY}', getdate(), '{UPDATED_BY}', getdate()
                )""".format(**rule_data)
                self._logger.info("SQL for AFM_RULES table is: %s" % _rules_sql)
                self.app_conn.execute(_rules_sql)

            if _rule_type == "RETAILER":
                _sql = """SELECT COUNT(*) FROM AFM_RETAILER_RULE 
                WHERE cycle_key = {cycleKey}""".format(cycleKey=_cycle_key)
                _exist = self.app_conn.query_scalar(_sql)
                if _exist != 0:
                    _update_sql = "UPDATE AFM_RETAILER_RULE SET owner='{owner}', rule_set_id = {rule_set_id} " \
                                  "WHERE cycle_key = {cycleKey}; "\
                        .format(cycleKey=_cycle_key,
                                owner=_owner,
                                rule_set_id=_rule_set_id)
                    self._logger.info("Sql for updating table AFM_RETAILER_RULE is: %s" % _update_sql)

                    # calling scd api to execute update/delete statements
                    _body = {
                        "sql": _update_sql,
                        "actioner": "ben.wu",
                        "log_detail": True,
                        "batch_size": 100,
                        "db_type": "MSSQL",
                        "table_schema": "(COMMON)"
                    }
                    # resp = requests.post(self.scd_url, data=json.dumps(_body))
                    resp = requests.post(self.scd_url, json=_body)
                    if resp.status_code != requests.codes.ok:
                        self._logger.warning("The response result is: %s" % resp.json())
                        self._logger.error("Calling API failed with body: %s. Refer to API: %s" % (_body, self.scd_url))

                else:
                    _insert_sql = """
                    INSERT INTO AFM_RETAILER_RULE(cycle_key, owner, rule_set_id)
                    VALUES({0}, '{1}', {2});""".format(_cycle_key, _owner, _rule_set_id)
                    self._logger.info("SQL for inserting table AFM_RETAILER_RULE is: %s" % _insert_sql)
                    self.app_conn.execute(_insert_sql)

            if _rule_type == "SVR":
                _sql = """
                SELECT COUNT(*) FROM AFM_SVR_RULE
                WHERE vendor_key = {vendorKey} AND retailer_key = {retailerKey}
                """.format(vendorKey=_vendor_key, retailerKey=_retailer_key)
                _exist = self.app_conn.query_scalar(_sql)
                if _exist != 0:
                    _update_sql = """
                    UPDATE AFM_SVR_RULE SET owner = '{owner}', rule_set_id = {rule_set_id} 
                    WHERE vendor_key = {vendorKey} AND retailer_key = {retailerKey}
                    AND cycle_key = {cycleKey}
                    """.format(owner=_owner,
                               rule_set_id=_rule_set_id,
                               vendorKey=_vendor_key,
                               retailerKey=_retailer_key,
                               cycleKey=_cycle_key)
                    self._logger.info("SQL for updating table AFM_SVR_RULE is: %s" % _update_sql)

                    # calling scd api to execute update/delete statements
                    _body = {
                        "sql": _update_sql,
                        "actioner": "ben.wu",
                        "log_detail": True,
                        "batch_size": 100,
                        "db_type": "MSSQL",
                        "table_schema": "(COMMON)"
                    }
                    # resp = requests.post(self.scd_url, data=json.dumps(_body))
                    resp = requests.post(self.scd_url, json=_body)
                    if resp.status_code != requests.codes.ok:
                        self._logger.warning("The response result is: %s" % resp.text)
                        self._logger.error(
                            "Calling API failed with body: %s. Refer to API: %s" % (_body, self.scd_url))

                else:
                    _insert_sql = """
                    INSERT INTO AFM_SVR_RULE(vendor_key, retailer_key, owner, rule_set_id, cycle_key)
                    VALUES({0}, {1}, '{2}', {3}, {4});
                    """.format(_vendor_key, _retailer_key, _owner, _rule_set_id, _cycle_key)
                    self._logger.info("SQL for inserting table AFM_SVR_RULE is: %s" % _insert_sql)
                    self.app_conn.execute(_insert_sql)

            # insert related schedule.
            self.gen_schedule()

            self._logger.info("Insert AFM config data completed. Please check rule_set_id: %s in related tables." % _rule_set_id)

        except Exception as e:
            self._logger.warning("WARNING: Error found. Please fix it and re-run this script.")
            self._logger.warning(e)
            raise

        finally:
            if self.app_conn:
                self.app_conn.close_connection()

    def get_job_def_id(self, job_name):
        _job_name = job_name
        _job_url = self.meta["api_schedule_str"]   # http://engv3dstr2.eng.rsicorp.local/common
        _headers = {#"tokenid": "eyJhbGciOiJIUzI1NiJ9.eyJjb29raWVWYWx1ZSI6IkFRSUM1d00yTFk0U2Zjd1ZidkJILXZOWFhEYS1HQm1ETlVpd240dWtMSzBsNEJjLipBQUpUU1FBQ01ERUFBbE5MQUJNek16azRPVEkyTXpFNU5EZzJNemMwTnpZeUFBSlRNUUFBKiIsInVzZXJJZCI6ImJlbi53dUByc2ljb3JwLmxvY2FsIiwiY29va2llTmFtZSI6InJzaVNzb05leHRHZW4iLCJzdGF0dXMiOiJzdWNjZXNzIiwiaWF0IjoxNTM0ODE1NTAxfQ.Hbv_wcsEqmUBFTy64BTf15nWC94fsFTfmt3LZMq24Ag",
                    "content-type": "application/json"}
        _job_def_url = _job_url + '/schedule/jobdefinitions'

        self._logger.info("URL to find the job definition is: %s " % _job_def_url)
        res = requests.get(url=_job_def_url, headers=_headers, verify=False)
        if res.text == "invalid token":
            self._logger.warning("WARNING: Please update the tokenid manually. "
                                 "Then rerun this script again!!!")
            exit(1)

        x = [dct["id"] for dct in res.json() if dct["jobDefName"] == _job_name]
        if not x:
            self._logger.info("There is no job id found for job: %s. You can refer to API: %s"
                              % (_job_name, _job_def_url))
            exit(1)
        # returning job definition id
        return x[0]

    def gen_schedule(self):
        self._logger.info("Inserting related schedule schedule for OSARetailerAFM.")
        _rule_type = self.params["ruleType"].upper()

        # only creating schedule for RETAILER rule.
        if _rule_type == "RETAILER":
            _job_name = "OSARetailerAFM"
            _job_schedule_id = self.get_job_def_id(_job_name)
            _cycle_key = self.params["cycleKey"]
            _group_name = "{0}:{1}".format(_job_schedule_id, _cycle_key)
            _schedule_name = "{0}:{1}".format(_group_name, _job_name)
            sch_params = dict(
                creater="afmsupport@rsicorp.local",
                groupName=_group_name,
                jobDefinitionId=_job_schedule_id,
                # parametersContext="",
                # priority=1,
                # scheduleExpression="",
                scheduleName=_schedule_name,
                scheduleType="EVENT"
            )
            loader = scheduler.ScheduleParamsToTable(self.meta, sch_params)
            loader.load_data()

        # OSMAlerting schedule will take care of SVR rule.
        if _rule_type == "SVR":
            pass


class AFMConfigToTableNanny(AFMConfigToTable):

    def __init__(self, meta, request_body, logger=None):
        logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="AFMSupportNanny")
        __debug = request_body.get("debug", 'N')
        __log_level = 'DEBUG' if str(__debug).upper() == 'Y' else 'INFO'
        logger.set_level(log_level=__log_level)
        
        AFMConfigToTable.__init__(self, meta={**meta}, params={**request_body}, logger=logger)
    
	
class AFMSupportHandler(MasterHandler):
    
    def set_service_properties(self):
        self.service_name = 'AFMSupportNanny'
        self.set_as_not_notifiable()
        
	
if __name__ == '__main__':
    # getting meta
    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + '..' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    exec(open(generic_main_file).read())  # fill meta argument

    data_load = AFMConfigToTable(meta=meta, params={})
    data_load.insert_data()
