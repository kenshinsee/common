import datetime
import os
import copy
from log.logger import Logger
from db.db_operation import DWOperation
from db.db_operation import MSOperation
from api.capacity_service import Capacity
from api.config_service import Config
from TransferData import TransferData
from common.step_status import StepStatus
from common.password import get_password
from db.crypto import Crypto
from agent.master import MasterHandler
from agent.app import App



class Feedback(object):
    def __init__(self, meta, params=None, init_flag=False, logger=None):
        """
        # sync feedback data from RDP side to IRIS(OSA) side by incremental via event_key.
        # 1, only sync those vendor&retailer which applied OSA Service.
        # 2, for Those new vendor&retailer, copy all historical data when initialization.

        :param meta: [mandatory] config data from config.properties file
        :param params: 2 cases here. depends on whether sync rdp feedback for whole RDP or new customer. see below.
            1, rdp_id: if rdp_id was given, then sync all data for this given RDP. otherwise, sync data from all related RDPs.
               Noted: rdp_id will be passed when calling this service via REST API.
            2, vendor_key:   mandatory only when init_flag is True.
               retailer_key: mandatory only when init_flag is True
               Noted: These 2 parameters will not be passed from REST API but called directly by deploy scripts.
        :param init_flag:
            if init_flag is True: then only sync feedback data for given vendor & retailer. This is used when introducing new customer.
            if init_flat is False: sync all customers' data from RDP periodically(e.g. sync daily).
        :param logger:
        """
        self.meta = meta
        self._params = {} if params is None else params
        self._rdp_id = self._params.get("rdpId", None)
        self._fact_type = 'fdbk'
        self._init_flag = init_flag
        self._vendor_key = self._params.get("vendor_key", None)
        self._retailer_key = self._params.get("retailer_key", None)
        self._debug = self._params.get('debug', 'N')
        self._default_rdp = "RDP_AUX"

        self._log_file = './log/sync_fdbk_%s_%s.log' % (self._rdp_id, datetime.datetime.now().strftime('%Y%m%d'))
        self.logger = logger if logger else Logger(log_level="debug", target="console|file",
                                                   vendor_key=-1, retailer_key=-1,
                                                   log_file=self._log_file, sql_conn=None)

        self.osa_app_conn = MSOperation(meta=self.meta, logger=self.logger)
        self.osa_dw_conn = DWOperation(meta=self.meta, logger=self.logger)
        self.max_event_key = None

        # we already know feedback table name of RDP
        self.source_table_rdp = "DS_FACT_FEEDBACK"         # source table in RDP side.
        self.staging_import_table_osa = "STAGE_FACT_FEEDBACK_RDP"  # used to store sync data from RDP table (same structure as table DS_FACT_FEEDBACK)
        self.target_table_osa = "FACT_FEEDBACK"            # final table in OSA side
        self.capacity = Capacity(meta=meta)

        self.dct_sync_data = copy.deepcopy(self.meta)    # required for calling sync_data module
        self.dct_sync_data["meta"] = self.meta          # required for calling sync_data module
        self.dct_sync_data["target_osa_conn"] = self.osa_dw_conn
        self.dct_sync_data["target_dw_schema"] = self.meta['db_conn_vertica_common_schema']
        self.dct_sync_data["target_dw_table"] = self.staging_import_table_osa
        self.dct_sync_data["logger"] = self.logger

        # [True|False(default)] True: direct connection between Vertica clusters. False: using vsql.
        self.dct_sync_data["dw_conn_vertica"] = False
        # self.dct_sync_data["dw_conn_vertica"] = True

        self.transfer = TransferData(dct_sync_data=self.dct_sync_data)

    def _populate_source_config(self, source_config):
        self.logger.debug("The source config is: %s" % source_config)

        _src_config = {}
        if os.name == 'nt':
            _src_config["temp_file_path"] = "d:"
        elif os.name == 'posix':
            _src_config["temp_file_path"] = "/tmp"

        # Getting user account from config.properties file first.
        if self.meta.get("db_conn_vertica_rdp_username"):
            _src_config["dw.etluser.id"] = self.meta.get("db_conn_vertica_rdp_username")
            if self.meta.get("db_conn_vertica_rdp_password"):
                _src_config["dw.etluser.password"] = self.meta.get("db_conn_vertica_rdp_password")
            else:
                _pmp_pwd = get_password(username=self.meta.get("db_conn_vertica_rdp_username"), meta=self.meta)
                # The pwd should be encrypted in order to: 1, align with else part, 2, pass it to db.sync_data module
                _src_config["dw.etluser.password"] = Crypto().encrypt(_pmp_pwd)
        # if not configed then get them directly from RDP config.
        else:
            _src_config["dw.etluser.id"] = source_config.get("dw.etluser.id")
            # the pwd is encrypted
            _src_config["dw.etluser.password"] = source_config.get("dw.etluser.password")

        # required info for calling sync_data module.
        _src_config["dw.server.name"] = source_config.get("dw.server.name")
        _src_config["dw.db.name"] = source_config.get("dw.db.name")
        _src_config["dw.db.portno"] = source_config.get("dw.db.portno", 5433)
        _src_config["dw.schema.name"] = source_config.get("dw.schema.name")

        self.logger.debug("srouce config is: %s" % _src_config)
        self.dct_sync_data["source_config"] = _src_config

        # Create the connection to RDP Vertica Cluster. which is the source Vertica cluster
        rdp_meta = copy.deepcopy(self.meta)
        tmp_rdp_meta = {'db_conn_vertica_servername': _src_config["dw.server.name"],
                        'db_conn_vertica_port': _src_config["dw.db.portno"],
                        'db_conn_vertica_dbname': _src_config["dw.db.name"],
                        'db_conn_vertica_username': _src_config["dw.etluser.id"],
                        'db_conn_vertica_password': _src_config["dw.etluser.password"],
                        'db_conn_vertica_password_encrypted': "true"
                        }
        rdp_meta.update(tmp_rdp_meta)
        self.logger.debug("rdp config is: %s" % rdp_meta)
        rdp_connection = DWOperation(meta=rdp_meta)
        self.dct_sync_data["source_dw"] = rdp_connection

    def main_process(self):
        try:
            # if not introducing new customer and _rdp_id was given,
            # then we will sync all feedback data from given RDP for registered users.
            if self._init_flag is False and self._rdp_id:
                try:
                    rdp_config = Config(meta=self.meta, hub_id=self._rdp_id).json_data
                    if not rdp_config['configs']:
                        raise Warning("There is no configs returned for RDP: %s."
                                      "Please check if this RDP registered in CP with below URL."
                                      "%s/properties/rdps?factType=fdbk" % (self._rdp_id, self.meta["api_config_str"]))
                        # exit(StepStatus.SUCCESS.value)

                    _rdp_schema = rdp_config['configs'].get('dw.schema.name')
                    self.logger.info("Started to sync data from rdp: %s" % _rdp_schema)

                    # self.dct_sync_data["source_config"] = rdp_config['configs']
                    self._populate_source_config(rdp_config['configs'])

                    self.initialize()

                    _flag = self.load_data()
                    if _flag:
                        # if no data, then no need to process & update variables table.
                        self.process_data()

                        sql = """
                        IF NOT EXISTS(SELECT * FROM VARIABLES WHERE VARIABLE_NAME = '{eventType}')
                            INSERT INTO VARIABLES (VARIABLE_NAME, VARIABLE_VALUE, PREVIOUS_VALUE, INSERT_TIME, UPDATE_TIME)
                            VALUES ('{eventType}', '{value}', '', getdate(), getdate())
                        ELSE
                            UPDATE VARIABLES
                            SET PREVIOUS_VALUE = VARIABLE_VALUE, VARIABLE_VALUE = '{value}',UPDATE_TIME = getdate()
                            WHERE VARIABLE_NAME = '{eventType}'
                        """.format(eventType=_rdp_schema, value=self.max_event_key)
                        self.logger.info(sql)
                        self.osa_app_conn.execute(sql)

                    self.logger.info("Data sync done for RDP: %s" % _rdp_schema)

                except Exception as e:
                    self.logger.warning(e)
                    raise
                    # exit(StepStatus.SUCCESS.value)  # exit(0) otherwise Docker container will fail.

            # Else we will get all RDPs from REST API: http://10.172.36.75/config/properties/rdps?factType=fdbk
            # There could be multi RDPs(e.g. for SVR & WM). if so, loop all RDPs
            elif self._init_flag is False and self._rdp_id is None:
                try:
                    rdp_configs = Config(meta=self.meta, rdp_info=True, rdp_fact_type=self._fact_type).json_data
                    if not rdp_configs:
                        raise Warning("No feedback related RDP found."
                                      "Please check if any data returned from below URL."
                                      "%s/properties/rdps?factType=fdbk" % (self.meta["api_config_str"]))
                        # exit(StepStatus.SUCCESS.value)

                    for rdp_config in rdp_configs:
                        _rdp_schema = rdp_config['configs'].get('dw.schema.name')
                        self.logger.info("Started to sync data from rdp: %s" % _rdp_schema)

                        # self.dct_sync_data["source_config"] = rdp_config['configs']
                        self._populate_source_config(rdp_config['configs'])

                        self.initialize()

                        _flag = self.load_data()
                        if _flag:
                            # if no data, then no need to process & update variables table.
                            self.process_data()

                            sql = """
                            IF NOT EXISTS(SELECT * FROM VARIABLES WHERE VARIABLE_NAME = '{eventType}')
                                INSERT INTO VARIABLES (VARIABLE_NAME, VARIABLE_VALUE, PREVIOUS_VALUE, INSERT_TIME, UPDATE_TIME)
                                VALUES ('{eventType}', '{value}', '', getdate(), getdate())
                            ELSE
                                UPDATE VARIABLES
                                SET PREVIOUS_VALUE = VARIABLE_VALUE, VARIABLE_VALUE = '{value}',UPDATE_TIME = getdate()
                                WHERE VARIABLE_NAME = '{eventType}'
                            """.format(eventType=_rdp_schema, value=self.max_event_key)
                            self.logger.info(sql)
                            self.osa_app_conn.execute(sql)

                        self.logger.info("Data sync done for RDP: %s" % _rdp_schema)

                except Exception as e:
                    self.logger.warning(e)
                    raise

            elif self._init_flag is True:
                if self._vendor_key is None or self._retailer_key is None:
                    self.logger.warning("vendor_key and retailer_key are required when initilize feedback for new customer")
                    raise ValueError

                # getting fdbk related rdps.
                try:
                    rdp_configs = Config(meta=self.meta, rdp_info=True, rdp_fact_type=self._fact_type).json_data
                    if not rdp_configs:
                        self.logger.warning("No feedback related RDP found."
                                            "Please check if any data returned from below URL."
                                            "%s/properties/rdps?factType=fdbk" % (self.meta["api_config_str"]))
                        exit(StepStatus.SUCCESS.value)

                    fdbk_rdps = [str(rdp_config["rdpId"]).upper() for rdp_config in rdp_configs]

                    # change table name in case conflict with normal sync process
                    self.dct_sync_data["target_dw_table"] = "{0}_{1}_{2}".format(self.staging_import_table_osa, self._vendor_key, self._retailer_key)

                    _silo_config = Config(meta=self.meta, vendor_key=self._vendor_key, retailer_key=self._retailer_key).json_data
                    _silo_type = _silo_config['configs'].get('etl.silo.type', 'SVR')
                    _rdp_id = _silo_config['configs'].get('rdp.db.name')

                    # RDP_AUX is default rdp id for feedback etl on PRODUCTION.
                    # 1, if there is no RDP for given silo. then exit.
                    if not _rdp_id or str(_rdp_id).strip() == '':
                        self.logger.warning("There is no RDP silo configed for the given vendor:%s "
                                            "and retailer:%s. So no need to sync feedback."
                                            % (self._vendor_key, self._retailer_key))
                        exit(StepStatus.SUCCESS.value)

                    # 2, Getting configed RDP list, and check if there are feedback related RDPs.
                    _tmp_rdp_lst = str(_rdp_id).upper().split(sep=",")
                    _rdp_lst = [_tmp.strip() for _tmp in _tmp_rdp_lst]
                    # common_rdps is RDP silo configed for syncing feedback data for given silo(vendor&retailer)
                    common_rdps = list(set(_rdp_lst).intersection(fdbk_rdps))
                    if common_rdps is None:
                        self.logger.warning("There is no RDP silo configed for the given vendor:%s "
                                            "and retailer:%s. So no need to sync feedback."
                                            % (self._vendor_key, self._retailer_key))
                        exit(StepStatus.SUCCESS.value)

                    # If there is 1 or more than 1 feedback related rdps configed, then loop them to sync feedback data,
                    # Normally, there should be only 1. or no feedback rdp configed.
                    for common_rdp in common_rdps:
                        _rdp_id = common_rdp
                        self.logger.info("Started to sync data from rdp: %s for given vendor:%s and retailer:%s. "
                                         % (_rdp_id, self._vendor_key, self._retailer_key))

                        # if RDP is not RDP_AUX, Won't exit but log a warning.
                        if _rdp_id != self._default_rdp:
                            self.logger.warning("Please be noted: The RDP is:%s. It is not RDP_AUX." % _rdp_id)

                        # WM silos are also following above logic.
                        # all hosted silo are ultilizing RDP_AUX to transfer feedback data. not sure about Walmart.
                        # if str(_silo_type).upper() in ["WMSSC", "WMCAT", "SASSC", "WMINTL"]:
                        #     _rdp_id = self._default_rdp  # WM rdp is RDP_AUX as well?

                        rdp_config = Config(meta=self.meta, hub_id=_rdp_id).json_data
                        if not rdp_config['configs']:
                            self.logger.warning("There is no configs for RDP: %s. Please check following URL:"
                                                "%s/properties/%s/%s" % (_rdp_id, self.meta["api_config_str"], _rdp_id, _rdp_id) )
                            exit(StepStatus.SUCCESS.value)

                        _rdp_schema = rdp_config['configs'].get('dw.schema.name')
                        self.logger.info("Started to init feedback data from rdp: %s for "
                                         "given vendor:%s and retailer:%s " % (_rdp_schema, self._vendor_key, self._retailer_key))

                        # self.dct_sync_data["source_config"] = rdp_config['configs']
                        self._populate_source_config(rdp_config['configs'])

                        self.initialize()

                        _flag = self.load_data()
                        if _flag:
                            # if no data, then no need to process.
                            self.process_data()

                        self.logger.info("Data sync done for RDP: %s" % _rdp_id)

                except Exception as e:
                    self.logger.warning(e)
                    self.logger.warning("Please check if any warning or error messages when doing the initialization!")

        finally:
            if self.osa_app_conn:
                self.osa_app_conn.close_connection()
            if self.osa_dw_conn:
                self.osa_dw_conn.close_connection()

    def initialize(self):
        """
        Create local temp tables , and DDLs required to process this fact type
        :return:
        """
        self.logger.info("Initialize...")

        # recreate this table for every RDP. no need to truncate any longer.
        # sql = "TRUNCATE TABLE {cmnSchema}.{targetTable}"\
        #     .format(cmnSchema=self.dct_sync_data["target_dw_schema"], targetTable=self.staging_import_table_osa)
        # self.logger.info(sql)
        # self.osa_dw.execute(sql)

        sql = """
        --Store data from RDP table.
        DROP TABLE IF EXISTS {cmnSchema}.{importTable};
        CREATE TABLE {cmnSchema}.{importTable}
        (
            EVENT_KEY int NOT NULL,
            RETAILER_KEY int,
            VENDOR_KEY int,
            STORE_VISIT_DATE date,
            PERIOD_KEY int NOT NULL,
            TYPE varchar(1),
            TYPE_DATE varchar(10),
            ALERT_ID int,
            ALERT_TYPE varchar(64),
            MERCHANDISER_STORE_NUMBER varchar(512),
            STORE_ID varchar(512),
            MERCHANDISER_UPC varchar(512),
            INNER_UPC varchar(512),
            MERCHANDISER varchar(100),
            STORE_REP varchar(1000),
            SOURCE varchar(1000),
            BEGIN_STATUS varchar(255),
            ACTION varchar(255),
            FEEDBACK_DESCRIPTION varchar(255),
            FEEDBACK_HOTLINEREPORTDATE date,
            FEEDBACK_ISININVENTORY varchar(5),
            ZIP_CODE varchar(64),
            ARTS_CHAIN_NAME varchar(255),
            UPC_STATUS varchar(255),
            MSI varchar(255)
        )
        UNSEGMENTED ALL NODES;
        """.format(cmnSchema=self.dct_sync_data["target_dw_schema"],
                   importTable=self.dct_sync_data["target_dw_table"])
        self.logger.info(sql)
        self.osa_dw_conn.execute(sql)

    def load_data(self):
        """
        # Load data from RDP table ds_fact_feedback to local temp tables.
        There is an column event_key which is incremental for all customers in ds_fact_feedback table.
        we can save the snapshot of this column to variable table, and do the incremental every time based on this column.
        There are few cases here:
        1, Routinely, There will be a scheduled job to sync the whole feedback data for valid customers from related RDP silo.
           And save the snapshot of the event_key from previous loading for next incremental loading.
        2, if on-boarding a new vendor & retailer customer. Getting rdp_event_key from variable for related RDP silo. (rdp_event_key is from previous loading)
           and then sync feedback data from related RDP silo only for this given customer when event_key < rdp_event_key.
           Then case1 will take care the rest of feedback data.
        :return:
        """
        rdp_schema = self.dct_sync_data["source_config"].get('dw.schema.name')

        # rdp_aux.ds_fact_feedback
        source_table = "{rdpSchema}.{rdptableName}"\
            .format(rdpSchema=rdp_schema,
                    rdptableName=self.source_table_rdp)
        # common.stage_fact_feedback_rdp
        target_table = "{dwSchema}.{importTable}"\
            .format(dwSchema=self.dct_sync_data["target_dw_schema"],
                    importTable=self.dct_sync_data["target_dw_table"])

        self.logger.info("Ready to load Data from {srouceTable} to {targetTable}"
                         .format(targetTable=target_table,
                                 srouceTable=source_table))

        insert_columns = " EVENT_KEY, RETAILER_KEY, VENDOR_KEY, STORE_VISIT_DATE, PERIOD_KEY, TYPE, TYPE_DATE," \
                         " ALERT_ID, ALERT_TYPE, MERCHANDISER_STORE_NUMBER, STORE_ID, MERCHANDISER_UPC, INNER_UPC," \
                         " MERCHANDISER, STORE_REP, SOURCE, BEGIN_STATUS, ACTION, FEEDBACK_DESCRIPTION," \
                         " FEEDBACK_HOTLINEREPORTDATE, FEEDBACK_ISININVENTORY, ZIP_CODE, ARTS_CHAIN_NAME, UPC_STATUS, MSI "

        try:
            self.logger.info("Getting the previous Event_key from last run for incremental load.")
            _event_sql = "SELECT VARIABLE_VALUE FROM variables " \
                         "WHERE VARIABLE_NAME = '{rdpName}'".format(rdpName=rdp_schema)
            self.logger.info(_event_sql)
            event_key = self.osa_app_conn.query_scalar(_event_sql)

            self.logger.info("Getting customer info which only applied OSA services as filter")
            sql = "SELECT DISTINCT retailer_key, vendor_key FROM AP_ALERT_CYCLE_MAPPING " \
                  "UNION " \
                  "SELECT DISTINCT retailer_key, vendor_key FROM AP_ALERT_CYCLE_RC_MAPPING"
            self.logger.info(sql)
            results = self.osa_app_conn.query(sql)
            if not results:
                raise Warning("There is no data in table AP_ALERT_CYCLE_MAPPING. Please check sql: %s" % sql)
                # exit(StepStatus.SUCCESS.value)

            user_filters = ['SELECT ' + str(result.retailer_key) + ',' + str(result.vendor_key) for result in results]
            user_filter_str = ' UNION ALL '.join(user_filters)
            self.logger.info("Customer filters are: %s" % user_filter_str)

            # incremental filter from RDP table
            where_sql = "EVENT_KEY > {eventKey} AND SOURCE != 'ARIA' " \
                        "AND (RETAILER_KEY, VENDOR_KEY) in ({userFilter})"\
                .format(eventKey=event_key,
                        userFilter=user_filter_str)

            # TODO2DONE: how to set default value? use -1
            # copy all if there is no value in variables table.
            if not event_key:
                self.logger.warning("There is no value set in variables table for RDP:{name}, "
                                    "So copy the whole table".format(name=rdp_schema))
                where_sql = " SOURCE != 'ARIA' AND (RETAILER_KEY, VENDOR_KEY) in ({userFilter})"\
                    .format(eventKey=event_key,
                            userFilter=user_filter_str)
                event_key = -1  # check if this is the first run.

            if self._init_flag is True:
                if event_key == -1:  # event_key is None
                    self.logger.warning("There is no event_key logged in variables table for the given RDP: %s."
                                        "So Let's wait for the routine job to sync the whole rdp feedback data"
                                        % rdp_schema)
                    return False

                self.logger.info("Generating init feedback filters")
                where_sql = "EVENT_KEY <= {eventKey} AND SOURCE != 'ARIA' " \
                            "AND (RETAILER_KEY, VENDOR_KEY) in ({userFilter}) " \
                            "AND RETAILER_KEY={retailerKey} AND VENDOR_KEY={vendorKey} "\
                    .format(eventKey=event_key,
                            userFilter=user_filter_str,
                            retailerKey=self._retailer_key,
                            vendorKey=self._vendor_key)

            self.logger.debug("The filters are: %s" % where_sql)

            # form the fetch query from RDP and then Insert into the target table
            fetch_query = """
            SELECT /*+ label(GX_IRIS_SYNCFEEDBACK)*/ {insertQuery} FROM {sourceTable}
            WHERE {whereSql}
            """.format(insertQuery=insert_columns,
                       sourceTable=source_table,
                       whereSql=where_sql)
            self.logger.info("fetch_query is : %s" % fetch_query)

            self.logger.info(">>Loading {factType} Data from event_key:{eventKey} start at: {timestamp}<<"
                             .format(factType=self._fact_type, eventKey=event_key, timestamp=datetime.datetime.now()))

            self.dct_sync_data["target_column"] = insert_columns
            self.dct_sync_data["source_sql"] = fetch_query

            row_count = self.transfer.transfer_data(dct_sync_data=self.dct_sync_data)

            self.logger.info(">>Done loaded {cnt} rows from event_key:{eventKey} completed at: {timestamp}<<"
                             .format(cnt=row_count,
                                     factType=self._fact_type,
                                     eventKey=event_key, timestamp=datetime.datetime.now())
                             )

            # if no data transfered, then update variables with previous value.
            sql = "SELECT /*+ label(GX_IRIS_SYNCFEEDBACK)*/ nvl(max(event_key), {oldEventKey}) " \
                  "FROM {schemaName}.{importTable} "\
                .format(schemaName=self.dct_sync_data["target_dw_schema"],
                        importTable=self.dct_sync_data["target_dw_table"],
                        oldEventKey=event_key)
            self.logger.info(sql)
            self.max_event_key = self.osa_dw_conn.query_scalar(sql)

            # max_event_key = -1   # testing purpose
            if self.max_event_key == -1:
                self.logger.warning("There is no feedback data in RDP table: {0}".format(source_table))
                return False

            return True

        except Exception as e:
            self.logger.warning(e)
            raise

        finally:
            pass

    def process_data(self):
        """
        after load_data part completes. sync data from temp table to related schemas.
        :return:
        """
        try:
            self.logger.info("Processing feedback start...")

            # loop retailer to insert feedback data
            sql = "SELECT DISTINCT retailer_key " \
                  "FROM {cmnSchema}.{importTable}"\
                .format(cmnSchema=self.dct_sync_data["target_dw_schema"],
                        importTable=self.dct_sync_data["target_dw_table"])
            self.logger.info(sql)
            retailers = self.osa_dw_conn.query(sql)

            if retailers.rowcount == 0:
                self.logger.warning("There is no data in table {cmnSchema}.{importTable}."
                                    "It could be no incremental data. Please check fetch_query against RDP database"
                                    .format(cmnSchema=self.dct_sync_data["target_dw_schema"],
                                            importTable=self.dct_sync_data["target_dw_table"]))

            for retailer in retailers:
                retailer_key = retailer.retailer_key
                osa_schema = self.capacity.get_retailer_schema_name(retailer_key)

                # Finally, run the sql
                msg = "Processing fdbk data within retailer {retailerKey}:{retailerName}"\
                    .format(retailerKey=retailer_key, retailerName=osa_schema)
                self.logger.info(msg)

                # Normally, There should NOT be duplicated alert_id transfered by incremental.
                # But should consider this case here. Delete existing alertid from target table
                # TODO: delete could have performance issue. consider using switch partition
                delete_sql = "DELETE FROM {osaSchema}.{targetTable} " \
                             "WHERE alert_id IN (SELECT alert_id FROM {cmnSchema}.{importTable} )"\
                    .format(targetTable=self.target_table_osa,
                            osaSchema=osa_schema,
                            cmnSchema=self.dct_sync_data["target_dw_schema"],
                            importTable=self.dct_sync_data["target_dw_table"])
                self.logger.info(delete_sql)
                self.osa_dw_conn.execute(delete_sql)

                # inserting feedback data into final table fact_feedback from processed table.
                sql = """
                INSERT INTO {osaSchema}.{targetTable}
                (EVENT_KEY, RETAILER_KEY, VENDOR_KEY, STORE_VISITED_PERIOD_KEY, PERIOD_KEY,
                 ALERT_ID, STORE_KEY, MERCHANDISER_STORE_NUMBER,
                 STORE_ID, ITEM_KEY, MERCHANDISER_UPC, UPC, MERCHANDISER, STORE_REP, SOURCE,
                 BEGIN_STATUS, ACTION, FEEDBACK_DESCRIPTION,
                 ON_HAND_PHYSICAL_COUNT, ON_HAND_CAO_COUNT
                )
                SELECT stage.EVENT_KEY, stage.RETAILER_KEY, stage.VENDOR_KEY,
                       TO_CHAR(stage.STORE_VISIT_DATE, 'YYYYMMDD')::int AS STORE_VISITED_PERIOD_KEY,
                       stage.PERIOD_KEY,
                       stage.ALERT_ID,
                       store.STORE_KEY AS STORE_KEY,
                       stage.MERCHANDISER_STORE_NUMBER,
                       COALESCE(store.STORE_ID , alert.STOREID, stage.STORE_ID) AS STORE_ID,
                       item.ITEM_KEY AS ITEM_KEY,
                       stage.MERCHANDISER_UPC,
                       COALESCE(item.UPC, alert.UPC, stage.INNER_UPC, stage.MERCHANDISER_UPC) AS UPC,
                       stage.MERCHANDISER, stage.STORE_REP, stage.SOURCE,
                       stage.BEGIN_STATUS, stage.ACTION, stage.FEEDBACK_DESCRIPTION,
                       0 AS ON_HAND_PHYSICAL_COUNT,
                       0 AS ON_HAND_CAO_COUNT
                FROM {cmnSchema}.{importTable} stage
                LEFT JOIN {osaSchema}.FACT_PROCESSED_ALERT alert
                ON stage.alert_id = alert.alert_id AND alert.issuanceid = 0
                AND alert.retailer_key = {retailerKey} AND stage.vendor_key = alert.vendor_key
                INNER JOIN {cmnSchema}.DIM_PRODUCT item
                ON item.retailer_key = {retailerKey} AND alert.vendor_key = item.vendor_key
                AND item.item_key = alert.item_key
                INNER JOIN {cmnSchema}.DIM_STORE store
                ON store.retailer_key = {retailerKey} AND alert.vendor_key = store.vendor_key
                AND store.store_key = alert.store_key
                WHERE stage.retailer_key = {retailerKey}
                """.format(osaSchema=osa_schema,
                           targetTable=self.target_table_osa,
                           cmnSchema=self.dct_sync_data["target_dw_schema"],
                           importTable=self.dct_sync_data["target_dw_table"],
                           retailerKey=retailer_key)
                self.logger.info("SQL used to load data to related schema. %s" % sql)
                self.osa_dw_conn.execute(sql)

            self.logger.info("Processing feedback ended...")

        except Exception as e:
            self.logger.warning("Process data for RDP {0} failed: {1}".format(self._rdp_id, e))
            raise

        finally:
            if self._debug.upper() == 'N':
                _drop_sql = "DROP TABLE IF EXISTS {schemaName}.{importTable};" \
                    .format(schemaName=self.dct_sync_data["target_dw_schema"],
                            importTable=self.dct_sync_data["target_dw_table"])
                self.logger.info(_drop_sql)
                self.osa_dw_conn.execute(_drop_sql)


class FeedbackNanny(Feedback):

    def __init__(self, meta, request_body, logger=None):
        logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1, module_name="syncRDPFeedbackNanny")
        __debug = request_body.get("debug", 'N')
        __log_level = 'DEBUG' if str(__debug).upper() == 'Y' else 'INFO'
        logger.set_level(log_level=__log_level)
        init_fdbk = False  # True is only for initial rdp feedback of new customer
        
        Feedback.__init__(self, meta={**meta}, params={**request_body}, init_flag=init_fdbk, logger=logger)
    
    
class FeedbackHandler(MasterHandler):

    def set_service_properties(self):
        self.service_name = 'syncRDPFeedbackNanny'
        
       
class FeedbackApp(App):
    '''
    This class is just for testing, osa_bundle triggers it somewhere else
    '''
    def __init__(self, meta):
        App.__init__(self, meta=meta, service_bundle_name='syncRDPFeedbackNanny')
    
             
                
if __name__ == '__main__':
    #import configparser, sys
    #with open("{}/../../../config/config.properties".format(sys.argv[0])) as fp:
    #    cp = configparser.ConfigParser()
    #    cp.read_file(fp)
    #    meta = dict(cp.items("DEFAULT"))
    #
    ## case1: sync all vendors feedback data from RDP.
    ## params = dict(rdpId="RDP_AUX_CAPABILITY_KATHERINE", debug='Y')
    #params = dict(rdpId=None, debug='Y')
    #f = Feedback(meta=meta, params=params)
    #
    ## case2: init new customer data for given vendor & retailer
    ## params = dict(vendor_key=684, retailer_key=158, debug='Y')
    ## f = Feedback(meta=meta, params=params, init_flag=True)
    #
    #
    #f.main_process()
    '''REQUEST BODY
    {
        "jobId": 1234,      # mandatory. passed from JobScheduler
        "stepId": 3,        # mandatory. passed from JobScheduler
        "batchId": 0,       # mandatory. passed from JobScheduler
        "retry": 0,         # mandatory. passed from JobScheduler
        "groupName": 22, 
        "rdpId": "RDP_AUX", # optional - will process data with all feedback related RDPs(get RDPs from cp) if no rdp pa
        "debug":"N"         # char: optional [Y|N]
    }
    '''
    import os
    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    exec(open(generic_main_file).read())
    
    app = FeedbackApp(meta=meta)   #************* update services.json --> syncRDPFeedbackNanny.service_bundle_name to syncRDPFeedbackNanny before running the script
    app.start_service()

