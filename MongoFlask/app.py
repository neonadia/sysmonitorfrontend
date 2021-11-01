from flask import Flask, render_template, request, url_for, jsonify, redirect, send_file, send_from_directory
from flask_weasyprint import HTML, render_pdf
import json
from bson import json_util
from pymongo import MongoClient
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
from sumtoolbox import makeSumExcutable, sumBiosUpdate, sumBMCUpdate, sumGetBiosSettings, sumCompBiosSettings, sumBootOrder, sumLogOutput, sumChangeBiosSettings, sumRunCustomProcess
import tarfile
from udpcontroller import getMessage, insertUdpevent, cleanIP
from glob import iglob
import datetime
from datetime import timedelta
import seaborn as sns
import matplotlib.pyplot as plt

app = Flask(__name__)
mongoport = int(os.environ['MONGOPORT'])
frontport = int(os.environ['FRONTPORT'])
rackname = os.environ['RACKNAME'].upper()
client = MongoClient('localhost', mongoport)
db = client.redfish
collection = db.servers
monitor_collection = db.monitor
udp_collection = db.udp
udp_deleted_collection = db.udpdel

err_list = ['Critical','critical','Error','error','Non-recoverable','non-recoverable','Uncorrectable','uncorrectable','Throttled','Failure','failure','Failed','faile','Processor','processor','Security','security'] # need more key words
IPMIdict = {"#0x09": "| Inlet Temperature"} # add "|" if neccessary

def printf(data):
    print(data, flush=True)

def get_temp_names(bmc_ip):
    dataset_Temps = get_data.find_temperatures_names(bmc_ip)
    cpu_temps = []
    vrm_temps = []
    dimm_temps = []
    sys_temps = []
    for x in range(len(dataset_Temps["Temperatures"])):
        if 'CPU' in dataset_Temps["Temperatures"][x]["Name"]:
            cpu_temps.append(dataset_Temps["Temperatures"][x]["Name"])
        elif 'DIMM' in dataset_Temps["Temperatures"][x]["Name"]:
            dimm_temps.append(dataset_Temps["Temperatures"][x]["Name"])
        elif 'VRM' in dataset_Temps["Temperatures"][x]["Name"]:
            vrm_temps.append(dataset_Temps["Temperatures"][x]["Name"])
        else:
            sys_temps.append(dataset_Temps["Temperatures"][x]["Name"])

    return cpu_temps,vrm_temps,dimm_temps,sys_temps

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

def indexHelper(bmc_ip):
    for i in monitor_collection.find({"BMC_IP": bmc_ip}, {"_id":0, "Event":1}).sort("_id",-1):
        details = i['Event']
        break
    details.reverse() # begin from latest
    bmc_details = []
    for i in range(len(details)):
        cur_detail = details[i]
        for key in IPMIdict.keys():
            if key in cur_detail:
                cur_detail = cur_detail.replace(key,IPMIdict[key])
        bmc_details.append(cur_detail)
    ikvm = get_data.find_ikvm(bmc_ip)
    if details == ['']:
        bmc_event = "OK"
    elif any(w in " ".join(str(x) for x in details) for w in err_list):
        bmc_event = "ERROR"
    else:
        bmc_event = "WARNING"
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    current_auth = ("ADMIN",df_pwd[df_pwd['ip'] == bmc_ip]['pwd'].values[0])
    if os.environ['POWERDISP'] == "ON":
        if powerState(bmc_ip,current_auth) == -1:
            current_state = "D/C"
        elif powerState(bmc_ip,current_auth):
            current_state = "ON"
        else:
            current_state = "OFF"
    else:
        current_state = "N/A"
    if os.environ['UIDDISP'] == "ON":
        uid_state = checkUID(bmc_ip, current_auth)
    else:
        uid_state = "N/A"
    current_flag = read_flag()
    if current_flag == 0:
        monitor_status = "IDLE " + current_state
    elif current_flag == 1:
        monitor_status = "FETCHING " + current_state
    elif current_flag == 2:
        monitor_status = "UPDATING " + current_state
    elif current_flag == 3:
        monitor_status = "REBOOTING " + current_state
    elif current_flag == 4:
        monitor_status = "REBOOT DONE " + current_state
    else:
        monitor_status = "UNKOWN " + current_state   
    for i in monitor_collection.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1}): # get last datetime
        cur_date = i['Datetime']

    

    cpu_temps = get_temp_names(bmc_ip)[0]
    sys_temps = get_temp_names(bmc_ip)[1]
    dimm_temps = get_temp_names(bmc_ip)[2]
    vrm_temps = get_temp_names(bmc_ip)[3]
    sys_fans = get_fan_names(bmc_ip)
    sys_voltages = get_voltage_names(bmc_ip)

    
    return [bmc_event, bmc_details, ikvm, monitor_status, cur_date, uid_state,cpu_temps,sys_temps,dimm_temps,vrm_temps,sys_fans,sys_voltages]

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
    cur = collection.find({},{"BMC_IP":1, "Datetime":1, "UUID":1, "Systems.1.SerialNumber":1, "Systems.1.Model":1, "UpdateService.SmcFirmwareInventory.1.Version": 1, "UpdateService.SmcFirmwareInventory.2.Version": 1, "_id":0})#.limit(50)
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    for i in cur:
        bmc_ip.append(i['BMC_IP'])
        bmcMacAddress.append(i['UUID'][24:])
        serialNumber.append(i['Systems']['1']['SerialNumber'])
        modelNumber.append(i['Systems']['1']['Model'])
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
    

    
    with Pool() as p:
        output = p.map(indexHelper, bmc_ip)
    
    cpu_temps = []
    sys_temps = []
    dimm_temps = []
    vrm_temps = []
    sys_fans = []
    sys_voltages = []
        
    for i in output:
        bmc_event.append(i[0])
        bmc_details.append(i[1])
        ikvm.append(i[2])
        monitorStatus.append(i[3])
        timestamp.append(i[4])
        uidStatus.append(i[5])
        cpu_temps.append(i[6])
        vrm_temps.append(i[7])
        dimm_temps.append(i[8])
        sys_temps.append(i[9])
        sys_fans.append(i[10])
        sys_voltages.append(i[11])
              
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
        data = zip(bmc_ip, bmcMacAddress, modelNumber, serialNumber, biosVersion, bmcVersion, bmc_event, timestamp, bmc_details, ikvm, monitorStatus, pwd, udp_msg, os_ip, mac_list, uidStatus)
    else:
        for i in bmc_ip:
            node_names.append(df_pwd[df_pwd['ip'] == i]['name'].values[0])
            
        if df_pwd['name'].isnull().sum() == len(bmc_ip):
            show_names = 'false'
        
        data = zip(bmc_ip, bmcMacAddress, modelNumber, serialNumber, biosVersion, bmcVersion, bmc_event, timestamp, bmc_details, ikvm, monitorStatus, pwd, udp_msg, os_ip, mac_list, uidStatus,node_names)
  
    cur_time = datetime.datetime.now().strftime("%m/%d/%Y %H:%M:%S")
    time_zone = os.environ['TZ']
    rackobserverurl = 'http://' + get_ip() + ':' +  os.environ['RACKPORT']
    return render_template('index.html', rackname = rackname,show_names = show_names, x=data, rackobserverurl = rackobserverurl,cpu_temps = cpu_temps,sys_temps=sys_temps,dimm_temps=dimm_temps,vrm_temps=vrm_temps,sys_fans=sys_fans,sys_voltages=sys_voltages, cur_time=cur_time, time_zone=time_zone)

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

def getSerialNumberFromFile(ip,opt):
    df_all = pd.read_csv(os.environ['UPLOADPATH'] + os.environ['RACKNAME']+'.csv')
    if opt == 0:
        return(df_all[df_all['OS_IP'] == ip]['System S/N'].values[0])
    elif opt == 1:
        return(df_all[df_all['IPMI_IP'] == ip]['System S/N'].values[0])

def getSerialNumber(ipmiip):
    cur = collection.find_one({"BMC_IP": ipmiip},{"Systems.1.SerialNumber":1})
    if cur != None:
        return(cur['Systems']['1']['SerialNumber'])
    else:
        return("NA")

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/details')
def details():
    ip = request.args.get('var')
    cpu_temps = get_temp_names(ip)[0]
    vrm_temps = get_temp_names(ip)[1]
    dimm_temps = get_temp_names(ip)[2]
    sys_temps = get_temp_names(ip)[3]
    sensor_fans = get_fan_names(ip)
    sensor_voltages = get_voltage_names(ip)

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
    return render_template('details.html', ip=ip, bmc_ip = ip, system=system, cpu=cpu, memory=memory, storage=storage, pcie=pcie,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages)

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
    return render_template('systemresetupload.html',data=zip(allips,indicators))

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
    return render_template('resetresult.html',iplist=iplist ,nreset=nreset, tp1=tp1, tp2=tp2, tspend=tspend, result=result)
    

@app.route('/systembootup')
def systembootup():
    filepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "resetip.txt"
    if fileEmpty(filepath):
        return render_template('error.html',error="No input IP found!")
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
        return render_template('error.html',error="No input IP found!")
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
        systemRebootTesting(IPMI,auth,"GracefulShutdown")
    return redirect(url_for('systemresetupload'))

@app.route('/systemreset')
def systemreset():
    filepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "resetip.txt"
    if fileEmpty(filepath):
        return render_template('error.html',error="No input IP found!")
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
        systemRebootTesting(IPMI,auth,"GracefulRestart")
    return redirect(url_for('systemresetupload'))


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
    return render_template('systemresetstatus.html',data=data)



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
    return render_template('biosupload.html',ip_list = getIPlist())

@app.route('/biosupdate',methods=["GET","POST"])
def biosupdate():
    ip = request.args.get('var')
    return render_template('biosupdate.html',ip=ip)

@app.route('/biosupdaterack',methods=["GET","POST"])
def biosupdaterack():
    return render_template('biosupdaterack.html',numOfNodes=len(getIPlist()))

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
        return render_template('biosupdateresult.html', ips = ip_nocomplete, me = str(me), nvram = str(nvram), smbios = str(smbios), tspend = tspend, completion = "Not Completed!")
    os.remove(fuopath)
    return render_template('biosupdateresult.html', ips = list(df_pwd['ip']), me = str(me), nvram = str(nvram), smbios = str(smbios), tspend = tspend, completion = "Completed!")

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
            return render_template('biosupdateresult.html', ips = [IPMI + " Not Completed!!"], me = str(StrToBool(me)), nvram = str(StrToBool(nvram)), smbios = str(StrToBool(smbios)), tspend = tspend, completion = "Not Completed!")
        biosflag = BiosUploadingFile(IPMI,biosfile,auth)
        if biosflag != None:
            CancelBiosUpdate(IPMI,auth)
            bftime = time.time()
            tspend = str(int(bftime - bstime)) + " secs"
            insert_flag(0) # updating ended
            return render_template('biosupdateresult.html', ips = [IPMI + " Not Completed!!"], me = str(StrToBool(me)), nvram = str(StrToBool(nvram)), smbios = str(StrToBool(smbios)), tspend = tspend, completion = "Not Completed!")
        biosflag = BiosStartUpdating(IPMI,auth,StrToBool(me),StrToBool(nvram),StrToBool(smbios))
        if biosflag != None:
            CancelBiosUpdate(IPMI,auth)
            bftime = time.time()
            tspend = str(int(bftime - bstime)) + " secs"
            insert_flag(0) # updating ended
            return render_template('biosupdateresult.html', ips = [IPMI + " Not Completed!!"], me = str(StrToBool(me)), nvram = str(StrToBool(nvram)), smbios = str(StrToBool(smbios)), tspend = tspend, completion = "Not Completed!")
        systemRebootTesting(IPMI,auth,"GracefulRestart")
        time.sleep(3)
        insert_flag(0) # updating ended
        bftime = time.time()
        tspend = str(int(bftime - bstime)) + " secs"
    os.remove(fuopath)
    return render_template('biosupdateresult.html', ips = [IPMI], me = str(StrToBool(me)), nvram = str(StrToBool(nvram)), smbios = str(StrToBool(smbios)), tspend = tspend, completion = "Completed")


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
    return render_template('bmcupload.html',ip_list = getIPlist())

@app.route('/bmcupdaterack',methods=["GET","POST"])
def bmcupdaterack():
    ip = str(request.args.get('var'))
    if ip == "ALL":
        ipstr = ",".join(str(x) for x in getIPlist())
        return render_template('bmcupdaterack.html',ip = ipstr,numOfNodes=len(getIPlist()) )
    else:
        return render_template('bmcupdaterack.html',ip = ip,numOfNodes=1 )

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
        return render_template('firmupdateresult.html', ips = ip_nocomplete, cfg = str(cfg), sdr = str(sdr), ssl = str(ssl), tspend = tspend, completion = "Not Completed!")
    with open(fuopath, 'a') as rprint:
        rprint.write(time.asctime() + ": Checking BMC status.\n")
    for ip, pwd in zip(list(df_pwd['ip']),list(df_pwd['pwd'])):
        while redfishReadyCheck("https://"+ip,("ADMIN",pwd)) != 0:
            time.sleep(5)
    os.remove(fuopath)
    insert_flag(0)
    return render_template('firmupdateresult.html', ips = ip_list, cfg = str(cfg), sdr = str(sdr), ssl = str(ssl), tspend = tspend, completion = "Completed")


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
    return render_template('firmwareupdatestatus.html',data=data)

@app.route('/bmceventcleanerupload',methods=["GET","POST"])
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
    if request.method == "POST":
        if request.files:
            bmcipfile = request.files["file"]
            if bmcipfile.filename == "":
                printf("Input file must have a filename")
                return redirect(url_for('bmceventcleanerupload'))
            bmcipfile.save(savepath+"bmceventcleanerip.txt")
            printf("{} has been saved as bmceventcleanerip.txt".format(bmcipfile.filename))
            return redirect(url_for('bmceventcleanerupload'))
    return render_template('bmceventcleanerupload.html',data=zip(allips,indicators))

@app.route('/bmceventcleanerstart',methods=["GET","POST"])
def bmceventcleanerstart():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    if request.method == "POST":
        if fileEmpty(savepath+"bmceventcleanerip.txt"):
            return render_template('error.html',error="No input IP found!")
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
                return render_template('error.html',error="Assigned ip " + iplist[i] + " not belongs current rack!")
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
        return render_template('simpleresult.html',messages=messages)

@app.route('/ipmitoolcommandlineupload',methods=["GET","POST"])
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
    if request.method == "POST":
        if request.files:
            ipmitoolipfile = request.files["file"]
            if ipmitoolipfile.filename == "":
                printf("Input file must have a filename")
                return redirect(url_for('ipmitoolcommandlineupload'))
            ipmitoolipfile.save(savepath + "ipmitoolip.txt")
            printf("{} has been saved as ipmitoolip.txt".format(ipmitoolipfile.filename))
            return redirect(url_for('ipmitoolcommandlineupload'))   
    return render_template('ipmitoolcommandlineupload.html',data = zip(allips, indicators))

@app.route('/ipmitoolstart',methods=["GET","POST"])
def ipmitoolstart():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    if request.method == "POST":
        if fileEmpty(savepath+"ipmitoolip.txt"):
            return render_template('error.html',error="No input IP found!")
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
                return render_template('error.html',error="Assigned ip " + iplist[i] + " not belongs current rack!")
            else:
                data.append([])
                data[i].append(iplist[i])
                data[i].append(df_pwd[df_pwd['ip'] == iplist[i]]['pwd'].values[0])
                data[i].append(request.form['ipmicmd'])
        #with Pool() as p:
        #    ipmioutput = p.map(ipmistartone, data)
        ipmistdout = []
        ipmistderr = []
        for i in range(len(data)):
            ipmistdout.append(ipmistartone(data[i])[0])
            ipmistderr.append(ipmistartone(data[i])[1])
        #os.remove(savepath+"ipmitoolip.txt")
        return render_template('ipmitoolcommandlineoutput.html', ipmistdout = ipmistdout, ipmistderr = ipmistderr)

def ipmistartone(data_list):
    ip = data_list[0]
    pwd = data_list[1]
    ipmicmd = data_list[2]
    process = Popen('ipmitool ' + ' -H ' +  ip + ' -U ' + 'ADMIN' + ' -P ' + pwd + ' ' + ipmicmd, shell=True, stdout=PIPE, stderr=PIPE)
    stdout, stderr = process.communicate()
    out = ["["+ip+"] start here!!"]
    err = ["["+ip+"] start here!!"]
    out += stdout.decode("utf-8").split('\n')
    out.append("["+ip+"] end here!!")
    err += stderr.decode("utf-8").split('\n')
    err.append("["+ip+"] end here!!")
    return([out,err])

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
        
@app.route('/sumlogpage',methods=['GET', 'POST'])
def sumlogpage():
    sumlogout = sumLogOutput()
    if sumlogout == 1:
        return render_template("sumLog.html", sumloglines = ['SUM is not running!!'])
    elif sumlogout == 1:
        return render_template("sumLog.html", sumloglines = ['Multiple SUM processes are detected, no output can display!!'])
    sumloglines = ["SUM is running!!"]
    with open(sumlogout, "r") as sumlogfile:
        for line in sumlogfile:
            line = line.strip()
            sumloglines.append(line)
    return render_template("sumLog.html", sumloglines = sumloglines)
        
@app.route('/sumtoolboxupload',methods=['GET', 'POST'])
def sumtoolboxupload():
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
    if request.method == "POST":
        if request.files:
            suminputipfile = request.files["file"]
            if suminputipfile.filename == "":
                printf("Input file must have a filename")
                return redirect(url_for('sumtoolboxupload'))
            suminputipfile.save(savepath + "suminput.txt")
            printf("{} has been saved as suminput.txt".format(suminputipfile.filename))
            return redirect(url_for('sumtoolboxupload'))   
    return render_template('sumtoolboxupload.html',data = zip(allips, indicators))

@app.route('/sumbioscompoutput',methods=['GET', 'POST'])
def sumbioscompoutput():
    if fileEmpty(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt"):
        return render_template('error.html',error="No input IP found!")
    makeSumExcutable()
    sumGetBiosSettings(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt")
    sum_bioscomp = sumCompBiosSettings()['compResult']
    #sumRemoveFiles('htmlBios')
    return render_template('sumbioscompoutput.html', sum_bioscomp = sum_bioscomp)

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
        return render_template('error.html',error="No input IP found!")
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
        return render_template('error.html',error="No input IP found!")
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
    if request.method == "POST":
        if request.files:
            sumbiosfile = request.files["biosimage"]
            if sumbiosfile.filename == "":
                printf("Input file must have a filename")
                return redirect(url_for('sumtoolboxupload'))
            sumbiosfile.save(savepath + "bios.222")
            return redirect(url_for('sumtoolboxupload'))
    return redirect(url_for('sumtoolboxupload')) 

@app.route('/sumbiosupdateoutput',methods=['GET', 'POST'])
def sumbiosupdateoutput():
    if fileEmpty(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt"):
        return render_template('error.html',error="No input IP found!")
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
    return render_template('simpleresult.html', messages = messages)

@app.route('/sumbmcimageupload',methods=['GET', 'POST'])
def sumbmcimageupload():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    if request.method == "POST":
        if request.files:
            sumbmcfile = request.files["bmcimage"]
            if sumbmcfile.filename == "":
                printf("Input file must have a filename")
                return redirect(url_for('sumtoolboxupload'))
            sumbmcfile.save(savepath + "bmc.bin")
            return redirect(url_for('sumtoolboxupload'))
    return redirect(url_for('sumtoolboxupload')) 

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
    return render_template('simpleresult.html', messages = messages)

@app.route('/sumbiossettingsupload',methods=['GET', 'POST'])
def sumbiossettingsupload():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    if request.method == "POST":
        if request.files:
            biossettingsfile = request.files["biossettings"]
            if biossettingsfile.filename == "":
                printf("Input file must have a filename")
                return redirect(url_for('sumtoolboxupload'))
            biossettingsfile.save(savepath + "biossettings.html")
            return redirect(url_for('sumtoolboxupload'))
    return redirect(url_for('sumtoolboxupload')) 

@app.route('/sumbiossettingschangeoutput',methods=['GET', 'POST'])
def sumbiossettingschangeoutput():
    if fileEmpty(os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + "suminput.txt"):
        return render_template('error.html',error="No input IP found!")
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
    return render_template('simpleresult.html', messages = messages)
     
@app.route('/bioscomparisonoutput')
def bioscomparisonoutput():
    df_path = os.environ['OUTPUTPATH']
    while not os.path.exists(df_path):
        time.sleep(1)
    df_auth = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    data_bioscomp = compareBiosSettings(df_auth)['compResult']
    return render_template('bioscomparisonoutput.html', data_bioscomp = data_bioscomp)

@app.route('/bootorderoutput')
def bootorderoutput():
    df_path = os.environ['OUTPUTPATH']
    while not os.path.exists(df_path):
        time.sleep(1)
    df_auth = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    df_bootorder = bootOrderOutput(df_auth)
    df_bootorder.to_excel(os.environ['BOOTORDERPATH'],index=None)
    while not os.path.isfile(os.environ['BOOTORDERPATH']):
        time.sleep(1)
    return send_file(os.environ['BOOTORDERPATH'], as_attachment=False, cache_timeout=0)

@app.route('/pwdoutput')
def pwdoutput():
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    df_pwd['user'] = ['ADMIN'] * len(df_pwd)
    new_path = os.environ['OUTPUTPATH'].replace(".txt","auth.txt")
    df_pwd[['ip','user','pwd']].to_csv(new_path,header=None,index=None,sep=' ')
    return send_file(new_path, as_attachment=True, cache_timeout=0)

@app.route('/event')
def event():
    ip = request.args.get('var')
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
    pwd = df_pwd.loc[df_pwd['ip'] == ip,'pwd'].iloc[0]
    date_time = get_data.get_time(ip,pwd)
    for i in monitor_collection.find({"BMC_IP": ip}, {"_id":0, "Event":1}).sort("_id",-1):
        events = i['Event']
        break
    for i in range(len(events)):
        for key in IPMIdict.keys():
            if key in events[i]:
                events[i] = events[i].replace(key,IPMIdict[key]) + " | Note the error number '" + key + "' has been replaced by '" + IPMIdict[key] + "'!"
    return render_template('event.html', date_time=date_time, data=events)

@app.route('/udpserverupload',methods=["GET","POST"])
def udpserverupload():
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
    if request.method == "POST":
        if request.files:
            udpipfile = request.files["file"]
            if udpipfile.filename == "":
                printf("Input file must have a filename")
                return redirect(url_for('udpserverupload'))
            udpipfile.save(savepath+"udpserveruploadip.txt")
            printf("{} has been saved as udpserveruploadip.txt".format(udpipfile.filename))
            return redirect(url_for('udpserverupload'))
    return render_template('udpserverupload.html',data=zip(allips,indicators))
    
@app.route('/udpserversendfileandrun',methods=["GET","POST"])
def udpserversendfileandrun():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    cleanIP(savepath + "udpserveruploadip.txt")
    printf("INPUTFILE EMPTY: " + str(fileEmpty(savepath + "udpserveruploadip.txt")))
    if fileEmpty(savepath + "udpserveruploadip.txt"):
        return render_template('error.html',error="No input IP found!")
    if request.method == "POST":
        if request.files:
            udpinputfile = request.files["inputfile"]
            if udpinputfile.filename == "":
                printf("Input file must have a filename")
                return redirect(url_for('udpserverupload'))
            udpinputfile.save(savepath+"udpinput.json")
            printf("{} has been saved as udpinput.json".format(udpinputfile.filename))
            # insert flag to run benchmark       
            insertUdpevent('f',savepath+"udpinput.json",savepath+"udpserveruploadip.txt")
            messages = []
            messages.append("Benchmark will be started in a few secs.")
            messages.append("Please do not submit any benchmarks while it's running.")
            return render_template('simpleresult.html',messages=messages)

@app.route('/udpserveruploadinputfile',methods=["GET","POST"])
def udpserveruploadinputfile():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    cleanIP(savepath + "udpserveruploadip.txt")
    printf("INPUTFILE EMPTY: " + str(fileEmpty(savepath + "udpserveruploadip.txt")))
    if fileEmpty(savepath + "udpserveruploadip.txt"):
        return render_template('error.html',error="No input IP found!")
    if request.method == "POST":
        if request.files:
            udpinputfile = request.files["bminputfile"]
            if udpinputfile.filename == "":
                printf("Input file must have a filename")
                return redirect(url_for('udpserverupload'))
            udpinputfile.save(os.environ['UPLOADPATH'] + udpinputfile.filename)
            printf("{} has been saved".format(udpinputfile.filename))
            # insert flag to run benchmark       
            insertUdpevent('f',os.environ['UPLOADPATH'] + udpinputfile.filename,savepath+"udpserveruploadip.txt")
            messages = []
            messages.append("Benchmark input files have been uploaded.")
            messages.append("Please back to the udp server page to run the benchmark.")
            return render_template('simpleresult.html',messages=messages)

@app.route('/udpservercheckonline',methods=["GET","POST"])
def udpservercheckonline():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    cleanIP(savepath + "udpserveruploadip.txt")
    printf("INPUTFILE EMPTY: " + str(fileEmpty(savepath + "udpserveruploadip.txt")))
    if fileEmpty(savepath + "udpserveruploadip.txt"):
        return render_template('error.html',error="No input IP found!")
    if request.method == "POST":
        insertUdpevent('m',"ONLINE",savepath+"udpserveruploadip.txt")
        time.sleep(1)
        return redirect(url_for('udpserverupload'))

@app.route('/udpserverinitialize',methods=["GET","POST"])
def udpserverinitialize():
    savepath = os.environ['UPLOADPATH'] + os.environ['RACKNAME']
    cleanIP(savepath + "udpserveruploadip.txt")
    printf("INPUTFILE EMPTY: " + str(fileEmpty(savepath + "udpserveruploadip.txt")))
    if fileEmpty(savepath + "udpserveruploadip.txt"):
        return render_template('error.html',error="No input IP found!")
    if request.method == "POST":
        insertUdpevent('m',"request_h",savepath+"udpserveruploadip.txt")
        time.sleep(1)
        messages = []
        messages.append("Initilize message has been sent to clients.")
        messages.append("You can check the status on index page.")
        messages.append("If the system still has not been initialized, please make sure:")
        messages.append("1. Connections bettween server and clients.")
        messages.append("2. MACNAME in env file is correct.")
        messages.append("3. UDP Clients are running.")
        messages.append("4. System firewall has been disabled and stopped.")
        return render_template('simpleresult.html',messages=messages)

@app.route('/udpoutput')
def udpoutput():
    star, os_ip,start_date,done_date,cmd,content,content_size,benchmark,config,result,id,file_name,conclusion= [],[],[],[],[],[],[],[],[],[],[],[],[]
    benchmark_data = list(udp_collection.find({}))
    for i in benchmark_data:
        star.append(i['star'])
        os_ip.append(i['os_ip'])
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
    return render_template('udpoutput.html',data=zip(star, os_ip, start_date, done_date, cmd, benchmark, content_size, result, id, file_name,conclusion))

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
    try:
        backup = list(udp_collection.find({'_id':ObjectId(data)}))[0]
        # unstar the obj before move to the dustbin
        backup['star'] = -1
        udp_deleted_collection.insert(backup)
        udp_collection.find_one_and_delete({'_id':ObjectId(data)},{})
    except Exception as e:
        return render_template('error.html',error=e)
    return redirect(url_for('udpoutput'))

@app.route('/udpstarobject')
def udpstarobject():
    data = request.args.get('var')
    try:        
        set_value = list(udp_collection.find({'_id':ObjectId(data)}))[0]['star'] * -1 # change the star to unstar or change the unstar to star
        os_ip = list(udp_collection.find({'_id':ObjectId(data)}))[0]['os_ip']
        benchmark = list(udp_collection.find({'_id':ObjectId(data)}))[0]['benchmark']
        # each os_ip and benchmark should only has one stared!
        if set_value == 1:
            for cur_obj in list(udp_collection.find({'os_ip':os_ip, 'benchmark':benchmark})):
                udp_collection.find_one_and_update({'_id':cur_obj['_id']},{'$set':{'star':-1}})
        udp_collection.find_one_and_update({'_id':ObjectId(data)},{'$set':{'star':set_value}})        
    except Exception as e:
        return render_template('error.html',error=e)
    return redirect(url_for('udpoutput'))

@app.route('/udpunstarallobject')
def udpunstarallobject():
    try:
        for i in range(len(list(udp_collection.find({})))):
            udp_collection.find_one_and_update({'star':1},{'$set':{'star':-1}})        
    except Exception as e:
        return render_template('error.html',error=e)
    return redirect(url_for('udpoutput'))

@app.route('/udpunstarfailedobject')
def udpunstarfailedobject():
    try:
        for i in range(len(list(udp_collection.find({})))):
            udp_collection.find_one_and_update({'star':1,'conclusion':'FAILED'},{'$set':{'star':-1}})        
    except Exception as e:
        return render_template('error.html',error=e)
    return redirect(url_for('udpoutput'))

@app.route('/udpunautostar')
def udpautostar():
    try:
        # unstar all
        for i in range(len(list(udp_collection.find({})))):
            udp_collection.find_one_and_update({'star':1},{'$set':{'star':-1}})
        # find best results, non-float/non-int results will be treat as one
        obj_autostar = {}
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
        # star the latest results
        for bm in obj_autostar.keys():
            for ip in obj_autostar[bm].keys():
                udp_collection.find_one_and_update({'_id':obj_autostar[bm][ip][1]},{'$set':{'star':1}})      
    except Exception as e:
        return render_template('error.html',error=e)
    return redirect(url_for('udpoutput'))    

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
    return render_template('simpleresult.html',messages=messages)

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

    
#################################################################################### Function to add functionality for nav bar drop down.
    
    cpu_temps = get_temp_names(bmc_ip)[0]
    vrm_temps = get_temp_names(bmc_ip)[1]
    dimm_temps = get_temp_names(bmc_ip)[2]
    sys_temps = get_temp_names(bmc_ip)[3]
    sensor_fans = get_fan_names(bmc_ip)
    sensor_voltages = get_voltage_names(bmc_ip)

################################################################################
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
    
    return render_template('imageOutput.html',chart_headers = chart_headers, sensor_voltages = sensor_voltages, cpu_temps = cpu_temps, sys_temps=sys_temps, vrm_temps = vrm_temps, dimm_temps = dimm_temps, sensor_fans = sensor_fans, data = zip(sensorNames, min_vals,min_dates,max_vals,max_dates, avg_vals, good_count, zero_count), imagepath="../static/images/" + imagepath,imageheight=imageheight,bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "min_max_temperatures")

@app.route('/min_max_voltages/<bmc_ip>')
def min_max_voltages(bmc_ip):
    messages, max_vals, min_vals, max_dates, min_dates, sensorNames, avg_vals, count_vals, elapsed_hour, good_count, zero_count, last_date = get_data.find_min_max(bmc_ip,"Voltages", "ReadingVolts", 1000)
    return render_template('simpleresult.html',messages=messages)

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
#################################################################################### Function to add functionality for nav bar drop down.
    cpu_temps = get_temp_names(bmc_ip)[0]
    vrm_temps = get_temp_names(bmc_ip)[1]
    dimm_temps = get_temp_names(bmc_ip)[2]
    sys_temps = get_temp_names(bmc_ip)[3]
    sensor_fans = get_fan_names(bmc_ip)
    sensor_voltages = get_voltage_names(bmc_ip)

################################################################################
    return render_template('imageOutput.html',chart_headers = chart_headers, sensor_voltages = sensor_voltages, cpu_temps = cpu_temps, sys_temps=sys_temps, vrm_temps = vrm_temps, dimm_temps = dimm_temps, sensor_fans = sensor_fans, data = zip(sensorNames, min_vals,min_dates,max_vals,max_dates, avg_vals, good_count, zero_count),imagepath="../static/images/" + imagepath,imageheight=imageheight,bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "min_max_voltages")

@app.route('/min_max_fans/<bmc_ip>')
def min_max_fans(bmc_ip):
    messages, max_vals, min_vals, max_dates, min_dates, sensorNames, avg_vals, count_vals, elapsed_hour, good_count, zero_count, last_date = get_data.find_min_max(bmc_ip,"Fans", "Reading", 999999)
    return render_template('simpleresult.html',messages=messages)

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
 #################################################################################### Function to add functionality for nav bar drop down.
    cpu_temps = get_temp_names(bmc_ip)[0]
    vrm_temps = get_temp_names(bmc_ip)[1]
    dimm_temps = get_temp_names(bmc_ip)[2]
    sys_temps = get_temp_names(bmc_ip)[3]
    sensor_fans = get_fan_names(bmc_ip)
    sensor_voltages = get_voltage_names(bmc_ip)

################################################################################   
    return render_template('imageOutput.html',chart_headers = chart_headers, sensor_voltages = sensor_voltages, cpu_temps = cpu_temps, sys_temps=sys_temps, vrm_temps = vrm_temps, dimm_temps = dimm_temps, sensor_fans = sensor_fans, data = zip(sensorNames, min_vals,min_dates,max_vals,max_dates,avg_vals,good_count,zero_count),imagepath="../static/images/" + imagepath,imageheight=imageheight,bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "min_max_fans")


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
    cpu_temps = get_temp_names(bmc_ip)[0]
    vrm_temps = get_temp_names(bmc_ip)[1]
    dimm_temps = get_temp_names(bmc_ip)[2]
    sys_temps = get_temp_names(bmc_ip)[3]
    sensor_fans = get_fan_names(bmc_ip)
    sensor_voltages = get_voltage_names(bmc_ip)
    while not os.path.isfile("/app/static/images/" + imagepath):
        time.sleep(1)
    return render_template('imageOutput.html',chart_headers = chart_headers, sensor_voltages = sensor_voltages, cpu_temps = cpu_temps, sys_temps=sys_temps, vrm_temps = vrm_temps, dimm_temps = dimm_temps, sensor_fans = sensor_fans, data = zip(sensorNames, min_vals,min_dates,max_vals,max_dates,avg_vals,good_count,zero_count),imagepath="../static/images/" + imagepath,imageheight=imageheight,bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "min_max_power")

@app.route('/min_max_alltemperatures_chart')
def min_max_alltemperatures_chart():
    ip_list = getIPlist()
    sn_list = []
    for ip in ip_list:
        sn_list.append(getSerialNumber(ip))   
    sensor_id = request.args.get('var')
    sensor_id = str(sensor_id)
    max_vals, min_vals, max_dates, min_dates, avg_vals, all_count,  elapsed_hour, good_count, zero_count, last_date, sensor_name = get_data.find_min_max_rack(sensor_id, "Temperatures", "ReadingCelsius", 9999, ip_list)
    chart_headers = ['Rack Name: ' + rackname, 'Sensor Name: ' + sensor_name,'Elapsed Time: ' + elapsed_hour + ' hours', 'Last Timestamp: ' + last_date, 'Value Counts: ' + str(all_count), 'Extreme Sensor Readings: (Light Blue: Min, Green: Max)']
    df_max = pd.DataFrame({"Temperature (Celsius)":max_vals, "BMC IPs": ip_list})
    df_min = pd.DataFrame({"Temperature (Celsius)":min_vals, "BMC IPs": ip_list})
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
    return render_template('imageOutputRack.html', sensor = sensor,chart_headers = chart_headers ,data = zip(ip_list, sn_list, min_vals,min_dates,max_vals,max_dates, avg_vals, good_count, zero_count),imagepath="../static/images/" + imagepath,imageheight=imageheight)

@app.route('/min_max_allpower_chart')
def min_max_allpower_chart():
    ip_list = getIPlist()
    sn_list = []
    for ip in ip_list:
        sn_list.append(getSerialNumber(ip))   
    sensor_id = request.args.get('var')
    sensor_id = str(sensor_id)
    max_vals, min_vals, max_dates, min_dates, avg_vals, all_count, elapsed_hour, good_count, zero_count, last_date, sensor_name = get_data.find_min_max_rack(sensor_id,"PowerControl", "PowerConsumedWatts", 9999, ip_list)
    chart_headers = ['Rack Name: ' + rackname, 'Sensor Name: ' + sensor_name,'Elapsed Time: ' + elapsed_hour + ' hours', 'Last Timestamp: ' + last_date, 'Value Counts: ' + str(all_count), 'Extreme Sensor Readings: (Light Blue: Min, Green: Max)']
    df_max = pd.DataFrame({"Power Consumption (W)":max_vals, "BMC IPs": ip_list})
    df_min = pd.DataFrame({"Power Consumption (W)":min_vals, "BMC IPs": ip_list})
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
    return render_template('imageOutputRack.html',chart_headers = chart_headers ,sensor = sensor, data = zip(ip_list, sn_list, min_vals,min_dates,max_vals,max_dates, avg_vals, good_count, zero_count),imagepath="../static/images/" + imagepath,imageheight=imageheight)


@app.route('/chart_powercontrol/<bmc_ip>')
def chart_powercontrol(bmc_ip):
    cpu_temps = get_temp_names(bmc_ip)[0]
    vrm_temps = get_temp_names(bmc_ip)[1]
    dimm_temps = get_temp_names(bmc_ip)[2]
    sys_temps = get_temp_names(bmc_ip)[3]
    sensor_fans = get_fan_names(bmc_ip)
    sensor_voltages = get_voltage_names(bmc_ip)

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


    data = get_data.find_powercontrol(bmc_ip)
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        return render_template('chart_powercontrol.html', reading= reading, title='Power Control', dataset=data,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_powercontrol")
    else:
        name = request.args.get('name')
        return render_template('chart_powercontrol.html',reading = reading,title='Power Control',cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages,name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_powercontrol")

@app.route('/chart_voltages/<bmc_ip>')
def chart_voltages(bmc_ip):
    cpu_temps = get_temp_names(bmc_ip)[0]
    vrm_temps = get_temp_names(bmc_ip)[1]
    dimm_temps = get_temp_names(bmc_ip)[2]
    sys_temps = get_temp_names(bmc_ip)[3]
    sensor_fans = get_fan_names(bmc_ip)
    sensor_voltages = get_voltage_names(bmc_ip)
    data = get_data.find_voltages(bmc_ip)
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        return render_template('chart_voltages.html', title='Voltages', dataset=data,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_voltages")

    else:
        name = request.args.get('name')
        return render_template('chart_voltages.html', title='Voltages',cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_voltages")
   

@app.route('/chart_powersuppliesvoltage/<bmc_ip>')
def chart_powersuppliesvoltage(bmc_ip):
    cpu_temps = get_temp_names(bmc_ip)[0]
    vrm_temps = get_temp_names(bmc_ip)[1]
    dimm_temps = get_temp_names(bmc_ip)[2]
    sys_temps = get_temp_names(bmc_ip)[3]
    sensor_fans = get_fan_names(bmc_ip)
    sensor_voltages = get_voltage_names(bmc_ip)
    data = get_data.find_powersupplies(bmc_ip)
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        return render_template('chart_powersuppliesvoltage.html', title='Power Supplies Voltage', dataset=data,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_powersuppliesvoltage")
    else:
        name = request.args.get('name')
        return render_template('chart_powersuppliesvoltage.html', title='Power Supplies Voltage',cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages,name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_powersuppliesvoltage")

@app.route('/chart_powersuppliespower/<bmc_ip>')
def chart_powersuppliespower(bmc_ip):
    cpu_temps = get_temp_names(bmc_ip)[0]
    vrm_temps = get_temp_names(bmc_ip)[1]
    dimm_temps = get_temp_names(bmc_ip)[2]
    sys_temps = get_temp_names(bmc_ip)[3]
    sensor_fans = get_fan_names(bmc_ip)
    sensor_voltages = get_voltage_names(bmc_ip)
    data = get_data.find_powersupplies(bmc_ip)
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        return render_template('chart_powersuppliespower.html', title='Power Supplies Power', dataset=data,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_powersuppliespower")

    else:
        name = request.args.get('name')
        return render_template('chart_powersuppliespower.html', title='Power Supplies Power', cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_powersuppliespower")
   
@app.route('/chart_allpowercontrols')
def chart_allpowercontrols():
    ip_list = getIPlist()
    data = get_data.find_allpowercontrols(ip_list)
    return render_template('chart_allpowercontrols.html', title='All Power Controls', dataset=data, chart_name = "chart_allpowercontrols")

@app.route('/chart_alltemperatures')
def chart_alltemperatures():
    ip_list = getIPlist()
    sensor_id = request.args.get('var')
    sensor_id = str(sensor_id)
    data = get_data.find_alltemperatures(ip_list, sensor_id)
    sensor_name = list(data.keys())[-1]
    return render_template('chart_alltemperatures.html', title='All Temperature ' + sensor_name, dataset=data, sensor_name=sensor_name, chart_name = "chart_alltemperatures")

@app.route('/chart_allfans')
def chart_allfans():
    ip_list = getIPlist()
    sensor_id = request.args.get('var')
    sensor_id = str(sensor_id)
    data = get_data.find_allfans(ip_list, sensor_id)
    sensor_name = list(data.keys())[-1]
    return render_template('chart_allfans.html', title='All Fans ' + sensor_name, dataset=data, sensor_name=sensor_name, chart_name = "chart_allfans")     

@app.route('/chart_fans/<bmc_ip>')
def chart_fans(bmc_ip):
    cpu_temps = get_temp_names(bmc_ip)[0]
    vrm_temps = get_temp_names(bmc_ip)[1]
    dimm_temps = get_temp_names(bmc_ip)[2]
    sys_temps = get_temp_names(bmc_ip)[3]
    sensor_fans = get_fan_names(bmc_ip)
    sensor_voltages = get_voltage_names(bmc_ip)
    data = get_data.find_fans(bmc_ip)
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')    
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        return render_template('chart_fans.html', title='Fans', dataset=data, skip = skip,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_fans")

    else:
        name = request.args.get('name')
        return render_template('chart_fans.html', title='Fans',cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_fans")


@app.route('/chart_cputemperatures/<bmc_ip>')
def chart_cputemperatures(bmc_ip):
      #Format 2021-07-01 22:22:28
    cpu_temps = get_temp_names(bmc_ip)[0]
    vrm_temps = get_temp_names(bmc_ip)[1]
    dimm_temps = get_temp_names(bmc_ip)[2]
    sys_temps = get_temp_names(bmc_ip)[3]
    sensor_fans = get_fan_names(bmc_ip)
    sensor_voltages = get_voltage_names(bmc_ip)
    data = get_data.find_temperatures(bmc_ip)
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        return render_template('chart_cputemperatures.html', title='CPU Temperatures',cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min , t_max = t_max ,t_min_max = t_min_max, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_cputemperatures")
    else:
        name = request.args.get('name')
        return render_template('chart_cputemperatures.html', title='CPU Temperatures',cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_cputemperatures")
    #Format 2021-07-01 22:22:28


"""
@app.route('/chart_systemtemperatures/<bmc_ip>')
def chart_systemtemperatures(bmc_ip):
    data = get_data.find_temperatures(bmc_ip)
    return render_template('chart_systemtemperatures.html', title='System Temperatures', dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist())
"""

@app.route('/chart_vrmtemperatures/<bmc_ip>')
def chart_vrmtemperatures(bmc_ip):
    data = get_data.find_temperatures(bmc_ip)
    cpu_temps = get_temp_names(bmc_ip)[0]
    vrm_temps = get_temp_names(bmc_ip)[1]
    dimm_temps = get_temp_names(bmc_ip)[2]
    sys_temps = get_temp_names(bmc_ip)[3]
    sensor_fans = get_fan_names(bmc_ip)
    sensor_voltages = get_voltage_names(bmc_ip)
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        return render_template('chart_vrmtemperatures.html', title='VRM Temperatures', dataset=data,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_vrmtemperatures")
    else:
        name = request.args.get('name')
        return render_template('chart_vrmtemperatures.html', title='VRM Temperatures',cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_vrmtemperatures")     


@app.route('/chart_dimmctemperatures/<bmc_ip>')
def chart_dimmctemperatures(bmc_ip):
    data = get_data.find_temperatures(bmc_ip)
    cpu_temps = get_temp_names(bmc_ip)[0]
    vrm_temps = get_temp_names(bmc_ip)[1]
    dimm_temps = get_temp_names(bmc_ip)[2]
    sys_temps = get_temp_names(bmc_ip)[3]
    sensor_fans = get_fan_names(bmc_ip)
    sensor_voltages = get_voltage_names(bmc_ip)
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        return render_template('chart_dimmctemperatures.html', title='DIMMC Temperatures', dataset=data,cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_dimmctemperatures")

    else:
        name = request.args.get('name')
        return render_template('chart_dimmctemperatures.html', title='DIMMC Temperatures', cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_dimmctemperatures")

@app.route('/chart_othertemperatures/<bmc_ip>')
def chart_othertemperatures(bmc_ip):
    data = get_data.find_temperatures(bmc_ip)
    cpu_temps = get_temp_names(bmc_ip)[0]
    vrm_temps = get_temp_names(bmc_ip)[1]
    dimm_temps = get_temp_names(bmc_ip)[2]
    sys_temps = get_temp_names(bmc_ip)[3]
    sensor_fans = get_fan_names(bmc_ip)
    sensor_voltages = get_voltage_names(bmc_ip)
    if "t=" in request.url:
        t_min_max = request.args.get('t')
        name = request.args.get('name')
        date_time_obj = datetime.datetime.strptime(t_min_max, "%Y-%m-%d %H:%M:%S")
        t_min = (date_time_obj - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        t_max = (date_time_obj + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        skip = "no"
        return render_template('chart_othertemperatures.html', title='Other Temperatures',cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, skip = skip, t_min = t_min, t_max = t_max, t_min_max = t_min_max, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_othertemperatures")

    else:
        name = request.args.get('name')
        return render_template('chart_othertemperatures.html', title='Other Temperatures',cpu_temps=cpu_temps,vrm_temps=vrm_temps,dimm_temps=dimm_temps,sys_temps=sys_temps,sensor_fans=sensor_fans,sensor_voltages=sensor_voltages, name = name, dataset=data, bmc_ip = bmc_ip, ip_list = getIPlist(), chart_name = "chart_othertemperatures")

@app.errorhandler(404)
def page_not_found(e):
    # note that we set the 404 status explicitly!!
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(e):
    # note that we set the 500 status explicitly!!
    return render_template('500.html'), 500

@app.route('/howToDeploy')
def howToDeploy():
    return send_file("/app/templates/Manual.pdf",cache_timeout=0)

@app.route('/developmentnote08182020')
def developmentnote08182020():
    return send_file("/app/templates/DevelopmentNote.pdf",cache_timeout=0)

@app.route('/developmentnote04152021')
def developmentnote04152021():
    return send_file("/app/templates/DevelopmentNoteV2.pdf",cache_timeout=0)

### Report Generation ###
@app.route('/downloadClusterReport')
def downloadClusterReport():
    os.system("chmod +wx cluster_report.py")
    try:
        os.remove("cluster_report.pdf")
    except Exception as e:
        print(e)
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
    printf("Frontend port number is " + str(frontport))
    app.run(host='0.0.0.0',port=frontport)
