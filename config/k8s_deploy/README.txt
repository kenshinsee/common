init_py_services.sh: # Initialize script to generate deploy & configmap yaml config file 


*_config: config files for remote connecting to k8s.

configmap/:     # Folder for java services configmap files.
	dev/
	local/
	qa/


py_configmap/:  # Folder for python services configmap files.
dev_python_config_properties.yml
local_python_config_properties.yml
qa_python_config_properties.yml


yml_files/:     # Folder for services deployment files .
    Python services:
        afmservice.yml
        alertgeneration.yml
        osa_bundle.yml

    Java services:
        authenticationservice.yml
        configurationservice.yml
        jobservice.yml
        osaalertservice.yml
        osacoreservice.yml
        provisionservice.yml
        scheduleservice.yml
        usermetadataservice.yml
