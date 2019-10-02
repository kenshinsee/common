#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import json
import sys
import requests
from db.crypto import Crypto
from db.db_operation import DWOperation, SiloOperation, MSOperation
from common.step_status import StepStatus
from db.sync_data import sync_data
from agent.master import MasterHandler
from agent.app import App
from api.config_service import Config
from log.logger import Logger


class SyncDimData:
    """
    Get product and store dimension data from hub. DIM_PRODUCT and DIM_STORE save pivoted data,
    tall table PRODUCT and STORE save attribute that config in AP_CONFIG_META_ATTRIBUTE
    """

    def __init__(self, context):
        self.context = {**context, **context["meta"]}.copy()
        self._hub_ids = context["hub_ids"]
        self._logger = context["logger"]
        self._db = MSOperation(meta=context["meta"])
        self._dw = DWOperation(meta=context["meta"])
        self._common_schema = context["meta"]["db_conn_vertica_common_schema"]
        # self._dw_conn_vertica = self.context["dw_conn_vertica"]
        self._all_dim = self.context["all_dim"]
        self._dim_calendar = "DIM_CALENDAR"
        self._dim_product = "DIM_PRODUCT"
        self._dim_store = "DIM_STORE"
        self._product_cis_src_tbl = "PS_ITEM_DIM_EXT"
        self._store_cis_src_tbl = "PS_STORE_DIM_EXT"
        self._dct_vendor_retailer_hub = {}
        self._dct_vendor_hub = {}
        self._dct_retailer_hub = {}
        self._all_vendor_retailer_hub = self._get_avaliable_vr()

    def _get_column(self):
        """Get attribute from config table
        :return:
        """
        self._dct_table = {"DIM_PRODUCT": "", "DIM_STORE": ""}
        self._dct_key = {"DIM_PRODUCT": "ITEM_KEY", "DIM_STORE": "STORE_KEY"}
        self._dct_table_column = {"PRODUCT": [], "STORE": []}
        sql = "SELECT DISTINCT KEY_COLUMN FROM AP_CONFIG_META_ATTRIBUTE WHERE DIMENSION_TYPE = 1"
        self._logger.debug(sql)
        for row in self._db.query(sql):
            self._dct_table_column["PRODUCT"].append(row[0])
        sql = "SELECT DISTINCT KEY_COLUMN FROM AP_CONFIG_META_ATTRIBUTE WHERE DIMENSION_TYPE = 2"
        self._logger.debug(sql)
        for row in self._db.query(sql):
            self._dct_table_column["STORE"].append(row[0])
        for k, v in self._dct_table_column.items():
            self._dct_table_column[k] = """'{}'""".format("', '".join(v))

    def _get_source_config(self, hub_id):
        """Get source config
        :return:
        """
        self._source_dw = SiloOperation(hub_id=hub_id, meta=self.context["meta"])
        if self.context["meta"]["db_conn_vertica_silo_username"]:
            self._source_dw.config.json_data["configs"]["dw.etluser.id"] = self._source_dw.username
            self._source_dw.config.json_data["configs"]["dw.etluser.password"] = Crypto().encrypt(
                self._source_dw.password)
        silo_type = self._source_dw.config.get_property("etl.silo.type", "None").upper()
        # TODO For hub, silo_type is MD, not find para for this, default host
        if silo_type in ("WMSSC", "SASSC", "WMCAT", "WMINTL"):
            self._active_status = ""
        else:
            self._active_status = " AND D.ACTIVE = 'T'"

    def _get_avaliable_vr(self):
        """
        getting all avaliable vendor and retailer from cycle mapping table.
        and get related hub_id via config service.
        :return: dict like {'vendor,retailer': 'hub_id', ...}
        """

        sql = "SELECT DISTINCT VENDOR_KEY, RETAILER_KEY FROM AP_ALERT_CYCLE_MAPPING " \
              "UNION " \
              "SELECT DISTINCT VENDOR_KEY, RETAILER_KEY FROM AP_ALERT_CYCLE_RC_MAPPING"
        self._logger.debug(sql)
        dct_vendor_retailer_hub = {}
        # dct_vendor_retailer_hub = dict(self._db.query(sql))
        for v_r in self._db.query(sql):
            try:
                config = Config(meta=self.context["meta"], vendor_key=v_r.VENDOR_KEY, retailer_key=v_r.RETAILER_KEY)
                hub_id = config.get_hub_id()
                _key = str(v_r.VENDOR_KEY) + ',' + str(v_r.RETAILER_KEY)
                dct_vendor_retailer_hub[_key] = hub_id
            # in case there is no config returned for given vendor & retailer, then skip this vendor & retailer.
            except Exception as e:
                # self._logger.warning(str(e))
                self._logger.warning("Seems there is no silo configed for vendor: %s and retailer: %s" %
                                     (str(v_r.VENDOR_KEY), str(v_r.RETAILER_KEY)))
                continue

        return dct_vendor_retailer_hub

    def _get_vendor_retailer_from_hub(self, hub_id):
        """Get vendor retailer from table AP_ALERT_CYCLE_MAPPING, only keep the first one that appear in multiple hubs
        :return:
        """
        self._str_vendor_retailer_filter = ""
        self._str_vendor_filter = ""
        self._str_retailer_filter = ""
        lst_vendor_retailer_filter = []
        lst_vendor_filter = []
        lst_retailer_filter = []
        dct_vendor_retailer_hub = self._all_vendor_retailer_hub

        sql = ("SELECT /*+ LABEL(GX_IRIS_SYNC_DIM_DATA)*/ "
               "    DISTINCT VENDOR_KEY, RETAILER_KEY FROM {self._meta_schema}.CONFIG_CUSTOMERS"
               " WHERE VENDOR_NAME != 'Alert' AND HUB_ID = '{hub_id}'"
               " ORDER BY VENDOR_KEY, RETAILER_KEY".format(hub_id=hub_id, self=self))
        self._logger.debug(sql)
        vendor_retailers = self._source_dw.query(sql)
        for row in vendor_retailers:
            _vr = "{row.VENDOR_KEY},{row.RETAILER_KEY}".format(row=row)
            # same vendor & retailer could have multi hubs.
            # So only getting the one which matches with the hub from Config service.
            if dct_vendor_retailer_hub.get(_vr) == hub_id or self._all_dim:
                if _vr not in self._dct_vendor_retailer_hub:
                    self._dct_vendor_retailer_hub[_vr] = hub_id
                    lst_vendor_retailer_filter.append("({row.VENDOR_KEY},{row.RETAILER_KEY})".format(row=row))
                if str(row.VENDOR_KEY) not in self._dct_vendor_hub:
                    self._dct_vendor_hub["{}".format(row.VENDOR_KEY)] = hub_id
                    lst_vendor_filter.append("{}".format(row.VENDOR_KEY))
                if str(row.RETAILER_KEY) not in self._dct_retailer_hub:
                    self._dct_retailer_hub["{}".format(row.RETAILER_KEY)] = hub_id
                    lst_retailer_filter.append("{}".format(row.RETAILER_KEY))
        if lst_vendor_retailer_filter:
            self._str_vendor_retailer_filter = (" AND (VENDOR_KEY, RETAILER_KEY) IN ({})"
                                                "".format(",".join(lst_vendor_retailer_filter)))
            self._logger.debug(self._str_vendor_retailer_filter)
        if lst_vendor_filter:
            self._str_vendor_filter = (" AND VENDOR_KEY IN ({})".format(",".join(list(set(lst_vendor_filter)))))
            self._logger.debug(self._str_vendor_filter)
        if lst_retailer_filter:
            self._str_retailer_filter = (" AND RETAILER_KEY IN ({})".format(",".join(list(set(lst_retailer_filter)))))
            self._logger.debug(self._str_retailer_filter)

    def _recreate_stage_table(self):
        """
        Creating related stage tables on IRIS DW.
        :return:
        """
        lst_sql = []
        for table in (list(self._dct_table.keys()) + ["PRODUCT", "STORE"]):
            lst_sql.append("""
                DROP TABLE IF EXISTS {self._common_schema}.STAGE_{table};
                CREATE TABLE {self._common_schema}.STAGE_{table} LIKE {self._common_schema}.{table} INCLUDING PROJECTIONS;
            """.format(self=self, table=table))
        sql = ''.join(lst_sql)
        self._logger.info(sql)
        self._dw.execute(sql)

        # creating staging table for loading CIS source data.
        _sql = """
         DROP TABLE IF EXISTS {cmnSchema}.STAGE_{itemTable}_CIS;
         CREATE TABLE {cmnSchema}.STAGE_{itemTable}_CIS LIKE {cmnSchema}.{itemTable} INCLUDING PROJECTIONS;
         
         DROP TABLE IF EXISTS {cmnSchema}.STAGE_{storeTable}_CIS;
         CREATE TABLE {cmnSchema}.STAGE_{storeTable}_CIS LIKE {cmnSchema}.{storeTable} INCLUDING PROJECTIONS;
         """.format(cmnSchema=self._common_schema,
                    itemTable=self._dim_product,
                    storeTable=self._dim_store)
        self._logger.info(_sql)
        self._dw.execute(_sql)

    def _truncate_stage_table(self):
        """Truncate stage table
        :return:
        """
        lst_sql = []
        for k in (list(self._dct_table.keys()) + ["PRODUCT", "STORE"]):
            lst_sql.append("TRUNCATE TABLE {self._common_schema}.STAGE_{k}".format(self=self, k=k))
        sql = ';\n'.join(lst_sql)
        self._logger.debug(sql)
        self._dw.execute(sql)

    def _analyze_table(self):
        """Analyze table
        :return:
        """
        lst_sql = []
        for k in self._dct_table.keys():
            lst_sql.append("SELECT /*+ LABEL(GX_IRIS_SYNC_DIM_DATA)*/ ANALYZE_STATISTICS('{self._common_schema}.{k}')"
                           "".format(self=self, k=k))
        sql = ';\n'.join(lst_sql)
        self._logger.debug(sql)
        self._dw.execute(sql)

    def _export_calendar_data(self, hub_id):
        """ Export calendar data to common schema from source schema if no data in DIM_CALENDAR table
        :param hub_id:
        :return:
        """
        cnt = self._dw.query_scalar("SELECT /*+ LABEL(GX_IRIS_SYNC_DIM_DATA)*/ COUNT(*) "
                                    "FROM {self._common_schema}.{self._dim_calendar}".format(self=self))
        if cnt != 0:
            self._logger.info("Calendar data exists, skip hub_id {}.".format(hub_id))
        else:
            col = ('PERIOD_KEY, CALENDAR_KEY, CALENDARNAME, YEAR, YEARNAME, QUARTER, QUARTERNAME, MONTH, MONTHNAME, '
                   'PERIOD, PERIODNAME, WEEKENDED, WEEKENDEDNAME, WEEKBEGIN, WEEKBEGINNAME, YEARWEEKNAME, YEARWEEK, '
                   'YEARMONTHWEEKNAME, LY_PERIOD_KEY, NY_PERIOD_KEY, DATE_NAME, DATE_VALUE, CAL_PERIOD_KEY, '
                   '"2YA_PERIOD_KEY", "3YA_PERIOD_KEY", "4YA_PERIOD_KEY"')
            sql = """
            SELECT /*+ LABEL(GX_IRIS_SYNC_DIM_DATA)*/ CAL.PERIOD_KEY AS PERIOD_KEY,
                   META.CALENDAR_KEY AS CALENDAR_KEY,
                   MAX(META.CALENDAR_NAME) AS CALENDARNAME,
                   MAX(CAL."YEAR") AS "YEAR",
                   MAX(CAL.YEARNAME) AS YEARNAME,
                   MAX(CAL.YEARQUARTER) AS QUARTER,
                   MAX(CAL.YEARQUARTERNAME) AS QUARTERNAME,
                   MAX(CAL.YEARPERIOD) AS "MONTH",
                   MAX(CAL.YEARPERIODNAME) AS MONTHNAME,
                   MAX(CAL.YEARMONTH) AS PERIOD,
                   MAX(CAL.YEARMONTHNAME) AS PERIODNAME,
                   MAX(CAL.WEEKENDED) AS WEEKENDED,
                   MAX(CAL.WEEKENDEDNAME) AS WEEKENDEDNAME,
                   MAX(CAL.WEEKBEGIN) AS WEEKBEGIN,
                   MAX(CAL.WEEKBEGINNAME) AS WEEKBEGINNAME,
                   (((MAX(CAL.YEAR))::VARCHAR|| ' - Wk '::VARCHAR(6)) || SUBSTR(('00'::VARCHAR(2) 
                   ||(MAX(CAL.WEEK))::VARCHAR),((LENGTH(('00'::VARCHAR(2) ||(MAX(CAL.WEEK))::VARCHAR)) - 2) + 1),2)
                   ) AS YEARWEEKNAME,
                   MAX(CAL.YEARWEEK) AS YEARWEEK,
                   (((((MAX(CAL.YEAR))::VARCHAR|| ' - '::VARCHAR(3)) || SUBSTR (('00'::VARCHAR(2) 
                   ||(MAX(CAL.MONTH))::VARCHAR),((LENGTH(('00'::VARCHAR(2) ||(MAX(CAL.MONTH))::VARCHAR)) - 2) + 1),2)) 
                   || ' Wk '::VARCHAR(4)) || SUBSTR(('00'::VARCHAR(2) 
                   ||(CEILING(((RANK() OVER (PARTITION BY META.CALENDAR_KEY,MAX(CAL.YEAR),MAX(META.MONTH) 
                   ORDER BY CAL.PERIOD_KEY)*1.0) / 7::NUMERIC(18,0))))::VARCHAR),((LENGTH(('00'::VARCHAR(2) 
                   ||(CEILING(((RANK() OVER (PARTITION BY META.CALENDAR_KEY,MAX(CAL.YEAR),MAX(CAL.MONTH) ORDER BY 
                   CAL.PERIOD_KEY)*1.0) / 7::NUMERIC(18,0))))::VARCHAR)) - 2) + 1),2)) AS YEARMONTHWEEKNAME,
                   MAX(CAL.LY_PERIOD_KEY) LY_PERIOD_KEY,
                   MAX(CAL.NY_PERIOD_KEY) NY_PERIOD_KEY,
                   TO_CHAR(TO_DATE(CAL.PERIOD_KEY::VARCHAR, 'YYYYMMDD'), 'YYYY-MM-DD') DATE_NAME,
                   TO_DATE(CAL.PERIOD_KEY::VARCHAR, 'YYYYMMDD') DATE_VALUE,
                   CAL.PERIOD_KEY CAL_PERIOD_KEY,
                   MAX("2YA_PERIOD_KEY") "2YA_PERIOD_KEY",  MAX("3YA_PERIOD_KEY") "3YA_PERIOD_KEY", 
                   MAX("4YA_PERIOD_KEY") "4YA_PERIOD_KEY"
            FROM (
                (SELECT 2 AS CALENDAR_KEY, 'STD' AS PREFIX, 1 AS "MONTH", '445 (Standard)' AS CALENDAR_NAME) META
                  JOIN (SELECT C.PERIOD_KEY AS PERIOD_KEY,
                        C.CALENDAR_KEY AS CALENDAR_KEY,
                        C.YEAR,
                        C.WEEK,
                        C.MONTH,
                        (C.YEAR)::VARCHAR(4) AS YEARNAME,
                        QE.YEARQUARTER,
                        QE.YEARQUARTERNAME,
                        ME.YEARPERIOD AS YEARMONTH,
                        ME.YEARPERIODNAME AS YEARMONTHNAME,
                        ME.YEARPERIOD,
                        ME.YEARPERIODNAME,
                        WE.YEARWEEK AS YEARWEEK,
                        WE.WEEKBEGIN,
                        TO_CHAR(TO_DATE ((WE.WEEKBEGIN)::VARCHAR,'YYYYMMDD'::VARCHAR(8)),'MM/DD/YYYY'::VARCHAR(10)
                        ) AS WEEKBEGINNAME,
                        WE.WEEKENDED,
                        TO_CHAR(TO_DATE ((WE.WEEKENDED)::VARCHAR,'YYYYMMDD'::VARCHAR(8)),'MM/DD/YYYY'::VARCHAR(10)
                        ) AS WEEKENDEDNAME,
                        C.LY_PERIOD_KEY,
                        C.NY_PERIOD_KEY,
                        YA2.LY_PERIOD_KEY "2YA_PERIOD_KEY",  YA3.LY_PERIOD_KEY "3YA_PERIOD_KEY", 
                        YA4.LY_PERIOD_KEY "4YA_PERIOD_KEY"
                    FROM ((({self._dim_schema}.CALENDAR_PERIOD C
                      JOIN (SELECT CALENDAR_PERIOD.CALENDAR_KEY,
                            MIN(CALENDAR_PERIOD.PERIOD_KEY) AS WEEKBEGIN,
                            MAX(CALENDAR_PERIOD.PERIOD_KEY) AS WEEKENDED,
                            CALENDAR_PERIOD.YEAR,
                            CALENDAR_PERIOD.WEEK AS WEEK,
                            CASE
                            WHEN (CALENDAR_PERIOD.WEEK > 2000) THEN CALENDAR_PERIOD.WEEK
                            ELSE ((CALENDAR_PERIOD.YEAR*100) + CALENDAR_PERIOD.WEEK)
                            END AS YEARWEEK
                        FROM {self._dim_schema}.CALENDAR_PERIOD
                        WHERE ((CALENDAR_PERIOD.WEEK_CODE = 'B'::CHAR(1)) OR (CALENDAR_PERIOD.WEEK_CODE = 'E'::CHAR(1)))
                        GROUP BY CALENDAR_PERIOD.CALENDAR_KEY,
                            CALENDAR_PERIOD.YEAR,
                            CALENDAR_PERIOD.WEEK) WE
                      ON ( ( (C.CALENDAR_KEY = WE.CALENDAR_KEY)
                      AND (C.YEAR = WE.YEAR)
                      AND (C.WEEK = WE.WEEK))))
                      JOIN (SELECT CALENDAR_PERIOD.CALENDAR_KEY,
                            CALENDAR_PERIOD.YEAR,
                            CALENDAR_PERIOD.MONTH AS PERIOD,
                            CASE
                            WHEN (CALENDAR_PERIOD.MONTH > 2000) THEN (CALENDAR_PERIOD.MONTH)::VARCHAR(6)
                            ELSE CONCAT (CONCAT (CONCAT ('Period '::VARCHAR(7),(CALENDAR_PERIOD.MONTH)::VARCHAR(2)), 
                                 ', '::VARCHAR(2)),(CALENDAR_PERIOD.YEAR)::VARCHAR(4))
                            END AS YEARPERIODNAME,
                            CASE
                            WHEN (CALENDAR_PERIOD.MONTH > 2000) THEN CALENDAR_PERIOD.MONTH
                            ELSE ((CALENDAR_PERIOD.YEAR*100) + CALENDAR_PERIOD.MONTH)
                            END AS YEARPERIOD
                        FROM {self._dim_schema}.CALENDAR_PERIOD
                        WHERE ((CALENDAR_PERIOD.MONTH_CODE = 'B'::CHAR (1)) 
                                OR (CALENDAR_PERIOD.MONTH_CODE = 'E'::CHAR (1)))
                        GROUP BY CALENDAR_PERIOD.CALENDAR_KEY,
                            CALENDAR_PERIOD.YEAR,
                            CALENDAR_PERIOD.MONTH) ME
                      ON ( ( (C.CALENDAR_KEY = ME.CALENDAR_KEY)
                      AND (C.YEAR = ME.YEAR)
                      AND (C.MONTH = ME.PERIOD))))
                      JOIN (SELECT CALENDAR_PERIOD.CALENDAR_KEY,
                            CALENDAR_PERIOD.YEAR,
                            CALENDAR_PERIOD.QUARTER AS QUARTER,
                            CASE WHEN CALENDAR_PERIOD.QUARTER > 2000 THEN CONCAT(CONCAT (CONCAT ('Q'::VARCHAR(1), 
                                (SUBSTR((CALENDAR_PERIOD.QUARTER)::VARCHAR(6), 6))::VARCHAR(2)), 
                                ', '::VARCHAR(2)),(CALENDAR_PERIOD.QUARTER)::VARCHAR(4)) 
                            ELSE CONCAT(CONCAT (CONCAT ('Q'::VARCHAR(1),(CALENDAR_PERIOD.QUARTER)::VARCHAR(2)), 
                                ', '::VARCHAR(2)),(CALENDAR_PERIOD.YEAR)::VARCHAR(4)) 
                            END AS  YEARQUARTERNAME,
                            CASE
                            WHEN (CALENDAR_PERIOD.QUARTER > 2000) THEN CALENDAR_PERIOD.QUARTER
                            ELSE ((CALENDAR_PERIOD.YEAR*100) + CALENDAR_PERIOD.QUARTER)
                            END AS YEARQUARTER
                        FROM {self._dim_schema}.CALENDAR_PERIOD
                        WHERE ((CALENDAR_PERIOD.QUARTER_CODE = 'B'::CHAR (1)) 
                                OR (CALENDAR_PERIOD.QUARTER_CODE = 'E'::CHAR (1)))
                        GROUP BY CALENDAR_PERIOD.CALENDAR_KEY,
                            CALENDAR_PERIOD.YEAR,
                            CALENDAR_PERIOD.QUARTER) QE
                      ON (((C.CALENDAR_KEY = QE.CALENDAR_KEY) AND (C.YEAR = QE.YEAR) AND (C.QUARTER = QE.QUARTER))))
                      LEFT JOIN {self._dim_schema}.CALENDAR_PERIOD YA2 
                      ON C.CALENDAR_KEY = YA2.CALENDAR_KEY AND C.LY_PERIOD_KEY = YA2.PERIOD_KEY
                      LEFT JOIN {self._dim_schema}.CALENDAR_PERIOD YA3 
                      ON C.CALENDAR_KEY = YA3.CALENDAR_KEY AND YA2.LY_PERIOD_KEY = YA3.PERIOD_KEY
                      LEFT JOIN {self._dim_schema}.CALENDAR_PERIOD YA4 
                      ON C.CALENDAR_KEY = YA4.CALENDAR_KEY AND YA3.LY_PERIOD_KEY = YA4.PERIOD_KEY        
                    WHERE (C.YEAR >= ((DATE_PART ('year'::VARCHAR (4),(NOW ())::TIMESTAMP))::INT- 5))) CAL 
                  ON ( (CAL.CALENDAR_KEY = META.CALENDAR_KEY))
            )
            GROUP BY CAL.PERIOD_KEY,META.CALENDAR_KEY;
            """.format(self=self)
            dct_sync_data = self.context.copy()
            dct_sync_data["source_dw"] = self._source_dw
            dct_sync_data["source_config"] = self._source_dw.config.json_data["configs"]
            dct_sync_data["target_dw_schema"] = self._common_schema
            dct_sync_data["target_dw_table"] = self._dim_calendar
            dct_sync_data["target_column"] = col
            dct_sync_data["source_sql"] = sql
            self._logger.debug(sql)
            sync_data(dct_sync_data)
            self._logger.info("Sync hub_id {} dim calendar done".format(hub_id))

    def _export_product_data(self, hub_id, cis_source=False):
        """
        Export product data to common schema from source schema
        :param hub_id:
        :return:
        """

        _target_stage_table = "STAGE_{}".format(self._dim_product)
        _src_item_table = "PRODUCT"
        if cis_source:
            _target_stage_table = "STAGE_{}_CIS".format(self._dim_product)
            _src_item_table = "STAGE_{}".format(self._product_cis_src_tbl)

            # Creating related staging table for CIS source in HUB dw.
            # Since CIS source tables are external tables, can NOT be used to join other tables directly.
            sql = """
            DROP TABLE IF EXISTS {dimSchema}.{stgItemTable};
            CREATE TABLE {dimSchema}.{stgItemTable} AS 
            SELECT RETAILER_KEY, VENDOR_KEY, ITEM_KEY, UPC_ID AS UPC, 
                   ATTRIBUTE_NAME as ATTRIBNAME, ATTRIBUTE_VALUE as ATTRIBVALUE, 'T' AS ACTIVE 
            FROM {dimSchema}.{srcItemTable}
            WHERE 0=0 {filters};
            """.format(dimSchema=self._dim_schema,
                       stgItemTable=_src_item_table,
                       srcItemTable=self._product_cis_src_tbl,
                       filters=self._str_vendor_retailer_filter
                       )
            self._logger.info(sql)
            self._source_dw.execute(sql)

        col = (" RETAILER_KEY, VENDOR_KEY, ITEM_KEY, UPC, ITEM_DESCRIPTION, ITEM_GROUP, OSM_ITEM_NBR, OSM_ITEM_STATUS,"
               "OSM_ITEM_TYPE, OSM_BRAND, OSM_UNIT_PRICE, OSM_CATEGORY, OSM_MAJOR_CATEGORY_NO, OSM_MAJOR_CATEGORY, "
               "OSM_SUB_CATEGORY_NO, OSM_SUB_CATEGORY, OSM_VENDOR_STK_NBR, OSM_VENDOR_PACK_COST, VENDOR_PACK_QTY, "
               "OSM_WHSE_PACK_COST, OSM_WHSE_PACK_QTY, DSD_IND, VENDOR_NAME ")
        sql = """
        SELECT /*+ LABEL(GX_IRIS_SYNC_DIM_DATA)*/ 
            CC.RETAILER_KEY, CC.VENDOR_KEY, PV.ITEM_KEY, PV.UPC, AGPG.ITEM_DESCRIPTION, 
            CASE WHEN AGPG.ITEM_GROUP IS NULL OR AGPG.ITEM_GROUP = '000000' THEN PV.UPC ELSE AGPG.ITEM_GROUP END AS 
            ITEM_GROUP, AGPG.OSM_ITEM_NBR, AGPG.OSM_ITEM_STATUS, AGPG.OSM_ITEM_TYPE, AGPG.OSM_BRAND,AGPG.OSM_UNIT_PRICE, 
            AGPG.OSM_CATEGORY, AGPG.OSM_MAJOR_CATEGORY_NO, AGPG.OSM_MAJOR_CATEGORY, AGPG.OSM_SUB_CATEGORY_NO, 
            AGPG.OSM_SUB_CATEGORY, AGPG.OSM_VENDOR_STK_NBR, AGPG.OSM_VENDOR_PACK_COST, 
            CASE WHEN length(AGPG.VENDOR_PACK_QTY) < 15
                THEN CASE WHEN REGEXP_LIKE(SUBSTR(REPLACE(AGPG.VENDOR_PACK_QTY, ',', ''),0,15), '^[0-9]*(\.[0-9]+)?$') 
                    THEN CASE WHEN SUBSTR(REPLACE(AGPG.VENDOR_PACK_QTY, ',', ''),0,15)::NUMERIC <= 1 THEN 1
                        ELSE SUBSTR(REPLACE(AGPG.VENDOR_PACK_QTY, ',', ''),0,15)::NUMERIC END 
                    ELSE 1 END 
                ELSE 1 END VENDOR_PACK_QTY, AGPG.OSM_WHSE_PACK_COST, AGPG.OSM_WHSE_PACK_QTY, 
            CASE WHEN AGPG.OSM_ITEM_TYPE IN ('07','37') THEN '1' ELSE '0' END AS DSD_IND, CC.VENDOR_NAME
        FROM (SELECT DISTINCT RETAILER_KEY, VENDOR_KEY, VENDOR_NAME FROM {self._meta_schema}.CONFIG_CUSTOMERS
              WHERE VENDOR_NAME != 'Alert' {self._str_vendor_retailer_filter}) CC
        JOIN (
            SELECT D.VENDOR_KEY, D.ITEM_KEY, MAX(D.UPC) UPC FROM {self._dim_schema}.{itemTable} D
            JOIN {self._dim_schema}.VENDOR V on V.VENDOR_KEY = D.VENDOR_KEY
            WHERE D.ITEM_KEY NOT IN (SELECT ITEM_KEY FROM {self._dim_schema}.PRODUCT_GLOBAL_FILTER) 
            {self._active_status}
            GROUP BY D.VENDOR_KEY, D.ITEM_KEY
        ) PV ON PV.VENDOR_KEY = CC.VENDOR_KEY
        LEFT JOIN (
            SELECT AGP.RETAILER_KEY, AGP.VENDOR_KEY, AGP.ITEM_KEY
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'ITEM_GROUP_X' THEN ATTRIBVALUE END) ITEM_GROUP
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'VENDOR_PACK_QTY_X' THEN ATTRIBVALUE END) VENDOR_PACK_QTY
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'ITEM_DESCRIPTION_X' THEN ATTRIBVALUE END) ITEM_DESCRIPTION
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'OSM_ITEM_NBR_X' THEN ATTRIBVALUE END)     OSM_ITEM_NBR
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'OSM_ITEM_STATUS_X' THEN ATTRIBVALUE END)     OSM_ITEM_STATUS
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'OSM_ITEM_TYPE_X' THEN ATTRIBVALUE END)     OSM_ITEM_TYPE
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'OSM_WHSE_PACK_QTY_X' THEN ATTRIBVALUE END)     OSM_WHSE_PACK_QTY
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'OSM_MAJOR_CATEGORY_NO_X' THEN ATTRIBVALUE END)     OSM_MAJOR_CATEGORY_NO
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'OSM_MAJOR_CATEGORY_X' THEN ATTRIBVALUE END)     OSM_MAJOR_CATEGORY
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'OSM_CATEGORY_X' THEN ATTRIBVALUE END)     OSM_CATEGORY
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'OSM_SUB_CATEGORY_NO_X' THEN ATTRIBVALUE END)     OSM_SUB_CATEGORY_NO
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'OSM_SUB_CATEGORY_X' THEN ATTRIBVALUE END)     OSM_SUB_CATEGORY
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'OSM_BRAND_X' THEN ATTRIBVALUE END)     OSM_BRAND
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'OSM_UNIT_PRICE_X' THEN ATTRIBVALUE END)     OSM_UNIT_PRICE
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'OSM_VENDOR_STK_NBR_X' THEN ATTRIBVALUE END)     OSM_VENDOR_STK_NBR
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'OSM_VENDOR_PACK_COST_X' THEN ATTRIBVALUE END)     OSM_VENDOR_PACK_COST
            , MAX(CASE WHEN AGP.ATTRIBNAME = 'OSM_WHSE_PACK_COST_X' THEN ATTRIBVALUE END)     OSM_WHSE_PACK_COST
            FROM (
                SELECT AG.RETAILER_KEY, AG.VENDOR_KEY, CONCAT(ATTR_GROUP, '_X') ATTRIBNAME, D.ITEM_KEY, D.ATTRIBVALUE
                      FROM {self._meta_schema}.ATTRIBUTEGROUP AG
                      JOIN {self._dim_schema}.{itemTable} D
                      ON D.VENDOR_KEY = AG.VENDOR_KEY AND D.ATTRIBNAME = AG.ATTR_NAME {self._active_status}
                      WHERE AG.ATTR_GROUP IN ('ITEM_GROUP','VENDOR_PACK_QTY','ITEM_DESCRIPTION','OSM_ITEM_NBR'
                          ,'OSM_ITEM_STATUS','OSM_ITEM_TYPE','OSM_WHSE_PACK_QTY','OSM_MAJOR_CATEGORY_NO'
                          ,'OSM_MAJOR_CATEGORY','OSM_CATEGORY','OSM_SUB_CATEGORY_NO','OSM_SUB_CATEGORY','OSM_BRAND',
                          'OSM_UNIT_PRICE','OSM_VENDOR_STK_NBR','OSM_VENDOR_PACK_COST','OSM_WHSE_PACK_COST')
            ) AGP
            GROUP BY AGP.RETAILER_KEY, AGP.VENDOR_KEY, AGP.ITEM_KEY
        ) AGPG ON AGPG.RETAILER_KEY = CC.RETAILER_KEY AND AGPG.VENDOR_KEY = PV.VENDOR_KEY AND AGPG.ITEM_KEY =PV.ITEM_KEY
        WHERE (CC.RETAILER_KEY, CC.VENDOR_KEY, PV.ITEM_KEY) NOT IN
                (SELECT RETAILER_KEY, VENDOR_KEY, ITEM_KEY FROM {self._dim_schema}.PRODUCT_DEFAULT_FILTER)
        """.format(self=self, itemTable=_src_item_table)
        dct_sync_data = self.context.copy()
        dct_sync_data["source_dw"] = self._source_dw
        dct_sync_data["source_config"] = self._source_dw.config.json_data["configs"]
        dct_sync_data["target_dw_schema"] = self._common_schema
        dct_sync_data["target_dw_table"] = _target_stage_table
        dct_sync_data["target_column"] = col
        dct_sync_data["source_sql"] = sql
        self._logger.debug(sql)
        sync_data(dct_sync_data)

        # sync tall table(not for CIS).
        if self._str_vendor_filter and not cis_source:
            self._product_columns = self._dct_table_column["PRODUCT"]
            col = " VENDOR_KEY, ITEM_KEY, UPC, ATTRIBNAME, ATTRIBVALUE, ACTIVE "
            sql = ("SELECT /*+ LABEL(GX_IRIS_SYNC_DIM_DATA)*/ {col} FROM {self._dim_schema}.PRODUCT WHERE ATTRIBNAME "
                   "IN ({self._product_columns}) {self._str_vendor_filter}".format(self=self, col=col))
            dct_sync_data["target_dw_table"] = "STAGE_PRODUCT"
            dct_sync_data["target_column"] = col
            dct_sync_data["source_sql"] = sql
            self._logger.debug(sql)
            sync_data(dct_sync_data)

    def _export_store_data(self, hub_id, cis_source=False):
        """
        Export store data to common schema table stage_<table_name> from source schema <table_name>
        :param hub_id:
        :return:
        """

        _target_store_table = "STAGE_{}".format(self._dim_store)
        _src_store_table = "STORE"
        if cis_source:
            _target_store_table = "STAGE_{}_CIS".format(self._dim_store)
            _src_store_table = "STAGE_{}".format(self._store_cis_src_tbl)

            # Creating related staging table for CIS source in HUB dw.
            # Since CIS source tables are external tables, can NOT be used to join other tables directly.
            sql = """
            DROP TABLE IF EXISTS {dimSchema}.{stgStoreTable};
            CREATE TABLE {dimSchema}.{stgStoreTable} AS 
            SELECT RETAILER_KEY, VENDOR_KEY, STORE_KEY, STORE_ID AS STOREID, 
                   ATTRIBUTE_NAME as ATTRIBNAME, ATTRIBUTE_VALUE as ATTRIBVALUE, 'T' as ACTIVE 
            FROM {dimSchema}.{srcStoreTable}
            WHERE 0=0 {filters};
            """.format(dimSchema=self._dim_schema,
                       stgStoreTable=_src_store_table,
                       srcStoreTable=self._store_cis_src_tbl,
                       filters=self._str_vendor_retailer_filter)
            self._logger.info(sql)
            self._source_dw.execute(sql)

        col = (" RETAILER_KEY, VENDOR_KEY, STORE_KEY, STORE_ID, MARKET_CLUSTER, STATE, CITY, ZIP, OSM_REGION, "
               "OSM_DISTRICT, RSI_ALERT_TYPE, RETAILER_NAME, RSI_BANNER, PRIME_DC, STORE_NAME")
        sql = """
        SELECT /*+ LABEL(GX_IRIS_SYNC_DIM_DATA)*/ CC.RETAILER_KEY, CC.VENDOR_KEY, SR.STORE_KEY, SR.STOREID, 
            AGSG.MARKET_CLUSTER, SR.STATE,
            CASE WHEN SR.CITY IS NULL AND STATE IS NULL THEN 'N/A'
                WHEN SR.CITY IS NOT NULL AND STATE IS NULL THEN CONCAT(SR.CITY, ', N/A')
                WHEN SR.CITY IS NULL AND STATE IS NOT NULL THEN CONCAT('N/A, ' , SR.STATE)
                WHEN SR.CITY IS NOT NULL AND STATE IS NOT NULL THEN CONCAT(CONCAT(SR.CITY, ', '), SR.STATE) END CITY,
            SR.ZIP, AGSG.OSM_REGION, AGSG.OSM_DISTRICT, COALESCE(SR.RSI_ALERT_TYPE, '0') RSI_ALERT_TYPE,
            CC.RETAILER_NAME, coalesce(AGSG.RSI_BANNER, 'unmapped') AS RSI_BANNER, AGSG.PRIME_DC, AGSG.STORE_NAME
        FROM (SELECT DISTINCT RETAILER_KEY, VENDOR_KEY, RETAILER_NAME FROM {self._meta_schema}.CONFIG_CUSTOMERS
              WHERE VENDOR_NAME != 'Alert' {self._str_vendor_retailer_filter}) CC
        JOIN (
            SELECT D.RETAILER_KEY, D.STORE_KEY, D.STOREID,
                MAX(CASE WHEN D.ATTRIBNAME = 'STATE' THEN D.ATTRIBVALUE END) STATE,
                MAX(CASE WHEN D.ATTRIBNAME = 'CITY' THEN D.ATTRIBVALUE END) CITY,
                MAX(CASE WHEN D.ATTRIBNAME = 'ZIP' THEN D.ATTRIBVALUE END) ZIP,
                MAX(CASE WHEN D.ATTRIBNAME = 'RSI_ALERT_TYPE' THEN D.ATTRIBVALUE END) RSI_ALERT_TYPE
            FROM {self._dim_schema}.{storeTable} D
            JOIN {self._dim_schema}.RETAILER R ON R.RETAILER_KEY = D.RETAILER_KEY
            WHERE STORE_KEY NOT IN (SELECT STORE_KEY FROM {self._dim_schema}.STORES_GLOBAL_FILTER) {self._active_status}
            GROUP BY D.RETAILER_KEY, D.STORE_KEY, D.STOREID
        ) SR ON SR.RETAILER_KEY = CC.RETAILER_KEY
        LEFT JOIN (
            SELECT AGS.RETAILER_KEY, AGS.VENDOR_KEY, AGS.STORE_KEY,
                MAX(CASE WHEN AGS.ATTRIBNAME = 'MARKET_CLUSTER_X' THEN ATTRIBVALUE END) MARKET_CLUSTER,
                MAX(CASE WHEN AGS.ATTRIBNAME = 'OSM_REGION_X' THEN ATTRIBVALUE END) OSM_REGION,
                MAX(CASE WHEN AGS.ATTRIBNAME = 'OSM_DISTRICT_X' THEN ATTRIBVALUE END) OSM_DISTRICT,
                MAX(CASE WHEN AGS.ATTRIBNAME = 'RSI_BANNER_X' THEN ATTRIBVALUE END) RSI_BANNER,
                MAX(CASE WHEN AGS.ATTRIBNAME = 'PRIME_DC_X' THEN ATTRIBVALUE END) PRIME_DC,
                MAX(CASE WHEN AGS.ATTRIBNAME = 'SAR_STORE_NAME_X' THEN ATTRIBVALUE END) STORE_NAME
                FROM (
                    SELECT AG.RETAILER_KEY, AG.VENDOR_KEY, CONCAT(AG.ATTR_GROUP, '_X') ATTRIBNAME, D.STORE_KEY, 
                        D.ATTRIBVALUE
                    FROM {self._meta_schema}.ATTRIBUTEGROUP AG
                    JOIN {self._dim_schema}.{storeTable} D
                    ON D.RETAILER_KEY = AG.RETAILER_KEY AND D.ATTRIBNAME = AG.ATTR_NAME {self._active_status}
                    WHERE AG.ATTR_GROUP IN ('RSI_BANNER','PRIME_DC', 'MARKET_CLUSTER', 'OSM_REGION', 'OSM_DISTRICT', 'SAR_STORE_NAME')
                ) AGS
                GROUP BY AGS.RETAILER_KEY, AGS.VENDOR_KEY, AGS.STORE_KEY
        ) AGSG 
        ON AGSG.RETAILER_KEY = SR.RETAILER_KEY AND AGSG.VENDOR_KEY = CC.VENDOR_KEY
        AND AGSG.STORE_KEY = SR.STORE_KEY
        WHERE (CC.RETAILER_KEY, CC.VENDOR_KEY, SR.STORE_KEY) NOT IN
                (SELECT RETAILER_KEY, VENDOR_KEY, STORE_KEY FROM {self._dim_schema}.STORES_DEFAULT_FILTER);
        """.format(self=self, storeTable=_src_store_table)
        dct_sync_data = self.context.copy()
        dct_sync_data["source_dw"] = self._source_dw
        dct_sync_data["source_config"] = self._source_dw.config.json_data["configs"]
        dct_sync_data["target_dw_schema"] = self._common_schema
        dct_sync_data["target_dw_table"] = _target_store_table
        dct_sync_data["target_column"] = col
        dct_sync_data["source_sql"] = sql
        self._logger.debug(sql)
        sync_data(dct_sync_data)

        # sync tall table(not for CIS)
        if self._str_retailer_filter and not cis_source:
            self._store_columns = self._dct_table_column["STORE"]
            col = " RETAILER_KEY, STORE_KEY, STOREID, ATTRIBNAME, ATTRIBVALUE, ACTIVE "
            sql = ("SELECT /*+ LABEL(GX_IRIS_SYNC_DIM_DATA)*/ {col} FROM {self._dim_schema}.STORE WHERE ATTRIBNAME "
                   "IN ({self._store_columns}) {self._str_retailer_filter}".format(self=self, col=col))
            dct_sync_data["target_dw_table"] = "STAGE_STORE"
            dct_sync_data["target_column"] = col
            dct_sync_data["source_sql"] = sql
            self._logger.debug(sql)
            sync_data(dct_sync_data)

    def _load_product_data_cis(self, hub_id):
        """
        Sync data from CIS source.
        if the same item_key exists in both CIS and NXG HUBs, the CIS one should override the one in NXG side.
        :param hub_id:
        :return:
        """

        # dump CIS data into cis staging table: stage_dim_product_cis
        self._export_product_data(hub_id=hub_id, cis_source=True)

        # Below part is moved from method self._export_product_data. Put it here when all product data are ready.
        # Override nxg items with CIS if there are duplicated items on both NXG and CIS
        sql = """
         DELETE FROM {cmnSchema}.STAGE_{itemTable} 
         WHERE (vendor_key, retailer_key, item_key) IN
         (SELECT vendor_key, retailer_key, item_key
          FROM {cmnSchema}.STAGE_{itemTable}_CIS);
         
         INSERT INTO {cmnSchema}.STAGE_{itemTable} 
         SELECT * FROM {cmnSchema}.STAGE_{itemTable}_CIS;
        """.format(itemTable=self._dim_product,
                   cmnSchema=self._common_schema)
        self._logger.info(sql)
        self._dw.execute(sql)

        # updating column OSM_MAJOR_CATEGORY when NXG and CIS sources are all done.
        sql = """
        DROP TABLE IF EXISTS TEMP_OSM_SUB_CATEGORY_CONSISTENCY;
        CREATE LOCAL TEMP TABLE IF NOT EXISTS TEMP_OSM_SUB_CATEGORY_CONSISTENCY ON COMMIT PRESERVE ROWS 
        AS /*+ DIRECT, LABEL(GX_IRIS_SYNC_DIM_DATA)*/ 
        SELECT distinct OSM_SUB_CATEGORY_NO,MAX(OSM_SUB_CATEGORY) as OSM_SUB_CATEGORY 
        FROM {self._common_schema}.{self._dim_product} GROUP BY OSM_SUB_CATEGORY_NO;

        DROP TABLE IF EXISTS TEMP_OSM_MAJOR_CATEGORY_CONSISTENCY;
        CREATE LOCAL TEMP TABLE IF NOT EXISTS TEMP_OSM_MAJOR_CATEGORY_CONSISTENCY ON COMMIT PRESERVE ROWS 
        AS /*+ DIRECT, LABEL(GX_IRIS_SYNC_DIM_DATA)*/ 
        SELECT distinct OSM_MAJOR_CATEGORY_NO,MAX(OSM_MAJOR_CATEGORY) as OSM_MAJOR_CATEGORY 
        FROM {self._common_schema}.{self._dim_product} GROUP BY OSM_MAJOR_CATEGORY_NO;
        """.format(self=self)
        self._logger.info(sql)
        self._dw.execute(sql)

        sql = ("""
        SELECT /*+ LABEL(GX_IRIS_SYNC_DIM_DATA)*/ ANALYZE_STATISTICS('{self._common_schema}.STAGE_{self._dim_product}');

        INSERT /*+ DIRECT, LABEL(GX_IRIS_SYNC_DIM_DATA)*/ INTO TEMP_OSM_SUB_CATEGORY_CONSISTENCY
        SELECT a.OSM_SUB_CATEGORY_NO, MAX(a.OSM_SUB_CATEGORY) AS OSM_SUB_CATEGORY
        FROM {self._common_schema}.STAGE_{self._dim_product} a
        LEFT JOIN TEMP_OSM_SUB_CATEGORY_CONSISTENCY b on a.OSM_SUB_CATEGORY_NO = b.OSM_SUB_CATEGORY_NO
        WHERE a.OSM_SUB_CATEGORY_NO IS NOT NULL AND a.OSM_SUB_CATEGORY_NO <> '' AND b.OSM_SUB_CATEGORY_NO IS NULL
        GROUP BY a.OSM_SUB_CATEGORY_NO;

        UPDATE /*+ LABEL(GX_IRIS_SYNC_DIM_DATA)*/ {self._common_schema}.STAGE_{self._dim_product}
        SET OSM_SUB_CATEGORY = b.OSM_SUB_CATEGORY
        FROM 
        (SELECT * FROM TEMP_OSM_SUB_CATEGORY_CONSISTENCY) b
        WHERE {self._common_schema}.STAGE_{self._dim_product}.OSM_SUB_CATEGORY_NO = b.OSM_SUB_CATEGORY_NO;
        /*UPDATE {self._common_schema}.STAGE_{self._dim_product}
        SET ITEM_GROUP = B.ITEM_GROUP
        FROM $schemaName.OLAP_ITEM B
        WHERE {self._common_schema}.STAGE_{self._dim_product}.ITEM_KEY = B.ITEM_KEY;*/

        INSERT /*+ DIRECT, LABEL(GX_IRIS_SYNC_DIM_DATA)*/ INTO TEMP_OSM_MAJOR_CATEGORY_CONSISTENCY
        SELECT a.OSM_MAJOR_CATEGORY_NO, MAX(a.OSM_MAJOR_CATEGORY) AS OSM_MAJOR_CATEGORY
        FROM {self._common_schema}.STAGE_{self._dim_product} a
        LEFT JOIN TEMP_OSM_MAJOR_CATEGORY_CONSISTENCY b on a.OSM_MAJOR_CATEGORY_NO = b.OSM_MAJOR_CATEGORY_NO
        WHERE a.OSM_MAJOR_CATEGORY_NO IS NOT NULL AND a.OSM_MAJOR_CATEGORY_NO <> '' AND b.OSM_MAJOR_CATEGORY_NO IS NULL
        GROUP BY a.OSM_MAJOR_CATEGORY_NO;

        UPDATE /*+ LABEL(GX_IRIS_SYNC_DIM_DATA)*/ {self._common_schema}.STAGE_{self._dim_product}
        SET OSM_MAJOR_CATEGORY = b.OSM_MAJOR_CATEGORY
        FROM 
        (SELECT * FROM TEMP_OSM_MAJOR_CATEGORY_CONSISTENCY) b
        WHERE {self._common_schema}.STAGE_{self._dim_product}.OSM_MAJOR_CATEGORY_NO = b.OSM_MAJOR_CATEGORY_NO;
        """.format(self=self))
        self._logger.info(sql)
        self._dw.execute(sql)

    def _load_store_data_cis(self, hub_id):
        """
        Sync data from CIS source.
        # if the same store_key exists in CIS and NXG HUBs, the CIS one should override the one in NXG side.
        :param hub_id:
        :return:
        """

        # dump CIS data into cis staging table: stage_dim_store_cis
        self._export_store_data(hub_id=hub_id, cis_source=True)

        # # Override nxg stores with CIS if there are duplicated items on both NXG and CIS
        sql = """
        DELETE FROM {cmnSchema}.STAGE_{storeTable} 
        WHERE (vendor_key, retailer_key, store_key) 
        IN (SELECT vendor_key, retailer_key, store_key 
            FROM {cmnSchema}.STAGE_{storeTable}_CIS );
        
        INSERT INTO {cmnSchema}.STAGE_{storeTable}  
        SELECT * FROM {cmnSchema}.STAGE_{storeTable}_CIS;
        """.format(storeTable=self._dim_store,
                   cmnSchema=self._common_schema)
        self._logger.info(sql)
        self._dw.execute(sql)

    def _swap_data(self):
        """
        Switch partition from stage table to final table.
        :return:
        """

        sql = ("SELECT /*+ LABEL(GX_IRIS_SYNC_DIM_DATA)*/ DISTINCT VENDOR_KEY "
               "FROM {self._common_schema}.STAGE_{self._dim_product}".format(self=self))
        self._logger.debug(sql)
        for row in self._dw.query(sql):
            self._dw.switch_partition(schema_name=self._common_schema, table_name=self._dim_product,
                                      partition_name=row[0], stage_schema_name=self._common_schema,
                                      stage_table_name='STAGE_{self._dim_product}'.format(self=self))

        sql = ("SELECT /*+ LABEL(GX_IRIS_SYNC_DIM_DATA)*/ DISTINCT VENDOR_KEY "
               "FROM {self._common_schema}.STAGE_PRODUCT".format(self=self))
        self._logger.debug(sql)
        for row in self._dw.query(sql):
            self._dw.switch_partition(schema_name=self._common_schema, table_name='PRODUCT', partition_name=row[0],
                                      stage_schema_name=self._common_schema, stage_table_name='STAGE_PRODUCT')

        sql = ("SELECT /*+ LABEL(GX_IRIS_SYNC_DIM_DATA)*/ DISTINCT RETAILER_KEY "
               "FROM {self._common_schema}.STAGE_{self._dim_store}".format(self=self))
        self._logger.debug(sql)
        for row in self._dw.query(sql):
            self._dw.switch_partition(schema_name=self._common_schema, table_name=self._dim_store,
                                      partition_name=row[0], stage_schema_name=self._common_schema,
                                      stage_table_name='STAGE_{self._dim_store}'.format(self=self))

        sql = ("SELECT /*+ LABEL(GX_IRIS_SYNC_DIM_DATA)*/ DISTINCT RETAILER_KEY "
               "FROM {self._common_schema}.STAGE_STORE".format(self=self))
        self._logger.debug(sql)
        for row in self._dw.query(sql):
            self._dw.switch_partition(schema_name=self._common_schema, table_name='STORE', partition_name=row[0],
                                      stage_schema_name=self._common_schema, stage_table_name='STAGE_STORE')

    def _process_sync_dim_data(self):
        """
        Process to sync dim data
        :return:
        """
        try:
            self._get_column()
            self._recreate_stage_table()
            for hub_id in self._hub_ids:
                try:
                    self._dim_schema = "DIM_{hub_id}".format(hub_id=hub_id)
                    self._meta_schema = "METADATA_{hub_id}".format(hub_id=hub_id)
                    self._logger.info("Sync dim data start hub_id {hub_id}".format(hub_id=hub_id))
                    self._get_source_config(hub_id)
                    self._export_calendar_data(hub_id)
                    self._get_vendor_retailer_from_hub(hub_id)

                    if not self._str_vendor_retailer_filter:
                        self._logger.warning("hub_id {} does not have any matched product and store data".format(hub_id))
                        continue

                    self._export_product_data(hub_id)
                    self._export_store_data(hub_id)

                    # handle CIS source.
                    self._load_product_data_cis(hub_id)
                    self._load_store_data_cis(hub_id)

                    self._logger.info("Sync hub_id {hub_id} dim data to stage table.".format(hub_id=hub_id))
                except Exception as msg:
                    self._logger.warning(msg)
                    continue

            self._swap_data()
            # self._truncate_stage_table()
            self._logger.info("Sync dim data done from hubs {hub_ids}".format(hub_ids=self._hub_ids))
            self._analyze_table()
        except Exception as msg:
            self._logger.error(msg)
        finally:
            pass

    def process(self):
        try:
            self._process_sync_dim_data()

        except Exception as e:
            self._logger.error(e)

        finally:
            if hasattr(self, "_dw"):
                self._dw.close_connection()
            if hasattr(self, "_source_dw"):
                self._source_dw.close_connection()
            if hasattr(self, "_db"):
                self._db.close_connection()


class SyncDimDataNanny(SyncDimData):

    def __init__(self, meta, request_body, logger=None):
        logger = logger if logger else Logger(log_level="info", vendor_key=-1, retailer_key=-1,
                                              module_name="syncDimDataNanny")
        logger.set_keys(log_id="{}_{}".format(request_body["jobId"], request_body["stepId"]))
        logger.debug(request_body)
        request_body["header"] = {"Content-Type": "application/json", "module_name": logger.format_dict["module_name"]}
        request_body["log_level"] = request_body.get("log_level", 20)
        logger.set_level(request_body["log_level"])
        request_body["dw_conn_vertica"] = request_body.get("dwConnVertica", False)
        request_body["all_dim"] = request_body.get("allDim", False)
        if request_body.get("hubIDs"):
            request_body["hub_ids"] = eval(request_body.get("hubIDs"))
        else:
            request_body["hub_ids"] = requests.get("{}/hubs".format(meta["api_config_str"])).json()

        SyncDimData.__init__(self, {**request_body, **{"meta": meta}, **{"logger": logger}})


class SyncDimDataHandler(MasterHandler):

    def set_service_properties(self):
        self.service_name = 'syncDimDataNanny'


class SyncDimDataApp(App):
    '''
    This class is just for testing, osa_bundle triggers it somewhere else
    '''

    def __init__(self, meta):
        App.__init__(self, meta=meta, service_bundle_name='syncDimDataNanny')


if __name__ == '__main__':
    # import configparser
    # from log.logger import Logger
    # with open("{}/../../../config/config.properties".format(sys.argv[0])) as fp:
    #    cp = configparser.ConfigParser()
    #    cp.read_file(fp)
    #    meta = dict(cp.items("DEFAULT"))
    # body = {"jobId": 234567890, "stepId": 1, "body": "Sync dim calendar done", "meta": meta,
    #        "hub_ids": ['HUB_FUNCTION_MB', 'HUB_FUNCTION_BETA'], "dw_conn_vertica": False, "all_dim": False}
    # log_file = "{}_{}.log".format(sys.argv[0], body['hub_ids'])
    # body["logger"] = Logger(log_level="INFO", target="console|file", module_name="sdd_service", log_file=log_file)
    ## sdd = SDDWrapper(meta=meta)
    ## sdd.on_action({"body": "Sync Dim Data done"})
    # s = SyncDimData(body)
    # s.process()
    """
    Handle Sync Dim Data by HTTP POST request
    http://localhost:7890/osa/syncDimData/process
    POST body like
    {
        "jobId": 234567890,
        "stepId": 1,
        "batchId": 1,
        "retry": 0,
        "groupName": 22,
        "dwConnVertica": false,
        "allDim": false,
        "hubIDs": "['HUB_FUNCTION_BETA', 'HUB_FUNCTION_MB']",
        "log_level": 20
    }
    dwConnVertica: optional - [true | false(default)] True will copy data from Vertica to Vertica, else exchange by file
    allDim: optional - [true | false(default)] True will get all dim data, else only those set in AP_ALERT_CYCLE_MAPPING
    hubIDs: optional - ignore this will get hubs from service {api_config_str}/hubs
    log_level: optional - default 20 AS Info, refer logging level
    """
    import os
    import datetime

    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + '..' + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    exec(open(generic_main_file).read())

    # app = SyncDimDataApp(meta=meta)   #************* update services.json --> syncDimDataNanny.service_bundle_name to syncDimDataNanny before running the script
    # app.start_service()
    _log_file = "./log/data_sync_%s.log" % datetime.datetime.now().strftime('%Y%m%d')
    _logger = Logger(log_level="debug", target="console|file", vendor_key=-1, retailer_key=-1, log_file=_log_file)
    _context = {'jobId': 98342, 'stepId': 1, 'batchId': 0, 'retry': 0, 'groupName': '6:singleton',
                'log_level': 10,
                # 'hubIDs': "['GAHUB']"
                }
    ins = SyncDimDataNanny(meta=meta, request_body=_context, logger=_logger)
    ins.process()
