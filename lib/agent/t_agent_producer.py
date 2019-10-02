import pika
import json
import ssl
import os
from db.db_operation import DBOperation
from abc import ABC, abstractmethod
from log.logger import Logger
from mq.publisher import BasePublisher
from mq.consumer import BaseConsumer


if __name__ == '__main__':
    
    class TestPublisher(BasePublisher):
    
        def on_action(self, body):
            self._body = body
            self._app_id = 'test_app'
            
    def main():
        import configparser
        CONFIG_FILE = '../../config/config.properties'
        config = configparser.ConfigParser()
        config.read(CONFIG_FILE)
        meta = config['DEFAULT']
        meta['mq_routing_key'] = meta['mq_agent_routing_key']
        meta['mq_exchange_name'] = meta['mq_agent_exchange_name']
        
        agent_params = {
            'jobId': 4
        }
        
        tp = TestPublisher(meta)
        tp.on_action(json.dumps(agent_params))
        tp.run()
        tp.stop()

    main()