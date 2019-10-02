
from optparse import OptionParser
import json
from db.db_operation import DWOperation
from log.logger import Logger
import pyodbc

parse = OptionParser()
parse.add_option("--retailer_key", action="store", dest="retailer_key")
parse.add_option("--vendor_key", action="store", dest="vendor_key")
parse.add_option("--meta", action="store", dest="meta")
(options, args) = parse.parse_args()

meta = json.loads(options.meta)

schema_name = meta['schema']
common_schema = meta['common_schema']
#schemas = [common_schema, schema_name]
schemas = [common_schema]

logger = Logger(log_level="info", target="console", vendor_key = options.vendor_key, retailer_key = options.retailer_key)
dw = DWOperation(meta=meta, logger=logger)

try:
    for s in schemas:
        dw.execute('''
CREATE SCHEMA IF NOT EXISTS %(schema_name)s DEFAULT INCLUDE SCHEMA PRIVILEGES;
GRANT USAGE ON SCHEMA %(schema_name)s TO read_internalusers;
GRANT SELECT ON SCHEMA %(schema_name)s TO read_internalusers;
GRANT USAGE ON SCHEMA %(schema_name)s TO write_internalusers;
GRANT SELECT,INSERT,UPDATE,DELETE,TRUNCATE ON SCHEMA %(schema_name)s TO write_internalusers;
        '''%{'schema_name': s})
        logger.info('%s is created, and permission has been granted for read_internalusers and write_internalusers.' % s)
        
        for env in ['uat','pp', 'Prod']:
            try: 
                dw.execute('''
GRANT USAGE ON SCHEMA %(schema_name)s TO %(env)sIRISolapvtc;
GRANT SELECT ON SCHEMA %(schema_name)s TO %(env)sIRISolapvtc;
                '''%{'schema_name': s, 'env': env})
                logger.info('%(schema_name)s permission has been granted for %(env)sIRISolapvtc.'%{'schema_name': s, 'env': env})
            except: 
                logger.info("%(env)sIRISolapvtc doesn't exist."%{'env': env})
            
            try: 
                dw.execute('''
GRANT USAGE ON SCHEMA %(schema_name)s TO %(env)sIRISetlvtc;
GRANT SELECT,INSERT,UPDATE,DELETE,TRUNCATE ON SCHEMA %(schema_name)s TO %(env)sIRISetlvtc;
                '''%{'schema_name': s, 'env': env})
                logger.info('%(schema_name)s permission has been granted for %(env)sIRISetlvtc.'%{'schema_name': s, 'env': env})
            except: 
                logger.info("%(env)sIRISetlvtc doesn't exist."%{'env': env})

finally:
    dw.close_connection()
