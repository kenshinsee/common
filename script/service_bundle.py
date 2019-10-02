#!/usr/bin/python
# coding=utf-8

import os
from agent.app import App


class OSABundle(App):

    def __init__(self, meta):
        App.__init__(self, meta=meta, service_bundle_name='osa_bundle')
    
    
if __name__ == '__main__':

    SEP = os.path.sep
    cwd = os.path.dirname(os.path.realpath(__file__))
    generic_main_file = cwd + SEP + 'main.py'
    CONFIG_FILE = cwd + SEP + '..' + SEP + 'config' + SEP + 'config.properties'
    exec(open(generic_main_file).read())

    # meta is ready to use

    osabundle = OSABundle(meta)
    osabundle.start_service()
