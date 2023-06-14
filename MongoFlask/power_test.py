# ====================================================================================================
# Date: 2023/06/05
# Author: David Moreno
# Description: power_test.py
#   The purpose of this script is to run a power cycle test on a single or multiple servers
#
# Requirements:
#   python 3.8 or higher should already be installed.
#   Only compatible with Linux
# ====================================================================================================

import argparse
import jc
import os
import pandas as pd
import paramiko
import pathlib
import re
import subprocess
import sys
import time

from datetime import datetime
from fabric import Connection
from pathlib import Path
from pymongo import MongoClient
from gridfs import GridFS

version_info = [
    '=' * 100,
    '2023-06-05: Initial version basic features being added.',
    '=' * 100]


# TODO
#   When the install of L12_Automation is finished remove starting from here
# ====================================================================================================
def add_to_log(log_file, data_to_add):
    """
    Function to add any list of strings to a log file and print out the same information.

    :param log_file: Full path to the log file
    :type log_file: str
    :param data_to_add: Data to be added to a file from another file.
    :type data_to_add: list
    """
    with open(log_file, 'a') as the_log:
        for line in data_to_add:
            the_log.write(f'{line}\n')
            print(line)


# ====================================================================================================
def get_current_time_for_log():
    """
    Function to get the current time for a long.

    :return: String containing time date information.
    :rtype: str
    """
    current_time = datetime.now()
    time_for_log = f'{current_time.year}_{current_time.month}_{current_time.day}-{current_time.hour}_' \
                   f'{current_time.minute}_{current_time.second}'
    return time_for_log

# TODO - End here


# ====================================================================================================
def insert_to_database(log_content, os_ip, log_date, log_cmd, uuid, update_db):
    """
    Function that will insert log to the database

    :param log_content: content of the log
    :type log_content: str
    :param os_ip: os ip address of the server
    :type os_ip: str
    :param log_date: datetime of the log being created
    :type log_date: str
    :param log_cmd: the command used to fetch the log
    :type log_cmd: str
    :param uuid: the unique id for dc on off test
    :type uuid: str
    :param update_db: whether to insert (False) of update (True) the database
    :type update_db: boolean
    """
    # parse the datetime
    date_format = "%Y_%m_%d-%H_%M_%S"
    log_date = datetime.strptime(log_date, date_format)
    # set up connection for dc on off collection
    mongoport = int(os.environ['MONGOPORT'])
    db = MongoClient('localhost', mongoport).redfish
    dc_collection = db.dc
    dc_gridfs = GridFS(db, collection='dc_gridfs')
    sample_dict = {'uuid': uuid, 'num_loops': num_loops, 'status': None, 'os_ip': os_ip, 'log_date': log_date, 'ipmi_lan': None, 'lspci': None,
                   'dmidecode': None, 'ipmi_sdr': None, 'power_cycle_log': None, 'dmesg': None}
    
    log_content = dc_gridfs.put(log_content.encode('utf-8')) # save the log content to gridfs and id for to log content

    if not update_db:
        # for loop 0, only save the old logs
        # if document exist, update it
        # if not, create it
        the_filter = {'os_ip': os_ip, 'uuid': uuid, 'status': 'Before Start'}
        result = dc_collection.find_one(the_filter)
        if result is not None:
            update = {'$set': {log_cmd: log_content, 'status': 'Before Start'}}
            dc_collection.update_one(the_filter, update)
        else:
            sample_dict[log_cmd] = log_content
            sample_dict['status'] = 'Before Start'
            dc_collection.insert_one(sample_dict)
    else:
        # for loop more than 0, keep updating the documents
        # if document exist, update it.
        # if not, create it.
        the_filter = {'os_ip': os_ip, 'uuid': uuid, 'status': 'Current'}
        result = dc_collection.find_one(the_filter)
        if result is not None:
            update = {'$set': {log_cmd: log_content, 'status': 'Current'}}
            dc_collection.update_one(the_filter, update)
        else:
            sample_dict[log_cmd] = log_content
            sample_dict['status'] = 'Current'
            dc_collection.insert_one(sample_dict)
    return 0


# ====================================================================================================
def system_summary_log(df_list, log_file, message=None):
    """
    Function that will log the status of all the systems to understand what state they are currently in.

    :param df_list: Full data frame items
    :type df_list: data frame
    :param log_file: File that holds the log info
    :type log_file: str
    :param message: Message to put at the top of the summary.
    :type message: str
    """
    log_padding = '-' * 100
    header_string = f'{"System IPMI":^16}{"System IP":^16}{"Status":<13}{"Notes"}'
    spacing_string = '-' * 15 + ' ' + '-' * 15 + ' ' + '-' * 12 + ' ' + '-' * 55
    if message:
        add_to_log(log_file, [log_padding, message, log_padding, header_string, spacing_string])
    else:
        add_to_log(log_file, [log_padding, log_padding, header_string, spacing_string])
    for df_index in df_list.index:
        add_to_log(log_file, [f'{df_list["IPMI"][df_index]:<16}{df_index:<16}{df_list["link_status"][df_index]:<13}'
                              f'{df_list["notes"][df_index]}'])
    add_to_log(log_file, [log_padding])


# ====================================================================================================
def ipmi_ping_check(df_list, log_file):
    """
    Function that will perform an ipmi ping to make sure the IPMI is alive. On a list of systems.
        It will update the link status appropriately.

    :param df_list: Full data frame items
    :type df_list: data frame
    :param log_file: File that holds the log info
    :type log_file: str
    """

    for df_item in df_list.index:
        if df_list['link_status'][df_item] != 'error':
            ipmi_ip = df_list['IPMI'][df_item]
            ipmi_ping_result = subprocess.run(['ping', '-c', '2', ipmi_ip], capture_output=True, text=True)

            if ipmi_ping_result.returncode:
                add_to_log(log_file, [f'IPMI NOT Alive at {ipmi_ip}'])
                df_list.at[df_item, 'link_status'] = 'error'
                df_list.at[df_item, 'notes'] = f'Failed at: Initial check. Failure: IPMI IP Not Pingable'
            else:
                add_to_log(log_file, [f'IPMI Alive at {ipmi_ip}'])


# ====================================================================================================
def ssh_connection_check(df_list, log_file):
    """
    Function that will check if the ssh connection to a system is live.

    :param df_list: Full data frame items
    :type df_list: data frame
    :param log_file: File that holds the log info
    :type log_file: str
    """
    for df_item in df_list.index:
        # If the system is not in an error state perform the check
        if df_list['link_status'][df_item] != 'error':
            os_ip = df_item
            os_user = df_list['OS_USER'][df_item]
            os_pass = df_list['OS_PASS'][df_item]
            add_to_log(log_file, [f'Attempting SSH connection to: {df_item}. 10 second timeout.'])
            try:
                ssh_connection = Connection(host=os_ip, user=os_user, connect_kwargs={'password': os_pass},
                                            connect_timeout=10)
                ssh_connection.run('touch checking_ssh_connection.log')
                ssh_connection.close()
                add_to_log(log_file, [f'SSH connection successful to: {df_item}'])
                df_list['link_status'][df_item] = 'on'
                df_list['notes'][df_item] = 'System OS Has Loaded'
            except TimeoutError:
                add_to_log(log_file, [f'Timeout: Unable to establish SSH connection to: {df_item}.'])
                continue
            except paramiko.ssh_exception.NoValidConnectionsError:
                add_to_log(log_file, [f'No Valid Connection: Unable to establish SSH connection to: {df_item}.'])
                continue
            except Exception as e:
                add_to_log(log_file, [f'New Exception at: {df_item}. \n{e}'])
                continue


# ====================================================================================================
def ipmi_power_command(df_list, log_file, state='status', loop_count='initial check', desired_state=None,
                       hard_mode=False):
    """
    Function that will check the IPMI power state. Or change the state of the power. For all items
        in the data frame list

    :param df_list: Full data frame items
    :type df_list: data frame
    :param log_file: File that holds the log info
    :type log_file: str
    :param state: Either get current state, or change the state, on, off, soft
    :type state: str
    :param loop_count: Either a number or initial to know where the failure happened
    :type loop_count: int or str
    :param desired_state: Specify this if you are expecting the system to be in a specific state.
        Will only update the link_status if it hits this state
    :type desired_state: str
    :param hard_mode: Specify if you want a hard shutdown instead of a soft shutdown
    :type hard_mode: bool
    """
    if state == 'status':
        ipmi_command = 'status'
    elif state == 'off' and hard_mode:
        ipmi_command = 'off'
    elif state == 'off':
        ipmi_command = 'soft'
    else:
        ipmi_command = 'on'
    for df_item in df_list.index:
        # If the system is not in an error state perform the check
        if df_list['link_status'][df_item] != 'error' and df_list['link_status'][df_item] != state:
            ipmi_ip = df_list['IPMI'][df_item]
            ipmi_user = df_list['IPMI_USER'][df_item]
            ipmi_pass = df_list['IPMI_PASS'][df_item]
            try:
                command = subprocess.run(
                    ['ipmitool', '-H', ipmi_ip, '-U', ipmi_user, '-P', ipmi_pass, 'chassis', 'power', ipmi_command],
                    check=True, capture_output=True, text=True).stdout.rstrip()
                if state == 'status':
                    command_response = re.search(r'Chassis Power is\s+(\w+)', command).group(1)

                    # If desired_state is not None then it must match the output of status to update the state
                    # If desired_state is None then you can update right away
                    # The purpose of this is to keep the system in the turning_xx phase until it has actually changed
                    if desired_state is not None and desired_state == command_response.lower():
                        df_list['link_status'][df_item] = command_response.lower()
                    elif desired_state is None:
                        df_list['link_status'][df_item] = command_response.lower()
                    if loop_count == 'initial check':
                        add_to_log(log_file, [f'{ipmi_ip} Power Status: {command_response.lower()}'])
                else:
                    command_response = re.search(r'Chassis Power Control:\s+(\w+)', command).group(1)
                    add_to_log(log_file, [f'{ipmi_ip} Power Status: {command_response.lower()}'])
                    if state == 'on':
                        df_list.at[df_item, 'link_status'] = 'turning_on'
                        df_list.at[df_item, 'notes'] = 'System is turning on.'
                    else:
                        df_list.at[df_item, 'link_status'] = 'turning_off'
                        df_list.at[df_item, 'notes'] = 'System is turning off.'
            except subprocess.CalledProcessError as error:
                add_to_log(log_file, [f'IPMI NOT Alive at {ipmi_ip}', 'Skipping this system from now on.'])
                df_list.at[df_item, 'link_status'] = 'error'
                df_list.at[df_item, 'notes'] = f'Failed at {loop_count}. Failure: {error}'
        elif df_list['link_status'][df_item] == state:
            add_to_log(log_file, [f'System {df_item} is already in {state}. No need to run power state command.'])


# ====================================================================================================
def wait_for_state_change(df_list, log_file, timeout, mode, loop_count):
    """
    Function that will first make sure the IPMI is pingable.
        Then wait for a state change or timeout if it takes too long.
        Depending on the input it will either check for ssh connection or check for ipmi power state to specified state.
        This function will operate on a list of systems give if they are not in error state.

    :param df_list: Full data frame items
    :type df_list: data frame
    :param log_file: File that holds the log info
    :type log_file: str
    :param timeout: Time in seconds to wait for the system to turn on
    :type timeout: int
    :param mode: Specify the mode you are trying to go on or off
    :type mode: str
    :param loop_count: Either a number or initial to know where the failure happened
    :type loop_count: int or str
    :return: Return True or False if the specified action completed
    :rtype: bool
    """

    ipmi_ping_check(df_list=df_list, log_file=log_file)

    # Check to see if any systems are not in the state they are expected to be in.
    # Don't go in while loop if all systems are error or equal to desired mode
    number_of_systems = len(df_list)
    system_check = 0
    for df_item in df_list.index:
        if df_list['link_status'][df_item] == 'error' or df_list['link_status'][df_item] == mode:
            system_check += 1
    if number_of_systems == system_check:
        add_to_log(log_file, ['All systems are in expected state.'])
        return

    start_time = time.perf_counter()
    current_time = time.perf_counter()
    while current_time - start_time < timeout:
        if mode == 'on':
            ssh_connection_check(df_list=df_list, log_file=log_file)
        else:
            ipmi_power_command(df_list=df_list, log_file=log_file, state='status', loop_count=loop_count,
                               desired_state='off')
        # Check to see if all systems are in the correct state or in error state then break the while loop
        counted_systems = 0
        for df_item in df_list.index:
            if df_list['link_status'][df_item] in ['error', 'on', 'off']:
                counted_systems += 1
        if counted_systems == number_of_systems:
            break
        current_time = time.perf_counter()
        add_to_log(log_file, [f'All systems are not {mode}. Waited {int(current_time - start_time)} '
                              f'seconds so far. Waiting a total of: {timeout} seconds.'])
        system_summary_log(df_list=df_list, log_file=log_file)
        time.sleep(10)
    # Go through all the systems that are still in a transitioning state and mark them failure
    if current_time - start_time < timeout:
        add_to_log(log_file, [f'Finished transitioning all systems. Took: {int(current_time - start_time)} seconds.'])
        system_summary_log(df_list=df_list, log_file=log_file)
    for df_item in df_list.index:
        if df_list['link_status'][df_item] in ['turning_on', 'turning_off']:
            add_to_log(log_file, [f'System {df_item} took too long to change state. Marking it as failed.',
                                  'Skipping this system from now on.'])
            df_list.at[df_item, 'link_status'] = 'error'
            df_list.at[df_item, 'notes'] = f'Failed at {loop_count}. Failure: Took too long to transition to {mode}'


# ====================================================================================================
def perform_diff_check(original_file, new_file, test_name, continue_on_error, log_file):
    """
    Function that will diff two files and add some information to a log.

    :param original_file: Path to the original file to dff
    :type original_file: str
    :param new_file: Path to the new file to diff
    :type new_file: str
    :param test_name: Name of the test for logging purposes
    :type test_name: str
    :param continue_on_error: Tells the script to not change system status to error
    :type continue_on_error: bool
    :param log_file: File that holds the log info
    :type log_file: str
    :return: Return True if good or False if you need to set the status to bad
    """
    log_padding = '-' * 50
    diff_check = subprocess.run(f'diff {original_file} {new_file}', capture_output=True, text=True, shell=True).stdout
    if diff_check and not continue_on_error:
        add_to_log(log_file,
                   [f'{test_name} check FAILED! Check:', original_file, new_file,
                    diff_check, log_padding])
        return False
    elif diff_check and continue_on_error:
        add_to_log(log_file,
                   [f'{test_name} check FAILED! Check:', original_file, new_file,
                    'Continue on Error is enable so we will not stop testing this system.',
                    diff_check, log_padding])
    else:
        add_to_log(log_file, [f'{test_name} check PASSED!', log_padding])
    return True


# ====================================================================================================
def run_ssh_command(ssh_connection, ssh_command, ssh_log, time_stamp, log_purpose, os_ip, uuid, initial_mode=False):
    """
    Function that will run an ssh command and save the output to specified file.

    :param ssh_connection: SSH connection information
    :type ssh_connection: Connection
    :param ssh_command: Command to be sent over ssh connection
    :type ssh_command: str
    :param ssh_log: File that holds the ssh log info
    :type ssh_log: str
    :param time_stamp: Information for the date and timestamp
    :type time_stamp: str
    :param log_purpose: Purpose of the log
    :type log_purpose: str
    :param os_ip: OS IP
    :type os_ip: str
    :param uuid: uuid to be used for the database, only insert it if it's not None
    :type uuid: str
    :param initial_mode: Tells the ssh command we are in initial mode, only really for database, so it knows what to do
    :type initial_mode: bool
    """
    # TODO WILL NEED DATABASE CODE CALL
    ssh_result = ssh_connection.run(ssh_command, hide=True).stdout
    with open(ssh_log, 'w') as f:
        f.write(ssh_result)
    if uuid:
        insert_to_database(log_content=ssh_result, os_ip=os_ip, log_date=time_stamp, log_cmd=log_purpose, uuid=uuid,
                           update_db=not initial_mode)


# ====================================================================================================
def pcie_device_check(ssh_connection, os_pass, log_file, continue_on_error):
    """
    Function that will use both dmidecode and lspci to check the status of all pcie devices.
        If any error and continue on error is not set it will fail the system.
        Adding support for nvme devices

    :param ssh_connection: SSH connection information
    :type ssh_connection: Connection
    :param os_pass: Sudo password for the OS
    :type os_pass: str
    :param log_file: File that holds the log info
    :type log_file: str
    :param continue_on_error: Tells the script to continue even if issues in the checkers are found.
    :type continue_on_error: bool
    :return: Return False if error is found and continue on error is not set.
    :rtype: bool
    """
    log_padding = '-' * 100
    pcie_dicts = []
    dmidecode_output = ssh_connection.run(f'echo {os_pass} | sudo -S dmidecode -t slot', hide=True).stdout
    pcie_slot_info: list = jc.parse('dmidecode', dmidecode_output)
    for device in pcie_slot_info:
        pcie_slot = {}
        pcie_slot.update({'Slot': device['values']['designation']})
        pcie_slot.update({'Type': device['values']['type']})
        pcie_slot.update({'Usage': device['values']['current_usage']})
        pcie_slot.update({'Address': device['values']['bus_address']})
        pcie_dicts.append(pcie_slot)

    # Adding code to grab nvme devices and put them in the list
    # Run ls -l /sys/block/ and search for nvme to find any nvme devices in the system
    nvme_search = ssh_connection.run(f'echo {os_pass} | sudo -S ls -l /sys/block/', hide=True).stdout.split('\n')
    nvme_drives = []
    for drive in nvme_search:
        if 'nvme' in drive:
            nvme_drives.append(drive)

    for drive in nvme_drives:
        nvme_info = re.search(r'(\S\S:\S\S.\S)/nvme/', drive)
        nvme_drive = {}
        nvme_drive.update({'Type': 'NVMe'})
        nvme_drive.update({'Usage': 'In Use'})
        if not nvme_info:
            nvme_drive.update({'Address': 'Unknown'})
        else:
            nvme_drive.update({'Address': nvme_info.group(1)})
        pcie_dicts.append(nvme_drive)

    new_dict = []
    for pcie in pcie_dicts:
        if pcie['Usage'] == 'In Use':
            new_dict.append(pcie)
    pcie_dicts = new_dict
    for pcie in pcie_dicts:
        lspci_output = ssh_connection.run(f'echo {os_pass} | sudo -S lspci -s {pcie["Address"]} -vvv', hide=True).stdout
        pcie_capability = re.search(r'LnkCap:.+Speed\s+(\S+),\s+Width\s+(\S+),', lspci_output)
        pcie_current = re.search(r'LnkSta:\s+Speed\s+(\S+).+Width\s+(\S+)', lspci_output)
        if not pcie_capability:
            pcie.update({'Speed Capability': 'UNK'})
            pcie.update({'Width Capability': 'UNK'})
        else:
            pcie.update({'Speed Capability': pcie_capability.group(1)})
            pcie.update({'Width Capability': pcie_capability.group(2)})
        if not pcie_current:
            pcie.update({'Speed Current': 'UNK'})
            pcie.update({'Width Current': 'UNK'})
        else:
            pcie.update({'Speed Current': pcie_current.group(1)})
            pcie.update({'Width Current': pcie_current.group(2)})
        if pcie['Type'] == 'NVMe':
            nvme_slot = re.search(r'(Physical Slot:\s+\d+)', lspci_output)
            if not nvme_slot:
                pcie.update({'Slot': 'UNK'})
            else:
                pcie.update({'Slot': nvme_slot.group(1)})
        pcie.update({'Name': lspci_output.strip().split('\n')[0]})

    fail_counter = 0
    for pcie in pcie_dicts:
        pcie_check = True
        add_to_log(log_file,
                   [f'{"PCIe Device:":<15}{pcie["Name"]}',
                    f'{f"Slot: " + pcie["Slot"]:<25}{"Type: " + pcie["Type"]:<30}Usage: {pcie["Usage"]}',
                    f'{"Current Speed: " + pcie["Speed Current"]:<25}Capable Speed: {pcie["Speed Capability"]}',
                    f'{"Current Width: " + pcie["Width Current"]:<25}Capable Width: {pcie["Width Capability"]}'])

        if pcie["Speed Capability"] != pcie["Speed Current"] or pcie["Width Capability"] != pcie["Width Current"]:
            pcie_check = False

        if not pcie_check and not continue_on_error:
            add_to_log(log_file, ['PCIe check FAILED!!', log_padding])
            fail_counter += 1
        elif not pcie_check:
            add_to_log(log_file, ['PCIe check FAILED!!',
                                  'Continue on Error is enable so we will not stop testing this system.',
                                  log_padding])
        else:
            add_to_log(log_file, ['PCIe check PASSED!', log_padding])

    if fail_counter != 0 and not continue_on_error:
        add_to_log(log_file, [log_padding, f'{fail_counter} PCIe devices failed. Failing this system.', log_padding])
        return False
    elif fail_counter != 0:
        add_to_log(log_file,
                   [log_padding,
                    f'{fail_counter} PCIe devices failed. Continue on Error is set. Continuing the test.', log_padding])
        return True
    else:
        add_to_log(log_file, [log_padding, 'ALL PCIe Devices PASSED!', log_padding])
        return True


# ====================================================================================================
def system_log_check(df_list, log_file, log_path, continue_on_error=False, uuid=None):
    """
    Function that will check certain commands for errors.
    dmesg check, lspci item count, more in the future

    :param df_list: Full data frame items
    :type df_list: data frame
    :param log_file: File that holds the log info
    :type log_file: str
    :param log_path: Path to log folder
    :type log_path: Path
    :param continue_on_error: Tells the script to continue even if issues in the checkers are found.
    :type continue_on_error: bool
    :param uuid: uuid to be used for the database, only insert it if it's not None
    :type uuid: str
    """

    log_padding = '-' * 50
    for df_item in df_list.index:
        time_for_database = get_current_time_for_log()
        if df_list['notes'][df_item] == 'needs_init':
            initial_mode = True
        else:
            initial_mode = False
        if df_list['link_status'][df_item] == 'on':
            if initial_mode:
                add_to_log(log_file, [log_padding, f'Running Full Initial System Check on {df_item}\n'])
            else:
                add_to_log(log_file, [log_padding, f'Running Full System Check on {df_item}\n'])
            os_ip = df_item
            os_user = df_list['OS_USER'][df_item]
            os_pass = df_list['OS_PASS'][df_item]
            os_ip_for_log = os_ip.replace(".", "_")
            ipmi_ip = df_list['IPMI'][df_item]
            ipmi_user = df_list['IPMI_USER'][df_item]
            ipmi_pass = df_list['IPMI_PASS'][df_item]

            # Establish ssh connection
            ssh_connection = Connection(host=os_ip, user=os_user, connect_kwargs={'password': os_pass})

            # ====================================================================================================
            # Get dmesg log and save to file
            add_to_log(log_file, [f'Grabbing dmesg log.\n'])
            run_ssh_command(ssh_connection=ssh_connection, ssh_command=f'echo {os_pass} | sudo -S dmesg',
                            ssh_log=f'{log_path}/{get_current_time_for_log()}-{os_ip_for_log}_dmesg.txt',
                            time_stamp=time_for_database, log_purpose='dmesg', os_ip=os_ip, uuid=uuid,
                            initial_mode=initial_mode)

            # ====================================================================================================
            # PCIe Device Check
            add_to_log(log_file, [f'Checking All PCIe Device Connections\n'])
            pcie_check = pcie_device_check(ssh_connection=ssh_connection, os_pass=os_pass, log_file=log_file,
                                           continue_on_error=continue_on_error)
            if not pcie_check:
                df_list.at[df_item, 'link_status'] = 'error'
                df_list.at[df_item, 'notes'] = 'System failed PCIe check.'
            # ====================================================================================================
            # Check IPMI MAC Change
            if initial_mode:
                ipmi_lan_log_name = f'{log_path}/{os_ip_for_log}_ipmi_lan_old.txt'
            else:
                ipmi_lan_log_name = f'{log_path}/{os_ip_for_log}_ipmi_lan_new.txt'
            ipmi_lan_print = subprocess.run(
                ['ipmitool', 'lan', 'print', '-H', ipmi_ip, '-U', ipmi_user, '-P', ipmi_pass], capture_output=True,
                text=True).stdout
            with open(ipmi_lan_log_name, 'w') as f:
                f.write(ipmi_lan_print)

            # TODO WILL NEED DATABASE CODE CALL
            if uuid:
                insert_to_database(log_content=ipmi_lan_print, os_ip=os_ip, log_date=time_for_database,
                                   log_cmd='ipmi_lan', uuid=uuid, update_db=not initial_mode)
            # Only do the comparisons when you are not in initial mode
            if not initial_mode:
                diff_error = perform_diff_check(original_file=f'{log_path}/{os_ip_for_log}_ipmi_lan_old.txt',
                                                new_file=ipmi_lan_log_name, test_name='ipmi lan print',
                                                continue_on_error=continue_on_error, log_file=log_file)
                if not diff_error:
                    df_list.at[df_item, 'link_status'] = 'error'
                    df_list.at[df_item, 'notes'] = 'System failed ipmi lan check.'

            # ====================================================================================================
            # lspci check
            # When initial mode is set create the original version of the logs for later comparison.
            if initial_mode:
                lspci_log_name = f'{log_path}/{os_ip_for_log}_lspci_old.txt'
            else:
                lspci_log_name = f'{log_path}/{os_ip_for_log}_lspci_new.txt'

            run_ssh_command(ssh_connection=ssh_connection, ssh_command=f'echo {os_pass} | sudo -S lspci',
                            ssh_log=lspci_log_name, time_stamp=time_for_database, log_purpose='lspci', os_ip=os_ip,
                            uuid=uuid, initial_mode=initial_mode)

            # Only do the comparisons when you are not in initial mode
            if not initial_mode:
                diff_error = perform_diff_check(original_file=f'{log_path}/{os_ip_for_log}_lspci_old.txt',
                                                new_file=lspci_log_name, test_name='lspci',
                                                continue_on_error=continue_on_error, log_file=log_file)
                if not diff_error:
                    df_list.at[df_item, 'link_status'] = 'error'
                    df_list.at[df_item, 'notes'] = 'System failed lspci check.'

            # ====================================================================================================
            # Memory check with dmidecode
            # diff the old and log
            # When initial mode is set create the original version of the logs for later comparison.
            if initial_mode:
                dmidecode_log_name = f'{log_path}/{os_ip_for_log}_dmidecode_old.txt'
            else:
                dmidecode_log_name = f'{log_path}/{os_ip_for_log}_dmidecode_new.txt'

            run_ssh_command(ssh_connection=ssh_connection, ssh_command=f'echo {os_pass} | sudo -S dmidecode -t memory',
                            ssh_log=dmidecode_log_name, time_stamp=time_for_database, log_purpose='dmidecode',
                            os_ip=os_ip, uuid=uuid, initial_mode=initial_mode)

            # Only do the comparisons when you are not in initial mode
            if not initial_mode:
                diff_error = perform_diff_check(original_file=f'{log_path}/{os_ip_for_log}_dmidecode_old.txt',
                                                new_file=dmidecode_log_name, test_name='dmidecode MEMORY Check',
                                                continue_on_error=continue_on_error, log_file=log_file)
                if not diff_error:
                    df_list.at[df_item, 'link_status'] = 'error'
                    df_list.at[df_item, 'notes'] = 'System failed dmidecode memory check.'

            ssh_connection.close()

            # ====================================================================================================
            # ipmitool sdr list full check
            # count ok and count number of rows
            if initial_mode:
                ipmi_sdr_log_name = f'{log_path}/{os_ip_for_log}_ipmi_sdr_old.txt'
            else:
                ipmi_sdr_log_name = f'{log_path}/{os_ip_for_log}_ipmi_sdr_new.txt'
            ipmi_sdr_list = subprocess.run(
                ['ipmitool', 'sdr', 'list', 'full', '-H', ipmi_ip, '-U', ipmi_user, '-P', ipmi_pass],
                capture_output=True, text=True).stdout
            with open(ipmi_sdr_log_name, 'w') as f:
                f.write(ipmi_sdr_list)
            # TODO WILL NEED DATABASE CODE CALL
            # TODO Update or new?
            if uuid:
                insert_to_database(log_content=ipmi_sdr_list, os_ip=os_ip, log_date=time_for_database,
                                   log_cmd='ipmi_sdr', uuid=uuid, update_db=not initial_mode)
            # Only do the comparisons when you are not in initial mode
            if not initial_mode:
                with open(f'{log_path}/{os_ip_for_log}_ipmi_sdr_old.txt', 'r') as f:
                    old_ipmi_sdr = f.read()
                with open(ipmi_sdr_log_name, 'r') as f:
                    new_ipmi_sdr = f.read()
                old_ok_count = re.findall(r'\|\s+ok', old_ipmi_sdr)
                new_ok_count = re.findall(r'\|\s+ok', new_ipmi_sdr)
                old_ipmi_sdr = old_ipmi_sdr.splitlines()
                new_ipmi_sdr = new_ipmi_sdr.splitlines()
                if old_ok_count == new_ok_count and len(old_ipmi_sdr) == len(new_ipmi_sdr):
                    ipmi_check = True
                else:
                    ipmi_check = False
                if not ipmi_check and not continue_on_error:
                    add_to_log(log_file,
                               ['ipmi sdr check FAILED!', log_padding])
                    df_list.at[df_item, 'link_status'] = 'error'
                    df_list.at[df_item, 'notes'] = 'System failed ipmi sdr check.'
                elif not ipmi_check:
                    add_to_log(log_file, ['ipmi sdr check FAILED!',
                                          'Continue on Error is enable so we will not stop testing this system.',
                                          log_padding])
                else:
                    add_to_log(log_file, ['ipmi sdr check PASSED!', log_padding])
            df_list['notes'][df_item] = 'finish_init'
        elif df_list['link_status'][df_item] == 'off' and initial_mode:
            add_to_log(log_file,
                       [f'System {df_item} was originally off. Will not get full log check during first loop.'])


# ====================================================================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--description', '-d', action='store_true', help='Enables a custom help function.')
    parser.add_argument('--version', '-v', action='store_true', help='Print out version information.')
    parser.add_argument('--input', '-i', type=str, help='Input file that contains the information about the system(s) '
                                                        'to test. If not specified it will ask you to enter.',
                        default=None)
    parser.add_argument('--loop', '-l', type=int, help='Enter the number of loops you want to cycle.', default=1)
    parser.add_argument('--boot', '-b', type=int, help='Enter how long to wait for the system(s) to boot before failing'
                                                       ' in minutes.', default=20)
    parser.add_argument('--continue_on_error', '-c', action='store_true', help='Enable this parameter if you want the '
                                                                               'system to continue no matter if any '
                                                                               'errors are found by any of the checks.')
    parser.add_argument('--shutdown', '-s', type=int, help='Enter how long you want to wait for the system(s) to '
                                                           'shutdown before failing in minutes.', default=10)
    parser.add_argument('--hard', action='store_true',
                        help='Enable this if you wish to do a hard shutdown as opposed to the default soft shutdown.')
    parser.add_argument('--output', '-o', type=str, help='Enter a specific string to use for the log name if you wish '
                                                         'to not use the timestamped default.', default=None)
    parser.add_argument('--uuid', '-u', type=str, help='Enter this value to store a unique ID to store the logs to a'
                                                       ' database using L12CM.', default=None)

    args = parser.parse_args()
    description_message = args.description
    version = args.version
    input_file = args.input
    global num_loops
    num_loops = args.loop
    boot_up_time = args.boot * 60
    continue_on_error = args.continue_on_error
    shutdown_time = args.shutdown * 60
    hard_mode = args.hard
    preferred_output = args.output
    uuid_for_database = args.uuid

    help_message = parser.format_help()

    # TODO
    #  Do a drive check

    # Will print version information and exit
    if version:
        for version_line in version_info:
            print(version_line)
        sys.exit()

    log_padding = '=' * 100
    log_padding_small = '-' * 50
    # Setup Initial Log Information
    if preferred_output:
        test_log = preferred_output
    else:
        test_log = f'{get_current_time_for_log()}_power_cycle_log.txt'

    # Make a log folder
    starting_directory = pathlib.Path.cwd().absolute()
    log_path = pathlib.Path().joinpath(starting_directory, 'power_test')
    pathlib.Path(log_path).mkdir(parents=True, exist_ok=True)
    test_log = f'{log_path}/{test_log}'

    with open(test_log, 'w') as the_log_file:
        the_log_file.write('=' * 100 + '\n')
        the_log_file.write('Log file for Power Cycle Test\n')
        the_log_file.write('=' * 100 + '\n')
        for version_line in version_info:
            the_log_file.write(f'{version_line}\n')

    if description_message:
        with open(test_log, 'a') as the_log_file:
            the_log_file.write(help_message)
        sys.exit()

    if not input_file:
        print('ERROR Must enter input file!')
        sys.exit()

    add_to_log(test_log, ['Starting the power cycle test.', f'Will run {num_loops} times per system.'])

    input_file = os.path.abspath(input_file)
    df_all = pd.read_csv(input_file, names=['IPMI', 'IPMI_PASS', 'IP', 'OS_USER', 'OS_PASS'], index_col='IP')
    df_all['IPMI_USER'] = 'ADMIN'
    df_all['link_status'] = 'unknown'
    df_all['notes'] = 'needs_init'
    df_all[['octet_1', 'octet_2', 'octet_3', 'octet_4']] = df_all.index.to_series().apply(
        lambda x: pd.Series(x.split('.')))
    df_all[['octet_1', 'octet_2', 'octet_3', 'octet_4']] = df_all[['octet_1', 'octet_2', 'octet_3', 'octet_4']].astype(
        int)
    df_all.sort_values(by=['octet_1', 'octet_2', 'octet_3', 'octet_4'], inplace=True)
    df_all.drop(columns=['octet_1', 'octet_2', 'octet_3', 'octet_4'], inplace=True)
    system_summary_log(df_list=df_all, log_file=test_log, message='Current Status of systems before starting the test.')
    # ====================================================================================================
    # Running initial check to make sure IPMI is ok and current state of the system
    # If the system is on get the logs
    add_to_log(test_log, [log_padding, log_padding_small, 'Running initial health check on all systems.',
                          log_padding_small, 'Running IPMI Ping Check.\n'])
    ipmi_ping_check(df_list=df_all, log_file=test_log)
    add_to_log(test_log, [log_padding_small, 'Running Initial IPMI State Check\n'])
    ipmi_power_command(df_list=df_all, log_file=test_log, state='status', loop_count='initial check')
    system_log_check(df_list=df_all, log_file=test_log, log_path=log_path, continue_on_error=continue_on_error,
                     uuid=uuid_for_database)
    num_systems = len(df_all)
    num_bad_systems = 0
    for df_item in df_all.index:
        if df_all['link_status'][df_item] == 'error':
            num_bad_systems += 1
    if num_systems == num_bad_systems:
        system_summary_log(df_list=df_all, log_file=test_log,
                           message='All the systems are in a bad state. Ending the test.')
        add_to_log(test_log, [log_padding, f'End of the test.', log_padding])
        sys.exit()
    # ====================================================================================================

    system_summary_log(df_list=df_all, log_file=test_log, message='Current Status of systems before starting the test.')

    # Run for desired loops and through each specified system, turn off the system, check status, turn on system
    # check status again and then run log check
    for loop in range(1, num_loops + 1):
        add_to_log(test_log, [log_padding, f'Running loop {loop} of {num_loops}.'])

        # Stage one turn on all servers that are not set as link_status = on
        ipmi_power_command(df_list=df_all, log_file=test_log, state='off', loop_count=loop, hard_mode=hard_mode)

        # Stage 2 wait for all servers to turn off and after timeout if any servers are still changing fail them
        wait_for_state_change(df_list=df_all, log_file=test_log, timeout=shutdown_time, mode='off', loop_count=loop)

        # Stage 3 all servers in off state turn on
        add_to_log(test_log, ['Waiting 30 seconds before turning the systems back on...'])
        time.sleep(30)
        ipmi_power_command(df_list=df_all, log_file=test_log, state='on', loop_count=loop)
        add_to_log(test_log, ['Waiting 30 seconds for the systems to start turning on...'])
        time.sleep(30)

        # Stage 4 wait for all servers to turn on
        wait_for_state_change(df_list=df_all, log_file=test_log, timeout=boot_up_time, mode='on', loop_count=loop)

        # Stage 5 run log check
        system_log_check(df_list=df_all, log_file=test_log, log_path=log_path, continue_on_error=continue_on_error,
                         uuid=uuid_for_database)
        num_bad_systems = 0
        for df_item in df_all.index:
            if df_all['link_status'][df_item] == 'error':
                num_bad_systems += 1
        if num_systems == num_bad_systems:
            add_to_log(test_log, ['All the systems are in a bad state. Ending the test.'])
            break
        system_summary_log(df_list=df_all, log_file=test_log, message=f'System status at the end of {loop} loop(s).')

    for df_item in df_all.index:
        if df_all['link_status'][df_item] == 'on':
            df_all['notes'][df_item] = 'PASSED'

    system_summary_log(df_list=df_all, log_file=test_log, message='Final System Status')
    add_to_log(test_log, [log_padding, f'End of the test.'])
    print('=' * 100)

    # If in L12CM Mode Move out the summary log and delete the log folder.
    if uuid_for_database:
        with open(test_log, 'r') as f:
            full_log = f.read()
        insert_to_database(log_content=full_log, os_ip=f'Num-Nodes-{len(df_all)}', log_date=get_current_time_for_log(),
                           log_cmd='power_cycle_log', uuid=uuid_for_database, update_db=True)


# ====================================================================================================
if __name__ == '__main__':
    main()
