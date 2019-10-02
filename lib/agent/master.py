#!/usr/bin/python
import os
import json
import copy
from tornado.web import RequestHandler
from concurrent.futures import ThreadPoolExecutor
from log.logger import Logger
from common.step_status import StepStatus
from abc import ABC, abstractmethod
from tornado.concurrent import run_on_executor
from agent.notifier import Notifier
from datetime import datetime

MAX_EXECUTOR = 100


class MasterHandler(RequestHandler, ABC):

    executor = ThreadPoolExecutor(MAX_EXECUTOR)
    
    def initialize(self, meta):
        self.meta = meta
        self.logger = Logger(log_level="info", vendor_key=-1, retailer_key=-1)
        self.service_name = None
        self.is_sync_service = False
        self.is_notifiable = True
        
    def prepare(self):
        self.set_header('Content-Type', 'application/json')
        self.logger.info("Accepted query arguments: %s" % self.request.query_arguments)
        self.query_arguments = {k:self.get_query_argument(k) for k in self.request.query_arguments}
        self.logger.info("Ajusted query arguments: %s" % self.query_arguments)
        self.request_body = {}
        if 'Content-Type' in self.request.headers and self.request.headers["Content-Type"].startswith("application/json"):
            self.request_body = json.loads(self.request.body.decode('utf-8')) # it may get list
            self.logger.info("Accepted post: %s" % self.request_body)
        
        osa_backend_base_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "..")
        service_config = os.path.join(osa_backend_base_dir, 'common', 'config', 'services.json')
        with open(service_config) as f:
            services = json.load(f)
        
        self.set_service_properties()
        if not self.service_name:
            raise ValueError('service_name is empty.')
        elif not self.service_name in services:
            raise ValueError('%s is not found.'%self.service_name)
            
        self.logger.set_keys(module_name=self.service_name)
        self.service = services[self.service_name]
        module_name = self.service['module_name']
        class_name = self.service['class_name']
        module = __import__(module_name, fromlist=[class_name])
        self.klass = getattr(module, class_name)
        
    @run_on_executor
    @Notifier
    def async_main(self, params):
        self.cls = self.klass(meta=copy.deepcopy(self.meta), request_body=copy.deepcopy(params), logger=self.logger)  # init class_name
        return eval('self.cls.%s' % self.service['class_main_func'])  # call main func and return result
    
    @Notifier
    def sync_main(self, params):
        self.cls = self.klass(meta=copy.deepcopy(self.meta), request_body=copy.deepcopy(params), logger=self.logger)
        return eval('self.cls.%s'%self.service['class_main_func'])
    
    def post(self):
        if self.is_sync_service:
            msg = self.sync_main(self.request_body)
            self.send_response(msg)
        else:
            self.async_main(self.request_body)
            msg = '%s - Running %s...'%(datetime.now(), self.service_name)
            self.send_response(msg)
    
    def send_response(self, msg):
        job_params = {}
        if self.is_notifiable:
            job_required_keys = ['jobId', 'stepId', 'batchId', 'retry', 'groupName']
            job_params = dict([(k, self.request_body[k]) for k in job_required_keys if k in self.request_body])
            job_params['status'] = StepStatus.RUNNING.value
        job_params['message'] = msg
        job_params['request_body'] = self.request_body
        self.write(json.dumps(job_params))
        self.flush()
        
    @abstractmethod
    def set_service_properties(self):
        '''
        [Mandatory] set self.service_name
        [Optional] call self.set_as_sync_service() to set self.is_sync_service = True
        [Optional] call self.set_as_not_notifiable() to set self.is_notifiable = False
        '''
        pass
    
    def set_as_sync_service(self):
        self.is_sync_service = True
        
    def set_as_not_notifiable(self):
        self.is_notifiable = False
        
        
class MessageMasterHandler(ABC):

    def __init__(self, meta, body, service_name, logger):
        self.meta = meta
        self.request_body = body
        self.logger = logger
        self.service_name = service_name
        self.is_notifiable = True
        
        osa_backend_base_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "..")
        service_config = os.path.join(osa_backend_base_dir, 'common', 'config', 'services.json')
        with open(service_config) as f:
            services = json.load(f)
            
        self.set_service_properties()
        if not self.service_name:
            raise ValueError('service_name is empty.')
        elif not self.service_name in services:
            raise ValueError('%s is not found.'%self.service_name)
        
        self.service = services[self.service_name]
        module_name = self.service['module_name']
        class_name = self.service['class_name']
        module = __import__(module_name, fromlist=[class_name])
        self.klass = getattr(module, class_name)
        
    def set_service_properties(self):
        '''
        [Optional] call self.set_as_not_notifiable() to set self.is_notifiable = False
        '''
        pass
        
    @Notifier
    def execute(self, params):
        self.cls = self.klass(meta=self.meta.copy(), request_body=copy.deepcopy(params), logger=self.logger)
        return eval('self.cls.%s'%self.service['class_main_func'])
        
    def main(self):
        msg = self.execute(self.request_body)
        self.send_response(msg)
        
    def send_response(self, msg):
        if self.is_notifiable:
            job_params = {}
            job_required_keys = ['jobId', 'stepId', 'batchId', 'retry', 'groupName']
            job_params = dict([(k, self.request_body[k]) for k in job_required_keys if k in self.request_body])
            job_params['status'] = StepStatus.RUNNING.value
            job_params['message'] = msg
            job_params['request_body'] = self.request_body
            self.logger.info(job_params)
        
    def set_as_not_notifiable(self):
        self.is_notifiable = False
