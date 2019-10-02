import pyodbc
conn = pyodbc.connect("DRIVER=HPVerticaDriver;SERVER=QAVERTICANXG.ENG.RSICORP.LOCAL;DATABASE=Fusion;PORT=5433;UID=engdeployvtc;PWD=Frl98YRmm1")
print('Successfully connected to vertica.')
conn = pyodbc.connect("DRIVER={ODBC Driver 13 for SQL Server};SERVER=ENGV2HHDBQA1;DATABASE=OSA;PORT=1433;UID=hong.hu;PWD=test666")
print('Successfully connected to sqlserver.')
