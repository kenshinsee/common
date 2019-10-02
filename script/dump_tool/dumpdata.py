import pandas
import csv
import os


class DumpData(object):

    def __init__(self, context):
        self.context = context
        self.meta = self.context["meta"]
        self.logger = self.context["logger"]
        self.dw_conn = self.context["dw_conn"]
        self.app_conn = self.context["app_conn"]

    def dump_data(self, src_sql, output_file, header=True, delimiter=None):
        self.logger.info("Start to dump data...")
        _delimiter = ',' if (delimiter is None or delimiter == '') else delimiter
        self.logger.debug("The source sql is: %s" % src_sql)

        _sql = 'SELECT COUNT(*) FROM ({query}) x'.format(query=src_sql)
        self.logger.info(_sql)
        _row_cnt = self.dw_conn.query_scalar(_sql)
        self.logger.info("The row count is: %s" % _row_cnt)
        if _row_cnt == 0:
            self.logger.warning("There is no data returned from source sql: %s" % _sql)
            return False

        # self.dump_with_csv(src_sql, output_file, header, delimiter)
        self.dump_with_pandas(src_sql=src_sql, output_file=output_file, header=header, delimiter=delimiter)

        return True

    def dump_with_pandas(self, src_sql, output_file, header=True, delimiter=','):
        # Using pandas to dump data as a default option.
        self.logger.info("Dumping data with pandas...")
        df = pandas.read_sql_query(src_sql, self.dw_conn.get_connection())
        df.to_csv(output_file, sep=delimiter, header=header, index=False)
        self.logger.info("Dumping data with pandas completes...")

    @DeprecationWarning
    def dump_with_csv(self, src_sql, output_file, header='', delimiter=','):
        # if the source sql is returning big volume of data, the pyodbc will be having issue. So deprecate this method.
        result = self.dw_conn.query(src_sql)
        with open(output_file, 'w', newline='', encoding='UTF-8') as f:
            writer = csv.writer(f, delimiter=delimiter)
            # header = ['vendor_key', 'item_key', 'upc']
            header = [str.strip(f) for f in header.split(',')]
            writer.writerow(header)
            for row in result:
                writer.writerow(row)

