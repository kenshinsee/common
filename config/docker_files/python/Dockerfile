FROM ubuntu
MAINTAINER hong.hu "hong.hu@retailsolutions.com"

COPY init.sh /tmp/init.sh
ENV PATH=/opt/vertica/bin:$PATH
ENV PATH=/opt/mssql-tools/bin:$PATH
ENV VERTICAINI=/etc/vertica.ini
RUN sh /tmp/init.sh
RUN rm -Rf /tmp/*
COPY test_pyodbc.py /tmp/test_pyodbc.py
RUN python /tmp/test_pyodbc.py
