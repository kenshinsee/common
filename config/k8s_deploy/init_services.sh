#!/usr/bin/env bash

# global variables
SCRIPT_PATH=$(cd $(dirname $(readlink -f "${BASH_SOURCE[0]}")) && pwd )
PROCESS_NAME=$0
OLD_IMAGE_NAME=
OLD_NS_NAME=

# arguments
ENV=
SVC_NAME=
IMAGE_NAME=
NS_NAME=
UPDATE_FLAG=false

# config file
KUBE_CONFIG=
DEPLOY_YML_FILE=

# error code
INVALID_ARGS=1
APPLY_ERROR=2
MULTI_TYPE_FOUND=3
WRONG_SVC_NAME=4


function help() {
    echo "This script is to update the deployment file for all services in K8s."
    echo ""
    echo "Usage:
    init_py_services.sh <flags> [options]
    "
    echo "Flags:
    -e, --env          environment [qa, dev, local]
    -s, --service      servicename to be created [e.g. afmservice, alertgeneration]
    "
    echo "Options:
    -i, --image        new image name to be updated and with tag. [e.g. afmservice:v1.4]
    -n, --namespace    the namespace which the service will be created in
    -u, --update       update object if exists [default: false]
    "
    echo "Help:
    -l, --list         list all available services
    -h, --help         show usage
    "
    echo "Examples:
    # update image for afmservice in qa environment
    init_py_services.sh --env qa --service afmservice --image afmservice:1.4

    # update image & namespace for afmservice in qa environment
    init_py_services.sh -e qa -s afmservice -i afmservice:1.4 -n osa-suite-qa"
}

function show_help() {
    echo "use \"$0 -h\" for the usage."
}

function set_env() {
    # pip install shyaml
    echo "kube config file is: ${1}. Exporting KUBECONFIG to this file."
    export KUBECONFIG="$SCRIPT_PATH"/kubeconfig/${1}
    env |grep KUBECONFIG
}

# getting available services according to existing services config files.
function list_services(){
    echo "Available services are list as below:"
    ls -1 "$SCRIPT_PATH"/yml_files/*.y*ml |awk -F/ '{print $NF}' | awk -F. '{print $1}'
}

# integrate python & java configmap
# apply python configmap. 2 arguments here
# arg1: namespace [e.g. osa-suite, rsicommon]
# arg2: env [e.g. qa, dev]
#function apply_py_configmap() {
#    local l_env=$1
#    local l_ns=$2
#    echo "Started applying python configmap in namespace ${l_ns} under environment ${l_env}..."
#
#    kubectl -n "$l_ns" create configmap py-config-properties --from-file=config.properties="$SCRIPT_PATH"/py_configmap/"${l_env}"_config.properties
#
#    if [[ $? -ne 0 ]]; then
#
#        if [[ "$UPDATE_FLAG" == true ]]; then
#            # echo "WARNING: Creating python configmap $1 failed. The configmap might already exists."
#            echo "Trying to issue the replace command to see if this works."
#            # kubectl replace -f ${1}
#            kubectl -n "$l_ns" create configmap py-config-properties --from-file=config.properties="$SCRIPT_PATH"/py_configmap/"${l_env}"_config.properties --dry-run -o yaml |kubectl replace -f -
#            if [ $? -ne 0 ]; then
#                echo "ERROR: Still failed with replace command. Please check line $(($LINENO-2))"
#                exit ${APPLY_ERROR}
#            fi
#        else
#            echo "ERROR: Failed with create command. Please check line $(($LINENO-14)). If configmap already exists, Try adding \"-u true\" argument to replace it."
#            exit $APPLY_ERROR
#        fi
#
#    fi
#
#    echo "Applying python configmap into K8s successfully"
#}

# apply configmap. 2 arguments here
# arg1: namespace [e.g. osa-suite, rsicommon]
# arg2: env [e.g. qa, dev]
function apply_configmap() {
    local l_env=$1
    local l_ns=$2
    echo "Started applying configmap in namespace $l_ns under environment ${l_env}..."

    kubectl -n "$l_ns" create configmap systemconf --from-file="$SCRIPT_PATH"/configmap/"$l_env"

    if [[ $? -ne 0 ]]; then

        if [[ "$UPDATE_FLAG" == true ]]; then
            echo "Trying to issue the replace command to see if this works."
            #kubectl replace -f ${1}
            kubectl -n "$l_ns" create configmap systemconf --from-file="$SCRIPT_PATH"/configmap/"$l_env" --dry-run -o yaml |kubectl replace -f -
            if [ $? -ne 0 ]; then
              echo "ERROR: Still failed with replace command. Please check line $(($LINENO-2))"
              exit ${APPLY_ERROR}
            fi
        else
            echo "ERROR: Failed with create command. Please check line $(($LINENO-14)).
            If the configmap already exists, Try adding \"-u true\" argument to replace it."
            echo "Continue the remaining processes..."
            # exit ${APPLY_ERROR}
        fi

    else
        echo "Applying configmap into K8s successfully"

    fi
}

# Getting current image name from given yaml file.
# e.g. line: "image: rsiiris/iris:afmservice-129_uat_azure". getting "rsiiris/iris:afmservice-129_uat_azure"
# usage: get_old_image $file_name
# todo2done: considering removing "image:" to get image name instead of using awk -F
function get_old_image() {
    local l_yml_file=$1
    local tmp_image
    local tmp_image_all
    local cnt=0

    while read line
    do
        new_line=`echo ${line} | sed 's/ \+//g'`
        # echo ${new_line}
        if [[ ${new_line} == *image:* ]]; then
            #echo ${new_line}
            #tmp_image=`echo ${new_line} |awk -F: '{print $2":"$3}'`
            tmp_image=`echo ${new_line#*image:}`
            if [[ ${tmp_image} == alpine* || ${tmp_image} == busybox* ]]; then
                echo "INFO: yml file might includes initContainers process."
            else
                if [[ ${OLD_IMAGE_NAME} =~ ${tmp_image} ]]; then
                    echo "Same image ${tmp_image} found."
                else
                    OLD_IMAGE_NAME=${tmp_image}
                    ((cnt+=1))
                    tmp_image_all=${tmp_image},${tmp_image_all}
                fi
            fi
        fi
    done < ${l_yml_file}

    if [ ${cnt} -gt 1 ]; then
        echo "WARNING: There are multi different images found in yml file: ${DEPLOY_YML_FILE}. Please double confirm."
        echo "Images are: ${tmp_image_all}"
        exit ${MULTI_TYPE_FOUND}
    fi

}

# Getting current namespace name from given yaml file.
# e.g. line: " namespace: osa-suite". getting osa-suite
# usage: get_old_ns $file_name
function get_old_ns() {
    local l_yml_file=$1
    local tmp_ns
    local tmp_ns_all

    while read line
    do
        new_line=`echo ${line} | sed 's/ \+//g'`
        if [[ ${new_line} == *namespace:* ]]; then
            #tmp_ns=`echo ${new_line} |awk -F: '{print $2}'`
            tmp_ns=`echo ${new_line#*namespace:}`
            if [[ ${tmp_ns} == kube* || ${tmp_ns} == default* || ${tmp_ns} == ingress* ]]; then
                echo "INFO: KUBE* or default or ingress namespaces found."
            else
                if [[ ${OLD_NS_NAME} =~ ${tmp_ns} ]]; then
                    echo "Same namespace ${tmp_ns} found."
                else
                    OLD_NS_NAME=${tmp_ns}
                    ((cnt+=1))
                    tmp_ns_all=${tmp_ns},${tmp_ns_all}
                fi
            fi
            OLD_NS_NAME=${tmp_ns}
        fi
    done < ${l_yml_file}

    if [ ${cnt} -gt 1 ]; then
        echo "WARNING: There are multi different namespaces found in yml file: ${DEPLOY_YML_FILE}. Please double confirm."
        echo "Namespaces are: ${tmp_ns_all}"
        exit ${MULTI_TYPE_FOUND}
    fi
}

# update previous value with new value.
# usage: update_yaml_file $yml_file
function update_yaml_file() {
    local l_yml_file=$1
    echo "Started to update yaml file ${l_yml_file}..."
    echo "New image name is: ${IMAGE_NAME} & New namespace name is: ${NS_NAME}."

    if [ -n "${NS_NAME}" ]; then
        get_old_ns ${l_yml_file}
        echo "Old namespace is: ${OLD_NS_NAME}"
        echo "s#${OLD_NS_NAME}#${NS_NAME}#g"
        sed -i "s#${OLD_NS_NAME}#${NS_NAME}#g" ${l_yml_file}
        echo "Update namespace successfully!!!"
        echo ""
    fi

    if [ -n "${IMAGE_NAME}" ]; then
        get_old_image ${l_yml_file}
        echo "old image is: ${OLD_IMAGE_NAME}"
        #echo ${IMAGE_NAME}
        echo "s#${OLD_IMAGE_NAME}#${IMAGE_NAME}#g"
        sed -i "s#${OLD_IMAGE_NAME}#${IMAGE_NAME}#g" ${l_yml_file}
        echo "Update image name successfully!!!"
        echo ""
    fi

    if [[ -z "${NS_NAME}" && -z "${IMAGE_NAME}" ]]; then
        echo "There is nothing to be updated. Please pass parameters correctly."
    fi

    if [ $? -ne 0 ]; then
      echo "ERROR: Updating yaml ${l_yml_file} failed"
      exit ${APPLY_ERROR}
    fi

}

# deploy service
function deploy_services() {
    local l_yml_file=$1

    kubectl create -f ${l_yml_file}
    if [[ $? -ne 0 ]]; then
        if [[ "$UPDATE_FLAG" == true ]]; then
            echo "Trying to issue replace command."
            kubectl apply -f ${l_yml_file}
            if [ $? -ne 0 ]; then
              echo "ERROR: Replace service failed with yaml file: ${l_yml_file} Please check line $(($LINENO-2))"
              exit ${APPLY_ERROR}
            fi
        else
            echo "ERROR: Deploying service failed with yaml: ${l_yml_file} Please check line $(($LINENO-10))"
            exit ${APPLY_ERROR}
        fi

    else
        echo "Deploying yaml file successfully!"
        echo ""

    fi
}



##
## main
##
########################################### 1, Initializing ENV ###########################################
GETOPT_ARGS=`getopt -o e:s:i:n:u:lh -al env:,service:,image:,namespace:,update:,list,help -- "$@"`
eval set -- "${GETOPT_ARGS}"

if [ $# -lt 2 ]; then
    echo "ERROR: Arguments are required. Check below help"
    echo ""
    help
    exit 0
fi

while [ -n "$1" ]
do
    case "$1" in
    -e|--env) ENV=$(echo $2 |tr [A-Z] [a-z]); shift 2;;
    -s|--service) SVC_NAME=$(echo $2 |tr [A-Z] [a-z]); shift 2;;
    -i|--image) IMAGE_NAME=$2; shift 2;;
    -n|--namespace) NS_NAME=$(echo $2 |tr [A-Z] [a-z]); shift 2;;
    -u|--update) UPDATE_FLAG=$(echo $2 |tr [A-Z] [a-z]); shift 2;;
    -l|--list) list_services; exit 0 ;;
    -h|--help) help; echo "calling help"; exit 0 ;;
    --) break ;;
    esac
done

# debug
# echo $ENV, $SVC_NAME, $IMAGE_NAME, $NS_NAME, $UPDATE_FLAG

# check if env and service name are null.
if [[ -z ${ENV} || -z ${SVC_NAME} ]]; then
    echo "ERROR: Arguments -e & -s both are mandatory."
    show_help
    exit ${INVALID_ARGS}
fi

# check if service name are correct
services=`list_services`
if [[ ! ${services} =~ ${SVC_NAME} ]]; then
    echo "ERROR: Service name is not correct. Please use \"$0 -l\" to check available services!"
    exit ${WRONG_SVC_NAME}
fi

# set the KUBECONFIG to the right config file for executing kubectl command
KUBE_CONFIG=${ENV}"_config"
set_env ${KUBE_CONFIG}

########################################### 2, Deploying ConfigMap ###########################################
#set -x
echo ""
echo ">>>>>>>> Started to deploy configmap... <<<<<<<<"

echo "Started to update fluentd configmap..."
kubectl apply -f "$SCRIPT_PATH"/configmap/fluentd-es-configmap.yaml
if [ $? -ne 0 ]; then
    echo "ERROR: Apply fluentd configmap failed"
    exit ${APPLY_ERROR}
fi
echo "Update fluentd configmap successfully!!!"
echo ""

# Retrieving all namespaces for deploying configmap.
# Ideally we need to deploy configmap to all namespaces.
kubectl get ns | awk '{print $1}' | grep -v NAME | while read namespaces
do
    if [[ ${namespaces} =~ kube* || ${namespaces} == default || ${namespaces} =~ ingress* ]]; then
        echo "Ignore system namespace $namespaces"
    else
        echo ""
        echo ">> Deploying configmap on namespaces: ${namespaces} <<"
        apply_configmap ${ENV} ${namespaces}
    fi
done

if [ $? -ne 0 ]; then
    echo "ERROR: apply configmap failed"
    exit ${APPLY_ERROR}
fi

echo ">>>>>>>> deploy configmap successfully!!! <<<<<<<<"
echo ""
echo ""
#set +x

########################################### 3, Deploying Services ###########################################
echo ">>>>>>>> Started to deploy service... <<<<<<<<"

DEPLOY_YML_FILE="$SCRIPT_PATH"/yml_files/"$SVC_NAME".yml
echo "The deployment file is: ${DEPLOY_YML_FILE}"

echo ""
echo "Updating deployment file if there are arguments passed. e.g. update image, namespace. etc."
update_yaml_file ${DEPLOY_YML_FILE}

echo ">> Deploying related service <<"
deploy_services ${DEPLOY_YML_FILE}

echo ">>>>>>>> Deploy service successfully!!! <<<<<<<<"
