
import json
import os
from tornado.ioloop import IOLoop
from tornado.web import Application, url
from log.logger import Logger
from agent.communicator import Communicator
from common.password import get_password_by_auth_token
from mq.consumer import BaseConsumer


def _cache_password(meta):
    usernames = [v for k, v in meta.items() if ('username' in k.lower() or 'pmpname' in k.lower()) and 'iris' in v.lower()]
    for username in usernames:
        try:
            get_password_by_auth_token(username=username, meta=meta)
            print('Password for %s cached'%username)
        except Exception as e:
            print('Unable to fetch password for %s'%username)
            raise e


class App(object):

    def __init__(self, meta, service_bundle_name, osa_backend_base_dir='/../../../', port=8000):
        self.meta = meta
        _cache_password(self.meta)
        file_abs_dir = os.path.dirname(os.path.abspath(__file__))
        relative_path = [*(osa_backend_base_dir.split('/')), 'common', 'config', 'services.json']
        service_config = file_abs_dir + os.path.sep + os.path.join(*relative_path)
        with open(service_config) as f:
            services = json.load(f)
        
        app_service_list = []
        self.service_list = [] # used in communicator
        for service_name in services:
            # dynamically loading modules based on services.json
            service = services[service_name]
            if ('module_name' in service
                and 'handler_class_name' in service
                and 'url_prefix' in service
                and 'service_bundle_name' in service
                and service['service_bundle_name']==service_bundle_name
                ):
                module_name = service['module_name']
                handler_class_name = service['handler_class_name']
                url_prefix = service['url_prefix']
                module = __import__(module_name, fromlist=[handler_class_name])
                klass = getattr(module, handler_class_name)
                self.service_list.append(service_name)
                app_service_list.append(url(r'%s'%url_prefix, klass, dict(meta=self.meta.copy())))
                print('Binding service: %s' % service_name)
        
        if not self.service_list:
            raise RuntimeError('No service is binded.')
        settings = {'debug': False, 'autoreload': False}
        self.app = Application(app_service_list, **settings)
        self.app.listen(port)
        print('Listen on the port %s' % port)
        print('Services start to running...')

    @Communicator()
    def start_service(self):
        IOLoop.current().start()
    

class MessageApp(object):

    class NestedConsumer(BaseConsumer):
        
        def __init__(self, meta, service_routing_key, service_queue_name, handler_class, service_name, logger):
            self.meta = meta.copy()
            self.meta_raw = meta.copy()
            self.handler_class = handler_class
            self.service_name = service_name
            self.logger = logger
            super().__init__(meta={**self.meta, "mq_routing_key": service_routing_key, "mq_queue_name": service_queue_name}, logger=logger)
            
        def on_action(self, body):
            self.logger.info('Consumer received message: %s'%body)
            body = json.loads(body)
            hc = self.handler_class(meta=self.meta_raw, body=body, service_name=self.service_name, logger=self.logger)
            hc.main()

    def __init__(self, meta, service_name, osa_backend_base_dir='/../../../', port=8000):
        self.meta = meta
        _cache_password(self.meta)
        file_abs_dir = os.path.dirname(os.path.abspath(__file__))
        relative_path = [*(osa_backend_base_dir.split('/')), 'common', 'config', 'services.json']
        service_config = file_abs_dir + os.path.sep + os.path.join(*relative_path)
        with open(service_config) as f:
            services = json.load(f)
            
        self.service_list = [] # used in communicator
        if (service_name in services
            and 'module_name' in services[service_name]
            and 'handler_class_name' in services[service_name]
            and 'routing_key' in services[service_name]
            and 'queue_name' in services[service_name]
            ):
            service = services[service_name]
            module_name = service['module_name']
            handler_class_name = service['handler_class_name']
            module = __import__(module_name, fromlist=[handler_class_name])
            klass = getattr(module, handler_class_name)
            self.service_list.append(service_name)
            logger = Logger(log_level="info", vendor_key=-1, retailer_key=-1)
            logger.set_keys(module_name=service_name)
            self.consumer = self.NestedConsumer(meta=meta, 
                                                service_routing_key=services[service_name]['routing_key'],
                                                service_queue_name=services[service_name]['queue_name'],
                                                handler_class=klass, 
                                                service_name=service_name, 
                                                logger=logger)

    @Communicator()
    def start_service(self):
        self.consumer.run()
