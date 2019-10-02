#!/usr/bin/python

import os
import configparser
import re
import subprocess
import json
import copy
import time
from log.logger import Logger
from io import StringIO
from db.db_operation import MSOperation, RedisOperation, DWOperation
from api.capacity_service import Capacity
from api.config_service import Config
from common.password import get_password
from agent.master import MasterHandler
from agent.app import App
from datetime import datetime
 
class Deploy(object):

    def __init__(self, 
                 meta=None, 
                 retailer_key=None, 
                 vendor_key=None, 
                 db_extra_param=None, 
                 #db_mode='updateSQL',
                 mode='echoRun',
                 logger=None, 
                 exec_folder=[]
                 ):
    
        if not (meta and retailer_key and vendor_key):
            raise ValueError('meta and retailer_key and vendor_key, either of them should not be None.')
        self.cwd = os.path.dirname(os.path.realpath(__file__))
        self.SEP = os.path.sep
        self.liquibase_dir = self.cwd + self.SEP + '..' + self.SEP + 'script' + self.SEP + 'liquibase'
        self.meta = copy.copy(meta)
        self.retailer_key = retailer_key
        self.vendor_key = vendor_key
        self.working_suffix = '.%s.%s' % (self.retailer_key, self.vendor_key)
        self.retailer_suffix = '.%s' % self.retailer_key
        self.capacity = Capacity(meta=meta)
        self.config = configparser.ConfigParser()
        self.common_schema = meta['db_conn_vertica_common_schema']
        self.vertica_schema_prefix = meta['db_conn_vertica_schema_prefix']
        
        self.meta['common_schema'] = self.common_schema
        self.meta['folder_prefix'] = self.vertica_schema_prefix
        
        self.schema = self.get_schema_name()
        self.meta['schema'] = self.schema
        
        self.mode = mode
        self.db_extra_param = db_extra_param if db_extra_param else ''
        modes = {
            'echoRun': {
                'db_mode': 'updateSQL',
                'script_mode': 'skip'
            }, 
            'echoRollback': {
                'db_mode': 'rollbackSQL',
                'script_mode': 'skip'
            }, 
            'run': {
                'db_mode': 'update',
                'script_mode': 'run'
            }, 
            'rollback': {
                'db_mode': 'rollback',
                'script_mode': 'rollback'
            }
        }
        self.db_mode = modes[mode]['db_mode']
        self.script_mode = modes[mode]['script_mode']
                
        self.logger = logger if logger else Logger(log_level="info", vendor_key=vendor_key, retailer_key=retailer_key)
        self.exec_folder = exec_folder
        self.dw = DWOperation(meta=self.meta, logger=self.logger) # move connection creation here in order to fix the outdated password in memory, get_password can return proper password
        self._sql = MSOperation(meta=self.meta, logger=self.logger) # move connection creation here in order to fix the outdated password in memory, get_password can return proper password (the connection will not be used in deploy, just for fixing password purpose)
                
    def get_schema_name(self):
        if not self.retailer_key:
            raise ValueError('retailer_key is None.')
        elif self.retailer_key == -1: # -1 is just for installing common schema (0000.initial/[00_init_common_script|00_init_common_db])
            return self.meta['common_schema'] # liquibase anyway would check this schema and create meta table in it, so it should be an existing schema, actually we do nothing to this schema if -1, -1 is specified
        else:
            return self.capacity.get_retailer_schema_name(self.retailer_key)
    
    def get_sub_folders(self, parent_folder):
        sub_folders = [ parent_folder + self.SEP + f for f in next(os.walk(parent_folder))[1] if not f.endswith('__pycache__')]
        sub_folders.sort()
        return sub_folders
        
    def add_suffix_to_file_name(self, file_name, suffix):
        '''
        file_name: xxxx.xml
        suffix: .1.2
        return: xxxx.1.2.xml
        '''
        path = (self.SEP).join( file_name.split(self.SEP)[0:-1])
        raw_file_name = file_name.split(self.SEP)[-1]
        raw_file_name_without_ext = '.'.join(raw_file_name.split('.')[0:-1])
        ext = raw_file_name.split('.')[-1]
        return path + self.SEP + raw_file_name_without_ext + suffix + '.' + ext
        
    def gen_empty_db_change_log(self, file_name):
        raw_file_name = file_name.split(self.SEP)[-1]
        change_log_file = 'dbchangelog_1_schema.xml'
        if raw_file_name.startswith('app_'):
            change_log_file = 'app_' + change_log_file
        else:
            prefix = '_'.join(raw_file_name.split('_')[0:2])
            change_log_file = prefix + '_' + change_log_file
        with open(file_name, 'w') as f:
            f.write('<?xml version="1.1" encoding="UTF-8" standalone="no"?>\n')
            f.write('<databaseChangeLog xmlns="http://www.liquibase.org/xml/ns/dbchangelog" xmlns:ext="http://www.liquibase.org/xml/ns/dbchangelog-ext" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.liquibase.org/xml/ns/dbchangelog-ext http://www.liquibase.org/xml/ns/dbchangelog/dbchangelog-ext.xsd http://www.liquibase.org/xml/ns/dbchangelog http://www.liquibase.org/xml/ns/dbchangelog/dbchangelog-3.5.xsd">\n')
            if 'master' in file_name: 
                f.write('  <include file="%s"/>\n' % (self.work_dir + self.SEP + change_log_file))
            f.write('</databaseChangeLog>')
            
    def gen_db_property_files(self, db_folder):
        '''
        1. create work_dir under db_folder
        2. create property files under work_dir
           - app property file with suffix
           - dw_common property file with suffix
           - dw_schema property file with suffix
        '''
        self.db_folder = db_folder
        folder_prefix = self.meta['folder_prefix']
        self.work_dir = db_folder + self.SEP + folder_prefix + 'work_dir'
        if not os.path.exists(self.work_dir):
            os.mkdir(self.work_dir)
            
        self.prop_meta = [ {'app_dbchangelog.properties': {
                             'driver': 'com.microsoft.sqlserver.jdbc.SQLServerDriver',
                             'classpath': self.liquibase_dir + self.SEP + 'lib' + self.SEP + 'sqljdbc42.jar',
                             'changeLogFile': 'app_dbchangelog_0_master.xml',
                             'url': 'jdbc:sqlserver://%s:%s;databaseName=%s;integratedSecurity=false' % (self.meta['db_conn_mssql_servername'], 
                                                                                                         self.meta['db_conn_mssql_port'], 
                                                                                                         self.meta['db_conn_mssql_dbname']
                                                                                                        ),
                             'username': self.meta['db_conn_mssql_username'], 
                             'password': get_password(self.meta['db_conn_mssql_username'], meta=self.meta), 
                             'logLevel': 'info'
                         }
                       },
                       {'dw_common_dbchangelog.properties': {
                             'driver': 'com.vertica.jdbc.Driver',
                             'classpath': self.liquibase_dir + self.SEP + 'lib' + self.SEP + 'vertica-jdbc-7.2.1-0.jar',
                             'changeLogFile': 'dw_common_dbchangelog_0_master.xml',
                             'url': 'jdbc:vertica://%s:%s/%s' % (self.meta['db_conn_vertica_servername'], 
                                                                 self.meta['db_conn_vertica_port'], 
                                                                 self.meta['db_conn_vertica_dbname']
                                                                ),
                             'username': self.meta['db_conn_vertica_username'], 
                             'password': get_password(self.meta['db_conn_vertica_username'], meta=self.meta),
                             'logLevel': 'info', 
                             'defaultSchemaName': self.common_schema
                         }
                       },
                       {'dw_schema_dbchangelog.properties': {
                             'driver': 'com.vertica.jdbc.Driver',
                             'classpath': self.liquibase_dir + self.SEP + 'lib' + self.SEP + 'vertica-jdbc-7.2.1-0.jar',
                             'changeLogFile': 'dw_schema_dbchangelog_0_master.xml',
                             'url': 'jdbc:vertica://%s:%s/%s' % (self.meta['db_conn_vertica_servername'], 
                                                                 self.meta['db_conn_vertica_port'], 
                                                                 self.meta['db_conn_vertica_dbname']
                                                                ),
                             'username': self.meta['db_conn_vertica_username'], 
                             'password': get_password(self.meta['db_conn_vertica_username'], meta=self.meta),
                             'logLevel': 'info', 
                             'defaultSchemaName': self.schema
                         }
                       }
                     ]
        
        self.master_src_tgt_mapping = {
            'app_': {
                'source_file': None, 
                'target_file': None, 
            }, 
            'dw_common_': {
                'source_file': None, 
                'target_file': None, 
            }, 
            'dw_schema_': {
                'source_file': None, 
                'target_file': None, 
            }, 
        }
        
        self.file_prefixes = set(['app_' if f.startswith('app_') else '_'.join(f.split('_')[0:2]) for f in os.listdir(db_folder) if os.path.isfile(os.path.join(db_folder,f))]) # file prefixes of the files in db_folder
        
        self.prop_files = []
        for idx, sub_meta in enumerate(self.prop_meta):
            file = list(sub_meta.keys())[0]
            file_prefix = 'app_' if file.startswith('app_') else '_'.join(file.split('_')[0:2])            
            full_file = self.add_suffix_to_file_name(self.work_dir + self.SEP + file, self.working_suffix)
            
            with open(full_file, 'w') as fh:
                m = self.prop_meta[idx][file]
                for prop in m:
                    if prop == 'changeLogFile':
                        for prefix in self.master_src_tgt_mapping:
                            if file.startswith(prefix):
                                self.master_src_tgt_mapping[prefix]['source_file'] = db_folder + self.SEP + m[prop].strip()
                                self.master_src_tgt_mapping[prefix]['target_file'] = self.add_suffix_to_file_name(self.work_dir + self.SEP + m[prop].strip(), self.working_suffix)
                                value = self.master_src_tgt_mapping[prefix]['target_file'].replace('\\', '\\\\') # escape \ for win
                                break
                    else:
                        value = m[prop].strip().replace('\\', '\\\\') # escape \ for win
                    fh.write('%s: %s\n' % (prop, value))
            self.prop_files.append(full_file)
            self.logger.info('Property file: %s is created.' % full_file)
            
    def gen_db_master_change_log(self):
        '''
        get master change log name from property file
        '''
        for prefix in self.master_src_tgt_mapping:
            if self.master_src_tgt_mapping[prefix]['source_file']:
                source_file = self.master_src_tgt_mapping[prefix]['source_file']
                target_file = self.master_src_tgt_mapping[prefix]['target_file']
                if os.path.exists(target_file):
                    self.logger.info('Master file: %s already exists.' % target_file)
                    continue
                
                if os.path.exists(source_file):
                    with open(source_file, 'rt') as in_file:
                        with open(target_file, 'wt') as out_file:
                            content = in_file.read()
                            change_log_files = re.findall(r'file="(.*)"', content)
                            for change_log_file in change_log_files:
                                full_change_log_file = self.work_dir + self.SEP + change_log_file
                                updated_change_log_file = self.add_suffix_to_file_name(full_change_log_file, self.retailer_suffix) if prefix == 'dw_schema_' else full_change_log_file
                                content = content.replace('"%s"' % change_log_file, '"%s"' % updated_change_log_file)
                            out_file.write(content)
                else:
                    self.gen_empty_db_change_log(target_file) # create master file with a change log file which actually is an empty change log file
                self.logger.info('Master file: %s is created.' % target_file)
        
    def gen_db_change_log(self):
        '''
        get change log names from master change log
        '''
        var_in_content = {
            '$(schema)': self.schema, 
            '$(common)': self.common_schema
        }
        for prefix in self.master_src_tgt_mapping:
            master_file = self.master_src_tgt_mapping[prefix]['target_file']
            self.logger.info(master_file)
            with open(master_file) as mf:
                mf_content = mf.read()
                db_change_log_files = re.findall(r'file="(.*)"', mf_content)
                for log_file in db_change_log_files:
                    if os.path.exists(log_file):
                        self.logger.info('Change log file: %s already exists.' % log_file)
                        continue
                        
                    raw_log_name = log_file.split(self.SEP)[-1].replace(self.retailer_suffix, '') # remove working path and suffix if exists
                    full_raw_log_name = self.db_folder + self.SEP + raw_log_name
                    if os.path.exists(full_raw_log_name):
                        with open(full_raw_log_name, 'rt', encoding='utf-8', errors='ignore') as in_file:
                            with open(log_file, 'wt', encoding='utf-8') as out_file:
                                content = in_file.read()
                                for v in var_in_content:
                                    content = content.replace(v, var_in_content[v])
                                out_file.write(content)
                    else:
                        self.gen_empty_db_change_log(log_file)
                    self.logger.info('Change log file: %s is created.' % log_file)
    
    def check_db_tag(self, prop_file, liquibase_script, liquibase_param, insert_tag_value):
        prefix = prop_file.split(self.SEP)[-1]
        if prefix.startswith('app_'):
            check_tag_cmd = '%s %s %s %s' % (liquibase_script, liquibase_param, 'tagExists', insert_tag_value) 
            output = subprocess.run(check_tag_cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            output_str = bytes.decode(output.stderr)
            tag_exists = True if ('The tag %s already exists' % insert_tag_value) in output_str else False
        else: # dw_
            # liquibase tagExists doesn't support vertica, so write the below query to check if tag existence
            with open(prop_file) as f:
                sio = StringIO('[DEFAULT]\n%s' % f.read())
                self.config.read_file(sio)
                schema_name = self.config['DEFAULT']['defaultSchemaName']
                try: 
                    tag_exists = self.dw.query_scalar("SELECT COUNT(*) FROM %s.DATABASECHANGELOG WHERE TAG = '%s'" % (schema_name, insert_tag_value))
                except Exception as e:
                    self.logger.info('%s.DATABASECHANGELOG does not exist, as it\'s the first time run liquibase.' % schema_name)
                    tag_exists = False
                tag_exists = True if tag_exists else False
        return tag_exists
        
    def exec_db(self):
        liquibase_script = self.liquibase_dir + self.SEP + 'liquibase'
        for prop_file in self.prop_files:
            liquibase_param = '--defaultsFile %s %s' % (prop_file, self.db_extra_param)
            
            rollback_modes = ['rollback', 'rollbackToDate', 'rollbackCount', 'rollbackSQL', 'rollbackToDateSQL', 'rollbackCountSQL']
            
            # adding tag
            # tag if not in rollback mode
            if self.db_mode not in rollback_modes: 
                insert_tag_value = (self.SEP).join(self.db_folder.split(self.SEP)[-2:-1]) # release_folder as tag
                self.logger.info('Tag: %s' % insert_tag_value)
                
                tag_exists = self.check_db_tag(prop_file, liquibase_script, liquibase_param, insert_tag_value)
                if tag_exists:
                    self.logger.info(insert_tag_value + ' already exists.')
                else: 
                    self.logger.info(insert_tag_value + ' does not exist, adding tag...')
                    tag_cmd = cmd = '%s %s %s %s' % (liquibase_script, liquibase_param, 'tag', insert_tag_value)
                    self.logger.info('Executing %s' % tag_cmd)
                    subprocess.run(tag_cmd, shell=True, check=True)
                latest_db_tag_value = ''
            else: 
                # it doesn't matter query DATABASECHANGELOG in which db, because the latest tag should be available in all the database DATABASECHANGELOG table, here to get the latest tag from vertica common schema
                # latest_db_tag_value is only for rollback mode
                latest_db_tag_value = self.dw.query_scalar("SELECT TAG FROM (SELECT TAG, ROW_NUMBER() OVER(ORDER BY ORDEREXECUTED DESC) RK FROM %s.DATABASECHANGELOG WHERE TAG IS NOT NULL) T WHERE RK = 1" % self.common_schema) if self.db_mode in rollback_modes else ''
            cmd = '%s %s %s %s' % (liquibase_script, liquibase_param, self.db_mode, latest_db_tag_value)
            self.logger.info('Executing %s' % cmd)
            subprocess.run(cmd, shell=True, check=True)
            
    def exec_script(self, script_folder, is_latest_release):
        try:
            self.logger.info(self.meta)
            json_meta_str = json.dumps(self.meta) # not sure why sometimes it stops here without any error info, so wrap it with try-except for debug purpose
            self.logger.info('Dump json successfully.')
        except Exception as e:
            self.logger.info('Dump json failed.')
            raise e
        self.logger.info('Is latest release: %s' % is_latest_release)
        if self.script_mode == 'skip':
            self.logger.info('Skipping executing scripts as echo mode is specified.')
        elif self.script_mode == 'run': 
            scripts = [ os.path.join(script_folder,f) for f in os.listdir(script_folder) if os.path.isfile(os.path.join(script_folder,f)) and f.endswith('.py')]
            scripts.sort()
            for script in scripts:
                args = ['python', script, '--vendor_key', str(self.vendor_key), '--retailer_key', str(self.retailer_key), '--meta', json_meta_str]
                self.logger.info('Executing %s' % script)
                subprocess.run(args, check=True)
        elif self.script_mode == 'rollback' and is_latest_release: # only can rollback the changes in the latest release
            rollback_folder = 'rollback'
            full_rollback_folder = os.path.join(script_folder, rollback_folder)
            if os.path.exists(full_rollback_folder):
                scripts = [ os.path.join(full_rollback_folder,f) for f in os.listdir(full_rollback_folder) if os.path.isfile(os.path.join(full_rollback_folder,f)) and f.endswith('.py')]
                scripts.sort()
                for script in scripts:
                    args = ['python', script, '--vendor_key', str(self.vendor_key), '--retailer_key', str(self.retailer_key), '--meta', json_meta_str]
                    self.logger.info('Executing %s' % script)
                    subprocess.run(args, check=True)
            else:
                self.logger.info('%s doesn\'t exist.' % full_rollback_folder)
        else:
            self.logger.info('No action for script_mode=%s and is_latest_release=%s' % (self.script_mode, is_latest_release))
        
    def main(self, exec_folder=[]):
        '''
        exec_folder: [] or [''], execute all the scripts under the sub folders of deploy/
        exec_folder: ['0000.init'], execute all the scripts under the sub folers of deploy/0000.init
        exec_folder: ['0000.init', '00_script'], execute all the scripts under deploy/0000.init/00_script
        exec_folder: ['0000.init', '01_db'], execute all the db implementation under deploy/0000.init/01_db
        '''
        release_folders = self.get_sub_folders(self.cwd)
        total_release_count = len(release_folders)
        exec_folder = self.exec_folder if self.exec_folder else exec_folder
        self.logger.info('Specified folder: %s'%self.exec_folder)

        for idx, folder in enumerate(release_folders):
            if len(exec_folder)>=1 and exec_folder[0]!='' and exec_folder[0]!=folder.split(self.SEP)[-1]:
                # exec_folder[0]!='': if we call the url like xxxx/deploy/?vendor_key=xxxx..., it 
                # supports to execute all the sub-folders, actually the exec_folder gets [''], so
                # we should exclude this case.
                self.logger.info('Skipping release folder %s as it\'s not specified.' % folder)
                continue
            self.logger.info('Entering release folder %s' % folder)
            sub_folders = self.get_sub_folders(folder)
            sub_folders.sort()
            is_latest_release = True if total_release_count == (idx+1) else False
            for sub_folder in sub_folders: # process each sub folder
                if len(exec_folder)>=2 and exec_folder[1]!=sub_folder.split(self.SEP)[-1]:
                    self.logger.info('Skipping sub-folder %s as it\'s not specified.' % sub_folder)
                    continue
                self.logger.info('Entering release folder %s' % sub_folder)
                if sub_folder.endswith('_db'): # db schema/data change put in xx_db
                    self.gen_db_property_files(sub_folder)
                    self.gen_db_master_change_log()
                    self.gen_db_change_log()
                    self.exec_db()
                elif sub_folder.endswith('_script'):
                    self.exec_script(sub_folder, is_latest_release)
                else:
                    self.logger.info('Unknown folder %s' % sub_folder)

    def close(self):
        if self.dw:
            self.dw.close_connection()
        if self._sql:
            self._sql.close_connection()
    
    
class DeployNanny(Deploy):

    def __init__(self, meta, request_body, logger=None):
        logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="deployNanny")
        
        if 'vendor_key' in request_body: 
            vendor_key = request_body.get("vendor_key")
        elif 'groupName' in request_body:
            vendor_key = request_body.get("groupName").split(':')[2] # groupName=defid:cyclekey:vendorkey:retailerkey
        else: 
            raise ValueError('No vendor_key specified')
        logger.info("vendor_key: %s" % vendor_key)
        
        if 'retailer_key' in request_body: 
            retailer_key = request_body.get("retailer_key")
        elif 'groupName' in request_body:
            retailer_key = request_body.get("groupName").split(':')[3] # groupName=defid:cyclekey:vendorkey:retailerkey
        else: 
            raise ValueError('No retailer_key specified')
        logger.info("retailer_key: %s" % retailer_key)
        
        db_extra_param = request_body.get("db_extra_param", '')
        mode = request_body.get("mode", "run")
        path = request_body.get("path", "")
        exec_folder = path.split('/')
        logger.info('Final body: %s'%request_body)
        
        Deploy.__init__(self, 
            meta=meta, 
            retailer_key=retailer_key, 
            vendor_key=vendor_key, 
            db_extra_param=db_extra_param, 
            mode=mode,
            logger=logger, 
            exec_folder=exec_folder
        )
    
    
class DeployHandler(MasterHandler):

    def set_service_properties(self):
        self.service_name = 'deployNanny'
        
    def get(self, path): # path here means /path/path2
        self.set_as_not_notifiable()
        params = {
            'vendor_key': self.query_arguments.get('vendor_key'), 
            'retailer_key': self.query_arguments.get('retailer_key'),
            'groupName': self.query_arguments.get('groupName'),
            'db_extra_param': self.query_arguments.get('db_extra_param', ''),
            'mode': self.query_arguments.get('mode', "run")
        }
        if path:
            self.logger.info('Execute path %s only.'%path)
            params['path'] = path
        self.async_main(params)
        msg = '%s - Running %s...'%(datetime.now(), self.service_name)
        self.send_response(msg)
    
    def post(self, path): # path here means /process
        if path.lower()=='process':
            self.async_main(self.request_body)
            msg = '%s - Running %s...'%(datetime.now(), self.service_name)
            self.send_response(msg)
        else:
            raise IndexError('Invalid action: %s'%path)
    
        
class DeployApp(App):
    
    def __init__(self, meta):
        self.meta = meta
        self.redis_key = 'DEPLOY:INITIAL'
        self.redis_conn = (RedisOperation(meta=meta)).get_connection()
        self.main()
        App.__init__(self, meta=meta, service_bundle_name='deploy')
    
    def is_locked(self):
        return True if self.redis_conn.exists(self.redis_key) else False

    def add_lock(self):
        self.redis_conn.hset(self.redis_key, 'create_time', datetime.now())

    def del_lock(self):
        if self.redis_conn.exists(self.redis_key):
            self.redis_conn.delete(self.redis_key)
    
    def get_sub_folders(self, parent_folder):
        sub_folders = [ parent_folder + SEP + f for f in next(os.walk(parent_folder))[1] if not f.endswith('__pycache__')]
        sub_folders.sort()
        return sub_folders
    
    def initial_custom(self):
        print('Start to initial sqlserver db and vertica common schema')
        deploy = Deploy(meta=self.meta, retailer_key=-1, vendor_key=-1, mode='run')
        for release_folder in self.get_sub_folders(cwd):
            for sub_folder in self.get_sub_folders(release_folder):
                raw_release_folder = sub_folder.split(SEP)[-2:][0]
                raw_sub_folder = sub_folder.split(SEP)[-2:][1]
                if 'common'==raw_sub_folder.split('_')[-2:][0]: # execute if xxx_xxx_common_xxx
                    print("Executing %s"%os.path.join(raw_release_folder, raw_sub_folder))
                    deploy.main(exec_folder=[raw_release_folder, raw_sub_folder])
                else:
                    print("Skipping %s as it's not a common folder"%os.path.join(raw_release_folder, raw_sub_folder))
        deploy.close()
        
        print('Start to initial each registed vendor/retailer')
        try: 
            sql = MSOperation(meta=self.meta)
            v_r_pair = sql.query('''SELECT VENDOR_KEY, RETAILER_KEY FROM AP_ALERT_CYCLE_MAPPING
                                    UNION
                                    SELECT VENDOR_KEY, RETAILER_KEY FROM AP_ALERT_CYCLE_RC_MAPPING
                                 ''')
            for p in v_r_pair:
                vendor_key = p.VENDOR_KEY
                retailer_key = p.RETAILER_KEY
                print('--> Initializing vendor=%s retailer=%s...' % (vendor_key, retailer_key))
                try:
                    silo_config = Config(meta=meta, vendor_key=vendor_key, retailer_key=retailer_key).json_data
                except Exception as e:
                    print(e)
                    print('----> vendor=%s retailer=%s is not found in the configuration service, skipping initializing it.' % (vendor_key, retailer_key))
                    continue
                deploy = Deploy(meta=self.meta, retailer_key=retailer_key, vendor_key=vendor_key, mode='run')
                deploy.main()
                deploy.close()
            print('Initialization done.')
        except Exception as e:
            raise
        finally:
            sql.close_connection()
    
    def main(self):
        if self.is_locked(): # only one k8s pod runs the initial_custom
            while self.is_locked():
                print('Initial deployment is locked, waiting 10s...')
                time.sleep(10)
        else:
            try:
                self.add_lock()
                self.initial_custom()
            except Exception as e:
                raise
            finally:
                self.del_lock()
        
    
if __name__ == '__main__':
    '''REQUEST BODY
    {
        "jobId": 8,
        "stepId": 1,
        "batchId": 0,
        "retry": 0,
        "groupName": "1:2:664:5240",
        "path": "0000.initial/00_init_common_script"
    }
    OR
    http://10.171.27.15:8000/deploy/0000.initial/00_init_common_script?retailer_key=5240&vendor_key=664
    '''
    import os
    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + 'script' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    exec(open(generic_main_file).read())
    
    app = DeployApp(meta=meta)   #************* update services.json --> deployNanny.service_bundle_name to deploy before running the script
    app.start_service()

    
    
    