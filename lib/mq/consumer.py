import pika
import ssl
import os
from abc import ABC, abstractmethod
from log.logger import Logger
from common.password import get_password, get_password_by_auth_token


class BaseConsumer(ABC):

    def __init__(self, meta={}, logger=None):
        self._connection = None
        self._channel = None
        self._password = get_password(username=meta["mq_pmpname"], meta=meta)
        self.meta = meta
        self._exchange = meta['mq_exchange_name']
        self._exchange_type = meta['mq_exchange_type']
        self._routing_key = meta['mq_routing_key']
        self._queue = meta['mq_queue_name']

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
        self._logger.info("Declaring exchange [%s], type [%s]" % (self._exchange, self._exchange_type))
        self._channel.exchange_declare(exchange=self._exchange,
                                       exchange_type=self._exchange_type,
                                       durable=True)
    
    def bind_queue(self):
        self.declare_exchange()
        self._channel.queue_declare(queue=self._queue, durable=True)

        self._logger.info("Binding queue [%s->%s->%s]" % (self._exchange, self._routing_key, self._queue))
        self._channel.queue_bind(exchange=self._exchange,
                           queue=self._queue,
                           routing_key=self._routing_key)
        
    @abstractmethod
    def on_action(self, body):
        pass
        
    def consume(self):
        self.bind_queue()
        
        def callback(ch, method, properties, body):
            self.on_action(body.decode('utf-8'))
            
        self._channel.basic_consume(callback,
                                    queue=self._queue,
                                    no_ack=True)
        
    def run(self):
        self.consume()
        self._channel.start_consuming()
            
    def stop(self):
        self._logger.info("Closing connection")
        self._connection.close()
        self._logger.info("Connection closed")


class FanoutConsumer(BaseConsumer):

    def __init__(self, meta={}, logger=None):

        self._connection = None
        self._channel = None
        self._password = get_password(username=meta["mq_pmpname"], meta=meta)
        self.meta = meta
        self._exchange = meta['mq_exchange_name']
        self._exchange_type = 'fanout'

        if not os.path.exists(meta['mq_ca_certs']): 
            raise RuntimeError("%s doesn't exist."%meta['mq_ca_certs'])
        if not os.path.exists(meta['mq_key_file']): 
            raise RuntimeError("%s doesn't exist."%meta['mq_key_file'])
        if not os.path.exists(meta['mq_cert_file']): 
            raise RuntimeError("%s doesn't exist."%meta['mq_cert_file'])
        
        self._app_id = None
        self._body = None
        self._logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1)

    def bind_queue(self):
        self.declare_exchange()
        result = self._channel.queue_declare(queue='', exclusive=True, durable=True)
        self._queue = result.method.queue

        self._logger.info("Binding queue [%s->%s]" % (self._exchange, self._queue))
        self._channel.queue_bind(exchange=self._exchange, queue=self._queue)

        
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
        meta["mq_queue_name"] = "test.feedback.queue"
        class TestConsumer(BaseConsumer):
            def on_action(self, body):
                print("running test case with body: %s" % body)

        test1 = TestConsumer(meta)
        try:
            test1.run()
        except KeyboardInterrupt:
            test1.stop()

    def fanout():
        import configparser
        CONFIG_FILE = '../../config/config.properties'
        config = configparser.ConfigParser()
        config.read(CONFIG_FILE)
        meta = config['DEFAULT']
        meta = {k:v for k, v in meta.items()}
        meta["mq_exchange_name"] = meta["mq_agent_exchange_name"]
        class TestConsumer(FanoutConsumer):
            def on_action(self, body):
                print("running test case with body: %s" % body)

        test1 = TestConsumer(meta)
        try:
            test1.run()
        except KeyboardInterrupt:
            test1.stop() 

    fanout()
