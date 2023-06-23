FROM python:3.8
MAINTAINER Chenyang Li
COPY MongoFlask/ /app
WORKDIR /app/
RUN apt-get update
# Install a static version for ipmitool
RUN apt-get install -y ./ipmitool_debs/libssl1.1_1.1.1n-0+deb10u5_amd64.deb
RUN apt-get install -y ./ipmitool_debs/libreadline7_7.0-5_amd64.deb
RUN apt-get install -y ./ipmitool_debs/ipmitool_1.8.18-6+deb10u1_amd64.deb
RUN apt-get install -y python3-distutils
RUN apt-get install -y ffmpeg libsm6 libxext6
RUN apt-get install -y sshpass iputils-ping
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
ENV PATH="/root/.local/bin:${PATH}"
CMD python app.py
