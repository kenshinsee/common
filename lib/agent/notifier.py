
import socket
import json
import traceback
import time
import copy
from common.step_status import StepStatus
from mq.publisher import BasePublisher
from datetime import datetime
from log.logger import Logger
from agent.job_info import JobInfo


def Notifier(func):
    
    class NestedPublisher(BasePublisher):
        
        def __init__(self, service_name, meta={}, logger=None):
            super().__init__(meta=meta, logger=logger)
            self.service_name = service_name
        
        def on_action(self, body):
            self._app_id = self.service_name
            self._body = body
            
    def set_vars(*args):
        service_name = args[0].service_name
        meta = args[0].meta
        request_body = args[0].request_body
        is_notifiable = args[0].is_notifiable
        job_params = {}
        logger = args[0].logger if hasattr(args[0], 'logger') else Logger(log_level="info", vendor_key=-1, retailer_key=-1)
        job_info = JobInfo()
        if is_notifiable:
            # we only need to send back keys which are listed below
            job_required_keys = ['jobId', 'stepId', 'batchId', 'retry', 'groupName']
            job_params = dict([(k, request_body[k]) for k in job_required_keys if k in request_body])
        return {
            'service_name': service_name, 
            'meta': meta, 
            'request_body': request_body, 
            'is_notifiable': is_notifiable, 
            'job_params': job_params, 
            'logger': logger, 
            'job_info': job_info
        }
        
    def _add_job_info(vars):
        if vars['is_notifiable']:
            vars['logger'].info('Current running jobs: %s'%vars['job_info'].get_job_info())
            info = vars['job_info'].set_job_info(vars['job_params']['jobId'], vars['service_name'])
            vars['logger'].info('Job info added: %s'%info)
        
    def _set_success(vars, msg=None):
        """
        Adding paras into job_params, this paras is used in JobService to pass parameters to given job.
        The paras format should be like below:
        paras = {"key1": "value1", "key2": "value2", "key3": "value3", ... }
        if msg is None or it is not a dict object, then no need to pass it to paras.

        :param vars:
        :param msg: it should be a dict object. then we can pass this to JobService. Otherwise do NOT pass it to paras.
        :return:
        """
        if vars['is_notifiable']:
            vars['job_params']['message'] = str(msg) if msg else '%s - Successfully executed %s' % (datetime.now(), vars['service_name'])
            vars['job_params']['status'] = StepStatus.SUCCESS.value
            if msg and isinstance(msg, dict):
                vars['job_params']['paras'] = msg

    def _set_failure(vars, msg=None):
        # no need to pass paras when job failed.
        if vars['is_notifiable']:
            vars['job_params']['message'] = str(msg) if msg else '%s - Failed when executing %s'%(datetime.now(), vars['service_name'])
            vars['job_params']['status'] = StepStatus.ERROR.value
            
    def _remove_job_info(vars):
        if vars['is_notifiable']:
            vars['logger'].info('Removing job info: job_id=%s service_name=%s' % (vars['job_params']['jobId'], vars['service_name']))
            info = vars['job_info'].del_job_info(vars['job_params']['jobId'], vars['service_name'])
            vars['logger'].info('Job info removed: %s' % info)
    
    def _send_message(vars):
        if vars['is_notifiable']:
            vars['logger'].info('Sending to job service: %s'%vars['job_params'])
            np = NestedPublisher(meta=vars['meta'], service_name=vars['service_name'], logger=vars['logger'])
            vars['job_params']['message'] = vars['job_params']['message'][0:999]  # truncate message just in case it's too long
            np.on_action(json.dumps(vars['job_params']))
            np.run()
            np.stop()
        
    def wrapper(*args, **kwargs):
        try:
            vars = set_vars(*args)
            _add_job_info(vars)
            msg = func(*args, **kwargs)
            _set_success(vars, msg)
            return msg
        except Exception as e:
            vars['logger'].warning(traceback.format_exc())
            _set_failure(vars, traceback.format_exc())
        finally:
            _remove_job_info(vars)
            _send_message(vars)
            
    return wrapper
    
    
    
if __name__=='__main__':
    
    import os
    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + '..' + SEP + 'script' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    exec(open(generic_main_file).read())
    # meta is ready to use
    
    
    class TestNotifier(object):
        def __init__(self):
            self.service_name = 'test_service'
            self.meta = meta
            self.request_body = {'jobId': 1, 'stepId': 1, 'batchId': 0, 'retry': 0, 'status': 3, 'message': 'RUNNING', 'groupName': 'TestGroupName'}
            self.is_notifiable = True
            #self.is_notifiable = False
            self.logger = Logger(log_level="info", vendor_key=20, retailer_key=100)
            self.logger.info('tttttttttttttttteeeeeeeeeeeeeeeeeeessssssssssstttttttttttttt')
            
        @Notifier
        def test(self):
            print('yoyo')
            
        @Notifier
        def test_failure(self):
            raise RuntimeError('Calling error.')
            
        def main(self):
            self.test()
            #self.test_failure()
            print('done')
            
    t = TestNotifier()
    t.main()
    
