import os
import datetime
import dumpdata as dd
import senddata as sd
import zipfile
import requests
import json
import re
from initialize import Initialize
from api.capacity_service import Capacity
from agent.master import MasterHandler
from db.db_operation import DWOperation
from db.db_operation import MSOperation
from log.logger import Logger
from common.password import get_password


class DumpMain(object):
    def __init__(self, meta, params, logger=None):
        self.meta = meta
        self.params = params
        self.file_ext = self.params.get("fileExt") if self.params.get("fileExt") else "txt"
        self.zip_flag = True if str(self.params.get("zipFlag", "N")).upper() in ["Y", "YES", "T", "TRUE"] else False

        self._debug = "Y" if str(self.params.get('debug', 'N')).upper() in ["Y", "YES", "T", "TRUE"] else 'N'
        __log_level = 'DEBUG' if self._debug == "Y" else 'INFO'
        self.logger = logger if logger else Logger(log_level="info", target="console",
                                                   vendor_key=-1, retailer_key=-1, sql_conn=None)
        self.logger.set_level(log_level=__log_level)
        self.logger.set_keys(log_id="{}".format(self.params["jobId"]))

        self.provision_url = self.meta["api_provision_str"] + "/filesDelivery/layout/attributes?cycle_key="
        self.capacity = Capacity(meta=self.meta)
        self.rsi_username = self.meta.get("fileshare_username")
        self.rsi_folder = self.meta.get("fileshare_folder")
        self.cmn_schema = self.meta.get("db_conn_vertica_common_schema", "common")

        self.app_conn = MSOperation(meta=self.meta)
        self.vertica_conn = DWOperation(meta=self.meta)

        self.dumper_context = self.get_context()
        self._layout_payload = {}

    def main_process(self):
        """
        Getting AFM related parameters. 2 cases here.
        1, called by AFM directly:
           Alerts Delivery is coupled with AFM. So it is better to call by AFM. Then we can get parameters directly from AFM via self.params
        2, called via REST API.
           in case failure when called by AFM, we also support the REST API while we can manually trigger this. And getting params from REST API Body.
        :return:
        """
        try:
            # Checking the cancel status from previous step.
            _cancel_flag = self.params.get("cancel_flag", False)
            if _cancel_flag:
                return self.params.get("message")

            self.logger.debug("The context is: %s" % str(self.dumper_context))
            init = Initialize(self.dumper_context)
            afm_params = init.init_process()
            _cycle_key = afm_params.get("cycleKey")

            _retailer_name = self.capacity.get_retailer_schema_name(retailer_key=afm_params["retailerKey"])
            self.dumper_context["retailer_name"] = _retailer_name
            self.dumper_context["schema"] = _retailer_name
            self.dumper_context["cycle_key"] = _cycle_key

            self._layout_payload = self._get_layout()
            self._process(afm_params)

        except Warning as e:
            return str(e)

        except Exception as e:
            self.logger.warning(str(e))
            raise

    def get_context(self):
        context = {"meta": self.meta,
                   "params": self.params,
                   "dw_conn": self.vertica_conn,
                   "app_conn": self.app_conn,
                   "logger": self.logger}

        return context

    def _get_layout(self):
        # Getting layout fields for alert delivery.
        _cycle_key = self.dumper_context["cycle_key"]
        _delivery_layout_api = "{0}{1}".format(self.provision_url, _cycle_key)

        self.logger.info("Alert delivery related columns(payload param) is not given, "
                         "So just calling provision API: %s to retrieve them." % _delivery_layout_api)
        # _header = {"tokenid": "eyJhbGciOiJIUzI1NiJ9.eyJjb29raWVOYW1lIjoicnNpU3NvTmV4dEdlbiIsImNvb2tpZVZhbHVlIjoiQVFJQzV3TTJMWTRTZmN6ZmRuLVVQazA2b2NnRzVWaTlZRFc1cHZZQzF6b3djbXMuKkFBSlRTUUFDTURFQUFsTkxBQkkyTVRBNU1EUTBPRFUwTXpZeU1UWTBORFlBQWxNeEFBQS4qIiwic3RhdHVzIjoic3VjY2VzcyIsInVzZXJJZCI6ImJlbi53dUByc2ljb3JwLmxvY2FsIiwiaWF0IjoxNTQ0Njg5OTY3fQ.AzCgFFHXHo3J1M4fk-17T8fBLwReDQDb4p-DXUcBm_M"}
        _header = {}
        resp = requests.get(_delivery_layout_api, _header, verify=False)
        if resp.text == "invalid token":
            self.logger.error("ERROR: invalid tokenid, Please update the tokenid manually. "
                              "Then rerun this script again!!!")

        if resp.status_code != requests.codes.ok or str(resp.json().get("status")).lower() != "success":
            self.logger.warning("The response result is: %s" % resp.json())
            self.logger.error("Calling API failed. Refer to API: %s" % _delivery_layout_api)

        # _payload = resp.json()["data"]["payload"]   # e.g. list({"key1":"value1"}, {}, {})
        _payload = resp.json()["data"]

        self.logger.debug("The layout payload is: %s" % _payload)
        return _payload

    def _gen_query(self, delivery_key):
        # getting the payload for given delivery key.
        _payload = self._layout_payload.get(str(delivery_key))["payload"]
        self.logger.debug("The payload is: %s" % str(_payload))

        # only getting data where field preselect is True.
        _payload = list(filter(lambda x: x["preselect"] is True, _payload))
        self.logger.debug("The filtered payload is: %s" % str(_payload))
        if not _payload:
            self.logger.warning("There is no layout configed for this delivery.")
            return None, None

        # It is required to order by seq, so need to convert list(dict) to list(tuple) to sort the data.
        # Otherwise, the following code will not be working correctly.
        # _payload_list should be like: e.g. [(1, 'Alert', 'ALERT_ID', 'ALERT ID', None), (), ...]
        # Noted: Please don't change below fields order for generating _payload_list.
        _payload_list = [(ele["sequence"], ele["dimension_type"], ele["Field"],
                          ele["display_name"], ele["sort_by"]) for ele in _payload]
        self.logger.debug("Converted payload is: %s" % str(_payload_list))

        # Fields should be listed based on sequence. In case seq is None, then putting those columns to the last.
        # if many elements with None value, then they will be sorted randomly.
        _payload_list.sort(key=lambda x: x[0] if x[0] is not None else 999)   # Assuming less than 999 columns.
        self.logger.debug("Sorted payload is: %s" % str(_payload_list))

        display_fields_lst = []  # getting display name like: ["alert type", ...] for displaying on delivery file.
        columns_with_alias = []  # getting fields with format like: [alert."alert_type" as "alert type", ...]
        table_list = set()  # getting required table list. ("Alert", "Store", ...)
        for columns in _payload_list:
            self.logger.debug("Current display name is: \"%s\" for column: %s" % (columns[3], columns[2]))
            table_list.add(str(columns[1]).lower())
            if columns[3] is None:  # display name could be None
                display_fields_lst.append(columns[2])
                columns_with_alias.append(columns[1] + '."' + columns[2] + '" AS "' + columns[2] + '"')
            else:
                display_fields_lst.append(columns[3])
                columns_with_alias.append(columns[1] + '."' + columns[2] + '" AS "' + columns[3] + '"')

        # if there is no "Alert Date" enabled, then manually added this field to the beginning.
        if "Alert Date".lower() not in list(map(lambda x: str(x).lower(), display_fields_lst)):
            display_fields_lst.insert(0, "Alert Date")
            columns_with_alias.insert(0, 'ALERT.period_key AS "Alert Date"')

        _display_fields_str = ",".join(['"' + column + '"' for column in display_fields_lst])  # combine them with comma(,)
        _required_columns_prefix_tmp = ",".join([column for column in columns_with_alias])  # combine them
        # replace one mandatory fields alert_type to intervention_name. Since it is not the column name in fact table.
        _required_columns_prefix = re.sub('(?i)'+re.escape('ALERT."ALERT_TYPE"'),
                                          'type.intervention_name',
                                          _required_columns_prefix_tmp
                                          )

        # Getting columns which sort_by is True(which is enabled sorting). And sort it.
        sort_by_list = sorted(list(filter(lambda x: x[4] is True, _payload_list)), key=lambda x: x[4])
        if sort_by_list:
            _sort_columns = ",".join([ele[1] + '."' + ele[2] + '" DESC NULLS LAST' for ele in sort_by_list])
        else:
            _sort_columns = '1'
        self.logger.debug(_sort_columns)
        _sort_columns = re.sub('(?i)'+re.escape('ALERT."ALERT_TYPE"'),
                               'type.intervention_name',
                               _sort_columns
                               )

        _fdbk_required = True if "feedback" in table_list else False
        _item_required = True if "product" in table_list else False
        _store_required = True   # mandatory

        # Generating the initial query.
        _init_sql = """
        SELECT {columns}, ROW_NUMBER() OVER(ORDER BY store.STORE_ID, {sortedFields} ) AS rn
        FROM {schema}.FACT_PROCESSED_ALERT alert 
        INNER JOIN {cmnSchema}.alt_meta_intervention type 
        ON alert.InterventionKey = type.Intervention_Key """\
            .format(columns=_required_columns_prefix,
                    sortedFields=_sort_columns,
                    schema=self.dumper_context["schema"],
                    cmnSchema=self.cmn_schema)

        if _fdbk_required:
            _init_sql += """
            LEFT JOIN {schema}.FACT_FEEDBACK Feedback 
            ON alert.alert_id = Feedback.alert_id"""\
                .format(schema=self.dumper_context["schema"])

        if _item_required:
            _init_sql += """
            INNER JOIN {cmnSchema}.dim_product Product 
            ON alert.item_key = Product.item_key
            AND alert.vendor_key = Product.vendor_key 
            AND alert.retailer_key = Product.retailer_key"""\
                .format(cmnSchema=self.cmn_schema)

        if _store_required:
            _init_sql += """
            INNER JOIN {cmnSchema}.dim_store Store 
            ON alert.store_key = store.store_key
            AND alert.vendor_key = store.vendor_key 
            AND alert.retailer_key = store.retailer_key"""\
                .format(cmnSchema=self.cmn_schema)

        # always apply the period_key filter for given vendor/retailer
        _init_sql += """
        WHERE 1=1 AND alert.IssuanceId = 0
        AND (alert.vendor_key, alert.retailer_key, alert.period_key) IN 
            ( SELECT vendor_key, retailer_key, alert_day FROM TMP_RAW_ALERTS_INFO )
            """

        return _display_fields_str, _init_sql

    def _process(self, afm_params):
        try:
            _cycle_key = afm_params.get("cycleKey")

            # Reading configuration from meta table under IRIS MSSQL.
            # Getting all owners(includes both SVR & RETAILER rule) according to given cycle_key.
            # the delivery file will be dumped by owner.
            sql = """
            SELECT d.ID AS DELIVERY_KEY, d.CYCLE_KEY, d.RETAILER_KEY, d.DELIVERY_NAME, d.FILTERS, 
                   d.DELIMITER, d.OWNER, ep.SERVER, ep.EXTRACTION_FOLDER, ep.USERNAME, ep.PASSWORD,
                   ep.MAIL_SUBJECT, ep.MAIL_BODY, ep.MAIL_RECPSCC, ep.MAIL_RECPSTO, ep.DELIVERY_TYPE 
            FROM AP_META_DELIVERIES d 
            INNER JOIN AP_META_ENDPOINTS ep
            ON d.ENDPOINT_ID = ep.ID 
            WHERE d.cycle_key = {0}
            AND d.ENABLED = 'T' AND ep.ENABLED = 'T' 
            """.format(_cycle_key)
            self.logger.info(sql)
            meta_rows = self.app_conn.query(sql)
            self.logger.debug("The meta data is: %s" % str(meta_rows))
            if not meta_rows:
                raise Warning("There is no endpoint or delivery configed. Please check meta table!")

            # There could be multi owners for the given cycle but with different filters.
            # This is required by PM. And we need to generate separate files for every single row.
            for meta_data in meta_rows:
                # 1, Getting the initial source query
                _delivery_key = meta_data.DELIVERY_KEY
                required_columns, _init_src_query = self._gen_query(delivery_key=_delivery_key)
                if required_columns is None and _init_src_query is None:
                    self.logger.warning("Seems no layout configed for delivery key: %s" % _delivery_key)
                    continue
                self.logger.info("The initial source query is: %s" % _init_src_query)

                delivery_type = meta_data.DELIVERY_TYPE
                if str.lower(delivery_type) == 'customer':
                    meta_data = meta_data._replace(EXTRACTION_FOLDER=self.rsi_folder, USERNAME=self.rsi_username)

                if meta_data.USERNAME is None:
                    self.logger.warning("There is no username configed for delivery key: %s" % _delivery_key)
                    continue

                _pmp_pwd = get_password(username=meta_data.USERNAME, meta=self.meta)
                if _pmp_pwd:
                    meta_data = meta_data._replace(PASSWORD=_pmp_pwd)

                self.logger.info("Start to dump & delivery for meta: %s" % str(meta_data))
                _src_query = _init_src_query

                # 2, checking if any filters applied. (e.g alert_type, category etc.)
                # User might wants to dump only given alert types of data. This should be configurable.
                # So far, we support 2 types of filters: alert_type & category
                # TODO: confirm the filter format with UI team. Currently filters are configed with json format.
                # e.g. {"alert_type": "d-void,phantom", "category":"cat1,cat2"}
                _filters_raw = meta_data.FILTERS
                if not _filters_raw or _filters_raw == "":
                    self.logger.info("No filters applied.")
                else:
                    self.logger.info("The filters are: %s" % _filters_raw)
                    _filters = json.loads(str(_filters_raw).lower().strip())
                    alert_type_str = _filters.get("alert_type", None)  # e.g. phantom,d-void,shelf oos
                    if alert_type_str is not None and str(alert_type_str).strip() != '':
                        alert_type = ','.join("'" + str(ele).strip() + "'" for ele in str(alert_type_str).split(','))
                        _src_query += " AND type.intervention_name IN ({type})".format(type=alert_type)

                    category_str = _filters.get("category", None)
                    if category_str is not None and str(category_str).strip() != '':
                        category_type = ','.join("'" + str(ele).strip() + "'" for ele in str(category_str).split(','))
                        _src_query += " AND Product.OSM_CATEGORY IN ({cat_type})".format(cat_type=category_type)

                # The owner format should be like: owner1 or owner1,owner2,...
                _owners = str(meta_data.OWNER)
                if not _owners:
                    # owner is the mandatory filter for every delivery.
                    raise ValueError("There is no owner configed in delivery meta table")

                _owner_in_str = ",".join("'" + ele.strip() + "'" for ele in _owners.split(","))
                _src_query += " AND alert.owner IN ({owner}) ".format(owner=_owner_in_str)

                _final_src_query = """
                SELECT {columns} FROM ({query}) x ORDER BY rn
                """.format(columns=required_columns,
                           query=_src_query)

                self.logger.info("The final source sql is: %s" % _final_src_query)

                # delivery file name should be: <delivery_name>_<YYYYMMDD>.<fileExt>. e.g. <delivery_name>_20180101.txt
                curr_folder = os.path.dirname(os.path.realpath(__file__))
                target_filename = meta_data.DELIVERY_NAME + "_" + datetime.datetime.now().strftime('%Y%m%d')

                # delivery file will be dumped to "<curr_dir>/data" folder temporarily.
                abs_target_filename = curr_folder + os.sep + "data" + os.sep + target_filename + '.' + self.file_ext
                zip_filename = curr_folder + os.sep + "data" + os.sep + target_filename + '.zip'

                # Getting data delimiter. e.g. ','
                delimiter = str(meta_data.DELIMITER).strip()
                if len(delimiter) != 1:
                    raise ValueError("delimiter should be 1 char")

                # start to dump data
                self.dumper = dd.DumpData(context=self.dumper_context)

                # dump data from source db
                self.logger.info("Dumping data into file: %s" % abs_target_filename)
                _dump_flag = self.dumper.dump_data(src_sql=_final_src_query,
                                                   output_file=abs_target_filename,
                                                   delimiter=delimiter)
                self.logger.debug("The dump flag is: %s" % _dump_flag)

                # dump alerts succeeded.
                if _dump_flag is True:
                    self.logger.info("Dumping data is done!")

                    # check the zip flag
                    if self.zip_flag:
                        _flat_file_size = round(os.path.getsize(abs_target_filename)/1024/1024)
                        self.logger.debug("The flat file size is: %s" % _flat_file_size)
                        self.logger.info("zipping file: %s" % abs_target_filename)
                        with zipfile.ZipFile(zip_filename, 'w') as z:
                            z.write(abs_target_filename, os.path.basename(abs_target_filename))

                        abs_target_filename = zip_filename
                        self.logger.info("The zip file name is: %s" % abs_target_filename)

                    # start to send data file
                    self.logger.info("Starting uploading delivery file to dest folder!")
                    self.sender = sd.SendData(context=self.dumper_context)
                    self.sender.delivery_file(meta_data=meta_data,
                                              src_file=abs_target_filename)

                else:
                    self.logger.warning("There is no data returned or dump data failed. "
                                        "Please refer to previous log to get the related source query.")

            self.logger.info("Alert delivery process is done")

        except Warning as e:
            raise

        except Exception:
            raise

        finally:
            if self.vertica_conn:
                self.vertica_conn.close_connection()
            if self.app_conn:
                self.app_conn.close_connection()


class DumpNanny(DumpMain):

    def __init__(self, meta, request_body, logger=None):
        logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="dumpAlertsNanny")
        __debug = request_body.get("debug", 'N')
        __log_level = 'DEBUG' if str(__debug).upper() in ('Y', 'YES', 'TRUE', 'T') else 'INFO'
        logger.set_level(log_level=__log_level)
        
        DumpMain.__init__(self, meta={**meta}, params={**request_body}, logger=logger)
    

class DumpHandler(MasterHandler):

    def set_service_properties(self):
        self.service_name = 'dumpAlertsNanny'
        
        
if __name__ == '__main__':
    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    meta = {}
    exec(open(generic_main_file).read())  # fill meta argument

    _params = {"jobId": 54249, "stepId": 1, "batchId": 0, "retry": 0,
               # "groupName": "1:3:342:6",
               "groupName": "6:3",
               # "groupName": "1:2:113:267",
               # "sla_time": "2019-02-27 05:25:00",   # no need sla_time for default
               "sla_time": "2019-03-20 06:25:00",   # no need sla_time for default
               "debug": "Y",
               # below data is just a sample, is not using in code. instead of calling api to get data like below.
               "data": {
                   "1": {"payload": [
                       {
                           "preselect": True,
                           "dimension_type": "Alert",
                           "Field": "ALERT_ID",
                           "display_name": "ALERT ID",
                           "sequence": 1,
                           "sort_by": False
                       },
                       {
                           "preselect": True,
                           "dimension_type": "Alert",
                           "Field": "PERIOD_KEY",
                           "display_name": "ALERT PERIOD",
                           "sequence": 2,
                           "sort_by": False
                       },
                       {
                           "preselect": True,
                           "dimension_type": "Store",
                           "Field": "STORE_ID",
                           "display_name": "STORE",
                           "sequence": 3,
                           "sort_by": False
                       },
                       {
                           "preselect": True,
                           "dimension_type": "Product",
                           "Field": "OSM_MAJOR_CATEGORY",
                           "display_name": "WAG DEPT",
                           "sequence": 4,
                           "sort_by": False
                       },
                       {
                           "preselect": True,
                           "dimension_type": "Alert",
                           "Field": "ExpectedLostSalesAmount",
                           "display_name": "OSM Expected Lost Sales Amount",
                           "sequence": 12,
                           "sort_by": True
                       },
                       {
                           "preselect": True,
                           "dimension_type": "Alert",
                           "Field": "ExpectedLostSalesUnits",
                           "display_name": "OSM Expected Lost Sales Volume Units",
                           "sequence": 13,
                           "sort_by": False
                       }]
                   },
                   "2": {"payload": [{}, {}]},
                   "3": {"payload": [{}, {}]}
               }
               }

    # dump = DumpMain(meta=self.meta, params={**self.params, **{"vertica_conn": self._dw_connection}})
    dump = DumpMain(meta=meta, params=_params)

    dump.main_process()
