import requests, json, sys, re, time, warnings, argparse, os
import urllib3
from jsondiff import diff
import pandas as pd
from json2html import *

def printf(data):
    print(data, flush=True)

def compareBiosSettings(df_auth):
    iplist = list(df_auth['ip'])
    pwdlist = list(df_auth['pwd'])
    # Get all BIOS settings
    jsonlist = []
    output = {}
    biosAPI = "/redfish/v1/Systems/1/Bios"
    for ip, pwd in zip(iplist,pwdlist):
        IPMI = "https://" + ip
        biosAPI = "/redfish/v1/Systems/1/Bios"
        username = "ADMIN"
        auth = (username,pwd)
        response = requests.get(IPMI+biosAPI,verify=False,auth=auth)
        if 'Attributes' in response.json().keys():
            jsonlist.append(response.json()['Attributes'])
        else:
            jsonlist.append({"Message":"No Settings Obtained!", "Contents":response.json()})
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
                if 'BootOption' not in str(key):
                    diff_real[key] = diff_all[key]
            if len(diff_real.keys()) > 1:
                count += 1
        numdifflist.append(count)
    data = []
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
            if 'BootOption' not in str(key):
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
    return output

def bootOrderOutput(df_auth):
    jsonlist = compareBiosSettings(df_auth)['allsettings']
    iplist = list(df_auth['ip'])
    pwdlist = list(df_auth['pwd'])
    # count max number of boot option
    numOfBoot = []
    for i in range(len(jsonlist)):
        count = 0
        for key in jsonlist[i].keys():
            if 'BootOption' in str(key):
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
            if 'BootOption' in str(key):
                bootorderlist['BootOption' + str(count_key+1)].append(key.replace('BootOption','') + "|" + jsonlist[i][key])
                count_key += 1
        if count_key < maxNumOfBoot: # if boot option less than the max boot option add n/a
            for m in range(count_key+1, maxNumOfBoot+1):
                bootorderlist['BootOption' + str(m)].append("N/A")
    # output dataframe
    df_order = pd.DataFrame(bootorderlist)
    return(df_order)