from sys import stderr
import pymongo
import datetime
from app import mongoport, rackname
from multiprocessing import Pool
from subprocess import Popen, PIPE

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
    print("SMCIPMITool is excutable now")
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