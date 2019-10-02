
import threading
import traceback
import socket
import json
from log.logger import Logger
from mq.publisher import BasePublisher
from mq.consumer import FanoutConsumer
from agent.job_info import JobInfo

LOGGER = Logger(log_level="info", vendor_key=-1, retailer_key=-1)


class AgentConsumer(FanoutConsumer):

    class NestedPublisher(BasePublisher):
        
        def __init__(self, service_name, meta={}):
            super().__init__(meta=meta)
            self.service_name = service_name
        
        def on_action(self, body):
            self._app_id = self.service_name
            self._body = body
    
    def __init__(self, service_list, meta, logger):
        self.service_list = service_list
        self.meta = meta
        self.original_meta = self.meta.copy()
        self.meta['mq_exchange_name'] = self.meta['mq_agent_exchange_name']
        self.host_name = socket.gethostname()
        self.host_ip = socket.gethostbyname(self.host_name)
        super().__init__(meta=meta, logger=logger)
        self.logger = logger
        self.job_info = JobInfo()
        
    def on_action(self, body):
        self.logger.info('Communicator received message: %s'%body)
        body = json.loads(body)
        self.logger.info('Current running jobs of (%s) on %s: %s'%(self.service_list, self.host_name, self.job_info.get_job_info()))
        for service_name in self.service_list:
            self.logger.info('Seeking for job_id=%s service_name=%s'%(body['jobId'], service_name))    
            status = self.job_info.get_job_status(body['jobId'], service_name)
            if status:
                body['status'] = status
                self.logger.info('Found job_id=%s service_name=%s'%(body['jobId'], service_name))
                self.logger.info('Send back to agent: %s'%body)
                np = self.NestedPublisher(meta=self.original_meta.copy(), service_name=service_name)
                np.on_action(json.dumps(body))
                np.run()
                np.stop()
                break
                
                
class Communicator(object):

    class NestedThread(threading.Thread):
        
        def __init__(self, service_list, meta, logger):
            threading.Thread.__init__(self)
            self.service_list = service_list
            self.meta = meta
            self.logger = logger
            self.consumer = AgentConsumer(service_list=self.service_list, meta=self.meta.copy(), logger=self.logger)
    
        def run(self):
            self.consumer.run()

            
    def _set_vars(self, args):
        self.service_list = args.service_list
        self.meta = args.meta
        self.logger = LOGGER
        nt = self.NestedThread(service_list=self.service_list, meta=self.meta.copy(), logger=self.logger)
        nt.start()

    def __call__(self, func):
        def wrapped(*args, **kwargs):
            try: 
                self._set_vars(*args)
                msg = func(*args, **kwargs)
                return msg
            except Exception as e:
                self.logger.warning(traceback.format_exc())
                raise e
        return wrapped
