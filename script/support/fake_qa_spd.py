from optparse import OptionParser
from db.db_operation import DWOperation
import datetime
import requests
import random

parse = OptionParser()
parse.add_option("--hub_id", action="store", dest="hub_id")
parse.add_option("--silo_id", action="store", dest="silo_id")
parse.add_option("--start_dt", action="store", dest="start_dt", default=None)
parse.add_option("--end_dt", action="store", dest="end_dt", default=None)
(options, args) = parse.parse_args()

#config_service = 'http://engv3dstr2.eng.rsicorp.local/config/properties/%s/%s'%(options.hub_id, options.silo_id)
#config = (requests.get(config_service).json())[0]['configs']
config_service = 'https://adminqa.rsicorp.local/config/properties/%s/%s'%(options.hub_id, options.silo_id)
config = (requests.get(config_service, verify=False).json())[0]['configs']

meta = {}
meta['db_conn_vertica_servername'] = config['dw.server.name']
meta['db_conn_vertica_port'] = config['dw.db.portno']
meta['db_conn_vertica_dbname'] = config['dw.db.name']
meta['db_conn_vertica_username'] = config['dw.user.id']
meta['db_conn_vertica_password'] = config['dw.user.password']
meta['db_conn_vertica_password_encrypted'] = 'True'
meta['db_driver_vertica_odbc'] = '{Vertica}'
meta['db_driver_vertica_sqlachemy'] = 'vertica_python'
schema = config['dw.schema.name']

v = DWOperation(meta=meta)

sql = 'SELECT DISTINCT PERIOD_KEY AS PERIOD_KEY FROM %s.SPD_FACT_PIVOT'%schema
rs = v.query(sql)
period_keys = [r[0] for r in rs]
max_period_key = max(period_keys)
max_period_key_dt = datetime.datetime.strptime(str(max_period_key), "%Y%m%d")

sql_min_period_key = "SELECT MIN(PERIOD_KEY) FROM %s.SPD_FACT_PIVOT"%schema
start_period_key = options.start_dt if options.start_dt else v.query_scalar(sql_min_period_key)
start_period_key_dt = datetime.datetime.strptime(str(start_period_key), "%Y%m%d")
print('Start period key:', start_period_key)

day_count = 30 #fake 30 days after max_period_key
to_be_max_period_key = options.end_dt if options.end_dt else datetime.datetime.strftime(max_period_key_dt + datetime.timedelta(days=day_count), "%Y%m%d")
to_be_max_period_key_dt = datetime.datetime.strptime(str(to_be_max_period_key), "%Y%m%d")
print('End period key:', to_be_max_period_key)

to_be_period_key_dt = start_period_key_dt
while to_be_period_key_dt<=to_be_max_period_key_dt:
	to_be_period_key = datetime.datetime.strftime(to_be_period_key_dt, "%Y%m%d")
	sql = "SELECT COUNT(*) FROM %s.SPD_FACT_PIVOT WHERE PERIOD_KEY='%s'"%(schema, to_be_period_key)
	if v.query_scalar(sql)>0:
		print('No need to fake', to_be_period_key)
		to_be_period_key_dt = to_be_period_key_dt + datetime.timedelta(days=1)
		continue
	rand_period_key = period_keys[random.randint(0, len(period_keys)-1)]
	while rand_period_key==to_be_period_key:
		rand_period_key = period_keys[random.randint(0, len(period_keys)-1)]
	sql = "DROP TABLE IF EXISTS %s.SPD_FACT_PIVOT_TMP"%schema
	v.execute(sql)
	sql = "CREATE TABLE %s.SPD_FACT_PIVOT_TMP AS SELECT * FROM %s.SPD_FACT_PIVOT WHERE PERIOD_KEY = '%s'"%(schema, schema, rand_period_key)
	v.execute(sql)
	sql = "UPDATE %s.SPD_FACT_PIVOT_TMP SET PERIOD_KEY='%s' WHERE PERIOD_KEY='%s'"%(schema, to_be_period_key, rand_period_key)
	v.execute(sql)
	sql = "INSERT INTO %s.SPD_FACT_PIVOT SELECT * FROM %s.SPD_FACT_PIVOT_TMP"%(schema, schema)
	v.execute(sql)
	print('[DONE]', to_be_period_key, 'is being copied from', rand_period_key)
	to_be_period_key_dt = to_be_period_key_dt + datetime.timedelta(days=1)
	
	
v.close_connection()