from subprocess import Popen, PIPE
import re
from jsondiff import diff
import pandas as pd
import os
from os import listdir
from os.path import isfile, join
from json2html import *
import urllib3
import glob

urllib3.disable_warnings()

logFolder = os.environ['UPLOADPATH']

def printf(data):
    print(data, flush=True)

def makeSumExcutable():
    process = Popen('chmod 777 sum', shell=True, stdout=PIPE, stderr=PIPE)
    process.communicate()
    printf("sum is excutable now")
    return(0)

def sumRunCustomProcess(CMD):
    process = Popen(CMD, shell=True, stdout=PIPE, stderr=PIPE)
    process.communicate()
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
    process = Popen('./sum -l ' + inputpath + ' -c UpdateBios --file ' + filepath, shell=True, stdout=PIPE, stderr=PIPE)
    process.communicate()
    return(0)

def sumBMCUpdate(inputpath,filepath):
    process = Popen('./sum -l ' + inputpath + ' -c UpdateBmc --file ' + filepath, shell=True, stdout=PIPE, stderr=PIPE)
    process.communicate()
    return(0)

def sumGetBiosSettings(inputpath):
    process = Popen('./sum -l ' + inputpath + ' -c GetCurrentBiosCfg --file htmlBios --overwrite', shell=True, stdout=PIPE, stderr=PIPE)
    process.communicate()
    return(0)
    

def sumChangeBiosSettings(inputpath,filepath):
    process = Popen('./sum -l ' + inputpath + ' -c ChangeBiosCfg --file ' + filepath + ' --skip_unknown', shell=True, stdout=PIPE, stderr=PIPE)
    process.communicate()
    return(0)
    
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
                jsonlist[-1]["|".join(contents_str[0:-2])] = contents_str[-2]
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