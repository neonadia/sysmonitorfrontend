from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle, TA_CENTER
from reportlab.lib.units import inch, mm, cm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, SimpleDocTemplate, Spacer, Image, KeepTogether, LongTable, TableStyle, PageBreak
from pymongo import MongoClient
from reportlab.lib import utils
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors
from reportlab.lib.colors import PCMYKColor, HexColor, blue, red, black, darkgrey, grey
from reportlab.graphics.shapes import Drawing, Line
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.textlabels import Label
from reportlab.platypus.flowables import HRFlowable, Image
from benchmark_parser import clean_mac
from get_data import find_min_max_rack
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os
import pandas as pd
import sys
import math
import datetime
import pymongo
import string
import gridfs
import cv2
import numpy as np
from subprocess import Popen, PIPE

# 0 : no issue/conclusion section
# 1 : add issue/conclusion section
has_issue = 0
has_conclusion = 0
has_notes = 0
has_l12_metrics= 1
n=6 # number of bars for each plot

class ConditionalSpacer(Spacer):

    def wrap(self, availWidth, availHeight):
        height = min(self.height, availHeight-1e-8)
        return (availWidth, height)

def printf(data):
    print(data, flush=True)

def getSerialNumberFromIP(ip,opt):
    df_all = pd.read_csv(os.environ['UPLOADPATH'] + os.environ['RACKNAME']+'.csv')
    if opt == 0:
        bmc_ip = df_all[df_all['OS_IP'] == ip]['IPMI_IP'].values[0]
    elif opt == 1:
        bmc_ip = ip
    # first search from hw_data collection 
    if 'hw_data' in list_of_collections:    
        result_hw = db.hw_data.find_one({"bmc_ip": bmc_ip},{"System.1.Serial Number":1,"_id":0})
        if result_hw != None and result_hw['System']['1']['Serial Number'] != "N/A" and result_hw['System']['1']['Serial Number'] != "NA":
            return result_hw['System']['1']['Serial Number']
        else:
            printf(f'Cluster Rreport Warning: cannot get serial number for {bmc_ip} from database (DMIDECODE), will try redfish API')
    # Then search from server collection, if not search from input csv file
    result_server = collection.find_one({"BMC_IP": bmc_ip},{"Systems.1.SerialNumber":1,"_id":0})    
    if result_server == None:
        printf(f'Cluster Rreport Warning: cannot get any information for {bmc_ip} from database (redfish API), reading it from csv file')
        return getSerialNumberFromFile(bmc_ip,1) # opt 1 means using bmc ip, get SN from csv input file when database has NA or N/A    
    elif result_server['Systems']['1']['SerialNumber'] == 'NA' or result_server['Systems']['1']['SerialNumber'] == 'N/A':
        printf(f'Cluster Rreport Warning: cannot get serial number for {bmc_ip} from database (redfish API), reading it from csv file')
        return getSerialNumberFromFile(bmc_ip,1) # opt 1 means using bmc ip, get SN from csv input file when database has NA or N/A
    else:
        return result_server['Systems']['1']['SerialNumber']
            
def getSerialNumberFromFile(ip,opt):
    df_all = pd.read_csv(os.environ['UPLOADPATH'] + os.environ['RACKNAME']+'.csv')
    if opt == 0:
        return(df_all[df_all['OS_IP'] == ip]['System S/N'].values[0])
    elif opt == 1:
        return(df_all[df_all['IPMI_IP'] == ip]['System S/N'].values[0])

def cleanUnits(unitsList, opt):
    if not all(x == unitsList[0] for x in unitsList): 
        return('Invalid Units!')
    if opt == 'all':
        if all(x == unitsList[0][0] for x in unitsList[0]):
            return unitsList[0][0]
        else:
            return ', '.join(unitsList[0])
    else:
        return unitsList[0][opt]

def create_table_colors(table_length,header_color,other_color):
    table_colors_list = []
    for i in range(table_length):
        if i == 0:
            table_colors_list.append(header_color)
        else:
            table_colors_list.append(other_color)
    return tuple(table_colors_list)

def get_string_width(st):
    size = 0 # in milinches
    for s in st:
        if s in 'lij|\' ': size += 37
        elif s in '![]fI.,:;/\\t': size += 50
        elif s in '`-(){}r"': size += 60
        elif s in '*^zcsJkvxy': size += 85
        elif s in 'aebdhnopqug#$L+<>=?_~FZT' + string.digits: size += 95
        elif s in 'BSPEAKVXY&UwNRCHD': size += 112
        elif s in 'QGOMm%W@': size += 135
        else: size += 50
    return size * 6 / 1000.0 # Convert to picas

def auto_font_size(input_string,seperator_html, seperator_real):
    input_string = input_string.replace(seperator_html,seperator_real)
    if get_string_width(input_string) <= 50:
        font_size = 7
    else:
        font_size = 50/get_string_width(input_string) * 7
    if font_size < 5:
        font_size = 5
    return font_size*0.8

def get_image(path, height=1*cm, width=1*cm): # maximize the size of photo
    img = utils.ImageReader(path)
    iw, ih = img.getSize()
    aspect = ih / float(iw)
    if width*aspect > height:
        new_width = height/aspect
        new_height = height
    else:
        new_width = width
        new_height = width*aspect        
    return Image(path, width=new_width, height=new_height)

def is_bmc_static(bmc_ip, password):
    if os.environ['POWERDISP'] != 'ON' and os.environ['UIDDISP'] != 'ON':
        return 3
    process = Popen(f"ipmitool -H {bmc_ip} -U ADMIN -P {password} lan print | grep 'IP Address Source'", shell=True, stdout=PIPE, stderr=PIPE)
    try:
        stdout, stderr = process.communicate(timeout=5)
    except Exception as e:
        printf(e)
        return 3
    output_string = stdout.decode("utf-8").lower()
    if 'static' in output_string:
        return 0
    elif 'dhcp' in output_string:
        return 1
    printf('----------------is_bmc_static stdout--------------------')
    printf(stdout.decode("utf-8"))
    printf('----------------is_bmc_static stderr--------------------')
    printf(stderr.decode("utf-8"))
    printf('----------------is_bmc_static end--------------------')
    return 2

mongoport = int(os.environ['MONGOPORT']) # using in jupyter: 8888
rackname = os.environ['RACKNAME'].upper() 
client = MongoClient('localhost', mongoport) # using in jupyter: change localhost to 172.27.28.15
db = client.redfish
collection = db.servers
collection2 = db.udp
collection3 = db.monitor
fs = gridfs.GridFS(db)
list_of_collections = db.list_collection_names()
bmc_ip = []
timestamp = []
serialNumber = []
modelNumber = []
bmcVersion = []
CPLDVersion = []
biosVersion = []
bmc_event = []
MacAddress = []
bmcMacAddress = []
benchmark_node = []
benchmark_data = []
benchmark_unit = []
result_name = []
benchmark_name = {}
saa_info = []

for data in list(collection2.find({})):
    if data['star'] != 1:
        continue
    elif data['benchmark'] not in benchmark_name:
        benchmark_name[data['benchmark']] = 1
    else:
        benchmark_name[data['benchmark']] += 1

benchmark_map = {}
for key, value in benchmark_name.items():
    for i in range(math.ceil(value/n)):
        if i < math.ceil(value/n) -1:
            benchmark_map[key+ '|' + str(i+1)] = list(range(i*n,i*n+n))
        else:
            benchmark_map[key+ '|' + str(i+1)] = list(range(i*n,value))

for i in range(len(benchmark_map)):
    benchmark_node.append([])
    benchmark_data.append(('N/A'))
    benchmark_unit.append([])
    result_name.append([])

printf("#####################benchmark_map#####################")
printf(benchmark_map)
printf("=======================================================")

for i, bm in enumerate(list(benchmark_map.keys())):
    counter = 0
    skip = benchmark_map[bm][0]
    cur_benchmark_data = []
    for data in list(collection2.find({})):
        if data['star'] == 1 and data['benchmark'] == bm.split('|')[0] and skip != 0:
            skip -= 1
            continue
        elif data['star'] == 1 and data['benchmark'] == bm.split('|')[0] and counter < len(benchmark_map[bm]):
            try:
                benchmark_node[i].append(getSerialNumberFromIP(data['os_ip'],0))
            except:
                benchmark_node[i].append('N/A')
            try:
                cur_benchmark_data.append(data['raw_result'])
            except:
                cur_benchmark_data.append('N/A')
            try: 
                benchmark_unit[i].append(data['unit'])
            except:
                benchmark_unit[i].append('N/A')
            try:
                result_name[i].append(data['result_name'])
            except:
                result_name[i].append('N/A')
            counter += 1
    cur_benchmark_data = list(map(list, zip(*cur_benchmark_data)))
    cur_benchmark_tuple = []
    for oneList in cur_benchmark_data:
        cur_benchmark_tuple.append(tuple(oneList))
    benchmark_data[i] = cur_benchmark_tuple
 
for i in collection.find({}):
    try:
        bmc_ip.append(i['BMC_IP'])
    except:
        bmc_ip.append('N/A')
    try:
        timestamp.append(i['Datetime'])
    except:
        timestamp.append('N/A')
    try:
        try:
            bmcMacAddress.append(i['Managers']['1']['EthernetInterfaces']['1']['MACAddress'])
        except:
            bmcMacAddress.append(i['UUID'][24:])
    except:
        bmcMacAddress.append('N/A')
    try:
        serialNumber.append(getSerialNumberFromIP(i['BMC_IP'],1))
    except:
        serialNumber.append('N/A')
    try:
        modelNumber.append(i['Systems']['1']['Model'])
    except:
        modelNumber.append('N/A')
    try:
        bmcVersion.append(i['UpdateService']['SmcFirmwareInventory']['1']['Version'])
    except:
        bmcVersion.append('N/A')
    try:
        biosVersion.append(i['UpdateService']['SmcFirmwareInventory']['2']['Version'])
    except:
        biosVersion.append('N/A')
    try:
        saa_info.append(i['SAA'])
    except:
        saa_info.append('N/A')
    try:
        CPLDVersion.append(i['CPLDVersion'])
    except:
        CPLDVersion.append('N/A')
        
serialNum, processorModel, processorCount, totalMemory, memoryPN, memoryCount, driveModel, driveCount = ([] for i in range(8))

for j in collection.find({}):
    try:
        serialNum.append(getSerialNumberFromIP(j['BMC_IP'],1))
    except:
        serialNum.append('N/A')
    try:
        processorModel.append(j['Systems']['1']['CPU']['1']['Model'])
    except:
        processorModel.append('N/A')
    try:
        processorCount.append(j['Systems']['1']['ProcessorSummary']['Count'])
    except:
        processorCount.append('N/A')
    try:
        totalMemory.append(j['Systems']['1']['MemorySummary']['TotalSystemMemoryGiB'])
    except:
        totalMemory.append('N/A')
    try:
        memoryPN.append(j['Systems']['1']['Memory']['1']['PartNumber'])
    except:
        memoryPN.append('N/A')
    try:
        memoryCount.append(len(j['Systems']['1']['Memory']))
    except:
        memoryCount.append('N/A')
    try:
        diff_drive_model = []
        for cur_key in j['Systems']['1']['SimpleStorage'].keys():
            for cur_device in j['Systems']['1']['SimpleStorage'][cur_key]['Devices']:
                if cur_device['Model'] not in diff_drive_model:
                    diff_drive_model.append(cur_device['Model'])
        driveModel.append(' & '.join(diff_drive_model))
    except Exception as e:
        printf(e)
        driveModel.append('N/A')
    try:
        total_drive_count = 0
        for cur_key in j['Systems']['1']['SimpleStorage'].keys():
            total_drive_count += len(j['Systems']['1']['SimpleStorage'][cur_key]['Devices'])
        driveCount.append(total_drive_count)
    except:
        driveCount.append('N/A')

df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
bmc_ip_table = []
for ip in bmc_ip:
    if 'N/A' not in bmc_ip:
        MacAddress.append(df_pwd[df_pwd['ip'] == ip]['mac'].values[0])
    else:
        MacAddress.append('N/A')
    bmc_pwd = df_pwd[df_pwd['ip'] == ip]['pwd'].values[0]
    if is_bmc_static(ip, bmc_pwd) == 0:
        bmc_ip_table.append(ip)
    elif is_bmc_static(ip, bmc_pwd) == 1:
        bmc_ip_table.append('DHCP')
    elif is_bmc_static(ip, bmc_pwd) == 2:
        bmc_ip_table.append(ip + '*')
    else:
        bmc_ip_table.append(ip + '**')    

res = [list(i) for i in zip(serialNumber, bmcMacAddress, modelNumber, CPLDVersion, biosVersion, bmcVersion, timestamp)]
res2 = [list(j) for j in zip(serialNum, processorModel, processorCount, totalMemory, memoryPN, memoryCount, driveModel, driveCount)]

try:
    max_vals, min_vals, max_dates, min_dates, avg_vals, all_count,  elapsed_hour, good_count, zero_count, last_date, sensor_name  =\
    find_min_max_rack("1", "PowerControl", "PowerConsumedWatts", 9999, bmc_ip)
    df_power = pd.DataFrame({"Serial Number":serialNumber,"Max":max_vals,"Min":min_vals})
    unit = 'W'
    Title = 'PowerConsumedWatts'
except Exception as e:
    df_power = -1
    print('Failed to find Power Consumption in the database: ' + str(e), flush=True)

if 'N/A' not in bmc_ip:
    temp_id = ["1","2","3","4","5","6"] # first 6 temp sensor
    temp_keys = ["CPU","Inlet","System","PLX","Peripheral","GPU","FPGA","ASIC"] # other sensors FPGA and ASIC are intel habana GPU
    # get temperature  data
    data_entries = []
    for i in bmc_ip:
        data_entries.append(collection3.find({"BMC_IP": i}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "Temperatures": 1}))

    # find temperature sensor name with id
    temp_sensor_name = []
    temp_id_sort = [] 
    for j in data_entries[0]: # one bmc ip data 
        for k in j['Temperatures'].keys(): # one datetime data
            for cid in temp_id: # seach through all id:
                if k == cid and k not in temp_id_sort:
                    temp_sensor_name.append(j['Temperatures'][k]['Name'])
                    temp_id_sort.append(cid)
                    break
                else:
                    for temp_key in temp_keys: 
                        if temp_key in j['Temperatures'][k]['Name'] and k not in temp_id_sort: # if not match cid, search from temp_keys
                            temp_sensor_name.append(j['Temperatures'][k]['Name'])
                            temp_id_sort.append(k)
                            break
        break # one bmc ip's data is enough 
    printf(temp_sensor_name)
    printf(temp_id_sort)
    # create a dataframe list for temp sensors
    df_temp_list = []
    unit_list = []
    sensor_name_list = []
    for sensor_id, sensor_name in zip(temp_id_sort, temp_sensor_name):
        unit_list.append('Celsius')
        sensor_name_list.append(sensor_name)
        try:
            max_vals, min_vals, max_dates, min_dates, avg_vals, all_count,  elapsed_hour, good_count, zero_count, last_date, sensor_name =\
            find_min_max_rack(sensor_id, "Temperatures", "ReadingCelsius", 9999, bmc_ip)
            df_temp_list.append(pd.DataFrame({"Serial Number":serialNumber,"Max":max_vals,"Min":min_vals}))
            printf(df_temp_list[-1])
        except Exception as e:
            df_temp_list.append(-1)
            printf('Failed to find ' + sensor_name + ' in the database: ' + str(e))

#### Code to fetch OS LEVEL hardware data from database
all_hw_data = []
if 'hw_data' in list_of_collections:
    for item in db.hw_data.find({}):
        all_hw_data.append(item)

parsed_data = []
template_data = {'bmc_ip':'N/A','mac':'N/A',\
                 'system_model':'N/A','motherboard_model':'N/A',\
                 'cpu_model':'N/A','cpu_num':'0','cpu_note':'N/A',\
                 'mem_model':'N/A','mem_num':'0','mem_note':'N/A',\
                 'gpu_model':'N/A','gpu_num':'0','gpu_note':'N/A',\
                 'hd_model':'N/A','hd_num':'0','hd_note':'N/A',\
                 'nic_model':'N/A','nic_num':'0','nic_note':'N/A',\
                 'power_model':'N/A','power_num':'0','power_note':'N/A',\
                 'fan_model':'N/A','fan_num':'0','fan_note':'N/A'\
                }
topo_files = {}
#parsed_data = [template_data for i in range(len(all_hw_data))]
for item in all_hw_data:
    #print(item['Hostname'])
    parsed_data.append(template_data.copy()) # if not using copy(), all the dicts are the same reference
    if 'Hostname' in item:
        parsed_data[-1]['mac'] = item['Hostname'].replace('-','').replace(':','')
    if 'bmc_ip' in item:
        parsed_data[-1]['bmc_ip'] = item['bmc_ip']
    if 'System' in item:
        for system_index in item['System']:
            if 'Product Name' in item['System'][system_index]:
                parsed_data[-1]['system_model'] = item['System'][system_index]['Product Name']
                break    
    if 'Base Board' in item:
        for board_index in item['Base Board']:
            if 'Product Name' in item['Base Board'][board_index]:
                parsed_data[-1]['motherboard_model'] = item['Base Board'][board_index]['Product Name']
                break    
    if 'CPU' in item:
        if 'Model name' in item['CPU']:
            parsed_data[-1]['cpu_model'] = item['CPU']['Model name']
        if 'Socket(s)' in item['CPU']:
            parsed_data[-1]['cpu_num'] = item['CPU']['Socket(s)']
        if 'Core(s) per socket' in item['CPU']:
            parsed_data[-1]['cpu_note'] = parsed_data[-1]['cpu_note'].replace('N/A','')
            parsed_data[-1]['cpu_note'] += item['CPU']['Core(s) per socket'] + ' Cores '
        if 'Thread(s) per core' in item['CPU']:
            parsed_data[-1]['cpu_note'] = parsed_data[-1]['cpu_note'].replace('N/A','')
            parsed_data[-1]['cpu_note'] += item['CPU']['Thread(s) per core'] + ' Thread(s) per core'
        parsed_data[-1]['cpu_note'] = parsed_data[-1]['cpu_note'].strip()
        
    if 'Storage' in item:
        cur_storage = {}
        for hd_index in item['Storage']:
            hd = item['Storage'][hd_index]
            if 'ModelNumber' in hd:
                # Initilize for the model
                if hd['ModelNumber'] not in cur_storage:
                    cur_storage[hd['ModelNumber']] = [1,'N/A']
                    if 'PhysicalSize' in hd:
                        cur_storage[hd['ModelNumber']][1] = hd['PhysicalSize']
                # Count the model
                else:
                    cur_storage[hd['ModelNumber']][0] += 1
        # cur_storage sample
        # {'Micron_9200_MTFDHAL3T8TCT': [2, 3840755982336], 'Micron_9100_MTFDHAL3T8TCT': [1, 3840755982336]}
        #print(cur_storage)
        parsed_data[-1]['hd_model'] = '<br/>'.join(cur_storage.keys())
        for key in cur_storage:
            #print(cur_storage[key][1])
            if parsed_data[-1]['hd_num'] == '0':
                parsed_data[-1]['hd_num'] = parsed_data[-1]['hd_num'].replace('0','')
            if parsed_data[-1]['hd_note'] == 'N/A':
                parsed_data[-1]['hd_note'] = parsed_data[-1]['hd_note'].replace('N/A','')
            parsed_data[-1]['hd_num'] += str(cur_storage[key][0]) + '<br/>'
            parsed_data[-1]['hd_note'] += str(round(int(cur_storage[key][1])/1099500000000,2)) + ' TB<br/>'
        parsed_data[-1]['hd_note'] = parsed_data[-1]['hd_note'].strip()
        parsed_data[-1]['hd_num'] = parsed_data[-1]['hd_num'].strip()
        
    if 'Graphics' in item:
        if 'Number of GPUs' in item['Graphics']:
            parsed_data[-1]['gpu_num'] = item['Graphics']['Number of GPUs']
        if 'Driver Version' in item['Graphics']:
            parsed_data[-1]['gpu_note'] = 'Driver: ' + item['Graphics']['Driver Version']
        if 'GPU' in item['Graphics']:
            # verify the model name
            cur_model = 'N/A'
            cur_fw = 'N/A'
            for index_g in item['Graphics']['GPU']:
                if cur_model == 'N/A' and 'Model' in item['Graphics']['GPU'][index_g]:
                    cur_model = item['Graphics']['GPU'][index_g]['Model']
                elif cur_model != 'N/A' and 'Model' in item['Graphics']['GPU'][index_g] and cur_model != item['Graphics']['GPU'][index_g]['Model']:
                    cur_model = "Different models found!"
                if cur_fw == 'N/A' and 'VBIOS' in item['Graphics']['GPU'][index_g]:
                    cur_fw = item['Graphics']['GPU'][index_g]['VBIOS']
                elif cur_fw != 'N/A' and 'VBIOS' in item['Graphics']['GPU'][index_g] and cur_fw != item['Graphics']['GPU'][index_g]['VBIOS']:
                    cur_fw = "Different VBIOS found!"
            parsed_data[-1]['gpu_model'] = cur_model
            if parsed_data[-1]['gpu_note'] == 'N/A':
                parsed_data[-1]['gpu_note'] = "VBIOS: "  +  cur_fw
            else:
                parsed_data[-1]['gpu_note'] += "<br/>VBIOS: "  +  cur_fw
    
    if 'NICS' in item:
        cur_nic = {}
        for index_n in item['NICS']:
            nic = item['NICS'][index_n]
            if 'Part Number' in nic:
                # Initilize for the model
                if nic['Part Number'] not in cur_nic:
                    cur_nic[nic['Part Number']] = 1
                # Count the model
                else:
                    cur_nic[nic['Part Number']] += 1
        if len(item['NICS']) != 0:        
            parsed_data[-1]['nic_model'] = '<br/>'.join(cur_nic.keys())
        for key in cur_nic:
            #print(cur_storage[key][1])
            if parsed_data[-1]['nic_num'] == '0':
               parsed_data[-1]['nic_num'] = parsed_data[-1]['nic_num'].replace('0','')
            parsed_data[-1]['nic_num'] += str(cur_nic[key]) + '<br/>'
        parsed_data[-1]['nic_num'] = parsed_data[-1]['nic_num'].strip()
            
    if 'PSU' in item:
        cur_psu = {}
        for index_p in item['PSU']:
            psu = item['PSU'][index_p]
            if type(psu) == int: # there is a key named "Number of PSUs"
                continue
            if 'Module No.' in psu:
                # Initilize for the model
                if psu['Module No.'] not in cur_psu:
                    cur_psu[psu['Module No.']] = 1
                # Count the model
                else:
                    cur_psu[psu['Module No.']] += 1
                    
        parsed_data[-1]['power_model'] = '<br/>'.join(cur_psu.keys())
        for key in cur_psu:
            #print(cur_storage[key][1])
            if parsed_data[-1]['power_num'] == '0':
               parsed_data[-1]['power_num'] = parsed_data[-1]['power_num'].replace('0','')
            parsed_data[-1]['power_num'] += str(cur_psu[key]) + '<br/>'
        parsed_data[-1]['power_num'] = parsed_data[-1]['power_num'].strip()
    
    if 'FANS' in item:
        num_fan = 0
        num_ns = 0
        parsed_data[-1]['fan_note'] = 'All Good'
        for index_f in item['FANS']:
            fan = item['FANS'][index_f]
            if type(fan) == dict:
                num_fan += 1
                if fan.get('status') != 'ok':
                    num_ns += 1
        parsed_data[-1]['fan_note'] = str(num_ns) + ' fan(s) show ns'
        parsed_data[-1]['fan_num'] = str(num_fan)
    
    if 'Memory' in item:
        if 'DIMMS' in item['Memory']:
            parsed_data[-1]['mem_num'] = item['Memory']['DIMMS']
        if 'Total Memory' in item['Memory']:
            parsed_data[-1]['mem_note'] = 'Total Size: ' + item['Memory']['Total Memory'] + ' GB'
        if 'Slots' in item['Memory']:
            all_manufactures = []
            for dim in item['Memory']['Slots']:
                if 'Manufacturer' in item['Memory']['Slots'][dim] and 'Part No.' in item['Memory']['Slots'][dim]:
                    cur_entry = item['Memory']['Slots'][dim]['Manufacturer'] + ' ' + item['Memory']['Slots'][dim]['Part No.']
                    if cur_entry not in all_manufactures and "NO DIMM" not in cur_entry:
                            all_manufactures.append(cur_entry)
        #print(all_manufactures)
        parsed_data[-1]['mem_model'] = '<br/>'.join(all_manufactures)

    if 'TOPO_file' in item and 'Hostname' in item:
        topo_files[item['Hostname']] = [item['TOPO_file']['imageID'], item['TOPO_file']['shape'], item['TOPO_file']['filename']]
#parsed_data[0]['mac'] = -1
parsed_data_sort = []

# sort the parsed data according to the bmc_ip list
for ip in bmc_ip:
    for item in parsed_data:
        if item['bmc_ip'] == ip:
            parsed_data_sort.append(item)

#### Code to fetch OS LEVEL serial number from database ###
sn_seperator = '<font color="blue">&nbsp|&nbsp;</font>'
sn_seperator_real = ' | ' # for calculating the length  
sn_data = []
sn_data_template = {'bmc_ip':'N/A','mac':'N/A',\
           'System PN':'N/A','System SN':'N/A',\
           'Chassis PN':'N/A','Chassis SN':'N/A',\
           'MB PN':'N/A','MB SN':'N/A',\
#           'System PN':'SYS-2029BT-HNR' + sn_seperator,'System SN':'S264322X9707411' + sn_seperator,\
#           'Chassis PN':'CSE-458GTS-R3K06P' + sn_seperator,'Chassis SN':'C458GAK45030007' + sn_seperator,\
#           'MB PN':'MBD-H12DGQ-NT6-P' + sn_seperator,'MB SN':'WM21AS603864' + sn_seperator,\
           'Memory PN':'N/A','Memory SN':'N/A',\
           'NIC PN':'N/A','NIC SN':'N/A','NIC FW':'N/A','NIC MAC':'N/A',\
           'GPU PN':'N/A','GPU SN':'N/A','GPU FW':'N/A',\
           'Disk PN':'N/A','Disk SN':'N/A','Disk FW':'N/A',\
           'PSU PN':'N/A','PSU SN':'N/A'\
          }           
for item in all_hw_data:
    #print(item['Hostname'])
    sn_data.append(sn_data_template.copy()) # if not using copy(), all the dicts are the same reference
    if 'bmc_ip' in item:
        sn_data[-1]['bmc_ip'] = item['bmc_ip']
    if 'Hostname' in item:
        sn_data[-1]['mac'] = item['Hostname'].replace('-','').replace(':','')
    if 'Memory' in item:
        if 'Slots' in item['Memory']:
            for mem_index in item['Memory']['Slots']:
                mem = item['Memory']['Slots'][mem_index]
                if isinstance(mem, dict):
                    if sn_data[-1]['Memory SN'] == 'N/A':
                        sn_data[-1]['Memory SN'] = ''
                    if sn_data[-1]['Memory PN'] == 'N/A':
                        sn_data[-1]['Memory PN'] = ''
                    if 'Serial No.' in mem and 'NO DIMM' not in mem['Serial No.']:
                        sn_data[-1]['Memory SN'] += mem['Serial No.'] + sn_seperator
                    elif 'NO DIMM' not in mem['Serial No.']:
                        sn_data[-1]['Memory SN'] += 'N/A' + sn_seperator
                    if 'Part No.' in mem and 'NO DIMM' not in mem['Part No.']:
                        sn_data[-1]['Memory PN'] += mem['Part No.'] + sn_seperator
    if 'Storage' in item:
        for hd_index in item['Storage']:
            hd = item['Storage'][hd_index]
            if isinstance(hd, dict):
                if sn_data[-1]['Disk SN'] == 'N/A':
                    sn_data[-1]['Disk SN'] = ''
                if sn_data[-1]['Disk FW'] == 'N/A':
                    sn_data[-1]['Disk FW'] = ''
                if sn_data[-1]['Disk PN'] == 'N/A':
                    sn_data[-1]['Disk PN'] = ''
                if 'SerialNumber' in hd:
                    sn_data[-1]['Disk SN'] += hd['SerialNumber'] + sn_seperator
                else:
                    sn_data[-1]['Disk SN'] += 'N/A' + sn_seperator
                if 'Firmware' in hd:
                    sn_data[-1]['Disk FW'] += hd['Firmware'] + sn_seperator
                else:
                    sn_data[-1]['Disk FW'] += 'N/A' + sn_seperator
                if 'ModelNumber' in hd:
                    sn_data[-1]['Disk PN'] += hd['ModelNumber'] + sn_seperator
                else:
                    sn_data[-1]['Disk PN'] += 'N/A' + sn_seperator
    if 'PSU' in item:
        for index_p in item['PSU']:
            psu = item['PSU'][index_p] 
            if isinstance(psu, dict):
                if sn_data[-1]['PSU SN'] == 'N/A':
                    sn_data[-1]['PSU SN'] = ''
                if sn_data[-1]['PSU PN'] == 'N/A':
                    sn_data[-1]['PSU PN'] = ''
                if 'Serial No.'  in psu:
                    sn_data[-1]['PSU SN'] += psu['Serial No.'] + sn_seperator
                else:
                    sn_data[-1]['PSU SN'] += 'N/A' + sn_seperator
                if 'Module No.'  in psu:
                    sn_data[-1]['PSU PN'] += psu['Module No.'] + sn_seperator
                else:
                    sn_data[-1]['PSU PN'] += 'N/A' + sn_seperator
    if 'Graphics' in item:
        if 'GPU' in item['Graphics']:
            for gpu_index in item['Graphics']['GPU']:
                gpu = item['Graphics']['GPU'][gpu_index]
                if isinstance(hd, dict):
                    if sn_data[-1]['GPU SN'] == 'N/A':
                        sn_data[-1]['GPU SN'] = ''
                    if sn_data[-1]['GPU FW'] == 'N/A':
                        sn_data[-1]['GPU FW'] = ''
                    if sn_data[-1]['GPU PN'] == 'N/A':
                        sn_data[-1]['GPU PN'] = ''
                    if 'Serial No.' in gpu:
                        sn_data[-1]['GPU SN'] += gpu['Serial No.'] + sn_seperator
                    else:
                        sn_data[-1]['GPU SN'] += 'N/A' + sn_seperator
                    if 'VBIOS' in gpu:
                        sn_data[-1]['GPU FW'] += gpu['VBIOS'] + sn_seperator
                    else:
                        sn_data[-1]['GPU FW'] += 'N/A' + sn_seperator
                    if 'Model' in gpu:
                        sn_data[-1]['GPU PN'] += gpu['Model'] + sn_seperator
                    else:
                        sn_data[-1]['GPU PN'] += 'N/A' + sn_seperator

    if 'NICS' in item:
        for nic_index in item['NICS']:
            nic = item['NICS'][nic_index]
            if isinstance(nic, dict):
                if sn_data[-1]['NIC SN'] == 'N/A':
                    sn_data[-1]['NIC SN'] = ''
                if sn_data[-1]['NIC FW'] == 'N/A':
                    sn_data[-1]['NIC FW'] = ''
                if sn_data[-1]['NIC MAC'] == 'N/A':
                    sn_data[-1]['NIC MAC'] = ''
                if sn_data[-1]['NIC PN'] == 'N/A':
                    sn_data[-1]['NIC PN'] = ''
                if 'Serial' in nic:
                    sn_data[-1]['NIC SN'] += nic['Serial'] + sn_seperator
                else:
                    sn_data[-1]['NIC SN'] += 'N/A' + sn_seperator
                if 'Firmware' in nic:
                    sn_data[-1]['NIC FW'] += nic['Firmware'] + sn_seperator
                else:
                    sn_data[-1]['NIC FW'] += 'N/A' + sn_seperator
                if 'MAC' in nic:
                    sn_data[-1]['NIC MAC'] += nic['MAC'] + sn_seperator
                else:
                    sn_data[-1]['NIC MAC'] += 'N/A' + sn_seperator
                if 'MAC' in nic:
                    sn_data[-1]['NIC PN'] += nic['Part Number'] + sn_seperator
                else:
                    sn_data[-1]['NIC PN'] += 'N/A' + sn_seperator

    if 'System' in item:
        for index_sys in item['System']:
            sys = item['System'][index_sys] 
            if isinstance(sys, dict):
                if sn_data[-1]['System SN'] == 'N/A':
                    sn_data[-1]['System SN'] = ''
                if sn_data[-1]['System PN'] == 'N/A':
                    sn_data[-1]['System PN'] = ''
                if 'Serial Number'  in sys:
                    sn_data[-1]['System SN'] += sys['Serial Number'] + sn_seperator
                else:
                    sn_data[-1]['System SN'] += 'N/A' + sn_seperator
                if 'Product Name'  in sys:
                    sn_data[-1]['System PN'] += sys['Product Name'] + sn_seperator
                else:
                    sn_data[-1]['System PN'] += 'N/A' + sn_seperator

    if 'Chassis' in item:
        for index_chas in item['Chassis']:
            chas = item['Chassis'][index_chas] 
            if isinstance(chas, dict):
                if sn_data[-1]['Chassis SN'] == 'N/A':
                    sn_data[-1]['Chassis SN'] = ''
                if sn_data[-1]['Chassis PN'] == 'N/A':
                    sn_data[-1]['Chassis PN'] = ''
                if 'Serial Number'  in chas:
                    sn_data[-1]['Chassis SN'] += chas['Serial Number'] + sn_seperator
                else:
                    sn_data[-1]['Chassis SN'] += 'N/A' + sn_seperator
                if 'Part Number'  in chas:
                    sn_data[-1]['Chassis PN'] += chas['Part Number'] + sn_seperator
                else:
                    sn_data[-1]['Chassis PN'] += 'N/A' + sn_seperator
                # chassis currently has no PN in dmidecode yet.

    if 'Base Board' in item:
        for index_mb in item['Base Board']:
            mb = item['Base Board'][index_mb] 
            if isinstance(mb, dict):
                if sn_data[-1]['MB SN'] == 'N/A':
                    sn_data[-1]['MB SN'] = ''
                if sn_data[-1]['MB PN'] == 'N/A':
                    sn_data[-1]['MB PN'] = ''
                if 'Serial Number'  in mb:
                    sn_data[-1]['MB SN'] += mb['Serial Number'] + sn_seperator
                else:
                    sn_data[-1]['MB SN'] += 'N/A' + sn_seperator
                if 'Product Name'  in mb:
                    sn_data[-1]['MB PN'] += mb['Product Name'] + sn_seperator
                else:
                    sn_data[-1]['MB PN'] += 'N/A' + sn_seperator

sn_data_sort = []

# sort the sn data according to the bmc_ip list
for ip in bmc_ip:
    for item in sn_data:
        if item['bmc_ip'] == ip:
            sn_data_sort.append(item)

# remove tail sn_seperator:
#for i, node_data in enumerate(sn_data_sort):
#    for key in node_data.keys():
#        if len(node_data[key]) >= 1 and node_data[key].endswith(sn_seperator):
#            sn_data_sort[i][key] = node_data[key][:-len(sn_seperator)]

printf('############sn_data############')
for i in sn_data_sort:
    printf(i)
printf('############sn_data END############')

class Test(object):
    """"""

    #----------------------------------------------------------------------
    def __init__(self):
        """Constructor"""
        self.width, self.height = letter
        self.styles = getSampleStyleSheet()

    #----------------------------------------------------------------------
    def coord(self, x, y, unit=1):
        """
        http://stackoverflow.com/questions/4726011/wrap-text-in-a-table-reportlab
        Helper class to help position flowables in Canvas objects
        """
        x, y = x * unit, self.height -  y * unit
        return x, y
    
    #----------------------------------------------------------------------
    def run(self):
        """
        Run the report
        """

        self.doc = SimpleDocTemplate("cluster_report.pdf")
        #logo = "logo.jpg"
        #im = Image(logo, 1.5*inch, 1*inch)
        self.story = [ConditionalSpacer(width=1, height=12.7)]
        #self.story.append(im)
        self.createLineItems()
        self.doc.build(self.story, onFirstPage=self.myFirstPage, onLaterPages=self.createDocument)
        printf("Notice: PDF generation finished!")
    #----------------------------------------------------------------------
    def createDocument(self, canvas, doc):
        """
        Create the document
        """
        self.c = canvas
        centered = ParagraphStyle(name="centered", alignment=TA_CENTER)
        #header_text = """<a name="TOP"/><strong>RACK REPORT: """ + rackname + """</strong>"""
        #p = Paragraph(header_text, centered)
        #p.wrapOn(self.c, self.width, self.height)
        #p.drawOn(self.c, *self.coord(0, 0, mm))

        """
        Headers and Footers
        """
        self._addLogos()
        self._addAuthor()
        self._addPageNumber()

    #----------------------------------------------------------------------
    def myFirstPage(self, canvas, doc):
        self.c = canvas
        
        """
        Title
        """
        def addTitleSection(section_height):
            Title = "L12 Solution and Validation Report" # + rackname
            fontsize=24
            self.c.setFont('Helvetica-Bold', fontsize)
            self.c.setFillColor(black)

            self.c.drawCentredString(self.width/2.0, section_height, rackname)
            self.c.drawCentredString(self.width/2.0, section_height-fontsize-5, Title)

            # # left align
            # self.c.drawString(inch, section_height, rackname)
            # self.c.setFillColor(darkgrey)
            # self.c.drawString(inch, section_height-fontsize-5, Title)
            # self.c.setFillColor(black)

        """
        Introduction
        """
        def addIntroSection(section_height):
            aihpclogo = "cluster_report_images/aihpc_logo.png"
            introduction = "Supermicro’s AI and HPC team (part of Supermicro Solution and Integration Center) is an elite team of software and hardware engineers. We generate and publish state-of-the-art benchmarks showcasing the performance of Supermicro’s wide array of Super Servers. We also work with the industry leading AI and HPC partners to generate the latest and greatest performance data."
            normal = self.styles["Normal"]

            aihpc_height = section_height
            aihpclogo_width, aihpclogo_ratio = 200, 12.7
            aihpclogo_height = aihpclogo_width/aihpclogo_ratio
            self.c.drawImage(aihpclogo, self.width/2-aihpclogo_width/2, aihpc_height, width=aihpclogo_width, height=aihpclogo_height, mask='auto')

            p = Paragraph(introduction, normal)
            w, h = p.wrap(self.doc.width, self.doc.topMargin)
            p.drawOn(self.c, self.doc.leftMargin, aihpc_height-55)

        """
        Logos for benchmarks
        """
        def addBenchmarksSection(section_height):
            bmlogo = "cluster_report_images/logos.png"
            self.c.setFont('Helvetica', 10)

            # benchmark logos
            bm_height = section_height
            self.c.drawCentredString(self.width/2, bm_height, "Here are some benchmarks we have conducted:")
            bmlogo_width, bmlogo_ratio = 410, 2.33
            bmlogo_height = bmlogo_width/bmlogo_ratio
            self.c.drawImage(bmlogo, self.width/2-bmlogo_width/2, bm_height-bmlogo_height-5, width=bmlogo_width, height=bmlogo_height)

        """
        Logos for Solutions
        """
        def addSolutionsSection(section_height):
            slogo = "cluster_report_images/ourSolutions.png"
            self.c.setFont('Helvetica', 10)

            # solutions logos
            s_height = section_height # 20 points below bmlogo
            self.c.drawCentredString(self.width/2, s_height, "Here is a list of other solutions that we offer:")
            slogo_width, slogo_ratio = 410, 2.67
            slogo_height = slogo_width/slogo_ratio
            self.c.drawImage(slogo, self.width/2-slogo_width/2, s_height-slogo_height-15, width=slogo_width, height=slogo_height)

        """
        Links to sites
        """
        def addLinkSection(section_height):
            self.c.setFont('Helvetica',10)
            self.c.drawCentredString(self.width/2, section_height, "For more information about our services, please visit:")
            self.c.drawCentredString(self.width/2, section_height-35, "For an in-depth view of our benchmarks, please visit our blog:")
            
            self.c.setFillColor(red)
            self.c.drawCentredString(self.width/2, section_height-85, "NOTE: Both pages require company network to access")
            
            self.c.setFillColor(blue)
            fontsize = 14
            self.c.setFont('Helvetica-Bold', fontsize)

            ssicline = section_height-15
            self.c.drawCentredString(self.width/2, ssicline, ssicname := "Supermicro Solution and Integration Center")
            self.c.linkURL('http://solution.supermicro.com/', (self.width/2-self.c.stringWidth(ssicname)/2, ssicline, self.width/2+self.c.stringWidth(ssicname)/2, ssicline+fontsize), relative=0)

            aihpcline = section_height-50
            self.c.drawCentredString(self.width/2, aihpcline, aihpcname := "AI and HPC Benchmarks")
            self.c.linkURL('http://aihpc.supermicro.com/', (self.width/2-self.c.stringWidth(aihpcname)/2, aihpcline, self.width/2+self.c.stringWidth(aihpcname)/2, aihpcline+fontsize), relative=0)

            self.c.setFillColor(black)

        def addTitleBox(section_height, box_height):
            leftX, rightX = inch, self.width-inch
            lowerY, upperY = section_height, section_height + box_height

            self.c.setLineWidth(1)
            self.c.line(leftX, upperY, rightX, upperY) # top
            self.c.line(leftX, lowerY, rightX, lowerY) # bottom
            self.c.line(leftX, lowerY, leftX, upperY) # left
            self.c.line(rightX, lowerY, rightX, upperY) # right


        addTitleSection(self.height-20)
        # addTitleBox(self.height-65, box_height=65)
        self._addLineBreak(self.height-65, length=self.width-2*inch)
        addIntroSection(self.height-105)
        self._addLineBreak(self.height-175)
        addBenchmarksSection(self.height-200)
        self._addLineBreak(self.height-382)
        addSolutionsSection(self.height-407)
        self._addLineBreak(self.height-590)
        addLinkSection(self.height-615)

        """
        Headers and Footers
        """
        self._addLogos()
        self._addAuthor()
        self._addPageNumber()
        
        
    #----------------------------------------------------------------------
    def createLineItems(self):
        """
        Create the line items
        """
        #General settings
        spacer = ConditionalSpacer(width=0, height=35)
        spacer_median = ConditionalSpacer(width=0, height=10)
        spacer_conclusion = ConditionalSpacer(width=0, height=5)
        spacer_tiny = ConditionalSpacer(width=0, height=2.5)
        font_size = 10
        centered = ParagraphStyle(name="centered", alignment=TA_CENTER)
        centered_bm = ParagraphStyle(name="centered_bm", fontSize=12, alignment=TA_CENTER)
        warning = ParagraphStyle(name="normal",fontSize=12, textColor="red",leftIndent=40)
        bm_title = ParagraphStyle(name="normal",fontSize=12,textColor="black",leftIndent=0)
        bm_intro = ParagraphStyle(name="normal",fontSize=8,leftIndent=0)
        issue_font = ParagraphStyle(name="normal",fontSize=10,leftIndent=0)
        issue_caption_font = ParagraphStyle(name="normal", fontSize=8, alignment=TA_CENTER)
        other_intro = ParagraphStyle(name="normal",fontSize=8,leftIndent=0)
        cluster_subtitle_font = ParagraphStyle(name="normal",fontSize=14,leftIndent=0)
        cluster_description_font = ParagraphStyle(name="normal",fontSize=10,leftIndent=0)
        hr_line = HRFlowable(width="100%", thickness=1, lineCap='round', color=colors.lightgrey, spaceBefore=1, spaceAfter=1, hAlign='CENTER', vAlign='BOTTOM', dash=None)
        # Looking for cluster photo
        testing_image = "cluster_report_images/service-testing.png"
        flow_image = "cluster_report_images/L12_Flow.jpg"
        #self.story.append(PageBreak())
        #Summary and Hardware Tables
        ## column names
        text_data = ["Serial Number", "BMC MAC Address", "Model Number", "CPLD Version", "BIOS Version", "BMC Version", "Date"] # Date is timstamp
        text_data2 = ["Serial Number", "CPU Model", "CPU Count", "MEM (GB)", "DIMM PN", "#", "Ext-Drive", "#"]

        d = []
        d2 = []
        ## Create header with column names
        for text in text_data:
            ptext = "<font size=%s><b>%s</b></font>" % (font_size-2, text)
            p = Paragraph(ptext, centered)
            d.append(p)
        for text in text_data2:
            ptext = "<font size=%s><b>%s</b></font>" % (font_size-2, text)
            p = Paragraph(ptext, centered)
            d2.append(p)

        data = [d]
        data2 = [d2]

        line_num = 1
        line_num2 = 1
        formatted_line_data = []
        count = collection.count_documents({})
        for x in range(count):
            line_data = res[x]
            for item in line_data:
                ptext = "<font size=%s>%s</font>" % (font_size-2, item)
                p = Paragraph(ptext, centered)
                formatted_line_data.append(p)
            data.append(formatted_line_data)
            formatted_line_data = []
            line_num += 1

        for y in range(count):
            line_data2 = res2[y]
            for item in line_data2:
                ptext = "<font size=%s>%s</font>" % (font_size-2, item)
                p = Paragraph(ptext, centered)
                formatted_line_data.append(p)
            data2.append(formatted_line_data)
            formatted_line_data = []
            line_num2 += 1

        table = Table(data, colWidths=[92, 90, 60, 75, 80, 80, 53])
        table.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
            ('BOX', (0,0), (-1,-1), 0.25, colors.black),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), create_table_colors(len(data),colors.lightgrey,colors.lightblue))
        ]))

        if has_l12_metrics == 1:
            ptext = """<link href="#TABLE1" color="blue" fontName="Helvetica-Bold" fontSize=8>Summary</link> 
/ <link href="#TABLE2"color="blue" fontName="Helvetica-Bold" fontSize=8>HW Counts</link> 
/ <link href="#TABLE3"color="blue" fontName="Helvetica-Bold" fontSize=8>HW Per Node</link> 
/ <link href="#TOPO_TITLE"color="blue" fontName="Helvetica-Bold" fontSize=8>PCI TOPO</link>
/ <link href="#SR_TITLE"color="blue" fontName="Helvetica-Bold" fontSize=8>Sensors</link> 
/ <link href="#BM_TITLE"color="blue" fontName="Helvetica-Bold" fontSize=8>Benchmark</link>
/ <link href="#PN&SN"color="blue" fontName="Helvetica-Bold" fontSize=8>PN & SN</link>
/ <link href="#License"color="blue" fontName="Helvetica-Bold" fontSize=8>License</link>"""
        else:
            ptext = """<link href="#TABLE1" color="blue" fontName="Helvetica-Bold" fontSize=8>Summary</link> 
/ <link href="#TABLE2"color="blue" fontName="Helvetica-Bold" fontSize=8>HW Counts</link> 
/ <link href="#SR_TITLE"color="blue" fontName="Helvetica-Bold" fontSize=8>Sensors</link> 
/ <link href="#BM_TITLE"color="blue" fontName="Helvetica-Bold" fontSize=8>Benchmark</link>
/ <link href="#License"color="blue" fontName="Helvetica-Bold" fontSize=8>License</link>"""            

        if has_issue == 1:
            ptext += '/ <link href="#ISSUE_TITLE"color="blue" fontName="Helvetica-Bold" fontSize=8>Issue</link>'
        if has_conclusion == 1:
            ptext += '/ <link href="#CONCLUSION_TITLE"color="blue" fontName="Helvetica-Bold" fontSize=8>Remarks</link>'
        if has_notes == 1:
            ptext += '/ <link href="#NOTES_TITLE"color="blue" fontName="Helvetica-Bold" fontSize=8>Notes</link>'
        
        ptext2 = """<a name="TABLE2"/><font color="black" size="12"><b>Hardware Counts and Models """ + rackname + """</b></font>"""
        ptext1 = """<a name="TABLE1"/><font color="black" size="12"><b>Cluster Summary for """ + rackname + """</b></font>"""
        p = Paragraph(ptext, centered)
        table2 = Table(data2, colWidths=[95, 120, 40, 40, 70, 40, 70, 40])
        table2.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
            ('BOX', (0,0), (-1,-1), 0.25, colors.black), 
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), create_table_colors(len(data2),colors.lightgrey,colors.lightblue))
        ]))
        
        paragraph1 = Paragraph(ptext1, centered)
        paragraph2 = Paragraph(ptext2, centered)
        paragraph1.keepWithNext = True
        paragraph2.keepWithNext = True
        p.keepWithNext = True
        
        """
        Cluster Showcase Page
        """
        self.story.append(PageBreak())
        ptext_schema = """<a name="TABLE1"/><font color="black" size="12"><b>Cluster Showcase during L12 Testing</b></font>"""
        paragraph_schema = Paragraph(ptext_schema, centered)
        self.story.append(paragraph_schema)
        self.story.append(spacer_tiny)
        self.story.append(p)
        ptext_schema_intro = """
        SMC HPC cluster aims to provide high-performance, high-efficiency server, storage technology and Green Computing.<br />
        The image below is a showcase of cluster during L12 testing. Followed by the hardware information and benchmark results.<br />
        For more information about this product, please visit our offical website: <link href="https://www.supermicro.com/"color="blue">https://www.supermicro.com/</link>         
        """.format(rackname)
        cluster_schema_intro = Paragraph(ptext_schema_intro, other_intro)
        self.story.append(cluster_schema_intro)
        self.story.append(ConditionalSpacer(width=0, height=10))

        """
        What We Provide
        """
        testing_image_width, testing_image_ratio = 18*cm, 2.89
        testing_image_height = testing_image_width/testing_image_ratio
        self.story.append(get_image(testing_image, height=testing_image_height, width=testing_image_width))        
        self.story.append(ConditionalSpacer(width=0, height=10))

        ptext_cluster_subtitle_1 = """<font color="grey"><b>What We Provide</b></font>"""        
        cluster_subtitle_1 = Paragraph(ptext_cluster_subtitle_1, cluster_subtitle_font)
        self.story.append(cluster_subtitle_1)
        self.story.append(ConditionalSpacer(width=0, height=10))

        ptext_cluster_description_1 = "We provide rack/cluster wide integration testing services. Our test items were designed to ensure the overall quality and integrity of the whole rack/cluster, and achieve 100% customer satisfaction with the Supermicro products and solutions."
        ptext_cluster_description_2 = "The Supermicro integration test aims to expose any issue within the system and network so that we can eliminate the issue and improve the availability, stability and performance of the rack/cluster."
        # ptext_cluster_description_3 = "In addition, the test will verify the functionality of each system and the interoperability between the systems in the rack/cluster. Our test program is the key for us to deliver high-quality rack/cluster systems to our valued customers."
        ptext_cluster_description_3 = "Our L12 test program leverages tools in AI, HPC, Big Data, Database, Virtualization/Cloud, File System, and Network, which is key for us to deliver high-quality, customizable rack/cluster solutions to our valued customers."
        cluster_description_1 = Paragraph(ptext_cluster_description_1, cluster_description_font)   
        cluster_description_2 = Paragraph(ptext_cluster_description_2, cluster_description_font)
        cluster_description_3 = Paragraph(ptext_cluster_description_3, cluster_description_font)

        self.story.append(cluster_description_1)
        self.story.append(ConditionalSpacer(width=0, height=10))
        self.story.append(cluster_description_2)
        self.story.append(ConditionalSpacer(width=0, height=10))
        self.story.append(cluster_description_3)
        self.story.append(ConditionalSpacer(width=0, height=15))

        """
        Test Flow
        """
        ptext_cluster_subtitle_2 = """<font color="grey"><b>Test Flow</b></font>"""        
        cluster_subtitle_2 = Paragraph(ptext_cluster_subtitle_2, cluster_subtitle_font)
        self.story.append(cluster_subtitle_2)
        self.story.append(ConditionalSpacer(width=0, height=10))

        flow_image_width, flow_image_ratio = 18*cm, 2.14
        flow_image_height = flow_image_width/flow_image_ratio
        self.story.append(get_image(flow_image, height=flow_image_height, width=flow_image_width))        


        #start by appending a pagebreak to separate first page from rest of document
        self.story.append(PageBreak())
        #table1 title
        self.story.append(paragraph1)
        #Navigation bar
        self.story.append(p)
        # Cluster Summary intro
        ptext_cs_intro = """
        Table below shows the hardware and firmware information for whole cluster:<br />
        1. The information below are fetched from Redfish API.<br />
        2. Serial Number is based on the information from csv file.<br />
        3. Date (Timestamp) is the datetime when LCM boot up.<br />
        """
        cluster_summary_intro = Paragraph(ptext_cs_intro, other_intro)
        cluster_summary_intro.keepWithNext = True
        #self.story.append(cluster_summary_intro)       
        #table1
        self.story.append(table)
        self.story.append(PageBreak())
        
        
        #table2 title
        self.story.append(paragraph2)
        #Navigation bar
        #p.keepWithNext = True
        self.story.append(p)
        # Hardware Counts intro
        ptext_hc_intro = """
        Table below shows the hardware counts and model names for whole cluster:<br />
        1. The information below are fetched from Redfish API.<br />
        2. GPU information is not supported by Redfish API.<br />
        """
        hardware_counts_intro = Paragraph(ptext_hc_intro, other_intro)
        hardware_counts_intro.keepWithNext = True
        #self.story.append(hardware_counts_intro)          
        #table2
        self.story.append(table2)     
        
        ########################################Node by Node Hardware summary##################################################
        self.story.append(PageBreak())
        ptext_hn = """<a name="TABLE3"/><font color="black" size="12"><b>Detailed Hardware Information Per Node</b></font>"""
        hn_title = Paragraph(ptext_hn, centered)
        hn_title.keepWithNext = True
        if has_l12_metrics == 1:
            self.story.append(hn_title) 
            self.story.append(p)

        ptext_hn_intro = """
        Table below shows the hardware information for each node:<br />
        1. The information below are fetched from both OS level and Redfish API.<br />
        2. MAC address is based on the information from csv file.<br />
        3. To refresh the hardware config, please check out the UDP cotroller page.<br />
        """
        hardware_node_intro = Paragraph(ptext_hn_intro, other_intro)
        hardware_node_intro.keepWithNext = True
        self.story.append(hardware_node_intro)
        
        if 'hw_data' in list_of_collections and len(serialNumber) == len(MacAddress) and len(serialNumber) == len(parsed_data_sort):
            for sn, mac, cur_hw in zip(serialNumber, MacAddress, parsed_data_sort):
                ptext_hn_sub = """<a name="NH_TITLE"/><font color="black" size="12"><b>SN: """ + sn + """ MAC: """ + mac +"""</b></font>"""
                hn_title_sub = Paragraph(ptext_hn_sub, bm_title)
                hn_title_sub.keepWithNext = True
                ## Create header with column names
                d3 = []
                hn_columns = ["Item Name", "Model Name", "Qty", "Notes"]
                for text in hn_columns:
                    ptext = "<font size=%s><b>%s</b></font>" % (font_size, text)
                    p3 = Paragraph(ptext, centered)
                    d3.append(p3)

                data3 = [d3]

                hn_rows_basic =  ['System','Motherboard','Processor','Memory','GPU','Disk','NIC cards','Power Supply','Fans']
                hn_rows = hn_rows_basic
                hn_counts = len(hn_rows)
                hw_details = [[0 for i in range(len(hn_columns))] for j in range(hn_counts) ]
                # len(hw_details) = 7  which is number of rows
                # check mac address
                if cur_hw['mac'].strip().lower() != mac.replace('-','').replace(':','').strip().lower():
                    print('Warning: Found unmatching MAC addressses between Database and CSV file.')
                    print(cur_hw['mac'].strip().lower())
                    print(mac.replace('-','').replace(':','').strip().lower())
                
                for i in range(hn_counts): # rows
                    for j in range(len(hn_columns)): # columns
                        if j == 0:
                            hw_details[i][j] = hn_rows[i]
                        elif 'System' in hn_rows[i]:
                            if j == 1: 
                                hw_details[i][j] = cur_hw['system_model']
                            elif j == 2:
                                hw_details[i][j] = 1
                            else:
                                hw_details[i][j] = 'N/A'
                        elif 'Motherboard' in hn_rows[i]:
                            if j == 1: 
                                hw_details[i][j] = cur_hw['motherboard_model']
                            elif j == 2:
                                hw_details[i][j] = 1
                            else:
                                hw_details[i][j] = 'N/A'                                 
                        elif 'Processor' in hn_rows[i]:
                            if j == 1: 
                                hw_details[i][j] = cur_hw['cpu_model']
                            elif j == 2:
                                hw_details[i][j] = cur_hw['cpu_num']
                            else:
                                hw_details[i][j] = cur_hw['cpu_note']
                        elif 'Memory' in hn_rows[i]:
                            if j == 1: 
                                hw_details[i][j] = cur_hw['mem_model']
                            elif j == 2:
                                hw_details[i][j] = cur_hw['mem_num']
                            else:
                                hw_details[i][j] = cur_hw['mem_note']
                        elif 'GPU' in hn_rows[i]:
                            if j == 1: 
                                hw_details[i][j] = cur_hw['gpu_model']
                            elif j == 2:
                                hw_details[i][j] = cur_hw['gpu_num']
                            else:
                                hw_details[i][j] = cur_hw['gpu_note']
                        elif 'Disk' in hn_rows[i]:
                            if j == 1: 
                                hw_details[i][j] = cur_hw['hd_model']
                            elif j == 2:
                                hw_details[i][j] = cur_hw['hd_num']
                            else:
                                hw_details[i][j] = cur_hw['hd_note']
                        elif 'NIC cards' in hn_rows[i]:
                            if j == 1: 
                                hw_details[i][j] = cur_hw['nic_model']
                            elif j == 2:
                                hw_details[i][j] = cur_hw['nic_num']
                            else:
                                hw_details[i][j] = cur_hw['nic_note']
                        elif 'Power Supply' in hn_rows[i]:
                            if j == 1: 
                                hw_details[i][j] = cur_hw['power_model']
                            elif j == 2:
                                hw_details[i][j] = cur_hw['power_num']
                            else:
                                hw_details[i][j] = cur_hw['power_note']
                        elif 'Fans' in hn_rows[i]:
                            if j == 1: 
                                hw_details[i][j] = cur_hw['fan_model']
                            elif j == 2:
                                hw_details[i][j] = cur_hw['fan_num']
                            else:
                                hw_details[i][j] = cur_hw['fan_note']

                formatted_line_data = []
                for x in range(hn_counts):
                    line_data = hw_details[x]
                    for item in line_data:
                        ptext = "<font size=%s>%s</font>" % (font_size-2, item)
                        p3 = Paragraph(ptext, centered)
                        formatted_line_data.append(p3)
                    data3.append(formatted_line_data)
                    formatted_line_data = []
                table3 = Table(data3, colWidths=[65, 175, 30, 170])
                table3.setStyle(TableStyle([
                    ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                    ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
                    ('BOX', (0,0), (-1,-1), 0.25, colors.black),
                    ('ROWBACKGROUNDS', (0, 0), (-1, -1), create_table_colors(len(data3),colors.lightgrey,colors.lightblue))
                ]))
                #self.story.append(hn_title_sub) 
                #self.story.append(ConditionalSpacer(width=1, height=2.5))     
                if has_l12_metrics == 1:
                    self.story.append(KeepTogether([hn_title_sub,spacer_tiny,table3,spacer_tiny,hr_line,spacer_tiny]))
        else:
            ptext_hn_nodata = """
            Warning: No OS level Hardware Data can be found in Database:<br />
            1. Make sure the 'hw_data' is inside the input directory.<br />
            2. Make sure the config file is inside the 'hw_data' directory.<br />
            3. Check the MAC addresses are the same as the input files.<br />
            4. Check if any nodes hw data missing.<br />
            5. Go the UDP Controller page to reload the data.<br />
            """
            hardware_node_nodata = Paragraph(ptext_hn_nodata, warning)
            if has_l12_metrics == 1:
                self.story.append(hardware_node_nodata)
        ########################################Node by Node Hardware summary END##################################################     
        
        ########################################Node by Node PCI Topo##################################################
        self.story.append(PageBreak())
        ptext_topo = """<a name="TOPO_TITLE"/><font color="black" size="12"><b>PCIE TOPOLOGY DIAGRAM</b></font>"""
        topo_title = Paragraph(ptext_topo, centered)
        topo_title.keepWithNext = True
        if has_l12_metrics == 1:
            self.story.append(topo_title)
            self.story.append(p)
            self.story.append(ConditionalSpacer(width=0, height=0.2*cm))
        
        # load topo files from database
        printf(topo_files)
        for key in topo_files.keys():
            printf(topo_files[key])
            gOut = fs.get(topo_files[key][0])
            cur_img = np.frombuffer(gOut.read(), dtype=np.uint8)
            cur_img = np.reshape(cur_img, topo_files[key][1])
            save_path = os.environ['UPLOADPATH'] + '/hw_data/hw_info_'  + key
            if not os.path.exists(save_path):
                os.makedirs(save_path, exist_ok=True )
            printf('--------------------------------Saving the image for: ' + key)
            cv2.imwrite(save_path  +  '/' + topo_files[key][2], cur_img)
        # initialize variables
        hw_data_path = os.environ['UPLOADPATH'] + '/hw_data'
        all_hw_info_dirs = []
        all_topo_files = {}
        num_of_topos = 0
        # scan all files
        for root,dirs,files in os.walk(hw_data_path):
            for one_dir in sorted(dirs):
                one_dir_full = hw_data_path + '/' + one_dir
                if one_dir_full not in all_hw_info_dirs and one_dir.startswith("hw_info_") and os.path.exists(hw_data_path + '/' + one_dir) and clean_mac(one_dir.split("_")[-1]).upper() in MacAddress:
                    all_hw_info_dirs.append(one_dir_full)
                    printf(one_dir_full)
        printf("--------------------------TOPO files info----------------------------")
        printf(MacAddress)
        for one_dir in all_hw_info_dirs:
            all_topo_files[clean_mac(one_dir.split("_")[-1]).upper()] = 'N/A'
            for root,dirs,files in os.walk(one_dir):
                for file in sorted(files):
                    if file.startswith("topo_") and file.endswith(".png") and os.path.exists(one_dir + '/' + file):
                        all_topo_files[clean_mac(one_dir.split("_")[-1]).upper()] = one_dir + '/' + file
                        num_of_topos += 1
                        printf(one_dir + '/' + file)
                        break
        printf(all_topo_files.keys())
        printf("---------------------------------------------------------------------")
        if num_of_topos == 0:
            ptext_topo_nodata = """
            Warning: No TOPO image can be found in Database:<br />
            1. Make sure the 'hw_data' is inside the input directory.<br />
            2. Try to put the topo_*.png file in the directory. <br />
            3. Check the MAC addresses are the same as the input files.<br />
            4. Check if any nodes hw data missing.<br />
            """
            topo_nodata = Paragraph(ptext_topo_nodata, warning)
            if has_l12_metrics == 1:
                self.story.append(topo_nodata)
                self.story.append(PageBreak())
        for cur_sn, cur_mac in zip(serialNumber, MacAddress):
            printf('Scanning ===> ' + cur_mac)
            for key in all_topo_files.keys():
                if cur_mac == key:                                         
                    if all_topo_files[key] != 'N/A':
                        printf('Found topo image <=== ' + cur_mac)
                        ptext_topo_sub = """<a name="NH_TITLE"/><font color="black" size="12"><b>SN: """ + cur_sn + """ MAC: """ + cur_mac +"""</b></font>"""
                        topo_title_sub = Paragraph(ptext_topo_sub, bm_title)
                        topo_title_sub.keepWithNext = True
                        if has_l12_metrics == 1:
                            self.story.append(KeepTogether([topo_title_sub,spacer_tiny,get_image(all_topo_files[key], height=21*cm, width=15.5*cm),spacer_tiny,hr_line,spacer_tiny]))
                        #self.story.append(ConditionalSpacer(width=0, height=0.2*cm))
                        #self.story.append(get_image(all_topo_files[key], height=21*cm, width=15.5*cm))
                        #self.story.append(PageBreak())
                    else:
                        printf('Cannot find topo image <=== ' + cur_mac)
                    break
            
            #break # only show one systems topo
        ########################################Node by Node PCI Topo END##################################################
        
        #Sensor reading charts
        self.story.append(PageBreak())
        ptext_sr = """<a name="SR_TITLE"/><font color="black" size="12"><b>Sensor Reading Report</b></font>"""
        sr_title = Paragraph(ptext_sr, centered)
        sr_title.keepWithNext = True
        self.story.append(sr_title)
        self.story.append(p)
        
        ptext_sn_intro = """
        The plots below show the maximum and minimum readings for selective sensors:<br />
        1. <font color="red">Red bar</font> denotes the maximum reading.<br />
        2. <font color="blue">Blue bar</font> denotes the minimum reading.<br />
        3. For more Min/Max readings, please check out the LCM pages.<br />
        """
        sensor_reading_intro = Paragraph(ptext_sn_intro, other_intro)
        sensor_reading_intro.keepWithNext = True
        self.story.append(sensor_reading_intro)
        
        
        #power consumption chart
        if type(df_power) != int:
            pData = []
            pNode = list(df_power['Serial Number'])
            pMin = list(df_power['Min'])
            pMax = list(df_power['Max'])
            pData.append(tuple(pMin))
            pData.append(tuple(pMax))
            
            drawing = Drawing(600,200)
            bc = VerticalBarChart()
            bc.x = 0
            bc.y = 0
            bc.height = 150
            bc.width = 500
            bc.valueAxis.valueMin = 0
            bc.valueAxis.valueMax = max(df_power['Max']) * 1.15
            bc.strokeColor = colors.black
            bc.bars[0].fillColor = colors.blue
            bc.bars[1].fillColor = colors.red
            bc.categoryAxis.labels.angle = 20
            bc.categoryAxis.labels.dx = -35
            bc.categoryAxis.labels.dy = -10
            # change fontsize if too many nodes
            if len(df_power['Min']) > 12:
                xlabel_fz = 10 * 12 / len(df_power['Min'])
                bc.categoryAxis.labels.setProperties(propDict={'fontSize':xlabel_fz}) 
                bc.categoryAxis.labels.dx = -35 * 12 / len(df_power['Min'])
            bc.data = pData
            bc.categoryAxis.categoryNames = pNode
            lab = Label()
            lab2 = Label()
            lab.x = 0
            lab.y = 160
            lab2.x = 225
            lab2.y = 175
            lab.fontSize = 12
            lab2.fontSize = 16
            lab.setText("W (Watts)")
            lab2.setText("Min and Max Power Consumption")
            drawing.add(bc)
            drawing.add(lab)
            drawing.add(lab2)
            # only if power reading is making sense, the plot will be made
            if min(df_power['Min']) > 0 and min(df_power['Max']) > 0:
                self.story.append(KeepTogether([drawing,spacer]))
        
        # min/max temp charts
        for df_cur, unit_cur, name_cur in zip(df_temp_list,unit_list, sensor_name_list):
            if type(df_cur) != int:
                pData = []
                pNode = list(df_cur['Serial Number'])
                pData.append(tuple(df_cur['Min']))
                pData.append(tuple(df_cur['Max']))
                printf('pData is:')
                printf(pData)
                drawing = Drawing(600,200)
                bc = VerticalBarChart()
                bc.x = 0
                bc.y = 0
                bc.height = 150
                bc.width = 500
                bc.valueAxis.valueMin = 0
                bc.valueAxis.valueMax = max(df_cur['Max']) * 1.15
                bc.strokeColor = colors.black
                bc.bars[0].fillColor = colors.blue
                bc.bars[1].fillColor = colors.red
                bc.categoryAxis.labels.angle = 20
                bc.categoryAxis.labels.dx = -35
                bc.categoryAxis.labels.dy = -10
                # change fontsize if too many nodes
                if len(df_cur['Min']) > 12:
                    xlabel_fz = 10 * 12 / len(df_cur['Min'])
                    bc.categoryAxis.labels.setProperties(propDict={'fontSize':xlabel_fz})       
                    bc.categoryAxis.labels.dx = -35 * 12 / len(df_cur['Min'])
                bc.data = pData
                bc.categoryAxis.categoryNames = pNode
                lab = Label()
                lab2 = Label()
                lab.x = 0
                lab.y = 160
                lab2.x = 225
                lab2.y = 175
                lab.fontSize = 12
                lab2.fontSize = 16
                lab.setText(unit_cur)
                lab2.setText("Min and Max " + name_cur)
                drawing.add(bc)
                drawing.add(lab)
                drawing.add(lab2)
                # only if temp reading is making sense, the plot will be made
                if min(df_cur['Min']) > 0 and min(df_cur['Min']) < 500 and max(df_cur['Max']) < 500 and min(df_cur['Max'])> 0:
                    self.story.append(KeepTogether([drawing,spacer]))
        
        
        
        self.story.append(PageBreak())
        #benchmark charts and tables
        ptext_bm = """<a name="BM_TITLE"/><font color="black" size="12"><b>Benchmark Report</b></font>"""
        benchmarks_title = Paragraph(ptext_bm, centered)
        benchmarks_title.keepWithNext = True    
        
        
        ptext_bm_intro = """
        Supported benchmark list:<br />
        1. <b>STRESS-NG</b>: designed to exercise various physical subsystems of a computer.<br />
        2. <b>STRESSAPPTEST</b>: memory test, maximize randomized traffic to memory from processor and I/O.<br />
        3. <b>HPCG</b>: intended to model the data access patterns of real-world applications.<br />
        4. <b>HPL</b>: High Performance Computing Linpack Benchmark. <br />
        5. <b>GPU-BURN</b>: Multi-GPU CUDA stress test. <br />
        6. <b>NCCL</b>: a stand-alone library of standard communication routines for GPUs.
        """
        benchmarks_intro = Paragraph(ptext_bm_intro, bm_intro)
        benchmarks_intro.keepWithNext = True
        
        
        
        self.story.append(benchmarks_title)
        self.story.append(p)
        self.story.append(benchmarks_intro)
        
        if len(benchmark_data) == 0:
            ptext_nocontent1 = """<font>WARNING: No Benchmark selected or performed !!</font>"""
            ptext_nocontent2 = """<font>1. Use UDP server controller page to perform benchmarks.</font>"""
            ptext_nocontent3 = """<font>2. Use UDP benchmark result page to select results.</font>"""
            benchmarks_nocontent1 = Paragraph(ptext_nocontent1, warning)
            benchmarks_nocontent2 = Paragraph(ptext_nocontent2, warning)
            benchmarks_nocontent3 = Paragraph(ptext_nocontent3, warning)
            benchmarks_nocontent1.keepWithNext = True
            benchmarks_nocontent2.keepWithNext = True
            benchmarks_nocontent3.keepWithNext = True
            self.story.append(ConditionalSpacer(width=1, height=2.5))
            self.story.append(benchmarks_nocontent1)
            self.story.append(benchmarks_nocontent2)
            self.story.append(benchmarks_nocontent3)
        
        ptext_chart = 'Results Bar Plot is as shown below'
        ptext_table = 'Results Table is as shown below'
        ptext_table_non_num = 'Non-Numerical Results Table is as shown below'
        benchmark_number = 1
        
        
        
        for data, unit, r_name, node, name in zip(benchmark_data,benchmark_unit, result_name, benchmark_node,list(benchmark_map.keys())):
            printf('Unit is:')
            printf(unit)
            
            benchmarks_chartTitle = Paragraph(ptext_chart, bm_title)
            benchmarks_tableTitle = Paragraph(ptext_table, bm_title)
            benchmarks_tableTitle_non_num = Paragraph(ptext_table_non_num, bm_title)
            
            # check if result type is numerical
            result_type = 0 # default is numerical 
            for t in data:
                for i in t:
                    if isinstance(i, int) or isinstance(i, float):
                        continue
                    else:
                        result_type = 1 # numerical result
                        break
                       
            if result_type == 0:
                data3 = []
                draw = Drawing(600,200)
                bar = VerticalBarChart()
                bar.x = 0
                bar.y = 0
                bar.height = 150
                bar.width = 500
                #bar.valueAxis.valueMin = min(min(data)) * 0.9
                bar.valueAxis.valueMin = 0 
                printf('Benchmark Data is:')
                printf(data)
                max_result = data[0][0]
                # get max benchmark results for the plot 
                for t in data:
                    if max_result < max(t):
                        max_result = max(t)                
                bar.valueAxis.valueMax = max_result * 1.15
                #bar.valueAxis.valueMax = 250000
                #bar.valueAxis.valueStep = 50000
                bar.strokeColor = colors.black
                bar.bars[0].fillColor = colors.lightblue
                bar.bars[1].fillColor = colors.lightgreen
                bar.bars[2].fillColor = colors.gold
                bar.categoryAxis.labels.angle = 20
                bar.categoryAxis.labels.dx = -35
                bar.categoryAxis.labels.dy = -10
                bar.data = data
                bar.categoryAxis.categoryNames = node
                #bar.categoryAxis.style = 'stacked'
                lab = Label() 
                lab2 = Label()
                lab.x = 0
                lab.y = 160
                lab2.x = 225
                lab2.y = 175
                lab.setText(cleanUnits(unit,'all'))
                lab.fontSize = 12
                lab2.setText(name)
                lab2.fontSize = 16
                draw.add(bar, '')
                draw.add(lab)
                draw.add(lab2)
                cur_content = "<font size=%s><b>%s</b></font>" % (font_size+2, name)
                cur_benchmark_title = Paragraph(cur_content, centered_bm)
                for item in node, data:
                    if item is node:
                        ptext = "<font size=%s>%s</font>" % (font_size-1, 'Serial Number')
                        p1 = Paragraph(ptext, centered)
                        formatted_line_data.append(p1)
                        for a in item:
                            ptext = "<font size=%s>%s</font>" % (font_size-1, a)
                            p1 = Paragraph(ptext, centered)
                            formatted_line_data.append(p1)
                        data3.append(formatted_line_data)
                        formatted_line_data = []
                    if item is data:
                        for b_index, b in enumerate(item):
                            ptext = "<font size=%s>%s</font>" % (font_size-1, cleanUnits(r_name,b_index) + ' ' + cleanUnits(unit,b_index))
                            p1 = Paragraph(ptext, centered)
                            formatted_line_data.append(p1)
                            for c in b:
                                ptext = "<font size=%s>%s</font>" % (font_size-1, str(c))
                                p1 = Paragraph(ptext, centered)
                                formatted_line_data.append(p1)
                            data3.append(formatted_line_data)
                            formatted_line_data = []
                printf(name + ' Table length is ' + str(len(data3)))
                t = Table(data3, colWidths=80, rowHeights=40, style=[
                    ('GRID',(0,0), (-1,-1),0.5,colors.black),
                    ('ALIGN', (0,-1),(-1,-1), 'CENTER'),
                    ('ROWBACKGROUNDS', (0, 0), (-1, -1), create_table_colors(len(data3),colors.lightgrey,colors.lightblue))
                ])
                #self.story.append(KeepTogether([draw,spacer,t,spacer,p]))
                self.story.append(KeepTogether([spacer,benchmarks_chartTitle,draw,spacer,spacer,benchmarks_tableTitle,spacer_median,cur_benchmark_title,spacer_median,t,spacer_median,hr_line,spacer]))
                #self.story.append(PageBreak())
            
            else:
                data3 = []
                cur_content = "<font size=%s><b>%s</b></font>" % (font_size+2, name)
                cur_benchmark_title = Paragraph(cur_content, centered_bm)
                for item in node, data:
                    if item is node:
                        ptext = "<font size=%s>%s</font>" % (font_size-1, 'Serial Number')
                        p1 = Paragraph(ptext, centered)
                        formatted_line_data.append(p1)
                        for a in item:
                            ptext = "<font size=%s>%s</font>" % (font_size-1, a)
                            p1 = Paragraph(ptext, centered)
                            formatted_line_data.append(p1)
                        data3.append(formatted_line_data)
                        formatted_line_data = []
                    if item is data:
                        for b_index, b in enumerate(item):
                            ptext = "<font size=%s>%s</font>" % (font_size-1, cleanUnits(r_name,b_index))
                            p1 = Paragraph(ptext, centered)
                            formatted_line_data.append(p1)
                            for c in b:
                                ptext = "<font size=%s>%s</font>" % (font_size-1, str(c))
                                p1 = Paragraph(ptext, centered)
                                formatted_line_data.append(p1)
                            data3.append(formatted_line_data)
                            formatted_line_data = []
                printf(name + ' Table length is ' + str(len(data3)))
                
                t = Table(data3, colWidths=80, rowHeights=30, style=[
                    ('GRID',(0,0), (-1,-1),0.5,colors.black),
                    ('ALIGN', (0,-1),(-1,-1), 'CENTER'),
                    ('ROWBACKGROUNDS', (0, 0), (-1, -1), create_table_colors(len(data3),colors.lightgrey,colors.lightblue))
                ])
                #self.story.append(KeepTogether([draw,spacer,t,spacer,p]))
                self.story.append(KeepTogether([benchmarks_tableTitle_non_num,spacer_median,cur_benchmark_title,spacer_median,t,spacer_median,hr_line,spacer]))
                #self.story.append(PageBreak())


        ########################################All Parts' Serial Number summary##################################################
        self.story.append(PageBreak())
        ptext_hn = """<a name="PN&SN"/><font color="black" size="12"><b>Archive: all parts' Part Number (PN), Serial Number (SN) and Firmware (FW)</b></font>"""
        hn_title = Paragraph(ptext_hn, centered)
        hn_title.keepWithNext = True
        if has_l12_metrics == 1:
            self.story.append(hn_title) 
            self.story.append(p)

        ptext_hn_intro = """
        Table below shows the parts' PN, SN and FW for each part of every node:<br />
        """
        sn_node_intro = Paragraph(ptext_hn_intro, other_intro)
        sn_node_intro.keepWithNext = True
        if has_l12_metrics == 1:
            self.story.append(sn_node_intro)
        
        if 'hw_data' in list_of_collections and len(serialNumber) == len(MacAddress) and len(serialNumber) == len(sn_data_sort):
            for sn, mac, cur_sn in zip(serialNumber, MacAddress, sn_data_sort):
                ptext_sn_sub = """<a name="NH_TITLE"/><font color="black" size="12"><b>SN: """ + sn + """ MAC: """ + mac +"""</b></font>"""
                sn_title_sub = Paragraph(ptext_sn_sub, bm_title)
                sn_title_sub.keepWithNext = True
                ## Create header with column names
                d4 = []
                sn_columns = ["Item", "Information","Qty"]
                for text in sn_columns:
                    ptext = "<font size=%s><b>%s</b></font>" % (font_size, text)
                    p4 = Paragraph(ptext, centered)
                    d4.append(p4)

                data4 = [d4]

                # check mac address
                if cur_sn['mac'].strip().lower() != mac.replace('-','').replace(':','').strip().lower():
                    print('Warning: Found unmatching MAC addressses between Database and CSV file.')
                    print(cur_sn['mac'].strip().lower())
                    print(mac.replace('-','').replace(':','').strip().lower())
                
                for cur_key in cur_sn.keys():
                    if 'SN' not in cur_key and 'FW' not in cur_key and 'MAC' not in cur_key and 'PN' not in cur_key:
                        continue
                    cur_quantity = str(cur_sn[cur_key].count(sn_seperator)) # count the number of items by counting the seporators
                    if len(cur_sn[cur_key]) >= 1 and cur_sn[cur_key].endswith(sn_seperator):  # remove the tail seporator
                        cur_box_content = cur_sn[cur_key][:-len(sn_seperator)]
                    else:
                        cur_box_content = cur_sn[cur_key]
                    ptext_key = "<font size=%s>%s</font>" % (font_size-2, cur_key)
                    ptext_value = "<font size=%s>%s</font>" % (auto_font_size(cur_box_content,sn_seperator,sn_seperator_real), cur_box_content)
                    ptext_quantity = "<font size=%s>%s</font>" % (font_size-2, cur_quantity)
                    p4_key = Paragraph(ptext_key, centered)
                    p4_value = Paragraph(ptext_value, centered)
                    p4_quantity = Paragraph(ptext_quantity, centered)
                    data4.append([p4_key,p4_value,p4_quantity])    
                    
                table4 = Table(data4, colWidths=[55, 355, 30])
                table4.setStyle(TableStyle([
                    ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                    ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
                    ('BOX', (0,0), (-1,-1), 0.25, colors.black),
                    ('ROWBACKGROUNDS', (0, 0), (-1, -1), create_table_colors(len(data4),colors.lightgrey,colors.lightblue))
                ]))  
                if has_l12_metrics == 1:
                    self.story.append(KeepTogether([sn_title_sub,spacer_tiny,table4,spacer_tiny,hr_line,spacer_tiny]))
        else:
            ptext_sn_nodata = """
            Warning: No OS level Hardware Data can be found in Database:<br />
            1. Make sure the 'hw_data' is inside the input directory.<br />
            2. Make sure the config file is inside the 'hw_data' directory.<br />
            3. Check the MAC addresses are the same as the input files.<br />
            4. Check if any nodes hw data missing.<br />
            5. Go the UDP Controller page to reload the data.<br />
            """
            hardware_node_nodata = Paragraph(ptext_sn_nodata, warning)
            if has_l12_metrics == 1:
                self.story.append(hardware_node_nodata)
            
        ########################################Activation summary##################################################
        self.story.append(PageBreak())
        ptext_oob = """<a name="License"/><font color="black" size="12"><b>Archive: System Activation Status</b></font>"""
        oob_title = Paragraph(ptext_oob, centered)
        oob_title.keepWithNext = True
        self.story.append(oob_title) 
        self.story.append(p)

        if 'N/A' not in saa_info and len(saa_info) == len(MacAddress) and len(serialNumber) == len(saa_info):
            ## Create header with column names
            d5 = []
            oob_columns = ["Serial Number", "MAC"]
            oob_columns += list(saa_info[0].keys())
            for text in oob_columns:
                ptext = f"<font size={font_size-3}><b>{text}</b></font>"
                p5 = Paragraph(ptext, centered)
                d5.append(p5)
            data5 = [d5]
            for cur_sum, mac, sn in zip(saa_info, MacAddress, serialNumber):
                print(cur_sum)
                p5_cur = []
                p5_cur.append(Paragraph(f"<font size={font_size-2}>{sn}</font>", centered))
                p5_cur.append(Paragraph(f"<font size={font_size-2}>{mac}</font>", centered))
                for k, v in cur_sum.items():
                    ptext_cur = f"<font size={font_size-2}>{v}</font>"
                    p5_cur.append(Paragraph(ptext_cur, centered))
                data5.append(p5_cur)
            table5 = Table(data5, colWidths=[87, 100, 87, 87, 87])
            table5.setStyle(TableStyle([
                    ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                    ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
                    ('BOX', (0,0), (-1,-1), 0.25, colors.black),
                    ('ROWBACKGROUNDS', (0, 0), (-1, -1), create_table_colors(len(data5),colors.lightgrey,colors.lightblue))
                ]))  
            self.story.append(KeepTogether([spacer_tiny,table5]))
        else:
            ptext_OOB_nodata = """
            Warning: No SAA info can be found in Database:<br />
            1. Please verify if SAA info has been inserted to the Database.<br />
            2. Try rerun the L12-CM to see if it is working.<br />
            """
            OOB_nodata = Paragraph(ptext_OOB_nodata, warning)
            self.story.append(OOB_nodata)
        
        if has_issue == 1:
            #Issue section
            self.story.append(PageBreak())
            ptext_issue = f"""<a name="ISSUE_TITLE"/><font color="black" size="12"><b>L12 Validation Issue Report for {rackname} (Sample)</b></font>"""
            issue_title = Paragraph(ptext_issue, centered)
            
            ptest_issue_subtitle = """<font color="black" size="10"><b>Issue 1: Processor Throttling Issue</b></font>"""        
            issue_subtitle_1 = Paragraph(ptest_issue_subtitle, issue_font)             
            
            #ptext_issue_paragraph_1 = """
            #Whenever we try to enter BIOS in Figure 1 in order to perform IPMI IP configuration setup,
            #after “Entering Setup”, the system restarts again. It appears this reboot keeps occurring due to
            #mixing families of nvme drives on this server. The other server (SN: S411795X0A17866) has all 9300
            #Micron nvme storage drives, while this server (SN: S411795X0A17867) has 17x 9300 Micron nvme 
            #and 5x 7300 Micron nvme storage drives. So the optimal solution to such issue is use the same 
            #family of nvme storage drives.
            #"""

            ptext_issue_paragraph_1 = """
            When SYS-221H-TNR is on, the system log keeps reporting “Processor automatically throttled” as shown in Figure 1 below. 
        The CPU temperature does not look like it is in critical condition. In idle state, CPU temperature is about 40 degrees, 
        while during load, CPU temperature is less than 70 degrees during the time the issue happened as shown in Figure 2 below.
        """
            issue_report_1 = Paragraph(ptext_issue_paragraph_1, issue_font)               
            
            self.story.append(spacer_conclusion)      
            ptext_figure1_caption = "Figure 1. Event logs showing \"Processor automatically throttled\""
            figure1_caption = Paragraph(ptext_figure1_caption, issue_caption_font)        

            ptext_figure2_caption = "Figure 2. CPU temperature chart display when CPU throttling issue kept appearing in event logs"
            figure2_caption = Paragraph(ptext_figure2_caption, issue_caption_font)        

            self.story.append(issue_title)
            self.story.append(spacer_conclusion)
            self.story.append(p)
            self.story.append(spacer_conclusion)
            self.story.append(issue_subtitle_1)
            self.story.append(spacer_conclusion)
            self.story.append(issue_report_1)
            self.story.append(spacer_conclusion)        
            self.story.append(spacer_conclusion)        
            self.story.append(spacer_conclusion)        
            self.story.append(get_image(f"sample_report_img/CPU_throttle.png", height=15*cm, width=15*cm))
            self.story.append(figure1_caption)
            self.story.append(spacer_conclusion)        
            self.story.append(spacer_conclusion)        
            self.story.append(get_image(f"sample_report_img/CPU_temp_chart.png", height=15*cm, width=15*cm))
            self.story.append(figure2_caption)
            self.story.append(spacer_conclusion)        
            self.story.append(spacer_conclusion)        

            # Paragraph Issue 2
           
            ptest_issue_subtitle = """<font color="black" size="10"><b>Issue 2: PCI-E bandwidth limitation for M.2</b></font>"""        
            issue_subtitle_2 = Paragraph(ptest_issue_subtitle, issue_font)             
     
            ptext_issue_paragraph_2 = """
            As shown in Figure 3, nvme0n1 and nvme1n1 has been capped at 2.0 GB/s, whereas other partitions’ bandwidths are capped at 3.9 GB/s. 
        This limitation can significantly impact the reading and writing performance of those nvme drives. 
        Despite this limitation, the performance of nvme0n1 and nvme1n1 is not a concern.
        """
            issue_report_2 = Paragraph(ptext_issue_paragraph_2, issue_font)               
            
            self.story.append(spacer_conclusion)      
            ptext_figure3_caption = "Figure 3. PCI-E Topo diagram"
            figure3_caption = Paragraph(ptext_figure3_caption, issue_caption_font)        

            self.story.append(spacer_conclusion)
            self.story.append(issue_subtitle_2)
            self.story.append(spacer_conclusion)
            self.story.append(issue_report_2)
            self.story.append(spacer_conclusion)        
            self.story.append(get_image(f"sample_report_img/PCIE_topo.png", height=15*cm, width=15*cm))
            self.story.append(figure3_caption)

        # Paragraph Issue 3

            ptest_issue_subtitle = """<font color="black" size="10"><b>Issue 3: Failed to Assign IO</b></font>"""        
            issue_subtitle_3 = Paragraph(ptest_issue_subtitle, issue_font)             
     
            ptext_issue_paragraph_3 = """
            We also found an assignment failure about IO as shown in Figure 4. This message consistently appears 
            when using dmesg command and rebooting the X13 system for 10 cycles during the DC Cycle Test. It 
            indicates Linux cannot assign an IO resource on this PCI device; however, if the PCIe root port does 
            not connect a device, the assigning of the IO resource is not used/needed. User can ignore this 
            message, since it does not affect the operation or functionality of the server or PCI device.
        """
            issue_report_3 = Paragraph(ptext_issue_paragraph_3, issue_font)               
            
            self.story.append(spacer_conclusion)      
            ptext_figure4_caption = "Figure 4. The OS dmesg shows failed to assign IO everytime boot up."
            figure4_caption = Paragraph(ptext_figure4_caption, issue_caption_font)        

            self.story.append(spacer_conclusion)
            self.story.append(issue_subtitle_3)
            self.story.append(spacer_conclusion)
            self.story.append(issue_report_3)
            self.story.append(spacer_conclusion)        
            self.story.append(get_image(f"sample_report_img/Fail_to_assign_IO.png", height=15*cm, width=15*cm))
            self.story.append(figure4_caption)
            self.story.append(spacer_conclusion)        
            self.story.append(spacer_conclusion)        

        # Paragraph Issue 4

            ptest_issue_subtitle = """<font color="black" size="10"><b>Issue 4: Direct firmware load for qat_4xxx_mmp.bin failed</b></font>"""        
            issue_subtitle_4 = Paragraph(ptest_issue_subtitle, issue_font)             
     
            ptext_issue_paragraph_4 = """
            This error occurred on this system because Intel Quick Assist Technology firmware is not 
            installed as shown in Figure 5 below. Since this system’s Intel CPU has not been formally released yet, 
            the Intel QAT feature may not be supported on this CPU. <br />
            User can ignore this message, since it does not affect the operation or functionality of the server or PCI device.
        """
            issue_report_4 = Paragraph(ptext_issue_paragraph_4, issue_font)               
            
            self.story.append(spacer_conclusion)      
            ptext_figure5_caption = "Figure 5. Failed to load Intel QAT firmware message"
            figure5_caption = Paragraph(ptext_figure5_caption, issue_caption_font)        

            self.story.append(spacer_conclusion)
            self.story.append(issue_subtitle_4)
            self.story.append(spacer_conclusion)
            self.story.append(issue_report_4)
            self.story.append(spacer_conclusion)        
            self.story.append(spacer_conclusion)        
            self.story.append(spacer_conclusion)        
            self.story.append(get_image(f"sample_report_img/Fail_Intel_QAT.png", height=15*cm, width=15*cm))
            self.story.append(figure5_caption)

        if has_conclusion == 1:
            #conclusion_section
            self.story.append(PageBreak())
            ptext_conclusion = f"""<a name="CONCLUSION_TITLE"/><font color="black" size="12"><b>L12 Validation Conclusion for {rackname}</b></font>"""       
            conclusion_title = Paragraph(ptext_conclusion, centered)

            ptext_conclusion_performance = """
            <font color="black" size="11"><b>Performance Highlights</b></font><br />
            <br />
              &#x2022; <b>High Performance Linpack</b> performance is <b>5250.6 GFlops</b>, as a reference, dual EPYC 7742 about 3800 GFlops.<br />
              &#x2022; <b>LAMMPS</b> 20k Atoms Performance is <b>40.504 ns/day</b>, as a reference, dual EPYC 7742 about 32.1 ns/day.<br/>
              &#x2022; <b>GROMACS</b> water_GMX50_bare Performance is <b>11.755 ns/day</b>, as a reference, dual EPYC 7763 about 10.05 ns/day.  <br />
              &#x2022; <b>MLC</b> sequential read/write bandwidth is <b>574344.3 MB/s</b>, random read/write bandwidth is 391603.5 MB/s. (Read:Write = 2:1).<br />
              &#x2022; <b>FIO</b> sequential and random read write performance can match advertisement. <br />
            <br />
            """
            
            performance_highlight = Paragraph(ptext_conclusion_performance, issue_font)

            ptext_conclusion_issue = """
            <font color="black" size="11"><b>Major Issues (Sample)</b></font><br />
            <br />
              &#x2022; Event log keeps reporting “Processor Throttled” despite CPU being in idle state. <br />
            <br />
            """
            conclusion_issue = Paragraph(ptext_conclusion_issue, issue_font)
            
            ptext_conclusion_issue2 = """
            <font color="black" size="11"><b>Minor Issues (Sample)</b></font><br />
            <br />
              &#x2022; Failed to assigned IO also appeared from dmesg. This error can be ignored, since it does not affect the operation or functionality of the server or PCI device. <br />
              &#x2022; Due to speed limitation on NVMe cables for nvme0n1 and nvme1n1, their performance is not considered a major issue. <br />
              &#x2022; Intel QAT firmware not installed is not a major concern as well. It does not affect operations or performance of this system. <br />
            <br />
            """
            #conclusion_issue = Paragraph(ptext_conclusion_issue, issue_font)
            conclusion_issue2 = Paragraph(ptext_conclusion_issue2, issue_font)
        

            self.story.append(conclusion_title)
            self.story.append(spacer_conclusion)
            self.story.append(p)
            self.story.append(spacer_conclusion)
            self.story.append(spacer_conclusion)
            self.story.append(spacer_conclusion)
            self.story.append(spacer_conclusion)
            self.story.append(performance_highlight)
            self.story.append(spacer_conclusion)
            self.story.append(conclusion_issue)
            self.story.append(spacer_conclusion)
            self.story.append(conclusion_issue2)
        
        if has_notes == 1:
            #notes section
            self.story.append(PageBreak())
            ptext_notes_header = f"""<a name="NOTES_TITLE"/><font color="black" size="12"><b>L11 Testing Notes for {rackname}</b></font>"""
            notes_title = Paragraph(ptext_notes_header, centered)

            ptext_notes_bullets = """
            <font color="black" size="11"><b>Notes</b></font><br />
            <br />
              &#x2022; ADD NOTE HERE.<br />
              &#x2022; ADD NOTE HERE.<br/>
            <br />
            """

            formatted_notes = Paragraph(ptext_notes_bullets, issue_font)

            self.story.append(notes_title)
            self.story.append(spacer_conclusion)
            self.story.append(p)
            self.story.append(spacer_conclusion)
            self.story.append(spacer_conclusion)
            self.story.append(spacer_conclusion)
            self.story.append(spacer_conclusion)
            self.story.append(formatted_notes)


    #----------------------------------------------------------------------

    def _addPageNumber(self):
        page_num = self.c.getPageNumber()
        text = "%s" % page_num
        self.c.setFillColorRGB(0,0,0) # black
        self.c.setFont('Helvetica', 10)
        self.c.drawCentredString(self.width/2, self.height-760, text)

    def _addAuthor(self):
        self.c.setFont('Helvetica', 10)
        datetime_text = 'Generated at: ' + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ' ' + os.environ['TZ'] 
        self.c.drawString(20, self.height-750, "AI and HPC Team: ReeannZ@supermicro.com" )
        self.c.drawString(20, self.height-760, datetime_text)

    def _addLogos(self):
        smclogo = "cluster_report_images/supermicro.jpg"
        ssiclogo = "cluster_report_images/SSIC.png"
        self.c.drawImage(ssiclogo, 20, self.height + 10, 119, 20)
        self.c.drawImage(smclogo, self.width-85, self.height + 10, 62, 30)
        self.c.drawImage(ssiclogo, self.width-141, self.height-765, 119, 20)     

    def _addLineBreak(self, section_height, length=60):
        self.c.setLineWidth(1)
        self.c.line(self.width/2-length/2, section_height, self.width/2+length/2, section_height)
        

#----------------------------------------------------------------------
if __name__ == "__main__":
    t = Test()
    t.run()
