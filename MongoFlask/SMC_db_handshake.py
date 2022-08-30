from ast import excepthandler
import pandas as pd
import os
import json
import pymongo
import sys

def create_hw_folder(hostname):   
    # create main dirs
    hw_dir = os.environ['UPLOADPATH'] + '/hw_data'
    if 'hw_data' not in os.listdir(directory):
        os.mkdir(hw_dir)
        print("Directory '% s' created" % hw_dir, flush=True)
    # create sub dirs
    if 'hw_info_' + hostname  not in os.listdir(hw_dir):
        os.mkdir(hw_dir + '/hw_info_' + hostname)
        print("Directory '% s' created" % hw_dir + '/hw_info_' + hostname, flush=True)
    # create an empty config file
    if not os.path.isfile(hw_dir + '/hw.conf'):
        with open(hw_dir + '/hw.conf', 'w') as hw_file:
            hw_file.write('OS=N/A\n')
            hw_file.write('GPU=N/A\n')    
        print("File '% s' created" % hw_dir + '/hw.conf', flush=True)

mongoport = int(os.environ['MONGOPORT'])
client = pymongo.MongoClient('localhost', mongoport)
db = client.redfish
collection = db.hw_data ### MongoDB Collection
### Get hostname from input file (.csv), insert dash to reflect, and get bmc_ip list
df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
hostname_list = df_pwd['mac'] #### Get mac address from pwd#.txt
new_hostname_list = []
for i in hostname_list: ### Convert MAC address to xx-xx-xx-xx-xx format
    if ":" in i:
        new = i.replace(":","-")
        new_hostname_list.append(new.lower())
    elif ":" not in i and "-" not in i: 
        new = ""
        for x in range(len(i)):
            if x%2 == 0 and x in range(2,11):
                new += "-"
                new += i[x]
            else:
                new += i[x]
        new_hostname_list.append(new.lower())
inputhosts = new_hostname_list
bmc_ips = list(df_pwd['ip'])  #### Get BMC_IPs from pwd#.txt

sys_serial_nums = []
for ip in bmc_ips:
    entry = collection.find({"bmc_ip":ip},{'_id':0})
    for machine in entry:
        for component in machine:
            if "System" in component:
                for system in machine[component]:
                    try:
                        sys_serial_nums.append([machine[component][str(system)]["Serial Number"],ip,machine['Hostname']])
                    except:
                        sys_serial_nums.append(["N/A",ip,machine['Hostname']])

#sys_serial_nums is array of style ['serial', 'bmc_ip', 'hostname']

# inputdir = "/app/RACK/"  i.e example path
directory = os.environ['UPLOADPATH'] #### Usually /app/<YOUR FOLDER FROM WHICH YOU DECLARED IN auto.env
# inputdir = directory + "/hw_data/" Navigate to your hardware logs folder. Needs to contain "hw_data" in the name in order to be flagged           
inputdir = directory + "/hw_data/"
if 'hw_data' not in os.listdir(directory):
    print('No hw_data folder found, creating the directory...', flush=True)
    df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])    
    for cur_mac in list(df_pwd['mac']):            
        cur_mac = cur_mac.lower()
        hostname = '-'.join(a+b for a,b in zip(cur_mac[::2], cur_mac[1::2]))
        create_hw_folder(hostname)

print("Performing SMC DB check...")
for file in os.listdir(inputdir):
    for i in sys_serial_nums:
        if i[0].lower() == file.split(".")[0].lower()  or i[2].replace("-","").lower() == file.split(".")[0].lower():
            print("Found pertaining file to system..." + i[2])
            all_components_accounted_for = True
            print("working on serial: " + i[0].lower()  + " and host: " + i[2])
            df_sn = pd.read_csv(inputdir + "/" + file ,names=['c1','c2','c3'],header=None, delimiter=r"\s+")
            entry = collection.find_one({"Hostname":i[2]},{'_id': 0,'bmc_ip':0,'CPU':0,'FANS':0})
            for component in entry:
                if component == 'Memory':
                    temp_dict = {component:entry[component]}
                    for DIMMS in temp_dict[component]["Slots"]:
                        dimm_serial = temp_dict[component]['Slots'][DIMMS]['Serial No.']
                        data = dimm_serial.upper()
                        if data != "NO DIMM":
                            if data in df_sn.values:
                                print("Found serial in DB for " + DIMMS)
                                temp_dict["Memory"]["Slots"][DIMMS]["SMC DB handshake"] = "True"
                            elif data != "N/A" and data not in df_sn.values and data != "UNKNOWN":
                                all_components_accounted_for = False
                                temp_dict["Memory"]["Slots"][DIMMS]["SMC DB handshake"] = "False"
                                print("Memory")
                            elif data == "N/A" or data == "" or data == "UNKNOWN":
                                temp_dict["Memory"]["Slots"][DIMMS]["SMC DB handshake"] = "TBD"
                        else:
                            temp_dict["Memory"]["Slots"][DIMMS]["SMC DB handshake"] = "N/A"
                    collection.update_one({"Hostname":i[2]},{"$set":temp_dict})
                elif component == "NICS":
                    temp_dict = {component:entry[component]}
                    for port in temp_dict[component]:
                        nic_serial = temp_dict[component][str(port)]['Serial']
                        try:
                            nic_mac = temp_dict[component][str(port)]['MAC'].replace(":","").upper()
                        except:
                            nic_mac = "N/A"
                        data = nic_serial.upper()
                        if data in df_sn.values:
                            temp_dict[component][str(port)]["SMC DB handshake"] = "True"
                            if nic_mac in df_sn.values:
                                temp_dict[component][str(port)]["MAC in DB?"] = "True"
                            elif nic_mac == "N/A":
                                temp_dict[component][str(port)]["MAC in DB?"] = "TBD"
                            else:
                                temp_dict[component][str(port)]["MAC in DB?"] = "False"
                                all_components_accounted_for = False
                        elif data == "N/A":
                            temp_dict[component][str(port)]["SMC DB handshake"] = "TBD"
                            if nic_mac in df_sn.values:
                                temp_dict[component][str(port)]["MAC in DB?"] = "True"
                            elif nic_mac == "N/A":
                                temp_dict[component][str(port)]["MAC in DB?"] = "TBD"
                            else:
                                temp_dict[component][str(port)]["MAC in DB?"] = "False"
                                all_components_accounted_for = False
                        else:
                            temp_dict[component][str(port)]["SMC DB handshake"] = "False"
                            all_components_accounted_for = False
                            if nic_mac in df_sn.values:
                                temp_dict[component][str(port)]["MAC in DB?"] = "True"
                            elif nic_mac == "N/A":
                                temp_dict[component][str(port)]["MAC in DB?"] = "TBD"
                            else:
                                temp_dict[component][str(port)]["MAC in DB?"] = "False"
                    collection.update_one({"Hostname":i[2]},{"$set":temp_dict})
                elif component == "PSU":
                    temp_dict = {component:entry[component]}
                    for unit in temp_dict[component]:
                        if unit != "Number of PSUs":
                            psu_serial = temp_dict[component][str(unit)]["Serial No."]
                            data = psu_serial.upper()
                            if data in df_sn.values:
                                print("Found serial in DB for PSU no. " + str(unit))
                                temp_dict[component][str(unit)]["SMC DB handshake"] = "True"
                            elif data != "N/A" and data not in df_sn.values and data != "TO BE FILLED BY O.E.M.":
                                all_components_accounted_for = False
                                temp_dict[component][str(unit)]["SMC DB handshake"] = "False"
                                print("PSU")
                            elif data == "N/A" or data == "" or data =="TO BE FILLED BY O.E.M.":
                                temp_dict[component][str(unit)]["SMC DB handshake"] = "TBD"
                    collection.update_one({"Hostname":i[2]},{"$set":temp_dict})
                elif component == "Chassis":
                    temp_dict = {component:entry[component]}
                    for chassis in temp_dict[component]:
                        chassis_serial = temp_dict[component][str(chassis)]["Serial Number"]
                        data = chassis_serial.upper()
                        if data in df_sn.values:
                            print("Found serial in DB for chassis no. " + str(chassis))
                            temp_dict[component][str(chassis)]["SMC DB handshake"] = "True"
                        elif data != "N/A" and data not in df_sn.values:
                            all_components_accounted_for = False
                            temp_dict[component][str(chassis)]["SMC DB handshake"] = "False"
                            print("Chassis")
                        elif data == "N/A" or data == "":
                            temp_dict[component][str(chassis)]["SMC DB handshake"] = "TBD"
                    collection.update_one({"Hostname":i[2]},{"$set":temp_dict})
                elif component == "Base Board":
                    temp_dict = {component:entry[component]}
                    for mobo in temp_dict[component]:
                        mobo_serial = temp_dict[component][str(mobo)]["Serial Number"]
                        data = mobo_serial.upper()
                        if data in df_sn.values:
                            print("Found serial in DB for MB no. " + str(mobo))
                            temp_dict[component][str(mobo)]["SMC DB handshake"] = "True"
                        elif data != "N/A" and data not in df_sn.values:
                            all_components_accounted_for = False
                            temp_dict[component][str(mobo)]["SMC DB handshake"] = "False"
                            print("MOBO")
                        elif data == "N/A" or data == "":
                            temp_dict[component][str(mobo)]["SMC DB handshake"] = "TBD"
                    collection.update_one({"Hostname":i[2]},{"$set":temp_dict})
                elif component == "Storage":
                    temp_dict = {component:entry[component]}
                    for drive in temp_dict["Storage"]:
                        drive_serial = temp_dict["Storage"][str(drive)]["SerialNumber"]
                        data = drive_serial.upper()
                        if data in df_sn.values:
                            print("Found serial in DB for storage no. " + str(drive))
                            temp_dict[component][str(drive)]["SMC DB handshake"] = "True"
                        elif data != "N/A" and data not in df_sn.values:
                            all_components_accounted_for = False
                            temp_dict[component][str(drive)]["SMC DB handshake"] = "False"
                            print("Storage")
                        elif data == "N/A" or data == "":
                            temp_dict[component][str(drive)]["SMC DB handshake"] = "TBD"
                    collection.update_one({"Hostname":i[2]},{"$set":temp_dict})   
                elif component == "System":
                    temp_dict = {component:entry[component]}
                    for system in temp_dict[component]:
                        sys_serial = temp_dict[component][str(system)]["Serial Number"]
                        data = sys_serial.upper()
                        if data in df_sn.values:
                            print("Found serial in DB for system no. " + str(system))
                            temp_dict[component][str(system)]["SMC DB handshake"] = "True"
                        elif data != "N/A" and data not in df_sn.values:
                            all_components_accounted_for = False
                            temp_dict[component][str(system)]["SMC DB handshake"] = "False"
                            print("System")
                        elif data == "N/A" or data == "":
                            temp_dict[component][str(system)]["SMC DB handshake"] = "TBD"
                    collection.update_one({"Hostname":i[2]},{"$set":temp_dict})
                elif component == "Graphics":
                    temp_dict = {component:entry[component]}
                    for gpu in temp_dict[component]["GPU"]:
                        gpu_serial = temp_dict[component]["GPU"][str(gpu)]["Serial No."]
                        data = gpu_serial.upper()
                        if data in df_sn.values:
                            print("Found serial in DB for GPU no. " + str(gpu))
                            temp_dict[component]["GPU"][str(gpu)]["SMC DB handshake"] = "True"
                        elif data != "N/A" and data not in df_sn.values:
                            all_components_accounted_for = False
                            temp_dict[component]["GPU"][str(gpu)]["SMC DB handshake"] = "False"
                            print("GPU")
                        elif data == "N/A" or data == "":
                            temp_dict[component][str(gpu)]["SMC DB handshake"] = "TBD"
                    collection.update_one({"Hostname":i[2]},{"$set":temp_dict})
                if all_components_accounted_for == True:
                    SMC_check = {"SMC DB approval" : "True"}
                else:
                    SMC_check = {"SMC DB approval" : "False"}
                collection.update_one({"Hostname":i[2]},{"$set":SMC_check})                
