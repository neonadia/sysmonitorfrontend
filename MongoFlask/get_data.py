from sys import stderr
import pymongo
import datetime
from app import mongoport, rackname
from multiprocessing import Pool
from subprocess import Popen, PIPE
import os
from pymongo import MongoClient

mongoport = int(os.environ['MONGOPORT'])
client = MongoClient('localhost', mongoport)
db = client.redfish
collection = db.servers
hardware_collection = db.hw_data
def fetch_hardware_details(bmc_ip,hardware):
    hardware_dict = hardware_collection.find_one({'bmc_ip':bmc_ip},{'_id':0})
    NoneType = type(None)
    if type(hardware_dict) != NoneType:
        hw_dict = {}
        if hardware == "cpu":
            for i in hardware_dict:
                    if i == "CPU":
                        for j in hardware_dict[i]:
                            if j != "Flags" and "Vulnerability" not in j:
                                hw_dict[j] = hardware_dict[i][j]
        elif hardware == "memory":
            for i in hardware_dict:
                if i == "Memory":
                    for j in hardware_dict[i]["Slots"]:
                        if "NO DIMM" not in hardware_dict[i]["Slots"][j]["Serial No."]:
                            hw_dict[j] = {}
                            hw_dict[j]["Manufacturer"] = hardware_dict[i]["Slots"][j]["Manufacturer"]
                            hw_dict[j]["Serial No."] = hardware_dict[i]["Slots"][j]["Serial No."]
                            try:
                                hw_dict[j]["SMC DB handshake"] = hardware_dict[i]["Slots"][j]["SMC DB handshake"]
                            except:
                                hw_dict[j]["SMC DB handshake"] = "N/A"
        elif hardware == "storage":
            device_no = 0
            for i in hardware_dict:
                if i == "Storage":
                    for j in hardware_dict[i]:
                            temp_device_name = "Device"+ str(device_no)
                            device_no += 1
                            hw_dict[temp_device_name] = {}
                            hw_dict[temp_device_name]["Model"] = hardware_dict[i][str(j)]["ModelNumber"]
                            if "nvme" in hardware_dict[i][str(j)]["DevicePath"]:
                                hw_dict[temp_device_name]["Type"] = "NVMe"
                            else:
                                hw_dict[temp_device_name]["Type"] = "HDD"
                            hw_dict[temp_device_name]["Serial Number"] = hardware_dict[i][str(j)]["SerialNumber"]
                            hw_dict[temp_device_name]["Physical Size"] = str(int(hardware_dict[i][str(j)].get("PhysicalSize")) / 1000000000) + " GB"
                            try:
                                hw_dict[temp_device_name]["SMC DB handshake"] =  hardware_dict[i][str(j)]["SMC DB handshake"]
                            except:
                                hw_dict[temp_device_name]["SMC DB handshake"] =  "N/A"
        elif hardware == "nics":
            for i in hardware_dict:
                if i == "NICS":
                    for j in hardware_dict[i]:
                        hw_dict["Device " + str(j)] = hardware_dict[i][str(j)]
                        try:
                            hw_dict["Device " + str(j)]["SMC DB handshake"] = hardware_dict[i][str(j)]["SMC DB handshake"]
                        except:
                            hw_dict["Device " + str(j)]["SMC DB handshake"] = "N/A"
        elif hardware == "gpu":
            for i in hardware_dict:
                if i == "Graphics":
                    for j in hardware_dict[i]["GPU"]:
                        temp_device_name = "GPU" + str(j)
                        hw_dict[temp_device_name] = {}
                        hw_dict[temp_device_name]["GPU Id"] = hardware_dict[i]["GPU"][str(j)]["GPU Id"]
                        hw_dict[temp_device_name]["Series"] = hardware_dict[i]["GPU"][str(j)]["Series"]
                        hw_dict[temp_device_name]["Model"] = hardware_dict[i]["GPU"][str(j)]["Model"]
                        hw_dict[temp_device_name]["PCI Bus"] = hardware_dict[i]["GPU"][str(j)]["PCI Bus"]
                        hw_dict[temp_device_name]["VBIOS"] = hardware_dict[i]["GPU"][str(j)]["VBIOS"]
                        hw_dict[temp_device_name]["Serial No."] = hardware_dict[i]["GPU"][str(j)]["Serial No."]
                        try:
                            hw_dict[temp_device_name]["SMC DB handshake"] = hardware_dict[i]["GPU"][str(j)]["SMC DB handshake"]
                        except:
                            hw_dict[temp_device_name]["SMC DB handshake"] = "N/A"
        elif hardware == "psu":
            for i in hardware_dict:
                if i == "PSU":
                    for j in hardware_dict[i]:
                        if j != "Number of PSUs":
                            temp_device_name = "Unit" + str(j)
                            hw_dict[temp_device_name] = {}
                            hw_dict[temp_device_name]["Module No."] = hardware_dict[i][str(j)]["Module No."]
                            hw_dict[temp_device_name]["Serial No."] = hardware_dict[i][str(j)]["Serial No."]
                            try:
                                hw_dict[temp_device_name]["SMC DB handshake"] = hardware_dict[i][str(j)]["SMC DB handshake"]
                            except:
                                hw_dict[temp_device_name]["SMC DB handshake"] = "N/A"
        elif hardware == "fans":
            for i in hardware_dict:
                if i == "FANS":
                    for j in hardware_dict[i]:
                        hw_dict[hardware_dict[i][str(j)]["name"]] = hardware_dict[i][str(j)]["status"].upper()
        elif hardware == "system":
            for i in hardware_dict:
                if i == "System":
                    for j in hardware_dict[i]:
                        hw_dict["System " + str(j)] = {}
                        hw_dict["System " + str(j)]["Manufacturer"] = hardware_dict[i][str(j)]["Manufacturer"]
                        hw_dict["System " + str(j)]["Serial"] = hardware_dict[i][str(j)]["Serial Number"]
                        try:
                            hw_dict["System " + str(j)]["SMC DB handshake"] = hardware_dict[i][str(j)]["SMC DB handshake"]
                        except:
                            hw_dict["System " + str(j)]["SMC DB handshake"] = "N/A"
                elif i == "Chassis":
                    for j in hardware_dict[i]:
                        hw_dict["Chassis " + str(j)] = {}
                        hw_dict["Chassis " + str(j)]["Manufacturer"] = hardware_dict[i][str(j)]["Manufacturer"]
                        hw_dict["Chassis " + str(j)]["Type"] = hardware_dict[i][str(j)]["Type"]
                        hw_dict["Chassis " + str(j)]["Serial"] = hardware_dict[i][str(j)]["Serial Number"]
                        hw_dict["Chassis " + str(j)]["PN"] = hardware_dict[i][str(j)]["Part Number"]
                        try:
                            hw_dict["Chassis " + str(j)]["SMC DB handshake"] = hardware_dict[i][str(j)]["SMC DB handshake"]
                        except:
                            hw_dict["Chassis " + str(j)]["SMC DB handshake"] = "N/A"
                elif i == "Base Board":
                    for j in hardware_dict[i]:
                        hw_dict["Board " + str(j)] = {}
                        hw_dict["Board " + str(j)]["Manufacturer"] = hardware_dict[i][str(j)]["Manufacturer"]
                        hw_dict["Board " + str(j)]["Product Name"] = hardware_dict[i][str(j)]["Product Name"]
                        hw_dict["Board " + str(j)]["Serial"] = hardware_dict[i][str(j)]["Serial Number"]
                        try:
                            hw_dict["Board " + str(j)]["SMC DB handshake"] = hardware_dict[i][str(j)]["SMC DB handshake"]
                        except:
                            hw_dict["Board " + str(j)]["SMC DB handshake"] = "N/A"
    return hw_dict

def get_hardwareData():
    bmc_ips = []
    cur = collection.find({},{"BMC_IP":1, "Datetime":1, "UUID":1, "Systems.1.SerialNumber":1, "Systems.1.Model":1, "UpdateService.SmcFirmwareInventory.1.Version": 1, "UpdateService.SmcFirmwareInventory.2.Version": 1, "CPLDVersion":1, "_id":0})#.limit(50)
    for i in cur:
        bmc_ips.append(i['BMC_IP'])
    CPU = []
    STORAGE = []
    FANS = []
    MEMORY = []
    NICS = []
    HOSTNAMES = []
    PSU = []
    GPU = []
    SYSTEMS = []
    bmc_ips_complete = []
    equalizer = {"HOSTNAMES":0,"CPU": 0,"MEMORY":0,"STORAGE":0,"NICS":0,"GPU":0,"PSU":0,"FANS":0,"SYSTEMS":0} #Equalizer scoreboard to have a symmetrical 2D array
    NoneType = type(None)
    for ip in bmc_ips:
        hardware_dict = hardware_collection.find_one({'bmc_ip':ip},{'_id':0})
        if type(hardware_dict) != NoneType and hardware_dict['bmc_ip'] == ip:
            bmc_ips_complete.append(ip)###append bmc_ips that are founded in Mongo hardware collection
            for i in hardware_dict:
                if "CPU" in i:
                    cpu_string = ""
                    add_string = ""
                    speed_string = ""
                    for j in hardware_dict[i]:
                        if j == "Socket(s)":
                            if hardware_dict[i][j] == "0":
                                cpu_string = "N/A"
                            else:
                                cpu_string = hardware_dict[i][j] + "x " + cpu_string
                        elif j == "Model name":
                            cpu_string += hardware_dict[i][j]
                    cpu_string += add_string + speed_string 
                    CPU.append(cpu_string)
                    equalizer["CPU"] += 1
                elif "Memory" in i:
                    dimm_no = ""
                    total_mem = ""
                    SMC_handshake = "True"
                    for j in hardware_dict[i]:
                        if 'DIMMS' in j:
                            dimm_no = hardware_dict[i][j]
                        elif "Total Memory" in j:
                            total_mem = hardware_dict[i][j]
                        elif "Slots" in j:
                            for k in hardware_dict[i][j]:
                                try:
                                    if "False" in hardware_dict[i][j][str(k)]["SMC DB handshake"]:
                                        SMC_handshake = "False"
                                except:
                                    SMC_handshake = "TBD"
                    memory = [dimm_no + " DIMMs; Total Memory: " + total_mem + "GB",SMC_handshake]
                    MEMORY.append(memory)
                    equalizer["MEMORY"] += 1
                elif "PSU" in i:
                    psu_num = ""
                    psu_string = ""
                    SMC_handshake = "True"
                    for j in hardware_dict[i]:
                        if "Number" in j:
                            psu_num = hardware_dict[str(i)][str(j)]
                        else:
                            for k in hardware_dict[i][str(j)]:
                                try:
                                    if "False" in hardware_dict[i][str(j)]["SMC DB handshake"]:
                                        SMC_handshake = "False"
                                except:
                                    SMC_handshake = "TBD"
                    psu_string += str(psu_num) + " PSUs"  
                    PSU.append([psu_string,SMC_handshake])
                    equalizer["PSU"] += 1
                elif "Storage" in i:
                    size = 0
                    no_drives = 0
                    SMC_handshake = "True"
                    for j in hardware_dict[i]:
                        for k in hardware_dict[i][j]:
                            if "PhysicalSize" in k:
                                size += (hardware_dict[i][str(j)][k] / 1000000000)
                                no_drives += 1
                        try:
                            if "False" in hardware_dict[i][str(j)]["SMC DB handshake"]:
                                SMC_handshake = "False"
                        except:
                            SMC_handshake = "TBD"
                    gb_size = size
                    storage = [str(no_drives) + " drives; " + "Total System Storage: " + str(round(gb_size,1)) + " GB", SMC_handshake]
                    STORAGE.append(storage)
                    equalizer["STORAGE"] += 1
                elif "NICS" in i:
                    no_nics = 0
                    SMC_handshake = "True"
                    for j in hardware_dict[i]:
                        no_nics = int(j)
                        try:
                            if "False" in hardware_dict[i][str(j)]["SMC DB handshake"]:
                                SMC_handshake = "False"
                        except:
                            SMC_handshake = "TBD"
                    no_nics += 1
                    network = [str(no_nics) + " network adapters", SMC_handshake]
                    NICS.append(network)
                    equalizer["NICS"] += 1
                elif "Graphics" in i:
                    no_gpus = 0
                    maker = ""
                    driver = ""
                    SMC_handshake = "True"
                    for j in hardware_dict[i]:
                        if "Number of GPUs" in j:
                            no_gpus = int(hardware_dict[i][j])
                        elif "Manufacturer" in j:
                            maker = hardware_dict[i][j]
                        elif "Driver Version" in j:
                            driver = hardware_dict[i][j]
                        elif "GPU" in j:
                            for gpu in hardware_dict[i][j]:
                                try:
                                    if "False" in hardware_dict[i][j][str(gpu)]["SMC DB handshake"]:
                                        SMC_handshake = "False"
                                except:
                                    SMC_handshake = "TBD"
                    graphics = [str(no_gpus) + " " + maker  + " GPUs w/ " + driver + " driver",SMC_handshake]
                    GPU.append(graphics)
                    equalizer["GPU"] += 1
                elif "FANS" in i:
                    no_fans = 0
                    for j in hardware_dict[i]:
                        # no_fans = int(j)
                        no_fans += 1
                    fans = "Number of fans: " + str(no_fans)
                    FANS.append(fans)
                    equalizer["FANS"] += 1
                elif "Hostname" in i:
                    HOSTNAMES.append(hardware_dict[i])
                    equalizer["HOSTNAMES"] += 1
                elif "System" in i:
                    SMC_handshake = "True"
                    for j in hardware_dict[i]:
                        try:
                            if "False" in hardware_dict[i][str(j)]["SMC DB handshake"]:
                                SMC_handshake = "False"
                        except:
                            SMC_handshake = "TBD"
                        name = hardware_dict[i][str(j)]["Product Name"]
                    try:
                        for j in hardware_dict["Base Board"]:
                            try:
                                if "False" in hardware_dict["Base Board"][str(j)]["SMC DB handshake"]:
                                    SMC_handshake = "False"
                            except:
                                SMC_handshake = "TBD"
                    except:
                        print("No Baseboard")
                    try:
                        for j in hardware_dict["Chassis"]:
                            try:
                                if "False" in hardware_dict["Chassis"][str(j)]["SMC DB handshake"]:
                                    SMC_handshake = "False"
                            except:
                                SMC_handshake = "TBD"
                    except:
                        print("No Chassis")
                    system = [name,SMC_handshake]
                    SYSTEMS.append(system)
                    equalizer["SYSTEMS"] += 1
        for i in equalizer:
            compare = equalizer[i]
            for j in equalizer:
                if equalizer[j] < compare:
                    equalizer[j] += 1
                    if j == "CPU":
                        CPU.append("N/A")
                    elif j == "MEMORY":
                        MEMORY.append(["N/A","N/A"])
                    elif j == "HOSTNAMES":
                        HOSTNAMES.append("N/A")
                    elif j == "STORAGE":
                        STORAGE.append(["N/A","N/A"])
                    elif j == "NICS":
                        NICS.append(["N/A","N/A"])
                    elif j == "GPU":
                        GPU.append(["N/A","N/A"])
                    elif j == "PSU":
                        PSU.append(["N/A","N/A"])
                    elif j == "SYSTEMS":
                        SYSTEMS.append(["N/A","N/A"])
                    else:
                        FANS.append("N/A")
                elif equalizer[j] > compare:
                    compare += 1
                    equalizer[i] = compare
                    if i == "CPU":
                        CPU.append("N/A")
                    elif i == "MEMORY":
                        MEMORY.append(["N/A","N/A"])
                    elif i == "HOSTNAMES":
                        HOSTNAMES.append("N/A")
                    elif i == "STORAGE":
                        STORAGE.append(["N/A","N/A"])
                    elif i == "NICS":
                        NICS.append(["N/A","N/A"])
                    elif i == "GPU":
                        GPU.append(["N/A","N/A"])
                    elif i == "PSU":
                        PSU.append(["N/A","N/A"])
                    elif j == "SYSTEMS":
                        SYSTEMS.append(["N/A","N/A"])
                    else:
                        FANS.append("N/A")
    data = zip(HOSTNAMES,bmc_ips_complete,SYSTEMS,CPU,MEMORY,STORAGE,NICS,GPU,PSU,FANS)
    return data

def find_ikvm(bmc_ip):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    data_entry = entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "IKVM": 1})
    for i in data_entry:
        try:
            ikvm_addr = i['IKVM']
        except:
            ikvm_addr = 'unknown'
            continue
    connect.close()
    return ikvm_addr

def makeSmcipmiExcutable():
    process = Popen('find SMCIPMITOOL -type f -iname "*" -exec chmod +x {} \;', shell=True, stdout=PIPE, stderr=PIPE)
    process.communicate()
    print("SMCIPMITool is excutable now", flush=True)
    return(0)


def get_Firmware(bmc_ip,user,pwd): #Returns a list of firmware version. You must parse through the return list for the desired value. Will return a boolean if no output
    r = Popen('./SMCIPMITOOL/SMCIPMITool ' + bmc_ip + ' ' + user + ' ' + pwd + ' ipmi oem summary',shell = 1, stdout = PIPE, stderr = PIPE)
    try:
        stdout,stderr = r.communicate(timeout=3)
        data = stdout.decode()
        err = stderr.decode()
        if err != '':
            print(err,flush=True)
            return True
        else:
            data = data.split('\n')
            return data
    except Exception as e:
        print(e,flush=True)
        return True

def find_powercontrol(bmc_ip):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    data_entry = entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "PowerControl": 1})

    # initial dataset
    dataset = {'RACK': rackname, 'bmc_ip': bmc_ip, 'datetime': [], 'PowerControl': []}

    # power control
    for i in range(len(data_entry[0]['PowerControl'])):
        dataset['PowerControl'].append({'Name': data_entry[0]['PowerControl'][str(i + 1)]['Name'], 'Reading': []})

    # get dataset
    for x in data_entry:
        dataset['datetime'].append(x['Datetime'])

        for i in range(len(x['PowerControl'])):
            dataset['PowerControl'][i]['Reading'].append(x['PowerControl'][str(i+1)]['PowerConsumedWatts'])

    connect.close()

    return dataset

def find_voltages_names(bmc_ip):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    data_entry = entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "Voltages": 1})

    # initial dataset
    dataset = {'RACK': rackname, 'bmc_ip': bmc_ip, 'Voltages': []}

    # voltages
    for i in range(len(data_entry[0]['Voltages'])):
        dataset['Voltages'].append({'Name': data_entry[0]['Voltages'][str(i + 1)]['Name']})

    connect.close()

    return dataset
    
def get_time(bmc_ip,pwd): # datetime for IPMI
    try:
        ipmi_response = Popen('ipmitool -H ' + bmc_ip + ' -U ADMIN -P ' +  pwd + ' sel time get ', shell = 1, stdout  = PIPE, stderr = PIPE)
        stdout,stderr = ipmi_response.communicate(timeout=1)
    except:
        print('<ipmitool set time get> got no response, please check the password and network connection.', flush=True)
        date_time = 'no_time'
    else:
        if stderr.decode('utf-8') == '':
            date_time = stdout.decode("utf-8")
            date_time = date_time.replace('\n','')
            print(stdout, flush=True)
        else:
            date_time = 'no_time'
            print(stderr, flush=True)
    return date_time

def get_ntp_server(bmc_ip,pwd):
    try:
        ipmi_response = Popen('ipmitool -H ' + bmc_ip + ' -U ADMIN -P ' +  pwd + ' raw 0x30 0x68 0x01 0x0 0x1 ', shell = 1, stdout  = PIPE, stderr = PIPE)
        stdout,stderr = ipmi_response.communicate(timeout=1)
    except:
        print('<ipmitool raw 0x30 0x68 0x01 0x0 0x1> got no response, please check the password and network connection.', flush=True)
        ntp_server = 'no response'
    else:
        if stderr.decode('utf-8') == '':
            ntp_server = stdout.decode("utf-8")
            ntp_server = ntp_server.replace('\n','')
            ntp_server = bytes.fromhex(ntp_server).decode('utf-8')
            print(stdout, flush=True)
        else:
            ntp_server = 'no response'
            print(stderr, flush=True)
    return ntp_server
 
def get_ntp_status(bmc_ip,pwd):
    try:
        ipmi_response = Popen('ipmitool -H ' + bmc_ip + ' -U ADMIN -P ' +  pwd + ' raw 0x30 0x68 0x01 0x0 0x0 ', shell = 1, stdout  = PIPE, stderr = PIPE)
        stdout,stderr = ipmi_response.communicate(timeout=1)
    except:
        print('<ipmitool raw 0x30 0x68 0x01 0x0 0x0> got no response, please check the password and network connection.', flush=True)
        return ['no response','no response','no response']
    else:
        if stderr.decode('utf-8') == '':
            ntp_status = stdout.decode("utf-8")
            ntp_status = ntp_status.replace('\n','')
            if len(ntp_status) >= 8:
                p0 = ntp_status[:2]
                p1 = ntp_status[3:-3]
                p2 = ntp_status[-2:]
                p1 = bytes.fromhex(p1).decode('utf-8')
                print('Enable/disable NTP: ' + p0 + '\n' + 'Daylight Savings enable/disable: ' + p2 + '\n' + 'Modulation: ' + p1 , flush=True)
                return [p0,p2,p1]
        else:
            print(stderr, flush=True)
            return [stderr,stderr,stderr]


def find_voltages(bmc_ip):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    data_entry = entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "Voltages": 1})

    # initial dataset
    dataset = {'RACK': rackname, 'bmc_ip': bmc_ip, 'datetime': [], 'Voltages': []}

    # voltages
    for i in range(len(data_entry[0]['Voltages'])):
        dataset['Voltages'].append({'Name': data_entry[0]['Voltages'][str(i + 1)]['Name'], 'Reading': []})

    # get dataset
    for x in data_entry:
        dataset['datetime'].append(x['Datetime'])

        for i in range(len(x['Voltages'])):
            dataset['Voltages'][i]['Reading'].append(x['Voltages'][str(i+1)]['ReadingVolts'])

    connect.close()

    return dataset


def find_powersupplies(bmc_ip):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    data_entry = entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "PowerSupplies": 1})

    # initial dataset
    dataset = {'RACK': rackname, 'bmc_ip': bmc_ip, 'datetime': [], 'PowerSupplies': []}

    # power supplies
    for i in range(len(data_entry[0]['PowerSupplies'])):
        dataset['PowerSupplies'].append({'Name': data_entry[0]['PowerSupplies'][str(i + 1)]['Name'], 'InputReading': [], 'OutputReading': []})

    # get dataset
    for x in data_entry:
        dataset['datetime'].append(x['Datetime'])
        for i in range(len(x['PowerSupplies'])):
            try:
                dataset['PowerSupplies'][i]['InputReading'].append(x['PowerSupplies'][str(i+1)]['LineInputVoltage'])
            except:
                dataset['PowerSupplies'][i]['InputReading'].append(0)
            try:
                dataset['PowerSupplies'][i]['OutputReading'].append(x['PowerSupplies'][str(i+1)]['LastPowerOutputWatts'])
            except:
                dataset['PowerSupplies'][i]['InputReading'].append(0)

    connect.close()

    return dataset    

def find_allpowercontrols_helper(input_list):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    entries = db.monitor
    bmc_ip = input_list[0]
    sensor_id = input_list[1]
    data_entry = entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "PowerControl": 1})
    all_time = []
    all_reading = []
    for j in data_entry:
        all_time.append(j['Datetime'])
        all_reading.append(j['PowerControl'][sensor_id]['PowerConsumedWatts'])
    return all_time, all_reading, bmc_ip


def find_allpowercontrols(ip_list):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    data_entries = []
    sensor_name = "PowerControl"
    sensor_id = "1"
    for bmc_ip in ip_list:
        data_entries.append(entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "PowerControl": 1}))

    # initial dataset
    dataset = {'RACK': rackname, 'datetime': [], 'PowerControl': []}

    # power supplies
    for bmc_ip, data_entry in zip(ip_list, data_entries):
        dataset['PowerControl'].append({'Name': bmc_ip + ' ,Unit: W', 'Reading': []})

    # get dataset
    input_list = []
    for ip in ip_list:
        input_list.append([ip, sensor_id])
    with Pool() as p:
        output = p.map(find_allpowercontrols_helper, input_list)
    dataset['datetime'] = output[0][0]
    for i, bmc_ip in enumerate(ip_list):
        if bmc_ip != output[i][2] or bmc_ip != dataset[sensor_name][i]['Name'].replace(' ,Unit: W',''):
            print("WARINING!! bmc_ip not match: " + bmc_ip + " && " + output[i][2] + " && " + dataset[sensor_name][i]['Name'],flush=True)
        else:
            print("Fetched " + bmc_ip, flush=True)
        dataset[sensor_name][i]['Reading'] = output[i][1]
    
    # avg and sum
    power_sum = [ 0 for x in range(len(dataset['datetime']))]
    power_avg = [ 0 for x in range(len(dataset['datetime']))]
    for i in range(len(dataset['datetime'])):
        for j in range(len(dataset['PowerControl'])):
            power_sum[i] += dataset['PowerControl'][j]['Reading'][i]
    for i in range(len(power_sum)):
        power_avg[i] = round(power_sum[i]/len(dataset['PowerControl']),1)
        power_sum[i] = round(power_sum[i]/1000,1)
    dataset['PowerControl'].insert(0,{'Name': 'Avg Node, Unit: W', 'Reading': power_avg})
    dataset['PowerControl'].insert(0,{'Name': 'Total, Unit: kW', 'Reading': power_sum})
    return dataset

def find_temperatures_names(bmc_ip):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    data_entry = entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "Temperatures": 1})

    # initial dataset
    dataset = {'RACK': rackname, 'bmc_ip': bmc_ip, 'Temperatures': []}

    # temperatures
    for i in range(len(data_entry[0]['Temperatures'])):
        dataset['Temperatures'].append({'Name': data_entry[0]['Temperatures'][str(i + 1)]['Name']})
    connect.close()

    return dataset

def find_temperatures(bmc_ip):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    data_entry = entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "Temperatures": 1})

    # initial dataset
    dataset = {'RACK': rackname, 'bmc_ip': bmc_ip, 'datetime': [], 'Temperatures': []}

    # temperatures
    for i in range(len(data_entry[0]['Temperatures'])):
        dataset['Temperatures'].append({'Name': data_entry[0]['Temperatures'][str(i + 1)]['Name'], 'Reading': []})

    # get dataset
    for x in data_entry:
        dataset['datetime'].append(x['Datetime'])
        for i in range(len(x['Temperatures'])):
            dataset['Temperatures'][i]['Reading'].append(x['Temperatures'][str(i+1)]['ReadingCelsius'])

    connect.close()

    return dataset

def find_alltemperatures_helper(input_list):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    entries = db.monitor
    bmc_ip = input_list[0]
    sensor_id = input_list[1]
    data_entry = entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "Temperatures": 1})
    all_time = []
    all_reading = []
    for j in data_entry:
        all_time.append(j['Datetime'])
        all_reading.append(j['Temperatures'][sensor_id]['ReadingCelsius'])
    return all_time, all_reading, bmc_ip

def find_alltemperatures(ip_list, sensor_id):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    
    # get sensor name
    data_entries = []
    for bmc_ip in ip_list:
        data_entries.append(entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "Temperatures": 1}))
        break    
    for j in data_entries[0]:
        sensor_name = j['Temperatures'][sensor_id]['Name']
        break
    
    # get data
    data_entries = []
    for bmc_ip in ip_list:
        data_entries.append(entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "Temperatures": 1}))
    
    # initial dataset
    dataset = {'RACK': rackname, 'datetime': [], sensor_name: []}

    # temperatures
    for bmc_ip, data_entry in zip(ip_list, data_entries):
        dataset[sensor_name].append({'Name': bmc_ip , 'Reading': []})
        
    # get dataset
    input_list = []
    for ip in ip_list:
        input_list.append([ip, sensor_id])
    with Pool() as p:
        output = p.map(find_alltemperatures_helper, input_list)
    dataset['datetime'] = output[0][0]
    for i, bmc_ip in enumerate(ip_list):
        if bmc_ip != output[i][2] or bmc_ip != dataset[sensor_name][i]['Name']:
            print("WARINING!! bmc_ip not match: " + bmc_ip + " && " + output[i][2] + " && " + dataset[sensor_name][i]['Name'],flush=True)
        else:
            print("Fetched " + bmc_ip, flush=True)
        dataset[sensor_name][i]['Reading'] = output[i][1]
    return dataset


def find_fans_names(bmc_ip):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    data_entry = entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "Fans": 1})

    # initial dataset
    dataset = {'RACK': rackname, 'bmc_ip': bmc_ip, 'Fans': []}

    # fans
    for i in range(len(data_entry[0]['Fans'])):
        try:
            dataset['Fans'].append({'Name': data_entry[0]['Fans'][str(i+1)]['Name']})
        except:
            print("FAN name is not readable, named as FAN1,FAN2..", flush=True)
            dataset['Fans'].append({'Name': 'FAN'+str(i+1), 'Speed': []})
            
    connect.close()

    return dataset

def find_fans(bmc_ip):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    data_entry = entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "Fans": 1})

    # initial dataset
    dataset = {'RACK': rackname, 'bmc_ip': bmc_ip, 'datetime': [], 'Fans': []}

    # fans
    for i in range(len(data_entry[0]['Fans'])):
        try:
            dataset['Fans'].append({'Name': data_entry[0]['Fans'][str(i+1)]['Name'], 'Speed': []})
        except:
            print("FAN name is not readable, named as FAN1,FAN2..", flush=True)
            dataset['Fans'].append({'Name': 'FAN'+str(i+1), 'Speed': []})

    # get dataset
    for x in data_entry:
        dataset['datetime'].append(x['Datetime'])
        for i in range(len(x['Fans'])):
            dataset['Fans'][i]['Speed'].append(x['Fans'][str(i+1)]['Reading'])

    connect.close()

    return dataset

def find_allfans_helper(input_list):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    entries = db.monitor
    bmc_ip = input_list[0]
    sensor_id = input_list[1]
    data_entry = entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "Fans": 1})
    all_time = []
    all_reading = []
    for j in data_entry:
        all_time.append(j['Datetime'])
        all_reading.append(j['Fans'][sensor_id]['Reading'])
    return all_time, all_reading, bmc_ip

def find_allfans(ip_list, sensor_id):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    
    # get sensor name
    data_entries = []
    for bmc_ip in ip_list:
        data_entries.append(entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "Fans": 1}))
        break    
    for j in data_entries[0]:
        try:
            sensor_name = j['Fans'][sensor_id]['Name']
        except:
            print("FAN name is not readable, named as FAN1,FAN2..", flush=True)
            sensor_name = "FAN" + sensor_id
        break
    
    # get data
    data_entries = []
    for bmc_ip in ip_list:
        data_entries.append(entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "Fans": 1}))
    
    # initial dataset
    dataset = {'RACK': rackname, 'datetime': [], sensor_name: []}

    # temperatures
    for bmc_ip, data_entry in zip(ip_list, data_entries):
        dataset[sensor_name].append({'Name': bmc_ip , 'Reading': []})
        
    # get dataset
    input_list = []
    for ip in ip_list:
        input_list.append([ip, sensor_id])
    with Pool() as p:
        output = p.map(find_allfans_helper, input_list)
    dataset['datetime'] = output[0][0]
    for i, bmc_ip in enumerate(ip_list):
        if bmc_ip != output[i][2] or bmc_ip != dataset[sensor_name][i]['Name']:
            print("WARINING!! bmc_ip not match: " + bmc_ip + " && " + output[i][2] + " && " + dataset[sensor_name][i]['Name'], flush=True)
        else:
            print("Fetched " + bmc_ip, flush=True)
        dataset[sensor_name][i]['Reading'] = output[i][1]
    return dataset

def find_min_max(bmc_ip, api1, api2, boundry):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    entries = db.monitor
    data_entry = entries.find({"BMC_IP": bmc_ip})
    all_readings = list(data_entry)
    all_vals = {}
    all_dates = []
    for sensorID in all_readings[0][api1]:
        try:
            all_vals[sensorID] = [all_readings[0][api1][sensorID]['Name']]
        except:
            print("FAN name is not readable, named as FAN1,FAN2..", flush=True)
            if api1 == "Fans":
                all_vals[sensorID] = ["Fan"+sensorID]
            else:
                all_vals[sensorID] = ["NaN"+sensorID]
            
    for i in range(len(all_readings)):
        all_dates.append(all_readings[i]["Datetime"])
        for sensorID in all_vals:
            all_vals[sensorID].append(all_readings[i][api1][sensorID][api2])
    extreme_vals = {}
    date_format = "%Y-%m-%d %H:%M:%S"
    elapsed_time = datetime.datetime.strptime(all_dates[-1], date_format) - datetime.datetime.strptime(all_dates[0], date_format)
    elapsed_hour = str(round(elapsed_time.total_seconds()/3600,2))
    last_date = all_dates[-1]
    zero_count  = []
    for sensorID in all_vals:
        low = boundry
        avg = 0
        zero_count.append(0)
        high = -boundry
        low_date = "N/A"
        high_date = "N/A" 
        for i, n in enumerate(all_vals[sensorID]):
            if type(n) == int or type(n) == float:
                if n != 0:
                    avg += n
                    if low > n:
                        low = n
                        low_date = all_dates[i-1] # i-1 because the first element of all_vals is name, so it has one more element than all_dates
                    if high < n:
                        high = n
                        high_date = all_dates[i-1]
                else:
                    zero_count[-1] += 1
        if  len(all_vals[sensorID]) - zero_count[-1] -1  == 0:
            avg = 0
            zero_count.pop() # delete all zero reading
        else:
            avg = round(avg/(len(all_vals[sensorID]) - zero_count[-1] -1),4) # -1 because the first element is name
        extreme_vals[all_vals[sensorID][0]] = [low, low_date, high, high_date,avg]    
    messages = []
    max_vals = []
    min_vals = []
    max_dates = []
    min_dates = []
    avg_vals = []
    sensorNames = []
    good_count =[]
    for i in zero_count:
        good_count.append(len(all_dates)-i) 
    for i, sensorName in enumerate(extreme_vals):
        min_temp = extreme_vals[sensorName][0]
        min_date = extreme_vals[sensorName][1]
        max_temp = extreme_vals[sensorName][2]
        max_date = extreme_vals[sensorName][3]
        avg_val = extreme_vals[sensorName][4]
        if min_temp > max_temp or min_temp == boundry or max_temp == -boundry or avg_val == 0:
            continue
        else:
            max_vals.append(max_temp)
            min_vals.append(min_temp)
            max_dates.append(max_date)
            min_dates.append(min_date)
            avg_vals.append(avg_val)
            sensorNames.append(sensorName)
            messages.append(sensorName + ": MIN=" + str(min_temp) + " " + min_date + " MAX=" + str(max_temp) + " " + max_date)
    if not min_vals:
        dummy = -9999
        max_vals.append(dummy)
        min_vals.append(dummy)
        #max_dates.append(dummy)
        #min_dates.append(dummy)
        avg_vals.append(dummy)
        good_count.append(dummy)
        zero_count.append(dummy)
        sensorNames.append("N/A")
        messages.append(sensorName + ": MIN=" + str(min_temp) + " " + min_date + " MAX=" + str(max_temp) + " " + max_date)
    
    return messages, max_vals, min_vals, max_dates, min_dates, sensorNames, avg_vals, len(all_dates), elapsed_hour, good_count, zero_count, last_date



def find_min_max_rack_helper(input_list):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    entries = db.monitor
    all_vals = {}
    all_dates = {}
    bmc_ip = input_list[0]
    api1 = input_list[1]
    api2 = input_list[2]
    sensor_id = input_list[3]
    data = entries.find({'BMC_IP':bmc_ip},{api1:1,'Datetime':1})
    all_vals[bmc_ip] = []
    all_dates[bmc_ip] = []
    for i in data: # data contains multiple readings, each reading has a time
        all_vals[bmc_ip].append(i[api1][sensor_id][api2])
        sensor_name = i[api1][sensor_id]['Name']
        all_dates[bmc_ip].append(i['Datetime'])
    return all_vals, sensor_name, all_dates

def find_min_max_rack(sensor_id,api1,api2,boundry,ip_list):
    input_list = []
    for bmc in ip_list:
        input_list.append([bmc, api1, api2, sensor_id])
    with Pool() as p:
        output = p.map(find_min_max_rack_helper, input_list)
    all_vals = {}
    all_dates = {}
    for i in output:
        cur_key = list(i[0].keys())[0]
        all_vals[cur_key] = i[0][cur_key]
        sensor_name = i[1]
        all_dates[cur_key] = i[2][cur_key]        
    # find min/max  
    max_vals = []
    max_dates = []
    min_vals = []
    min_dates = []
    avg_vals = []
    zero_count = []
    for bmc_ip in ip_list:
        high = -boundry
        low = boundry
        high_date = "N/A"
        low_date = "N/A"
        zero_count.append(0)
        avg = 0
        for i, n in enumerate(all_vals[bmc_ip]):
            if type(n) == int or type(n) == float:
                if n != 0:
                    avg += n
                    if low > n:
                        low = n
                        low_date = all_dates[bmc_ip][i] 
                    if high < n:
                        high = n
                        high_date = all_dates[bmc_ip][i]
                else:
                    zero_count[-1] += 1
        if  len(all_vals[bmc_ip]) - zero_count[-1]  == 0:
            avg = 0
            #zero_count.pop() # delete all zero reading
        else:
            avg = round(avg/(len(all_vals[bmc_ip]) - zero_count[-1]),4)
        max_vals.append(high)
        max_dates.append(high_date)
        min_vals.append(low)
        min_dates.append(low_date)
        avg_vals.append(avg)

    date_format = "%Y-%m-%d %H:%M:%S"
    elapsed_time = datetime.datetime.strptime(all_dates[ip_list[-1]][-1], date_format) - datetime.datetime.strptime(all_dates[ip_list[0]][0], date_format)
    elapsed_hour = str(round(elapsed_time.total_seconds()/3600,2))
    last_date = all_dates[ip_list[-1]][-1]

    good_count = []
    for i, bmc_ip in enumerate(ip_list):
        good_count.append(len(all_dates[bmc_ip])-zero_count[i])
        
    all_count = 0
    for i in all_dates.values():
        all_count += len(i)
    all_count = int(all_count/len(all_dates))
    
    return max_vals, min_vals, max_dates, min_dates, avg_vals, all_count,  elapsed_hour, good_count, zero_count, last_date, sensor_name