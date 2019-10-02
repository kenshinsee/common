#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import requests
from common.step_status import StepStatus
from agent.master import MasterHandler
from agent.app import App
from api.capacity_service import Capacity
from upload_to_azure_storage import UploadToBlobStorage
from log.logger import Logger
from db.db_operation import DWOperation, MSOperation
from mq.kafka_producer import Producer


class PacificNotification:
    """
    Check alert generation completeness status for all cycles.
    """

    def __init__(self, context):
        self.context = context
        self.meta = self.context["meta"]
        self._logger = self.context["logger"]
        self._db = MSOperation(meta=self.meta)
        self._dw = DWOperation(meta=self.meta)
        self.bundle_base_url = self.meta["api_osa_bundle_str"]
        self.alert_base_url = self.meta["api_alerts_str"]
        self._common_schema = self.meta["db_conn_vertica_common_schema"]
        self._dim_calendar = "DIM_CALENDAR"
        self._dim_product = "DIM_PRODUCT"
        self._dim_store = "DIM_STORE"
        self._meta_intvn = "ALT_META_INTERVENTION"
        self._dim_base_dir = self.meta["azure_storage_dim_root"]
        self._azure_storage_account_name = self.meta["azure_storage_account_name"]
        self._azure_storage_blob_container = self.meta["azure_storage_blob_container"]
        self._prefix_name = "IRIS_"
        self.azure_uploader = UploadToBlobStorage(meta=self.meta, logger=self._logger)
        self.body = {"job_id": self.context["jobId"], "step_id": self.context["stepId"], "status": StepStatus.RUNNING.name}
        self.capacity = Capacity(meta=self.meta)
        self.cycle_key = self._get_cycle_key()

    def _get_cycle_key(self):
        """
        Getting cycle_key from groupName. groupName format should be like: jobDefId:cycleKey
        :return: cycleKey
        """
        _group_name = str(self.context["groupName"])
        _cycle_key = _group_name.split(":")[1]
        return _cycle_key

    def get_url_response(self, url, method="POST", **kwargs):
        """
        Getting response from url
        :return: resp
        """
        self._logger.info(url)
        if method.upper() not in ["GET", "POST", "PUT"]:
            method = "GET"
        resp = requests.request(method=method, url=url, verify=False, **kwargs)

        self._logger.info(resp.text)
        return resp

    def _dump_dim_data(self, retailer_key):
        """
        Dump dim data into Azure Blob Storage
        This is cycle_key(retailer) level
        :return:
        """
        self._logger.info("Syncing dim tables...")

        # for retailer_key in retailer_list:
        _retailer_name = self.capacity.get_data_by_retailer_key(retailer_key=retailer_key)['retailerName']
        self._logger.info("Uploading 4 tables into Azure blob storage for retailer: %s." % _retailer_name)

        sql_for_item = """
        SELECT VENDOR_KEY, ITEM_KEY, UPC, ITEM_GROUP, item_description AS ITEM_DESC, 
               OSM_BRAND AS BRAND, OSM_CATEGORY AS CATEGORY, OSM_SUB_CATEGORY AS SUBCATEGORY, VENDOR_NAME 
        FROM (SELECT *, ROW_NUMBER() OVER(PARTITION BY VENDOR_KEY, ITEM_KEY) rn
              FROM {schema}.{table} 
        ) x
        WHERE retailer_key = {retailerKey} AND rn = 1""" \
            .format(schema=self._common_schema, table=self._dim_product, retailerKey=retailer_key)

        sql_for_store = """
        SELECT RETAILER_KEY, STORE_KEY, STORE_ID, RETAILER_NAME, OSM_REGION AS REGION,
               RSI_BANNER AS BANNER, PRIME_DC AS DISTRIBUTE_CENTER
        FROM (SELECT *, ROW_NUMBER() OVER(PARTITION BY RETAILER_KEY, STORE_KEY) rn 
              FROM {schema}.{table}
        ) x
        WHERE retailer_key = {retailerKey} AND rn = 1""" \
            .format(schema=self._common_schema, table=self._dim_store, retailerKey=retailer_key)

        sql_for_cal = """
        SELECT PERIOD_KEY, CALENDAR_KEY, CALENDARNAME AS CALENDAR_NAME, YEAR, 
               YEARNAME AS YEAR_NAME, QUARTER, QUARTERNAME AS QUARTER_NAME, MONTH, 
               MONTHNAME AS MONTH_NAME, PERIOD, PERIODNAME AS PERIOD_NAME, WEEKENDED AS WEEK_ENDED, 
               WEEKENDEDNAME AS WEEK_ENDED_NAME, WEEKBEGIN AS WEEK_BEGIN, 
               WEEKBEGINNAME AS WEEK_BEGIN_NAME, YEARWEEKNAME AS YEAR_WEEK_NAME, 
               YEARWEEK AS YEAR_WEEK, YEARMONTHWEEKNAME AS YEAR_MONTH_WEEK_NAME, 
               LY_PERIOD_KEY, NY_PERIOD_KEY, DATE_NAME, TO_CHAR(date_value) AS DATE_VALUE, 
               CAL_PERIOD_KEY, 
               "2ya_period_key" AS _2YA_PERIOD_KEY, 
               "3ya_period_key" AS _3YA_PERIOD_KEY, 
               "4ya_period_key" AS _4YA_PERIOD_KEY 
        FROM {schema}.{table}""".format(schema=self._common_schema, table=self._dim_calendar)

        sql_for_alert = """
        SELECT INTERVENTION_KEY as OSA_TYPE_KEY, INTERVENTION_ENABLED as OSA_TYPE_STATUS, 
               INTERVENTION_NAME as OSA_TYPE_NAME, INTERVENTION_DESC as OSA_TYPE_DESC, 
               CASE WHEN application = 'oos' THEN 1 ELSE 0 END AS OSA_INDICATOR 
        FROM {schema}.{table}""".format(schema=self._common_schema, table=self._meta_intvn)

        self.azure_uploader.upload_azure_main(parq_filename=self._prefix_name + self._dim_product, sql=sql_for_item,
                                              azure_base_dir=_retailer_name + '/' + self._dim_base_dir,
                                              azure_sub_dir="ITEM")
        self.azure_uploader.upload_azure_main(parq_filename=self._prefix_name + self._dim_store, sql=sql_for_store,
                                              azure_base_dir=_retailer_name + '/' + self._dim_base_dir,
                                              azure_sub_dir="STORE")
        self.azure_uploader.upload_azure_main(parq_filename=self._prefix_name + self._dim_calendar, sql=sql_for_cal,
                                              azure_base_dir=_retailer_name + '/' + self._dim_base_dir,
                                              azure_sub_dir="CALENDAR")
        self.azure_uploader.upload_azure_main(parq_filename=self._prefix_name + self._meta_intvn, sql=sql_for_alert,
                                              azure_base_dir=_retailer_name + '/' + self._dim_base_dir,
                                              azure_sub_dir="OSA_CLASSIFICATION")

    def _notify_pacific(self, msg):
        """
        Send message to pacific
        :return:
        """

        self._logger.info("Sending kafka message to Pacific")
        p = Producer(meta=self.meta)
        p.produce_data(msg=msg)
        self._logger.info("Sending kafka message to Pacific completes")

    def process(self):
        """
        main process
        :return:
        """
        try:
            self._logger.info("Data complete Blob getting start")
            self.body["status"] = StepStatus.RUNNING.name
            self.body["message"] = "Dumping dim tables and notify pacific."

            _vendors = self.context["vendors"]  # list
            _retailer_key = self.context["retailerKey"]
            _retailer_name = self.capacity.get_data_by_retailer_key(retailer_key=_retailer_key)['retailerName']
            _data_range = self.context["dateRange"]  # list
            _min_period = min(_data_range)
            _max_period = max(_data_range)

            # dump dim tables to blob storage and then notify pacific
            self._dump_dim_data(_retailer_key)

            _base_azure_url = "wasbs://{}@{}.blob.core.windows.net/".format(self._azure_storage_blob_container, self._azure_storage_account_name)
            _spd_status = {
                "jobId": self.context["jobId"],
                "aggregationType": "OSA",
                "aggregationLevel": "RETAILER",
                "dimBaseUri": _base_azure_url,
                "osaFactBaseUri": _base_azure_url,
                "calendarId": [
                    "2"
                ],
                "retailer": _retailer_name,
                "vendors": _vendors,
                "dateRange": {
                    "startPeriodKey": _min_period,
                    "endPeriodKey": _max_period
                }
            }
            self._logger.info("The message to send to Pacific is: %s" % _spd_status)
            self._notify_pacific(msg=_spd_status)

            # update notify status once sync dim is done.
            _notify_status_api = "{}/availablecycle/rc/status".format(self.alert_base_url)
            rc_ids = self.context["rcId"]  # list
            _request_body = {"payload": []}
            for _rc_id in rc_ids:
                _notified_rc = {
                    "id": _rc_id,
                    "notified": True
                }
                _request_body["payload"].append(_notified_rc)

            self._logger.info("update rc status with request body: %s" % str(_request_body))
            resp = self.get_url_response(url=_notify_status_api, method="PUT", json=_request_body)
            if resp.status_code != requests.codes.ok:
                self._logger.error("Updating notify status failed, Refer to API: %s" % _notify_status_api)

            self.body["status"] = StepStatus.SUCCESS.name
            self.body["message"] = "Done dumped dim tables and notified pacific."

        except Exception as msg:
            self.body["message"] = str(msg)
            self.body["status"] = StepStatus.ERROR.name
            self._logger.error(self.body)


class PacificNotificationNanny(PacificNotification):

    def __init__(self, meta, request_body, logger=None):
        logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1,
                                              module_name="PacificNotificationNanny")
        logger.set_keys(log_id="{}_{}".format(request_body["jobId"], request_body["stepId"]))
        logger.debug(request_body)
        request_body["header"] = {"Content-Type": "application/json", "hour_offset": "-6",
                                  "module_name": logger.format_dict["module_name"]}
        request_body["log_level"] = request_body.get("log_level", 20)
        logger.set_level(request_body["log_level"])

        PacificNotification.__init__(self, {**request_body, **{"meta": meta}, **{"logger": logger}})


class PacificNotificationHandler(MasterHandler):

    def set_service_properties(self):
        self.service_name = 'PacificNotificationNanny'


class PacificNotificationApp(App):
    '''
    This class is just for testing, osa_bundle triggers it somewhere else
    '''

    def __init__(self, meta):
        App.__init__(self, meta=meta, service_bundle_name='PacificNotificationNanny')


if __name__ == "__main__":
    # import configparser
    # from log.logger import Logger
    #
    # with open("{}/../../../config/config.properties".format(sys.argv[0])) as fp:
    #    cp = configparser.ConfigParser()
    #    cp.read_file(fp)
    #    meta = dict(cp.items("DEFAULT"))
    # body = {"jobId": 1234567890, "stepId": 1, "body": "Data complete AG done", "meta": meta}
    # log_file = "{}_{}.log".format(sys.argv[0], body["jobId"])
    # body["meta"]["logger"] = Logger(log_level="INFO", target="console|file", module_name="dc_ag_service",
    #                                log_file=log_file)
    # dc = DCWrapperAG(meta=body["meta"])
    # dc.on_action(body)
    ## d = DataCompleteBlob(body)
    ## d.process()

    '''REQUEST BODY
    POST body like
    {
        "jobId": 1234567890,
        "stepId": 1,
        "batchId": 1,
        "retry": 0,
        "log_level": 10,
        "groupName": "8:7"
    }
    log_level: optional default 20 AS Info, refer logging level
    '''
    import os

    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    exec(open(generic_main_file).read())

    # ************* update services.json --> DataCompleteBlobNanny.service_bundle_name to DataCompleteBlobNanny before running the script
    # app = PacificNotificationApp(meta=meta)
    # app.start_service()
    request_body = {
        "jobId": 1234567890,
        "stepId": 1,
        "batchId": 1,
        "retry": 0,
        "log_level": 10,
        "groupName": "12:69",
        "meta": meta,
        "logger": Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="PacificNotificationNanny"),
        "dateRange": [20180808, 20190806], "retailerKey": 6, "vendors": [342], "rcId": [19]
        # "vendors": [1, 3, 4], "dateRange": [20190101, 20190102], "rcId": [11, 22], "retailerKey": 6
    }
    inst = PacificNotification(context=request_body)
    inst.process()
