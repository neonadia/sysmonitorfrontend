import requests
import sys
import os
import time
import datetime

link_lists =['','/chart_allpowercontrols','/checkipmisensor']

health_log = os.environ['UPLOADPATH'] + os.environ['RACKNAME'] + '-health.log'

start_time = time.time()
for link in link_lists:
    try:
        cur_request = requests.get(sys.argv[1] + link)
        if cur_request.status_code != 200:
            print('Error code: ' + str(cur_request.status_code), flush=True)
            cur_time = datetime.datetime.now().strftime("%m/%d/%Y %H:%M:%S")
            output = "--- %s | Health check faild: took %s seconds ---\n" % (cur_time, time.time() - start_time)
            with open(health_log, "a") as myfile:
                myfile.write(output)
                myfile.write('Error code: ' + str(cur_request.status_code) + '\n')
            sys.exit(1)
        else:
            print(sys.argv[1] + link + 'Response OK', flush=True)
    except Exception as e:
        print('Error message: ' + str(e), flush=True)
        cur_time = datetime.datetime.now().strftime("%m/%d/%Y %H:%M:%S")
        output = "--- %s | Health check faild: took %s seconds ---\n" % (cur_time, time.time() - start_time)
        with open(health_log, "a") as myfile:
            myfile.write(output)
            myfile.write('Error message: ' + str(e) + '\n')
        sys.exit(1)
# if all links work, then it is healthy
cur_time = datetime.datetime.now().strftime("%m/%d/%Y %H:%M:%S")
output = "--- %s | Health check passed all requests: took %s seconds ---\n" % (cur_time, time.time() - start_time)
print(output, flush=True)
with open(health_log, "a") as myfile:
    myfile.write(output)
sys.exit(0)