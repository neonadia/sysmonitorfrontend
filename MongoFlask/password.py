import os
import pandas as pd

def find_password(ip):
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','mac','node','pwd'])
    pwd = df_pwd[df_pwd['ip']==ip]['pwd'].values[0]
    return(pwd)