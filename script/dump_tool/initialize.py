from api.capacity_service import Capacity
import requests
from pyodbc import ProgrammingError


class Initialize(object):

    def __init__(self, context):
        self.context = context
        self.meta = self.context["meta"]
        self.params = self.context["params"]
        self.logger = self.context["logger"]
        self.dw_conn = self.context["dw_conn"]
        self.app_conn = self.context["app_conn"]

        self.alert_url = self.meta["api_alerts_str"]
        self.capacity = Capacity(meta=self.meta)

    def init_process(self):

        afm_params = self.get_afm_params()
        # generating temp table: TMP_RAW_ALERTS_INFO
        self._gen_meta_info(afm_params=afm_params)

        return afm_params

    def get_afm_params(self):
        """
        Checking the group name. it should be cycle level now.
        The group name should always be with format: $jobDefinitionID:$cycleKey  e.g. 2:7, 2:8 etc.

        :return:
        """
        _group_name_list = self.params["groupName"].split(":")
        _afm_params = {}
        _params_cnt = len(_group_name_list)

        # retailer rule.
        # groupName for the given cycle key should be: $jobDefinitionId:$cycleKey
        if _params_cnt == 2:
            _retailer_key = self._get_retailer_key(cycle_key=_group_name_list[1])
            _afm_params = {"jobDefinitionId": _group_name_list[0],
                           "cycleKey": _group_name_list[1],
                           "retailerKey": _retailer_key,
                           }

        # otherwise, wrong groupName for AFM
        else:
            self.logger.error("groupName for AFM should only have 2 parameters. "
                              "Please check table RSI_CORE_SCHEDULE for OSAAFM job.")

        self.logger.debug(_afm_params)
        return _afm_params

    def _gen_meta_info(self, afm_params):
        """
        This method will create a temp table TMP_RAW_ALERTS_INFO as filters. This is same as AFM logic,
        It is only for AFM retailer rule since multi vendors could have multi period_keys not just one.
        This method will only be called when calling via REST API.
        :param afm_params:
        :return:
        """
        sla_time = self.params.get("sla_time", None)  # params passed from AFMService
        raw_alerts_info = self.params.get("raw_alerts_info", None)  # params passed from AFMService
        _cycle_key = afm_params["cycleKey"]

        # Getting retailer key for given cycleKey by calling cyclemapping API instead of reading table directly
        _retailer_key = self._get_retailer_key(_cycle_key)

        # Vertica version
        _ddl_sql_dw = """
        DROP TABLE IF EXISTS TMP_RAW_ALERTS_INFO;
        CREATE LOCAL TEMP TABLE TMP_RAW_ALERTS_INFO
        (vendor_key int,
         retailer_key int,
         alert_day int,
         seq_num bigint
        ) ON COMMIT PRESERVE ROWS;
        """
        self.logger.info("Creating raw alerts info table for dw: %s " % _ddl_sql_dw)
        self.dw_conn.execute(_ddl_sql_dw)

        # if sla_time is None, then getting latest sla_time via cycle_key. This is mainly for testing purpose.
        if sla_time is None:
            self.logger.warning("sla_time is not given, so getting it via cycle_key:%s" % _cycle_key)
            _cycle_url = "{0}/availablecycles".format(self.alert_url)
            _headers = {"content-type": "application/json",
                        "cycle_key": _cycle_key,
                        "hour_offset": "-6"}
            self.logger.info("Calling availablecycles API(POST): %s with headers: %s" % (_cycle_url, _headers))
            resp = requests.post(url=_cycle_url, headers=_headers, verify=False)
            self.logger.debug("Result of calling availablecycles is: %s" % resp.json())
            if resp.status_code != requests.codes.ok or str(resp.json().get("status")).lower() != "success":
                self.logger.warning("The response result is: %s" % resp.json())
                self.logger.error("Calling API failed with cycle: %s. Refer to API: %s" % (_cycle_key, _cycle_url))

            _cycle_data = resp.json()["data"]
            if not _cycle_data or not _cycle_data["payload"]:
                self.logger.warning("The cycle data is: %s" % _cycle_data)
                self.logger.error(
                    "There is no data returned with cycle: %s. Refer to API: %s" % (_cycle_key, _cycle_url))

            # For given cycle_key, There should only have one element.
            _data = _cycle_data["payload"][0]
            sla_time = _data.get("sla_time_est")

        self.logger.info("The sla_time is: %s" % sla_time)

        # if no passed, then calling API to get it. This is mainly for testing purpose.
        if not raw_alerts_info:
            # Getting retailer_key, vendor_key, period_key, alert_gen_seq by calling alertgen status API.
            # This is for both SVR rule & RETAILER rule.
            self.logger.info("The alert gen status info is not passed. Getting it via API.")
            _headers = {"content-type": "application/json", "sla_time": sla_time}
            _alerts_url = "{url}/{cycle_key}/alertgen/status".format(url=self.alert_url, cycle_key=_cycle_key)
            self.logger.info("Calling alertgen status API(GET): %s with headers: %s" % (_alerts_url, _headers))
            _resp = requests.get(url=_alerts_url, headers=_headers, verify=False)
            if _resp.status_code != requests.codes.ok or str(_resp.json().get("status")).lower() != "success":
                self.logger.warning("The response result is: %s" % _resp.text)
                self.logger.error("The given cycle: %s is no available." % _cycle_key)

            self.logger.debug("Result of calling AlertGen status API is: %s" % _resp.json())

            _alert_data = _resp.json()["data"]
            if not _alert_data or not _alert_data["payload"]:
                self.logger.warning("The alert gen status info is: %s" % _alert_data)
                raise ValueError("The alertgen might not be ready at the time being "
                                 "for given sla_time: %s and cycle: %s" % (sla_time, _cycle_key))

            self.logger.info("Processing the given cycle key: %s to get vendor and retailer info" % _cycle_key)

            # Filter out the row where alert_gen_seq is None(Meaning AlertGen is not ready yet)
            _payload = _alert_data["payload"]
            _final_payload = list(filter(lambda x: x["alert_gen_seq"] is not None, _payload))
            self.logger.info("The final AlertGen status info are: %s" % _final_payload)

        else:
            _final_payload = raw_alerts_info

        # Generating tmp raw alerts info table for following processes.
        _tmp_data = " UNION ALL ".join(["SELECT {0}, {1}, {2}, {3}"
                                       .format(_tmp["vendor_key"], _retailer_key, _tmp["period_key"], _tmp["alert_gen_seq"])
                                        for _tmp in _final_payload])
        try:
            # populate app table
            _insert_sql = "INSERT INTO TMP_RAW_ALERTS_INFO {0}".format(_tmp_data)
            self.logger.info(_insert_sql)
            self.dw_conn.execute(_insert_sql)
        except ProgrammingError as e:
            self.logger.warning(e)
            raise Warning("The alert_gen_seq could be null in alert_cycle_status table."
                          "Refer to result data: %s ."
                          "And please make sure alertgen is completed successfully!" % _final_payload)

    def _get_retailer_key(self, cycle_key):
        """
        This method is getting Retailer by calling cyclemapping API.
        The API is actually reading data from AP_ALERT_CYCLE_MAPPING. Since it is not recommended to read table directly.

        :return: retailer_key
        """
        _headers = {"content-type": "application/json", "cycle_key": cycle_key}
        _cycle_map_url = "{0}/cyclemappings".format(self.alert_url)
        self.logger.info("Calling cyclemapping API(GET): %s with headers: %s" % (_cycle_map_url, _headers))
        _resp = requests.get(url=_cycle_map_url, headers=_headers, verify=False)
        # self.logger.debug("test")
        self.logger.debug("Result of calling cycle mapping API is: %s" % _resp.json())
        if _resp.status_code != requests.codes.ok or str(_resp.json().get("status")).lower() != "success":
            self.logger.warning("The response result is: %s" % _resp.json())
            self.logger.error("Getting cycle mapping failed for cycle key: %s. Please refer to API: %s"
                              % (cycle_key, _cycle_map_url))

        # There should be only one retailer_key for one cycle_key.
        if not _resp.json().get("data"):
            self.logger.warning("Calling cyclemapping status info is: %s" % _resp.json())
            raise ValueError("No data returned. Please Refer to API: %s with cycle_key: %s" % (_cycle_map_url, cycle_key))

        _data = _resp.json().get("data")[0]
        _retailer_key = _data["retailer_key"]

        return _retailer_key
