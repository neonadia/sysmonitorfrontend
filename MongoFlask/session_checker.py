import time
import secrets

def printf(data):
    print(data, flush=True)

def udp_session_checker(udp_session_info):
    time.sleep(0.100) ##### Fixes timing issue between page close and page reload
    if udp_session_info['state'] == 'active':
        printf("Failed to create new udp_server session")
        printf("Current UDP Session info is:")
        printf("state: " + udp_session_info['state'])
        printf("guid: " + udp_session_info['guid'])
        return False
    else:
        url_saf = secrets.token_urlsafe(8)
        udp_session_info['state'] = 'active'
        udp_session_info['guid'] = url_saf
        printf("Creating new udp_server session")
        printf("state: " + udp_session_info['state'])
        printf("guid: " + udp_session_info['guid'])
        return True

def sum_session_checker(sum_session_info):
    time.sleep(0.100) ##### Fixes timing issue between page close and page reload
    if sum_session_info['state'] == 'active':
        printf("Failed to create new sum_server session")
        printf("Current SUM Session info is:")
        printf("state: " + sum_session_info['state'])
        printf("guid: " + sum_session_info['guid'])
        return False
    else:
        url_saf = secrets.token_urlsafe(8)
        sum_session_info['state'] = 'active'
        sum_session_info['guid'] = url_saf
        printf("Creating new sum_server session")
        printf("state: " + sum_session_info['state'])
        printf("guid: " + sum_session_info['guid'])
        return True

def telemetry_session_checker(telemetry_session_info):
    time.sleep(0.100) ##### Fixes timing issue between page close and page reload
    if telemetry_session_info['state'] == 'active':
        printf("Failed to create new telemetry_server session")
        printf("Current telemetry Session info is:")
        printf("state: " + telemetry_session_info['state'])
        printf("guid: " + telemetry_session_info['guid'])
        return False
    else:
        url_saf = secrets.token_urlsafe(8)
        telemetry_session_info['state'] = 'active'
        telemetry_session_info['guid'] = url_saf
        printf("Creating new telemetry session")
        printf("state: " + telemetry_session_info['state'])
        printf("guid: " + telemetry_session_info['guid'])
        return True

def redfish_session_checker(redfish_session_info):
    time.sleep(0.100) ##### Fixes timing issue between page close and page reload
    if redfish_session_info['state'] == 'active':
        printf("Failed to create new redfish_server session")
        printf("Current RedFish Session info is:")
        printf("state: " + redfish_session_info['state'])
        printf("guid: " + redfish_session_info['guid'])
        return False
    else:
        url_saf = secrets.token_urlsafe(8)
        redfish_session_info['state'] = 'active'
        redfish_session_info['guid'] = url_saf
        printf("Creating new RedFish session")
        printf("state: " + redfish_session_info['state'])
        printf("guid: " + redfish_session_info['guid'])
        return True