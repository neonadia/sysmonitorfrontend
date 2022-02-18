from re import S
import pandas as pd
import os
import json
import pymongo
import sys
import math
import xml.etree.ElementTree as ET
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
            if x == 2 or x == 4 or x == 6 or x == 8 or x == 10:
                new += "-"
                new += i[x]
            else:
                new += i[x]
        new_hostname_list.append(new.lower())
inputhosts = new_hostname_list
bmc_ips = list(df_pwd['ip'])  #### Get BMC_IPs from pwd#.txt
# inputdir = "/app/RACK/"  i.e example path
directory = os.environ['UPLOADPATH'] #### Usually /app/<YOUR FOLDER FROM WHICH YOU DECLARED IN auto.env
# inputdir = directory + "/hw_data/" Navigate to your hardware logs folder. Needs to contain "hw_data" in the name in order to be flagged
for x in os.listdir(directory):
    if 'hw_data' in x:
        if os.path.isdir(directory + x):
            inputdir = directory + x
##### FIND DIRECTORIES #################
all_files = {} #### Create dictionary of the hw_data directory to map all the subdirectories and files
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
        if OS == "":
            found = False
            print("Missing one or more variables in conf file",file=sys.stderr,flush=True)
            break
        elif OS != "" and GPU == "":
            found = True
            print("Missing GPU variable in conf file but that is OK",flush=True)
        else:
            found = True
            break
print("'found' is :" + str(found), file=sys.stdout, flush=True)
print(OS + " " + GPU, file=sys.stdout, flush=True) #For debug
##### GET HOST NAMES FROM DIRECTORIES and Parse through data
if found:
    if OS == "ubuntu" or OS == "centos": #### FOR UBUNTU or CENTOS 
        print("Parsing hw info for..." + OS,flush = True)
        for key in all_files.keys():
            hostname = str(key).split("_")[2]
            item = collection.find({},{"Hostname":1,"_id":0})
            hostlist = list(item)
            if len(hostlist) == 0:######## Search for existing document in mongo DB, if exists delete and create a new empty doc, or create a new empty doc if does not exist.
                found = False
                for i in range(len(inputhosts)):
                        if inputhosts[i] == hostname:
                            collection.insert_one({"Hostname":hostname,'bmc_ip':bmc_ips[i]})
                            found = True
            else:
                found = False
                for i in range(len(hostlist)):
                    if hostname == hostlist[i]["Hostname"]:
                        for j in range(len(inputhosts)):
                            if inputhosts[j] == hostlist[i]["Hostname"]:
                                collection.delete_one({"Hostname":hostname})
                                collection.insert_one({"Hostname":hostname,'bmc_ip':bmc_ips[j]})
                                found = True
                if not found:
                    for i in range(len(inputhosts)):
                        if inputhosts[i] == hostname:
                            collection.insert_one({"Hostname":hostname,'bmc_ip':bmc_ips[i]})
                            found = True
            if found:
                storage_dict = {"Storage":{}} ### Storage entry consists of two seperate file( nvme or hdd). Creating a variable to cover the scope of the following for loop
                for file in all_files[key]:
                    ######## PARSE CPU HARDWARE DATA
                    # cpu info parser
                    if 'cpu' in file:
                        if os.path.getsize(file) != 0: 
                            if 'json' in file:
                                try:
                                    df_cpu_single = pd.read_json(file)
                                except:
                                    cpu_dict = {"CPU":{"Model name":"N/A","Socket(s)":0}}
                                    collection.update_one({"Hostname":hostname},{"$set":cpu_dict})
                                    print("Error: cannot read lscpu json file. Might be empty or wrong format",file=sys.stderr,flush=True )
                                else:
                                    dict_cpu_cur = {}
                                    for i in df_cpu_single['lscpu']:
                                        dict_cpu_cur[i['field'].split(":")[0]] = i['data']
                                    cpu_dict = {"CPU":dict_cpu_cur}
                                    collection.update_one({"Hostname":hostname},{"$set":cpu_dict})
                            elif '.log' in file or '.txt' in file:
                                    cpu_dict = {"CPU":{}}
                                    with open(file,'r') as f:
                                        lines = f.readlines()
                                        for i in lines:
                                            keyData = i.split(":")
                                            cpu_dict['CPU'][keyData[0].strip()] = keyData[1].strip()
                                        collection.update_one({"Hostname":hostname},{"$set":cpu_dict})
                    ######### PARSE STORAGE DATA (from nvme-cli in json format)
                    # # Opening JSON file
                    elif 'nvme' in file and 'json' in file:
                        if os.path.getsize(file) != 0: 
                            with open(file) as json_file:
                                nvme_data = json.load(json_file)
                                i = len(storage_dict["Storage"])
                                for device in nvme_data["Devices"]:
                                    storage_dict["Storage"][str(i)] = device
                                    i += 1
                    elif "hdd" in file and ".log" in file:
                        if os.path.getsize(file) != 0: 
                            with open(file,'r') as log:
                                hdd_data = log.readlines()
                                # locate the disk information
                                read_flag = 0
                                hdd_data_clean = []
                                for line in hdd_data:
                                    if "*-disk" in line: # starting line
                                        read_flag = 1                                    
                                    if read_flag == 1:
                                        hdd_data_clean.append(line)                                    
                                    if "configuration:" in line: # ending line
                                        read_flag = 0                               
                                ModelNumber = []
                                DevicePath = []
                                SerialNumber = []
                                PhysicalSize = []
                                firmware = []
                                for line in hdd_data_clean:
                                    if "product" in line:
                                        ModelNumber.append(line.split(":")[1].strip())
                                    elif "logical name" in line:
                                        DevicePath.append(line.split(":")[1].strip())
                                    elif "serial" in line:
                                        SerialNumber.append(line.split(":")[1].strip())
                                    elif "size" in line and "GiB" in line:
                                        PhysicalSize.append(int(line.split(":")[1].strip().split()[1].strip("(GB)").strip())* 1000000000)
                                    elif "version" in line:
                                        firmware.append(line.split(":")[1].strip())
                                j = len(storage_dict["Storage"])
                                for i in range(len(ModelNumber)):
                                    storage_dict["Storage"][str(j)] = {"DevicePath":DevicePath[i],"ModelNumber" : ModelNumber[i],"Firmware": firmware[i],"SerialNumber":SerialNumber[i],"PhysicalSize":PhysicalSize[i]}
                                    j += 1
                    ######## PARSE RAM specs ###########
                    elif 'memory' in file and 'txt' in file:
                        if os.path.getsize(file) != 0: 
                            with open(file,"r") as cur_file:
                                lines = cur_file.readlines()######## Get Memory data (dmidecode type 17)
                                serial_nums = []
                                size = []
                                con_mem_speed = []
                                max_speed = []
                                manu = []
                                type = []
                                pn = []
                                for line in lines:
                                    # Initialize for all lists, assume the sequency is that 
                                    if 'Memory Device' in line:
                                        size.append("No Module Installed")
                                        serial_nums.append("NO DIMM")
                                        con_mem_speed.append("Unknown")
                                        max_speed.append("Unknown")
                                        manu.append("NO DIMM")
                                        type.append("UNKNOWN")
                                        pn.append("NO DIMM") 
                                        continue
                                    elif 'Size:' in line and 'Volatile' not in line and 'Cache' not in line and 'Logical' not in line:                                        
                                        temp_size = line.split(":")[1].strip()
                                        if "MB" in temp_size:
                                            gb_converter = math.trunc(round(int(temp_size.split(" ")[0]) / 1000,0))
                                            temp_size = str(gb_converter) + " GB"
                                        size[-1] = temp_size
                                        continue
                                    elif 'Serial Number' in line:
                                        serial_nums[-1] = line.split(":")[1].strip()
                                        continue
                                    elif 'Configured Memory Speed' in line or 'Configured Clock Speed' in line:
                                        con_mem_speed[-1] = line.split(":")[1].strip()
                                        continue
                                    elif 'Speed' in line and 'Configured Memory Speed' not in line and 'Configured Clock Speed' not in line:
                                        max_speed[-1] = line.split(":")[1].strip()
                                        continue
                                    elif 'Manufacturer' in line and 'Module' not in line and 'Memory' not in line:
                                        manu[-1] = line.split(":")[1].strip()
                                        continue
                                    elif 'Part Number' in line:
                                        pn[-1] = line.split(":")[1].strip()
                                        continue
                                    elif 'Type' in line and 'Detail' not in line and "Error" not in line:
                                        type[-1] = line.split(":")[1].strip()
                                        continue                                        
                                gb = 0
                                dimms_no = 0
                                for i in size:
                                    if i != "No Module Installed":
                                        dimms_no += 1
                                        gb += int(i.split(" ")[0])
                                total_mem = gb
                                memory_data = {"Memory":{"DIMMS":str(dimms_no),"Total Memory":str(total_mem),"Slots": {}}}
                                for i in range(len(size)):
                                    memory_data["Memory"]["Slots"]["DIMM" + str(i)] = {"Manufacturer" : manu[i],"Serial No.":serial_nums[i],"Part No.": pn[i],"Max Speed":max_speed[i],"Configured Speed": con_mem_speed[i],"Size":size[i],"Type":type[i]}
                                collection.update_one({"Hostname":hostname},{"$set":memory_data})
                    elif 'network' in file and 'xml' in file:
                        try:
                            tree = ET.parse(file)
                        except:
                            print("Could not open xml file for network parsing",file=sys.stderr,flush=True)
                        else:
                            root = tree.getroot()
                            net_dict = {"NICS":{}}
                            pci_bus_nums = []
                            for index,i in enumerate(root):
                                if 'handle' in i.attrib: #### "handle" is attribute in the xml that denotes the PCIe bus, this excludes any virtual network connections.
                                    temp_dict = {'Name':"N/A","Part Number":"N/A","PCIe Bus":"N/A",'Firmware':"N/A","Vendor":"N/A","Serial":"N/A"}
                                    for j in i:
                                        if j.tag == 'product':
                                            temp_dict['Name'] = j.text
                                        elif j.tag == 'businfo':
                                            temp_dict["PCIe Bus"] = j.text.split("@")[1]
                                            pci_bus_nums.append(j.text.split("@")[1])
                                        elif j.tag == "vendor":
                                            temp_dict['Vendor'] = j.text
                                        elif j.tag == 'serial':
                                            temp_dict['MAC'] = j.text
                                        elif j.tag in 'logicalname':
                                            temp_dict["Interface Name"] = j.text
                                    for j in i.find('configuration'):
                                        if j.attrib['id'] == 'firmware':
                                            temp_dict['Firmware'] = j.attrib['value'].split()[0].split(",")[0]
                                    net_dict["NICS"][str(index)] = temp_dict
                            ###### Cross reference nics serial and insert to temporary dictionary before pushing
                            ref_txt = inputdir + "/" + key + "/nic_serial_reference_" + hostname + ".txt"
                            try:
                                with open(ref_txt,"r") as r:
                                    lines = r.readlines()
                                    worker_bus = "" ###Bus number identifies nic card
                                    for x in lines:
                                        if "Ethernet controller" in x: ###If bus number read, switch worker bus to this
                                            for bus_num in pci_bus_nums:
                                                if bus_num.strip("000:") in x.split(" ")[0]:
                                                    worker_bus = bus_num
                                        elif "[PN] Part number" in x:
                                            part_num = x.split(":")[1].strip()
                                            for y in net_dict["NICS"]:
                                                if net_dict["NICS"][str(y)]["PCIe Bus"] == worker_bus: # Cross reference bus number
                                                    net_dict["NICS"][str(y)]["Part Number"] = part_num
                                                    print("Inserting into dictionary: " + worker_bus + " === " + part_num)
                                        elif "[SN] Serial number" in x:
                                            serial_num = x.split(":")[1].strip()
                                            for y in net_dict["NICS"]:
                                                if net_dict["NICS"][str(y)]["PCIe Bus"] == worker_bus: # Cross reference bus number
                                                    net_dict["NICS"][str(y)]["Serial"] = serial_num
                                                    print("Inserting into dictionary: " + worker_bus + " === " + serial_num)
                            except Exception as e:
                                print(e,file=sys.stderr,flush=True)
                            collection.update_one({"Hostname":hostname},{"$set":net_dict})
                    elif 'gpu' in file and 'csv' in file:
                        if os.path.getsize(file) != 0: 
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
                                                        columns.update({'Device':iter})
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
                        if os.path.getsize(file) != 0: 
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
                        if os.path.getsize(file) != 0: 
                            with open(file,"r") as cur_file:
                                fans =  {"FANS" : {}}
                                lines = cur_file.readlines()
                                i = 0
                                for line in lines:
                                    if "FAN" in line and "OS" not in line:
                                        fans["FANS"][str(i)] = {"name": line.split("|")[0].strip(),'status' :line.split("|")[2].strip(),"rpm":line.split("|")[1].strip() }
                                        i += 1
                                collection.update_one({"Hostname":hostname},{"$set":fans})
                    elif 'system' in file and ".log" in file:
                        if os.path.getsize(file) != 0:
                            with open(file,"r") as cur_file:
                                lines = cur_file.readlines()
                                current_component = ""
                                baseboard_num = 0
                                chassis_num = 0
                                system_num = 0
                                system_dict = {"System":{}}
                                chassis_dict = {"Chassis": {}}
                                baseboard_dict = {"Base Board":{}}
                                for i in lines:
                                    if "Information" in i:
                                        if "Base" in i:
                                            current_component = i.split(" ")[0] + " " + i.split(" ")[1]
                                        else:
                                            current_component = i.split(" ")[0]

                                        if current_component == "System":
                                            system_num += 1
                                            system_dict['System'][str(system_num)] = {"Manufacturer":"N/A","Product Name":"N/A","Version":"N/A","Serial Number":"N/A","UUID":"N/A","Family":"N/A","SKU Number":"N/A"}
                                        elif current_component == "Chassis":
                                            chassis_num += 1
                                            chassis_dict["Chassis"][str(chassis_num)] = {"Manufacturer":"N/A","Version":"N/A","Type":"N/A","Serial Number":"N/A"}
                                        else:
                                            baseboard_num += 1
                                            baseboard_dict["Base Board"][str(baseboard_num)] = {"Manufacturer":"N/A","Product Name":"N/A","Version":"N/A","Serial Number":"N/A"}
                                    elif "Manufacturer" in i:
                                        if current_component == "System":
                                            system_dict[current_component][str(system_num)]['Manufacturer'] = i.split(":")[1].strip()
                                        elif current_component == "Chassis":
                                            chassis_dict[current_component][str(chassis_num)]['Manufacturer'] = i.split(":")[1].strip()
                                        elif current_component == "Base Board":
                                            baseboard_dict[current_component][str(baseboard_num)]['Manufacturer'] = i.split(":")[1].strip()
                                    elif "Product Name" in i:
                                        if current_component == "System":
                                            system_dict[current_component][str(system_num)]['Product Name'] = i.split(":")[1].strip()
                                        elif current_component == "Chassis":
                                            chassis_dict[current_component][str(chassis_num)]['Product Name'] = i.split(":")[1].strip()
                                        elif current_component == "Base Board":
                                            baseboard_dict[current_component][str(baseboard_num)]['Product Name'] = i.split(":")[1].strip()
                                    elif "Version" in i:
                                        if current_component == "System":
                                            system_dict[current_component][str(system_num)]['Version'] = i.split(":")[1].strip()
                                        elif current_component == "Chassis":
                                            chassis_dict[current_component][str(chassis_num)]['Version'] = i.split(":")[1].strip()
                                        elif current_component == "Base Board":
                                            baseboard_dict[current_component][str(baseboard_num)]['Version'] = i.split(":")[1].strip()
                                    elif "Serial Number" in i:
                                        if current_component == "System":
                                            system_dict[current_component][str(system_num)]['Serial Number'] = i.split(":")[1].strip()
                                        elif current_component == "Chassis":
                                            chassis_dict[current_component][str(chassis_num)]['Serial Number'] = i.split(":")[1].strip()
                                        elif current_component == "Base Board":
                                            baseboard_dict[current_component][str(baseboard_num)]['Serial Number'] = i.split(":")[1].strip()
                                    elif "UUID" in i:
                                        system_dict[current_component][str(system_num)]['UUID'] = i.split(":")[1].strip()
                                    elif "SKU Number" in i:
                                        system_dict[current_component][str(system_num)]['SKU Number'] = i.split(":")[1].strip()
                                    elif "Family" in i:
                                        system_dict[current_component][str(system_num)]['Family'] = i.split(":")[1].strip()
                                    elif "Type" in i and "Wake-up" not in i:
                                        chassis_dict[current_component][str(system_num)]['Type'] = i.split(":")[1].strip()

                                collection.update_one({"Hostname":hostname},{"$set":system_dict})
                                collection.update_one({"Hostname":hostname},{"$set":chassis_dict})
                                collection.update_one({"Hostname":hostname},{"$set":baseboard_dict})
                if len(storage_dict["Storage"]) != 0: ##### If no storage logs were processed, do not update with empty dictionary.
                    collection.update_one({"Hostname":hostname},{"$set":storage_dict})
                    del storage_dict
    else:
        print("No compatible OS declared, current support is CentOS or Ubuntu",file=sys.stderr)
else:
    print("Missing Configuration file",file=sys.stderr)

    