import logging
import datetime

class LogDBHandler(logging.Handler):
    """
    CREATE SEQUENCE SEQ_RSI_LOG START WITH 1 INCREMENT BY 1 NO CACHE;
    CREATE TABLE RSI_LOG (
        ID BIGINT PRIMARY KEY NOT NULL DEFAULT (NEXT VALUE FOR SEQ_RSI_LOG),
        APP_NAME VARCHAR(100),
        LOG_TIMESTAMP DATETIME,
        LOG_LEVEL VARCHAR(32),
        RECORD VARCHAR(1024),
        VENDOR_KEY INTEGER, 
        RETAILER_KEY INTEGER );
    """
    
    def __init__(self, app_name, vendor_key, retailer_key, sql_conn):
        logging.Handler.__init__(self)
        self.sql_conn = sql_conn
        self.sql_cur = sql_conn.cursor()
        self.db_table = "RSI_LOG"
        self.app_name = app_name
        self.vendor_key = vendor_key
        self.retailer_key = retailer_key
        
    def emit(self, record):
        curr_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        msg = record.msg
        msg = msg.strip()
        msg = msg.replace('\'', '\'\'')
        insert_sql = "INSERT INTO %s (APP_NAME, LOG_TIMESTAMP, LOG_LEVEL, RECORD, VENDOR_KEY, RETAILER_KEY) VALUES ('%s', '%s', '%s', '%s', '%s', '%s')" % (self.db_table, self.app_name, curr_time, record.levelname, msg, self.vendor_key, self.retailer_key)
        self.sql_cur.execute(insert_sql)
        self.sql_conn.commit()
        