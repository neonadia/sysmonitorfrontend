import pandas as pd
import numpy as np
import os
import json
from pandas import ExcelWriter
import pymongo
import sys
mongoport = int(os.environ['MONGOPORT'])
client = pymongo.MongoClient('localhost', mongoport)
db = client.redfish
collection = db.hw_data
### Get hostname from input file (.csv), insert dash to reflect, and get bmc_ip list
df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
hostname_list = df_pwd['mac']
new_hostname_list = []
for i in hostname_list:
    if ":" in i:
        new = i.replace(":","-")
        new_hostname_list.append(new.lower())
    elif ":" not in i and "-" not in i: 
        new = ""
        for x in range(len(i)):
            if x == 2 or x == 4 or x == 6 or x == 8 or x == 10:
                new += "-"
                new += i[x]
            else:
                new += i[x]
        new_hostname_list.append(new.lower())
inputhosts = new_hostname_list
del new_hostname_list
bmc_ips = list(df_pwd['ip']) 


# inputdir = "/app/RACK/"  i.e example path
directory = os.environ['UPLOADPATH']
# inputdir = directory + "/hw_data/"
for x in os.listdir(directory):
    if 'hw_data' in x:
        if os.path.isdir(directory + x):
            inputdir = directory + x
##### FIND SUB DIRECTORIES #################
all_files = {}
try:
    for dirname in os.listdir(inputdir):
        if os.path.isdir(inputdir+'/' +dirname) and "hw_info" in dirname:
            all_files[dirname] = []
            for filename in os.listdir(inputdir+"/"+dirname):
                if "info" in filename:
                    #print(inputdir+ "/" + dirname + "/" +filename)
                    all_files[dirname].append(inputdir+ "/" + dirname + "/" +filename)
except Exception as e:
    print("Cannot find folder with hardware data, please make sure folder exists and contains (hw_data) in the name",file=sys.stderr,flush = True)
    print("Error msg: " + str(e),file=sys.stderr,flush = True)


#### Configuration variables
OS = ""
GPU = ""
found = False
for file in os.listdir(inputdir):
    if "hw.conf" in file and os.path.exists(inputdir + "/" + file):
        print("Found configuration file",flush=True)
        with open(inputdir + "/" + file ,'r') as f:
            content = f.read()
            lines = content.split("\n")
            for i in lines:
                if "OS" in i:
                    OS = i.split("=")[1]
                elif "GPU" in i:
                    GPU = i.split("=")[1]
        if OS == "" or GPU == "":
            found = False
            print("Missing one or more variables in conf file",file=sys.stderr,flush=True)
            break
        else:
            found = True
            break

print("'found' is :" + str(found), file=sys.stdout, flush=True)
print(OS + " " + GPU, file=sys.stdout, flush=True) #For debug

##### GET HOST NAMES FROM DIRECTORIES and Parse through data
if found:
    if OS == "ubuntu" or OS == 'centos':
        print("Parsing hw info for ubuntu...", flush=True)
        for key in all_files.keys():
            hostname = str(key).split("_")[2]
            item = collection.find({},{"Hostname":1,"_id":0})
            hostlist = list(item)
            if len(hostlist) == 0:
                for i in range(len(inputhosts)):
                        if inputhosts[i] == hostname:
                            collection.insert_one({"Hostname":hostname,'bmc_ip':bmc_ips[i]})
            else:
                found = False
                for i in range(len(hostlist)):
                    temp_dict = hostlist[i]
                    temp_name = temp_dict["Hostname"]
                    if hostname == temp_name:
                        found = True
                if not found:
                    for i in range(len(inputhosts)):
                        if inputhosts[i] == hostname:
                            collection.insert_one({"Hostname":hostname,'bmc_ip':bmc_ips[i]})

            for file in all_files[key]:
                ######## PARSE CPU HARDWARE DATA
                # cpu info parser
                if 'cpu' in file and 'json' in file:
                    df_cpu_single = pd.read_json(file)
                    dict_cpu_cur = {}
                    for i in df_cpu_single['lscpu']:
                        dict_cpu_cur[i['field'].split(":")[0]] = i['data']
                    cpu_dict = {"CPU":dict_cpu_cur}
                    collection.update_one({"Hostname":hostname},{"$set":cpu_dict})
        #             collection.insert_one({"Hostname":hostname,"CPU":cpu_dict})
                ######### PARSE STORAGE DATA (from nvme-cli in json format)
                # # Opening JSON file
                elif 'nvme' in file and 'json' in file:
                    with open(file) as json_file:
                        nvme_data = json.load(json_file)
                        storage_dict = {"Storage":{}}
                        i = 0
                        for device in nvme_data["Devices"]:
                            storage_dict["Storage"][str(i)] = device
                            i+= 1
                        ### Get dict data structure for mongo insertion
                    collection.update_one({"Hostname":hostname},{"$set":storage_dict}) 
                ######## PARSE RAM specs ###########
                elif 'memory' in file and 'txt' in file:
                    with open(file,"r") as cur_file:
                        lines = cur_file.readlines()######## Get Memory data (dmidecode type 17)
                        serial_nums = []
                        size = []
                        con_mem_speed = []
                        max_speed = []
                        manu = []
                        type = []
                        pn = []
                        size = []
                        for line in lines:
                            if 'Size:' in line and 'Volatile' not in line and 'Cache' not in line and 'Logical' not in line:
                                size.append(line.split(":")[1].strip())
                            elif 'Serial Number' in line:
                                serial_nums.append(line.split(":")[1].strip())
                            elif 'Configured Memory Speed' in line:
                                con_mem_speed.append(line.split(":")[1].strip())
                            elif 'Speed' in line:
                                max_speed.append(line.split(":")[1].strip())
                            elif 'Manufacturer' in line and 'Module' not in line and 'Memory' not in line:
                                manu.append(line.split(":")[1].strip())
                            elif 'Part Number' in line:
                                pn.append(line.split(":")[1].strip())
                            elif 'Type' in line and 'Detail' not in line and "Error" not in line:
                                type.append(line.split(":")[1].strip())
                            elif 'Number Of Devices' in line:
                                dimms_no = line.split(":")[1].strip()
                        gb = 0
                        for i in size:
                            gb += int(i.split(" ")[0])
                        total_mem = gb
                        memory_data = {"Memory":{"DIMMS":dimms_no,"Total Memory":str(total_mem),"Slots": {}}}
                        for i in range(len(size)):
                            memory_data["Memory"]["Slots"]["DIMM" + str(i)] = {"Manufacturer" : manu[i],"Serial No.":serial_nums[i],"Part No.": pn[i],"Max Speed":max_speed[i],"Configured Speed": con_mem_speed[i],"Size":size[i],"Type":type[i]}

                        # memory_data = {"Memory":{"Manufacturer":manu,"Part Number":pn,"Serial numbers":serial_nums,"DIMMS":dimms_no,"Size":size,"Total Memory":str(total_mem),"Type":type,"Max Speed": max_speed,"Configured Speed":con_mem_speed}}
                    collection.update_one({"Hostname":hostname},{"$set":memory_data})
                elif 'network' in file and 'txt' in file:
                    with open(file,"r") as cur_file:
                        lines = cur_file.readlines()
                        net_dict = {"NICS":{}}
                        i = 0
                        for line in lines:
                            if len(line) != 0:
                                bus = line.split(" ")[0].strip()
                                name = line.split("r:")[1].strip()
                                net_dict["NICS"][str(i)] = {"PCIe Bus" : bus, "Name" : name} 
                                i += 1
                    collection.update_one({"Hostname":hostname},{"$set":net_dict})
                elif 'gpu' in file and 'csv' in file:
                    if GPU == "AMD" or GPU == "amd":
                        print("Parsing for AMD gpu hw info.....",flush=True)
                        df_gpu_all = []
                        # read the driver version
                        with open(file,"r") as cur_file:            
                            lines = cur_file.readlines()
                            columns = {}
                            card_counter = 0
                            csv_lines = []
                            for i, line in enumerate(lines):
                                if i == 1:
                                    driver_version = line.split(',')[1].replace('\n','')
                                    gpu_dict = {'Graphics':{"Number of GPUs" : 0,"Manufacturer":"AMD", "Driver Version":driver_version,"GPU":{}}}
                                elif i > 2:
                                    if "device" in line:
                                        headers = line.split(",")
                                        for iter in range(len(headers)):
                                            if 'device'in headers[iter]:
                                                columns.update({'Device':iter});
                                            elif 'GPU ID' in headers[iter]:
                                                columns.update({"GPU ID":iter})
                                            elif 'VBIOS' in headers[iter]:
                                                columns.update({"VBIOS":iter})
                                            elif 'Max Graphics Package Power (W)' in headers[iter]:
                                                columns.update({"Max Power(W)":iter})
                                            elif 'GPU memory vendor' in headers[iter]:
                                                columns.update({"Memory Vendor":iter})
                                            elif 'Serial Number' in headers[iter]:
                                                columns.update({'Serial No.':iter})
                                            elif 'PCI Bus' in headers[iter]:
                                                columns.update({"PCI Bus":iter})
                                            elif 'Card series' in headers[iter]:
                                                columns.update({'Series':iter})
                                            elif 'Card model' in headers[iter]:
                                                columns.update({"Model":iter})
                                            elif 'Card vendor' in headers[iter]:
                                                columns.update({"Vendor":iter})
                                            elif 'Card SKU' in headers[iter]:
                                                columns.update({"SKU":iter})
                                            elif "Valid sclk" in headers[iter]:
                                                columns.update({"SClock":iter})
                                            elif "Valid mclk" in headers[iter]:
                                                columns.update({"Mem Clock":iter})
                                    elif 'card' in line:
                                        csv_lines.append(line)
                            a = 0
                        for i in csv_lines:
                            i = i.split(',')
                            device = i[int(columns['Device'])]
                            gpu_id = i[int(columns['GPU ID'])]
                            vbios = i[int(columns['VBIOS'])]
                            max_pwr = i[int(columns['Max Power(W)'])]
                            mem_vendor = i[int(columns['Memory Vendor'])]
                            serial = i[int(columns['Serial No.'])]
                            pci = i[int(columns['PCI Bus'])]
                            series = i[int(columns['Series'])]
                            model = i[int(columns['Model'])]
                            vendor = i[int(columns['Vendor'])]
                            sku = i[int(columns['SKU'])]
                            sclk = i[int(columns['SClock'])]
                            mclk = i[int(columns['Mem Clock'])]
                            gpu_dict['Graphics']['GPU'][str(a)] = {"Device":device,'GPU Id':gpu_id,'VBIOS':vbios,'Max Power(W)':max_pwr,'Serial No.':serial,'PCI Bus':pci,"Series":series,"Model":model,'Vendor':vendor,"SKU":sku,'SClock':sclk,'Mem Clock':mclk} 
                            a+=1
                        gpu_dict['Graphics']['Number of GPUs'] = a
                        collection.update_one({"Hostname":hostname},{"$set":gpu_dict})      

                elif 'psu' in file and 'txt' in file:
                    template = {'MAC':[],'PWS Serial Number':[],'PWS Module Number':[],'Input Power':[],'Main Output Power':[],'Status':[]}
                    with open(file,"r") as cur_file:
                        lines = cur_file.readlines()
                        modules = 0
                        serial_numbers = []
                        module_numbers = []
                        input_power = []
                        output_power = []
                        output_current = []
                        output_voltage = []
                        status = []
                        input_current = []
                        input_voltage = []

                        for line in lines:
                            if 'Item' in line:
                                modules += 1
                            elif 'PWS Serial Number' in line:
                                serial_numbers.append(line.split("|")[1].strip())
                            elif 'PWS Module Number' in line:
                                module_numbers.append(line.split("|")[1].strip())
                            elif 'Input Power' in line:
                                input_power.append(line.split("|")[1].strip())
                            elif 'Main Output Power' in line:
                                output_power.append(line.split("|")[1].strip())
                            elif 'Main Output Current' in line:
                                output_current.append(line.split("|")[1].strip())
                            elif 'Main Output Voltage' in line:
                                output_voltage.append(line.split("|")[1].strip())
                            elif 'Input Voltage' in line:
                                input_voltage.append(line.split("|")[1].strip())
                            elif 'Input Current' in line:
                                input_current.append(line.split("|")[1].strip())
                            elif 'Status' in line:
                                status.append(line.split("|")[1].strip())
                        psu_dict = {"PSU":{"Number of PSUs":modules}} 
                        for i in range(modules):
                            psu_dict["PSU"][str(i)] = {"Serial No.": serial_numbers[i],"Status":status[i],"Module No.":module_numbers[i],"Input":{"Power":input_power[i],"Current":input_current[i],"Voltage":input_voltage[i]},"Output":{"Power":output_power[i],"Current":output_current[i],"Voltage":output_voltage[i]}}    
                    collection.update_one({"Hostname":hostname},{"$set":psu_dict})   
                elif 'fan' in file:
                    with open(file,"r") as cur_file:
                        fans =  {"FANS" : {}}
                        lines = cur_file.readlines()
                        i = 0
                        for line in lines:
                            if "FAN" in line and "OS" not in line:
                                fans["FANS"][str(i)] = {"name": line.split("|")[0].strip(),'status' :line.split("|")[2].strip(),"rpm":line.split("|")[1].strip() }
                                i += 1
                        collection.update_one({"Hostname":hostname},{"$set":fans})
                

else:
    print("Missing Configuration file",file=sys.stderr,flush=True)