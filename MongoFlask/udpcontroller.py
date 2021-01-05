import json
import os
import time
import pandas as pd

def fileEmpty(filepath):
    if not os.path.isfile(filepath):
        return True
    elif os.stat(filepath).st_size == 0:
        return True
    return False

def getMessage(json_path, mac_list):
    if fileEmpty(json_path) == True:
        return(['Initialize Needed!' for i in range(len(mac_list))])
    with open(json_path) as json_file:
        data = json.load(json_file)
        msg = ['Initialize Needed!' for i in range(len(mac_list))]
        for mac in data.keys():
            mac_cut = mac.replace(':','').upper()
            if mac_cut in mac_list:
                msg[mac_list.index(mac_cut)] = data[mac]['log'][-1]['data']
    return msg

def cleanIP(ipfilepath):
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])       
    ip_list = list(df_pwd['os_ip'])
    
    with open(ipfilepath, 'r') as ip_file:
        lines = ip_file.readlines()
    
    with open(ipfilepath, "w") as ip_file_new:
        for line in lines:
            if line.strip("\n") in ip_list:
                ip_file_new.write(line)
    

def insertUdpevent(flag,data,ipfilepath): # if flag == f, data is the filepath 
    #udpflag_path = os.environ['UPLOADPATH'] + 'udpflag.txt'
    udpflag_path = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + '-udpflag.txt'
    cleanIP(ipfilepath)
    with open(udpflag_path, 'a') as flag_file:
        flag_file.write(str(flag) + ',' + str(data) + ',' + str(ipfilepath) + ',' + time.ctime()  + '\n')