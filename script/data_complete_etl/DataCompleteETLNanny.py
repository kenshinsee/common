#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import base64
import copy
import sys
import json
import datetime
import requests
import traceback

from log.logger import Logger
from api.config_service import Config
from db.db_operation import DWOperation, SiloOperation, MSOperation, HubOperation
from api.job_service import JobService
from api.capacity_service import Capacity
from common.job_status import JobStatus
from common.step_status import StepStatus
from common.data_complete_status import DataCompleteStatus as ETLDataCompleteStatus
from DataCompleteETL import DataCompleteETL, DataCompleteETLVR
from agent.master import MasterHandler
from agent.app import App

class DataCompleteETLNanny(DataCompleteETL):
    
    def __init__(self, meta, request_body, logger=None):
        logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="dataCompleteETLNanny")
        logger.set_keys(log_id="{}_{}".format(request_body["jobId"], request_body["stepId"]))
        logger.debug(request_body)
        request_body["header"] = {"Content-Type": "application/json", "hour_offset": "-6", "module_name": logger.format_dict["module_name"]}
        request_body["log_level"] = request_body.get("log_level", 20)
        logger.set_level(request_body["log_level"])
        request_body["parameter_json"] = request_body.get("parameter_json", {})

        DataCompleteETL.__init__(self, request_body=request_body, meta=meta, logger=logger)
        
        
class DataCompleteETLHandler(MasterHandler):
    
    def set_service_properties(self):
        self.service_name = 'dataCompleteETLNanny'
    

class DataCompleteETLVRNanny(DataCompleteETLVR):
    
    def __init__(self, meta, request_body, logger=None):
        logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="dataCompleteETLVRNanny")
        logger.set_keys(log_id="{}_{}".format(request_body["jobId"], request_body["stepId"]))
        logger.debug(request_body)
        request_body["meta"] = meta.copy()
        request_body["header"] = {"Content-Type": "application/json", "hour_offset": "-6", "module_name": logger.format_dict["module_name"]}
        request_body["log_level"] = request_body.get("log_level", 20)
        logger.set_level(request_body["log_level"])
        request_body["parameter_json"] = request_body.get("parameter_json", {})

        DataCompleteETLVR.__init__(self, {**request_body, **{"logger": logger}})
        
        
class DataCompleteETLVRHandler(MasterHandler):
    
    def set_service_properties(self):
        self.service_name = 'dataCompleteETLVRNanny'
        # self.set_as_not_notifiable()
    
        
class DataCompleteApp(App):
    '''
    This class is just for testing, osa_bundle triggers it somewhere else
    '''
    def __init__(self, meta):
        App.__init__(self, meta=meta, service_bundle_name='datacomplete')
       

if __name__=='__main__':

    '''REQUEST BODY
    {
        "jobId": 1234567,
        "stepId": 1,
        "batchId": 1,
        "retry": 0,
        "groupName": 22,
        "log_level": 20,
        "parameter_json": {"availableCycles":{"status":"success","data":{"payload":[{"cycle_key":2,"time_zone":"US/Eastern","period_key":20180911,"period_key_est":20180910,"sla_time":"2018-09-11 10:00:00","sla_time_est":"2018-09-10 10:00:00","afm_action":"RUN","vendor_retailer_pair":[{"vendor_key":300,"retailer_key":5240,"check_extra_days":null,"data_complete_action":"SKIP","previous_data_complete_status":"RED","job_id":12345},{"vendor_key":664,"retailer_key":5240,"check_extra_days":[20180906,20180909],"data_complete_action":"RUN","previous_data_complete_status":"RED","job_id":null}]}],"error":null}},"schedule":{"1:2:300:5240":[{"id":3,"parametersContext":{"JobSteps":[{"StepName":"OSADataCompleteness","StepID":"2","DefaultSetting":{"paraDataCompleteETL":"eyJjaGVja09uIjpbInBvcyIsIm9uSGFuZCIsInBvZyJdLCJtYXhQb2dFeHRyYXBvbGF0ZURheXMiOjE0LCJwb3MiOnsiZ3JlZW4iOltbMC44LDEuMl1dLCJ5ZWxsb3ciOltbMC4zLDAuOF0sWzEuMiwxLjddXSwicHJlV2VlayI6MTN9LCJpdGVtQ291bnQiOnsieWVsbG93IjpbWzAuOCwxLjJdXSwicHJlV2VlayI6MTN9LCJzdG9yZUNvdW50Ijp7InllbGxvdyI6W1swLjgsMS4yXV0sInByZVdlZWsiOjEzfSwib25IYW5kIjp7ImdyZWVuIjpbWzAuOCwxLjJdXSwieWVsbG93IjpbWzAuMywwLjhdLFsxLjIsMS43XV0sInByZVdlZWsiOjR9LCJwb2ciOnsiZ3JlZW4iOltbMC44LDEuMl1dLCJ5ZWxsb3ciOltbMC4zLDAuOF0sWzEuMiwxLjddXX0sInJlY2VpcHQiOnsiZ3JlZW4iOjUsInllbGxvdyI6OX0sImZlZWRiYWNrIjp7ImdyZWVuIjo1LCJ5ZWxsb3ciOjl9fQ=="}}]}}],"1:2:664:5240":[{"id":3,"parametersContext":{"JobSteps":[{"StepName":"OSADataCompleteness","StepID":"2","DefaultSetting":{"paraDataCompleteETL":"eyJsYXN0QXZhaWxhYmxlRGF0ZURhdGEiOnsiZW5hYmxlIjoiRmFsc2UiLCJkYXlzIjozfSwiY2hlY2tPbiI6WyJwb3MiLCJvbkhhbmQiLCJwb2ciXSwibWF4UG9nRXh0cmFwb2xhdGVEYXlzIjoxNCwicG9zIjp7ImdyZWVuIjpbWzAuOCwxLjJdXSwieWVsbG93IjpbWzAuMywwLjhdLFsxLjIsMS43XV0sInByZVdlZWsiOjEzfSwiaXRlbUNvdW50Ijp7InllbGxvdyI6W1swLjgsMS4yXV0sInByZVdlZWsiOjEzfSwic3RvcmVDb3VudCI6eyJ5ZWxsb3ciOltbMC44LDEuMl1dLCJwcmVXZWVrIjoxM30sIm9uSGFuZCI6eyJncmVlbiI6W1swLjgsMS4yXV0sInllbGxvdyI6W1swLjMsMC44XSxbMS4yLDEuN11dLCJwcmVXZWVrIjo0fSwicG9nIjp7ImdyZWVuIjpbWzAuOCwxLjJdXSwieWVsbG93IjpbWzAuMywwLjhdLFsxLjIsMS43XV19LCJyZWNlaXB0Ijp7ImdyZWVuIjo1LCJ5ZWxsb3ciOjl9LCJmZWVkYmFjayI6eyJncmVlbiI6NSwieWVsbG93Ijo5fX0="}}]}}]}}
    }
    '''
    import os
    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    exec(open(generic_main_file).read())
    
    app = DataCompleteApp(meta=meta)   #************* update services.json --> dataCompleteETLNanny.service_bundle_name to datacomplete and dataCompleteETLVRNanny.service_bundle_name to datacomplete before running the script
    app.start_service()




