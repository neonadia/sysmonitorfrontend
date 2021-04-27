import requests, json, sys, re, warnings, argparse, time
import urllib3
import os
from subprocess import Popen, PIPE
urllib3.disable_warnings()

fuopath = os.environ['FUOPATH']

def printf(data):
    print(data, flush=True)

# Check UID light status
def checkUID(IPMI, auth):
    ipmicmd = 'raw 0x30 0x0c'
    process = Popen('ipmitool -I lanplus' + ' -H ' +  IPMI + ' -U ' + 'ADMIN' + ' -P ' + auth[1] + ' ' + ipmicmd, shell=True, stdout=PIPE, stderr=PIPE)
    try:
        stdout, stderr = process.communicate()
    except:
        printf("No connection!!!")
        return "N/A"
    if "01" in str(stdout):
        return "BLINKING"
    else:
        return "OFF"

# deprecated
def checkUIDRedfish(IPMI, auth):
    login_host = "https://" + IPMI
    uidAPI = "/redfish/v1/Chassis/1"
    response = requests.get(login_host + uidAPI,verify=False,auth=auth)     
    if response.status_code == 200:
        return(response.json()['IndicatorLED'])
    else:
        return(str(response.status_code))

# Entering updating mode
def BiosUpdatingMode(IPMI,auth):
    biosAPI = "/redfish/v1/UpdateService/SmcFirmwareInventory/BIOS/"
    updatemodeAPI = biosAPI + "Actions/SmcFirmwareInventory.EnterUpdateMode"
    response = requests.post(IPMI + updatemodeAPI,verify=False,auth=auth)
    if response.status_code == 200:
        printf('BIOS updating mode activated!')
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + " BIOS updating mode activated\n")
    else:
        printf('BIOS updating mode activation failed, error code: ' + str(response.status_code))
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + ' BIOS updating mode activation failed, error code: ' + str(response.status_code) + "\n")
        return(time.asctime() + ": " + IPMI + ' BIOS updating mode activation failed, error code: ' + str(response.status_code) + "\n")

# Uploading file
def BiosUploadingFile(IPMI,filepath,auth):
    biosAPI = "/redfish/v1/UpdateService/SmcFirmwareInventory/BIOS/"
    uploadAPI = biosAPI + "Actions/SmcFirmwareInventory.Upload"
    files = {'file': open(filepath, 'rb')}
    printf('BIOS file uploading..')
    response = requests.post(IPMI + uploadAPI,verify=False,auth=auth,files=files)
    if response.status_code == 200:
        printf('BIOS file uploaded successfully!')
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + " BIOS file uploaded successfully!\n")
    else:
        printf('BIOS file uploaded failed, error code: ' + str(response.status_code))
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + " BIOS file uploaded failed, error code: ' + str(response.status_code)" + "\n")
        return(time.asctime() + ": " + IPMI + " BIOS file uploaded failed, error code: ' + str(response.status_code)" + "\n")
    time.sleep(3)
        
# Start Updating
def BiosStartUpdating(IPMI,auth,me,nvram,smbios):
    biosAPI = "/redfish/v1/UpdateService/SmcFirmwareInventory/BIOS/"
    updatemodeAPI = biosAPI + "Actions/SmcFirmwareInventory.Update"
    json = {"PreserveME":me,"PreserveNVRAM":nvram,"PreserveSMBIOS":smbios}
    response = requests.post(IPMI + updatemodeAPI,verify=False, auth=auth, json=json)
    if response.status_code == 202:
        printf('BIOS updating started!')
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + " BIOS updating started...\n")
    else:
        printf('BIOS update cannot started, error code: ' + str(response.status_code))
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + "  BIOS update cannot started, error code: " + str(response.status_code) + "\n")
        return(time.asctime() + ": " + IPMI + "  BIOS update cannot started, error code: " + str(response.status_code) + "\n")
    # check update status
    
    response = requests.get(IPMI + biosAPI, verify=False, auth=auth)
    if response.status_code == 200:
        keys = response.json().keys()
    else:
        keys = ['UpdateStatus']
    printf("BIOS updating....")
    while 'UpdateStatus' in keys:
        response = requests.get(IPMI + biosAPI, verify=False, auth=auth)
        if response.status_code == 200:
            keys = response.json().keys()
            time.sleep(3)
        else:
            keys = ['UpdateStatus'] 
            time.sleep(3)
    time.sleep(5)
    printf("BIOS update Completed")
    with open(fuopath, 'a') as rprint:
        rprint.write(time.asctime() + ": " + IPMI + " BIOS update Completed, start reboot..." + "\n")

def CancelBiosUpdate(IPMI,auth):
    biosAPI = "/redfish/v1/UpdateService/SmcFirmwareInventory/BIOS/"
    cancelAPI = biosAPI + "Actions/SmcFirmwareInventory.Cancel"
    response = requests.post(IPMI + cancelAPI,verify=False, auth=auth)
    if response.status_code == 200:
        printf('BIOS update canceled!')
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + " BIOS update canceled!\n")
    else:
        printf('BIOS update cannot canceled, error code: ' + str(response.status_code))
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + "  'BIOS update cannot canceled, error code: " + str(response.status_code) + "\n")
    
def FirmUpdatingMode(IPMI,auth):
    bmcAPI = "/redfish/v1/UpdateService/SmcFirmwareInventory/BMC/"
    updatemodeAPI = bmcAPI + "Actions/SmcFirmwareInventory.EnterUpdateMode"
    response = requests.post(IPMI + updatemodeAPI,verify=False,auth=auth)
    if response.status_code == 200:
        printf('Firmware updating mode activated!')
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + " Firmware updating mode activated!\n")
        return(0)
    else:
        printf('Firmware updating mode activation failed, error code: ' + str(response.status_code))
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + " Firmware updating mode activation failed, error code: " + str(response.status_code) + "\n")
        return(1)

# Uploading file
def FirmUploadingFile(IPMI,filepath,auth):
    bmcAPI = "/redfish/v1/UpdateService/SmcFirmwareInventory/BMC/"
    uploadAPI = bmcAPI + "Actions/SmcFirmwareInventory.Upload"
    files = {'file': open(filepath, 'rb')}
    printf('BMC file uploading..')
    response = requests.post(IPMI + uploadAPI,verify=False,auth=auth,files=files)
    if response.status_code == 200:
        printf('BMC file uploaded successfully!')
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + " BMC file uploaded successfully!\n")
        return(0)
    else:
        printf('BMC file uploaded failed, error code: ' + str(response.status_code))
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + " BMC file uploaded failed, error code: " + str(response.status_code) + "\n")
        return(1)
        
# Start Updating
def FirmStartUpdating(IPMI,auth,cfg,sdr,ssl):
    bmcAPI = "/redfish/v1/UpdateService/SmcFirmwareInventory/BMC/"
    updatemodeAPI = bmcAPI + "Actions/SmcFirmwareInventory.Update"
    json = {"PreserveCfg":cfg,"PreserveSdr":sdr,"PreserveSsl":ssl}
    response = requests.post(IPMI + updatemodeAPI,verify=False, auth=auth, json=json)
    if response.status_code == 202:
        printf('Firmware updating started!')
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + " Firmware updating started!\n")
    else:
        printf('Firmware update cannot started, error code: ' + str(response.status_code))
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + " Firmware update cannot started, error code: " + str(response.status_code) + "\n")
        return(1)
    # check update status
    response = requests.get(IPMI + bmcAPI, verify=False, auth=auth)
    printf("Firmware updating....")
    while 'UpdateProgress' in response.json().keys():
        response = requests.get(IPMI + bmcAPI, verify=False, auth=auth)
        printf(response.json()['UpdateProgress'])
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + " " + response.json()['UpdateProgress'] + "\n")
        if response.json()['UpdateProgress'] == "100%":
            break
        time.sleep(15)
    time.sleep(5)
    printf("Firmware update Completed")
    with open(fuopath, 'a') as rprint:
        rprint.write(time.asctime() + ": " + IPMI + " Firmware update Completed!\n")
    return(0)

def CancelFirmUpdate(IPMI,auth):
    bmcAPI = "/redfish/v1/UpdateService/SmcFirmwareInventory/BMC/"
    cancelAPI = bmcAPI + "Actions/SmcFirmwareInventory.Cancel"
    response = requests.post(IPMI + cancelAPI,verify=False, auth=auth)
    if response.status_code == 200:
        printf('BMC update canceled!')
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + " BMC update canceled!\n")
        return(0)
    else:
        printf('BMC update cannot canceled, error code: ' + str(response.status_code))
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + "  'BMC update cannot canceled, error code: " + str(response.status_code) + "\n")
        return(1)

def powerState(IPMI,auth):
    #API = "/redfish/v1/Systems/1"
    #response = requests.get(IPMI + API, verify=False, auth=auth)
    #if response.json()['PowerState'] == 'On':
    #    return True
    #else:
    #    return False
    ip = IPMI.replace("https://","")
    user = auth[0]
    pwd = auth[1]
    process = Popen('ipmitool ' +  'chassis status' + ' -H ' +  ip + ' -U ' + user + ' -P ' + pwd + ' | grep "System Power"', shell=True, stdout=PIPE, stderr=PIPE)
    try:
        stdout, stderr = process.communicate(timeout=2)
    except:
        printf("No connection!!!")
        return False
    if "on" in str(stdout):
        printf(str(stdout))
        return True
    else:
        printf(str(stdout))
        return False
    

# Reset allow: "On","ForceOff","GracefulShutdown","GracefulRestart","ForceRestart","Nmi","ForceOn"
def systemRebootTesting(IPMI,auth,api):
    resetAPI = "/redfish/v1/Systems/1/Actions/ComputerSystem.Reset"
    json = {"ResetType":api}
    response = requests.post(IPMI + resetAPI,verify=False,auth=auth,json=json)
    if response.status_code == 200:
        printf(api)
        return(0)
    else:
        printf(api + ' failed, error code: ' + str(response.status_code))
        return(1)

def redfishReadyCheck(IPMI,auth):
    checkAPI = "/redfish/v1/Systems/1/"
    try:
        response = requests.get(IPMI + checkAPI,verify=False,auth=auth)
        if response.status_code == 200:
            with open(fuopath, 'a') as rprint:
                rprint.write(time.asctime() + ": " + IPMI + " working!\n")
            return(0)
        else:
            with open(fuopath, 'a') as rprint:
                rprint.write(time.asctime() + ": " + IPMI + " error code " + str(response.status_code) + "!\n")
            return(1)
    except:
        with open(fuopath, 'a') as rprint:
            rprint.write(time.asctime() + ": " + IPMI + " unreachable!\n")
        return(2) # unreachable