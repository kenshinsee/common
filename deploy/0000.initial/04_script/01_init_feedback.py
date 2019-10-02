from optparse import OptionParser
import json, os
from log.logger import Logger
from SyncFeedbackFromRDP import Feedback


host = None
parse = OptionParser()
parse.add_option("--retailer_key", action="store", dest="retailer_key")
parse.add_option("--vendor_key", action="store", dest="vendor_key")
parse.add_option("--meta", action="store", dest="meta")
parse.add_option("--debug", action="store", dest="debug")
(options, args) = parse.parse_args()

meta = json.loads(options.meta)
logger = Logger(log_level="info", target="console", vendor_key=options.vendor_key, retailer_key=options.retailer_key)
# logger = Logger(log_level="debug", target="console", vendor_key=684, retailer_key=158)   # testing


def trigger_init_feedback(meta, vendor_key, retailer_key, debug='N'):
    """
    feedback data for some vendor&retailers was stored in RDP side.
    And they are required by AFM & Scorecard. So we need to sync RDP feedback to OSA DW Cluster.
    We are having routing process to sync whole RDP data.
    Here this process only takes care about new customer with below parameters
    :param meta: used for connection
    :param vendor_key: vendor key for new customer (mandatory)
    :param retailer_key: retailer key for new customer (mandatory)
    :param debug:
    :return:

    Sample URL to call this script:
    http://localhost:8000/osa_bundle/deploy/0000.initial/03_script?vendor_key=684&retailer_key=158&mode=run
    """

    try:
        params = {"vendor_key": vendor_key,
                  "retailer_key": retailer_key,
                  "debug": debug
                  }
        run_init = Feedback(meta=meta,
                            params=params,
                            init_flag=True,
                            logger=logger)
        run_init.main_process()

    except Exception as msg:
        logger.warning(msg)
        raise

    finally:
        pass


if __name__ == '__main__':
    try:
        logger.info("Trying to sync feedback data from RDP for vendor:{0} and retailer:{1}"
                    .format(options.vendor_key, options.retailer_key))

        # getting meta
        # SEP = os.path.sep
        # cwd = os.path.dirname(os.path.realpath(__file__))
        # generic_main_file = cwd + SEP + '..' + SEP + '..' + SEP + '..' + SEP + 'script' + SEP + 'main.py'
        # CONFIG_FILE = cwd + SEP + '..' + SEP + '..' + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
        # exec(open(generic_main_file).read())
        # trigger_init_feedback(meta=meta, vendor_key=684, retailer_key=158, debug='Y')  # testing

        trigger_init_feedback(meta=meta, vendor_key=options.vendor_key, retailer_key=options.retailer_key)

    finally:
        pass
