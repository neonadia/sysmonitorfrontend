import json
import os
import time
import pandas as pd
import uuid

def printf(data):
    print(data, flush=True)

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

def getMessage_dictResponse(json_path,mac_os,state):
    response = {}
    found = False
    latest_state = state
    for i in range(4):
        if fileEmpty(json_path) == False:
            found = True
            break
        time.sleep(1)
    if not found:
        printf("UDP Host File not found or empty")
        for i in range(len(mac_os)):
            response[mac_os[i][1]] = 'Error: Initialization needed, File not found!'
    else:
        if latest_state != "latest":
            for iterations in range(1000):###Check the file for the client_state desired a total of 10 times w/ 2 second
                client_state_checking_done = True
                with open(json_path) as json_file:
                    data = json.load(json_file)
                    for mac in data.keys():
                        mac_cut = mac.replace(':','').upper()
                        for selected_mac in mac_os:
                            if mac_cut == selected_mac[0]:
                                selected_ip = selected_mac[1]
                                response[selected_ip] = data[mac]['log'][-1]['data']
                for r in response:
                    if latest_state not in response[r]:
                        client_state_checking_done = False
                if client_state_checking_done:
                    break
                time.sleep(2)
        else:
            printf("Reading UDP Host file, getting last log msg...")
            with open(json_path) as json_file:
                data = json.load(json_file)
                for mac in data.keys():
                    mac_cut = mac.replace(':','').upper()
                    for selected_mac in mac_os:
                        if mac_cut == selected_mac[0]:
                            selected_ip = selected_mac[1]
                            response[selected_ip] = data[mac]['log'][-1]['data']
    return response

def getClientState_dictResponse(json_path,mac_os,client_state):
    response = {}
    found = False
    for i in range(4):
        if fileEmpty(json_path) == False:
            found = True
            break
        time.sleep(1)
    if not found:
        for i in range(len(mac_os)):
            response[mac_os[i][1]] = 'Error: Initialization  Needed!'
    else:
        for i in range(len(mac_os)):
            response[mac_os[i][1]] = 'Error: Initialization  Needed!'
        for iterations in range(10):###Check the file for the client_state desired a total of 10 times w/ 2 second
            client_state_checking_done = True
            with open(json_path) as json_file:
                data = json.load(json_file)
                for mac in data:
                    mac_cut = mac.replace(':','').upper()
                    for selected_mac in mac_os:
                        if mac_cut == selected_mac[0]:
                            selected_ip = selected_mac[1]
                            for msg in data[mac]['log']:
                                if client_state in msg['data']:
                                    response[selected_ip] = msg['data']
            for r in response:
                if client_state not in response[r]:
                    client_state_checking_done = False
            if client_state_checking_done:
                break
            time.sleep(2)
    return response

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

def generateCommandInput(command, walltime=10):
    cur_uid = str(uuid.uuid4()) # need a uid to search the result from database
    file_path = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + 'udpinput.json'
    inputDict = {"category":"command",\
                "exe":command,\
                "prefix":"",\
                "config":"",\
                "log":cur_uid,\
                "walltime":walltime,\
                "parseResultLog":0,\
                "selfLog":0,\
                "selfLogPath":"",\
                "numOfResults":0,\
                "keywords":[],\
                "addRow":[],\
                "dfs":[],\
                "index":[],\
                "unit":[],\
                "criteriaType":[],\
                "criteria":[]}
    with open(file_path, 'w') as json_file:
        json.dump(inputDict, json_file)                
    return cur_uid