import pika
import json
import ssl
import os
from db.db_operation import DBOperation
from abc import ABC, abstractmethod
from log.logger import Logger
from mq.publisher import BasePublisher
from mq.consumer import BaseConsumer
from datetime import datetime

if __name__ == '__main__':

    class TestConsumer(BaseConsumer):
        def on_action(self, body):
            print('[%s] Received in TestConsumer: %s'%(datetime.now(), body))
            
    def main():
        import configparser
        CONFIG_FILE = '../../config/config.properties'
        config = configparser.ConfigParser()
        config.read(CONFIG_FILE)
        props = config['DEFAULT']
        meta = dict([(k, props[k]) for k in props])
        print(meta)
        
        c = TestConsumer(meta)
        try:
            c.run()
        except KeyboardInterrupt:
            c.stop()

    main()
    