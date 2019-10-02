# -*- coding: UTF-8 -*-
import os
import subprocess

from common.password import get_password
from db.crypto import Crypto


def sync_data(dct_sync_data):
    """Get data from source to target. If dw_conn_vertica is Ture, it will create connect to vertica to export data
    :param dct_sync_data: The dict need source_config, source_dw, target meta, arget_dw_schema, target_dw_table,
                          target_column, source_sql
    :return:
    """
    dct_sync_data["sep"] = os.path.sep
    dct_sync_data["temp_file_path"] = dct_sync_data["source_config"].get('temp_file_path', '/tmp')
    dct_sync_data["source_dw_server"] = dct_sync_data["source_config"].get('dw.server.name')
    dct_sync_data["source_dw_name"] = dct_sync_data["source_config"].get('dw.db.name')
    dct_sync_data["source_dw_port"] = dct_sync_data["source_config"].get('dw.db.portno', '5433')
    dct_sync_data["source_dw_user"] = dct_sync_data["source_config"].get('dw.etluser.id')
    dct_sync_data["source_dw_password"] = dct_sync_data["source_config"].get('dw.etluser.password')
    dct_sync_data["source_dw_password_decrypt"] = Crypto().decrypt(
        dct_sync_data["source_config"].get('dw.etluser.password'))
    dct_sync_data["source_dw_schema"] = dct_sync_data["source_config"].get("dw.schema.name")
    dct_sync_data["target_dw_server"] = dct_sync_data["db_conn_vertica_servername"]
    dct_sync_data["target_dw_name"] = dct_sync_data["db_conn_vertica_dbname"]
    dct_sync_data["target_dw_port"] = dct_sync_data["db_conn_vertica_port"]
    dct_sync_data["target_dw_user"] = dct_sync_data["db_conn_vertica_username"]
    dct_sync_data["target_dw_password_decrypt"] = get_password(dct_sync_data['db_conn_vertica_username'],
                                                                             dct_sync_data["meta"])
    if dct_sync_data["dw_conn_vertica"]:
        script = (
            "CONNECT TO VERTICA {target_dw_name} USER {target_dw_user} PASSWORD '{target_dw_password_decrypt}' "
            "ON '{target_dw_server}', {target_dw_port}; "
            "EXPORT TO VERTICA {target_dw_name}.{target_dw_schema}.{target_dw_table}({target_column}) "
            "AS {source_sql};"
            "DISCONNECT {target_dw_name}".format(**dct_sync_data))
        dct_sync_data["logger"].debug(script)
        dct_sync_data["source_dw"].execute(script)
    else:
        with open('{temp_file_path}{sep}{source_dw_schema}_{target_dw_table}.sql'.format(**dct_sync_data),
                  'w', encoding='UTF-8') as file:
            file.write(dct_sync_data["source_sql"])
        dct_sync_data["target_column"] = dct_sync_data["target_column"].replace('"', '\\"')
        script = ("vsql -h {source_dw_server} -d {source_dw_name} -p {source_dw_port} "
                  "-U {source_dw_user} -w {source_dw_password_decrypt} -At -F \"|\" "
                  "-f {temp_file_path}{sep}{source_dw_schema}_{target_dw_table}.sql "
                  "| gzip > {temp_file_path}{sep}{source_dw_schema}_{target_dw_table}.gz; "
                  "vsql -h {target_dw_server} -d {target_dw_name} -p {target_dw_port} "
                  "-U {target_dw_user} -w {target_dw_password_decrypt} -c \"COPY "
                  "{target_dw_schema}.{target_dw_table}({target_column}) FROM LOCAL "
                  "'{temp_file_path}{sep}{source_dw_schema}_{target_dw_table}.gz' GZIP "
                  "DELIMITER E'|' NO ESCAPE REJECTMAX 1000 "
                  "REJECTED DATA '{temp_file_path}{sep}{source_dw_schema}_{target_dw_table}.reject' "
                  "EXCEPTIONS '{temp_file_path}{sep}{source_dw_schema}_{target_dw_table}.exception' "
                  "DIRECT STREAM NAME 'GX_OSA_SYNC_DATA_COPYCMD' --enable-connection-load-balance\"; "
                  "".format(**dct_sync_data))
        dct_sync_data["logger"].debug(script)
        result = subprocess.run(script, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            dct_sync_data["logger"].info(
                "{target_dw_schema}.{target_dw_table} data load done".format(**dct_sync_data))
        else:
            err = "Sync data error. {}".format(result.stdout)
            dct_sync_data["logger"].error(err)
            raise Exception(err)
