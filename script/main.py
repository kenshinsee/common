#!/usr/bin/python

import os
import sys
from optparse import OptionParser
import configparser

parse = OptionParser()
parse.add_option("--api_capacity_str", action="store", dest="api_capacity_str")
parse.add_option("--api_config_str", action="store", dest="api_config_str")
parse.add_option("--api_job_str", action="store", dest="api_job_str")
parse.add_option("--api_schedule_str", action="store", dest="api_schedule_str")
parse.add_option("--api_osa_bundle_str", action="store", dest="api_osa_bundle_str")
parse.add_option("--api_afm_str", action="store", dest="api_afm_str")
parse.add_option("--api_alerts_str", action="store", dest="api_alerts_str")
parse.add_option("--api_provision_str", action="store", dest="api_provision_str")
parse.add_option("--api_pmp_str", action="store", dest="api_pmp_str")
parse.add_option("--decrypt_key", action="store", dest="decrypt_key")
parse.add_option("--db_driver_vertica_odbc", action="store", dest="db_driver_vertica_odbc")
parse.add_option("--db_driver_vertica_sqlachemy", action="store", dest="db_driver_vertica_sqlachemy")
parse.add_option("--db_driver_mssql_odbc", action="store", dest="db_driver_mssql_odbc")
parse.add_option("--db_driver_mssql_sqlachemy", action="store", dest="db_driver_mssql_sqlachemy")
parse.add_option("--db_conn_token", action="store", dest="db_conn_token")
parse.add_option("--db_conn_vertica_servername", action="store", dest="db_conn_vertica_servername")
parse.add_option("--db_conn_vertica_port", action="store", dest="db_conn_vertica_port")
parse.add_option("--db_conn_vertica_dbname", action="store", dest="db_conn_vertica_dbname")
parse.add_option("--db_conn_vertica_username", action="store", dest="db_conn_vertica_username")
parse.add_option("--db_conn_vertica_common_schema", action="store", dest="db_conn_vertica_common_schema")
parse.add_option("--db_conn_vertica_schema_prefix", action="store", dest="db_conn_vertica_schema_prefix")
parse.add_option("--db_conn_vertica_silo_username", action="store", dest="db_conn_vertica_silo_username")
parse.add_option("--db_conn_mssql_servername", action="store", dest="db_conn_mssql_servername")
parse.add_option("--db_conn_mssql_port", action="store", dest="db_conn_mssql_port")
parse.add_option("--db_conn_mssql_dbname", action="store", dest="db_conn_mssql_dbname")
parse.add_option("--db_conn_mssql_username", action="store", dest="db_conn_mssql_username")
parse.add_option("--db_conn_mssql_schema", action="store", dest="db_conn_mssql_schema")
parse.add_option("--db_conn_mssql_hub_username", action="store", dest="db_conn_mssql_hub_username")
parse.add_option("--db_conn_redis_servername", action="store", dest="db_conn_redis_servername")
parse.add_option("--db_conn_redis_port", action="store", dest="db_conn_redis_port")
parse.add_option("--db_conn_redis_dbname", action="store", dest="db_conn_redis_dbname")
parse.add_option("--db_conn_redis_pmpname", action="store", dest="db_conn_redis_pmpname")
parse.add_option("--mq_host", action="store", dest="mq_host")
parse.add_option("--mq_port", action="store", dest="mq_port")
parse.add_option("--mq_username", action="store", dest="mq_username")
parse.add_option("--mq_pmpname", action="store", dest="mq_pmpname")
parse.add_option("--mq_exchange_name", action="store", dest="mq_exchange_name")
parse.add_option("--mq_exchange_type", action="store", dest="mq_exchange_type")
parse.add_option("--mq_routing_key", action="store", dest="mq_routing_key")
parse.add_option("--mq_queue_name", action="store", dest="mq_queue_name")
parse.add_option("--mq_ca_certs", action="store", dest="mq_ca_certs")
parse.add_option("--mq_key_file", action="store", dest="mq_key_file")
parse.add_option("--mq_cert_file", action="store", dest="mq_cert_file")
parse.add_option("--mq_connection_attempts", action="store", dest="mq_connection_attempts")
parse.add_option("--mq_heartbeat_interval", action="store", dest="mq_heartbeat_interval")
parse.add_option("--mq_agent_exchange_name", action="store", dest="mq_agent_exchange_name")
parse.add_option("--mq_iris_exchange_name", action="store", dest="mq_iris_exchange_name")
parse.add_option("--mq_iris_exchange_type", action="store", dest="mq_iris_exchange_type")
parse.add_option("--mq_iris_feedback_routing_key", action="store", dest="mq_iris_feedback_routing_key")
parse.add_option("--k8s_namespace", action="store", dest="k8s_namespace")
parse.add_option("--tzinfo", action="store", dest="tzinfo")
parse.add_option("--fileshare_username", action="store", dest="fileshare_username")
parse.add_option("--fileshare_folder", action="store", dest="fileshare_folder")
parse.add_option("--extra_args", action="store", dest="extra_args")
parse.add_option("--azure_storage_account_name", action="store", dest="azure_storage_account_name")
parse.add_option("--azure_storage_blob_container", action="store", dest="azure_storage_blob_container")
parse.add_option("--azure_storage_dim_root", action="store", dest="azure_storage_dim_root")
parse.add_option("--kafka_broker", action="store", dest="kafka_broker")
parse.add_option("--kafka_topic", action="store", dest="kafka_topic")
(options, args) = parse.parse_args()

'''
Read properties file, create a dictionary, if parameters are not passed in from CMD, use the values in the properties file
'''
SEP = os.path.sep
cwd = os.path.dirname(os.path.realpath(__file__))
#CONFIG_FILE = cwd + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
if 'CONFIG_FILE' not in locals().keys(): 
    raise ValueError('CONFIG_FILE is not set from parent script.')
if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError(CONFIG_FILE)
config = configparser.ConfigParser()
config.read(CONFIG_FILE)

meta = {}
print('Parameter values.')
for o in options.__dict__:
    if eval('options.%s' % o) == None:
        if o not in config['DEFAULT']:
            meta[o] = None
        else:
            meta[o] = config['DEFAULT'][o]
    else:
        meta[o] = eval('options.%s' % o)
    print('{:<40}={}'.format(o, meta[o]))

# meta is ready to use
