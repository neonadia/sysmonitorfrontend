from this import d
from flask import Flask, render_template, request, url_for, jsonify, redirect, send_file, send_from_directory
from flask_weasyprint import HTML, render_pdf
import json
from bson import json_util
from pymongo import MongoClient
import pymongo
from bson.objectid import ObjectId
from json2html import *
import get_data # including min_max
import os
import sys
from sys import getsizeof
import time
import subprocess
from subprocess import Popen, PIPE
from firmwareupdate import BiosUpdatingMode, BiosUploadingFile, BiosStartUpdating, powerState, systemRebootTesting, FirmUpdatingMode, FirmUploadingFile, FirmStartUpdating, redfishReadyCheck, CancelBiosUpdate, CancelFirmUpdate, checkUID
from password import find_password
from multiprocessing import Pool
from bioscomparison import compareBiosSettings, bootOrderOutput
import pandas as pd
import socket
from ipaddress import ip_address
from sumtoolbox import makeSumExcutable, sumBiosUpdate, sumBMCUpdate, sumGetBiosSettings, sumCompBiosSettings, sumBootOrder, sumLogOutput, sumChangeBiosSettings, sumRunCustomProcess, sumRedfishAPI
import tarfile
from udpcontroller import getMessage, insertUdpevent, cleanIP, getMessage_dictResponse, generateCommandInput
from glob import iglob
import datetime
from datetime import timedelta
import seaborn as sns
import matplotlib.pyplot as plt
from flask_debugtoolbar import DebugToolbarExtension
import concurrent.futures
from benchmark_parser import parseInput, resultParser, clean_mac, mac_with_seperator
import secrets
import flask_monitoringdashboard as dashboard
from io import StringIO
import gridfs
import cv2
import numpy as np
import shutil

app = Flask(__name__)
mongoport = int(os.environ['MONGOPORT'])
frontport = int(os.environ['FRONTPORT'])
rackname = os.environ['RACKNAME'].upper()
client = MongoClient('localhost', mongoport)
db = client.redfish
collection = db.servers
monitor_collection = db.monitor
udp_collection = db.udp
cmd_collection = db.cmd
udp_deleted_collection = db.udpdel
hardware_collection = db.hw_data
udp_session_info = {'state': 'inactive', 'guid' : 'n/a'}
sum_session_info = {'state': 'inactive', 'guid' : 'n/a'}
redfish_session_info = {'state': 'inactive', 'guid' : 'n/a'}
err_list = ['Critical','critical','AER','Error','error','Non-recoverable','non-recoverable','Uncorrectable','uncorrectable','Failure','failure','Failed','failed','Processor','processor','Security','security','thermal','Thermal','throttle','Throttle','Limited','limited'] # need more key words
IPMIdict = {"#0x09": " Inlet Temperature"} # add "|" if neccessary

@app.route('/get_host_details')
def get_host_details():
    mongo_client = MongoClient('localhost', mongoport)
    database = mongo_client.redfish
    found_collection = False
    iter = 0
    response = {}
    while not found_collection:
        try:
            database.validate_collection("metrics")  # Try to validate a collection
        except pymongo.errors.OperationFailure:  # If the collection doesn't exist
            print("This collection doesn't exist")
            if iter > 6:
                response['Error'] = "No metrics collection found"
                return json.dumps(response)
            else:
                iter = iter + 1
                time.sleep(10)
        else:
            current_collection = database.metrics
            found_collection = True
    cur = current_collection.find({},{"Hostname":1, "OS":1, "Kernel":1,"_id":0})
    for i in cur:
        response[i['Hostname']] = {}
        response[i['Hostname']]['OS'] = i['OS']
        response[i['Hostname']]['Kernel'] = i['Kernel']
    mongo_client.close()
    return json.dumps(response)
    
def get_single_node_metrics(hostname):
    mongo_client = MongoClient('localhost', mongoport)
    database = mongo_client.redfish
    current_collection = database.metrics
    if current_collection.count_documents({ 'Hostname': hostname, "Memory": {"$exists": True}}, limit = 1) != 0:
        i = current_collection.find_one({"Hostname":hostname},{"Hostname":1,"Disk":1,"NETCARDS":1,"Processes":1, "Network.Download Speed": 1,"Network.Upload Speed": 1,"CPU_Metrics.Usage":1, "CPU_Metrics.Frequency":1,"CPU_Metrics.Avg_load":1, "Memory":1, "dmesg":1,"_id":0})
        response = {}
        response[i['Hostname']] = {"CPU":{},"MEMORY":{},"NETWORK":{}, "DISK" : {}, "PROCESSES":{},"NICS":{}, "DMESG":[]}
        response[i['Hostname']]['CPU'] = i['CPU_Metrics']
        response[i['Hostname']]['MEMORY'] = i['Memory']
        for msg in i['dmesg']:
            for err in err_list:
                if err in msg:
                    response[i['Hostname']]['DMESG'].append(msg)
                    break
        response[i['Hostname']]['NETWORK'] = {"Download Speed": i['Network']['Download Speed'],"Upload Speed": i["Network"]['Upload Speed']}
        for partition in i['Disk']:
            if partition == '/':
                response[i['Hostname']]['DISK']['/root'] = i['Disk'][partition]['Percent']
            else:
                response[i['Hostname']]['DISK'][partition] = i['Disk'][partition]['Percent']
        response[i['Hostname']]['PROCESSES'] = i["Processes"]
        for nic in i["NETCARDS"]:
            for stat in i["NETCARDS"][nic]:
                if stat == "incoming":
                    download = i["NETCARDS"][nic]['incoming']["Download Speed"]
                    upload = i["NETCARDS"][nic]['outgoing']["Upload Speed"]
                    response[i['Hostname']]['NICS'][nic] = {"MAC":i["NETCARDS"][nic]['addresses']["MAC"]['address'], "Rx": download, "Tx":upload}
        mongo_client.close()
        return response
    else:
        mongo_client.close()

@app.route('/cluster_metrics')
def cluster_metrics():       
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    mac_list = list(df_pwd['mac'])
    response = {}
    for m in range(len(mac_list)):
        mac_list[m] = mac_list[m].lower()
        mac_list[m] = '-'.join(mac_list[m][i:i + 2] for i in range(0, len(mac_list[m]), 2))
    with Pool() as p:
        output = p.map(get_single_node_metrics, mac_list)
    for i in output:
        if i is not None:
            response.update(i)
    return json.dumps(response)

@app.route('/system_telemetry')
def system_telemetry():
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    bmc_ip = []
    mac_list = []
    cur = collection.find({},{"BMC_IP":1,"_id":0})
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    for i in cur:
        bmc_ip.append(i['BMC_IP'])
        mac_list.append(df_pwd[df_pwd['ip'] == i['BMC_IP']]['mac'].values[0])
    data = zip(mac_list,bmc_ip)
    return render_template('system_telemetry.html',rackobserverurl = rackobserverurl, rackname = rackname, data = data, frontend_urls = get_frontend_urls())

@app.route('/udp_session_handler',methods = ['POST']) ##### Get UDP Session information on page close
def udp_sesssion_handler():
    if request.method == 'POST':
        udp_session_info['state'] = request.form['session_state']
        udp_session_info['guid'] = request.form['session_guid']
        printf('Updating UDP Session info to...')
        printf("state: " + udp_session_info['state'])
        printf("guid: " + udp_session_info['guid'])
    return 'updated session info'

@app.route('/sum_session_handler',methods = ['POST']) ##### Get SUM Session information on page close
def sum_sesssion_handler():
    if request.method == 'POST':
        sum_session_info['state'] = request.form['session_state']
        sum_session_info['guid'] = request.form['session_guid']
        printf('Updating SUM Session info to...')
        printf("state: " + sum_session_info['state'])
        printf("guid: " + sum_session_info['guid'])
    return 'updated session info'

@app.route('/redfish_session_handler',methods = ['POST']) ##### Get Redfish Session information on page close
def redfish_sesssion_handler():
    if request.method == 'POST':
        redfish_session_info['state'] = request.form['session_state']
        redfish_session_info['guid'] = request.form['session_guid']
        printf('Updating RedFish Session info to...')
        printf("state: " + redfish_session_info['state'])
        printf("guid: " + redfish_session_info['guid'])
    return 'updated session info'
 
def printf(data):
    print(data, flush=True)

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

@app.route('/ajax_get_ikvm')
def get_ikvm():
    bmc_ip = request.args.get('ip')
    ikvm = get_data.find_ikvm(bmc_ip)
    data = {"ikvm": ikvm }
    data = json.dumps(data)
    return data

@app.route('/get_container_time')
def get_container_time():
    cur_time = datetime.datetime.now().strftime("%m/%d/%Y %H:%M:%S")
    time = {'Time' : cur_time}
    data = json.dumps(time)
    return data

@app.route('/get_node_time')
def get_node_time():
    bmc_ip = request.args.get('ip')
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    pwd = df_pwd.loc[df_pwd['ip'] == bmc_ip,'pwd'].iloc[0]
    date_time = get_data.get_time(bmc_ip,pwd)
    time = {'Time' : date_time}
    data = json.dumps(time)
    return data

@app.route('/uid_onoff')
def uid_onoff():# Returns BLINKING, OFF, N/A
    bmc_ip = request.args.get('ip')
    uid_state = request.args.get('uid_state')
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    current_auth = ("ADMIN",df_pwd[df_pwd['ip'] == bmc_ip]['pwd'].values[0])
    if uid_state == "N/A":
        result = {'Status' : "N/A"}
        process = Popen('ipmitool -H ' +  bmc_ip + ' -U ' + 'ADMIN' + ' -P ' + current_auth[1] + ' chassis identify force', shell=True, stdout=PIPE, stderr=PIPE)
        try:
            stdout, stderr = process.communicate()
            result = {'Status' : "BLINKING"}
        except:
            printf("No ipmi connection!!!")
            result = {'Status' : "N/A"}

    elif uid_state == "OFF":
        process = Popen('ipmitool -H ' +  bmc_ip + ' -U ' + 'ADMIN' + ' -P ' + current_auth[1] + ' chassis identify force', shell=True, stdout=PIPE, stderr=PIPE)
        try:
            stdout, stderr = process.communicate()
            result = {'Status' : "BLINKING"}
        except:
            printf("No ipmi connection!!!")
            result = {'Status' : "N/A"}
    else:
        process = Popen('ipmitool -H ' +  bmc_ip + ' -U ' + 'ADMIN' + ' -P ' + current_auth[1] + ' chassis identify 0', shell=True, stdout=PIPE, stderr=PIPE)
        try:
            stdout, stderr = process.communicate()
            result = {'Status' : "OFF"}
        except:
            printf("No ipmi connection!!!")
            result = {'Status' : "N/A"}
    data = json.dumps(result)
    return data

def get_temp_names(bmc_ip):
    dataset_Temps = get_data.find_temperatures_names(bmc_ip)
    cpu_temps = []
    vrm_temps = []
    dimm_temps = []
    gpu_temps = []
    sys_temps = []
    for x in range(len(dataset_Temps["Temperatures"])):
        if 'CPU' in dataset_Temps["Temperatures"][x]["Name"]:
            cpu_temps.append(dataset_Temps["Temperatures"][x]["Name"])
        elif 'DIMM' in dataset_Temps["Temperatures"][x]["Name"]:
            dimm_temps.append(dataset_Temps["Temperatures"][x]["Name"])
        elif 'VRM' in dataset_Temps["Temperatures"][x]["Name"]:
            vrm_temps.append(dataset_Temps["Temperatures"][x]["Name"])
        elif 'GPU' in dataset_Temps["Temperatures"][x]["Name"]:
            gpu_temps.append(dataset_Temps["Temperatures"][x]["Name"])
        else:
            sys_temps.append(dataset_Temps["Temperatures"][x]["Name"])

    return cpu_temps,vrm_temps,dimm_temps,sys_temps,gpu_temps

def get_voltage_names(bmc_ip):
    dataset_Voltages = get_data.find_voltages_names(bmc_ip)
    sys_voltages = []
    for x in range(len(dataset_Voltages["Voltages"])):
        sys_voltages.append(dataset_Voltages["Voltages"][x]["Name"])    
    return sys_voltages

def get_fan_names(bmc_ip):
    dataset_Fans = get_data.find_fans_names(bmc_ip)
    sys_fans = []
    for x in range(len(dataset_Fans["Fans"])):
        sys_fans.append(dataset_Fans["Fans"][x]["Name"])
    return sys_fans

def indexHelper(bmc_ip_auth):
    bmc_ip = bmc_ip_auth[0]
    client_index = MongoClient('localhost', mongoport)
    db_index = client_index.redfish
    monitor_collection_index = db_index.monitor
    for i in monitor_collection_index.find({"BMC_IP": bmc_ip}, {"_id":0, "Event":1}).sort("_id",-1):
        details = i['Event']
        break
    details.reverse() # begin from latest
    bmc_details = []
    for i in range(len(details)):
        if "|||" in details[i]: #Split redfish and ipmitool log
            cur_detail = details[i].split("|||")[1]
        elif "only redfish sel log" in details[i] or "only ipmitool sel log" in details[i]:      # remove flag lines
            continue
        else:
            cur_detail = details[i]
        for key in IPMIdict.keys():
            if key in cur_detail:
                cur_detail = cur_detail.replace(key,IPMIdict[key])
        bmc_details.append(cur_detail)
    if details == [''] or bmc_details == ['']:
        bmc_event = "OK"
    elif any(w in " ".join(str(x) for x in details) for w in ["|||","only redfish sel log"]): # check if the redfish log exsist, if so check the severity
        bmc_event = "WARNING"
        for event in details:
            if "Critical" in event.split("|")[2] or "critical" in event.split("|")[2] or "CRITICAL" in event.split("|")[2]:
                bmc_event = "ERROR"
                break
    elif any(w in " ".join(str(x) for x in details) for w in err_list): # check if event contains any key from err_list
        bmc_event = "ERROR"
    else:
        bmc_event = "WARNING"
    current_auth = (bmc_ip_auth[1],bmc_ip_auth[2])
    if os.environ['POWERDISP'] == "ON":
        if powerState(bmc_ip,current_auth) == -1:
            current_state = "D/C"
        elif powerState(bmc_ip,current_auth):
            current_state = "ON"
        else:
            current_state = "OFF"
    else:
        current_state = "PwrDisp: OFF" ### IF POWERDISP variable set to off in auto.env file
    if os.environ['UIDDISP'] == "ON":
        uid_state = checkUID(bmc_ip, current_auth)
    else:
        uid_state = "N/A" 
    for i in monitor_collection_index.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1}): # get last datetime
        cur_date = i['Datetime']
    cpu_temps,vrm_temps,dimm_temps,sys_temps,sys_fans,sys_voltages,gpu_temps = get_sensor_names(bmc_ip)
    client_index.close()
    return [bmc_event, bmc_details, current_state, cur_date, uid_state,cpu_temps,vrm_temps,dimm_temps,sys_temps,sys_fans,sys_voltages,gpu_temps]

@app.route('/')
def index():
    bmc_ip = []
    timestamp = []
    serialNumber = []
    modelNumber = []
    bmcVersion = []
    biosVersion = []
    bmc_event = []
    bmc_details = []
    bmcMacAddress = []
    ikvm = []
    monitorStatus = []
    uidStatus = []
    pwd =[]
    mac_list = []
    os_ip = []
    cpld_version = []
    cpu_temps = []
    vrm_temps = []
    dimm_temps = []
    sys_temps = []
    sys_fans = []
    sys_voltages = []
    gpu_temps = []
    bmc_ip_auth = []
    current_flag = read_flag()
    if current_flag == 0:
        monitor = "IDLE "
    elif current_flag == 1:
        monitor = "FETCHING "
    elif current_flag == 2:
        monitor = "UPDATING "
    elif current_flag == 3:
        monitor = "REBOOTING "
    elif current_flag == 4:
        monitor = "REBOOT DONE "
    elif current_flag == 5:
        monitor = "SUM in use "
    else:
        monitor = "UNKOWN "                   
    cur = collection.find({},{"BMC_IP":1, "Datetime":1, "UUID":1, "Systems.1.SerialNumber":1, "Systems.1.Model":1, "UpdateService.SmcFirmwareInventory.1.Version": 1, "UpdateService.SmcFirmwareInventory.2.Version": 1, "CPLDVersion":1, "_id":0})#.limit(50)
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    for i in cur:
        bmc_ip.append(i['BMC_IP'])
        bmcMacAddress.append(i['UUID'][24:])
        if i['Systems']['1']['SerialNumber'] == 'NA' or i['Systems']['1']['SerialNumber'] == 'N/A':
            serialNumber.append(getSerialNumberFromFile(i['BMC_IP'],1)) # opt 1 means using bmc ip, get SN from csv input file when database has NA or N/A
            printf('Warning: cannot get serial number from database (redfish API), reading it from csv file')
        else:
            serialNumber.append(i['Systems']['1']['SerialNumber'])
        modelNumber.append(i['Systems']['1']['Model'])
        try:
            cpld_version.append(i['CPLDVersion'])
        except:
            cpld_version.append("N/A") # Archive MongoDB might not contain CPLD
        try:
            bmcVersion.append(i['UpdateService']['SmcFirmwareInventory']['1']['Version'])
        except:
            bmcVersion.append("Not Avaliable")
        try:
            biosVersion.append(i['UpdateService']['SmcFirmwareInventory']['2']['Version'])
        except:
            biosVersion.append("Not Avaliable")
        current_auth = ("ADMIN",df_pwd[df_pwd['ip'] == i['BMC_IP']]['pwd'].values[0])
        pwd.append(current_auth[1])
        mac_list.append(df_pwd[df_pwd['ip'] == i['BMC_IP']]['mac'].values[0])
        os_ip.append(df_pwd[df_pwd['ip'] == i['BMC_IP']]['os_ip'].values[0])
        bmc_ip_auth.append((i['BMC_IP'],"ADMIN",current_auth[1]))
    
    with Pool() as p:
        output = p.map(indexHelper, bmc_ip_auth)
         
    for i in output:
        bmc_event.append(i[0])
        bmc_details.append(i[1])
        monitorStatus.append(monitor + " " + i[2])
        timestamp.append(i[3])
        uidStatus.append(i[4])
        cpu_temps.append(i[5])
        vrm_temps.append(i[6])
        dimm_temps.append(i[7])
        sys_temps.append(i[8])
        sys_fans.append(i[9])
        sys_voltages.append(i[10])
        gpu_temps.append(i[11])
    
    json_path = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + '-host.json'
    udp_msg = getMessage(json_path, mac_list)
    show_names = 'true' # default
    try:
        df_names = pd.read_csv(os.environ['NODENAMES'])
        df_pwd['name'] = list(df_names['name'])
        node_names = []
    except Exception as e:
        printf(e)
        show_names = 'false'
        data = zip(bmc_ip, bmcMacAddress, modelNumber, serialNumber, biosVersion, bmcVersion, bmc_event, timestamp, bmc_details, ikvm, monitorStatus, pwd, udp_msg, os_ip, mac_list, uidStatus,cpld_version)
    else:
        no_name_count = 0
        for i in bmc_ip:
            if df_pwd[df_pwd['ip'] == i]['name'].values[0] == 'No Value':
                no_name_count += 1
            node_names.append(df_pwd[df_pwd['ip'] == i]['name'].values[0])
        if df_pwd['name'].isnull().sum() == len(bmc_ip) or no_name_count == len(bmc_ip):
            show_names = 'false'
        data = zip(bmc_ip, bmcMacAddress, modelNumber, serialNumber, biosVersion, bmcVersion, bmc_event, timestamp, bmc_details, monitorStatus, pwd, udp_msg, os_ip, mac_list, uidStatus,cpld_version,node_names)

    cur_time = datetime.datetime.now().strftime("%m/%d/%Y %H:%M:%S")
    time_zone = os.environ['TZ']
    frontend_url = "http://" + get_ip() + ":" + str(frontport)
    return render_template('index.html', rackname = rackname,show_names = show_names, x=data, rackobserverurl = rackobserverurl, frontend_url = frontend_url,gpu_temps=gpu_temps, cpu_temps = cpu_temps,sys_temps=sys_temps,dimm_temps=dimm_temps,vrm_temps=vrm_temps,sys_fans=sys_fans,sys_voltages=sys_voltages, cur_time=cur_time, time_zone=time_zone)


@app.route('/update_index_page')
def update_index_page():
    bmc_ip = []
    pwd =[]
    mac_list = []
    os_ip = []
    bmc_ip_auth = []  
    cur = collection.find({},{"BMC_IP":1, "Datetime":1, "UUID":1, "Systems.1.SerialNumber":1, "Systems.1.Model":1, "UpdateService.SmcFirmwareInventory.1.Version": 1, "UpdateService.SmcFirmwareInventory.2.Version": 1, "CPLDVersion":1, "_id":0})#.limit(50)
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    json_path = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + '-host.json'
    response = {}
    current_flag = read_flag()
    if current_flag == 0:
        monitor = "IDLE "
    elif current_flag == 1:
        monitor = "FETCHING "
    elif current_flag == 2:
        monitor = "UPDATING "
    elif current_flag == 3:
        monitor = "REBOOTING "
    elif current_flag == 4:
        monitor = "REBOOT DONE "
    elif current_flag == 5:
        monitor = "SUM in use "
    else:
        monitor = "UNKOWN "  
    for i in cur:
        bmc_ip.append(i['BMC_IP'])
        response[i['BMC_IP']] = {}
        if i['Systems']['1']['SerialNumber'] == 'NA' or i['Systems']['1']['SerialNumber'] == 'N/A':
            response[i['BMC_IP']]['SerialNumber'] = getSerialNumberFromFile(i['BMC_IP'],1)
            printf('Warning: cannot get serial number from database (redfish API), reading it from csv file')
        else:
            response[i['BMC_IP']]['SerialNumber'] = i['Systems']['1']['SerialNumber']
        response[i['BMC_IP']]['ModelNumber'] = i['Systems']['1']['Model']
        try:
            response[i['BMC_IP']]['CPLDVersion'] = i['CPLDVersion']
        except:
            response[i['BMC_IP']]['CPLDVersion'] = "N/A"
        try:
            response[i['BMC_IP']]['BmcVersion'] = i['UpdateService']['SmcFirmwareInventory']['1']['Version']
        except:
           response[i['BMC_IP']]['BmcVersion'] = "N/A"
        try:
            response[i['BMC_IP']]['BiosVersion'] = i['UpdateService']['SmcFirmwareInventory']['2']['Version']
        except:
            response[i['BMC_IP']]['BiosVersion'] = "N/A"
        current_auth = ("ADMIN",df_pwd[df_pwd['ip'] == i['BMC_IP']]['pwd'].values[0])
        pwd.append(current_auth[1])
        mac_list.append(df_pwd[df_pwd['ip'] == i['BMC_IP']]['mac'].values[0])
        os_ip.append(df_pwd[df_pwd['ip'] == i['BMC_IP']]['os_ip'].values[0])
        bmc_ip_auth.append((i['BMC_IP'],"ADMIN",current_auth[1]))
    with Pool() as p:
        output = p.map(indexHelper, bmc_ip_auth)
    udp_msg = getMessage(json_path, mac_list)
    for node_iter,i in enumerate(output):
        node = bmc_ip[node_iter]
        response[node]['bmc_event'] = i[0]
        response[node]['bmc_details'] = i[1]
        response[node]['monitorStatus'] = monitor + " " + i[2]
        response[node]['timestamp'] = i[3]
        response[node]['udp_message'] = udp_msg[node_iter]
    response['time'] = datetime.datetime.now().strftime("%m/%d/%Y %H:%M:%S")
    return json.dumps(response)

def getSerialNumberFromFile(ip,opt):
    df_all = pd.read_csv(os.environ['UPLOADPATH'] + os.environ['RACKNAME']+'.csv')
    if 'System S/N' not in df_all.columns:
        return 'N/A'
    if 'OS_IP' in df_all.columns and opt == 0:
        return(df_all[df_all['OS_IP'] == ip]['System S/N'].values[0])
    elif 'IPMI_IP' in df_all.columns and opt == 1:
        return(df_all[df_all['IPMI_IP'] == ip]['System S/N'].values[0])
    else:
        return 'N/A'
def getSerialNumber(ipmiip):
    cur = collection.find_one({"BMC_IP": ipmiip},{"Systems.1.SerialNumber":1})
    if cur != None:
        return(cur['Systems']['1']['SerialNumber'])
    else:
        return("NA")

@app.route('/about')
def about():
    return render_template('about.html',rackname=rackname,rackobserverurl = rackobserverurl)

@app.route('/details')
def details():
    ip = request.args.get('var')
    cpu_temps,vrm_temps,dimm_temps,sys_temps,sensor_fans,sensor_voltages,gpu_temps = get_sensor_names(ip)
    data = hardware_collection.find_one({"bmc_ip": ip},{'_id': 0,'TOPO_file': 0}) 
    NoneType = type(None)
    if isinstance(data,NoneType) == False:
        return render_template('details_v2.html', data=json.dumps(data), ip=ip,rackname=rackname,bmc_ip = ip,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages,rackobserverurl = rackobserverurl)
    else:
        details1 = collection.find_one({"BMC_IP": ip}, {"_id":0,"BMC_IP":1, "Datetime":1,"UUID":1,"Systems.1.Description":1,"Systems.1.Model":1,"Systems.1.SerialNumber":1, "Systems.1.ProcessorSummary.Count":1, "Systems.1.ProcessorSummary.Model":1, "Systems.1.MemorySummary.TotalSystemMemoryGiB":1, "Systems.1.SimpleStorage.1.Devices.Name":1, "Systems.1.SimpleStorage.1.Devices.Model":1,  "UpdateService.SmcFirmwareInventory.1.Name":1, "UpdateService.SmcFirmwareInventory.1.Version":1, "UpdateService.SmcFirmwareInventory.2.Name":1, "UpdateService.SmcFirmwareInventory.2.Version":1}  )
        details2 = collection.find_one({"BMC_IP": ip}, {"_id":0,"Systems.1.CPU":1})
        details3 = collection.find_one({"BMC_IP": ip}, {"_id":0,"Systems.1.Memory":1})
        details4 = collection.find_one({"BMC_IP": ip}, {"_id":0,"Systems.1.SimpleStorage":1})
        details5 = collection.find_one({"BMC_IP": ip}, {"_id":0,"Systems.1.PCIeDevices":1})
        system = json2html.convert(json = details1)
        cpu = json2html.convert(json = details2)
        memory = json2html.convert(json = details3)
        storage = json2html.convert(json = details4)
        pcie = json2html.convert(json = details5)
        return render_template('details.html', ip=ip,rackname=rackname,bmc_ip = ip, system=system, cpu=cpu, memory=memory, storage=storage, pcie=pcie,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages,rackobserverurl = rackobserverurl)
                                                                                          
@app.route('/systemresetupload',methods=["GET","POST"])
def systemresetupload():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    try:
        df_input = pd.read_csv(savepath+"resetip.txt",header=None,names=['ip'])
        inputips = list(df_input['ip'])
    except:
        inputips = []
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    allips = list(df_pwd['ip'])
    indicators = []
    for i in range(len(allips)):
        if allips[i] in inputips:
            indicators.append(1)
        else:
            indicators.append(0)
    if request.method == "POST":
        if request.files:
            resetfile = request.files["file"]
            if resetfile.filename == "":
                printf("Input file must have a filename")
                return redirect(url_for('systemresetupload'))
            resetfile.save(savepath + "resetip.txt")
            printf("{} has been saved as resetip.txt".format(resetfile.filename))
            return redirect(url_for('systemresetupload'))
    return render_template('systemresetupload.html',data=zip(allips,indicators),rackname=rackname,rackobserverurl = rackobserverurl)

@app.route('/systemresetstart',methods=["GET","POST"])
def systemresetstart():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    rstatuspath = os.environ['RESETSTATUSPATH']
    if request.method == "POST":
        if fileEmpty(savepath+"resetip.txt"):
            return render_template('error.html',error="No input IP found!")
        df_reset = pd.read_csv(savepath+"resetip.txt",names=['ip'])
        '''
        try:
            df_reset = pd.read_csv(savepath+"resetip.txt",names=['ip'])
        except:
            result = "Power Reset Test Failed: no input file found!"
            return render_template('resetresult.html',iplist=["N/A"] ,nreset="N/A", tp1="N/A", tp2="N/A", tspend="N/A", result=result)
        '''
        df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])       
        iplist = list(df_reset['ip'])
        iplist_rack = list(df_pwd['ip'])
        nreset = int(request.form['nreset'])
        tp1 = int(request.form['tp1'])
        tp2 = int(request.form['tp2'])
        pwd_list = []
        for ip in iplist:
            if ip not in iplist_rack:
                result = "Power Reset Test Failed: assigned ip " + ip + " not belongs current rack!"
                return render_template('resetresult.html',iplist=iplist ,nreset=nreset, tp1=tp1, tp2=tp2, tspend="N/A", result=result)
            else:
                pwd_list.append(df_pwd[df_pwd['ip'] == ip]['pwd'].values[0])
        data = []
        for i in range(len(iplist)):
            data.append([])
            data[i].append(iplist[i])
            data[i].append(nreset)
            data[i].append(tp1)
            data[i].append(tp2)
            data[i].append(("ADMIN",pwd_list[i]))
        flag = read_flag()
        while flag != 0 and flag != 2:
            flag = read_flag()
            time.sleep(1)
        starttime = time.time()
        insert_flag(3)
        with Pool() as p:
            p.map(systemresetone, data)
        insert_flag(4)
        endtime = time.time()
        tspend = str(round(endtime - starttime,0)) + " secs"
    with open(rstatuspath, 'a') as rprint:
        rprint.write(time.asctime() + ": " + "Reboot test finished!\n")
    time.sleep(5)
    os.remove(rstatuspath)
    #os.remove(savepath+"resetip.txt")
    result = "Power Reset Test Done"
    return render_template('resetresult.html',iplist=iplist ,rackname=rackname,nreset=nreset, tp1=tp1, tp2=tp2, tspend=tspend, result=result,rackobserverurl = rackobserverurl)
    

@app.route('/systembootup')
def systembootup():
    filepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "resetip.txt"
    if fileEmpty(filepath):
        return render_template('error.html',error="No input IP found!",rackname=rackname,rackobserverurl = rackobserverurl)
    df_reset = pd.read_csv(filepath,names=['ip'])
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    iplist = list(df_reset['ip'])
    iplist_rack = list(df_pwd['ip'])
    pwd_list = []
    for ip in iplist:
        if ip not in iplist_rack:
            return render_template('error.html',error="Assigned IP [" + ip + "] not belong to current rack!")
        else:
            pwd_list.append(df_pwd[df_pwd['ip'] == ip]['pwd'].values[0])
    for ip, pwd in zip(iplist,pwd_list):
        IPMI = "https://" + ip
        auth = ("ADMIN",pwd)
        systemRebootTesting(IPMI,auth,"ForceOn")
    return redirect(url_for('systemresetupload'))

@app.route('/systemshutdown')
def systemshutdown():
    filepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "resetip.txt"
    if fileEmpty(filepath):
        return render_template('error.html',error="No input IP found!",rackname=rackname,rackobserverurl = rackobserverurl)
    df_reset = pd.read_csv(filepath,names=['ip'])
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    iplist = list(df_reset['ip'])
    iplist_rack = list(df_pwd['ip'])
    pwd_list = []
    for ip in iplist:
        if ip not in iplist_rack:
            return render_template('error.html',error="Assigned IP [" + ip + "] not belong to current rack!",rackname=rackname,rackobserverurl = rackobserverurl)
        else:
            pwd_list.append(df_pwd[df_pwd['ip'] == ip]['pwd'].values[0])
    for ip, pwd in zip(iplist,pwd_list):
        IPMI = "https://" + ip
        auth = ("ADMIN",pwd)
        systemRebootTesting(IPMI,auth,"GracefulShutdown")
    return redirect(url_for('systemresetupload'))

@app.route('/systemreset')
def systemreset():
    filepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "resetip.txt"
    if fileEmpty(filepath):
        return render_template('error.html',error="No input IP found!",rackname=rackname,rackobserverurl = rackobserverurl)
    df_reset = pd.read_csv(filepath,names=['ip'])
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    iplist = list(df_reset['ip'])
    iplist_rack = list(df_pwd['ip'])
    pwd_list = []
    for ip in iplist:
        if ip not in iplist_rack:
            return render_template('error.html',error="Assigned IP [" + ip + "] not belong to current rack!",rackname=rackname,rackobserverurl = rackobserverurl)
        else:
            pwd_list.append(df_pwd[df_pwd['ip'] == ip]['pwd'].values[0])
    for ip, pwd in zip(iplist,pwd_list):
        IPMI = "https://" + ip
        auth = ("ADMIN",pwd)
        systemRebootTesting(IPMI,auth,"GracefulRestart")
    return redirect(url_for('systemresetupload'))


def runipmisingle(input_list):
    bmc_ip = input_list[0]
    ipmi_cmd = input_list[1]
    try:
        df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
        current_pwd = df_pwd[df_pwd['ip'] == bmc_ip]['pwd'].values[0]
        response = Popen('ipmitool -H ' + bmc_ip + ' -U ADMIN -P ' + current_pwd + ' ' + ipmi_cmd, shell = 1, stdout  = PIPE, stderr = PIPE)
        stdout , stderr = response.communicate(timeout=2)
    except:
        printf('Cannot perform IPMI command for ' + bmc_ip + '!!!')
        return []
    else:
        if stderr.decode('utf-8') == '':
            output = stdout.decode("utf-8").split('\n')
            if output[-1] == '': # remove last empty item
                output.pop()
            #printf(output)
        else:
            printf('IPMI command on ' + bmc_ip + ' got following error:')
            printf(stderr.decode('utf-8'))
            return []
    return output # output = ["CPU1 Temp        | 59 degrees C      | ok",  "CPU2 Temp        | 62 degrees C      | ok",.....]

@app.route('/checkipmisensor')
def checkipmisensor():
    #ip_list = getIPlist()
    ips_names = get_node_names()
    ip_list = []
    name_list = []
    sn_list = []
    pwd_list = []
    bios_version = []
    bmc_version = []
    cpld_version = []
    input_lists = []
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])    
    if isinstance(ips_names,bool) != True:
        for ip, name in ips_names:
            if name != "No Value" and len(name) > 0:
                name_list.append(name + ' - ' + ip)
            else:
                name_list.append(ip)
            ip_list.append(ip)
            
    else:
        ip_list = getIPlist()
        name_list = ip_list
    for ip in ip_list:
        input_lists.append([ip, 'sdr list full'])
        sn_list.append(getSerialNumber(ip))
        pwd_list.append(df_pwd[df_pwd['ip'] == ip]['pwd'].values[0])
        cur_list = list(collection.find({"BMC_IP":ip},{"UpdateService.SmcFirmwareInventory.1.Version": 1,\
        "UpdateService.SmcFirmwareInventory.2.Version": 1, "CPLDVersion":1}))
        try:
            bmc_version.append(cur_list[0]['UpdateService']['SmcFirmwareInventory']['1']['Version'])
        except:
            bmc_version.append("N/A")
        try:
            bios_version.append(cur_list[0]['UpdateService']['SmcFirmwareInventory']['2']['Version'])
        except:
            bios_version.append("N/A")
        try:
            cpld_version.append(cur_list[0]['CPLDVersion'])
        except:
            cpld_version.append("N/A")   
    # Check how many working sensors
    with Pool() as p:
        output = p.map(runipmisingle, input_lists) # output = [[bmc1 output],[bmc2 output],....]
    num_all = []
    num_workable = []
    num_nonworkable = []
    num_unknown = []
    prob_flags = []
    for sensors in output: # sensors are all sensors of one bmc ["CPU1 Temp        | 59 degrees C      | ok","CPU2 Temp        | 62 degrees C      | ok",.....]
        cur_num_workable = 0
        cur_num_nonworkable = 0
        cur_num_unknown = 0
        for sensor in sensors:
            if "ok"  in sensor:
                cur_num_workable += 1
            elif "ns" in sensor:
                cur_num_nonworkable += 1
            else:
                cur_num_unknown += 1
        num_all.append(len(sensors))
        num_workable.append(cur_num_workable) # sensor show ok
        num_nonworkable.append(cur_num_nonworkable) # sensor show ns
        num_unknown.append(cur_num_unknown) # other situations
        
    for a, w, n, u in zip(num_all, num_workable, num_nonworkable, num_unknown):
        if a < max(num_all) or w < max(num_workable):
            prob_flags.append(1)
        else:
            prob_flags.append(0)
    return render_template('checkipmisensor.html',rackname=rackname,data=zip(name_list,ip_list,pwd_list,sn_list,bmc_version,bios_version,cpld_version,num_all,num_workable,num_nonworkable,num_unknown,prob_flags),rackobserverurl = rackobserverurl)


@app.route('/showipmisensor')
def showipmisensor():
    bmc_ip = request.args.get('var')
    name_list = []
    reading_list = []
    unit_list = []
    severity_list = []
    lownr_list = []
    lowct_list = []
    highct_list = []
    highnr_list = []
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        show_names = 'false'
    else:
        show_names = 'true'
    try:
        df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
        current_pwd = df_pwd[df_pwd['ip'] == bmc_ip]['pwd'].values[0]
        response = Popen('ipmitool -H ' + bmc_ip + ' -U ADMIN -P ' + current_pwd + ' sensor', shell = 1, stdout  = PIPE, stderr = PIPE)
        stdout , stderr = response.communicate(timeout=2)
    except:
        printf('Cannot perform IPMI command for ' + bmc_ip + '!!!')
    else:
        if stderr.decode('utf-8') == '':
            output = StringIO(stdout.decode("utf-8"))
            df_output = pd.read_csv(output,header=None,names=['Name','Reading','Unit','Severity','Low NR','Low CT','Unkown-1','Unkown-2','High CT','High NR'], sep="|")
            name_list = df_output['Name']
            reading_list = df_output['Reading']
            unit_list = df_output['Unit']
            severity_list = df_output['Severity']
            lownr_list = df_output['Low NR']
            lowct_list = df_output['Low CT']
            highct_list = df_output['High CT']
            highnr_list = df_output['High NR']
        else:
            printf('IPMI command on ' + bmc_ip + ' got following error:')
            printf(stderr.decode('utf-8'))
    if show_names == 'true':
        return render_template('showipmisensor.html',\
        rackname=rackname,data=zip(name_list,reading_list,unit_list,severity_list,lownr_list,lowct_list,highct_list,highnr_list),\
        bmc_ip = bmc_ip, ip_list =  ips_names, rackobserverurl = rackobserverurl,show_names = show_names)        
    else:
        return render_template('showipmisensor.html',\
        rackname=rackname,data=zip(name_list,reading_list,unit_list,severity_list,lownr_list,lowct_list,highct_list,highnr_list),\
        bmc_ip = bmc_ip, ip_list = getIPlist(), rackobserverurl = rackobserverurl,show_names = show_names)   

@app.route('/updateipmisensor')
def updateipmisensor():
    bmc_ip = request.args.get('address')
    data = {'Reading':{},'Severity':{}}
    try:
        df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
        current_pwd = df_pwd[df_pwd['ip'] == bmc_ip]['pwd'].values[0]
        response = Popen('ipmitool -H ' + bmc_ip + ' -U ADMIN -P ' + current_pwd + ' sensor', shell = 1, stdout  = PIPE, stderr = PIPE)
        stdout , stderr = response.communicate(timeout=2)
    except:
        printf('Cannot perform IPMI command for ' + bmc_ip + '!!!')
    else:
        if stderr.decode('utf-8') == '':
            output = StringIO(stdout.decode("utf-8"))
            df_output = pd.read_csv(output,header=None,names=['Name','Reading','Unit','Severity','Low NR','Low CT','Unkown-1','Unkown-2','High CT','High NR'], sep="|")
            for i in range(len(df_output)):
                data['Reading'][df_output['Name'][i]] = df_output['Reading'][i]
                data['Severity'][df_output['Name'][i]] = df_output['Severity'][i]
        else:
            printf('IPMI command on ' + bmc_ip + ' got following error:')
            printf(stderr.decode('utf-8'))
            data['error_msg'] = str(stderr.decode('utf-8'))
    return json.dumps(data) 


@app.route('/systemresetstatus')
def systemresetstatus():
    rstatuspath = os.environ['RESETSTATUSPATH']
    try:
        with open(rstatuspath, 'r') as rprint:
            data = []
            for line in rprint.readlines():
                data.append(line.replace('\n',''))
    except:
        data = ['Not Started Yet']
    return render_template('systemresetstatus.html',rackname=rackname,data=data,rackobserverurl = rackobserverurl)

def systemresetone(data_list):
    rstatuspath = os.environ['RESETSTATUSPATH']
    IPMI = "https://" + data_list[0]
    nreset = data_list[1]
    tp1 = data_list[2]
    tp2 = data_list[3]
    auth = data_list[4]
    for i in range(nreset):
        with open(rstatuspath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + data_list[0] + " begins loop " + str(i+1) + ".........\n")
        if powerState(IPMI,auth):
            systemRebootTesting(IPMI,auth,"ForceOff")
            printf("Start reboot!")
            with open(rstatuspath, 'a') as rprint:
                rprint.write(time.asctime() + ": " + data_list[0] + " start reboot...\n")
        else:
            printf("System is not on!")
            with open(rstatuspath, 'a') as rprint:
                rprint.write(time.asctime() + ": " + data_list[0] + " system is not on!\n")
            break
        while powerState(IPMI,auth):
            printf("Waiting shutdown!")
            with open(rstatuspath, 'a') as rprint:
                rprint.write(time.asctime() + ": " + data_list[0] + " waiting shutdown...\n")
            time.sleep(1)
        printf("Shut down already, begin period count down!")
        with open(rstatuspath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + data_list[0] + " shut down already, begin period count down...\n")
        time.sleep(tp1*60)
        printf("Period count down finished, begin boot up!")
        with open(rstatuspath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + data_list[0] + " period count down finished, begin boot up...\n")
        systemRebootTesting(IPMI,auth,"ForceOn")
        while not powerState(IPMI,auth):
            time.sleep(1)
        printf("Boot up already, begin period count down!")
        with open(rstatuspath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + data_list[0] + " boot up already, begin period count down...\n")
        time.sleep(tp2*60)
        printf("Period count down finished!")
        with open(rstatuspath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + data_list[0] + " period count down finished...\n")

def redfish_session_creator():
    time.sleep(0.100) ##### Fixes timing issue between page close and page reload
    if redfish_session_info['state'] == 'active':
        printf("Failed to create new sum_server session")
        printf("Current RedFish Session info is:")
        printf("state: " + redfish_session_info['state'])
        printf("guid: " + redfish_session_info['guid'])
        return False
    else:
        url_saf = secrets.token_urlsafe(8)
        redfish_session_info['state'] = 'active'
        redfish_session_info['guid'] = url_saf
        printf("Creating new RedFish session")
        printf("state: " + redfish_session_info['state'])
        printf("guid: " + redfish_session_info['guid'])
        return True

@app.route('/biosupload',methods=["GET","POST"])
def biosupload():
    savepath = os.environ['UPLOADPATH']
    if request.method == "POST":
        if request.files:
            biosfile = request.files["file"]
            if biosfile.filename == "":
                printf("Input file must have a filename")
                return redirect(url_for('biosupload'))
            biosfile.save(os.path.join(savepath, "bios.222"))
            printf("{} has been saved as bios.222".format(biosfile.filename))
            return redirect(url_for('biosupload'))
    return render_template('biosupload.html',ip_list = getIPlist(),rackname=rackname,rackobserverurl = rackobserverurl)

@app.route('/biosupdate',methods=["GET","POST"])
def biosupdate():
    if not redfish_session_creator(): #### Check if a session is active...
        error = ["ERROR: An instance of the RedFish API server controller have been detected.", "Someone might be using this feature.", "Since, this page can create some conflict with multiple users, please only have one instance open."]
        return render_template('simpleresult.html',messages = error)
    ip = request.args.get('var')
    return render_template('biosupdate.html',ip=ip,rackname=rackname,rackobserverurl = rackobserverurl, session_auth = redfish_session_info['guid'])

@app.route('/biosupdaterack',methods=["GET","POST"])
def biosupdaterack():
    if not redfish_session_creator(): #### Check if a session is active...
        error = ["ERROR: An instance of the RedFish API server controller have been detected.", "Someone might be using this feature.", "Since, this page can create some conflict with multiple users, please only have one instance open."]
        return render_template('simpleresult.html',messages = error)
    return render_template('biosupdaterack.html',numOfNodes=len(getIPlist()),rackname=rackname,rackobserverurl = rackobserverurl, session_auth = redfish_session_info['guid'])

@app.route('/biosupdatestartrack',methods=["GET","POST"])
def biosupdatestartrack():
    savepath = os.environ['UPLOADPATH']
    fuopath = os.environ['FUOPATH']
    biosfile = savepath + "bios.222"
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])    
    if request.method == "POST":
        bstime = time.time()
        me = StrToBool(request.form['me'])
        nvram = StrToBool(request.form['nvram'])
        smbios = StrToBool(request.form['smbios'])
        data = []
        for i in range(len(df_pwd)):
            data.append([])
            data[i].append("https://" + list(df_pwd['ip'])[i])
            data[i].append(list(df_pwd['pwd'])[i])
            data[i].append(biosfile)
            data[i].append(me)
            data[i].append(nvram)
            data[i].append(smbios)
        printf(data)
        flag = read_flag()
        while flag != 0:
            flag = read_flag()
            time.sleep(1)
        insert_flag(2)
        with Pool() as p:
            biosflag = p.map(updateBIOSrack, data)
        time.sleep(3)
        insert_flag(0)
        bftime = time.time()
        tspend = str(int(bftime - bstime)) + " secs"
    if 1 in biosflag:
        ip_nocomplete = []
        for i in range(len(biosflag)):
            if biosflag[i] == 1:
                ip_nocomplete.append(list(df_pwd['ip'])[i] + " Not Completed!")
            else:
                ip_nocomplete.append(list(df_pwd['ip'])[i])
        return render_template('biosupdateresult.html', ips = ip_nocomplete,rackname=rackname, me = str(me), nvram = str(nvram), smbios = str(smbios), tspend = tspend, completion = "Not Completed!",rackobserverurl = rackobserverurl)
    os.remove(fuopath)
    return render_template('biosupdateresult.html', ips = list(df_pwd['ip']),rackname=rackname, me = str(me), nvram = str(nvram), smbios = str(smbios), tspend = tspend, completion = "Completed!",rackobserverurl = rackobserverurl)

@app.route('/biosupdatestart',methods=["GET","POST"])
def biosupdatestart():
    savepath = os.environ['UPLOADPATH']
    fuopath = os.environ['FUOPATH']
    IPMI = "https://" + request.args.get('var')
    username = "ADMIN"
    pwd = find_password(request.args.get('var'))
    auth = (username,pwd)
    biosfile = savepath + "bios.222"
    if request.method == "POST":
        bstime = time.time()
        me = request.form['me']
        nvram = request.form['nvram']
        smbios = request.form['smbios']
        flag = read_flag()
        flag_list = read_all_flag()
        while flag != 0 or (flag_list.count(3) != flag_list.count(4)): # redfish request not finished or reboot not finished 
            flag = read_flag()
            flag_list = read_all_flag()
            time.sleep(1)
        insert_flag(2) # updating start
        biosflag = BiosUpdatingMode(IPMI,auth)
        if biosflag != None:
            CancelBiosUpdate(IPMI,auth)
            bftime = time.time()
            tspend = str(int(bftime - bstime)) + " secs"
            insert_flag(0) # updating ended
            return render_template('biosupdateresult.html', ips = [IPMI + " Not Completed!!"], me = str(StrToBool(me)), nvram = str(StrToBool(nvram)), smbios = str(StrToBool(smbios)), tspend = tspend, completion = "Not Completed!",rackname=rackname,rackobserverurl = rackobserverurl)
        biosflag = BiosUploadingFile(IPMI,biosfile,auth)
        if biosflag != None:
            CancelBiosUpdate(IPMI,auth)
            bftime = time.time()
            tspend = str(int(bftime - bstime)) + " secs"
            insert_flag(0) # updating ended
            return render_template('biosupdateresult.html', ips = [IPMI + " Not Completed!!"], me = str(StrToBool(me)), nvram = str(StrToBool(nvram)), smbios = str(StrToBool(smbios)), tspend = tspend, completion = "Not Completed!",rackname=rackname,rackobserverurl = rackobserverurl)
        biosflag = BiosStartUpdating(IPMI,auth,StrToBool(me),StrToBool(nvram),StrToBool(smbios))
        if biosflag != None:
            CancelBiosUpdate(IPMI,auth)
            bftime = time.time()
            tspend = str(int(bftime - bstime)) + " secs"
            insert_flag(0) # updating ended
            return render_template('biosupdateresult.html', ips = [IPMI + " Not Completed!!"], me = str(StrToBool(me)), nvram = str(StrToBool(nvram)), smbios = str(StrToBool(smbios)), tspend = tspend, completion = "Not Completed!",rackname=rackname,rackobserverurl = rackobserverurl)
        systemRebootTesting(IPMI,auth,"GracefulRestart")
        time.sleep(3)
        insert_flag(0) # updating ended
        bftime = time.time()
        tspend = str(int(bftime - bstime)) + " secs"
    os.remove(fuopath)
    return render_template('biosupdateresult.html', ips = [IPMI], me = str(StrToBool(me)), nvram = str(StrToBool(nvram)), smbios = str(StrToBool(smbios)), tspend = tspend, completion = "Completed",rackname=rackname,rackobserverurl = rackobserverurl)


@app.route('/bmcupload',methods=["GET","POST"])
def bmcupload():
    savepath = os.environ['UPLOADPATH']
    if request.method == "POST":
        if request.files:
            bmcfile = request.files["file"]
            if bmcfile.filename == "":
                printf("Input file must have a filename")
                return redirect(url_for('bmcupload'))
            bmcfile.save(os.path.join(savepath, "bmc.bin"))
            printf("{} has been saved as bmc.bin".format(bmcfile.filename))
            return redirect(url_for('bmcupload'))
    return render_template('bmcupload.html',ip_list = getIPlist(),rackname=rackname,rackobserverurl = rackobserverurl)

@app.route('/bmcupdaterack',methods=["GET","POST"])
def bmcupdaterack():
    if not redfish_session_creator(): #### Check if a session is active...
        error = ["ERROR: An instance of the RedFish API server controller have been detected.", "Someone might be using this feature.", "Since, this page can create some conflict with multiple users, please only have one instance open."]
        return render_template('simpleresult.html',messages = error)
    ip = str(request.args.get('var'))
    if ip == "ALL":
        ipstr = ",".join(str(x) for x in getIPlist())
        return render_template('bmcupdaterack.html',ip = ipstr,numOfNodes=len(getIPlist()),rackname=rackname,rackobserverurl = rackobserverurl, session_auth = redfish_session_info['guid'])
    else:
        return render_template('bmcupdaterack.html',ip = ip,numOfNodes=1,rackname=rackname,rackobserverurl = rackobserverurl, session_auth = redfish_session_info['guid'])

@app.route('/bmcupdatestartrack',methods=["GET","POST"])
def bmcupdatestartrack():
    savepath = os.environ['UPLOADPATH']
    fuopath = os.environ['FUOPATH']
    bmcfile = savepath + "bmc.bin"
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    if request.method == "POST":
        bstime = time.time()
        ip_list = request.form['inputips'].split(',')
        cfg = StrToBool(request.form['cfg'])
        sdr = StrToBool(request.form['sdr'])
        ssl = StrToBool(request.form['ssl'])
        data = []
        for i in range(len(ip_list)):
            data.append([])
            data[i].append("https://" + ip_list[i])
            data[i].append(df_pwd[df_pwd['ip'] == ip_list[i]]['pwd'].values[0])
            data[i].append(bmcfile)
            data[i].append(cfg)
            data[i].append(sdr)
            data[i].append(ssl)
        printf(data)
        flag = read_flag()
        while flag != 0:
            flag = read_flag()
            time.sleep(1)
        insert_flag(2)
        with Pool() as p:
            bmcflag = p.map(updateBMCrack, data)
        bftime = time.time()
        tspend = str(int(bftime - bstime)) + " secs"
    if 1 in bmcflag:
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": Checking BMC status.\n")
        for ip, pwd in zip(list(df_pwd['ip']),list(df_pwd['pwd'])):
            while redfishReadyCheck("https://"+ip,("ADMIN",pwd)) != 0:
                time.sleep(5)
        insert_flag(0)      
        ip_nocomplete = []
        for i in range(len(bmcflag)):
            if bmcflag[i] == 1:
                ip_nocomplete.append(list(df_pwd['ip'])[i] + " Not Completed!")
            else:
                ip_nocomplete.append(list(df_pwd['ip'])[i])       
        return render_template('firmupdateresult.html', ips = ip_nocomplete, cfg = str(cfg), sdr = str(sdr), ssl = str(ssl), tspend = tspend, completion = "Not Completed!",rackname=rackname,rackobserverurl = rackobserverurl)
    with open(fuopath, 'a') as rprint:
        rprint.write(time.asctime() + ": Checking BMC status.\n")
    for ip, pwd in zip(list(df_pwd['ip']),list(df_pwd['pwd'])):
        while redfishReadyCheck("https://"+ip,("ADMIN",pwd)) != 0:
            time.sleep(5)
    os.remove(fuopath)
    insert_flag(0)
    return render_template('firmupdateresult.html', ips = ip_list, cfg = str(cfg), sdr = str(sdr), ssl = str(ssl), tspend = tspend, completion = "Completed",rackname=rackname,rackobserverurl = rackobserverurl)


@app.route('/firmwareupdatestatus')
def firmwareupdatestatus():
    fuopath = os.environ['FUOPATH']
    try:
        with open(fuopath, 'r') as rprint:
            data = []
            for line in rprint.readlines():
                data.append(line.replace('\n',''))
    except:
        data = ['Not Started Yet']
    return render_template('firmwareupdatestatus.html',data=data,rackname=rackname,rackobserverurl = rackobserverurl)

@app.route('/bmceventcleanerupload')
def bmceventcleanerupload():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    try:
        df_input = pd.read_csv(savepath+"bmceventcleanerip.txt",header=None,names=['ip'])
        inputips = list(df_input['ip'])
    except:
        inputips = []
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    allips = list(df_pwd['ip'])
    indicators = []
    for i in range(len(allips)):
        if allips[i] in inputips:
            indicators.append(1)
        else:
            indicators.append(0)
    return render_template('bmceventcleanerupload.html',data=zip(allips,indicators),rackname=rackname,rackobserverurl = rackobserverurl,frontend_urls = get_frontend_urls())

@app.route('/checkSelectedIPs')
def checkSelectedIps():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])       
    if request.args.get('iptype') == 'os':
        allips = list(df_pwd['os_ip'])
    else:
        allips = list(df_pwd['ip'])
    try:
        if request.args.get('filetype') == "suminput": # sum input file is different
            df_input = pd.read_csv(savepath+ request.args.get('filetype') + ".txt",header=None,sep='\s+',names=['ip','user','pwd'])
        elif request.args.get('filetype') == "ansible":
            df_input = pd.read_csv('/app/inventory.ini',header=None,sep='\s+',names=['ip','host','user','pwd'])
        else:
            df_input = pd.read_csv(savepath+ request.args.get('filetype') + ".txt",header=None,names=['ip'])
        inputips = list(df_input['ip'])
    except:
        inputips = []
        response = {}
        for ip in allips:
            response[ip] = "false"
        if os.path.exists(savepath+ request.args.get('filetype') +".txt"):
            os.remove(savepath+ request.args.get('filetype') +".txt")
        return json.dumps(response)
    else:
        indicators = {}
        for i in range(len(allips)):
            if allips[i] in inputips:
                indicators[allips[i]] = "true"
            else:
                indicators[allips[i]] = "false"
        response = json.dumps(indicators)
        return response

@app.route('/deselectIP', methods=["GET"])
def deselectIPs():
    if request.method == "GET":
        sel_ip = request.args.get('ip')
        if request.args.get('inputtype') == "ansible":
            savepath = '/app/inventory.ini'
        else:
            savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + str(request.args.get('inputtype'))  + ".txt"
        if "all" in sel_ip:
            if os.path.isfile(savepath):
                os.remove(savepath)
                response = {"SUCCESS": "Cleared all IPs"}
                return json.dumps(response)
            else:
                response = {"ERROR" : "No IPs to be cleared"}
                return json.dumps(response)
        else:
            if os.path.isfile(savepath):
                if request.args.get('inputtype') == "suminput":
                    df_ipmi = pd.read_csv(savepath,header=None,sep='\s+',names=['ip','user','pwd'])
                elif request.args.get('inputtype') == "ansible":
                    df_ipmi = pd.read_csv('/app/inventory.ini',header=None,sep='\s+',names=['ip','host','user','pwd'])
                    selected_users = list(df_ipmi['user'])
                    selected_pwds = list(df_ipmi['pwd'])
                else:
                    df_ipmi = pd.read_csv(savepath,header=None,names=['ip'])
                selected_ips = list(df_ipmi['ip'])
                if sel_ip in selected_ips:
                    if request.args.get('inputtype') == "ansible":
                        item_loc = selected_ips.index(sel_ip)
                        del selected_users[item_loc]
                        del selected_pwds[item_loc]
                    selected_ips.remove(sel_ip)
                else:
                    response = {"ERROR": "Error: IP was not selected initially"}
                    return json.dumps(response)
                os.remove(savepath)
                iplist = selected_ips
                df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd']) 
                ipmi_list = list(df_pwd['ip'])
                osip_list = list(df_pwd['os_ip'])
                if request.args.get('inputtype') == "ansible":                            
                    with open(savepath,"w") as fileinput:
                        for ip, ansible_usr, ansible_pwd in zip(iplist, selected_users, selected_pwds):
                            fileinput.write('{} ansible_host={} {} {}\n'.format(ip, ip, ansible_usr, ansible_pwd))
                    response = {"SUCCESS" : "Removed " + sel_ip + " from selection"}
                    print("Saved file...",flush=True)
                else:
                    with open(savepath,"w") as fileinput:
                        for ip in iplist:
                            if request.args.get('iptype') == "ipmi" and ip in ipmi_list:
                                current_pwd = df_pwd[df_pwd['ip'] == ip]['pwd'].values[0]
                                if 'suminput' in savepath:
                                    fileinput.write(ip + ' ADMIN ' + current_pwd  + '\n')
                                else:
                                    fileinput.write(ip + '\n')
                            elif request.args.get('iptype') == "os" and ip in osip_list:
                                fileinput.write(ip + '\n')
                        response = {"SUCCESS" : "Removed " + sel_ip + " from selection"}
                        print("Saved file...",flush=True)
                if os.path.isfile(savepath):
                    return json.dumps(response)
                else:
                    response = {"ERROR": "Error: Could not remove IP from selection, error saving file"}
                    return json.dumps(response)
            else:
                response = {"ERROR": "Error: Could not remove IP from selection, no IPs selected"}
                return json.dumps(response)
                
@app.route('/generate_quickBench')
def generate_quickBench():
    if request.method == 'GET':
        savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
        bench_config = get_data.quick_benchmark_configs(request.args.get('bench'))
        with open(savepath+"udpinput.json",'w') as file:
            json.dump(bench_config,file)
        response = json.dumps(bench_config)
        return response


@app.route('/uploadinputipsfileforall',methods=["POST"]) # used for all input file upload
def uploadinputipsfileforall():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    filetype = request.args.get('filetype')
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])       
    if request.args.get('iptype') == 'os':
        allips = list(df_pwd['os_ip'])
    else:
        allips = list(df_pwd['ip'])    
    if request.method == "POST":
        if request.files:
            if "Benchmark" not in filetype and "ansible" not in filetype:
                ipfile = request.files["file"]
                if ipfile.filename == "":
                    printf("Input file must have a filename")
                    response = {"response":"Error: Input file must have a filename"}
                else:
                    ipfile.save(savepath+ filetype +".txt.bak")
                    if filetype == "suminput":
                        df_input = pd.read_csv(savepath+ request.args.get('filetype') + ".txt.bak",header=None,sep='\s+',names=['ip','user','pwd'])
                    else:
                        df_input = pd.read_csv(savepath+ request.args.get('filetype') + ".txt.bak",header=None,names=['ip'])
                    df_input[df_input['ip'].isin(allips)].to_csv(savepath+ request.args.get('filetype') + ".txt",header=None,index=None,sep=' ')
                    printf("Input ip file has been saved as " + filetype + ".txt".format(ipfile.filename))
                    os.remove(savepath+ filetype +".txt.bak")
                    response = {"response": "inputfile has been saved as " + filetype + ".txt" }
                response = json.dumps(response)
            else:
                if filetype == "Benchmark": # benchmark json file
                    udpinputfile = request.files["inputfile"]
                    if udpinputfile.filename == "":
                        printf("Input file must have a filename")
                        response = {"ERROR":"Input file must have a filename"}
                    else:
                        udpinputfile.save(savepath+"udpinput.json")
                        printf("{} has been saved as udpinput.json".format(udpinputfile.filename))
                        response = {"SUCCESS":"{} has been saved".format(udpinputfile.filename)}
                elif filetype == "ansible_playbook": # ansible playbook
                    playbookfile = request.files["playbook"]
                    if playbookfile.filename == "":
                        response = {"ERROR":"Input file must have a filename"}
                    else:
                        playbookfile.save('/app/ansible-playbook_l12cm.yml')                    
                        response = {"SUCCESS":"{} has been saved as ansible-playbook_l12cm.yml".format(playbookfile.filename)}                      
                else: # benchmark input file
                    udpinputfile = request.files["bminputfile"]
                    if udpinputfile.filename == "":
                        response = {"ERROR":"Input file must have a filename"}
                    else:
                        udpinputfile.save(os.environ['UPLOADPATH'] + udpinputfile.filename)
                        printf("{} has been saved".format(udpinputfile.filename))
                        response = {"SUCCESS":"{} has been saved".format(udpinputfile.filename)}
                response = json.dumps(response)
            return response
            
@app.route('/ansible_syntax_check', methods=["GET"])
def ansible_syntax_check():
    cur_cmd = 'ansible-playbook /app/ansible-playbook_l12cm.yml -i /app/inventory.ini --syntax-check'
    with open(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + '-ansible.log','a') as ansible_log:
        ansible_log.write('\n')
        ansible_log.write('**********************************************Ansible Syntax Check**********************************************\n')
        ansible_log.write('[' + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + '] Running ansible command:' + cur_cmd + '\n') 
    process = Popen(cur_cmd, shell=True, stdout=PIPE, stderr=PIPE)
    stdout, stderr = process.communicate(timeout=5)
    output_string = stdout.decode("utf-8") + stderr.decode("utf-8")
    output = stdout.decode("utf-8").split('\n') + stderr.decode("utf-8").split('\n')
    output_strip = []
    for line in output:
        output_strip.append(line.strip())
    if 'ERROR' in output_string:
        output_strip.append("Info: /app/ansible-playbook_l12cm.yml failed the syntax check.")
        output_strip.append("Syntax-Check: FAILED")
        output_strip.append("********************************************************************************")
        response = {"ERROR": output_strip}
    else:
        output_strip.append("Info: /app/ansible-playbook_l12cm.yml passed the syntax check.")
        output_strip.append("Syntax-Check: PASS")
        output_strip.append("********************************************************************************")
        response = {"SUCCESS": output_strip}  
    response = json.dumps(response)
    return response
    
@app.route('/ansible_controller')
def ansible_controller():
    try:
        df_input = pd.read_csv("/app/inventory.ini",header=None,names=['ip','host','user','pwd'])
        inputips = list(df_input['ip'])
    except:
        inputips = []
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    allips = list(df_pwd['os_ip'])
    indicators = []
    for i in range(len(allips)):
        if allips[i] in inputips:
            indicators.append(1)
        else:
            indicators.append(0)
    return render_template('ansible_controller.html',data=zip(allips,indicators),rackname=rackname,rackobserverurl = rackobserverurl,frontend_urls = get_frontend_urls())

@app.route('/ansible_read_log', methods=["GET"])
def ansible_read_log():
    ansible_uuid = str(request.args.get('uuid'))
    file_path = '/app/log.ansible-{}'.format(ansible_uuid)
    file_lines = []
    counter = 0
    while fileEmpty(file_path) and counter < 10:
        time.sleep(0.5)
        counter += 1
    with open(file_path, "r") as ansible_single_log:
        for line in ansible_single_log:
            line = line.strip()
            file_lines.append(line)
    response = json.dumps({'SUCCESS': file_lines})
    if file_lines[-1] == "----------------------------------------------Last Line of UUID: {}----------------------------------------------". format(ansible_uuid):
        os.remove(file_path)
    return response
    
@app.route('/ansibleplaybookexecute',methods=["GET"])
def ansibleplaybookexecute():
    ansible_become = int(request.args.get('become'))
    ansible_become_usr = str(request.args.get('become_usr'))
    ansible_become_pass = str(request.args.get('become_pwd'))
    ansible_uuid = str(request.args.get('uuid'))
    if ansible_become == 1:
        # copy the ansible cfg file
        cur_cmd = 'ansible-playbook /app/ansible-playbook_l12cm.yml -f 300 -i /app/inventory.ini --become-user {} -b --extra-vars="ansible_become_pass={}"  2>&1 | tee /app/log.ansible-{}'.format(ansible_become_usr,ansible_become_pass,ansible_uuid)
        with open(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + '-ansible.log','a') as ansible_log:
            ansible_log.write('\n')
            ansible_log.write('**********************************************Ansible Playbook**********************************************\n')
            ansible_log.write('[' + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + '] Running ansible command:' + cur_cmd + '\n') 
        process = Popen(cur_cmd, shell=True, stdout=PIPE, stderr=PIPE)
        stdout, stderr = process.communicate()
        output_string = stdout.decode("utf-8") + stderr.decode("utf-8")
        output = stdout.decode("utf-8").split('\n') + stderr.decode("utf-8").split('\n')
        output_strip = []
        for line in output:
            output_strip.append(line.strip())      
        response = {"SUCCESS": "DONE"}
    else:
        cur_cmd = 'ansible-playbook /app/ansible-playbook_l12cm.yml -f 300 -i /app/inventory.ini 2>&1 | tee /app/log.ansible-{}'.format(ansible_uuid)
        with open('/app/log.ansible-{}'.format(ansible_uuid),'a') as ansible_log:
            ansible_log.write('\n')
            ansible_log.write('**********************************************Ansible Playbook**********************************************\n')
            ansible_log.write('[' + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + '] Running ansible command:' + cur_cmd + '\n') 
        process = Popen(cur_cmd, shell=True, stdout=PIPE, stderr=PIPE)
        stdout, stderr = process.communicate()
        output_string = stdout.decode("utf-8") + stderr.decode("utf-8")
        output = stdout.decode("utf-8").split('\n') + stderr.decode("utf-8").split('\n')
        output_strip = []
        for line in output:
            output_strip.append(line.strip())      
        response = {"SUCCESS": "DONE"}
    # Append last line to ansible single log
    with open('/app/log.ansible-{}'.format(ansible_uuid),'a') as ansible_single_log:
        ansible_single_log.write("----------------------------------------------Last Line of UUID: {}----------------------------------------------". format(ansible_uuid))
    response = json.dumps(response)
    return response

@app.route('/ansiblecommandline',methods=["GET"])
def ansiblecommandline():
    ansible_command = str(request.args.get('ansible_cmd'))
    cur_cmd = 'ansible {} -f 300 -i /app/inventory.ini all'.format(ansible_command)
    with open(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + '-ansible.log','a') as ansible_log:    
        ansible_log.write('\n')
        ansible_log.write('**********************************************Ansible Commandline**********************************************\n')
        ansible_log.write('[' + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + '] Running ansible command:' + cur_cmd + '\n') 
    process = Popen(cur_cmd, shell=True, stdout=PIPE, stderr=PIPE)
    stdout,stderr = process.communicate()    
    output = stdout.decode("utf-8").split('\n') + stderr.decode("utf-8").split('\n')
    output_strip = []
    for line in output:
        output_strip.append(line.strip())  
    response = {"SUCCESS": output_strip}
    response = json.dumps(response)
    return response

@app.route('/ansiblebuiltinpackage',methods=["GET"])
def ansiblebuiltinpackage():
    package_name = str(request.args.get('packagename'))
    ansible_uuid = str(request.args.get('uuid'))
    if package_name == "udpclient":        
        with open("/app/ansiblepackages/playbook-udpclient-package.yaml", 'r') as input_f:
            yml_file = input_f.read() % (get_ip() + ':8888')
    elif package_name == "l12-metrics":
        with open("/app/ansiblepackages/playbook-l12-metrics-package.yaml", 'r') as input_f:
            yml_file = input_f.read() % (get_ip())      
    elif package_name == "python3":
        with open("/app/ansiblepackages/playbook-python3-package.yaml", 'r') as input_f:
            yml_file = input_f.read()       
    elif package_name == "checkos":
        with open("/app/ansiblepackages/playbook-checkOS.yaml", 'r') as input_f:
            yml_file = input_f.read()   
    else:
        return json.dumps({"ERROR": ['Package is not supported.']})    
    with open("/app/ansible-playbook_builtin_package.yml", "w") as output_f:
        output_f.write(yml_file)
    cur_cmd = 'ansible-playbook /app/ansible-playbook_builtin_package.yml -f 300 -i /app/inventory.ini | tee /app/log.ansible-{}'.format(ansible_uuid)
    with open(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + '-ansible.log','a') as ansible_log:    
        ansible_log.write('\n')
        ansible_log.write('**********************************************Ansible Builtin Package**********************************************\n')
        ansible_log.write('[' + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + '] Running ansible command:' + cur_cmd + '\n') 
    process = Popen(cur_cmd, shell=True, stdout=PIPE, stderr=PIPE)
    stdout,stderr = process.communicate()    
    output = stdout.decode("utf-8").split('\n') + stderr.decode("utf-8").split('\n')
    output_strip = []
    for line in output:
        output_strip.append(line.strip())  
    response = {"SUCCESS": "Done"}
    # Append last line to ansible single log
    with open('/app/log.ansible-{}'.format(ansible_uuid),'a') as ansible_single_log:
        ansible_single_log.write("----------------------------------------------Last Line of UUID: {}----------------------------------------------". format(ansible_uuid))
    response = json.dumps(response)
    os.remove("/app/ansible-playbook_builtin_package.yml")
    return response

@app.route('/ansibleuninstall',methods=["GET"])
def ansibleuninstall():
    package_name = str(request.args.get('packagename'))
    ansible_uuid = str(request.args.get('uuid'))
    if package_name == "udpclient":        
        with open("/app/ansiblepackages/playbook-udpclient-uninstall.yaml", 'r') as input_f:
            yml_file = input_f.read()
    elif package_name == "l12-metrics": 
        with open("/app/ansiblepackages/playbook-l12-metrics-uninstall.yaml", 'r') as input_f:
            yml_file = input_f.read()
    else:
        return json.dumps({"ERROR": ['Package is not supported.']})    
    with open("/app/ansible-playbook_uninstall.yml", "w") as output_f:
        output_f.write(yml_file)
    cur_cmd = 'ansible-playbook /app/ansible-playbook_uninstall.yml -f 300 -i /app/inventory.ini | tee /app/log.ansible-{}'.format(ansible_uuid)
    with open(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + '-ansible.log','a') as ansible_log:    
        ansible_log.write('\n')
        ansible_log.write('**********************************************Ansible Pacakge Uninstall**********************************************\n')
        ansible_log.write('[' + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + '] Running ansible command:' + cur_cmd + '\n')     
    process = Popen(cur_cmd, shell=True, stdout=PIPE, stderr=PIPE)
    stdout,stderr = process.communicate()    
    output = stdout.decode("utf-8").split('\n') + stderr.decode("utf-8").split('\n')
    output_strip = []
    for line in output:
        output_strip.append(line.strip())  
    response = {"SUCCESS": "DONE"}
    # Append last line to ansible single log
    with open('/app/log.ansible-{}'.format(ansible_uuid),'a') as ansible_single_log:
        ansible_single_log.write("----------------------------------------------Last Line of UUID: {}----------------------------------------------". format(ansible_uuid))
    response = json.dumps(response)
    os.remove("/app/ansible-playbook_uninstall.yml")
    return response
    
@app.route('/bmceventcleanerstart',methods=["GET"])
def bmceventcleanerstart():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    if request.method == "GET":
        if fileEmpty(savepath+"bmceventcleanerip.txt"):
            response = {"ERROR":"No file found, try inserting the IPs again...."}
            return json.dumps(response)
        df_cleaner = pd.read_csv(savepath+"bmceventcleanerip.txt",names=['ip'])
        '''
        try:
            df_cleaner = pd.read_csv(savepath+"bmceventcleanerip.txt",names=['ip'])
        except:
            return render_template('error.html',error="No input file found!")
        '''
        df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])       
        iplist = list(df_cleaner['ip'])
        iplist_rack = list(df_pwd['ip'])
        data = []
        for i in range(len(iplist)):
            if iplist[i] not in iplist_rack:
                response = {"ERROR": "Assigned ip " + iplist[i] + " not belongs current rack!"}
                return json.dumps(response)
            else:
                data.append([])
                data[i].append(iplist[i])
                data[i].append(df_pwd[df_pwd['ip'] == iplist[i]]['pwd'].values[0])            
        with Pool() as p:
            p.map(bmceventcleanerone, data)
        os.remove(savepath+"bmceventcleanerip.txt")
        messages = []
        messages.append("BMC events has been cleaned up for the following IPs:")
        messages += iplist
        response = {}
        for i,ip in enumerate(iplist):
            response[str(i)] = ip
        return json.dumps(response)

@app.route('/ipmitoolcommandlineupload')
def ipmitoolcommandlineupload():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    try:
        df_input = pd.read_csv(savepath+"ipmitoolip.txt",header=None,names=['ip'])
        inputips = list(df_input['ip'])
    except:
        inputips = []
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    allips = list(df_pwd['ip'])
    indicators = []
    for i in range(len(allips)):
        if allips[i] in inputips:
            indicators.append(1)
        else:
            indicators.append(0)
    return render_template('ipmitoolcommandlineupload.html',data = zip(allips, indicators),rackname=rackname,rackobserverurl = rackobserverurl,frontend_urls = get_frontend_urls())

@app.route('/ipmitoolstart',methods=["GET"])
def ipmitoolstart(): ### Take a command for processing and distribution to servers
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    if request.method == "GET":
        if fileEmpty(savepath+"ipmitoolip.txt"):
            response = {"ERROR": "No input IP found!"}
            return json.dumps(response)
        df_ipmi = pd.read_csv(savepath+"ipmitoolip.txt",names=['ip'])
        '''
        try:
            df_ipmi = pd.read_csv(savepath+"ipmitoolip.txt",names=['ip'])
        except:
            return render_template('error.html',error="No input file found!")
        '''
        df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])       
        iplist = list(df_ipmi['ip'])
        iplist_rack = list(df_pwd['ip'])
        data = []
        for i in range(len(iplist)):
            if iplist[i] not in iplist_rack:
                response = {"ERROR": "Assigned ip " + iplist[i] + " not belongs current rack!"}
                return json.dumps(response)
            else:
                data.append([])
                data[i].append(iplist[i])
                data[i].append(df_pwd[df_pwd['ip'] == iplist[i]]['pwd'].values[0])
                data[i].append(request.args.get('command'))
        response = {}
        with concurrent.futures.ProcessPoolExecutor() as executor:
            future_to_output = {executor.submit(ipmistartone, ip_com): ip_com for ip_com in data}
            for future in concurrent.futures.as_completed(future_to_output):
                output = future.result()                
                for ip in output:
                    response[ip] = output[ip]
        ordered_response = {}
        for ordered_ip in data:
            ip = ordered_ip[0]
            for bmc_ip in response:
                if ip == bmc_ip:
                    ordered_response[ip] = response[ip]
        del response
        response = ordered_response
        for ip in response:
            for typeOfoutput in response[ip]:
                for output in response[ip][typeOfoutput]: ###Check for key words in command that denote an error from the IPMITOOL response. Display only one error for all servers.
                    if "Invalid" in response[ip][typeOfoutput][output] or "No&nbsp;command&nbsp;provided!" in response[ip][typeOfoutput][output] or "Commands:"  in response[ip][typeOfoutput][output]:
                        error_response = {}
                        error_response["IPMI Tool Error Response"] = response[ip]
                        return json.dumps(error_response)
                    elif "ipmitool&nbsp;version" in response[ip][typeOfoutput][output]:
                        help_response = {}
                        help_response["IPMI Tool Help"] = response[ip]
                        return json.dumps(help_response)
                    else: ###tReturn original response for all servers.
                        return json.dumps(response) ### Response JSON is in the form of {"IP":{"STDOUT":{"0":"outputLine0","1":"outputLine1"}}}

def ipmistartone(data_list): ###Execute IPMItool command. data_list is a list in the form of [[ip,pwd,cmd],[ip,pwd,cmd]]
    ip = data_list[0]
    pwd = data_list[1]
    ipmicmd = data_list[2]
    response = {}
    try:
        process = Popen('ipmitool ' + ' -H ' +  ip + ' -U ' + 'ADMIN' + ' -P ' + pwd + ' ' + ipmicmd, shell=True, stdout=PIPE, stderr=PIPE)
        stdout, stderr = process.communicate(timeout=2)
    except:
        response = {ip : {"output":{"0":"No response from BMC"}}}
    else: ### Create a dictionary style response in the form of {"STDOUT":{"0":"outputLine0","1":"outputLine1"}}. This is because it will be sent to the HTML web page for processing in JSON format.
        if stdout.decode() == '':
            response = {ip : {"output":{}}}
            for i,line in enumerate(stderr.decode().split('\n')):
                response[ip]["output"][str(i)] = line.replace(" ","&nbsp;")
        else:
            response = {ip : { "output":{}}}
            for i,line in enumerate(stdout.decode().split('\n')):
                response[ip]["output"][str(i)] = line.replace(" ","&nbsp;")
    return response

def bmceventcleanerone(data_list):
    ip = data_list[0]
    pwd = data_list[1]
    os.popen("ipmitool -I lanplus -H " + ip + " -U ADMIN -P " + pwd + " sel clear")

def StrToBool(input):
    if input == "1":
        return(True)
    else:
        return(False)

def insert_flag(flag):
    flag_path = os.environ['FLAGPATH']
    with open(flag_path, 'a') as flag_file:
        flag_file.write(str(flag) + ',' + time.ctime()  + '\n')  

def read_flag():
    with open(os.environ['FLAGPATH'], 'r') as flag_file:
        flag = int(flag_file.readlines()[-1].split(',')[0])
    return flag

def read_all_flag():
    flag_list = []
    with open(os.environ['FLAGPATH'], 'r') as flag_file:
        for line in flag_file.readlines():
            flag_list.append(line.split(',')[0])
    return flag_list

def updateBIOSrack(data_list):
    IPMI = data_list[0]
    auth = ("ADMIN",data_list[1])
    filepath = data_list[2]
    me = data_list[3]
    nvram = data_list[4]
    smbios = data_list[5]
    biosflag = BiosUpdatingMode(IPMI,auth)
    if biosflag != None:
        CancelBiosUpdate(IPMI,auth)
        return(1)
    biosflag = BiosUploadingFile(IPMI,filepath,auth)
    if biosflag != None:
        CancelBiosUpdate(IPMI,auth)
        return(1)
    biosflag = BiosStartUpdating(IPMI,auth,me,nvram,smbios)
    if biosflag != None:
        CancelBiosUpdate(IPMI,auth)
        return(1)
    systemRebootTesting(IPMI,auth,"GracefulRestart")
    #return(IPMI + " update done!")
    return(0)

def updateBMCrack(data_list):
    IPMI = data_list[0]
    auth = ("ADMIN",data_list[1])
    filepath = data_list[2]
    cfg = data_list[3]
    sdr = data_list[4]
    ssl = data_list[5]
    bmcflag = FirmUpdatingMode(IPMI,auth)
    if bmcflag == 1:
        CancelFirmUpdate(IPMI,auth)
        return(1)
    bmcflag = FirmUploadingFile(IPMI,filepath,auth)
    if bmcflag == 1:
        CancelFirmUpdate(IPMI,auth)
        return(1)
    bmcflag = FirmStartUpdating(IPMI,auth,cfg,sdr,ssl)
    if bmcflag == 1:
        CancelFirmUpdate(IPMI,auth)
        return(1)
    #systemRebootTesting(IPMI,auth,"GracefulRestart")
    return(0)


def IPRangeToList(start, end):
    try:
        start_int = int(ip_address(start).packed.hex(), 16)
        end_int = int(ip_address(end).packed.hex(), 16)
    except:
        return(0)
    else:
        if end_int - start_int > 500:
            return(1)
        else:
            return [ip_address(ip).exploded for ip in range(start_int, end_int)]
    
@app.route('/advanceinputgenerator',methods=['GET', 'POST'])
def advanceinputgenerator():
    if request.method == "POST":
        savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + request.form['inputtype']  + ".txt"
        ipstart = request.form['ipstart']
        ipend = request.form['ipend']
        iplist = IPRangeToList(ipstart,ipend)
        if iplist == 0:
            return render_template('error.html',error="Invalid input format!")
        elif iplist == 1:
            return render_template('error.html',error="Range too large!")
        elif len(iplist) == 0:
            return render_template('error.html',error="No input IP obtained!") 
        df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd']) 
        ipmi_list = list(df_pwd['ip'])
        osip_list = list(df_pwd['os_ip'])
        with open(savepath,"w") as cleanerinput:
            for ip in iplist:
                if request.form['iptype'] == "ipmi" and ip in ipmi_list:
                    current_pwd = df_pwd[df_pwd['ip'] == ip]['pwd'].values[0]
                    if 'suminput' in savepath:
                        cleanerinput.write(ip + ' ADMIN ' + current_pwd  + '\n')
                    else:
                        cleanerinput.write(ip + '\n')
                elif request.form['iptype'] == "os" and ip in osip_list:
                    cleanerinput.write(ip + '\n')
        return redirect(url_for(request.form['redirectpage']))

@app.route('/advanceinputgenerator_ajaxVersion', methods=["GET"])
def advanceinputgenerator_ajaxVerison():
    if request.method == "GET":
        if 'ansible' in str(request.args.get('inputtype')):           
            ansible_usr = str(request.args.get('usr'))
            ansible_pwd = str(request.args.get('pwd'))
            if 'ansible.cfg' not in os.listdir('/app'):
                with open('/app/ansible.cfg','w') as cfg:
                    cfg.write('[defaults]\n')
                    cfg.write('host_key_checking=False\n')
                    cfg.write('deprecation_warnings=False\n')
                    cfg.write('ansible_python_interpreter=/usr/bin/python3\n')
                    cfg.write('log_path=' + os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + '-ansible.log\n')
            savepath = '/app/inventory.ini'
        else:
            savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + str(request.args.get('inputtype'))  + ".txt"
        ipstart = request.args.get('ipstart')
        ipend = request.args.get('ipend')
        iplist = IPRangeToList(ipstart,ipend)
        if iplist == 0:
            response = {"ERROR":"ERROR: Invalid input format! "}
            response = json.dumps(response)
            return response
        elif iplist == 1:
            response = {"ERROR":"ERROR: Range too large! "}
            response = json.dumps(response)
            return response
        elif len(iplist) == 0:
            response = {"ERROR":"ERROR: No input IP obtained! "}
            response = json.dumps(response)
            return response 
        df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd']) 
        ipmi_list = list(df_pwd['ip'])
        osip_list = list(df_pwd['os_ip'])
        with open(savepath,"w") as cleanerinput:
            for ip in iplist:
                if 'ansible' in str(request.args.get('inputtype')):
                    cleanerinput.write('{} ansible_host={} {} {}\n'.format(ip, ip, ansible_usr, ansible_pwd))
                elif request.args.get('iptype') == "ipmi" and ip in ipmi_list:
                    current_pwd = df_pwd[df_pwd['ip'] == ip]['pwd'].values[0]
                    if 'suminput' in savepath:
                        cleanerinput.write(ip + ' ADMIN ' + current_pwd  + '\n')
                    else:
                        cleanerinput.write(ip + '\n')
                elif request.args.get('iptype') == "os" and ip in osip_list:
                    cleanerinput.write(ip + '\n')
            response = {"response" : "SUCCESS: saved file: " + savepath}
            print("Saved file...",flush=True)
        if os.path.isfile(savepath):
            return json.dumps(response)
        else:
            response = {"ERROR": "ERROR: could not save file " + savepath}
            return json.dumps(response)

@app.route('/advanceinputgenerator_all_ajaxVersion', methods=["GET"])
def advanceinputgenerator_all_ajaxVerison():
    if request.method == "GET":
        if 'ansible' in str(request.args.get('inputtype')):
            # write a cfg config file for excution part to use
            if 'ansible.cfg' not in os.listdir('/app'):
                with open('/app/ansible.cfg','w') as cfg:
                    cfg.write('[defaults]\n')
                    cfg.write('host_key_checking=False\n')
                    cfg.write('deprecation_warnings=False\n')
                    cfg.write('ansible_python_interpreter=/usr/bin/python3\n')
                    cfg.write('log_path=' + os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + '-ansible.log\n')
            ansible_usr = str(request.args.get('usr'))
            ansible_pwd = str(request.args.get('pwd'))
            savepath = '/app/inventory.ini'
        else:
            savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + str(request.args.get('inputtype'))  + ".txt"
        df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd']) 
        ip_list = list(df_pwd['ip'])
        osip_list = list(df_pwd['os_ip'])
        with open(savepath,"w") as cleanerinput:
            for ip, osip in zip(ip_list, osip_list):                
                if 'ansible' in str(request.args.get('inputtype')):
                    cleanerinput.write('{} ansible_host={} ansible_user={} ansible_ssh_pass={}\n'.format(osip, osip, ansible_usr, ansible_pwd))
                elif request.args.get('iptype') == "ipmi":
                    current_pwd = df_pwd[df_pwd['ip'] == ip]['pwd'].values[0]
                    if 'suminput' in savepath:
                        cleanerinput.write(ip + ' ADMIN ' + current_pwd  + '\n')
                    else:
                        cleanerinput.write(ip + '\n')
                elif request.args.get('iptype') == "os":
                    cleanerinput.write(osip + '\n')
                response = {"response" : "SUCCESS: saved file: " + savepath}
                print("Saved file...",flush=True)        
        if os.path.isfile(savepath):
            return json.dumps(response)
        else:
            response = {"ERROR": "ERROR: could not save file " + savepath}
            return json.dumps(response)

# this page might be deprecated        
@app.route('/sumlogpage',methods=['GET', 'POST'])
def sumlogpage():
    sumlogout = sumLogOutput()
    if sumlogout == 1:
        return render_template("sumLog.html", sumloglines = ['SUM is not running!!'],rackname=rackname,rackobserverurl = rackobserverurl)
    elif sumlogout == 2:
        return render_template("sumLog.html", sumloglines = ['Multiple SUM processes are detected, no output can be displayed!!'],rackname=rackname,rackobserverurl = rackobserverurl)
    sumloglines = ["SUM is running!!"]
    with open(sumlogout, "r") as sumlogfile:
        for line in sumlogfile:
            line = line.strip()
            sumloglines.append(line)
    return render_template("sumLog.html", sumloglines = sumloglines,rackname=rackname,rackobserverurl = rackobserverurl)

@app.route('/sumlogtermial')
def sumlogtermial():
    sumlogout = sumLogOutput()
    response = {'status':-1,'log_lines':[]}
    if sumlogout == 1:
        response['status'] = 1
        response['log_lines'] = ['SUM is IDLE ...']
        return json.dumps(response)
    elif sumlogout == 2:
        response['status'] = 2
        response['log_lines'] = ['Error: multiple SUM processes are detected, no output can be displayed!!']
        return json.dumps(response)
    response['status'] = 0
    response['log_lines'] = ['SUM is RUNNING NOW, Please do not submit multiple SUM request ...']
    with open(sumlogout, "r") as sumlogfile:
        for line in sumlogfile:
            line = line.strip()
            response['log_lines'].append(line)
    return json.dumps(response)

def sum_session_creator():
    time.sleep(0.100) ##### Fixes timing issue between page close and page reload
    if sum_session_info['state'] == 'active':
        printf("Failed to create new sum_server session")
        printf("Current SUM Session info is:")
        printf("state: " + sum_session_info['state'])
        printf("guid: " + sum_session_info['guid'])
        return False
    else:
        url_saf = secrets.token_urlsafe(8)
        sum_session_info['state'] = 'active'
        sum_session_info['guid'] = url_saf
        printf("Creating new sum_server session")
        printf("state: " + sum_session_info['state'])
        printf("guid: " + sum_session_info['guid'])
        return True

@app.route('/sumtoolboxupload',methods=['GET', 'POST'])
def sumtoolboxupload():
    if not sum_session_creator(): #### Check if a session is active...
        error = ["ERROR: An instance of the SUM server controller have been detected.", "Someone might be using this feature.", "Since, this page can create some conflict with multiple users, please only have one instance open."]
        return render_template('simpleresult.html',messages = error)
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    try:
        df_input = pd.read_csv(savepath+"suminput.txt",sep=" ",header=None,names=['ip','user','pwd'])
        inputips = list(df_input['ip'])
    except:
        inputips = []
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    allips = list(df_pwd['ip'])
    indicators = []
    for i in range(len(allips)):
        if allips[i] in inputips:
            indicators.append(1)
        else:
            indicators.append(0)
    return render_template('sumtoolboxupload.html',data = zip(allips, indicators),rackname=rackname,rackobserverurl = rackobserverurl,frontend_urls = get_frontend_urls(), session_auth = sum_session_info['guid'])

@app.route('/sumtoolboxterminal')
def sumtoolboxterminal():
    if not sum_session_creator(): #### Check if a session is active...
        error = ["ERROR: An instance of the SUM server controller have been detected.", "Someone might be using this feature.", "Since, this page can create some conflict with multiple users, please only have one instance open."]
        return render_template('simpleresult.html',messages = error)
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    try:
        df_input = pd.read_csv(savepath+"suminput.txt",header=None,names=['ip'])
        inputips = list(df_input['ip'])
    except:
        inputips = []
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    allips = list(df_pwd['ip'])
    indicators = []
    for i in range(len(allips)):
        if allips[i] in inputips:
            indicators.append(1)
        else:
            indicators.append(0)
    return render_template('sumtoolboxterminal.html',data = zip(allips, indicators),rackname=rackname,rackobserverurl = rackobserverurl,frontend_urls = get_frontend_urls(), session_auth = sum_session_info['guid'])

@app.route('/sumtoolboxredfish',methods=["GET"])
def sumtoolboxredfish(): ### Take a command for processing and distribution to servers
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    if request.method == "GET":
        if fileEmpty(savepath+"suminput.txt"):
            response = {"ERROR": "No input IP found!"}
    api_url = request.args.get('command')
    makeSumExcutable()
    return sumRedfishAPI(savepath+"suminput.txt", api_url)        

@app.route('/sumbioscompoutput',methods=['GET', 'POST'])
def sumbioscompoutput():
    if fileEmpty(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt"):
        return render_template('error.html',error="No input IP found!")
    makeSumExcutable()
    sumGetBiosSettings(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt")
    sum_bioscomp = sumCompBiosSettings()['compResult']
    #sumRemoveFiles('htmlBios')
    return render_template('sumbioscompoutput.html', sum_bioscomp = sum_bioscomp,rackname=rackname,rackobserverurl = rackobserverurl)

@app.route('/sumbootorderdownload',methods=['GET', 'POST'])
def sumbootorderdownload():
    if fileEmpty(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt"):
        return render_template('error.html',error="No input IP found!")
    makeSumExcutable()
    sumGetBiosSettings(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt")
    jsonlist = sumCompBiosSettings()['allsettings']
    iplist = sumCompBiosSettings()['iplist']
    df_bootorder = sumBootOrder(jsonlist,iplist)
    df_bootorder.to_excel(os.environ['BOOTORDERPATH'],index=None)
    while not os.path.isfile(os.environ['BOOTORDERPATH']):
        time.sleep(1)
    #sumRemoveFiles('htmlBios')
    return send_file(os.environ['BOOTORDERPATH'], as_attachment=False, cache_timeout=0)

@app.route('/sumdownloadbiossettings',methods=['GET', 'POST'])
def sumdownloadbiossettings():
    if fileEmpty(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt"):
        return render_template('error.html',error="No input IP found!",rackname=rackname,rackobserverurl = rackobserverurl)
    makeSumExcutable()
    inputpath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt"
    outputdir = os.environ['UPLOADPATH'] + 'BiosSettings_' + os.environ['RACKNAME']
    if not os.path.exists(outputdir):
        os.makedirs(outputdir)
    sumRunCustomProcess('./sum -l ' + inputpath + ' -c GetCurrentBiosCfg --file ' + outputdir + '/html --overwrite')
    tarpath = os.environ['UPLOADPATH'] + 'BiosSettings_' + os.environ['RACKNAME'] + '.tar.gz'
    '''
    if os.path.isfile(tarpath):# maybe not useful at all
        os.remove(tarpath)
    '''
    make_tarfile(tarpath, outputdir)    
    while not os.path.isfile(tarpath):
        time.sleep(1)
    return send_file(tarpath, as_attachment=False, cache_timeout=0)

@app.route('/sumdownloaddmi',methods=['GET', 'POST'])
def sumdownloaddmi():
    if fileEmpty(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt"):
        return render_template('error.html',error="No input IP found!",rackname=rackname,rackobserverurl = rackobserverurl)
    makeSumExcutable()
    inputpath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt"
    outputdir = os.environ['UPLOADPATH'] + 'DMI_' + os.environ['RACKNAME']
    if not os.path.exists(outputdir):
        os.makedirs(outputdir)
    sumRunCustomProcess('./sum -l ' + inputpath + ' -c GetDmiInfo --file ' + outputdir + '/txt --overwrite')
    tarpath = os.environ['UPLOADPATH'] + 'DMI_' + os.environ['RACKNAME'] + '.tar.gz'
    '''
    if os.path.isfile(tarpath):# maybe not useful at all
        os.remove(tarpath)
    '''
    make_tarfile(tarpath, outputdir)    
    while not os.path.isfile(tarpath):
        time.sleep(1)
    return send_file(tarpath, as_attachment=False, cache_timeout=0)

@app.route('/sumbiosimageupload',methods=['GET', 'POST'])
def sumbiosimageupload():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    data = {"response":"N/A"}
    if request.method == "POST":
        if request.files:
            sumbiosfile = request.files["biosimage"]
            if sumbiosfile.filename == "":
                printf("Input file must have a filename")
                data["response"] = "Error: Input file must have a filename."
                return json.dumps(data)
            sumbiosfile.save(savepath + "bios.222")
            data["response"] = "Info: BIOS image has been uploaded."
            return json.dumps(data)
    return json.dumps(data)

@app.route('/sumbiosupdateoutput',methods=['GET', 'POST'])
def sumbiosupdateoutput():
    if fileEmpty(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt"):
        return render_template('error.html',error="No input IP found!",rackname=rackname,rackobserverurl = rackobserverurl)
    makeSumExcutable()
    inputpath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt"
    filepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "bios.222"
    sumBiosUpdate(inputpath,filepath) # should not use --reboot option
    iplist = list(pd.read_csv(inputpath,sep=' ',names=['ip','user','pwd'])['ip'])
    pwdlist = list(pd.read_csv(inputpath,sep=' ',names=['ip','user','pwd'])['pwd'])
    for ip, pwd in zip(iplist,pwdlist):
        IPMI = "https://" + ip
        auth = ("ADMIN",pwd)
        systemRebootTesting(IPMI,auth,"GracefulRestart")
    messages = ["SUM finished BIOS update for following nodes:"]
    messages = messages + iplist
    messages.append("System reboot has been performed.")
    return render_template('simpleresult.html', messages = messages,rackname=rackname,rackobserverurl = rackobserverurl)

@app.route('/sumbmcimageupload',methods=['GET', 'POST'])
def sumbmcimageupload():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    data = {"response":"N/A"}
    if request.method == "POST":
        if request.files:
            sumbmcfile = request.files["bmcimage"]
            if sumbmcfile.filename == "":
                printf("Input file must have a filename")
                data["response"] = "Error: Input file must have a filename."
                return json.dumps(data)
            sumbmcfile.save(savepath + "bmc.bin")
            data["response"] = "Info: BMC image has been uploaded."
            return json.dumps(data)
    return json.dumps(data) 

@app.route('/sumbmcupdateoutput',methods=['GET', 'POST'])
def sumbmcupdateoutput():
    if fileEmpty(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt"):
        return render_template('error.html',error="No input IP found!")
    makeSumExcutable()
    inputpath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt"
    filepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "bmc.bin"
    sumBMCUpdate(inputpath,filepath) # should not use --reboot option
    iplist = list(pd.read_csv(inputpath,sep=' ',names=['ip','user','pwd'])['ip'])
    pwdlist = list(pd.read_csv(inputpath,sep=' ',names=['ip','user','pwd'])['pwd'])
    messages = ["SUM finished BMC update for following nodes:"]
    messages = messages + iplist
    messages.append("Redfish will be reset automatically.")
    return render_template('simpleresult.html', messages = messages,rackname=rackname,rackobserverurl = rackobserverurl)

@app.route('/sumbiossettingsupload',methods=['GET', 'POST'])
def sumbiossettingsupload():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    data = {"response":"N/A"}
    if request.method == "POST":
        if request.files:
            biossettingsfile = request.files["biossettings"]
            if biossettingsfile.filename == "":
                printf("Input file must have a filename")
                data['response'] = "Error: Input file must have a filename."
                return json.dumps(data)
            biossettingsfile.save(savepath + "biossettings.html")
            data["response"] = "Info: BIOS settings file has been uploaded."
            return json.dumps(data)
    return json.dumps(data)

@app.route('/sumbiossettingschangeoutput',methods=['GET', 'POST'])
def sumbiossettingschangeoutput():
    if fileEmpty(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt"):
        return render_template('error.html',error="No input IP found!",rackname=rackname,rackobserverurl = rackobserverurl)
    makeSumExcutable()
    inputpath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt"
    filepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "biossettings.html"
    sumChangeBiosSettings(inputpath,filepath) # should not use --reboot option
    iplist = list(pd.read_csv(inputpath,sep=' ',names=['ip','user','pwd'])['ip'])
    pwdlist = list(pd.read_csv(inputpath,sep=' ',names=['ip','user','pwd'])['pwd'])
    for ip, pwd in zip(iplist,pwdlist):
        IPMI = "https://" + ip
        auth = ("ADMIN",pwd)
        systemRebootTesting(IPMI,auth,"GracefulRestart")
    messages = ["SUM finished BIOS settings change for following nodes:"]
    messages = messages + iplist
    messages.append("Redfish will be reset automatically.")
    messages.append("After reboot it could take 5 to 10 mins for the BIOS modification take effects.")
    return render_template('simpleresult.html', messages = messages,rackname=rackname,rackobserverurl = rackobserverurl)
     
@app.route('/bioscomparisonoutput')
def bioscomparisonoutput():
    if not redfish_session_creator(): #### Check if a session is active...
        error = ["ERROR: An instance of the RedFish API server controller have been detected.", "Someone might be using this feature.", "Since, this page can create some conflict with multiple users, please only have one instance open."]
        return render_template('simpleresult.html',messages = error)
    df_path = os.environ['OUTPUTPATH']
    while not os.path.exists(df_path):
        time.sleep(1)
    df_auth = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    data_bioscomp = compareBiosSettings(df_auth)['compResult']
    return render_template('bioscomparisonoutput.html', data_bioscomp = data_bioscomp,rackname=rackname,rackobserverurl = rackobserverurl, session_auth = redfish_session_info['guid'])

@app.route('/bootorderoutput')
def bootorderoutput():
    if not redfish_session_creator(): #### Check if a session is active...
        error = ["ERROR: An instance of the RedFish API server controller have been detected.", "Someone might be using this feature.", "Since, this page can create some conflict with multiple users, please only have one instance open."]
        return render_template('simpleresult.html',messages = error)
    df_path = os.environ['OUTPUTPATH']
    while not os.path.exists(df_path):
        time.sleep(1)
    df_auth = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    df_bootorder = bootOrderOutput(df_auth)
    df_bootorder.to_excel(os.environ['BOOTORDERPATH'],index=None)
    while not os.path.isfile(os.environ['BOOTORDERPATH']):
        time.sleep(1)
    redfish_session_info['state'] = 'inactive'
    return send_file(os.environ['BOOTORDERPATH'], as_attachment=False, cache_timeout=0)

@app.route('/pwdoutput')
def pwdoutput():
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    df_pwd['user'] = ['ADMIN'] * len(df_pwd)
    new_path = os.environ['OUTPUTPATH'].replace(".txt","auth.txt")
    df_pwd[['ip','user','pwd']].to_csv(new_path,header=None,index=None,sep=' ')
    return send_file(new_path, as_attachment=True, cache_timeout=0)

def list_helper(input_list,list_index):
    if list_index < len(input_list):
        return(input_list[list_index])
    else:
        return("N/A")

@app.route('/event')
def event():
    ip = request.args.get('var')
    event_url = "http://" + get_ip() + ":" + str(frontport) + '/event?var=' + str(ip) 
    try:
        e_id = int(request.args.get('id'))
    except:
        e_id = 1
        printf("Info: using latest event")
    show_names = 'true' # Default value to pass to html to enable a list of nodenames
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        show_names = 'false'
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    pwd = df_pwd.loc[df_pwd['ip'] == ip,'pwd'].iloc[0]
    date_time = get_data.get_time(ip,pwd)
    if 'no_time' not in date_time:
        ntp_server = get_data.get_ntp_server(ip,pwd)
        ntp_status = get_data.get_ntp_status(ip,pwd)
    else:
        ntp_server = 'n/a'
        ntp_status = ['n/a'] * 3  
    total_counts = monitor_collection.find({"BMC_IP": ip}, {"_id":0, "Event":1}).count()
    if e_id > total_counts:
        e_id = total_counts  # can not exceed the length
    elif e_id < 1:
        e_id = 1
    selected_one = e_id     
    for i in monitor_collection.find({"BMC_IP": ip}, {"_id":0, "Event":1, "Datetime":1}).sort("_id",-1):
        if e_id <= 1:
            events = i['Event']
            events_date = i['Datetime']
            break
        e_id -= 1
    for i in range(len(events)):
        for key in IPMIdict.keys():
            if key in events[i]:
                events[i] = events[i].replace(key,IPMIdict[key]) + " | Note the error number '" + key + "' has been replaced by '" + IPMIdict[key] + "'!"
    sel_id = []
    dates = []
    severity = []
    action = []
    sensor = []
    redfish_msg = []
    ipmitool_msg = []

    if  events[0] != "Error: the number of events are not the same between Redfish and IPMITOOL." :
        if "|||" in events[0]:
            for event_index, i in enumerate(events):
                temp_event = i.split("|")
                sel_id.append(str(event_index+1))
                dates.append(list_helper(temp_event,1))
                severity.append(list_helper(temp_event,2))
                action.append(list_helper(temp_event,3))
                sensor.append(list_helper(temp_event,4))
                redfish_msg.append(list_helper(temp_event,5))
                ipmitool_msg.append(list_helper(temp_event,11) + " | " + list_helper(temp_event,12))
        elif "|||" not in events[0] and "only redfish sel log" in events[0]:
            events.remove("only redfish sel log")
            for event_index, i in enumerate(events):
                temp_event = i.split("|")
                sel_id.append(str(event_index+1))
                dates.append(list_helper(temp_event,1))
                severity.append(list_helper(temp_event,2))
                action.append(list_helper(temp_event,3))
                sensor.append(list_helper(temp_event,4))
                redfish_msg.append(list_helper(temp_event,5))
                ipmitool_msg.append("N/A")
        else:
            if "only ipmitool sel log" in events:
                events.remove("only ipmitool sel log")
            for event_index, i in enumerate(events):
                temp_event = i.split("|")
                sel_id.append(str(event_index+1))
                dates.append(list_helper(temp_event,1) + " : " + list_helper(temp_event,2))
                severity.append("N/A")
                action.append(list_helper(temp_event,5))
                sensor.append("N/A")
                redfish_msg.append("N/A")
                ipmitool_msg.append(list_helper(temp_event,3) + " | " + list_helper(temp_event,4))
    else:
        sel_id.append("N/A")
        dates.append("N/A")
        severity.append("N/A")
        action.append("N/A")
        sensor.append("N/A")
        redfish_msg.append("N/A")
        ipmitool_msg.append("N/A")
    sel_id.reverse()
    dates.reverse()
    severity.reverse()
    action.reverse()
    sensor.reverse()
    redfish_msg.reverse()
    ipmitool_msg.reverse()
    data = zip(sel_id,dates,severity,action,sensor,redfish_msg,ipmitool_msg)
    if show_names == "true":
        return render_template('event.html',event_url = event_url, total_counts = total_counts, selected_one = selected_one, events_date = events_date, \
        show_names = show_names, date_time=date_time, ntp_server=ntp_server, data=data, ntp_on_off = ntp_status[0], daylight = ntp_status[1], \
        modulation = ntp_status[2],bmc_ip=ip,ip_list = ips_names,rackname=rackname,rackobserverurl = rackobserverurl)
    else:
        return render_template('event.html',event_url = event_url, total_counts= total_counts, selected_one = selected_one, events_date = events_date, \
        show_names = show_names, date_time=date_time, ntp_server=ntp_server, data=data, ntp_on_off = ntp_status[0], daylight = ntp_status[1], \
        modulation = ntp_status[2],bmc_ip=ip,ip_list = getIPlist(),rackname=rackname,rackobserverurl = rackobserverurl)

@app.route('/udp_command_testor')
def udp_command_testor():
    command = request.args.get('command')
    timeout = int(request.args.get('timeout'))
    command_uid = generateCommandInput(command,timeout) # uid is used for the file name and search from database
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    df_input_os = pd.read_csv(savepath+"udpserveruploadip.txt",names=['ip']) # used to measure the length of output
    insertUdpevent('f',savepath+"udpinput.json",savepath+"udpserveruploadip.txt")
    response_counter = 0
    messages = [] # messages are the final outputs, contain a list with response from every selected node
    while response_counter < len(df_input_os): # looking for uid in the collection
        response = [] # response contains the output message but need to be sort before using
        response_counter = 0
        cur = cmd_collection.find({"file_name" : {'$regex' : command_uid}},{'os_ip','file_name','mac','start_date','content'})
        for i in cur:
            response.append({i['os_ip']: i['content'],'MAC':i['mac']})
            response_counter += 1
        printf('Response not ready yet, wait 1 sec ...')
        if timeout <= -5: # given database 5 more seconds to response. 
            response = []
            messages.append('Error: command "' + command + '" failed with timeout')
            break
        time.sleep(1)
        timeout -= 1        
    # sort the response
    for cur_ip in df_input_os['ip']:
        for cur_msg in response:
            if cur_ip in cur_msg.keys():
                messages.append('======================' + cur_ip + '-' + cur_msg['MAC'] + '======================')
                messages  += cur_msg[cur_ip].split('\n')
    return render_template('simpleresult.html', messages = messages, rackname=rackname,rackobserverurl = rackobserverurl)

@app.route('/UDP_commandline')
def UDP_commandline():
    if not udp_session_creator(): #### Check if a session is active...
        error = ["ERROR: An instance of the UDP server controller have been detected", "Someone might be using this feature.", "Since, this page can create some conflict with multiple users, please only have one instance open"]
        return render_template('simpleresult.html',messages = error)
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    try:
        df_input = pd.read_csv(savepath+"udpserveruploadip.txt",header=None,names=['ip'])
        inputips = list(df_input['ip'])
    except:
        inputips = []
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    allips = list(df_pwd['os_ip'])
    indicators = []
    for i in range(len(allips)):
        if allips[i] in inputips:
            indicators.append(1)
        else:
            indicators.append(0)
    return render_template('UDP_commandline.html',data=zip(allips,indicators),rackname=rackname,rackobserverurl = rackobserverurl,frontend_urls = get_frontend_urls(), session_auth = udp_session_info['guid'])

@app.route('/udp_command_start')
def udp_command_start():
    command = request.args.get('command')
    timeout = int(10)
    command_uid = generateCommandInput(command,timeout) # uid is used for the file name and search from database
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    df_input_os = pd.read_csv(savepath+"udpserveruploadip.txt",names=['ip']) # used to measure the length of output
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    remain_ips = list(df_input_os['ip']) # used for remove value 
    insertUdpevent('f',savepath+"udpinput.json",savepath+"udpserveruploadip.txt")
    messages = [] # messages are the final outputs, contain a list with response from every selected node
    while len(remain_ips) != 0: # looking for uid in the collection
        response = [] # response contains the output message but need to be sort before using
        cur = cmd_collection.find({"file_name" : {'$regex' : command_uid}},{'os_ip','file_name','mac','start_date','content'})
        for i in cur:
            response.append({i['os_ip']: i['content'],'MAC':i['mac']})
            if i['os_ip'] in remain_ips:
                printf('Found ' + i['os_ip'] + ' in database!')
                remain_ips.remove(i['os_ip'])
        printf('Response not ready yet, wait 1 sec ...')
        if timeout <= -5: # given database 5 more seconds to response. 
            for cur_ip in remain_ips:
                cur_mac = clean_mac(df_pwd[df_pwd['os_ip'] == cur_ip]['mac'].values[0])
                # insert ':' into the mac
                cur_mac_column = mac_with_seperator(cur_mac,':')             
                response.append({cur_ip: 'Error: No connection between UDP server and Client for this node!','MAC':cur_mac_column})   
                printf('Error: ' + cur_ip + ' can not get response, please check udp_client, connection and OS IP!')
            break
        time.sleep(1)
        timeout -= 1        
    output = {}
    for cur_ip in df_input_os['ip']:
        for cur_msg in response:
            if cur_ip in cur_msg.keys():
                output[cur_ip + " - " + cur_msg['MAC']] = {"output":{}}
                temp_msg_array = cur_msg[cur_ip].split('\n')
                temp_msg_array = list(filter(None, temp_msg_array)) # filter out the empty item in the list
                if len(temp_msg_array) == 0:
                    temp_msg_array = ['Warning: Command has been excuted successfully, but there is no output!']
                for i,msg in enumerate(temp_msg_array):
                    output[cur_ip + " - " + cur_msg['MAC']]['output'][i] = msg
    return json.dumps(output)

def udp_session_creator():
    time.sleep(0.100) ##### Fixes timing issue between page close and page reload
    if udp_session_info['state'] == 'active':
        printf("Failed to create new udp_server session")
        printf("Current UDP Session info is:")
        printf("state: " + udp_session_info['state'])
        printf("guid: " + udp_session_info['guid'])
        return False
    else:
        url_saf = secrets.token_urlsafe(8)
        udp_session_info['state'] = 'active'
        udp_session_info['guid'] = url_saf
        printf("Creating new udp_server session")
        printf("state: " + udp_session_info['state'])
        printf("guid: " + udp_session_info['guid'])
        return True

@app.route('/udpserverupload')
def udpserverupload():
    if not udp_session_creator(): #### Check if a session is active...
        error = ["ERROR: An instance of the UDP server controller have been detected", "Someone might be using this feature.", "Since, this page can create some conflict with multiple users, please only have one instance open"]
        return render_template('simpleresult.html',messages = error)
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    try:
        df_input = pd.read_csv(savepath+"udpserveruploadip.txt",header=None,names=['ip'])
        inputips = list(df_input['ip'])
    except:
        inputips = []
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    allips = list(df_pwd['os_ip'])
    indicators = []
    for i in range(len(allips)):
        if allips[i] in inputips:
            indicators.append(1)
        else:
            indicators.append(0)
    return render_template('udpserverupload.html',data=zip(allips,indicators),rackname=rackname,rackobserverurl = rackobserverurl,frontend_urls = get_frontend_urls(),session_auth = udp_session_info['guid'])

@app.route('/runBenchmark')
def runBenchmark():
    filetype = request.args.get('filetype')
    benchmark_file = request.args.get('benchmark')
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    cleanIP(savepath + "udpserveruploadip.txt")
    printf("INPUTFILE EMPTY: " + str(fileEmpty(savepath + "udpserveruploadip.txt")))
    if fileEmpty(savepath + "udpserveruploadip.txt") or fileEmpty(savepath + "-host.json"):
        response = {"ERROR":"No input IP found! or No host output file found... Please initiate server first or restart the UDP container"}
        return json.dumps(response)
    if filetype == "BenchamarkInput":
        udpinputfile = benchmark_file
        if udpinputfile == "":
            response = {"ERROR":"Input file must have a filename"}
            return json.dumps(response)
        # insert flag to run benchmark       
        insertUdpevent('f',os.environ['UPLOADPATH'] + udpinputfile.filename,savepath+"udpserveruploadip.txt")
        response = {}
        response["SUCCESS0"] = "info: Benchmark input files have been uploaded."
        response["SUCCESS1"] = "info: Run the benchmark when ready."
        return json.dumps(response)
    elif filetype == "Benchmark":
        # insert flag to run benchmark       
        insertUdpevent('f',savepath+"udpinput.json",savepath+"udpserveruploadip.txt")
        response = {}
        response["SUCCESS0"] = "info: Benchmark will be started in a few secs."
        response["SUCCESS1"] = "warning: Please do not submit any benchmarks while it's running."
        return json.dumps(response)

@app.route('/check_UDP_clientState')
def check_UDP_clientState():
    client_state = request.args.get('state')
    response = {}
    mac_os = []
    mac_os_all = []
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    df_input = pd.read_csv(savepath+"_udpserveruploadip_all.txt",header=None,names=['ip'])
    inputips = list(df_input['ip'])
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    cur = collection.find({},{"BMC_IP":1,"_id":0})
    for i in cur:
        temp_array = []
        temp_array.append(df_pwd[df_pwd['ip'] == i['BMC_IP']]['mac'].values[0])
        temp_array.append(df_pwd[df_pwd['ip'] == i['BMC_IP']]['os_ip'].values[0])
        mac_os_all.append(temp_array)
        for sel_ip in inputips: ####If OS ip is in the selected os_list, append to mac_os (os_list is the input ip list 'RACKNAME'udpserveruploadip.txt)
            if temp_array[1] == sel_ip:
                mac_os.append(temp_array)
    udp_json = savepath+"-host.json"
    if client_state == "ONLINE":
        if os.path.exists(udp_json):
            insertUdpevent('m',"request_h",savepath + '_udpserveruploadip_all.txt') # request_h means requst client to send h back to initilize the json file
            time.sleep(1)
            printf("Performing UDP Client/server handshake...")
            response = getMessage_dictResponse(udp_json,mac_os_all,client_state)
        else:
            response = {"ERROR":"info: No UDP json file found"}
            printf("ERROR cannot find file: " + udp_json)
    elif client_state != "latest":
        if os.path.exists(udp_json):
            printf("Getting latest client state: " + client_state)
            response = getMessage_dictResponse(udp_json,mac_os,client_state)
        else:
            response = {"ERROR":"info: No UDP json file found"}
            printf("ERROR cannot find file: " + udp_json)
    else:
        if os.path.exists(udp_json):       
            printf("Getting latest client state")
            response = getMessage_dictResponse(udp_json,mac_os,client_state)
        else:
            response = {"ERROR":"info: No UDP json file found"}
            printf("ERROR cannot find file: " + udp_json)
    return response

@app.route('/udpserverinitialize')
def udpserverinitialize():
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])       
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + '_udpserveruploadip_all.txt'
    with open(savepath,'w') as all_ip_file:
        for ip in df_pwd['os_ip']:
            all_ip_file.write("%s\n" % ip)    
    if request.method == "GET":
        insertUdpevent('m',"request_h",savepath) # request_h means requst client to send h back to initilize the json file
        time.sleep(5)
        response = {}
        response['msg0'] = "Success! Initilize message has been sent to clients."
        response['msg1'] = "info: You can also check the status on index page."
        response['msg2'] = "info: If the system still has not been initialized, please make sure:"
        response['msg3'] = "info: 1. Connections bettween server and clients."
        response['msg4'] = "info: 2. MACNAME in env file is correct."
        response['msg5'] = "info: 3. UDP Clients are running."
        response['msg6'] = "info: 4. System firewall has been disabled and stopped."
        return json.dumps(response)

@app.route('/udpoutput')
def udpoutput():
    star,mac,ipmi,os_ip,start_date,done_date,cmd,content,content_size,benchmark,config,result,id,file_name,conclusion= [],[],[],[],[],[],[],[],[],[],[],[],[],[],[]
    benchmark_data = list(udp_collection.find({}))
    for i in benchmark_data:
        cur_mac_clean = clean_mac(i['mac'])
        df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
        star.append(i['star'])
        mac.append(i['mac'])
        try: 
            cur_os_ip = df_pwd[df_pwd['mac'].isin([cur_mac_clean.upper(),cur_mac_clean.lower()])]['os_ip'].values[0]
            os_ip.append(cur_os_ip)
            ipmi.append(df_pwd[df_pwd['mac'].isin([cur_mac_clean.upper(),cur_mac_clean.lower()])]['ip'].values[0])
            if cur_os_ip != i['os_ip']:
                printf('Found OS IP changed: [Benchmark OS IP] ' + i['os_ip']  + ' ====> [Current OS IP] ' +  cur_os_ip)
        except Exception as e:
            printf(e)
            printf('Wanrning: can not find matching mac address. Below is the pwd dataframe')
            printf(df_pwd)
            printf('mac address from benchmark data is: ' + cur_mac_clean)
            os_ip.append('N/A')
            ipmi.append('N/A')
        start_date.append(i['start_date'])
        done_date.append(i['done_date'])
        cmd.append(i['cmd'])
        content.append(i['content'])
        content_size.append(getsizeof(i['content']))
        benchmark.append(i['benchmark'])
        result.append(i['result'])
        id.append(str(i['_id']))
        file_name.append(i['file_name'])
        conclusion.append(i['conclusion'])
    return render_template('udpoutput.html',rackname=rackname,\
    data=zip(star, mac, ipmi, os_ip, start_date, done_date, cmd, benchmark, content_size, result, id, file_name,conclusion),ids = id,rackobserverurl = rackobserverurl)

@app.route('/udpsendlogfile')
def udpsendlogfile():
    data = request.args.get('var')
    cur_result = list(udp_collection.find({'_id':ObjectId(data)},{'file_name':1,'content':1}))[0]
    try:
        content = cur_result['content']
        file_path = cur_result['file_name']
    except Exception as e:
        return render_template('error.html',error=e)
    with open(file_path, 'w') as output:
        output.write(content)
    return send_file(file_path,as_attachment=True,cache_timeout=0)

@app.route('/udpdeleteobject')
def udpdeleteobject():
    data = request.args.get('var')
    deleted_data = {'Status': 'success','ID': 'del_' + data}
    try:
        backup = list(udp_collection.find({'_id':ObjectId(data)}))[0]
        # unstar the obj before move to the dustbin
        backup['star'] = -1
        udp_deleted_collection.insert(backup)
        udp_collection.find_one_and_delete({'_id':ObjectId(data)},{})
    except Exception as e:
        deleted_data = {'Status': 'failed'}
        printf(e)
    return json.dumps(deleted_data)

@app.route('/udpdeleteallobject')
def udpdeleteallobject():
    deleted_data = {'Status': 'success'}
    try:
        for i in udp_collection.find({}):
            backup = list(udp_collection.find({'_id':i['_id']}))[0]
            backup['star'] = -1
            udp_deleted_collection.insert(backup)
            udp_collection.find_one_and_delete({'_id':i['_id']},{})
            deleted_data[str(i['_id'])] = str(i['file_name'])
    except Exception as e:
        deleted_data = {'Status': 'failed'}
        deleted_data = {'Error Message': str(e)}
        printf(e)
    data = json.dumps(deleted_data)
    return data

@app.route('/udpstarobject')
def udpstarobject():
    data = request.args.get('id')
    result = {}
    try:        
        set_value = list(udp_collection.find({'_id':ObjectId(data)}))[0]['star'] * -1 # change the star to unstar or change the unstar to star
        os_ip = list(udp_collection.find({'_id':ObjectId(data)}))[0]['os_ip']
        benchmark = list(udp_collection.find({'_id':ObjectId(data)}))[0]['benchmark']
        # each os_ip and benchmark should only has one stared!
        if set_value == 1:
            for cur_obj in list(udp_collection.find({'os_ip':os_ip, 'benchmark':benchmark})):
                udp_collection.find_one_and_update({'_id':cur_obj['_id']},{'$set':{'star':-1}})
                result[str(cur_obj['_id'])] = -1
                printf('Unselect: ' + str(cur_obj['_id']))
        result[data] = set_value
        udp_collection.find_one_and_update({'_id':ObjectId(data)},{'$set':{'star':set_value}})       
    except Exception as e:
        printf('Error msg:' + str(e))
        result = {'value': 0}
    data = json.dumps(result)
    return data

@app.route('/udpunstarallobject')
def udpunstarallobject():
    try:
        for i in range(len(list(udp_collection.find({})))):
            udp_collection.find_one_and_update({'star':1},{'$set':{'star':-1}})      
        result = {'value':'success'}  
    except Exception as e:
        printf('Error msg:' + str(e))
        result = {'value':'failed'}
    data = json.dumps(result)
    return data

@app.route('/udpunstarfailedobject')
def udpunstarfailedobject():
    try:
        ids = []
        for i in range(len(list(udp_collection.find({})))):
            ids.append((udp_collection.find_one({'star':1,'conclusion':'FAILED'},{'_id':1})))
            udp_collection.find_one_and_update({'star':1,'conclusion':'FAILED'},{'$set':{'star':-1}})
        objects = {}
        for index, i in enumerate(ids):
            try:
                objects[str(index)] = str(i.get('_id'))
            except:
                printf("item is Nonetype") # i could be None
        objects = json.dumps(objects)
    except Exception as e:
        printf('Error msg:' + str(e))
        objects = json.dumps({'0':'FAILED'})
    return objects

@app.route('/udpunautostar')
def udpautostar():
    try:
        ids = []
        # unstar all
        for i in range(len(list(udp_collection.find({})))):
            udp_collection.find_one_and_update({'star':1},{'$set':{'star':-1}})
        # find best results, non-float/non-int results will be treat as one
        obj_autostar = {} 
        # obj_autostar = { bm_name_1: {os_ip_1: [resultMul, result_id], os_ip_2: [resultMul, result_id]} \
        #                  bm_name_2: {os_ip_1: [resultMul, result_id], os_ip_2: [resultMul, result_id]} \
        #                }
        for oneResult in list(udp_collection.find({})):
            if oneResult['benchmark'] in obj_autostar.keys():
                resultMul = 1
                for num in oneResult['raw_result']:
                    if type(num) == float or type(num) == int:
                        resultMul *= num
                if oneResult['os_ip'] not in obj_autostar[oneResult['benchmark']].keys():
                     obj_autostar[oneResult['benchmark']][oneResult['os_ip']] = [resultMul,oneResult['_id']]
                for ip in obj_autostar[oneResult['benchmark']].keys():
                    if ip == oneResult['os_ip'] and obj_autostar[oneResult['benchmark']][ip][0] < resultMul:
                        obj_autostar[oneResult['benchmark']][ip] = [resultMul,oneResult['_id']]
            elif oneResult['benchmark'] not in obj_autostar.keys():
                resultMul = 1
                for num in oneResult['raw_result']:
                    if type(num) == float or type(num) == int:
                        resultMul *= num
                obj_autostar[oneResult['benchmark']] = {oneResult['os_ip']:[resultMul,oneResult['_id']]}
        # select best non-numerical results:
        # obj_autostar = { bm_name_1: {os_ip_1: ['PASS', result_id], os_ip_2: ['PASS', result_id]} \
        #                  bm_name_2: {os_ip_1: ['FAILED', result_id], os_ip_2: ['PASS', result_id]} \
        #                }
        # PASS reuslt has higher priority than failed ones.        
        for oneResult in list(udp_collection.find({})):
            if oneResult['benchmark'] in obj_autostar.keys():
                if oneResult['os_ip'] not in obj_autostar[oneResult['benchmark']].keys():
                    obj_autostar[oneResult['benchmark']][oneResult['os_ip']] = [oneResult['conclusion'],oneResult['_id']]
                for ip in obj_autostar[oneResult['benchmark']].keys():
                    if ip == oneResult['os_ip'] and obj_autostar[oneResult['benchmark']][ip][0] == 'FAILED' and oneResult['conclusion'] == 'PASS':
                        obj_autostar[oneResult['benchmark']][ip] = [oneResult['conclusion'],oneResult['_id']]
            elif oneResult['benchmark'] not in obj_autostar.keys():
                obj_autostar[oneResult['benchmark']] = {oneResult['os_ip']:[oneResult['conclusion'],oneResult['_id']]}
        
        # star the latest results
        for bm in obj_autostar.keys():
            for ip in obj_autostar[bm].keys():
                ids.append(str(obj_autostar[bm][ip][1]))
                udp_collection.find_one_and_update({'_id':obj_autostar[bm][ip][1]},{'$set':{'star':1}})      
        temp_dict = {}
        for index, i in enumerate(ids):
            temp_dict[str(index)] = i
        data = json.dumps(temp_dict)
    except Exception as e:
        printf('Error msg:' + str(e))
        data = {'value':'failed'}
        data = json.dumps(data)
    return data

def fileEmpty(filepath):
    if not os.path.isfile(filepath):
        return True
    elif os.stat(filepath).st_size == 0:
        return True
    return False

def getIPlist():
    ip_list = []
    curIP = collection.find({},{"BMC_IP":1}).limit(100)
    for i in curIP:
        ip_list.append(i['BMC_IP'])
    return(ip_list)

def make_tarfile(output_filename, source_dir):
    with tarfile.open(output_filename, "w:gz") as tar:
        tar.add(source_dir, arcname=os.path.basename(source_dir))

@app.route('/min_max_temperatures/<bmc_ip>')
def min_max_temperatures(bmc_ip):
    messages, max_vals, min_vals, max_dates, min_dates, sensorNames, avg_vals, count_vals, elapsed_hour, good_count, zero_count, last_date = get_data.find_min_max(bmc_ip,"Temperatures", "ReadingCelsius", 9999)
    return render_template('simpleresult.html',messages=messages,rackname=rackname,rackobserverurl = rackobserverurl)

@app.route('/min_max_temperatures_chart/<bmc_ip>')
def min_max_temperatures_chart(bmc_ip):
    messages, max_vals, min_vals, max_dates, min_dates, sensorNames, avg_vals, count_vals, elapsed_hour, good_count, zero_count, last_date = get_data.find_min_max(bmc_ip,"Temperatures", "ReadingCelsius", 9999)
    messages.insert(0,'Numerical Results: (Units: Celsius)')
    chart_headers = ['Rack Name: ' + rackname, 'BMC IP: ' + bmc_ip,  'Elapsed Time: ' + elapsed_hour + ' hours', 'Last Timestamp: ' + last_date, 'Value Counts: ' + str(count_vals), 'Extreme Sensor Readings: (Light Blue: Min, Green: Max)']
    df_max = pd.DataFrame({"Temperature (Celsius)":max_vals, "Sensor names": sensorNames})
    df_min = pd.DataFrame({"Temperature (Celsius)":min_vals, "Sensor names": sensorNames})
    sns.set_theme(style="whitegrid")
    fig, ax =plt.subplots(1,1,figsize=(10,len(df_max)/4+1))
    custom_palette = ["green"]
    sns_plot = sns.barplot(y="Sensor names", x="Temperature (Celsius)", palette = custom_palette,data=df_max, ax=ax)
    ax.set_xticks(range(0,int(max(max_vals))+1,10))
    ax.xaxis.label.set_color('black')
    ax.yaxis.label.set_color('black')
    ax.tick_params(labelcolor='black')
    ax2 = ax.twinx()
    custom_palette2 = ["white"]
    sns.barplot(y="Sensor names", x="Temperature (Celsius)", palette = custom_palette2,alpha=0.9,data=df_min,ax=ax2)
    ax2.set_yticklabels([])
    ax2.set_yticks([])
    ax2.set_ylabel('')
    for p in ax.patches:
        _x = p.get_x() + p.get_width() + 0.3
        _y = p.get_y() + p.get_height()
        value = int(p.get_width())
        ax.text(_x, _y, value, horizontalalignment='left', verticalalignment='bottom')   
    plt.tight_layout()
    imagepath = "min_max_temperatures_" + datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S") + ".png"
    fig.savefig("/app/static/images/" + imagepath)
    imageheight = (len(df_min)/4+1)*1500/10
    while not os.path.isfile("/app/static/images/" + imagepath):
        time.sleep(1)
    show_names = 'true' # Default value to pass to html to enable a list of nodenames
    cpu_temps,vrm_temps,dimm_temps,sys_temps,sensor_fans,sensor_voltages,gpu_temps = get_sensor_names(bmc_ip)
    ips_names = get_node_names()
    plt.close()
    if isinstance(ips_names,bool) == True:
        show_names = 'false'   
    if show_names == 'true':
        return render_template('imageOutput.html',rackname=rackname,chart_headers = chart_headers, show_names = show_names,sensor_voltages = sensor_voltages,gpu_temps=gpu_temps,cpu_temps = cpu_temps, sys_temps=sys_temps, vrm_temps = vrm_temps, dimm_temps = dimm_temps, sensor_fans = sensor_fans, data = zip(sensorNames, min_vals,min_dates,max_vals,max_dates, avg_vals, good_count, zero_count), imagepath="../static/images/" + imagepath,imageheight=imageheight,bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "min_max_temperatures",rackobserverurl = rackobserverurl)
    else:
        return render_template('imageOutput.html',rackname=rackname,chart_headers = chart_headers, show_names = show_names,sensor_voltages = sensor_voltages,gpu_temps=gpu_temps,cpu_temps = cpu_temps, sys_temps=sys_temps, vrm_temps = vrm_temps, dimm_temps = dimm_temps, sensor_fans = sensor_fans, data = zip(sensorNames, min_vals,min_dates,max_vals,max_dates, avg_vals, good_count, zero_count), imagepath="../static/images/" + imagepath,imageheight=imageheight,bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "min_max_temperatures",rackobserverurl = rackobserverurl)

@app.route('/min_max_voltages/<bmc_ip>')
def min_max_voltages(bmc_ip):
    messages, max_vals, min_vals, max_dates, min_dates, sensorNames, avg_vals, count_vals, elapsed_hour, good_count, zero_count, last_date = get_data.find_min_max(bmc_ip,"Voltages", "ReadingVolts", 1000)
    return render_template('simpleresult.html',messages=messages,rackname=rackname,rackobserverurl = rackobserverurl)

@app.route('/min_max_voltages_chart/<bmc_ip>')
def min_max_voltages_chart(bmc_ip):
    messages, max_vals, min_vals, max_dates, min_dates, sensorNames, avg_vals, count_vals, elapsed_hour, good_count, zero_count, last_date = get_data.find_min_max(bmc_ip,"Voltages", "ReadingVolts", 1000)
    messages.insert(0,'Numerical Results: (Units: Voltages)')
    chart_headers = ['Rack Name: ' + rackname, 'BMC IP: ' + bmc_ip,  'Elapsed Time: ' + elapsed_hour + ' hours', 'Last Timestamp: ' + last_date, 'Value Counts: ' + str(count_vals), 'Extreme Sensor Readings: (Light Blue: Min, Green: Max)']
    df_max = pd.DataFrame({"Voltages (Volts)":max_vals, "Sensor names": sensorNames})
    df_min = pd.DataFrame({"Voltages (Volts)":min_vals, "Sensor names": sensorNames})
    sns.set_theme(style="whitegrid")
    fig, ax =plt.subplots(1,1,figsize=(10,len(df_max)/4+1))
    custom_palette = ["green"]
    sns_plot = sns.barplot(y="Sensor names", x="Voltages (Volts)", palette = custom_palette,data=df_max, ax=ax)
    ax.set_xticks(range(0,int(max(max_vals))+1,1))
    ax.xaxis.label.set_color('black')
    ax.yaxis.label.set_color('black')
    ax.tick_params(labelcolor='black')
    ax2 = ax.twinx()
    custom_palette2 = ["white"]
    sns.barplot(y="Sensor names", x="Voltages (Volts)", palette = custom_palette2,alpha=0.9,data=df_min,ax=ax2)
    ax2.set_yticklabels([])
    ax2.set_yticks([])
    ax2.set_ylabel('')
    for i, p in enumerate(ax.patches):
        _x = p.get_x() + p.get_width()
        _y = p.get_y() + p.get_height() - 0.2
        value = max_vals[i]
        ax.text(_x, _y, value, horizontalalignment='left', verticalalignment='bottom',size='xx-small')
    plt.tight_layout()
    imagepath = "min_max_voltages_" + datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S") + ".png"
    fig.savefig("/app/static/images/" + imagepath)
    imageheight = (len(df_min)/4+1)*1500/10
    while not os.path.isfile("/app/static/images/" + imagepath):
        time.sleep(1)    
    show_names = 'true' # Default value to pass to html to enable a list of nodenames
    cpu_temps,vrm_temps,dimm_temps,sys_temps,sensor_fans,sensor_voltages,gpu_temps = get_sensor_names(bmc_ip)
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        show_names = 'false'
    plt.close()
    if show_names == 'true':
        return render_template('imageOutput.html',rackname=rackname,chart_headers = chart_headers, show_names = show_names,sensor_voltages = sensor_voltages,gpu_temps=gpu_temps, cpu_temps = cpu_temps, sys_temps=sys_temps, vrm_temps = vrm_temps, dimm_temps = dimm_temps, sensor_fans = sensor_fans, data = zip(sensorNames, min_vals,min_dates,max_vals,max_dates, avg_vals, good_count, zero_count),imagepath="../static/images/" + imagepath,imageheight=imageheight,bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "min_max_voltages",rackobserverurl = rackobserverurl)    
    else:
        return render_template('imageOutput.html',rackname=rackname,chart_headers = chart_headers, show_names = show_names,sensor_voltages = sensor_voltages,gpu_temps=gpu_temps, cpu_temps = cpu_temps, sys_temps=sys_temps, vrm_temps = vrm_temps, dimm_temps = dimm_temps, sensor_fans = sensor_fans, data = zip(sensorNames, min_vals,min_dates,max_vals,max_dates, avg_vals, good_count, zero_count),imagepath="../static/images/" + imagepath,imageheight=imageheight,bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "min_max_voltages",rackobserverurl = rackobserverurl)

@app.route('/min_max_fans/<bmc_ip>')
def min_max_fans(bmc_ip):
    messages, max_vals, min_vals, max_dates, min_dates, sensorNames, avg_vals, count_vals, elapsed_hour, good_count, zero_count, last_date = get_data.find_min_max(bmc_ip,"Fans", "Reading", 999999)
    return render_template('simpleresult.html',rackname=rackname,messages=messages,rackobserverurl = rackobserverurl)

@app.route('/min_max_fans_chart/<bmc_ip>')
def min_max_fans_chart(bmc_ip):
    messages, max_vals, min_vals, max_dates, min_dates, sensorNames, avg_vals, count_vals, elapsed_hour, good_count, zero_count, last_date = get_data.find_min_max(bmc_ip,"Fans", "Reading", 999999)
    messages.insert(0,'Numerical Results: (Units: rd/min)')
    chart_headers = ['Rack Name: ' + rackname, 'BMC IP: ' + bmc_ip,  'Elapsed Time: ' + elapsed_hour + ' hours', 'Last Timestamp: ' + last_date, 'Value Counts: ' + str(count_vals), 'Extreme Sensor Readings: (Light Blue: Min, Green: Max)']
    df_max = pd.DataFrame({"Fan Speed(rd/min)":max_vals, "Sensor names": sensorNames})
    df_min = pd.DataFrame({"Fan Speed(rd/min)":min_vals, "Sensor names": sensorNames})
    sns.set_theme(style="whitegrid")
    fig, ax =plt.subplots(1,1,figsize=(10,len(df_max)/4+1))
    custom_palette = ["green"]
    sns_plot = sns.barplot(y="Sensor names", x="Fan Speed(rd/min)", palette = custom_palette,data=df_max, ax=ax)
    ranger = int(max(max_vals)/15000 + 0.5)*1000
    if ranger == 0:
        ranger = 1000
    ax.set_xticks(range(0,int(max(max_vals))+1,ranger))
    #ax.set_xticks(range(0,int(max(max_vals))+1,1000))
    ax.xaxis.label.set_color('black')
    ax.yaxis.label.set_color('black')
    ax.tick_params(labelcolor='black')
    ax2 = ax.twinx()
    custom_palette2 = ["white"]
    sns.barplot(y="Sensor names", x="Fan Speed(rd/min)", palette = custom_palette2,alpha=0.9,data=df_min,ax=ax2)
    ax2.set_yticklabels([])
    ax2.set_yticks([])
    ax2.set_ylabel('')
    for p in ax.patches:
        _x = p.get_x() + p.get_width() + 0.1
        _y = p.get_y() + p.get_height() - 0.2
        value = int(p.get_width())
        ax.text(_x, _y, value, horizontalalignment='left', verticalalignment='bottom', size='x-small')  
    plt.tight_layout()
    imagepath = "min_max_fansspeed_" + datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S") + ".png"
    fig.savefig("/app/static/images/" + imagepath, bbox_inches = "tight", pad_inches = 0.01)
    imageheight = (len(df_min)/4+1)*1500/10
    while not os.path.isfile("/app/static/images/" + imagepath):
        time.sleep(1)
    ############################## Sensor data and node names for header ########################
    show_names = 'true' # Default value to pass to html to enable a list of nodenames
    cpu_temps,vrm_temps,dimm_temps,sys_temps,sensor_fans,sensor_voltages,gpu_temps = get_sensor_names(bmc_ip)
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        show_names = 'false'    
    plt.close()
    if show_names == 'true':
        return render_template('imageOutput.html',rackname=rackname,show_names = show_names, chart_headers = chart_headers, sensor_voltages = sensor_voltages,gpu_temps=gpu_temps, cpu_temps = cpu_temps, sys_temps=sys_temps, vrm_temps = vrm_temps, dimm_temps = dimm_temps, sensor_fans = sensor_fans, data = zip(sensorNames, min_vals,min_dates,max_vals,max_dates,avg_vals,good_count,zero_count),imagepath="../static/images/" + imagepath,imageheight=imageheight,bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "min_max_fans",rackobserverurl = rackobserverurl)
    else:
        return render_template('imageOutput.html',rackname=rackname,show_names = show_names, chart_headers = chart_headers, sensor_voltages = sensor_voltages,gpu_temps=gpu_temps, cpu_temps = cpu_temps, sys_temps=sys_temps, vrm_temps = vrm_temps, dimm_temps = dimm_temps, sensor_fans = sensor_fans, data = zip(sensorNames, min_vals,min_dates,max_vals,max_dates,avg_vals,good_count,zero_count),imagepath="../static/images/" + imagepath,imageheight=imageheight,bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "min_max_fans",rackobserverurl = rackobserverurl)


@app.route('/min_max_power_chart/<bmc_ip>')
def min_max_power_chart(bmc_ip):
    messages, max_vals, min_vals, max_dates, min_dates, sensorNames, avg_vals, count_vals, elapsed_hour, good_count, zero_count, last_date = get_data.find_min_max(bmc_ip,"PowerControl", "PowerConsumedWatts", 9999)
    messages.insert(0,'Numerical Results: (Units: W)')    
    chart_headers = ['Rack Name: ' + rackname, 'BMC IP: ' + bmc_ip,  'Elapsed Time: ' + elapsed_hour + ' hours', 'Last Timestamp: ' + last_date, 'Value Counts: ' + str(count_vals), 'Extreme Sensor Readings: (Light Blue: Min, Green: Max)']
    df_max = pd.DataFrame({"Power Consumption (W)":max_vals, "Sensor Names": sensorNames})
    df_min = pd.DataFrame({"Power Consumption (W)":min_vals, "Sensor Names": sensorNames})
    sns.set_theme(style="whitegrid")
    fig, ax =plt.subplots(1,1,figsize=(10,len(df_max)/4+1))
    custom_palette = ["green"]
    sns_plot = sns.barplot(y="Sensor Names", x="Power Consumption (W)", palette = custom_palette,data=df_max, ax=ax)
    #ax.set_xticks(range(0,int(max(max_vals))+1,1000))
    ax.xaxis.label.set_color('black')
    ax.yaxis.label.set_color('black')
    ax.tick_params(labelcolor='black')
    ax2 = ax.twinx()
    custom_palette2 = ["white"]
    sns.barplot(y="Sensor Names", x="Power Consumption (W)", palette = custom_palette2,alpha=0.9,data=df_min,ax=ax2)
    ax2.set_yticklabels([])
    ax2.set_yticks([])
    ax2.set_ylabel('')
    for p in ax.patches:
        _x = (p.get_x() + p.get_width()) * 1.001
        _y = p.get_y() + p.get_height() - 0.13
        value = int(p.get_width())
        ax.text(_x, _y, value, horizontalalignment='left', verticalalignment='bottom')   
    plt.tight_layout()
    imagepath = "min_max_power_" + datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S") + ".png"
    fig.savefig("/app/static/images/" + imagepath, bbox_inches = "tight", pad_inches = 0.01)
    imageheight = (len(df_min)/4+1)*1500/10
    while not os.path.isfile("/app/static/images/" + imagepath):
        time.sleep(1)
    ############################## Sensor data and node names for header ########################
    show_names = 'true' # Default value to pass to html to enable a list of nodenames
    cpu_temps,vrm_temps,dimm_temps,sys_temps,sensor_fans,sensor_voltages,gpu_temps = get_sensor_names(bmc_ip)
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        show_names = 'false'
    plt.close()
    if show_names == 'true':
        return render_template('imageOutput.html',rackname=rackname,show_names = show_names, chart_headers = chart_headers, sensor_voltages = sensor_voltages,gpu_temps=gpu_temps, cpu_temps = cpu_temps, sys_temps=sys_temps, vrm_temps = vrm_temps, dimm_temps = dimm_temps, sensor_fans = sensor_fans, data = zip(sensorNames, min_vals,min_dates,max_vals,max_dates,avg_vals,good_count,zero_count),imagepath="../static/images/" + imagepath,imageheight=imageheight,bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "min_max_power",rackobserverurl = rackobserverurl)   
    else:
        return render_template('imageOutput.html',rackname=rackname,show_names = show_names, chart_headers = chart_headers, sensor_voltages = sensor_voltages,gpu_temps=gpu_temps, cpu_temps = cpu_temps, sys_temps=sys_temps, vrm_temps = vrm_temps, dimm_temps = dimm_temps, sensor_fans = sensor_fans, data = zip(sensorNames, min_vals,min_dates,max_vals,max_dates,avg_vals,good_count,zero_count),imagepath="../static/images/" + imagepath,imageheight=imageheight,bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "min_max_power",rackobserverurl = rackobserverurl)

@app.route('/min_max_alltemperatures_chart')
def min_max_alltemperatures_chart():
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        ip_list = getIPlist()
        names = ["" for a in range(len(ip_list))]
        node_names = ip_list
    else:
        node_names = []
        names = []
        ip_list = []
        for cur_ip, cur_name in ips_names:
            if cur_name == "No Value":
                node_names.append(cur_ip)
                names.append("")
            else:
                node_names.append(cur_ip + " (" + cur_name + ")" )
                names.append("(" + cur_name + ")")
            ip_list.append(cur_ip)
    sn_list = []
    for ip in ip_list:
        sn_list.append(getSerialNumber(ip))   
    sensor_id = request.args.get('var')
    sensor_id = str(sensor_id)
    max_vals, min_vals, max_dates, min_dates, avg_vals, all_count,  elapsed_hour, good_count, zero_count, last_date, sensor_name = get_data.find_min_max_rack(sensor_id, "Temperatures", "ReadingCelsius", 9999, ip_list)
    chart_headers = ['Rack Name: ' + rackname, 'Sensor Name: ' + sensor_name,'Elapsed Time: ' + elapsed_hour + ' hours', 'Last Timestamp: ' + last_date, 'Value Counts: ' + str(all_count), 'Extreme Sensor Readings: (Light Blue: Min, Green: Max)']
    df_max = pd.DataFrame({"Temperature (Celsius)":max_vals, "BMC IPs": node_names})
    df_min = pd.DataFrame({"Temperature (Celsius)":min_vals, "BMC IPs": node_names})
    sns.set_theme(style="whitegrid")
    fig, ax =plt.subplots(1,1,figsize=(10,len(df_max)/4+1))
    custom_palette = ["green"]
    sns_plot = sns.barplot(y="BMC IPs", x="Temperature (Celsius)", palette = custom_palette,data=df_max, ax=ax)
    ax.set_xticks(range(0,int(max(max_vals))+1,10))
    ax.xaxis.label.set_color('black')
    ax.yaxis.label.set_color('black')
    ax.tick_params(labelcolor='black')
    ax2 = ax.twinx()
    custom_palette2 = ["white"]
    sns.barplot(y="BMC IPs", x="Temperature (Celsius)", palette = custom_palette2,alpha=0.9,data=df_min,ax=ax2)
    ax2.set_yticklabels([])
    ax2.set_yticks([])
    ax2.set_ylabel('')
    for p in ax.patches:
        _x = p.get_x() + p.get_width() + 0.3
        _y = p.get_y() + p.get_height()
        value = int(p.get_width())
        ax.text(_x, _y, value, horizontalalignment='left', verticalalignment='bottom')   
    plt.tight_layout()
    imagepath = "min_max_alltemperatures_" + datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S") + ".png"
    fig.savefig("/app/static/images/" + imagepath)
    imageheight = (len(df_min)/4+1)*1500/10
    sensor = sensor_name #used for scoping into the chart
    while not os.path.isfile("/app/static/images/" + imagepath):
        time.sleep(1)
    plt.close()
    return render_template('imageOutputRack.html',rackname=rackname, sensor = sensor,chart_headers = chart_headers ,data = zip(ip_list, names, sn_list, min_vals,min_dates,max_vals,max_dates, avg_vals, good_count, zero_count),imagepath="../static/images/" + imagepath,imageheight=imageheight,rackobserverurl = rackobserverurl)

@app.route('/min_max_allpower_chart')
def min_max_allpower_chart():
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        ip_list = getIPlist()
        names = ["" for a in range(len(ip_list))]
        node_names = ip_list
    else:
        node_names = []
        names = []
        ip_list = []
        for cur_ip,cur_name in ips_names:
            if cur_name == "No Value":
                node_names.append(cur_ip)
                names.append("")
            else:
                node_names.append(cur_ip + " (" + cur_name + ")" )
                names.append("(" + cur_name + ")")
            ip_list.append(cur_ip)
    sn_list = []
    for ip in ip_list:
        sn_list.append(getSerialNumber(ip))   
    sensor_id = request.args.get('var')
    sensor_id = str(sensor_id)
    max_vals, min_vals, max_dates, min_dates, avg_vals, all_count, elapsed_hour, good_count, zero_count, last_date, sensor_name = get_data.find_min_max_rack(sensor_id,"PowerControl", "PowerConsumedWatts", 9999, ip_list)
    chart_headers = ['Rack Name: ' + rackname, 'Sensor Name: ' + sensor_name,'Elapsed Time: ' + elapsed_hour + ' hours', 'Last Timestamp: ' + last_date, 'Value Counts: ' + str(all_count), 'Extreme Sensor Readings: (Light Blue: Min, Green: Max)']
    df_max = pd.DataFrame({"Power Consumption (W)":max_vals, "BMC IPs": node_names})
    df_min = pd.DataFrame({"Power Consumption (W)":min_vals, "BMC IPs": node_names})
    sns.set_theme(style="whitegrid")
    fig, ax =plt.subplots(1,1,figsize=(10,len(df_max)/4+1))
    custom_palette = ["green"]
    sns_plot = sns.barplot(y="BMC IPs", x="Power Consumption (W)", palette = custom_palette,data=df_max, ax=ax)
    ax.xaxis.label.set_color('black')
    ax.yaxis.label.set_color('black')
    ax.tick_params(labelcolor='black')
    ax2 = ax.twinx()
    custom_palette2 = ["white"]
    sns.barplot(y="BMC IPs", x="Power Consumption (W)", palette = custom_palette2,alpha=0.9,data=df_min,ax=ax2)
    ax2.set_yticklabels([])
    ax2.set_yticks([])
    ax2.set_ylabel('')
    for p in ax.patches:
        _x = (p.get_x() + p.get_width()) * 1.001
        _y = p.get_y() + p.get_height() - 0.13
        value = int(p.get_width())
        ax.text(_x, _y, value, horizontalalignment='left', verticalalignment='bottom')   
    plt.tight_layout()
    imagepath = "min_max_allpower_" + datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S") + ".png"
    fig.savefig("/app/static/images/" + imagepath)
    imageheight = (len(df_min)/4+1)*1500/10
    sensor = sensor_name #used for scoping into the chart
    while not os.path.isfile("/app/static/images/" + imagepath):
        time.sleep(1)
    plt.close()
    return render_template('imageOutputRack.html',rackname=rackname,chart_headers = chart_headers ,sensor = sensor, data = zip(ip_list, names, sn_list, min_vals,min_dates,max_vals,max_dates, avg_vals, good_count, zero_count),imagepath="../static/images/" + imagepath,imageheight=imageheight,rackobserverurl = rackobserverurl)


@app.route('/chart_powercontrol/<bmc_ip>')
def chart_powercontrol(bmc_ip):
    ###################### Get Data ###################################################
    data = get_data.find_powercontrol(bmc_ip)
    show_names = 'true' # Default value to pass to html to enable a list of nodenames
    cpu_temps,vrm_temps,dimm_temps,sys_temps,sensor_fans,sensor_voltages,gpu_temps = get_sensor_names(bmc_ip)
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        show_names = 'false'
    ######## For Displaying Current Reading in realtime ##############################################
    try:
        df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
        current_pwd = df_pwd[df_pwd['ip'] == bmc_ip]['pwd'].values[0]
        response = Popen('ipmitool -H ' + bmc_ip + ' -U ADMIN -P ' + current_pwd + ' dcmi power reading', shell = 1, stdout  = PIPE, stderr = PIPE)
        stdout , stderr = response.communicate(timeout=1)
    except:
        reading = "ERROR"
        printf('No dcmi power reading!')
    else:
        if stderr.decode('utf-8') == '':
            output = stdout.decode("utf-8").split('\n')
            inst_power = output[1].split(':')
            reading = inst_power[1].lstrip()
        else:
            reading = "ERROR"
    #######  Returns reading as a number or a ERROR string for exception handling or a response from stderr ####################

    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        if show_names == 'true':
            return render_template('chart_powercontrol.html',rackname=rackname, reading= reading, title='Power Control', show_names = show_names, dataset=data,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_powercontrol",rackobserverurl = rackobserverurl)        
        else:
            return render_template('chart_powercontrol.html', reading= reading, title='Power Control', show_names = show_names, dataset=data,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_powercontrol",rackobserverurl = rackobserverurl)
    else:
        name = request.args.get('name')
        if show_names == 'true':
            return render_template('chart_powercontrol.html',rackname=rackname,reading = reading,title='Power Control',show_names = show_names,gpu_temps=gpu_temps, cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages,name = name, dataset=data, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_powercontrol",rackobserverurl = rackobserverurl)
        else:
            return render_template('chart_powercontrol.html',rackname=rackname,reading = reading,title='Power Control',show_names = show_names,gpu_temps=gpu_temps, cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages,name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_powercontrol",rackobserverurl = rackobserverurl)

@app.route('/chart_voltages/<bmc_ip>')
def chart_voltages(bmc_ip):
    ###################### Get Data ###################################################
    data = get_data.find_voltages(bmc_ip)
    show_names = 'true' # Default value to pass to html to enable a list of nodenames
    cpu_temps,vrm_temps,dimm_temps,sys_temps,sensor_fans,sensor_voltages,gpu_temps = get_sensor_names(bmc_ip)
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        show_names = 'false'
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        if show_names == 'true':
            return render_template('chart_voltages.html', title='Voltages',rackname=rackname, show_names = show_names, dataset=data,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_voltages",rackobserverurl = rackobserverurl)
        else:
            return render_template('chart_voltages.html', title='Voltages',rackname=rackname, show_names = show_names, dataset=data,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_voltages",rackobserverurl = rackobserverurl)

    else:
        name = request.args.get('name')
        if show_names == 'true':
            return render_template('chart_voltages.html', title='Voltages',rackname=rackname,show_names = show_names,gpu_temps=gpu_temps, cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_voltages",rackobserverurl = rackobserverurl)
        else:
            return render_template('chart_voltages.html', title='Voltages',rackname=rackname,show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_voltages",rackobserverurl = rackobserverurl)
   

@app.route('/chart_powersuppliesvoltage/<bmc_ip>')
def chart_powersuppliesvoltage(bmc_ip):
    ###################### Get Data ###################################################
    data = get_data.find_powersupplies(bmc_ip)
    show_names = 'true' # Default value to pass to html to enable a list of nodenames
    cpu_temps,vrm_temps,dimm_temps,sys_temps,sensor_fans,sensor_voltages,gpu_temps = get_sensor_names(bmc_ip)
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        show_names = 'false'
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        if show_names == 'true':
            return render_template('chart_powersuppliesvoltage.html', title='Power Supplies Voltage',rackname=rackname, show_names = show_names, dataset=data,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_powersuppliesvoltage")
        else:
            return render_template('chart_powersuppliesvoltage.html', title='Power Supplies Voltage',rackname=rackname, show_names = show_names, dataset=data,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_powersuppliesvoltage")
    else:
        name = request.args.get('name')
        if show_names == 'true':
            return render_template('chart_powersuppliesvoltage.html', title='Power Supplies Voltage',rackname=rackname,show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages,name = name, dataset=data, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_powersuppliesvoltage",rackobserverurl = rackobserverurl)        
        else:
            return render_template('chart_powersuppliesvoltage.html', title='Power Supplies Voltage',rackname=rackname,show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages,name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_powersuppliesvoltage",rackobserverurl = rackobserverurl)
     
@app.route('/chart_powersuppliespower/<bmc_ip>')
def chart_powersuppliespower(bmc_ip):
    ###################### Get Data ###################################################
    data = get_data.find_powersupplies(bmc_ip)
    show_names = 'true' # Default value to pass to html to enable a list of nodenames
    cpu_temps,vrm_temps,dimm_temps,sys_temps,sensor_fans,sensor_voltages,gpu_temps = get_sensor_names(bmc_ip)
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        show_names = 'false'
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        if show_names == 'true':
            return render_template('chart_powersuppliespower.html', title='Power Supplies Power',rackname=rackname, show_names = show_names, dataset=data,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_powersuppliespower",rackobserverurl = rackobserverurl)
        else: 
            return render_template('chart_powersuppliespower.html', title='Power Supplies Power',rackname=rackname, show_names = show_names, dataset=data,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_powersuppliespower",rackobserverurl = rackobserverurl)

    else:
        name = request.args.get('name')
        if show_names == 'true':
            return render_template('chart_powersuppliespower.html', title='Power Supplies Power',rackname=rackname, show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_powersuppliespower",rackobserverurl = rackobserverurl)        
        else:
            return render_template('chart_powersuppliespower.html', title='Power Supplies Power',rackname=rackname, show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_powersuppliespower",rackobserverurl = rackobserverurl)
  
@app.route('/chart_allpowercontrols')
def chart_allpowercontrols():
    ip_list = getIPlist()
    node_names = get_node_names()
    data = get_data.find_allpowercontrols(ip_list)
    if isinstance(node_names,bool) != True:
        node_names = list(node_names)
        for i in data.get("PowerControl"):
            for cur_ip,cur_name in node_names:
                if cur_ip == i.get("Name").split(",")[0].strip(" ") and cur_name != "No Value":
                    i.update({"Name": cur_name + " (" + cur_ip + "), Unit: W"})
                    break
    return render_template('chart_allpowercontrols.html', title='All Power Controls',rackname=rackname, dataset=data, chart_name = "chart_allpowercontrols",rackobserverurl = rackobserverurl)

@app.route('/chart_alltemperatures')
def chart_alltemperatures():
    ip_list = getIPlist()
    sensor_id = request.args.get('var')
    sensor_id = str(sensor_id)
    data = get_data.find_alltemperatures(ip_list, sensor_id)
    sensor_name = list(data.keys())[-1] # sensoranme is the last key
    node_names = get_node_names()
    if isinstance(node_names,bool) != True:
        node_names = list(node_names)
        for i in data.get(sensor_name): # ip = data[sensor_name]["Name"]
            for cur_ip,cur_name in node_names:
                if cur_ip == i.get("Name").split(",")[0] and cur_name != "No Value": # 
                    i.update({"Name": cur_name + " (" + cur_ip + ")"})
                    break
    return render_template('chart_alltemperatures.html', title='All Temperature ' + sensor_name,rackname=rackname, dataset=data, sensor_name=sensor_name, chart_name = "chart_alltemperatures",rackobserverurl = rackobserverurl)

@app.route('/chart_allfans')
def chart_allfans():
    ip_list = getIPlist()
    sensor_id = request.args.get('var')
    sensor_id = str(sensor_id)
    data = get_data.find_allfans(ip_list, sensor_id)
    sensor_name = list(data.keys())[-1] # sensoranme is the last key
    node_names = get_node_names()
    if isinstance(node_names,bool) != True:
        node_names = list(node_names)
        for i in data.get(sensor_name): # ip = data[sensor_name]["Name"]
            for cur_ip,cur_name in node_names:
                if cur_ip == i.get("Name") and cur_name != "No Value":
                    i.update({"Name": cur_name + " (" + cur_ip + ")"})
                    break
    return render_template('chart_allfans.html', title='All Fans ' + sensor_name,rackname=rackname, dataset=data, sensor_name=sensor_name, chart_name = "chart_allfans",rackobserverurl = rackobserverurl)     

@app.route('/chart_fans/<bmc_ip>')
def chart_fans(bmc_ip):
    ###################### Get Data ###################################################
    data = get_data.find_fans(bmc_ip)
    show_names = 'true' # Default value to pass to html to enable a list of nodenames
    cpu_temps,vrm_temps,dimm_temps,sys_temps,sensor_fans,sensor_voltages,gpu_temps = get_sensor_names(bmc_ip)
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        show_names = 'false'
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')    
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        if show_names == 'true':
            return render_template('chart_fans.html', title='Fans',rackname=rackname, show_names = show_names, dataset=data, skip = skip,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_fans",rackobserverurl = rackobserverurl)
        else:
            return render_template('chart_fans.html', title='Fans',rackname=rackname, show_names = show_names, dataset=data, skip = skip,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_fans",rackobserverurl = rackobserverurl)

    else:
        name = request.args.get('name')
        if show_names == 'true':
            return render_template('chart_fans.html', title='Fans',rackname=rackname,show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_fans",rackobserverurl = rackobserverurl)        
        else:
            return render_template('chart_fans.html', title='Fans',rackname=rackname,show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_fans",rackobserverurl = rackobserverurl)


@app.route('/chart_cputemperatures/<bmc_ip>')
def chart_cputemperatures(bmc_ip):
    ###################### Get Data ###################################################
    data = get_data.find_temperatures(bmc_ip)
    show_names = 'true' # Default value to pass to html to enable a list of nodenames
    cpu_temps,vrm_temps,dimm_temps,sys_temps,sensor_fans,sensor_voltages,gpu_temps = get_sensor_names(bmc_ip)
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        show_names = 'false'
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        if show_names == 'true':
            return render_template('chart_cputemperatures.html', title='CPU Temperatures',rackname=rackname,show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min , t_max = t_max ,t_min_max = t_min_max, dataset=data, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_cputemperatures",rackobserverurl = rackobserverurl)
        else:
            return render_template('chart_cputemperatures.html', title='CPU Temperatures',rackname=rackname,show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min , t_max = t_max ,t_min_max = t_min_max, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_cputemperatures",rackobserverurl = rackobserverurl)
    else:
        name = request.args.get('name')
        if show_names == 'true':
            return render_template('chart_cputemperatures.html', title='CPU Temperatures',rackname=rackname,show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_cputemperatures",rackobserverurl = rackobserverurl)
        else:
            return render_template('chart_cputemperatures.html', title='CPU Temperatures',rackname=rackname,show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_cputemperatures",rackobserverurl = rackobserverurl)

@app.route('/chart_gputemperatures/<bmc_ip>')
def chart_gputemperatures(bmc_ip):
    ###################### Get Data ###################################################
    data = get_data.find_temperatures(bmc_ip)
    show_names = 'true' # Default value to pass to html to enable a list of nodenames
    cpu_temps,vrm_temps,dimm_temps,sys_temps,sensor_fans,sensor_voltages,gpu_temps = get_sensor_names(bmc_ip)
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        show_names = 'false'
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        if show_names == 'true':
            return render_template('chart_gputemperatures.html', title='GPU Temperatures',rackname=rackname,show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min , t_max = t_max ,t_min_max = t_min_max, dataset=data, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_gputemperatures",rackobserverurl = rackobserverurl)
        else:
            return render_template('chart_gputemperatures.html', title='GPU Temperatures',rackname=rackname,show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min , t_max = t_max ,t_min_max = t_min_max, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_gputemperatures",rackobserverurl = rackobserverurl)
    else:
        name = request.args.get('name')
        if show_names == 'true':
            return render_template('chart_gputemperatures.html', title='GPU Temperatures',rackname=rackname,show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_gputemperatures",rackobserverurl = rackobserverurl)
        else:
            return render_template('chart_gputemperatures.html', title='GPU Temperatures',rackname=rackname,show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_gputemperatures",rackobserverurl = rackobserverurl)

"""
@app.route('/chart_systemtemperatures/<bmc_ip>')
def chart_systemtemperatures(bmc_ip):
    data = get_data.find_temperatures(bmc_ip)
    return render_template('chart_systemtemperatures.html', title='System Temperatures', dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist())
"""

@app.route('/chart_vrmtemperatures/<bmc_ip>')
def chart_vrmtemperatures(bmc_ip):
    ###################### Get Data ###################################################
    data = get_data.find_temperatures(bmc_ip)
    show_names = 'true' # Default value to pass to html to enable a list of nodenames
    cpu_temps,vrm_temps,dimm_temps,sys_temps,sensor_fans,sensor_voltages,gpu_temps = get_sensor_names(bmc_ip)
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        show_names = 'false'
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        if show_names == 'true':
            return render_template('chart_vrmtemperatures.html', title='VRM Temperatures',rackname=rackname,show_names = show_names, dataset=data,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_vrmtemperatures",rackobserverurl = rackobserverurl)
        else:
            return render_template('chart_vrmtemperatures.html', title='VRM Temperatures',rackname=rackname, show_names = show_names, dataset=data,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_vrmtemperatures",rackobserverurl = rackobserverurl)
    else:
        name = request.args.get('name')
        if show_names == 'true':
            return render_template('chart_vrmtemperatures.html', title='VRM Temperatures',rackname=rackname,show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_vrmtemperatures",rackobserverurl = rackobserverurl)     
        else:
            return render_template('chart_vrmtemperatures.html', title='VRM Temperatures',rackname=rackname,show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_vrmtemperatures",rackobserverurl = rackobserverurl)     


@app.route('/chart_dimmctemperatures/<bmc_ip>')
def chart_dimmctemperatures(bmc_ip):
    ###################### Get Data ###################################################
    data = get_data.find_temperatures(bmc_ip)
    show_names = 'true' # Default value to pass to html to enable a list of nodenames
    cpu_temps,vrm_temps,dimm_temps,sys_temps,sensor_fans,sensor_voltages,gpu_temps = get_sensor_names(bmc_ip)
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        show_names = 'false'
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        if show_names == 'true':
            return render_template('chart_dimmctemperatures.html', title='DIMMC Temperatures',rackname=rackname, show_names = show_names, dataset=data,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_dimmctemperatures",rackobserverurl = rackobserverurl)

        else:
            return render_template('chart_dimmctemperatures.html', title='DIMMC Temperatures',rackname=rackname, show_names = show_names, dataset=data,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_dimmctemperatures",rackobserverurl = rackobserverurl)

    else:
        name = request.args.get('name')
        if show_names == 'true':
            return render_template('chart_dimmctemperatures.html', title='DIMMC Temperatures',rackname=rackname, show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_dimmctemperatures",rackobserverurl = rackobserverurl)

        else:
            return render_template('chart_dimmctemperatures.html', title='DIMMC Temperatures',rackname=rackname, show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_dimmctemperatures",rackobserverurl = rackobserverurl)

@app.route('/chart_othertemperatures/<bmc_ip>')
def chart_othertemperatures(bmc_ip):
    ###################### Get Data ###################################################
    data = get_data.find_temperatures(bmc_ip)
    show_names = 'true' # Default value to pass to html to enable a list of nodenames
    cpu_temps,vrm_temps,dimm_temps,sys_temps,sensor_fans,sensor_voltages,gpu_temps = get_sensor_names(bmc_ip)
    ips_names = get_node_names()
    if isinstance(ips_names,bool) == True:
        show_names = 'false'

    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        if show_names == 'true':
            return render_template('chart_othertemperatures.html', title='Other Temperatures',rackname=rackname,show_names = show_names,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, dataset=data, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_othertemperatures",rackobserverurl = rackobserverurl)
        else:
            return render_template('chart_othertemperatures.html', title='Other Temperatures',rackname=rackname,show_names = show_names,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_othertemperatures",rackobserverurl = rackobserverurl)
    else:
        name = request.args.get('name')
        if show_names == 'true':
            return render_template('chart_othertemperatures.html', title='Other Temperatures',rackname=rackname,show_names = show_names,gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = ips_names, chart_name = "chart_othertemperatures",rackobserverurl = rackobserverurl)
        else:
            return render_template('chart_othertemperatures.html', title='Other Temperatures',rackname=rackname,show_names = show_names, gpu_temps=gpu_temps,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_othertemperatures",rackobserverurl = rackobserverurl)

def get_frontend_urls():
    files = os.listdir(os.environ['UPLOADPATH'])
    frontend_urls = []
    for i in files:
        if 'port' in i and '.env' in i:
            with open(os.environ["UPLOADPATH"] + i,'r') as file:
                url_name = []
                lines = file.readlines()
                for line in lines:
                    if 'FRONTPORT' in line:
                        port = line.split("=")[1]
                        url_name.append('http://' + get_ip() + ':' + str(port))
                    elif 'RACKNAME' in line:
                        url_name.append(line.split("=")[1])
                frontend_urls.append(url_name)      
    return frontend_urls #### (RACKNAME,FRONTEND_URL)                        
@app.route("/hardware_output",methods=["GET","POST"])
def hardware_output():
    data = get_data.get_hardwareData()
    urls = get_frontend_urls()  
    return render_template('hardware_output.html',data=data,rackname=rackname,rackobserverurl = rackobserverurl,frontend_urls = urls)

@app.route('/get_node_hardware_json')
def get_node_hardware_json():
    bmc_ip = request.args.get('var')
    cur_result = hardware_collection.find_one({'bmc_ip':bmc_ip},{'_id':0})
    hostname = cur_result['Hostname']
    try:
        filename = os.environ['UPLOADPATH'] + hostname + "_hardware.json"
        with open(filename, 'w') as output:
            json.dump(cur_result,output)
    except:
        print("Error on downloading json",flush=True)
    else:
        return send_file(filename,as_attachment=True,cache_timeout=0)

@app.route('/check_Topo_file')
def check_Topo_file():
    hostname = request.args.get('hostname')
    client = MongoClient('localhost', mongoport)
    db_temp = client.redfish
    hw_collec = db_temp.hw_data
    node_dict = hw_collec.find_one({'Hostname':hostname})
    try: 
        image_id = node_dict['TOPO_file']['imageID']
        image_shape = node_dict['TOPO_file']['shape']
        topo_filename = node_dict['TOPO_file']['filename']
    except:
        response = {"response" : "Error"}
    else:
        response = {"response" : "OK"}
    return json.dumps(response)

@app.route('/get_node_Topo')
def get_node_Topo():
    hostname = request.args.get('hostname')
    client = MongoClient('localhost', mongoport)
    db_temp = client.redfish
    hw_collec = db_temp.hw_data
    fs = gridfs.GridFS(db_temp)
    node_dict = hw_collec.find_one({'Hostname':hostname})
    image_id = node_dict['TOPO_file']['imageID']
    image_shape = node_dict['TOPO_file']['shape']
    topo_filename = node_dict['TOPO_file']['filename']
    gOut = fs.get(image_id)
    img = np.frombuffer(gOut.read(), dtype=np.uint8)
    img = np.reshape(img, image_shape)
    filepath = os.environ['UPLOADPATH'] + '/hw_data/hw_info_' + hostname + '/' + topo_filename
    if not os.path.exists(os.environ['UPLOADPATH'] + '/hw_data/hw_info_' + hostname):
        path = os.environ['UPLOADPATH'] + '/hw_data/hw_info_' + hostname
        md = 0o666
        os.mkdir(path, md)
    topo_image = cv2.imwrite(filepath,img)
    client.close()
    return send_file(filepath,as_attachment=True,cache_timeout=0)

@app.route('/get_node_serialNums_txt')
def get_node_serialNums_txt():
    filename = request.args.get('file')
    return send_file(filename,as_attachment=True,cache_timeout=0)

@app.route('/check_serial_num')
def check_serial_num():
    bmc_ip = request.args.get('ip')
    cur_result = hardware_collection.find_one({'bmc_ip':bmc_ip},{'_id':0})
    hostname = cur_result['Hostname']
    hostname = hostname.replace("-","")
    filename = ""
    directory = os.environ['UPLOADPATH']
    for folder in os.listdir(directory): ##### Get hw_data directory
        if 'hw_data' in folder and os.path.isdir(directory + folder) == True:
            directory += folder
            break
    try:
        sys_serial = [] ############# Check if system serial number exists....
        for i in cur_result['System']:
            sys_serial.append(cur_result['System'][str(i)]['Serial Number'].lower())
    except Exception as e: ######### If it does not exist, use ONLY hostname to check...
        print(e,file=sys.stderr,flush=True)
        for file in os.listdir(directory):
            if file.split(".")[0].upper() == hostname.upper():
                print("Found file",flush=True)
                filename = directory +  "/" +  file
                break
    else: ######### If serial number exists, check with serial OR hostname
        for file in os.listdir(directory):
            for y in sys_serial:
                if file.split(".")[0].upper() == y.upper() or file.split(".")[0].upper() == hostname.upper():
                    print("Found file",flush=True)
                    filename = directory +  "/" +  file
                    break
    if filename == "":
        print("No file found: parsed with " + hostname + " " + sys_serial[0] + " " + directory ,file=sys.stderr,flush=True)
        data = {"response":"Not found"}
    else:
        data = {"response": "OK","file":filename}
    result = json.dumps(data)
    return result   

@app.route("/get_hardware_details")
def get_hardware_details():
    bmc_ip = request.args.get('ip')
    hardware = request.args.get('hw')
    details = get_data.fetch_hardware_details(bmc_ip,hardware)
    data = json.dumps(details)
    return data

@app.route('/SMC_db_handshake')
def SMC_db_handshake():
    os.system("chmod +wx SMC_db_handshake.py")
    compare = Popen("python3 SMC_db_handshake.py",shell=True,stdout=PIPE,stderr=PIPE)
    stdout,stderr = compare.communicate()
    if stderr.decode() != '':
        feedback = {"response" : stderr.decode()}
        data = json.dumps(feedback)
        return data
    else:
        feedback = {"response":"Completed"}
        data = json.dumps(feedback)
        return data                                               

@app.route('/hardware_parser')
def hardware_parser():
    os.system("chmod +wx hw_data_extractor.py")
    get_hardware = Popen("python3 hw_data_extractor.py",shell=True,stdout=PIPE,stderr=PIPE)
    stdout,stderr = get_hardware.communicate()
    if stderr.decode() != '':
        feedback = {"response" : stderr.decode()}
        data = json.dumps(feedback)
        return data
    else:
        hw_collection = db.hw_data
        df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
        bmc_ips = list(df_pwd['ip'])
        database_ips = hw_collection.find({},{"bmc_ip":1,"_id":0})
        db_ips = list(database_ips)
        if len(db_ips) == 0:
            feedback = {"response" : "Error: no entries inserted"}
        else:
            feedback = True
            db_ips = []
            for i in database_ips:
                if i['bmc_ip'] not in bmc_ips:
                    feedback = False
            if feedback == True:
                feedback = {"response" : "OK"}
            else:
                feedback = {"response" : "Error: some data was not inserted"}
        data = json.dumps(feedback)
        return data

@app.route('/benchmark_result_parser')
def benchmark_result_parser():
    # inputs
    output_path = os.environ['OUTPUTPATH']
    inputdir = os.environ['UPLOADPATH'] + '/' + 'benchmark_logs'
    configdir = os.environ['UPLOADPATH']  + '/'+ 'benchmark_configs'
    # read config files
    config_list = []
    for root,dirs,files in os.walk(configdir):
        for file in sorted(files):
            if '.json' in file:
                #print(file)
                config_list.append(parseInput(configdir + '/' + file))
    # Get mac addreess
    mac_dict = {}
    df_pwd = pd.read_csv(output_path,names=['ip','os_ip','mac','node','pwd'])
    for os_ip, mac in zip(df_pwd['os_ip'],df_pwd['mac']):
        mac_dict[clean_mac(mac)] = os_ip
    dirname_list = []
    messages = {'Insert Status':'success'}
    try:
        for dirname in os.listdir(inputdir):
        # Check MAC address for each dir, only read mac address belongs to the rack
            if os.path.isdir(inputdir + '/' + dirname) and clean_mac(dirname.split('_')[-1]) in mac_dict:
                dirname_list.append(dirname)
                cur_mac = dirname.split('_')[-1]
                cur_ip = mac_dict[clean_mac(cur_mac)]
                printf("###################################################### " + cur_ip + '||' + dirname + " #####################################################")
                messages[cur_ip]  = dirname
                for filename in os.listdir(inputdir + '/' + dirname):
                    for config in config_list:
                        # Only parse the log has config files
                        if filename.lower().startswith(config['log'].lower()):
                            print(filename)
                            with open(inputdir + '/' + dirname + '/' + filename, 'r') as logfile:
                                contents = logfile.read()
                            if getsizeof(contents) > 16000000:                               
                                lines = contents.split('\n')
                                sub_lines = int(len(lines) * 16000000/getsizeof(contents) * 0.9)
                                contents_mongo = 'Info: Lines have been hidden due to the size of log file is larger than 16 MB.\n' + '\n'.join(lines[-sub_lines::])
                            else:
                                contents_mongo = contents
                            conclusionAndResult = 'N/A'
                            if config['parseResultLog'] == 1:
                                conclusionAndResult = resultParser(contents, keywords=config['keywords'], addRow=config['addRow'], \
                                                       dfs=config['dfs'], index=config['index'], unit=config['unit'], \
                                                       criteriaType=config['criteriaType'], criteria=config['criteria'])
                                print(conclusionAndResult.values())                                
                                file_data = {\
                                        'os_ip':cur_ip,\
                                        'mac':cur_mac,\
                                        'file_name':filename,\
                                        'start_date':"Self-inserted",\
                                        'done_date':datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),\
                                        'content':contents_mongo,\
                                        'result':conclusionAndResult['result'],\
                                        'conclusion':conclusionAndResult['conclusion'],\
                                        'category':config['category'],\
                                        'config':config['config'],\
                                        'cmd':config['prefix'] + " " + config['exe'] + " " + config['config'],\
                                        'benchmark':config['log'],\
                                        'unit':config['unit'],\
                                        'result_name':config['resultName'],\
                                        'raw_result':conclusionAndResult['raw_result'],\
                                        'star':-1}
                                #print(file_data)
                            else:
                                file_data = {\
                                        'os_ip':cur_ip,\
                                        'mac':cur_mac,\
                                        'file_name':filename,\
                                        'start_date':"Self-inserted",\
                                        'done_date':datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),\
                                        'content':contents_mongo,\
                                        'result':'Disabled',\
                                        'conclusion':'Disabled',\
                                        'category':config['category'],\
                                        'config':config['config'],\
                                        'cmd':config['prefix'] + " " + config['exe'] + " " + config['config'],\
                                        'benchmark':config['log'],\
                                        'unit':['N/A'],\
                                        'result_name':['N/A'],\
                                        'raw_result':['N/A'],\
                                        'star':-1} 
                            udp_collection.insert(file_data)       
        printf("Benchmark Data Insert Done!")
        printf(messages)
    except Exception as e:
        messages['Insert Status'] = 'failed'
        messages['Error Message'] = str(e)
        printf("Error message: " + str(e))
    data = json.dumps(messages)
    return data

def get_sensor_names(bmc_ip): #Sensor names only for header in html - return a various lists
    cpu_temps,vrm_temps,dimm_temps,sys_temps,gpu_temps = get_temp_names(bmc_ip)
    sensor_fans = get_fan_names(bmc_ip)
    sensor_voltages = get_voltage_names(bmc_ip)
    return cpu_temps,vrm_temps,dimm_temps,sys_temps,sensor_fans,sensor_voltages,gpu_temps

def get_node_names(): #Gather node names from node_names file. Return a boolean if failed or no names in all, else a list tuple list  of (ipmi ip - nodename)
    ##################### Try Catch block for accepting a nodenames values in nodes list
    try:
        df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
        df_names = pd.read_csv(os.environ['NODENAMES']) #Global variable file for container
        df_pwd['name'] = list(df_names['name'])
    except Exception as e:
        show_names = False
        printf("Failed to get node names with error message:" + str(e))
        return show_names
    else:
        node_names = []
        ips = []
        no_name_count = 0
        for i in list(df_pwd['ip']):
            if df_pwd[df_pwd['ip'] == i]['name'].values[0] == 'No Value':
                no_name_count += 1
            node_names.append(df_pwd[df_pwd['ip'] == i]['name'].values[0])
            ips.append(i)
        if df_pwd['name'].isnull().sum() == len(list(df_pwd['ip']))  or no_name_count == len(list(df_pwd['ip'])):
            show_names = False
            return show_names
        else:
            ips_names = zip(ips,node_names) #zip for easy reading in html
            return ips_names


@app.errorhandler(404)
def page_not_found(e):
    # note that we set the 404 status explicitly!!
    return render_template('404.html',rackname=rackname,rackobserverurl = rackobserverurl), 404

@app.errorhandler(500)
def internal_error(e):
    # note that we set the 500 status explicitly!!
    return render_template('500.html',rackname=rackname,rackobserverurl = rackobserverurl), 500

@app.route('/sum_manual')
def sum_manual():
    return send_file("/app/templates/SUM_UserGuide_280.pdf",cache_timeout=0)

@app.route('/howToDeploy')
def howToDeploy():
    return send_file("/app/templates/Manual.pdf",cache_timeout=0)

@app.route('/developmentnote08182020')
def developmentnote08182020():
    return send_file("/app/templates/DevelopmentNote.pdf",cache_timeout=0)

@app.route('/developmentnote04152021')
def developmentnote04152021():
    return send_file("/app/templates/DevelopmentNoteV2.pdf",cache_timeout=0)

@app.route('/developmentnote06022022')
def developmentnote06022022():
    return send_file("/app/templates/DevelopmentNoteV3.pdf",cache_timeout=0)

### Report Generation ###
@app.route('/downloadClusterReport')
def downloadClusterReport():
    os.system("chmod +wx cluster_report.py")
    try:
        os.remove("cluster_report.pdf")
    except Exception as e:
        printf(e)
    try:
        subprocess.check_call("python3 cluster_report.py",shell=True)
    except Exception as e:
        return render_template('error.html',error=e)
    while not os.path.isfile("cluster_report.pdf"):
        time.sleep(1)
    return send_file("cluster_report.pdf",cache_timeout=0)

### Report Generation ###
@app.route('/downloadNodeReport_JSON/<bmc_ip>')
def downloadNodeReport_JSON(bmc_ip):
    #details = collection.find_one({"BMC_IP": bmc_ip}, {"_id":0,"BMC_IP":1, "Datetime":1,"UUID":1,"Systems.1.Description":1,"Systems.1.Model":1,"Systems.1.SerialNumber":1, "Systems.1.ProcessorSummary.Count":1, "Systems.1.ProcessorSummary.Model":1, "Systems.1.MemorySummary.TotalSystemMemoryGiB":1, "Systems.1.SimpleStorage.1.Devices.Name":1, "Systems.1.SimpleStorage.1.Devices.Model":1,  "UpdateService.SmcFirmwareInventory.1.Name":1, "UpdateService.SmcFirmwareInventory.1.Version":1, "UpdateService.SmcFirmwareInventory.2.Name":1, "UpdateService.SmcFirmwareInventory.2.Version":1, "Systems.1.CPU":1, "Systems.1.Memory":1, "Systems.1.SimpleStorage":1,"Systems.1.PCIeDevices":1}  )
    details = collection.find_one({"BMC_IP": bmc_ip})
    path = os.environ['JSONPATH']
    new_path = path[:-4] + "_" + str(time.perf_counter()).replace(".","") + path[-4:] # Need debug
    json.dump(json_util.dumps(details), open(new_path, "w"))
    return send_file(new_path, as_attachment=True, cache_timeout=0)

@app.route('/downloadNodeReport_PDF/<bmc_ip>')
def downloadNodeReport_PDF(bmc_ip):
    summary = collection.find_one({"BMC_IP": bmc_ip}, {"_id":0,"BMC_IP":1, "Datetime":1,"UUID":1,"Systems.1.Description":1,"Systems.1.Model":1,"Systems.1.SerialNumber":1, "Systems.1.ProcessorSummary.Count":1, "Systems.1.ProcessorSummary.Model":1, "Systems.1.MemorySummary.TotalSystemMemoryGiB":1, "Systems.1.SimpleStorage.1.Devices.Name":1, "Systems.1.SimpleStorage.1.Devices.Model":1,  "UpdateService.SmcFirmwareInventory.1.Name":1, "UpdateService.SmcFirmwareInventory.1.Version":1, "UpdateService.SmcFirmwareInventory.2.Name":1, "UpdateService.SmcFirmwareInventory.2.Version":1})
    cpu = collection.find({"BMC_IP": bmc_ip}, {"_id":0,"Systems.1.CPU":1})
    mem = collection.find({"BMC_IP": bmc_ip}, {"_id":0,"Systems.1.Memory":1})
    storage = collection.find({"BMC_IP": bmc_ip}, {"_id":0,"Systems.1.SimpleStorage":1})
    pcie = collection.find_one({"BMC_IP": bmc_ip}, {"_id":0,"Systems.1.PCIeDevices":1})
    system1 = json2html.convert(json = summary)
    driveCount = 0
    memSerial = []
    for x in cpu:
        try:
            processorModel = x['Systems']['1']['CPU']['1']['Model']
        except:
            processorModel = "N/A"
        try:
            processorCount = len(x['Systems']['1']['CPU'])
        except:
            processorCount = "N/A"
        try:
            processorCores = x['Systems']['1']['CPU']['1']['TotalCores']
        except:
            processorCores = "N/A"
        try:
            processorSpeed = x['Systems']['1']['CPU']['1']['MaxSpeedMHz']
        except:
            processorSpeed = "N/A"
    
    for x in mem:
        try:
            memCount = len(x['Systems']['1']['Memory'])
        except:
            memCount = "N/A"
        try:
            memCapacity = x['Systems']['1']['Memory']['1']['CapacityMiB']
        except:
            memCapacity = "N/A"
        try:
            memDeviceType = x['Systems']['1']['Memory']['1']['MemoryDeviceType']
        except:
            memDeviceType = "N/A"
        try:
           memOpSpeed = x['Systems']['1']['Memory']['1']['OperatingSpeedMhz']
        except:
            memOpSpeed = "N/A"
        try:
            memManufacturer = x['Systems']['1']['Memory']['1']['Manufacturer']
        except:
            memManufacturer = "N/A"
        try:
            memPartNumber = x['Systems']['1']['Memory']['1']['PartNumber']
        except:
            memPartNumber = "N/A"
        try:
            for y in range(1,memCount+1):
                count = str(y)
                memSerial.append(x['Systems']['1']['Memory'][count]['SerialNumber'])
        except:
            memSerial = ["N/A"]
    
    for x in storage:
        try:
            driveDescription = x['Systems']['1']['SimpleStorage']['1']['Description']
        except:
            driveDescription = "N/A"
        try:
            driveCount = len(x['Systems']['1']['SimpleStorage']['1']['Devices'])
        except:
            driveCount = "N/A"
        try:
            driveModel = x['Systems']['1']['SimpleStorage']['1']['Devices'][0]['Model']
        except:
            driveModel = "N/A"
       
    pcie = json2html.convert(json = pcie)
        
    
    
    html = render_template('details_pdf.html', ip=bmc_ip, system=system1, processorModel=processorModel, processorCount=processorCount, processorCores=processorCores, processorSpeed=processorSpeed, memCount=memCount, memCapacity = memCapacity, memDeviceType=memDeviceType, memOpSpeed=memOpSpeed, memManufacturer=memManufacturer, memPartNumber=memPartNumber, memSerial=memSerial, driveDescription=driveDescription, driveCount=driveCount, driveModel=driveModel, pcie=pcie)
    return render_pdf(HTML(string=html))
### Report Generation ####

if __name__ == '__main__':
    get_data.makeSmcipmiExcutable()
    rackobserverurl =  'http://' + get_ip() + ':' +  os.environ['RACKPORT']
    printf("Frontend port number is " + str(frontport))
    if os.environ['DEBUG_MODE'] == 'True':
        printf('Debug Mode is True')
        app.debug =True
        app.secret_key = b'_5#y2L"F4Q8z\n\xec]/'
        app.config['DEBUG_TB_PROFILER_ENABLED'] = True # enable the profiler by default
        toolbar = DebugToolbarExtension(app)
        dashboard.bind(app)
        app.run(host='0.0.0.0',port=frontport, debug=True)
    else:
        printf('Debug Mode is False')
        app.run(host='0.0.0.0',port=frontport)
