#!/bin/sh

apt-get update

######################################
# install required packages
echo ""
echo "Step1: install required packages..."
apt -y install unixodbc unixodbc-dev libssl-dev python3 python3-pip wget

######################################
# install vertica client
echo ""
echo "Step2: install vertica client..."
cd /tmp
wget https://my.vertica.com/client_drivers/9.0.x/9.0.0-1/vertica-client-9.0.0-1.x86_64.tar.gz
cd /
tar -xf /tmp/vertica-client-9.0.0-1.x86_64.tar.gz
rm /tmp/vertica-client-9.0.0-1.x86_64.tar.gz
rm -Rf /opt/vertica/lib
rm -Rf /opt/vertica/Python
rm -Rf /opt/vertica/java
rm -Rf /opt/vertica/en-US

######################################
# install python
echo ""
echo "Step3: install python..."
ln -fs /usr/bin/pip3 /usr/bin/pip
ln -fs /usr/bin/python3 /usr/bin/python
# pip install --upgrade pip
pip install numpy pandas pyodbc PyYAML xlrd sqlalchemy sqlalchemy-vertica-python pymssql pycrypto pika redis tornado requests pytz

######################################
# install sqlserver client
echo ""
echo "Step4: install sqlserver client..."
apt -y install locales && echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && locale-gen
apt -y install apt-transport-https curl

curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
curl https://packages.microsoft.com/config/ubuntu/15.10/prod.list > /etc/apt/sources.list.d/mssql-release.list
apt update
ACCEPT_EULA=Y apt-get -y install msodbcsql
ACCEPT_EULA=Y apt-get -y install mssql-tools

######################################
# odbc.ini
echo ""
echo "Step5: config odbc..."
echo "[ODBC Data Sources]" >> /etc/odbc.ini
echo "Vertica = Vertica" >> /etc/odbc.ini
echo "" >> /etc/odbc.ini
echo "[Vertica]" >> /etc/odbc.ini
echo "Description = Verica DSN" >> /etc/odbc.ini
echo "Driver = HPVerticaDriver" >> /etc/odbc.ini
echo "Locale = en_GB" >> /etc/odbc.ini

######################################
# odbcinst.ini
echo "[HPVerticaDriver]" >> /etc/odbcinst.ini
echo "Description = Vertica Driver" >> /etc/odbcinst.ini
echo "Driver = /opt/vertica/lib64/libverticaodbc.so" >> /etc/odbcinst.ini

######################################
# vertica.ini
echo "[Driver]" >> /etc/vertica.ini
echo "ODBCInstLib = /usr/lib/x86_64-linux-gnu/libodbcinst.so" >> /etc/vertica.ini
export VERTICAINI=/etc/vertica.ini

######################################
# clean up cache
apt -y remove apt-transport-https curl wget
dpkg --list | grep "^rc" | cut -d " " -f 3 | xargs -i dpkg --purge {}
apt -y autoremove
apt -y clean
apt -y autoclean
rm -Rf ~/.cache/pip
