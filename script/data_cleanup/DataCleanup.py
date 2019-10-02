#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import datetime
import json
import sys
import requests
from common.step_status import StepStatus
from db.db_operation import DWOperation
from agent.master import MasterHandler
from agent.app import App

class DataCleanup:
    """
    Cleanup outdated Data
    For table: it will drop the table end with job id which less then job id from api /common/job/cleanup
    Gor data, it will drop partition set in config json
    """

    def __init__(self, context):
        self.context = context.copy()
        self._logger = context["logger"]
        self.body = {"job_id": context["jobId"], "step_id": context["stepId"], "status": StepStatus.RUNNING.name,
                     "message": "Data Cleanup start"}
        self._logger.info(self.body)

    def get_url_response(self, url, method="POST", **kwargs):
        """Get response from url
        :return: response
        """
        self._logger.info(url)
        if method.upper() not in ["GET", "POST", "PUT", "DELETE"]:
            method = "GET"
        response = requests.request(method=method, url=url, verify=False, **kwargs)
        self._logger.info(response.json())
        return response

    def _get_boundary_job_id(self):
        """Get boundary job id
        :return: boundary_job_id
        """
        boundary_job_id = None
        response = self.get_url_response(url="{}/job/cleanup".format(self.context["meta"]["api_job_str"]),
                                         method="DELETE", headers=self.context["header"]).json()
        if response["status"].upper() == StepStatus.SUCCESS.name:
            if response["data"]:
                boundary_job_id = response["data"]
                self.body["message"] = "Boundary job id is {}".format(boundary_job_id)
                self._logger.info(self.body)
            else:
                self.body["message"] = "None boundary job id".format(boundary_job_id)
                self._logger.warning(self.body)
        else:
            self.body["message"] = response["error"]
            self._logger.error(response)
        return boundary_job_id

    def _get_outdated_data(self, dct_job_id):
        """Get outdated data
        :return: dictionary of outdated data
        """
        dct = {}
        boundary_job_id = self._get_boundary_job_id()
        if boundary_job_id:
            for k, v in dct_job_id.items():
                if int(k) < int(boundary_job_id):
                    dct[k] = v
        return dct

    def _cleanup_table(self, config):
        """Cleanup dw table
        :return:
        """
        dct_table = {}
        sql = ("SELECT /*+ LABEL(GX_IRIS_DATA_CLEANUP)*/ TABLE_SCHEMA || '.' || TABLE_NAME AS SCHEMA_TABLE"
               "    , REGEXP_SUBSTR(TABLE_NAME, '(.+)_(\d+)$', 1, 1, '', 2) AS JOB_ID FROM TABLES "
               "WHERE TABLE_SCHEMA IN ( "
               "    SELECT SCHEMA_NAME FROM SCHEMATA WHERE SCHEMA_OWNER = '{}' AND SCHEMA_NAME NOT IN ('{}'))"
               "AND (REGEXP_ILIKE(TABLE_NAME,'^{}$'))"
               "".format(self.context["meta"]["db_conn_vertica_username"], "','".join(config["excludeSchema"]),
                         "$') OR REGEXP_ILIKE(TABLE_NAME,'^".join(config["namePattern"])))
        self._logger.info(sql)
        for row in self._dw.query(sql):
            dct_table[row.JOB_ID] = row.SCHEMA_TABLE
        if dct_table:
            dct_outdated_data = self._get_outdated_data(dct_table)
            if dct_outdated_data:
                sql = "DROP TABLE IF EXISTS {} CASCADE".format(",".join(dct_outdated_data.values()))
                self._logger.info(sql)
                self._dw.execute(sql)
            else:
                self.body["message"] = "None table cleanup"
                self._logger.warning(self.body)
        else:
            self.body["message"] = "Not found table to cleanup"
            self._logger.warning(self.body)

    def _cleanup_data(self, config):
        """Cleanup dw table partition, SEQ_NUM logic relate to OSA-471
        :return:
        """
        if "SEQ_NUM" in config["partitionTable"]:
            sql = ("SELECT /*+ LABEL(GX_IRIS_DATA_CLEANUP)*/ DISTINCT INCIDENT_ID_START//1000000000%36500 AS SEQ_NUM "
                   "FROM {}.DIM_INCIDENT_ID_START "
                   "WHERE PERIOD_KEY = {}".format(
                    self.context["meta"]["db_conn_vertica_common_schema"],
                    (datetime.datetime.now() - datetime.timedelta(days=config["reserveDays"])).strftime("%Y%m%d")))
            self._logger.info(sql)
            seq_num = self._dw.query_scalar(sql)
            if seq_num:
                sql = ("SELECT /*+ LABEL(GX_IRIS_DATA_CLEANUP)*/ SCHEMA_TABLE, PARTITION_KEY FROM ( "
                       "    SELECT DISTINCT PA.PARTITION_KEY, PA.TABLE_SCHEMA||'.'||PR.ANCHOR_TABLE_NAME SCHEMA_TABLE "
                       "    FROM PARTITIONS PA "
                       "    JOIN PROJECTIONS PR ON PR.PROJECTION_ID = PA.PROJECTION_ID "
                       "    WHERE PA.TABLE_SCHEMA IN ( "
                       "        SELECT SCHEMA_NAME FROM SCHEMATA "
                       "        WHERE SCHEMA_OWNER = '{}' AND SCHEMA_NAME NOT IN ('{}')) "
                       "    AND PR.ANCHOR_TABLE_NAME IN ('{}')) T "
                       "WHERE T.PARTITION_KEY < {} "
                       "".format(self.context["meta"]["db_conn_vertica_username"], "','".join(config["excludeSchema"]),
                                 "','".join(config["partitionTable"]['SEQ_NUM']), seq_num))
                self._logger.info(sql)
                for row in self._dw.query(sql):
                    sql = "SELECT /*+ LABEL(GX_IRIS_DATA_CLEANUP)*/ DROP_PARTITION('{}', {})" \
                          "".format(row.SCHEMA_TABLE, row.PARTITION_KEY)
                    self._logger.info(sql)
                    self._dw.execute(sql)
            else:
                self.body["message"] = self._logger.warning("Not found SEQ_NUM to cleanup")
                self._logger.warning(self.body)
        else:
            self.body["message"] = "None data cleanup"
            self._logger.warning(self.body)

    def _process_data_cleanup(self):
        """Process Data Cleanup
        :return:
        """
        try:
            self._dw = DWOperation(meta=self.context["meta"])
            lst_warning = [" none warning"]
            for cfg in eval(self.context["config_json"]):
                try:
                    if cfg["type"].upper() == "TABLE":
                        self._cleanup_table(cfg)
                    elif cfg["type"].upper() == "DATA":
                        self._cleanup_data(cfg)
                    self.body["message"] = "{} cleanup done".format(cfg["type"])
                    self._logger.info(self.body)
                except Exception as msg:
                    self.body["status"] = StepStatus.ERROR.name
                    self.body["message"] = ("Data Cleanup error with config {}  --||##  {}".format(cfg, msg))
                    self._logger.warning(self.body)
                    lst_warning.append(cfg)
                    continue
            self.body["status"] = StepStatus.SUCCESS.name
            self.body["message"] = ("Data Cleanup done with config {}, {}".format(cfg, "; ".join(lst_warning)))
            self._logger.info(self.body)
        except Exception as msg:
            self.body["status"] = StepStatus.ERROR.name
            self._logger.error(msg)
        finally:
            if hasattr(self, "_dw"):
                self._dw.close_connection()
            self.body["message"] = "Data Cleanup end"
            self._logger.info(self.body)

    def process(self):
        self._process_data_cleanup()

        
class DataCleanupNanny(DataCleanup):

    def __init__(self, meta, request_body, logger=None):
        logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="data_cleanup_service")
        logger.set_keys(log_id="{}_{}".format(request_body["jobId"], request_body["stepId"]))
        logger.debug(request_body)
        request_body["header"] = {"Content-Type": "application/json", "module_name": logger.format_dict["module_name"]}
        request_body["config_json"] = request_body["configJson"]
        request_body["log_level"] = request_body.get("log_level", 20)
        logger.set_level(request_body["log_level"])

        DataCleanup.__init__(self, {**request_body, **{"meta": meta}, **{"logger": logger}})
        

class DataCleanupHandler(MasterHandler):

    def set_service_properties(self):
        self.service_name = 'dataCleanupNanny'
        
    
class DataCleanupApp(App):
    '''
    This class is just for testing, osa_bundle triggers it somewhere else
    '''
    def __init__(self, meta):
        App.__init__(self, meta=meta, service_bundle_name='data_cleanup')
    
    
        
if __name__ == '__main__':
    #import configparser
    #from log.logger import Logger
    #
    #with open("{}/../../../config/config.properties".format(sys.argv[0])) as fp:
    #    cp = configparser.ConfigParser()
    #    cp.read_file(fp)
    #    meta = dict(cp.items("DEFAULT"))
    #body = {"jobId": 23456789, "stepId": 1, "body": "Data Cleanup done", "meta": meta,
    #        "config_json": "[{'type': 'TABLE', 'excludeSchema': ['QA_AHOLD','QA_LOBCA'], 'namePattern': ['AFM_RULES_FEEDBACK_STAGE_\\d+', 'FACT_PROCESSED_ALERT_SWAP_\\d+_\\d+']},{'type': 'DATA', 'reserveDays': 90, 'excludeSchema': ['QA_AHOLD','QA_LOBCA'], 'partitionTable': {'SEQ_NUM': ['FACT_RAW_ALERT', 'FACT_OSM_STORE'], 'PERIOD_KEY': []}}]"
    #        }
    #log_file = "{}_{}.log".format(sys.argv[0], body['jobId'])
    #body["logger"] = Logger(log_level="INFO", target="console|file", module_name="data_cleanup_service",
    #                        log_file=log_file)
    ## data_cleanup = DataCleanupWrapper(meta=body["meta"])
    ## data_cleanup.on_action(body)
    #data_cleanup = DataCleanup(body)
    #data_cleanup.process()
    '''REQUEST BODY
    {
      "jobId": 23456789,
      "stepId": 1,
      "batchId": 0,
      "retry": 0, 
      "status": 3, 
      "message": "running", 
      "groupName": "11",
      "body": "Data Cleanup done",
      "configJson": "[{'type': 'TABLE', 'excludeSchema': ['QA_AHOLD','QA_LOBCA'], 'namePattern': ['AFM_RULES_FEEDBACK_STAGE_\\d+', 'FACT_PROCESSED_ALERT_SWAP_\\d+_\\d+']},{'type': 'DATA', 'reserveDays': 90, 'excludeSchema': ['QA_AHOLD','QA_LOBCA'], 'partitionTable': {'SEQ_NUM': ['FACT_RAW_ALERT', 'FACT_OSM_STORE'], 'PERIOD_KEY': []}}]"
    }
    '''
    import os
    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    exec(open(generic_main_file).read())
    
    app = DataCleanupApp(meta=meta)   #************* update services.json --> dataCleanupNanny.service_bundle_name to data_cleanup before running the script
    app.start_service()
