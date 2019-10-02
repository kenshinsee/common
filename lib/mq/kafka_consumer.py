import os
from kafka import KafkaConsumer
from json import loads


class Consumer(object):
    def __init__(self, meta, offset='earliest', group_id=None):
        self.meta = meta

        self.kafka_broker = str(self.meta.get("kafka_broker")).split(',')
        self.kafka_topic = self.meta.get("kafka_topic")
        # self.kafka_username = self.meta.get("kafka_username")
        self.consumer = KafkaConsumer(
            self.kafka_topic,
            bootstrap_servers=self.kafka_broker,
            auto_offset_reset=offset,
            enable_auto_commit=True,
            group_id=group_id,
            # value_deserializer=lambda x: loads(x.decode('utf-8'))
        )

    def subscribe(self, topics=(), pattern=None):
        # subscribe multi topics with given topics or using pattern.
        self.consumer.subscribe(topics=topics, pattern=pattern)
        # self.consumer.subscribe(pattern='^mytopic*')

    def consume_data(self):
        for message in self.consumer:
            message = message.value
            print(message, type(message))


if __name__ == '__main__':
    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + '..' + SEP + 'script\\' + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    meta = {}
    exec(open(generic_main_file).read())  # fill meta argument

    c = Consumer(meta, group_id="group1")
    c.subscribe(topics=['mytopic', 'topic1', 'topic4'])
    c.consume_data()
