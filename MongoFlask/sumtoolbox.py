from subprocess import Popen, PIPE
import re
from time import sleep
from jsondiff import diff
import pandas as pd
import os
from os import listdir
from os.path import isfile, join
from json2html import *
import urllib3
import glob
import time
import json

urllib3.disable_warnings()

logFolder = os.environ['UPLOADPATH']

def printf(data):
    print(data, flush=True)

def insert_flag(flag):
    flag_path = os.environ['FLAGPATH']
    with open(flag_path, 'a') as flag_file:
        flag_file.write(str(flag) + ',' + time.ctime()  + '\n')  

def read_flag():
    with open(os.environ['FLAGPATH'], 'r') as flag_file:
        flag = int(flag_file.readlines()[-1].split(',')[0])
    return flag

def makeSumExcutable():
    process = Popen('chmod 777 sum', shell=True, stdout=PIPE, stderr=PIPE)
    process.communicate()
    # printf("sum is excutable now")
    return(0)

def sumRunCustomProcess(CMD):
    # flag = read_flag()
    # while(flag == 1):
    #     flag = read_flag()
    # insert_flag(5)
    process = Popen(CMD, shell=True, stdout=PIPE, stderr=PIPE)
    process.communicate()
    insert_flag(0)
    return(0)

def sumLogOutput():
    process1 = Popen('ps aux | grep "[s]um" | grep -v "/bin/sh"', shell=True, stdout=PIPE, stderr=PIPE) # run sum in docker container will result in two processes
    stdout1, stderr1 = process1.communicate()
    if len(stdout1.decode('utf-8').split()) < 2:
        return(1)
    else:
        pid = stdout1.decode('utf-8').split()[1]
        LogFileList = glob.glob(logFolder + '**.txt.log**' + pid)
        if len(LogFileList) != 1:
            return(2)
        return(LogFileList[0])
        
def sumBiosUpdate(inputpath,filepath):
    # flag = read_flag()
    # while(flag == 1):
    #     flag = read_flag()
    # insert_flag(5)
    process = Popen('./sum -l ' + inputpath + ' -c UpdateBios --file ' + filepath, shell=True, stdout=PIPE, stderr=PIPE)
    process.communicate()
    insert_flag(0)
    return(0)

def sumBMCUpdate(inputpath,filepath):
    # flag = read_flag()
    # while(flag == 1):
    #     flag = read_flag()
    # insert_flag(5)
    process = Popen('./sum -l ' + inputpath + ' -c UpdateBmc --file ' + filepath, shell=True, stdout=PIPE, stderr=PIPE)
    process.communicate()
    insert_flag(0)
    return(0)

def sumGetBiosSettings(inputpath):
    # flag = read_flag()
    # while(flag == 1):
    #     flag = read_flag()
    # insert_flag(5)
    process = Popen('./sum -l ' + inputpath + ' -c GetCurrentBiosCfg --file htmlBios --overwrite', shell=True, stdout=PIPE, stderr=PIPE)
    process.communicate()
    insert_flag(0)
    return(0)
    

def sumChangeBiosSettings(inputpath,filepath):
    # flag = read_flag()
    # while(flag == 1):
    #     flag = read_flag()
    # insert_flag(5)
    process = Popen('./sum -l ' + inputpath + ' -c ChangeBiosCfg --file ' + filepath + ' --skip_unknown', shell=True, stdout=PIPE, stderr=PIPE)
    process.communicate()
    insert_flag(0)
    return(0)

def sumCheckOOB(inputpath): # License Key checking
    # flag = read_flag()
    # while(flag == 1):
    #     flag = read_flag()
    # insert_flag(5)
    process = Popen('./sum -l ' + inputpath + ' -c CheckOOBSupport', shell=True, stdout=PIPE, stderr=PIPE)
    stdout, stderr = process.communicate()
    all_lines = stdout.decode('utf-8').split('\n')
    # get 2nd last line which is the log file name
    for i in range(1, len(all_lines)+1):
        if len(all_lines[-i].replace(' ','')) != 0:
            log_path = all_lines[-i].strip()
            break
    # read log file contents
    with open(log_path, 'r') as log:
        log_lines = log.readlines()
    # parse log file contents to a dict
    result = {'Number of Nodes': 0, 'Node Product Key Activated':{}, 'SFT-DCMS-SVC-KEY Activated':{}, 'Node Product Key Format': {}, 'Feature Toggled On': {}, \
    'BMC FW Version': {}, 'BMC Supports OOB BIOS Config': {}, 'BMC Supports OOB DMI Edit': {}, 'BIOS Build Date': {}, 'BIOS Supports OOB BIOS Config': {}, \
    'BIOS Supports OOB DMI Edit': {}, 'System Supports RoT Feature': {}}
    for line in log_lines:
        line = line.replace('\n','')
        line = line.replace('.','').strip()
        if 'Execution Message' in line:
            result['Number of Nodes'] += 1
        for pre_key in result.keys():
            if pre_key in line and pre_key != 'Number of Nodes':
                cur_key = line.replace(pre_key,'')
                if cur_key in result[pre_key]:
                    result[pre_key][cur_key] += 1
                else:
                    result[pre_key][cur_key] = 1
    # parse dict to a list for print out
    output_lines = ['-------------------------OOB CHECKING SUMMARY-------------------------']
    for key in result.keys():
        if key == 'Number of Nodes':
            output_lines.append('[Number of Nodes]')
            output_lines.append('- ' + str(result[key]))
            continue
        output_lines.append('[' + key + ']')
        for sub_key in result[key]:
            output_lines.append("- '" + sub_key + "': " + str(result[key][sub_key]))
    insert_flag(0)
    
    # parse log file contents for mongodb inserting
    ## trim the unnecessary information
    log_lines_trim = []
    sep_nums = []
    for i, line in enumerate(log_lines):
        log_lines_trim.append(line.replace('\n','').strip())
        if 'Execution Message' in line:
            sep_nums.append(i)
    sep_nums.append(len(log_lines)-1)            
    ## sep_num to sep_range
    sep_range = [] # [(1,10),(10,15)....]
    for i, j in enumerate(sep_nums):
        if i < len(sep_nums)-1:
            sep_range.append((j,sep_nums[i+1]))
    ## seperate the lines into parts
    log_lines_trim_parts = [] # [[ info of BMC1 ],[ info of BMC2 ],....]
    for t in sep_range:
        log_lines_trim_parts.append(log_lines_trim[t[0]:t[1]])
    result_sum = {}
    sample_dict = {'Node Product Key Activated':'N/A', 'Node Product Key Format':'N/A', 'Feature Toggled On': 'N/A'}
    for p in log_lines_trim_parts:
        for i, l in enumerate(p):
            if 'System Name' in l:
                cur_bmc_ip = p[i+1]
                result_sum[cur_bmc_ip] = sample_dict
                print(f'({cur_bmc_ip}) Fetching Activation Info using SUM ...')
        for l in p:
            for key in sample_dict:
                if key in l and len(l) > 33:
                    result_sum[cur_bmc_ip][key] = l[33::]
    return(output_lines, result_sum)
    
'''
def sumGetDmiInfo(inputpath):
    process = Popen('./sum -l ' + inputpath + ' -c GetDmiInfo --file DMI --overwrite', shell=True, stdout=PIPE, stderr=PIPE)
    process.communicate()
    return(0)
'''

'''
def sumRemoveFiles(inputtype):
    process = Popen('rm -f ' + inputtype + "*", shell=True, stdout=PIPE, stderr=PIPE)
    process.communicate()
    return(0)
'''

def sumCompBiosSettings():
    # Get all bios html file names
    file_list = []
    iplist = []
    folder = "/app/"
    for file in listdir(folder):
        if isfile(folder+file) and 'htmlBios' in file:
            file_list.append(folder+file)
            iplist.append(file.replace('htmlBios.',''))    
    # Get all BIOS settings
    jsonlist = []
    output = {}
    for file in file_list:
        jsonlist.append({})
        f = open(file, "rb")
        lines = f.readlines()
        for line in lines:
            if 'selectedOption' in str(line):
                contents = re.findall(r'".+?"',str(line))
                contents_str = []
                for content in contents:
                    contents_str.append(content.replace('"',''))
                try:
                    jsonlist[-1]["|".join(contents_str[0:-2])] = contents_str[-2]
                except:
                    printf("------------This line does not contains enough information--------")
                    printf(contents_str)
                    printf("------------------------------------------------------------------")
    output['allsettings'] = jsonlist
    # find out number of different nodes
    numdifflist = []
    for j in range(len(jsonlist)):
        count = 0
        for i in range(len(jsonlist)):
            diff_all = diff(jsonlist[j],jsonlist[i])
            diff_real = {}
            diff_real['ip'] = iplist[i]
            for key in diff_all.keys():
                if 'Boot Option' not in str(key):
                    diff_real[key] = diff_all[key]
            if len(diff_real.keys()) > 1:
                count += 1
        numdifflist.append(count)
    # print out difference
    sample_index = numdifflist.index(min(numdifflist))
    printf(str(min(numdifflist)) + " different BIOS settings found!!")
    count = 0
    compResult = []
    for i in range(len(jsonlist)):
        diff_all = diff(jsonlist[sample_index],jsonlist[i])
        diff_real = {}
        sample = {}
        diff_real['ip'] = iplist[i]
        sample['ip'] = iplist[sample_index]
        for key in diff_all.keys():
            if 'Boot Option' not in str(key):
                diff_real[key] = diff_all[key]
                try:
                    sample[key] = jsonlist[sample_index][key]
                except:
                    sample[key] = None
        if len(diff_real.keys()) > 1:
            count += 1
            compResult.append("No." + str(count) + ":")
            compResult.append("############### Golden Sample ###############")
            compResult.append(json2html.convert(json = sample))
            compResult.append("############### Different Node ###############")
            compResult.append(json2html.convert(json = diff_real))
            compResult.append("##############################################")
            compResult.append("")
    if len(compResult) == 0:
        compResult.append("No Difference Found!")
    compResult.append("############### Golden Sample All Settings ###############")
    compResult.append(json2html.convert(json = jsonlist[sample_index]))
    output['compResult'] = compResult
    output['iplist'] = iplist
    return output

def sumBootOrder(jsonlist,iplist):
    # count max number of boot option
    numOfBoot = []
    for i in range(len(jsonlist)):
        count = 0
        for key in jsonlist[i].keys():
            if 'Boot Option' in str(key):
                count += 1
        numOfBoot.append(count)
    # find max number of boot option in the rack
    maxNumOfBoot = max(numOfBoot)
    # initialize the dict
    bootorderlist = {}
    bootorderlist['IPMI_IP'] = iplist
    for i in range(maxNumOfBoot):
        bootorderlist['BootOption' + str(i+1)] = []
    # assign boot options
    for i in range(len(jsonlist)):
        count_key = 0
        for key in jsonlist[i].keys():
            if 'Boot Option' in str(key):
                bootorderlist['BootOption' + str(count_key+1)].append(key.replace('Boot Option','') + "|" + jsonlist[i][key]) # value contains "boot option number|order number|selected option"
                count_key += 1
        if count_key < maxNumOfBoot: # if boot option less than the max boot option add n/a
            for m in range(count_key+1, maxNumOfBoot+1):
                bootorderlist['BootOption' + str(m)].append("N/A")
    df_order = pd.DataFrame(bootorderlist)
    return(df_order)

def sumRedfishAPI(inputpath, API_url):
    with open(inputpath, 'r') as input:
        printf(input.readlines())    
    folder = os.environ['UPLOADPATH']
    
    # clean files before using
    for file in listdir(folder):
        if isfile(folder + file) and 'redfish-json' in file:# maybe not useful at all
            os.remove(folder + file)
            printf('Deleted: ' + folder + file)
    # run redfishAPI    
    process = Popen('./sum -l ' +  inputpath + ' -c RedfishAPI --api ' + API_url + ' --file ' + folder + 'redfish-json --overwrite', shell=True, stdout=PIPE, stderr=PIPE)
    stdout, stderr = process.communicate()
    printf(stdout.decode("utf-8"))
    printf(stderr.decode("utf-8"))
    
    file_list = []
    ip_list = []
    output_dict_list = []
    output = {}

    for file in listdir(folder):
        if isfile(folder + file) and 'redfish-json' in file:
            file_list.append(folder + file)
            ip_list.append(file.replace('redfish-json.',''))
    printf(file_list)
    printf(ip_list)
            
    for file in file_list:
        f = open(file)
        try:
            output_dict_list.append(json.load(f))
        except:
            output_dict_list.append({'Error': 'Command can not be excuted, please verify if the syntax correct.'})
        
    for one_dict, ip in zip(output_dict_list,ip_list):
        output[ip] = {"output":{}}
        line_num = 0
        for k in one_dict.keys():
            cur_line = "'{}':'{}'".format(k, json.dumps(one_dict[k],indent = 2).replace("\"","\'")) # pretty form
            output[ip]["output"][str(line_num)] = cur_line.replace(" ","&nbsp;")
            line_num += 1
    return output