from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle, TA_CENTER
from reportlab.lib.units import inch, mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, SimpleDocTemplate, Spacer, Image, KeepTogether, LongTable, TableStyle, PageBreak
from pymongo import MongoClient
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors
from reportlab.lib.colors import PCMYKColor, HexColor, blue, red
from reportlab.graphics.shapes import Drawing, Line
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.textlabels import Label
from reportlab.platypus.flowables import HRFlowable
from get_data import find_min_max_rack
import os
import pandas as pd
import sys
import math
import datetime
import pymongo

class ConditionalSpacer(Spacer):

    def wrap(self, availWidth, availHeight):
        height = min(self.height, availHeight-1e-8)
        return (availWidth, height)

def printf(data):
    print(data, flush=True)

def getSerialNumberFromOsip(ip,opt):
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

mongoport = int(os.environ['MONGOPORT']) # using in jupyter: 8888
rackname = os.environ['RACKNAME'].upper() 
client = MongoClient('localhost', mongoport) # using in jupyter: change localhost to 172.27.28.15
db = client.redfish
collection = db.servers
collection2 = db.udp
collection3 = db.monitor
list_of_collections = db.list_collection_names()
bmc_ip = []
timestamp = []
serialNumber = []
modelNumber = []
bmcVersion = []
biosVersion = []
bmc_event = []
MacAddress = []
bmcMacAddress = []
benchmark_node = []
benchmark_data = []
benchmark_unit = []
benchmark_name = {}

for data in list(collection2.find({})):
    if data['star'] != 1:
        continue
    elif data['benchmark'] not in benchmark_name:
        benchmark_name[data['benchmark']] = 1
    else:
        benchmark_name[data['benchmark']] += 1
n = 6
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


for i, bm in enumerate(list(benchmark_map.keys())):
    counter = 0
    skip = benchmark_map[bm][0]
    cur_benchmark_data = []
    for data in list(collection2.find({})):
        if data['star'] == 1 and data['benchmark'] in bm and skip != 0:
            skip -= 1
            continue
        elif data['star'] == 1 and data['benchmark'] in bm and counter < len(benchmark_map[bm]):
            try:
                benchmark_node[i].append(getSerialNumberFromOsip(data['os_ip'],0))
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
        bmcMacAddress.append(i['UUID'][24:])
    except:
        bmcMacAddress.append('N/A')
    try:
        serialNumber.append(getSerialNumberFromOsip(i['BMC_IP'],1))
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
        
serialNum, processorModel, processorCount, totalMemory, memoryPN, memoryCount, driveModel, driveCount = ([] for i in range(8))

for j in collection.find({}):
    try:
        serialNum.append(getSerialNumberFromOsip(j['BMC_IP'],1))
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
        driveModel.append(j['Systems']['1']['SimpleStorage']['1']['Devices'][0]['Model'])
    except:
        driveModel.append('N/A')
    try:
        driveCount.append(len(j['Systems']['1']['SimpleStorage']['1']['Devices']))
    except:
        driveCount.append('N/A')


res = [list(i) for i in zip(serialNumber, bmcMacAddress, modelNumber, bmc_ip, biosVersion, bmcVersion, timestamp)]
res2 = [list(j) for j in zip(serialNum, processorModel, processorCount, totalMemory, memoryPN, memoryCount, driveModel, driveCount)]

for ip in bmc_ip:
    if 'N/A' not in bmc_ip:
        df_pwd = pd.read_csv(os.environ['OUTPUTPATH'],names=['ip','os_ip','mac','node','pwd'])
        MacAddress.append(df_pwd[df_pwd['ip'] == ip]['mac'].values[0])
    else:
        MacAddress.append('N/A')
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
    temp_keys = ["CPU","Inlet","System","Peripheral","GPU","FPGA","ASIC"] # other sensors FPGA and ASIC are intel habana GPU
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
                 'cpu_model':'N/A','cpu_num':'0','cpu_note':'N/A',\
                 'mem_model':'N/A','mem_num':'0','mem_note':'N/A',\
                 'gpu_model':'N/A','gpu_num':'0','gpu_note':'N/A',\
                 'hd_model':'N/A','hd_num':'0','hd_note':'N/A',\
                 'nic_model':'N/A','nic_num':'0','nic_note':'N/A',\
                 'power_model':'N/A','power_num':'0','power_note':'N/A',\
                 'fan_model':'N/A','fan_num':'0','fan_note':'N/A'\
                }

#parsed_data = [template_data for i in range(len(all_hw_data))]
for item in all_hw_data:
    #print(item['Hostname'])
    parsed_data.append(template_data.copy()) # if not using copy(), all the dicts are the same reference
    if 'Hostname' in item:
        parsed_data[-1]['mac'] = item['Hostname'].replace('-','').replace(':','')
    if 'bmc_ip' in item:
        parsed_data[-1]['bmc_ip'] = item['bmc_ip']
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
            parsed_data[-1]['cpu_note'] += item['CPU']['Thread(s) per core'] + ' Threads '
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
            parsed_data[-1]['hd_num'] = parsed_data[-1]['hd_num'].replace('0','')
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
            for index_g in item['Graphics']['GPU']:
                if cur_model == 'N/A' and 'Model' in item['Graphics']['GPU'][index_g]:
                    cur_model = item['Graphics']['GPU'][index_g]['Model']
                elif cur_model != 'N/A' and cur_model != item['Graphics']['GPU'][index_g]['Model']:
                    cur_model = "Different models found!"
            parsed_data[-1]['gpu_model'] = cur_model
    
    if 'NICS' in item:
        cur_nic = {}
        for index_n in item['NICS']:
            nic = item['NICS'][index_n]
            if 'Name' in nic:
                # Initilize for the model
                if nic['Name'] not in cur_nic:
                    cur_nic[nic['Name']] = 1
                # Count the model
                else:
                    cur_nic[nic['Name']] += 1
                    
        parsed_data[-1]['nic_model'] = '<br/>'.join(cur_nic.keys())
        for key in cur_nic:
            #print(cur_storage[key][1])
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
            parsed_data[-1]['power_num'] = parsed_data[-1]['power_num'].replace('0','')
            parsed_data[-1]['power_num'] += str(cur_psu[key]) + '<br/>'
        parsed_data[-1]['power_num'] = parsed_data[-1]['power_num'].strip()
    
    if 'FANS' in item:
        num_fan = 0
        parsed_data[-1]['fan_note'] = 'All Good'
        for index_f in item['FANS']:
            fan = item['FANS'][index_f]
            if type(fan) == dict:
                num_fan += 1
                if fan.get('status') != 'ok':
                    parsed_data[-1]['fan_note'] = 'Error'
        parsed_data[-1]['fan_num'] = str(num_fan)
    
    if 'Memory' in item:
        if 'DIMMS' in item['Memory']:
            parsed_data[-1]['mem_num'] = item['Memory']['DIMMS']
        if 'Total Memory' in item['Memory']:
            parsed_data[-1]['mem_note'] = 'Total Size: ' + item['Memory']['Total Memory'] + ' MB'
        if 'Slots' in item['Memory']:
            all_manufactures = []
            for dim in item['Memory']['Slots']:
                if 'Manufacturer' in item['Memory']['Slots'][dim] and item['Memory']['Slots'][dim]['Manufacturer'] not in all_manufactures:
                    all_manufactures.append(item['Memory']['Slots'][dim]['Manufacturer'])
        #print(all_manufactures)
        parsed_data[-1]['mem_model'] = '<br/>'.join(all_manufactures)
#parsed_data[0]['mac'] = -1
parsed_data_sort = []

# sort the parsed data according to the bmc_ip list
for ip in bmc_ip:
    for item in parsed_data:
        if item['bmc_ip'] == ip:
            parsed_data_sort.append(item)

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
        
        smclogo = "supermicro.jpg"
        ssiclogo = "SSIC.png"
        self.c.drawImage(smclogo, self.width-85, self.height, 62, 30)
        self.c.drawImage(ssiclogo, self.width-200, self.height-765, 178, 30)
        #header_text = """<a name="TOP"/><strong>RACK REPORT: """ + rackname + """</strong>"""
        #p = Paragraph(header_text, centered)
        #p.wrapOn(self.c, self.width, self.height)
        #p.drawOn(self.c, *self.coord(0, 0, mm))

    #----------------------------------------------------------------------
    def myFirstPage(self, canvas, doc):
        normal = self.styles["Normal"]
        Title = "L12 Test Report for " + rackname
        introduction = "Supermicro’s HPC and AI team (part of Supermicro Solution and Integration Center) is an elite team of software and hardware engineers. We generate and publish state-of-the-art benchmarks showcasing the performance of Supermicro’s wide array of Super Servers. We also work with the industry leading HPC and AI partners to generate the latest and greatest performance data."
        bmlogo = "logos.png"
        slogo = "ourSolutions.png"
        smclogo = "supermicro.jpg"
        ssiclogo = "SSIC.png"
        datetime_text = "Report generated at: " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        p = Paragraph(introduction, normal)
        w, h = p.wrap(self.doc.width, self.doc.topMargin)
        self.c = canvas
        self.c.drawImage(smclogo, self.width-85, self.height, 62, 30)
        self.c.drawImage(ssiclogo, self.width-200, self.height-765, 178, 30)
        self.c.setFont('Helvetica-Bold',16)
        self.c.drawCentredString(self.width/2.0, self.height-10, Title)
        self.c.setFont('Helvetica',12)
        #self.c.drawCentredString(self.width/2.0, self.height-25, datetime_text)
        self.c.drawString(10,45, "Test Report Generated by HPC & AI Team")
        self.c.drawString(10,30,datetime_text)
        p.drawOn(self.c, self.doc.leftMargin, self.height-75)
        self.c.drawCentredString(self.width/2, self.height-90, "Here are some examples of the benchmarks we have conducted:")
        self.c.drawImage(bmlogo, 75, self.height-300, 466, 200)
        self.c.drawCentredString(self.width/2, self.height-315, "Here is a list of other solutions that we offer:")
        self.c.drawImage(slogo, 40, self.height-520, 534, 200)
        self.c.drawCentredString(self.width/2, self.height-545, "For more information about our services please visit:")
        self.c.drawCentredString(self.width/2, self.height-580, "If you would like to see an in-depth view of our benchmarks please visit our blog:")
        self.c.setFillColor(red)
        self.c.drawCentredString(self.width/2, self.height-630, "NOTE: Both pages require company network to access")
        self.c.setFillColor(blue)
        self.c.setFont('Helvetica-Bold',14)
        self.c.drawCentredString(self.width/2, self.height-560, "Supermicro Solution and Integration Center")
        self.c.drawCentredString(self.width/2, self.height-595, "HPC & AI Benchmarks")
        self.c.linkURL('http://solution.supermicro.com/', (165,225,445,245),relative=0)
        self.c.linkURL('http://172.31.32.198:8080/', (225,190,385,210),relative=0)
        
    #----------------------------------------------------------------------
    def createLineItems(self):
        """
        Create the line items
        """
        spacer = ConditionalSpacer(width=0, height=35)
        spacer_median = ConditionalSpacer(width=0, height=10)
        spacer_tiny = ConditionalSpacer(width=0, height=2.5)
        #Summary and Hardware Tables
        ## column names
        text_data = ["Serial Number", "BMC MAC Address", "Model Number", "BMC IP", "BIOS Version", "BMC Version", "Date"] # Date is timstamp
        text_data2 = ["Serial Number", "CPU Model", "CPU Count", "MEM (GB)", "DIMM PN", "DIMM Count", "Drive Model", "Drive Count"]

        d = []
        d2 = []
        font_size = 10
        centered = ParagraphStyle(name="centered", alignment=TA_CENTER)
        centered_bm = ParagraphStyle(name="centered_bm", fontSize=12, alignment=TA_CENTER)
        warning = ParagraphStyle(name="normal",fontSize=12, textColor="red",leftIndent=40)
        bm_title = ParagraphStyle(name="normal",fontSize=12,textColor="black",leftIndent=0)
        bm_intro = ParagraphStyle(name="normal",fontSize=8,leftIndent=0)
        other_intro = ParagraphStyle(name="normal",fontSize=8,leftIndent=0)
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

        table = Table(data, colWidths=[95, 90, 60, 75, 80, 80, 50])
        table.setStyle(TableStyle([
            ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
            ('BOX', (0,0), (-1,-1), 0.25, colors.black),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), create_table_colors(len(data),colors.lightgrey,colors.lightblue))
        ]))
        ptext = """<link href="#TABLE1" color="blue" fontName="Helvetica-Bold">Cluster Summary</link> 
/ <link href="#TABLE2"color="blue" fontName="Helvetica-Bold">Hardware Counts</link> 
/ <link href="#TABLE3"color="blue" fontName="Helvetica-Bold">Hardware Per Node</link> 
/ <link href="#SR_TITLE"color="blue" fontName="Helvetica-Bold">Sensors</link> 
/ <link href="#BM_TITLE"color="blue" fontName="Helvetica-Bold">Benchmark Report</link>"""
        
        ptext2 = """<a name="TABLE2"/><font color="black" size="12">Hardware Counts and Models """ + rackname + """</font>"""
        ptext1 = """<a name="TABLE1"/><font color="black" size="12">Cluster Summary for """ + rackname + """</font>"""
        p = Paragraph(ptext, centered)
        table2 = Table(data2, colWidths=[95, 120, 40, 40, 70, 40, 70, 40])
        table2.setStyle(TableStyle([
            ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
            ('BOX', (0,0), (-1,-1), 0.25, colors.black), 
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), create_table_colors(len(data2),colors.lightgrey,colors.lightblue))
        ]))
        
        paragraph1 = Paragraph(ptext1, centered)
        paragraph2 = Paragraph(ptext2, centered)
        paragraph1.keepWithNext = True
        paragraph2.keepWithNext = True
        p.keepWithNext = True
        
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
        self.story.append(cluster_summary_intro)       
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
        self.story.append(hardware_counts_intro)          
        #table2
        self.story.append(table2)     
        
        ########################################Node by Node Hardware summary##################################################
        self.story.append(PageBreak())
        ptext_hn = """<a name="TABLE3"/><font color="black" size="12">Detailed Hardware Information Per Node</font>"""
        hn_title = Paragraph(ptext_hn, centered)
        hn_title.keepWithNext = True
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
                ptext_hn_sub = """<a name="NH_TITLE"/><font color="black" size="12">Hardware List of SN: """ + sn + """ MAC: """ + mac +"""</font>"""
                hn_title_sub = Paragraph(ptext_hn_sub, centered)
                hn_title_sub.keepWithNext = True
                self.story.append(hn_title_sub) 
                self.story.append(ConditionalSpacer(width=1, height=2.5))     
                ## Create header with column names
                d3 = []
                hn_columns = ["Item Name", "Model Name", "Quantity", "Notes"]
                for text in hn_columns:
                    ptext = "<font size=%s><b>%s</b></font>" % (font_size, text)
                    p3 = Paragraph(ptext, centered)
                    d3.append(p3)

                data3 = [d3]

                hn_rows_basic =  ['Processor','Memory','GPU','Hard Drive','NIC cards','Power Supply','Fans']
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
                        elif 'Hard Drive' in hn_rows[i]:
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
                table3 = Table(data3, colWidths=[70, 170, 65, 170])
                table3.setStyle(TableStyle([
                    ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
                    ('BOX', (0,0), (-1,-1), 0.25, colors.black),
                    ('ROWBACKGROUNDS', (0, 0), (-1, -1), create_table_colors(len(data3),colors.lightgrey,colors.lightblue))
                ]))
                self.story.append(table3)
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
            self.story.append(hardware_node_nodata)
#######################################################################        
        
        #Sensor reading charts
        self.story.append(PageBreak())
        ptext_sr = """<a name="SR_TITLE"/><font color="black" size="12">Sensor Reading Report</font>"""
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
        ptext_bm = """<a name="BM_TITLE"/><font color="black" size="12">Benchmark Report</font>"""
        benchmarks_title = Paragraph(ptext_bm, centered)
        benchmarks_title.keepWithNext = True    
        
        
        ptext_bm_intro = """
        Benchmarks include but not limited to:<br />
        1. <b>STRESS-NG</b>: designed to exercise various physical subsystems of a computer.<br />
        2. <b>STRESSAPPTEST</b>: memory test, maximize randomized traffic to memory from processor and I/O.<br />
        3. <b>HPCG</b>: intended to model the data access patterns of real-world applications.<br />
        4. <b>HPL</b>: High Performance Computing Linpack Benchmark. <br />
        5. <b>GPU-BURN</b>: Multi-GPU CUDA stress test 
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
        
        ptext_chart = 'Restulst Bar Plot is as shown below'
        ptext_table = 'Results Table is as shown below'
        ptext_table_non_num = 'Non-Numerical Results Table is as shown below'
        benchmark_number = 1
        
        hr_line = HRFlowable(width="100%", thickness=1, lineCap='round', color=colors.lightgrey, spaceBefore=1, spaceAfter=1, hAlign='CENTER', vAlign='BOTTOM', dash=None)
        
        
        for data, unit, node, name in zip(benchmark_data,benchmark_unit,benchmark_node,list(benchmark_map.keys())):
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
                            ptext = "<font size=%s>%s</font>" % (font_size-1, 'Result No.' + str(b_index))
                            p1 = Paragraph(ptext, centered)
                            formatted_line_data.append(p1)
                            for c in b:
                                ptext = "<font size=%s>%s</font>" % (font_size-1, str(c) + ' ' + cleanUnits(unit,b_index))
                                p1 = Paragraph(ptext, centered)
                                formatted_line_data.append(p1)
                            data3.append(formatted_line_data)
                            formatted_line_data = []
                printf(name + ' Table length is ' + str(len(data3)))
                t = Table(data3, colWidths=90, rowHeights=40, style=[
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
                            ptext = "<font size=%s>%s</font>" % (font_size-1, 'Result No.' + str(b_index))
                            p1 = Paragraph(ptext, centered)
                            formatted_line_data.append(p1)
                            for c in b:
                                ptext = "<font size=%s>%s</font>" % (font_size-1, str(c))
                                p1 = Paragraph(ptext, centered)
                                formatted_line_data.append(p1)
                            data3.append(formatted_line_data)
                            formatted_line_data = []
                printf(name + ' Table length is ' + str(len(data3)))
                
                t = Table(data3, colWidths=90, rowHeights=30, style=[
                    ('GRID',(0,0), (-1,-1),0.5,colors.black),
                    ('ALIGN', (0,-1),(-1,-1), 'CENTER'),
                    ('ROWBACKGROUNDS', (0, 0), (-1, -1), create_table_colors(len(data3),colors.lightgrey,colors.lightblue))
                ])
                #self.story.append(KeepTogether([draw,spacer,t,spacer,p]))
                self.story.append(KeepTogether([benchmarks_tableTitle_non_num,spacer_median,cur_benchmark_title,spacer_median,t,spacer_median,hr_line,spacer]))
                #self.story.append(PageBreak())
#----------------------------------------------------------------------
if __name__ == "__main__":
    t = Test()
    t.run()