from urllib import request
import json
from common.step_status import StepStatus


class JobService(object):
    def __init__(self, meta={}):

        # url example: http://engv3dstr2.eng.rsicorp.local/capacityService/getRetailerByKey?retailerKey=267
        if 'api_job_str' not in meta:
            raise ValueError('api_job_str is not found.')

        api_job_str = meta['api_job_str']
        self.__job_status_url = api_job_str

    def get_job_status(self, jobid, stepid):
        status_url = self.__job_status_url + '/job/jobs/' + str(jobid) + '/steps/' + str(stepid) + '/step'
        # print(status_url)
        response = request.urlopen(status_url)
        data = response.read().decode('utf-8')
        json_data = json.loads(data)
        if str(json_data['status']).upper() != StepStatus.SUCCESS.name:
            print("The response result is: %s" % json_data)
            raise RuntimeError("Calling job status API failed. Refer to API: %s" % status_url)

        return json_data["data"]

    def cancel_job_status(self, jobid, stepid):
        json_data = self.get_job_status(jobid, stepid)
        # if job or step get canceled, then exit.
        if json_data['status'].upper() == StepStatus.CANCEL.name:
            exit(StepStatus.CANCEL.value)


if __name__ == '__main__':
    meta = {'api_capacity_str': 'http://engv3dstr2.eng.rsicorp.local/usermetadata',
            'api_job_str': 'http://engv3dstr2.eng.rsicorp.local/common',
            'api_config_str': 'http://engv3dstr2.eng.rsicorp.local/config',
            'db_driver_vertica_odbc': '{HPVerticaDriver}', 'db_driver_vertica_sqlachemy': 'vertica_python',
            'db_driver_mssql_odbc': '{ODBC Driver 13 for SQL Server}', 'db_driver_mssql_sqlachemy': 'pymssql',
            'db_conn_vertica_servername': 'QAVERTICANXG.ENG.RSICORP.LOCAL', 'db_conn_vertica_port': '5433',
            'db_conn_vertica_dbname': 'Fusion', 'db_conn_vertica_username': 'engdeployvtc',
            'db_conn_vertica_password': 'egE8eterS9HgycJfxIOZ+w==',
            'db_conn_mssql_servername': 'ENGV2HHDBQA1.ENG.RSICORP.LOCAL', 'db_conn_mssql_port': '1433',
            'db_conn_mssql_dbname': 'OSA', 'db_conn_mssql_username': 'hong.hu', 'db_conn_mssql_password': 'test666',
            'db_conn_redis_servername': '10.172.36.74', 'db_conn_redis_port': '6379', 'db_conn_redis_dbname': '0',
            'db_conn_redis_password': '', 'mq_host': '10.172.36.74', 'mq_port': '5672', 'mq_username': 'admin',
            'mq_password': 'admin', 'db_conn_vertica_schema_prefix': 'QA_', 'db_conn_vertica_common_schema': 'COMMON'}

    js = JobService(meta)
    status = js.get_job_status(1234,1)
    print(status)

    js.cancel_job_status(1234, 1)
