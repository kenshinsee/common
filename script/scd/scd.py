import os
import json
import datetime
import traceback
import collections
from db.db_operation import DWOperation, MSOperation
from log.logger import Logger
from common.timer import Timer
from agent.master import MasterHandler
from agent.app import App

class Scd(object):

    def __init__(self, sql, actioner, log_detail=True, batch_size=100, meta={}, db_type=None, table_schema=None, logger=None):
        self.meta = meta
        self.actioner = actioner
        self.log_detail = log_detail
        self.batch_size = batch_size
        self.logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="scd")
        self.sql = sql
        self.raw_sql_splitted = self.sql.split(' ')
        self.raw_sql_splitted_trimed = [str for str in self.raw_sql_splitted if str != '']
        self.db_type = db_type
        self.table_schema = table_schema
        self.logger.info('[SQL] %s'%self.sql)
        self.logger.info('[SQL splitted] %s'%self.raw_sql_splitted)
        self.mssql = MSOperation(meta=self.meta)
        self.vtc = None
        self.saved_records_count = 0
        
    def set_insert_delete_update(self):
        cmd = self.raw_sql_splitted_trimed[0].upper()
        if cmd in ('DELETE', 'UPDATE', 'INSERT'):
            self.cmd = cmd
        else:
            raise RuntimeError('%s is not supported.'%cmd)
    
    def locate_keyword(self, keyword, sql_splitted=[]):
        # find the location of the keyword firstly appears in the sql
        # e.g. locate WHERE
        # UPDATE TEST SET COL = ' WHERE ' WHERE ID=1, the first ' WHERE ' is not a keyword, so return the index of the 2nd WHERE
        keyword = keyword.upper()
        base_seq_splitted = sql_splitted if sql_splitted else self.raw_sql_splitted # if sql_splitted is specified, locate keyword in sql_splitted, otherwise locate keyword in raw_sql_splitted
        index_keyword = [k for k, v in enumerate(base_seq_splitted) if keyword in v.upper()]
        for ind in index_keyword:
            count_of_single_quote_ahead_of_where = sum([base_seq_splitted[i].count("'") for i in range(0, ind) if "'" in base_seq_splitted[i]])
            i = base_seq_splitted[ind].upper().index(keyword)
            count_of_single_quote_ahead_of_where += base_seq_splitted[ind][0:i].count("'")
            if count_of_single_quote_ahead_of_where%2==0: # the KEYWORD we want to capture is the one has n*2 "'" ahead of it
                return ind
        return -1 # KEYWORD not found
    
    def locate_keyword_combination(self, keywords):  #--mainly for parsing merge, may need to be updated
        # find the location of the first keyword, and to check if 2nd, 3rd keywords are just following the 1st keyword in the SQL
        # if match all the keywords, return the index of the first keyword
        # else return -1
        keywords_list = [w.upper().strip() for w in keywords.split(' ') if w.strip()!='']
        sql_splitted = [*self.raw_sql_splitted]
        base_ind = 0
        self.logger.info('Locating %s'%keywords_list)
        while True:
            self.logger.info('Locating 1st keyword "%s"'%keywords_list[0])
            ind = self.locate_keyword(keywords_list[0], sql_splitted)
            if ind==-1:
                self.logger.warning('Keyword not found.')
                return -1
            following = [v.upper().strip() for v in sql_splitted[ind+1:] if v.strip()!='']
            self.logger.info('Getting following %s', following)
            if following[0:len(keywords_list)-1]==keywords_list[1:]:
                self.logger.info('Keywords matched!')
                return base_ind + ind
            else:
                self.logger.warning('Keywords not matched.')
                sql_splitted = sql_splitted[ind+1:]
                base_ind += ind
            
    def get_merge_where(self): #--TODO, not done yet, the sql gramma "update from" for vertica and sqlserver are different, need more time to work on this
        index_using = self.locate_keyword('USING')
        index_on = self.locate_keyword('ON')
        index_when_match = self.locate_keyword_combination('WHEN MATCHED THEN')
        index_when_not_match = self.locate_keyword_combination('WHEN NOT MATCHED THEN')
    
    def get_where_condition(self):
        index_where = self.locate_keyword('WHERE')
        return '' if index_where==-1 else ' '.join(self.raw_sql_splitted[index_where:])
    
    def get_table_name(self):
        self.set_insert_delete_update()
        return self.raw_sql_splitted_trimed[1].upper() if self.cmd=='UPDATE' else self.raw_sql_splitted_trimed[2].upper()
    
    def get_raw_table_name(self, table_name):
        return table_name.split('.')[-1]
    
    def get_table_def(self, raw_table_name):
        sql = "SELECT ID, TABLE_NAME, PK, DB_TYPE, TABLE_SCHEMA FROM META_SCD_TABLE_DEF WHERE TABLE_NAME='%s'"%raw_table_name
        if self.db_type:
            sql += " AND DB_TYPE='%s'"%self.db_type
        if self.table_schema:
            sql += " AND TABLE_SCHEMA='%s'"%self.table_schema
        rs = self.mssql.query(sql)
        if len(rs)==0:
            raise ValueError('[TABLE_NAME:%s, DB_TYPE:%s, TABLE_SCHEMA:%s] The table is not found.'%(raw_table_name, db_type, table_schema))
        elif len(rs)>1:
            self.logger.info('|ID|TABLE_NAME|DB_TYPE|TABLE_SCHEMA|')
            for r in rs:
                self.logger.info('|%s|%s|%s|%s|'%(r.ID, r.TABLE_NAME, r.DB_TYPE, r.TABLE_SCHEMA))
            raise ValueError('[TABLE_NAME:%s, DB_TYPE:%s, TABLE_SCHEMA:%s] More than one records returned for the table.'%(raw_table_name, db_type, table_schema))
        else:
            if rs[0].DB_TYPE=='MSSQL':
                self.target_conn = self.mssql
            else:
                self.vtc = DWOperation(meta=self.meta)
                self.target_conn = self.vtc
            return rs[0]
    
    def get_mssql_table_ddl_def(self, db_name, table_name, table_schema):
        ddl_sql = '''SELECT COLUMN_NAME, DATA_TYPE
            FROM %s.INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = N'%s'
            AND TABLE_SCHEMA = N'%s'
            ORDER BY ORDINAL_POSITION
        '''%(db_name, table_name, table_schema)
        rs = self.mssql.query(ddl_sql)
        #return dict([('"%s"'%r.COLUMN_NAME if ' ' in r.COLUMN_NAME else r.COLUMN_NAME, r.DATA_TYPE) for r in rs])
        return dict([(r.COLUMN_NAME, r.DATA_TYPE) for r in rs])
        
    def get_vertica_table_ddl_def(self, table_name, table_schema):
        ddl_sql = '''SELECT COLUMN_NAME, DATA_TYPE
            FROM COLUMNS
            WHERE TABLE_NAME = '%s'
            AND TABLE_SCHEMA = '%s'
            ORDER BY ORDINAL_POSITION
        '''%(table_name, table_schema)
        rs = self.vtc.query(ddl_sql)
        #return dict([('"%s"'%r.COLUMN_NAME if ' ' in r.COLUMN_NAME else r.COLUMN_NAME, r.DATA_TYPE) for r in rs])
        return dict([(r.COLUMN_NAME, r.DATA_TYPE) for r in rs])
        
    def save_to_db(self, table_def, recs):
        pk = json.loads(table_def.PK)
        batch_sqls = []
        columns = 'TABLE_DEF_ID, PK_VALUE, ACTION, RECORD, UPDATE_TIME, ACTIONER' if self.log_detail else 'TABLE_DEF_ID, PK_VALUE, ACTION, UPDATE_TIME, ACTIONER'
        counter = 0
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for rec in recs:
            pk_dict = collections.OrderedDict()
            for k in pk:
                pk_dict[k] = rec[k]
            pk_value = json.dumps(pk_dict).replace("'", "''")
            if self.log_detail:
                batch_sqls.append('''SELECT %s, '%s', '%s', '%s', '%s', '%s' '''%(table_def.ID, pk_value, self.cmd, json.dumps(rec).replace("'", "''"), now, self.actioner))
            else:
                batch_sqls.append('''SELECT %s, '%s', '%s', '%s', '%s' '''%(table_def.ID, pk_value, self.cmd, now, self.actioner))
            counter += 1
            if len(batch_sqls)%self.batch_size==0:
                self.mssql.execute('''INSERT INTO META_SCD_CHANGE_LOG(%s) %s'''%(columns, ' UNION ALL '.join(batch_sqls)))
                batch_sqls = []
                self.logger.info('%s has been logged.'%counter)
        if len(batch_sqls)>0:
            self.mssql.execute('''INSERT INTO META_SCD_CHANGE_LOG(%s) %s'''%(columns, ' UNION ALL '.join(batch_sqls)))
            self.logger.info('%s has been logged.'%counter)

    @Timer()
    def save_data_to_be_changed(self, table_def, where_condition):
        if table_def.DB_TYPE=='MSSQL':
            table_schema = 'dbo' if table_def.TABLE_SCHEMA=='(COMMON)' else table_def.TABLE_SCHEMA
            table_ddl_def = self.get_mssql_table_ddl_def(self.meta['db_conn_mssql_dbname'], table_def.TABLE_NAME, table_schema)
        else: # vertica
            table_schema = self.meta['db_conn_vertica_common_schema'] if table_def.TABLE_SCHEMA=='(COMMON)' else table_def.TABLE_SCHEMA
            table_ddl_def = self.get_vertica_table_ddl_def(table_def.TABLE_NAME, table_schema)
        if not self.log_detail: # only dump primary key columns
            pk = json.loads(table_def.PK)
            table_ddl_def = dict([(c,table_ddl_def[c]) for c in table_ddl_def if c in pk])
        self.logger.info(table_ddl_def)
        query_columns = ','.join(['"%s"'%c if ' ' in c else c for c in list(table_ddl_def.keys())])
        pull_data_sql = 'SELECT %s FROM %s.%s %s'%(query_columns, table_schema, table_def.TABLE_NAME, where_condition)
        self.logger.info(pull_data_sql)
        rs = self.target_conn.query(pull_data_sql)
        recs = []
        for r in rs:
            rec = {}
            for c in list(table_ddl_def.keys()):
                #rec[c] = str(eval("r."+c)) if 'TIME' not in table_ddl_def[c].upper() and 'DATE' not in table_ddl_def[c].upper() else eval("r."+c).strftime("%Y-%m-%d %H:%M:%S")
                rec[c] = str(eval('r.__getattribute__("%s")'%c))
            recs.append(rec.copy())
        self.saved_records_count = len(recs)
        self.logger.info('%s records will be saved.'%self.saved_records_count)
        self.save_to_db(table_def, recs)
    
    @Timer()
    def execute_sql(self):
        self.target_conn.execute(self.sql)
    
    def main(self):
        try: 
            try: 
                table_name = self.get_table_name()
                raw_table_name = self.get_raw_table_name(table_name)
                table_def = self.get_table_def(raw_table_name)
                saved = False
                if self.cmd!='INSERT':
                    where_condition = self.get_where_condition()
                    self.save_data_to_be_changed(table_def, where_condition)
                    saved = True
            except Exception as e:
                self.logger.warning(traceback.format_exc())
                self.logger.warning('Failed to save the to-be-changed data, start to executing sql.')
            self.execute_sql()
            return '(%(db_type)s)%(table_schema)s.%(table_name)s - impacted %(row_count)s rows, saved %(status)s'%{
                    'db_type': table_def.DB_TYPE,
                    'table_schema': table_def.TABLE_SCHEMA,
                    'table_name': table_def.TABLE_NAME, 
                    'row_count': self.saved_records_count,
                    'status': 'N/A' if self.cmd=='INSERT' else 'successfully' if saved else 'unsuccessfully'
                }
        finally:
            if self.mssql:
                self.mssql.close_connection()
            if self.vtc:
                self.vtc.close_connection()
        

class ScdExecutor(Scd):
    
    def __init__(self, meta, request_body, logger=None):
        self.logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="scd")
        
        Scd.__init__(
            self, 
            sql=request_body.get('sql'), 
            actioner=request_body.get('actioner'), 
            log_detail=request_body.get('log_detail', True), 
            batch_size=request_body.get('batch_size', 100), 
            meta=meta, 
            db_type=request_body.get('db_type'), 
            table_schema=request_body.get('table_schema'), 
            logger=self.logger
        )
        
        
class ScdNanny:
    
    def __init__(self, meta, request_body, logger=None):
        self.logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="scd")
        self.meta = meta
        self.request_body = request_body
        
    def main(self):
        if isinstance(self.request_body, dict):
            s = ScdExecutor(meta=self.meta, request_body=self.request_body, logger=self.logger)
            return s.main()
        elif isinstance(self.request_body, list):
            msg = []
            for rb in self.request_body:
                s = ScdExecutor(meta=self.meta, request_body=rb, logger=self.logger)
                msg.append(s.main())
            return ' | '.join(msg)
        

class ScdHandler(MasterHandler):

    def set_service_properties(self):
        self.service_name = 'scdNanny'
        self.set_as_sync_service()
        self.set_as_not_notifiable()
    
    
class ScdApp(App):
    '''
    This class is just for testing, osa_bundle triggers it somewhere else
    '''
    def __init__(self, meta):
        App.__init__(self, meta=meta, osa_backend_base_dir='../../../', service_bundle_name='osa_bundle')
    
    
if __name__ == '__main__':

    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    exec(open(generic_main_file).read())
    
    def test_parse_table_and_where():
        scd = Scd(sql="DELETE FROM AAAA WHERE A=1 AND B=2 and c = 'where'", actioner='test', meta=meta)
        print(scd.get_table_name())
        print(scd.get_where_condition())
        scd = Scd(sql='DELETE FROM AAAA ', actioner='test', meta=meta)
        print(scd.get_table_name())
        print(scd.get_where_condition())
        scd = Scd(sql="UPDATE bbb.AAAA SET A='WHERE ' WHERE 1 = 2 AND B = 'WHERE WHERE' AND C = 'C' ", actioner='test', meta=meta)
        print(scd.get_table_name())
        print(scd.get_where_condition())
        
    #test_parse_table_and_where()
        
    def test_gen_mssql_test_data():
        mssql = MSOperation(meta=meta)
        try:
            mssql.execute('drop table test_backupfille')
        except:
            print('table doesn\'t exists')
        mssql.execute('select * into test_backupfille from msdb.dbo.backupfile') #--backup_set_id, file_number
        
        rs = mssql.query('select id from META_SCD_TABLE_DEF where table_name=\'test_backupfille\'')
        if not rs:
            sql = '''
            INSERT INTO META_SCD_TABLE_DEF(TABLE_NAME, PK, DB_TYPE, TABLE_SCHEMA, CREATE_TIME)
            SELECT 'test_backupfille', '["backup_set_id", "file_number"]', 'MSSQL', '(COMMON)', GETDATE()
            '''
            mssql.execute(sql)
        
        '''
        CREATE TABLE DIM_SCD_TEST(
          ID INT NOT NULL IDENTITY(1,1),
          NAME VARCHAR(128), 
          DESCRIPTION VARCHAR(1024),
          CREATE_TIME DATETIME, 
          DEPT_ID INT
        );
        INSERT INTO DIM_SCD_TEST(NAME, DESCRIPTION, CREATE_TIME, DEPT_ID) VALUES('DAN', 'TEST DAN', GETDATE(), 100);
        INSERT INTO DIM_SCD_TEST(NAME, DESCRIPTION, CREATE_TIME, DEPT_ID) VALUES('LUCY', 'TEST LUCY', GETDATE(), 100);
        INSERT INTO DIM_SCD_TEST(NAME, DESCRIPTION, CREATE_TIME, DEPT_ID) VALUES('JACK', 'TEST JACK', GETDATE(), 100);
        INSERT INTO DIM_SCD_TEST(NAME, DESCRIPTION, CREATE_TIME, DEPT_ID) VALUES('ROSE', 'TEST ROSE', GETDATE(), 101);
        INSERT INTO DIM_SCD_TEST(NAME, DESCRIPTION, CREATE_TIME, DEPT_ID) VALUES('MARY', 'TEST MARY', GETDATE(), 101);
        INSERT INTO DIM_SCD_TEST(NAME, DESCRIPTION, CREATE_TIME, DEPT_ID) VALUES('JASON', 'TEST JASON', GETDATE(), 101);

        INSERT INTO META_SCD_TABLE_DEF(TABLE_NAME, PK, DB_TYPE, TABLE_SCHEMA, CREATE_TIME)
        SELECT 'DIM_SCD_TEST', '["NAME", "DEPT_ID"]', 'MSSQL', '(COMMON)', GETDATE();
        '''
        
    def test_gen_vtc_test_data():
        mssql = MSOperation(meta=meta)
        vtc = DWOperation(meta=meta)
        try:
            vtc.execute('drop table common.test_columns')
        except:
            print('table doesn\'t exists')
        vtc.execute('create table common.test_columns as select * from columns')
        
        rs = mssql.query('select id from META_SCD_TABLE_DEF where table_name=\'test_columns\'')
        if not rs:
            sql = '''
            INSERT INTO META_SCD_TABLE_DEF(TABLE_NAME, PK, DB_TYPE, TABLE_SCHEMA, CREATE_TIME)
            SELECT 'test_columns', '["table_schema", "table_name", "column_name"]', 'VERTICA', '(COMMON)', GETDATE()
            '''
            mssql.execute(sql)
        
        '''
        CREATE TABLE DIM_SCD_TEST_vtc(
          ID IDENTITY(1,1),
          NAME VARCHAR(128), 
          DESCRIPTION VARCHAR(1024),
          CREATE_TIME DATETIME, 
          DEPT_ID INT
        );
        INSERT INTO DIM_SCD_TEST_vtc(NAME, DESCRIPTION, CREATE_TIME, DEPT_ID) VALUES('DAN', 'TEST DAN', now(), 100);
        INSERT INTO DIM_SCD_TEST_vtc(NAME, DESCRIPTION, CREATE_TIME, DEPT_ID) VALUES('LUCY', 'TEST LUCY', now(), 100);
        INSERT INTO DIM_SCD_TEST_vtc(NAME, DESCRIPTION, CREATE_TIME, DEPT_ID) VALUES('JACK', 'TEST JACK', now(), 100);
        INSERT INTO DIM_SCD_TEST_vtc(NAME, DESCRIPTION, CREATE_TIME, DEPT_ID) VALUES('ROSE', 'TEST ROSE', now(), 101);
        INSERT INTO DIM_SCD_TEST_vtc(NAME, DESCRIPTION, CREATE_TIME, DEPT_ID) VALUES('MARY', 'TEST MARY', now(), 101);
        INSERT INTO DIM_SCD_TEST_vtc(NAME, DESCRIPTION, CREATE_TIME, DEPT_ID) VALUES('JASON', 'TEST JASON', now(), 101);
        '''
        
    def test_delete_update():
        scd = Scd(sql="DELETE FROM DIM_SCD_TEST WHERE name='MARY'", meta=meta, actioner='hong.hu')
        scd.main()
        scd = Scd(sql="UPDATE COMMON.DIM_SCD_TEST_vtc SET DESCRIPTION='test MARY 1' WHERE name='MARY'", meta=meta, actioner='hong.hu')
        scd.main()
        scd = Scd(sql="UPDATE COMMON.DIM_SCD_TEST_vtc SET DESCRIPTION='TEST DAN 2' WHERE name='DAN'", meta=meta, actioner='hong.hu')
        scd.main()
        scd = Scd(sql="UPDATE COMMON.DIM_SCD_TEST_vtc SET DESCRIPTION='TEST DAN 2' WHERE name='JASON'", meta=meta, actioner='hong.hu')
        scd.main()
        
    def test_performance_mssql():
        scd = Scd(sql='''update test_backupfille set logical_name = replace(logical_name, '1', '')
            where logical_name like 'HUB_FUNCTION_BETA%' or logical_name like 'HUB_Beta_UAT%' ''', meta=meta, actioner='hong.hu', log_detail=True)
        msg = scd.main()
        print(msg)
        
    #test_gen_mssql_test_data()
    #test_performance_mssql()
    
    def test_performance_vertica():
        scd = Scd(sql='''UPDATE common.test_columns 
            SET table_schema = table_schema || '1'
            WHERE table_schema like 'test public%' ''', meta=meta, actioner='hong.hu', log_detail=True)
        msg = scd.main()
        print(msg)
        
    #test_gen_vtc_test_data()
    #test_performance_vertica()
    
    def test_vtc_black_space():
        '''
        create table test_black_space_vtc (id int, "first name" varchar(100))
        insert into test_black_space_vtc values(1, 'hong')
        '''
        scd = Scd(sql='''update common.test_black_space_vtc set "first name" = 'aaaa' ''', meta=meta, actioner='hong.hu', log_detail=True)
        msg = scd.main()
        print(msg)
        
    #test_vtc_black_space()   
    
    def test_mssql_black_space():
        '''
        create table test_black_space (id int, "first name" varchar(100))
        insert into test_black_space values(1, 'hong')
        '''
        scd = Scd(sql='''update test_black_space set "first name" = 'aaaa' ''', meta=meta, actioner='hong.hu', log_detail=True)
        msg = scd.main()
        print(msg)
        
    #test_mssql_black_space()  
    
    def test_parse_merge():
        scd = Scd(sql='''merge into common.test_columns test
            using (select 45035997495706786 as table_id) tmp
            on test.table_id = tmp.table_id
            when matched then
              update set table_id=45035997495706786
            when not matched then
              insert(table_id) values(45035997495706786)''', meta=meta, actioner='hong.hu')
        print(scd.locate_keyword_combination('when matched '))
        print(scd.locate_keyword_combination('when not matched '))
        
    def test_nanny():
    
        request_body = {
            "sql": "DELETE FROM AAAA WHERE A=1 AND B=2 and c = 'where'", 
            "actioner": "hong.hu"
        }
        scd = ScdNanny(request_body=request_body, meta=meta)
        print(scd.get_table_name())
        print(scd.get_where_condition())
        
    #test_nanny()
    '''REQUEST BODY
    {
      "sql": "update test_backupfille set logical_name = logical_name + '1' where logical_name like 'HUB_FUNCTION_BETA%' or logical_name like 'HUB_Beta_UAT%' ",
      "actioner": "hong.hu", 
      "log_detail": true, 
      "batch_size": 50, 
      "db_type": "MSSQL", 
      "table_schema": "(COMMON)"
    }
    OR
    [
        {
          "sql": "update osa.dbo.AP_ALERT_CYCLE_DEFINITION set updated_by='test' where cycle_key = 2",
          "actioner": "hong.hu", 
          "log_detail": true, 
          "batch_size": 50, 
          "db_type": "MSSQL", 
          "table_schema": "(COMMON)"
        },  
        {
          "sql": "insert into osa.dbo.AP_ALERT_CYCLE_DEFINITION (cycle_name, alerts_sla_time, alerts_full_eta_time, feedback_cutoff_time, show_old_alerts, ALERTS_AVAILABILITY_WEEKDAYS, status, updated_by, updated_date, time_zone, data_lag) values ('mytest', '0000', NULL, '0000', 'F', 'Thursday', 'D', 'hong.hu', GETDATE(), 'Asia/Shanghai', 1)",
          "actioner": "hong.hu", 
          "log_detail": true, 
          "batch_size": 50, 
          "db_type": "MSSQL", 
          "table_schema": "(COMMON)"
        },  
        {
          "sql": "delete from osa.dbo.AP_ALERT_CYCLE_DEFINITION where cycle_name='mytest'",
          "actioner": "hong.hu", 
          "log_detail": true, 
          "batch_size": 50, 
          "db_type": "MSSQL", 
          "table_schema": "(COMMON)"
        }
    ]
    '''
    scd = ScdApp(meta=meta)
    scd.start_service()
    