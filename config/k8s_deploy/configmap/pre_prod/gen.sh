basepath=$(cd `dirname $0`; pwd)
base64 -d $basepath/rabbitstore.encode >$basepath/keystore/rabbitstore
base64 -d $basepath/keycert.p12.encode >$basepath/keystore/keycert.p12 
