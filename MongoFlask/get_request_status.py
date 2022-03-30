import requests
import sys

link_lists =['','/chart_allpowercontrols','/min_max_allpower_chart?var=1']

for link in link_lists:
    try:
        cur_request = requests.get(sys.argv[1] + link)
        if cur_request.status_code != 200:
            print('Error code: ' + str(cur_request.status_code))
            sys.exit(1)
        else:
            print(sys.argv[1] + link + 'Response OK')
    except Exception as e:
        print('Error message: ' + str(e))
        sys.exit(1)
# if all links work, then it is healthy
sys.exit(0)