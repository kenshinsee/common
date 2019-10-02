from urllib import request
import json


class Capacity():
    def __init__(self, meta={}):
    
        # url example: http://engv3dstr2.eng.rsicorp.local/capacityService/getRetailerByKey?retailerKey=267
        if 'api_capacity_str' not in meta:
            raise ValueError('api_capacity_str is not found.')
        
        api_capacity_str = meta['api_capacity_str']
        self.schema_prefix = meta['db_conn_vertica_schema_prefix']
        self.__url = api_capacity_str

    def get_data_by_retailer_key(self, retailer_key=None):
        # api_name = 'getRetailerByKey'
        # entire_url = self.__url + '/' + api_name + '?retailerKey=' + str(retailer_key)
        entire_url = self.__url + '/retailer/' + str(retailer_key)

        response = request.urlopen(entire_url)
        data = response.read().decode('utf-8')
        json_data = json.loads(data)
        
        return json_data

    def get_retailer_name_by_key(self, retailer_key=None):
        json_data = self.get_data_by_retailer_key(retailer_key)
        return json_data['retailerSname']

    def get_retailer_schema_name(self, retailer_key=None):
        return self.schema_prefix + self.get_retailer_name_by_key(retailer_key)

    def get_data_by_vendor_key(self, vendor_key=None):
        # api_name = 'getVendorByKey'
        # entire_url = self.__url + '/' + api_name + '?vendorKey=' + str(vendor_key)
        entire_url = self.__url + '/vendor/' + str(vendor_key)
        
        response = request.urlopen(entire_url)
        data = response.read().decode('utf-8')
        json_data = json.loads(data)
        
        return json_data

    def get_vendor_name_by_key(self, vendor_key=None):
        json_data = self.get_data_by_vendor_key(vendor_key)
        return json_data['vendorSname']


if __name__ == '__main__':

    # meta = {'api_capacity_str': 'http://engv3dstr2.eng.rsicorp.local/capacityService', 'api_config_str': 'http://engv3dstr2.eng.rsicorp.local/config', 'db_driver_vertica_odbc': '{HPVerticaDriver}', 'db_driver_vertica_sqlachemy': 'vertica_python', 'db_driver_mssql_odbc': '{ODBC Driver 13 for SQL Server}', 'db_driver_mssql_sqlachemy': 'pymssql', 'db_conn_vertica_servername': 'QAVERTICANXG.ENG.RSICORP.LOCAL', 'db_conn_vertica_port': '5433', 'db_conn_vertica_dbname': 'Fusion', 'db_conn_vertica_username': 'engdeployvtc', 'db_conn_vertica_password': 'egE8eterS9HgycJfxIOZ+w==', 'db_conn_mssql_servername': 'ENGV2HHDBQA1.ENG.RSICORP.LOCAL', 'db_conn_mssql_port': '1433', 'db_conn_mssql_dbname': 'OSA', 'db_conn_mssql_username': 'hong.hu', 'db_conn_mssql_password': 'test666', 'db_conn_redis_servername': '10.172.36.74', 'db_conn_redis_port': '6379', 'db_conn_redis_dbname': '0', 'db_conn_redis_password': '', 'mq_host': '10.172.36.74', 'mq_port': '5672', 'mq_username': 'admin', 'mq_password': 'admin', 'db_conn_vertica_schema_prefix': 'QA_', 'db_conn_vertica_common_schema': 'COMMON'}
    meta = {'api_capacity_str': 'http://engv3dstr2.eng.rsicorp.local/usermetadata', 'api_job_str': 'http://engv3dstr2.eng.rsicorp.local/common', 'api_config_str': 'http://engv3dstr2.eng.rsicorp.local/config', 'db_driver_vertica_odbc': '{HPVerticaDriver}', 'db_driver_vertica_sqlachemy': 'vertica_python', 'db_driver_mssql_odbc': '{ODBC Driver 13 for SQL Server}', 'db_driver_mssql_sqlachemy': 'pymssql', 'db_conn_vertica_servername': 'QAVERTICANXG.ENG.RSICORP.LOCAL', 'db_conn_vertica_port': '5433', 'db_conn_vertica_dbname': 'Fusion', 'db_conn_vertica_username': 'engdeployvtc', 'db_conn_vertica_password': 'egE8eterS9HgycJfxIOZ+w==', 'db_conn_mssql_servername': 'ENGV2HHDBQA1.ENG.RSICORP.LOCAL', 'db_conn_mssql_port': '1433', 'db_conn_mssql_dbname': 'OSA', 'db_conn_mssql_username': 'hong.hu', 'db_conn_mssql_password': 'test666', 'db_conn_redis_servername': '10.172.36.74', 'db_conn_redis_port': '6379', 'db_conn_redis_dbname': '0', 'db_conn_redis_password': '', 'mq_host': '10.172.36.74', 'mq_port': '5672', 'mq_username': 'admin', 'mq_password': 'admin', 'db_conn_vertica_schema_prefix': 'QA_', 'db_conn_vertica_common_schema': 'COMMON'}

    cap = Capacity(meta)
    retailer_name = cap.get_retailer_name_by_key(267)
    print(retailer_name)
    schema_name = cap.get_retailer_schema_name(267)
    print(schema_name)
    vendor_name = cap.get_vendor_name_by_key(15)
    print(vendor_name)
