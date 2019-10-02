
from optparse import OptionParser
import json
from db.db_operation import DWOperation
from log.logger import Logger
import pyodbc
from api.capacity_service import Capacity
import datetime

parse = OptionParser()
parse.add_option("--retailer_key", action="store", dest="retailer_key")
parse.add_option("--vendor_key", action="store", dest="vendor_key")
parse.add_option("--meta", action="store", dest="meta")
(options, args) = parse.parse_args()

meta = json.loads(options.meta)
schema_name = meta['common_schema']

logger = Logger(log_level="info", target="console", vendor_key = options.vendor_key, retailer_key = options.retailer_key)

def populate_incident_key_start(dw, vendor_key, retailer_key):
    head_sql = 'INSERT INTO %s.DIM_INCIDENT_ID_START (VENDOR_KEY, RETAILER_KEY, PERIOD_KEY, INCIDENT_ID_START) ' % schema_name
    
    start_date_str = '20130101'
    start_date_dt = datetime.datetime.strptime(start_date_str, '%Y%m%d')
    end_date_dt = start_date_dt + datetime.timedelta(days=365*100)
    end_date_str = end_date_dt.strftime('%Y%m%d')
    current_date_dt = start_date_dt
    
    vendor_retailer_key = dw.query_scalar('SELECT ID FROM %s.DIM_VENDOR_RETAILER WHERE VENDOR_KEY=%s AND RETAILER_KEY=%s' % (schema_name, vendor_key, retailer_key))
    delta = (int(vendor_retailer_key)-1) * 365 * 100
    i = 0
    body_sqls = []
    while current_date_dt<end_date_dt:
        current_date_str = current_date_dt.strftime('%Y%m%d')
        
        incident_id_start = str(delta + i) + '000000000'
        
        body_sql = 'SELECT %s, %s, %s, %s' % (str(vendor_key), str(retailer_key), str(current_date_str), incident_id_start)
        body_sqls.append(body_sql)
        
        if ((i+1)%500)==0:
            sql = head_sql + ' UNION '.join(body_sqls)
            dw.execute(sql)
            logger.info('%s records for vendor_key=%s, retailer_key=%s have been inserted into %s.DIM_INCIDENT_ID_START' % (str(i+1), vendor_key, retailer_key, schema_name))
            body_sqls = []
            
        i += 1
        current_date_dt = start_date_dt + datetime.timedelta(days=i)
    
    if body_sqls:
        sql = head_sql + ' UNION '.join(body_sqls)
        dw.execute(sql)
    logger.info('Totally %s records for vendor_key=%s, retailer_key=%s have been inserted into %s.DIM_INCIDENT_ID_START' % (str(delta), vendor_key, retailer_key, schema_name))
    
    
    
try:
    dw = DWOperation(meta=meta, logger=logger)

    try:
        check_sql = 'SELECT COUNT(*) FROM %s.DIM_VENDOR_RETAILER WHERE VENDOR_KEY=%s AND RETAILER_KEY=%s' % (schema_name, str(options.vendor_key), str(options.retailer_key))
        count = dw.query_scalar(check_sql)
        if count==0:
            insert_sql = 'INSERT INTO %s.DIM_VENDOR_RETAILER (VENDOR_KEY, RETAILER_KEY) VALUES(%s, %s)' % (schema_name, str(options.vendor_key), str(options.retailer_key))
            dw.execute(insert_sql)
    except pyodbc.ProgrammingError:
        logger.info('%s.DIM_VENDOR_RETAILER doesn''t exist, if you run updateSQL before update' % schema_name)
    logger.info('vendor_key=%s, retailer_key=%s has been inserted into %s.DIM_VENDOR_RETAILER' % (options.vendor_key, options.retailer_key, schema_name))
    
    try:
        check_sql = 'SELECT COUNT(*) FROM %s.DIM_INCIDENT_ID_START WHERE VENDOR_KEY=%s AND RETAILER_KEY=%s' % (schema_name, str(options.vendor_key), str(options.retailer_key))
        count = dw.query_scalar(check_sql)
        if count==0:
            populate_incident_key_start(dw, options.vendor_key, options.retailer_key)
    except pyodbc.ProgrammingError:
        logger.info('%s.DIM_INCIDENT_ID_START doesn''t exist, if you run updateSQL before update' % schema_name)
    logger.info('vendor_key=%s, retailer_key=%s has been inserted into %s.DIM_INCIDENT_ID_START' % (options.vendor_key, options.retailer_key, schema_name))
    
finally:
    dw.close_connection()
    