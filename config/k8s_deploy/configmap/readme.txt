1. How to generate p12 file with client cert and key files
openssl pkcs12 -export -out keycert.p12 -in cert.pem -inkey key.pem -passout pass:T3ciT3ci2
2. How to generate trust key store according to server pem
keytool -import -alias server1 -file ../server/cert.pem -keystore rabbitstore
3. How to create configmap
kubectl -n rsicommon create configmap systemconf --from-file=dev 
4. How to update configmap
kubectl -n rsicommon create configmap systemconf --from-file=dev --dry-run -o yaml |kubectl replace -f -
