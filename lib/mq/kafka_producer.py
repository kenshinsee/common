import os
from json import dumps
from kafka import KafkaProducer
from kafka.errors import KafkaError
from log.logger import Logger


class Producer(object):
    def __init__(self, meta, logger=None):
        self.meta = meta
        self.logger = logger

        self.kafka_broker = str(self.meta.get("kafka_broker")).split(',')
        self.kafka_topic = self.meta.get("kafka_topic")

        self.producer = KafkaProducer(bootstrap_servers=self.kafka_broker,
                                      # value_serializer=lambda x: dumps(x).encode('utf-8')
                                      )

    def _check_msg_format(self, msg):
        # This func will handle python dict.
        # check if msg is json format
        if isinstance(msg, dict):
            return True

        return False

    def produce_data(self, msg, key=None, headers=None, partition=None, timestamp_ms=None):
        try:
            flag = self._check_msg_format(msg=msg)
            if flag:
                print("Sending message of python dict type...")
                msg_byte = dumps(msg).encode('utf-8')

            else:
                print("Sending message of string type...")
                msg_byte = str(msg).encode('utf-8')

            future_rec = self.producer.send(self.kafka_topic, value=msg_byte, key=key,
                                            headers=headers, partition=partition,
                                            timestamp_ms=timestamp_ms)
            res = future_rec.get(timeout=1)  # have to add this line, otherwise there will be no message sent out.
            # sleep(1)  # or adding sleep(1) instead
            print(res)
        except KafkaError as e:
            print(e)


if __name__ == '__main__':
    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + '..' + SEP + 'script\\' + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    meta = {}
    exec(open(generic_main_file).read())  # fill meta argument

    p = Producer(meta)
    data = {"key2": "value2"}
    # data = '{"key1": "value1"}'
    p.produce_data(data)
