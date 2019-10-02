import os
import pandas as pd
from db.db_operation import DWOperation
from azure.storage.blob import BlockBlobService
from log.logger import Logger
import datetime, time
import glob
import shutil
from api.capacity_service import Capacity
from common.password import get_password


class UploadToBlobStorage(object):
    def __init__(self, meta, logger=None, chuck_size=5000000, time_out=3600):
        """
        :param meta:  Parameters from config file
        :param logger:  logger handler
        :param chuck_size: The chuck size when reading data for Pandas
        :param time_out: time out when uploading data to Azure Storage
        """

        self.meta = meta
        self.account_name = self.meta.get("azure_storage_account_name")
        self.container_name = self.meta.get("azure_storage_blob_container")
        self.logger = logger if logger else Logger(log_level="info", target="console",
                                                   vendor_key=-1, retailer_key=-1, sql_conn=None)

        self.account_key = get_password(username=self.account_name, meta=self.meta)
        self.blob_service = BlockBlobService(self.account_name, self.account_key)
        self.dw_conn = DWOperation(meta=self.meta)

        self.sql = ""
        self.parq_filename = ""
        self.local_path = ""
        self.chuck_size = chuck_size  # 5,000,000 rows as a chuck
        self.time_out = time_out  # time secs

    def upload_azure_main(self, parq_filename, sql, azure_base_dir, azure_sub_dir):
        self.parq_filename = parq_filename
        self._prepare_work()
        self.dump_data_to_parquet(sql)
        self.upload_to_blob_storage(azure_base_dir=azure_base_dir, azure_sub_dir=azure_sub_dir)

    def _prepare_work(self):
        """
        Check if the local dest folder exists: The local dest path should be like: <currdir>/data/20190403/IRIS_DIM_PRODUCT/
        1, if exists, then remove existing dir.
           Meaning this is not the first time run this script for given table & day. That case, we should remove the existing files.
        2, not exists. Then create the folder.
        :return:
        """
        _day = datetime.datetime.now().strftime('%Y%m%d')
        self.local_path = os.path.join(os.path.realpath(os.curdir), "data", _day, self.parq_filename)
        _flag = os.path.exists(self.local_path)
        if _flag:
            shutil.rmtree(self.local_path)
            time.sleep(0.5)   # in case there are many files to be deleted. then below makedirs might fail.

        os.makedirs(self.local_path)

    def dump_data_to_parquet(self, sql):
        self.logger.info("Loading data to Pandas DataFrame from db based on sql: %s" % self.sql)
        file_index = 0
        for df in pd.read_sql(sql=sql, con=self.dw_conn.get_connection(), chunksize=self.chuck_size):
            final_parq_name = "%s-PART-%04d.parquet" % (self.parq_filename, file_index)
            abs_parq_file = os.path.join(self.local_path, final_parq_name)
            self.logger.info("Dumping DataFrame data into parquet file: %s" % abs_parq_file)
            df.to_parquet(abs_parq_file)
            self.logger.info("Done dumping data into file: %s" % abs_parq_file)
            # csv_file = "%s/test-PART-%04d.csv" % (self.local_path, file_index)
            # df.to_csv(csv_file, index=False)
            file_index += 1

    def clear_blobs(self, folder=None):
        """
        Remove all existing files from azure folder.
        :param folder:
        :return:
        """
        blobs = self.blob_service.list_blobs(container_name=self.container_name, prefix=folder)
        for blob in blobs:
            self.logger.info("Deleting blob file: %s from Azure blob storage" % blob.name)
            self.blob_service.delete_blob(container_name=self.container_name, blob_name=blob.name)

    def upload_to_blob_storage(self, azure_base_dir="DIM_DATA", azure_sub_dir=""):
        _azure_dir = azure_base_dir + "/" + azure_sub_dir
        self.logger.info("Started to clear all existing blobs from Azure under given path: %s" % _azure_dir)
        self.clear_blobs(folder=_azure_dir)
        self.logger.info("Done clear all existing blobs.")

        self.logger.info("Start to upload parquet file into Azure Blob Storage")
        for files in glob.glob(os.path.join(self.local_path, '*.parquet')):
            self.logger.info("Uploading blob file: %s" % files)
            self.blob_service.create_blob_from_path(container_name=self.container_name,
                                                    blob_name="{0}/{1}".format(_azure_dir, os.path.basename(files)),  # the sep in Azure is always '/'
                                                    file_path=files,
                                                    timeout=self.time_out)

        self.logger.info("Done uploaded into Azure Blob Storage")


if __name__ == "__main__":
    import os

    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    exec(open(generic_main_file).read())

    _common_schema = "common"
    _dim_product = "DIM_PRODUCT"
    _dim_store = "DIM_STORE"
    _dim_calendar = "DIM_CALENDAR"
    _meta_intvn = "ALT_META_INTERVENTION"
    _dim_base_dir = meta.get("azure_storage_dim_root")
    _prefix_name = "IRIS_"

    _dw_conn = DWOperation(meta=meta)
    # Getting retailer list from dim table
    retailer_list_in_table = []
    _retailer_sql = "SELECT DISTINCT retailer_key FROM {schema}.{table} where retailer_key in (6, 5240)"\
        .format(schema=_common_schema,
                table=_dim_store)
    res = _dw_conn.query(_retailer_sql)
    for ele in res:
        retailer_list_in_table.append(ele.retailer_key)
    print(retailer_list_in_table)

    capacity = Capacity(meta=meta)
    azure_uploader = UploadToBlobStorage(meta=meta)
    # sql_for_item = "SELECT * FROM {schema}.{table}".format(schema=_common_schema, table=_dim_product)
    # sql_for_store = "SELECT * FROM {schema}.{table}".format(schema=_common_schema, table=_dim_store)
    # sql_for_cal = "SELECT * FROM {schema}.{table}".format(schema=_common_schema, table=_dim_calendar)
    # sql_for_alert = "SELECT * FROM {schema}.{table}".format(schema=_common_schema, table=_meta_intvn)

    # retailer_list = [6, 5240]
    retailer_list = retailer_list_in_table

    for retailer_key in retailer_list:
        _retailer_name = capacity.get_data_by_retailer_key(retailer_key=retailer_key)['retailerName']
        print("Uploading 4 tables into Azure blob storage for retailer: %s." % _retailer_name)

        sql_for_item = """
        SELECT VENDOR_KEY, ITEM_KEY, UPC, ITEM_GROUP, item_description AS ITEM_DESC, 
               OSM_BRAND as BRAND, OSM_CATEGORY as CATEGORY, OSM_SUB_CATEGORY as SUBCATEGORY, VENDOR_NAME 
        FROM {schema}.{table}
        WHERE retailer_key = {retailerKey}""" \
            .format(schema=_common_schema, table=_dim_product, retailerKey=retailer_key)
        sql_for_store = """
        SELECT RETAILER_KEY, VENDOR_KEY, STORE_KEY, STORE_ID, RETAILER_NAME, OSM_REGION as REGION
        FROM {schema}.{table}
        WHERE retailer_key = {retailerKey}""" \
            .format(schema=_common_schema, table=_dim_store, retailerKey=retailer_key)
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
        FROM {schema}.{table}""".format(schema=_common_schema, table=_dim_calendar)
        sql_for_alert = """
        SELECT INTERVENTION_KEY as OSA_TYPE_KEY, INTERVENTION_ENABLED as OSA_TYPE_STATUS, 
               INTERVENTION_NAME as OSA_TYPE_NAME, INTERVENTION_DESC as OSA_TYPE_DESC, 
               CASE WHEN application = 'oos' THEN 1 ELSE 0 END AS OSA_INDICATOR 
        FROM {schema}.{table}""".format(schema=_common_schema, table=_meta_intvn)

        azure_uploader.upload_azure_main(parq_filename=_prefix_name + _dim_product, sql=sql_for_item,
                                         azure_base_dir=_retailer_name + '/' + _dim_base_dir,
                                         azure_sub_dir="ITEM")
        azure_uploader.upload_azure_main(parq_filename=_prefix_name + _dim_store, sql=sql_for_store,
                                         azure_base_dir=_retailer_name + '/' + _dim_base_dir,
                                         azure_sub_dir="STORE")
        azure_uploader.upload_azure_main(parq_filename=_prefix_name + _dim_calendar, sql=sql_for_cal,
                                         azure_base_dir=_retailer_name + '/' + _dim_base_dir,
                                         azure_sub_dir="CALENDAR")
        azure_uploader.upload_azure_main(parq_filename=_prefix_name + _meta_intvn, sql=sql_for_alert,
                                         azure_base_dir=_retailer_name + '/' + _dim_base_dir,
                                         azure_sub_dir="OSA_CLASSIFICATION")
