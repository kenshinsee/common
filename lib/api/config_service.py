import requests
import cProfile
import json
import os


class Config(object):

    def __init__(self, vendor_key=None, retailer_key=None, hub_id=None, meta={}, 
                 rdp_info=False, rdp_fact_type='fdbk'):
        """
        Get config data from given REST API.
        The REST API url looks like:
        without hub: http://10.172.36.75/config/properties?vendorKey=5&retailerKey=267
        with hub   : http://10.172.36.75/config/properties/HUB_FUNCTION_MB?vendorKey=5&retailerKey=267

        :param vendor_key:
        :param retailer_key:
        :param env: read config from json file
        :param server: we can simply pass the server instead of read from json file. it is having high priority than env.
        :param hub_id: we might have more than 1 hub for the given vendor&retailer.
                        if so: then hub id is required.
                               if no vendor&retailer passed, then only get hub configs
                        else: just simply get the first 1
        :param rdp_info:
        :param rdp_fact_type:
        """
        if 'api_config_str' not in meta:
            raise ValueError('api_config_str is not found.')
            
        self._vendor_key = vendor_key
        self._retailer_key = retailer_key
        self._hub_id = hub_id
        self._rdp_info = rdp_info
        self._rdp_fact_type = rdp_fact_type
        self._host = meta['api_config_str']
        self._url = self._get_rest_url()
        self.json_data = self._get_json_data()
        self._property_dict = self.get_config_data()
        # self._property_dict = self._prepare_data2()


    def _get_rest_url(self):
        # url example1: http://10.172.36.75/config/properties?vendorKey=5&retailerKey=267
        # url example2: http://10.172.36.75/config/properties/HUB_FUNCTION_MB/HUB_FUNCTION_MB
        # url example3: http://10.172.36.75/config/properties/HUB_FUNCTION_MB?vendorKey=5&retailerKey=267
        # url example4: http://10.172.36.75/config/properties/rdps?factType=fdbk
        if self._hub_id:
            if self._vendor_key and self._retailer_key:
                _url = "{host}/properties/{hub}?vendorKey={vendorKey}&retailerKey={retailerKey}"\
                    .format(host=self._host,
                            hub=self._hub_id,
                            vendorKey=self._vendor_key,
                            retailerKey=self._retailer_key)
            else:
                _url = "{host}/properties/{hub}/{hub}".format(host=self._host, hub=self._hub_id)

        elif self._rdp_info and self._rdp_fact_type:
            _url = "{host}/properties/rdps?factType={factType}".format(host=self._host, factType=self._rdp_fact_type)

        else:
            _url = "{host}/properties?vendorKey={vendorKey}&retailerKey={retailerKey}"\
                .format(host=self._host,
                        vendorKey=self._vendor_key,
                        retailerKey=self._retailer_key)
        return _url

    def _get_json_data(self):
        _json_data = requests.get(self._url).json()
        if not _json_data:
            raise IndexError("There is no data returned from given URL, Please help to check: %s" % self._url)

        if self._hub_id:
            _tmp_data = [x for x in _json_data if x["hubId"] == self._hub_id]
            if _tmp_data:
                _result = _tmp_data[0]
            else:
                raise ValueError("ERROR: There is no data for given vendor:%s, retailer:%s, hub_id:%s, check url: %s"
                                 % (self._vendor_key, self._retailer_key, self._hub_id, self._url))
        elif self._rdp_info and self._rdp_fact_type:
            _result = _json_data
        else:
            # print("WARN: There is no hub_id pass, So just simply get the first element of returned data.")
            _result = _json_data[0]

        return _result

    def get_hub_id(self):
        if self._hub_id:
            __hub_id = self._hub_id
        else:
            __hub_id = self.json_data["hubId"]

        return __hub_id

    def get_silo_id(self):
        return self.json_data["siloId"]

    def get_config_data(self):
        # return dict([(x['propertyName'], x['propertyValue']) for x in self.json_data["configs"]])
        if self._rdp_info and self._rdp_fact_type:
            return
        return self.json_data["configs"]

    # option2
    # def _prepare_data2(self):
    #     json_data = requests.get(self._url).json()
    #     name = [x['propertyName'] for x in json_data]
    #     value = [x['propertyValue'] for x in json_data]
    #     return dict(zip(name, value))

    def get_property(self, property_name, default_value=None):
        _result = self._property_dict.get(property_name, default_value)
        if _result is None or _result.strip() == '':
            _result = default_value
        return _result

    def get_bool_property(self, property_name, default_value='False'):
        _tmp = self.get_property(property_name, default_value)
        if _tmp.upper() == 'TRUE' or _tmp.upper() == 'T' or _tmp.upper() == 'Y' or _tmp.upper() == 'YES' or _tmp == '1':
            return True
        else:
            return False


if __name__ == '__main__':

    meta = {'api_capacity_str': 'http://engv3dstr2.eng.rsicorp.local/capacityService', 'api_config_str': 'http://engv3dstr2.eng.rsicorp.local/config', 'db_driver_vertica_odbc': '{HPVerticaDriver}', 'db_driver_vertica_sqlachemy': 'vertica_python', 'db_driver_mssql_odbc': '{ODBC Driver 13 for SQL Server}', 'db_driver_mssql_sqlachemy': 'pymssql', 'db_conn_vertica_servername': 'QAVERTICANXG.ENG.RSICORP.LOCAL', 'db_conn_vertica_port': '5433', 'db_conn_vertica_dbname': 'Fusion', 'db_conn_vertica_username': 'engdeployvtc', 'db_conn_vertica_password': 'egE8eterS9HgycJfxIOZ+w==', 'db_conn_mssql_servername': 'ENGV2HHDBQA1.ENG.RSICORP.LOCAL', 'db_conn_mssql_port': '1433', 'db_conn_mssql_dbname': 'OSA', 'db_conn_mssql_username': 'hong.hu', 'db_conn_mssql_password': 'test666', 'db_conn_redis_servername': '10.172.36.74', 'db_conn_redis_port': '6379', 'db_conn_redis_dbname': '0', 'db_conn_redis_password': '', 'mq_host': '10.172.36.74', 'mq_port': '5672', 'mq_username': 'admin', 'mq_password': 'admin', 'db_conn_vertica_schema_prefix': 'QA_', 'db_conn_vertica_common_schema': 'COMMON'}
 
    # cProfile.run('x = Config()')
    # x = Config('10.172.36.75', '5', '267', hub_id='HUB_FUNCTION_BETA')
    # x = Config('5', '267', env='qa')
    x = Config('5', '267', hub_id='HUB_FUNCTION_BETA', meta=meta)
    print(x._url)
    print(x.get_config_data())
    # cProfile.run("data = x.get_config('ap.alerts.alertSLATime1', '070001')")
    data = x.get_property('ap.alerts.alertSLATime', '070001')
    print(data)

    b1 = x.get_bool_property('rsi.osm.aaJava', 'False')
    b2 = x.get_bool_property('rsi.osm.withRAAT', 'True')
    b3 = x.get_bool_property('deploy.remote.portal.enabled','True')
    print(b1)
    print(b2)
    print(b3)

    print(x.get_hub_id())
    print(x.get_silo_id())

    y = Config(meta=meta, rdp_info=True, rdp_fact_type='fdbk')
    print(y.json_data)
