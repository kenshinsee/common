from db.sync_data import sync_data


# TransferData.ps1
class TransferData(object):

    def __init__(self, dct_sync_data):
        self.logger = dct_sync_data['logger']
        self._dw = dct_sync_data["target_osa_conn"]

    def transfer_data(self, dct_sync_data):

        try:
            self.logger.info("Loading Data from RDP cluster")
            _table_name = dct_sync_data["target_dw_table"]
            _schema_name = dct_sync_data["target_dw_schema"]
            # Commented out below export statement.
            # Since it might not work from one side direct connect to another side. (e.g. dw silo to cloud)
            # sql = "EXPORT TO VERTICA {dbName}.{schemaName}.{tableName} ({insertQuery}) AS ({fetchQuery})"\
            #     .format(dbName='fusion',
            #             schemaName=schema_name,
            #             tableName=table_name,
            #             insertQuery=target_column,
            #             fetchQuery=fetch_query)
            # self.logger.info(sql)
            # # dct_sync_data["source_dw"].execute(sql)
            # transferred_records = dct_sync_data["source_dw"].query(sql).rowcount
            sync_data(dct_sync_data=dct_sync_data)

            _sql = "SELECT /*+ label(GX_IRIS_SYNCFEEDBACK)*/ COUNT(*) FROM {schemaName}.{tableName}"\
                .format(schemaName=_schema_name, tableName=_table_name)
            self.logger.info(_sql)
            transferred_records = self._dw.query_scalar(_sql)

            return transferred_records

        except Exception as e:
            self.logger.warning(e)
            raise
        finally:
            pass

