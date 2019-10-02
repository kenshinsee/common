import pika
import json
import ssl
import os
import requests
from log.logger import Logger
from abc import ABC, abstractmethod
from db.db_operation import DBOperation
from common.password import get_password, get_password_by_auth_token

class BasePublisher(ABC):
    
    def __init__(self, meta={}, logger=None):
        self._connection = None
        self._channel = None
        self._password = get_password(username=meta["mq_pmpname"], meta=meta)
        self.meta = meta
        self._exchange = meta['mq_exchange_name']
        self._exchange_type = meta['mq_exchange_type']
        self._routing_key = meta['mq_routing_key']

        if not os.path.exists(meta['mq_ca_certs']): 
            raise RuntimeError("%s doesn't exist."%meta['mq_ca_certs'])
        if not os.path.exists(meta['mq_key_file']): 
            raise RuntimeError("%s doesn't exist."%meta['mq_key_file'])
        if not os.path.exists(meta['mq_cert_file']): 
            raise RuntimeError("%s doesn't exist."%meta['mq_cert_file'])
            
        self._app_id = None
        self._body = None
        self._logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1)

    def get_connection_parameters(self, meta):
        credentials = pika.PlainCredentials(meta['mq_username'], self._password)    
        ssl_options = dict(
            ssl_version=ssl.PROTOCOL_TLSv1,
            ca_certs=meta['mq_ca_certs'],
            keyfile=meta['mq_key_file'],
            certfile=meta['mq_cert_file'],
            cert_reqs=ssl.CERT_REQUIRED
        )
        return pika.ConnectionParameters(ssl=True,
            host=meta['mq_host'],
            port=meta['mq_port'],
            credentials=credentials,
            connection_attempts=int(meta['mq_connection_attempts']), 
            heartbeat=int(meta['mq_heartbeat_interval']),
            ssl_options=ssl_options
            )
    
    def connect(self):
        try:
            self._connection = pika.BlockingConnection(self.get_connection_parameters(self.meta))
        except:
            self._logger.warning('Connection refused, try to sync the password of %s from PMP and connect again.'%self.meta["mq_pmpname"])
            self._password = get_password_by_auth_token(username=self.meta["mq_pmpname"], meta=self.meta)
            self._connection = pika.BlockingConnection(self.get_connection_parameters(self.meta))
    
    def open_channel(self):
        if not self._connection:
            self.connect()
        self._channel = self._connection.channel()
    
    def declare_exchange(self):
        if not self._channel:
            self.open_channel()
        self._logger.info("Declaring exchange [%s], type [%s], routing_key [%s]" % (self._exchange, self._exchange_type, self._routing_key))
        self._channel.exchange_declare(exchange=self._exchange,
                                       exchange_type=self._exchange_type,
                                       durable=True)
    
    @abstractmethod
    def on_action(self, body):
        pass
        #self._app_id = 'APPID'
        #self._body = 'BODY'
    
    def run(self):
        if not (self._app_id and self._body):
            raise ValueError('app_id or body is not specified in the method on_action')
            
        self.declare_exchange()
        properties = pika.BasicProperties(app_id=self._app_id,
                                          content_type='application/json', 
                                          delivery_mode=2
                                          )

        message = self._body
        self._channel.basic_publish(self._exchange, 
                                    self._routing_key,
                                    #json.dumps(message, ensure_ascii=False),
                                    message,
                                    properties)  
        self._logger.info("Published successfully [%s]" % message)
        
    def stop(self):
        self._logger.info("Closing connection")
        self._connection.close()
        self._logger.info("Connection closed")
    

if __name__ == '__main__':

    def main():
        import configparser
        CONFIG_FILE = '../../config/config.properties'
        config = configparser.ConfigParser()
        config.read(CONFIG_FILE)
        meta = config['DEFAULT']
        meta = {k:v for k, v in meta.items()}
        meta["mq_exchange_name"] = meta["mq_iris_exchange_name"]
        meta["mq_exchange_type"] = meta["mq_iris_exchange_type"]
        meta["mq_routing_key"] = meta["mq_iris_feedback_routing_key"]
        
        class AFMPublisher(BasePublisher):
            def on_action(self, body):
                self._app_id = 'AFM'
                self._body = body
        afm = AFMPublisher(meta)
        for i in range(0,10):
            afm.on_action('{"jobId":%s,"stepId":2,"batchId":0,"retry":0,"status":0}'%i)
            afm.run()
        afm.stop()

    def fanout():
        import configparser
        CONFIG_FILE = '../../config/config.properties'
        config = configparser.ConfigParser()
        config.read(CONFIG_FILE)
        meta = config['DEFAULT']
        meta = {k:v for k, v in meta.items()}
        meta["mq_exchange_name"] = meta["mq_agent_exchange_name"]
        meta["mq_exchange_type"] = 'fanout'
        meta["mq_routing_key"] = ''
        
        class AFMPublisher(BasePublisher):
            def on_action(self, body):
                self._app_id = 'AFM'
                self._body = body
        afm = AFMPublisher(meta)
        for i in range(0,10):
            afm.on_action('{"jobId":%s,"stepId":2,"batchId":0,"retry":0,"status":0}'%i)
            afm.run()
        afm.stop()

    fanout()
