import pyodbc
import redis
import socket
import time
from api.config_service import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from collections import namedtuple
from log.logger import Logger
from common.password import get_password, decrypt_code, get_password_by_auth_token


class DBOperation(object):

    def __init__(self, db_type=None, logger=None, meta={}):
    
        if not db_type or db_type.upper() not in ('VERTICA', 'MSSQL'):
            raise ValueError("DB type is not specified or is not supported.")
        
        self.meta = meta
        self.db_type = db_type.lower()
        self.server_name = eval("meta['db_conn_%s_servername']" % self.db_type)
        self.port = eval("meta['db_conn_%s_port']" % self.db_type)
        self.db_name = eval("meta['db_conn_%s_dbname']" % self.db_type)
        self.username = eval("meta['db_conn_%s_username']" % self.db_type)
        self.is_pmp_password = False
        if 'db_conn_%s_password' % self.db_type in meta and eval("meta['db_conn_%s_password']" % self.db_type):
            self.password = eval("meta['db_conn_%s_password']" % self.db_type)
            if 'db_conn_%s_password_encrypted' % self.db_type in meta:
                self.password_encrypted = eval("meta['db_conn_%s_password_encrypted']" % self.db_type)
            else:
                raise ValueError('db_conn_%(db_type)s_password_encrypted is missing in meta, it must be specified if db_conn_%(db_type)s_password is specified.'%{'db_type':self.db_type})
        else:
            self.password = get_password(username=self.username, meta=meta)
            self.is_pmp_password = True
            self.password_encrypted = 'false'
        self.odbc_driver = eval("meta['db_driver_%s_odbc']" % self.db_type)
        self.sqlalchemy_driver = eval("meta['db_driver_%s_sqlachemy']" % self.db_type)
        
        if self.password_encrypted.lower() == "true":
            self.password = decrypt_code(self.password)

        self._connection = None
        self.__engine = None
        self._logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1)
    
    def get_connection_string(self, type='pyodbc'):
        if type=='pyodbc':
            return "DRIVER=%s;SERVER=%s;DATABASE=%s;PORT=%s;UID=%s;PWD=%s" % (self.odbc_driver, self.server_name, self.db_name, self.port, self.username, self.password)
        elif type=='sqlalchemy':
            dialect_driver = "%s+%s" % (self.db_type, self.sqlalchemy_driver) if self.db_type and self.sqlalchemy_driver else self.db_type
            return "%s://%s:%s@%s:%s/%s" % (dialect_driver, self.username, self.password, self.server_name, self.port, self.db_name)
        else:
            raise ValueError('Invalid type: %s'%type)
        
    def get_connection(self):
        if not self._connection:
            try:
                self._connection = pyodbc.connect(self.get_connection_string())
            except:
                if self.is_pmp_password: #if pasword work is changed in PMP
                    self._logger.warning('Connection refused, try to sync the password of %s from PMP and connect again.'%self.username)
                    self.password = get_password_by_auth_token(username=self.username, meta=self.meta) #refetch password and reconnect once
                    self._connection = pyodbc.connect(self.get_connection_string())
                else:
                    raise
        return self._connection
    
    def query(self, sql):
        conn = self.get_connection()
        c = conn.cursor()
        try:
            c.execute(sql)
        except Exception as e:
            self._logger.info("Failed to execute [%s] \nError: [%s]" % (sql, e))
            raise
        return c
            
    def execute(self, sql):
        conn = self.get_connection()
        with conn.cursor() as c:
            try:
                c.execute(sql)
            except Exception as e:
                self._logger.info("Failed to execute [%s] \nError: [%s]" % (sql, e))
                raise
        
    def query_scalar(self, sql):
        conn = self.get_connection()
        with conn.cursor() as c:
            try:
                c.execute(sql)
                row = c.fetchone()
                scalar_value = row[0] if row else None
                return scalar_value
            except Exception as e:
                self._logger.info("Failed to execute [%s] \nError: [%s]" % (sql, e))
                raise            
    
    def close_connection(self):
        if self._connection:
            self._connection.close()
    
    # ORM
    def get_engine(self):
        if not self.__engine:
            try:
                self.__engine = create_engine(self.get_connection_string('sqlalchemy'))
            except Exception as e:
                if self.is_pmp_password:
                    self._logger.warning('Connection refused, try to sync the password of %s from PMP and connect again.'%self.username)
                    self.password = get_password_by_auth_token(username=self.username, meta=self.meta) #refetch password and reconnect once
                    self.__engine = create_engine(self.get_connection_string('sqlalchemy'))
                else:
                    raise e
        return self.__engine

    def get_session(self):
        engine = self.get_engine()
        self.__session = scoped_session(sessionmaker(bind=engine))
        return self.__session
        
    def get_engine_connection(self):
        engine = self.get_engine()
        self.__engine_connection = engine.connect()
        return self.__engine_connection
        
    def close_engine_connection(self):
        if self.__engine_connection:
            self.__engine_connection.close()
        
        
class DWOperation(DBOperation):

    def __init__(self, logger=None, meta={}):
        super(DWOperation, self).__init__(db_type='vertica', logger=logger, meta=meta)
        
    def switch_partition(self, schema_name, table_name, partition_name, stage_schema_name, stage_table_name):
        self._logger.info("Starting to switch partition for %(schema_name)s.%(table_name)s.%(partition_name)s..." % {"schema_name": schema_name, 
                                                                                                                      "table_name": table_name, 
                                                                                                                      "partition_name": partition_name
                                                                                                                     }
                          )
        _sql = """
            SELECT SWAP_PARTITIONS_BETWEEN_TABLES('%(stage)s',
            '%(min_partition)s',
            '%(max_partition)s',
            '%(target)s'
            )""" % {"stage": stage_schema_name + "." + stage_table_name,
                    "min_partition": partition_name,
                    "max_partition": partition_name,
                    "target": schema_name + "." + table_name
                    }
        self._logger.info(_sql)
        self.execute(_sql)

        self._logger.info("Switch partition is completed for %(schema_name)s.%(table_name)s.%(partition_name)s." % {"schema_name": schema_name, 
                                                                                                                     "table_name": table_name, 
                                                                                                                     "partition_name": partition_name
                                                                                                                    }
                          )
    
    def create_temp_table(self, schema_name, table_name, body, to_physical_table=False, create_as_select=False):
        as_flag = "AS" if create_as_select else ""
        out_table_name = None
        drop_sql = None
        create_sql = None

        out_table_name = '%s.%s' % (schema_name, table_name)
        drop_sql = "DROP TABLE IF EXISTS %s" % out_table_name
        create_sql = "CREATE TABLE %s %s %s" % (out_table_name, as_flag, body)
        # no matter is_tmp_table is true or false, drop the physical temp table is exists
        self._logger.info("Dropping %s if exists" % out_table_name)
        self.execute(drop_sql)
        # if not to_physical_table, overwrite out_table_name, drop_sql and create_sql
        if not to_physical_table: 
            out_table_name = table_name
            drop_sql = "DROP TABLE IF EXISTS " + table_name
            if as_flag: 
                create_sql = "CREATE LOCAL TEMP TABLE %s ON COMMIT PRESERVE ROWS %s %s" % (out_table_name, as_flag, body)
            else: 
                create_sql = "CREATE LOCAL TEMP TABLE %s %s %s ON COMMIT PRESERVE ROWS" % (out_table_name, as_flag, body)
        
        self.execute(drop_sql)
        self.execute(create_sql)
        self._logger.info('%s is created successfully.' % out_table_name)
        return out_table_name
        
        
class MSOperation(DBOperation):

    def __init__(self, logger=None, meta={}, instance_name=None, iris_meta={}):
        super(MSOperation, self).__init__(db_type='mssql', logger=logger, meta=meta)
        self.instance_name = instance_name
        self.iris_meta = iris_meta # the meta from config.properties
        if self.does_query_mssql_instance():
            self.server_name = self.get_server_name_with_instance_port()
        
    def get_connection(self):
        if not self._connection:
            try:
                self._connection = pyodbc.connect(self.get_connection_string())
            except: 
                if self.is_pmp_password:
                    self._logger.warning('Connection refused, try to sync the password of %s from PMP and connect again.'%self.username)
                    self.password = get_password_by_auth_token(username=self.username, meta=self.meta) #refetch password
                if self.does_query_mssql_instance(): # if failed to connect to mssql instance, refresh port first and try again.
                    self._logger.info('Failed to connect to mssql instance with old port, getting the latest port...')
                    self.save_instance_port_to_db(self.server_name.split(',')[0], self.instance_name)
                    self.server_name = self.get_server_name_with_instance_port()
                    self._connection = pyodbc.connect(self.get_connection_string())
                elif self.is_pmp_password:
                    self._connection = pyodbc.connect(self.get_connection_string())
                else:
                    raise
        return self._connection
        
    def query(self, sql):
        conn = self.get_connection()
        with conn.cursor() as c:
            try: 
                c.execute(sql)
                columns = [column[0] for column in c.description]
                tmp_tuple = namedtuple('tmp_tuple', columns)
                result = []
                for row in c.fetchall():
                    result.append(tmp_tuple(**dict(zip(columns, row))))
                return result
            except Exception as e:
                self._logger.info("Failed to execute [%s] \nError: [%s]" % (sql, e))
                raise
    
    def get_server_name_with_instance_port(self):
        raw_server_name = self.server_name.split(',')[0]
        instance_port = self.get_instance_port(raw_server_name, self.instance_name)
        new_server_name = '%s,%s'%(raw_server_name, instance_port)
        self._logger.info('Adding instance port to server name: %s' % new_server_name)
        return new_server_name
    
    def does_query_mssql_instance(self):
        return True if hasattr(self, 'instance_name') and self.instance_name else False
    
    def lookup_instance_port(self, server, instance):
        """Query the SQL Browser service and extract the port number
        :type server: str
        :type instance: str
        """
        udp_port = 1434
        # message type per SQL Server Resolution Protocol
        udp_message_type = b'\x04'  # CLNT_UCAST_INST (client, unicast, instance)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(10)

        udp_message = udp_message_type + instance.encode()
        sock.sendto(udp_message, (server, udp_port))
        response = sock.recv(1024)  # max 1024 bytes for CLNT_UCAST_INST

        # response_type = response[0]  # \x05
        # response_length = response[1:3]  # 2 bytes, little-endian
        response_list = response[3:].decode().split(';')
        response_dict = {response_list[i]: response_list[i+1] for i in range(0, len(response_list), 2)}
        self._logger.info('Instance %s is listening on the port %s' % (instance, response_dict['tcp']))
        return int(response_dict['tcp'])
    
    def _get_iris_connection(self, server, instance):
        if hasattr(self, 'iris_conn') and self.iris_conn:
            return self.iris_conn
        else:
            self.iris_conn = MSOperation(logger=self._logger, meta={
              'db_conn_mssql_servername': self.iris_meta['db_conn_mssql_servername'], 
              'db_conn_mssql_port': self.iris_meta['db_conn_mssql_port'], 
              'db_conn_mssql_dbname': self.iris_meta['db_conn_mssql_dbname'], 
              'db_conn_mssql_username': self.iris_meta['db_conn_mssql_username'], 
              'db_driver_mssql_odbc': self.iris_meta['db_driver_mssql_odbc'],
              'db_driver_mssql_sqlachemy': self.iris_meta['db_driver_mssql_sqlachemy'], 
              'api_pmp_str': self.iris_meta['api_pmp_str'], 
              'db_conn_token': self.iris_meta['db_conn_token']
            })
            return self.iris_conn
    
    def get_instance_port(self, server, instance):
        iris_conn = self._get_iris_connection(server, instance)
        # VARIABLE_NAME: 'HUB:$HUB_SERVER:$HUB_INSTANCE_NAME'
        # VARIABLE_VALUE: '$HUB_INSTANCE_PORT'
        port = iris_conn.query_scalar("SELECT MAX(VARIABLE_VALUE) FROM VARIABLES WHERE VARIABLE_NAME='HUB:%s:%s'"%(server, instance))
        if port:
            return port
        else:
            return self.save_instance_port_to_db(server, instance)
        
    def save_instance_port_to_db(self, server, instance):
        iris_conn = self._get_iris_connection(server, instance)
        for i in range(0,10): 
            port = self.lookup_instance_port(server, instance)
            if port:
                break
            else:
                self._logger.info('[%s try] Didn''t get instance port, waiting for 5s to try to refetch port info...'%i)
                time.sleep(5)
        else:
            raise RuntimeError('Unable to get port for %s\\%s'%(server, instance))
        exists = iris_conn.query_scalar("SELECT COUNT(*) AS CNT FROM VARIABLES WHERE VARIABLE_NAME='HUB:%s:%s'"%(server, instance))
        if exists:
            iris_conn.execute("UPDATE VARIABLES SET VARIABLE_VALUE='%s', UPDATE_TIME=getdate() WHERE VARIABLE_NAME='HUB:%s:%s'"%(port, server, instance))
        else:
            iris_conn.execute("INSERT INTO VARIABLES(VARIABLE_NAME, VARIABLE_VALUE, INSERT_TIME, UPDATE_TIME) VALUES('HUB:%s:%s', '%s', getdate(), getdate())"%(server, instance, port))
        return port
            
        
class HubOperation(MSOperation):
    
    def __init__(self, hub_id, logger=None, meta={}):
        if not hub_id:
            raise ValueError("hub_id is not specified.")
        iris_meta = meta.copy()
        meta = meta.copy()
        config = Config(hub_id=hub_id, meta=meta)
        meta['db_conn_mssql_servername'] = config.get_property("db.server.name")
        meta['db_conn_mssql_port'] = config.get_property("db.port.no")
        meta['db_conn_mssql_dbname'] = config.get_property("db.database.name")
        meta['db_conn_mssql_username'] = meta["db_conn_mssql_hub_username"]
        #meta['db_conn_mssql_password'] = get_password(username=meta['db_conn_mssql_hub_username'], meta=meta)
        meta['db_conn_mssql_password_encrypted'] = 'false'
        instance_name = config.get_property("db.server.instance", "").replace("\\", "")
        
        super(HubOperation, self).__init__(logger=logger, meta=meta, instance_name=instance_name, iris_meta=iris_meta)
        

class SiloOperation(DWOperation):
    
    def __init__(self, vendor_key=None, retailer_key=None, hub_id=None, logger=None, meta={}):
        if not (vendor_key and retailer_key or hub_id):
            raise ValueError("vendor_key and retailer_key or hub_id is not specified.")
        meta = meta.copy()
        self.config = Config(vendor_key=vendor_key, retailer_key=retailer_key, hub_id=hub_id, meta=meta)
        meta['db_conn_vertica_servername'] = self.config.get_property("dw.server.name")
        meta['db_conn_vertica_port'] = self.config.get_property("dw.db.portno", "5433")
        meta['db_conn_vertica_dbname'] = self.config.get_property("dw.db.name")
        if meta["db_conn_vertica_silo_username"]:
            meta['db_conn_vertica_username'] = meta["db_conn_vertica_silo_username"]
            #meta['db_conn_vertica_password'] = get_password(username=meta['db_conn_vertica_silo_username'], meta=meta)
            meta['db_conn_vertica_password_encrypted'] = 'false'
        else:
            meta['db_conn_vertica_username'] = self.config.get_property("dw.etluser.id")
            meta['db_conn_vertica_password'] = self.config.get_property("dw.etluser.password")
            meta['db_conn_vertica_password_encrypted'] = 'true'
            
        super(SiloOperation, self).__init__(logger=logger, meta=meta)
        
        
class RedisOperation(object):
    
    def __init__(self, logger=None, meta={}):
        self.meta = meta
        self.server_name = meta['db_conn_redis_servername']
        self.port = meta['db_conn_redis_port']
        self.db = meta['db_conn_redis_dbname']
        self.password = get_password(username=meta["db_conn_redis_pmpname"], meta=meta)
        self.__connection = None
        self._logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1)
    
    def get_connection(self):
        if not self.__connection:
            if self.password:
                try:
                    self.__connection = redis.Redis(host=self.server_name, port=self.port, db=self.db, password=self.password, decode_responses=True)
                    self.test_connection(self.__connection)
                except:
                    self._logger.warning('Connection refused, try to sync the password of %s from PMP and connect again.'%self.meta["db_conn_redis_pmpname"])
                    self.password = get_password_by_auth_token(username=self.meta["db_conn_redis_pmpname"], meta=self.meta) #refetch password and reconnect once
                    self.__connection = redis.Redis(host=self.server_name, port=self.port, db=self.db, password=self.password, decode_responses=True)
                    self.test_connection(self.__connection)
            else:
                self.__connection = redis.Redis(host=self.server_name, port=self.port, db=self.db, decode_responses=True)
        return self.__connection

    def test_connection(self, conn):
        for k in conn.scan_iter(match='TESTREDISCONNECTION', count=100):
            c.rename(k, 'TESTREDISCONNECTION')

if __name__ == "__main__":
    
    import configparser
    CONFIG_FILE = '../../config/config.properties'
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    props = config['DEFAULT']
    meta = dict([(k, props[k]) for k in props])
    #print(meta)
    
    def test_vertica_connetion():
        print('>>>>>>>>>>>>>>>>>>>> test_vertica_connetion')
        dw = DWOperation(meta=meta)
        result = dw.query('select vendor_key, item_key, upc from OSA_AHOLD_BEN.OLAP_ITEM_OSM where %s = 24043' % 'item_key')
        for row in result:
            print(row.vendor_key)
        dw.execute("drop table if exists OSA_AHOLD_BEN.testtest; create table OSA_AHOLD_BEN.testtest(id int)")
        result = dw.query_scalar('select vendor_key from OSA_AHOLD_BEN.OLAP_ITEM_OSM where 1=2')
        print(result)
        
        tmp_1 = dw.create_temp_table('OSA_AHOLD_BEN', 'TEST1', '(ID INT, NAME VARCHAR(10))', to_physical_table=False, create_as_select=False)
        print(dw.query_scalar('SELECT COUNT(*) FROM %s' % tmp_1))
        tmp_2 = dw.create_temp_table('OSA_AHOLD_BEN', 'TEST2', 'SELECT * FROM TABLES WHERE 1=2', to_physical_table=False, create_as_select=True)
        print(dw.query_scalar('SELECT COUNT(*) FROM %s' % tmp_2))
        tmp_3 = dw.create_temp_table('OSA_AHOLD_BEN', 'TEST3', '(ID INT, NAME VARCHAR(10))', to_physical_table=True, create_as_select=False)
        print(dw.query_scalar('SELECT COUNT(*) FROM %s' % tmp_3))
        tmp_4 = dw.create_temp_table('OSA_AHOLD_BEN', 'TEST4', 'SELECT * FROM TABLES WHERE 1=2', to_physical_table=True, create_as_select=True)
        print(dw.query_scalar('SELECT COUNT(*) FROM %s' % tmp_4))
        dw.execute('drop table ' + tmp_1)
        print('dropped ' + tmp_1)
        dw.execute('drop table ' + tmp_2)
        print('dropped ' + tmp_2)
        
        dw.close_connection()
        
        conn = dw.get_engine_connection()
        result = conn.execute('select count(*) as cnt from OSA_AHOLD_BEN.OLAP_ITEM_OSM')
        for row in result:
            print(row['cnt'])
        dw.close_engine_connection()
    
    def test_vertica_field_with_blankspace():
        print('>>>>>>>>>>>>>>>>>>>> test_vertica_field_with_blankspace')
        dw = DWOperation(meta=meta)
        dw.execute('create table common.test_black_space_vtc("first name" varchar(100), id integer)')
        rs = dw.query('select "first name", id from common.test_black_space_vtc')
        print(rs.description)
        print(rs)
        for r in rs:
            print(r.__getattribute__('first name'))
        dw.execute('drop table common.test_black_space_vtc')
    
    def test_mssql_connection():
        print('>>>>>>>>>>>>>>>>>>>> test_mssql_connection')
        sql = MSOperation(meta=meta)
        result = sql.query('select id, log_timestamp from [dbo].[RSI_LOG]')
        for row in result:
            print("%s - %s" % ( row.id, row.log_timestamp) )
        #sql.execute("create table testtest(id int)")
        
        result = sql.query_scalar('select count(*) from RSI_LOG')
        print(result)
        sql.close_connection()
        
        #conn = sql.get_engine_connection()
        #result = conn.execute('select count(*) as cnt from RSI_LOG')
        #for row in result:
        #    print(row['cnt'])
        #sql.close_engine_connection()
        
    def test_mssql_instance_connection(): # HubOperation
        print('>>>>>>>>>>>>>>>>>>>> test_mssql_instance_connection')
        sql = HubOperation(meta=meta, hub_id='HUB_FUNCTION_MB') # the hub server with instance name
        cnt = sql.query_scalar('select count(*) from ETL.RSI_TRANSFER_DETAIL')
        print('>>>>', cnt)
        print('Connected successfully.')
        
        sql = HubOperation(meta=meta, hub_id='HUB_FUNCTION_beta') # the hub server without instance name
        cnt = sql.query_scalar('select count(*) from ETL.RSI_TRANSFER_DETAIL')
        print('>>>>', cnt)
        print('Connected successfully.')
        
    def test_partition_switcher():
        print('>>>>>>>>>>>>>>>>>>>> test_partition_switcher')
        logger = Logger(log_level="info", target="console|file", vendor_key = -1, retailer_key = -1, log_file="./test.log")

        dw = DWOperation(meta=meta, logger=logger)
        dw.switch_partition('RDP_WAG_DEMO', 'RAW_STORE_INVENTORY_1', 'A', 'RDP_WAG_DEMO', 'RAW_STORE_INVENTORY_1_A')

    def test_redis_connection():
        print('>>>>>>>>>>>>>>>>>>>> test_redis_connection')
        r = RedisOperation(meta=meta)
        c = r.get_connection()
        to_vendor_key = 23
        to_retailer_key = 267
        for k in c.scan_iter(match='FEEDBACK:*:*:*:*', count=10000):
            prefix, vendor_key, retailer_key, alert_id, ts = k.split(':')
            c.rename(k, '%s:%s:%s:%s:%s' % (prefix, to_vendor_key, to_retailer_key, alert_id, ts))
        
    def test_silo_connection(): # SiloOperation
        print('>>>>>>>>>>>>>>>>>>>> test_silo_connection')
        dw = SiloOperation(vendor_key=342, retailer_key=6, meta=meta)
        rs = dw.query('select distinct table_schema from columns')
        schemas = [r.table_schema for r in rs]
        print(len(schemas))
    
    print('+++++++++++++++++++++PMP+++++++++++++++++++++')
    test_vertica_connetion()
    test_vertica_field_with_blankspace()
    test_mssql_connection()
    #test_partition_switcher()
    test_redis_connection()
    test_mssql_instance_connection()
    test_silo_connection()
    print('+++++++++++++++++++++MEM+++++++++++++++++++++')
    test_vertica_connetion()
    test_vertica_field_with_blankspace()
    test_mssql_connection()
    #test_partition_switcher()
    test_redis_connection()
    test_mssql_instance_connection()
    test_silo_connection()
    print('+++++++++++++++++++++UPD PASSWORD WRONG IN MEM++++++++++++++++++++')
    from common.password_info import PasswordInfo
    pi = PasswordInfo()
    print(pi.get_password())
    for username in pi.get_password():
        pi.set_password(username, 'aaa')
    test_vertica_connetion()
    test_vertica_field_with_blankspace()
    test_mssql_connection()
    #test_partition_switcher()
    test_redis_connection()
    test_mssql_instance_connection()
    test_silo_connection()
    print('+++++++++++++++++++++MEM AGAIN++++++++++++++++++++')
    test_vertica_connetion()
    test_vertica_field_with_blankspace()
    test_mssql_connection()
    #test_partition_switcher()
    test_redis_connection()
    test_mssql_instance_connection()
    test_silo_connection()
