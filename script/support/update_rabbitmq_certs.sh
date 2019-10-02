#!/bin/bash

# STEPS
# 1.  [manual DevOps] Generate new certificates
# 2.  [manual Engineering] Developer updates configmap and check-in to stash
# 3.  [manual DevOps] Pull the latest code from stash
# 4.  [DevOps] make sure the server ssl directory/file names are aligned with the code
#    o  server_rabbitmq_ssl_dir="/etc/rabbitmq/ssl"
#    o  target_key_pem="$server_rabbitmq_ssl_dir/key.pem"
#    o  target_cert_pem="$server_rabbitmq_ssl_dir/cert.pem"
#    o  target_cacert_pem="$server_rabbitmq_ssl_dir/cacert.pem"
# 5.  [DevOps] make sure the newly generated certificates directory/file names are aligned with the code
#    o  cert_dir='.'
#    o  cert_client_dir="$cert_dir/client"
#    o  cert_server_dir="$cert_dir/server"
#    o  cert_testca_dir="$cert_dir/testca"
#    o  new_client_key_pem="$cert_client_dir/key.pem"
#    o  new_client_cert_pem="$cert_client_dir/cert.pem"
#    o  new_server_key_pem="$cert_server_dir/key.pem"
#    o  new_server_cert_pem="$cert_server_dir/cert.pem"
#    o  new_cacert_pem="$cert_testca_dir/cacert.pem"
# 6.  [DevOps] execute
#    o   sh ./update_rabbitmq_certs.sh -d /home/hong.hu/osa_backend/common/config/k8s_deploy/configmap/${env}

configmap_dir=

while getopts ":d:" opt
do
    case $opt in
        d)
        configmap_dir=$OPTARG;;
        ?)
        echo "Unknown option -$OPTARG."
        exit 1;;
    esac
done

function validate_configmap_dir() {
    if [ -z $configmap_dir ]
    then
        echo "Please execute the script with -d {configmap_dir}"
        exit 1
    elif [ ! -e $configmap_dir ]
    then
        echo "$configmap_dir doesn't exist."
        exit 1
    fi
}

server_rabbitmq_ssl_dir=
target_key_pem=
target_cert_pem=
target_cacert_pem=
cert_dir=
cert_client_dir=
cert_server_dir=
cert_testca_dir=
new_client_key_pem=
new_client_cert_pem=
new_server_key_pem=
new_server_cert_pem=
new_cacert_pem=

function set_certs_location() {
    server_rabbitmq_ssl_dir="/etc/rabbitmq/ssl"
    target_key_pem="$server_rabbitmq_ssl_dir/key.pem"
    target_cert_pem="$server_rabbitmq_ssl_dir/cert.pem"
    target_cacert_pem="$server_rabbitmq_ssl_dir/cacert.pem"

    if [ ! -e $target_key_pem ]
    then
        echo "$target_key_pem doesn't exist."
        exit 1
    fi

    if [ ! -e $target_cert_pem ]
    then
        echo "$target_cert_pem doesn't exist."
        exit 1
    fi

    if [ ! -e $target_cacert_pem ]
    then
        echo "$target_cacert_pem doesn't exist."
        exit 1
    fi

    cert_dir='.'
    cert_client_dir="$cert_dir/client"
    cert_server_dir="$cert_dir/server"
    cert_testca_dir="$cert_dir/testca"
    new_client_key_pem="$cert_client_dir/key.pem"
    new_client_cert_pem="$cert_client_dir/cert.pem"
    new_server_key_pem="$cert_server_dir/key.pem"
    new_server_cert_pem="$cert_server_dir/cert.pem"
    new_cacert_pem="$cert_testca_dir/cacert.pem"

    if [ ! -e $new_client_key_pem ]
    then
        echo "$new_client_key_pem doesn't exist."
        exit 1
    fi

    if [ ! -e $new_client_cert_pem ]
    then
        echo "$new_client_cert_pem doesn't exist."
        exit 1
    fi
    
    if [ ! -e $new_server_key_pem ]
    then
        echo "$new_server_key_pem doesn't exist."
        exit 1
    fi

    if [ ! -e $new_server_cert_pem ]
    then
        echo "$new_server_cert_pem doesn't exist."
        exit 1
    fi

    if [ ! -e $new_cacert_pem ]
    then
        echo "$new_cacert_pem doesn't exist."
        exit 1
    fi
}

function renew_server_certs() {
    set_certs_location
    # backup
    cp $target_key_pem ${target_key_pem}_`date +%Y%m%d` || { echo "backup $target_key_pem failed"; exit 1; }
    cp $target_cert_pem ${target_cert_pem}_`date +%Y%m%d` || { echo "backup $target_cert_pem failed"; exit 1; }
    cp $target_cacert_pem ${target_cacert_pem}_`date +%Y%m%d` || { echo "backup $target_cacert_pem failed"; exit 1; }
    echo "Backup done."
    # renew
    cp $new_server_key_pem $target_key_pem || { echo "renew $target_key_pem failed"; exit 1; }
    cp $new_server_cert_pem $target_cert_pem || { echo "renew $target_cert_pem failed"; exit 1; }
    cp $new_cacert_pem $target_cacert_pem || { echo "renew $target_cacert_pem failed"; exit 1; }
    chmod 755 $target_key_pem || { echo "chmod $target_key_pem failed"; exit 1; }
    chmod 755 $target_cert_pem || { echo "chmod $target_cert_pem failed"; exit 1; }
    chmod 755 $target_cacert_pem || { echo "chmod $target_cacert_pem failed"; exit 1; }
    echo "Renew done."
    # restart service
    systemctl restart rabbitmq-server || { echo "restart rabbitmq-server failed"; exit 1; }
    echo "Restart service done."
}

function update_rsicommon_namespace() {
    validate_configmap_dir
    namespace="rsicommon"
    kubectl -n $namespace create configmap systemconf --from-file=$configmap_dir --dry-run -o yaml | kubectl replace -f -
}

function update_osa_suite_namespace() {
    validate_configmap_dir
    namespace="osa-suite"
    kubectl -n $namespace create configmap systemconf --from-file=$configmap_dir --dry-run -o yaml | kubectl replace -f -
}

function restart_rsicommon_pods() {
    namespace="rsicommon"
    services="scheduleservice jobservice"
    for service in $services
    do
        kubectl -n $namespace get pods | grep $service | awk '{print $1}' | xargs -i kubectl -n $namespace delete pod {}
    done
}

function restart_osa_suite_pods() {
    namespace="osa-suite"
    services="deploy osabundle alertgeneration afmservice scorecard osacoreservice provisionservice osaalertservice"
    for service in $services
    do
        kubectl -n $namespace get pods | grep $service | awk '{print $1}' | xargs -i kubectl -n $namespace delete pod {}
    done
}

function check_cert_correctness() {
    # make sure the certs in repository and the newly generated certs are identical
    validate_configmap_dir
    set_certs_location
    repo_key_pem="$configmap_dir/key.pem"
    repo_cert_pem="$configmap_dir/cert.pem"
    repo_cacert_pem="$configmap_dir/cacert.pem"
    repo_keycert_p12_encode="$configmap_dir/keycert.p12.encode"
    repo_rabbitstore_encode="$configmap_dir/rabbitstore.encode"
    
    md5_repo_key_pem=`cat $repo_key_pem | md5sum`
    md5_new_client_key_pem=`cat $new_client_key_pem | md5sum`
    if [ "$md5_repo_key_pem" != "$md5_new_client_key_pem" ]
    then
        echo "key.pem are not identical."
        echo "md5_repo_key_pem: $md5_repo_key_pem"
        echo "md5_new_client_key_pem: $md5_new_client_key_pem"
        exit 1
    else
        echo "key.pem are identical."
    fi
    
    md5_repo_cert_pem=`cat $repo_cert_pem | md5sum`
    md5_new_client_cert_pem=`cat $new_client_cert_pem | md5sum`
    if [ "$md5_repo_cert_pem" != "$md5_new_client_cert_pem" ]
    then
        echo "cert.pem are not identical."
        echo "md5_repo_cert_pem: $md5_repo_cert_pem"
        echo "md5_new_client_cert_pem: $md5_new_client_cert_pem"
        exit 1
    else
        echo "cert.pem are identical."
    fi
    
    md5_repo_cacert_pem=`cat $repo_cacert_pem | md5sum`
    md5_new_cacert_pem=`cat $new_cacert_pem | md5sum`
    if [ "$md5_repo_cacert_pem" != "$md5_new_cacert_pem" ]
    then
        echo "cacert.pem are not identical."
        echo "md5_repo_cacert_pem: $md5_repo_cacert_pem"
        echo "md5_new_cacert_pem: $md5_new_cacert_pem"
        exit 1
    else
        echo "cacert.pem are identical."
    fi
    
    #//////////// everytime run the below, the results are different
    #md5_repo_keycert_p12_encode=`cat $repo_keycert_p12_encode | md5sum`
    #keycert_p12_tmp="./keycert.p12.tmp"
    #cmd="openssl pkcs12 -export -out $keycert_p12_tmp -in $new_client_cert_pem -inkey $new_client_key_pem -passout pass:T3ciT3ci2"
    #echo $cmd
    #eval $cmd || { echo "generate $keycert_p12_tmp failed"; exit 1; }
    #new_keycert_p12_tmp_encode="./keycert.p12.tmp.encode"
    #base64 $keycert_p12_tmp > $new_keycert_p12_tmp_encode
    #md5_new_keycert_p12_tmp_encode=`cat $new_keycert_p12_tmp_encode | md5sum`
    #if [ "$md5_repo_keycert_p12_encode" != "$md5_new_keycert_p12_tmp_encode" ]
    #then
    #    echo "keycert.p12 are not identical."
    #    echo "md5_repo_keycert_p12_encode: $md5_repo_keycert_p12_encode"
    #    echo "md5_new_keycert_p12_tmp_encode: $md5_new_keycert_p12_tmp_encode"
    #    exit 1
    #else
    #    echo "keycert.p12 are identical."
    #fi
    
    #//////////// everytime run the below, the results are different
    #md5_repo_rabbitstore_encode=`cat $repo_rabbitstore_encode | md5sum`
    #rabbitstore_tmp="./rabbitstore.tmp"
    #cmd="yes | keytool -import -alias server1 -file $new_server_cert_pem -keystore $rabbitstore_tmp -storepass T3ciT3ci2"
    #echo $cmd
    #eval $cmd || { echo "generate $rabbitstore_tmp failed"; exit 1; }
    #new_rabbitstore_tmp_encode="./rabbitstore.tmp.encode"
    #base64 $rabbitstore_tmp > $new_rabbitstore_tmp_encode
    #md5_new_rabbitstore_tmp_encode=`cat $new_rabbitstore_tmp_encode | md5sum`
    #if [ "$md5_repo_rabbitstore_encode" != "$md5_new_rabbitstore_tmp_encode" ]
    #then
    #    echo "rabbitstore are not identical."
    #    echo "md5_repo_rabbitstore_encode: $md5_repo_rabbitstore_encode"
    #    echo "md5_new_rabbitstore_tmp_encode: $md5_new_rabbitstore_tmp_encode"
    #    exit 1
    #else
    #    echo "rabbitstore are identical."
    #fi
}

function main() {
    check_cert_correctness
    renew_server_certs
    update_rsicommon_namespace
    update_osa_suite_namespace
    restart_rsicommon_pods
    restart_osa_suite_pods
}

main

