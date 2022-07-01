FROM python:3.8
MAINTAINER Chenyang Li
COPY MongoFlask/ /app
WORKDIR /app/
RUN apt-get update
RUN apt-get install -y ipmitool
RUN apt-get install -y python3-distutils
RUN apt-get install -y ffmpeg libsm6 libxext6
RUN apt-get install -y ansible sshpass
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
CMD python app.py
