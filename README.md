# Introduction 2020/04/15

Linux Cluster Monitor (LCM) is an easy deploy program built upon Redfish and Intelligent Platform Management Interface (IPMI) aims to monitor the system status on super sever remotely. It includes multiple functions: real-time device status monitor, cluster hardware software summary, benchmark results reader and system report generation. \
LCM consists of three parts: back-end, front-end and data repository.  The back-end is responsible for query system information and sensor readings and insert them into data repository. Currently, the data repository we use is mongoDB.  While the front-end is responsible for initialize a webpage service, which can display the system information and sensor readings in real-time. The flask module has been applied for the web-interface. Additionally, to use LCM, the target cluster need to have Redfish installed.

## Getting Started

Before running image, you need to pull the following images:
1. Back end of system monitor:\
https://hub.docker.com/repository/docker/neonadia/sysmonitorbackend\
2. Front end of system monitor:\
https://hub.docker.com/repository/docker/neonadia/sysmonitorfrontend\
3. MongoDB:\
https://hub.docker.com/_/mongo


### Preparation before boot up

To use LCM, Docker is necessary, you can follow one of the instructions below to finish the installation: \
https://docs.docker.com/engine/install/ \
Docker-compose is recommended, since it will save you lots of time to start the service: \
https://docs.docker.com/compose/install/ \
After finishing the installation above, there are two ways to start the service:
1.	Using docker
2.	Using docker-compose 

### Boot up using Docker-Compose

1.	Login as root user or add current user into docker group
2.	Make sure docker-compose has been installed already
3.	Create a folder named “inputfiles” inside ~/  , create a txt file named “iplist.txt” with the following content inside “inputfiles” folder.
4.	Copy “docker-compose.yml” into home dir
5.	Under same directory, run:
```
$ docker-compose run -d
```

### Boot up using Docker

1. Login as root user
2. Start the MongoDB container:
```
$ docker run -d -p 27017-27019:27017-27019 --name mongodb mongo
```
For better storage control, mount a volume to mongodb
```
$ docker run -d -p 27017-27019:27017-27019 --name mongodb -v /home/<user>/data:/data/db mongo
```
3. Create a folder named “inputfiles” inside ~/  , create a txt file named “iplist.txt” with the following content inside “inputfiles” folder: 
```
172.27.28.51
172.27.28.52
172.27.28.53
172.27.28.54
172.27.28.55
172.27.28.56
172.27.28.57
172.27.28.58
```

4. Start the back-end container:
```
$ docker run -d -v ~/inputfiles:/app/inputfiles --network host neonadia/sysmonitorbackend
```
6. Check whether the data has been written in by:
```
$ docker exec -it mongodb bash
# mongo
MongoDB shell version v4.2.3
> show dbs
admin    0.000GB
config   0.000GB
local    0.000GB
redfish  0.004GB
> use redfish
switched to db redfish
> show tables
monitor
servers
```
7. Once the data has been written in, start the front-end webpage container:
```
$ docker run -d --network host neonadia/sysmonitorfrontend
```
8. Now the website is online, you can visit 172.27.28.XX:5000
9. Save the log information by running:
```
$ docker logs $(container id) >~/logfile 2>~/error.log
```

## How to build it

### Docker image for back-end database

To build an image to query and upload the system data into MongoDB, following the steps as below:

1. “redfish_v3.py” and “redfish_monitor.py” are responsible for query and upload the data, some adjustments must be made before building the image:
* IP address must be read from outside
* Password must be read from Microsoft Database
* The code is IPMI/Redfish version sensitive
* The address of MongoDB container must be correctly specified
2. Create a “requirements.txt” with following environmental settings:
```	
datetime==4.3
pymongo==3.10.1
redfish==2.1.5
```
Or run:
```
$ pip3 freeze > requirements.txt
```
3. Create a folder named “mongodbDocker_addcombination”, and create “Dockerfile” with the following content: (Delete “-u” will cause the latency of log information.)
```
FROM python:alpine
MAINTAINER Chenyang Li
COPY createDBandInsertData /app
WORKDIR /app/
RUN apk add ipmitool                                              
RUN pip install -r requirements.txt
CMD python -u redfish_sys_docker_v1.py ; python -u redfish_monitor_docker_v1.py
```
4.	Create a folder named “createDBandInsertData” and move “redfish_v3.py” and “redfish_monitor.py” inside it, modify their names according to the “Dockerfile”.
5.	Move the “requirements.txt” inside “createDBandInsertData”.
6.	Inside “mongodbDocker_addcombination” folder, run:
```
$ sudo docker build -t $(please specify the image name here) .
```
7.	To check the images, run:
```
$ sudo docker images
```

**Warning**: Currently the image is still sensitive to the version of IPMI/Redfish of the target system. The current image is compatible with the nodes: http://172.27.28.51/ to http://172.27.28.58/

### Docker image for front-end webpage

1. Modify the "app.py", change the following line:
```
client = MongoClient('localhost', 27017)
```
into
```
client = MongoClient('172.27.28.16', 27017)
``` 

2. Create the "DOCKERFILE" in the same directory as "MongoFlask" with the following content:
```
FROM python:alpine
MAINTAINER Chenyang Li
COPY MongoFlask/ /app
WORKDIR /app/
RUN ls -alt
RUN pip install -r requirements.txt
EXPOSE 5000
CMD [ "python", "app.py" ]
```
3. Create the "requirements.txt" in the same directory as DOCKERFILE with the following content:
```
flask==1.1.1
redfish==2.1.5
pymongo==3.10.1
json2html==1.3.0
```
or run
```
$ pip3 freeze >> requirements.txt
```
4. Create the "README.md" with any readme information you want to write and put it inside the same directory as "DOCKERFILE".
5. In the same directory as "DOCKERFILE" run:
```
$ sudo docker build -t $(nameofthisimage) .
```
6. Push it into public repository:
```
$ sudo docker push $(nameofthisimage)
```
7. Link it with github repository if you want.

### Docker-compose file:

To use docker-compose, you can create a file named "docker-compose.yml" with the following content:
```
version: "2.4"
services:
  mongodb:
    image: mongo
    ports:
      - 27017-27019:27017-27019
  frontend:
    image: neonadia/sysmonitorfrontend
    network_mode: host
    depends_on:
      - mongodb
      - backend
  backend:
    image: neonadia/sysmonitorbackend
    network_mode: host
    depends_on:
      - mongodb
    volumes:
      - ~/inputfiles:/app/inputfiles
```

## Possible concerns

1. **Why not use “cart1-mapping.csv” as the input file?**\
Because currently, the query module can only be fully compatible the redfish version of those VPN nodes. If we want to use the “cart1-mapping.csv” as the input file, we need to modify the code to make it compatible with the redfish version of the nodes listing in the “cart1-mapping.csv”.

2. **How about the module reading the password from MSSQL database?**\
It has been integrated in another version of query module, currently it has been disabled in the docker image because those nodes do not exist in the MSSQL database and, we cannot access MSSQL inside those nodes.

3. **What is the next step?**\
Currently, the docker image is fully compatible with our testing nodes, or any other nodes having the same version of IPMI and redfish. The next step is to figure out a way to make the query module compatible with those machines having different versions of IPMI and redfish: such as forced it to update the IPMI and redfish version.