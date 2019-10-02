import redis
import os
import json
import datetime
import traceback
import copy
from db.crypto import Crypto
from db.db_operation import DBOperation, DWOperation, RedisOperation
from log.logger import Logger
from optparse import OptionParser
from api.capacity_service import Capacity
from common.step_status import StepStatus
from agent.master import MasterHandler
from agent.app import App
from tornado.gen import coroutine
from mq.publisher import BasePublisher

class FeedbackPersist(object):

    def __init__(self, 
                 meta={}, 
                 to_physical_table=False, 
                 no_delete_key=False, 
                 logger=None):
                 
        logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="Persist_Feedback")
        vertica_conn = DWOperation(meta=meta,
                                   logger=logger)
        redis_conn = RedisOperation(meta=meta,
                                    logger=logger)
        c = redis_conn.get_connection()
        column_mapping = { 
            'from_key': [
                # Save a value from key into dataset
                # ['key name in dataset', 'index of key elements splitted by :']
                ['UPDATE_TIME', 4] #FEEDBACK:342:6:38726000097879:20190219013621  --> get key.split(':')[4]
            ], 
            'hardcode': [
                # ['key name in dataset', 'hardcode value']
                ['EVENT_KEY', '-1'], 
            ], 
            'from_redis': [
                # ['table column', 'key name in dataset', 'table column type', 'value updatable', 'target']
                # Be noted, the table column type, if the value needs to be quoted, use VARCHAR, else use NUMBER
                # so int, float, number -> NUMBER
                # varchar, date, timestamp -> VARCHAR
                # updatable means the value of the column would be updated if alerts already exist
                ['ALERT_ID', 'ALERT_ID', 'NUMBER', 'NON-UPDATABLE', 'TABLE|MOBILE'],
                ['VENDOR_KEY', 'VENDOR_KEY', 'NUMBER', 'NON-UPDATABLE', 'TABLE|MOBILE'],
                ['RETAILER_KEY', 'RETAILER_KEY', 'NUMBER', 'NON-UPDATABLE', 'TABLE|MOBILE'],
                ['ITEM_KEY', 'ITEM_KEY', 'NUMBER', 'NON-UPDATABLE', 'TABLE'],
                ['STORE_KEY', 'STORE_KEY', 'NUMBER', 'NON-UPDATABLE', 'TABLE'],
                ['PERIOD_KEY', 'PERIOD_KEY', 'NUMBER', 'NON-UPDATABLE', 'TABLE'],
                ['STORE_REP', 'STORE_REP', 'VARCHAR', 'NON-UPDATABLE', 'TABLE'],
                ['STORE_VISITED_PERIOD_KEY', 'STORE_VISITED_PERIOD_KEY', 'NUMBER', 'NON-UPDATABLE', 'TABLE'],        
                ['FEEDBACK_DESCRIPTION', 'FEEDBACK_DESCRIPTION', 'VARCHAR', 'UPDATABLE', 'TABLE|MOBILE'], 
                ['ON_HAND_PHYSICAL_COUNT', 'ON_HAND_PHYSICAL_COUNT', 'NUMBER', 'UPDATABLE', 'TABLE|MOBILE'],
                ['ON_HAND_CAO_COUNT', 'ON_HAND_CAO_COUNT', 'NUMBER', 'UPDATABLE', 'TABLE|MOBILE'],
                ['SOURCE', 'SOURCE', 'VARCHAR', 'NON-UPDATABLE', 'TABLE'],
                ['CYCLE_KEY', 'CYCLE_KEY', 'NUMBER', 'NON-UPDATABLE', 'MOBILE'],
                ['UPDATE_TIME', 'UPDATE_TIME', 'VARCHAR', 'NON-UPDATABLE', 'MOBILE'],
                ['EVENT_KEY', 'EVENT_KEY', 'NUMBER', 'NON-UPDATABLE', 'TABLE'],
            ]
        }
        
        self.vars = {
            "meta": meta,
            "logger": logger, 
            "column_mapping": column_mapping,
            "vertica_conn": vertica_conn,
            "redis_conn": c,
            "to_physical_table": to_physical_table, 
            "no_delete_key": no_delete_key
        }
        
        capacity = Capacity(meta)
        self.vars['capacity'] = capacity
        

    class NestedPublisher(BasePublisher):
        
        def on_action(self, body):
            self._app_id = 'feedbackNanny'
            self._body = body
            
        
    def _gen_dataset(self):
        redis_conn = self.vars['redis_conn']
        logger = self.vars['logger']
        ## Collect keys
        to_do = {} # {'FEEDBACK:VENDOR:RETAILER:ALERTID1':'TS', 'FEEDBACK:VENDOR:RETAILER:ALERTID2':'TS', 'FEEDBACK:VENDOR:RETAILER:ALERTID3':'TS'}
        keys_to_delete = []
        for key in redis_conn.scan_iter(match='FEEDBACK:*:*:*:*', count=10000):
            key_no_ts = ':'.join(key.split(':')[0:4])
            ts = key.split(':')[4]
            if key_no_ts in to_do:
                if to_do[key_no_ts] < ts:
                    keys_to_delete.append(key_no_ts + ':' + to_do[key_no_ts]) # old ts -> keys_to_delete if old ts < new ts
                    to_do[key_no_ts] = ts
                else:
                    keys_to_delete.append(key_no_ts + ':' + ts) # new ts -> keys_to_delete if new ts < old ts
            else:
                to_do[key_no_ts] = ts
            
        keys_ready = [k + ':' + str(to_do[k]) for k in to_do] # keys will be insert/update into db
        logger.info('%s keys not up-to-date' % len(keys_to_delete))
        logger.info('%s keys ready to ins/upd' % len(keys_ready))
        keys_to_delete = keys_to_delete + keys_ready # keys to delete including keys ready to update db, now it should have all the keys query out from redis
        keys_to_delete_by_retailer = {} # this dataset is used to delete keys once they're updated in DB
        for k in keys_to_delete:
            retailer = k.split(':')[2]
            keys_to_delete_by_retailer.setdefault(retailer, []).append(k)
        logger.info('%s keys will be removed from redis' % len(keys_to_delete))
        
        ## Create a dataset for ins/upd db
        dataset = {}
        #{
        #  r1: [ {alert:a1, fdbk_desc:f1, store_on_hand:10}, 
        #        {alert:a2, fdbk_desc:f2, store_on_hand:8}, 
        #      ],
        #  r2: [ {alert:a3, fdbk_desc:f2, store_on_hand:9}, 
        #        {alert:a4, fdbk_desc:f3, store_on_hand:2}, 
        #      ]
        #}
        for key in keys_ready:
            vendor, retailer, alert_id, update_ts = key.split(':')[1:]
            row_data = redis_conn.hgetall(key)
            logger.info('key: %s'%key)
            dataset.setdefault(retailer, []).append({'ALERT_ID': row_data['ALERT_ID'], 
                                                     'VENDOR_KEY':row_data['VENDOR_KEY'], 
                                                     'RETAILER_KEY':row_data['RETAILER_KEY'], 
                                                     'ITEM_KEY': row_data['ITEM_KEY'], 
                                                     'STORE_KEY': row_data['STORE_KEY'],
                                                     'PERIOD_KEY': row_data['PERIOD_KEY'], 
                                                     'STORE_REP': row_data['STORE_REP'], 
                                                     'STORE_VISITED_PERIOD_KEY': row_data['STORE_VISIT_PERIOD_KEY'], 
                                                     'FEEDBACK_DESCRIPTION': row_data['FEEDBACK_DESCRIPTION'] if 'FEEDBACK_DESCRIPTION' in row_data else '', 
                                                     'ON_HAND_PHYSICAL_COUNT': row_data['ON_HAND_PHYSICAL_COUNT'] if 'ON_HAND_PHYSICAL_COUNT' in row_data and row_data['ON_HAND_PHYSICAL_COUNT'].strip(' ')!='' else 'null', #if null, when generating the query, it look like ..., null, ...
                                                     'ON_HAND_CAO_COUNT': row_data['ON_HAND_CAO_COUNT'] if 'ON_HAND_CAO_COUNT' in row_data and row_data['ON_HAND_CAO_COUNT'].strip(' ')!='' else 'null', 
                                                     'SOURCE': row_data['SOURCE'],
                                                     'CYCLE_KEY': row_data['CYCLE_KEY'],
                                                     **dict([(e[0], key.split(':')[e[1]]) for e in self.vars['column_mapping']['from_key']]), # merge values from key into data row
                                                     **dict([(e[0], e[1]) for e in self.vars['column_mapping']['hardcode']]), # merge hardcoded values into data row
                                                    })
        logger.info('%s retailers are in the dataset.' % len(dataset))
        return (dataset, keys_to_delete, keys_to_delete_by_retailer)
        
        
    def _save_to_temp_table(self):
        dataset = self.vars['dataset']
        column_mapping = self.vars['column_mapping']
        vertica_conn = self.vars['vertica_conn']
        to_physical_table = self.vars['to_physical_table']
        logger = self.vars['logger']
        capacity = self.vars['capacity']
        
        table_name = 'FACT_FEEDBACK'
        column_names = [pair[0] for pair in column_mapping['from_redis'] if 'TABLE' in pair[4].split('|')]
        dataset_column_names = [pair[1] for pair in column_mapping['from_redis'] if 'TABLE' in pair[4].split('|')]
        column_types = [pair[2] for pair in column_mapping['from_redis'] if 'TABLE' in pair[4].split('|')]
        
        ## save dataset into tmp table
        common_schema_name = self.vars['meta']['db_conn_vertica_common_schema']
        rand_retailer_key = list(dataset.keys())[0] #randomly choose one retailer key and to find its retailer name as schema name
        feedback_schema_name = capacity.get_retailer_schema_name(rand_retailer_key)
        
        logger.info('Start to create temp table %s...' % 'TMP_REDIS_FEEDBACK')
        temp_table_name = vertica_conn.create_temp_table(common_schema_name, 
                                                         table_name='TMP_REDIS_FEEDBACK', 
                                                         body='SELECT %s FROM %s.%s WHERE 1=2' % (','.join(column_names), feedback_schema_name, table_name), 
                                                         to_physical_table=to_physical_table, 
                                                         create_as_select=True
                                                        )
        logger.info('%s is created.' % temp_table_name)
        ins_head_sql = 'INSERT INTO %(temp_table_name)s(%(column_names)s) ' %{'temp_table_name': temp_table_name, 
                                                                              'column_names': ','.join(column_names)
                                                                             }
        total_idx = 0
        for retailer in dataset:
            ins_value_sql = [] # ["(1,'b')", "(2,'c')", ...]
            idx = 0
            for row in dataset[retailer]:
                tmp_value = []
                for i, v in enumerate(dataset_column_names):
                    if column_types[i].upper() in ('VARCHAR'):
                        tmp_value.append("'" + row[v] + "'")
                    else:
                        tmp_value.append(row[v])
                ins_value_sql.append(','.join([v for v in tmp_value]))
                idx += 1
                if idx%1000 == 0: # 1000 rows insert in batch
                    exec_sql = ins_head_sql + ' UNION ALL '.join(['SELECT ' + v for v in ins_value_sql])
                    vertica_conn.execute(exec_sql)
                    logger.info('retailer_key=%s %s keys have been refreshed into tmp table.' % (retailer, idx))
                    ins_value_sql = []
                    
            if len(ins_value_sql) > 0:
                exec_sql = ins_head_sql + ' UNION ALL '.join(['SELECT ' + v for v in ins_value_sql])
                vertica_conn.execute(exec_sql)
            logger.info('retailer_key=%s %s keys have been refreshed into tmp table.' % (retailer, idx))
            total_idx += idx
        logger.info('totally %s keys have been refreshed into tmp table.' % total_idx)
        
        return temp_table_name
        
        
    def _update_feedback_data(self, retailer): 
    # update data based on temp table
        dataset = self.vars['dataset']
        column_mapping = self.vars['column_mapping']
        vertica_conn = self.vars['vertica_conn']
        temp_table_name = self.vars['temp_table_name']
        logger = self.vars['logger']
        capacity = self.vars['capacity']

        table_name = 'FACT_FEEDBACK'
        column_names = [c[0] for c in column_mapping['from_redis'] if 'TABLE' in c[4].split('|')]
        temp_column_names = ['temp.' + c[0] for c in column_mapping['from_redis'] if 'TABLE' in c[4].split('|')]
        updatable_columns = [c[0] for c in column_mapping['from_redis'] if c[3] == 'UPDATABLE' and 'TABLE' in c[4].split('|')]
        temp_updatable_columns = ['temp.' + c for c in updatable_columns]
        update_columns = ','.join(['='.join(c) for c in zip(updatable_columns, temp_updatable_columns)])
        
        retailer_name = capacity.get_retailer_schema_name(retailer)
        full_table_name = retailer_name + '.' + table_name
        full_alert_table_name = retailer_name + '.FACT_PROCESSED_ALERT'
        upd_sql = '''UPDATE %(full_table_name)s fact
            SET %(update_columns)s
            FROM %(temp_table_name)s temp
            WHERE fact.ALERT_ID = temp.ALERT_ID
            AND temp.RETAILER_KEY = %(retailer_key)s
            ''' % {'full_table_name': full_table_name,
                   'update_columns': update_columns,
                   'temp_table_name': temp_table_name, 
                   'retailer_key': retailer
                  }
        vertica_conn.execute(upd_sql)
        logger.info('Feedback data has been updated into %s for retailer key %s' % (full_table_name, retailer))
            
        ins_sql = '''INSERT INTO %(full_table_name)s(%(column_names)s, MERCHANDISER) 
            SELECT %(temp_column_names)s, alert.OWNER
            FROM %(temp_table_name)s temp
            INNER JOIN %(full_alert_table_name)s alert ON temp.ALERT_ID = alert.ALERT_ID
            LEFT JOIN %(full_table_name)s fact ON temp.ALERT_ID = fact.ALERT_ID
            WHERE fact.ALERT_ID IS NULL 
            AND temp.RETAILER_KEY = %(retailer_key)s
            ''' % {'full_table_name': full_table_name,
                   'column_names': ','.join(column_names), 
                   'temp_column_names': ','.join(temp_column_names),
                   'full_alert_table_name': full_alert_table_name, 
                   'temp_table_name': temp_table_name,
                   'retailer_key': retailer, 
                  }
        vertica_conn.execute(ins_sql)
        logger.info('New feedback data has been inserted into %s for retailer key %s' % (full_table_name, retailer))
        
    
    def _send_to_mobile(self, retailer, publisher):
        '''
        {
          "delivery_time": "2018-12-13 13:00:00", 
          "alerts": [
            {"retailer_key": 1, "vendor_key": 100, "cycle_key": 1, "alert_id": 123, "feedback_description": "1. xxxx", "cao_count": 100, "physical_count": 20, "updated_time": "2018-12-13 12:58:00"}, 
            {"retailer_key": 1, "vendor_key": 100, "cycle_key": 1, "alert_id": 124, "feedback_description": "2. xxxx", "cao_count": 70, "physical_count": 40, "updated_time": "2018-12-13 12:58:20"},
            ...
          ]
        }
        '''
        dataset = self.vars['dataset'][retailer]
        columns = [e[0] for e in self.vars['column_mapping']['from_redis'] if 'MOBILE' in e[4].split('|')]
        dataset_keys = [e[1] for e in self.vars['column_mapping']['from_redis'] if 'MOBILE' in e[4].split('|')]
        key_column_pair = dict(list(zip(dataset_keys, columns)))
        body = {}
        body['delivery_time'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        body['alerts'] = []
        for r in dataset:
            body['alerts'].append({key_column_pair[k]:v for k, v in r.items() if k in dataset_keys})
        publisher.on_action(json.dumps(body))
        publisher.run()
        
        
    def _del_keys(self, redis_conn, keys_to_delete, logger, retailer):
    # as keys are already persisted into db, deleting keys from redis
        no_delete_key = self.vars['no_delete_key'] if self.vars['no_delete_key'] else False
        if not no_delete_key:
            with redis_conn.pipeline() as p:
                for k in keys_to_delete:
                    p.delete(k)
                p.execute()
            logger.info('%s keys have been deleted for retailer %s.' % (len(keys_to_delete), retailer))
        else:
            logger.info('Keys will not be deleted as no_delete_key=True')

            
    def run(self):
        logger = self.vars['logger']
        dataset, keys_to_delete, keys_to_delete_by_retailer = self._gen_dataset()
        logger.info('The dataset below is going to be processed...')
        logger.info('%s'%dataset)
        if len(keys_to_delete) == 0:
            logger.info('No feedback needs to be saved.')
            return 'No feedback needs to be saved.'
        
        self.vars['dataset'] = dataset
        temp_table_name = self._save_to_temp_table()
        self.vars['temp_table_name'] = temp_table_name
        
        meta = copy.deepcopy(self.vars['meta'])
        meta["mq_exchange_name"] = self.vars['meta']["mq_iris_exchange_name"]
        meta["mq_exchange_type"] = self.vars['meta']["mq_iris_exchange_type"]
        meta["mq_routing_key"] = self.vars['meta']["mq_iris_feedback_routing_key"]
        np = self.NestedPublisher(meta=meta, logger=self.vars['logger'])
        try:
            for retailer in dataset:
                self._update_feedback_data(retailer)
                self._send_to_mobile(retailer, np)
                self._del_keys(self.vars['redis_conn'], keys_to_delete_by_retailer[retailer], logger, retailer)
        except Exception as e:
            np.stop()

        return '|'.join(['retailer_key=%s:persisted_feedbacks=%s'%(d, len(dataset[d])) for d in dataset])
    
    
class FeedbackPersistNanny(FeedbackPersist):
    
    def __init__(self, meta, request_body, logger=None):
        meta = meta.copy()
        logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="feedbackNanny")
        to_physical_table = request_body.get('to_physical_table', 'false').lower()
        no_delete_key = request_body.get('no_delete_key', 'false').lower()
        FeedbackPersist.__init__(self, 
                                 meta=meta,
                                 to_physical_table=False if to_physical_table=='false' else True, 
                                 no_delete_key=False if no_delete_key=='false' else True, 
                                 logger=logger)
    
    
class FeedbackPersistHandler(MasterHandler):

    def set_service_properties(self):
        self.service_name = 'feedbackNanny'
    
    
class FeedbackPersistApp(App):
    '''
    This class is just for testing, osa_bundle triggers it somewhere else
    '''
    def __init__(self, meta):
        App.__init__(self, meta=meta, service_bundle_name='feedbackNanny')
    
    
if __name__ == '__main__':

    '''REQUEST BODY
    {
      "jobId": 23456789,
      "stepId": 1,
      "batchId": 0,
      "retry": 0, 
      "status": 3, 
      "message": "running", 
      "groupName": "11"
    }
    '''
    import os
    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    exec(open(generic_main_file).read())
    
    app = FeedbackPersistApp(meta=meta)   #************* update services.json --> feedbackNanny.service_bundle_name to feedbackNanny before running the script
    app.start_service()

    
    