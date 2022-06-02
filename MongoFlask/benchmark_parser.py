from subprocess import Popen, PIPE
import json
import sys
import time
import re
import os
from glob import glob
from pymongo import MongoClient
import pandas as pd
import datetime

def parseInput(filepath): 
    '''
    EXAMPLE:
    {
    "category":"benchmark",
    "exe":"stress-ng",
    "prefix":"",
    "config":"--matrix 0 -t 10s --metrics-brief --tz",
    "log":"stress-ng",
    "walltime":3600,
    "parseResultLog":1,
    "selfLog":0,
    "selfLogPath":"",
    "numOfResults":1,
    "keywords":[["real time","usr time","sys time","bogo ops/s"]],
    "addRow":[2],
    "dfs":[" "], # default seperator
    "index":[-2],
    "unit":["ops/s"],
    "resultName":["Throughput"],
    "criteriaType":["numericType"],
    "criteria":[[0,99999]]
    }
    '''
    # all keys
    basicKeys = ['category','exe','prefix','config','log','walltime','parseResultLog']
    parserKeys = ['selfLog','selfLogPath','numOfResults','keywords','addRow','dfs','index','unit','resultName','criteriaType','criteria']
    # key type, note that keywords not included inside either strkeys nor intKeys
    strKeys = ['category','exe','prefix','config','log','walltime','selfLogPath','dfs','unit','resultName','criteriaType']
    listKeys = ['keywords','addRow','dfs','index','unit','resultName','criteriaType','criteria']
    intKeys = ['parseResultLog','walltime','selfLog','numOfResults','addRow','index']
    specialKeys = ['criteria']
    print('Parsing json into dict...', flush=True)    
    try:
        with open(filepath, "r") as read_file:
            inputData = json.load(read_file)
    except Exception as e:
        print("parseInput() failed", flush=True)
        print("Error msg:\n{0}".format(e), flush=True)
        raise Exception('parseInput() failed, Parse json into dict failed. Error msg:\n{0}'.format(e))
    print("Checking if need to parse log...", flush=True)
    if inputData['parseResultLog'] == 0:
        keys = basicKeys
        print("Log will not be parsed", flush=True)
    elif inputData['parseResultLog'] == 1:
        keys = basicKeys + parserKeys
        print("Log will be parsed", flush=True)
    else:
        raise Exception('parseInput() failed, parseResultLog should be either 0 or 1.')
    # check whether key exsists in the inputData
    print("Checking if all necessary keys are included in the config....", flush=True)
    for key in keys:
        if key not in inputData.keys():
            print("parseInput() failed, " + key + " not found", flush=True)
            raise Exception("parseInput() failed, " + key + " not found")
    # check key type:
    print("Checking if all necessary keys have valid format....", flush=True)
    for key in inputData.keys():
        print("Checking " + key + ":", flush=True)
        if key in intKeys and key not in listKeys:
            print("Checking listKeys....", flush=True)
            if not isinstance(inputData[key], int):
                raise Exception("parseInput() failed, the value of " + key + " must be int, the type is " + str(type(inputData[key])))
        elif key in strKeys and key not in listKeys:
            print("Checking strKeys....", flush=True)
            if not isinstance(inputData[key], str):
                raise Exception("parseInput() failed, the value of " + key + " must be str, the type is " + str(type(inputData[key])))
        elif key in listKeys:
            print("Checking listKeys....", flush=True)
            if not isinstance(inputData[key], list):
                raise Exception("parseInput() failed, the value of " + key + " must be list, the type is " + str(type(inputData[key])))
            if len(inputData[key]) != inputData['numOfResults']:
                raise Exception("parseInput() failed, the length of value of " + key + " must be same as numOfResults: " + str(inputData['numOfResults']))
            for i in inputData[key]:
                if key in intKeys and not isinstance(i, int):
                    raise Exception("parseInput() failed, the item of list of the " + key + " must be int, the type is " + str(type(i)))
                elif key in strKeys and not isinstance(i, str):
                    raise Exception("parseInput() failed, the item of list of the " + key + " must be str, the type is " + str(type(i)))
        if key in specialKeys:
            print("Checking specialKeys....", flush=True)
            if not isinstance(inputData[key], list):
                raise Exception("parseInput() failed, the value of " + key + " must be list, the type is " + str(type(inputData[key])))
            if len(inputData[key]) != inputData['numOfResults']:
                raise Exception("parseInput() failed, the length of value of " + key + " must be same as numOfResults: " + str(inputData['numOfResults']))
            for i, j in zip(inputData[key],inputData['criteriaType']):
                if len(i) != 2:
                    raise Exception("parseInput() failed, the length of lit of " + key + " must be 2!")
                if j == 'numericType':
                    for v in i:
                        if not isinstance(v, int):
                            raise Exception("parseInput() failed, the value of list of " + key + " must be int, the type is " + str(type))
                    if i[0] > i[1]:
                        raise Exception("parseInput() failed, the smaller value of list of " + key + " must be in front of larger one.")
                elif j == 'stringType':
                    for v in i:
                        if not isinstance(v, str):
                            raise Exception("parseInput() failed, the value of list of " + key + " must be str, the type is " + str(type(v)))
                else:
                    raise Exception("criteriaType should be either numericType or stringType, not " + j)
    print("parseInput() Done successfully, all inputs are valid!", flush=True)                    
    return inputData

def resultParser(contents, keywords, addRow, dfs, index, unit, criteriaType, criteria):
    contents = contents.split('\n')
    output = {'result':'N/A','conclusion':'N/A'}
    conclusion = 1
    rawResult = []
    resultS = ''
    for kw, ar, df, ix, un, ct, cr in zip(keywords, addRow, dfs, index, unit, criteriaType, criteria):
        line_numbers = []
        for i, content in enumerate(contents):
            if all([x in content for x in kw]):
                line_numbers.append(i+ar)
        print('Find ' + str(len(line_numbers)) + ' results!', flush=True)
        if len(line_numbers) < 1:
            return {'result':'N/A','conclusion':'N/A'}       
        print('Take the first one as the result!', flush=True)
        if df == "None":
            result = str(contents[line_numbers[0]].split()[ix])
        else:
            result = str(contents[line_numbers[0]].split(df)[ix])
        print("Current result is:", flush=True)
        print(result, flush=True)
        
        if ct == 'numericType':
            try:
                resultN = float(result)
            except:
                resultN = float(re.findall(r"[+-]? *(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", result)[0])
            rawResult.append(resultN)
            resultS += str(resultN) + ' ' + un + ' '
            if resultN <= cr[1] and resultN >= cr[0]:
                conclusion *= 1
            else:
                conclusion *= 0
        else:
            rawResult.append(result)
            resultS += result
            if result == cr[0]:
                conclusion *= 1
            elif result == cr[1]:
                conclusion *= 0
            else:
                raise Exception("resultParser() failed, result does not fit any stringCritria")
    if len(resultS) > 0:
        output['result'] = resultS
        output['raw_result'] = rawResult
    if conclusion == 1:
        output['conclusion'] = 'PASS'
    elif conclusion == 0:
        output['conclusion'] = 'FAILED'
    return output

def clean_mac(mac):
    mac_cleaned = mac.replace(':','').replace('-','').lower()
    if len(mac_cleaned) != 12:
        print('Warning! invalid MAC address: ' + mac)
    return(mac_cleaned)

def mac_with_seperator(mac,sep):
    mac = clean_mac(mac)
    mac_sep = ''
    for i, one_chr in enumerate(mac):
        if i == len(mac)-1 or i%2 == 0:
            mac_sep += one_chr
        else:
            mac_sep += one_chr + ':' 
    return mac_sep