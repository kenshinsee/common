import os,re,sys
from optparse import OptionParser
from distutils.sysconfig import get_python_lib
from optparse import OptionParser
import json

# this module we don't need pass in any parameter values, 
# to have OptionParser here is just to match the format of interface
parse = OptionParser()
parse.add_option("--retailer_key", action="store", dest="retailer_key")
parse.add_option("--vendor_key", action="store", dest="vendor_key")
parse.add_option("--meta", action="store", dest="meta")
(options, args) = parse.parse_args()


SEP = os.path.sep
lib_dir = get_python_lib()


def install_pth(pth_file_name, file_content):
    if not os.path.exists(pth_file_name):
        print("Start to install " + pth_file_name)
        with open(pth_file_name,'w') as fh:
            fh.write(file_content + '\n')
        print(">>" + file_content)
        print(pth_file_name + " has been installed successfully.")
    else:
        print(pth_file_name + " already exists.")
    
    
osa_backend_base_dir = os.path.dirname(os.path.realpath(__file__)) + SEP + ".." + SEP + ".." + SEP + ".." + SEP + ".." 
service_file = osa_backend_base_dir + SEP + 'common' + SEP + 'config' + SEP + 'services.json'

with open(service_file) as f:
    services = json.load(f)

for service in services:
    pth_file_name = lib_dir + SEP + 'osa_backend_' + service + '.pth'
    if 'base_dir' in services[service]:
        content = osa_backend_base_dir + SEP + SEP.join(services[service]['base_dir'].split('/'))
        install_pth(pth_file_name, content)
    
