import pymongo
from app import mongoport

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

def find_powercontrol(bmc_ip):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    data_entry = entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "PowerControl": 1})

    # initial dataset
    dataset = {'bmc_ip': bmc_ip, 'datetime': [], 'PowerControl': []}

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


def find_voltages(bmc_ip):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    data_entry = entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "Voltages": 1})

    # initial dataset
    dataset = {'bmc_ip': bmc_ip, 'datetime': [], 'Voltages': []}

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
    dataset = {'bmc_ip': bmc_ip, 'datetime': [], 'PowerSupplies': []}

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
    

def find_allpowercontrols(ip_list):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    data_entries = []
    for bmc_ip in ip_list:
        data_entries.append(entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "PowerControl": 1}))

    # initial dataset
    dataset = {'RACK': "RACK", 'datetime': [], 'PowerControl': []}

    # power supplies
    for bmc_ip, data_entry in zip(ip_list, data_entries):
        dataset['PowerControl'].append({'Name': bmc_ip + ' ,Unit: W', 'Reading': []})

    # get dataset
    all_nodes_time = []
    for i, data_entry in enumerate(data_entries):
        all_time = []
        all_reading = []
        for j in data_entry:
            all_time.append(j['Datetime'])
            for k in range(len(j['PowerControl'])):
                all_reading.append(j['PowerControl'][str(k+1)]['PowerConsumedWatts'])
        all_nodes_time.append(all_time)
        dataset['PowerControl'][i]['Reading'] = all_reading
    dataset['datetime'] = all_nodes_time[0] # different node has slightly different datetime
    
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


def find_temperatures(bmc_ip):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    data_entry = entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "Temperatures": 1})

    # initial dataset
    dataset = {'bmc_ip': bmc_ip, 'datetime': [], 'Temperatures': []}

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


def find_fans(bmc_ip):
    connect = pymongo.MongoClient('localhost', mongoport)
    db = connect['redfish']
    collection = 'monitor'
    entries = db[collection]
    data_entry = entries.find({"BMC_IP": bmc_ip}, {"_id": 0, "BMC_IP": 1, "Datetime": 1, "Fans": 1})

    # initial dataset
    dataset = {'bmc_ip': bmc_ip, 'datetime': [], 'Fans': []}

    # fans
    for i in range(len(data_entry[0]['Fans'])):
        #dataset['Fans'].append({'Name': data_entry[0]['Fans'][str(i+1)]['Name'], 'Speed': []})
        dataset['Fans'].append({'Name': 'Fan'+str(i+1), 'Speed': []})

    # get dataset
    for x in data_entry:
        dataset['datetime'].append(x['Datetime'])
        for i in range(len(x['Fans'])):
            dataset['Fans'][i]['Speed'].append(x['Fans'][str(i+1)]['Reading'])

    connect.close()

    return dataset

