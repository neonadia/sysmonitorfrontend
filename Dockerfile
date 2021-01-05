FROM python:3.8
MAINTAINER Chenyang Li
COPY MongoFlask/ /app
WORKDIR /app/
RUN apt-get update
RUN apt-get install -y ipmitool
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
CMD python app.py
