import psycopg2
conn=psycopg2.connect(dbname='wms_db',user='wms_user',password='wms_password',host='localhost',port=5432)
cur=conn.cursor()
cur.execute("SELECT column_name,data_type FROM information_schema.columns WHERE table_name='users';")
rows=cur.fetchall()
for r in rows:
    print(r[0], r[1])
cur.close()
conn.close()
