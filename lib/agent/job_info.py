import time
import threading
import socket
from common.singleton import SingletonMetaClass
from datetime import datetime
from common.step_status import StepStatus

class JobInfo(metaclass=SingletonMetaClass):

    def __init__(self):
        self.job_status = {}        
    
    def _get_host_name(self):
        return socket.gethostname()
    
    def _get_host_ip(self):
        return socket.gethostbyname(self._get_host_name())
    
    def set_job_info(self, job_id, service_name):
        key = 'IRISJOB:%s:%s'%(job_id, service_name)
        self.job_status[key] = {'job_id': job_id, 'service_name': service_name, 'start_time': datetime.now(), 'host_name': self._get_host_name(), 'host_ip': self._get_host_ip()}
        return self.job_status[key]
        
    def get_job_info(self, job_id=None, service_name=None):
        key = 'IRISJOB:%s:%s'%(job_id, service_name)
        if job_id is None or service_name is None:
            return self.job_status
        elif key in self.job_status:
            return self.job_status[key]
        else:
            return None
    
    def del_job_info(self, job_id=None, service_name=None):
        key = 'IRISJOB:%s:%s'%(job_id, service_name)
        if key in self.job_status:
            return self.job_status.pop(key)
        else:
            return None
    
    def get_job_status(self, job_id=None, service_name=None):
        job_status = self.get_job_info(job_id=job_id, service_name=service_name)
        if job_status:
            return StepStatus.RUNNING.value
        return None
        
    
if __name__=='__main__':
    from pprint import pprint
    
    class T1(threading.Thread):
        
        def __init__(self):
            threading.Thread.__init__(self)
            self.a = JobInfo()
            self.a.set_job_info('1', 'afm')
            self.a.set_job_info('2', 'ag')
        
        def run(self):
            print('T1')
            pprint(self.a.get_job_info())
            #time.sleep(10)
        
    class T2(threading.Thread):
        
        def __init__(self):
            threading.Thread.__init__(self)
            self.b = JobInfo()
            self.b.set_job_info('3', 'sc')
            
        def run(self):
            print('T2')
            pprint(self.b.get_job_info())

    t1 = T1()
    t1.start()
    time.sleep(1)
    t2 = T2()
    t2.start()
    
    time.sleep(1)
    c = JobInfo()
    print('Delete C')
    pprint(c.del_job_info('3', 'sc'))
    print('All C')
    pprint(c.get_job_info())
    
    