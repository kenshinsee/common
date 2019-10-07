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
from db.db_operation import MSOperation, DWOperation
from api.capacity_service import Capacity
from api.config_service import Config
from common.password import get_password
from agent.master import MasterHandler
from agent.app import App
from datetime import datetime
 
class Deploy(object):
    
    def __init__(self, meta=None, request_body=None, logger=None):
        
        self.meta = meta
        self.request_body = request_body
        self.logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="deployMain")
        self.cwd = os.path.dirname(os.path.realpath(__file__))
        self.liquibase_dir = self.path_join(self.cwd, '..', 'script', 'liquibase')
        self.common_schema = meta['db_conn_vertica_common_schema']
        self.vertica_schema_prefix = meta['db_conn_vertica_schema_prefix']
        self.capacity = Capacity(meta=meta)
        
        if 'groupName' in request_body:
            # 1 - 
            # groupName: $def_id:singleton             - is_initial=True, deploy common and each vendor and retailer combination
            # {
            #    "groupName": "9:singleton"
            # }
            # 2 - 
            # groupName: $def_id:singleton:$cycle_key  - is_initial=False, deploy specified vendor and retailer combination only
            # {
            #    "groupName": "9:singleton:10", 
            #    "retailer_key": 11, 
            #    "vendor_key_list": [100, 101, 102], 
            # }
            # based on the above, cycle_key=-1 if is_initial=True
            group_name = request_body.get("groupName")
            group_name_elements = group_name.split(':')
            self.is_initial = True if len(group_name_elements) == 2 else False
            self.cycle_key = group_name_elements[2] if len(group_name_elements) == 3 else -1
        else: 
            raise ValueError('No groupName is specified')
        
                    
    def path_join(self, *args):
        '''
        os.path.join has a bug on Windows, it is not able to add os.sep after root path.
        e.g.
        os.path.join('c:', 'a')
        expected: c:\\a
        actual return: c:a
        '''
        ret = []
        for arg in args:
            ret.append(arg)
        return (os.sep).join(ret)
    
        
    def is_valid_retailer_vendor_combination(self, retailer_key, vendor_key):
        is_valid = True
        try:
            silo_config = Config(meta=self.meta, vendor_key=vendor_key, retailer_key=retailer_key).json_data
        except Exception as e:
            self.logger.warning('vendor=%s retailer=%s is not found in the configuration service, skipping...' % (vendor_key, retailer_key))
            is_valid = False
        return is_valid
        
        
    def get_schema_name(self, retailer_key):
        if not retailer_key:
            raise ValueError('retailer_key is None.')
        elif retailer_key == -1:
            return self.common_schema
        else:
            return self.capacity.get_retailer_schema_name(retailer_key)
        
        
    def get_sub_folders(self, folder):
        sub_folders = [self.path_join(folder, f) for f in next(os.walk(folder))[1] if not f.endswith('__pycache__')]
        sub_folders.sort()
        return sub_folders
        
        
    def get_folder_list(self, deploy_type):
        release_folders = self.get_sub_folders(self.cwd)
        return_folders = []
        for release_folder in release_folders:
            sub_folders = self.get_sub_folders(release_folder)
            for sub_folder in sub_folders:
                if deploy_type == 'common' and (sub_folder.endswith('common_script') or sub_folder.endswith('common_db')): 
                    return_folders.append(sub_folder)
                elif deploy_type == 'retailer' and not (sub_folder.endswith('common_script') or sub_folder.endswith('common_db')): 
                    return_folders.append(sub_folder)
                else:
                    pass
        return return_folders
    
    
    def add_suffix_to_file_name(self, file_name, suffix):
        '''
        file_name: /aa/bb/xxxx.xml
        suffix: -1
        return: /aa/bb/xxxx.-1.xml
        '''
        path = (os.sep).join( file_name.split(os.sep)[0:-1])
        raw_file_name = file_name.split(os.sep)[-1]
        raw_file_name_without_ext = '.'.join(raw_file_name.split('.')[0:-1])
        ext = raw_file_name.split('.')[-1]
        return self.path_join(path, '%s.%s.%s'%(raw_file_name_without_ext, suffix, ext))
        
    
    def remove_suffix_from_file_name(self, file_name, suffix):
        '''
        file_name: /aa/bb/xxxx.-1.xml
        suffix: -1
        return: /aa/bb/xxxx.xml
        '''
        path = self.path_join(*file_name.split(os.sep)[0:-1])
        raw_file_name = file_name.split(os.sep)[-1]
        raw_file_name_ext = raw_file_name.split('.')[-2:-1][0]
        if str(raw_file_name_ext) == str(suffix):
            raw_file_name_without_ext = '.'.join(raw_file_name.split('.')[0:-2])
            ext = raw_file_name.split('.')[-1]
            return self.path_join(path, '%s.%s'%(raw_file_name_without_ext, ext))
        else:
            raise ValueError('Suffix %s is not found in %s'%(suffix, file_name))
        
        
    def gen_db_property_files(self, retailer_key, db_dir, work_dir):
        '''
        1. create property files under work_dir
           - app property file with suffix
           - dw_common property file with suffix
           - dw_schema property file with suffix
        2. retailer_key = -1: deploy common schema, otherwise deploy retailer schema
        '''
        prop_meta = [ {'app_dbchangelog.properties': {
                             'driver': 'com.microsoft.sqlserver.jdbc.SQLServerDriver',
                             'classpath': self.path_join(self.liquibase_dir, 'lib', 'sqljdbc42.jar'),
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
                             'classpath': self.path_join(self.liquibase_dir, 'lib', 'vertica-jdbc-7.2.1-0.jar'),
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
                             'classpath': self.path_join(self.liquibase_dir, 'lib', 'vertica-jdbc-7.2.1-0.jar'),
                             'changeLogFile': 'dw_schema_dbchangelog_0_master.xml',
                             'url': 'jdbc:vertica://%s:%s/%s' % (self.meta['db_conn_vertica_servername'], 
                                                                 self.meta['db_conn_vertica_port'], 
                                                                 self.meta['db_conn_vertica_dbname']
                                                                ),
                             'username': self.meta['db_conn_vertica_username'], 
                             'password': get_password(self.meta['db_conn_vertica_username'], meta=self.meta),
                             'logLevel': 'info', 
                             'defaultSchemaName': self.get_schema_name(retailer_key)
                         }
                       }
                     ]
        
        master_src_tgt_mapping = {
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
                
        prop_files = []
        for idx, sub_meta in enumerate(prop_meta):
            file = list(sub_meta.keys())[0]
            full_file = self.add_suffix_to_file_name(self.path_join(work_dir, file), retailer_key)
            
            with open(full_file, 'w') as fh:
                m = prop_meta[idx][file]
                for prop in m:
                    if prop == 'changeLogFile':
                        for prefix in master_src_tgt_mapping:
                            if file.startswith(prefix):
                                master_src_tgt_mapping[prefix]['source_file'] = self.path_join(db_dir, m[prop].strip())
                                master_src_tgt_mapping[prefix]['target_file'] = self.add_suffix_to_file_name(self.path_join(work_dir, m[prop].strip()), retailer_key)
                                value = master_src_tgt_mapping[prefix]['target_file'].replace('\\', '\\\\') # escape \ for win
                                break
                    else:
                        value = m[prop].strip().replace('\\', '\\\\') # escape \ for win
                    fh.write('%s: %s\n' % (prop, value))
            prop_files.append(full_file)
            self.logger.info('Property file: %s is created.' % full_file)
            
        return (master_src_tgt_mapping, prop_files)
    
        
    def gen_db_master_change_log(self, retailer_key, master_src_tgt_mapping, work_dir):
        '''
        get master change log name from property file
        '''
        for prefix in master_src_tgt_mapping:
            if master_src_tgt_mapping[prefix]['source_file']:
                source_file = master_src_tgt_mapping[prefix]['source_file']
                target_file = master_src_tgt_mapping[prefix]['target_file']
                if os.path.exists(target_file):
                    self.logger.info('Master file: %s already exists.' % target_file)
                    continue
                
                if os.path.exists(source_file):
                    with open(source_file, 'rt') as in_file:
                        with open(target_file, 'wt') as out_file:
                            content = in_file.read()
                            change_log_files = re.findall(r'file="(.*)"', content)
                            for change_log_file in change_log_files:
                                updated_change_log_file = self.add_suffix_to_file_name(self.path_join(work_dir, change_log_file), retailer_key)
                                content = content.replace('"%s"' % change_log_file, '"%s"' % updated_change_log_file)
                            out_file.write(content)
                else:
                    self.gen_empty_db_change_log(target_file, work_dir, retailer_key) # create master file with a change log file which actually is an empty change log file
                self.logger.info('Master file: %s is created.' % target_file)
        
        
    def gen_db_change_log(self, retailer_key, master_src_tgt_mapping, db_dir, work_dir):
        '''
        get change log names from master change log
        '''
        var_in_content = {
            '$(schema)': self.get_schema_name(retailer_key), 
            '$(common)': self.common_schema
        }
        for prefix in master_src_tgt_mapping:
            master_file = master_src_tgt_mapping[prefix]['target_file']
            self.logger.info('Creating changelogfile for %s'%master_file)
            with open(master_file) as mf:
                mf_content = mf.read()
                db_change_log_files = re.findall(r'file="(.*)"', mf_content)
                for log_file in db_change_log_files:
                    if os.path.exists(log_file):
                        self.logger.info('Change log file: %s already exists.' % log_file)
                        continue
                    raw_log_name = self.remove_suffix_from_file_name(log_file, retailer_key).split(os.sep)[-1]
                    full_raw_log_name = self.path_join(db_dir, raw_log_name)
                    if os.path.exists(full_raw_log_name):
                        with open(full_raw_log_name, 'rt', encoding='utf-8', errors='ignore') as in_file:
                            with open(log_file, 'wt', encoding='utf-8') as out_file:
                                content = in_file.read()
                                for v in var_in_content:
                                    content = content.replace(v, var_in_content[v])
                                out_file.write(content)
                    else:
                        self.gen_empty_db_change_log(log_file, work_dir, retailer_key)
                    self.logger.info('Change log file: %s is created.' % log_file)
                    
                    
    def gen_empty_db_change_log(self, file_name, work_dir, retailer_key):
        with open(file_name, 'w') as f:
            f.write('<?xml version="1.1" encoding="UTF-8" standalone="no"?>\n')
            f.write('<databaseChangeLog xmlns="http://www.liquibase.org/xml/ns/dbchangelog" xmlns:ext="http://www.liquibase.org/xml/ns/dbchangelog-ext" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.liquibase.org/xml/ns/dbchangelog-ext http://www.liquibase.org/xml/ns/dbchangelog/dbchangelog-ext.xsd http://www.liquibase.org/xml/ns/dbchangelog http://www.liquibase.org/xml/ns/dbchangelog/dbchangelog-3.5.xsd">\n')
            if 'master' in file_name: 
                raw_file_name = file_name.split(os.sep)[-1]
                change_log_file = 'dbchangelog_1_schema.xml'
                if raw_file_name.startswith('app_'):
                    change_log_file = 'app_' + change_log_file
                else:
                    prefix = '_'.join(raw_file_name.split('_')[0:2])
                    change_log_file = prefix + '_' + change_log_file
                f.write('  <include file="%s"/>\n' % self.add_suffix_to_file_name(self.path_join(work_dir, change_log_file), retailer_key))
            f.write('</databaseChangeLog>')
            

    def exec_db(self, db_dir, retailer_key):
        work_dir = self.path_join(db_dir, self.vertica_schema_prefix + 'work_dir')
        if not os.path.exists(work_dir):
            os.mkdir(work_dir)
        master_src_tgt_mapping, prop_files = self.gen_db_property_files(retailer_key = retailer_key, db_dir = db_dir, work_dir = work_dir)
        self.gen_db_master_change_log(retailer_key = retailer_key, master_src_tgt_mapping = master_src_tgt_mapping, work_dir = work_dir)
        self.gen_db_change_log(retailer_key = retailer_key, master_src_tgt_mapping = master_src_tgt_mapping, db_dir = db_dir, work_dir = work_dir)
                
        liquibase_script = self.path_join(self.liquibase_dir, 'liquibase')
        db_extra_param = ''
        db_mode = 'update'
        for prop_file in prop_files:
            liquibase_param = '--defaultsFile %s %s' % (prop_file, db_extra_param)
            cmd = '%s %s %s' % (liquibase_script, liquibase_param, db_mode)
            self.logger.info('Executing %s' % cmd)
            subprocess.run(cmd, shell=True, check=True)
            
            
    def exec_script(self, script_dir, vendor_key, retailer_key):
        try:
            self.logger.info(self.meta)
            self.meta['schema'] = self.get_schema_name(retailer_key)
            self.meta['common_schema'] = self.common_schema
            json_meta_str = json.dumps(self.meta) # not sure why sometimes it stops here without any error info, so wrap it with try-except for debug purpose
            self.logger.info('Dump json successfully.')
        except Exception as e:
            self.logger.info('Dump json failed.')
            raise e
        
        scripts = [self.path_join(script_dir,f) for f in os.listdir(script_dir) if os.path.isfile(self.path_join(script_dir,f)) and f.endswith('.py')]
        scripts.sort()
        for script in scripts:
            args = ['python', script, '--vendor_key', str(vendor_key), '--retailer_key', str(retailer_key), '--meta', json_meta_str]
            self.logger.info('Executing %s' % script)
            subprocess.run(args, check=True)
    
    
    def main(self):
        try: 
            order_executed = []
            if self.is_initial:
                # initialize common schema
                common_folders = self.get_folder_list(deploy_type='common')
                for common_folder in common_folders:
                    if common_folder.endswith('_db'):
                        self.exec_db(db_dir = common_folder, retailer_key = -1)
                    elif common_folder.endswith('_script'):
                        self.exec_script(script_dir = common_folder, vendor_key = -1, retailer_key = -1)
                    order_executed.append('Initial: %s'%common_folder)
            
            self.retailer_vendor_pair = {}
            if self.is_initial: 
                try: 
                    self._sql = MSOperation(meta=self.meta)
                    v_r_pair = self._sql.query('''SELECT VENDOR_KEY, RETAILER_KEY FROM AP_ALERT_CYCLE_MAPPING
                                                  UNION
                                                  SELECT VENDOR_KEY, RETAILER_KEY FROM AP_ALERT_CYCLE_RC_MAPPING''')
                finally:
                    self._sql.close_connection()
                    
                for p in v_r_pair:
                    if self.is_valid_retailer_vendor_combination(retailer_key = p.RETAILER_KEY, vendor_key = p.VENDOR_KEY):
                        self.retailer_vendor_pair.setdefault(p.RETAILER_KEY, []).append(p.VENDOR_KEY)
            else:
                retailer_key = self.request_body.get("retailer_key")
                vendor_key_list = self.request_body.get("vendor_key_list", [])
                if retailer_key is None or len(vendor_key_list)==0:
                    raise ValueError('retailer_key=%s vendor_key_list=%s must be specified.'%(retailer_key, vendor_key_list))
                for vendor_key in vendor_key_list:
                    if self.is_valid_retailer_vendor_combination(retailer_key = retailer_key, vendor_key = vendor_key):
                        self.retailer_vendor_pair.setdefault(retailer_key, []).append(vendor_key)
            
            self.logger.info('Executing deploy service for %s'%self.retailer_vendor_pair)
            
            folders = self.get_folder_list(deploy_type='retailer')
            for retailer_key in self.retailer_vendor_pair:
                retailer_db_executed = False
                for vendor_key in self.retailer_vendor_pair[retailer_key]:
                    for folder in folders:
                        if folder.endswith('_db') and (not retailer_db_executed): # Just need to execute db schema once for same retailer
                            self.exec_db(db_dir = folder, retailer_key = retailer_key)
                            order_executed.append('Retailer %s: %s'%(retailer_key, folder))
                        elif folder.endswith('_script'):
                            self.exec_script(script_dir = folder, vendor_key = vendor_key, retailer_key = retailer_key)
                            order_executed.append('Retailer %s, vendor %s: %s'%(retailer_key, vendor_key, folder))
                    retailer_db_executed = True
                    
        finally:
            for file in order_executed:
                self.logger.info(file)
        
        
class DeployHandler(MasterHandler):

    def set_service_properties(self):
        self.service_name = 'deploy'
        
    def post(self, path): # path here means /process
        if path.lower()=='process':
            self.async_main(self.request_body)
            msg = '%s - Running %s...'%(datetime.now(), self.service_name)
            self.send_response(msg)
        else:
            raise IndexError('Invalid action: %s'%path)
    
        
class DeployApp(App):
    
    def __init__(self, meta):
        App.__init__(self, meta=meta, service_bundle_name='deploy')
        
    
if __name__ == '__main__':
    '''REQUEST BODY
    # Deploy common and also enrolled retailer and vendor combinations
    {
        "jobId": 8,
        "stepId": 1,
        "batchId": 0,
        "retry": 0,
        "groupName": "9:singleton"
    }
    # Deploy specific retailer and vendors
    {
        "jobId": 8,
        "stepId": 1,
        "batchId": 0,
        "retry": 0,
        "groupName": "9:singleton:2",
        "retailer_key": 6, 
        "vendor_key_list": [300, 342]
    }
    '''
    import os
    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + 'script' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    exec(open(generic_main_file).read())
    
    app = DeployApp(meta=meta)   #************* update services.json --> deployNanny.service_bundle_name to deploy before running the script
    app.start_service()
    
    
    
    